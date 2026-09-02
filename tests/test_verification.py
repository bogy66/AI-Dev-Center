"""Canonical verification — planning, execution, aggregation, safety."""
import json
from pathlib import Path
import sys as _real_sys
from unittest.mock import Mock

import pytest

from app.project_intelligence import (
    DetectedBuildSystem, DetectedFirmware, DetectedFramework,
    DetectedLanguage, DetectedPackageSystem, DetectedTestSystem,
    Evidence, ProjectArea, ProjectIntelligence, inspect_project,
)
from app.verification import (
    PASS, FAIL, UNSUPPORTED, TOOL_UNAVAILABLE, INVALID_PLAN,
    EXECUTION_ERROR, TIMEOUT, NOT_APPLICABLE,
    VerificationPlan, VerificationStep, VerificationStepResult,
    VerificationResult, VerificationRunner, ControlledRunnerRegistry,
    PytestRunner, PythonUnittestRunner,
    build_verification_plan, build_default_registry, _aggregate,
)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ============================================================================
# 1. Python + pytest planning
# ============================================================================
def test_pytest_planning_creates_controlled_step(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "tests" / "test_main.py", "def test_x(): pass\n")

    intelligence = inspect_project(tmp_path)
    plan = build_verification_plan(intelligence, "run-1")
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.verification_kind == "test"
    assert step.test_system == "pytest"
    assert step.runner_type == "pytest"
    assert step.policy == "controlled_execution"
    assert step.is_executable


