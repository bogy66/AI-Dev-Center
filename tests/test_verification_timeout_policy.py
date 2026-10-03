"""DEF-RSE033-ESPHOME-COMPILE-TIMEOUT: permanent lower-gate regressions.

CLAUDE-ADC-RSE033-ESPHOME-COMPILE-TIMEOUT-REQ-CODE-FIX-001. A Real-System
run timed out a real firmware compile after a runner-constructor literal
budget; the timed-out process tree was only partially killed, its partial
output kept the wrong type, and the timeout consumed the single bounded
source rework. Each class below owns one of those defect classes:

  TestVerificationBudgetPolicy       -- the budget is owned by the
      VerificationPlan/Step execution policy (ARC_022, IF_REQ_022);
  TestBudgetConsumptionAndProcessBoundary -- runners consume exactly that
      budget, and the real controlled process boundary contains the whole
      process tree on timeout with str partial output -- also when that
      output is not valid UTF-8 or cannot be drained (FIX-002);
  TestTimeoutReworkClassification    -- TIMEOUT is fail-closed but never
      automatic source rework (ARC_026, IF_REQ_026).
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.execution as _execution
from app.controlled_rework_stage import ControlledReworkStage
from app.development_testing_stage import (
    DevelopmentTestingResult, _test_result_from_verification,
)
from app.execution import TIMEOUT_RETURN_CODE, ExecutionRequest, execute_controlled
from app.missing_toolchain_setup import deserialize_verification_plan, serialize_verification_plan
from app.testing_stage import (
    VERIFICATION_TIMEOUT, DiagnosisReviewer, TestingStage,
)
from app.verification import (
    BLOCKED, EXECUTION_ERROR, FAIL, INVALID_PLAN, MAX_VERIFICATION_EXECUTION_BUDGET_SECONDS,
    PASS, TIMEOUT, TOOL_UNAVAILABLE, VERIFICATION_EXECUTION_BUDGET_SECONDS,
    CMakeRunner, ControlledRunnerRegistry, ESPHomeCheckRunner, PlatformIORunner,
    PytestRunner, PythonUnittestRunner, VerificationStep, VerificationStepResult,
    _aggregate, build_default_registry, build_verification_plan,
    verification_execution_budget,
)

posix_only = pytest.mark.skipif(sys.platform != "linux", reason="uses /proc to observe descendants")


def _firmware_intelligence(root):
    fw = SimpleNamespace(name="esphome", config_path="device.yaml")
    area = SimpleNamespace(path=".", test_systems=(), build_systems=(), firmware_indicators=(fw,))
    return SimpleNamespace(project_root=str(root), project_kind="firmware", areas=(area,))


def _mixed_intelligence(root):
    area = SimpleNamespace(
        path=".",
        test_systems=(SimpleNamespace(name="pytest", evidence=()),),
        build_systems=(SimpleNamespace(name="cmake", evidence=()),),
        firmware_indicators=(SimpleNamespace(name="platformio", boards=("native",), has_untrusted_hooks=False),),
    )
    return SimpleNamespace(project_root=str(root), project_kind="mixed", areas=(area,))


def _alive(pid: int) -> bool:
    # A process that exits while /proc is read yields ENOENT or ESRCH
    # (ProcessLookupError); zombie (Z) and dead (X) states have run to
    # completion. Only a still-running process counts as alive.
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state not in ("Z", "X")


def _wait_gone(pid: int, seconds: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return not _alive(pid)


# A controlled external process that emits progress on both streams,
# spawns a descendant that ignores SIGTERM (the harder cleanup case), and
# outlives any short budget. {pid_file} is filled in per test.
_SLOW_TREE_SCRIPT = textwrap.dedent("""\
    import subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c",
        "import signal, time\\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\\ntime.sleep(120)"])
    with open({pid_file!r}, "w") as fh:
        fh.write(str(child.pid))
    for i in range(1000):
        print(f"[{{i}}/1000] building object", flush=True)
        print(f"warning {{i}}", file=sys.stderr, flush=True)
        time.sleep(0.05)
