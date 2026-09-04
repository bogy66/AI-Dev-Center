import json
from unittest.mock import Mock
import pytest
from app.development_stage import DevelopmentRequest, DevelopmentStage, DeveloperAgent


def _structured_response(extra_changes=None):
    changes = extra_changes or [{
        "file": "a.py", "action": "create", "content": "print(1)"
    }]
    return json.dumps({"changes": changes, "tests": ["pytest"]})


def test_developer_agent_generates_changes_without_writing():
    executor = Mock()
    executor.run.return_value = _structured_response()
    changes = DeveloperAgent(executor).generate_changes(
        DevelopmentRequest("p", "/tmp", "task"),
    )
    assert changes["changes"] == [{"file": "a.py", "action": "create", "content": "print(1)"}]
    assert changes["tests"] == ["pytest"]


def test_stage_delegates_generated_changes_to_applier(tmp_path):
    agent = Mock()
    changes = {"changes": [{"file": "a.py", "action": "create", "content": "x"}], "tests": []}
    agent.generate_changes.return_value = changes
    applier = Mock()
    applier.apply.return_value = {"applied": ["a.py"], "skipped": []}
    factory = Mock(return_value=applier)
    result = DevelopmentStage(agent, factory).run(DevelopmentRequest("p", tmp_path, "task"))
    agent.generate_changes.assert_called_once()
    applier.apply.assert_called_once_with(changes)
    assert result.status == "success"
    assert result.generated_changes is changes
    assert result.applied_changes == {"applied": ["a.py"], "skipped": []}


def test_developer_receives_request_exactly_once():
    executor = Mock()
    executor.run.return_value = _structured_response()
    request = DevelopmentRequest("project", "/tmp/project", "implement feature")
    DeveloperAgent(executor).generate_changes(request)
    executor.run.assert_called_once_with("developer", request.task, "", "developer")


def test_developer_failure_does_not_apply_changes(tmp_path):
    agent = Mock()
    agent.generate_changes.side_effect = RuntimeError("provider failed")
    factory = Mock()
    with pytest.raises(RuntimeError, match="provider failed"):
        DevelopmentStage(agent, factory).run(DevelopmentRequest("p", tmp_path, "task"))
    factory.assert_not_called()


def test_invalid_developer_output_does_not_apply_changes(tmp_path):
    executor = Mock()
    executor.run.return_value = "not json"
    factory = Mock()
    with pytest.raises(ValueError):
        DevelopmentStage(DeveloperAgent(executor), factory).run(
            DevelopmentRequest("p", tmp_path, "task"),
        )
    factory.assert_not_called()


def test_applier_error_is_not_swallowed(tmp_path):
    agent = Mock()
    agent.generate_changes.return_value = {"changes": [], "tests": []}
    applier = Mock()
    applier.apply.side_effect = OSError("write failed")
    with pytest.raises(OSError, match="write failed"):
        DevelopmentStage(agent, Mock(return_value=applier)).run(
            DevelopmentRequest("p", tmp_path, "task"),
        )


def test_valid_first_response_is_exactly_one_provider_call():
    executor = Mock()
    executor.run.return_value = _structured_response()
    DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert executor.run.call_count == 1


def test_invalid_first_response_triggers_exactly_one_repair():
    executor = Mock()
    executor.run.side_effect = ["not json", _structured_response()]
    result = DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert executor.run.call_count == 2
    assert result["changes"][0]["file"] == "a.py"


def test_invalid_repair_fails_closed():
    executor = Mock()
    executor.run.side_effect = ["not json", "still not json"]
    with pytest.raises(ValueError, match="not valid JSON"):
        DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert executor.run.call_count == 2


def test_never_more_than_two_provider_calls():
    executor = Mock()
    executor.run.side_effect = ["not json", "also invalid", "should not be called"]
    with pytest.raises(ValueError):
        DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert executor.run.call_count == 2


def test_productive_path_does_not_use_legacy_markdown():
    executor = Mock()
    executor.run.return_value = "## Dateien\n### Datei: a.py\ncreate\n### Inhalt:\nprint(1)"
    with pytest.raises(ValueError):
        DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert executor.run.call_count == 2


def test_repair_does_not_contain_raw_invalid_response():
    executor = Mock()
    executor.run.side_effect = [
        json.dumps({"changes": [{"file": "a.py", "action": "invalid_action", "content": "x"}], "tests": []}),
        _structured_response(),
    ]
    result = DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert "invalid_action" not in executor.run.call_args_list[1].args[1]
    assert result["changes"][0]["file"] == "a.py"


def test_development_stage_applies_only_validated_structured_changes(tmp_path):
    executor = Mock()
    executor.run.return_value = _structured_response()
    applier = Mock()
    applier.apply.return_value = {"applied": ["a.py"], "skipped": []}
    factory = Mock(return_value=applier)
    result = DevelopmentStage(DeveloperAgent(executor), factory).run(
        DevelopmentRequest("p", tmp_path, "task"),
    )
    assert result.status == "success"
    applier.apply.assert_called_once()


def test_developer_agent_multiple_changes():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [
            {"file": "a.py", "action": "create", "content": "print('a')"},
            {"file": "b.py", "action": "update", "content": "print('b')"},
            {"file": "c.py", "action": "delete", "content": ""},
        ],
        "tests": ["pytest -q"],
    })
    result = DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert len(result["changes"]) == 3
    assert result["changes"][0]["action"] == "create"
    assert result["changes"][1]["action"] == "update"
    assert result["changes"][2]["action"] == "delete"


def test_invalid_entry_rejects_whole_response():
    executor = Mock()
    executor.run.side_effect = [
        json.dumps({
            "changes": [
                {"file": "ok.py", "action": "create", "content": "x"},
                {"file": "bad.py", "action": "execute", "content": "x"},
            ],
            "tests": [],
        }),
        "also invalid",
    ]
    with pytest.raises(ValueError, match="unsupported action"):
        DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert executor.run.call_count == 2