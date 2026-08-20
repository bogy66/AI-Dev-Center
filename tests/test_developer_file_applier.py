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
