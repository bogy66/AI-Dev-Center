"""CLAUDE-004 / CLAUDE-004A execution-consolidation proof tests.

These prove that productive package installation and project-test
execution now actually route through app.execution.execute_controlled
(cwd confinement + environment allowlist + capability validation) when
a project_root is available, while preserving:
  - the exact prior direct-call shape for callers/tests that inject
    their own runner or omit project_root (backward compatibility);
  - real command/cwd/exit-code/stdout/stderr behavior end to end.

No external package is installed by these tests: "install" is proven
using a real, local, disposable Python package built in tmp_path and
installed with `pip install <path>`, matching the isolated-probe-package
pattern already used by this suite's real-system tests, without
requiring network access or --real-system-e2e.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.execution import CONTROLLED_SETUP_EFFECTS, DEFAULT_CAPABILITY_REGISTRY
from app.python_package_executor import PythonPackageExecutor
from app.project_test_runner import ProjectTestRunner, TestExecutionRequest
from app.requirement_model import SetupEffect, SetupStep


# ---------------------------------------------------------------------------
# Central routing: package installation
# ---------------------------------------------------------------------------
def _local_probe_package(tmp_path: Path, name: str = "adc_probe_pkg") -> Path:
    """Build a tiny, disposable, local (no-network) installable package."""
    pkg_dir = tmp_path / "probe_src"
    pkg_dir.mkdir()
    (pkg_dir / name).mkdir()
    (pkg_dir / name / "__init__.py").write_text("VALUE = 1\n")
    (pkg_dir / "pyproject.toml").write_text(textwrap.dedent(f"""
        [build-system]
        requires = ["setuptools>=61.0"]
        build-backend = "setuptools.build_meta"

        [project]
        name = "{name}"
        version = "0.0.1"
    """))
    return pkg_dir


def test_install_with_project_root_routes_through_execute_controlled_and_confines_cwd(tmp_path, monkeypatch):
    """A cwd that escapes project_root must be rejected by the central boundary."""
    executor = PythonPackageExecutor()
    project_root = tmp_path / "project"
    project_root.mkdir()

    calls = []
    import app.execution as execution_module
    real_run = subprocess.run

    def spy_run(args, **kwargs):
        calls.append(kwargs.get("cwd"))
        return real_run(args, **kwargs)

    monkeypatch.setattr(execution_module.subprocess, "run", spy_run)

    step = SetupStep(
        id="s1", requirement_id="r1", action="install",
        install_method="pip", package="this-package-should-not-need-to-exist",
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, is_approved=True,
    )
    result = executor.execute(step, str(project_root))

    # execute_controlled was genuinely invoked: the underlying subprocess.run
    # call it makes was confined to project_root, not the test's own cwd or
    # the ADC repository root.
    assert calls, "execute_controlled's subprocess.run was never invoked"
    assert calls[0] == str(project_root.resolve())
    # a nonexistent/invalid package version still yields a clean failure
    # result rather than a crash, proving exit-code propagation.
    assert result.success is False


def test_install_environment_is_allowlisted_not_fully_inherited(tmp_path, monkeypatch):
    """A secret-like env var on the ADC process must not reach the install subprocess."""
    monkeypatch.setenv("ADC_TEST_SECRET_TOKEN", "should-not-leak")
    project_root = tmp_path / "project"
    project_root.mkdir()

    captured_env = {}
    import app.execution as execution_module
    real_run = subprocess.run

    def spy_run(args, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        return real_run(args, **kwargs)

    monkeypatch.setattr(execution_module.subprocess, "run", spy_run)

    executor = PythonPackageExecutor()
    step = SetupStep(
        id="s1", requirement_id="r1", action="install",
        install_method="pip", package="nonexistent-package-xyz",
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, is_approved=True,
    )
    executor.execute(step, str(project_root))

    assert "ADC_TEST_SECRET_TOKEN" not in captured_env
    assert "PATH" in captured_env  # the allowlist still preserves what pip needs


def test_install_without_project_root_preserves_prior_unconfined_behavior():
    """Omitting project_root (e.g. the current MCP call shape) must not change."""
    calls = []

    class RecordingRunner:
        def run(self, args):
            calls.append(args)
            from app.python_package_executor import CommandResult
            return CommandResult(returncode=0, stdout="", stderr="")

    executor = PythonPackageExecutor(runner=RecordingRunner())
    step = SetupStep(
        id="s1", requirement_id="r1", action="install",
        install_method="pip", package="whatever",
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, is_approved=True,
    )
    executor.execute(step)  # no project_root supplied

    assert len(calls) == 1  # went straight to the injected runner, unchanged


def test_install_operation_type_is_permitted_for_the_python_capability():
    """The central boundary must recognize package installation explicitly."""
    registration = DEFAULT_CAPABILITY_REGISTRY.get("python")
    assert "install" in registration.allowed_operations
    assert SetupEffect.PYTHON_PACKAGE_INSTALL in CONTROLLED_SETUP_EFFECTS


@pytest.mark.real_system
@pytest.mark.skipif(
    subprocess.run(
        [sys.executable, "-m", "pip", "--version"], capture_output=True,
    ).returncode != 0,
    reason="pip is not available in this environment",
)
def test_real_local_package_install_and_uninstall_via_central_boundary(tmp_path):
    """End-to-end proof using a real, local, disposable package (no network).

    Installs into the current interpreter's user site via the central
    execute_controlled path, verifies presence, then uninstalls directly
    (uninstall is not part of PythonPackageExecutor's current productive
    contract - see report section 8) and verifies absence again, leaving
    no trace behind.
    """
    pkg_name = "adc_probe_pkg_consolidation_test"
    pkg_dir = _local_probe_package(tmp_path, pkg_name)
    project_root = tmp_path / "project"
    project_root.mkdir()

    executor = PythonPackageExecutor()
    step = SetupStep(
        id="s1", requirement_id="r1", action="install",
        install_method="pip", package=str(pkg_dir),
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, is_approved=True,
    )
    # PythonPackageExecutor validates package names structurally, so a
    # local path can't flow through step.package - install directly with
    # the same central primitive it uses, to prove the boundary itself
    # handles a real install/uninstall round trip correctly.
    from app.execution import ExecutionRequest, execute_controlled

    install_request = ExecutionRequest(
        (sys.executable, "-m", "pip", "install", str(pkg_dir)),
        str(project_root), 120, "python", "install",
    )
    try:
        result = execute_controlled(install_request, project_root)
        assert result is not None and result.returncode == 0, result.stderr if result else None

        check = subprocess.run(
            [sys.executable, "-c", f"import {pkg_name}; print({pkg_name}.VALUE)"],
            capture_output=True, text=True,
        )
        assert check.returncode == 0
        assert check.stdout.strip() == "1"
    finally:
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", pkg_name],
            capture_output=True, text=True,
        )

    check_after = subprocess.run(
        [sys.executable, "-c", f"import {pkg_name}"],
        capture_output=True, text=True,
    )
    assert check_after.returncode != 0  # module is gone


# ---------------------------------------------------------------------------
# Central routing: project test execution
# ---------------------------------------------------------------------------
def test_project_test_runner_default_routes_through_execute_controlled_success(tmp_path):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    runner = ProjectTestRunner()

    result = runner.run(TestExecutionRequest(tmp_path))

    assert result.passed is True
    assert result.return_code == 0
    assert result.command == (sys.executable, "-m", "pytest", "-q")


def test_project_test_runner_default_routes_through_execute_controlled_failure(tmp_path):
    (tmp_path / "test_fail.py").write_text("def test_fail():\n    assert False\n")
    runner = ProjectTestRunner()

    result = runner.run(TestExecutionRequest(tmp_path))

    assert result.passed is False
    assert result.return_code != 0


def test_project_test_runner_uses_exact_project_cwd(tmp_path):
    (tmp_path / "test_cwd.py").write_text(textwrap.dedent("""
        import os
        def test_cwd_is_project_root():
            assert os.getcwd() == r'%s'
    """ % str(tmp_path.resolve())))
    runner = ProjectTestRunner()

    result = runner.run(TestExecutionRequest(tmp_path))

    assert result.passed is True, result.stdout + result.stderr


def test_project_test_runner_default_still_confines_cwd_to_project_root(tmp_path, monkeypatch):
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    calls = []
    import app.execution as execution_module
    real_run = subprocess.run

    def spy_run(args, **kwargs):
        calls.append(kwargs.get("cwd"))
        return real_run(args, **kwargs)

    monkeypatch.setattr(execution_module.subprocess, "run", spy_run)

    ProjectTestRunner().run(TestExecutionRequest(tmp_path))

    assert calls == [str(tmp_path.resolve())]


def test_project_test_runner_injected_runner_still_bypasses_central_boundary(tmp_path):
    """The existing unit-test seam (tests/test_project_test_runner.py) must be unaffected."""
    from unittest.mock import Mock

    runner = Mock(return_value=Mock(returncode=0, stdout="ok", stderr=""))
    result = ProjectTestRunner(runner=runner).run(TestExecutionRequest(tmp_path))

    assert result.passed
    runner.assert_called_once()


# ---------------------------------------------------------------------------
# Lock consolidation
# ---------------------------------------------------------------------------
def test_workflow_execution_guard_module_no_longer_exists():
    """The dead, zero-importer duplicate lock authority has been removed."""
    with pytest.raises(ModuleNotFoundError):
        import app.workflow_execution_guard  # noqa: F401


def test_canonical_execution_is_the_sole_surviving_lock_authority():
    import app.web_api as web_api_module
    import app.project_setup_application as psa_module
    import app.workflow_manager as wm_module

    for module in (web_api_module, psa_module, wm_module):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "workflow_execution_guard" not in source


def test_canonical_execution_lock_identity_is_the_resolved_project_path(tmp_path):
    """Lock identity must be the stable filesystem path, never a display name."""
    from app.canonical_execution import project_key

    a = project_key(str(tmp_path))
    b = project_key(str(tmp_path) + "/")  # trailing slash, same real path
    assert a == b
    assert a == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# CLAUDE-004A: fail-closed default execution (no productive bypass)
# ---------------------------------------------------------------------------
def test_default_runner_without_project_root_fails_closed_not_direct_subprocess(monkeypatch):
    """A missing project_root must raise, never fall back to a direct subprocess."""
    from app.python_package_executor import MissingProjectRootError

    subprocess_started = []
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess_started.append((a, k)) or (_ for _ in ()).throw(
            AssertionError("a real subprocess must not be started")
        ),
    )

    executor = PythonPackageExecutor()  # default runner, no injection
    step = SetupStep(
        id="s1", requirement_id="r1", action="install",
        install_method="pip", package="whatever",
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, is_approved=True,
    )

    with pytest.raises(MissingProjectRootError):
        executor.execute(step)  # project_root omitted

    assert subprocess_started == []


def test_custom_runner_without_project_root_is_a_justified_exception(tmp_path):
    """An explicitly injected runner is a deliberate, non-default exception,
    clearly separate from the fail-closed productive default path."""
    calls = []

    class RecordingRunner:
        def run(self, args):
            calls.append(args)
            from app.python_package_executor import CommandResult
            return CommandResult(returncode=0, stdout="", stderr="")

    executor = PythonPackageExecutor(runner=RecordingRunner(), verifier=lambda step: True)
    step = SetupStep(
        id="s1", requirement_id="r1", action="install",
        install_method="pip", package="whatever",
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, is_approved=True,
    )

    result = executor.execute(step)  # no project_root, but a runner IS injected

    assert len(calls) == 1
    assert result.success is True


# ---------------------------------------------------------------------------
# CLAUDE-004A: MCP setup-plan execution reaches the central boundary
# ---------------------------------------------------------------------------
def test_mcp_plan_then_execute_round_trip_persists_and_resolves_project_root(tmp_path):
    """plan_project_setup validates+persists project_root; execute_setup_plan
    retrieves the same value later, proving the round trip through the
    existing, already-authoritative WorkflowPlanStore (no second registry)."""
    from unittest.mock import Mock
    from app.mcp_server import MCPServer
    from app.workflow_plan_store import WorkflowPlanStore
    from app.requirement_model import SetupPlan

    project_root = tmp_path / "mcp-project"
    project_root.mkdir()

    plan_store = WorkflowPlanStore(tmp_path / "plans")
    development_workflow = Mock()
    setup_plan = SetupPlan(id="plan-1", project_id="proj-mcp", steps=(), status="pending_approval")
    development_workflow.run.return_value = Mock(setup_plan=setup_plan)

    server = MCPServer(
        project_scanner=Mock(), discovery=Mock(), preflight=Mock(), planner=None,
        plan_store=plan_store, approval=Mock(),
        development_workflow=development_workflow,
    )

    server.plan_project_setup({}, "proj-mcp", str(project_root))

    assert plan_store.load_project_root("proj-mcp") == str(project_root.resolve())


def test_mcp_execute_setup_plan_routes_through_execute_controlled_with_correct_cwd(tmp_path, monkeypatch):
    """The exact CLAUDE-004 bypass: MCP execute_setup_plan -> execute_approved
    -> PythonPackageExecutor.execute -> execute_controlled, proven end to end
    with a real WorkflowPlanStore and a real DevelopmentWorkflow/executor."""
    from app.mcp_server import MCPServer
    from app.workflow_plan_store import WorkflowPlanStore
    from app.dev_workflow import DevelopmentWorkflow
    from app.requirement_model import SetupPlan
    from unittest.mock import Mock

    project_root = tmp_path / "mcp-project"
    project_root.mkdir()

    plan_store = WorkflowPlanStore(tmp_path / "plans")
    step = SetupStep(
        id="s1", requirement_id="r1", action="install",
        install_method="pip", package="nonexistent-mcp-probe-package",
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL, is_approved=True,
    )
    plan = SetupPlan(id="plan-1", project_id="proj-mcp", steps=(step,), status="approved")
    plan_store.save(plan)
    plan_store.save_project_root("proj-mcp", str(project_root))

    executor = PythonPackageExecutor()
    workflow = DevelopmentWorkflow(
        discovery=Mock(), validator=Mock(), preflight=Mock(), executor=executor,
    )
    server = MCPServer(
        project_scanner=Mock(), discovery=Mock(), preflight=Mock(), planner=None,
        plan_store=plan_store, approval=Mock(), development_workflow=workflow,
    )

    calls = []
    import app.execution as execution_module
    real_run = subprocess.run

    def spy_run(args, **kwargs):
        calls.append(kwargs.get("cwd"))
        return real_run(args, **kwargs)

    monkeypatch.setattr(execution_module.subprocess, "run", spy_run)

    server.execute_setup_plan("proj-mcp", "plan-1")

    assert calls, "execute_controlled's subprocess.run was never reached from the MCP path"
    assert calls[0] == str(project_root.resolve())


def test_mcp_execute_setup_plan_fails_closed_when_no_project_root_was_ever_associated(tmp_path):
    """A plan that somehow exists without an associated project_root (e.g.
    predating this fix, or store corruption) must refuse execution rather
    than silently falling back to unconfined direct execution."""
    from app.mcp_server import MCPServer
    from app.workflow_plan_store import WorkflowPlanStore
    from app.requirement_model import SetupPlan
    from app.setup_approval import SetupApprovalError
    from unittest.mock import Mock

    plan_store = WorkflowPlanStore(tmp_path / "plans")
    plan = SetupPlan(id="plan-1", project_id="proj-orphan", steps=(), status="approved")
    plan_store.save(plan)  # note: save_project_root() is never called

    server = MCPServer(
        project_scanner=Mock(), discovery=Mock(), preflight=Mock(), planner=None,
        plan_store=plan_store, approval=Mock(), development_workflow=Mock(),
    )

    with pytest.raises(SetupApprovalError):
        server.execute_setup_plan("proj-orphan", "plan-1")
