"""S5.2 target-workspace integrity (CLAUDE-ADC-S5-VERIFICATION-WORKSPACE-
INTEGRITY-FIX-001, strengthened by FIX-002).

A fresh authorized Real-System-E2E reached 93% and failed correctly at
Controlled Git with "new working-tree change outside approved
provenance: .gitignore" -- a side effect of the real `esphome compile`
subprocess invoked during S5 verification, never accounted for by any
provenance because verification is never authorized to mutate the
target workspace at all.

These tests prove the closed gap directly at the S5.2 boundary itself:

    ControlledRunnerRegistry.execute_step()
        -> _execute_verification_isolated()
            -> runner executes against a disposable shadow copy of the
               real target workspace (never the real one)
            -> the real target workspace is snapshotted before/after as
               deterministic, attributable proof
            -> PASS/FAIL/etc. is only ever the runner's own real result
               when the real target workspace is provably unchanged;
               otherwise the step is WORKSPACE_INTEGRITY_VIOLATION,
               regardless of the runner's own reported exit code.

Never a `.gitignore`-specific rule, never ESPHome-specific, never a
change to Controlled Git's own fail-closed behavior (kept as
defense-in-depth -- see tests/test_controlled_git_stage.py::
test_verification_tool_side_effect_blocks_commit_instead_of_false_success,
untouched by this task).

FIX-002 adds the size/mtime same-size- and mtime-preserving-mutation,
removed-path, and object-type-replacement regressions below: FIX-001's
original fingerprint (relative path -> (size, mtime_ns)) could not
distinguish a real-target file rewritten to different content of the
same byte length (optionally with its original mtime restored/forced
afterward) from a genuinely untouched file. The fingerprint is now a
cryptographic content hash for regular files and a raw, never-followed
symlink target for symlinks (see app.verification._entry_fingerprint).
"""
from __future__ import annotations

import os
import subprocess

import pytest

import app.execution as _execution
from app.verification import (
    FAIL, PASS, TOOL_UNAVAILABLE, WORKSPACE_INTEGRITY_VIOLATION,
    ControlledRunnerRegistry, ESPHomeCheckRunner, VerificationPlan,
    VerificationRunner, VerificationStep, VerificationStepResult,
    build_default_registry,
)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _snapshot(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*") if p.is_file()
    }


# ============================================================================
# 1. Verification-only runner leaves target workspace unchanged
# ============================================================================
class _IncidentalSideEffectRunner(VerificationRunner):
    """Technology-neutral synthetic runner proving the contract is not
    ESPHome-only: writes incidental cache/build artifacts into whatever
    cwd it is given, exactly like a real compiler/validator would."""

    runner_type = "synthetic_incidental_side_effect"

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == self.runner_type

    def execute(self, step: VerificationStep, project_root) -> VerificationStepResult:
        from pathlib import Path
        cwd = Path(project_root)
        (cwd / ".synthetic-cache").mkdir(exist_ok=True)
        (cwd / ".synthetic-cache" / "artifact.bin").write_text("cache")
        (cwd / ".toolgitignore").write_text("*.cache\n")
        return VerificationStepResult(
            step_id=step.step_id, area=step.area, status=PASS.value,
            verification_kind=step.verification_kind,
            runner_type=step.runner_type, passed=True, return_code=0,
        )


def test_synthetic_runner_incidental_side_effects_do_not_reach_target(tmp_path):
    before = _snapshot(tmp_path)
    registry = ControlledRunnerRegistry([_IncidentalSideEffectRunner()])
    step = VerificationStep(
        step_id="synthetic", area=".", working_directory=".",
        verification_kind="validate", test_system="synthetic",
        runner_type="synthetic_incidental_side_effect",
        policy="controlled_execution",
    )
    result = registry.execute_step(step, str(tmp_path))

    assert result.status == PASS.value
    assert result.passed is True
    # The runner's own incidental artifacts landed only in its isolated
    # execution area -- the real target project remains exactly as before.
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / ".synthetic-cache").exists()
    assert not (tmp_path / ".toolgitignore").exists()


