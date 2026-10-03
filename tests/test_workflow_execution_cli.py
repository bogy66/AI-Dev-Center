import sys
from unittest.mock import MagicMock

import pytest

import app.workflow_cli as cli
from app.requirement_model import SetupPlan, SetupStep


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
    """Return a WorkflowResult-like object with a real SetupPlan."""
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
        steps=steps,
        requires_user_approval=True,
        rollback_steps=(),
        warnings=(),
        status=plan_status,
    )
    return result


class TestValidProject:
    def test_successful_run(self, tmp_path, monkeypatch, capsys):
        project = tmp_path / "myproj"
        project.mkdir()
        (project / "main.py").write_text("print('hello')")
        (project / "readme.md").write_text("# Project")

        mock_workflow_cls = MagicMock()
        mock_instance = mock_workflow_cls.return_value
        fake_result = _make_fake_result()
        mock_instance.run.return_value = fake_result

        monkeypatch.setattr(cli, "DevelopmentWorkflow", mock_workflow_cls)
        monkeypatch.setattr(
            cli,
            "build_workflow",
            lambda config: mock_instance,
        )

        fake_config = MagicMock(
            provider="test-provider",
            model="test-model",
        )
        monkeypatch.setattr(
            cli,
            "load_ai_config",
            lambda path: fake_config,
        )

        store = MagicMock()
        monkeypatch.setattr(
            cli,
            "WorkflowPlanStore",
            lambda root: store,
        )

        monkeypatch.setattr(
            sys,
            "argv",
            ["workflow_cli.py", str(project)],
        )

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

        assert exc_info.value.code == 0

        out = capsys.readouterr().out

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
        assert "SetupPlan ID: plan-test-1" in out
        assert "SetupPlan status: pending_approval" in out
        assert "Number of SetupSteps: 1" in out
        assert "requirement_id: req-1" in out
        assert "action: install" in out
        assert "package: some-pkg" in out
        assert "version: 1.2.3" in out
        assert "is_approved: False" in out

        assert "secret" not in out.lower()
        assert "api_key" not in out.lower()

        mock_instance.run.assert_called_once()
        store.save.assert_called_once_with(fake_result.setup_plan)

        project_info_arg = mock_instance.run.call_args.kwargs[
            "project_info"
        ]
        paths = {
            item["path"] for item in project_info_arg["files"]
        }
        assert "main.py" in paths
        assert "readme.md" in paths

    def test_non_existent_path(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys,
            "argv",
            ["workflow_cli.py", "/no/such/dir"],
        )

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

        assert exc_info.value.code == 1
        assert "does not exist" in capsys.readouterr().err

    def test_config_load_failure(self, tmp_path, monkeypatch, capsys):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "dummy.txt").write_text("hello")

        monkeypatch.setattr(
            sys,
            "argv",
            ["workflow_cli.py", str(project)],
        )
        monkeypatch.setattr(
            cli,
            "load_ai_config",
            lambda path: (_ for _ in ()).throw(
                Exception("boom")
            ),
        )

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

        assert exc_info.value.code == 1
        assert "Error loading AI config" in capsys.readouterr().err

    def test_workflow_exception(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "dummy.txt").write_text("hello")

        fake_config = MagicMock(
            provider="p",
            model="m",
        )
        monkeypatch.setattr(
            cli,
            "load_ai_config",
            lambda path: fake_config,
        )

        workflow = MagicMock()
        workflow.run.side_effect = RuntimeError("boom")

        monkeypatch.setattr(
            cli,
            "build_workflow",
            lambda config: workflow,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["workflow_cli.py", str(project)],
        )

        with pytest.raises(SystemExit) as exc_info:
            cli.main()

        assert exc_info.value.code == 1
        assert "Workflow failed: boom" in capsys.readouterr().err