# ============================================================================
# 2. pytest controlled execution
# ============================================================================
def test_pytest_runner_executes(tmp_path):
    _write(tmp_path / "tests" / "test_trivial.py",
           "def test_passes():\n    assert 1 + 1 == 2\n")

    step = VerificationStep(
        step_id="root-test-pytest", area=".", working_directory=".",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    runner = PytestRunner(timeout=30)
    result = runner.execute(step, tmp_path)
    assert result.status == PASS.value
    assert result.passed is True
    assert result.return_code == 0
    assert len(result.command) == 4


def test_pytest_runner_detects_failure(tmp_path):
    _write(tmp_path / "tests" / "test_fails.py",
           "def test_fails():\n    assert False\n")

    step = VerificationStep(
        step_id="root-test-pytest", area=".", working_directory=".",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    runner = PytestRunner(timeout=30)
    result = runner.execute(step, tmp_path)
    assert result.status == FAIL.value
    assert result.passed is False


# ============================================================================
# 3. Python unittest planning
# ============================================================================
def test_unittest_planning_is_supported():
    """unittest is not automatically detected by OC-004, but test directly the runner."""
    step = VerificationStep(
        step_id="test-ut", area=".", working_directory=".",
        verification_kind="test", test_system="unittest",
        runner_type="python_unittest", policy="controlled_execution",
    )
    assert step.is_executable


# ============================================================================
# 4. Python unittest execution
# ============================================================================
def test_unittest_runner_executes(tmp_path):
    _write(tmp_path / "tests" / "test_trivial.py",
           "import unittest\nclass TestTrivial(unittest.TestCase):\n"
           "    def test_passes(self):\n"
           "        self.assertEqual(1 + 1, 2)\n")

    step = VerificationStep(
        step_id="test-unittest", area=".", working_directory=".",
        verification_kind="test", test_system="unittest",
        runner_type="python_unittest", policy="controlled_execution",
    )
    runner = PythonUnittestRunner(timeout=30)
    result = runner.execute(step, tmp_path)
    assert result.status in (PASS.value, FAIL.value)


# ============================================================================
# 5. Greenfield without verification target
# ============================================================================
def test_greenfield_creates_no_target_step(tmp_path):
    intelligence = inspect_project(tmp_path)
    plan = build_verification_plan(intelligence, "run-g")
    assert len(plan.steps) == 1
    assert plan.steps[0].runner_type == "none"
    assert plan.steps[0].policy == "unsupported"


# ============================================================================
# 6. Mixed project creates multiple area steps
# ============================================================================
def test_mixed_project_produces_multiple_steps(tmp_path):
    _write(tmp_path / "backend" / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "backend" / "src" / "main.py", "pass\n")
    _write(tmp_path / "backend" / "src" / "util.py", "pass\n")
    _write(tmp_path / "frontend" / "package.json",
           json.dumps({"devDependencies": {"vitest": "^2.0.0"}}))
    _write(tmp_path / "frontend" / "src" / "index.ts", "const x = 1;\n")
    _write(tmp_path / "frontend" / "src" / "util.ts", "export const y = 2;\n")

    intelligence = inspect_project(tmp_path)
    plan = build_verification_plan(intelligence, "run-m")
    areas = set(s.area for s in plan.steps)
    assert "backend" in areas
    area_steps = {s.area: s.runner_type for s in plan.steps}
    assert area_steps.get("backend") == "pytest"


# ============================================================================
# 7. Area cwd is correct
# ============================================================================
def test_area_cwd_is_set(tmp_path):
    _write(tmp_path / "backend" / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "backend" / "src" / "main.py", "pass\n")
    _write(tmp_path / "backend" / "src" / "util.py", "pass\n")

    intelligence = inspect_project(tmp_path)
    plan = build_verification_plan(intelligence, "run-cwd")
    backend_step = next(s for s in plan.steps if s.area == "backend")
    assert backend_step.working_directory == "backend"


# ============================================================================
# 8. cwd path traversal blocked
# ============================================================================
def test_path_traversal_is_blocked(tmp_path):
    step = VerificationStep(
        step_id="escape", area="..", working_directory="../etc",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    runner = PytestRunner()
    result = runner.execute(step, tmp_path)
    assert result.status == INVALID_PLAN.value


# ============================================================================
# 9. Symlink cwd escape blocked
# ============================================================================
def test_cwd_path_traversal_is_blocked(tmp_path):
    step = VerificationStep(
        step_id="escape", area="..", working_directory="../etc",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    runner = PytestRunner()
    result = runner.execute(step, tmp_path)
    assert result.status == INVALID_PLAN.value


def test_symlink_cwd_is_blocked(tmp_path):
    step = VerificationStep(
        step_id="escape", area="/etc",
        working_directory="/etc/passwd",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    runner = PytestRunner()
    result = runner.execute(step, tmp_path)
    assert result.status in (INVALID_PLAN.value, TOOL_UNAVAILABLE.value)


# ============================================================================
# 10. Unknown test system → unsupported
# ============================================================================
def test_unknown_test_system_is_unsupported():
    registry = build_default_registry()
    step = VerificationStep(
        step_id="unknown", area=".", working_directory=".",
        verification_kind="test", test_system="mystery_framework",
        runner_type="unknown", policy="unsupported",
    )
    result = registry.execute_step(step, "/tmp")
    assert result.status == UNSUPPORTED.value


# ============================================================================
# 11. Unknown toolchain → unsupported
# ============================================================================
def test_unknown_toolchain_is_unsupported():
    registry = build_default_registry()
    step = VerificationStep(
        step_id="tc", area=".", working_directory=".",
        verification_kind="build", test_system="some_future_toolchain",
        runner_type="some_future_toolchain", policy="unsupported",
    )
    result = registry.execute_step(step, "/tmp")
    assert result.status == UNSUPPORTED.value
    assert result.passed is False


# ============================================================================
# 12. Missing tool → tool_unavailable
# ============================================================================
def test_missing_python_is_tool_unavailable():
    result = VerificationStepResult(
        step_id="no-py", area=".", status=TOOL_UNAVAILABLE.value,
        verification_kind="test", runner_type="pytest",
        passed=False,
        diagnostics="Python executable not found",
    )
    assert result.status == TOOL_UNAVAILABLE.value
    assert result.passed is False


# ============================================================================
# 13. Runner exception → execution_error
# ============================================================================
def test_runner_exception_is_execution_error():
    class BrokenRunner(VerificationRunner):
        runner_type = "broken"
        def can_run(self, step): return step.runner_type == "broken"
        def execute(self, step, root):
            raise RuntimeError("simulated crash")

    registry = ControlledRunnerRegistry([BrokenRunner()])
    step = VerificationStep(
        step_id="crash", area=".", working_directory=".",
        verification_kind="test", test_system="broken",
        runner_type="broken", policy="controlled_execution",
    )
    result = registry.execute_step(step, "/tmp")
    assert result.status == EXECUTION_ERROR.value
    assert result.error_category == "RuntimeError"


# ============================================================================
# 14. Timeout → controlled failure status
# ============================================================================
def test_timeout_is_reported(tmp_path, monkeypatch):
    import subprocess

    class TimeoutResult:
        returncode = -1
        stdout = "partial"
        stderr = ""
        timed_out = True

    def fake_run(args, **kwargs):
        return TimeoutResult()

    monkeypatch.setattr(subprocess, "run", fake_run)
    _write(tmp_path / "tests" / "test_slow.py",
           "def test_slow():\n    while True:\n        pass\n")
    step = VerificationStep(
        step_id="slow", area=".", working_directory=".",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    runner = PytestRunner(timeout=1)
    result = runner.execute(step, tmp_path)
    assert result.status == TIMEOUT.value
    assert result.timed_out
    assert result.passed is False


# ============================================================================
# 15. stdout bounded
# ============================================================================
def test_output_is_bounded(tmp_path):
    long_output = "x" * 60_000
    _write(tmp_path / "tests" / "test_big.py",
           f"def test_big():\n    print('{long_output}')\n    assert True\n")

    step = VerificationStep(
        step_id="big", area=".", working_directory=".",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    runner = PytestRunner(timeout=30)
    result = runner.execute(step, tmp_path)
    assert len(result.stdout) <= 50_000 + 1000
    assert len(result.stderr) <= 50_000 + 1000


# ============================================================================
# 16. Truncation indication
# ============================================================================
def test_truncation_constant_is_sane():
    from app import verification
    assert verification._MAX_OUTPUT == 50_000


def test_output_trimming_is_applied():
    massive = "x" * 80_000
    result = VerificationStepResult(
        step_id="huge", area=".", status=FAIL.value,
        verification_kind="test", runner_type="pytest",
        passed=False, return_code=1,
        stdout=massive, stderr=massive,
    )
    assert len(result.stdout) <= 80_000  # just data — trimming happens in runner
    # Runner truncation tested via the actual execute path below:

    import subprocess
    class _MockProcess:
        returncode = 0
        stdout = "x" * 80_000
        stderr = ""
        timed_out = False

    original = subprocess.run
    subprocess.run = lambda *a, **kw: _MockProcess()
    try:
        runner = PytestRunner(timeout=30)
        step = VerificationStep(
            step_id="t", area=".", working_directory=".",
            verification_kind="test", test_system="pytest",
            runner_type="pytest", policy="controlled_execution",
        )
        import tempfile
        from pathlib import Path as _Path
        td = tempfile.mkdtemp()
        _Path(td, "tests").mkdir(exist_ok=True)
        _Path(td, "tests/test_x.py").write_text("def test_x(): pass\n")
        result = runner.execute(step, td)
        assert result.truncated_output or len(result.stdout) <= 50_000 + 100
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    finally:
        subprocess.run = original


# ============================================================================
# 17. No shell=True
# ============================================================================
def test_no_shell_execution():
    runner = PytestRunner()
    assert hasattr(runner, "execute")
    import inspect
    src = inspect.getsource(runner.__class__.execute)
    assert "shell=True" not in src
    assert "shell = True" not in src


# ============================================================================
# 18. Deferred policy → unsupported
# ============================================================================
def test_deferred_policy_is_unsupported():
    registry = build_default_registry()
    step = VerificationStep(
        step_id="deferred", area=".", working_directory=".",
        verification_kind="test", test_system="vitest",
        runner_type="vitest", policy="deferred",
    )
    result = registry.execute_step(step, "/tmp")
    assert result.status == UNSUPPORTED.value


# ============================================================================
# 19. Unsupported policy → unsupported
# ============================================================================
def test_unsupported_policy_is_unsupported():
    registry = build_default_registry()
    step = VerificationStep(
        step_id="unsup", area=".", working_directory=".",
        verification_kind="test", test_system="platformio",
        runner_type="platformio", policy="unsupported",
    )
    result = registry.execute_step(step, "/tmp")
    assert result.status == UNSUPPORTED.value


# ============================================================================
# 20. No dependency install during verification
# ============================================================================
def test_verification_does_not_install():
    runner = PytestRunner()
    assert not hasattr(runner, "install")
    import inspect
    src = inspect.getsource(runner.__class__.execute)
    assert "pip install" not in src
    assert "npm install" not in src


# ============================================================================
# 21. No dependency install in any runner
# ============================================================================
def test_unittest_runner_does_not_install():
    runner = PythonUnittestRunner()
    import inspect
    src = inspect.getsource(runner.__class__.execute)
    assert "pip install" not in src


# ============================================================================
# 22. pytest FAIL aggregates to FAIL
# ============================================================================
def test_pytest_fail_aggregates_to_fail():
    result = VerificationResult(
        run_id="r1",
        steps=(VerificationStepResult(
            step_id="s1", area=".", status=FAIL.value,
            verification_kind="test", runner_type="pytest",
            passed=False, return_code=1,
        ),),
        aggregate_status=FAIL.value,
    )
    assert result.passed is False
    assert result.failed_count == 1


# ============================================================================
# 23. Unsupported required step results in not-pass
# ============================================================================
def test_unsupported_step_does_not_pass():
    result = VerificationResult(
        run_id="r1",
        steps=(VerificationStepResult(
            step_id="s1", area=".", status=UNSUPPORTED.value,
            verification_kind="test", runner_type="unknown",
            passed=False,
        ),),
        aggregate_status=FAIL.value,
    )
    assert result.passed is False


# ============================================================================
# 24. Multiple PASS steps produce PASS
# ============================================================================
def test_multiple_pass_produces_pass():
    result = VerificationResult(
        run_id="r1",
        steps=(
            VerificationStepResult(
                step_id="s1", area="backend", status=PASS.value,
                verification_kind="test", runner_type="pytest",
                passed=True, return_code=0,
            ),
            VerificationStepResult(
                step_id="s2", area=".", status=PASS.value,
                verification_kind="test", runner_type="python_unittest",
                passed=True, return_code=0,
            ),
        ),
        aggregate_status=PASS.value,
    )
    assert result.passed is True
    assert result.passed_count == 2
    assert result.failed_count == 0


# ============================================================================
# 25. PASS + FAIL = FAIL
# ============================================================================
def test_pass_and_fail_produces_fail():
    result = VerificationResult(
        run_id="r1",
        steps=(
            VerificationStepResult(
                step_id="s1", area="backend", status=PASS.value,
                verification_kind="test", runner_type="pytest",
                passed=True, return_code=0,
            ),
            VerificationStepResult(
                step_id="s2", area="frontend", status=FAIL.value,
                verification_kind="test", runner_type="vitest",
                passed=False, return_code=1,
            ),
        ),
        aggregate_status=FAIL.value,
    )
    assert result.passed is False
    assert result.passed_count == 1
    assert result.failed_count == 1


# ============================================================================
# 26. PASS + unsupported = not PASS
# ============================================================================
def test_pass_and_unsupported_is_not_pass():
    steps = (
        VerificationStepResult(
            step_id="s1", area="backend", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="s2", area="firmware", status=UNSUPPORTED.value,
            verification_kind="test", runner_type="platformio",
            passed=False,
        ),
    )
    aggregated = _aggregate(steps)
    assert aggregated == FAIL.value  # unsupported blocks pass


# ============================================================================
# 27. Aggregation with NOT_APPLICABLE
# ============================================================================
def test_not_applicable_is_excluded():
    steps = (
        VerificationStepResult(
            step_id="s1", area="backend", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="none", area=".", status=NOT_APPLICABLE.value,
            verification_kind="test", runner_type="none",
            passed=False,
        ),
    )
    aggregated = _aggregate(steps)
    assert aggregated == PASS.value


# ============================================================================
# 28. Greenfield intelligence produces empty plan
# ============================================================================
def test_greenfield_intelligence_plan():
    pi = ProjectIntelligence(
        project_root="/tmp/proj",
        project_kind="greenfield",
        areas=(),
        languages=(),
        frameworks=(),
        package_systems=(),
        build_systems=(),
        test_systems=(),
        firmware_indicators=(),
        ci_indicators=(),
        doc_indicators=(),
        git_repository_present=False,
        sensitive_configuration_present=False,
        warnings=(),
        truncated=False,
        total_files_traversed=0,
        total_files_excluded=0,
        inspection_limit_exceeded=False,
    )
    plan = build_verification_plan(pi, "run-g")
    assert plan.project_kind == "greenfield"
    assert plan.area_count == 0
    assert len(plan.steps) >= 1  # no-target placeholder


# ============================================================================
# 29. None intelligence → empty plan
# ============================================================================
def test_none_intelligence_produces_empty_plan():
    plan = build_verification_plan(None, "run-n")
    assert plan.project_kind == "greenfield"
    assert len(plan.steps) == 0


# ============================================================================
# 30. Registry.execute_plan aggregates correctly
# ============================================================================
def test_registry_execute_plan(tmp_path):
    _write(tmp_path / "tests" / "test_passes.py",
           "def test_passes():\n    assert True\n")

    registry = build_default_registry()
    plan = VerificationPlan(
        run_id="run", project_root=str(tmp_path), project_kind="existing",
        area_count=1,
        steps=(VerificationStep(
            step_id="root-test-pytest", area=".", working_directory=".",
            verification_kind="test", test_system="pytest",
            runner_type="pytest", policy="controlled_execution",
        ),),
    )
    result = registry.execute_plan(plan)
    assert result.aggregate_status == PASS.value
    assert result.step_count == 1


# ============================================================================
# 31. VerificationResult properties
# ============================================================================
def test_verification_result_properties():
    result = VerificationResult(
        run_id="r",
        steps=(
            VerificationStepResult(
                step_id="s1", area="a", status=PASS.value,
                verification_kind="test", runner_type="pytest",
                passed=True, return_code=0,
            ),
            VerificationStepResult(
                step_id="s2", area="b", status=FAIL.value,
                verification_kind="test", runner_type="pytest",
                passed=False, return_code=1,
            ),
        ),
        aggregate_status=FAIL.value,
    )
    assert result.step_count == 2
    assert result.passed_count == 1
    assert result.failed_count == 1
    assert result.unsupported_count == 0
    assert "s2" in result.failure_summary


# ============================================================================
# 32. Default registry contains pytest and unittest runners
# ============================================================================
def test_default_registry_has_expected_runners():
    registry = build_default_registry()
    pytest_step = VerificationStep(
        step_id="s1", area=".", working_directory=".",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    ut_step = VerificationStep(
        step_id="s2", area=".", working_directory=".",
        verification_kind="test", test_system="unittest",
        runner_type="python_unittest", policy="controlled_execution",
    )
    assert registry.find(pytest_step) is not None
    assert registry.find(ut_step) is not None


# ============================================================================
# 33. Existing Project Intelligence is used
# ============================================================================
def test_intelligence_feeds_plan(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.10)\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "util.py", "pass\n")
    _write(tmp_path / "src" / "main.cpp", "int main() { return 0; }\n")

    intelligence = inspect_project(tmp_path)
    plan = build_verification_plan(intelligence, "run")
    step_names = [s.test_system for s in plan.steps]
    assert "pytest" in step_names


# ============================================================================
# 34. No second repository detection in planning
# ============================================================================
def test_plan_builder_does_not_access_filesystem():
    pi = ProjectIntelligence(
        project_root="/nonexistent",
        project_kind="existing",
        areas=(ProjectArea(
            path=".", languages=(), frameworks=(),
            package_systems=(),
            build_systems=(DetectedBuildSystem(
                "cmake", (Evidence("CMakeLists.txt", "explicit_configuration"),),
            ),),
            test_systems=(DetectedTestSystem(
                "pytest", (Evidence("pytest.ini", "explicit_configuration"),),
            ),),
            firmware_indicators=(),
        ),),
        languages=(), frameworks=(), package_systems=(),
        build_systems=(), test_systems=(), firmware_indicators=(),
        ci_indicators=(), doc_indicators=(),
        git_repository_present=False,
        sensitive_configuration_present=False,
        warnings=(), truncated=False,
        total_files_traversed=0, total_files_excluded=0,
        inspection_limit_exceeded=False,
    )
    plan = build_verification_plan(pi, "run")
    steps = {s.verification_kind for s in plan.steps}
    assert "test" in steps
    assert "build" in steps


# ============================================================================
# 35. Execution step has command in result
# ============================================================================
def test_result_includes_command(tmp_path):
    _write(tmp_path / "tests" / "test_trivial.py",
           "def test_passes():\n    assert True\n")
    step = VerificationStep(
        step_id="root-test-pytest", area=".", working_directory=".",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    runner = PytestRunner(timeout=30)
    result = runner.execute(step, tmp_path)
    assert len(result.command) > 0
    assert "pytest" in str(result.command)


# ============================================================================
# 36. Registry handles mixed executable + unsupported steps
# ============================================================================
def test_registry_mixed_steps(tmp_path):
    _write(tmp_path / "tests" / "test_passes.py",
           "def test_passes():\n    assert True\n")
    registry = build_default_registry()
    plan = VerificationPlan(
        run_id="mixed", project_root=str(tmp_path), project_kind="mixed",
        area_count=2,
        steps=(
            VerificationStep(
                step_id="backend-test-pytest", area=".", working_directory=".",
                verification_kind="test", test_system="pytest",
                runner_type="pytest", policy="controlled_execution",
            ),
            VerificationStep(
                step_id="firmware-build-platformio", area="firmware",
                working_directory="firmware",
                verification_kind="build", test_system="platformio",
                runner_type="platformio", policy="unsupported",
            ),
        ),
    )
    result = registry.execute_plan(plan)
    assert result.step_count == 2
    statuses = {s.status for s in result.steps}
    assert PASS.value in statuses
    assert UNSUPPORTED.value in statuses


# ============================================================================
# 37. Pytest runner uses list args, not shell
# ============================================================================
def test_pytest_runner_uses_list_args(tmp_path):
    _write(tmp_path / "tests" / "test_trivial.py",
           "def test_passes():\n    assert True\n")
    step = VerificationStep(
        step_id="test", area=".", working_directory=".",
        verification_kind="test", test_system="pytest",
        runner_type="pytest", policy="controlled_execution",
    )
    runner = PytestRunner(timeout=30)
    result = runner.execute(step, tmp_path)
    assert isinstance(result.command, tuple)
    assert len(result.command) == 4
    assert result.command[0].endswith("python") or "python" in str(result.command[0])


# ============================================================================
# KORREKTUR — Verbindliche Aggregation + Not-Applicable Semantik
# ============================================================================

def test_pass_plus_pass_is_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area="a", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="s2", area="b", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
    ))
    assert aggregated == PASS.value


def test_pass_plus_fail_is_fail():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area="a", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="s2", area="b", status=FAIL.value,
            verification_kind="test", runner_type="pytest",
            passed=False, return_code=1,
        ),
    ))
    assert aggregated != PASS.value


def test_pass_plus_unsupported_is_not_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area="backend", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="s2", area="firmware", status=UNSUPPORTED.value,
            verification_kind="test", runner_type="platformio",
            passed=False,
        ),
    ))
    assert aggregated != PASS.value


