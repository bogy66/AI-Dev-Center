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
from app.execution import is_controlled_setup_effect
from app.execution_identity import execution_identity


class WorkflowExecutionError(Exception):
    """Raised when the workflow cannot continue safely."""


class WorkflowBlockedError(WorkflowExecutionError):
    """Raised after central policy intentionally records a blocked outcome."""

    def __init__(self, safe_reason: str):
        super().__init__(safe_reason)
        self.safe_reason = safe_reason


@dataclass(frozen=True)
class WorkflowResult:
    """Immutable result of discovery through Council-based planning."""

    discovery_result: DiscoveryResult
    validation_result: ValidationResult
    preflight_result: PreflightResult
    council_result: CouncilResult
    setup_plan: SetupPlan
    project_context: object | None = None


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

    def materialize_setup_plan(
        self, council_result: CouncilResult, project_id: str,
        preflight: PreflightResult | None = None,
    ) -> SetupPlan:
        """Provide the workflow-owned Council-to-SetupPlan boundary."""
        if self._materializer is None:
            raise WorkflowExecutionError("No toolchain materializer has been configured.")
        return self._materializer.materialize(council_result, project_id, preflight=preflight)

    def _trace(self, run_id, phase, event_type, status, summary, **kwargs):
        if self._diagnostic_trace is not None:
            try:
                self._diagnostic_trace.record(
                    run_id, phase, event_type, status, summary,
                    source="development_workflow", **kwargs,
                )
            except DiagnosticTraceError:
                return None

    @staticmethod
    def _requirement_view(requirement, *, fullest=False, activation=None):
        view = {
            "id": requirement.id, "name": requirement.name,
            "type": requirement.type, "purpose": requirement.purpose,
            "required": requirement.required,
            "status": getattr(requirement.status, "value", requirement.status),
        }
        if activation is not None:
            view["state"] = activation.state
        if fullest:
            view.update({
                "confidence": requirement.confidence,
                "required_version": requirement.required_version,
                "evidence_count": len(requirement.evidence),
            })
        return view

    def _discovery_identity(self):
        provider = getattr(self._discovery, "_provider", None)
        return execution_identity(
            "requirement_discovery",
            provider=type(provider).__name__ if provider is not None else None,
            model=getattr(self._discovery, "_ai_model", None),
        )

    def _interface(
        self, run_id, phase, summary, *, info_x, info_y,
        verbose_x=None, verbose_y=None, very_verbose_x=None,
        very_verbose_y=None, upstream_stage=None, downstream_stage=None,
        status="completed", identity=None, x_type="structured_input",
        y_type="structured_output", interface="internal",
    ):
        def typed(data, data_type, source, destination):
            return {
                "type": data_type, "interface": interface,
                "source": source or "unavailable",
                "destination": destination or "unavailable", "data": data,
            }
        processor = identity or execution_identity(phase)
        source = upstream_stage or "unavailable"
        destination = downstream_stage or "unavailable"
        self._trace(
            run_id, phase, "completed" if status == "completed" else "failed",
            status, summary,
            details={
                "diagnostic_level": "NORMAL", "result_kind": "interface",
                "interface_stage": phase, "upstream_stage": upstream_stage or "",
                "downstream_stage": downstream_stage or "",
                "interface_data": {
                    "normal": {"summary": summary, "f": processor},
                    "info": {"x": typed(info_x, x_type, source, phase),
                             "f": processor,
                             "y": typed(info_y, y_type, phase, destination)},
                    "verbose": {
                        "x": typed(verbose_x if verbose_x is not None else info_x,
                                   x_type, source, phase),
                        "f": processor,
                        "y": typed(verbose_y if verbose_y is not None else info_y,
                                   y_type, phase, destination),
                    },
                    "very_verbose": {
                        "x": typed(very_verbose_x if very_verbose_x is not None else (
                            verbose_x if verbose_x is not None else info_x
                        ), x_type, source, phase),
                        "f": processor,
                        "y": typed(very_verbose_y if very_verbose_y is not None else (
                            verbose_y if verbose_y is not None else info_y
                        ), y_type, phase, destination),
                    },
                },
            },
        )

    def run(
        self, project_info: object, project_id: str, run_id: str | None = None,
        project_context: object | None = None,
        user_request: str | None = None, source_interface: str | None = None,
    ) -> WorkflowResult:
        """Run discovery through Council-based planning only.

        This method never approves, rejects or executes setup steps.
        """

        run_id = run_id or project_id
        self._trace(run_id, "requirement_discovery", "started", "started", "Requirement discovery started")
        discovery_input = self._project_intelligence_from(project_info) or {}
        discovery_input = {
            "project": discovery_input,
            "user_request_present": bool(user_request),
            "user_request": user_request or "not available at this boundary",
        }
        set_discovery_activity = getattr(self._discovery, "set_activity_callback", None)
        if callable(set_discovery_activity):
            def record_discovery_activity(**activity):
                runtime_state = activity.get("runtime_state", "working")
                event_type = "failed" if runtime_state == "failed" else (
                    "completed" if runtime_state == "completed" else "started"
                )
                self._trace(
                    run_id, "requirement_discovery", event_type, event_type,
                    f"Requirement discovery provider {runtime_state}",
                    details=activity,
                )
            set_discovery_activity(record_discovery_activity)
        try:
            if user_request:
                discovery_result = self._discovery.discover(
                    project_info, project_id, user_request=user_request,
                )
            else:
                discovery_result = self._discovery.discover(project_info, project_id)
        except Exception as error:
            self._trace(run_id, "requirement_discovery", "failed", "failed", f"Requirement discovery failed: {type(error).__name__}")
            self._interface(
                run_id, "requirement_discovery", "Requirement Discovery produced no structured output",
                info_x={"user_request_present": bool(user_request)},
                info_y={"available": False, "error_category": type(error).__name__},
                verbose_x=discovery_input,
                verbose_y={"available": False, "error_category": type(error).__name__},
                upstream_stage="project_inspection", downstream_stage="requirement_validation",
                status="failed",
                identity=self._discovery_identity(),
                x_type="project_intelligence", y_type="requirement_set",
            )
            raise
        self._trace(run_id, "requirement_discovery", "completed", "completed" if not discovery_result.fallback_used else "blocked", "Requirement discovery completed", details={"requirement_count": len(discovery_result.requirements), "warning_count": len(discovery_result.warnings)})
        discovery_activation_by_id = {
            activation.requirement_id: activation
            for activation in discovery_result.activations
        }
        discovery_output = [
            self._requirement_view(
                requirement,
                activation=discovery_activation_by_id.get(requirement.id),
            )
            for requirement in discovery_result.requirements
        ]
        very_verbose_x = dict(discovery_input)
        discovery_effective_prompt = getattr(self._discovery, "effective_prompt", None)
        if discovery_effective_prompt:
            very_verbose_x["effective_prompt"] = discovery_effective_prompt
        discovery_repair_prompt = getattr(self._discovery, "effective_repair_prompt", None)
        if discovery_repair_prompt:
            very_verbose_x["effective_repair_prompt"] = discovery_repair_prompt
        self._interface(
            run_id, "requirement_discovery", "Requirement Discovery transformed project facts into requirements",
            info_x={"user_request_present": bool(user_request), "project_kind": discovery_input["project"].get("project_kind", "")},
            info_y={"requirement_count": len(discovery_output), "warning_count": len(discovery_result.warnings)},
            verbose_x=discovery_input,
            verbose_y={"requirements": discovery_output, "warnings": list(discovery_result.warnings)},
            very_verbose_x=very_verbose_x,
            very_verbose_y={"requirements": [self._requirement_view(item, fullest=True, activation=discovery_activation_by_id.get(item.id)) for item in discovery_result.requirements], "warnings": list(discovery_result.warnings)},
            upstream_stage="project_inspection", downstream_stage="requirement_validation",
            status="failed" if discovery_result.fallback_used else "completed",
            identity=self._discovery_identity(),
            x_type="project_intelligence", y_type="requirement_set",
        )

        if discovery_result.fallback_used:
            self._trace(run_id, "requirement_discovery", "blocked", "blocked", "Requirement discovery fallback blocked planning")
            raise WorkflowBlockedError(
                "Requirement discovery could not produce a valid structured result; planning was blocked."
            )

        self._trace(run_id, "requirement_validation", "started", "started", "Requirement validation started")
        try:
            validation_result = self._validator.validate(
                discovery_result.requirements, discovery_result.activations,
            )
        except Exception as error:
            self._trace(run_id, "requirement_validation", "failed", "failed", f"Requirement validation failed: {type(error).__name__}")
            self._interface(
                run_id, "requirement_validation", "Requirement Validation produced no structured output",
                info_x={"requirement_count": len(discovery_output)},
                info_y={"available": False, "error_category": type(error).__name__},
                verbose_x={"requirements": discovery_output},
                verbose_y={"available": False, "error_category": type(error).__name__},
                upstream_stage="requirement_discovery", downstream_stage="preflight",
                status="failed",
                identity=execution_identity("requirement_validation"),
                x_type="requirement_set", y_type="validation_result",
            )
            raise
        validation_activation_by_id = {
            activation.requirement_id: activation
            for activation in validation_result.activations
        }
        self._trace(run_id, "requirement_validation", "completed", "completed", "Requirement validation completed", details={"requirement_count": len(validation_result.normalized_requirements), "warning_count": len(validation_result.warnings), "error_count": len(validation_result.errors)})
        self._interface(
            run_id, "requirement_validation", "Requirement Validation transformed discovered requirements",
            info_x={"requirement_count": len(discovery_result.requirements)},
            info_y={"valid": validation_result.valid, "requirement_count": len(validation_result.normalized_requirements), "warning_count": len(validation_result.warnings), "error_count": len(validation_result.errors)},
            verbose_x={"requirements": discovery_output},
            verbose_y={"valid": validation_result.valid, "normalized_requirements": [self._requirement_view(item, activation=validation_activation_by_id.get(item.id)) for item in validation_result.normalized_requirements], "warning_count": len(validation_result.warnings), "error_count": len(validation_result.errors)},
            very_verbose_x={"requirements": [self._requirement_view(item, fullest=True, activation=discovery_activation_by_id.get(item.id)) for item in discovery_result.requirements]},
            very_verbose_y={"valid": validation_result.valid, "normalized_requirements": [self._requirement_view(item, fullest=True, activation=validation_activation_by_id.get(item.id)) for item in validation_result.normalized_requirements], "warning_count": len(validation_result.warnings), "error_count": len(validation_result.errors)},
            upstream_stage="requirement_discovery", downstream_stage="preflight",
            identity=execution_identity("requirement_validation"),
            x_type="requirement_set", y_type="validation_result",
        )

        self._trace(run_id, "preflight", "started", "started", "Requirement preflight started")
        try:
            preflight_result = self._preflight.check(
                validation_result.normalized_requirements,
                project_id,
                validation_result.activations,
            )
        except Exception as error:
            self._trace(run_id, "preflight", "failed", "failed", f"Preflight failed: {type(error).__name__}")
            normalized = [
                self._requirement_view(item)
                for item in validation_result.normalized_requirements
            ]
            self._interface(
                run_id, "preflight", "Preflight produced no structured output",
                info_x={"requirement_count": len(normalized)},
                info_y={"available": False, "error_category": type(error).__name__},
                verbose_x={"requirements": normalized},
                verbose_y={"available": False, "error_category": type(error).__name__},
                upstream_stage="requirement_validation", downstream_stage="engineering_council",
                status="failed",
                identity=execution_identity("preflight"),
                x_type="requirement_set", y_type="preflight_result",
            )
            raise
        self._trace(run_id, "preflight", "completed", "completed", "Requirement preflight completed", details={"result_count": len(preflight_result.results), "missing_count": len(preflight_result.missing_requirements), "warning_count": len(preflight_result.warnings)})
        preflight_rows = [{
            "requirement_id": item.requirement_id, "present": item.present,
            "satisfied": item.satisfied, "detected_version": item.detected_version,
            "state": (
                "inactive" if not item.active else
                "active_blocker" if item.blocks_current_operation else
                "active_non_blocking"
            ),
        } for item in preflight_result.results]
        self._interface(
            run_id, "preflight", "Preflight checked validated requirements",
            info_x={"requirement_count": len(validation_result.normalized_requirements)},
            info_y={"overall_ready": preflight_result.overall_ready, "result_count": len(preflight_rows), "missing_count": len(preflight_result.missing_requirements)},
            verbose_x={"requirements": [self._requirement_view(item) for item in validation_result.normalized_requirements]},
            verbose_y={"overall_ready": preflight_result.overall_ready, "preflight_results": preflight_rows, "missing_requirements": [self._requirement_view(item) for item in preflight_result.missing_requirements]},
            upstream_stage="requirement_validation", downstream_stage="engineering_council",
            identity=execution_identity("preflight"),
            x_type="requirement_set", y_type="preflight_result",
        )

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
            requirement_activations=validation_result.activations,
        )

        self._trace(run_id, "engineering_council", "started", "started", "Engineering Council started")
        set_activity_callback = getattr(self._council, "set_activity_callback", None)
        if callable(set_activity_callback):
            def record_council_activity(**activity):
                runtime_state = activity.get("runtime_state", "working")
                event_type = "failed" if runtime_state == "failed" else (
                    "completed" if runtime_state == "completed" else "started"
                )
                status = event_type
                actor = activity.get("actor", "Council")
                self._trace(
                    run_id, "engineering_council", event_type, status,
                    f"{actor} {runtime_state}", details=activity,
                )
            set_activity_callback(record_council_activity)
        set_result_callback = getattr(self._council, "set_result_callback", None)
        if callable(set_result_callback):
            def record_council_result(**result):
                summary = result.pop("summary", "Council structured result")
                self._trace(
                    run_id, "engineering_council", "completed", "completed",
                    summary,
                    details={"diagnostic_level": "NORMAL", **result},
                )
            set_result_callback(record_council_result)
        try:
            council_result = self._council.evaluate(council_input)
        except Exception as error:
            self._trace(run_id, "engineering_council", "failed", "failed", f"Engineering Council failed: {type(error).__name__}")
            council_failure_x = {
                "project_id": council_input.project_id,
                "stack": council_input.detected_stack,
                "requirements": [
                    self._requirement_view(item) for item in council_input.requirements
                ],
                "project_files": list(council_input.project_files),
                "validation_warnings": list(council_input.validation_warnings),
            }
            self._interface(
                run_id, "engineering_council", "Engineering Council produced no CouncilResult",
                info_x={"requirement_count": len(council_input.requirements)},
                info_y={"available": False, "error_category": type(error).__name__},
                verbose_x=council_failure_x,
                verbose_y={"available": False, "error_category": type(error).__name__},
                upstream_stage="preflight", downstream_stage="toolchain_materialization",
                status="failed",
                identity=execution_identity("engineering_council"),
                x_type="council_input", y_type="council_result",
            )
            raise
        council_status = "completed" if council_result.council_complete else "incomplete"
        self._trace(
            run_id,
            "engineering_council",
            "completed",
            council_status,
            "Engineering Council completed",
            details={
                "variant_count": len(council_result.variants),
                "recommendation": council_result.recommendation or "",
                "council_complete": council_result.council_complete,
                "council_degraded": council_result.council_degraded,
                "error_count": (
                    len(council_result.agent_errors)
                    + bool(council_result.chairman_error)
                ),
            },
            related_result_id=council_result.id,
        )
        council_x = {
            "project_id": council_input.project_id,
            "stack": council_input.detected_stack,
            "requirements": [self._requirement_view(item) for item in council_input.requirements],
            "project_files": list(council_input.project_files),
            "validation_warnings": list(council_input.validation_warnings),
        }
        council_y = {
            "result_id": council_result.id,
            "council_complete": council_result.council_complete,
            "council_degraded": council_result.council_degraded,
            "recommendation": council_result.recommendation,
            "variant_ids": [item.id for item in council_result.variants],
            "error_count": len(council_result.agent_errors) + bool(council_result.chairman_error),
        }
        self._interface(
            run_id, "engineering_council", "Engineering Council transformed CouncilInput into CouncilResult",
            info_x={"requirement_count": len(council_input.requirements), "stack": council_input.detected_stack or ""},
            info_y={"proposal_count": len(council_result.variants), "council_complete": council_result.council_complete, "council_degraded": council_result.council_degraded, "recommendation": council_result.recommendation},
            verbose_x=council_x, verbose_y=council_y,
            very_verbose_x={**council_x, "requirements": [self._requirement_view(item, fullest=True) for item in council_input.requirements]},
            very_verbose_y={**council_y, "total_llm_calls": council_result.total_llm_calls},
            upstream_stage="preflight", downstream_stage="toolchain_materialization",
            status="completed" if council_result.council_complete else "failed",
            identity=execution_identity("engineering_council"),
            x_type="council_input", y_type="council_result",
        )

        if not council_result.council_complete:
            self._trace(
                run_id, "engineering_council", "blocked", "blocked",
                "Incomplete Engineering Council result blocked planning",
                details={"council_complete": False},
                related_result_id=f"{council_result.id}:incomplete",
            )
            self._trace(
                run_id, "workflow_end", "blocked", "blocked",
                "Workflow stopped at incomplete Engineering Council result",
                details={"end_state": "engineering_council_incomplete"},
                related_result_id=f"workflow-end:{council_result.id}:incomplete",
            )
            raise WorkflowBlockedError(
                "Engineering Council did not reach a complete decision; planning was blocked."
            )

        self._trace(run_id, "toolchain_materialization", "started", "started", "Toolchain materialization started")
        try:
            setup_plan = self._materializer.materialize(council_result, project_id, preflight=preflight_result)
        except Exception as error:
            self._trace(run_id, "toolchain_materialization", "failed", "failed", f"Toolchain materialization failed: {type(error).__name__}")
            self._interface(
                run_id, "toolchain_materialization", "Toolchain Materializer produced no SetupPlan",
                info_x={"result_id": council_result.id},
                info_y={"available": False, "error_category": type(error).__name__},
                upstream_stage="engineering_council", downstream_stage="setup_plan",
                status="failed", identity=execution_identity("toolchain_materializer"),
                x_type="council_result", y_type="setup_plan",
            )
            raise
        self._trace(run_id, "toolchain_materialization", "completed", "completed", "Toolchain materialization completed", details={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)}, related_result_id=setup_plan.id)
        self._interface(
            run_id, "toolchain_materialization", "Toolchain Materializer transformed CouncilResult into SetupPlan",
            info_x={"result_id": council_result.id},
            info_y={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)},
            verbose_x={"result_id": council_result.id,
                       "recommendation": council_result.recommendation,
                       "council_complete": council_result.council_complete,
                       "council_degraded": council_result.council_degraded},
            verbose_y={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)},
            upstream_stage="engineering_council", downstream_stage="setup_plan",
            identity=execution_identity("toolchain_materializer"),
            x_type="council_result", y_type="setup_plan",
        )
        self._trace(run_id, "setup_plan", "completed", "completed", "Setup plan created", details={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)}, related_result_id=setup_plan.id)
        self._trace(run_id, "setup_approval", "pending", "pending", "Setup approval is pending", details={"plan_id": setup_plan.id}, related_result_id=f"setup-approval:{setup_plan.id}:pending")
        self._trace(run_id, "workflow_end", "completed", "pending", "Workflow stopped at pending setup approval", details={"end_state": "setup_approval_pending"}, related_result_id=f"workflow-end:{setup_plan.id}:pending")

        return WorkflowResult(
            discovery_result=discovery_result,
            validation_result=validation_result,
            preflight_result=preflight_result,
            council_result=council_result,
            setup_plan=setup_plan,
            project_context=project_context,
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

    def _validate_executable_step(self, step, plan: SetupPlan | None = None) -> None:
        """Reject steps that are not safe for automatic execution.

        A step whose requirement is inactive or nonblocking is skipped,
        not rejected — its requirement remains represented in the plan but
        does not block controlled execution of unrelated setup work.
        """
        if plan is not None and plan.requirement_activations:
            activation_by_id = {
                activation.requirement_id: activation
                for activation in plan.requirement_activations
            }
            activation = activation_by_id.get(step.requirement_id)
            if activation is not None and not activation.blocks_current_operation:
                return

        effect = step.setup_effect

        if effect is not None and is_controlled_setup_effect(effect):
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
            return

        if effect is not None and not is_controlled_setup_effect(effect):
            raise WorkflowExecutionError(
                f"Setup step '{step.id}' requires setup effect '{effect}' "
                f"for which ADC has no controlled execution backend."
            )

        raise WorkflowExecutionError(
            f"Setup step '{step.id}' requires manual review: "
            f"no structured setup effect is defined "
            f"(action={step.action!r})."
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

        activation_by_id = {}
        if plan.requirement_activations:
            activation_by_id = {
                activation.requirement_id: activation
                for activation in plan.requirement_activations
            }

        executable_steps: list[SetupStep] = []
        for step in plan.steps:
            activation = activation_by_id.get(step.requirement_id)
            if activation is not None and not activation.blocks_current_operation:
                continue
            if not step.is_approved:
                raise WorkflowExecutionError(
                    f"Setup step '{step.id}' is not approved."
                )
            self._validate_executable_step(step, plan)
            executable_steps.append(step)

        return tuple(
            self._executor.execute(step)
            for step in executable_steps
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
