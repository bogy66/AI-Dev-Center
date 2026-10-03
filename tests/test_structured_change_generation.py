"""Regressions for CLAUDE-ADC-S3-CHANGE-GENERATION-APPLICATION-ARCH-FIX-001.

Proves DeveloperAgent (Development Change Generation) and
TestChangeGenerator (Test Change Generation) share ONE
structured-generate-and-repair implementation (app.structured_change_
generation.generate_structured_changes) while remaining distinct role
boundaries with correct, explicit role identity -- and that neither
class ever touches the filesystem.
"""
import json
from unittest.mock import Mock, patch

import app.development_stage as development_stage_module
import app.test_change_generator as test_change_generator_module
from app.development_stage import DeveloperAgent, DevelopmentRequest
from app.structured_change_generation import generate_structured_changes
from app.test_change_generator import TestChangeGenerator


def _structured_response(files=("a.py",)):
    return json.dumps({
        "changes": [{"file": f, "action": "create", "content": "x"} for f in files],
        "tests": [],
    })


class _PromptSensitiveRepairExecutor:
    """Returns a repair only when the original task and role-specific
    repair contract survive in the second prompt."""
    def __init__(self, role, task, response):
        self.role = role
        self.task = task
        self.response = response
        self.prompts = []

    def run(self, role, task, context, role_again):
        assert role == self.role == role_again
        assert context == ""
        self.prompts.append(task)
        if len(self.prompts) == 1:
            return '{"changes": [INVALID_RAW_PRIVATE_SENTINEL'
        assert self.task in task
        assert "OUTPUT FORMAT CORRECTION" in task
        if self.role == "developer":
            assert "previously identified changes" in task
        else:
            assert "test-file changes" in task
        assert "INVALID_RAW_PRIVATE_SENTINEL" not in task
        return self.response


# ---------------------------------------------------------------------
# 1: DeveloperAgent
# ---------------------------------------------------------------------

def test_developer_agent_generates_structured_changes():
    executor = Mock()
    executor.run.return_value = _structured_response()
    result = DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert result["changes"][0]["file"] == "a.py"


def test_developer_agent_performs_exactly_one_repair_attempt_on_malformed_output():
    executor = Mock()
    executor.run.side_effect = ["not json", _structured_response()]
    result = DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert executor.run.call_count == 2
    assert result["changes"][0]["file"] == "a.py"


def test_developer_repair_preserves_task_and_redacts_invalid_answer():
    task = "Implement the requested behavior using the project's established API."
    executor = _PromptSensitiveRepairExecutor("developer", task, _structured_response())
    result = DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", task))
    assert len(executor.prompts) == 2
    assert result["changes"][0]["file"] == "a.py"
    assert result.generation_evidence["repair_attempted"] is True
    assert "INVALID_RAW_PRIVATE_SENTINEL" not in repr(result.generation_evidence)


def test_tester_repair_preserves_test_task_and_role_contract():
    task = "Add a regression for the documented public behavior."
    executor = _PromptSensitiveRepairExecutor(
        "tester", task, _structured_response(files=("tests/test_api.py",)),
    )
    result = TestChangeGenerator(executor).generate(Mock(task=task))
    assert len(executor.prompts) == 2
    assert result["changes"][0]["file"] == "tests/test_api.py"


def test_developer_agent_second_malformed_result_fails_closed():
    executor = Mock()
    executor.run.side_effect = ["not json", "still not json"]
    try:
        DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
        assert False, "expected ValueError"
    except ValueError:
        pass
    assert executor.run.call_count == 2


def test_developer_agent_never_touches_the_filesystem(tmp_path):
    executor = Mock()
    executor.run.return_value = _structured_response(files=("would_be_written.py",))
    DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", tmp_path, "task"))
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------
# 2: TestChangeGenerator
# ---------------------------------------------------------------------

def test_test_change_generator_shares_the_same_repair_policy():
    executor = Mock()
    executor.run.side_effect = ["not json", _structured_response(files=("tests/test_a.py",))]
    result = TestChangeGenerator(executor).generate(Mock(task="add tests"))
    assert executor.run.call_count == 2
    assert result["changes"][0]["file"] == "tests/test_a.py"


def test_test_change_generator_uses_the_tester_role_not_developer():
    executor = Mock()
    executor.run.return_value = _structured_response()
    TestChangeGenerator(executor).generate(Mock(task="add tests"))
    executor.run.assert_called_once_with("tester", "add tests", "", "tester")


def test_test_change_generator_never_touches_the_filesystem(tmp_path):
    executor = Mock()
    executor.run.return_value = _structured_response(files=("would_be_written_test.py",))
    TestChangeGenerator(executor).generate(Mock(task=str(tmp_path)))
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------
# 3: one shared implementation, correct role identity preserved
# ---------------------------------------------------------------------

def test_developer_agent_and_test_change_generator_delegate_to_the_same_function():
    """Behavioral sharing through the actual import seam: both modules
    hold a reference to the exact same function object -- not two
    independent implementations of the same algorithm."""
    assert development_stage_module.generate_structured_changes is generate_structured_changes
    assert test_change_generator_module.generate_structured_changes is generate_structured_changes


def test_developer_role_identity_is_developer():
    executor = Mock()
    with patch.object(development_stage_module, "generate_structured_changes") as fake:
        fake.return_value = {"changes": [], "tests": []}
        DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "implement x"))
    fake.assert_called_once_with(executor, "developer", "implement x", "changes")


def test_tester_role_identity_is_tester():
    executor = Mock()
    with patch.object(test_change_generator_module, "generate_structured_changes") as fake:
        fake.return_value = {"changes": [], "tests": []}
        TestChangeGenerator(executor).generate(Mock(task="write tests for x"))
    fake.assert_called_once_with(executor, "tester", "write tests for x", "test-file changes")


def test_shared_repair_prompt_wording_is_role_appropriate():
    developer_executor = Mock()
    developer_executor.run.side_effect = ["not json", _structured_response()]
    generate_structured_changes(developer_executor, "developer", "task", "changes")
    developer_repair_prompt = developer_executor.run.call_args_list[1].args[1]
    assert "previously identified changes" in developer_repair_prompt

    tester_executor = Mock()
    tester_executor.run.side_effect = ["not json", _structured_response()]
    generate_structured_changes(tester_executor, "tester", "task", "test-file changes")
    tester_repair_prompt = tester_executor.run.call_args_list[1].args[1]
    assert "previously identified test-file changes" in tester_repair_prompt
