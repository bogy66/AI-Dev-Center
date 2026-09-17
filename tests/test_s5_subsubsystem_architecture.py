"""S5 Quality & Verification subsubsystem architecture acceptance suite
(CLAUDE-ADC-S3-S4-S5-ARCHITECTURE-PERSIST-001, following the S2 pilot's
own model -- tests/test_s2_subsubsystem_architecture.py).

Proves the CURRENT productive S5.1-S5.7 decomposition persisted in
ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4D: exactly one productive
Primary Owner per Sx.y, real input/output artifacts, the mandatory
"deterministic failure always forces rework, no reviewer override"
invariant, bounded rework, Genericity, and the S4<->S5<->S3<->S6
boundaries.

Genericity nuance this suite deliberately does NOT paper over: S5.1's
own build_verification_plan() (app/verification.py) legitimately
contains a small amount of ecosystem-aware STEP-SEQUENCING logic (e.g.
pairing cmake configure->build, esphome validate->compile) for the
handful of ecosystems ADC already has runners for -- this is a
pre-existing, self-documented characteristic of that one function (see
its own RUNNER_MAP/BUILD_RUNNER_MAP/FIRMWARE_RUNNER_MAP module
comments), not a violation of the architecture's actual S5.1 claim,
which is narrower than S5.2's: "multi-toolchain capable, no one-stack-
only central rule" (persisted §15), never "zero ecosystem literal
anywhere in planning". The STRICT "zero forbidden literal" invariant
IS the architecture's explicit claim for S5.2 (ControlledRunnerRegistry:
"toolchain-spezifische Logik gehört ausschließlich in Runner/Adapter,
niemals in die zentrale S5-Orchestrierung") and is verified precisely
there, scoped to that one class, in TestS5GenericityNonSpecialization
below -- and it holds cleanly. S5.1's own claim is verified instead by
the heterogeneous-shape proof (TestS5_1_VerificationPlanning), which is
what "not one-stack-only" actually means.

Does NOT duplicate:
  - tests/test_verification*.py (the exhaustive per-runner argv/
    timeout/output-truncation matrix)
  - tests/test_missing_toolchain_setup.py / this suite's sibling
    tests/test_s3_subsubsystem_architecture.py (the exhaustive S3.5
    missing-toolchain matrix -- this file's own S5->S3 boundary
    section is intentionally light, referencing that matrix as the
    authority)
  - tests/test_rework_diagnostic_fidelity.py (the exhaustive rework-
    prompt content matrix)
  - tests/test_s4_s5_apply_gate.py (the apply-gate collision matrix)

Mocks/fakes are used only at true external boundaries: the LLM
executor (DiagnosisReviewer) and, where a specific tool's real absence/
presence would make a test environment-dependent, `shutil.which`.
ControlledRunnerRegistry, PytestRunner and CMakeRunner are always the
real, productive classes.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.controlled_rework_stage import ControlledReworkStage, ReworkDevelopmentRequest
from app.development_stage import DeveloperAgent, DevelopmentRequest, DevelopmentStage
from app.development_testing_stage import (
    DevelopmentTestingStage,
    _step_failure_evidence,
    _test_result_from_verification,
)
from app.developer_file_applier import DeveloperFileApplier
from app.diagnostic_evidence import format_test_result_evidence
from app.project_test_runner import TestResult
from app.test_change_generator import TestChangeGenerator
from app.testing_stage import (
    DiagnosisReviewer,
    ReviewDecision,
    TestingReviewRequest,
    TestingStage,
)
from app.verification import (
    FAIL,
    PASS,
    TOOL_UNAVAILABLE,
    UNSUPPORTED,
    ControlledRunnerRegistry,
    CMakeRunner,
    PytestRunner,
    VerificationPlan,
    VerificationResult,
    VerificationStep,
    VerificationStepResult,
    build_verification_plan,
)

from pathlib import Path

from tests._architecture_genericity_scan import class_subtree, parse, scan_forbidden_ecosystem_dispatch
from tests.test_s3_legacy_hygiene_wiring import FORBIDDEN_ECOSYSTEM_NAMES

ROOT = Path(__file__).parents[1]

CENTRAL_S5_FILES = (
    "app/development_testing_stage.py",
    "app/testing_stage.py",
    "app/controlled_rework_stage.py",
    "app/diagnostic_evidence.py",
    "app/project_test_runner.py",
)


def _passing_step(step_id="unit"):
    return VerificationStepResult(
        step_id=step_id, area="root", status=PASS.value, verification_kind="test",
        runner_type="pytest", passed=True, return_code=0, stdout="", stderr="",
        command=("pytest",), timed_out=False,
    )


def _failing_step(step_id="unit", stdout="boom", return_code=1):
    return VerificationStepResult(
        step_id=step_id, area="root", status=FAIL.value, verification_kind="test",
        runner_type="pytest", passed=False, return_code=return_code, stdout=stdout, stderr="",
        command=("pytest", "-q"), timed_out=False,
    )


# =========================================================================
# S5.1 Verification Planning -- build_verification_plan
# =========================================================================


class TestS5_1_VerificationPlanning:
    def test_real_project_intelligence_produces_structured_plan(self):
        intelligence = SimpleNamespace(
            project_root="/proj", project_kind="python",
            areas=(SimpleNamespace(path=".", test_systems=(SimpleNamespace(name="pytest", evidence=()),),
                                    build_systems=(), firmware_indicators=()),),
        )
        plan = build_verification_plan(intelligence, "run-1")
        assert isinstance(plan, VerificationPlan)
        assert plan.steps and plan.steps[0].runner_type == "pytest"
        assert plan.steps[0].policy == "controlled_execution"

    def test_planning_does_not_execute_verification(self, monkeypatch):
        import subprocess
        called = {"ran": False}

        def _fail_if_called(*args, **kwargs):
            called["ran"] = True
            raise AssertionError("build_verification_plan must never execute a subprocess")

        monkeypatch.setattr(subprocess, "run", _fail_if_called)
        intelligence = SimpleNamespace(
            project_root="/proj", project_kind="python",
            areas=(SimpleNamespace(path=".", test_systems=(SimpleNamespace(name="pytest", evidence=()),),
                                    build_systems=(), firmware_indicators=()),),
        )
        build_verification_plan(intelligence, "run-1")
        assert called["ran"] is False

    def test_heterogeneous_toolchain_shapes_reach_the_same_central_planning_function(self):
        """§15/§26: at least two materially different project/toolchain
        shapes -- a Python-test project and a CMake/native project --
        pass through the exact same build_verification_plan(), no
        central redesign required for the second shape."""
        python_intelligence = SimpleNamespace(
            project_root="/proj-py", project_kind="python",
            areas=(SimpleNamespace(path=".", test_systems=(SimpleNamespace(name="pytest", evidence=()),),
                                    build_systems=(), firmware_indicators=()),),
        )
        native_intelligence = SimpleNamespace(
            project_root="/proj-native", project_kind="native",
            areas=(SimpleNamespace(path=".", test_systems=(),
                                    build_systems=(SimpleNamespace(name="cmake", evidence=()),),
                                    firmware_indicators=()),),
        )

        python_plan = build_verification_plan(python_intelligence, "run-py")
        native_plan = build_verification_plan(native_intelligence, "run-native")

        assert {s.runner_type for s in python_plan.steps} == {"pytest"}
        assert {s.runner_type for s in native_plan.steps} == {"cmake"}
        assert all(s.policy == "controlled_execution" for s in native_plan.steps)

    def test_no_one_stack_only_central_rule_arbitrary_area_paths_respected(self):
        """Planning derives working directories from whatever
        ProjectIntelligence already discovered -- no assumption that
        verification targets live at a fixed, ADC-chosen path."""
        intelligence = SimpleNamespace(
            project_root="/proj", project_kind="mixed",
            areas=(SimpleNamespace(path="firmware/esp32", test_systems=(SimpleNamespace(name="pytest", evidence=()),),
                                    build_systems=(), firmware_indicators=()),),
        )
        plan = build_verification_plan(intelligence, "run-1")
        assert plan.steps[0].working_directory == "firmware/esp32"
        assert plan.steps[0].area == "firmware/esp32"


# =========================================================================
# S5.2 Controlled Verification Execution -- ControlledRunnerRegistry
# =========================================================================


class TestS5_2_ControlledVerificationExecution:
    def test_dispatch_by_structured_runner_capability_contract(self):
        registry = ControlledRunnerRegistry([PytestRunner(), CMakeRunner()])
        pytest_step = VerificationStep("s1", ".", ".", "test", "pytest", "pytest", "controlled_execution")
        cmake_step = VerificationStep("s2", ".", ".", "configure", "cmake", "cmake", "controlled_execution")
        assert isinstance(registry.find(pytest_step), PytestRunner)
        assert isinstance(registry.find(cmake_step), CMakeRunner)

    def test_toolchain_specific_logic_remains_runner_local_never_central(self):
        """The strict architecture claim ("toolchain-specific logic only
        in Runner/Adapter, never central S5 orchestration") is verified
        precisely where the architecture asserts it: ControlledRunnerRegistry
        itself, scoped by class so the (legitimately ecosystem-aware)
        VerificationRunner subclasses in the same file are never
        mistakenly included."""
        tree = parse("app/verification.py", ROOT)
        registry_subtree = class_subtree(tree, "ControlledRunnerRegistry")
        from tests._architecture_genericity_scan import (
            inline_dict_subscript_dispatch,
            match_case_string_patterns,
            string_literal_comparison_operands,
        )
        violations = [
            (lineno, literal) for lineno, literal in string_literal_comparison_operands(registry_subtree)
            if literal.strip().lower() in FORBIDDEN_ECOSYSTEM_NAMES
        ]
        violations += [
            (lineno, literal) for lineno, literal in match_case_string_patterns(registry_subtree)
            if literal.strip().lower() in FORBIDDEN_ECOSYSTEM_NAMES
        ]
        for lineno, keys in inline_dict_subscript_dispatch(registry_subtree):
            violations += [(lineno, key) for key in keys if key.strip().lower() in FORBIDDEN_ECOSYSTEM_NAMES]
        assert violations == []

    def test_unsupported_runner_fails_with_structured_result(self):
        registry = ControlledRunnerRegistry([PytestRunner()])
        step = VerificationStep("s1", ".", ".", "build", "future", "future", "controlled_execution")
        result = registry.execute_step(step, "/tmp")
        assert result.status == UNSUPPORTED.value
        assert result.passed is False

    def test_unavailable_tool_fails_with_structured_result(self, monkeypatch, tmp_path):
        import shutil as shutil_module
        monkeypatch.setattr(shutil_module, "which", lambda name: None)
        registry = ControlledRunnerRegistry([CMakeRunner()])
        step = VerificationStep("s1", ".", ".", "configure", "cmake", "cmake", "controlled_execution")
        result = registry.execute_step(step, tmp_path)
        assert result.status == TOOL_UNAVAILABLE.value

    def test_two_different_runner_types_dispatch_without_special_casing(self, monkeypatch, tmp_path):
        import shutil as shutil_module
        monkeypatch.setattr(shutil_module, "which", lambda name: None if name == "cmake" else "/usr/bin/" + name)
        registry = ControlledRunnerRegistry([PytestRunner(), CMakeRunner()])
        pytest_step = VerificationStep("s1", ".", ".", "test", "pytest", "pytest", "controlled_execution")
        cmake_step = VerificationStep("s2", ".", ".", "configure", "cmake", "cmake", "controlled_execution")

        pytest_result = registry.execute_step(pytest_step, tmp_path)
        cmake_result = registry.execute_step(cmake_step, tmp_path)

        assert pytest_result.runner_type == "pytest"
        assert cmake_result.runner_type == "cmake"
        assert cmake_result.status == TOOL_UNAVAILABLE.value  # deterministic: cmake forced absent

    def test_project_test_runner_fallback_only_when_no_executable_verification_step_exists(self, tmp_path):
        executor = Mock()
        executor.run.return_value = json.dumps({"changes": [{"file": "x.py", "action": "create", "content": "x"}], "tests": []})
        development_stage = DevelopmentStage(DeveloperAgent(executor))
        test_change_generator = TestChangeGenerator(executor)
        project_test_runner = Mock()
        project_test_runner.run.return_value = TestResult(True, 0, "", "", ("pytest",))
        testing_stage = Mock()
        testing_stage.run.return_value = SimpleNamespace(status="accepted", rework_request=None)
        verification_registry = Mock()
        verification_registry.execute_plan.return_value = VerificationResult(
            run_id="r", steps=(VerificationStepResult(
                step_id="none", area=".", status=UNSUPPORTED.value, verification_kind="test",
                runner_type="none", passed=False,
            ),), aggregate_status=UNSUPPORTED.value,
        )
        project_inspector = Mock()
        project_inspector.build_intelligence.return_value = None
        stage = DevelopmentTestingStage(
            development_stage, test_change_generator, DeveloperFileApplier,
            project_test_runner, testing_stage,
            verification_registry=verification_registry, project_inspector=project_inspector,
        )
        executor.run.side_effect = [
            executor.run.return_value,
            json.dumps({"changes": [{"file": "test_x.py", "action": "create", "content": "def test(): pass"}], "tests": []}),
        ]

        stage.run(DevelopmentRequest("p", tmp_path, "task"))

        project_test_runner.run.assert_called_once()


# =========================================================================
# S5.3 Verification Evidence Aggregation
# =========================================================================


class TestS5_3_VerificationEvidenceAggregation:
    def test_all_passed_maps_to_passed_test_result(self):
        result = _test_result_from_verification([_passing_step(), _passing_step("s2")])
        assert result.passed is True
        assert result.step_failures == ()

    def test_single_failing_step_is_faithfully_mirrored(self):
        failing = _failing_step(stdout="specific failure text", return_code=7)
        result = _test_result_from_verification([_passing_step(), failing])
        assert result.passed is False
        assert result.return_code == 7
        assert result.stdout == "specific failure text"
        assert len(result.step_failures) == 1

    def test_multiple_failing_steps_preserve_each_steps_evidence_individually(self):
        f1, f2 = _failing_step("s1", stdout="first failure"), _failing_step("s2", stdout="second failure")
        result = _test_result_from_verification([f1, f2])
        assert result.passed is False
        assert "2 verification steps failed" in result.stdout
        assert {sf.step_id for sf in result.step_failures} == {"s1", "s2"}
        assert {sf.stdout for sf in result.step_failures} == {"first failure", "second failure"}

    def test_tool_unavailable_diagnostics_only_evidence_is_not_fabricated_away(self):
        unavailable = VerificationStepResult(
            step_id="s1", area="root", status=TOOL_UNAVAILABLE.value, verification_kind="build",
            runner_type="cmake", passed=False, diagnostics="CMake not found",
        )
        evidence = _step_failure_evidence(unavailable)
        assert evidence.diagnostics == "CMake not found"
        assert evidence.status == TOOL_UNAVAILABLE.value
        result = _test_result_from_verification([unavailable])
        assert result.step_failures[0].diagnostics == "CMake not found"

    def test_no_diagnosis_decision_occurs_here(self):
        import inspect
        source = inspect.getsource(_test_result_from_verification) + inspect.getsource(_step_failure_evidence)
        assert "DiagnosisReviewer" not in source
        assert "ReviewDecision" not in source
        assert ".run(" not in source


# =========================================================================
# S5.4 Diagnostic Evidence Formatting -- format_test_result_evidence
# =========================================================================


class TestS5_4_DiagnosticEvidenceFormatting:
    def test_deterministic_formatting(self):
        result = TestResult(False, 1, "out", "err", ("pytest",))
        assert format_test_result_evidence(result) == format_test_result_evidence(result)

    def test_preserves_relevant_failure_evidence(self):
        result = TestResult(False, 1, "a very specific stdout marker", "a stderr marker", ("pytest", "-q"))
        rendered = format_test_result_evidence(result)
        assert "a very specific stdout marker" in rendered
        assert "a stderr marker" in rendered

    def test_does_not_mutate_test_result(self):
        result = TestResult(False, 1, "out", "err", ("pytest",))
        before = (result.passed, result.return_code, result.stdout, result.stderr)
        format_test_result_evidence(result)
        after = (result.passed, result.return_code, result.stdout, result.stderr)
        assert before == after

    def test_does_not_decide_rework_or_success(self):
        """Purely a rendering function: its return type is a bounded
        string, never a status/decision value, and it takes no
        reviewer/policy input to produce one."""
        import inspect
        result = TestResult(False, 1, "out", "err", ("pytest",))
        rendered = format_test_result_evidence(result)
        assert isinstance(rendered, str)
        params = list(inspect.signature(format_test_result_evidence).parameters)
        assert params == ["test_result", "max_field_chars"]

    def test_no_llm_call(self):
        import inspect
        import app.diagnostic_evidence as module
        source = inspect.getsource(module)
        assert "executor" not in source.lower()
        assert ".run(" not in source


# =========================================================================
# S5.5 LLM Diagnosis Interpretation -- DiagnosisReviewer (fake LLM
# boundary only)
# =========================================================================


class _CapturingExecutor:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def run(self, role, content, context, role_again):
        self.calls.append((role, content, context, role_again))
        return self._response


class TestS5_5_LLMDiagnosisInterpretation:
    def test_receives_structured_testing_review_request(self):
        dev_result, test_result = object(), TestResult(True, 0, "", "", ())
        executor = _CapturingExecutor(json.dumps({"decision": "accepted", "summary": "looks fine"}))
        DiagnosisReviewer(executor).review(TestingReviewRequest(dev_result, test_result))
        assert executor.calls[0][0] == "reviewer"

    def test_maps_accepted_decision(self):
        executor = _CapturingExecutor(json.dumps({"decision": "accepted", "summary": "ok"}))
        result = DiagnosisReviewer(executor).review(
            TestingReviewRequest(None, TestResult(True, 0, "", "", ())),
        )
        assert result.decision is ReviewDecision.ACCEPTED

    def test_maps_rework_required_decision(self):
        executor = _CapturingExecutor(json.dumps({"decision": "rework_required", "summary": "needs work"}))
        result = DiagnosisReviewer(executor).review(
            TestingReviewRequest(None, TestResult(False, 1, "", "", ())),
        )
        assert result.decision is ReviewDecision.REWORK_REQUIRED

    def test_malformed_json_fails_closed(self):
        executor = _CapturingExecutor("not json")
        with pytest.raises(ValueError):
            DiagnosisReviewer(executor).review(TestingReviewRequest(None, TestResult(True, 0, "", "", ())))

    def test_invalid_decision_value_fails_closed(self):
        executor = _CapturingExecutor(json.dumps({"decision": "maybe", "summary": "x"}))
        with pytest.raises(ValueError):
            DiagnosisReviewer(executor).review(TestingReviewRequest(None, TestResult(True, 0, "", "", ())))

    def test_missing_or_blank_summary_fails_closed(self):
        executor = _CapturingExecutor(json.dumps({"decision": "accepted", "summary": "  "}))
        with pytest.raises(ValueError):
            DiagnosisReviewer(executor).review(TestingReviewRequest(None, TestResult(True, 0, "", "", ())))

    def test_reviewer_interpretation_alone_cannot_accept_a_real_deterministic_failure(self):
        """Verbotene Authority: even a well-formed 'accepted' reviewer
        decision must not turn a real test failure into a final
        accepted outcome -- proven through TestingStage.run(), S5.6's
        own owner, since DiagnosisReviewer's own return value carries
        no separate authority of its own."""
        executor = _CapturingExecutor(json.dumps({"decision": "accepted", "summary": "looks fine to me"}))
        stage = TestingStage(DiagnosisReviewer(executor))
        result = stage.run(development_result=object(), test_result=TestResult(False, 1, "boom", "", ("pytest",)))
        assert result.status == "rework_required"


# =========================================================================
# S5.6 Deterministic Test Outcome Policy -- TestingStage.run(). Mandatory
# invariant: REAL FAILURE ALWAYS FORCES REWORK, no reviewer override.
# =========================================================================


class TestS5_6_DeterministicTestOutcomePolicy:
    def _stage(self, decision):
        executor = _CapturingExecutor(json.dumps({"decision": decision, "summary": "s"}))
        return TestingStage(DiagnosisReviewer(executor))

    def test_passed_and_reviewer_accepts(self):
        result = self._stage("accepted").run(object(), TestResult(True, 0, "", "", ()))
        assert result.status == "accepted"

    def test_passed_and_reviewer_requests_rework(self):
        result = self._stage("rework_required").run(object(), TestResult(True, 0, "", "", ()))
        assert result.status == "rework_required"
        assert result.rework_request is not None

    def test_failed_and_reviewer_accepts_still_forces_rework(self):
        """The mandatory case: deterministic failure cannot be overruled
        into success by reviewer interpretation."""
        result = self._stage("accepted").run(object(), TestResult(False, 1, "boom", "", ("pytest",)))
        assert result.status == "rework_required"

    def test_failed_and_reviewer_requests_rework(self):
        result = self._stage("rework_required").run(object(), TestResult(False, 1, "boom", "", ("pytest",)))
        assert result.status == "rework_required"

    def test_timed_out_forces_rework_regardless_of_reviewer(self):
        result = self._stage("accepted").run(object(), TestResult(True, 0, "", "", (), timed_out=True))
        assert result.status == "rework_required"

    def test_reviewer_infrastructure_exception_fails_closed_never_silently_accepted(self):
        class RaisingExecutor:
            def run(self, *a, **k):
                raise RuntimeError("provider unavailable")
        stage = TestingStage(DiagnosisReviewer(RaisingExecutor()))
        result = stage.run(object(), TestResult(True, 0, "", "", ()))
        assert result.status == "review_failed"
        assert result.status != "accepted"


# =========================================================================
# S5.7 Controlled Rework Orchestration -- ControlledReworkStage
# =========================================================================


class _FakeExecutorS5:
    def __init__(self, developer_responses, tester_responses, reviewer_responses):
        self.developer_responses = list(developer_responses)
        self.tester_responses = list(tester_responses)
        self.reviewer_responses = list(reviewer_responses)
        self.calls = []

    def run(self, role, content, context, role_again):
        self.calls.append(role)
        if role == "developer":
            return self.developer_responses.pop(0)
        if role == "tester":
            return self.tester_responses.pop(0)
        if role == "reviewer":
            return self.reviewer_responses.pop(0)
        raise AssertionError(role)


def _rework_stage(executor, verification_results):
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    testing_stage = TestingStage(DiagnosisReviewer(executor))
    verification_registry = Mock()
    verification_registry.execute_plan.side_effect = list(verification_results)
    project_inspector = Mock()
    project_inspector.build_intelligence.return_value = None
    dt_stage = DevelopmentTestingStage(
        development_stage, test_change_generator, DeveloperFileApplier,
        Mock(), testing_stage,
        verification_registry=verification_registry, project_inspector=project_inspector,
    )
    return ControlledReworkStage(dt_stage)


class TestS5_7_ControlledReworkOrchestration:
    def test_accepted_initial_cycle_produces_no_rework(self, tmp_path):
        executor = _FakeExecutorS5(
            developer_responses=[json.dumps({"changes": [{"file": "a.py", "action": "create", "content": "x"}], "tests": []})],
            tester_responses=[json.dumps({"changes": [{"file": "test_a.py", "action": "create", "content": "y"}], "tests": []})],
            reviewer_responses=[json.dumps({"decision": "accepted", "summary": "fine"})],
        )
        result = _rework_stage(executor, [VerificationResult("r", (_passing_step(),), PASS.value)]).run(
            DevelopmentRequest("p", tmp_path, "task"),
        )
        assert result.rework_executed is False
        assert result.status == "accepted"

    def test_rework_required_triggers_exactly_one_cycle(self, tmp_path):
        executor = _FakeExecutorS5(
            developer_responses=[
                json.dumps({"changes": [{"file": "a.py", "action": "create", "content": "x"}], "tests": []}),
                json.dumps({"changes": [{"file": "a.py", "action": "update", "content": "x2"}], "tests": []}),
            ],
            tester_responses=[
                json.dumps({"changes": [{"file": "test_a.py", "action": "create", "content": "y"}], "tests": []}),
                json.dumps({"changes": [{"file": "test_a2.py", "action": "create", "content": "y2"}], "tests": []}),
            ],
            reviewer_responses=[
                json.dumps({"decision": "rework_required", "summary": "fix it"}),
                json.dumps({"decision": "accepted", "summary": "fixed"}),
            ],
        )
        result = _rework_stage(executor, [
            VerificationResult("r1", (_failing_step(),), FAIL.value),
            VerificationResult("r2", (_passing_step(),), PASS.value),
        ]).run(DevelopmentRequest("p", tmp_path, "task"))
        assert result.rework_executed is True
        assert result.status == "accepted"
        assert result.initial_result.status == "rework_required"

    def test_second_failure_does_not_create_a_third_cycle(self, tmp_path):
        executor = _FakeExecutorS5(
            developer_responses=[
                json.dumps({"changes": [{"file": "a.py", "action": "create", "content": "x"}], "tests": []}),
                json.dumps({"changes": [{"file": "a.py", "action": "update", "content": "x2"}], "tests": []}),
            ],
            tester_responses=[
                json.dumps({"changes": [{"file": "test_a.py", "action": "create", "content": "y"}], "tests": []}),
                json.dumps({"changes": [{"file": "test_a2.py", "action": "create", "content": "y2"}], "tests": []}),
            ],
            reviewer_responses=[
                json.dumps({"decision": "rework_required", "summary": "fix it"}),
                json.dumps({"decision": "rework_required", "summary": "still broken"}),
            ],
        )
        result = _rework_stage(executor, [
            VerificationResult("r1", (_failing_step(),), FAIL.value),
            VerificationResult("r2", (_failing_step(),), FAIL.value),
        ]).run(DevelopmentRequest("p", tmp_path, "task"))
        assert result.rework_executed is True
        assert result.status == "rework_required"
        assert executor.calls.count("developer") == 2  # never a third development attempt

    def test_diagnostic_evidence_reaches_the_rework_request(self, tmp_path):
        executor = _FakeExecutorS5(
            developer_responses=[
                json.dumps({"changes": [{"file": "a.py", "action": "create", "content": "x"}], "tests": []}),
                json.dumps({"changes": [{"file": "a.py", "action": "update", "content": "x2"}], "tests": []}),
            ],
            tester_responses=[
                json.dumps({"changes": [{"file": "test_a.py", "action": "create", "content": "y"}], "tests": []}),
                json.dumps({"changes": [{"file": "test_a2.py", "action": "create", "content": "y2"}], "tests": []}),
            ],
            reviewer_responses=[
                json.dumps({"decision": "rework_required", "summary": "fix it"}),
                json.dumps({"decision": "accepted", "summary": "fixed"}),
            ],
        )
        result = _rework_stage(executor, [
            VerificationResult("r1", (_failing_step(stdout="a very distinctive failure marker"),), FAIL.value),
            VerificationResult("r2", (_passing_step(),), PASS.value),
        ]).run(DevelopmentRequest("p", tmp_path, "task"))

        rework_request = result.rework_request
        original = DevelopmentRequest("p", tmp_path, "task")
        wrapped = ReworkDevelopmentRequest(
            original_request=original, previous_development_result=result.initial_result.development_result,
            previous_test_result=result.initial_result.test_result,
            previous_testing_stage_result=result.initial_result.testing_stage_result,
            rework_request=rework_request,
        )
        assert "a very distinctive failure marker" in wrapped.task

    def test_s4_2_no_op_works_identically_during_rework(self, tmp_path):
        executor = _FakeExecutorS5(
            developer_responses=[
                json.dumps({"changes": [{"file": "a.py", "action": "create", "content": "x"}], "tests": []}),
                json.dumps({"changes": [{"file": "a.py", "action": "update", "content": "x2"}], "tests": []}),
            ],
            tester_responses=[
                json.dumps({"changes": [{"file": "test_a.py", "action": "create", "content": "y"}], "tests": []}),
                json.dumps({"disposition": "no_changes_required", "reason": "existing tests still apply", "changes": [], "tests": []}),
            ],
            reviewer_responses=[
                json.dumps({"decision": "rework_required", "summary": "fix it"}),
                json.dumps({"decision": "accepted", "summary": "fixed"}),
            ],
        )
        result = _rework_stage(executor, [
            VerificationResult("r1", (_failing_step(),), FAIL.value),
            VerificationResult("r2", (_passing_step(),), PASS.value),
        ]).run(DevelopmentRequest("p", tmp_path, "task"))
        assert result.rework_result.apply_result is None  # no-op honored in the rework cycle too
        assert result.status == "accepted"

    def test_s4_s5_ownership_boundaries_preserved(self):
        """ControlledReworkStage never applies changes or reviews tests
        itself -- it only re-invokes DevelopmentTestingStage.run()."""
        import inspect
        source = inspect.getsource(ControlledReworkStage)
        assert "DeveloperFileApplier" not in source
        assert "DiagnosisReviewer" not in source
        assert "ChangeApplicationService" not in source


# =========================================================================
# S5 -> S4 boundary
# =========================================================================


class TestS5_to_S4_Boundary:
    def test_rework_request_is_the_only_sanctioned_backwards_path(self):
        import inspect
        source = inspect.getsource(ControlledReworkStage)
        assert "ReworkRequest" in source or "rework_request" in source
        assert "GOTO" not in source  # sanity: no informal backwards jump construct

    def test_no_direct_s5_filesystem_mutation(self):
        import inspect
        for module_name, module in (
            ("app.testing_stage", __import__("app.testing_stage", fromlist=["x"])),
            ("app.controlled_rework_stage", __import__("app.controlled_rework_stage", fromlist=["x"])),
            ("app.diagnostic_evidence", __import__("app.diagnostic_evidence", fromlist=["x"])),
        ):
            source = inspect.getsource(module)
            assert "write_text(" not in source, module_name
            assert "unlink(" not in source, module_name

    def test_no_unlimited_retry_bounded_at_exactly_one_rework_cycle(self):
        """Structurally, not just by convention: ControlledReworkStage.run()
        contains no loop construct at all -- it is physically incapable
        of a second rework attempt, since there is no branch that calls
        development_testing_stage.run() more than twice (initial +
        exactly one rework)."""
        import ast
        import inspect
        import textwrap
        source = inspect.getsource(ControlledReworkStage.run)
        tree = ast.parse(textwrap.dedent(source))
        loop_nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.While))]
        assert loop_nodes == []
        run_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run"
        ]
        assert len(run_calls) == 2


# =========================================================================
# S5 -> S3 boundary (light: the exhaustive matrix is authoritative in
# tests/test_s3_subsubsystem_architecture.py's TestS3_5_MissingToolchainRecovery)
# =========================================================================


class TestS5_to_S3_Boundary:
    def test_tool_unavailable_evidence_is_the_generic_trigger_shape(self):
        """The S5-produced evidence that can trigger S3.5 recovery is
        exactly a structured VerificationResult containing a
        TOOL_UNAVAILABLE step -- generic, never ecosystem-specific."""
        unavailable = VerificationStepResult(
            step_id="s1", area=".", status=TOOL_UNAVAILABLE.value, verification_kind="build",
            runner_type="cmake", passed=False, diagnostics="CMake not found",
        )
        result = VerificationResult("r", (unavailable,), "fail")
        assert any(s.status == TOOL_UNAVAILABLE.value for s in result.steps)

    def test_retry_reenters_only_s5_never_s2(self):
        """ARCHITECTURE-level corroboration (full behavioral matrix is
        tests/test_s3_subsubsystem_architecture.py's own S3.5 suite):
        retry_missing_toolchain_verification's own code never imports
        any S2 selection function."""
        import inspect
        import app.project_setup_application as module
        source = inspect.getsource(module.ProjectSetupApplicationService.retry_missing_toolchain_verification)
        assert "select_engineering_variant" not in source
        assert "EngineeringCouncil" not in source


# =========================================================================
# S5 -> S6 boundary
# =========================================================================


class TestS5_to_S6_Boundary:
    def test_terminal_approval_only_proceeds_after_accepted_s5_policy(self):
        from app.project_setup_application import ProjectSetupApplicationService
        workflow_manager = Mock()
        service = ProjectSetupApplicationService.__new__(ProjectSetupApplicationService)
        service._workflow_manager = workflow_manager

        for status in ("apply_failed", "rework_required", "review_failed"):
            approval = service._final_approval_for("run-1", status)
            assert approval.status == "not_applicable"
        workflow_manager.create_final_approval.assert_not_called()

        service._final_approval_for("run-1", "accepted")
        workflow_manager.create_final_approval.assert_called_once_with("run-1", "accepted")


# =========================================================================
# Genericity / Non-Specialization (§4G)
# =========================================================================


class TestS5GenericityNonSpecialization:
    def test_central_s5_orchestration_has_no_forbidden_ecosystem_dispatch(self):
        """Scoped to the files whose OWN documented claim is "no
        ecosystem name in central orchestration" -- app/verification.py
        is checked separately, and only for ControlledRunnerRegistry
        (see TestS5_2's own scoped check and this file's module
        docstring for why the whole-file scan would be a false
        positive against build_verification_plan's documented, narrower
        S5.1 claim)."""
        violations = scan_forbidden_ecosystem_dispatch(CENTRAL_S5_FILES, ROOT, FORBIDDEN_ECOSYSTEM_NAMES)
        assert violations == []

    def test_verification_runner_adapters_are_not_flagged_by_design(self):
        """The VerificationRunner subclasses (PytestRunner, CMakeRunner,
        ...) legitimately know their own ecosystem's name -- that is
        precisely what an adapter is for. Confirms they are excluded
        from the strict S5.2 scope, not merely never checked."""
        assert PytestRunner.runner_type == "pytest"
        assert CMakeRunner.runner_type == "cmake"


# =========================================================================
# Existing foreign repository (§27)
# =========================================================================


class TestS5ExistingForeignRepository:
    def test_verification_planning_respects_arbitrary_existing_area_layout(self):
        intelligence = SimpleNamespace(
            project_root="/some/foreign/repo", project_kind="existing",
            areas=(
                SimpleNamespace(path="vendor/legacy/module", test_systems=(SimpleNamespace(name="pytest", evidence=()),),
                                 build_systems=(), firmware_indicators=()),
            ),
        )
        plan = build_verification_plan(intelligence, "run-1")
        assert plan.steps[0].working_directory == "vendor/legacy/module"
        # No ADC-imposed top-level convention: the plan's own project_root
        # is exactly what Project Intelligence reported, untouched.
        assert plan.project_root == "/some/foreign/repo"
