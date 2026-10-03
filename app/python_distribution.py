"""Structured Python distribution identity and target-Python resolution.

This module is the single, central place ADC answers three related but
distinct questions:

1. "Do these two strings identify the same Python distribution?" —
   Python distribution (PyPI package) names are compared according to
   the PEP 503 normalization rule: case-insensitive, and runs of
   ``-``, ``_``, ``.`` are treated as equivalent separators. This
   normalization is specific to distribution-name identity comparison
   and must never be applied to arbitrary shell/command text.

2. "Is this text even a plausible technical distribution identifier, or
   is it free-form, human-readable prose (a display label)?" — a
   display name such as "ESPHome CLI" or "Beautiful Soup package" must
   never be guessed at or silently treated as if it were a real,
   installable distribution identifier.

3. "Which single, already-resolved Python executable is the target for
   this productive Python-package operation, and is a given
   distribution actually installed there?" — a distribution can be
   present in the currently-running ADC process's own interpreter while
   being absent from a different, explicitly selected target Python
   (e.g. an isolated toolchain venv), or vice versa. The target
   identity is resolved exactly once per workflow/setup operation and
   then carried as plain data (never re-resolved from PATH later), and
   every component that needs to check "is X installed there" asks the
   SAME way, through the central controlled execution boundary, rather
   than maintaining its own competing definition or its own unconfined
   execution path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shutil
import sys

_SEPARATOR_RUN = re.compile(r"[-_.]+")


def normalize_distribution_name(name: str) -> str:
    """Return the PEP 503 canonical form of a Python distribution name.

    Lowercases the name and collapses any run of ``-``, ``_``, or ``.``
    into a single ``-``, matching the normalization rule PyPI itself
    uses to decide that two distribution names are the same package
    (e.g. "ESPHome", "esphome", "foo_bar", "foo-bar", and "foo.bar" all
    normalize identically where applicable). This is a narrow,
    identity-specific transform — it must never be used to interpret or
    compare arbitrary command/shell text.
    """
    return _SEPARATOR_RUN.sub("-", name).lower()


def distribution_names_match(a: str, b: str) -> bool:
    """Return True when *a* and *b* identify the same Python distribution."""
    return normalize_distribution_name(a) == normalize_distribution_name(b)


_DISTRIBUTION_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def is_valid_distribution_identifier(text: str | None) -> bool:
    """Return True when *text* is already a single, structured token that
    could itself serve as a Python distribution identifier.

    This is a syntactic check only ("ESPHome" qualifies, "ESPHome CLI"
    and "Beautiful Soup package" do not, because they contain spaces/
    free-form prose) — it never confirms the named distribution actually
    exists anywhere, and it must never be used to *derive* a package
    name from arbitrary human-readable text, only to validate that a
    candidate value is already shaped like one.
    """
    return isinstance(text, str) and bool(text) and _DISTRIBUTION_IDENTIFIER.fullmatch(text.strip()) is not None


# CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003: the one
# controlled, closed-grammar shape a Requirement.verification_method may
# take to express a Python distribution package-presence check ADC itself
# recognizes -- "pip show <distribution>", matched end to end
# (re.fullmatch) against exactly one literal "pip show " prefix followed
# by one already-structured distribution-identifier token (the SAME
# token grammar _DISTRIBUTION_IDENTIFIER already defines above -- never a
# second, competing token rule). This is deliberately NOT a shell
# grammar: no flags, no extra package names, no pipes/`&&`, no wrapper
# commands (docker/venv-activation/...), and no case-insensitive
# "pip show" spelling can ever match, because nothing beyond this one
# exact shape is ever accepted -- a value outside it is simply not this
# kind of requirement (returns None), never partially parsed or
# guessed at. The text is never executed or shell-tokenized in any way.
_PIP_SHOW_REQUIREMENT = re.compile(r"^pip show ([A-Za-z0-9][A-Za-z0-9._-]*)$")


def parse_pip_show_requirement(text: str | None) -> str | None:
    """Return the raw distribution token named by a controlled
    "pip show <distribution>" verification requirement, or None when
    *text* is not exactly this one shape.

    The returned token is the RAW text as written -- this function
    performs no PEP 503 normalization of its own; a caller that needs to
    compare it against a technical_identity must do so explicitly via
    distribution_names_match()/normalize_distribution_name(). Keeping
    normalization out of the parser itself means a string that is only
    "valid" after separator-collapsing can never slip past the fixed
    grammar check above before its caller ever sees the raw match.
    """
    if not text or not isinstance(text, str):
        return None
    match = _PIP_SHOW_REQUIREMENT.fullmatch(text.strip())
    if match is None:
        return None
    return match.group(1)


def resolve_target_python_executable() -> str:
    """Resolve the default target Python executable identity.

    Prefers whatever "python" resolves to on the current PATH (e.g. an
    isolated toolchain venv activated for this operation), falling back
    to the currently-running interpreter only when no "python" is found
    on PATH at all.

    This function must be called exactly ONCE per workflow/setup
    operation (by RequirementPreflight, at the point it first needs a
    target Python), and its result then carried as plain, immutable data
    through the central, ecosystem-neutral
    PreflightRequirementResult.target_executable -> SetupStep.target_executable
    fields into every later stage of that same operation. It must NOT be
    called independently again by installation or verification for the
    same operation — doing so would re-resolve against whatever PATH happens
    to be at that later moment, which is exactly the guarantee this
    module exists to remove. Callers that already have a specific,
    previously-resolved target must use it directly, never re-derive it
    through this function.

    CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004: this is
    RequirementPreflight's own broad, pre-candidate "some plausible
    Python" probe — it deliberately has no opinion about whether the
    result is a venv interpreter, because Preflight runs before any
    candidate/environment even exists. It is NOT the function that binds
    a selected candidate's `environment="host"` to a real target for
    materialization/installation/verification — see
    resolve_host_python_executable() for that corrected, venv-aware
    policy, used exclusively by resolve_environment_python_target()'s
    "host" branch below.
    """
    return shutil.which("python") or sys.executable


def _resolved_path(value: str | Path) -> Path | None:
    try:
        return Path(value).resolve()
    except (OSError, ValueError):
        return None


def _is_within(candidate: str | None, root: Path | None) -> bool:
    if not candidate or root is None:
        return False
    resolved_candidate = _resolved_path(candidate)
    if resolved_candidate is None:
        return False
    try:
        return resolved_candidate.is_relative_to(root)
    except (OSError, ValueError):
        return False


def _is_this_projects_venv_interpreter(executable: str | None, project_root: str | None) -> bool:
    """True when *executable* sits inside THIS project's own
    `<project_root>/.venv` -- the SAME convention-bound directory
    `resolve_environment_python_target()`'s own "venv" branch below
    manages. Without a `project_root` there is no "this project's own
    venv" to compare against at all, so this is always False -- never a
    guess at which venv might be "the project's"."""
    if not project_root:
        return False
    root = _resolved_path(_venv_directory(project_root))
    if root is None:
        return False
    return _is_within(executable, root)


def _is_adc_controller_venv_interpreter(executable: str | None) -> bool:
    """True when *executable* sits inside the SAME virtual environment
    ADC's own controller process is currently running from --
    `sys.prefix` differs from `sys.base_prefix` exactly when the running
    process is itself inside a venv, and that `sys.prefix` IS that
    venv's own root directory. When ADC's own process is not running
    inside a venv at all (`sys.prefix == sys.base_prefix`, e.g. a bare
    system interpreter), there is no controller venv to exclude, so this
    is always False."""
    if sys.prefix == sys.base_prefix:
        return False
    controller_root = _resolved_path(sys.prefix)
    if controller_root is None:
        return False
    return _is_within(executable, controller_root)


def resolve_host_python_executable(project_root: str | None = None) -> str | None:
    """CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004: THE
    corrected resolution policy for a candidate's own declared
    `environment="host"` — used exclusively by
    resolve_environment_python_target()'s "host" branch, never by
    RequirementPreflight's own broad, pre-candidate probe (see
    resolve_target_python_executable() above, unchanged).

    "host" must mean a genuine host/system Python interpreter — never
    THIS project's own isolated `<project_root>/.venv`
    (`_is_this_projects_venv_interpreter()`), and never ADC's own
    currently-running controller/project virtualenv merely because
    PATH's "python"/"python3" or `sys.executable` happen to point there
    (`_is_adc_controller_venv_interpreter()`). Every candidate (PATH
    "python", PATH "python3", then `sys.executable`, in that order — the
    same PATH-then-current-interpreter convention
    resolve_target_python_executable() and app.execution's own bootstrap
    "python" capability already use) is rejected when it matches EITHER
    of those two specific, narrow exclusions, never silently accepted as
    a fallback. When no candidate survives that filter, this returns
    None — a deliberate fail-closed result, never a guess and never a
    hard-coded system path (no platform policy in this codebase
    guarantees one exists at a fixed location) — and
    resolve_environment_python_target() turns that into
    `resolved=False`, exactly like an absent project venv already does
    for `environment="venv"`.

    This is deliberately NARROWER than "reject any virtual environment
    whatsoever": an isolated toolchain venv a user has activated for
    this operation that is neither this project's own `.venv` nor ADC's
    own controller venv remains a legitimate, historically-accepted
    "host" target (see resolve_target_python_executable()'s own
    docstring) — only the two specific role-confusions this fix targets
    are excluded.

    Deterministic and testable: this function consults only
    `shutil.which`, `sys.executable`/`sys.prefix`, and filesystem state,
    never network or process execution."""
    def _acceptable(candidate: str | None) -> bool:
        return bool(candidate) and not (
            _is_this_projects_venv_interpreter(candidate, project_root)
            or _is_adc_controller_venv_interpreter(candidate)
        )

    for candidate in (shutil.which("python"), shutil.which("python3")):
        if _acceptable(candidate):
            return candidate
    if _acceptable(sys.executable):
        return sys.executable
    return None


# CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003: the fixed,
# closed set of CouncilVariant.environment labels this module can
# actually bind to a real, resolved target Python executable. Membership
# only, never inferred from a label's spelling -- a candidate that
# merely names "container"/"docker"/anything else is never treated as
# though a concrete target could be resolved for it.
CONTROLLED_PYTHON_ENVIRONMENTS = frozenset({"host", "venv"})


@dataclass(frozen=True)
class EnvironmentTargetResolution:
    """The outcome of binding ONE engineering candidate's own declared
    `environment` ("host" | "venv") to a single, concrete Python
    executable target, BEFORE that target is ever carried into
    materialization/installation/verification -- see
    resolve_environment_python_target()."""

    environment: str
    target_executable: str | None
    resolved: bool
    venv_directory: str | None = None
    needs_provisioning: bool = False


def _venv_directory(project_root: str | Path) -> Path:
    return Path(project_root) / ".venv"


def _venv_python_executable(venv_directory: Path) -> Path:
    if os.name == "nt":
        return venv_directory / "Scripts" / "python.exe"
    return venv_directory / "bin" / "python"


def _is_executable_interpreter(path: Path) -> bool:
    """CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004: a
    venv target is only ever "resolved" when it is a genuine, usable
    interpreter — a regular file the current process may actually
    execute (`os.access(..., os.X_OK)`), never merely a path that
    happens to exist (a directory, or an ordinary non-executable file
    such as a stray placeholder). This never launches *path* to prove
    it; it is the same non-invasive filesystem permission check, nothing
    more."""
    return path.is_file() and os.access(str(path), os.X_OK)


def resolve_environment_python_target(
    environment: str, project_root: str | None = None,
) -> EnvironmentTargetResolution:
    """THE single, central authority binding a CouncilVariant's own
    `environment` label to the ACTUAL Python executable target ADC's
    controlled install/verification architecture will use for it --
    called once, after a candidate has been selected and before its
    toolchain is materialized, so the SAME resolved target then flows
    unchanged through SetupPlan -> materialization ->
    PythonPackageExecutor install -> post-install verification.

    "host" resolves through resolve_host_python_executable() (CLAUDE-ADC-
    S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004: the corrected,
    venv-aware host policy) -- this function adds no further rule of its
    own for host and never routes a host resolution through the venv
    logic below, so a "host" candidate can never silently pick up a
    project's own isolated venv interpreter, or ADC's own controller/
    project virtualenv, merely because this function happens to also
    know about venvs. When no genuine host interpreter can be
    established, this fails closed (resolved=False) exactly like an
    absent project venv already does for "venv".

    "venv" resolves to THIS project's own isolated interpreter --
    `<project_root>/.venv/bin/python` (`Scripts\\python.exe` on
    Windows) -- a fixed, deterministic convention entirely independent
    of PATH/host resolution; it never falls back to
    resolve_target_python_executable() or to `sys.executable`. When
    that interpreter does not yet exist, no current ADC setup executor
    creates/provisions one, so resolution fails closed
    (resolved=False, needs_provisioning=True) rather than silently
    substituting the host target.

    Any environment outside CONTROLLED_PYTHON_ENVIRONMENTS (container,
    docker, an arbitrary label, or no project_root at all for "venv")
    always fails closed (resolved=False, target_executable=None).
    """
    if environment not in CONTROLLED_PYTHON_ENVIRONMENTS:
        return EnvironmentTargetResolution(
            environment=environment, target_executable=None, resolved=False,
        )
    if environment == "host":
        host_target = resolve_host_python_executable(project_root)
        return EnvironmentTargetResolution(
            environment="host",
            target_executable=host_target,
            resolved=host_target is not None,
        )
    # environment == "venv"
    if not project_root:
        return EnvironmentTargetResolution(
            environment="venv", target_executable=None, resolved=False,
        )
    venv_dir = _venv_directory(project_root)
    venv_python = _venv_python_executable(venv_dir)
    if _is_executable_interpreter(venv_python):
        return EnvironmentTargetResolution(
            environment="venv", target_executable=str(venv_python), resolved=True,
            venv_directory=str(venv_dir),
        )
    return EnvironmentTargetResolution(
        environment="venv", target_executable=None, resolved=False,
        venv_directory=str(venv_dir), needs_provisioning=True,
    )


def environment_target_matches(
    environment: str, target_executable: str | None, project_root: str | None = None,
) -> bool:
    """Defense-in-depth structural invariant: True only when
    *target_executable* is EXACTLY the one target
    resolve_environment_python_target() itself would resolve for this
    same (environment, project_root) pair -- never a looser
    compatibility guess (e.g. "looks like a venv path"). A venv target
    can never satisfy a host binding and a host target can never
    satisfy a venv binding, because each environment resolves through
    its own independent rule above and this function only ever compares
    against that SAME rule's own output."""
    resolution = resolve_environment_python_target(environment, project_root)
    return resolution.resolved and bool(target_executable) and (
        resolution.target_executable == target_executable
    )


