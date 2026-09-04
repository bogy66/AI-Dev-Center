import importlib.metadata
import importlib.util
import shutil
import socket
import subprocess

import pytest

from app.requirement_model import Requirement, RequirementActivation, RequirementType
from app.requirement_preflight import RequirementPreflight


def make_requirement(req_id, required):
    return Requirement(
        id=req_id,
        name=f"req-{req_id}",
        type="capability",
        purpose="test requirement",
        required=required,
        confidence=1.0,
    )


def make_typed_requirement(req_id, req_type, required=True, name=None):
    return Requirement(
        id=req_id,
        name=name or f"req-{req_id}",
        type=req_type,
        purpose="test requirement",
        required=required,
        confidence=1.0,
    )


def test_single_required_requirement():
    req = make_requirement("req-required", required=True)

    result = RequirementPreflight.check([req], "project-1")

    assert result.project_id == "project-1"
    assert result.overall_ready is True

    assert len(result.results) == 1
    res = result.results[0]
    assert res.requirement_id == req.id
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "requirement type not locally verifiable"

    assert result.missing_requirements == ()
    assert result.already_installed == ()
    assert result.warnings == ("requirement type not locally verifiable",)


def test_single_optional_requirement():
    req = make_requirement("req-optional", required=False)

    result = RequirementPreflight.check([req], "project-2")

    assert result.project_id == "project-2"
    assert result.overall_ready is True

    assert len(result.results) == 1
    res = result.results[0]
    assert res.requirement_id == req.id
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "requirement type not locally verifiable"

    assert result.missing_requirements == ()
    assert result.already_installed == ()
    assert result.warnings == ("requirement type not locally verifiable",)


def test_multiple_requirements():
    req_required_1 = make_requirement("req-1", required=True)
    req_optional = make_requirement("req-2", required=False)
    req_required_2 = make_requirement("req-3", required=True)

    result = RequirementPreflight.check(
        [req_required_1, req_optional, req_required_2],
        "project-3",
    )

    assert len(result.results) == 3

    result_map = {r.requirement_id: r for r in result.results}
    assert set(result_map) == {"req-1", "req-2", "req-3"}

    for res in result.results:
        assert res.present is False
        assert res.satisfied is False
        assert res.detected_version is None
        assert res.warning == "requirement type not locally verifiable"

    assert result.missing_requirements == ()
    assert result.overall_ready is True
    assert result.already_installed == ()
    assert result.warnings == (
        "requirement type not locally verifiable",
        "requirement type not locally verifiable",
        "requirement type not locally verifiable",
    )


def test_overall_ready_without_required_requirements():
    req_optional_1 = make_requirement("req-opt-1", required=False)
    req_optional_2 = make_requirement("req-opt-2", required=False)

    result = RequirementPreflight.check([req_optional_1, req_optional_2], "project-4")

    assert result.overall_ready is True
    assert result.missing_requirements == ()
    assert len(result.results) == 2
    assert result.warnings == (
        "requirement type not locally verifiable",
        "requirement type not locally verifiable",
    )


def test_does_not_mutate_requirements():
    req = make_requirement("req-immutable", required=True)
    original = make_requirement("req-immutable", required=True)

    RequirementPreflight.check([req], "project-5")

    assert req == original
    assert req.id == original.id
    assert req.required == original.required
    assert req.evidence == original.evidence
    assert req.metadata == original.metadata


