# -*- coding: utf-8 -*-
"""Drive NanoCoder with MasterLoop: fully autonomous crawler task.

The Master sets the goal and criteria, then drives the SubAgent in a loop
until every criterion is verified. No human code intervention needed.
"""
import sys
import os
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nanocoder.llm import LLM
from nanocoder.config import Config
from nanocoder.master import MasterLoop
from rich.console import Console
from rich.panel import Panel

console = Console()

TODAY = datetime.now().strftime("%Y-%m-%d")

GOAL = (
    "Create a Python script scripts/github_agent_crawler.py that fetches "
    "the top 20 AI-agent-related open-source projects from GitHub (updated "
    "in the last 7 days), and saves the results to data/ as both JSON and "
    "Markdown. Then run it successfully."
)

CRITERIA = [
    "File scripts/github_agent_crawler.py exists and has valid Python syntax",
    "The script runs without errors and exits with code 0",
    f"File data/github_agents_{TODAY}.json exists and is valid JSON with at least 10 items",
    "File data/github_agents_latest.md exists and contains a Markdown table with at least 10 rows",
]

CHECK_CMDS = [
    "python -m py_compile scripts/github_agent_crawler.py",
    "python scripts/github_agent_crawler.py",
    f'python -c "import json; d=json.load(open(\'data/github_agents_{TODAY}.json\')); assert len(d)>=10, f\'only {{len(d)}} items\'"',
    'python -c "lines=open(\'data/github_agents_latest.md\').readlines(); assert len(lines)>12, f\'only {len(lines)} lines\'"',
]


def main():
    # clean previous outputs so the test is honest
    for f in ["scripts/github_agent_crawler.py",
              f"data/github_agents_{TODAY}.json",
              "data/github_agents_latest.md"]:
        if os.path.exists(f):
            os.remove(f)

    config = Config.from_env()
    console.print(Panel(
        f"[bold]NanoCoder MasterLoop[/bold]\n"
        f"Model: [cyan]{config.model}[/cyan]  Base: [dim]{config.base_url}[/dim]\n"
        f"Max iterations: 10",
        border_style="blue",
    ))

    llm = LLM(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    master = MasterLoop(llm=llm, max_iterations=10, max_sub_rounds=40)

    def on_iteration(iteration, items):
        met = sum(1 for c in items if c.met)
        console.print(f"\n[bold yellow]=== Iteration {iteration}: "
                       f"{met}/{len(items)} criteria met ===[/bold yellow]")
        for i, c in enumerate(items):
            mark = "[x]" if c.met else "[ ]"
            console.print(f"  {mark} {i+1}. {c.description}")
            if not c.met and c.reason:
                console.print(f"       -> {c.reason[:120]}")
        console.print()

    def on_tool(name, kwargs):
        brief = ", ".join(f"{k}={repr(v)[:50]}" for k, v in kwargs.items())
        console.print(f"  [dim]>> {name}({brief[:120]})[/dim]")

    def on_token(tok):
        print(tok, end="", flush=True)

    console.rule("[bold green]Goal[/bold green]")
    console.print(GOAL)
    console.print()
    for i, c in enumerate(CRITERIA):
        console.print(f"  {i+1}. {c}")
    console.rule()

    result = master.run(
        goal=GOAL,
        criteria=CRITERIA,
        check_cmds=CHECK_CMDS,
        on_iteration=on_iteration,
        on_tool=on_tool,
        on_token=on_token,
    )
    print()
    console.print(Panel(result.summary(),
                        title="Final Result",
                        border_style="green" if result.met else "red"))

    p = llm.total_prompt_tokens
    c = llm.total_completion_tokens
    console.print(f"\n[dim]Tokens: {p} prompt + {c} completion = {p+c} total[/dim]")

    sys.exit(0 if result.met else 1)


if __name__ == "__main__":
    main()
