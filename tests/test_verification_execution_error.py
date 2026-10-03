"""DEF-RSE033-ESPHOME-COMPILE-TIMEOUT / EXECUTION_ERROR_CLASSIFICATION:
permanent lower-gate regressions.

CLAUDE-ADC-RSE033-EXECUTION-ERROR-REQ-CODE-FIX-001. A controlled
verification process that had successfully started and then failed at
ADC's own execution boundary (a communicate()/pipe error) was reported
as TOOL_UNAVAILABLE -- the S5 -> S3.5 missing-toolchain trigger. Each
class below owns one part of the corrected taxonomy (ARC_022, ARC_026,
IF_REQ_023, IF_REQ_026):

  TestExecutionErrorClassification  -- S5.2: the launch boundary decides
      TOOL_UNAVAILABLE (cannot start) vs EXECUTION_ERROR (started, then
      the execution infrastructure failed); TIMEOUT and FAIL stay distinct;
  TestExecutionErrorOutcomePolicy   -- S5.6: EXECUTION_ERROR ends in the
      fail-closed verification_execution_error outcome; a diagnosis
      cannot authorize rework for it; a real FAIL still dominates;
  TestExecutionErrorReworkBudget    -- S5.7: it never consumes the single
      bounded rework;
  TestExecutionErrorToolchainRecoveryBoundary -- S5 -> S3: it never takes
      the missing-toolchain route, while a genuinely unavailable tool
      still does.

Post-start failures are injected at the stdlib boundary
(subprocess.Popen.communicate) of a real, running controlled process;
every ADC component on the path is real.
"""
from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.execution as _execution
from app.controlled_rework_stage import ControlledReworkStage
from app.dev_workflow import _DIAGNOSIS_TRACE_PROJECTION
from app.development_testing_stage import (
    DevelopmentTestingResult, DevelopmentTestingStage, _test_result_from_verification,
)
from app.diagnostic_trace import EVENT_TYPES, STATUSES
from app.execution import (
    TIMEOUT_RETURN_CODE, ControlledExecutionError, ExecutionRequest, execute_controlled,
)
from app.project_inspector import ProjectInspector
from app.python_distribution import (
    DISTRIBUTION_METADATA_QUERY_SCRIPT, QUERY_COMPLETED, QUERY_EXECUTION_ERROR, QUERY_TIMEOUT,
    TARGET_PYTHON_UNAVAILABLE,
)
from app.project_test_runner import TestExecutionRequest
from app.testing_stage import (
    VERIFICATION_EXECUTION_ERROR, VERIFICATION_TIMEOUT, DiagnosisReviewer, TestingStage,
)
from app.verification import (
    BLOCKED, EXECUTION_ERROR, FAIL, TIMEOUT, TOOL_UNAVAILABLE,
    VerificationStep, VerificationStepResult, _safe_exec, build_default_registry,
)

posix_only = pytest.mark.skipif(sys.platform != "linux", reason="uses /proc to observe processes")


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state not in ("Z", "X")


def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


def _wait_for(path: Path, seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"the controlled process never reached {path.name}")


# The external work of a started verification: it spawns a descendant that
# ignores SIGTERM (the harder containment case), publishes the descendant's
# pid atomically, and then keeps running.
_LONG_RUNNING_TEST = textwrap.dedent("""\
    import os, subprocess, sys, time

    def test_long_running_external_work():
        child = subprocess.Popen([sys.executable, "-c",
            "import signal, time\\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\\ntime.sleep(120)"])
        tmp = {pid_file!r} + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(str(child.pid))
        os.replace(tmp, {pid_file!r})
        time.sleep(120)
""")


def _is_pytest_run(args) -> bool:
    args = list(args) if isinstance(args, (list, tuple)) else []
    return "-m" in args and "pytest" in args


def _fail_after_start(monkeypatch, *, ready: Path | None = None, matches=_is_pytest_run):
    """Make the first communicate() with a matching, already started
    controlled process fail with a real OSError -- once the process has
    reached `ready` (if given). Returns the list of started pids."""
    real_communicate = subprocess.Popen.communicate
    started: list[int] = []

    def communicate(self, *args, **kwargs):
        if not started and matches(self.args):
            started.append(self.pid)
            if ready is not None:
                _wait_for(ready)
            raise OSError(errno.EPIPE, "Broken pipe while talking to the controlled process")
        return real_communicate(self, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "communicate", communicate)
    return started