# ============================================================================
# 2. Exact ESPHome regression: compile-created .gitignore/.esphome/ never
#    reach the real target project
# ============================================================================
def test_esphome_compile_incidental_gitignore_and_cache_do_not_reach_target(tmp_path, monkeypatch):
    _write(tmp_path / "esphome" / "device.yaml", "esphome:\n  name: test\n")
    before = _snapshot(tmp_path)

    class FakeProcess:
        returncode = 0
        stdout = "INFO Successfully compiled program."
        stderr = ""
        timed_out = False

    def fake_run(*args, **kwargs):
        # Reproduce the real discovered side effect: ESPHome writes a
        # .gitignore and its own build-cache directory into whatever cwd
        # it was actually invoked in.
        from pathlib import Path as _Path
        cwd = _Path(kwargs.get("cwd"))
        (cwd / ".gitignore").write_text(".esphome/\n")
        esphome_cache = cwd / ".esphome"
        esphome_cache.mkdir(exist_ok=True)
        (esphome_cache / "build_cache").write_text("cache")
        return FakeProcess()

    monkeypatch.setattr(_execution, "run_contained_process", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/esphome")

    registry = ControlledRunnerRegistry([ESPHomeCheckRunner()])
    step = VerificationStep(
        step_id="esphome-compile", area=".", working_directory=".",
        verification_kind="compile", test_system="esphome",
        runner_type="esphome_check", policy="controlled_execution",
        metadata={"config": "esphome/device.yaml"},
    )
    result = registry.execute_step(step, str(tmp_path))

    assert result.status == PASS.value
    assert result.passed is True
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / ".gitignore").exists()
    assert not (tmp_path / ".esphome").exists()


# ============================================================================
# 3. Successful verifier + unauthorized real-target mutation must NOT be
#    a clean authoritative result (defense-in-depth: a runner that somehow
#    bypasses its given cwd and writes to the real target anyway)
# ============================================================================
class _BypassingRunner(VerificationRunner):
    """Simulates a non-compliant/buggy runner that ignores the cwd it is
    handed and mutates the REAL target directly via an injected callback
    -- proving the registry's own post-execution proof catches real-target
    mutation even when the isolation copy itself was bypassed, for any
    kind of mutation the callback performs (new/removed/modified path,
    same-size content rewrite, mtime-preserving rewrite, object-type
    replacement, ...), not merely when isolation works as intended."""

    runner_type = "bypassing"

    def __init__(self, real_root, mutate):
        self._real_root = real_root
        self._mutate = mutate

    def can_run(self, step: VerificationStep) -> bool:
        return step.runner_type == "bypassing"

    def execute(self, step: VerificationStep, project_root) -> VerificationStepResult:
        self._mutate(self._real_root)
        return VerificationStepResult(
            step_id=step.step_id, area=step.area, status=PASS.value,
            verification_kind=step.verification_kind,
            runner_type=step.runner_type, passed=True, return_code=0,
        )


def _run_bypassing(tmp_path, mutate):
    registry = ControlledRunnerRegistry([_BypassingRunner(tmp_path, mutate)])
    step = VerificationStep(
        step_id="bypass", area=".", working_directory=".",
        verification_kind="validate", test_system="bypassing",
        runner_type="bypassing", policy="controlled_execution",
    )
    return registry.execute_step(step, str(tmp_path))


def test_successful_verifier_with_bypassed_isolation_fails_closed(tmp_path):
    result = _run_bypassing(tmp_path, lambda root: (root / "unauthorized.txt").write_text("mutated"))

    assert result.status == WORKSPACE_INTEGRITY_VIOLATION.value
    assert result.passed is False
    assert "unauthorized.txt" in result.diagnostics
    # The unauthorized mutation is reported, never silently deleted.
    assert (tmp_path / "unauthorized.txt").read_text() == "mutated"


