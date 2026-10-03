"""Regressions for CLAUDE-ADC-S3-LEGACY-HYGIENE-OWNERSHIP-FIX-001.

Pins the accepted S3 decomposition's productive ownership so a future
change cannot accidentally rewire canonical S3 planning/execution back
through the legacy app.setup_planner.SetupPlanner / app.setup_executor.
SetupExecutor classes, and confirms central S3 orchestration remains
generic (no hard-coded ecosystem-name branching), while explicitly NOT
asserting that ADC currently has automated executors for every
ecosystem -- generic central architecture is a different claim from
complete adapter coverage.
"""
import ast
from pathlib import Path
from unittest.mock import Mock

import app.canonical_composition as composition
from app.python_package_executor import PythonPackageExecutor
from app.requirement_model import SetupEffect, SetupPlan, SetupStep
from app.setup_executor import SetupExecutor
from app.setup_execution_state import SetupExecutionStateStore
from app.setup_planner import SetupPlanner
from app.toolchain_materializer import ToolchainMaterializer

ROOT = Path(__file__).parents[1]


# ---------------------------------------------------------------------
# 1. Canonical wiring: behavioral evidence (a real build_canonical_
#    components() call, with only the LLM-provider/secret boundary
#    mocked -- not the S3 objects themselves).
# ---------------------------------------------------------------------

def test_canonical_composition_wires_the_productive_s3_owners(monkeypatch, tmp_path):
    monkeypatch.setattr(composition, "create_llm_provider", Mock(return_value=Mock()))
    monkeypatch.setattr(composition, "LocalSecretStore", Mock())

    components = composition.build_canonical_components(
        diagnostic_trace_path=tmp_path / "events.jsonl",
    )
    workflow = components.development_workflow

    assert isinstance(workflow._materializer, ToolchainMaterializer)
    assert isinstance(workflow._executor, PythonPackageExecutor)
    assert isinstance(workflow._execution_state_store, SetupExecutionStateStore)

    # The legacy classes are never the wired productive owners.
    assert not isinstance(workflow._executor, SetupExecutor)
    assert workflow._planner is None or not isinstance(workflow._planner, SetupPlanner)


# ---------------------------------------------------------------------
# 2. Canonical wiring: structural/AST evidence -- SetupPlanner( and
#    SetupExecutor( are never called (constructed) anywhere in the
#    composition root's own source, regardless of how it is invoked.
# ---------------------------------------------------------------------

def _call_names(tree):
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.append(node.func.attr)
    return names


def test_canonical_composition_never_constructs_legacy_setup_classes():
    tree = ast.parse((ROOT / "app/canonical_composition.py").read_text(encoding="utf-8"))
    calls = _call_names(tree)

    assert "SetupPlanner" not in calls
    assert "SetupExecutor" not in calls
    assert calls.count("ToolchainMaterializer") == 1
    assert calls.count("PythonPackageExecutor") == 1
    assert calls.count("SetupExecutionStateStore") == 1


def test_development_workflow_constructor_receives_the_productive_owners_by_keyword():
    """AST evidence that the *specific* DevelopmentWorkflow(...) call site
    in canonical composition passes the real objects under materializer=
    and executor=, mirroring the existing require_json= wiring-proof
    pattern in tests/test_productive_adapter_reachability.py."""
    tree = ast.parse((ROOT / "app/canonical_composition.py").read_text(encoding="utf-8"))
    workflow_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "DevelopmentWorkflow"
    ]
    assert len(workflow_calls) == 1
    keywords = {kw.arg: ast.unparse(kw.value) for kw in workflow_calls[0].keywords}

    assert keywords.get("materializer") == "materializer"
    assert keywords.get("executor") == "package_executor"
    assert keywords.get("execution_state_store") == "execution_state_store"
    assert "planner" not in keywords


# ---------------------------------------------------------------------
# 3. Genericity: central S3 orchestration must not branch on a
#    hard-coded ecosystem name. This does NOT assert complete adapter
#    coverage -- only that CENTRAL comparisons/branches never select
#    behavior by literal ecosystem name.
# ---------------------------------------------------------------------

CENTRAL_S3_FILES = (
    "app/dev_workflow.py",
    "app/project_setup_application.py",
    "app/toolchain_materializer.py",
    "app/setup_approval.py",
    "app/setup_execution_state.py",
    "app/requirement_model.py",
    "app/missing_toolchain_setup.py",
)
FORBIDDEN_ECOSYSTEM_NAMES = {
    "esphome", "python", "pytest", "platformio", "cmake", "npm",
    "javascript", "pnpm", "yarn",
}


def _string_literals_used_in_comparisons(tree):
    literals = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for operand in (node.left, *node.comparators):
                if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                    literals.append(operand.value)
    return literals


def test_central_s3_orchestration_never_branches_on_a_hardcoded_ecosystem_name():
    violations = []
    for relative in CENTRAL_S3_FILES:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for literal in _string_literals_used_in_comparisons(tree):
            if literal.strip().lower() in FORBIDDEN_ECOSYSTEM_NAMES:
                violations.append((relative, literal))

    assert violations == [], (
        "central S3 orchestration must not select behavior by a hard-coded "
        f"ecosystem name (found: {violations})"
    )


def test_genericity_does_not_claim_complete_adapter_coverage():
    """Guards the distinction the task requires: PythonPackageExecutor
    legitimately contains Python-specific logic as an ADAPTER, and
    CONTROLLED_SETUP_EFFECTS legitimately supports only what ADC
    actually has a backend for today -- this must remain true, not be
    "fixed" by inventing fake executors."""
    from app.execution import CONTROLLED_SETUP_EFFECTS

    assert CONTROLLED_SETUP_EFFECTS == {SetupEffect.PYTHON_PACKAGE_INSTALL}


# ---------------------------------------------------------------------
# 4. Multi-toolchain semantics: one repository may need more than one
#    setup effect/toolchain area; a plan is not restricted to one.
# ---------------------------------------------------------------------

def test_setup_plan_may_contain_multiple_distinct_toolchain_effects():
    python_step = SetupStep(
        id="step-1", requirement_id="req-1", action="install",
        install_method="pip", package="requests",
        setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
    )
    unsupported_step = SetupStep(
        id="step-2", requirement_id="req-2", action="manual_review",
        setup_effect=None,
    )

    plan = SetupPlan(
        id="plan-mixed", project_id="mixed-project",
        steps=(python_step, unsupported_step),
        unsupported_backend_effects=(SetupEffect.PROJECT_TOOL_INSTALL,),
    )

    assert len(plan.steps) == 2
    assert plan.steps[0].setup_effect == SetupEffect.PYTHON_PACKAGE_INSTALL
    assert plan.steps[1].setup_effect is None
    # The coverage gap is surfaced explicitly, never hidden or silently
    # treated as executable.
    assert SetupEffect.PROJECT_TOOL_INSTALL in plan.unsupported_backend_effects