def _is_distribution_query(args) -> bool:
    return DISTRIBUTION_METADATA_QUERY_SCRIPT in list(args)


def _pytest_project(root: Path, test_source: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "test_project.py").write_text(test_source)
    return root


def _cmake_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.10)\nproject(x C)\nadd_executable(x main.c)\n"
    )
    (root / "main.c").write_text("int main(void) { return 0; }\n")
    return root


def _pytest_step(budget: int = 60) -> VerificationStep:
    return VerificationStep("s", ".", ".", "test", "pytest", "pytest", "controlled_execution",
                            execution_budget_seconds=budget)


def _cmake_step() -> VerificationStep:
    return VerificationStep("c", ".", ".", "configure", "cmake", "cmake", "controlled_execution",
                            execution_budget_seconds=60)


def _without_path_executables(monkeypatch, tmp_path: Path) -> None:
    empty = tmp_path / "empty-bin"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))


def _real_execution_error(tmp_path, monkeypatch) -> tuple[VerificationStepResult, list[int], Path]:
    pid_file = tmp_path / "descendant.pid"
    project = _pytest_project(tmp_path / "project", _LONG_RUNNING_TEST.format(pid_file=str(pid_file)))
    started = _fail_after_start(monkeypatch, ready=pid_file)
    result = build_default_registry().execute_step(_pytest_step(), str(project))
    monkeypatch.undo()
    return result, started, pid_file


class _ScriptedReviewer:
    def __init__(self, *decisions):
        self._decisions = list(decisions)
        self.calls = 0

    def run(self, *_args, **_kwargs):
        self.calls += 1
        return json.dumps({"decision": self._decisions.pop(0), "summary": "execution diagnosis"})


class _RaisingReviewer:
    def run(self, *_args, **_kwargs):
        raise RuntimeError("provider unavailable")


def _step(step_id, status, *, return_code=None, timed_out=False):
    return VerificationStepResult(
        step_id=step_id, area=".", status=status, verification_kind="test",
        runner_type="generic", passed=False, return_code=return_code,
        timed_out=timed_out, diagnostics=status,
    )