# A fixed, internal, never-LLM-authored query with an explicit, tagged
# verdict protocol. A valid verdict is exactly one stdout line
#   "<tag> PRESENT <version>" | "<tag> PRESENT_VERSION_UNKNOWN" | "<tag> ABSENT"
# emitted by a query process that then exits 0. ABSENT is printed only for
# PackageNotFoundError -- genuine absence reported by the target Python's
# own distribution metadata. Any other outcome (nonzero exit, a runtime
# exception, no tagged line, extra or malformed output) carries NO
# presence verdict: absence is never inferred from a returncode, empty
# stdout, stderr text or a parser failure
# (CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003). The
# queried name is the only variable input, and it is always a value ADC
# has already validated as a structured distribution identifier.
DISTRIBUTION_QUERY_PROTOCOL_TAG = "__ADC_DISTRIBUTION_QUERY_V1__"
DISTRIBUTION_VERDICT_PRESENT = "PRESENT"
DISTRIBUTION_VERDICT_PRESENT_VERSION_UNKNOWN = "PRESENT_VERSION_UNKNOWN"
DISTRIBUTION_VERDICT_ABSENT = "ABSENT"

_VERDICT_LINE = re.compile(
    re.escape(DISTRIBUTION_QUERY_PROTOCOL_TAG)
    + r" (?:(?P<absent>ABSENT)|(?P<unknown>PRESENT_VERSION_UNKNOWN)|PRESENT (?P<version>\S+))"
)

