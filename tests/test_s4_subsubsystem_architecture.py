"""S4 Development & Change subsubsystem architecture acceptance suite
(CLAUDE-ADC-S3-S4-S5-ARCHITECTURE-PERSIST-001, following the S2 pilot's
own model -- tests/test_s2_subsubsystem_architecture.py).

Proves the CURRENT productive S4.1-S4.4 decomposition persisted in
ADC_Zielbild_Ausfuehrliche_Beschreibung.txt §4C: exactly one productive
Primary Owner per Sx.y, real input/output artifacts, allowed/forbidden
Authority, the explicit S4.2 no-op contract, path safety, provenance,
Genericity, and the S4->S5 boundary.

Does NOT duplicate:
  - tests/test_s42_test_change_noop_contract.py (the tester-facing
    prompt/repair-instruction wording matrix)
  - tests/test_s43_s44_path_safety.py (the exhaustive traversal/
    symlink/absolute-path attack matrix -- this file's own path-safety
    tests are the ARCHITECTURE-level corroboration: one representative
    case per fail-closed category, not a re-run of that matrix)
  - tests/test_s4_s5_apply_gate.py (the collision/partial-apply/rework
    gating scenarios -- this file's S4->S5 boundary section uses
    DIFFERENT concrete triggers, e.g. an unsafe path rather than an
    "already exists" collision, to add coverage rather than mirror it)
  - tests/test_change_provenance.py (RunChangeProvenance's own
    git-flag/hash-detail matrix)

Mocks/fakes are used only at the true external boundary: the LLM
executor. DeveloperFileApplier, resolve_safe_path, ChangeApplicationService
and RunChangeProvenance are always the real, productive classes, run
against real temporary files.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.change_application import ChangeApplicationService, phase_for
from app.change_provenance import RunChangeProvenance
from app.developer_changes import DeveloperChanges
from app.developer_file_applier import DeveloperFileApplier
from app.development_stage import DeveloperAgent, DevelopmentRequest, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.safe_project_path import resolve_safe_path
from app.structured_change_generation import generate_structured_changes
from app.test_change_generator import TestChangeDisposition, TestChangeGenerator

from tests._architecture_genericity_scan import scan_forbidden_ecosystem_dispatch
from tests.test_s3_legacy_hygiene_wiring import FORBIDDEN_ECOSYSTEM_NAMES

ROOT = Path(__file__).parents[1]

CENTRAL_S4_FILES = (
    "app/development_stage.py",
    "app/test_change_generator.py",
    "app/structured_change_generation.py",
    "app/developer_changes.py",
    "app/change_application.py",
    "app/developer_file_applier.py",
    "app/safe_project_path.py",
    "app/change_provenance.py",
)


class _FakeExecutor:
    def __init__(self, developer_response=None, tester_responses=None):
        self._developer_response = developer_response
        self._tester_responses = list(tester_responses or [])
        self.calls: list[str] = []

    def run(self, role, task, context, role_again):
        self.calls.append(role)
        if role == "developer":
            return self._developer_response
        if role == "tester":
            return self._tester_responses.pop(0)
        raise AssertionError(f"unexpected role: {role}")


def _dev_response(files):
    return json.dumps({
        "changes": [{"file": f, "action": "create", "content": "content"} for f in files],
        "tests": [],
    })


# =========================================================================
# S4.1 Development Change Generation -- DeveloperAgent
# =========================================================================


class TestS4_1_DevelopmentChangeGeneration:
    def test_produces_structured_changes(self):
        executor = _FakeExecutor(developer_response=_dev_response(["feature.py"]))
        agent = DeveloperAgent(executor)
        changes = agent.generate_changes(DevelopmentRequest("p", "/nonexistent", "task"))
        assert changes["changes"][0]["file"] == "feature.py"
        assert executor.calls == ["developer"]

    def test_does_not_mutate_disk_itself(self, tmp_path):
        executor = _FakeExecutor(developer_response=_dev_response(["feature.py"]))
        agent = DeveloperAgent(executor)
        agent.generate_changes(DevelopmentRequest("p", tmp_path, "task"))
        assert list(tmp_path.iterdir()) == []

    def test_empty_development_change_set_must_fail_at_application_boundary(self, tmp_path):
        executor = _FakeExecutor(developer_response=_dev_response([]))
        development_stage = DevelopmentStage(DeveloperAgent(executor))
        result = development_stage.run(DevelopmentRequest("p", tmp_path, "task"))
        assert result.status == "apply_failed"
        assert ChangeApplicationService.status_for(result.applied_changes) == "apply_failed"

    def test_s4_1_has_no_no_op_authority(self):
        """DeveloperAgent's own code never references the S4.2-owned
        disposition/no_changes_required vocabulary."""
        import ast
        import inspect
        import textwrap
        source = inspect.getsource(DeveloperAgent)
        tree = ast.parse(textwrap.dedent(source))
        body_source = ast.unparse(tree)
        assert "disposition" not in body_source
        assert "no_changes_required" not in body_source

    def test_disposition_metadata_smuggled_into_a_developer_response_cannot_legitimize_emptiness(self, tmp_path):
        """Even if a developer response somehow carries a `disposition`
        field (DeveloperChanges.parse_structured passes it through
        structurally, role-agnostically -- see its own docstring),
        DevelopmentStage/ChangeApplicationService never interpret it:
        an empty `changes` array still fails closed exactly as if no
        such field existed."""
        smuggled = json.dumps({
            "disposition": "no_changes_required", "reason": "not my call to make",
            "changes": [], "tests": [],
        })
        executor = _FakeExecutor(developer_response=smuggled)
        development_stage = DevelopmentStage(DeveloperAgent(executor))
        result = development_stage.run(DevelopmentRequest("p", tmp_path, "task"))
        assert result.status == "apply_failed"

    def test_shared_repair_mechanism_never_applies_s4_2_semantic_validation_to_the_developer_role(self):
        """generate_structured_changes() is shared MECHANICS (JSON
        parse + one repair retry) between S4.1 and S4.2, but the S4.2
        disposition semantic check (_validate_tester_disposition) is
        applied by TestChangeGenerator alone, never inside the shared
        function itself -- so a "developer" role call never has that
        validation silently applied to it."""
        import inspect
        source = inspect.getsource(generate_structured_changes)
        assert "_validate_tester_disposition" not in source
        assert "TestChangeDisposition" not in source


# =========================================================================
# S4.2 Test Change Generation -- TestChangeGenerator, full disposition
# matrix.
# =========================================================================


class TestS4_2_TestChangeGeneration:
    def _generate(self, response):
        executor = _FakeExecutor(tester_responses=[response])
        return TestChangeGenerator(executor).generate(DevelopmentRequest("p", "/x", "task")), executor

    def test_absent_disposition_defaults_to_changes(self):
        result, _ = self._generate(json.dumps({"changes": [{"file": "t.py", "action": "create", "content": "c"}], "tests": []}))
        assert result["disposition"] == TestChangeDisposition.CHANGES.value

    def test_changes_with_nonempty_mutation_is_the_normal_path(self):
        result, _ = self._generate(json.dumps({
            "disposition": "changes",
            "changes": [{"file": "t.py", "action": "create", "content": "c"}], "tests": [],
        }))
        assert result["disposition"] == "changes"
        assert len(result["changes"]) == 1

    def test_changes_with_empty_changes_fails_closed_at_the_s4_3_apply_boundary(self, tmp_path):
        """TestChangeGenerator itself does not reject disposition=
        "changes" with an empty changes array -- that shape is only
        rejected downstream, by the SAME S4.3 apply-gate MUST_FAIL rule
        that governs S4.1 (ChangeApplicationService.status_for), never
        by a second, competing S4.2-owned emptiness rule."""
        result, _ = self._generate(json.dumps({"disposition": "changes", "changes": [], "tests": []}))
        assert result["disposition"] == "changes"
        applier = DeveloperFileApplier(tmp_path)
        apply_result = applier.apply(result)
        assert ChangeApplicationService.status_for(apply_result) == "apply_failed"

    def test_bare_empty_changes_is_not_a_no_op_and_fails_closed(self, tmp_path):
        result, _ = self._generate(json.dumps({"changes": [], "tests": []}))
        assert result["disposition"] == TestChangeDisposition.CHANGES.value
        applier = DeveloperFileApplier(tmp_path)
        apply_result = applier.apply(result)
        assert ChangeApplicationService.status_for(apply_result) == "apply_failed"

    def test_no_changes_required_with_empty_changes_and_reason_is_valid(self):
        result, _ = self._generate(json.dumps({
            "disposition": "no_changes_required", "reason": "existing tests already cover this",
            "changes": [], "tests": [],
        }))
        assert result["disposition"] == "no_changes_required"
        assert result["changes"] == []

    def test_no_changes_required_with_nonempty_changes_is_invalid(self):
        with pytest.raises(ValueError, match="must not include changes"):
            self._generate(json.dumps({
                "disposition": "no_changes_required", "reason": "x",
                "changes": [{"file": "t.py", "action": "create", "content": "c"}], "tests": [],
            }))

    def test_no_changes_required_with_missing_reason_is_invalid(self):
        with pytest.raises(ValueError, match="non-empty reason"):
            self._generate(json.dumps({"disposition": "no_changes_required", "changes": [], "tests": []}))

    def test_no_changes_required_with_blank_reason_is_invalid(self):
        with pytest.raises(ValueError, match="non-empty reason"):
            self._generate(json.dumps({
                "disposition": "no_changes_required", "reason": "   ", "changes": [], "tests": [],
            }))

    def test_unknown_disposition_is_invalid(self):
        with pytest.raises(ValueError, match="unknown disposition"):
            self._generate(json.dumps({"disposition": "maybe", "changes": [], "tests": []}))

    def test_semantic_violation_triggers_no_second_repair_or_provider_attempt(self):
        """A structurally valid JSON response that fails the S4.2
        SEMANTIC contract (no_changes_required + real changes) is a
        different failure class than a malformed JSON response -- the
        one-repair-then-fail-closed policy belongs exclusively to
        structural/JSON malformation (generate_structured_changes'
        own docstring); a semantic violation must never trigger a
        second executor.run() call."""
        bad = json.dumps({
            "disposition": "no_changes_required", "reason": "x",
            "changes": [{"file": "t.py", "action": "create", "content": "c"}], "tests": [],
        })
        executor = _FakeExecutor(tester_responses=[bad])
        with pytest.raises(ValueError):
            TestChangeGenerator(executor).generate(DevelopmentRequest("p", "/x", "task"))
        assert executor.calls == ["tester"]

    def test_tests_metadata_array_is_non_authoritative_over_disposition(self):
        for tests_value in ([], ["pytest -q"], ["a", "b", "c"]):
            result, _ = self._generate(json.dumps({
                "disposition": "no_changes_required", "reason": "covered",
                "changes": [], "tests": tests_value,
            }))
            assert result["disposition"] == "no_changes_required"


# =========================================================================
# S4.3 Change Application -- ChangeApplicationService / DeveloperFileApplier
# / resolve_safe_path
# =========================================================================


class TestS4_3_ChangeApplication:
    def test_generated_content_reaches_disk_only_through_this_path(self, tmp_path):
        changes = {"changes": [{"file": "a.py", "action": "create", "content": "X"}], "tests": []}
        service = ChangeApplicationService(DeveloperFileApplier)
        result = service.apply(tmp_path, changes, "development", False)
        assert (tmp_path / "a.py").read_text() == "X"
        assert ChangeApplicationService.status_for(result) == "success"

    def test_success_iff_applied_and_nothing_skipped(self):
        assert ChangeApplicationService.status_for({"applied": ["a"], "skipped": []}) == "success"
        assert ChangeApplicationService.status_for({"applied": [], "skipped": []}) == "apply_failed"
        assert ChangeApplicationService.status_for({"applied": ["a"], "skipped": ["b"]}) == "apply_failed"
        assert ChangeApplicationService.status_for({"applied": [], "skipped": ["b"]}) == "apply_failed"

    def test_partial_mutation_is_apply_failed(self, tmp_path):
        (tmp_path / "existing.py").write_text("STALE")
        changes = {"changes": [
            {"file": "new.py", "action": "create", "content": "X"},
            {"file": "existing.py", "action": "create", "content": "Y"},
        ], "tests": []}
        applier = DeveloperFileApplier(tmp_path)
        result = applier.apply(changes)
        assert result["applied"] == ["new.py"]
        assert ChangeApplicationService.status_for(result) == "apply_failed"

    def test_unsafe_path_is_skipped_unsafe_path(self, tmp_path):
        changes = {"changes": [{"file": "../escape.py", "action": "create", "content": "X"}], "tests": []}
        applier = DeveloperFileApplier(tmp_path)
        result = applier.apply(changes)
        assert result["skipped"] == [{"file": "../escape.py", "reason": "unsafe_path"}]
        assert not (tmp_path.parent / "escape.py").exists()

    def test_traversal_and_absolute_paths_fail_closed(self, tmp_path):
        assert resolve_safe_path(tmp_path, "../outside.py") is None
        assert resolve_safe_path(tmp_path, "a/../../outside.py") is None
        assert resolve_safe_path(tmp_path, "/etc/passwd") is None
        assert resolve_safe_path(tmp_path, "") is None
        assert resolve_safe_path(tmp_path, None) is None

    def test_symlink_escape_fails_closed(self, tmp_path):
        outside = tmp_path.parent / "outside-target"
        outside.mkdir(exist_ok=True)
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "escape-link").symlink_to(outside)

        resolved = resolve_safe_path(project_root, "escape-link/new.py")
        assert resolved is None

    def test_direct_and_provenance_enabled_apply_classification_stays_equivalent(self, tmp_path):
        changes = {"changes": [{"file": "a.py", "action": "create", "content": "X"}], "tests": []}
        direct = DeveloperFileApplier(tmp_path).apply(changes)

        (tmp_path / "a.py").unlink()
        manager = Mock()
        provenance = RunChangeProvenance(manager, "run-1", tmp_path)
        via_provenance = provenance.apply(DeveloperFileApplier(tmp_path), changes, "development")

        assert ChangeApplicationService.status_for(direct) == ChangeApplicationService.status_for(via_provenance)
        assert direct["applied"] == via_provenance["applied"]

    def test_no_toolchain_specific_filesystem_policy(self):
        violations = scan_forbidden_ecosystem_dispatch(
            ("app/developer_file_applier.py", "app/safe_project_path.py"),
            ROOT, FORBIDDEN_ECOSYSTEM_NAMES,
        )
        assert violations == []


# =========================================================================
# S4.4 Change Provenance & Attribution -- RunChangeProvenance
# =========================================================================


class TestS4_4_ChangeProvenanceAttribution:
    def test_baseline_captured_before_mutation(self, tmp_path):
        manager = Mock()
        provenance = RunChangeProvenance(manager, "run-1", tmp_path)
        changes = {"changes": [{"file": "a.py", "action": "create", "content": "X"}], "tests": []}

        provenance.apply(DeveloperFileApplier(tmp_path), changes, "development")

        manager.capture_provenance_baseline.assert_called_once()
        call = manager.capture_provenance_baseline.call_args
        assert call.args[0] == "run-1"
        assert call.args[3] == "development"
        assert call.args[4]["file_existed_before"] is False

    def test_event_recorded_after_mutation(self, tmp_path):
        manager = Mock()
        provenance = RunChangeProvenance(manager, "run-1", tmp_path)
        changes = {"changes": [{"file": "a.py", "action": "create", "content": "X"}], "tests": []}

        provenance.apply(DeveloperFileApplier(tmp_path), changes, "development")

        manager.record_provenance_event.assert_called_once()
        event_args = manager.record_provenance_event.call_args.args
        assert event_args[1] == "a.py"
        assert event_args[2]["apply_success"] is True
        assert event_args[2]["file_exists_after"] is True

    def test_phase_attribution_initial_and_rework_development_and_test(self):
        assert phase_for("development", False) == "development"
        assert phase_for("development", True) == "rework_development"
        assert phase_for("test", False) == "test"
        assert phase_for("test", True) == "rework_test"
        with pytest.raises(ValueError):
            phase_for("unknown-kind", False)

    def test_unsafe_paths_get_no_false_baseline_hash_or_event(self, tmp_path):
        manager = Mock()
        provenance = RunChangeProvenance(manager, "run-1", tmp_path)
        changes = {"changes": [{"file": "../escape.py", "action": "create", "content": "X"}], "tests": []}

        result = provenance.apply(DeveloperFileApplier(tmp_path), changes, "development")

        manager.capture_provenance_baseline.assert_not_called()
        manager.record_provenance_event.assert_not_called()
        assert result["skipped"] == [{"file": "../escape.py", "reason": "unsafe_path"}]

    def test_consumes_s4_3_path_policy_rather_than_reimplementing_it(self):
        import inspect
        source = inspect.getsource(RunChangeProvenance)
        assert "resolve_safe_path" in source
        assert "def resolve_safe_path" not in source
        import app.change_provenance as module
        assert "from app.safe_project_path import resolve_safe_path" in inspect.getsource(module)

    def test_provenance_does_not_become_mutation_authority(self):
        """RunChangeProvenance never writes file content itself -- it
        delegates the actual mutation to `applier.apply()` and only
        records metadata about what that call did."""
        import inspect
        source = inspect.getsource(RunChangeProvenance)
        assert "write_text(" not in source
        assert "unlink(" not in source
        assert ".apply(changes)" in source


# =========================================================================
# S4 -> S5 boundary (§14): different concrete triggers than
# tests/test_s4_s5_apply_gate.py, using the productive
# DevelopmentTestingStage.
# =========================================================================


class TestS4_to_S5_Boundary:
    def _stage(self, executor, verification_registry=None, project_inspector=None, testing_stage=None):
        development_stage = DevelopmentStage(DeveloperAgent(executor))
        test_change_generator = TestChangeGenerator(executor)
        return DevelopmentTestingStage(
            development_stage, test_change_generator, DeveloperFileApplier,
            Mock(), testing_stage or Mock(),
            verification_registry=verification_registry, project_inspector=project_inspector,
        )

    def test_development_mutation_through_a_symlink_escape_blocks_s5(self, tmp_path):
        """A literal '..' path is already rejected at S4.1's own JSON-
        contract structural validation (DeveloperChanges._valid_path --
        a syntactic input-shape check, never a project-root/filesystem
        decision) before it can even reach S4.3's resolve_safe_path().
        A symlink escape is the case that genuinely exercises S4.3's
        OWN filesystem-level authoritative safety decision: a
        syntactically ordinary relative path whose resolved target
        still lies outside the project root."""
        outside = tmp_path.parent / "s4-s5-boundary-outside"
        outside.mkdir(exist_ok=True)
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "escape-link").symlink_to(outside)

        executor = _FakeExecutor(developer_response=json.dumps({
            "changes": [{"file": "escape-link/new.py", "action": "create", "content": "X"}], "tests": [],
        }))
        test_change_generator = Mock()
        verification_registry = Mock()
        stage = DevelopmentTestingStage(
            DevelopmentStage(DeveloperAgent(executor)), test_change_generator, DeveloperFileApplier,
            Mock(), Mock(), verification_registry=verification_registry, project_inspector=Mock(),
        )

        result = stage.run(DevelopmentRequest("p", project_root, "task"))

        assert result.status == "apply_failed"
        assert result.failure_stage == "development_apply"
        assert result.development_result.applied_changes["skipped"] == [
            {"file": "escape-link/new.py", "reason": "unsafe_path"},
        ]
        test_change_generator.generate.assert_not_called()
        verification_registry.execute_plan.assert_not_called()
        assert not (outside / "new.py").exists()

    def test_valid_explicit_no_op_test_mutation_is_not_required_and_s5_still_starts(self, tmp_path):
        executor = _FakeExecutor(
            developer_response=_dev_response(["feature.py"]),
            tester_responses=[json.dumps({
                "disposition": "no_changes_required", "reason": "existing coverage suffices",
                "changes": [], "tests": [],
            })],
        )
        from app.verification import PASS, VerificationResult, VerificationStepResult
        passing = VerificationStepResult(
            step_id="unit", area="root", status=PASS.value, verification_kind="test",
            runner_type="pytest", passed=True, return_code=0, stdout="", stderr="",
            command=("pytest",), timed_out=False,
        )
        verification_registry = Mock()
        verification_registry.execute_plan.return_value = VerificationResult(run_id="r", steps=(passing,), aggregate_status=PASS.value)
        project_inspector = Mock()
        project_inspector.build_intelligence.return_value = None
        from app.testing_stage import TestingStage, DiagnosisReviewer
        testing_stage = TestingStage(DiagnosisReviewer(executor))
        stage = self._stage(executor, verification_registry=verification_registry, project_inspector=project_inspector, testing_stage=testing_stage)

        result = stage.run(DevelopmentRequest("p", tmp_path, "task"))

        assert result.apply_result is None  # no test-file apply was ever attempted
        verification_registry.execute_plan.assert_called_once()  # S5 still ran

    def test_development_mutation_is_always_required_even_for_a_no_op_test_cycle(self, tmp_path):
        """The development mutation gate applies unconditionally --
        S4.2's no-op authority covers only the TEST mutation, never
        the development one."""
        executor = _FakeExecutor(developer_response=_dev_response([]))
        test_change_generator = Mock()
        stage = self._stage(executor)
        stage._test_change_generator = test_change_generator

        result = stage.run(DevelopmentRequest("p", tmp_path, "task"))

        assert result.failure_stage == "development_apply"
        test_change_generator.generate.assert_not_called()

    def test_successful_required_mutations_permit_s5(self, tmp_path):
        executor = _FakeExecutor(
            developer_response=_dev_response(["feature.py"]),
            tester_responses=[json.dumps({
                "changes": [{"file": "test_feature.py", "action": "create", "content": "def test(): pass"}],
                "tests": [],
            })],
        )
        from app.verification import PASS, VerificationResult, VerificationStepResult
        passing = VerificationStepResult(
            step_id="unit", area="root", status=PASS.value, verification_kind="test",
            runner_type="pytest", passed=True, return_code=0, stdout="", stderr="",
            command=("pytest",), timed_out=False,
        )
        verification_registry = Mock()
        verification_registry.execute_plan.return_value = VerificationResult(run_id="r", steps=(passing,), aggregate_status=PASS.value)
        project_inspector = Mock()
        project_inspector.build_intelligence.return_value = None
        stage = self._stage(executor, verification_registry=verification_registry, project_inspector=project_inspector)

        result = stage.run(DevelopmentRequest("p", tmp_path, "task"))

        assert result.failure_stage is None
        verification_registry.execute_plan.assert_called_once()


# =========================================================================
# Genericity / Non-Specialization (§4G) -- improved beyond ast.Compare.
# =========================================================================


class TestS4GenericityNonSpecialization:
    def test_central_s4_orchestration_has_no_forbidden_ecosystem_dispatch(self):
        violations = scan_forbidden_ecosystem_dispatch(CENTRAL_S4_FILES, ROOT, FORBIDDEN_ECOSYSTEM_NAMES)
        assert violations == []

    def test_no_hardcoded_filename_extension_selection_in_central_policy(self):
        """Central S4 mutation policy (DeveloperFileApplier, resolve_
        safe_path, ChangeApplicationService) decides purely by
        action/path-safety, never by inspecting a file's extension."""
        from tests._architecture_genericity_scan import scan_forbidden_extension_literals
        violations = scan_forbidden_extension_literals(
            ("app/developer_file_applier.py", "app/safe_project_path.py", "app/change_application.py"),
            ROOT, frozenset({".py", ".cpp", ".c", ".h", ".js", ".ts", ".yaml", ".yml", ".json"}),
        )
        assert violations == []

    def test_heterogeneous_file_shapes_reach_the_same_central_application_path(self, tmp_path):
        """§26: a Python source file and a native/build-config file
        (materially different shapes) both flow through the exact same
        ChangeApplicationService/DeveloperFileApplier path, with zero
        per-extension branching required."""
        changes = {"changes": [
            {"file": "app.py", "action": "create", "content": "print('x')"},
            {"file": "CMakeLists.txt", "action": "create", "content": "cmake_minimum_required(VERSION 3.10)"},
        ], "tests": []}
        service = ChangeApplicationService(DeveloperFileApplier)
        result = service.apply(tmp_path, changes, "development", False)
        assert ChangeApplicationService.status_for(result) == "success"
        assert (tmp_path / "app.py").exists()
        assert (tmp_path / "CMakeLists.txt").exists()


