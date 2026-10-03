"""Regression tests for the SetupPlan.deferred_requirements MappingProxyType
persistence defect (OC-ADC-RSE-SETUP-PLAN-MAPPINGPROXY-PERSISTENCE-FIX-001),
follow-up validation task -002.

Before the fix, a SetupPlan whose ``deferred_requirements`` contained a
``Requirement`` with a ``MappingProxyType`` (or any other ``Mapping``
subclass) ``metadata`` field could not be persisted at all:
``dataclasses.asdict()`` (used implicitly by naive serialization) relies on
``copy.deepcopy()``, which does not know how to traverse
``MappingProxyType``. ``_serialize_plan`` in app/workflow_plan_store.py
replaces that with an explicit recursive serializer that handles
``MappingProxyType``/``Mapping``, ``datetime``, ``Enum``, tuples, and
nested dataclasses, and raises ``TypeError`` (never a lossy
``repr()``/``str()`` fallback) for anything else.

These tests exercise the real, productive persistence path
(``persist_setup_plan`` -> ``WorkflowPlanStore.save`` ->
``WorkflowPlanStore.load``), not just the private ``_serialize_plan``
helper in isolation, and confirm the fix does not disturb ordinary
(non-MappingProxyType) WorkflowPlanStore persistence, which
tests/test_workflow_plan_store.py already covers and this file re-runs
nothing of.
"""
import json
from types import MappingProxyType

import pytest

from app.project_setup_application import persist_setup_plan
from app.requirement_model import Requirement, SetupPlan, SetupStep
from app.workflow_plan_store import WorkflowPlanStore


def _plan_with_deferred(*deferred_requirements, plan_id="plan-deferred"):
    return SetupPlan(
        id=plan_id,
        project_id="workflow-demo",
        steps=(
            SetupStep(
                id="step-1", requirement_id="req-1", action="install",
                install_method="python_package", package="build",
                is_approved=True, setup_effect="python_package_install",
            ),
        ),
        requires_user_approval=True,
        status="pending_approval",
        deferred_requirements=deferred_requirements,
    )


def _requirement(req_id="req-deferred", metadata=None, name="Deferred package"):
    return Requirement(
        id=req_id,
        name=name,
        type="python_package",
        purpose="Needed later in the toolchain graph.",
        required=True,
        confidence=0.9,
        metadata=metadata if metadata is not None else {"origin": "council", "priority": 1},
    )


# --- 1/2/3: a SetupPlan with MappingProxyType metadata can be saved, the ----
# persisted representation is JSON-safe, and the plan loads again ----------

