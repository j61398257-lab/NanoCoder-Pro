# -*- coding: utf-8 -*-
"""Drive NanoCoder to write the GitHub agent-projects crawler by itself."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nanocoder.agent import Agent
from nanocoder.llm import LLM
from nanocoder.config import Config
from rich.console import Console

console = Console()

TASK = (
    "Please complete ALL of the following tasks in the current project directory:\n\n"
    "1. Create directories scripts/ and data/ (if they do not exist).\n"
    "2. Create the file scripts/github_agent_crawler.py with these requirements:\n"
    "   - Call the GitHub Search API (public endpoint, no token needed):\n"
    "     GET https://api.github.com/search/repositories\n"
    "   - Use query string: q=AI+agent+llm, sort=stars, order=desc, per_page=100\n"
    "   - Filter results where updated_at is within the last 7 days\n"
    "   - Take the top 20 from the filtered list\n"
    "   - Fields to include per project:\n"
    "     name, full_name, description, stargazers_count, html_url, language, updated_at\n"
    "   - Save results to TWO files:\n"
    "     a) data/github_agents_YYYY-MM-DD.json  (JSON array with today's date in filename)\n"
    "     b) data/github_agents_latest.md  (Markdown table, overwritten each run)\n"
    "   - Include a proper if __name__ == '__main__' entry point\n"
    "   - Set User-Agent: 'NanoCoder-Crawler/1.0' header to avoid GitHub rate limiting\n"
    "   - Print progress to console while running\n"
    "3. After writing the script, execute it immediately with bash:\n"
    "   python scripts/github_agent_crawler.py\n"
    "4. If there are any errors, fix them and run again. Keep fixing until it succeeds.\n\n"
    "Use only stdlib (urllib) - do NOT install new packages.\n"
)


def main():
    config = Config.from_env()
    console.print(f"[bold]NanoCoder[/bold] - Model: [cyan]{config.model}[/cyan]  Base: [dim]{config.base_url}[/dim]")
    console.print()

    llm = LLM(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    agent = Agent(llm=llm, max_context_tokens=config.max_context_tokens, max_rounds=40)

    def on_token(tok):
        print(tok, end="", flush=True)

    def on_tool(name, kwargs):
        brief = ", ".join(f"{k}={repr(v)[:70]}" for k, v in kwargs.items())
        console.print(f"\n[bold yellow]  >> {name}[/bold yellow]([dim]{brief[:120]}[/dim])")

    console.rule("[bold green]NanoCoder Task Start[/bold green]")
    console.print(TASK)
    console.rule()

    response = agent.chat(TASK, on_token=on_token, on_tool=on_tool)
    print()
    console.rule("[bold green]NanoCoder Task Complete[/bold green]")

    p = agent.llm.total_prompt_tokens
    c = agent.llm.total_completion_tokens
    console.print(f"[dim]Tokens used: {p} prompt + {c} completion = {p + c} total[/dim]")


if __name__ == "__main__":
    main()