class TestExecutionErrorClassification:
    """ARC_022 / IF_REQ_023: S5.2 decides the launch boundary structurally."""

    @posix_only
    def test_four_way_taxonomy_through_real_boundary_and_runners(self, tmp_path, monkeypatch):
        registry = build_default_registry()

        with monkeypatch.context() as m:
            _without_path_executables(m, tmp_path)
            unavailable = registry.execute_step(_cmake_step(), str(_cmake_project(tmp_path / "a")))

        execution_error, started, _ = _real_execution_error(tmp_path / "b", monkeypatch)

        timeout = registry.execute_step(_pytest_step(budget=2), str(_pytest_project(
            tmp_path / "c", "import time\ndef test_slow():\n    time.sleep(60)\n")))
        fail = registry.execute_step(_pytest_step(), str(_pytest_project(
            tmp_path / "d", "def test_fail():\n    assert False\n")))

        assert unavailable.status == TOOL_UNAVAILABLE.value
        assert execution_error.status == EXECUTION_ERROR.value and started
        assert timeout.status == TIMEOUT.value and timeout.return_code == TIMEOUT_RETURN_CODE
        assert fail.status == FAIL.value and fail.return_code == 1 and not fail.timed_out
        assert len({r.status for r in (unavailable, execution_error, timeout, fail)}) == 4
        assert not any(r.passed for r in (unavailable, execution_error, timeout, fail))

    @posix_only
    def test_post_start_runtime_error_is_execution_error_after_containment(self, tmp_path, monkeypatch):
        result, started, pid_file = _real_execution_error(tmp_path, monkeypatch)

        (leader,) = started
        descendant = int(pid_file.read_text())
        assert result.status == EXECUTION_ERROR.value
        assert result.status != TOOL_UNAVAILABLE.value
        assert result.passed is False and result.timed_out is False
        assert result.return_code is None
        assert result.error_category == ControlledExecutionError.__name__
        assert "after the process started" in result.diagnostics
        assert result.unavailable_tool is None
        # cleanup occurred before the error surfaced: the whole owned tree is gone
        assert _wait_gone(leader), "the started verification process was left running"
        assert _wait_gone(descendant), "a descendant of the started process survived the execution error"

    @posix_only
    def test_launch_failure_before_start_is_tool_unavailable(self, tmp_path, monkeypatch):
        """A real OS launch failure (the executable's interpreter does not
        exist): the process never started, so the tool is unavailable."""
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "python3"
        fake.write_text("#!/nonexistent/adc-interpreter\n")
        fake.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        request = ExecutionRequest(("python3", "-c", "pass"), str(tmp_path), 5, "python", "test")

        assert execute_controlled(request, tmp_path) is None
        assert _safe_exec(("python3", "-c", "pass"), tmp_path, 5, operation_type="test") is None

    def test_launch_failure_that_provisioning_cannot_remedy_is_not_tool_unavailable(self, tmp_path, monkeypatch):
        def exhausted(*_args, **_kwargs):
            raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")

        monkeypatch.setattr(subprocess, "Popen", exhausted)
        request = ExecutionRequest((sys.executable, "-c", "pass"), str(tmp_path), 5, "python", "test")

        with pytest.raises(ControlledExecutionError) as caught:
            execute_controlled(request, tmp_path)
        assert caught.value.started is False
        result = build_default_registry().execute_step(_pytest_step(), str(tmp_path))
        assert result.status == EXECUTION_ERROR.value

    @posix_only
    def test_started_process_error_at_the_boundary_is_structured(self, tmp_path, monkeypatch):
        started = _fail_after_start(monkeypatch, matches=lambda _args: True)
        request = ExecutionRequest((sys.executable, "-c", "import time; time.sleep(30)"),
                                   str(tmp_path), 30, "python", "test")

        with pytest.raises(ControlledExecutionError) as caught:
            execute_controlled(request, tmp_path)

        assert caught.value.started is True
        assert isinstance(caught.value.__cause__, OSError)
        assert _wait_gone(started[0])

    @posix_only
    def test_auxiliary_consumers_never_report_tool_unavailable_after_start(self, tmp_path, monkeypatch):
        from app.project_test_runner import ProjectTestRunner
        from app.python_distribution import check_distribution_installed
        from app.python_package_executor import PythonPackageExecutor

        _pytest_project(tmp_path, "def test_ok():\n    assert True\n")
        _fail_after_start(monkeypatch, matches=lambda _args: True)
        test_result = ProjectTestRunner(timeout=30).run(TestExecutionRequest(tmp_path))
        assert test_result.passed is False
        assert "tool unavailable" not in test_result.stderr
        assert "after the process started" in test_result.stderr
        monkeypatch.undo()

        _fail_after_start(monkeypatch, matches=lambda _args: True)
        command = PythonPackageExecutor()._run(
            [sys.executable, "-c", "pass"], str(tmp_path), 30, operation_type="verification",
        )
        assert command.returncode != 0
        assert "tool unavailable" not in command.stderr
        assert "after the process started" in command.stderr
        monkeypatch.undo()

        _fail_after_start(monkeypatch, matches=lambda _args: True)
        check = check_distribution_installed("pytest", sys.executable, project_root=str(tmp_path))
        # the query never completed: no verdict -- neither "not installed" nor "unavailable"
        assert check.query_state == QUERY_EXECUTION_ERROR and check.execution_failed
        assert check.installed is None and not check.absent and check.target_python_available is True

    @posix_only
    def test_python_distribution_keeps_unavailable_and_execution_error_distinct(self, tmp_path, monkeypatch):
        """CLAUDE-ADC-RSE033-EXECUTION-ERROR-AUXILIARY-ASSURANCE-CLOSURE-FIX-002:
        the real python-distribution producer classifies each target-Python
        query outcome from the central boundary's structured result."""
        from app.python_distribution import check_distribution_installed

        def check(target=sys.executable):
            return check_distribution_installed("pytest", target, project_root=str(tmp_path))

        completed = check()
        unavailable = check(str(tmp_path / "no-such-python"))
        with monkeypatch.context() as m:
            started = _fail_after_start(m, matches=_is_distribution_query)
            post_start = check()
        with monkeypatch.context() as m:
            def exhausted(*_args, **_kwargs):
                raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")
            m.setattr(subprocess, "Popen", exhausted)
            pre_start = check()
        with monkeypatch.context() as m:
            def expired(self, *args, **kwargs):
                m.undo()
                raise subprocess.TimeoutExpired(self.args, kwargs.get("timeout"))
            m.setattr(subprocess.Popen, "communicate", expired)
            timed_out = check()

        assert completed.query_state == QUERY_COMPLETED and completed.installed and completed.version
        assert unavailable.query_state == TARGET_PYTHON_UNAVAILABLE
        assert unavailable.target_python_available is False and not unavailable.execution_failed
        assert "no-such-python" in unavailable.diagnostics
        assert started and _wait_gone(started[0])
        for outcome, state in ((post_start, QUERY_EXECUTION_ERROR), (pre_start, QUERY_EXECUTION_ERROR),
                               (timed_out, QUERY_TIMEOUT)):
            assert outcome.query_state == state and outcome.execution_failed
            assert outcome.target_python_available is True and not outcome.installed
            assert "target python" not in outcome.diagnostics.lower()
        assert post_start.diagnostics.startswith("ControlledExecutionError")
        assert "after the process started" in post_start.diagnostics
        assert pre_start.diagnostics.startswith("ControlledExecutionError")
        assert "could not be started" in pre_start.diagnostics
        assert len({r.query_state for r in (completed, unavailable, post_start, timed_out)}) == 4

    @posix_only
    def test_python_distribution_execution_error_never_authorizes_setup(self, tmp_path, monkeypatch):
        """A no-verdict target-Python query fails Preflight closed: no
        missing requirement, no setup step, no Council/materialization --
        while a genuinely unavailable target keeps its existing route."""
        from app.ai_requirement_discovery import AIRequirementDiscovery
        from app.dev_workflow import DevelopmentWorkflow
        from app.engineering_council import EngineeringCouncil
        from app.requirement_model import DiscoveryResult, Requirement
        from app.requirement_preflight import RequirementCheckExecutionError, RequirementPreflight
        from app.requirement_validator import RequirementValidator
        from app.setup_planner import SetupPlanner
        from app.toolchain_materializer import ToolchainMaterializer

        requirement = Requirement(
            id="req-pytest", name="pytest", technical_identity="pytest", type="python_package",
            purpose="tests", required=True, confidence=0.9, install_method="pip",
            verification_method="pip show pytest",
        )

        def preflight(target=sys.executable):
            return RequirementPreflight.check((requirement,), "proj", project_root=str(tmp_path),
                                              target_executable=target)

        satisfied = preflight()
        assert satisfied.results[0].satisfied and not satisfied.missing_requirements
        unavailable = preflight(str(tmp_path / "no-such-python"))
        assert unavailable.missing_requirements == (requirement,)
        assert unavailable.results[0].warning == RequirementPreflight.NOT_LOCALLY_VERIFIABLE_WARNING
        assert [s.package for s in SetupPlanner().plan((requirement,), unavailable, "proj").steps] == ["pytest"]

        _fail_after_start(monkeypatch, matches=_is_distribution_query)
        with pytest.raises(RequirementCheckExecutionError) as caught:
            preflight()
        assert caught.value.requirement_id == "req-pytest"
        assert caught.value.query_state == QUERY_EXECUTION_ERROR
        monkeypatch.undo()

        discovery = Mock(spec=AIRequirementDiscovery)
        discovery.discover.return_value = DiscoveryResult(
            id="d", source="test", project_id="proj", requirements=(requirement,),
        )
        council = Mock(spec=EngineeringCouncil)
        materializer = Mock(spec=ToolchainMaterializer)
        workflow = DevelopmentWorkflow(
            discovery, RequirementValidator(), RequirementPreflight(), Mock(spec=SetupPlanner),
            council=council, materializer=materializer,
        )
        _fail_after_start(monkeypatch, matches=_is_distribution_query)
        with pytest.raises(RequirementCheckExecutionError):
            workflow.run({"name": "p"}, "proj", project_context=SimpleNamespace(project_root=str(tmp_path)))
        council.evaluate.assert_not_called()
        materializer.materialize_decision.assert_not_called()


