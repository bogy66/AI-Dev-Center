"""Shared composition root for every productive canonical adapter."""
from dataclasses import dataclass

from app.agent_executor import AgentExecutor
from app.ai_config import load_ai_config
from app.ai_requirement_discovery import AIRequirementDiscovery
from app.dev_workflow import DevelopmentWorkflow, WorkflowExecutionError
from app.development_stage import DeveloperAgent, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.developer_file_applier import DeveloperFileApplier
from app.engineering_council import EngineeringCouncil
from app.llm_provider_factory import create_llm_provider
from app.local_secret_store import LocalSecretStore
from app.project_inspector import ProjectInspector
from app.project_setup_application import ProjectSetupApplicationService
from app.project_test_runner import ProjectTestRunner
from app.python_package_executor import PythonPackageExecutor
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
from app.workflow_manager import WorkflowManager


@dataclass(frozen=True)
class CanonicalComponents:
    service: ProjectSetupApplicationService
    plan_store: WorkflowPlanStore
    approval: object
    development_workflow: DevelopmentWorkflow
    signal_adapter: SignalCommunicationAdapter


def build_canonical_components(config_path="config/ai-dev-center.yml"):
    config = load_ai_config(config_path)
    council_config = config.council
    if council_config is None or not council_config.enabled:
        raise WorkflowExecutionError("Engineering Council configuration must be enabled.")
    secrets = LocalSecretStore()
    provider = create_llm_provider(config, secrets)
    discovery = AIRequirementDiscovery(
        llm_provider=provider,
        ai_model=config.model,
    )
    council = EngineeringCouncil(
        council_config=council_config,
        secret_resolver=secrets,
    )
    executor = AgentExecutor(model=config.model)
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
    workflow = DevelopmentWorkflow(
        discovery, RequirementValidator, RequirementPreflight,
        executor=package_executor, council=council,
        materializer=materializer,
        development_testing_stage=development_testing,
    )
    installers = StructuredInstallerRegistry()
    installers.register(StructuredInstallerRegistration("pip", package_executor))
    installers.register(StructuredInstallerRegistration("python_package", package_executor))
    workflow_manager = WorkflowManager()
    plan_store = WorkflowPlanStore(".workflow-plans")
    service = ProjectSetupApplicationService(
        workflow, ProjectInspector(),
        workflow_manager=workflow_manager,
        capability_registry=DEFAULT_CAPABILITY_REGISTRY,
        structured_installers=installers,
        verification_registry=verification_registry,
        project_definition_store=ProjectDefinitionStore(),
        technical_config=config,
    )
    return CanonicalComponents(
        service, plan_store, SetupApproval, workflow,
        SignalCommunicationAdapter(service, plan_store, workflow_manager),
    )
