import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.workflow_cli as cli
from app.requirement_model import SetupPlan, SetupStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_fake_result(
    *,
    requirements_count=3,
    fallback_used=False,
    valid=True,
    normalized_count=2,
    rejected_count=0,
    preflight_ready=True,
    missing_count=0,
    warning_count=0,
    plan_status="pending_approval",
    steps=None,
):
    """Return a MagicMock that looks like a WorkflowResult."""
    if steps is None:
        steps = (
            SetupStep(
                id="step-1",
                requirement_id="req-1",
                action="install",
                install_method="python_package",
                package="some-pkg",
                version="1.2.3",
                command=None,
                verification_after=None,
                is_approved=False,
            ),
        )
    else:
        steps = tuple(steps)

    result = MagicMock()
    result.discovery_result = MagicMock(
        requirements=[MagicMock()] * requirements_count,
        fallback_used=fallback_used,
    )
    result.validation_result = MagicMock(
        valid=valid,
        normalized_requirements=[MagicMock()] * normalized_count,
        rejected_requirements=[MagicMock()] * rejected_count,
    )
    result.preflight_result = MagicMock(
        overall_ready=preflight_ready,
        missing_requirements=[MagicMock()] * missing_count,
        warnings=[MagicMock()] * warning_count,
    )
    result.setup_plan = SetupPlan(
        id="plan-test-1",
        project_id="myproj",
        steps=tuple(steps),
        requires_user_approval=True,
        rollback_steps=(),
        warnings=(),
        status=plan_status,
    )
    return result


@pytest.fixture(autouse=True)
def isolate_workflow_plan_store(monkeypatch):
    """Keep CLI tests from persisting plans in the repository."""
    store = MagicMock()
    monkeypatch.setattr(cli, "WorkflowPlanStore", lambda root: store)
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestWorkflowComposition:
    def test_build_workflow_injects_council_and_materializer(self, monkeypatch):
        config = SimpleNamespace(
            model="test-model",
            council=SimpleNamespace(enabled=True),
        )
        secret_resolver = MagicMock()
        provider = MagicMock()
        council = MagicMock()
        materializer = MagicMock()
        council_factory = MagicMock(return_value=council)
        materializer_factory = MagicMock(return_value=materializer)

        monkeypatch.setattr(cli, "LocalSecretStore", lambda: secret_resolver)
        monkeypatch.setattr(cli, "create_llm_provider", lambda c, s: provider)
        monkeypatch.setattr(cli, "EngineeringCouncil", council_factory)
        monkeypatch.setattr(cli, "ToolchainMaterializer", materializer_factory)

        workflow = cli.build_workflow(config)

        council_factory.assert_called_once_with(
            council_config=config.council,
            secret_resolver=secret_resolver,
        )
        materializer_factory.assert_called_once_with()
        assert workflow._discovery._provider is provider
        assert workflow._discovery._ai_model == "test-model"
        assert workflow._council is council
        assert workflow._materializer is materializer

    def test_build_workflow_blocks_missing_council_config(self, monkeypatch):
        config = SimpleNamespace(council=None)
        secret_store = MagicMock()
        provider_factory = MagicMock()
        council_factory = MagicMock()

        monkeypatch.setattr(cli, "LocalSecretStore", secret_store)
        monkeypatch.setattr(cli, "create_llm_provider", provider_factory)
        monkeypatch.setattr(cli, "EngineeringCouncil", council_factory)

        with pytest.raises(
            cli.WorkflowExecutionError,
            match="Engineering Council configuration",
        ):
            cli.build_workflow(config)

        secret_store.assert_not_called()
        provider_factory.assert_not_called()
        council_factory.assert_not_called()