class TestExecutionErrorOutcomePolicy:
    """ARC_026 / IF_REQ_026: EXECUTION_ERROR is a fail-closed terminal S5.6
    outcome; a diagnosis may describe it but cannot turn it into rework."""

    @posix_only
    @pytest.mark.parametrize("decision", ["accepted", "rework_required"])
    def test_real_execution_error_is_terminal_whatever_the_diagnosis(self, tmp_path, monkeypatch, decision):
        step, _, _ = _real_execution_error(tmp_path, monkeypatch)
        reviewer = _ScriptedReviewer(decision)
        test_result = _test_result_from_verification((step,))

        outcome = TestingStage(DiagnosisReviewer(reviewer)).run("development", test_result)

        assert reviewer.calls == 1  # evidence is still diagnosed ...
        assert outcome.status == VERIFICATION_EXECUTION_ERROR  # ... but it has no routing authority
        assert outcome.rework_request is None
        assert test_result.passed is False

    def test_unavailable_diagnosis_keeps_the_terminal_outcome(self):
        test_result = _test_result_from_verification((_step("e", EXECUTION_ERROR.value),))
        outcome = TestingStage(DiagnosisReviewer(_RaisingReviewer())).run("development", test_result)
        assert (outcome.status, outcome.rework_request) == (VERIFICATION_EXECUTION_ERROR, None)

    @pytest.mark.parametrize("companion", [TIMEOUT.value, BLOCKED.value])
    def test_no_verdict_companions_keep_the_terminal_outcome(self, companion):
        steps = (_step("e", EXECUTION_ERROR.value),
                 _step("t", companion, timed_out=companion == TIMEOUT.value))
        outcome = TestingStage(DiagnosisReviewer(_ScriptedReviewer("rework_required"))).run(
            "development", _test_result_from_verification(steps),
        )
        assert outcome.status == VERIFICATION_EXECUTION_ERROR
        assert outcome.rework_request is None

    def test_real_failure_alongside_still_forces_rework(self):
        steps = (_step("e", EXECUTION_ERROR.value), _step("f", FAIL.value, return_code=1))
        outcome = TestingStage(DiagnosisReviewer(_ScriptedReviewer("accepted"))).run(
            "development", _test_result_from_verification(steps),
        )
        assert outcome.status == "rework_required"
        assert outcome.rework_request is not None

    def test_timeout_only_policy_is_unchanged(self):
        steps = (_step("t", TIMEOUT.value, timed_out=True),)
        outcome = TestingStage(DiagnosisReviewer(_ScriptedReviewer("accepted"))).run(
            "development", _test_result_from_verification(steps),
        )
        assert outcome.status == VERIFICATION_TIMEOUT

    def test_trace_projection_preserves_the_cause_in_existing_vocabulary(self):
        event_type, status = _DIAGNOSIS_TRACE_PROJECTION[VERIFICATION_EXECUTION_ERROR]
        assert event_type in EVENT_TYPES and status in STATUSES
        assert status == EXECUTION_ERROR.value


