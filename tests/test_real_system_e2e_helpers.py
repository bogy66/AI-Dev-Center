"""Deterministic regression coverage for the RSE fail-fast/observability
and progress-label helpers added to tests/real_system/real_system_e2e.py
by KIB-ADC-RSE-SETUP-TRACE-DUAL-DEFECT-FIX-001 (sections 3 and 4).

tests/real_system/real_system_e2e.py is neither test_*.py-named (so
default `pytest tests/` discovery never collects it) nor runnable
without the paid --real-system-e2e flag (tests/conftest.py skips
anything marked pytest.mark.real_system). Its plain helper FUNCTIONS are
pure and deterministic -- no live LLM, no real install, no RSE run
needed -- and deserve their own always-collected regression coverage
independent of that gate. Loaded by file path (rather than a package
import) since tests/real_system/ has no __init__.py.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

_MODULE_PATH = Path(__file__).parent / "real_system" / "real_system_e2e.py"
_spec = importlib.util.spec_from_file_location(
    "real_system_e2e_module_under_test", _MODULE_PATH,
)
rse = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rse)

from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    Requirement,
    SetupPlan,
    SetupStep,
)


def _requirement(req_id, required=True, install_method="pip"):
    return Requirement(
        id=req_id, name=req_id, type="python_package", purpose="build",
        required=required, confidence=1.0, install_method=install_method,
    )


def _preflight(results, missing_requirements):
    return PreflightResult(
        id="pre-1", project_id="proj", overall_ready=True,
        results=tuple(results), missing_requirements=tuple(missing_requirements),
    )


def test_preverification_rse_failure_bundle_reports_cause_and_trace_range():
    development = SimpleNamespace(
        status="apply_failed",
        generated_changes={"changes": []},
        private_context="/private/path/source.py SOURCE_CONTENT_PRIVATE_SENTINEL",
        applied_changes=None,
        generation_evidence={
            "generated_change_count": 0,
            "repair_attempted": True,
            "apply_attempted": False,
        },
    )
    workflow = SimpleNamespace(
        development_result=development,
        verification_result=None,
        failure_stage="development_apply",
        status="apply_failed",
    )
    result = SimpleNamespace(development_testing_result=workflow)
    events = [
        SimpleNamespace(sequence=4, phase="development", event_type="started", status="started", details={}, summary="PROMPT_PRIVATE_SENTINEL"),
        SimpleNamespace(sequence=5, phase="development", event_type="failed", status="failed", details={"failure_category": "apply_failed"}, summary="RESPONSE_PRIVATE_SENTINEL"),
    ]

    bundle = rse._verification_failure_bundle(result, events, "rse-run-1")
    assert bundle is not None
    for field in (
        "run_id=rse-run-1", "workflow_status=apply_failed",
        "first_failure_stage=development_apply", "failure_category=apply_failed",
        "last_successful_stage=none", "generated_change_count=0",
        "applied_path_count=0", "skipped_path_count=0",
        "generation_attempted=True",
        "repair_attempted=True", "apply_attempted=False",
        "verification_reached=False", "trace_sequence_range=4-5",
    ):
        assert field in bundle
    for private_value in (
        "/private/path/source.py", "SOURCE_CONTENT_PRIVATE_SENTINEL",
        "PROMPT_PRIVATE_SENTINEL", "RESPONSE_PRIVATE_SENTINEL",
    ):
        assert private_value not in bundle
    try:
        rse._assert_verification_reached(result, events, "rse-run-1")
        assert False, "RSE must still fail when verification was not reached"
    except AssertionError as error:
        assert "Verification was not reached" in str(error)
        assert "generated_change_count=0" in str(error)


def test_verification_failure_report_does_not_change_success_acceptance():
    verification = object()
    result = SimpleNamespace(development_testing_result=SimpleNamespace(
        verification_result=verification,
    ))
    assert rse._verification_failure_bundle(result, [], "rse-run-2") is None
    assert rse._assert_verification_reached(result, [], "rse-run-2") is verification


def _plan(steps=(), deferred=(), provided=(), unsupported_effects=()):
    return SetupPlan(
        id="plan-1", project_id="proj", steps=tuple(steps),
        deferred_requirement_ids=tuple(deferred),
        provided_requirement_ids=tuple(provided),
        unsupported_backend_effects=tuple(unsupported_effects),
    )


# ============================================================================
# Section 3: silent-loss detection
# ============================================================================

def test_inactive_deferred_requirement_is_never_flagged():
    """Defect A's legitimate case: inactive/deferred, zero steps, no flag."""
    result = PreflightRequirementResult(
        requirement_id="req-esphome", present=False, satisfied=False, active=False,
    )
    preflight = _preflight([result], [_requirement("req-esphome")])
    plan = _plan(steps=())
    assert rse.find_silently_lost_active_setup_requirements(plan, preflight) == ()
    rse.assert_no_silently_lost_active_setup_requirements(plan, preflight)  # must not raise


def test_active_required_controllable_requirement_with_no_accounting_is_flagged():
    """The bug shape: active + required + controllable, but the plan
    has neither a step nor a deferred/provided/unsupported marker."""
    result = PreflightRequirementResult(
        requirement_id="req-esphome", present=False, satisfied=False, active=True,
    )
    preflight = _preflight([result], [_requirement("req-esphome")])
    plan = _plan(steps=())
    assert rse.find_silently_lost_active_setup_requirements(plan, preflight) == ("req-esphome",)
    try:
        rse.assert_no_silently_lost_active_setup_requirements(plan, preflight)
        assert False, "expected AssertionError for a silently-lost requirement"
    except AssertionError as exc:
        assert "req-esphome" in str(exc)


