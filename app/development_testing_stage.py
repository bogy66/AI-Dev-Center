"""Canonical coordination of existing development and testing stages."""
from dataclasses import dataclass

from app.project_test_runner import TestExecutionRequest


@dataclass(frozen=True)
class DevelopmentTestingResult:
    development_result: object
    test_changes: dict
    apply_result: dict
    test_result: object
    testing_stage_result: object

    @property
    def status(self) -> str:
        """Expose the testing decision without introducing a second policy."""
        return self.testing_stage_result.status


class DevelopmentTestingStage:
    def __init__(self, development_stage, test_change_generator, file_applier_factory, project_test_runner, testing_stage):
        self._development_stage = development_stage
        self._test_change_generator = test_change_generator
        self._file_applier_factory = file_applier_factory
        self._project_test_runner = project_test_runner
        self._testing_stage = testing_stage

    def run(self, request):
        development_result = self._development_stage.run(request)
        test_changes = self._test_change_generator.generate(request)
        applier = self._file_applier_factory(request.project_path)
        phase = "rework_test" if getattr(request, "rework_request", None) else "test"
        apply_result = request.provenance_recorder.apply(applier, test_changes, phase) if getattr(request, "provenance_recorder", None) else applier.apply(test_changes)
        test_result = self._project_test_runner.run(TestExecutionRequest(request.project_path))
        stage_result = self._testing_stage.run(development_result, test_result)
        return DevelopmentTestingResult(development_result, test_changes, apply_result, test_result, stage_result)
