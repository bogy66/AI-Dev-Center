"""Regressions for CLAUDE-ADC-S43-S44-PATH-SAFETY-SEMANTICS-FIX-001.

Unifies S4.3 Change Application and S4.4 Change Provenance & Attribution
path-safety semantics under one shared policy (app.safe_project_path.
resolve_safe_path). An unsafe/escaping requested path is now a
deterministic, fail-closed APPLICATION FAILURE identically represented
whether provenance is enabled or not: skipped with reason "unsafe_path",
never silently dropped, never an uncaught exception specific to one
route. Uses only generic, non-toolchain-specific fixture paths
throughout (data/config.txt, src/item.txt, ...).
"""
from pathlib import Path

from app.change_application import ChangeApplicationService
from app.change_provenance import RunChangeProvenance
from app.developer_file_applier import DeveloperFileApplier
from app.safe_project_path import resolve_safe_path
from app.workflow_manager import WorkflowManager


# ---------------------------------------------------------------------
# A: direct relative escape
# ---------------------------------------------------------------------

def test_a_direct_relative_escape_is_skipped_with_unsafe_path(tmp_path):
    outside = tmp_path.parent / "escaped_a.txt"
    applier = DeveloperFileApplier(tmp_path)

    result = applier.apply({"changes": [{"file": "../escaped_a.txt", "action": "create", "content": "danger"}]})

    assert result == {"applied": [], "skipped": [{"file": "../escaped_a.txt", "reason": "unsafe_path"}]}
    assert not outside.exists()


# ---------------------------------------------------------------------
# B: absolute path
# ---------------------------------------------------------------------

def test_b_absolute_path_is_skipped_with_unsafe_path(tmp_path):
    outside = tmp_path.parent / "escaped_b.txt"
    applier = DeveloperFileApplier(tmp_path)

    result = applier.apply({"changes": [{"file": str(outside), "action": "create", "content": "danger"}]})

    assert result == {"applied": [], "skipped": [{"file": str(outside), "reason": "unsafe_path"}]}
    assert not outside.exists()


# ---------------------------------------------------------------------
# C: symlink-mediated escape
# ---------------------------------------------------------------------

