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
