import os
import subprocess
import sys

import pytest

from app.python_package_executor import (
    CommandResult,
    PackageMissingError,
    PythonPackageExecutor,
    RequirementIdMissingError,
    SubprocessCommandRunner,
    UnsupportedInstallMethodError,
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
        "install_method": "python_package",
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

    assert runner.calls == [[sys.executable, "-m", "pip", "install", "requests"]]
    assert result.success is True
    assert result.verification_passed is True


@pytest.mark.parametrize(
    "version",
    [">=2.0", "<=2.0", ">2.0", "<2.0", "!=2.0", "==2.0"],
)
def test_approved_package_with_comparator_passes_version_to_pip(version):
    runner = FakeRunner()
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step(version=version)

    executor.execute(step)

    assert runner.calls == [[sys.executable, "-m", "pip", "install", f"requests{version}"]]


def test_approved_package_with_plain_version_normalizes_to_exact_pin():
    runner = FakeRunner()
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step(version="1.2.3")

    executor.execute(step)

    assert runner.calls == [[sys.executable, "-m", "pip", "install", "requests==1.2.3"]]


def test_structured_install_method_can_leave_version_in_separate_field():
    runner = FakeRunner()
    executor = PythonPackageExecutor(runner=runner, verifier=FakeVerifier(True))
    step = make_step(install_method="pip install requests", version="1.2.3")

    executor.execute(step)

    assert runner.calls == [[sys.executable, "-m", "pip", "install", "requests==1.2.3"]]


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

    assert runner.calls == [[sys.executable, "-m", "pip", "install", "requests"]]
    assert "echo" not in runner.calls[0]


def test_unsupported_install_method_raises_and_runner_not_called():
    runner = FakeRunner()
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step(install_method="apt install requests")

    with pytest.raises(UnsupportedInstallMethodError):
        executor.execute(step)

    assert runner.calls == []
    assert verifier.calls == []


@pytest.mark.parametrize(
    "install_method",
    [
        "pip",
        "python_package",
        "pip install requests",
        "python -m pip install requests",
    ],
)
def test_supported_python_install_methods_use_structured_pip_command(install_method):
    runner = FakeRunner()
    executor = PythonPackageExecutor(runner=runner, verifier=FakeVerifier(True))

    executor.execute(make_step(install_method=install_method))

    assert runner.calls == [[sys.executable, "-m", "pip", "install", "requests"]]


@pytest.mark.parametrize(
    "install_method",
    [
        None,
        "",
        "pip install other-package",
        "pip install --user requests",
        "pip install requests; echo pwned",
        "python -c 'print(1)'",
    ],
)
def test_unsupported_or_mismatched_install_methods_are_rejected(install_method):
    runner = FakeRunner()
    executor = PythonPackageExecutor(runner=runner, verifier=FakeVerifier(True))

    with pytest.raises(UnsupportedInstallMethodError):
        executor.execute(make_step(install_method=install_method))

    assert runner.calls == []


def test_subprocess_runner_forwards_shell_false(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.python_package_executor.subprocess.run", fake_run)

    runner = SubprocessCommandRunner()
    result = runner.run([sys.executable, "-m", "pip", "install", "requests"])

    assert captured["args"] == [sys.executable, "-m", "pip", "install", "requests"]
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


def test_default_verifier_passes_when_package_metadata_exists(monkeypatch):
    runner = FakeRunner(returncode=0)
    executor = PythonPackageExecutor(runner=runner)
    step = make_step()

    monkeypatch.setattr(
        "app.python_package_executor.metadata.version",
        lambda package: "1.0.0",
    )

    result = executor.execute(step)

    assert result.success is True
    assert result.verification_passed is True


def test_default_verifier_fails_when_package_metadata_is_missing(monkeypatch):
    runner = FakeRunner(returncode=0)
    executor = PythonPackageExecutor(runner=runner)
    step = make_step()

    def missing_package(package):
        raise __import__("importlib").metadata.PackageNotFoundError(package)

    monkeypatch.setattr(
        "app.python_package_executor.metadata.version",
        missing_package,
    )

    result = executor.execute(step)

    assert result.success is False
    assert result.verification_passed is False


def test_verification_after_is_never_executed(monkeypatch):
    runner = FakeRunner(returncode=0)
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step(verification_after="echo pwned")

    def subprocess_must_not_run(*args, **kwargs):
        pytest.fail("verification_after must not be executed as a command")

    monkeypatch.setattr(
        "app.python_package_executor.subprocess.run",
        subprocess_must_not_run,
    )

    executor.execute(step)

    assert runner.calls == [[sys.executable, "-m", "pip", "install", "requests"]]
    assert verifier.calls == [step]


def test_input_step_unchanged():
    runner = FakeRunner(returncode=0)
    verifier = FakeVerifier(True)
    executor = PythonPackageExecutor(runner=runner, verifier=verifier)
    step = make_step()
    original = make_step()

    executor.execute(step)

    assert step == original


def test_default_runner_resolves_python_via_path(monkeypatch, tmp_path):
    isolated_bin = tmp_path / "bin"
    isolated_bin.mkdir()
    python_link = isolated_bin / "python"
    python_link.symlink_to(sys.executable)

    prior_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{isolated_bin}:{prior_path}")

    executor = PythonPackageExecutor()

    assert executor._uses_default_runner is True
    resolved = executor.python_executable
    assert resolved is not None
    assert resolved == str(python_link.resolve()) or resolved.startswith(
        str(isolated_bin)
    ), f"Default runner must use Python from isolated venv PATH, got {resolved}"


def test_custom_runner_falls_back_to_sys_executable():
    executor = PythonPackageExecutor(runner=FakeRunner())

    assert executor._uses_default_runner is False
    assert executor.python_executable == sys.executable


# ---------------------------------------------------------------------------
# CLAUDE-E2E-003: package/install_method distribution-identity comparison
# ---------------------------------------------------------------------------

def test_real_e2e_shape_case_mismatch_is_accepted():
    """Exact real-E2E shape: package='ESPHome', install_method='pip
    install esphome' must be accepted -- both identify the same
    distribution and previously failed only due to case-sensitive
    string comparison."""
    runner = FakeRunner()
    executor = PythonPackageExecutor(runner=runner, verifier=FakeVerifier(True))
    step = make_step(package="ESPHome", install_method="pip install esphome")

    executor.execute(step)

    assert runner.calls == [[sys.executable, "-m", "pip", "install", "ESPHome"]]


@pytest.mark.parametrize(
    "package, install_method",
    [
        ("ESPHome", "pip install esphome"),
        ("esphome", "pip install ESPHome"),
        ("Requests", "pip install requests"),
        ("REQUESTS", "python -m pip install requests"),
    ],
)
def test_case_differences_are_accepted(package, install_method):
    runner = FakeRunner()
    executor = PythonPackageExecutor(runner=runner, verifier=FakeVerifier(True))
    step = make_step(package=package, install_method=install_method)

    executor.execute(step)

    assert runner.calls == [[sys.executable, "-m", "pip", "install", package]]


@pytest.mark.parametrize(
    "package, install_method",
    [
        ("foo_bar", "pip install foo-bar"),
        ("foo-bar", "pip install foo_bar"),
        ("foo.bar", "pip install foo-bar"),
        ("foo-bar", "python -m pip install foo.bar"),
    ],
)
def test_hyphen_underscore_dot_differences_are_accepted(package, install_method):
    runner = FakeRunner()
    executor = PythonPackageExecutor(runner=runner, verifier=FakeVerifier(True))
    step = make_step(package=package, install_method=install_method)

    executor.execute(step)

    assert runner.calls == [[sys.executable, "-m", "pip", "install", package]]


def test_genuinely_different_distribution_still_rejected():
    """Normalization equivalence must never smuggle a different package
    through: 'esp-home' does not normalize to 'esphome'."""
    runner = FakeRunner()
    executor = PythonPackageExecutor(runner=runner, verifier=FakeVerifier(True))
    step = make_step(package="ESPHome", install_method="pip install esp-home")

    with pytest.raises(UnsupportedInstallMethodError):
        executor.execute(step)

    assert runner.calls == []


@pytest.mark.parametrize(
    "install_method",
    [
        "pip install ESPHome extra-package",
        "pip install --user ESPHome",
        "pip install ESPHome; echo pwned",
        "pip install ESPHome && rm -rf /",
        "python -c 'print(1)'",
        "apt install esphome",
    ],
)
def test_additional_options_and_shell_syntax_still_rejected(install_method):
    runner = FakeRunner()
    executor = PythonPackageExecutor(runner=runner, verifier=FakeVerifier(True))
    step = make_step(package="ESPHome", install_method=install_method)

    with pytest.raises(UnsupportedInstallMethodError):
        executor.execute(step)

    assert runner.calls == []


def test_install_method_text_is_never_executed_directly():
    """The install_method string itself must never appear as an argv
    element passed to the runner -- only the internally-constructed,
    fixed-shape pip command does."""
    runner = FakeRunner()
    executor = PythonPackageExecutor(runner=runner, verifier=FakeVerifier(True))
    step = make_step(package="ESPHome", install_method="pip install esphome")

    executor.execute(step)

    assert len(runner.calls) == 1
    assert "pip install esphome" not in runner.calls[0]
    assert runner.calls[0] == [sys.executable, "-m", "pip", "install", "ESPHome"]


def test_real_e2e_shape_reaches_default_execute_controlled_exactly_once(
    monkeypatch, tmp_path,
):
    """CLAUDE-E2E-003 productive proof: the exact real-E2E shape
    (package='ESPHome', install_method='pip install esphome') must
    reach the central controlled execution boundary exactly once for
    the *default* (productive) runner -- not raise
    UnsupportedInstallMethodError, and not execute pip twice."""
    import app.execution as execution_module

    calls = []

    def fake_execute_controlled(request, project_root):
        calls.append((tuple(request.args), project_root))
        return subprocess.CompletedProcess(list(request.args), 0, "1.0\n", "")

    monkeypatch.setattr(execution_module, "execute_controlled", fake_execute_controlled)

    executor = PythonPackageExecutor()  # default (productive) runner/verifier
    step = make_step(
        package="ESPHome", install_method="pip install esphome", version=None,
    )

    result = executor.execute(step, str(tmp_path))

    assert result.success is True
    # install + verification each call execute_controlled once == 2 total,
    # never more (no double install).
    assert len(calls) == 2
    install_calls = [c for c in calls if "install" in c[0]]
    assert len(install_calls) == 1
    assert install_calls[0][0] == (
        executor.python_executable, "-m", "pip", "install", "ESPHome",
    )


def test_real_default_verification_construction_uses_step_target_executable(
    monkeypatch, tmp_path,
):
    """CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004 (item
    11c): a focused integration regression through the REAL, unmodified
    `execute()` -> `_run_verification()` -> `distribution_query_command()`
    construction path -- never bypassed via an injected verifier/runner
    that would hide a target-binding bug -- with only the lowest-level
    command execution faked (the same style as
    test_real_e2e_shape_reaches_default_execute_controlled_exactly_once
    above). Proves install target == post-install verification target
    for an EXPLICIT `step.target_executable` (the productive case, once
    RequirementPreflight/ToolchainMaterializer have resolved a real,
    environment-bound target) -- not merely the constructor's own
    fallback `self.python_executable`."""
    import app.execution as execution_module

    calls = []
    explicit_target = "/fake/prepared-venv/bin/python"

    def fake_execute_controlled(request, project_root):
        calls.append(tuple(request.args))
        if "install" in request.args:
            return subprocess.CompletedProcess(list(request.args), 0, "", "")
        return subprocess.CompletedProcess(list(request.args), 0, "1.2.3\n", "")

    monkeypatch.setattr(execution_module, "execute_controlled", fake_execute_controlled)

    executor = PythonPackageExecutor()  # default (productive) runner/verifier
    step = make_step(
        package="acme-widgets", install_method="pip", version=None,
        target_executable=explicit_target,
    )

    result = executor.execute(step, str(tmp_path))

    assert result.success is True
    assert result.verification_passed is True
    assert len(calls) == 2
    install_call, verify_call = calls
    assert install_call == (explicit_target, "-m", "pip", "install", "acme-widgets")
    assert verify_call[0] == explicit_target
    assert verify_call[-1] == "acme-widgets"
    # The SAME target for both -- install target == verification target.
    assert install_call[0] == verify_call[0] == explicit_target
    assert install_call[0] != executor.python_executable