def test_c_symlink_escape_is_skipped_with_unsafe_path(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (project / "link").symlink_to(outside_dir, target_is_directory=True)
    applier = DeveloperFileApplier(project)

    result = applier.apply({"changes": [{"file": "link/escaped.txt", "action": "create", "content": "danger"}]})

    assert result == {"applied": [], "skipped": [{"file": "link/escaped.txt", "reason": "unsafe_path"}]}
    assert not (outside_dir / "escaped.txt").exists()


# ---------------------------------------------------------------------
# D: provenance-enabled -- no exception, same skipped semantics, no
# outside baseline/hash/event access
# ---------------------------------------------------------------------

def test_d_provenance_enabled_same_unsafe_path_no_exception(tmp_path):
    manager = WorkflowManager(tmp_path / "state.json")
    recorder = RunChangeProvenance(manager, "run-d", tmp_path)
    applier = DeveloperFileApplier(tmp_path)
    outside = tmp_path.parent / "escaped_d.txt"

    result = recorder.apply(applier, {"changes": [{"file": "../escaped_d.txt", "action": "create", "content": "danger"}]}, "development")

    assert result == {"applied": [], "skipped": [{"file": "../escaped_d.txt", "reason": "unsafe_path"}]}
    assert not outside.exists()
    assert manager.load().get("change_provenance", {}).get("run-d", {}) == {}


# ---------------------------------------------------------------------
# E: direct vs provenance equivalence
# ---------------------------------------------------------------------

def test_e_direct_and_provenance_paths_classify_unsafe_change_identically(tmp_path):
    changes = {"changes": [{"file": "../escaped_e.txt", "action": "create", "content": "danger"}]}

    direct_root = tmp_path / "direct"
    direct_root.mkdir()
    direct_result = DeveloperFileApplier(direct_root).apply(changes)

    provenance_root = tmp_path / "provenance"
    provenance_root.mkdir()
    manager = WorkflowManager(provenance_root / "state.json")
    recorder = RunChangeProvenance(manager, "run-e", provenance_root)
    provenance_result = recorder.apply(DeveloperFileApplier(provenance_root), changes, "development")

    expected = {"applied": [], "skipped": [{"file": "../escaped_e.txt", "reason": "unsafe_path"}]}
    assert direct_result == expected
    assert provenance_result == expected


# ---------------------------------------------------------------------
# F: mixed safe + unsafe -> partial apply, overall apply_failed
# ---------------------------------------------------------------------

def test_f_mixed_safe_and_unsafe_changes_overall_apply_failed(tmp_path):
    applier = DeveloperFileApplier(tmp_path)
    changes = {
        "changes": [
            {"file": "data/config.txt", "action": "create", "content": "ok"},
            {"file": "../escaped_f.txt", "action": "create", "content": "danger"},
        ],
    }

    result = applier.apply(changes)

    assert result["applied"] == ["data/config.txt"]
    assert result["skipped"] == [{"file": "../escaped_f.txt", "reason": "unsafe_path"}]
    assert (tmp_path / "data" / "config.txt").read_text() == "ok"
    assert ChangeApplicationService.status_for(result) == "apply_failed"


# ---------------------------------------------------------------------
# G: normal safe create/update/delete unchanged
# ---------------------------------------------------------------------

def test_g_normal_safe_create_update_delete_unchanged(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    create_result = applier.apply({"changes": [{"file": "src/item.txt", "action": "create", "content": "v1"}]})
    assert create_result == {"applied": ["src/item.txt"], "skipped": []}

    update_result = applier.apply({"changes": [{"file": "src/item.txt", "action": "update", "content": "v2"}]})
    assert update_result == {"applied": ["src/item.txt"], "skipped": []}
    assert (tmp_path / "src" / "item.txt").read_text() == "v2"

    delete_result = applier.apply({"changes": [{"file": "src/item.txt", "action": "delete", "content": ""}]})
    assert delete_result == {"applied": ["src/item.txt"], "skipped": []}
    assert not (tmp_path / "src" / "item.txt").exists()


# ---------------------------------------------------------------------
# I: initial vs rework phase -- identical path-safety contract
# ---------------------------------------------------------------------

def test_i_initial_and_rework_phases_share_the_same_path_safety_contract(tmp_path):
    service = ChangeApplicationService(DeveloperFileApplier)
    changes = {"changes": [{"file": "../escaped_i.txt", "action": "create", "content": "x"}]}
    expected = {"applied": [], "skipped": [{"file": "../escaped_i.txt", "reason": "unsafe_path"}]}

    assert service.apply(tmp_path, changes, "development", False) == expected
    assert service.apply(tmp_path, changes, "development", True) == expected


# ---------------------------------------------------------------------
# J: development vs test kind -- identical path-safety contract
# ---------------------------------------------------------------------

def test_j_development_and_test_kinds_share_the_same_path_safety_contract(tmp_path):
    service = ChangeApplicationService(DeveloperFileApplier)
    changes = {"changes": [{"file": "../escaped_j.txt", "action": "create", "content": "x"}]}
    expected = {"applied": [], "skipped": [{"file": "../escaped_j.txt", "reason": "unsafe_path"}]}

    assert service.apply(tmp_path, changes, "development", False) == expected
    assert service.apply(tmp_path, changes, "test", False) == expected


# ---------------------------------------------------------------------
# K: genericity -- generic paths, no toolchain-specific central logic
# ---------------------------------------------------------------------

def test_k_genericity_generic_paths_no_toolchain_assumptions(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    result = applier.apply({
        "changes": [
            {"file": "data/config.txt", "action": "create", "content": "generic"},
            {"file": "../../etc/generic_escape.cfg", "action": "create", "content": "danger"},
        ],
    })

    assert result["applied"] == ["data/config.txt"]
    assert result["skipped"] == [{"file": "../../etc/generic_escape.cfg", "reason": "unsafe_path"}]


def test_k_safe_project_path_module_has_no_toolchain_specific_tokens():
    source = Path("app/safe_project_path.py").read_text(encoding="utf-8").lower()
    for forbidden in ("esphome", "pytest", "platformio", "cmake", "javascript", ".py\"", ".js\"", ".ino"):
        assert forbidden not in source


# ---------------------------------------------------------------------
# Additional safety-condition coverage: empty/invalid/root-self path
# ---------------------------------------------------------------------

def test_empty_and_missing_file_values_are_unsafe(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    result = applier.apply({
        "changes": [
            {"file": "", "action": "create", "content": "x"},
            {"action": "create", "content": "y"},
        ],
    })

    assert result["applied"] == []
    assert result["skipped"] == [
        {"file": "", "reason": "unsafe_path"},
        {"file": None, "reason": "unsafe_path"},
    ]


def test_path_naming_the_project_root_itself_is_unsafe(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    result = applier.apply({"changes": [{"file": ".", "action": "create", "content": "x"}]})

    assert result == {"applied": [], "skipped": [{"file": ".", "reason": "unsafe_path"}]}


# ---------------------------------------------------------------------
# Direct unit coverage of the shared policy function itself
# ---------------------------------------------------------------------

def test_resolve_safe_path_accepts_a_normal_relative_path(tmp_path):
    assert resolve_safe_path(tmp_path, "data/config.txt") == (tmp_path / "data" / "config.txt").resolve()


def test_resolve_safe_path_rejects_absolute(tmp_path):
    assert resolve_safe_path(tmp_path, "/etc/passwd") is None


def test_resolve_safe_path_rejects_traversal(tmp_path):
    assert resolve_safe_path(tmp_path, "../escape.txt") is None


def test_resolve_safe_path_rejects_empty_none_and_non_string(tmp_path):
    assert resolve_safe_path(tmp_path, "") is None
    assert resolve_safe_path(tmp_path, None) is None
    assert resolve_safe_path(tmp_path, 123) is None
