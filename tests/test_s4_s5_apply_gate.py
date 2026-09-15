"""Regressions for CLAUDE-ADC-S4-S5-APPLY-GATE-ARCH-FIX-001.

Confirmed defect: DevelopmentTestingStage computed development_result.status
("success"|"apply_failed", from S4.3 ChangeApplicationService) and the test
apply_result, but never inspected either before invoking S5 Quality &
Verification. A required development or test-file mutation that was
skipped/partially applied let verification run against unintended or stale
project state and could still reach "accepted" -- a false positive.

These tests use REAL DeveloperFileApplier and real temporary files for the
collision scenarios (never an invented apply_failed status from a mock),
faking only the LLM executor and, where irrelevant to the scenario, the
verification/testing boundary -- satisfying the productive-boundary
requirement across the collision regressions rather than as one isolated
test.
"""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from app.change_application import ChangeApplicationService
from app.controlled_rework_stage import ControlledReworkStage
from app.developer_file_applier import DeveloperFileApplier
from app.development_stage import DeveloperAgent, DevelopmentRequest, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.test_change_generator import TestChangeGenerator
from app.testing_stage import DiagnosisReviewer, TestingStage
from app.verification import FAIL, PASS, VerificationResult, VerificationStepResult


def _stage(development_stage, test_change_generator, project_test_runner=None, testing_stage=None,
           verification_registry=None, project_inspector=None):
    return DevelopmentTestingStage(
        development_stage, test_change_generator, DeveloperFileApplier,
        project_test_runner or Mock(), testing_stage or Mock(),
        verification_registry=verification_registry, project_inspector=project_inspector,
    )


# ---------------------------------------------------------------------
# 1: development apply failure -- initial cycle
# ---------------------------------------------------------------------

def test_development_apply_failure_gates_before_verification(tmp_path):
    collision = tmp_path / "already_there.py"
    collision.write_text("STALE")
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [{"file": "already_there.py", "action": "create", "content": "NEW"}],
        "tests": [],
    })
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = Mock()
    project_test_runner = Mock()
    testing_stage = Mock()
    verification_registry = Mock()
    project_inspector = Mock()
    stage = _stage(development_stage, test_change_generator, project_test_runner, testing_stage,
                   verification_registry, project_inspector)

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    assert result.development_result.status == "apply_failed"
    test_change_generator.generate.assert_not_called()
    project_inspector.build_intelligence.assert_not_called()
    verification_registry.execute_plan.assert_not_called()
    project_test_runner.run.assert_not_called()
    testing_stage.run.assert_not_called()
    assert result.status == "apply_failed"
    assert result.failure_stage == "development_apply"
    assert result.test_changes is None
    assert result.apply_result is None
    assert collision.read_text() == "STALE"


# ---------------------------------------------------------------------
# 2: test apply failure -- initial cycle. Reproduces the exact
# false-positive class the architecture review found: the colliding
# test file stays stale, but the pipeline can no longer reach accepted.
# ---------------------------------------------------------------------

def test_test_apply_failure_gates_before_verification_and_leaves_stale_file_untouched(tmp_path):
    stale_test = tmp_path / "test_feature.py"
    stale_test.write_text("def test_feature():\n    assert True  # STALE, never updated\n")

    class FakeExecutor:
        def run(self, role, content, context, role_again):
            if role == "developer":
                return json.dumps({
                    "changes": [{"file": "feature.py", "action": "create", "content": "def feature(): return 42"}],
                    "tests": [],
                })
            if role == "tester":
                return json.dumps({
                    "changes": [{
                        "file": "test_feature.py", "action": "create",
                        "content": "def test_feature():\n    assert False  # intended fix\n",
                    }],
                    "tests": [],
                })
            raise AssertionError(f"unexpected role: {role}")

    executor = FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    project_test_runner = Mock()
    testing_stage = Mock()
    verification_registry = Mock()
    project_inspector = Mock()
    stage = _stage(development_stage, test_change_generator, project_test_runner, testing_stage,
                   verification_registry, project_inspector)

    result = stage.run(DevelopmentRequest("project", tmp_path, "fix the feature"))

    assert result.apply_result == {
        "applied": [], "skipped": [{"file": "test_feature.py", "reason": "already_exists"}],
    }
    project_inspector.build_intelligence.assert_not_called()
    verification_registry.execute_plan.assert_not_called()
    project_test_runner.run.assert_not_called()
    testing_stage.run.assert_not_called()
    assert result.status == "apply_failed"
    assert result.failure_stage == "test_apply"
    assert stale_test.read_text() == "def test_feature():\n    assert True  # STALE, never updated\n"


