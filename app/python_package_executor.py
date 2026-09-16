from dataclasses import dataclass
from importlib import metadata
import re
import subprocess
import sys
from typing import Protocol

from app.python_distribution import (
    distribution_names_match,
    distribution_query_command,
    parse_distribution_query_output,
    resolve_target_python_executable,
)
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


# CLAUDE-E2E-NIO-008A: module-level (not PythonPackageExecutor-private) so
# that ToolchainMaterializer -- the producer that decides whether a
# SetupStep may become an "install" action at all -- can consult the
# EXACT SAME compatibility contract this executor itself enforces at
# execution time, rather than reimplementing or heuristically
# approximating it. There is exactly one place this shape is defined; a
# real Real-System-E2E reached 50% and failed because no producer-side
# component ever consulted it before a SetupStep with an incompatible,
# free-form compound shell install_method became an approved "install"
# step in the first place.
SUPPORTED_INSTALL_METHOD_MARKERS = frozenset({"pip", "python_package"})

# A narrow, fixed set of recognized command-like install_method shapes.
# Each pattern captures exactly one structured distribution identifier
# and nothing else: no extra flags, no extra packages, no shell
# metacharacters, no compound commands can ever match, because the whole
# string must match end to end (see is_supported_python_package_install_method).
INSTALL_METHOD_COMMAND_PATTERNS = (
    re.compile(r"^pip install ([A-Za-z0-9][A-Za-z0-9._-]*)$"),
    re.compile(r"^python -m pip install ([A-Za-z0-9][A-Za-z0-9._-]*)$"),
)


def is_supported_python_package_install_method(
    install_method: str | None, package: str,
) -> bool:
    """Decide whether install_method genuinely asserts "install this
    exact package via pip", never executing install_method itself.

    install_method remains a security assertion, not descriptive-only
    text: a bareword form (`pip`/`python_package`) is always accepted as
    a plain structured-install marker, and a command-like form is
    accepted only when it matches one of a small, fixed set of exact
    shapes (see INSTALL_METHOD_COMMAND_PATTERNS) naming exactly one
    package whose distribution identity matches *package* — compared via
    PEP 503 distribution-name normalization (case/-/_/. equivalence),
    never via blind lowercasing of the whole install_method text. A
    different package, extra flags/packages, or any shell/compound
    syntax never matches any recognized shape and is rejected.

    Shared by PythonPackageExecutor (enforced at execution time) and
    ToolchainMaterializer (enforced at materialization time, before a
    SetupStep can ever become an approvable "install" action) — the one
    place this compatibility contract is defined, never duplicated or
    heuristically approximated.
    """
    if install_method in SUPPORTED_INSTALL_METHOD_MARKERS:
        return True

    if not install_method:
        return False

    for pattern in INSTALL_METHOD_COMMAND_PATTERNS:
        match = pattern.fullmatch(install_method)
        if match is not None:
            return distribution_names_match(match.group(1), package)

    return False


class PythonPackageExecutor:
    """Executes approved Python-package setup steps using structured pip installs.

    This is the CURRENT productive backend adapter for S3.3 Controlled
    Execution -- not the generic definition of S3.3 itself. That
    central role (validating approval, enforcing the replay/idempotency
    guard, dispatching to whichever backend is configured) belongs to
    app.dev_workflow.DevelopmentWorkflow.execute_approved(); this class
    is only the concrete thing it currently dispatches to, scoped
    exclusively to Python package installation. It must never become
    central policy for other ecosystems (npm, CMake, PlatformIO,
    ESPHome, ...) -- those remain adapter-level concerns for their own,
    not-yet-written executors, and a step with no controlled backend
    surfaces honestly via SetupPlan.unsupported_backend_effects instead
    of being forced through this one.
    """

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
            self.python_executable = resolve_target_python_executable()
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
        # One exact target Python identity for this operation: whatever
        # RequirementPreflight resolved and the materializer stamped onto
        # this step's generic target_executable field takes priority
        # over this executor's own instance-level default, and that SAME
        # value is then used for both install and post-install
        # verification below — never re-resolved from PATH a second time
        # within this single execute() call.
        target_python = step.target_executable or self.python_executable
        command = [
            target_python,
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

        verification_passed = self._run_verification(step, project_root, target_python)
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
        """Delegates to the shared, module-level compatibility contract
        (see is_supported_python_package_install_method) so this
        executor and ToolchainMaterializer's producer-side check can
        never drift apart."""
        return is_supported_python_package_install_method(install_method, package)

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

    def _run_verification(
        self, step: SetupStep, project_root: str | None = None,
        target_python: str | None = None,
    ) -> bool:
        try:
            if self._uses_default_runner and self.verifier is _default_verifier:
                # Same target Python passed in from execute() (which is
                # the same one just used for the pip install), same
                # distribution-metadata query used by RequirementPreflight
                # (app.python_distribution) — there is exactly one
                # definition of "is this Python distribution installed",
                # asked of the exact same executable that performed the
                # install, never re-resolved here.
                command = distribution_query_command(
                    target_python or self.python_executable, step.package.strip(),
                )
                result = self._run(
                    command, project_root, self._VERIFY_TIMEOUT_SECONDS, "verification",
                )
                installed, _version = parse_distribution_query_output(
                    result.returncode, result.stdout,
                )
                return installed

            return bool(self.verifier(step))
        except Exception:
            return False
