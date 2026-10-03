"""DEF-RSE033-ESPHOME-COMPILE-TIMEOUT / NO_VERDICT_AS_ABSENCE_CLASSIFICATION:
permanent lower-gate regressions.

CLAUDE-ADC-RSE033-RESIDUAL-DISTRIBUTION-PTY-CLOSURE-FIX-003. A target-Python
distribution query whose process started, reached the real query and then
crashed exited nonzero; that returncode was parsed as "not installed", the
completed DistributionCheckResult said installed=False, RequirementPreflight
listed the requirement as missing, and SetupPlanner produced an install step
for a requirement whose presence was never established.

Absence may be asserted only from the query protocol's own explicit ABSENT
verdict (IF_REQ_003 observable facts, SYS_REQ_024 fail-closed, SYS_REQ_021 /
SYS_REQ_027 no reinterpretation of infrastructure failure). Every query
outcome below comes from a REAL child process run through the real central
controlled execution boundary; nothing downstream is hand-built:

  TestDistributionPresenceClassification -- present / absent / target
      unavailable / runtime crash / timeout / malformed stay distinct;
  TestPreflightNoVerdictFailsClosed      -- RequirementPreflight and the
      real DevelopmentWorkflow fail closed on every no-verdict outcome: no
      missing requirement, no setup step, no Council, no materialization;
  TestValidAbsenceStillAuthorizesSetup   -- a genuine ABSENT verdict keeps
      the existing missing-requirement -> SetupPlanner install route.
"""
from __future__ import annotations

import functools
import os
import shlex
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.requirement_preflight as preflight_module
from app.ai_requirement_discovery import AIRequirementDiscovery
from app.dev_workflow import DevelopmentWorkflow
from app.engineering_council import EngineeringCouncil
from app.python_distribution import (
    QUERY_COMPLETED,
    QUERY_EXECUTION_ERROR,
    QUERY_MALFORMED_RESULT,
    QUERY_TIMEOUT,
    TARGET_PYTHON_UNAVAILABLE,
    check_distribution_installed,
)
from app.requirement_model import DiscoveryResult, Requirement
from app.requirement_preflight import RequirementCheckExecutionError, RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_planner import SetupPlanner
from app.toolchain_materializer import ToolchainMaterializer

posix_only = pytest.mark.skipif(os.name != "posix", reason="uses POSIX shell target interpreters")

PRESENT_DISTRIBUTION = "pytest"
ABSENT_DISTRIBUTION = "adc-no-such-distribution-xyz"

# The wrapper runs the REAL query script handed to it (-c <script> <name>)
# in a real interpreter, after making the metadata backend fail with a
# runtime error that is NOT PackageNotFoundError -- the query process
# starts, reaches the actual distribution query, and dies nonzero with a
# traceback and no verdict line.
_CRASHING_QUERY = (
    "import importlib.metadata as metadata, sys\n"
    "def _broken(name):\n"
    "    raise RuntimeError('distribution metadata backend failure')\n"
    "metadata.distribution = _broken\n"
    "code = sys.argv[1]\n"
    "sys.argv = [sys.argv[0]] + sys.argv[2:]\n"
    "exec(compile(code, '<adc-distribution-query>', 'exec'), {'__name__': '__main__'})\n"
)


def _python_wrapper(tmp_path: Path, name: str, body: str) -> Path:
    """A real target "python" on its own PATH dir, named python so the
    capability registry and resolve_target_python_executable() treat it
    exactly like a real interpreter."""
    bin_dir = tmp_path / f"{name}-bin"
    bin_dir.mkdir()
    target = bin_dir / "python"
    target.write_text("#!/bin/sh\n" + body)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def crashing_query_python(tmp_path: Path) -> Path:
    return _python_wrapper(
        tmp_path, "crashing",
        f'exec {shlex.quote(sys.executable)} -c {shlex.quote(_CRASHING_QUERY)} "$2" "$3"\n',
    )


def hanging_query_python(tmp_path: Path) -> Path:
    return _python_wrapper(tmp_path, "hanging", f"exec {shlex.quote(sys.executable)} -c 'import time; time.sleep(60)'\n")


def malformed_query_python(tmp_path: Path) -> Path:
    # starts, exits 0, but answers without the tagged verdict protocol
    return _python_wrapper(tmp_path, "malformed", "echo 1.2.3\nexit 0\n")


def _requirement(distribution: str) -> Requirement:
    return Requirement(
        id=f"req-{distribution}", name=distribution, technical_identity=distribution,
        type="python_package", purpose="tests", required=True, confidence=0.9,
        install_method="pip", verification_method=f"pip show {distribution}",
    )


def _on_path(monkeypatch, target: Path) -> None:
    monkeypatch.setenv("PATH", f"{target.parent}{os.pathsep}{os.environ.get('PATH', '')}")


def _no_verdict_targets(tmp_path: Path, monkeypatch):
    """(label, target, expected query_state), each with the REAL central
    check; the timeout case gets a 1 s budget instead of the default."""
    monkeypatch.setattr(
        preflight_module, "check_distribution_installed",
        functools.partial(check_distribution_installed, timeout=1),
    )
    return (
        ("runtime-crash", crashing_query_python(tmp_path), QUERY_EXECUTION_ERROR),
        ("timeout", hanging_query_python(tmp_path), QUERY_TIMEOUT),
        ("malformed", malformed_query_python(tmp_path), QUERY_MALFORMED_RESULT),
    )


