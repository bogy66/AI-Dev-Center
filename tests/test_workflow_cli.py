import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import app.workflow_cli as cli


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
        steps = [
            MagicMock(
                requirement_id="req-1",
                action="install",
                package="some-pkg",
                version="1.2.3",
                is_approved=False,
            )
        ]

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
    result.setup_plan = MagicMock(status=plan_status, steps=steps)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
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