class TestValidProject:
    def test_successful_run(self, tmp_path, monkeypatch, capsys):
        """End‑to‑end happy path: valid project, workflow succeeds."""
        project = tmp_path / "myproj"
        project.mkdir()
        (project / "main.py").write_text("print('hello')")
        (project / "readme.md").write_text("# Project")

        # Mock the workflow
        mock_workflow_cls = MagicMock()
        mock_instance = mock_workflow_cls.return_value
        fake_result = _make_fake_result()
        mock_instance.run.return_value = fake_result
        monkeypatch.setattr(cli, "DevelopmentWorkflow", mock_workflow_cls)
        monkeypatch.setattr(cli, "build_workflow", lambda config: mock_instance)

        # Mock config loading
        fake_config = MagicMock(provider="test-provider", model="test-model")
        monkeypatch.setattr(cli, "load_ai_config", lambda path: fake_config)

        store = MagicMock()
        monkeypatch.setattr(
            cli,
            "WorkflowPlanStore",
            lambda root: store,
        )

        monkeypatch.setattr(sys, "argv", ["workflow_cli.py", str(project)])

        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 0

        captured = capsys.readouterr()
        out = captured.out

        # Basic output checks
        assert "Provider: test-provider" in out
        assert "Model: test-model" in out
        assert "Discovery fallback: False" in out
        assert "Number of requirements: 3" in out
        assert "Validation valid: True" in out
        assert "Normalized: 2" in out
        assert "Rejected: 0" in out
        assert "Preflight ready: True" in out
        assert "Missing count: 0" in out
        assert "Warning count: 0" in out
        assert "SetupPlan status: pending_approval" in out
        assert "Number of SetupSteps: 1" in out
        assert "requirement_id: req-1" in out
        assert "action: install" in out
        assert "package: some-pkg" in out
        assert "version: 1.2.3" in out
        assert "is_approved: False" in out

        # No secrets leaked
        assert "secret" not in out.lower()
        assert "api_key" not in out.lower()

        # Workflow was called with the expected project_info
        mock_instance.run.assert_called_once()
        store.save.assert_called_once_with(fake_result.setup_plan)
        call_args = mock_instance.run.call_args
        project_info_arg = call_args.kwargs["project_info"]
        assert "files" in project_info_arg
        paths = {f["path"] for f in project_info_arg["files"]}
        assert "main.py" in paths
        assert "readme.md" in paths

    def test_non_existent_path(self, monkeypatch, capsys):
        """Exit code 1 when the project path does not exist."""
        monkeypatch.setattr(sys, "argv", ["workflow_cli.py", "/no/such/dir"])
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: project path does not exist" in captured.err

    def test_config_load_failure(self, tmp_path, monkeypatch, capsys):
        """Exit code 1 when AI config cannot be loaded."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "dummy.txt").write_text("hello")

        monkeypatch.setattr(sys, "argv", ["workflow_cli.py", str(project)])
        monkeypatch.setattr(
            cli, "load_ai_config", lambda path: (_ for _ in ()).throw(Exception("boom"))
        )

        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error loading AI config" in captured.err

    def test_workflow_exception(self, tmp_path, monkeypatch, capsys):
        """Exit code 1 when the workflow raises an exception."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "dummy.txt").write_text("hello")

        fake_config = MagicMock(provider="p", model="m")
        monkeypatch.setattr(cli, "load_ai_config", lambda path: fake_config)

        mock_workflow_cls = MagicMock()
        mock_instance = mock_workflow_cls.return_value
        mock_instance.run.side_effect = RuntimeError("something broke")
        monkeypatch.setattr(cli, "DevelopmentWorkflow", mock_workflow_cls)

        monkeypatch.setattr(sys, "argv", ["workflow_cli.py", str(project)])

        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Workflow failed" in captured.err
        # No secret values in the error message
        assert "secret" not in captured.err.lower()


def test_discovery_fallback_blocks_cli_and_does_not_save(
    tmp_path,
    monkeypatch,
    capsys,
):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "README.md").write_text("# demo")

    fake_config = MagicMock(
        provider="test-provider",
        model="test-model",
    )
    monkeypatch.setattr(
        cli,
        "load_ai_config",
        lambda path: fake_config,
    )

    workflow = MagicMock()
    workflow.run.side_effect = cli.WorkflowExecutionError(
        "Requirement discovery fallback was used; "
        "workflow planning is blocked."
    )
    monkeypatch.setattr(
        cli,
        "build_workflow",
        lambda config: workflow,
    )

    store = MagicMock()
    monkeypatch.setattr(
        cli,
        "WorkflowPlanStore",
        lambda root: store,
    )

    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["workflow_cli.py", str(project)],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2

    captured = capsys.readouterr()
    assert "Workflow blocked:" in captured.err
    assert "Requirement discovery fallback was used" in captured.err

    workflow.run.assert_called_once()
    store.save.assert_not_called()