DISTRIBUTION_METADATA_QUERY_SCRIPT = (
    "import importlib.metadata as metadata, sys\n"
    f"tag = {DISTRIBUTION_QUERY_PROTOCOL_TAG!r}\n"
    "name = sys.argv[1]\n"
    "try:\n"
    "    dist = metadata.distribution(name)\n"
    "except metadata.PackageNotFoundError:\n"
    "    print(tag, 'ABSENT'); sys.exit(0)\n"
    "try:\n"
    "    version = dist.version\n"
    "except Exception:\n"
    "    version = None\n"
    "if isinstance(version, str) and version.strip() and len(version.split()) == 1:\n"
    "    print(tag, 'PRESENT', version.strip())\n"
    "else:\n"
    "    print(tag, 'PRESENT_VERSION_UNKNOWN')\n"
    "sys.exit(0)\n"
)


def distribution_query_command(target_python: str, distribution_name: str) -> list[str]:
    """Build the fixed-shape, argv-only command that asks *target_python*
    whether *distribution_name* is installed, via distribution metadata
    (never import-module) semantics."""
    return [target_python, "-c", DISTRIBUTION_METADATA_QUERY_SCRIPT, distribution_name]


def distribution_query_verdict_line(verdict: str, version: str | None = None) -> str:
    """The exact stdout line a valid query emits for *verdict* -- the one
    place the protocol's serialized form is spelled, so test doubles and
    the producer can never drift apart."""
    if verdict == DISTRIBUTION_VERDICT_PRESENT:
        return f"{DISTRIBUTION_QUERY_PROTOCOL_TAG} {verdict} {version}"
    return f"{DISTRIBUTION_QUERY_PROTOCOL_TAG} {verdict}"