def test_active_requirement_materialized_as_a_setup_step_is_not_flagged():
    result = PreflightRequirementResult(
        requirement_id="req-esphome", present=False, satisfied=False, active=True,
    )
    preflight = _preflight([result], [_requirement("req-esphome")])
    step = SetupStep(
        id="step-1", requirement_id="req-esphome", action="install",
        install_method="pip", package="esphome",
    )
    plan = _plan(steps=(step,))
    assert rse.find_silently_lost_active_setup_requirements(plan, preflight) == ()


def test_active_requirement_explicitly_deferred_is_not_flagged():
    result = PreflightRequirementResult(
        requirement_id="req-esphome", present=False, satisfied=False, active=True,
    )
    preflight = _preflight([result], [_requirement("req-esphome")])
    plan = _plan(steps=(), deferred=("req-esphome",))
    assert rse.find_silently_lost_active_setup_requirements(plan, preflight) == ()


def test_active_requirement_explicitly_provided_is_not_flagged():
    result = PreflightRequirementResult(
        requirement_id="req-esphome", present=False, satisfied=False, active=True,
    )
    preflight = _preflight([result], [_requirement("req-esphome")])
    plan = _plan(steps=(), provided=("req-esphome",))
    assert rse.find_silently_lost_active_setup_requirements(plan, preflight) == ()


def test_active_requirement_with_no_controlled_backend_is_not_flagged():
    """A requirement type/install_method ADC genuinely cannot control
    (e.g. a hardware component) is correctly absent from the plan --
    this is not the silent-loss shape and must never be flagged."""
    result = PreflightRequirementResult(
        requirement_id="req-board", present=False, satisfied=False, active=True,
    )
    requirement = Requirement(
        id="req-board", name="ESP32 board", type="hardware_component",
        purpose="target", required=True, confidence=1.0, install_method=None,
    )
    preflight = _preflight([result], [requirement])
    plan = _plan(steps=())
    assert rse.find_silently_lost_active_setup_requirements(plan, preflight) == ()


def test_active_requirement_recorded_as_unsupported_backend_is_not_flagged():
    result = PreflightRequirementResult(
        requirement_id="req-esphome", present=False, satisfied=False, active=True,
    )
    preflight = _preflight([result], [_requirement("req-esphome")])
    effect = rse.classify_setup_effect("python_package", "req-esphome", "pip")
    plan = _plan(steps=(), unsupported_effects=(effect,))
    assert rse.find_silently_lost_active_setup_requirements(plan, preflight) == ()


def test_already_present_or_satisfied_requirement_is_never_flagged():
    result = PreflightRequirementResult(
        requirement_id="req-esphome", present=True, satisfied=True, active=True,
    )
    preflight = _preflight([result], [])
    plan = _plan(steps=())
    assert rse.find_silently_lost_active_setup_requirements(plan, preflight) == ()


def test_not_required_requirement_is_never_flagged():
    result = PreflightRequirementResult(
        requirement_id="req-optional", present=False, satisfied=False, active=True,
    )
    preflight = _preflight([result], [_requirement("req-optional", required=False)])
    plan = _plan(steps=())
    assert rse.find_silently_lost_active_setup_requirements(plan, preflight) == ()


# ============================================================================
# Section 4: honest phase-aware progress labels
# ============================================================================

class _FakeEvent:
    def __init__(self, phase, status, sequence):
        self.phase = phase
        self.status = status
        self.sequence = sequence
        self.details = {}
        self.summary = ""


class _FakeProgress:
    def __init__(self):
        self.info_lines = []

    def milestone(self, pct, label):
        pass

    def info(self, label):
        self.info_lines.append(label)


def test_post_approval_progress_line_labels_development_and_rework_phases_honestly():
    for phase in ("setup_execution", "development", "test_generation",
                  "testing", "diagnosis_review", "controlled_rework"):
        event = _FakeEvent(phase, "started", 1)
        line = rse._post_approval_progress_line(event)
        assert line is not None, f"expected an honest label for phase {phase!r}"
        assert "setup/toolchain handling" not in line


def test_post_approval_progress_line_is_none_for_unrelated_phases():
    for phase in ("engineering_council", "preflight", "controlled_git"):
        event = _FakeEvent(phase, "completed", 1)
        assert rse._post_approval_progress_line(event) is None


def test_render_new_trace_events_surfaces_development_phase_progress_not_stale_setup_label():
    """Reproduces the exact observability gap: during the single broad
    execute_approved_plan_from_store() call, once a `development` phase
    event arrives, the rendered progress lines must say so -- never stay
    silent (which would leave "setup/toolchain handling" as the last
    thing an operator saw)."""
    progress = _FakeProgress()
    events = [
        _FakeEvent("setup_execution", "completed", 1),
        _FakeEvent("development", "started", 2),
        _FakeEvent("testing", "completed", 3),
        _FakeEvent("diagnosis_review", "rework_required", 4),
        _FakeEvent("controlled_rework", "started", 5),
    ]
    rse._render_new_trace_events(progress, events, set(), diagnostic_level="NONE")
    joined = " | ".join(progress.info_lines)
    assert "Development" in joined
    assert "Testing" in joined
    assert "Diagnosis review" in joined
    assert "Controlled rework" in joined
