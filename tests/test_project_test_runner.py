from unittest.mock import Mock
import subprocess
import pytest
from app.project_test_runner import ProjectTestRunner, TestExecutionRequest


def test_runner_uses_allowlisted_argv_and_project_root(tmp_path):
    runner = Mock(return_value=Mock(returncode=0, stdout="ok", stderr=""))
    result = ProjectTestRunner(runner=runner).run(TestExecutionRequest(tmp_path))
    assert result.passed
    assert runner.call_args.kwargs["cwd"] == tmp_path.resolve()
    assert runner.call_args.args[0][1:] == ("-m", "pytest", "-q")


@pytest.mark.parametrize("command", ["rm -rf /", "pytest && rm x", "bash -c x"])
def test_runner_rejects_untrusted_commands(tmp_path, command):
    with pytest.raises(ValueError):
        ProjectTestRunner(runner=Mock()).run(TestExecutionRequest(tmp_path, command))


def test_runner_returns_timeout_result(tmp_path):
    runner = Mock(side_effect=subprocess.TimeoutExpired([], 1, output="out", stderr="err"))
    result = ProjectTestRunner(runner=runner).run(TestExecutionRequest(tmp_path))
    assert result.timed_out and not result.passed