class _Cycle:
    """One S4/S5 cycle whose S5 part is real: step results -> real
    _test_result_from_verification -> real TestingStage."""

    def __init__(self, testing_stage, *steps_per_cycle):
        self._testing_stage = testing_stage
        self._cycles = list(steps_per_cycle)
        self.runs = 0

    def run(self, request):
        self.runs += 1
        test_result = _test_result_from_verification(self._cycles.pop(0))
        stage_result = self._testing_stage.run("development", test_result)
        return DevelopmentTestingResult("development", None, None, test_result, stage_result)


class TestExecutionErrorReworkBudget:
    """ARC_REQ_021 / IF_REQ_027: EXECUTION_ERROR never consumes the single
    bounded S5 -> S4 rework."""

    @posix_only
    def test_execution_error_never_starts_a_rework_cycle(self, tmp_path, monkeypatch):
        step, _, _ = _real_execution_error(tmp_path, monkeypatch)
        reviewer = _ScriptedReviewer("rework_required")
        cycle = _Cycle(TestingStage(DiagnosisReviewer(reviewer)), (step,))

        result = ControlledReworkStage(cycle).run(SimpleNamespace(run_id="r"))

        assert cycle.runs == 1
        assert result.rework_executed is False
        assert result.status == VERIFICATION_EXECUTION_ERROR

    def test_real_failure_rework_stays_bounded_when_the_rework_hits_an_execution_error(self):
        reviewer = _ScriptedReviewer("accepted", "rework_required")
        cycle = _Cycle(
            TestingStage(DiagnosisReviewer(reviewer)),
            (_step("f", FAIL.value, return_code=1),),
            (_step("e", EXECUTION_ERROR.value),),
        )

        result = ControlledReworkStage(cycle).run(SimpleNamespace(run_id="r"))

        assert cycle.runs == 2  # the one bounded rework, never a third cycle
        assert result.rework_executed is True
        assert result.status == VERIFICATION_EXECUTION_ERROR


