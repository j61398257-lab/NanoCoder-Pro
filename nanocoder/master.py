"""Master-SubAgent loop - goal-driven autonomous execution.

The Master sets a goal and criteria, then drives a SubAgent in a loop:
  1. SubAgent works on the task (has full tool access)
  2. Master checks each criterion (LLM judgment + optional bash commands)
  3. If any criterion is unmet, Master pushes SubAgent to continue
  4. Loop until all criteria are satisfied or max iterations reached

The SubAgent keeps its context across iterations (same Agent instance),
so it accumulates knowledge and doesn't repeat itself.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from .agent import Agent
from .tools import ALL_TOOLS
from .tools.base import Tool

if TYPE_CHECKING:
    from .llm import LLM


CRITERIA_CHECK_PROMPT = """\
You are a strict criteria evaluator. Given a goal, a list of criteria, and the \
agent's latest work output, judge whether EACH criterion is met.

You MUST respond with a JSON array (no markdown fencing, no extra text). Each \
element has exactly these fields:
  {"index": <int>, "met": <bool>, "reason": "<one-line explanation>"}

Be strict: a criterion is "met" only if the evidence clearly proves it. \
If uncertain, mark it as NOT met.
"""


@dataclass
class CriteriaItem:
    """One criterion the goal must satisfy."""
    description: str
    check_cmd: str | None = None
    met: bool = False
    reason: str = ""


@dataclass
class GoalResult:
    """Outcome of a MasterLoop run."""
    goal: str
    met: bool
    iterations: int
    criteria: list[CriteriaItem]
    final_output: str

    def summary(self) -> str:
        status = "GOAL MET" if self.met else "GOAL NOT MET"
        lines = [f"[{status}] {self.goal}  ({self.iterations} iterations)"]
        for i, c in enumerate(self.criteria):
            mark = "[x]" if c.met else "[ ]"
            lines.append(f"  {mark} {i+1}. {c.description}")
            if c.reason:
                lines.append(f"       -> {c.reason}")
        return "\n".join(lines)


class MasterLoop:
    """Goal-driven loop: Master supervises SubAgent until criteria are met."""

    def __init__(
        self,
        llm: LLM,
        tools: list[Tool] | None = None,
        max_iterations: int = 10,
        max_sub_rounds: int = 40,
    ):
        self.llm = llm
        self.tools = tools if tools is not None else list(ALL_TOOLS)
        self.max_iterations = max_iterations
        self.max_sub_rounds = max_sub_rounds

    def run(
        self,
        goal: str,
        criteria: list[str],
        check_cmds: list[str | None] | None = None,
        on_iteration: Callable[[int, list[CriteriaItem]], None] | None = None,
        on_tool: Callable | None = None,
        on_token: Callable | None = None,
    ) -> GoalResult:
        """Drive SubAgent until all criteria are satisfied."""

        # build criteria items
        cmds = check_cmds or [None] * len(criteria)
        items = [
            CriteriaItem(description=desc, check_cmd=cmd)
            for desc, cmd in zip(criteria, cmds)
        ]

        # single SubAgent instance - keeps context across iterations
        sub = Agent(
            llm=self.llm,
            tools=self.tools,
            max_context_tokens=self.llm.extra.get("max_context_tokens", 128_000)
                if hasattr(self.llm, "extra") else 128_000,
            max_rounds=self.max_sub_rounds,
        )

        task_prompt = self._build_initial_prompt(goal, criteria)
        last_result = ""

        for iteration in range(1, self.max_iterations + 1):
            # --- Phase 1: SubAgent works ---
            last_result = sub.chat(
                task_prompt,
                on_token=on_token,
                on_tool=on_tool,
            )

            # --- Phase 2: Master checks criteria ---
            self._run_cmd_checks(items)
            self._llm_check(goal, items, last_result)

            if on_iteration:
                on_iteration(iteration, items)

            # --- Phase 3: All met? ---
            if all(c.met for c in items):
                return GoalResult(
                    goal=goal, met=True, iterations=iteration,
                    criteria=items, final_output=last_result,
                )

            # --- Phase 4: Not done -> push SubAgent to continue ---
            task_prompt = self._build_continue_prompt(items)

        # exhausted iterations
        return GoalResult(
            goal=goal, met=False, iterations=self.max_iterations,
            criteria=items, final_output=last_result,
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_initial_prompt(goal: str, criteria: list[str]) -> str:
        criteria_text = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(criteria))
        return (
            f"GOAL: {goal}\n\n"
            f"You must satisfy ALL of these criteria:\n{criteria_text}\n\n"
            f"Work step by step. Use tools to write code, run commands, and "
            f"verify your work. Do NOT stop until every criterion above is met."
        )

    @staticmethod
    def _build_continue_prompt(items: list[CriteriaItem]) -> str:
        unmet = [c for c in items if not c.met]
        lines = ["The following criteria are NOT YET MET. Continue working:\n"]
        for c in unmet:
            reason_part = f" (issue: {c.reason})" if c.reason else ""
            lines.append(f"  - {c.description}{reason_part}")
        lines.append(
            "\nFix the issues above using tools (edit_file, bash, write_file, etc). "
            "Do NOT just describe what to do - actually DO it with tool calls. "
            "Do NOT stop until everything works."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Criteria checking
    # ------------------------------------------------------------------

    def _run_cmd_checks(self, items: list[CriteriaItem]) -> None:
        """Run bash verification commands for criteria that have them."""
        for c in items:
            if not c.check_cmd:
                continue
            try:
                proc = subprocess.run(
                    c.check_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if proc.returncode == 0:
                    c.met = True
                    c.reason = "check command passed"
                else:
                    c.met = False
                    stderr = proc.stderr.strip()[:200]
                    stdout = proc.stdout.strip()[:200]
                    c.reason = stderr or stdout or f"exit code {proc.returncode}"
            except subprocess.TimeoutExpired:
                c.met = False
                c.reason = "check command timed out"
            except Exception as e:
                c.met = False
                c.reason = f"check error: {e}"

    def _llm_check(self, goal: str, items: list[CriteriaItem], sub_result: str) -> None:
        """Use the LLM to judge criteria that have no check_cmd or whose cmd failed."""
        need_judge = [
            (i, c) for i, c in enumerate(items)
            if not c.met and not c.check_cmd
        ]
        if not need_judge:
            return

        criteria_list = "\n".join(
            f"  {i+1}. {c.description}" for i, c in need_judge
        )
        user_msg = (
            f"Goal: {goal}\n\n"
            f"Criteria to evaluate:\n{criteria_list}\n\n"
            f"Agent's latest output (last 3000 chars):\n"
            f"{sub_result[-3000:]}"
        )

        try:
            resp = self.llm.chat(
                messages=[
                    {"role": "system", "content": CRITERIA_CHECK_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            verdicts = self._parse_verdicts(resp.content)
            for v in verdicts:
                idx = v.get("index")
                if idx is None:
                    continue
                for orig_i, c in need_judge:
                    if orig_i + 1 == idx:
                        c.met = bool(v.get("met", False))
                        c.reason = v.get("reason", "")
                        break
        except Exception:
            pass  # LLM check failure is non-fatal; cmd checks are authoritative

    @staticmethod
    def _parse_verdicts(text: str) -> list[dict]:
        """Extract JSON array from LLM response, tolerating markdown fencing."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            )
        try:
            result = json.loads(text)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        # fallback: try to find JSON array in the text
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return []