@posix_only
class TestDistributionPresenceClassification:
    def test_every_query_outcome_has_its_own_state(self, tmp_path, monkeypatch):
        root = str(tmp_path)

        def check(distribution, target, timeout=30):
            with monkeypatch.context() as m:
                _on_path(m, Path(target))
                return check_distribution_installed(distribution, str(target), project_root=root, timeout=timeout)

        present = check(PRESENT_DISTRIBUTION, sys.executable)
        absent = check(ABSENT_DISTRIBUTION, sys.executable)
        unavailable = check(PRESENT_DISTRIBUTION, tmp_path / "no-such-python")
        crashed = check(PRESENT_DISTRIBUTION, crashing_query_python(tmp_path))
        timed_out = check(PRESENT_DISTRIBUTION, hanging_query_python(tmp_path), timeout=1)
        malformed = check(PRESENT_DISTRIBUTION, malformed_query_python(tmp_path))

        assert (present.query_state, present.presence_verdict, present.installed) == (QUERY_COMPLETED, "PRESENT", True)
        assert present.version
        assert (absent.query_state, absent.presence_verdict, absent.installed) == (QUERY_COMPLETED, "ABSENT", False)
        assert absent.absent and not absent.execution_failed
        assert unavailable.query_state == TARGET_PYTHON_UNAVAILABLE
        assert unavailable.target_python_available is False and unavailable.installed is None
        assert not unavailable.absent and not unavailable.execution_failed
        for outcome, state in ((crashed, QUERY_EXECUTION_ERROR), (timed_out, QUERY_TIMEOUT),
                               (malformed, QUERY_MALFORMED_RESULT)):
            assert outcome.query_state == state
            # a started target Python is available -- and still proves nothing about the query
            assert outcome.target_python_available is True
            assert outcome.installed is None and outcome.presence_verdict is None
            assert not outcome.absent and not outcome.present and outcome.execution_failed
        assert "returncode=1" in crashed.diagnostics
        assert "distribution metadata backend failure" in crashed.diagnostics

    def test_runtime_crash_really_reached_the_query(self, tmp_path):
        """The crash is inside the real query process -- not a parent-side
        injection: the child ran the real query script and died in it."""
        import subprocess

        from app.python_distribution import distribution_query_command

        command = distribution_query_command(str(crashing_query_python(tmp_path)), PRESENT_DISTRIBUTION)
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 1
        assert "<adc-distribution-query>" in completed.stderr
        assert "RuntimeError: distribution metadata backend failure" in completed.stderr
        assert completed.stdout == ""


@posix_only
class TestPreflightNoVerdictFailsClosed:
    def test_preflight_raises_for_every_no_verdict_outcome(self, tmp_path, monkeypatch):
        requirement = _requirement(PRESENT_DISTRIBUTION)
        for label, target, state in _no_verdict_targets(tmp_path, monkeypatch):
            with monkeypatch.context() as m, pytest.raises(RequirementCheckExecutionError) as caught:
                _on_path(m, target)
                RequirementPreflight.check(
                    (requirement,), "proj", project_root=str(tmp_path), target_executable=str(target),
                )
            assert (label, caught.value.requirement_id, caught.value.query_state) == (
                label, requirement.id, state,
            )

    def test_real_runtime_crash_never_reaches_setup_council_or_materialization(self, tmp_path, monkeypatch):
        """real query crash -> real DistributionCheckResult -> real
        RequirementPreflight inside the real DevelopmentWorkflow -> fail
        closed: no missing requirement, no SetupPlanner step, no Council or
        provider, no materialization."""
        requirement = _requirement(PRESENT_DISTRIBUTION)
        for label, target, state in _no_verdict_targets(tmp_path, monkeypatch):
            with monkeypatch.context() as m:
                _on_path(m, target)
                discovery = Mock(spec=AIRequirementDiscovery)
                discovery.discover.return_value = DiscoveryResult(
                    id="d", source="test", project_id="proj", requirements=(requirement,),
                )
                planner = Mock(spec=SetupPlanner)
                council = Mock(spec=EngineeringCouncil)
                materializer = Mock(spec=ToolchainMaterializer)
                workflow = DevelopmentWorkflow(
                    discovery, RequirementValidator(), RequirementPreflight(), planner,
                    council=council, materializer=materializer,
                )
                with pytest.raises(RequirementCheckExecutionError) as caught:
                    workflow.run({"name": "p"}, "proj", project_context=SimpleNamespace(project_root=str(tmp_path)))
                assert (label, caught.value.query_state) == (label, state)
                assert planner.method_calls == []
                council.evaluate.assert_not_called()
                assert council.method_calls == []
                materializer.materialize_decision.assert_not_called()
                assert materializer.method_calls == []


@posix_only
class TestValidAbsenceStillAuthorizesSetup:
    def test_genuine_absence_is_missing_and_planned(self, tmp_path):
        requirement = _requirement(ABSENT_DISTRIBUTION)
        result = RequirementPreflight.check(
            (requirement,), "proj", project_root=str(tmp_path), target_executable=sys.executable,
        )
        assert result.missing_requirements == (requirement,)
        assert result.results[0].present is False and result.results[0].warning is None
        plan = SetupPlanner().plan((requirement,), result, "proj")
        assert [step.package for step in plan.steps] == [ABSENT_DISTRIBUTION]

    def test_genuine_presence_is_already_installed(self, tmp_path):
        requirement = _requirement(PRESENT_DISTRIBUTION)
        result = RequirementPreflight.check(
            (requirement,), "proj", project_root=str(tmp_path), target_executable=sys.executable,
        )
        assert result.missing_requirements == () and result.already_installed == (requirement,)
        assert result.results[0].satisfied and result.results[0].detected_version
        assert SetupPlanner().plan((requirement,), result, "proj").steps == ()