class TestFileReading:
    def test_binary_file_skipped(self, tmp_path, monkeypatch, capsys):
        """Binary files are skipped and a warning is printed."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "good.py").write_text("print(1)")
        binary = project / "data.bin"
        binary.write_bytes(b"\x00\x01\x02\xff")

        # Minimal mocks so the workflow doesn't actually run
        fake_config = MagicMock(provider="p", model="m")
        monkeypatch.setattr(cli, "load_ai_config", lambda path: fake_config)

        mock_workflow_cls = MagicMock()
        mock_instance = mock_workflow_cls.return_value
        mock_instance.run.return_value = _make_fake_result()
        monkeypatch.setattr(cli, "DevelopmentWorkflow", mock_workflow_cls)
        monkeypatch.setattr(cli, "build_workflow", lambda config: mock_instance)

        store = MagicMock()
        monkeypatch.setattr(cli, "WorkflowPlanStore", lambda root: store)

        monkeypatch.setattr(sys, "argv", ["workflow_cli.py", str(project)])

        with pytest.raises(SystemExit):
            cli.main()

        captured = capsys.readouterr()
        assert "Skipping binary/unreadable file" in captured.err
        # The binary file must not appear in the project_info
        call_args = mock_instance.run.call_args
        files = call_args.kwargs["project_info"]["files"]
        paths = {f["path"] for f in files}
        assert "good.py" in paths
        assert "data.bin" not in paths

    def test_large_file_skipped(self, tmp_path, monkeypatch, capsys):
        """Files larger than MAX_FILE_SIZE are skipped with a warning."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "small.txt").write_text("ok")
        large = project / "big.log"
        # Create a file larger than the limit
        large.write_bytes(b"x" * (cli.MAX_FILE_SIZE + 1))

        fake_config = MagicMock(provider="p", model="m")
        monkeypatch.setattr(cli, "load_ai_config", lambda path: fake_config)

        mock_workflow_cls = MagicMock()
        mock_instance = mock_workflow_cls.return_value
        mock_instance.run.return_value = _make_fake_result()
        monkeypatch.setattr(cli, "DevelopmentWorkflow", mock_workflow_cls)
        monkeypatch.setattr(cli, "build_workflow", lambda config: mock_instance)

        monkeypatch.setattr(sys, "argv", ["workflow_cli.py", str(project)])

        with pytest.raises(SystemExit):
            cli.main()

        captured = capsys.readouterr()
        assert "Skipping large file" in captured.err
        call_args = mock_instance.run.call_args
        files = call_args.kwargs["project_info"]["files"]
        paths = {f["path"] for f in files}
        assert "small.txt" in paths
        assert "big.log" not in paths

    def test_unreadable_file_skipped(self, tmp_path, monkeypatch, capsys):
        """Files that cannot be read are skipped."""

        # Simulate an unreadable file by making read_text raise OSError.
        project = tmp_path / "proj"
        project.mkdir()
        (project / "good.txt").write_text("hello")

        # Simulate an unreadable file by making read_text raise OSError.
        original_read_text = Path.read_text

        def _read_text(self, *args, **kwargs):
            if self.name == "bad.txt":
                raise OSError("permission denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", _read_text)
        # Create the file so it exists
        (project / "bad.txt").write_text("should be skipped")

        fake_config = MagicMock(provider="p", model="m")
        monkeypatch.setattr(cli, "load_ai_config", lambda path: fake_config)

        mock_workflow_cls = MagicMock()
        mock_instance = mock_workflow_cls.return_value
        mock_instance.run.return_value = _make_fake_result()
        monkeypatch.setattr(cli, "DevelopmentWorkflow", mock_workflow_cls)
        monkeypatch.setattr(cli, "build_workflow", lambda config: mock_instance)

        monkeypatch.setattr(sys, "argv", ["workflow_cli.py", str(project)])

        with pytest.raises(SystemExit):
            cli.main()

        captured = capsys.readouterr()
        assert "Skipping binary/unreadable file" in captured.err
        call_args = mock_instance.run.call_args
        files = call_args.kwargs["project_info"]["files"]
        paths = {f["path"] for f in files}
        assert "good.txt" in paths
        assert "bad.txt" not in paths


class TestNoSideEffects:
    def test_no_approval_or_execution(self, tmp_path, monkeypatch):
        """The CLI must not trigger approval, execution, or installation."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "f.py").write_text("pass")

        fake_config = MagicMock(provider="p", model="m")
        monkeypatch.setattr(cli, "load_ai_config", lambda path: fake_config)

        mock_workflow_cls = MagicMock()
        mock_instance = mock_workflow_cls.return_value
        mock_instance.run.return_value = _make_fake_result()
        monkeypatch.setattr(cli, "DevelopmentWorkflow", mock_workflow_cls)
        monkeypatch.setattr(cli, "build_workflow", lambda config: mock_instance)

        # Also ensure that no approval‑related classes are touched
        with patch("app.approval_manager.ApprovalManager") as mock_approval, patch(
            "app.setup_executor.SetupExecutor"
        ) as mock_executor:
            monkeypatch.setattr(sys, "argv", ["workflow_cli.py", str(project)])
            with pytest.raises(SystemExit):
                cli.main()

        # The workflow itself was called, but no approval/execution objects
        # should have been instantiated by the CLI.
        mock_approval.assert_not_called()
        mock_executor.assert_not_called()
