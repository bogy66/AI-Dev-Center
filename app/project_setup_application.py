"""Application-core entry point for canonical project setup planning."""

from __future__ import annotations

from pathlib import Path

from app.common_request import CommonRequest, RequestIntent
from app.development_stage import DevelopmentRequest
from app.dev_workflow import (
    DevelopmentWorkflow,
    SetupDevelopmentTestingResult,
    WorkflowResult,
)
from app.project_inspector import ProjectInspector
from app.project_intelligence import ProjectIntelligence
from app.workflow_manager import WorkflowManager
from app.final_approval import FinalApprovalResult
from app.change_provenance import RunChangeProvenance
from app.controlled_git_stage import ControlledGitStage, GitCommitRequest, GitCommitResult
from app.controlled_publish_stage import ControlledPublishStage, PublishRequest, PublishResult
from app.publish_approval import PublishApprovalResult
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from app.diagnostic_trace import DiagnosticTraceError
from app.canonical_execution import (
    PROCESS_OWNER_ID, ConcurrentExecutionError, ExecutionReentryError,
    RecoveryRequiredError, acquire_project_execution,
)
from app.capability_registration import (
    CapabilityRegistrationError,
    CapabilityRegistrationRequest,
    CapabilityRegistrationResult,
)
from app.execution import (
    ApprovalProvenance,
    CapabilityRegistration,
    CapabilityRegistry,
    DEFAULT_CAPABILITY_REGISTRY,
)
from app.missing_toolchain_setup import (
    MissingToolchainSetupError,
    MissingToolchainSetupRequest,
    MissingToolchainSetupResult,
    StructuredInstallerRegistry,
    already_available_setup_result,
    deserialize_setup_plan,
    deserialize_verification_plan,
    serialize_setup_plan,
    serialize_verification_plan,
)
from app.setup_approval import SetupApproval
from app.verification import TOOL_UNAVAILABLE
from app.project_context import (
    ProjectContext, ProjectDefinition, ProjectDefinitionStore,
    compose_project_context,
)


