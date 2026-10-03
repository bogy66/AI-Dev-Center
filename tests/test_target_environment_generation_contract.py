"""TEST_040 regressions for target-environment context across S3 -> S4 -> S5.

These cases use the real approved-setup workflow, S4.1 generation and file
application, DevelopmentTestingStage, verification planning, and
ControlledRunnerRegistry. Only the external setup/LLM/environment-probe
boundaries are deterministic test doubles. They intentionally remain ordinary
tests while TEST_040 is draft / NOT_RUN until its formal acceptance run is
authorized and recorded.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

from app.controlled_rework_stage import ControlledReworkStage
from app.dev_workflow import DevelopmentWorkflow
from app.development_stage import DeveloperAgent, DevelopmentRequest, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.developer_file_applier import DeveloperFileApplier
from app.project_test_runner import TestResult as ProjectTestResult
from app.requirement_model import SetupPlan, SetupStep
from app.setup_execution_state import SetupExecutionStateStore
from app.setup_executor import ExecutionResult
from app.test_change_generator import TestChangeGenerator
from app.testing_stage import DiagnosisReviewer, TestingStage
from app.verification import (
    build_default_registry,
)


_USER_TASK = (
    "The user selected TypeScript for this project. Preserve that choice and "
    "the existing project conventions while updating the generated artifact."
)
_GENERATED_SOURCE = "target-tool-requirement: TargetTool 5.7\n"


class _LLMExecutor:
    def __init__(self, timeline):
        self.timeline = timeline
        self.calls = []

    def run(self, role, task, context, role_again):
        self.calls.append((role, task, context))
        if role == "developer":
            self.timeline.append("generator")
            return json.dumps({
                "changes": [{
                    "file": "generated.contract",
                    "action": "create",
                    "content": _GENERATED_SOURCE,
                }],
                "tests": [],
            })
        if role == "tester":
            return json.dumps({
                "disposition": "no_changes_required",
                "reason": "the configured verifier checks generated.contract",
                "changes": [],
                "tests": [],
            })
        if role == "reviewer":
            return json.dumps({"decision": "accepted", "summary": "review complete"})
        raise AssertionError(f"unexpected LLM role: {role}")


class _SetupExecutor:
    def __init__(self, timeline):
        self.timeline = timeline

    def execute(self, step, project_root=None):
        self.timeline.append("setup")
        return ExecutionResult(step.id, True, "controlled setup completed", True)


class _ProjectInspector:
    """A deterministic ProjectIntelligence input for real S5 planning."""
    def build_intelligence(self, project_root):
        return SimpleNamespace(
            project_root=str(project_root), project_kind="existing",
            areas=(SimpleNamespace(
                path=".",
                test_systems=(SimpleNamespace(name="pytest", evidence=()),),
                build_systems=(), firmware_indicators=(),
            ),),
        )


def _approved_plan(*, with_observable_toolchain: bool):
    steps = ()
    if with_observable_toolchain:
        # The environment probe itself is stubbed at the controlled
        # execution/distribution query boundary, while the production
        # environment establishment and S3 -> S4 handoff run normally.
        from app.requirement_model import SetupEffect
        steps = (SetupStep(
            id="toolchain-step", requirement_id="toolchain-req", action="install",
            install_method="pip", package="target-tool", version="5.7",
            is_approved=True, setup_effect=SetupEffect.PYTHON_PACKAGE_INSTALL,
            target_executable="controlled-test-target",
        ),)
    return SetupPlan(
        id="plan-target-environment", project_id="project-target-environment",
        steps=steps, status="approved",
    )


def _workflow(tmp_path, timeline, llm):
    testing = DevelopmentTestingStage(
        DevelopmentStage(DeveloperAgent(llm)),
        TestChangeGenerator(llm), DeveloperFileApplier,
        project_test_runner=SimpleNamespace(run=lambda request: ProjectTestResult(True, 0, "", "", ())),
        testing_stage=TestingStage(DiagnosisReviewer(llm)),
        verification_registry=build_default_registry(),
        project_inspector=_ProjectInspector(),
    )
    return DevelopmentWorkflow(
        discovery=None, validator=None, preflight=None,
        executor=_SetupExecutor(timeline),
        controlled_rework_stage=ControlledReworkStage(testing),
        execution_state_store=SetupExecutionStateStore(storage=tmp_path / "setup-state.json"),
    )


def _current_cycle(result):
    return result.controlled_rework_result.initial_result


def _project_verification_checks_generated_source(project_root):
    (project_root / "test_target_source.py").write_text(
        "from pathlib import Path\n"
        "def test_generated_source_matches_target():\n"
        "    assert 'TargetTool 5.7' in Path('generated.contract').read_text()\n",
        encoding="utf-8",
    )


def _target_python_wrapper(project_root):
    """Return a distinct target executable that runs the installed pytest.

    The subprocess boundary is exercised through the production PytestRunner;
    the wrapper makes target-vs-host selection observable without requiring a
    second interpreter installation in the test environment.
    """
    wrapper = project_root / "target-python"
    wrapper.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return str(wrapper)


def _run_real_verification_process(args, cwd, timeout, **kwargs):
    return subprocess.run(
        args, cwd=cwd, timeout=timeout, capture_output=True, text=True,
        check=False,
    )


def test_s3_s4_generation_and_production_s5_runner_use_the_same_target(
    tmp_path, monkeypatch,
):
    """The production S5 runner must execute project checks through the
    target executable established before generation, against applied source.
    """
    import app.execution
    import app.python_distribution
    timeline = []
    llm = _LLMExecutor(timeline)
    target_python = _target_python_wrapper(tmp_path)
    verification_commands = []

    def execute_target(request, project_root=None):
        args = tuple(request.args)
        if args[0] == target_python and args[1:] == ("--version",):
            timeline.append("environment_probe")
            return SimpleNamespace(
                returncode=0, stdout="TargetTool 5.7\n", stderr="", timed_out=False,
            )
        timeline.append("verification")
        verification_commands.append(args)
        return _run_real_verification_process(
            args, Path(request.cwd), request.timeout,
        )

    monkeypatch.setattr(app.execution, "execute_controlled", execute_target)
    monkeypatch.setattr(
        app.python_distribution, "check_distribution_installed",
        lambda *args, **kwargs: SimpleNamespace(
            present=True, absent=False, version="5.7", query_state="present",
        ),
    )
    _project_verification_checks_generated_source(tmp_path)

    (tmp_path / "package.json").write_text(
        '{"devDependencies":{"typescript":"5.7.0"}}', encoding="utf-8",
    )
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions":{}}', encoding="utf-8")
    request = DevelopmentRequest(
        "project-target-environment", tmp_path, _USER_TASK, run_id="target-context-run",
    )
    plan = _approved_plan(with_observable_toolchain=True)
    plan = replace(
        plan,
        steps=tuple(replace(step, target_executable=target_python) for step in plan.steps),
    )

    result = _workflow(tmp_path, timeline, llm).execute_approved_and_run_development(
        plan, request,
    )

    developer_call = next(call for call in llm.calls if call[0] == "developer")
    generator_input = developer_call[1] + "\n" + developer_call[2]
    assert timeline.index("setup") < timeline.index("environment_probe") < timeline.index("generator")
    assert "TargetTool 5.7" in generator_input
    assert "Project conventions detected: established" in generator_input
    assert "typescript" in generator_input.lower()
    assert "Preserve the user's chosen technology" in generator_input
    assert _USER_TASK in generator_input
    assert _current_cycle(result).status == "accepted"
    assert _current_cycle(result).verification_result is not None
    assert verification_commands
    assert verification_commands[0][0] == target_python
    assert "pytest" in verification_commands[0]
    assert _current_cycle(result).verification_result.passed is True
    assert timeline.index("generator") < timeline.index("verification")


def test_unavailable_target_environment_cannot_be_confirmed_by_host_verification(
    tmp_path, monkeypatch,
):
    """A project with no established setup properties still receives an
    explicit unknown context; absence is not turned into a compatibility claim.
    """
    import app.execution

    timeline = []
    llm = _LLMExecutor(timeline)
    def execute_host_verification(request, project_root=None):
        args = tuple(request.args)
        timeline.append("verification")
        return _run_real_verification_process(
            args, Path(request.cwd), request.timeout,
        )

    monkeypatch.setattr(app.execution, "execute_controlled", execute_host_verification)
    _project_verification_checks_generated_source(tmp_path)
    request = DevelopmentRequest(
        "project-target-environment", tmp_path, _USER_TASK, run_id="unknown-context-run",
    )

    result = _workflow(tmp_path, timeline, llm).execute_approved_and_run_development(
        _approved_plan(with_observable_toolchain=False), request,
    )

    developer_call = next(call for call in llm.calls if call[0] == "developer")
    generator_input = developer_call[1] + "\n" + developer_call[2]
    cycle = _current_cycle(result)
    assert "Environment properties: unknown" in generator_input
    assert "not confirmed (unknown)" in generator_input
    assert cycle.development_result.generation_evidence["target_environment_state"] == "unknown"
    assert cycle.status != "accepted"
    assert cycle.verification_result is None or not cycle.verification_result.passed


def _interpreter(target, state="established"):
    from app.target_environment import EnvironmentProperty
    return EnvironmentProperty(
        kind="interpreter", name="execution target", state=state,
        target_executable=target if state == "established" else None,
    )


def test_plan_selected_target_that_cannot_be_observed_is_never_replaced():
    """S5 must not fall back to another observed target when the target the
    approved plan selected could not be established."""
    from app.target_environment import TargetEnvironmentContext
    context = TargetEnvironmentContext(
        state="partial",
        properties=(_interpreter("/x/plan-target", "unknown"), _interpreter("/x/step-target")),
        declared_target="/x/plan-target",
    )
    assert context.verification_target is None


def test_plan_selected_target_is_the_verification_target_when_observed():
    from app.target_environment import TargetEnvironmentContext
    context = TargetEnvironmentContext(
        state="established",
        properties=(_interpreter("/x/step-target"), _interpreter("/x/plan-target")),
        declared_target="/x/plan-target",
    )
    assert context.verification_target == "/x/plan-target"


def test_several_different_observed_targets_are_ambiguous_not_a_choice():
    from app.target_environment import TargetEnvironmentContext
    context = TargetEnvironmentContext(
        state="established",
        properties=(_interpreter("/x/a"), _interpreter("/x/b")),
    )
    assert context.verification_target is None
