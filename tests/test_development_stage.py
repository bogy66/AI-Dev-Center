from unittest.mock import Mock
import pytest
from app.development_stage import DevelopmentRequest, DevelopmentStage, DeveloperAgent


def test_developer_agent_generates_changes_without_writing():
    executor = Mock()
    executor.run.return_value = "## Dateien\n### Datei: a.py\ncreate\n### Inhalt:\nprint(1)"
    changes = DeveloperAgent(executor).generate_changes(DevelopmentRequest("p", "/tmp", "task"))
    assert changes["changes"] == [{"file": "a.py", "action": "create", "content": "print(1)"}]


def test_stage_delegates_generated_changes_to_applier(tmp_path):
    agent = Mock()
    changes = {"changes": [{"file": "a.py", "action": "create", "content": "x"}]}
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
    executor.run.return_value = "## Dateien"
    request = DevelopmentRequest("project", "/tmp/project", "implement feature")

    DeveloperAgent(executor).generate_changes(request)

    executor.run.assert_called_once_with("developer", request.task, "", "developer", 0)


def test_developer_failure_does_not_apply_changes(tmp_path):
    agent = Mock()
    agent.generate_changes.side_effect = RuntimeError("provider failed")
    factory = Mock()

    with pytest.raises(RuntimeError, match="provider failed"):
        DevelopmentStage(agent, factory).run(DevelopmentRequest("p", tmp_path, "task"))

    factory.assert_not_called()


def test_invalid_developer_output_does_not_apply_changes(tmp_path):
    executor = Mock()
    executor.run.return_value = "invalid"
    factory = Mock()

    with pytest.raises(ValueError):
        DevelopmentStage(DeveloperAgent(executor), factory).run(DevelopmentRequest("p", tmp_path, "task"))

    factory.assert_not_called()


def test_applier_error_is_not_swallowed(tmp_path):
    agent = Mock()
    agent.generate_changes.return_value = {"changes": []}
    applier = Mock()
    applier.apply.side_effect = OSError("write failed")

    with pytest.raises(OSError, match="write failed"):
        DevelopmentStage(agent, Mock(return_value=applier)).run(DevelopmentRequest("p", tmp_path, "task"))