def test_no_network_or_subprocess_calls(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Network or subprocess call attempted")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(subprocess, "run", fail)

    req = make_requirement("req-no-io", required=True)

    try:
        RequirementPreflight.check([req], "project-6")
    except AssertionError as exc:
        pytest.fail(f"Preflight should not perform network/subprocess calls: {exc}")


def test_inactive_project_requirement_is_preserved_without_blocking(monkeypatch):
    req = make_typed_requirement(
        "future-executable", RequirementType.EXECUTABLE, required=True,
    )
    activation = RequirementActivation(req.id, False, False, "not used now")
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    result = RequirementPreflight.check([req], "project", [activation])

    assert result.overall_ready is True
    assert result.missing_requirements == ()
    assert result.inactive_requirements == (req,)
    assert result.results[0].active is False
    assert result.results[0].requirement_id == req.id


def test_same_project_requirement_can_become_active_and_block_later(monkeypatch):
    req = make_typed_requirement(
        "future-executable", RequirementType.EXECUTABLE, required=True,
    )
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    inactive = RequirementPreflight.check(
        [req], "project", [RequirementActivation(req.id, False, False)],
    )
    active = RequirementPreflight.check(
        [req], "project", [RequirementActivation(req.id, True, True)],
    )

    assert inactive.overall_ready is True
    assert active.overall_ready is False
    assert active.missing_requirements == (req,)
    assert active.results[0].blocks_current_operation is True


def test_active_manual_requirement_remains_a_blocker():
    req = make_typed_requirement(
        "physical-capability", RequirementType.HARDWARE_COMPONENT, required=True,
    )
    activation = RequirementActivation(req.id, True, True, "needed now")

    result = RequirementPreflight.check([req], "project", [activation])

    assert result.overall_ready is False
    assert result.missing_requirements == (req,)


def test_active_non_blocking_requirement_remains_visible_without_unready_state():
    req = make_typed_requirement(
        "future-manual", "future_capability_kind", required=True,
    )
    activation = RequirementActivation(req.id, True, False, "useful but not blocking")

    result = RequirementPreflight.check([req], "project", [activation])

    assert result.overall_ready is True
    assert result.missing_requirements == (req,)
    assert result.results[0].active is True
    assert result.results[0].blocks_current_operation is False


def test_satisfied_preflight_remains_authoritative_for_active_requirement(monkeypatch):
    req = make_typed_requirement(
        "available", RequirementType.EXECUTABLE, required=True,
    )
    activation = RequirementActivation(req.id, True, True)
    monkeypatch.setattr(shutil, "which", lambda _name: "/controlled/available")

    result = RequirementPreflight.check([req], "project", [activation])

    assert result.overall_ready is True
    assert result.results[0].satisfied is True
    assert result.missing_requirements == ()


def test_executable_present_requirement(monkeypatch):
    req = Requirement(
        id="req-exe-present",
        name="python",
        type=RequirementType.EXECUTABLE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/python")

    result = RequirementPreflight.check([req], "project-exe-present")

    assert result.project_id == "project-exe-present"
    assert result.overall_ready is True
    assert len(result.results) == 1
    res = result.results[0]
    assert res.requirement_id == req.id
    assert res.present is True
    assert res.satisfied is True
    assert res.detected_version is None
    assert res.warning is None
    assert result.missing_requirements == ()
    assert result.already_installed == ()
    assert result.warnings == ()


def test_executable_missing_required_requirement(monkeypatch):
    req = Requirement(
        id="req-exe-missing-required",
        name="not-present",
        type=RequirementType.EXECUTABLE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = RequirementPreflight.check([req], "project-exe-missing")

    assert result.project_id == "project-exe-missing"
    assert result.overall_ready is False
    assert len(result.results) == 1
    res = result.results[0]
    assert res.requirement_id == req.id
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning is None
    assert len(result.missing_requirements) == 1
    assert result.missing_requirements[0].id == req.id
    assert result.already_installed == ()
    assert result.warnings == ()


def test_executable_missing_optional_requirement(monkeypatch):
    req = Requirement(
        id="req-exe-missing-optional",
        name="not-present-opt",
        type=RequirementType.EXECUTABLE,
        purpose="test requirement",
        required=False,
        confidence=1.0,
    )
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = RequirementPreflight.check([req], "project-exe-optional")

    assert result.project_id == "project-exe-optional"
    assert result.overall_ready is True
    assert len(result.results) == 1
    res = result.results[0]
    assert res.requirement_id == req.id
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning is None
    assert result.missing_requirements == ()
    assert result.already_installed == ()
    assert result.warnings == ()


def test_executable_required_present_and_optional_missing(monkeypatch):
    req_present_required = Requirement(
        id="req-exe-present-required",
        name="git",
        type=RequirementType.EXECUTABLE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    req_missing_optional = Requirement(
        id="req-exe-missing-optional-2",
        name="not-present-opt",
        type=RequirementType.EXECUTABLE,
        purpose="test requirement",
        required=False,
        confidence=1.0,
    )

    def fake_which(name):
        return "/usr/bin/git" if name == "git" else None

    monkeypatch.setattr(shutil, "which", fake_which)

    result = RequirementPreflight.check(
        [req_present_required, req_missing_optional],
        "project-mixed",
    )

    assert result.overall_ready is True
    result_map = {r.requirement_id: r for r in result.results}
    assert set(result_map) == {"req-exe-present-required", "req-exe-missing-optional-2"}
    assert result_map["req-exe-present-required"].present is True
    assert result_map["req-exe-present-required"].satisfied is True
    assert result_map["req-exe-missing-optional-2"].present is False
    assert result_map["req-exe-missing-optional-2"].satisfied is False
    assert result.missing_requirements == ()
    assert result.already_installed == ()
    assert result.warnings == ()


def test_executable_does_not_mutate_requirements(monkeypatch):
    req = make_requirement("req-immutable-exe", required=True)
    req_exe = Requirement(
        id=req.id,
        name=req.name,
        type=RequirementType.EXECUTABLE,
        purpose=req.purpose,
        required=req.required,
        confidence=req.confidence,
    )
    original = Requirement(
        id=req_exe.id,
        name=req_exe.name,
        type=req_exe.type,
        purpose=req_exe.purpose,
        required=req_exe.required,
        confidence=req_exe.confidence,
    )

    monkeypatch.setattr(shutil, "which", lambda name: "/bin/foo")

    RequirementPreflight.check([req_exe], "project-immutable-exe")

    assert req_exe == original
    assert req_exe.id == original.id
    assert req_exe.required == original.required
    assert req_exe.type == original.type
    assert req_exe.evidence == original.evidence
    assert req_exe.metadata == original.metadata


def test_executable_no_real_system_dependencies(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Network/system call attempted")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/bin/true" if name == "python" else None,
    )

    req = Requirement(
        id="req-exe-no-io",
        name="python",
        type=RequirementType.EXECUTABLE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )

    try:
        result = RequirementPreflight.check([req], "project-no-io")
    except AssertionError as exc:
        pytest.fail(f"Preflight should not perform network/subprocess calls: {exc}")

    assert result.missing_requirements == ()
    assert result.results[0].present is True
    assert result.warnings == ()


# ---------------------------------------------------------------------------
# New tests for RequirementType.PYTHON_PACKAGE
# ---------------------------------------------------------------------------

def test_python_package_present_requirement(monkeypatch):
    req = Requirement(
        id="req-py-present",
        name="requests",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "2.31.0")

    result = RequirementPreflight.check([req], "project-py-present")

    assert result.project_id == "project-py-present"
    assert result.overall_ready is True
    assert len(result.results) == 1
    res = result.results[0]
    assert res.requirement_id == req.id
    assert res.present is True
    assert res.satisfied is True
    assert res.detected_version == "2.31.0"
    assert res.warning is None
    assert result.missing_requirements == ()
    assert result.already_installed == ()
    assert result.warnings == ()


def test_python_package_missing_requirement(monkeypatch):
    req = Requirement(
        id="req-py-missing",
        name="not-installed",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    result = RequirementPreflight.check([req], "project-py-missing")

    assert result.project_id == "project-py-missing"
    assert result.overall_ready is False
    assert len(result.results) == 1
    res = result.results[0]
    assert res.requirement_id == req.id
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning is None
    assert len(result.missing_requirements) == 1
    assert result.missing_requirements[0].id == req.id
    assert result.already_installed == ()
    assert result.warnings == ()


def test_python_package_version_success(monkeypatch):
    req = Requirement(
        id="req-py-version-success",
        name="some-package",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "1.2.3")

    result = RequirementPreflight.check([req], "project-py-version-success")

    assert result.results[0].present is True
    assert result.results[0].satisfied is True
    assert result.results[0].detected_version == "1.2.3"
    assert result.results[0].warning is None
    assert result.warnings == ()


def test_python_package_version_not_determinable(monkeypatch):
    req = Requirement(
        id="req-py-version-error",
        name="some-package",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())

    def raise_version(_):
        raise RuntimeError("no metadata available")

    monkeypatch.setattr(importlib.metadata, "version", raise_version)

    result = RequirementPreflight.check([req], "project-py-version-error")

    assert result.results[0].present is True
    assert result.results[0].satisfied is True
    assert result.results[0].detected_version is None
    assert result.results[0].warning is None
    assert result.missing_requirements == ()
    assert result.warnings == ()


def test_python_package_required_missing(monkeypatch):
    req = Requirement(
        id="req-py-required-missing",
        name="missing-required",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    result = RequirementPreflight.check([req], "project-py-required-missing")

    assert result.overall_ready is False
    assert len(result.missing_requirements) == 1
    assert result.missing_requirements[0].id == req.id
    assert result.warnings == ()


def test_python_package_optional_missing(monkeypatch):
    req = Requirement(
        id="req-py-optional-missing",
        name="missing-optional",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="test requirement",
        required=False,
        confidence=1.0,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    result = RequirementPreflight.check([req], "project-py-optional-missing")

    assert result.overall_ready is True
    assert result.missing_requirements == ()
    assert result.warnings == ()


def test_python_package_does_not_mutate_requirements(monkeypatch):
    req = Requirement(
        id="req-py-immutable",
        name="some-package",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    original = Requirement(
        id=req.id,
        name=req.name,
        type=req.type,
        purpose=req.purpose,
        required=req.required,
        confidence=req.confidence,
    )
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "9.9.9")

    RequirementPreflight.check([req], "project-py-immutable")

    assert req == original
    assert req.id == original.id
    assert req.required == original.required
    assert req.type == original.type
    assert req.evidence == original.evidence
    assert req.metadata == original.metadata


def test_python_package_uses_mocked_dependencies(monkeypatch):
    calls = []

    def fake_find_spec(name):
        calls.append(("find_spec", name))
        return object()

    def fake_version(name):
        calls.append(("version", name))
        return "1.0"

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(importlib.metadata, "version", fake_version)

    req = Requirement(
        id="req-py-mocked",
        name="some-package",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )

    RequirementPreflight.check([req], "project-py-mocked")

    assert calls == [
        ("find_spec", "some-package"),
        ("version", "some-package"),
    ]


def test_python_package_no_network_or_subprocess_calls(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Network or subprocess call attempted")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "1.0")

    req = Requirement(
        id="req-py-no-io",
        name="some-package",
        type=RequirementType.PYTHON_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )

    try:
        result = RequirementPreflight.check([req], "project-py-no-io")
    except AssertionError as exc:
        pytest.fail(f"Preflight should not perform network/subprocess calls: {exc}")

    assert result.overall_ready is True
    assert result.results[0].present is True
    assert result.results[0].satisfied is True
    assert result.warnings == ()


# ---------------------------------------------------------------------------
# New tests for non-locally-verifiable requirement types
# ---------------------------------------------------------------------------

def test_unknown_type_required_not_locally_verifiable():
    req = make_typed_requirement("req-unknown", RequirementType.UNKNOWN, required=True)
    result = RequirementPreflight.check([req], "project-unknown-required")

    res = result.results[0]
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "requirement type not locally verifiable"
    assert result.missing_requirements == ()
    assert result.overall_ready is True
    assert result.warnings == ("requirement type not locally verifiable",)


def test_sdk_type_required_not_locally_verifiable():
    req = make_typed_requirement("req-sdk", RequirementType.SDK, required=True)
    result = RequirementPreflight.check([req], "project-sdk-required")

    res = result.results[0]
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "requirement type not locally verifiable"
    assert result.missing_requirements == ()
    assert result.overall_ready is True
    assert result.warnings == ("requirement type not locally verifiable",)


def test_toolchain_type_required_not_locally_verifiable():
    req = make_typed_requirement("req-toolchain", RequirementType.TOOLCHAIN, required=True)
    result = RequirementPreflight.check([req], "project-toolchain-required")

    res = result.results[0]
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "requirement type not locally verifiable"
    assert result.missing_requirements == ()
    assert result.overall_ready is True
    assert result.warnings == ("requirement type not locally verifiable",)


def test_connection_type_required_not_locally_verifiable():
    req = make_typed_requirement("req-connection", RequirementType.CONNECTION, required=True)
    result = RequirementPreflight.check([req], "project-connection-required")

    res = result.results[0]
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "requirement type not locally verifiable"
    assert result.missing_requirements == ()
    assert result.overall_ready is True
    assert result.warnings == ("requirement type not locally verifiable",)


def test_build_command_type_required_not_locally_verifiable():
    req = make_typed_requirement("req-build", RequirementType.BUILD_COMMAND, required=True)
    result = RequirementPreflight.check([req], "project-build-required")

    res = result.results[0]
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "requirement type not locally verifiable"
    assert result.missing_requirements == ()
    assert result.overall_ready is True
    assert result.warnings == ("requirement type not locally verifiable",)


def test_test_command_type_required_not_locally_verifiable():
    req = make_typed_requirement("req-testcmd", RequirementType.TEST_COMMAND, required=True)
    result = RequirementPreflight.check([req], "project-testcmd-required")

    res = result.results[0]
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "requirement type not locally verifiable"
    assert result.missing_requirements == ()
    assert result.overall_ready is True
    assert result.warnings == ("requirement type not locally verifiable",)


def test_version_constraint_type_required():
    req = make_typed_requirement("req-vc", RequirementType.VERSION_CONSTRAINT, required=True)
    result = RequirementPreflight.check([req], "project-vc-required")

    res = result.results[0]
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "version constraint not evaluated"
    assert result.missing_requirements == ()
    assert result.overall_ready is True
    assert result.warnings == ("version constraint not evaluated",)


def test_optional_non_verifiable_requirement():
    req = make_typed_requirement("req-opt-nv", RequirementType.SDK, required=False)
    result = RequirementPreflight.check([req], "project-opt-nv")

    assert result.overall_ready is True
    assert result.missing_requirements == ()
    res = result.results[0]
    assert res.warning == "requirement type not locally verifiable"
    assert result.warnings == ("requirement type not locally verifiable",)


def test_required_non_verifiable_requirement():
    req = make_typed_requirement("req-req-nv", RequirementType.CAPABILITY, required=True)
    result = RequirementPreflight.check([req], "project-req-nv")

    assert result.overall_ready is True
    assert result.missing_requirements == ()
    res = result.results[0]
    assert res.warning == "requirement type not locally verifiable"
    assert result.warnings == ("requirement type not locally verifiable",)


def test_overall_ready_stays_true_with_only_non_verifiable_types():
    reqs = [
        make_typed_requirement("req-sdk", RequirementType.SDK, required=True),
        make_typed_requirement("req-toolchain", RequirementType.TOOLCHAIN, required=True),
        make_typed_requirement("req-build", RequirementType.BUILD_COMMAND, required=True),
    ]
    result = RequirementPreflight.check(reqs, "project-only-nv")

    assert result.overall_ready is True
    assert result.missing_requirements == ()
    assert result.warnings == (
        "requirement type not locally verifiable",
        "requirement type not locally verifiable",
        "requirement type not locally verifiable",
    )


def test_non_verifiable_requirement_does_not_mutate_input():
    req = make_typed_requirement("req-nv-immutable", RequirementType.UNKNOWN, required=True)
    original = make_typed_requirement("req-nv-immutable", RequirementType.UNKNOWN, required=True)

    RequirementPreflight.check([req], "project-nv-immutable")

    assert req == original
    assert req.metadata == original.metadata
    assert req.evidence == original.evidence


def test_non_verifiable_no_network_or_subprocess_calls(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Network or subprocess call attempted")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(subprocess, "run", fail)

    req = make_typed_requirement("req-nv-no-io", RequirementType.UNKNOWN, required=True)

    try:
        RequirementPreflight.check([req], "project-nv-no-io")
    except AssertionError as exc:
        pytest.fail(f"Preflight should not perform network/subprocess calls: {exc}")


# ---------------------------------------------------------------------------
# New tests for RequirementType.SYSTEM_PACKAGE capability-aware preflight
# ---------------------------------------------------------------------------

def test_system_package_available_as_executable_is_satisfied(monkeypatch):
    """SYSTEM_PACKAGE requirement whose name resolves in PATH is satisfied."""
    req = Requirement(
        id="req-sys-available",
        name="python3",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="Python 3 runtime environment",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/python3")

    result = RequirementPreflight.check([req], "project-sys-available")

    assert result.project_id == "project-sys-available"
    assert result.overall_ready is True
    assert len(result.results) == 1
    res = result.results[0]
    assert res.requirement_id == req.id
    assert res.present is True
    assert res.satisfied is True
    assert res.detected_version is None
    assert res.warning is None
    assert result.missing_requirements == ()
    assert result.warnings == ()


def test_system_package_not_in_path_remains_not_verifiable(monkeypatch):
    """SYSTEM_PACKAGE requirement whose name is not in PATH gets existing behavior."""
    req = Requirement(
        id="req-sys-missing",
        name="not-present",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="system package not in PATH",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = RequirementPreflight.check([req], "project-sys-missing")

    assert result.project_id == "project-sys-missing"
    assert result.overall_ready is True
    assert len(result.results) == 1
    res = result.results[0]
    assert res.requirement_id == req.id
    assert res.present is False
    assert res.satisfied is False
    assert res.detected_version is None
    assert res.warning == "requirement type not locally verifiable"
    assert result.missing_requirements == ()
    assert result.warnings == ("requirement type not locally verifiable",)


def test_system_package_generic_executable_not_hardcoded(monkeypatch):
    """Preflight uses generic shutil.which, not technology-specific logic."""
    req = Requirement(
        id="req-sys-generic",
        name="git",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="Generic version control",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/git" if name == "git" else None)

    result = RequirementPreflight.check([req], "project-sys-generic")

    assert result.results[0].present is True
    assert result.results[0].satisfied is True
    assert result.warnings == ()


def test_system_package_does_not_mutate_requirements(monkeypatch):
    req = Requirement(
        id="req-sys-immutable",
        name="python3",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    original = Requirement(
        id=req.id,
        name=req.name,
        type=req.type,
        purpose=req.purpose,
        required=req.required,
        confidence=req.confidence,
    )
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/python3")

    RequirementPreflight.check([req], "project-sys-immutable")

    assert req == original
    assert req.id == original.id
    assert req.required == original.required
    assert req.type == original.type
    assert req.evidence == original.evidence
    assert req.metadata == original.metadata


def test_system_package_no_network_or_subprocess_calls(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Network or subprocess call attempted")

    monkeypatch.setattr(socket, "socket", fail)
    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/python3")

    req = Requirement(
        id="req-sys-no-io",
        name="python3",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )

    try:
        result = RequirementPreflight.check([req], "project-sys-no-io")
    except AssertionError as exc:
        pytest.fail(f"Preflight should not perform network/subprocess calls: {exc}")

    assert result.overall_ready is True
    assert result.results[0].present is True
    assert result.results[0].satisfied is True
    assert result.warnings == ()


# ---------------------------------------------------------------------------
# Structured deterministic verification executable identity (OC-018)
# ---------------------------------------------------------------------------

def test_structured_verification_executable_differs_from_display_name(monkeypatch):
    req = Requirement(
        id="req-structured",
        name="Runtime Display Name",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
        verification_executable="generic-runtime",
    )
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "/usr/bin/generic-runtime" if name == "generic-runtime" else None,
    )

    result = RequirementPreflight.check([req], "project-structured")

    res = result.results[0]
    assert res.present is True
    assert res.satisfied is True
    assert result.missing_requirements == ()
    assert result.overall_ready is True


def test_preflight_uses_structured_executable_not_display_name(monkeypatch):
    resolved = []

    def fake_which(name):
        resolved.append(name)
        return "/usr/bin/generic-runtime" if name == "generic-runtime" else None

    monkeypatch.setattr(shutil, "which", fake_which)

    req = Requirement(
        id="req-structured-2",
        name="Runtime Display Name",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
        verification_executable="generic-runtime",
    )

    result = RequirementPreflight.check([req], "project-structured-2")

    assert "generic-runtime" in resolved
    assert "Runtime Display Name" not in resolved
    assert result.results[0].satisfied is True


def test_missing_structured_executable_remains_unsatisfied(monkeypatch):
    req = Requirement(
        id="req-structured-missing",
        name="Runtime Display Name",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
        verification_executable="fictional-tool",
    )
    monkeypatch.setattr(shutil, "which", lambda name: None)

    result = RequirementPreflight.check([req], "project-structured-missing")

    res = result.results[0]
    assert res.present is False
    assert res.satisfied is False


def test_executable_type_uses_structured_verification_executable(monkeypatch):
    req = Requirement(
        id="req-exe-structured",
        name="Some Tool Display",
        type=RequirementType.EXECUTABLE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
        verification_executable="tool-bin",
    )
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "/usr/bin/tool-bin" if name == "tool-bin" else None,
    )

    result = RequirementPreflight.check([req], "project-exe-structured")

    assert result.results[0].present is True
    assert result.results[0].satisfied is True


def test_system_package_without_structured_field_remains_compatible(monkeypatch):
    """OC-017 behavior preserved: SYSTEM_PACKAGE name still resolves in PATH."""
    req = Requirement(
        id="req-sys-legacy",
        name="git",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
    )
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "/usr/bin/git" if name == "git" else None,
    )

    result = RequirementPreflight.check([req], "project-sys-legacy")

    assert result.results[0].present is True
    assert result.results[0].satisfied is True


def test_unsafe_command_like_verification_executable_is_neutralized(monkeypatch):
    resolved = []

    def fake_which(name):
        resolved.append(name)
        return None

    monkeypatch.setattr(shutil, "which", fake_which)

    req = Requirement(
        id="req-unsafe",
        name="Runtime Display Name",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
        verification_executable="python3 --version",
    )

    # The model validation must neutralize the command-like value down to a
    # safe single executable identity (or None) before preflight.
    assert req.verification_executable != "python3 --version"

    result = RequirementPreflight.check([req], "project-unsafe")

    # The rejected command-like verification value must never become
    # deterministic verification authority. The legacy fallback to the
    # human-readable requirement name remains allowed.
    assert "python3 --version" not in resolved
    assert "Runtime Display Name" in resolved


def test_verification_method_is_never_executed(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("verification_method must never be executed")

    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(socket, "socket", fail)

    req = Requirement(
        id="req-no-verify-exec",
        name="Runtime Display Name",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="test requirement",
        required=True,
        confidence=1.0,
        verification_method="python3 --version",
        verification_executable="generic-runtime",
    )
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "/usr/bin/generic-runtime" if name == "generic-runtime" else None,
    )

    try:
        result = RequirementPreflight.check([req], "project-no-verify-exec")
    except AssertionError as exc:
        pytest.fail(f"verification_method must never be executed: {exc}")

    assert result.results[0].satisfied is True
