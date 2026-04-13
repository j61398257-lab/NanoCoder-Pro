"""Tests for MasterLoop (Master-SubAgent autonomous loop).

Uses a mock LLM to test the loop logic without real API calls.
"""
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from nanocoder.master import MasterLoop, CriteriaItem, GoalResult
from nanocoder.llm import LLMResponse, ToolCall


class MockLLM:
    """Fake LLM that returns scripted responses for testing the loop."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._call_count = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.model = "mock"
        self.extra = {}

    def chat(self, messages, tools=None, on_token=None):
        idx = min(self._call_count, len(self._responses) - 1)
        content = self._responses[idx]
        self._call_count += 1
        if on_token and content:
            on_token(content)
        return LLMResponse(content=content, tool_calls=[])


def test_goal_result_summary():
    r = GoalResult(
        goal="test goal",
        met=True,
        iterations=2,
        criteria=[
            CriteriaItem(description="file exists", met=True, reason="ok"),
            CriteriaItem(description="runs ok", met=True, reason="passed"),
        ],
        final_output="done",
    )
    s = r.summary()
    assert "GOAL MET" in s
    assert "test goal" in s
    assert "[x]" in s


def test_goal_result_not_met():
    r = GoalResult(
        goal="test goal",
        met=False,
        iterations=3,
        criteria=[
            CriteriaItem(description="file exists", met=True, reason="ok"),
            CriteriaItem(description="runs ok", met=False, reason="syntax error"),
        ],
        final_output="failed",
    )
    s = r.summary()
    assert "GOAL NOT MET" in s
    assert "[ ]" in s
    assert "syntax error" in s


def test_master_loop_all_criteria_met_by_cmd():
    """When all check_cmds pass on the first try, loop should finish in 1 iteration."""
    mock_llm = MockLLM([
        "I have completed the task.",
        '[{"index": 1, "met": true, "reason": "ok"}]',
    ])

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test.txt")
        Path(test_file).write_text("hello\nworld\n")

        master = MasterLoop(llm=mock_llm, max_iterations=5, max_sub_rounds=5)
        result = master.run(
            goal="create a file",
            criteria=["file exists"],
            check_cmds=[f'python -c "assert __import__(\'os\').path.exists(\'{test_file.replace(chr(92), chr(47))}\')"'],
        )

        assert result.met is True
        assert result.iterations == 1
        assert result.criteria[0].met is True


def test_master_loop_retries_on_failure():
    """When check_cmd fails initially, loop should retry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "output.txt").replace("\\", "/")

        call_count = [0]

        class RetryMockLLM(MockLLM):
            def chat(self, messages, tools=None, on_token=None):
                call_count[0] += 1
                if call_count[0] == 2:
                    Path(test_file).write_text("data line 1\ndata line 2\n")
                return LLMResponse(content="Working on it.", tool_calls=[])

        mock_llm = RetryMockLLM(["working"])
        master = MasterLoop(llm=mock_llm, max_iterations=5, max_sub_rounds=3)

        result = master.run(
            goal="create output file",
            criteria=["output.txt exists and has content"],
            check_cmds=[f'python -c "assert len(open(\'{test_file}\').readlines())>=2"'],
        )

        assert result.met is True
        assert result.iterations >= 2


def test_master_loop_max_iterations():
    """Loop should stop after max_iterations even if criteria not met."""
    mock_llm = MockLLM(["I tried but failed."] * 5)
    master = MasterLoop(llm=mock_llm, max_iterations=3, max_sub_rounds=3)

    result = master.run(
        goal="impossible task",
        criteria=["this will never pass"],
        check_cmds=["python -c \"assert False, 'always fails'\""],
    )

    assert result.met is False
    assert result.iterations == 3


def test_criteria_item_defaults():
    c = CriteriaItem(description="test")
    assert c.met is False
    assert c.check_cmd is None
    assert c.reason == ""


def test_build_continue_prompt():
    items = [
        CriteriaItem(description="file exists", met=True),
        CriteriaItem(description="runs ok", met=False, reason="syntax error on line 5"),
        CriteriaItem(description="output valid", met=False, reason="file not found"),
    ]
    prompt = MasterLoop._build_continue_prompt(items)
    assert "NOT YET MET" in prompt
    assert "runs ok" in prompt
    assert "output valid" in prompt
    assert "syntax error" in prompt
    assert "file exists" not in prompt  # met items should not appear


def test_parse_verdicts_clean_json():
    text = '[{"index": 1, "met": true, "reason": "ok"}, {"index": 2, "met": false, "reason": "missing"}]'
    result = MasterLoop._parse_verdicts(text)
    assert len(result) == 2
    assert result[0]["met"] is True
    assert result[1]["met"] is False


def test_parse_verdicts_with_markdown_fence():
    text = '```json\n[{"index": 1, "met": true, "reason": "ok"}]\n```'
    result = MasterLoop._parse_verdicts(text)
    assert len(result) == 1
    assert result[0]["met"] is True


def test_parse_verdicts_embedded_in_text():
    text = 'Here is my evaluation:\n[{"index": 1, "met": false, "reason": "nope"}]\nThat is all.'
    result = MasterLoop._parse_verdicts(text)
    assert len(result) == 1
    assert result[0]["met"] is False