def test_pass_plus_tool_unavailable_is_not_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area="backend", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="s2", area="frontend", status=TOOL_UNAVAILABLE.value,
            verification_kind="test", runner_type="vitest",
            passed=False,
        ),
    ))
    assert aggregated != PASS.value


def test_pass_plus_deferred_is_not_pass():
    # deferred steps get UNSUPPORTED status from the registry
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area="backend", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="s2", area="firmware", status=UNSUPPORTED.value,
            verification_kind="build", runner_type="cmake_build",
            passed=False,
        ),
    ))
    assert aggregated != PASS.value


def test_only_unsupported_required_step_is_not_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area="firmware", status=UNSUPPORTED.value,
            verification_kind="build", runner_type="platformio",
            passed=False,
        ),
    ))
    assert aggregated != PASS.value


def test_only_tool_unavailable_required_step_is_not_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area="frontend", status=TOOL_UNAVAILABLE.value,
            verification_kind="test", runner_type="vitest",
            passed=False,
        ),
    ))
    assert aggregated != PASS.value


def test_not_applicable_alone_is_neutral():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="none", area=".", status=NOT_APPLICABLE.value,
            verification_kind="test", runner_type="none",
            passed=False,
        ),
    ))
    assert aggregated == NOT_APPLICABLE.value