# CLAUDE-ADC-RSE033-EXECUTION-ERROR-AUXILIARY-ASSURANCE-CLOSURE-FIX-002:
# how the one target-Python query ended, taken only from the central
# controlled execution boundary's own structured outcome and the tagged
# verdict protocol above -- never from message text. Only QUERY_COMPLETED
# carries a presence verdict. TARGET_PYTHON_UNAVAILABLE (the target
# cannot be executed: boundary rejection, or a launch errno
# execute_controlled() classifies as an unavailable executable) is the
# only state that means capability absence; QUERY_EXECUTION_ERROR (the
# target started and then the query or its execution failed -- including
# a nonzero query exit -- or its launch failed for a reason provisioning
# cannot remedy), QUERY_TIMEOUT (the budget expired) and
# QUERY_MALFORMED_RESULT (the query exited 0 without exactly one valid
# verdict line) are no-verdict outcomes, never "unavailable" and never
# "not installed".
QUERY_COMPLETED = "completed"
TARGET_PYTHON_UNAVAILABLE = "target_python_unavailable"
QUERY_EXECUTION_ERROR = "execution_error"
QUERY_TIMEOUT = "timeout"
QUERY_MALFORMED_RESULT = "malformed_result"
_NO_VERDICT_QUERY_STATES = frozenset({QUERY_EXECUTION_ERROR, QUERY_TIMEOUT, QUERY_MALFORMED_RESULT})
_QUERY_STATES = frozenset({QUERY_COMPLETED, TARGET_PYTHON_UNAVAILABLE}) | _NO_VERDICT_QUERY_STATES


