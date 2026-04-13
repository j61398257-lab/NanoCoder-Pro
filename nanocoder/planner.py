"""Plan Mode — 'think before act' two-stage execution.

Stage 1: Planner LLM produces a structured step-by-step plan.
Stage 2: Executor (the normal Agent loop) follows the plan step by step.

Inspired by:
  - Cursor's Plan Mode (plan-then-execute)
  - Aider's architect/editor split
  - Devin's Plan-and-Execute pattern
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLM

PLAN_SYSTEM_PROMPT = """\
You are a planning assistant. Given a user request, produce a clear step-by-step plan.

Output format (strict):
1. <action description>
2. <action description>
...

Rules:
- Each step should be a concrete, executable action (e.g. "Read file X", "Edit function Y in Z").
- Keep steps atomic — one file or one logical change per step.
- Do NOT include code. Only describe what to do.
- Number each step starting from 1.
- End with a step that verifies the result (e.g. "Run tests", "Check output").
"""


@dataclass
class PlanStep:
    index: int
    description: str
    status: str = "pending"   # pending | in_progress | done | skipped


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)

    @property
    def current_step(self) -> PlanStep | None:
        for s in self.steps:
            if s.status in ("pending", "in_progress"):
                return s
        return None

    @property
    def is_complete(self) -> bool:
        return all(s.status in ("done", "skipped") for s in self.steps)

    def advance(self):
        """Mark the current step done and move to the next."""
        step = self.current_step
        if step:
            step.status = "done"

    def format(self) -> str:
        """Pretty-print the plan with status indicators."""
        markers = {"pending": "[ ]", "in_progress": "[>]", "done": "[x]", "skipped": "[-]"}
        lines = [f"Plan: {self.goal}", ""]
        for s in self.steps:
            m = markers.get(s.status, "[ ]")
            lines.append(f"  {m} {s.index}. {s.description}")
        return "\n".join(lines)


class Planner:
    """Generates a plan from a user request via an LLM call."""

    def __init__(self, llm: LLM):
        self.llm = llm

    def create_plan(self, user_request: str) -> Plan:
        """Ask the LLM to produce a step-by-step plan."""
        resp = self.llm.chat(
            messages=[
                {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                {"role": "user", "content": user_request},
            ],
        )
        steps = self._parse_steps(resp.content)
        return Plan(goal=user_request, steps=steps)

    @staticmethod
    def _parse_steps(text: str) -> list[PlanStep]:
        """Parse numbered steps from planner output."""
        import re
        steps: list[PlanStep] = []
        for match in re.finditer(r'(\d+)\.\s+(.+)', text):
            idx = int(match.group(1))
            desc = match.group(2).strip()
            steps.append(PlanStep(index=idx, description=desc))
        return steps