# ---------------------------------------------------------------------
# 3: partial application -- at least one applied, at least one skipped
# ---------------------------------------------------------------------

def test_partial_test_application_gates_before_verification(tmp_path):
    (tmp_path / "existing.py").write_text("STALE")

    class FakeExecutor:
        def run(self, role, content, context, role_again):
            if role == "developer":
                return json.dumps({"changes": [{"file": "feature.py", "action": "create", "content": "x"}], "tests": []})
            if role == "tester":
                return json.dumps({
                    "changes": [
                        {"file": "new_test.py", "action": "create", "content": "def test_new(): pass"},
                        {"file": "existing.py", "action": "create", "content": "NEW"},
                    ],
                    "tests": [],
                })
            raise AssertionError(f"unexpected role: {role}")

    executor = FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    verification_registry = Mock()
    project_test_runner = Mock()
    testing_stage = Mock()
    stage = _stage(development_stage, test_change_generator, project_test_runner, testing_stage,
                   verification_registry, Mock())

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    assert result.apply_result["applied"] == ["new_test.py"]
    assert len(result.apply_result["skipped"]) == 1
    verification_registry.execute_plan.assert_not_called()
    project_test_runner.run.assert_not_called()
    testing_stage.run.assert_not_called()
    assert result.status == "apply_failed"
    assert result.failure_stage == "test_apply"
    assert (tmp_path / "new_test.py").exists()
    assert (tmp_path / "existing.py").read_text() == "STALE"


# ---------------------------------------------------------------------
# 4: empty required change-set classification -- preserve the existing
# S4.3 contract (empty applied stays apply_failed) and ensure it cannot
# reach S5.
# ---------------------------------------------------------------------

def test_empty_test_change_set_is_classified_apply_failed_and_gated(tmp_path):
    class FakeExecutor:
        def run(self, role, content, context, role_again):
            if role == "developer":
                return json.dumps({"changes": [{"file": "feature.py", "action": "create", "content": "x"}], "tests": []})
            if role == "tester":
                return json.dumps({"changes": [], "tests": []})
            raise AssertionError(f"unexpected role: {role}")

    executor = FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    verification_registry = Mock()
    project_test_runner = Mock()
    testing_stage = Mock()
    stage = _stage(development_stage, test_change_generator, project_test_runner, testing_stage,
                   verification_registry, Mock())

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    assert result.apply_result == {"applied": [], "skipped": []}
    assert ChangeApplicationService.status_for(result.apply_result) == "apply_failed"
    verification_registry.execute_plan.assert_not_called()
    project_test_runner.run.assert_not_called()
    testing_stage.run.assert_not_called()
    assert result.status == "apply_failed"
    assert result.failure_stage == "test_apply"


# ---------------------------------------------------------------------
# 5: successful path -- unchanged S5 behavior
# ---------------------------------------------------------------------

def test_successful_application_reaches_verification_and_testing_unchanged(tmp_path):
    class FakeExecutor:
        def run(self, role, content, context, role_again):
            if role == "developer":
                return json.dumps({"changes": [{"file": "feature.py", "action": "create", "content": "x"}], "tests": []})
            if role == "tester":
                return json.dumps({"changes": [{"file": "test_feature.py", "action": "create", "content": "def test_x(): pass"}], "tests": []})
            raise AssertionError(f"unexpected role: {role}")

    executor = FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    passing_step = VerificationStepResult(
        step_id="unit", area="root", status=PASS.value, verification_kind="test",
        runner_type="pytest", passed=True, return_code=0, stdout="", stderr="",
        command=("pytest",), timed_out=False,
    )
    verification_registry = Mock()
    verification_registry.execute_plan.return_value = VerificationResult(
        run_id="r", steps=(passing_step,), aggregate_status=PASS.value,
    )
    project_test_runner = Mock()
    testing_stage = Mock()
    testing_stage.run.return_value = SimpleNamespace(status="accepted", rework_request=None)
    project_inspector = Mock()
    project_inspector.build_intelligence.return_value = None
    stage = _stage(development_stage, test_change_generator, project_test_runner, testing_stage,
                   verification_registry, project_inspector)

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    verification_registry.execute_plan.assert_called_once()
    testing_stage.run.assert_called_once()
    project_test_runner.run.assert_not_called()
    assert result.status == "accepted"
    assert result.failure_stage is None


