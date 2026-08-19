from unittest.mock import MagicMock

from app.git_manager import GitManager


def test_push_success():
    manager = GitManager()

    manager.run = MagicMock(
        return_value={
            "code": 0,
            "stdout": "Everything up-to-date",
            "stderr": ""
        }
    )

    result = manager.push("mock_project")

    assert result["code"] == 0
    assert result["stdout"] == "Everything up-to-date"
    assert result["stderr"] == ""

    manager.run.assert_called_once_with(
        "git push",
        "mock_project"
    )

def test_push_invalid_project():
    manager = GitManager()

    result = manager.push(
        "/does/not/exist"
    )

    assert result["code"] != 0
    assert result["stdout"] == ""
    assert result["stderr"] != ""
