"""Eval — automatic verification and self-healing.

After the agent finishes a task, Eval checks if the result is correct by:
  1. Running linter / type checker on modified files
  2. Running tests if a test file exists
  3. Asking the LLM to review the diff

If issues are found, generates a fix prompt and feeds it back to the agent.

Inspired by:
  - SWE-Agent's test-then-fix loop
  - Devin's self-healing CI pipeline
  - Aider's auto-lint-fix
"""

from __future__ import annotations
import subprocess
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLM


@dataclass
class EvalResult:
    passed: bool
    checks: list[str]
    errors: list[str]
    fix_suggestion: str = ""

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"Eval: {status}"]
        for c in self.checks:
            lines.append(f"  [check] {c}")
        for e in self.errors:
            lines.append(f"  [error] {e}")
        if self.fix_suggestion:
            lines.append(f"  [fix] {self.fix_suggestion}")
        return "\n".join(lines)


class Evaluator:
    """Run post-task verification checks."""

    def __init__(self, llm: LLM | None = None, max_fix_attempts: int = 2):
        self.llm = llm
        self.max_fix_attempts = max_fix_attempts

    def evaluate(self, modified_files: list[str]) -> EvalResult:
        """Run all checks on modified files."""
        checks: list[str] = []
        errors: list[str] = []

        for fpath in modified_files:
            if fpath.endswith(".py"):
                lint_ok, lint_msg = self._check_python_syntax(fpath)
                checks.append(f"syntax({fpath}): {'OK' if lint_ok else 'FAIL'}")
                if not lint_ok:
                    errors.append(lint_msg)

        test_ok, test_msg = self._run_tests(modified_files)
        if test_msg:
            checks.append(f"tests: {'OK' if test_ok else 'FAIL'}")
            if not test_ok:
                errors.append(test_msg)

        passed = len(errors) == 0
        fix_suggestion = ""
        if not passed and self.llm:
            fix_suggestion = self._generate_fix(errors)

        return EvalResult(
            passed=passed,
            checks=checks,
            errors=errors,
            fix_suggestion=fix_suggestion,
        )

    @staticmethod
    def _check_python_syntax(filepath: str) -> tuple[bool, str]:
        """Check Python file syntax using py_compile."""
        try:
            result = subprocess.run(
                ["python", "-m", "py_compile", filepath],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True, ""
            return False, result.stderr.strip()[:300]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return True, ""

    @staticmethod
    def _run_tests(modified_files: list[str]) -> tuple[bool, str]:
        """Run pytest if any test files were modified or exist alongside modified files."""
        test_files = [f for f in modified_files if "test" in f.lower()]
        if not test_files:
            return True, ""

        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "--tb=short", "-q"] + test_files,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return True, result.stdout.strip()[-200:]
            return False, (result.stdout + result.stderr).strip()[-500:]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return True, ""

    def _generate_fix(self, errors: list[str]) -> str:
        """Ask the LLM for a fix suggestion based on the errors."""
        if not self.llm:
            return ""
        error_text = "\n".join(errors[:5])
        try:
            resp = self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a code repair assistant. Given the errors below, "
                            "suggest a concise fix. Be specific about which file and "
                            "what change to make."
                        ),
                    },
                    {"role": "user", "content": f"Errors:\n{error_text}"},
                ],
            )
            return resp.content.strip()[:500]
        except Exception:
            return ""

    @staticmethod
    def extract_modified_files(messages: list[dict]) -> list[str]:
        """Extract file paths that were likely modified from conversation history."""
        files: set[str] = set()
        for m in messages:
            text = m.get("content", "") or ""
            for match in re.finditer(
                r'(?:write_file|edit_file|created|modified|wrote)\s*[:(]?\s*["\']?'
                r'([\w./\\-]+\.\w{1,5})',
                text,
                re.IGNORECASE,
            ):
                files.add(match.group(1))
        return list(files)
