import json
from unittest.mock import Mock
import pytest
from app.test_change_generator import TestChangeGenerator
from app.developer_changes import DeveloperChanges


def test_generator_returns_structured_changes_without_running_tests():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [{"file": "tests/test_x.py", "action": "create",
                      "content": "def test_x(): pass"}],
        "tests": ["pytest"],
    })
    request = Mock(task="add test")
    result = TestChangeGenerator(executor).generate(request)
    executor.run.assert_called_once_with("tester", "add test", "", "tester")
    assert result["changes"][0]["file"] == "tests/test_x.py"
    assert result["changes"][0]["action"] == "create"
    assert result["changes"][0]["content"] == "def test_x(): pass"


def test_generator_uses_parse_structured_only():
    """The productive Tester path must not fall back to legacy Markdown."""
    executor = Mock()
    executor.run.return_value = "## Dateien\n### Datei: tests/test_x.py\ncreate"
    with pytest.raises(ValueError, match="not valid JSON"):
        TestChangeGenerator(executor).generate(Mock(task="x"))


def test_markdown_tester_response_rejected():
    executor = Mock()
    executor.run.return_value = "## Dateien\n### Datei: tests/y.py\ncreate"
    with pytest.raises(ValueError, match="not valid JSON"):
        TestChangeGenerator(executor).generate(Mock(task="write tests"))


def test_yaml_tester_response_rejected():
    executor = Mock()
    executor.run.return_value = "changes:\n  - file: tests/z.py\n    action: create"
    with pytest.raises(ValueError, match="not valid JSON"):
        TestChangeGenerator(executor).generate(Mock(task="write tests"))


def test_invalid_json_rejected():
    executor = Mock()
    executor.run.return_value = '{changes: [bogus]}'
    with pytest.raises(ValueError, match="not valid JSON"):
        TestChangeGenerator(executor).generate(Mock(task="x"))


def test_missing_tests_rejected():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [{"file": "tests/x.py", "action": "create", "content": "x"}],
    })
    with pytest.raises(ValueError, match="'tests' must be an array"):
        TestChangeGenerator(executor).generate(Mock(task="x"))


def test_invalid_action_rejected():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [{"file": "tests/x.py", "action": "execute", "content": "rm -rf"}],
        "tests": [],
    })
    with pytest.raises(ValueError, match="unsupported action"):
        TestChangeGenerator(executor).generate(Mock(task="x"))


def test_valid_structured_response_succeeds():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [{"file": "tests/test_y.py", "action": "create",
                      "content": "def test_y(): pass"}],
        "tests": [],
    })
    result = TestChangeGenerator(executor).generate(Mock(task="add another test"))
    assert result["changes"][0]["file"] == "tests/test_y.py"
    assert executor.run.call_count == 1


def test_generator_update_delete_changes():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [
            {"file": "tests/test_a.py", "action": "update", "content": "updated"},
            {"file": "tests/test_b.py", "action": "delete", "content": ""},
        ],
        "tests": ["pytest -q"],
    })
    result = TestChangeGenerator(executor).generate(Mock(task="refactor tests"))
    assert len(result["changes"]) == 2
    assert result["changes"][0]["action"] == "update"
    assert result["changes"][1]["action"] == "delete"


def test_generator_tests_array_is_preserved():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [],
        "tests": ["pytest", "black --check tests/", "mypy tests/"],
    })
    result = TestChangeGenerator(executor).generate(Mock(task="lint tests"))
    assert result["tests"] == ["pytest", "black --check tests/", "mypy tests/"]


def test_no_markdown_expected_in_tester_prompt():
    """Verify the productive ProviderAgentExecutor sends a JSON contract for testers."""
    from app.agent_executor import ProviderAgentExecutor

    class RecordingProvider:
        def __init__(self):
            self.prompt = None

        def complete(self, prompt, max_tokens=None):
            self.prompt = prompt
            return json.dumps({"changes": [], "tests": []})

    provider = RecordingProvider()
    executor = ProviderAgentExecutor(provider)
    executor.run("tester elementary", "add tests for module X", "src/: module.py",
                 "tester", 400)
    assert '"changes"' in provider.prompt
    assert '"tests"' in provider.prompt
    assert "## Dateien" not in provider.prompt
    assert "### Aktion:" not in provider.prompt
    assert "Tester of AI-Dev-Center" in provider.prompt