# ---------------------------------------------------------------------
# 6: initial apply failure under ControlledReworkStage -- zero rework
# cycle, final status apply_failed
# ---------------------------------------------------------------------

def test_controlled_rework_stage_never_starts_a_cycle_after_initial_apply_failure(tmp_path):
    (tmp_path / "already_there.py").write_text("STALE")
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [{"file": "already_there.py", "action": "create", "content": "NEW"}],
        "tests": [],
    })
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = Mock()
    stage = _stage(development_stage, test_change_generator)

    result = ControlledReworkStage(stage).run(DevelopmentRequest("project", tmp_path, "task"))

    test_change_generator.generate.assert_not_called()
    assert result.rework_executed is False
    assert result.status == "apply_failed"


# ---------------------------------------------------------------------
# 7: rework application failure -- one legitimate S5-driven rework
# cycle, whose OWN development application then fails. Fail-closed,
# no third cycle, initial S5 evidence remains inspectable.
# ---------------------------------------------------------------------

def test_rework_cycle_application_failure_terminates_fail_closed(tmp_path):
    calls = {"developer": 0, "tester": 0}

    class FakeExecutor:
        def run(self, role, content, context, role_again):
            if role == "developer":
                calls["developer"] += 1
                if calls["developer"] == 1:
                    return json.dumps({"changes": [{"file": "feature.py", "action": "create", "content": "v1"}], "tests": []})
                # Rework attempt: the LLM mistakenly re-issues "create" for
                # the file it already created in the initial cycle instead
                # of "update" -- a realistic collision this gate must catch.
                return json.dumps({"changes": [{"file": "feature.py", "action": "create", "content": "v2"}], "tests": []})
            if role == "tester":
                calls["tester"] += 1
                return json.dumps({
                    "changes": [{"file": f"test_feature_{calls['tester']}.py", "action": "create", "content": "def test_x(): pass"}],
                    "tests": [],
                })
            if role == "reviewer":
                return json.dumps({"decision": "rework_required", "summary": "needs fixing"})
            raise AssertionError(f"unexpected role: {role}")

    executor = FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    project_test_runner = Mock()
    testing_stage = TestingStage(DiagnosisReviewer(executor))
    failing_step = VerificationStepResult(
        step_id="unit", area="root", status=FAIL.value, verification_kind="test",
        runner_type="pytest", passed=False, return_code=1, stdout="boom", stderr="",
        command=("pytest",), timed_out=False,
    )
    verification_registry = Mock()
    verification_registry.execute_plan.return_value = VerificationResult(
        run_id="r", steps=(failing_step,), aggregate_status=FAIL.value,
    )
    project_inspector = Mock()
    project_inspector.build_intelligence.return_value = None
    stage = _stage(development_stage, test_change_generator, project_test_runner, testing_stage,
                   verification_registry, project_inspector)

    result = ControlledReworkStage(stage).run(DevelopmentRequest("project", tmp_path, "task"))

    assert result.rework_executed is True
    assert result.status == "apply_failed"
    # The rework cycle's own development apply failed before test
    # generation, verification, or diagnosis were ever reached again.
    assert calls["developer"] == 2
    assert calls["tester"] == 1
    assert verification_registry.execute_plan.call_count == 1
    # Original S5 evidence that triggered rework remains inspectable.
    assert result.initial_result.status == "rework_required"
    assert result.rework_request is not None
    assert result.rework_result.status == "apply_failed"
    assert result.rework_result.failure_stage == "development_apply"
