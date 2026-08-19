from unittest.mock import MagicMock, patch

from app.git_manager import GitManager


def test_push_success():
    manager = GitManager()

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Everything up-to-date\n"
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = manager.run(
            "git push",
            "mock_project"
        )

    assert result["code"] == 0
    assert result["stdout"] == "Everything up-to-date"
    assert result["stderr"] == ""

    mock_run.assert_called_once_with(
        "git push",
        cwd="mock_project",
        shell=True,
        text=True,
        capture_output=True
    )
