"""Development workflow with Council planning and explicit approved execution."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.council_models import CouncilInput, CouncilResult
from app.engineering_council import EngineeringCouncil
from app.requirement_model import (
    DiscoveryResult,
    PreflightResult,
    SetupPlan,
    ValidationResult,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_executor import ExecutionResult, SetupExecutor
from app.setup_planner import SetupPlanner
from app.toolchain_materializer import ToolchainMaterializer
from app.development_testing_stage import DevelopmentTestingResult, DevelopmentTestingStage
from app.controlled_rework_stage import ControlledReworkResult, ControlledReworkStage
from app.diagnostic_trace import DiagnosticTraceError


class WorkflowExecutionError(Exception):
    """Raised when the workflow cannot continue safely."""


@dataclass(frozen=True)
class WorkflowResult:
    """Immutable result of discovery through Council-based planning."""

    discovery_result: DiscoveryResult
    validation_result: ValidationResult
    preflight_result: PreflightResult
    council_result: CouncilResult
    setup_plan: SetupPlan


@dataclass(frozen=True)
class SetupDevelopmentTestingResult:
    """Results of approved setup execution followed by canonical testing."""

    setup_execution_results: tuple[ExecutionResult, ...]
    controlled_rework_result: ControlledReworkResult
    final_approval_result: object | None = None

    @property
    def development_testing_result(self) -> DevelopmentTestingResult:
        return self.controlled_rework_result.final_result

    @property
    def status(self) -> str:
        return self.controlled_rework_result.status


class DevelopmentWorkflow:
    """Run canonical planning and, separately, approved execution."""

    def __init__(
        self,
        discovery: AIRequirementDiscovery,
        validator: RequirementValidator,
        preflight: RequirementPreflight,
        planner: SetupPlanner | None = None,
        executor: SetupExecutor | None = None,
        council: EngineeringCouncil | None = None,
        materializer: ToolchainMaterializer | None = None,
        development_testing_stage: DevelopmentTestingStage | None = None,
        controlled_rework_stage: ControlledReworkStage | None = None,
        diagnostic_trace: object | None = None,
    ) -> None:
        self._discovery = discovery
        self._validator = validator
        self._preflight = preflight

        # Transitional constructor compatibility only.
        # The canonical planning flow no longer uses SetupPlanner.
        self._planner = planner

        self._executor = executor
        self._council = council
        self._materializer = materializer
        self._development_testing_stage = development_testing_stage
        self._controlled_rework_stage = controlled_rework_stage
        self._diagnostic_trace = diagnostic_trace

    def set_diagnostic_trace(self, diagnostic_trace) -> None:
        self._diagnostic_trace = diagnostic_trace

    def _trace(self, run_id, phase, event_type, status, summary, **kwargs):
        if self._diagnostic_trace is not None:
            try:
                self._diagnostic_trace.record(
                    run_id, phase, event_type, status, summary,
                    source="development_workflow", **kwargs,
                )
            except DiagnosticTraceError:
                return None

    def run(self, project_info: object, project_id: str, run_id: str | None = None) -> WorkflowResult:
        """Run discovery through Council-based planning only.

        This method never approves, rejects or executes setup steps.
        """

        run_id = run_id or project_id
        self._trace(run_id, "requirement_discovery", "started", "started", "Requirement discovery started")
        try:
            discovery_result = self._discovery.discover(project_info, project_id)
        except Exception as error:
            self._trace(run_id, "requirement_discovery", "failed", "failed", f"Requirement discovery failed: {type(error).__name__}")
            raise
        self._trace(run_id, "requirement_discovery", "completed", "completed", "Requirement discovery completed", details={"requirement_count": len(discovery_result.requirements), "warning_count": len(discovery_result.warnings)})

        if discovery_result.fallback_used:
            self._trace(run_id, "requirement_discovery", "blocked", "blocked", "Requirement discovery fallback blocked planning")
            raise WorkflowExecutionError(
                "Requirement discovery fallback was used; "
                "workflow planning is blocked."
            )

        self._trace(run_id, "requirement_validation", "started", "started", "Requirement validation started")
        try:
            validation_result = self._validator.validate(discovery_result.requirements)
        except Exception as error:
            self._trace(run_id, "requirement_validation", "failed", "failed", f"Requirement validation failed: {type(error).__name__}")
            raise
        self._trace(run_id, "requirement_validation", "completed", "completed", "Requirement validation completed", details={"requirement_count": len(validation_result.normalized_requirements), "warning_count": len(validation_result.warnings), "error_count": len(validation_result.errors)})

        self._trace(run_id, "preflight", "started", "started", "Requirement preflight started")
        try:
            preflight_result = self._preflight.check(validation_result.normalized_requirements, project_id)
        except Exception as error:
            self._trace(run_id, "preflight", "failed", "failed", f"Preflight failed: {type(error).__name__}")
            raise
        self._trace(run_id, "preflight", "completed", "completed", "Requirement preflight completed", details={"result_count": len(preflight_result.results), "missing_count": len(preflight_result.missing_requirements), "warning_count": len(preflight_result.warnings)})

        if self._council is None:
            raise WorkflowExecutionError(
                "No Engineering Council has been configured."
            )

        if self._materializer is None:
            raise WorkflowExecutionError(
                "No ToolchainMaterializer has been configured."
            )

        council_input = CouncilInput(
            requirements=validation_result.normalized_requirements,
            preflight=preflight_result,
            project_id=project_id,
            project_files=self._extract_project_files(project_info),
            detected_stack=self._build_detected_stack(project_info),
            project_intelligence=self._project_intelligence_from(project_info),
            validation_warnings=validation_result.warnings,
        )

        self._trace(run_id, "engineering_council", "started", "started", "Engineering Council started")
        try:
            council_result = self._council.evaluate(council_input)
        except Exception as error:
            self._trace(run_id, "engineering_council", "failed", "failed", f"Engineering Council failed: {type(error).__name__}")
            raise
        council_status = "completed" if council_result.council_complete else "incomplete"
        self._trace(run_id, "engineering_council", "completed", council_status, "Engineering Council completed", details={"variant_count": len(council_result.variants), "recommendation": council_result.recommendation or "", "council_complete": council_result.council_complete, "error_count": len(council_result.agent_errors) + bool(council_result.chairman_error)}, related_result_id=council_result.id)

        self._trace(run_id, "toolchain_materialization", "started", "started", "Toolchain materialization started")
        try:
            setup_plan = self._materializer.materialize(council_result, project_id)
        except Exception as error:
            self._trace(run_id, "toolchain_materialization", "failed", "failed", f"Toolchain materialization failed: {type(error).__name__}")
            raise
        self._trace(run_id, "toolchain_materialization", "completed", "completed", "Toolchain materialization completed", details={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)}, related_result_id=setup_plan.id)
        self._trace(run_id, "setup_plan", "completed", "completed", "Setup plan created", details={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)}, related_result_id=setup_plan.id)
        self._trace(run_id, "setup_approval", "pending", "pending", "Setup approval is pending", details={"plan_id": setup_plan.id}, related_result_id=f"setup-approval:{setup_plan.id}:pending")
        self._trace(run_id, "workflow_end", "completed", "pending", "Workflow stopped at pending setup approval", details={"end_state": "setup_approval_pending"}, related_result_id=f"workflow-end:{setup_plan.id}:pending")

        return WorkflowResult(
            discovery_result=discovery_result,
            validation_result=validation_result,
            preflight_result=preflight_result,
            council_result=council_result,
            setup_plan=setup_plan,
        )

    @staticmethod
    def _extract_project_files(project_info: object) -> tuple[str, ...]:
        """Return only explicitly supplied project file paths."""
        if not isinstance(project_info, dict):
            return ()
        # New intelligence shape: has language_names and no 'files' key
        # Old shape: direct 'files' list
        files = project_info.get("files")
        if isinstance(files, (list, tuple)):
            paths: list[str] = []
            for item in files:
                if not isinstance(item, dict):
                    continue
                if isinstance(item, dict):
                    path = item.get("path") or item.get("file", "")
                else:
                    path = str(item)
                if isinstance(path, str) and path:
                    paths.append(path)
            return tuple(paths)
        files = project_info.get("project_files") or ()
        if isinstance(files, (list, tuple)):
            return tuple(str(f) for f in files if isinstance(f, str) and f)
        return ()

    @staticmethod
    def _build_detected_stack(project_info: object) -> str:
        if not isinstance(project_info, dict):
            return ""
        parts: list[str] = []
        languages = project_info.get("languages") or ()
        if languages:
            parts.append("languages: " + ", ".join(str(l) for l in languages))
        frameworks = project_info.get("frameworks") or ()
        if frameworks:
            parts.append("frameworks: " + ", ".join(str(f) for f in frameworks))
        pkg = project_info.get("package_systems") or ()
        if pkg:
            parts.append("packages: " + ", ".join(str(p) for p in pkg))
        build = project_info.get("build_systems") or ()
        if build:
            parts.append("build: " + ", ".join(str(b) for b in build))
        test = project_info.get("test_systems") or ()
        if test:
            parts.append("tests: " + ", ".join(str(t) for t in test))
        fw = project_info.get("firmware_indicators") or ()
        if fw:
            parts.append("firmware: " + ", ".join(str(f) for f in fw))
        kind = project_info.get("project_kind") or ""
        if kind:
            parts.append(f"kind: {kind}")
        return "; ".join(parts) if parts else ""

    @staticmethod
    def _project_intelligence_from(project_info: object) -> dict | None:
        if not isinstance(project_info, dict):
            return None
        keys = (
            "project_kind", "area_count", "languages", "frameworks",
            "package_systems", "build_systems", "test_systems",
            "firmware_indicators", "truncated",
        )
        result: dict = {}
        for key in keys:
            value = project_info.get(key)
            if value is not None:
                result[key] = value
        return result if result else None

    def _validate_executable_step(self, step) -> None:
        """Reject steps that are not safe for automatic execution."""

        if step.action != "install":
            raise WorkflowExecutionError(
                f"Setup step '{step.id}' requires manual review: "
                f"action={step.action!r}."
            )

        if not step.package or not step.package.strip():
            raise WorkflowExecutionError(
                f"Setup step '{step.id}' requires manual review: "
                "no package is specified."
            )

        if not step.install_method:
            raise WorkflowExecutionError(
                f"Setup step '{step.id}' requires manual review: "
                "no install method is specified."
            )

    def execute_approved(
        self,
        plan: SetupPlan,
    ) -> tuple[ExecutionResult, ...]:
        """Execute an already approved setup plan safely."""

        if plan.status != "approved":
            raise WorkflowExecutionError(
                f"Setup plan '{plan.id}' is not approved; "
                f"current status is '{plan.status}'."
            )

        if self._executor is None:
            raise WorkflowExecutionError(
                "No setup executor has been configured."
            )

        for step in plan.steps:
            if not step.is_approved:
                raise WorkflowExecutionError(
                    f"Setup step '{step.id}' is not approved."
                )

            self._validate_executable_step(step)

        return tuple(
            self._executor.execute(step)
            for step in plan.steps
        )

    def execute_approved_and_run_development(
        self,
        plan: SetupPlan,
        development_request: object,
    ) -> SetupDevelopmentTestingResult:
        """Run development/testing only after successful approved setup."""

        controlled_rework_stage = self._controlled_rework_stage
        if controlled_rework_stage is None and self._development_testing_stage is not None:
            controlled_rework_stage = ControlledReworkStage(
                self._development_testing_stage,
            )
        if controlled_rework_stage is None:
            raise WorkflowExecutionError(
                "No DevelopmentTestingStage has been configured."
            )

        run_id = getattr(development_request, "run_id", None) or plan.id
        self._trace(run_id, "setup_approval", "approved", "approved", "Setup approval granted", details={"plan_id": plan.id}, related_result_id=f"setup-approval:{plan.id}:approved")
        self._trace(run_id, "setup_execution", "started", "started", "Setup execution started", details={"step_count": len(plan.steps)})
        try:
            setup_execution_results = self.execute_approved(plan)
        except Exception as error:
            self._trace(run_id, "setup_execution", "failed", "failed", f"Setup execution failed: {type(error).__name__}")
            raise
        if not all(result.success for result in setup_execution_results):
            self._trace(run_id, "setup_execution", "failed", "failed", "Setup execution returned unsuccessful results", details={"result_count": len(setup_execution_results)})
            raise WorkflowExecutionError(
                "Setup execution did not complete successfully."
            )
        self._trace(run_id, "setup_execution", "completed", "completed", "Setup execution completed", details={"result_count": len(setup_execution_results)})

        controlled_rework_result = controlled_rework_stage.run(development_request)
        self._trace_development_cycles(run_id, controlled_rework_result)
        return SetupDevelopmentTestingResult(
            setup_execution_results=setup_execution_results,
            controlled_rework_result=controlled_rework_result,
        )

    def _trace_development_cycles(self, run_id, result):
        initial_result = getattr(result, "initial_result", None)
        rework_result = getattr(result, "rework_result", None)
        if initial_result is None:
            initial_result = getattr(result, "final_result", None)

        cycles = []
        if initial_result is not None:
            cycles.append(("initial", initial_result))
        if rework_result is not None and rework_result is not initial_result:
            cycles.append(("rework", rework_result))

        for index, (cycle, item) in enumerate(cycles):
            if index:
                self._trace(run_id, "controlled_rework", "rework_required", "rework_required", "Controlled rework was requested", details={"rework_executed": True}, related_result_id=f"rework:{run_id}:requested")
                self._trace(run_id, "controlled_rework", "started", "started", "Controlled rework cycle started", details={"cycle": cycle})
            development = getattr(item, "development_result", None)
            self._trace(run_id, "development", "started", "started", f"Development cycle started: {cycle}", details={"cycle": cycle})
            development_status = getattr(development, "status", None)
            development_succeeded = development_status == "success"
            development_details = {"cycle": cycle}
            applied = getattr(development, "applied_changes", None)
            if isinstance(applied, dict):
                applied_paths = applied.get("applied")
                skipped_paths = applied.get("skipped")
                if isinstance(applied_paths, (list, tuple)):
                    development_details["applied_path_count"] = len(applied_paths)
                if isinstance(skipped_paths, (list, tuple)):
                    development_details["skipped_path_count"] = len(skipped_paths)
            development_event = "completed" if development_succeeded else "failed"
            development_trace_status = development_event
            if not isinstance(development_status, str):
                development_event = "completed"
                development_trace_status = "incomplete"
            self._trace(run_id, "development", development_event, development_trace_status, f"Development cycle finished: {cycle}", details=development_details)

            changes = getattr(item, "test_changes", None)
            self._trace(run_id, "test_generation", "started", "started", f"Test generation started: {cycle}", details={"cycle": cycle})
            test_generation_details = {"cycle": cycle}
            if isinstance(changes, dict) and isinstance(changes.get("changes"), (list, tuple)):
                test_generation_details["controlled_path_count"] = len(changes["changes"])
            self._trace(run_id, "test_generation", "completed", "completed", f"Test generation completed: {cycle}", details=test_generation_details)

            provenance_details = {"cycle": cycle}
            applied_result = getattr(item, "apply_result", None)
            controlled_path_count = 0
            path_count_available = False
            for candidate in (applied, applied_result):
                if isinstance(candidate, dict) and isinstance(candidate.get("applied"), (list, tuple)):
                    controlled_path_count += len(candidate["applied"])
                    path_count_available = True
            if path_count_available:
                provenance_details["controlled_path_count"] = controlled_path_count
            self._trace(run_id, "change_provenance", "completed", "completed", f"Change provenance captured: {cycle}", details=provenance_details)

            test_result = getattr(item, "test_result", None)
            self._trace(run_id, "testing", "started", "started", f"Controlled testing started: {cycle}", details={"cycle": cycle, "runner": type(test_result).__name__})
            timed_out = getattr(test_result, "timed_out", None) is True
            passed = getattr(test_result, "passed", None) is True
            test_type = "timeout" if timed_out else "completed"
            test_status = "timeout" if timed_out else ("passed" if passed else "failed")
            testing_details = {"cycle": cycle}
            if isinstance(getattr(test_result, "timed_out", None), bool):
                testing_details["timed_out"] = timed_out
            if isinstance(getattr(test_result, "passed", None), bool):
                testing_details["passed"] = passed
            return_code = getattr(test_result, "return_code", None)
            if isinstance(return_code, int):
                testing_details["return_code"] = return_code
            if not any(key in testing_details for key in ("timed_out", "passed", "return_code")):
                test_status = "incomplete"
            self._trace(run_id, "testing", test_type, test_status, f"Controlled testing finished: {cycle}", details=testing_details)
            testing_stage_result = getattr(item, "testing_stage_result", None)
            decision = getattr(testing_stage_result, "status", None)
            if not isinstance(decision, str):
                decision = getattr(item, "status", "incomplete")
            if not isinstance(decision, str):
                decision = "incomplete"
            decision_type = decision if decision in {"rework_required", "failed"} else "completed"
            self._trace(run_id, "diagnosis_review", decision_type, decision, f"Diagnosis review finished: {decision}", details={"cycle": cycle})
            if index:
                self._trace(run_id, "controlled_rework", "completed", "completed", "Controlled rework cycle completed", details={"cycle": cycle})
