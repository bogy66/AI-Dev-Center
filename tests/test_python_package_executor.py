import subprocess

import pytest

from app.python_package_executor import (
    CommandResult,
    PackageMissingError,
    PythonPackageExecutor,
    RequirementIdMissingError,
    SubprocessCommandRunner,
)
from app.requirement_model import SetupStep
from app.setup_executor import StepNotApprovedError


class FakeRunner:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def run(self, args: list[str]) -> CommandResult:
        self.calls.append(args)
        return CommandResult(self.returncode, self.stdout, self.stderr)


class FakeVerifier:
    def __init__(self, result: bool = True):
        self.result = result
        self.calls: list[SetupStep] = []

    def __call__(self, step: SetupStep) -> bool:
        self.calls.append(step)
        return self.result


def make_step(**overrides):
    defaults = {
        "id": "step-1",
        "requirement_id": "req-1",
        "action": "install",
        "package": "requests",
        "version": None,
        "command": None,
        "is_approved": True,
    }
    defaults.update(overrides)
    return SetupStep(**defaults)


def test_approved_package_runner_gets_correct_argv():
    runner = FakeRunner()
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step()

    result = executor.execute(step)

    assert runner.calls == [["python", "-m", "pip", "install", "requests"]]
    assert result.success is True
    assert result.verification_passed is True


def test_approved_package_with_version_passes_version_to_pip():
    runner = FakeRunner()
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step(version=">=2.0")

    executor.execute(step)

    assert runner.calls == [["python", "-m", "pip", "install", "requests>=2.0"]]


def test_not_approved_raises_and_runner_not_called():
    runner = FakeRunner()
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step(is_approved=False)

    with pytest.raises(StepNotApprovedError):
        executor.execute(step)

    assert len(runner.calls) == 0
    assert len(verifier.calls) == 0


def test_package_missing_raises_and_runner_not_called():
    runner = FakeRunner()
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step(package=None)

    with pytest.raises(PackageMissingError):
        executor.execute(step)

    assert len(runner.calls) == 0
    assert len(verifier.calls) == 0


def test_package_empty_raises_and_runner_not_called():
    runner = FakeRunner()
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step(package="   ")

    with pytest.raises(PackageMissingError):
        executor.execute(step)

    assert len(runner.calls) == 0
    assert len(verifier.calls) == 0


def test_arbitrary_step_command_ignored():
    runner = FakeRunner()
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step(command="echo pwned")

    executor.execute(step)

    assert runner.calls == [["python", "-m", "pip", "install", "requests"]]
    assert "echo" not in runner.calls[0]


def test_subprocess_runner_forwards_shell_false(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.python_package_executor.subprocess.run", fake_run)

    runner = SubprocessCommandRunner()
    result = runner.run(["python", "-m", "pip", "install", "requests"])

    assert captured["args"] == ["python", "-m", "pip", "install", "requests"]
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["check"] is False
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["capture_output"] is True
    assert result.returncode == 0


def test_returncode_0_verifier_called():
    runner = FakeRunner(returncode=0)
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step()

    result = executor.execute(step)

    assert len(verifier.calls) == 1
    assert result.success is True
    assert result.verification_passed is True


def test_returncode_nonzero_skips_verifier_and_fails():
    runner = FakeRunner(returncode=1, stderr="some error")
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step()

    result = executor.execute(step)

    assert len(verifier.calls) == 0
    assert result.success is False
    assert result.verification_passed is False
    assert "pip install failed" in result.message


def test_verification_success():
    runner = FakeRunner(returncode=0)
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step()

    result = executor.execute(step)

    assert result.success is True
    assert result.verification_passed is True
    assert "verification passed" in result.message


def test_verification_failure():
    runner = FakeRunner(returncode=0)
    verifier = FakeVerifier(False)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step()

    result = executor.execute(step)

    assert result.success is False
    assert result.verification_passed is False
    assert "verification failed" in result.message


def test_input_step_unchanged():
    runner = FakeRunner(returncode=0)
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step()
    original = make_step()

    executor.execute(step)

    assert step == original