""")


# FIX-002: the same escape class with output that is not valid UTF-8 --
# valid progress text around invalid, and a split multibyte sequence at
# the end of each stream -- while a SIGTERM-resistant descendant stays in
# the owned process group.
_INVALID_OUTPUT_TREE_SCRIPT = textwrap.dedent("""\
    import os, subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c",
        "import signal, time\\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\\ntime.sleep(120)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open({pid_file!r}, "w") as fh:
        fh.write(str(child.pid))
    os.write(1, b"[1/9] building object\\n\\xff\\xfe garbage\\n[2/9] linking \\xe2\\x82")
    os.write(2, b"warning: slow\\n\\xc3\\x28 broken\\n")
    time.sleep(120)
""")


def _write_script(tmp_path, source):
    script = tmp_path / "controlled.py"
    script.write_text(source)
    return script


class TestVerificationBudgetPolicy:
    """ARC_022 / IF_REQ_022: the producer writes the policy budget into
    every step explicitly; no technology special case decides it."""

    def test_producer_writes_explicit_policy_budget_into_every_step(self, tmp_path):
        plan = build_verification_plan(_firmware_intelligence(tmp_path), "run-budget")
        by_kind = {s.verification_kind: s for s in plan.steps}
        assert by_kind["validate"].execution_budget_seconds == VERIFICATION_EXECUTION_BUDGET_SECONDS["check"]
        assert by_kind["compile"].execution_budget_seconds == VERIFICATION_EXECUTION_BUDGET_SECONDS["build"]

    def test_budget_depends_on_generic_operation_class_never_on_tool(self, tmp_path):
        plan = build_verification_plan(_mixed_intelligence(tmp_path), "run-mixed")
        for step in plan.steps:
            if step.policy != "controlled_execution":
                continue
            expected = verification_execution_budget(step.verification_kind)
            if step.step_id.endswith("pio-test-native"):
                # declared operation class: builds the native target first
                expected = verification_execution_budget("test", operation_class="build")
            assert step.execution_budget_seconds == expected, step.step_id
        # the same generic kind gets the same budget across ecosystems
        builds = {s.execution_budget_seconds for s in plan.steps if s.verification_kind == "build"}
        assert builds == {VERIFICATION_EXECUTION_BUDGET_SECONDS["build"]}

    def test_policy_values_are_bounded(self):
        for value in VERIFICATION_EXECUTION_BUDGET_SECONDS.values():
            assert 0 < value <= MAX_VERIFICATION_EXECUTION_BUDGET_SECONDS
        assert verification_execution_budget("unknown-kind") is None

    def test_budget_survives_plan_persistence_exactly(self, tmp_path):
        plan = build_verification_plan(_firmware_intelligence(tmp_path), "run-persist")
        custom = dataclasses.replace(plan, steps=tuple(
            dataclasses.replace(s, execution_budget_seconds=7) for s in plan.steps
        ))
        restored = deserialize_verification_plan(json.loads(json.dumps(serialize_verification_plan(custom))))
        assert [s.execution_budget_seconds for s in restored.steps] == [7, 7]

    def test_legacy_persisted_step_without_budget_takes_central_policy_not_runner_value(self, tmp_path):
        plan = build_verification_plan(_firmware_intelligence(tmp_path), "run-legacy")
        data = serialize_verification_plan(plan)
        for step in data["steps"]:
            del step["execution_budget_seconds"]
        restored = deserialize_verification_plan(data)
        compile_step = next(s for s in restored.steps if s.verification_kind == "compile")
        assert compile_step.execution_budget_seconds == verification_execution_budget("compile")

    def test_runners_have_no_constructor_budget(self):
        for runner_cls in (PytestRunner, PythonUnittestRunner, ESPHomeCheckRunner,
                           PlatformIORunner, CMakeRunner):
            with pytest.raises(TypeError):
                runner_cls(timeout=1)
        assert all(not hasattr(r, "_timeout") for r in build_default_registry()._runners)


class TestBudgetConsumptionAndProcessBoundary:
    """ARC_REQ_016 / SUB_REQ_018: the step budget reaches the real
    ExecutionRequest, and a timeout at the real process boundary is
    structured, typed, and leaves no descendant behind."""

    def _capture_timeouts(self, monkeypatch):
        seen = []

        def capture(args, *, cwd, timeout, env):
            seen.append(timeout)
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(_execution, "run_contained_process", capture)
        return seen

    def test_changing_step_policy_changes_the_real_execution_budget(self, tmp_path, monkeypatch):
        seen = self._capture_timeouts(monkeypatch)
        (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n")
        registry = build_default_registry()
        base = VerificationStep("s", ".", ".", "test", "pytest", "pytest", "controlled_execution")
        for budget in (11, 42):
            result = registry.execute_step(dataclasses.replace(base, execution_budget_seconds=budget), str(tmp_path))
            assert result.status == PASS.value
        assert seen == [11, 42]

    @pytest.mark.parametrize("budget", [0, -5, MAX_VERIFICATION_EXECUTION_BUDGET_SECONDS + 1, True, "600"])
    def test_invalid_budget_fails_closed_before_any_process(self, tmp_path, monkeypatch, budget):
        seen = self._capture_timeouts(monkeypatch)
        step = VerificationStep("s", ".", ".", "test", "pytest", "pytest", "controlled_execution",
                                execution_budget_seconds=budget)
        result = PytestRunner().execute(step, tmp_path)
        assert result.status == INVALID_PLAN.value
        assert result.passed is False
        assert "execution budget" in result.diagnostics
        assert seen == []

    def test_unknown_kind_without_policy_budget_fails_closed(self, tmp_path, monkeypatch):
        seen = self._capture_timeouts(monkeypatch)
        step = VerificationStep("s", ".", ".", "lint", "pytest", "pytest", "controlled_execution")
        assert step.execution_budget_seconds is None
        assert PytestRunner().execute(step, tmp_path).status == INVALID_PLAN.value
        assert seen == []

    @posix_only
    def test_real_process_timeout_contains_tree_and_keeps_str_partial_output(self, tmp_path):
        pid_file = tmp_path / "descendant.pid"
        script = tmp_path / "slow_tree.py"
        script.write_text(_SLOW_TREE_SCRIPT.format(pid_file=str(pid_file)))
        request = ExecutionRequest((sys.executable, str(script)), str(tmp_path), 1, "python", "test")

        result = execute_controlled(request, tmp_path)

        assert result.timed_out is True
        assert result.returncode == TIMEOUT_RETURN_CODE
        assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
        assert "[0/1000] building object" in result.stdout
        assert "warning 0" in result.stderr
        descendant = int(pid_file.read_text())
        assert _wait_gone(descendant), "a timed-out controlled process left a descendant alive"

    @posix_only
    def test_real_timeout_with_invalid_utf8_output_contains_tree_and_stays_timeout(self, tmp_path):
        """The real escape: undecodable partial output must neither abort
        timeout cleanup nor turn the timeout into an unavailable tool."""
        pid_file = tmp_path / "descendant.pid"
        script = _write_script(tmp_path, _INVALID_OUTPUT_TREE_SCRIPT.format(pid_file=str(pid_file)))
        request = ExecutionRequest((sys.executable, str(script)), str(tmp_path), 1, "python", "test")

        result = execute_controlled(request, tmp_path)

        assert result is not None
        assert result.timed_out is True
        assert result.returncode == TIMEOUT_RETURN_CODE
        assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
        assert result.stdout == "[1/9] building object\n\ufffd\ufffd garbage\n[2/9] linking \ufffd"
        assert result.stderr == "warning: slow\n\ufffd( broken\n"
        assert _wait_gone(int(pid_file.read_text())), "invalid output let a descendant survive the timeout"

    @posix_only
    @pytest.mark.parametrize("stdout_bytes, stderr_bytes, stdout_text, stderr_text", [
        (b"ok \xff end", b"", "ok \ufffd end", ""),
        (b"", b"ok \xff end", "", "ok \ufffd end"),
        (b"a\xfeb", b"c\x80d", "a\ufffdb", "c\ufffdd"),
        (b"", b"", "", ""),
        (b"caf\xc3\xa9 \xe2\x9c\x93", b"\xf0\x9f\x94\xa5", "caf\u00e9 \u2713", "\U0001f525"),
        (b"partial \xe2\x82", b"partial \xf0\x9f\x94", "partial \ufffd", "partial \ufffd"),
    ], ids=["invalid-stdout", "invalid-stderr", "invalid-both", "no-output",
            "valid-multibyte", "invalid-trailing-multibyte"])
    def test_real_timeout_output_is_always_str_and_keeps_valid_text(
        self, tmp_path, stdout_bytes, stderr_bytes, stdout_text, stderr_text,
    ):
        script = _write_script(tmp_path, (
            "import os, time\n"
            f"os.write(1, {stdout_bytes!r})\n"
            f"os.write(2, {stderr_bytes!r})\n"
            "time.sleep(120)\n"
        ))
        request = ExecutionRequest((sys.executable, str(script)), str(tmp_path), 1, "python", "test")

        result = execute_controlled(request, tmp_path)

        assert result.timed_out is True and result.returncode == TIMEOUT_RETURN_CODE
        assert (result.stdout, result.stderr) == (stdout_text, stderr_text)

    @posix_only
    def test_output_draining_failure_cannot_bypass_process_group_containment(self, tmp_path, monkeypatch):
        """Draining the timed-out process's pipes fails (a pipe error):
        the timeout stays the outcome with the output captured before
        the budget expired, and the owned process group is still
        contained."""
        import subprocess

        pid_file = tmp_path / "descendant.pid"
        script = _write_script(tmp_path, _INVALID_OUTPUT_TREE_SCRIPT.format(pid_file=str(pid_file)))
        real_communicate = subprocess.Popen.communicate
        calls = []

        def failing_drain(self, *args, **kwargs):
            calls.append(kwargs.get("timeout"))
            if len(calls) > 1:
                raise OSError("pipe broke while draining timed-out output")
            return real_communicate(self, *args, **kwargs)

        monkeypatch.setattr(subprocess.Popen, "communicate", failing_drain)
        request = ExecutionRequest((sys.executable, str(script)), str(tmp_path), 1, "python", "test")

        result = execute_controlled(request, tmp_path)

        assert len(calls) == 2, "the drain after the budget expired must have been attempted"
        assert result.timed_out is True and result.returncode == TIMEOUT_RETURN_CODE
        assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
        assert "[1/9] building object" in result.stdout
        assert _wait_gone(int(pid_file.read_text())), "a drain failure skipped process-group containment"

    @posix_only
    def test_invalid_output_timeout_through_real_runner_is_generic_timeout_never_s3(self, tmp_path):
        """Tool exists, process starts, emits invalid UTF-8 and times out:
        real registry/runner -> TIMEOUT (never TOOL_UNAVAILABLE, the only
        S5 -> S3 missing-toolchain trigger) -> real S5 classification ->
        generic fail-closed timeout without rework."""
        pid_file = tmp_path / "descendant.pid"
        project = tmp_path / "project"
        project.mkdir()
        (project / "test_slow.py").write_text(
            "import os, subprocess, sys, time\n"
            "def test_slow(capsys):\n"
            "    child = subprocess.Popen([sys.executable, '-c',\n"
            "        'import signal, time\\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\\ntime.sleep(120)'])\n"
            f"    open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
            "    with capsys.disabled():\n"
            "        os.write(1, b'\\nprogress before timeout \\xff\\xfe\\n')\n"
            "        os.write(2, b'stderr progress \\xc3\\x28\\n')\n"
            "    time.sleep(120)\n"
        )
        step = VerificationStep("slow", ".", ".", "test", "pytest", "pytest", "controlled_execution",
                                execution_budget_seconds=4)

        result = build_default_registry().execute_step(step, str(project))

        assert result.status == TIMEOUT.value, result.diagnostics
        assert result.status != TOOL_UNAVAILABLE.value
        assert result.timed_out is True and result.passed is False
        assert result.return_code == TIMEOUT_RETURN_CODE
        assert pid_file.exists(), "the runner timed out before reaching the external work"
        assert "progress before timeout \ufffd\ufffd" in result.stdout
        assert "stderr progress \ufffd(" in result.stderr
        assert _wait_gone(int(pid_file.read_text()))

        executor = _ScriptedReviewerExecutor("accepted")
        cycle = _VerificationCycle(TestingStage(DiagnosisReviewer(executor)), (result,))
        routed = ControlledReworkStage(cycle).run(SimpleNamespace(run_id="r"))
        assert routed.status == VERIFICATION_TIMEOUT
        assert routed.rework_executed is False and cycle.runs == 1

    def test_output_handling_error_is_never_reported_as_unavailable_tool(self, tmp_path, monkeypatch):
        """_safe_exec maps only a boundary rejection to "unavailable"; an
        output-handling error surfaces as an execution error instead."""
        def undecodable(*_args, **_kwargs):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

        monkeypatch.setattr(_execution, "execute_controlled", undecodable)
        step = VerificationStep("s", ".", ".", "test", "pytest", "pytest", "controlled_execution",
                                execution_budget_seconds=5)

        result = build_default_registry().execute_step(step, str(tmp_path))

        assert result.status == EXECUTION_ERROR.value
        assert result.status != TOOL_UNAVAILABLE.value

    @posix_only
    def test_real_runner_timeout_through_registry_is_structured_timeout(self, tmp_path):
        pid_file = tmp_path / "descendant.pid"
        project = tmp_path / "project"
        project.mkdir()
        (project / "test_slow.py").write_text(
            "import subprocess, sys, time\n"
            "def test_slow():\n"
            + textwrap.indent(_SLOW_TREE_SCRIPT.format(pid_file=str(pid_file)), "    ")
        )
        step = VerificationStep("slow", ".", ".", "test", "pytest", "pytest", "controlled_execution",
                                execution_budget_seconds=3)

        result = build_default_registry().execute_step(step, str(project))

        assert result.status == TIMEOUT.value
        assert result.timed_out is True and result.passed is False
        assert result.return_code == TIMEOUT_RETURN_CODE
        assert isinstance(result.stdout, str) and isinstance(result.stderr, str)
        assert _wait_gone(int(pid_file.read_text()))


def _step_result(step_id, status, *, timed_out=False, return_code=None):
    return VerificationStepResult(
        step_id=step_id, area=".", status=status, verification_kind="compile",
        runner_type="generic", passed=status == PASS.value,
        return_code=return_code, timed_out=timed_out,
        stdout="[512/1024] building" if timed_out else "", diagnostics=status,
    )


_TIMEOUT_STEP = _step_result("compile", TIMEOUT.value, timed_out=True, return_code=TIMEOUT_RETURN_CODE)


class _ScriptedReviewerExecutor:
    def __init__(self, *decisions):
        self._decisions = list(decisions)
        self.calls = 0

    def run(self, *_args, **_kwargs):
        self.calls += 1
        return json.dumps({"decision": self._decisions.pop(0), "summary": "diagnosis"})


class _VerificationCycle:
    """One S4/S5 cycle whose S5 part is real: verification step results ->
    real _test_result_from_verification -> real TestingStage."""

    def __init__(self, testing_stage, *step_results_per_cycle):
        self._testing_stage = testing_stage
        self._cycles = list(step_results_per_cycle)
        self.runs = 0

    def run(self, request):
        self.runs += 1
        steps = self._cycles.pop(0)
        test_result = _test_result_from_verification(steps)
        stage_result = self._testing_stage.run("development", test_result)
        return DevelopmentTestingResult("development", None, None, test_result, stage_result)


class TestTimeoutReworkClassification:
    """ARC_026 / IF_REQ_026: TIMEOUT is a fail-closed non-PASS outcome that
    only a diagnosed source-correctable cause may send to S5 -> S4."""

    def test_timeout_is_never_pass(self):
        assert _TIMEOUT_STEP.passed is False
        assert _aggregate((_TIMEOUT_STEP,)) == FAIL.value
        assert _test_result_from_verification((_TIMEOUT_STEP,)).passed is False

    @pytest.mark.parametrize("steps", [
        (_TIMEOUT_STEP,),
        (_TIMEOUT_STEP, _step_result("after", BLOCKED.value)),
    ])
    def test_timeout_without_source_diagnosis_does_not_consume_rework(self, steps):
        executor = _ScriptedReviewerExecutor("accepted")
        cycle = _VerificationCycle(TestingStage(DiagnosisReviewer(executor)), steps)

        result = ControlledReworkStage(cycle).run(SimpleNamespace(run_id="r"))

        assert cycle.runs == 1
        assert result.rework_executed is False
        assert result.status == VERIFICATION_TIMEOUT
        test_result = result.final_result.test_result
        assert test_result.timed_out is True and test_result.passed is False
        # the synthetic timeout marker stays attributable to its step
        timed_out = [f for f in test_result.step_failures if f.timed_out]
        assert [f.return_code for f in timed_out] == [TIMEOUT_RETURN_CODE]

    def test_timeout_with_unavailable_diagnosis_does_not_consume_rework(self):
        class Raising:
            def run(self, *_a, **_k):
                raise RuntimeError("provider unavailable")

        cycle = _VerificationCycle(TestingStage(DiagnosisReviewer(Raising())), (_TIMEOUT_STEP,))
        result = ControlledReworkStage(cycle).run(SimpleNamespace(run_id="r"))
        assert (cycle.runs, result.rework_executed, result.status) == (1, False, VERIFICATION_TIMEOUT)

    def test_diagnosed_source_correctable_timeout_uses_at_most_one_rework(self):
        executor = _ScriptedReviewerExecutor("rework_required", "rework_required")
        cycle = _VerificationCycle(TestingStage(DiagnosisReviewer(executor)), (_TIMEOUT_STEP,), (_TIMEOUT_STEP,))

        result = ControlledReworkStage(cycle).run(SimpleNamespace(run_id="r"))

        assert cycle.runs == 2 and executor.calls == 2
        assert result.rework_executed is True
        assert result.initial_result.status == "rework_required"
        assert "source-correctable" in result.rework_request.reason
        # the one bounded rework is spent; its outcome is final
        assert result.status == "rework_required"
        assert result.final_result is result.rework_result

    def test_real_failure_alongside_timeout_still_forces_rework(self):
        executor = _ScriptedReviewerExecutor("accepted", "accepted")
        failing = (_TIMEOUT_STEP, _step_result("lint", FAIL.value, return_code=1))
        cycle = _VerificationCycle(TestingStage(DiagnosisReviewer(executor)), failing, (_TIMEOUT_STEP,))

        result = ControlledReworkStage(cycle).run(SimpleNamespace(run_id="r"))

        assert result.rework_executed is True
        assert result.initial_result.status == "rework_required"
        assert result.status == VERIFICATION_TIMEOUT
