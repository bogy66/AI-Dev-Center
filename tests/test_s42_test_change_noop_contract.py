"""Regressions for CLAUDE-ADC-S42-TEST-CHANGE-NOOP-CONTRACT-FIX-001.

Establishes the explicit S4.2 Test Change Generation no-op contract:
a tester may declare `disposition: "no_changes_required"` with a
non-empty `reason` when existing repository tests/verification already
sufficiently cover the task, bypassing S4.3 Change Application entirely
(there is no apply attempt to classify) and proceeding straight to S5.
An empty `changes` array alone, without this explicit declaration,
remains fail-closed exactly as before -- distinguishing "no mutation
required" from "required mutation not produced" is never inferred from
emptiness, only from an explicit, evidenced declaration.
"""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.change_application import ChangeApplicationService
from app.controlled_rework_stage import ControlledReworkStage
from app.developer_file_applier import DeveloperFileApplier
from app.development_stage import DeveloperAgent, DevelopmentRequest, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.structured_change_generation import generate_structured_changes
from app.test_change_generator import TestChangeDisposition, TestChangeGenerator
from app.testing_stage import DiagnosisReviewer, TestingStage
from app.verification import FAIL, PASS, VerificationResult, VerificationStepResult


def _passing_step(step_id="unit"):
    return VerificationStepResult(
        step_id=step_id, area="root", status=PASS.value, verification_kind="test",
        runner_type="pytest", passed=True, return_code=0, stdout="", stderr="",
        command=("pytest",), timed_out=False,
    )


def _failing_step(step_id="unit"):
    return VerificationStepResult(
        step_id=step_id, area="root", status=FAIL.value, verification_kind="test",
        runner_type="pytest", passed=False, return_code=1, stdout="boom", stderr="",
        command=("pytest",), timed_out=False,
    )


def _stage(development_stage, test_change_generator, project_test_runner=None, testing_stage=None,
           verification_registry=None, project_inspector=None, change_application=None):
    return DevelopmentTestingStage(
        development_stage, test_change_generator, DeveloperFileApplier,
        project_test_runner or Mock(), testing_stage or Mock(),
        verification_registry=verification_registry, project_inspector=project_inspector,
        change_application=change_application,
    )


def _accepted_environment():
    verification_registry = Mock()
    verification_registry.execute_plan.return_value = VerificationResult(
        run_id="r", steps=(_passing_step(),), aggregate_status=PASS.value,
    )
    testing_stage = Mock()
    testing_stage.run.return_value = SimpleNamespace(status="accepted", rework_request=None)
    project_inspector = Mock()
    project_inspector.build_intelligence.return_value = None
    return verification_registry, testing_stage, project_inspector


# ---------------------------------------------------------------------
# A: development empty changes remains fail-closed
# ---------------------------------------------------------------------

def test_a_development_empty_changes_remains_fail_closed(tmp_path):
    executor = Mock()
    executor.run.return_value = json.dumps({"changes": [], "tests": []})
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = Mock()
    stage = _stage(development_stage, test_change_generator)

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    test_change_generator.generate.assert_not_called()
    assert result.status == "apply_failed"
    assert result.failure_stage == "development_apply"


# ---------------------------------------------------------------------
# B: explicit no-op bypasses S4.3 entirely and reaches S5
# ---------------------------------------------------------------------

def test_b_explicit_no_changes_required_bypasses_application_and_reaches_s5(tmp_path):
    class FakeExecutor:
        def run(self, role, content, context, role_again):
            if role == "developer":
                return json.dumps({"changes": [{"file": "feature.py", "action": "create", "content": "x"}], "tests": []})
            if role == "tester":
                return json.dumps({
                    "disposition": "no_changes_required",
                    "reason": "Existing repository tests already cover the requested behavior.",
                    "changes": [], "tests": [],
                })
            raise AssertionError(f"unexpected role: {role}")

    executor = FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    change_application = Mock()
    verification_registry, testing_stage, project_inspector = _accepted_environment()
    project_test_runner = Mock()
    stage = _stage(development_stage, test_change_generator, project_test_runner, testing_stage,
                   verification_registry, project_inspector, change_application=change_application)

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    change_application.apply.assert_not_called()
    verification_registry.execute_plan.assert_called_once()
    testing_stage.run.assert_called_once()
    assert result.apply_result is None
    assert result.test_changes["disposition"] == "no_changes_required"
    assert result.test_changes["reason"] == "Existing repository tests already cover the requested behavior."
    assert result.status == "accepted"
    assert result.failure_stage is None


# ---------------------------------------------------------------------
# C: empty changes with no disposition -> fail closed before S5
# ---------------------------------------------------------------------

def test_c_empty_test_changes_with_no_disposition_fails_closed(tmp_path):
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
    verification_registry, testing_stage, project_inspector = _accepted_environment()
    stage = _stage(development_stage, test_change_generator, Mock(), testing_stage,
                   verification_registry, project_inspector)

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    verification_registry.execute_plan.assert_not_called()
    testing_stage.run.assert_not_called()
    assert result.status == "apply_failed"
    assert result.failure_stage == "test_apply"


