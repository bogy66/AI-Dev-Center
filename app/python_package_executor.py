from dataclasses import dataclass
from importlib import metadata
import re
import shutil
import subprocess
import sys
from typing import Protocol

from app.setup_executor import ExecutionResult, StepNotApprovedError
from app.requirement_model import SetupStep


class PythonPackageExecutorError(Exception):
    """Base exception for PythonPackageExecutor errors."""


class PackageMissingError(PythonPackageExecutorError):
    """Raised when the step does not contain a usable package name."""


class RequirementIdMissingError(PythonPackageExecutorError):
    """Raised when the step does not contain a requirement id."""


class UnsupportedInstallMethodError(PythonPackageExecutorError):
    """Raised when a step requests an installation method this executor cannot run."""


class MissingProjectRootError(PythonPackageExecutorError):
    """Raised when the default runner is used without a resolved project_root.

    The default runner must always route through the central controlled
    execution boundary, which requires a project_root to confine cwd and
    validate capability scope. There is no unconfined fallback: a caller
    that cannot supply project_root must fix its own call site, not
    silently execute outside the boundary.
    """


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult:
        ...


class Verifier(Protocol):
    def __call__(self, step: SetupStep) -> bool:
        ...


class SubprocessCommandRunner:
    """Runs a command with subprocess.run using shell=False and list args."""

    def run(self, args: list[str]) -> CommandResult:
        completed = subprocess.run(
            args,
            shell=False,
            check=False,
            text=True,
            capture_output=True,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def _default_verifier(step: SetupStep) -> bool:
    try:
        metadata.version(step.package.strip())
    except (metadata.PackageNotFoundError, ValueError, TypeError):
        return False
    return True


class PythonPackageExecutor:
    """Executes approved Python-package setup steps using structured pip installs."""

    _SUPPORTED_INSTALL_METHODS = frozenset({"pip", "python_package"})
    _PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    _INSTALL_TIMEOUT_SECONDS = 300
    _VERIFY_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        runner: CommandRunner | None = None,
        verifier: Verifier | None = None,
    ):
        self._uses_default_runner = runner is None
        self.runner = runner if runner is not None else SubprocessCommandRunner()
        self.verifier = verifier if verifier is not None else _default_verifier

        if self._uses_default_runner:
            self.python_executable = shutil.which("python") or sys.executable
        else:
            self.python_executable = sys.executable

    def _run(
        self, command: list[str], project_root, timeout: int,
        operation_type: str = "install",
    ) -> CommandResult:
        """Run one command through the central controlled execution boundary.

        An explicitly injected CommandRunner (unit tests, or the
        isolated-venv runner used by the real-system environment-setup
        test) keeps its exact existing call shape untouched — it is a
        deliberate, justified, non-productive-default execution path.

        The default runner (no CommandRunner injected) has no unconfined
        fallback: it always routes through execute_controlled, and a
        missing project_root is a fail-closed error, never a reason to
        fall back to a direct, unconfined subprocess call.
        """
        if not self._uses_default_runner:
            return self.runner.run(command)

        if project_root is None:
            raise MissingProjectRootError(
                "PythonPackageExecutor's default runner requires an "
                "explicit project_root to execute through the central "
                "controlled execution boundary; refusing to execute "
                "unconfined."
            )

        from app.execution import ExecutionRequest, execute_controlled

        request = ExecutionRequest(
            tuple(command), str(project_root), timeout, "python", operation_type,
        )
        completed = execute_controlled(request, project_root)
        if completed is None:
            return CommandResult(
                returncode=1, stdout="",
                stderr="Execution failed: tool unavailable",
            )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def execute(self, step: SetupStep, project_root: str | None = None) -> ExecutionResult:
        self._validate_step(step)
        package_arg = self._build_package_arg(step)
        self._validate_install_method(
            step.install_method,
            step.package.strip(),
            package_arg,
        )
        command = [
            self.python_executable,
            "-m",
            "pip",
            "install",
            package_arg,
        ]
        result = self._run(command, project_root, self._INSTALL_TIMEOUT_SECONDS)

        if result.returncode != 0:
            return ExecutionResult(
                step_id=step.id,
                success=False,
                message=f"pip install failed with exit code {result.returncode}",
                verification_passed=False,
            )

        verification_passed = self._run_verification(step, project_root)
        if verification_passed:
            message = "pip install succeeded and verification passed"
        else:
            message = "pip install succeeded but verification failed"

        return ExecutionResult(
            step_id=step.id,
            success=verification_passed,
            message=message,
            verification_passed=verification_passed,
        )

    def _validate_step(self, step: SetupStep) -> None:
        if not step.is_approved:
            raise StepNotApprovedError(
                f"Step {step.id} has not been approved and cannot be executed."
            )
        if not step.requirement_id:
            raise RequirementIdMissingError(
                "step.requirement_id must be a non-empty string"
            )
        if not step.package or not step.package.strip():
            raise PackageMissingError(
                "step.package must be a non-empty string"
            )
        if self._PACKAGE_NAME.fullmatch(step.package.strip()) is None:
            raise PackageMissingError("step.package must be one structured package name")

    def _validate_install_method(
        self,
        install_method: str | None,
        package: str,
        package_arg: str,
    ) -> None:
        if not self._is_supported_install_method(
            install_method,
            package,
            package_arg,
        ):
            raise UnsupportedInstallMethodError(
                "step.install_method must identify the structured Python/pip install"
            )

    def _is_supported_install_method(
        self,
        install_method: str | None,
        package: str,
        package_arg: str,
    ) -> bool:
        if install_method in self._SUPPORTED_INSTALL_METHODS:
            return True

        return install_method in {
            f"pip install {package}",
            f"pip install {package_arg}",
            f"python -m pip install {package}",
            f"python -m pip install {package_arg}",
        }

    def _build_package_arg(self, step: SetupStep) -> str:
        package = step.package.strip()
        version = step.version
        if version:
            normalized_version = version.strip()
            if not normalized_version.startswith(
                ("==", ">=", "<=", "!=", ">", "<")
            ):
                normalized_version = f"=={normalized_version}"
            return f"{package}{normalized_version}"
        return package

    def _run_verification(self, step: SetupStep, project_root: str | None = None) -> bool:
        try:
            if self._uses_default_runner and self.verifier is _default_verifier:
                result = self._run(
                    [
                        self.python_executable,
                        "-c",
                        (
                            "import importlib.metadata as metadata, sys; "
                            "metadata.version(sys.argv[1])"
                        ),
                        step.package.strip(),
                    ],
                    project_root,
                    self._VERIFY_TIMEOUT_SECONDS,
                    "verification",
                )
                return result.returncode == 0

            return bool(self.verifier(step))
        except Exception:
            return False
