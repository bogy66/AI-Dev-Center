from app.specification_tester import SpecificationTester


def test_create_file_matches_expected_content(tmp_path):
    path = tmp_path / "app" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('print("hello")', encoding="utf-8")

    changes = {
        "changes": [
            {
                "file": "app/example.py",
                "action": "create",
                "content": 'print("hello")'
            }
        ]
    }

    result = SpecificationTester().check(
        tmp_path,
        changes
    )

    assert result["success"] is True
    assert result["errors"] == []


def test_create_file_fails_on_wrong_content(tmp_path):
    path = tmp_path / "app" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('print("wrong")', encoding="utf-8")

    changes = {
        "changes": [
            {
                "file": "app/example.py",
                "action": "create",
                "content": 'print("hello")'
            }
        ]
    }

    result = SpecificationTester().check(
        tmp_path,
        changes
    )

    assert result["success"] is False
    assert result["errors"]


def test_update_file_matches_expected_content(tmp_path):
    path = tmp_path / "app" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('print("new")', encoding="utf-8")

    changes = {
        "changes": [
            {
                "file": "app/example.py",
                "action": "update",
                "content": 'print("new")'
            }
        ]
    }

    result = SpecificationTester().check(
        tmp_path,
        changes
    )

    assert result["success"] is True


def test_delete_file_is_verified(tmp_path):
    path = tmp_path / "app" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('print("old")', encoding="utf-8")

    path.unlink()

    changes = {
        "changes": [
            {
                "file": "app/example.py",
                "action": "delete",
                "content": ""
            }
        ]
    }

    result = SpecificationTester().check(
        tmp_path,
        changes
    )

    assert result["success"] is True