def interpret_distribution_query_output(
    returncode: int, stdout: str,
) -> tuple[str, bool | None, str | None]:
    """Return (query_state, installed, version) for one started query.

    installed is True/False only for QUERY_COMPLETED -- a valid tagged
    PRESENT/ABSENT verdict from a query that exited 0 -- and None for
    every no-verdict outcome: a nonzero exit is QUERY_EXECUTION_ERROR, an
    exit 0 without exactly one valid verdict line is
    QUERY_MALFORMED_RESULT."""
    if returncode != 0:
        return QUERY_EXECUTION_ERROR, None, None
    lines = [line.strip() for line in (stdout or "").splitlines() if line.strip()]
    match = _VERDICT_LINE.fullmatch(lines[0]) if len(lines) == 1 else None
    if match is None:
        return QUERY_MALFORMED_RESULT, None, None
    if match.group("absent"):
        return QUERY_COMPLETED, False, None
    if match.group("unknown"):
        return QUERY_COMPLETED, True, None
    return QUERY_COMPLETED, True, match.group("version")


def parse_distribution_query_output(returncode: int, stdout: str) -> tuple[bool | None, str | None]:
    """Return (installed, version) from one query's raw process output.

    installed=True means a valid PRESENT verdict (version=None when the
    version could not be determined -- a distinct, preserved state);
    installed=False means a valid ABSENT verdict only; installed=None
    means the query produced no presence verdict at all (see
    interpret_distribution_query_output) and must never be read as
    "not installed"."""
    _state, installed, version = interpret_distribution_query_output(returncode, stdout)
    return installed, version


