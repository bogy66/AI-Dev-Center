"""Shared composition root for every productive canonical adapter."""
from dataclasses import dataclass
from pathlib import Path

from app.agent_executor import ProviderAgentExecutor
from app.ai_config import load_ai_config
from app.ai_requirement_discovery import AIRequirementDiscovery
from app.dev_workflow import DevelopmentWorkflow, WorkflowExecutionError
from app.development_stage import DeveloperAgent, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.developer_file_applier import DeveloperFileApplier
from app.diagnostic_trace import DiagnosticTrace, DiagnosticTraceStore
from app.engineering_council import EngineeringCouncil
from app.llm_provider_factory import create_llm_provider
from app.local_secret_store import LocalSecretStore
from app.project_inspector import ProjectInspector
from app.project_setup_application import ProjectSetupApplicationService
from app.project_test_runner import ProjectTestRunner
from app.python_package_executor import PythonPackageExecutor
from app.setup_execution_state import SetupExecutionStateStore
from app.approved_plan_content import ApprovedPlanContentStore
from app.requirement_preflight import RequirementPreflight
from app.requirement_validator import RequirementValidator
from app.setup_approval import SetupApproval
from app.test_change_generator import TestChangeGenerator
from app.testing_stage import DiagnosisReviewer, TestingStage
from app.toolchain_materializer import ToolchainMaterializer
from app.verification import build_default_registry
from app.execution import DEFAULT_CAPABILITY_REGISTRY
from app.missing_toolchain_setup import StructuredInstallerRegistration, StructuredInstallerRegistry
from app.workflow_plan_store import WorkflowPlanStore
from app.project_context import ProjectDefinitionStore
from app.signal_adapter import SignalCommunicationAdapter
from app.signal_project_binding import SignalProjectBindingService
from app.workflow_manager import WorkflowManager


@dataclass(frozen=True)
class CanonicalComponents:
    service: ProjectSetupApplicationService
    plan_store: WorkflowPlanStore
    approval: object
    development_workflow: DevelopmentWorkflow
    signal_adapter: SignalCommunicationAdapter
    signal_project_bindings: SignalProjectBindingService


def build_canonical_components(
    config_path="config/ai-dev-center.yml", diagnostic_trace_path: str | Path | None = None,
):
    """Compose the productive canonical adapter.

    `diagnostic_trace_path` (CLAUDE-ADC-COUNCIL-DIAGNOSTIC-TRACE-
    INTEGRATION-FIX-001): optional explicit location for the central
    app.diagnostic_trace.DiagnosticTrace's own events.jsonl (the SAME
    contract/format ProjectSetupApplicationService already writes,
    never a new sink/format). When omitted (every existing caller),
    behavior is completely unchanged: ProjectSetupApplicationService
    still derives its own default, CWD-relative path exactly as before.
    A caller that runs with a temporarily-changed working directory it
    later deletes -- Real-System-E2E's own owned temp workspace being
    the motivating case -- passes an explicit, anchored path here so
    that evidence survives its cleanup, without EngineeringCouncil or
    any other component ever opening a file itself for this."""
    config = load_ai_config(config_path)
    council_config = config.council
    if council_config is None or not council_config.enabled:
        raise WorkflowExecutionError("Engineering Council configuration must be enabled.")
    secrets = LocalSecretStore()
    provider = create_llm_provider(config, secrets)
    discovery = AIRequirementDiscovery(
        llm_provider=provider,
        ai_model=config.model,
        require_json=config.discovery.require_json,
    )
    council = EngineeringCouncil(
        council_config=council_config,
        secret_resolver=secrets,
    )
    executor = ProviderAgentExecutor(provider)
    verification_registry = build_default_registry()
    development_testing = DevelopmentTestingStage(
        DevelopmentStage(DeveloperAgent(executor)),
        TestChangeGenerator(executor), DeveloperFileApplier,
        ProjectTestRunner(), TestingStage(DiagnosisReviewer(executor)),
        verification_registry=verification_registry,
        project_inspector=ProjectInspector(),
    )
    materializer = ToolchainMaterializer()
    package_executor = PythonPackageExecutor()
    execution_state_store = SetupExecutionStateStore()
    approved_content_store = ApprovedPlanContentStore()
    workflow = DevelopmentWorkflow(
        discovery, RequirementValidator, RequirementPreflight,
        executor=package_executor, council=council,
        materializer=materializer,
        development_testing_stage=development_testing,
        execution_state_store=execution_state_store,
    )
    installers = StructuredInstallerRegistry()
    installers.register(StructuredInstallerRegistration("pip", package_executor))
    installers.register(StructuredInstallerRegistration("python_package", package_executor))
    workflow_manager = WorkflowManager()
    plan_store = WorkflowPlanStore(".workflow-plans")
    diagnostic_trace = (
        DiagnosticTrace(DiagnosticTraceStore(diagnostic_trace_path))
        if diagnostic_trace_path is not None else None
    )
    service = ProjectSetupApplicationService(
        workflow, ProjectInspector(),
        workflow_manager=workflow_manager,
        capability_registry=DEFAULT_CAPABILITY_REGISTRY,
        structured_installers=installers,
        verification_registry=verification_registry,
        project_definition_store=ProjectDefinitionStore(),
        technical_config=config,
        approved_content_store=approved_content_store,
        diagnostic_trace=diagnostic_trace,
    )
    signal_project_bindings = SignalProjectBindingService(workflow_manager)
    return CanonicalComponents(
        service, plan_store, SetupApproval, workflow,
        SignalCommunicationAdapter(
            service, plan_store, workflow_manager, signal_project_bindings,
        ),
        signal_project_bindings,
    )
