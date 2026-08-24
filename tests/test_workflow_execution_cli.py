from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.workflow_execution_cli as cli
from app.requirement_model import SetupPlan, SetupStep
from app.setup_executor import ExecutionResult


def _make_plan():
    step = SetupStep(
        id="step-1",
        requirement_id="req-1",
        action="install",
        install_method="python_package",
        package="example-package",
        version=None,
        command=None,
        verification_after="import example_package",
        is_approved=False,
    )

    return SetupPlan(
        id="plan-1",
        project_id="demo",
        steps=(step,),
        requires_user_approval=True,
        rollback_steps=(),
        warnings=(),
        status="pending_approval",
    )


def test_run_approved_execution_approves_plan_and_executes(tmp_path):
    project = tmp_path / "demo"
    project.mkdir()
    (project / "README.md").write_text("# demo")

    workflow = MagicMock()
    workflow.run.return_value = SimpleNamespace(
        setup_plan=_make_plan(),
    )

    execution_result = ExecutionResult(
        step_id="step-1",
        success=True,
        message="ok",
        verification_passed=True,
    )
    workflow.execute_approved.return_value = (execution_result,)

    results, approved_plan, warnings = cli.run_approved_execution(
        project,
        workflow=workflow,
    )

    assert warnings == []
    assert approved_plan.status == "approved"
    assert approved_plan.steps[0].is_approved is True
    assert results == (execution_result,)

    workflow.run.assert_called_once()
    workflow.execute_approved.assert_called_once()

    called_plan = workflow.execute_approved.call_args.args[0]
    assert called_plan.status == "approved"
    assert called_plan.steps[0].is_approved is True


def test_main_requires_explicit_approval(monkeypatch, capsys, tmp_path):
    project = tmp_path / "demo"
    project.mkdir()

    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["workflow_execution_cli.py", str(project)],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 2
    assert "--approve" in capsys.readouterr().err


def test_main_with_approval_uses_workflow(monkeypatch, capsys, tmp_path):
    project = tmp_path / "demo"
    project.mkdir()

    config = SimpleNamespace(
        provider="test-provider",
        model="test-model",
    )
    monkeypatch.setattr(
        cli,
        "load_ai_config",
        lambda path: config,
    )

    execution_result = ExecutionResult(
        step_id="step-1",
        success=True,
        message="ok",
        verification_passed=True,
    )

    approved_plan = _make_plan()

    workflow = MagicMock()
    workflow.run.return_value = SimpleNamespace(
        setup_plan=approved_plan,
    )
    workflow.execute_approved.return_value = (execution_result,)

    monkeypatch.setattr(
        cli,
        "build_workflow",
        lambda config: workflow,
    )
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "workflow_execution_cli.py",
            "--approve",
            str(project),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "SetupPlan status: approved" in output
    assert "Execution results: 1" in output
    workflow.run.assert_called_once()
    workflow.execute_approved.assert_called_once()

def test_main_returns_error_when_execution_fails(
    monkeypatch,
    capsys,
    tmp_path,
):
    project = tmp_path / "demo"
    project.mkdir()

    config = SimpleNamespace(
        provider="test-provider",
        model="test-model",
    )
    monkeypatch.setattr(
        cli,
        "load_ai_config",
        lambda path: config,
    )

    workflow = MagicMock()
    workflow.run.return_value = SimpleNamespace(
        setup_plan=_make_plan(),
    )
    workflow.execute_approved.side_effect = RuntimeError(
        "execution failed"
    )

    monkeypatch.setattr(
        cli,
        "build_workflow",
        lambda config: workflow,
    )
    monkeypatch.setattr(
        cli.sys,
        "argv",
        [
            "workflow_execution_cli.py",
            "--approve",
            str(project),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 1
    assert capsys.readouterr().err.strip() == "Workflow execution failed."