@dataclass(frozen=True)
class DistributionCheckResult:
    """`query_state` is the whole answer; `installed` is only a presence
    verdict for QUERY_COMPLETED (True/False) and is None for every other
    state, so no consumer can read a missing verdict as absence --
    `present` / `absent` / `presence_verdict` state that explicitly.
    `target_python_available` is False exactly for
    TARGET_PYTHON_UNAVAILABLE and is kept for compatibility; when
    `query_state` is omitted it follows `target_python_available`
    (completed / unavailable)."""

    installed: bool | None
    version: str | None = None
    target_python_available: bool = True
    query_state: str | None = None
    diagnostics: str | None = field(default=None, compare=False)

    def __post_init__(self):
        if self.query_state is None:
            object.__setattr__(self, "query_state", (
                QUERY_COMPLETED if self.target_python_available else TARGET_PYTHON_UNAVAILABLE
            ))
        if self.query_state not in _QUERY_STATES:
            raise ValueError(f"unknown query_state={self.query_state!r}")
        if self.target_python_available != (self.query_state != TARGET_PYTHON_UNAVAILABLE):
            raise ValueError(
                f"target_python_available={self.target_python_available} contradicts "
                f"query_state={self.query_state!r}"
            )
        if self.query_state == QUERY_COMPLETED:
            if not isinstance(self.installed, bool):
                raise ValueError("a completed query requires an explicit presence verdict")
            if not self.installed and self.version is not None:
                raise ValueError("an absent distribution carries no version")
            return
        if self.installed or self.version is not None:
            raise ValueError(f"query_state={self.query_state!r} carries no presence verdict")
        object.__setattr__(self, "installed", None)

    @property
    def query_completed(self) -> bool:
        return self.query_state == QUERY_COMPLETED

    @property
    def present(self) -> bool:
        """A valid PRESENT verdict."""
        return self.query_completed and self.installed is True

    @property
    def absent(self) -> bool:
        """A valid ABSENT verdict -- the only state that means "not installed"."""
        return self.query_completed and self.installed is False

    @property
    def presence_verdict(self) -> str | None:
        if not self.query_completed:
            return None
        return DISTRIBUTION_VERDICT_PRESENT if self.installed else DISTRIBUTION_VERDICT_ABSENT

    @property
    def execution_failed(self) -> bool:
        """The query was attempted and produced no verdict -- neither
        presence nor absence of the distribution or the target Python."""
        return self.query_state in _NO_VERDICT_QUERY_STATES