def test_deferred_requirement_with_mappingproxy_metadata_saves_and_loads(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    requirement = _requirement()
    # Requirement.__post_init__ always coerces metadata to MappingProxyType
    # (see app/requirement_model.py) -- assert that precondition explicitly
    # so this test fails loudly, not silently, if that guarantee ever changes.
    assert isinstance(requirement.metadata, MappingProxyType)

    plan = _plan_with_deferred(requirement)

    saved_path = store.save(plan)  # must not raise

    assert saved_path.is_file()
    # JSON-safe: the file is valid JSON, and the persisted metadata is a
    # plain JSON object, not a repr()/str() fallback of the MappingProxyType.
    raw = json.loads(saved_path.read_text(encoding="utf-8"))
    persisted_metadata = raw["deferred_requirements"][0]["metadata"]
    assert persisted_metadata == {"origin": "council", "priority": 1}
    assert isinstance(persisted_metadata, dict)

    loaded = store.load("workflow-demo", "plan-deferred")
    assert loaded == plan
    assert len(loaded.deferred_requirements) == 1
    assert loaded.deferred_requirements[0].id == "req-deferred"


# --- 4: Requirement.metadata is reconstructed with the expected immutable --
# semantics ------------------------------------------------------------------

def test_reconstructed_deferred_requirement_metadata_is_immutable(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    plan = _plan_with_deferred(_requirement())
    store.save(plan)

    loaded = store.load("workflow-demo", "plan-deferred")
    metadata = loaded.deferred_requirements[0].metadata

    assert isinstance(metadata, MappingProxyType)
    assert dict(metadata) == {"origin": "council", "priority": 1}
    with pytest.raises(TypeError):
        metadata["origin"] = "tampered"


# --- 5: multiple deferred_requirements work ---------------------------------

def test_multiple_deferred_requirements_each_round_trip_independently(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    req_a = _requirement(req_id="req-a", metadata={"origin": "council", "rank": 1})
    req_b = _requirement(req_id="req-b", metadata={"origin": "preflight", "rank": 2})
    req_c = _requirement(req_id="req-c", metadata={})  # empty mapping is a valid mapping too
    plan = _plan_with_deferred(req_a, req_b, req_c)

    store.save(plan)
    loaded = store.load("workflow-demo", "plan-deferred")

    assert len(loaded.deferred_requirements) == 3
    by_id = {r.id: r for r in loaded.deferred_requirements}
    assert dict(by_id["req-a"].metadata) == {"origin": "council", "rank": 1}
    assert dict(by_id["req-b"].metadata) == {"origin": "preflight", "rank": 2}
    assert dict(by_id["req-c"].metadata) == {}
    for r in loaded.deferred_requirements:
        assert isinstance(r.metadata, MappingProxyType)
    # Each Requirement's own identity/fields are independently preserved,
    # not just the shared metadata shape.
    assert by_id["req-a"].id != by_id["req-b"].id != by_id["req-c"].id


# --- 6: unsupported non-serializable values fail closed ---------------------

def test_unsupported_metadata_value_fails_closed_with_type_error(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    # A set() is a real, concrete example of a value app/workflow_plan_store.py's
    # _serialize_plan does not know how to handle -- not str/int/float/bool/
    # None, not a Mapping, not a list/tuple, not a datetime, not an Enum,
    # not a dataclass.
    requirement = _requirement(metadata={"bad": {"a", "b", "c"}})
    plan = _plan_with_deferred(requirement, plan_id="plan-bad")

    with pytest.raises(TypeError, match="unsupported type for plan serialization"):
        store.save(plan)

    # Fail-closed: no partial/corrupt file was left behind for this plan.
    assert not (tmp_path / "plans" / "workflow-demo" / "plan-bad.json").exists()


def test_unsupported_metadata_value_is_never_silently_stringified(tmp_path):
    """The TypeError message must name the real unsupported type, never
    silently degrade to a lossy repr()/str() fallback that would make an
    unsupported value look like it was accepted."""
    store = WorkflowPlanStore(tmp_path / "plans")
    requirement = _requirement(metadata={"bad": object()})
    plan = _plan_with_deferred(requirement, plan_id="plan-bad-2")

    with pytest.raises(TypeError) as excinfo:
        store.save(plan)
    assert "object" in str(excinfo.value)


# --- 2/7: exercise the real productive path, not only WorkflowPlanStore -----
# directly: persist_setup_plan(...) -> WorkflowPlanStore.save(...) ----------
# -> WorkflowPlanStore.load(...) ---------------------------------------------

def test_persist_setup_plan_productive_path_round_trips_mappingproxy_metadata(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    requirement = _requirement(metadata={"origin": "council", "confidence_note": "high"})
    plan = _plan_with_deferred(requirement, plan_id="plan-productive")

    # The real adapter-agnostic entry point every caller (web/API, MCP)
    # goes through -- app/project_setup_application.py::persist_setup_plan
    # -- not the store's save() called directly.
    persist_setup_plan(store, plan, council_result=None)

    loaded = store.load("workflow-demo", "plan-productive")
    assert loaded == plan
    assert dict(loaded.deferred_requirements[0].metadata) == {
        "origin": "council", "confidence_note": "high",
    }
    assert isinstance(loaded.deferred_requirements[0].metadata, MappingProxyType)


# --- 8: existing ordinary WorkflowPlanStore persistence remains intact ------
# (deferred_requirements=() is the default/common case; must be unaffected)

def test_plan_without_deferred_requirements_still_round_trips(tmp_path):
    store = WorkflowPlanStore(tmp_path / "plans")
    plan = SetupPlan(
        id="plan-ordinary", project_id="workflow-demo",
        steps=(
            SetupStep(id="step-1", requirement_id="req-1", action="install",
                      install_method="python_package", package="build",
                      is_approved=True, setup_effect="python_package_install"),
        ),
        requires_user_approval=True, status="pending_approval",
    )

    store.save(plan)
    loaded = store.load("workflow-demo", "plan-ordinary")

    assert loaded == plan
    assert loaded.deferred_requirements == ()