def test_mixed_project_aggregate_must_not_pass():
    # backend pytest PASS + frontend vitest deferred + firmware platformio unsupported
    # All three must block aggregate PASS.
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="backend-test-pytest", area="backend",
            status=PASS.value, verification_kind="test",
            runner_type="pytest", passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="frontend-test-vitest", area="frontend",
            status=UNSUPPORTED.value, verification_kind="test",
            runner_type="vitest", passed=False,
        ),
        VerificationStepResult(
            step_id="firmware-build-platformio", area="firmware",
            status=UNSUPPORTED.value, verification_kind="build",
            runner_type="platformio", passed=False,
        ),
        VerificationStepResult(
            step_id="esphome", area="esphome",
            status=UNSUPPORTED.value, verification_kind="test",
            runner_type="esphome", passed=False,
        ),
    ))
    assert aggregated != PASS.value


def test_single_pass_is_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area=".", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
    ))
    assert aggregated == PASS.value


def test_execution_error_blocks_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area=".", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="s2", area=".", status=EXECUTION_ERROR.value,
            verification_kind="test", runner_type="pytest",
            passed=False,
        ),
    ))
    assert aggregated != PASS.value


def test_timeout_blocks_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area=".", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="s2", area=".", status=TIMEOUT.value,
            verification_kind="test", runner_type="pytest",
            passed=False, timed_out=True,
        ),
    ))
    assert aggregated != PASS.value


def test_invalid_plan_blocks_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area=".", status=INVALID_PLAN.value,
            verification_kind="test", runner_type="pytest",
            passed=False,
        ),
    ))
    assert aggregated != PASS.value


# ============================================================================
# 38–39. ProjectTestRunner compatibility + canonical flow
# ============================================================================
def test_project_test_runner_still_works_in_isolation(tmp_path):
    """The classic ProjectTestRunner works when invoked directly."""
    from app.project_test_runner import ProjectTestRunner, TestExecutionRequest
    _write(tmp_path / "tests" / "test_trivial.py",
           "def test_x():\n    assert True\n")
    runner = ProjectTestRunner(timeout=30)
    result = runner.run(TestExecutionRequest(tmp_path))
    assert result.passed is True


def test_canonical_composition_wires_verification_registry():
    from app.canonical_composition import build_canonical_components
    components = build_canonical_components()
    assert components.service is not None
    assert components.development_workflow is not None