# =========================================================================
# Existing foreign repository (§27): central S4 mutation confinement
# respects arbitrary pre-existing structure and imposes no ADC layout.
# =========================================================================


class TestS4ExistingForeignRepository:
    def test_mutation_stays_confined_and_respects_existing_conventions(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.cpp").write_text("// pre-existing native source\n")
        (tmp_path / "Makefile").write_text("all:\n\techo build\n")
        (tmp_path / "docs").mkdir()

        changes = {"changes": [
            {"file": "src/feature.cpp", "action": "create", "content": "// new"},
            {"file": "src/main.cpp", "action": "update", "content": "// updated pre-existing file"},
            {"file": "../outside.cpp", "action": "create", "content": "// escape attempt"},
        ], "tests": []}
        service = ChangeApplicationService(DeveloperFileApplier)
        result = service.apply(tmp_path, changes, "development", False)

        assert (tmp_path / "src" / "feature.cpp").exists()
        assert "updated pre-existing file" in (tmp_path / "src" / "main.cpp").read_text()
        assert (tmp_path / "Makefile").read_text() == "all:\n\techo build\n"  # untouched
        assert not (tmp_path.parent / "outside.cpp").exists()
        assert not (tmp_path / "tests").exists()  # no ADC-imposed layout
        assert {"file": "../outside.cpp", "reason": "unsafe_path"} in result["skipped"]
