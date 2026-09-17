from app.developer_file_applier import DeveloperFileApplier


def test_apply_create_file(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    changes = {
        "changes": [
            {
                "file": "app/example.py",
                "action": "create",
                "content": 'print("hello")'
            }
        ]
    }

    result = applier.apply(changes)

    assert result["applied"] == ["app/example.py"]
    assert (tmp_path / "app/example.py").read_text() == 'print("hello")'


def test_apply_update_file(tmp_path):
    path = tmp_path / "app/example.py"
    path.parent.mkdir(parents=True)
    path.write_text('print("old")')

    applier = DeveloperFileApplier(tmp_path)

    changes = {
        "changes": [
            {
                "file": "app/example.py",
                "action": "update",
                "content": 'print("new")'
            }
        ]
    }

    result = applier.apply(changes)

    assert result["applied"] == ["app/example.py"]
    assert path.read_text() == 'print("new")'


def test_apply_delete_file(tmp_path):
    path = tmp_path / "app/example.py"
    path.parent.mkdir(parents=True)
    path.write_text('print("old")')

    applier = DeveloperFileApplier(tmp_path)

    changes = {
        "changes": [
            {
                "file": "app/example.py",
                "action": "delete",
                "content": ""
            }
        ]
    }

    result = applier.apply(changes)

    assert result["applied"] == ["app/example.py"]
    assert not path.exists()


def test_apply_rejects_path_traversal(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    changes = {
        "changes": [
            {
                "file": "../../outside.py",
                "action": "create",
                "content": "danger"
            }
        ]
    }

    result = applier.apply(changes)

    assert result["applied"] == []
    assert not (tmp_path.parent.parent / "outside.py").exists()

def test_apply_rejects_invalid_action(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    changes = {
        "changes": [
            {
                "file": "app/example.py",
                "action": "execute",
                "content": "print('danger')"
            }
        ]
    }

    result = applier.apply(changes)

    assert result["applied"] == []
    assert not (tmp_path / "app/example.py").exists()

def test_apply_create_does_not_overwrite_existing_file(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    existing = tmp_path / "existing.py"
    existing.write_text(
        'print("original")',
        encoding="utf-8"
    )

    result = applier.apply({
        "changes": [
            {
                "file": "existing.py",
                "action": "create",
                "content": 'print("replacement")'
            }
        ]
    })

    assert existing.read_text(encoding="utf-8") == 'print("original")'
    assert result["applied"] == []


def test_apply_reports_skipped_when_create_targets_existing_file(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    existing = tmp_path / "existing.py"
    existing.write_text(
        'print("original")',
        encoding="utf-8"
    )

    result = applier.apply({
        "changes": [
            {
                "file": "existing.py",
                "action": "create",
                "content": 'print("replacement")'
            }
        ]
    })

    assert existing.read_text(encoding="utf-8") == 'print("original")'
    assert result["applied"] == []
    assert result["skipped"] == [
        {
            "file": "existing.py",
            "reason": "already_exists"
        }
    ], (
        "Expected a create-on-existing-file attempt to be reported as "
        "a visible, structured 'skipped' entry instead of being "
        "silently discarded."
    )


def test_apply_mixed_applied_and_skipped(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    existing = tmp_path / "existing.py"
    existing.write_text(
        'print("original")',
        encoding="utf-8"
    )

    result = applier.apply({
        "changes": [
            {
                "file": "new_file.py",
                "action": "create",
                "content": 'print("new")'
            },
            {
                "file": "existing.py",
                "action": "create",
                "content": 'print("replacement")'
            }
        ]
    })

    assert result["applied"] == ["new_file.py"]
    assert result["skipped"] == [
        {
            "file": "existing.py",
            "reason": "already_exists"
        }
    ]

    assert (
        tmp_path / "new_file.py"
    ).read_text(encoding="utf-8") == 'print("new")'

    assert existing.read_text(encoding="utf-8") == 'print("original")'


def test_apply_create_fails_on_mkdir_permission_error(tmp_path):
    applier = DeveloperFileApplier(tmp_path)

    # Create a file where we want the directory to be
    # This will cause mkdir to fail
    (tmp_path / "app").write_text("not a directory", encoding="utf-8")

    result = applier.apply({
        "changes": [
            {
                "file": "app/new_file.py",
                "action": "create",
                "content": 'print("new")'
            }
        ]
    })

    assert result["applied"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["file"] == "app/new_file.py"
    assert result["skipped"][0]["reason"].startswith("mkdir_failed:")


# ---------------------------------------------------------------------------
# CLAUDE-ADC-ZIELBILD-DIFF-FIX-001 (C1): update/delete filesystem errors
# must become a normal, classified apply-result entry (never an
# uncaught exception escaping S4.3), exactly like create's own OSError
# handling above.
# ---------------------------------------------------------------------------

def test_apply_update_fails_closed_on_write_os_error(tmp_path):
    """A real OSError (writing where a directory exists at that path)
    must be classified as skipped, never propagate out of apply()."""
    applier = DeveloperFileApplier(tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "example.py").mkdir()  # a directory, not a file

    result = applier.apply({
        "changes": [
            {"file": "app/example.py", "action": "update", "content": "new"},
        ],
    })

    assert result["applied"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["file"] == "app/example.py"
    assert result["skipped"][0]["reason"].startswith("write_failed:")

    from app.change_application import ChangeApplicationService
    assert ChangeApplicationService.status_for(result) == "apply_failed"


def test_apply_delete_fails_closed_on_unlink_os_error(tmp_path):
    """A real OSError (unlink() on a directory) must be classified as
    skipped, never propagate out of apply()."""
    applier = DeveloperFileApplier(tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "example.py").mkdir()  # a directory, not a file

    result = applier.apply({
        "changes": [
            {"file": "app/example.py", "action": "delete", "content": ""},
        ],
    })

    assert result["applied"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["file"] == "app/example.py"
    assert result["skipped"][0]["reason"].startswith("delete_failed:")

    from app.change_application import ChangeApplicationService
    assert ChangeApplicationService.status_for(result) == "apply_failed"


def test_apply_mixed_success_and_os_error_yields_partial_apply_failed_result(tmp_path):
    """One change applies successfully while a sibling change fails
    with a real OSError -- both are represented in the normal
    {"applied": [...], "skipped": [...]} contract, never a crash that
    leaves earlier-applied changes unaccounted for."""
    (tmp_path / "app").mkdir()
    good_path = tmp_path / "app" / "good.py"
    good_path.write_text("old")
    (tmp_path / "app" / "bad.py").mkdir()  # a directory, not a file

    applier = DeveloperFileApplier(tmp_path)
    result = applier.apply({
        "changes": [
            {"file": "app/good.py", "action": "update", "content": "new"},
            {"file": "app/bad.py", "action": "update", "content": "new"},
        ],
    })

    assert result["applied"] == ["app/good.py"]
    assert good_path.read_text() == "new"
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["file"] == "app/bad.py"
    assert result["skipped"][0]["reason"].startswith("write_failed:")

    from app.change_application import ChangeApplicationService
    assert ChangeApplicationService.status_for(result) == "apply_failed"


def test_apply_update_safe_path_behavior_unchanged(tmp_path):
    """The existing safe-path update behavior (successful write) is
    unaffected by the new OSError handling."""
    path = tmp_path / "app" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('print("old")')

    applier = DeveloperFileApplier(tmp_path)
    result = applier.apply({
        "changes": [
            {"file": "app/example.py", "action": "update", "content": 'print("new")'},
        ],
    })

    assert result["applied"] == ["app/example.py"]
    assert result["skipped"] == []
    assert path.read_text() == 'print("new")'


def test_apply_delete_safe_path_behavior_unchanged(tmp_path):
    """The existing safe-path delete behavior (successful unlink) is
    unaffected by the new OSError handling."""
    path = tmp_path / "app" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('print("old")')

    applier = DeveloperFileApplier(tmp_path)
    result = applier.apply({
        "changes": [
            {"file": "app/example.py", "action": "delete", "content": ""},
        ],
    })

    assert result["applied"] == ["app/example.py"]
    assert result["skipped"] == []
    assert not path.exists()