def check_distribution_installed(
    distribution_name: str,
    target_python: str | None = None,
    *,
    project_root: str | None = None,
    timeout: int = 30,
) -> DistributionCheckResult:
    """Central distribution presence check, always routed through the
    central controlled execution boundary (execute_controlled) — there
    is no direct, unconfined subprocess fallback of any kind.

    project_root is required to perform any check at all: without it,
    this function makes no subprocess call whatsoever and reports the
    check as unavailable. A caller with no project scope available
    (e.g. a standalone diagnostic tool with no project context) must
    treat that the same way RequirementPreflight treats any other
    requirement type it cannot safely check — as "not locally
    verifiable" — rather than this function silently falling back to an
    uncontrolled, unconfined process launch.

    An explicitly supplied target_python is used exactly as given, with
    no fallback substitution — only the *default* (target_python=None)
    case uses resolve_target_python_executable()'s PATH-based heuristic,
    and callers that already have a specific resolved target (the
    normal productive case) must always pass it explicitly.

    A target Python that cannot be launched at all (missing, not
    executable, or rejected by the controlled execution boundary) is
    reported as unavailable (TARGET_PYTHON_UNAVAILABLE) rather than
    raising, or silently reporting "not installed". A query whose
    controlled execution failed (ControlledExecutionError) or timed out
    is reported as QUERY_EXECUTION_ERROR / QUERY_TIMEOUT, and a started
    query that exits nonzero or without exactly one valid tagged verdict
    as QUERY_EXECUTION_ERROR / QUERY_MALFORMED_RESULT -- never as
    unavailable and never as "not installed".
    """
    if project_root is None:
        return DistributionCheckResult(None, None, target_python_available=False)

    python_executable = target_python or resolve_target_python_executable()
    command = distribution_query_command(python_executable, distribution_name)

    from app.execution import ControlledExecutionError, ExecutionRequest, execute_controlled

    request = ExecutionRequest(
        tuple(command), str(project_root), timeout, "python", "verification",
    )
    try:
        completed = execute_controlled(request, project_root)
    except ValueError as exc:
        return DistributionCheckResult(
            None, None, target_python_available=False, diagnostics=str(exc)[:500],
        )
    except ControlledExecutionError as exc:
        # The query could not complete: its answer is unknown -- neither
        # "not installed" nor "target Python unavailable".
        return DistributionCheckResult(
            None, None, query_state=QUERY_EXECUTION_ERROR,
            diagnostics=f"{type(exc).__name__}: {exc}"[:500],
        )
    if completed is None:
        return DistributionCheckResult(
            None, None, target_python_available=False,
            diagnostics=f"Target Python could not be executed: {python_executable}",
        )
    if getattr(completed, "timed_out", False):
        return DistributionCheckResult(
            None, None, query_state=QUERY_TIMEOUT,
            diagnostics=f"Distribution query timed out after {timeout}s",
        )

    query_state, installed, version = interpret_distribution_query_output(
        completed.returncode, completed.stdout or "",
    )
    if query_state != QUERY_COMPLETED:
        # The query process started but produced no valid verdict: its
        # answer is unknown -- never "not installed".
        stderr_tail = (getattr(completed, "stderr", "") or "").strip()[-300:]
        return DistributionCheckResult(
            None, None, query_state=query_state,
            diagnostics=(
                f"Distribution query ended without a valid verdict "
                f"(returncode={completed.returncode}): {stderr_tail}"
            )[:500],
        )
    return DistributionCheckResult(installed, version, target_python_available=True)
