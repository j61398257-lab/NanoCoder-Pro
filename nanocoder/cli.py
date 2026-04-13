"""Interactive REPL - the user-facing terminal interface."""

import sys
import os
import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.history import FileHistory

from .agent import Agent
from .llm import LLM
from .config import Config
from .gateway import Gateway, ModelProfile
from .master import MasterLoop
from .session import save_session, load_session, list_sessions
from . import __version__

console = Console()


def _parse_args():
    p = argparse.ArgumentParser(
        prog="nanocoder",
        description="Minimal AI coding agent. Works with any OpenAI-compatible LLM.",
    )
    p.add_argument("-m", "--model", help="Model name (default: $NANOCODER_MODEL or gpt-4o)")
    p.add_argument("--base-url", help="API base URL (default: $OPENAI_BASE_URL)")
    p.add_argument("--api-key", help="API key (default: $OPENAI_API_KEY)")
    p.add_argument("-p", "--prompt", help="One-shot prompt (non-interactive mode)")
    p.add_argument("-r", "--resume", metavar="ID", help="Resume a saved session")
    p.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args()


def main():
    args = _parse_args()
    config = Config.from_env()

    # CLI args override env vars
    if args.model:
        config.model = args.model
    if args.base_url:
        config.base_url = args.base_url
    if args.api_key:
        config.api_key = args.api_key

    if not config.api_key:
        console.print("[red bold]No API key found.[/]")
        console.print(
            "Set one of: OPENAI_API_KEY, DEEPSEEK_API_KEY, or NANOCODER_API_KEY\n"
            "\nExamples:\n"
            "  # OpenAI\n"
            "  export OPENAI_API_KEY=sk-...\n"
            "\n"
            "  # DeepSeek\n"
            "  export OPENAI_API_KEY=sk-... OPENAI_BASE_URL=https://api.deepseek.com\n"
            "\n"
            "  # Ollama (local)\n"
            "  export OPENAI_API_KEY=ollama OPENAI_BASE_URL=http://localhost:11434/v1 NANOCODER_MODEL=qwen2.5-coder\n"
        )
        sys.exit(1)

    llm = LLM(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    gateway = None
    if config.gateway_models:
        gateway = Gateway()
        for gm in config.gateway_models:
            gateway.add_profile(ModelProfile(
                name=gm.name,
                api_key=gm.api_key,
                base_url=gm.base_url,
                tier=gm.tier,
                max_tokens=gm.max_tokens,
                temperature=gm.temperature,
            ))

    agent = Agent(llm=llm, max_context_tokens=config.max_context_tokens)

    # resume saved session
    if args.resume:
        loaded = load_session(args.resume)
        if loaded:
            agent.messages, loaded_model = loaded
            console.print(f"[green]Resumed session: {args.resume}[/green]")
        else:
            console.print(f"[red]Session '{args.resume}' not found.[/red]")
            sys.exit(1)

    # one-shot mode
    if args.prompt:
        _run_once(agent, args.prompt)
        return

    # interactive REPL
    _repl(agent, config, gateway)


def _run_once(agent: Agent, prompt: str):
    """Non-interactive: run one prompt and exit."""
    def on_token(tok):
        print(tok, end="", flush=True)

    def on_tool(name, kwargs):
        console.print(f"\n[dim]> {name}({_brief(kwargs)})[/dim]")

    agent.chat(prompt, on_token=on_token, on_tool=on_tool)
    print()


def _repl(agent: Agent, config: Config, gateway: Gateway | None = None):
    """Interactive read-eval-print loop."""
    console.print(Panel(
        f"[bold]NanoCoder[/bold] v{__version__}\n"
        f"Model: [cyan]{config.model}[/cyan]"
        + (f"  Base: [dim]{config.base_url}[/dim]" if config.base_url else "")
        + "\nType [bold]/help[/bold] for commands, [bold]Ctrl+C[/bold] to cancel, [bold]quit[/bold] to exit.",
        border_style="blue",
    ))

    hist_path = os.path.expanduser("~/.nanocoder_history")
    history = FileHistory(hist_path)

    while True:
        try:
            user_input = pt_prompt("You > ", history=history).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye!")
            break

        if not user_input:
            continue

        # built-in commands
        if user_input.lower() in ("quit", "exit", "/quit", "/exit"):
            break
        if user_input == "/help":
            _show_help()
            continue
        if user_input == "/reset":
            agent.reset()
            console.print("[yellow]Conversation reset.[/yellow]")
            continue
        if user_input == "/tokens":
            p = agent.llm.total_prompt_tokens
            c = agent.llm.total_completion_tokens
            console.print(f"Tokens used this session: [cyan]{p}[/cyan] prompt + [cyan]{c}[/cyan] completion = [bold]{p+c}[/bold] total")
            continue
        if user_input.startswith("/model "):
            new_model = user_input[7:].strip()
            if new_model:
                agent.llm.model = new_model
                config.model = new_model
                console.print(f"Switched to [cyan]{new_model}[/cyan]")
            continue
        if user_input == "/compact":
            from .context import estimate_tokens
            before = estimate_tokens(agent.messages)
            compressed = agent.context.maybe_compress(agent.messages, agent.llm)
            after = estimate_tokens(agent.messages)
            if compressed:
                console.print(f"[green]Compressed: {before} éˆ?? {after} tokens ({len(agent.messages)} messages)[/green]")
            else:
                console.print(f"[dim]Nothing to compress ({before} tokens, {len(agent.messages)} messages)[/dim]")
            continue
        if user_input == "/plan":
            console.print("[cyan]Plan Mode ON â€? next message will trigger plan-then-execute.[/cyan]")
            try:
                plan_input = pt_prompt("Plan > ", history=history).strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not plan_input:
                continue

            streamed: list[str] = []

            def on_token_plan(tok):
                streamed.append(tok)
                print(tok, end="", flush=True)

            def on_tool_plan(name, kwargs):
                console.print(f"\n[dim]> {name}({_brief(kwargs)})[/dim]")

            def on_plan(plan):
                console.print(f"\n[yellow]{plan.format()}[/yellow]\n")

            try:
                response = agent.chat_with_plan(
                    plan_input,
                    on_token=on_token_plan,
                    on_tool=on_tool_plan,
                    on_plan=on_plan,
                )
                if streamed:
                    print()
                else:
                    console.print(Markdown(response))
            except KeyboardInterrupt:
                console.print("\n[yellow]Plan interrupted.[/yellow]")
            except Exception as e:
                console.print(f"\n[red]Error: {e}[/red]")
            continue
        if user_input == "/memory":
            entries = agent.memory.list_all()
            if not entries:
                console.print("[dim]No memories stored.[/dim]")
            else:
                for e in entries[-10:]:
                    console.print(f"  [cyan]{e.id}[/cyan] {e.text[:80]}")
            continue
        if user_input == "/gateway":
            if gateway:
                console.print(gateway.stats())
            else:
                console.print("[dim]Gateway not configured. Set NANOCODER_GATEWAY_MODELS to enable.[/dim]")
            continue
        if user_input == "/eval":
            agent.auto_eval = not agent.auto_eval
            state = "ON" if agent.auto_eval else "OFF"
            console.print(f"[cyan]Auto-eval is now {state}[/cyan]")
            continue
        if user_input == "/goal":
            _run_goal(agent.llm)
            continue
        if user_input == "/save":
            sid = save_session(agent.messages, config.model)
            console.print(f"[green]Session saved: {sid}[/green]")
            console.print(f"Resume with: nanocoder -r {sid}")
            continue
        if user_input == "/sessions":
            sessions = list_sessions()
            if not sessions:
                console.print("[dim]No saved sessions.[/dim]")
            else:
                for s in sessions:
                    console.print(f"  [cyan]{s['id']}[/cyan] ({s['model']}, {s['saved_at']}) {s['preview']}")
            continue

        # call the agent
        streamed: list[str] = []

        def on_token(tok):
            streamed.append(tok)
            print(tok, end="", flush=True)

        def on_tool(name, kwargs):
            console.print(f"\n[dim]> {name}({_brief(kwargs)})[/dim]")

        try:
            response = agent.chat(user_input, on_token=on_token, on_tool=on_tool)
            if streamed:
                print()  # newline after streamed tokens
            else:
                # response wasn't streamed (came after tool calls)
                console.print(Markdown(response))
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")


def _run_goal(llm):
    """Interactive /goal command: set goal + criteria, run MasterLoop."""
    console.print("[cyan]Goal Mode: Master-SubAgent autonomous loop[/cyan]")
    try:
        goal = pt_prompt("Goal > ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if not goal:
        return

    console.print("[dim]Enter criteria (one per line, empty line to finish):[/dim]")
    criteria = []
    check_cmds = []
    while True:
        try:
            line = pt_prompt(f"  criteria {len(criteria)+1} > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        # optional: "criterion ||| check_command" syntax
        if "|||" in line:
            desc, cmd = line.split("|||", 1)
            criteria.append(desc.strip())
            check_cmds.append(cmd.strip())
        else:
            criteria.append(line)
            check_cmds.append(None)

    if not criteria:
        console.print("[yellow]No criteria entered, cancelled.[/yellow]")
        return

    console.print(f"\n[bold]Goal:[/bold] {goal}")
    for i, c in enumerate(criteria):
        cmd_hint = f"  [dim](check: {check_cmds[i]})[/dim]" if check_cmds[i] else ""
        console.print(f"  {i+1}. {c}{cmd_hint}")
    console.print()

    master = MasterLoop(llm=llm, max_iterations=10, max_sub_rounds=40)

    def on_iteration(iteration, items):
        met_count = sum(1 for c in items if c.met)
        console.print(f"\n[bold yellow]--- Iteration {iteration} check: "
                       f"{met_count}/{len(items)} criteria met ---[/bold yellow]")
        for i, c in enumerate(items):
            mark = "[green][x][/green]" if c.met else "[red][ ][/red]"
            console.print(f"  {mark} {i+1}. {c.description}")
            if c.reason and not c.met:
                console.print(f"       [dim]{c.reason}[/dim]")
        console.print()

    def on_tool(name, kwargs):
        brief = ", ".join(f"{k}={repr(v)[:40]}" for k, v in kwargs.items())
        console.print(f"[dim]> {name}({brief[:100]})[/dim]")

    def on_token(tok):
        print(tok, end="", flush=True)

    try:
        result = master.run(
            goal=goal,
            criteria=criteria,
            check_cmds=check_cmds,
            on_iteration=on_iteration,
            on_tool=on_tool,
            on_token=on_token,
        )
        print()
        console.print(Panel(result.summary(), title="Goal Result",
                            border_style="green" if result.met else "red"))
    except KeyboardInterrupt:
        console.print("\n[yellow]Goal interrupted.[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")


def _show_help():
    console.print(Panel(
        "[bold]Commands:[/bold]\n"
        "  /help          Show this help\n"
        "  /reset         Clear conversation history\n"
        "  /model <name>  Switch model mid-conversation\n"
        "  /tokens        Show token usage\n"
        "  /compact       Compress conversation context\n"
        "  /plan          Plan Mode: plan first, then execute\n"
        "  /goal          Goal Mode: Master-SubAgent loop until criteria met\n"
        "  /memory        Show stored long-term memories\n"
        "  /eval          Toggle auto-eval (syntax check + tests after edits)\n"
        "  /gateway       Show current model routing info\n"
        "  /save          Save session to disk\n"
        "  /sessions      List saved sessions\n"
        "  quit           Exit NanoCoder",
        title="NanoCoder Pro Help",
        border_style="dim",
    ))


def _brief(kwargs: dict, maxlen: int = 80) -> str:
    s = ", ".join(f"{k}={repr(v)[:40]}" for k, v in kwargs.items())
    return s[:maxlen] + ("..." if len(s) > maxlen else "")