class TestFileReading:
    def _setup_workflow(self, monkeypatch):
        fake_config = MagicMock(
            provider="p",
            model="m",
        )
        monkeypatch.setattr(
            cli,
            "load_ai_config",
            lambda path: fake_config,
        )

        mock_workflow_cls = MagicMock()
        mock_instance = mock_workflow_cls.return_value
        mock_instance.run.return_value = _make_fake_result()

        monkeypatch.setattr(
            cli,
            "DevelopmentWorkflow",
            mock_workflow_cls,
        )
        monkeypatch.setattr(
            cli,
            "build_workflow",
            lambda config: mock_instance,
        )

        store = MagicMock()
        monkeypatch.setattr(
            cli,
            "WorkflowPlanStore",
            lambda root: store,
        )

        return mock_instance, store

    def test_binary_file_skipped(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "good.py").write_text("print(1)")
        (project / "data.bin").write_bytes(
            b"\x00\x01\x02\xff"
        )

        mock_instance, store = self._setup_workflow(monkeypatch)

        monkeypatch.setattr(
            sys,
            "argv",
            ["workflow_cli.py", str(project)],
        )

        with pytest.raises(SystemExit):
            cli.main()

        assert (
            "Skipping binary/unreadable file"
            in capsys.readouterr().err
        )

        project_info = mock_instance.run.call_args.kwargs[
            "project_info"
        ]
        paths = {
            item["path"]
            for item in project_info["files"]
        }

        assert "data.bin" not in paths
        assert "good.py" in paths
        store.save.assert_called_once()

    def test_large_file_skipped(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "small.txt").write_text("ok")

        (project / "big.log").write_bytes(
            b"x" * (cli.MAX_FILE_SIZE + 1)
        )

        mock_instance, store = self._setup_workflow(monkeypatch)

        monkeypatch.setattr(
            sys,
            "argv",
            ["workflow_cli.py", str(project)],
        )

        with pytest.raises(SystemExit):
            cli.main()

        assert "Skipping large file" in capsys.readouterr().err

        project_info = mock_instance.run.call_args.kwargs[
            "project_info"
        ]
        paths = {
            item["path"] for item in project_info["files"]
        }

        assert "big.log" not in paths
        assert "small.txt" in paths
        store.save.assert_called_once()

    def test_unreadable_file_skipped(
        self,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "good.txt").write_text("hello")

        original_read_text = cli.Path.read_text

        def _read_text(self, *args, **kwargs):
            if self.name == "bad.txt":
                raise OSError("permission denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(
            cli.Path,
            "read_text",
            _read_text,
        )

        (project / "bad.txt").write_text(
            "should be skipped"
        )

        mock_instance, store = self._setup_workflow(monkeypatch)

        monkeypatch.setattr(
            sys,
            "argv",
            ["workflow_cli.py", str(project)],
        )

        with pytest.raises(SystemExit):
            cli.main()

        assert (
            "Skipping binary/unreadable file"
            in capsys.readouterr().err
        )

        project_info = mock_instance.run.call_args.kwargs[
            "project_info"
        ]
        paths = {
            item["path"] for item in project_info["files"]
        }

        assert "bad.txt" not in paths
        assert "good.txt" in paths
        store.save.assert_called_once()


class TestNoSideEffects:
    def test_no_approval_or_execution(
        self,
        tmp_path,
        monkeypatch,
    ):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "f.py").write_text("pass")

        fake_config = MagicMock(
            provider="p",
            model="m",
        )
        monkeypatch.setattr(
            cli,
            "load_ai_config",
            lambda path: fake_config,
        )

        mock_workflow_cls = MagicMock()
        mock_instance = mock_workflow_cls.return_value
        mock_instance.run.return_value = _make_fake_result()

        monkeypatch.setattr(
            cli,
            "DevelopmentWorkflow",
            mock_workflow_cls,
        )
        monkeypatch.setattr(
            cli,
            "build_workflow",
            lambda config: mock_instance,
        )

        store = MagicMock()
        monkeypatch.setattr(
            cli,
            "WorkflowPlanStore",
            lambda root: store,
        )

        monkeypatch.setattr(
            sys,
            "argv",
            ["workflow_cli.py", str(project)],
        )

        with pytest.raises(SystemExit):
            cli.main()

        mock_instance.run.assert_called_once()
        store.save.assert_called_once()

        if hasattr(mock_instance, "approve"):
            mock_instance.approve.assert_not_called()

        if hasattr(mock_instance, "execute_approved"):
            mock_instance.execute_approved.assert_not_called()
