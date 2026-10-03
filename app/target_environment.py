"""Target-environment compatibility context for S4.1 source generation.

SYS_REQ_032 / ARC_REQ_027 / SUB_REQ_041 / IF_REQ_038: before source is
generated, ADC establishes the properties of the INTENDED project
environment that affect source compatibility (tool/interpreter versions,
installed component versions) and hands them to the generator as context
over the existing S3->S4 handoff (DevelopmentRequest).

Honesty rules (never relaxed):
- Every property carries its own state. Only an actually observed value is
  "established"; a probe that cannot run, fails, times out or has no
  registered probe for a setup effect yields "unknown" -- never a guess.
- `compatibility` is ALWAYS "unknown" here: ADC has not checked any
  generated source at this point, so compatibility is never represented as
  confirmed by this module. Confirmation, if any, is later verification
  evidence, not this context.
- Technology neutral: the establishing logic dispatches on the plan step's
  own `setup_effect` through a registry (_PROBES). No language, toolchain or
  platform is preferred; an effect without a probe is reported unknown. The
  user's technology choice and the project's conventions are carried as
  context and the generator is told to preserve them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Callable

STATE_ESTABLISHED = "established"
STATE_PARTIAL = "partial"
STATE_UNKNOWN = "unknown"

# Property-level states.
PROPERTY_ESTABLISHED = "established"
PROPERTY_ABSENT = "absent"
PROPERTY_UNKNOWN = "unknown"

COMPATIBILITY_UNKNOWN = "unknown"

_PROBE_TIMEOUT_SECONDS = 15
_MAX_PROPERTIES = 64
_MAX_VALUE_LENGTH = 200
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value, limit: int = _MAX_VALUE_LENGTH) -> str:
    return _CONTROL_CHARS.sub(" ", str(value)).strip()[:limit]


@dataclass(frozen=True)
class EnvironmentProperty:
    """One compatibility-relevant property of the intended environment."""
    kind: str                      # "interpreter" | "component" | "setup_target"
    name: str
    state: str                     # PROPERTY_*
    observed_version: str | None = None
    required_version: str | None = None
    reason: str | None = None      # fixed token explaining an unknown/absent state
    # Execution target actually observed (probed) for this property; S5
    # verifies through exactly this target.
    target_executable: str | None = None


@dataclass(frozen=True)
class TargetEnvironmentContext:
    """Established (or explicitly unknown) target-environment context."""
    state: str = STATE_UNKNOWN
    properties: tuple[EnvironmentProperty, ...] = field(default_factory=tuple)
    # Project conventions / chosen technology as detected, context only.
    conventions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    conventions_state: str = STATE_UNKNOWN
    compatibility: str = COMPATIBILITY_UNKNOWN
    # The environment target the approved plan itself selected (independent
    # of its steps), when it named one. S5 may only verify through exactly
    # this target; it never falls back to another observed target.
    declared_target: str | None = None

    def evidence_token(self) -> str:
        return self.state

    @property
    def verification_target(self) -> str | None:
        """The execution target observed before generation, through which S5
        must verify. None when no single target could be identified and used
        reliably -- compatibility then stays unconfirmed. A plan-selected
        target that could not be observed is never replaced by another one,
        and several different observed targets are ambiguous, not a choice."""
        observed = {
            prop.target_executable for prop in self.properties
            if prop.kind == "interpreter" and prop.state == PROPERTY_ESTABLISHED
            and prop.target_executable
        }
        if self.declared_target:
            return self.declared_target if self.declared_target in observed else None
        if len(observed) == 1:
            return next(iter(observed))
        return None

    def render_for_generator(self) -> str:
        """Deterministic, bounded, delimited text block for the generator.
        Observed values are data, never instructions."""
        lines = [
            "----- TARGET ENVIRONMENT CONTEXT (established by ADC before generation) -----",
            f"Environment properties: {self.state}",
            "Source compatibility with this environment: not confirmed (unknown) -- "
            "generate source compatible with the observed properties below; do not "
            "assume anything about properties marked unknown.",
        ]
        for prop in self.properties[:_MAX_PROPERTIES]:
            detail = prop.state
            if prop.observed_version:
                detail += f", observed version {_clean(prop.observed_version)}"
            if prop.required_version:
                detail += f", planned version {_clean(prop.required_version)}"
            if prop.reason:
                detail += f" ({_clean(prop.reason)})"
            lines.append(f"- {_clean(prop.kind)} {_clean(prop.name)}: {detail}")
        if not self.properties:
            lines.append("- no environment property could be established")
        lines.append(f"Project conventions detected: {self.conventions_state}")
        for key in sorted(self.conventions):
            values = ", ".join(_clean(v, 80) for v in self.conventions[key])
            if values:
                lines.append(f"- {_clean(key, 40)}: {values}")
        lines.append(
            "Preserve the user's chosen technology and the project's existing "
            "conventions; do not change technology to suit the environment."
        )
        lines.append("----- END TARGET ENVIRONMENT CONTEXT -----")
        return "\n".join(lines)


# --- probes (registry keyed by the plan step's own setup_effect) -----------

def _first_line(text: str | None) -> str | None:
    for line in (text or "").splitlines():
        if line.strip():
            return _clean(line)
    return None


def _probe_interpreter_version(target_executable: str, project_root: str) -> EnvironmentProperty:
    """Observed `--version` of an already-resolved execution target, run
    only through the central controlled execution boundary."""
    from app.execution import ExecutionRequest, execute_controlled
    name = "execution target"
    try:
        completed = execute_controlled(
            ExecutionRequest(
                (target_executable, "--version"), project_root,
                _PROBE_TIMEOUT_SECONDS, "python", "verification",
            ),
            project_root,
        )
    except Exception:
        return EnvironmentProperty("interpreter", name, PROPERTY_UNKNOWN, reason="probe_failed")
    if completed is None:
        return EnvironmentProperty("interpreter", name, PROPERTY_UNKNOWN, reason="target_unavailable")
    if getattr(completed, "timed_out", False):
        return EnvironmentProperty("interpreter", name, PROPERTY_UNKNOWN, reason="probe_timeout")
    if completed.returncode != 0:
        return EnvironmentProperty("interpreter", name, PROPERTY_UNKNOWN, reason="probe_failed")
    version = _first_line(completed.stdout) or _first_line(getattr(completed, "stderr", None))
    if not version:
        return EnvironmentProperty("interpreter", name, PROPERTY_UNKNOWN, reason="no_version_output")
    return EnvironmentProperty("interpreter", name, PROPERTY_ESTABLISHED, observed_version=version,
                               target_executable=target_executable)


def _probe_python_package_step(step, project_root: str) -> list[EnvironmentProperty]:
    from app.python_distribution import check_distribution_installed
    props: list[EnvironmentProperty] = []
    package = getattr(step, "package", None)
    target = getattr(step, "target_executable", None)
    if not package or not target:
        return [EnvironmentProperty(
            "component", _clean(package or step.id), PROPERTY_UNKNOWN,
            required_version=getattr(step, "version", None), reason="no_execution_target",
        )]
    result = check_distribution_installed(
        package, target, project_root=project_root, timeout=_PROBE_TIMEOUT_SECONDS,
    )
    required = getattr(step, "version", None)
    if result.present:
        props.append(EnvironmentProperty(
            "component", _clean(package), PROPERTY_ESTABLISHED,
            observed_version=result.version, required_version=required,
            reason=None if result.version else "version_unreported",
        ))
    elif result.absent:
        props.append(EnvironmentProperty(
            "component", _clean(package), PROPERTY_ABSENT, required_version=required,
        ))
    else:
        props.append(EnvironmentProperty(
            "component", _clean(package), PROPERTY_UNKNOWN,
            required_version=required, reason=str(result.query_state),
        ))
    return props


# setup_effect -> (execution-target probe, per-step probe). Adding another
# ecosystem means adding one entry here.
def _python_effect() -> str:
    from app.requirement_model import SetupEffect
    return SetupEffect.PYTHON_PACKAGE_INSTALL


def _probes() -> dict[str, tuple[Callable, Callable]]:
    return {_python_effect(): (_probe_interpreter_version, _probe_python_package_step)}


def _conventions_from_intelligence(intelligence) -> tuple[dict[str, tuple[str, ...]], str]:
    if intelligence is None:
        return {}, STATE_UNKNOWN
    try:
        summary = intelligence.to_summary()
        keys = ("languages", "frameworks", "package_systems", "build_systems", "test_systems")
        conventions = {
            k: tuple(_clean(v, 80) for v in summary.get(k, ()) if v)
            for k in keys if summary.get(k)
        }
    except Exception:
        return {}, STATE_UNKNOWN
    return conventions, STATE_ESTABLISHED


def establish_target_environment(plan, project_path, intelligence=None) -> TargetEnvironmentContext:
    """Establish the intended target environment's compatibility-relevant
    properties. Never raises: any failure leaves the affected property (or
    the whole context) explicitly unknown."""
    try:
        return _establish(plan, str(project_path), intelligence)
    except Exception:
        return TargetEnvironmentContext()


def _establish(plan, project_root: str, intelligence) -> TargetEnvironmentContext:
    registry = _probes()
    properties: list[EnvironmentProperty] = []
    probed_targets: set[tuple[str, str]] = set()
    # The environment selected for the approved variant (carried by the plan
    # independent of its steps) is probed first, so it is the S5 target even
    # when setup has no steps. Never inferred from PATH or this interpreter.
    plan_target = getattr(plan, "environment_target_executable", None)
    if plan_target and isinstance(plan_target, str):
        probed_targets.add((_python_effect(), plan_target))
        prop = _probe_interpreter_version(plan_target, project_root)
        properties.append(replace(prop, name=f"{prop.name} #{len(probed_targets)}"))
    for step in getattr(plan, "steps", ()) or ():
        if len(properties) >= _MAX_PROPERTIES:
            break
        effect = getattr(step, "setup_effect", None)
        probes = registry.get(effect) if effect else None
        if probes is None:
            properties.append(EnvironmentProperty(
                "setup_target", _clean(getattr(step, "package", None) or step.id),
                PROPERTY_UNKNOWN, required_version=getattr(step, "version", None),
                reason="no_probe_for_setup_effect",
            ))
            continue
        target_probe, step_probe = probes
        target = getattr(step, "target_executable", None)
        if target and (effect, target) not in probed_targets:
            probed_targets.add((effect, target))
            prop = target_probe(target, project_root)
            properties.append(replace(prop, name=f"{prop.name} #{len(probed_targets)}"))
        try:
            properties.extend(step_probe(step, project_root))
        except Exception:
            properties.append(EnvironmentProperty(
                "component", _clean(getattr(step, "package", None) or step.id),
                PROPERTY_UNKNOWN, reason="probe_failed",
            ))
    states = {p.state for p in properties}
    if not properties or states <= {PROPERTY_UNKNOWN}:
        state = STATE_UNKNOWN
    elif PROPERTY_UNKNOWN in states:
        state = STATE_PARTIAL
    else:
        state = STATE_ESTABLISHED
    conventions, conventions_state = _conventions_from_intelligence(intelligence)
    return TargetEnvironmentContext(
        state=state, properties=tuple(properties),
        conventions=conventions, conventions_state=conventions_state,
        declared_target=plan_target if isinstance(plan_target, str) and plan_target else None,
    )
