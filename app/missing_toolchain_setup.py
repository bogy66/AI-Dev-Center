"""Central, approval-gated bridge from TOOL_UNAVAILABLE to verification retry."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import shutil

from app.council_models import CouncilResult
from app.requirement_model import SetupPlan, SetupStep
from app.setup_executor import ExecutionResult
from app.verification import TOOL_UNAVAILABLE, VerificationPlan, VerificationResult, VerificationStep


class MissingToolchainSetupError(Exception):
    pass


@dataclass(frozen=True)
class MissingToolchainSetupRequest:
    project_id: str
    project_root: str
    toolchain: str
    operation_type: str
    council_result: CouncilResult
    verification_plan: VerificationPlan
    verification_result: VerificationResult


@dataclass(frozen=True)
class MissingToolchainSetupResult:
    plan_id: str
    status: str
    setup_result: ExecutionResult | None = None
    verification_result: VerificationResult | None = None
    blockers: tuple[str, ...] = ()


def already_available_setup_result(step_id: str) -> ExecutionResult:
    """Return the existing setup execution contract for a safe no-op."""
    return ExecutionResult(
        step_id=step_id,
        success=True,
        message="toolchain already available",
        verification_passed=True,
    )


@dataclass(frozen=True)
class StructuredInstallerRegistration:
    install_method: str
    executor: object
    availability_checker: object = shutil.which

    def is_available(self, toolchain: str) -> bool:
        return self.availability_checker(toolchain) is not None


class StructuredInstallerRegistry:
    """Trusted installer implementations; registrations contain no command argv."""
    def __init__(self):
        self._installers: dict[str, StructuredInstallerRegistration] = {}

    def register(self, registration: StructuredInstallerRegistration) -> None:
        if not registration.install_method or registration.install_method in self._installers:
            raise ValueError("Installer method is empty or already registered")
        self._installers[registration.install_method] = registration

    def get(self, install_method: str) -> StructuredInstallerRegistration | None:
        return self._installers.get(install_method)


def serialize_setup_plan(plan: SetupPlan) -> dict:
    return {
        "id": plan.id, "project_id": plan.project_id, "status": plan.status,
        "requires_user_approval": plan.requires_user_approval,
        "steps": [asdict(step) for step in plan.steps],
    }


def deserialize_setup_plan(data: dict) -> SetupPlan:
    return SetupPlan(
        id=data["id"], project_id=data["project_id"],
        steps=tuple(SetupStep(**step) for step in data["steps"]),
        requires_user_approval=data.get("requires_user_approval", True),
        status=data["status"],
    )


def serialize_verification_plan(plan: VerificationPlan) -> dict:
    return {
        "run_id": plan.run_id, "project_root": plan.project_root,
        "project_kind": plan.project_kind, "area_count": plan.area_count,
        "steps": [asdict(step) for step in plan.steps],
    }


def deserialize_verification_plan(data: dict) -> VerificationPlan:
    return VerificationPlan(
        run_id=data["run_id"], project_root=data["project_root"],
        project_kind=data["project_kind"], area_count=data["area_count"],
        steps=tuple(VerificationStep(**step) for step in data["steps"]),
    )
