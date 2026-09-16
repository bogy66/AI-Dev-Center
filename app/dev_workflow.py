"""Development workflow with Council planning and explicit approved execution."""

from __future__ import annotations

from dataclasses import dataclass

from app.ai_requirement_discovery import AIRequirementDiscovery
from app.council_models import CouncilInput, CouncilResult
from app.engineering_council import EngineeringCouncil
from app.python_distribution import is_valid_distribution_identifier
from app.requirement_model import (
    DiscoveryResult,
    RequirementType,
    PreflightResult,
    SetupPlan,
    ValidationResult,
)
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_executor import ExecutionResult, SetupExecutor
from app.setup_planner import SetupPlanner
from app.toolchain_materializer import ToolchainMaterializer
from app.verification import all_trusted_verification_groups
from app.engineering_decision import (
    CandidateValidation,
    EngineeringVariantSelection,
    admissible_variants,
    binding_materializer_diagnostics,
    describe_engineering_variant_selection,
    resolve_human_engineering_selection,
    select_engineering_variant,
    validate_candidates,
)
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
    """Immutable result of discovery through Council-based planning.

    CLAUDE-ARCH-S2-013C: run() now stops at the productive S2.4 Human
    Engineering Authority boundary whenever S2.3 found at least one
    admissible candidate -- `setup_plan` is None and
    `engineering_selection` (a display-only, non-binding
    EngineeringVariantSelection -- see app.engineering_decision) is set
    instead. Only an explicit call to
    DevelopmentWorkflow.resolve_engineering_selection() -- never run()
    itself -- may produce a populated `setup_plan`; that resumed
    WorkflowResult carries `engineering_selection=None` and (since the
    discovery/validation stages already ran before the pause and are not
    part of the state that survives it) `discovery_result=None`,
    `validation_result=None`.
    """

    discovery_result: DiscoveryResult | None
    validation_result: ValidationResult | None
    preflight_result: PreflightResult
    council_result: CouncilResult
    setup_plan: SetupPlan | None = None
    engineering_selection: "EngineeringVariantSelection | None" = None
    platform: str | None = None
    project_context: object | None = None
    # CLAUDE-ARCH-S2-013G: the raw ProjectIntelligence run() itself always
    # computes (independent of whether a full ProjectContext could be
    # composed -- see run()'s own docstring) -- the independent, ADC-owned
    # evidence S2.3 Verification Feasibility's mechanism-compatibility
    # check needs so a candidate's own provides_verification declaration
    # can never be the last word (see app.verification.
    # all_trusted_verification_groups()). Carried across the S2.4
    # pause the same way preflight_result/platform already are.
    project_intelligence: object | None = None


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
        execution_state_store: object | None = None,
    ) -> None:
        self._discovery = discovery
        self._validator = validator
        self._preflight = preflight

        # Transitional constructor compatibility only. `planner` (if
        # supplied) carries NO productive planning authority: it is
        # stored and never read back anywhere in this class. The
        # canonical S3.1 Setup Planning path is exclusively
        # materialize_setup_plan() below, via the configured
        # ToolchainMaterializer -- SetupPlanner never re-enters the
        # canonical path through this parameter or otherwise.
        self._planner = planner

        self._executor = executor
        self._council = council
        self._materializer = materializer
        self._development_testing_stage = development_testing_stage
        self._controlled_rework_stage = controlled_rework_stage
        self._diagnostic_trace = diagnostic_trace
        # Optional, additive (CLAUDE-E2E-003H): when supplied (always
        # true in real productive composition -- see
        # canonical_composition.py and mcp_transport.py), each SetupStep
        # execution is guarded by a persisted, project/plan/step-scoped
        # execution-state record instead of being launched unconditionally
        # every time execute_approved() runs. Omitted, execute_approved()
        # behaves exactly as it did before this task -- existing direct
        # unit-test callers that do not need retry-safety are unaffected.
        self._execution_state_store = execution_state_store

    def set_diagnostic_trace(self, diagnostic_trace) -> None:
        self._diagnostic_trace = diagnostic_trace

    def materialize_setup_plan(
        self, council_result: CouncilResult, project_id: str,
        preflight: PreflightResult | None = None,
        platform: str | None = None,
        project_root: str | None = None,
    ) -> SetupPlan:
        """Provide the workflow-owned Council-to-SetupPlan boundary.

        CLAUDE-PRE-E2E-009C: platform defaults to None (unchanged prior
        behaviour -- no platform Constraint enforcement) so every existing
        caller keeps working unmodified; a caller that has a platform to
        supply (e.g. a future MissingToolchainSetupRequest.platform) can
        now have it enforced here too, the same way the productive
        run()-owned materialize() call already does.

        `project_root` (CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-
        BINDING-FIX-003): optional and additive, forwarded unchanged to
        ToolchainMaterializer.materialize() -- see its own docstring.
        """
        if self._materializer is None:
            raise WorkflowExecutionError("No toolchain materializer has been configured.")
        return self._materializer.materialize(
            council_result, project_id, preflight=preflight, platform=platform,
            project_root=project_root,
        )

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
        if requirement.type == RequirementType.PYTHON_PACKAGE:
            identity = requirement.technical_identity
            view.update({
                "technical_identity_present": identity is not None,
                "technical_identity_python_type": type(identity).__name__,
                "technical_identity_valid": is_valid_distribution_identifier(identity),
            })
            if is_valid_distribution_identifier(identity):
                view["safe_identifier"] = identity
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
        project_intelligence: object | None = None,
    ) -> WorkflowResult:
        """Run discovery through Council-based planning only.

        This method never approves, rejects or executes setup steps.

        `project_intelligence` (CLAUDE-ARCH-S2-013G): the real
        ProjectIntelligence the caller's own inspection pass already
        computed -- passed separately from `project_context` because a
        ProjectContext is only composed when technical_config is
        available, while ProjectIntelligence itself is always available.
        Threaded, unmodified, into S2.3 Verification Feasibility's
        mechanism-compatibility check (validate_candidates()) so a
        candidate's own provides_verification declaration is never
        accepted on its own say-so.
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
                project_root=(
                    project_context.project_root if project_context is not None else None
                ),
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

        # CLAUDE-ARCH-S2-013C: closes CLAUDE-ARCH-S2-013A's CRITICAL
        # finding. run() previously called select_engineering_variant()
        # (which silently treats an admissible Chairman recommendation as
        # the final selection, authority="chairman", whenever no explicit
        # human_selected_variant_id is given) and materialize_decision()
        # in the SAME synchronous call -- there was no productive human
        # engineering-selection boundary at all. run() now ONLY ever
        # determines S2.3 admissibility (never S2.4 selection, never S2.5,
        # never S3) and, whenever at least one candidate is admissible,
        # STOPS here and returns a display-only EngineeringVariantSelection
        # (S2.4's own describe_engineering_variant_selection(), never a
        # duplicated notion of admissibility/authority). Only an explicit,
        # separate call to resolve_engineering_selection() -- always given
        # a real human_selected_variant_id -- may proceed to S2.4's actual
        # authority resolution, S2.5 and S3. A genuine dead end (ZERO
        # admissible candidates) is still a terminal failure here: there is
        # nothing for a human to decide between, so the existing
        # NoEligibleEngineeringCandidateError (S2.3/S2.4's own, never
        # duplicated) is still raised immediately, preserving the exact
        # per-candidate evidence CLAUDE-E2E-NIO-010A already established.
        self._trace(run_id, "toolchain_materialization", "started", "started", "Toolchain materialization started")
        platform = council_input.platform
        trusted_verification_groups = all_trusted_verification_groups(project_intelligence)
        # CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004: the
        # SAME project_root expression already used above for Preflight
        # (project_context is only composed when technical_config is
        # available) -- threaded into S2.3 admissibility so its pip_show
        # verification-capability check can determine whether a "venv"
        # candidate has an actual, resolvable target before it is ever
        # exposed as admissible, exactly like materialization itself will
        # later require.
        run_project_root = (
            project_context.project_root if project_context is not None else None
        )
        try:
            validations = validate_candidates(
                council_result, preflight_result, platform, trusted_verification_groups,
                project_root=run_project_root,
            )
            # CLAUDE-ADC-S23-MATERIALIZER-DIAGNOSTICS-001: purely
            # observational -- computed from, but never fed back into,
            # `validations` above, and emitted regardless of whether the
            # admissibility check below ends up raising. Never changes
            # which candidates are admissible or which SetupPlan gets
            # produced later.
            for candidate_validation in validations:
                for item_diagnostic in binding_materializer_diagnostics(
                    candidate_validation.variant, preflight_result,
                ):
                    item_facts = {
                        key: item_diagnostic[key] for key in (
                            "variant_id", "requirement_ref", "type", "name",
                            "technical_identity_present", "technical_identity_python_type",
                            "technical_identity_check_applicable", "technical_identity_valid",
                            "name_valid_as_identifier", "install_method_python_type",
                        )
                    }
                    materializer_result = {
                        key: item_diagnostic[key] for key in (
                            "safe_identifier", "install_method_classification",
                            "install_method_compatible", "materializer_action",
                            "materializer_rejection_category",
                        )
                    }
                    self._interface(
                        run_id, "toolchain_materialization",
                        "S2.3 materializer diagnostic for a binding toolchain item",
                        info_x={
                            "variant_id": item_diagnostic["variant_id"],
                            "requirement_ref": item_diagnostic["requirement_ref"],
                        },
                        info_y={
                            "materializer_action": item_diagnostic["materializer_action"],
                            "materializer_rejection_category": item_diagnostic["materializer_rejection_category"],
                        },
                        verbose_x=item_facts,
                        verbose_y=materializer_result,
                        upstream_stage="engineering_council", downstream_stage="setup_plan",
                        status="completed", identity=execution_identity("toolchain_materializer"),
                        x_type="toolchain_item", y_type="materializer_binding_diagnostic",
                    )
            if not admissible_variants(validations):
                resolve_human_engineering_selection(validations)
        except Exception as error:
            evidence = getattr(error, "validations", None) or getattr(error, "rejected", None)
            details = {"failure_summary": str(error)[:3000]} if evidence else {}
            self._trace(run_id, "toolchain_materialization", "failed", "failed", f"Toolchain materialization failed: {type(error).__name__}", details=details)
            self._interface(
                run_id, "toolchain_materialization", "Toolchain Materializer produced no SetupPlan",
                info_x={"result_id": council_result.id},
                info_y={"available": False, "error_category": type(error).__name__},
                upstream_stage="engineering_council", downstream_stage="setup_plan",
                status="failed", identity=execution_identity("toolchain_materializer"),
                x_type="council_result", y_type="setup_plan",
            )
            raise

        selection = describe_engineering_variant_selection(
            council_result, preflight_result, platform,
            chairman_recommendation=council_result.recommendation,
            trusted_verification_groups=trusted_verification_groups,
            project_root=run_project_root,
        )
        admissible_ids = [v.variant.id for v in validations if v.admissible]
        self._trace(
            run_id, "human_engineering_authority", "pending", "pending",
            "Human engineering selection is pending", details={
                "recommendation": council_result.recommendation,
                "admissible_variant_ids": admissible_ids,
            },
            related_result_id=f"human-engineering-authority:{council_result.id}:pending",
        )
        self._interface(
            run_id, "human_engineering_authority",
            "S2.3 exposed the Chairman recommendation and admissible alternatives for human decision",
            info_x={"result_id": council_result.id, "recommendation": council_result.recommendation},
            info_y={"admissible_variant_ids": admissible_ids},
            verbose_x={"result_id": council_result.id, "recommendation": council_result.recommendation,
                       "variant_ids": [v.id for v in council_result.variants]},
            verbose_y={"recommendation": self._variant_presentation(
                next(v for v in validations if v.variant.id == council_result.recommendation)
            ) if council_result.recommendation in {v.variant.id for v in validations} else None,
                       "alternatives": [
                           self._variant_presentation(v) for v in validations
                           if v.variant.id != council_result.recommendation
                       ]},
            very_verbose_y={"validations": [self._variant_presentation(v) for v in validations]},
            upstream_stage="engineering_council", downstream_stage="human_engineering_authority",
            status="completed", identity=execution_identity("engineering_admissibility"),
            x_type="council_result", y_type="engineering_variant_selection",
        )
        self._trace(
            run_id, "workflow_end", "completed", "pending",
            "Workflow stopped at pending human engineering selection",
            details={"end_state": "human_engineering_authority_pending"},
            related_result_id=f"workflow-end:{council_result.id}:pending",
        )

        return WorkflowResult(
            discovery_result=discovery_result,
            validation_result=validation_result,
            preflight_result=preflight_result,
            council_result=council_result,
            setup_plan=None,
            engineering_selection=selection,
            platform=platform,
            project_context=project_context,
            project_intelligence=project_intelligence,
        )

    @staticmethod
    def _variant_presentation(validation: "CandidateValidation") -> dict:
        """CLAUDE-ARCH-S2-013C: the user-facing comparison evidence for one
        candidate (ADC_Zielbild Abschnitt 25) -- Pro/Contra, risks,
        verification strategy, rank/score and technical admissibility.
        Reads only already-structured CouncilVariant/CandidateValidation
        fields; invents nothing."""
        variant = validation.variant
        return {
            "id": variant.id,
            "name": variant.name,
            "environment": variant.environment,
            "admissible": validation.admissible,
            "reasons": list(validation.reasons),
            "advantages": list(variant.advantages),
            "disadvantages": list(variant.disadvantages),
            "risks": list(variant.risks),
            "verification": variant.verification,
            "rank": variant.rank,
            "total_score": variant.total_score,
            "consensus_level": variant.consensus_level,
            "requirement_coverage": sorted({
                item.requirement_ref for item in variant.toolchain
            }),
            "toolchain": [
                {
                    "requirement_ref": item.requirement_ref, "name": item.name,
                    "type": item.type, "state": item.state,
                }
                for item in variant.toolchain
            ],
        }

    def resolve_engineering_selection(
        self,
        council_result: CouncilResult,
        preflight_result: PreflightResult | None,
        platform: str | None,
        project_id: str,
        *,
        human_selected_variant_id: str,
        run_id: str | None = None,
        project_intelligence: object | None = None,
        project_root: str | None = None,
    ) -> "WorkflowResult":
        """Resumes a run() paused at the productive S2.4 Human Engineering
        Authority boundary (CLAUDE-ARCH-S2-013C).

        `project_root` (CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-
        BINDING-FIX-003): optional and additive, forwarded unchanged to
        ToolchainMaterializer.materialize_decision() so the selected
        candidate's own `environment` ("host"/"venv") is bound to a real
        Python target before materialization -- see that method's own
        docstring. Omitting it preserves the exact prior behavior.

        `human_selected_variant_id` is REQUIRED and always an explicit
        human action -- accepting the Chairman's own recommendation means
        passing that exact id here, never omitting it; this is the one and
        only place production code may call select_engineering_variant()
        with a human_selected_variant_id, which guarantees
        EngineeringDecision.selection_authority == "human" for every
        candidate this method ever hands to S2.5, regardless of whether it
        happens to equal the Chairman's recommendation. S2.3 admissibility
        is (re)computed by select_engineering_variant() itself, exactly as
        it was for every prior caller -- never weakened, never duplicated,
        never overridable by the human_selected_variant_id: an unknown or
        technically inadmissible id still raises
        EngineeringVariantNotFoundError / ChairmanRecommendationInadmissibleError
        unchanged. This method never re-invokes the Engineering Council
        and never touches its bounded, automatic S2.3->S2.2 admissibility
        repair budget (CLAUDE-ARCH-S2-012B/012D) -- it only ever resolves
        an ALREADY-COMPLETE CouncilResult's admissible candidates."""
        run_id = run_id or project_id
        if self._materializer is None:
            raise WorkflowExecutionError("No ToolchainMaterializer has been configured.")

        self._trace(
            run_id, "human_engineering_authority", "completed", "started",
            "Explicit human engineering selection received",
            details={"human_selected_variant_id": human_selected_variant_id},
        )
        try:
            engineering_decision = select_engineering_variant(
                council_result, preflight_result, platform,
                chairman_recommendation=council_result.recommendation,
                human_selected_variant_id=human_selected_variant_id,
                trusted_verification_groups=all_trusted_verification_groups(project_intelligence),
                project_root=project_root,
            )
        except Exception as error:
            self._trace(
                run_id, "human_engineering_authority", "failed", "failed",
                f"Human engineering selection rejected: {type(error).__name__}",
                details={"failure_summary": str(error)[:3000]},
            )
            raise
        self._trace(
            run_id, "human_engineering_authority", "completed", "completed",
            "Human engineering selection resolved",
            details={
                "selected_variant_id": engineering_decision.variant.id,
                "selection_authority": engineering_decision.selection_authority,
            },
            related_result_id=f"human-engineering-authority:{project_id}:{engineering_decision.variant.id}",
        )

        self._trace(run_id, "toolchain_materialization", "started", "started", "Toolchain materialization started")
        try:
            setup_plan = self._materializer.materialize_decision(
                engineering_decision, project_id, preflight=preflight_result,
                project_root=project_root,
            )
        except Exception as error:
            evidence = getattr(error, "validations", None) or getattr(error, "rejected", None)
            details = {"failure_summary": str(error)[:3000]} if evidence else {}
            self._trace(run_id, "toolchain_materialization", "failed", "failed", f"Toolchain materialization failed: {type(error).__name__}", details=details)
            self._interface(
                run_id, "toolchain_materialization", "Toolchain Materializer produced no SetupPlan",
                info_x={"result_id": council_result.id},
                info_y={"available": False, "error_category": type(error).__name__},
                upstream_stage="human_engineering_authority", downstream_stage="setup_plan",
                status="failed", identity=execution_identity("toolchain_materializer"),
                x_type="council_result", y_type="setup_plan",
            )
            raise
        self._trace(run_id, "toolchain_materialization", "completed", "completed", "Toolchain materialization completed", details={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)}, related_result_id=setup_plan.id)
        self._interface(
            run_id, "toolchain_materialization", "Toolchain Materializer transformed the EngineeringDecision into a SetupPlan",
            info_x={"result_id": council_result.id},
            info_y={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)},
            verbose_x={"result_id": council_result.id,
                       "selected_variant_id": engineering_decision.variant.id,
                       "selection_authority": engineering_decision.selection_authority},
            verbose_y={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)},
            upstream_stage="human_engineering_authority", downstream_stage="setup_plan",
            identity=execution_identity("toolchain_materializer"),
            x_type="council_result", y_type="setup_plan",
        )
        self._trace(run_id, "setup_plan", "completed", "completed", "Setup plan created", details={"plan_id": setup_plan.id, "step_count": len(setup_plan.steps)}, related_result_id=setup_plan.id)
        self._trace(run_id, "setup_approval", "pending", "pending", "Setup approval is pending", details={"plan_id": setup_plan.id}, related_result_id=f"setup-approval:{setup_plan.id}:pending")
        self._trace(run_id, "workflow_end", "completed", "pending", "Workflow stopped at pending setup approval", details={"end_state": "setup_approval_pending"}, related_result_id=f"workflow-end:{setup_plan.id}:pending")

        return WorkflowResult(
            discovery_result=None,
            validation_result=None,
            preflight_result=preflight_result,
            council_result=council_result,
            setup_plan=setup_plan,
            engineering_selection=None,
            platform=platform,
            project_context=None,
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
            "firmware_indicators", "truncated", "areas",
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

        A step is structurally executable either through the controlled
        ``setup_effect`` classification, or through the legacy
        ``action="install"`` + ``install_method`` + ``package``
        representation that predates that field. Anything else —
        notably ``action="manual_review"`` steps with no install data —
        genuinely requires manual review and must still block.
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

        if (
            step.action == "install"
            and step.install_method
            and step.package
            and step.package.strip()
        ):
            return

        raise WorkflowExecutionError(
            f"Setup step '{step.id}' requires manual review: "
            f"no structured setup effect is defined "
            f"(action={step.action!r})."
        )

    def execute_approved(
        self,
        plan: SetupPlan,
        project_root: str | None = None,
    ) -> tuple[ExecutionResult, ...]:
        """Execute an already approved setup plan safely.

        This is the productive S3.3 Controlled Execution central gate:
        it validates the plan is approved and every executable step is
        individually approved, enforces the replay/idempotency guard
        (see _execute_with_state_guard/SetupExecutionStateStore) before
        any mutation, and only then delegates the concrete mutation to
        whichever executor was configured (`self._executor`, wired in
        canonical composition as PythonPackageExecutor). This method
        does not itself know or care which ecosystem/toolchain a step
        targets -- that is the configured executor's own concern, never
        this gate's. PythonPackageExecutor is the CURRENT productive
        backend adapter (Python package installation only); it is not a
        generic definition of S3.3 and must not become central policy
        for other ecosystems (npm, CMake, PlatformIO, ESPHome, ...) --
        a step for an ecosystem with no controlled backend surfaces
        honestly via SetupPlan.unsupported_backend_effects instead of
        being silently treated as executable.

        project_root is optional and purely additive: when supplied, it
        lets the configured executor route its actual subprocess work
        through the central controlled execution boundary (cwd
        confinement, environment allowlist, capability validation)
        instead of an unconfined default.

        CLAUDE-E2E-003I: supplying project_root is exactly the signal
        that this is a confined, productive mutation attempt -- and for
        that shape, a configured execution_state_store is now MANDATORY,
        not optional. There is no "productive mutation without replay
        protection" mode: a DevelopmentWorkflow built without one
        (real productive composition -- canonical_composition.py,
        mcp_transport.py -- always builds one) fails closed with
        WorkflowExecutionError the moment a confined execution is
        attempted, rather than silently executing unguarded. Omitting
        project_root entirely remains the one legitimate way to use this
        method as a narrow, non-productive, unconfined low-level unit
        helper (never reachable through Web/MCP/the application service,
        all of which always supply a real project_root).
        """

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

        def _execute(step: SetupStep) -> ExecutionResult:
            if project_root is not None:
                if self._execution_state_store is None:
                    raise WorkflowExecutionError(
                        "Confined setup execution (project_root supplied) "
                        "requires a configured execution_state_store; "
                        "refusing to execute a mutating SetupStep without "
                        "replay/restart-safety authority (CLAUDE-E2E-003I)."
                    )
                return self._execute_with_state_guard(step, project_root, plan.generation_id)
            return self._executor.execute(step)

        return tuple(
            _execute(step)
            for step in executable_steps
        )

    def _execute_with_state_guard(
        self, step: SetupStep, project_root: str, generation_id: str,
    ) -> ExecutionResult:
        """Persisted, project/generation/step-scoped retry/restart guard
        (CLAUDE-E2E-003H, generation-aware since CLAUDE-E2E-003I) around
        a single SetupStep's execution.

        KNOWN SUCCESS/FAILURE is never silently repeated: the persisted
        terminal result is returned as-is, through the exact same
        ExecutionResult contract a real execution would produce -- no
        second launch. A persisted IN_PROGRESS record (this step was
        started by an earlier, now-gone attempt whose outcome was never
        established) fails closed via SetupExecutionStateError rather
        than guessing whether it is safe to run again. This function
        makes no claim of exactly-once execution across an ADC crash
        between launching the real mutation and persisting its result --
        only that a KNOWN outcome is never blindly repeated, and an
        UNKNOWN one is never silently treated as safe to repeat either.
        """
        import uuid

        from app.setup_execution_state import FAILED, SUCCEEDED, SetupStepIdentity

        identity = SetupStepIdentity.for_step(project_root, generation_id, step)
        owner_id = uuid.uuid4().hex
        # claim_or_report() -- not a separate get() then begin() -- is
        # what makes this safe across genuinely separate OS processes
        # (CLAUDE-E2E-003I): the whole check-and-claim decision is made
        # under one real, cross-process advisory file lock, so two
        # processes racing on the same identity cannot both observe
        # NOT_STARTED and both proceed to execute.
        status, record = self._execution_state_store.claim_or_report(identity, owner_id)
        if status in (SUCCEEDED, FAILED):
            payload = record.get("result") or {}
            return ExecutionResult(
                step_id=step.id,
                success=bool(payload.get("success", status == SUCCEEDED)),
                message=payload.get(
                    "message",
                    f"Setup step already {status}; not re-executed.",
                ),
                verification_passed=bool(payload.get("verification_passed", False)),
            )
        # status == "claimed": this call itself just persisted a fresh
        # IN_PROGRESS record for this identity; a matching IN_PROGRESS/
        # RECOVERY_REQUIRED record found instead would already have
        # raised SetupExecutionStateError inside claim_or_report() above.
        try:
            result = self._executor.execute(step, project_root)
        except Exception as error:
            self._execution_state_store.finish(identity, owner_id, FAILED, {
                "success": False,
                "message": f"Execution raised {type(error).__name__}: {error}",
                "verification_passed": False,
            })
            raise
        self._execution_state_store.finish(
            identity, owner_id, SUCCEEDED if result.success else FAILED,
            {
                "success": result.success, "message": result.message,
                "verification_passed": result.verification_passed,
            },
        )
        return result

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
            setup_execution_results = self.execute_approved(
                plan, getattr(development_request, "project_path", None),
            )
        except Exception as error:
            self._trace(run_id, "setup_execution", "failed", "failed", f"Setup execution failed: {type(error).__name__}")
            raise
        if not all(result.success for result in setup_execution_results):
            self._trace(run_id, "setup_execution", "failed", "failed", "Setup execution returned unsuccessful results", details={"result_count": len(setup_execution_results)})
            raise WorkflowExecutionError(
                "Setup execution did not complete successfully."
            )
        self._trace(run_id, "setup_execution", "completed", "completed", "Setup execution completed", details={"result_count": len(setup_execution_results)})

        try:
            controlled_rework_result = controlled_rework_stage.run(development_request)
        except Exception as error:
            # CLAUDE-E2E-NIO-007A: a terminal provider/infrastructure
            # exception during the rework attempt must not erase the
            # last meaningful engineering failure that caused rework to
            # be attempted in the first place (e.g. a real ESPHome
            # verification failure). ControlledReworkStage.run() attaches
            # the preserved initial_result/rework_request to the
            # exception precisely so this can still be traced here,
            # before the original exception is re-raised unchanged.
            preserved_initial = getattr(error, "controlled_rework_initial_result", None)
            preserved_request = getattr(error, "controlled_rework_request", None)
            if preserved_initial is not None:
                self._trace_development_cycles(
                    run_id,
                    ControlledReworkResult(initial_result=preserved_initial, rework_executed=False),
                )
                reason = getattr(preserved_request, "reason", "") or "unknown reason"
                diagnostics = getattr(preserved_request, "diagnostics", "") or ""
                # diagnostics (not reason) is where TestingStage.run()
                # actually places the specific engineering-failure
                # summary (e.g. an ESPHome validate/compile failure);
                # reason is a fixed, generic string ("tests require
                # rework"). Prefer diagnostics for the human-readable
                # summary; keep both available in details.
                self._trace(
                    run_id, "controlled_rework", "failed", "failed",
                    f"Controlled rework attempt failed ({type(error).__name__}) "
                    f"after rework was required: {diagnostics or reason}",
                    details={"diagnostics": diagnostics},
                )
            raise
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
            if isinstance(changes, dict) and changes.get("disposition") == "no_changes_required":
                # S4.2's explicit no-op -- kept traceable without
                # redesigning the trace model or granting `tests` any
                # authority it does not have.
                test_generation_details["disposition"] = "no_changes_required"
                if isinstance(changes.get("reason"), str):
                    test_generation_details["reason"] = changes["reason"]
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
