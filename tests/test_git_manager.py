import subprocess
from unittest.mock import MagicMock, patch

from app.git_manager import GitManager


def _init_repo(path):
    subprocess.run(
        ["git", "init"],
        cwd=path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
        capture_output=True
    )


def _last_commit_message(path):
    result = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip()


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


def test_commit_succeeds_with_normal_message(tmp_path):
    _init_repo(tmp_path)

    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")

    manager = GitManager()

    result = manager.commit(str(tmp_path), "Initial commit")

    assert result["code"] == 0
    assert _last_commit_message(tmp_path) == "Initial commit"


def test_commit_message_with_shell_metacharacters_is_not_executed(tmp_path):
    _init_repo(tmp_path)

    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")

    manager = GitManager()

    malicious_message = 'hack"; touch INJECTED.txt #'

    result = manager.commit(str(tmp_path), malicious_message)

    assert result["code"] == 0

    injected_file = tmp_path / "INJECTED.txt"
    assert not injected_file.exists(), (
        "Expected the commit message to be treated as a literal "
        "argument, but a shell command embedded in the message "
        "appears to have been executed."
    )

    assert _last_commit_message(tmp_path) == malicious_message


def test_commit_message_with_command_substitution_is_not_executed(tmp_path):
    _init_repo(tmp_path)

    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")

    manager = GitManager()

    malicious_message = (
        "hack $(touch INJECTED2.txt) `touch INJECTED3.txt`"
    )

    result = manager.commit(str(tmp_path), malicious_message)

    assert result["code"] == 0

    assert not (tmp_path / "INJECTED2.txt").exists(), (
        "Expected $(...) command substitution inside the commit "
        "message to not be executed by a shell."
    )
    assert not (tmp_path / "INJECTED3.txt").exists(), (
        "Expected backtick command substitution inside the commit "
        "message to not be executed by a shell."
    )

    assert _last_commit_message(tmp_path) == malicious_message


def test_commit_does_not_call_git_commit_when_git_add_fails():
    manager = GitManager()

    add_failure = {
        "code": 1,
        "stdout": "",
        "stderr": "fatal: not a git repository"
    }

    with patch.object(
        manager,
        "_run_args",
        return_value=add_failure
    ) as mock_run_args:

        result = manager.commit(
            "mock_project",
            "Should not run"
        )

    assert result == add_failure

    mock_run_args.assert_called_once_with(
        ["git", "add", "."],
        "mock_project"
    )
