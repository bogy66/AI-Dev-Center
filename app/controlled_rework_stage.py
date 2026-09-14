"""A bounded, contract-preserving rework cycle for canonical testing."""
from dataclasses import dataclass

from app.development_stage import DevelopmentRequest
from app.development_testing_stage import DevelopmentTestingResult
from app.testing_stage import ReworkRequest


@dataclass(frozen=True)
class ReworkDevelopmentRequest:
    """Structured developer input derived from an actual rework decision."""

    original_request: DevelopmentRequest
    previous_development_result: object
    previous_test_result: object
    previous_testing_stage_result: object
    rework_request: ReworkRequest

    @property
    def project_id(self):
        return self.original_request.project_id

    @property
    def project_path(self):
        return self.original_request.project_path

    @property
    def task(self):
        return (
            f"{self.original_request.task}\n\n"
            f"Rework required: {self.rework_request.reason}\n"
            f"Diagnostics: {self.rework_request.diagnostics}"
        )

    @property
    def run_id(self): return self.original_request.run_id

    @property
    def provenance_recorder(self): return self.original_request.provenance_recorder


@dataclass(frozen=True)
class ControlledReworkResult:
    """Preserve the initial result and, at most, one real rework result."""

    initial_result: DevelopmentTestingResult
    rework_executed: bool
    rework_request: ReworkRequest | None = None
    rework_result: DevelopmentTestingResult | None = None

    @property
    def final_result(self) -> DevelopmentTestingResult:
        return self.rework_result or self.initial_result

    @property
    def status(self) -> str:
        return self.final_result.status

    @property
    def rework_development_result(self):
        return self.rework_result.development_result if self.rework_result else None

    @property
    def rework_test_changes(self):
        return self.rework_result.test_changes if self.rework_result else None

    @property
    def rework_apply_result(self):
        return self.rework_result.apply_result if self.rework_result else None

    @property
    def rework_test_result(self):
        return self.rework_result.test_result if self.rework_result else None

    @property
    def rework_testing_stage_result(self):
        return self.rework_result.testing_stage_result if self.rework_result else None


class ControlledReworkStage:
    """Run one initial cycle and at most one rework cycle."""

    def __init__(self, development_testing_stage):
        self._development_testing_stage = development_testing_stage

    def run(self, request: DevelopmentRequest) -> ControlledReworkResult:
        initial_result = self._development_testing_stage.run(request)
        if initial_result.status != "rework_required":
            return ControlledReworkResult(initial_result, False)

        rework_request = initial_result.testing_stage_result.rework_request
        if rework_request is None:
            raise ValueError("rework_required result is missing a ReworkRequest")

        rework_development_request = ReworkDevelopmentRequest(
            original_request=request,
            previous_development_result=initial_result.development_result,
            previous_test_result=initial_result.test_result,
            previous_testing_stage_result=initial_result.testing_stage_result,
            rework_request=rework_request,
        )
        try:
            rework_result = self._development_testing_stage.run(rework_development_request)
        except Exception as error:
            # CLAUDE-E2E-NIO-007A: a Real-System-E2E failed with a
            # terminal provider exception (OpenRouterError) raised
            # DURING this exact rework attempt, well after a real
            # ESPHome verification failure had already produced
            # initial_result/rework_request -- the very reason rework
            # was attempted in the first place. Uncaught, this method
            # would propagate the exception with initial_result and
            # rework_request as plain local variables the caller can
            # never see again -- silently erasing the last meaningful
            # engineering failure (e.g. "esphome-validate failed and
            # esphome-compile was blocked") behind a bare infrastructure
            # error. Attaching them to the exception (not raising a new,
            # narrower one) preserves the original exception type/chain
            # exactly as before for any caller that does not need this
            # evidence, while making it available, safely (only already
            # ADC-produced diagnostic text -- never a raw provider
            # response or secret), to any caller that does.
            error.controlled_rework_initial_result = initial_result
            error.controlled_rework_request = rework_request
            raise
        return ControlledReworkResult(
            initial_result=initial_result,
            rework_executed=True,
            rework_request=rework_request,
            rework_result=rework_result,
        )