# ---------------------------------------------------------------------
# D: disposition="changes" with empty changes -> fail closed before S5
# ---------------------------------------------------------------------

def test_d_explicit_disposition_changes_with_empty_changes_fails_closed(tmp_path):
    class FakeExecutor:
        def run(self, role, content, context, role_again):
            if role == "developer":
                return json.dumps({"changes": [{"file": "feature.py", "action": "create", "content": "x"}], "tests": []})
            if role == "tester":
                return json.dumps({"disposition": "changes", "changes": [], "tests": []})
            raise AssertionError(f"unexpected role: {role}")

    executor = FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    verification_registry, testing_stage, project_inspector = _accepted_environment()
    stage = _stage(development_stage, test_change_generator, Mock(), testing_stage,
                   verification_registry, project_inspector)

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    verification_registry.execute_plan.assert_not_called()
    testing_stage.run.assert_not_called()
    assert result.status == "apply_failed"
    assert result.failure_stage == "test_apply"


# ---------------------------------------------------------------------
# E-H: semantic contract violations fail closed immediately (no second
# repair pass -- these are unit-level, directly against TestChangeGenerator)
# ---------------------------------------------------------------------

def test_e_no_changes_required_with_nonempty_changes_is_invalid():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "disposition": "no_changes_required",
        "reason": "claims no-op but also proposes a change",
        "changes": [{"file": "sneaky.py", "action": "create", "content": "x"}],
        "tests": [],
    })

    with pytest.raises(ValueError, match="must not include changes"):
        TestChangeGenerator(executor).generate(Mock(task="task"))


def test_f_no_changes_required_with_missing_reason_is_invalid():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "disposition": "no_changes_required", "changes": [], "tests": [],
    })

    with pytest.raises(ValueError, match="non-empty reason"):
        TestChangeGenerator(executor).generate(Mock(task="task"))


def test_g_no_changes_required_with_blank_reason_is_invalid():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "disposition": "no_changes_required", "reason": "   ", "changes": [], "tests": [],
    })

    with pytest.raises(ValueError, match="non-empty reason"):
        TestChangeGenerator(executor).generate(Mock(task="task"))


def test_h_unknown_disposition_is_invalid():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "disposition": "skip_everything", "changes": [], "tests": [],
    })

    with pytest.raises(ValueError, match="unknown disposition"):
        TestChangeGenerator(executor).generate(Mock(task="task"))


def test_semantic_violations_do_not_trigger_a_second_repair_attempt():
    """Exactly one provider call for a structurally valid but semantically
    contradictory response -- generate_structured_changes' own repair
    policy is for structural/JSON malformation only."""
    executor = Mock()
    executor.run.return_value = json.dumps({
        "disposition": "no_changes_required", "changes": [], "tests": [],
    })

    with pytest.raises(ValueError, match="non-empty reason"):
        TestChangeGenerator(executor).generate(Mock(task="task"))

    assert executor.run.call_count == 1


# ---------------------------------------------------------------------
# I: normal non-empty test mutation, fully applied -> unchanged
# ---------------------------------------------------------------------

def test_i_normal_test_mutation_fully_applied_is_unchanged(tmp_path):
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
    verification_registry, testing_stage, project_inspector = _accepted_environment()
    stage = _stage(development_stage, test_change_generator, Mock(), testing_stage,
                   verification_registry, project_inspector)

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    verification_registry.execute_plan.assert_called_once()
    testing_stage.run.assert_called_once()
    assert result.apply_result == {"applied": ["test_feature.py"], "skipped": []}
    assert result.status == "accepted"
    assert (tmp_path / "test_feature.py").exists()


# ---------------------------------------------------------------------
# J: required test mutation partially/skipped -> unchanged apply_failed
# ---------------------------------------------------------------------

def test_j_partial_test_mutation_remains_apply_failed(tmp_path):
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
    verification_registry, testing_stage, project_inspector = _accepted_environment()
    stage = _stage(development_stage, test_change_generator, Mock(), testing_stage,
                   verification_registry, project_inspector)

    result = stage.run(DevelopmentRequest("project", tmp_path, "task"))

    verification_registry.execute_plan.assert_not_called()
    testing_stage.run.assert_not_called()
    assert result.status == "apply_failed"
    assert result.failure_stage == "test_apply"
    assert (tmp_path / "existing.py").read_text() == "STALE"


# ---------------------------------------------------------------------
# K: rework cycle honors the identical no-op contract
# ---------------------------------------------------------------------