def test_structured_contract_precedes_task_content():
    """Output contract must appear before task content in the tester prompt."""
    from app.agent_executor import ProviderAgentExecutor

    class RecordingProvider:
        def __init__(self):
            self.prompt = None

        def complete(self, prompt, max_tokens=None):
            self.prompt = prompt
            return "{}"

    provider = RecordingProvider()
    executor = ProviderAgentExecutor(provider)
    executor.run("tester", "write unit tests", "project facts", "tester")

    contract_idx = provider.prompt.index('"changes"')
    task_idx = provider.prompt.index("write unit tests")
    assert contract_idx < task_idx, (
        f"structured contract (idx {contract_idx}) must precede task "
        f"(idx {task_idx})"
    )


def test_developer_and_tester_share_structured_contract():
    """Both Developer and Tester use the same DeveloperChanges.parse_structured()."""
    from app.agent_executor import ProviderAgentExecutor

    class RecordingProvider:
        def __init__(self):
            self.prompts = []

        def complete(self, prompt, max_tokens=None):
            self.prompts.append(prompt)
            return json.dumps({"changes": [], "tests": []})

    provider = RecordingProvider()
    executor = ProviderAgentExecutor(provider)
    executor.run("developer", "add feature", "", "developer")
    executor.run("tester", "add tests", "", "tester")

    assert len(provider.prompts) == 2
    for p in provider.prompts:
        assert '"changes"' in p
        assert '"tests"' in p
        assert '"file"' in p
        assert '"action"' in p
        assert '"content"' in p


def test_invalid_first_response_with_valid_repair_succeeds():
    """One repair call succeeds after first response fails structural parse."""
    executor = Mock()
    executor.run.side_effect = [
        "not json at all",
        json.dumps({
            "changes": [{"file": "tests/test_a.py", "action": "create",
                          "content": "def test_a(): pass"}],
            "tests": ["pytest"],
        }),
    ]
    result = TestChangeGenerator(executor).generate(Mock(task="add tests"))
    assert result["changes"][0]["file"] == "tests/test_a.py"
    assert executor.run.call_count == 2


def test_markdown_fenced_json_recovers_through_repair():
    """Markdown-fenced JSON is not permissively parsed but recovers through repair."""
    executor = Mock()
    executor.run.side_effect = [
        '```json\n{"changes": [], "tests": []}\n```',
        json.dumps({
            "changes": [{"file": "tests/test_b.py", "action": "create",
                          "content": "b"}],
            "tests": [],
        }),
    ]
    result = TestChangeGenerator(executor).generate(Mock(task="x"))
    assert result["changes"][0]["file"] == "tests/test_b.py"
    assert executor.run.call_count == 2


def test_two_invalid_responses_fail_closed_with_original_error():
    """Two invalid responses re-raise the original structured parse error."""
    executor = Mock()
    executor.run.side_effect = ["bogus {}", "still bogus"]
    with pytest.raises(ValueError, match="not valid JSON"):
        TestChangeGenerator(executor).generate(Mock(task="x"))
    assert executor.run.call_count == 2


def test_never_more_than_two_executor_calls():
    """Invalid first response yields exactly two calls (one repair), never three."""
    executor = Mock()
    executor.run.side_effect = ["invalid", "also invalid", "should not be reached"]
    with pytest.raises(ValueError):
        TestChangeGenerator(executor).generate(Mock(task="x"))
    assert executor.run.call_count == 2


def test_structural_invalid_json_still_rejected_through_recovery():
    """Valid JSON with missing 'tests' key fails through recovery as well."""
    executor = Mock()
    executor.run.side_effect = [
        json.dumps({
            "changes": [{"file": "tests/x.py", "action": "create", "content": "x"}],
        }),
        json.dumps({
            "changes": [{"file": "tests/x.py", "action": "create", "content": "x"}],
        }),
    ]
    with pytest.raises(ValueError, match="'tests' must be an array"):
        TestChangeGenerator(executor).generate(Mock(task="x"))
    assert executor.run.call_count == 2


def test_invalid_action_still_rejected_through_recovery():
    """Unsupported action fails through recovery as well."""
    executor = Mock()
    executor.run.side_effect = [
        json.dumps({
            "changes": [{"file": "tests/x.py", "action": "execute", "content": "rm"}],
            "tests": [],
        }),
        json.dumps({
            "changes": [{"file": "tests/x.py", "action": "execute", "content": "rm"}],
            "tests": [],
        }),
    ]
    with pytest.raises(ValueError, match="unsupported action"):
        TestChangeGenerator(executor).generate(Mock(task="x"))
    assert executor.run.call_count == 2