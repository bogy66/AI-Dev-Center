import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import SetupPlan, SetupStep
from app.setup_approval import SetupApproval
from app.workflow_plan_store import WorkflowPlanStore


def _build_plan() -> SetupPlan:
    step = SetupStep(
        id="step-build-live",
        requirement_id="req-build-live",
        action="install",
        install_method="pip install build",
        package="build",
        version=None,
        command=None,
        verification_after="python -m build --version",
        is_approved=False,
    )

    return SetupPlan(
        id="plan-build-live",
        project_id="workflow-demo-live",
        steps=(step,),
        requires_user_approval=True,
        rollback_steps=(),
        warnings=(),
        status="pending_approval",
    )


def test_real_build_execution_in_isolated_venv(tmp_path):
    if importlib.util.find_spec("venv") is None:
        pytest.skip("venv module unavailable")

    demo_venv = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", str(demo_venv)],
        check=True,
    )

    python_bin = demo_venv / "bin" / "python"
    assert python_bin.is_file()

    before = subprocess.run(
        [
            str(python_bin),
            "-c",
            "import importlib.util; "
            "print(importlib.util.find_spec('build') is not None)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert before.stdout.strip() == "False"

    original_cwd = Path.cwd()
    store_root = tmp_path / ".workflow-plans"
    store = WorkflowPlanStore(store_root)

    try:
        plan = _build_plan()
        saved_path = store.save(plan)

        assert saved_path.is_file()

        loaded = store.load(
            plan.project_id,
            plan.id,
        )

        assert loaded == plan
        assert loaded.status == "pending_approval"
        assert loaded.steps[0].is_approved is False

        approved = SetupApproval.approve(loaded)

        assert approved.status == "approved"
        assert approved.steps[0].is_approved is True
        assert loaded.status == "pending_approval"

        # PythonPackageExecutor arbeitet mit dem aktuellen Interpreter.
        # Deshalb wird der isolierte venv-Python vorne in PATH gesetzt.
        import os

        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = (
            f"{python_bin.parent}:{old_path}"
        )

        executor = PythonPackageExecutor()

        # Der Executor ruft pip über den aktiven Python-Interpreter auf.
        result = executor.execute(approved.steps[0])

        assert result.success is True
        assert result.verification_passed is True
        assert result.step_id == "step-build-live"

        after = subprocess.run(
            [
                str(python_bin),
                "-c",
                "import importlib.util; "
                "print(importlib.util.find_spec('build') is not None)",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        assert after.stdout.strip() == "True"

    finally:
        # Sicherheitshalber kein persistenter Plan im Repository.
        if store_root.exists():
            import shutil

            shutil.rmtree(store_root)

        # PATH des Prozesses wiederherstellen.
        if "old_path" in locals():
            os.environ["PATH"] = old_path

        os.chdir(original_cwd)