def test_k_rework_cycle_no_changes_required_is_honored_identically(tmp_path):
    calls = {"developer": 0, "tester": 0, "reviewer": 0}

    class FakeExecutor:
        def run(self, role, content, context, role_again):
            if role == "developer":
                calls["developer"] += 1
                return json.dumps({
                    "changes": [{"file": f"feature_{calls['developer']}.py", "action": "create", "content": "x"}],
                    "tests": [],
                })
            if role == "tester":
                calls["tester"] += 1
                if calls["tester"] == 1:
                    return json.dumps({
                        "changes": [{"file": "test_feature.py", "action": "create", "content": "def test_x(): assert False"}],
                        "tests": [],
                    })
                # Rework: the diagnosed fix is purely production code --
                # the already-existing test file suffices to verify it.
                return json.dumps({
                    "disposition": "no_changes_required",
                    "reason": "The existing test already exercises the fixed behavior.",
                    "changes": [], "tests": [],
                })
            if role == "reviewer":
                calls["reviewer"] += 1
                decision = "rework_required" if calls["reviewer"] == 1 else "accepted"
                return json.dumps({"decision": decision, "summary": f"cycle {calls['reviewer']}"})
            raise AssertionError(f"unexpected role: {role}")

    executor = FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    testing_stage = TestingStage(DiagnosisReviewer(executor))
    project_test_runner = Mock()

    verification_results = iter([
        VerificationResult(run_id="r1", steps=(_failing_step(),), aggregate_status=FAIL.value),
        VerificationResult(run_id="r2", steps=(_passing_step(),), aggregate_status=PASS.value),
    ])
    verification_registry = Mock()
    verification_registry.execute_plan.side_effect = lambda plan: next(verification_results)
    project_inspector = Mock()
    project_inspector.build_intelligence.return_value = None

    stage = _stage(development_stage, test_change_generator, project_test_runner, testing_stage,
                   verification_registry, project_inspector)

    result = ControlledReworkStage(stage).run(DevelopmentRequest("project", tmp_path, "task"))

    assert result.rework_executed is True
    assert result.status == "accepted"
    assert result.rework_result.apply_result is None
    assert result.rework_result.test_changes["disposition"] == "no_changes_required"
    assert result.rework_result.test_changes["reason"] == "The existing test already exercises the fixed behavior."
    assert verification_registry.execute_plan.call_count == 2
    assert calls["tester"] == 2


# ---------------------------------------------------------------------
# L: productive boundary -- real files, real DeveloperFileApplier/
# ChangeApplicationService, existing-repository no-op scenario
# ---------------------------------------------------------------------

def test_l_productive_existing_repository_noop_leaves_existing_test_untouched(tmp_path):
    existing_test = tmp_path / "test_feature.py"
    existing_test.write_text("def test_feature():\n    assert True  # already covers this\n")

    class FakeExecutor:
        def run(self, role, content, context, role_again):
            if role == "developer":
                return json.dumps({
                    "changes": [{"file": "feature.py", "action": "create", "content": "def feature(): return 42"}],
                    "tests": [],
                })
            if role == "tester":
                return json.dumps({
                    "disposition": "no_changes_required",
                    "reason": "test_feature.py already covers this behavior.",
                    "changes": [], "tests": [],
                })
            raise AssertionError(f"unexpected role: {role}")

    executor = FakeExecutor()
    development_stage = DevelopmentStage(DeveloperAgent(executor))
    test_change_generator = TestChangeGenerator(executor)
    verification_registry, testing_stage, project_inspector = _accepted_environment()
    project_test_runner = Mock()
    stage = _stage(development_stage, test_change_generator, project_test_runner, testing_stage,
                   verification_registry, project_inspector)

    result = stage.run(DevelopmentRequest("project", tmp_path, "implement feature"))

    assert existing_test.read_text() == "def test_feature():\n    assert True  # already covers this\n"
    assert result.apply_result is None
    verification_registry.execute_plan.assert_called_once()
    project_test_runner.run.assert_not_called()
    assert result.status == "accepted"
    assert (tmp_path / "feature.py").read_text() == "def feature(): return 42"


# ---------------------------------------------------------------------
# Backward compatibility of the shared parser / enum default
# ---------------------------------------------------------------------

def test_disposition_defaults_to_changes_when_absent():
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [{"file": "x.py", "action": "create", "content": "y"}], "tests": [],
    })

    result = TestChangeGenerator(executor).generate(Mock(task="task"))

    assert result["disposition"] == TestChangeDisposition.CHANGES.value == "changes"


def test_developer_agent_response_is_unaffected_by_disposition_field():
    """DeveloperChanges.parse_structured() mechanically preserves an
    optional disposition/reason without ever requiring or interpreting
    them -- confirmed here via the shared generator directly, used the
    way DeveloperAgent uses it (no disposition semantics applied)."""
    executor = Mock()
    executor.run.return_value = json.dumps({
        "changes": [{"file": "x.py", "action": "create", "content": "y"}], "tests": [],
    })

    result = generate_structured_changes(executor, "developer", "task", "changes")

    assert "disposition" not in result
    assert result["changes"][0]["file"] == "x.py"