def _development_testing_stage(reviewer=None):
    development_stage = Mock()
    development_stage.run.return_value = SimpleNamespace(status="success")
    generator = Mock()
    generator.generate.return_value = {"changes": [{"file": "test_feature.py", "action": "create", "content": "x"}]}
    applier = Mock()
    applier.apply.return_value = {"applied": ["test_feature.py"], "skipped": []}
    reviewer = reviewer or _ScriptedReviewer("rework_required")
    stage = DevelopmentTestingStage(
        development_stage, generator, Mock(return_value=applier), Mock(),
        TestingStage(DiagnosisReviewer(reviewer)),
        verification_registry=build_default_registry(), project_inspector=ProjectInspector(),
    )
    return stage, reviewer


def _request(project: Path):
    # These direct S5 tests declare their already-resolved target explicitly;
    # the production workflow normally supplies it during S3 -> S4.
    return SimpleNamespace(
        project_id="project", project_path=str(project), task="t", run_id="run-x",
        target_environment=SimpleNamespace(verification_target=sys.executable),
    )


class TestExecutionErrorToolchainRecoveryBoundary:
    """IF_REQ_029 / ARC_026: only an unavailable tool takes the S5 -> S3.5
    route; an execution error of a started tool never does. Real
    ProjectInspector, plan producer, registry, runner and S5.6 policy."""

    @posix_only
    def test_execution_error_never_takes_the_missing_toolchain_route(self, tmp_path, monkeypatch):
        pid_file = tmp_path / "descendant.pid"
        project = _pytest_project(tmp_path / "project", _LONG_RUNNING_TEST.format(pid_file=str(pid_file)))
        stage, reviewer = _development_testing_stage()
        _fail_after_start(monkeypatch, ready=pid_file)

        result = stage.run(_request(project))

        (step,) = result.verification_result.steps
        assert step.status == EXECUTION_ERROR.value
        assert result.failure_stage != "tool_unavailable"
        assert result.status == VERIFICATION_EXECUTION_ERROR
        assert result.testing_stage_result.rework_request is None
        assert reviewer.calls == 1
        assert _wait_gone(int(pid_file.read_text()))

    def test_unavailable_tool_still_takes_the_missing_toolchain_route(self, tmp_path, monkeypatch):
        project = _cmake_project(tmp_path / "project")
        stage, reviewer = _development_testing_stage()
        _without_path_executables(monkeypatch, tmp_path)

        result = stage.run(_request(project))

        assert result.status == "tool_unavailable"
        assert result.failure_stage == "tool_unavailable"
        assert {s.status for s in result.verification_result.steps} >= {TOOL_UNAVAILABLE.value}
        assert result.verification_plan is not None  # carried for the S3.5 recovery request
        assert result.testing_stage_result is None and reviewer.calls == 0
