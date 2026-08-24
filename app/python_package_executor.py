from dataclasses import dataclass
import subprocess
from typing import Protocol

from app.setup_executor import ExecutionResult, StepNotApprovedError
from app.requirement_model import SetupStep


class PythonPackageExecutorError(Exception):
    """Base exception for PythonPackageExecutor errors."""


class PackageMissingError(PythonPackageExecutorError):
    """Raised when the step does not contain a usable package name."""


class RequirementIdMissingError(PythonPackageExecutorError):
    """Raised when the step does not contain a requirement id."""


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
    return True


class PythonPackageExecutor:
    """Executes approved Python-package setup steps using structured pip installs."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        verifier: Verifier | None = None,
    ):
        self.runner = runner if runner is not None else SubprocessCommandRunner()
        self.verifier = verifier if verifier is not None else _default_verifier

    def execute(self, step: SetupStep) -> ExecutionResult:
        self._validate_step(step)
        package_arg = self._build_package_arg(step)
        command = ["python", "-m", "pip", "install", package_arg]
        result = self.runner.run(command)

        if result.returncode != 0:
            return ExecutionResult(
                step_id=step.id,
                success=False,
                message=f"pip install failed with exit code {result.returncode}",
                verification_passed=False,
            )

        verification_passed = self._run_verification(step)
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

    def _build_package_arg(self, step: SetupStep) -> str:
        package = step.package.strip()
        version = step.version
        if version:
            return f"{package}{version}"
        return package

    def _run_verification(self, step: SetupStep) -> bool:
        try:
            return bool(self.verifier(step))
        except Exception:
            return False