# ============================================================================
# 3b-3f. FIX-002: content/identity fingerprint regressions -- size/mtime
# alone (FIX-001's original fingerprint) cannot distinguish these from a
# genuinely untouched file; a content hash (regular files) and a raw,
# never-followed symlink target (symlinks) can.
# ============================================================================

def test_same_size_content_mutation_is_detected(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("same_size_A")  # exactly 11 bytes

    def mutate(root):
        (root / "config.yaml").write_text("same_size_B")  # also 11 bytes

    result = _run_bypassing(tmp_path, mutate)

    assert result.status == WORKSPACE_INTEGRITY_VIOLATION.value
    assert result.passed is False
    assert "config.yaml" in result.diagnostics
    assert target.read_text() == "same_size_B"  # reported, never reverted


def test_mtime_preserving_mutation_is_detected(tmp_path):
    """The exact worst case from the confirmed defect: same byte length
    AND a forced/restored original mtime -- both size and mtime give a
    false "unchanged" signal simultaneously, so only a content hash can
    still catch it."""
    target = tmp_path / "config.yaml"
    target.write_text("same_size_A")  # 11 bytes
    original_stat = target.stat()

    def mutate(root):
        path = root / "config.yaml"
        path.write_text("same_size_B")  # also 11 bytes -- size preserved too
        # Nanosecond-precision restore (not the float-seconds utime API,
        # which loses sub-microsecond precision) -- an exact match against
        # st_mtime_ns, the same precision FIX-001's fingerprint compared.
        os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    result = _run_bypassing(tmp_path, mutate)

    assert target.stat().st_size == original_stat.st_size  # size genuinely preserved
    assert target.stat().st_mtime_ns == original_stat.st_mtime_ns  # mtime_ns exactly preserved
    assert result.status == WORKSPACE_INTEGRITY_VIOLATION.value
    assert result.passed is False
    assert "config.yaml" in result.diagnostics


def test_removed_path_is_detected(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("must not disappear")

    def mutate(root):
        (root / "existing.txt").unlink()

    result = _run_bypassing(tmp_path, mutate)

    assert result.status == WORKSPACE_INTEGRITY_VIOLATION.value
    assert result.passed is False
    assert "removed" in result.diagnostics
    assert "existing.txt" in result.diagnostics


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform has no symlink support")
def test_object_type_replacement_is_detected(tmp_path):
    target = tmp_path / "asset.bin"
    target.write_bytes(b"regular file content")
    elsewhere = tmp_path / "elsewhere.bin"
    elsewhere.write_bytes(b"unrelated")

    def mutate(root):
        path = root / "asset.bin"
        path.unlink()
        path.symlink_to(elsewhere)

    result = _run_bypassing(tmp_path, mutate)

    assert result.status == WORKSPACE_INTEGRITY_VIOLATION.value
    assert result.passed is False
    assert "asset.bin" in result.diagnostics
    assert target.is_symlink()  # reported, never reverted


def test_symlink_target_change_is_detected_without_dereferencing(tmp_path):
    """A symlink's own identity is its target string -- changing what it
    points to must be detected without ever reading through it (proves
    the fingerprint never follows/dereferences a symlink)."""
    first_target = tmp_path / "first.txt"
    first_target.write_text("first")
    second_target = tmp_path / "second.txt"
    second_target.write_text("second")
    link = tmp_path / "link"
    link.symlink_to(first_target)

    def mutate(root):
        path = root / "link"
        path.unlink()
        path.symlink_to(second_target)

    result = _run_bypassing(tmp_path, mutate)

    assert result.status == WORKSPACE_INTEGRITY_VIOLATION.value
    assert os.readlink(link) == str(second_target)  # reported, never reverted


# ============================================================================
# 4. Pre-existing user-owned target state is preserved, never absorbed
# ============================================================================
def test_preexisting_foreign_state_is_preserved_and_never_flagged(tmp_path):
    foreign = tmp_path / "notes.txt"
    foreign.write_text("human notes, unrelated to this run")

    registry = ControlledRunnerRegistry([_IncidentalSideEffectRunner()])
    step = VerificationStep(
        step_id="synthetic", area=".", working_directory=".",
        verification_kind="validate", test_system="synthetic",
        runner_type="synthetic_incidental_side_effect",
        policy="controlled_execution",
    )
    result = registry.execute_step(step, str(tmp_path))

    assert result.status == PASS.value
    assert foreign.read_text() == "human notes, unrelated to this run"


# ============================================================================
# 5. Failure path preserves diagnostics/result fidelity and never
#    corrupts target state
# ============================================================================
def test_failing_verifier_preserves_diagnostics_and_target_state(tmp_path):
    class _FailingRunner(VerificationRunner):
        runner_type = "synthetic_failing"

        def can_run(self, step: VerificationStep) -> bool:
            return step.runner_type == self.runner_type

        def execute(self, step: VerificationStep, project_root) -> VerificationStepResult:
            from pathlib import Path
            (Path(project_root) / ".synthetic-cache").mkdir(exist_ok=True)
            return VerificationStepResult(
                step_id=step.step_id, area=step.area, status=FAIL.value,
                verification_kind=step.verification_kind,
                runner_type=step.runner_type, passed=False, return_code=1,
                stdout="compiling...", stderr="error: undefined reference",
                command=("synthetic-tool", "build"),
            )

    before = _snapshot(tmp_path)
    registry = ControlledRunnerRegistry([_FailingRunner()])
    step = VerificationStep(
        step_id="synthetic-fail", area=".", working_directory=".",
        verification_kind="build", test_system="synthetic",
        runner_type="synthetic_failing", policy="controlled_execution",
    )
    result = registry.execute_step(step, str(tmp_path))

    assert result.status == FAIL.value
    assert result.passed is False
    assert result.return_code == 1
    assert result.stderr == "error: undefined reference"
    assert result.command == ("synthetic-tool", "build")
    assert _snapshot(tmp_path) == before


# ============================================================================
# 6. Multiple runner types: the real CMakeRunner's own build-directory
#    side effect is also isolated, proving the contract is not
#    ESPHome-only and applies uniformly across registered runner types.
# ============================================================================
def test_cmake_configure_build_directory_does_not_reach_target(tmp_path, monkeypatch):
    from app.verification import CMakeRunner

    _write(tmp_path / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.10)\n")
    before = _snapshot(tmp_path)

    class FakeProcess:
        returncode = 0
        stdout = "-- Configuring done"
        stderr = ""
        timed_out = False

    monkeypatch.setattr(_execution, "run_contained_process", lambda *a, **kw: FakeProcess())
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/cmake" if name == "cmake" else None)

    registry = ControlledRunnerRegistry([CMakeRunner()])
    step = VerificationStep(
        step_id="cmake-configure", area=".", working_directory=".",
        verification_kind="configure", test_system="cmake",
        runner_type="cmake", policy="controlled_execution",
    )
    result = registry.execute_step(step, str(tmp_path))

    assert result.status == PASS.value
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / ".ai-build").exists()


# ============================================================================
# 7. Existing result-fidelity contract (TEST_022) remains valid through
#    the registry dispatch path, end to end via execute_plan.
# ============================================================================
def test_registry_execute_plan_result_fidelity_preserved(tmp_path):
    _write(tmp_path / "tests" / "test_passes.py", "def test_passes():\n    assert True\n")
    registry = build_default_registry()
    plan = VerificationPlan(
        run_id="fidelity-run", project_root=str(tmp_path), project_kind="existing",
        area_count=1,
        steps=(VerificationStep(
            step_id="root-test-pytest", area=".", working_directory=".",
            verification_kind="test", test_system="pytest",
            runner_type="pytest", policy="controlled_execution",
        ),),
    )
    result = registry.execute_plan(plan)
    assert result.aggregate_status == PASS.value
    step_result = result.steps[0]
    assert step_result.status == PASS.value
    assert step_result.return_code == 0
    assert step_result.runner_type == "pytest"
    # pytest's own cache side effects never reach the real target project.
    assert not (tmp_path / ".pytest_cache").exists()
