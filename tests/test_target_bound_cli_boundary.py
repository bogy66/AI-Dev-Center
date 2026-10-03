"""TEST_040 regressions: detection, approval and execution of a CLI tool are
bound to the SAME selected and approved target environment (IF_REQ_038).

A host PATH hit for the same tool name is never a substitute, an unknown,
unapproved or ambiguous target stays fail-closed, and the result does not
change when the host PATH changes or when verification is retried.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.execution import (
    ApprovalProvenance, CapabilityRegistry, ExecutionRequest, _bootstrap,
    execute_controlled, register_setup_step_targets, resolve_tool_in_target,
    validate_request,
)
from app.missing_toolchain_setup import StructuredInstallerRegistration
from app.requirement_model import SetupPlan, SetupStep
from app.verification import (
    ESPHomeCheckRunner, TOOL_UNAVAILABLE, VerificationStep, verification_target,
)

TOOL = "esphome"


def _script(path: Path, marker: Path, label: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho {label} >> {marker}\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _env(root: Path, name: str, *, with_tool: bool, marker: Path) -> Path:
    """An isolated environment: its own bin directory with a `python` target
    and, optionally, the CLI tool. Returns the target executable."""
    bin_dir = root / name / "bin"
    target = _script(bin_dir / "python", marker, f"{name}-python")
    if with_tool:
        _script(bin_dir / TOOL, marker, f"{name}-{TOOL}")
    return target


@pytest.fixture
def world(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    marker = tmp_path / "calls.log"
    host_bin = tmp_path / "host-bin"
    _script(host_bin / TOOL, marker, f"host-{TOOL}")
    monkeypatch.setenv("PATH", os.pathsep.join((str(host_bin), "/usr/bin", "/bin")))
    selected = _env(tmp_path, "selected", with_tool=True, marker=marker)
    bare = _env(tmp_path, "bare", with_tool=False, marker=marker)
    other = _env(tmp_path, "other", with_tool=True, marker=marker)
    registry = CapabilityRegistry()
    registry._register_bootstrap(_bootstrap(TOOL, (TOOL,), ("validate", "compile")))
    return SimpleNamespace(
        project=project, marker=marker, host_bin=host_bin, selected=selected,
        bare=bare, other=other, registry=registry, root=str(project.resolve()),
    )


def _approve(world, *targets: Path) -> None:
    provenance = ApprovalProvenance(world.root, "council", "chairman", "human")
    for target in targets:
        world.registry.approve_execution_target(world.project, str(target), provenance)


def _request(world, command: str, target: Path | None) -> ExecutionRequest:
    return ExecutionRequest(
        (command, "config", "x.yaml"), str(world.project), 10, TOOL, "validate",
        target_executable=None if target is None else str(target),
    )


def _calls(world) -> list[str]:
    return world.marker.read_text(encoding="utf-8").split() if world.marker.exists() else []


# --- detection -------------------------------------------------------------

def test_detection_uses_only_the_selected_target_never_the_host_path(world):
    installer = StructuredInstallerRegistration("m", object())
    assert installer.is_available(TOOL, str(world.selected)) is True
    # A host hit for the same name does not make a target lacking it available.
    assert installer.is_available(TOOL, str(world.bare)) is False
    # Host PATH changes cannot flip either answer.
    os.environ["PATH"] = "/usr/bin:/bin"
    assert installer.is_available(TOOL, str(world.selected)) is True
    assert installer.is_available(TOOL, str(world.bare)) is False


def test_unknown_or_unusable_target_is_never_available(world):
    installer = StructuredInstallerRegistration("m", object(), availability_checker=lambda _t: "/x")
    for target in ("relative/python", "/nonexistent/bin/python"):
        assert installer.is_available(TOOL, target) is False
        assert resolve_tool_in_target(target, TOOL) is None
    # No target selected (an effect without an execution-target concept):
    # the unchanged host checker applies.
    assert installer.is_available(TOOL, None) is True


def test_target_lookup_never_resolves_a_path_like_or_different_name(world):
    assert resolve_tool_in_target(str(world.selected), "../python") is None
    assert resolve_tool_in_target(str(world.selected), "nope", TOOL) == str(world.selected.parent / TOOL)


# --- approval --------------------------------------------------------------

def test_target_bound_request_requires_an_approved_target(world):
    command = str(world.selected.parent / TOOL)
    assert validate_request(_request(world, command, world.selected), world.project, world.registry).diagnostics.startswith(
        "Execution target is not approved")
    _approve(world, world.selected)
    assert validate_request(_request(world, command, world.selected), world.project, world.registry) is None


def test_approval_of_one_target_never_covers_another(world):
    _approve(world, world.selected)
    command = str(world.other.parent / TOOL)
    assert "not approved" in validate_request(
        _request(world, command, world.other), world.project, world.registry).diagnostics
    # Bound to the approved target, a tool of ANOTHER environment is rejected.
    violation = validate_request(_request(world, command, world.selected), world.project, world.registry)
    assert "outside the selected target environment" in violation.diagnostics


def test_host_resolved_or_bare_command_is_rejected_for_a_target_bound_request(world):
    _approve(world, world.selected)
    for command in (str(world.host_bin / TOOL), TOOL):
        violation = validate_request(_request(world, command, world.selected), world.project, world.registry)
        assert violation is not None and "outside the selected target environment" in violation.diagnostics


def test_target_bound_request_requires_a_capability_named_tool_that_exists(world):
    _approve(world, world.selected)
    _script(world.selected.parent / "unrelated", world.marker, "unrelated")
    unrelated = validate_request(
        _request(world, str(world.selected.parent / "unrelated"), world.selected), world.project, world.registry)
    assert "does not match capability" in unrelated.diagnostics
    (world.selected.parent / TOOL).unlink()
    missing = validate_request(
        _request(world, str(world.selected.parent / TOOL), world.selected), world.project, world.registry)
    assert missing.status == TOOL_UNAVAILABLE.value


def test_unusable_target_stays_fail_closed(world):
    gone = world.selected.parent.parent / "gone" / "bin" / "python"
    provenance = ApprovalProvenance(world.root, "c", "c", "h")
    world.registry.approve_execution_target(world.project, str(gone), provenance)
    assert validate_request(
        _request(world, str(gone.parent / TOOL), gone), world.project, world.registry).status == TOOL_UNAVAILABLE.value


def test_target_approval_needs_complete_provenance_for_this_project(world):
    with pytest.raises(ValueError):
        world.registry.approve_execution_target(
            world.project, str(world.selected), ApprovalProvenance(world.root, "", "c", "h"))
    with pytest.raises(ValueError):
        world.registry.approve_execution_target(
            world.project, str(world.selected), ApprovalProvenance("/elsewhere", "c", "c", "h"))
    with pytest.raises(ValueError):
        world.registry.approve_execution_target(
            world.project, "relative/python", ApprovalProvenance(world.root, "c", "c", "h"))


def test_plan_selected_environment_is_approved_even_without_steps(world):
    plan = SetupPlan("p", "proj", status="approved", environment_target_executable=str(world.selected))
    register_setup_step_targets(
        plan, world.project, engineering_council_ref="c", chairman_approval_ref="c",
        human_approval_ref="h", capability_registry=world.registry,
    )
    assert world.registry.is_execution_target_approved(world.project, str(world.selected))
    assert not world.registry.is_execution_target_approved(world.project, str(world.other))
    unapproved_step = SetupStep("s", "r", "install", package="x", target_executable=str(world.other))
    plan = SetupPlan("p2", "proj", status="approved", steps=(unapproved_step,))
    register_setup_step_targets(
        plan, world.project, engineering_council_ref="c", chairman_approval_ref="c",
        human_approval_ref="h", capability_registry=world.registry,
    )
    assert not world.registry.is_execution_target_approved(world.project, str(world.other))


# --- execution and verification --------------------------------------------

def test_execution_runs_exactly_the_target_tool_even_if_the_host_path_changes(world, monkeypatch):
    _approve(world, world.selected)
    command = str(world.selected.parent / TOOL)
    assert execute_controlled(_request(world, command, world.selected), world.project, world.registry) is not None
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # host copy disappears
    assert execute_controlled(_request(world, command, world.selected), world.project, world.registry) is not None
    assert _calls(world) == ["selected-esphome", "selected-esphome"]


def _step(world) -> VerificationStep:
    return VerificationStep(
        step_id="s", area=".", working_directory=".", verification_kind="validate",
        test_system="esphome", runner_type="esphome_check", policy="controlled_execution",
        metadata={"config": "x.yaml"},
    )


def test_runner_never_falls_back_to_a_host_tool_when_the_target_lacks_it(world):
    (world.project / "x.yaml").write_text("esphome: {}\n", encoding="utf-8")
    with verification_target(str(world.bare)):
        result = ESPHomeCheckRunner().execute(_step(world), world.project)
    assert result.status == TOOL_UNAVAILABLE.value and result.unavailable_tool == TOOL
    assert _calls(world) == []  # neither the host tool nor any other ran


def test_runner_executes_the_selected_target_tool_and_repeats_identically(world, monkeypatch):
    (world.project / "x.yaml").write_text("esphome: {}\n", encoding="utf-8")
    import app.execution as execution
    _approve(world, world.selected)
    import functools
    monkeypatch.setattr(
        execution, "execute_controlled",
        functools.partial(execution.execute_controlled, capability_registry=world.registry),
    )
    for _ in range(2):  # retry verification: same tool both times
        with verification_target(str(world.selected)):
            result = ESPHomeCheckRunner().execute(_step(world), world.project)
        assert result.passed is True, result.diagnostics
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # host PATH change
    with verification_target(str(world.selected)):
        assert ESPHomeCheckRunner().execute(_step(world), world.project).passed is True
    assert set(_calls(world)) == {"selected-esphome"}
    # An unapproved target is rejected at the boundary, never run.
    with verification_target(str(world.other)):
        rejected = ESPHomeCheckRunner().execute(_step(world), world.project)
    assert rejected.status == TOOL_UNAVAILABLE.value
    assert "other-esphome" not in _calls(world)


def test_target_environment_prose_lists_exactly_the_selector_map():
    """The TEST_040 entry in the Requirements source names exactly the
    selectors the Evidence selector map proves it with -- no more, no less."""
    import re
    from requirements.evidence.selector_map import SELECTOR_MAP
    rst = (Path(__file__).parents[1] / "requirements" / "verification" / "tests.rst").read_text(encoding="utf-8")
    block = rst[rst.index(":id: TEST_040"):]
    block = block[:block.index(".. test::")] if ".. test::" in block else block
    listed = set(re.findall(r"``(tests/[^`]+::[^`]+)``", block))
    assert listed == set(SELECTOR_MAP["TEST_040"])