class ProjectSetupApplicationService:
    """Inspect a project, normalize adapter input, and delegate planning."""

    def __init__(
        self,
        development_workflow: DevelopmentWorkflow,
        project_inspector: ProjectInspector | None = None,
        workflow_manager: WorkflowManager | None = None,
        controlled_git_stage: ControlledGitStage | None = None,
        controlled_publish_stage: ControlledPublishStage | None = None,
        diagnostic_trace: DiagnosticTrace | None = None,
        capability_registry: CapabilityRegistry | None = None,
        structured_installers: StructuredInstallerRegistry | None = None,
        verification_registry: object | None = None,
        project_definition_store: ProjectDefinitionStore | None = None,
        technical_config: object | None = None,
    ) -> None:
        self._development_workflow = development_workflow
        self._project_inspector = project_inspector or ProjectInspector()
        self._workflow_manager = workflow_manager or WorkflowManager()
        self._controlled_git_stage = controlled_git_stage or ControlledGitStage()
        self._controlled_publish_stage = controlled_publish_stage or ControlledPublishStage()
        self._capability_registry = capability_registry or DEFAULT_CAPABILITY_REGISTRY
        self._structured_installers = structured_installers or StructuredInstallerRegistry()
        self._verification_registry = verification_registry
        self._project_definition_store = project_definition_store or ProjectDefinitionStore()
        self._technical_config = technical_config
        trace_path = self._workflow_manager.storage.parent / ".diagnostic-traces" / "events.jsonl"
        self._diagnostic_trace = diagnostic_trace or DiagnosticTrace(DiagnosticTraceStore(trace_path))
        if hasattr(self._development_workflow, "set_diagnostic_trace"):
            self._development_workflow.set_diagnostic_trace(self._diagnostic_trace)
        self.recover_approved_capabilities()

    def _trace(self, run_id, phase, event_type, status, summary, **kwargs):
        try:
            return self._diagnostic_trace.record(
                run_id, phase, event_type, status, summary,
                source="project_setup_application", **kwargs,
            )
        except DiagnosticTraceError:
            return None

    def get_diagnostic_trace(self, run_id: str):
        """Return the ordered, read-only central trace for one run."""
        return self._diagnostic_trace.get_trace(run_id)

    def build_request(
        self, project_id: str, project_path: str | Path
    ) -> CommonRequest:
        """Inspect the project and create the sole supported input intent."""
        _, intelligence = self._project_inspector.inspect_managed(
            project_id, project_path,
        )
        project_info = intelligence.to_summary()
        project_info["project_id"] = project_id
        project_info["project_path"] = str(Path(project_path).expanduser().resolve())
        return CommonRequest(
            project_id=project_id,
            project_info=project_info,
            intent=RequestIntent.PLAN_PROJECT_SETUP,
        )

    def build_intelligence(
        self, project_path: str | Path
    ) -> ProjectIntelligence:
        """Return the full typed project intelligence profile."""
        return self._project_inspector.build_intelligence(project_path)

    def build_project_context(
        self, project_id: str, project_path: str | Path,
    ) -> ProjectContext:
        """Compose observed, decided and configured sources without flattening."""
        if self._technical_config is None:
            raise ValueError("Technical config is required for Project Context")
        intelligence = self._project_inspector.build_intelligence(project_path)
        return compose_project_context(
            project_id, intelligence,
            self._project_definition_store.active(project_id),
            self._technical_config,
        )

    def create_project_definition(
        self, project_id: str, key: str, value, category: str,
        scope: str, source: str,
    ) -> ProjectDefinition:
        """Controlled structured update; never grants workflow authority."""
        return self._project_definition_store.create(
            project_id, key, value, category, scope, source,
        )

    def supersede_project_definition(
        self, definition_id: str, value, source: str,
    ) -> ProjectDefinition:
        return self._project_definition_store.supersede(definition_id, value, source)

    def revoke_project_definition(self, definition_id: str) -> ProjectDefinition:
        return self._project_definition_store.revoke(definition_id)

    def request_capability_registration(
        self, request: CapabilityRegistrationRequest,
    ) -> CapabilityRegistrationResult:
        """Validate Council authority and open a separate Human Approval."""
        try:
            variant = self._validate_capability_request(request)
            normalized_scope = self._normalized_capability_scope(request)
        except (CapabilityRegistrationError, ValueError) as error:
            return CapabilityRegistrationResult(
                request.request_id, "rejected", blockers=(str(error),),
            )
        self._workflow_manager.create_capability_approval(
            request.request_id,
            request.project_id,
            request.project_intelligence.project_root,
            request.council_result.id,
            variant.id,
            request.capability,
            request.executable_names,
            request.allowed_operations,
            normalized_scope,
        )
        self._trace(
            request.request_id, "capability_approval", "pending", "pending",
            "Capability Human Approval is pending",
            details={"capability": request.capability, "chairman_variant": variant.id},
            related_result_id=request.request_id,
        )
        return CapabilityRegistrationResult(request.request_id, "pending")

    def decide_capability_approval(
        self, request_id: str, decision: str,
        approved_by: str | None = None, comment: str | None = None,
    ) -> CapabilityRegistrationResult:
        record = self._workflow_manager.decide_capability_approval(
            request_id, decision, approved_by, comment,
        )
        return CapabilityRegistrationResult(request_id, record["status"])

    def register_approved_capability(
        self, request: CapabilityRegistrationRequest,
    ) -> CapabilityRegistrationResult:
        """Produce and register capability metadata only after all authorities."""
        try:
            variant = self._validate_capability_request(request)
            normalized_scope = self._normalized_capability_scope(request)
            human = self._workflow_manager.get_capability_approval(request.request_id)
            if human is None or human.get("status") != "approved":
                state = human.get("status") if human else "missing"
                raise CapabilityRegistrationError(f"Human Approval is {state}")
            if (
                human.get("project_id") != request.project_id
                or human.get("project_intelligence_ref") != request.project_intelligence.project_root
                or human.get("council_result_id") != request.council_result.id
                or human.get("chairman_variant_id") != variant.id
                or human.get("capability") != request.capability
                or tuple(human.get("executable_names", ())) != request.executable_names
                or tuple(human.get("allowed_operations", ())) != request.allowed_operations
                or human.get("project_scope") != normalized_scope
            ):
                raise CapabilityRegistrationError("Human Approval does not match the registration request")
            provenance = ApprovalProvenance(
                project_intelligence_ref=request.project_intelligence.project_root,
                engineering_council_ref=request.council_result.id,
                chairman_approval_ref=variant.id,
                human_approval_ref=human.get("id", ""),
            )
            if not provenance.is_complete():
                raise CapabilityRegistrationError("Required approval provenance is incomplete")
            registration = CapabilityRegistration(
                capability=request.capability,
                executable_names=request.executable_names,
                allowed_operations=request.allowed_operations,
                approval_provenance=provenance,
                project_scope=normalized_scope,
            )
            self._capability_registry.register_approved(registration)
        except (CapabilityRegistrationError, ValueError) as error:
            return CapabilityRegistrationResult(
                request.request_id, "rejected", blockers=(str(error),),
            )
        self._trace(
            request.request_id, "capability_registration", "registered", "completed",
            "Approved capability registered",
            details={"capability": request.capability},
            related_result_id=request.request_id,
        )
        return CapabilityRegistrationResult(
            request.request_id, "registered", registration=registration,
        )

    def recover_approved_capabilities(self) -> tuple[CapabilityRegistration, ...]:
        """Idempotently restore valid approved dynamic registrations."""
        recovered: list[CapabilityRegistration] = []
        state = self._workflow_manager.load()
        if not isinstance(state, dict):
            return ()
        approvals = state.get("capability_approvals", {})
        if not isinstance(approvals, dict):
            return ()
        for record in approvals.values():
            if not isinstance(record, dict) or record.get("status") != "approved":
                continue
            try:
                scope = str(Path(record["project_scope"]).resolve())
                intelligence_ref = str(Path(record["project_intelligence_ref"]).resolve())
                if scope != intelligence_ref or not record.get("approved_at"):
                    raise ValueError("Recovered project scope or Human Approval is invalid")
                provenance = ApprovalProvenance(
                    project_intelligence_ref=record["project_intelligence_ref"],
                    engineering_council_ref=record["council_result_id"],
                    chairman_approval_ref=record["chairman_variant_id"],
                    human_approval_ref=record["id"],
                )
                if not provenance.is_complete():
                    raise ValueError("Recovered approval provenance is incomplete")
                registration = CapabilityRegistration(
                    capability=record["capability"],
                    executable_names=tuple(record["executable_names"]),
                    allowed_operations=tuple(record["allowed_operations"]),
                    approval_provenance=provenance,
                    project_scope=scope,
                )
                self._capability_registry.register_approved(registration)
            except (KeyError, TypeError, ValueError):
                continue
            recovered.append(registration)
        return tuple(recovered)

    def prepare_missing_toolchain_setup(
        self, request: MissingToolchainSetupRequest,
    ) -> MissingToolchainSetupResult:
        """Turn a structured TOOL_UNAVAILABLE result into a pending SetupPlan."""
        try:
            root = str(Path(request.project_root).resolve())
            if root != str(Path(request.verification_plan.project_root).resolve()):
                raise MissingToolchainSetupError("VerificationPlan belongs to another project")
            unavailable_ids = {
                result.step_id for result in request.verification_result.steps
                if result.status == TOOL_UNAVAILABLE.value
            }
            candidates = tuple(
                step for step in request.verification_plan.steps
                if step.step_id in unavailable_ids
                and step.verification_kind == request.operation_type
            )
            if not candidates:
                raise MissingToolchainSetupError("No matching TOOL_UNAVAILABLE verification step")
            materialized = self._development_workflow.materialize_setup_plan(
                request.council_result, request.project_id,
            )
            setup_steps = tuple(
                step for step in materialized.steps
                if step.package == request.toolchain and step.action == "install"
            )
            if len(setup_steps) != 1:
                raise MissingToolchainSetupError("Council SetupPlan has no unique structured toolchain action")
            plan = type(materialized)(
                id=f"{materialized.id}-missing-{candidates[0].step_id}",
                project_id=materialized.project_id,
                steps=setup_steps,
                requires_user_approval=True,
                warnings=materialized.warnings,
                status="pending_approval",
            )
            record = {
                "status": "pending_approval",
                "project_id": request.project_id,
                "project_root": root,
                "toolchain": request.toolchain,
                "operation_type": request.operation_type,
                "council_result_id": request.council_result.id,
                "setup_plan": serialize_setup_plan(plan),
                "verification_plan": serialize_verification_plan(request.verification_plan),
                "verification_retry_status": "pending",
            }
            persisted = self._workflow_manager.create_missing_toolchain_setup(plan.id, record)
            return MissingToolchainSetupResult(plan.id, persisted["status"])
        except (MissingToolchainSetupError, ValueError) as error:
            return MissingToolchainSetupResult("", "rejected", blockers=(str(error),))

    def decide_missing_toolchain_setup(
        self, plan_id: str, decision: str,
        approved_by: str | None = None, comment: str | None = None,
    ) -> MissingToolchainSetupResult:
        record = self._workflow_manager.get_missing_toolchain_setup(plan_id)
        if record is None:
            return MissingToolchainSetupResult(plan_id, "rejected", blockers=("Setup request is missing",))
        if decision not in {"approved", "rejected"}:
            return MissingToolchainSetupResult(plan_id, "rejected", blockers=("Invalid Setup Approval decision",))
        plan = deserialize_setup_plan(record["setup_plan"])
        decided = SetupApproval.approve(plan) if decision == "approved" else SetupApproval.reject(plan)
        updated = self._workflow_manager.decide_missing_toolchain_setup(
            plan_id, decision, serialize_setup_plan(decided), approved_by, comment,
        )
        return MissingToolchainSetupResult(plan_id, updated["status"])

    def execute_missing_toolchain_setup(self, plan_id: str) -> MissingToolchainSetupResult:
        """Execute one approved structured installer exactly once."""
        record = self._workflow_manager.get_missing_toolchain_setup(plan_id)
        if record is not None and record.get("status") == "completed":
            return MissingToolchainSetupResult(
                plan_id, record.get("setup_outcome", "completed"),
            )
        if record is not None and record.get("status") == "executing":
            return MissingToolchainSetupResult(
                plan_id, "recovery_required",
                blockers=("Interrupted setup requires explicit recovery",),
            )
        if record is None or record.get("status") != "approved":
            status = record.get("status") if record else "missing"
            return MissingToolchainSetupResult(plan_id, status, blockers=("Setup Approval is required",))
        plan = deserialize_setup_plan(record["setup_plan"])
        if len(plan.steps) != 1 or not plan.steps[0].is_approved:
            return MissingToolchainSetupResult(plan_id, "failed", blockers=("Approved structured setup step is invalid",))
        step = plan.steps[0]
        installer = self._structured_installers.get(step.install_method or "")
        if installer is None:
            self._workflow_manager.update_missing_toolchain_setup(plan_id, status="failed")
            return MissingToolchainSetupResult(plan_id, "failed", blockers=("No structured installer is registered",))
        if installer.is_available(record["toolchain"]):
            result = already_available_setup_result(step.id)
            self._workflow_manager.update_missing_toolchain_setup(
                plan_id, status="completed", setup_outcome="already_available",
            )
            return MissingToolchainSetupResult(plan_id, "already_available", result)
        self._workflow_manager.update_missing_toolchain_setup(plan_id, status="executing")
        result = installer.executor.execute(step)
        available = result.success and installer.is_available(record["toolchain"])
        self._workflow_manager.update_missing_toolchain_setup(
            plan_id, status="completed" if available else "failed",
            setup_outcome="installed" if available else "failed",
        )
        return MissingToolchainSetupResult(
            plan_id, "completed" if available else "failed", result,
            blockers=() if available else ("Toolchain is unavailable after setup",),
        )

    def retry_missing_toolchain_verification(self, plan_id: str) -> MissingToolchainSetupResult:
        """Retry only the persisted workflow-owned VerificationPlan."""
        record = self._workflow_manager.get_missing_toolchain_setup(plan_id)
        if record is None or record.get("status") != "completed":
            return MissingToolchainSetupResult(plan_id, "retry_blocked", blockers=("Successful setup is required",))
        if record.get("verification_retry_status") == "completed":
            return MissingToolchainSetupResult(plan_id, "verification_completed")
        if self._verification_registry is None:
            return MissingToolchainSetupResult(plan_id, "retry_blocked", blockers=("Verification registry is unavailable",))
        plan = deserialize_verification_plan(record["verification_plan"])
        result = self._verification_registry.execute_plan(plan)
        self._workflow_manager.update_missing_toolchain_setup(
            plan_id, verification_retry_status="completed",
            verification_retry_aggregate=result.aggregate_status,
        )
        return MissingToolchainSetupResult(
            plan_id, "verification_completed", verification_result=result,
        )

    @staticmethod
    def _normalized_capability_scope(request: CapabilityRegistrationRequest) -> str:
        intelligence_root = Path(request.project_intelligence.project_root).resolve()
        if request.project_scope is None:
            raise CapabilityRegistrationError("Dynamic capability registration requires project scope")
        requested_scope = Path(request.project_scope).resolve()
        if requested_scope != intelligence_root:
            raise CapabilityRegistrationError(
                "Capability project scope must match the Project Intelligence root"
            )
        return str(intelligence_root)

    @staticmethod
    def _validate_capability_request(request: CapabilityRegistrationRequest):
        if not request.request_id or not request.project_id:
            raise CapabilityRegistrationError("Capability request identity is incomplete")
        intelligence = request.project_intelligence
        council = request.council_result
        if not intelligence.project_root:
            raise CapabilityRegistrationError("Project Intelligence reference is missing")
        if council.project_id != request.project_id:
            raise CapabilityRegistrationError("Council result belongs to another project")
        if not council.council_complete or council.chairman_error or not council.id:
            raise CapabilityRegistrationError("Chairman approval is missing")
        variant = request.recommended_variant()
        if request.capability not in variant.capabilities:
            raise CapabilityRegistrationError("Capability is not present in the Chairman recommendation")
        council_tools = {item.name for item in variant.toolchain if item.name}
        if not request.executable_names or not set(request.executable_names).issubset(council_tools):
            raise CapabilityRegistrationError("Executable identity is not present in the Council result")
        # Construction performs the shared metadata validation without registering.
        CapabilityRegistration(
            capability=request.capability,
            executable_names=request.executable_names,
            allowed_operations=request.allowed_operations,
            approval_provenance=None,
            project_scope=request.project_scope,
        )
        return variant

    def plan_project_setup(
        self, project_id: str, project_path: str | Path, run_id: str | None = None,
    ) -> WorkflowResult:
        """Plan setup through the canonical workflow; never approve or execute."""
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")

        trace_run_id = run_id or project_id
        self._trace(trace_run_id, "common_request", "started", "started", "Canonical project setup workflow started", details={"project_id": project_id})
        self._trace(trace_run_id, "project_inspection", "started", "started", "Project inspection started", details={"project_id": project_id})

        intelligence = self._project_inspector.build_intelligence(project_path)
        project_context = None
        if self._technical_config is not None:
            project_context = compose_project_context(
                project_id, intelligence,
                self._project_definition_store.active(project_id),
                self._technical_config,
            )

        try:
            request = self.build_request(project_id, project_path)
        except Exception as error:
            self._trace(trace_run_id, "project_inspection", "failed", "failed", f"Project inspection failed: {type(error).__name__}")
            self._trace(trace_run_id, "workflow_end", "failed", "failed", "Workflow ended after project inspection failure", details={"end_state": "failed"})
            raise
        info = request.project_info if isinstance(request.project_info, dict) else {}
        self._trace(trace_run_id, "project_inspection", "completed", "completed", "Project inspection completed", details={
            "project_id": project_id,
            "project_kind": intelligence.project_kind,
            "language_count": len(intelligence.language_names),
            "framework_count": len(intelligence.framework_names),
            "area_count": intelligence.area_count,
            "git_repository_present": intelligence.git_repository_present,
            "truncated": intelligence.truncated,
            "warning_count": len(intelligence.warnings),
            "file_count": intelligence.total_files_traversed,
        })
        if request.intent is not RequestIntent.PLAN_PROJECT_SETUP:
            raise ValueError(f"Unsupported request intent: {request.intent}")

        try:
            if project_context is None:
                if run_id is None:
                    return self._development_workflow.run(
                        request.project_info, request.project_id,
                    )
                return self._development_workflow.run(
                    request.project_info, request.project_id, run_id,
                )
            if run_id is None:
                return self._development_workflow.run(
                    request.project_info, request.project_id,
                    project_context=project_context,
                )
            return self._development_workflow.run(
                request.project_info, request.project_id, run_id,
                project_context=project_context,
            )
        except Exception as error:
            self._trace(trace_run_id, "workflow_end", "failed", "failed", f"Planning workflow failed: {type(error).__name__}", details={"end_state": "failed"}, related_result_id=f"planning:{trace_run_id}:failed")
            raise

    def execute_approved_setup_and_development(
        self,
        plan,
        project_id: str,
        project_path: str | Path,
        task: str,
        run_id: str | None = None,
    ) -> SetupDevelopmentTestingResult:
        """Execute approved setup, then delegate development/testing once."""
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")

        execution_run_id = run_id or plan.id
        request = DevelopmentRequest(
            project_id=project_id,
            project_path=project_path,
            task=task,
            run_id=execution_run_id,
            provenance_recorder=RunChangeProvenance(self._workflow_manager, execution_run_id, project_path),
        )
        stage = "development"
        try:
            lease = acquire_project_execution(project_path, execution_run_id, stage)
        except ConcurrentExecutionError:
            self._trace(execution_run_id, "workflow_end", "blocked", "blocked", "Concurrent mutating execution rejected", details={"execution_stage": stage})
            raise
        try:
            self._workflow_manager.begin_execution(
                execution_run_id, stage, lease.project_root, PROCESS_OWNER_ID,
            )
        except RecoveryRequiredError:
            lease.release()
            self._trace(execution_run_id, "workflow_end", "blocked", "recovery_required", "Execution re-entry rejected", details={"execution_stage": stage})
            raise
        except ExecutionReentryError:
            lease.release()
            self._trace(execution_run_id, "workflow_end", "blocked", "blocked", "Execution re-entry rejected", details={"execution_stage": stage})
            raise
        self._trace(execution_run_id, "setup_execution", "started", "started", "Mutating execution lifecycle started", details={"execution_stage": stage})
        try:
            result = self._development_workflow.execute_approved_and_run_development(
                plan, request,
            )
            approval = self._workflow_manager.complete_development_execution(
                execution_run_id, PROCESS_OWNER_ID, result.status,
            )
            if approval is None:
                approval = FinalApprovalResult(execution_run_id, "not_applicable", False, False)
        except Exception as error:
            self._workflow_manager.finish_execution(
                execution_run_id, stage, PROCESS_OWNER_ID, "failed",
                type(error).__name__,
            )
            self._trace(execution_run_id, "workflow_end", "failed", "failed", "Mutating execution failed", details={"execution_stage": stage})
            raise
        finally:
            lease.release()
        self._trace(execution_run_id, "workflow_end", "completed", "completed", "Mutating execution lifecycle completed", details={"execution_stage": stage})
        from dataclasses import replace
        approval_type = approval.status if approval.status in {"pending", "approved", "rejected"} else "completed"
        self._trace(execution_run_id, "final_approval", approval_type, approval.status if approval.status in {"pending", "approved", "rejected"} else "completed", f"Final approval state: {approval.status}", related_result_id=f"final-approval:{execution_run_id}:{approval.status}")
        end_state = "final_approval_pending" if approval.status == "pending" else result.status
        self._trace(execution_run_id, "workflow_end", "completed", "pending" if approval.status == "pending" else "completed", f"Workflow stopped at {end_state}", details={"end_state": end_state}, related_result_id=f"workflow-end:{execution_run_id}:{end_state}")
        return replace(result, final_approval_result=approval)

    def decide_final_approval(
        self,
        run_id: str,
        decision: str,
        approved_by: str | None = None,
        comment: str | None = None,
    ) -> FinalApprovalResult:
        result = self._workflow_manager.decide_final_approval(
            run_id, decision, approved_by, comment,
        )
        self._trace(run_id, "final_approval", result.status, result.status, f"Final approval {result.status}", related_result_id=f"final-approval:{run_id}:{result.status}")
        end_state = "ready_for_git" if result.ready_for_git else "final_approval_rejected"
        self._trace(run_id, "workflow_end", "completed", "ready_for_git" if result.ready_for_git else "rejected", f"Workflow stopped at {end_state}", details={"end_state": end_state}, related_result_id=f"workflow-end:{run_id}:{end_state}")
        return result

    def commit_approved_run(
        self, run_id: str, project_root: str | Path, commit_message: str,
    ) -> GitCommitResult:
        """Run the explicit post-approval local Git stage exactly once."""
        self._trace(run_id, "controlled_git", "requested", "started", "Controlled Git stage requested", related_result_id=f"git:{run_id}:requested")
        state = self._workflow_manager.load()
        persisted = state.get("git_commit_results", {}).get(run_id)
        if persisted and persisted.get("status") in {"committed", "nothing_to_commit"}:
            result = GitCommitResult.from_record(persisted)
            self._trace_git_result(result)
            return result
        try:
            lease = acquire_project_execution(project_root, run_id, "git")
        except ConcurrentExecutionError:
            self._trace(run_id, "controlled_git", "blocked", "blocked", "Concurrent Git execution rejected", details={"execution_stage": "git"})
            raise
        result = None
        try:
            lifecycle = self._workflow_manager.get_execution_state(run_id, "git")
            if lifecycle.get("status") == "started":
                request = self._git_request(state, run_id, project_root, commit_message)
                baseline = (lifecycle.get("metadata") or {}).get("baseline_head")
                result = self._controlled_git_stage.recover_committed_result(request, baseline)
                if result is None:
                    self._workflow_manager.require_recovery(run_id, "git")
                    raise RecoveryRequiredError("Git execution requires manual recovery")
                with self._workflow_manager.git_stage_transaction():
                    recovered_state = self._workflow_manager.load()
                    self._workflow_manager.persist_git_commit_result(
                        recovered_state, run_id, result.to_record(),
                    )
                    self._workflow_manager.create_publish_approval(run_id)
                self._workflow_manager.complete_recovered_execution(
                    run_id, "git", PROCESS_OWNER_ID,
                )
                self._trace_git_result(result)
                return result
            baseline_head = self._controlled_git_stage.current_head(project_root)
            if not isinstance(baseline_head, str):
                baseline_head = None
            self._workflow_manager.begin_execution(
                run_id, "git", lease.project_root, PROCESS_OWNER_ID,
                {"baseline_head": baseline_head},
            )
            with self._workflow_manager.git_stage_transaction():
                state = self._workflow_manager.load()
                request = self._git_request(state, run_id, project_root, commit_message)
                result = self._controlled_git_stage.run(request)
                self._workflow_manager.persist_git_commit_result(
                    state, run_id, result.to_record(),
                )
                if result.status == "committed":
                    self._workflow_manager.create_publish_approval(run_id)
            terminal = "completed" if result.status in {"committed", "nothing_to_commit"} else "failed"
            self._workflow_manager.finish_execution(
                run_id, "git", PROCESS_OWNER_ID, terminal,
            )
        except RecoveryRequiredError:
            self._trace(run_id, "controlled_git", "blocked", "recovery_required", "Git execution requires recovery", details={"execution_stage": "git"})
            raise
        except ExecutionReentryError:
            self._trace(run_id, "controlled_git", "blocked", "blocked", "Git execution re-entry rejected", details={"execution_stage": "git"})
            raise
        except Exception as error:
            lifecycle = self._workflow_manager.get_execution_state(run_id, "git")
            # A successful commit followed by a state-save failure is an
            # ambiguous crash window.  Preserve STARTED so the next process
            # requires proof-based recovery instead of recording a retryable
            # controlled failure.
            if lifecycle.get("status") == "started" and not (
                result is not None and result.status == "committed"
            ):
                self._workflow_manager.finish_execution(
                    run_id, "git", PROCESS_OWNER_ID, "failed", type(error).__name__,
                )
            raise
        finally:
            lease.release()
        self._trace_git_result(result)
        if result.status == "committed":
            self._trace(run_id, "publish_approval", "pending", "pending", "Publish approval is pending", related_result_id=f"publish-approval:{run_id}:pending")
            self._trace(run_id, "workflow_end", "completed", "ready_for_publish", "Workflow stopped at pending publish approval", details={"end_state": "publish_pending"}, related_result_id=f"workflow-end:{run_id}:publish-pending")
        else:
            self._trace(run_id, "workflow_end", "completed", "failed" if result.status == "failed" else "completed", f"Workflow stopped after Controlled Git: {result.status}", details={"end_state": f"git_{result.status}"}, related_result_id=f"workflow-end:{run_id}:git-{result.status}")
        return result

    @staticmethod
    def _git_request(state, run_id, project_root, commit_message):
        approval = state.get("final_approvals", {}).get(run_id, {})
        return GitCommitRequest(
            run_id=run_id, project_root=project_root,
            commit_message=commit_message,
            development_status=approval.get("development_status", "missing"),
            final_approval_status=approval.get("status", "missing"),
            ready_for_git=approval.get("status") == "approved",
            provenance=state.get("change_provenance", {}).get(run_id, {}),
            all_provenance=state.get("change_provenance", {}),
        )

    def _trace_git_result(self, result: GitCommitResult):
        event_type = result.status if result.status in {"committed", "nothing_to_commit", "failed"} else "completed"
        details = {"commit_hash": result.commit_hash or "", "controlled_path_count": len(result.paths), "blockers": list(result.blockers)}
        self._trace(result.run_id, "controlled_git", event_type, result.status, f"Controlled Git finished: {result.status}", details=details, related_result_id=f"git:{result.run_id}:{result.status}:{result.commit_hash or ''}")

    def decide_publish_approval(
        self, run_id: str, decision: str, approved_by: str | None = None,
        comment: str | None = None,
    ) -> PublishApprovalResult:
        result = self._workflow_manager.decide_publish_approval(
            run_id, decision, approved_by, comment,
        )
        self._trace(run_id, "publish_approval", result.status, result.status, f"Publish approval {result.status}", related_result_id=f"publish-approval:{run_id}:{result.status}")
        if result.status == "rejected":
            self._trace(run_id, "workflow_end", "completed", "rejected", "Workflow stopped at rejected publish approval", details={"end_state": "publish_rejected"}, related_result_id=f"workflow-end:{run_id}:publish-rejected")
        return result

    def publish_approved_run(
        self, run_id: str, project_root: str | Path, remote: str,
    ) -> PublishResult:
        """Run the explicit post-publish-approval remote stage exactly once."""
        self._trace(run_id, "controlled_publish", "requested", "started", "Controlled Publish stage requested", details={"remote": remote if isinstance(remote, str) and "://" not in remote else ""}, related_result_id=f"publish:{run_id}:requested")
        state = self._workflow_manager.load()
        persisted = state.get("publish_results", {}).get(run_id)
        if persisted and persisted.get("status") in {"published", "already_published"}:
            result = PublishResult.from_record(persisted, status="already_published")
            self._trace_publish_result(result)
            return result
        try:
            lease = acquire_project_execution(project_root, run_id, "publish")
        except ConcurrentExecutionError:
            self._trace(run_id, "controlled_publish", "blocked", "blocked", "Concurrent publish execution rejected", details={"execution_stage": "publish"})
            raise
        result = None
        try:
            lifecycle = self._workflow_manager.get_execution_state(run_id, "publish")
            if lifecycle.get("status") in {"started", "recovery_required"}:
                self._workflow_manager.resume_publish_execution(run_id, PROCESS_OWNER_ID)
            else:
                self._workflow_manager.begin_execution(
                    run_id, "publish", lease.project_root, PROCESS_OWNER_ID,
                )
            with self._workflow_manager.git_stage_transaction():
                state = self._workflow_manager.load()
                commit = state.get("git_commit_results", {}).get(run_id, {})
                approval = state.get("publish_approvals", {}).get(run_id, {})
                request = PublishRequest(
                    run_id=run_id, project_root=project_root, remote=remote,
                    git_commit_status=commit.get("status", "missing"),
                    local_commit_hash=commit.get("commit_hash"),
                    ready_for_publish=(commit.get("status") == "committed" and bool(commit.get("commit_hash")) and approval.get("ready_for_publish") is True),
                    publish_approval_status=approval.get("status", "missing"),
                )
                result = self._controlled_publish_stage.run(request)
                self._workflow_manager.persist_publish_result(
                    state, run_id, result.to_record(),
                )
            terminal = "completed" if result.status in {"published", "already_published"} else "failed"
            self._workflow_manager.finish_execution(
                run_id, "publish", PROCESS_OWNER_ID, terminal,
            )
        except RecoveryRequiredError:
            self._trace(run_id, "controlled_publish", "blocked", "recovery_required", "Publish execution requires recovery", details={"execution_stage": "publish"})
            raise
        except ExecutionReentryError:
            self._trace(run_id, "controlled_publish", "blocked", "blocked", "Publish execution re-entry rejected", details={"execution_stage": "publish"})
            raise
        except Exception as error:
            lifecycle = self._workflow_manager.get_execution_state(run_id, "publish")
            if lifecycle.get("status") == "started" and not (
                result is not None and result.status in {"published", "already_published"}
            ):
                self._workflow_manager.finish_execution(
                    run_id, "publish", PROCESS_OWNER_ID, "failed", type(error).__name__,
                )
            raise
        finally:
            lease.release()
        self._trace_publish_result(result)
        end_state = result.status if result.status in {"published", "already_published"} else "publish_failed"
        self._trace(run_id, "workflow_end", "completed", "published" if result.status in {"published", "already_published"} else "failed", f"Workflow stopped after publish: {result.status}", details={"end_state": end_state}, related_result_id=f"workflow-end:{run_id}:{end_state}")
        return result

    def _trace_publish_result(self, result: PublishResult):
        event_type = result.status if result.status in {"published", "already_published", "failed"} else "completed"
        self._trace(result.run_id, "controlled_publish", event_type, result.status, f"Controlled Publish finished: {result.status}", details={"commit_hash": result.local_commit_hash or "", "published_commit_hash": result.published_commit_hash or "", "remote": result.remote, "remote_ref": result.remote_ref or "", "blockers": list(result.blockers), "failure_summary": result.error or ""}, related_result_id=f"publish:{result.run_id}:{result.status}:{result.published_commit_hash or ''}")

    def _final_approval_for(self, run_id: str, development_status: str) -> FinalApprovalResult:
        if development_status != "accepted":
            return FinalApprovalResult(run_id, "not_applicable", False, False)
        return self._workflow_manager.create_final_approval(run_id, development_status)
