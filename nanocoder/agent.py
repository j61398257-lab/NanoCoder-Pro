"""Core agent loop.

This is the heart of NanoCoder.  The pattern is simple:

    user message -> LLM (with tools) -> tool calls? -> execute -> loop
                                      -> text reply? -> return to user

It keeps looping until the LLM responds with plain text (no tool calls),
which means it's done working and ready to report back.
"""

import concurrent.futures
from .llm import LLM
from .tools import ALL_TOOLS, get_tool
from .tools.base import Tool
from .tools.agent import AgentTool
from .prompt import system_prompt
from .context import ContextManager
from .memory import Memory
from .planner import Planner, Plan
from .eval import Evaluator, EvalResult


class Agent:
    def __init__(
        self,
        llm: LLM,
        tools: list[Tool] | None = None,
        max_context_tokens: int = 128_000,
        max_rounds: int = 50,
        memory: Memory | None = None,
    ):
        self.llm = llm
        self.tools = tools if tools is not None else ALL_TOOLS
        self.messages: list[dict] = []
        self.context = ContextManager(max_tokens=max_context_tokens)
        self.max_rounds = max_rounds
        self.memory = memory or Memory()
        self.planner = Planner(llm)
        self.evaluator = Evaluator(llm=llm, max_fix_attempts=2)
        self.active_plan: Plan | None = None
        self.auto_eval: bool = False
        self._system = system_prompt(self.tools)

        # wire up sub-agent capability
        for t in self.tools:
            if isinstance(t, AgentTool):
                t._parent_agent = self

    def _full_messages(self) -> list[dict]:
        return [{"role": "system", "content": self._system}] + self.messages

    def _tool_schemas(self) -> list[dict]:
        return [t.schema() for t in self.tools]

    def chat(self, user_input: str, on_token=None, on_tool=None) -> str:
        """Process one user message. May involve multiple LLM/tool rounds."""
        self.messages.append({"role": "user", "content": user_input})

        # recall relevant long-term memories and inject into context
        recalled = self.memory.recall(user_input, top_k=3)
        memory_block = self.memory.format_for_prompt(recalled)
        if memory_block:
            self.messages.insert(-1, {
                "role": "system",
                "content": memory_block,
            })

        self.context.maybe_compress(self.messages, self.llm)

        for _ in range(self.max_rounds):
            resp = self.llm.chat(
                messages=self._full_messages(),
                tools=self._tool_schemas(),
                on_token=on_token,
            )

            # no tool calls -> LLM is done
            if not resp.tool_calls:
                self.messages.append(resp.message)

                if self.auto_eval:
                    eval_result = self._run_eval()
                    if eval_result and not eval_result.passed:
                        fix_prompt = (
                            f"Eval found issues:\n{eval_result.summary()}\n\n"
                            f"Please fix these errors."
                        )
                        return self.chat(fix_prompt, on_token=on_token, on_tool=on_tool)

                return resp.content

            # tool calls -> execute (parallel when multiple, like Claude Code's
            # StreamingToolExecutor which runs independent tools concurrently)
            self.messages.append(resp.message)

            if len(resp.tool_calls) == 1:
                tc = resp.tool_calls[0]
                if on_tool:
                    on_tool(tc.name, tc.arguments)
                result = self._exec_tool(tc)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            else:
                # parallel execution for multiple tool calls
                results = self._exec_tools_parallel(resp.tool_calls, on_tool)
                for tc, result in zip(resp.tool_calls, results):
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

            # compress if tool outputs are big
            self.context.maybe_compress(self.messages, self.llm)

        return "(reached maximum tool-call rounds)"

    def _exec_tool(self, tc) -> str:
        """Execute a single tool call, returning the result string."""
        tool = get_tool(tc.name)
        if tool is None:
            return f"Error: unknown tool '{tc.name}'"
        try:
            return tool.execute(**tc.arguments)
        except TypeError as e:
            return f"Error: bad arguments for {tc.name}: {e}"
        except Exception as e:
            return f"Error executing {tc.name}: {e}"

    def _exec_tools_parallel(self, tool_calls, on_tool=None) -> list[str]:
        """Run multiple tool calls concurrently using threads.

        This is inspired by Claude Code's StreamingToolExecutor which starts
        executing tools while the model is still generating.  We simplify to:
        when the model returns N tool calls at once, run them in parallel.
        """
        for tc in tool_calls:
            if on_tool:
                on_tool(tc.name, tc.arguments)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self._exec_tool, tc) for tc in tool_calls]
            return [f.result() for f in futures]

    def _run_eval(self) -> EvalResult | None:
        """Run eval checks on files modified in the conversation."""
        modified = Evaluator.extract_modified_files(self.messages)
        if not modified:
            return None
        return self.evaluator.evaluate(modified)

    def chat_with_plan(self, user_input: str, on_token=None, on_tool=None,
                        on_plan=None) -> str:
        """Plan Mode: generate a plan first, then execute step by step."""
        self.active_plan = self.planner.create_plan(user_input)
        if on_plan:
            on_plan(self.active_plan)

        results: list[str] = []
        while not self.active_plan.is_complete:
            step = self.active_plan.current_step
            if step is None:
                break
            step.status = "in_progress"
            if on_plan:
                on_plan(self.active_plan)

            step_prompt = (
                f"Execute this step of the plan:\n"
                f"Step {step.index}: {step.description}\n\n"
                f"Full plan context: {self.active_plan.goal}"
            )
            result = self.chat(step_prompt, on_token=on_token, on_tool=on_tool)
            results.append(f"Step {step.index}: {result}")
            self.active_plan.advance()
            if on_plan:
                on_plan(self.active_plan)

        self.active_plan = None
        return "\n\n".join(results)

    def save_memories(self):
        """Extract and persist key facts from the current conversation."""
        facts = Memory.extract_from_conversation(self.messages)
        for fact in facts:
            self.memory.remember(fact, scope="global", importance=0.8)

    def reset(self):
        """Clear conversation history (auto-saves memories first)."""
        self.save_memories()
        self.messages.clear()
