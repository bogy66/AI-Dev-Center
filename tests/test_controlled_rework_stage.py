from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.controlled_rework_stage import ControlledReworkStage, ReworkDevelopmentRequest
from app.development_stage import DevelopmentRequest
from app.development_testing_stage import DevelopmentTestingResult
from app.testing_stage import ReworkRequest


def _result(status, label):
    development = SimpleNamespace(label=f"{label}-development")
    test = SimpleNamespace(label=f"{label}-test")
    review = SimpleNamespace(status=status, rework_request=None)
    if status == "rework_required":
        review.rework_request = ReworkRequest(
            reason="tests require rework",
            diagnostics="failing assertion",
            development_result=development,
            test_result=test,
        )
    return DevelopmentTestingResult(
        development_result=development,
        test_changes={"changes": [{"file": f"{label}.py"}]},
        apply_result={"applied": [f"{label}.py"], "skipped": []},
        test_result=test,
        testing_stage_result=review,
    )


def _request(tmp_path):
    return DevelopmentRequest("project", tmp_path, "implement feature")


def test_accepted_initial_result_does_not_start_rework(tmp_path):
    initial = _result("accepted", "initial")
    stage = Mock()
    stage.run.return_value = initial

    result = ControlledReworkStage(stage).run(_request(tmp_path))

    assert result.initial_result is initial
    assert result.final_result is initial
    assert result.status == "accepted"
    assert result.rework_executed is False
    stage.run.assert_called_once()


def test_review_failed_initial_result_does_not_start_rework(tmp_path):
    initial = _result("review_failed", "initial")
    stage = Mock()
    stage.run.return_value = initial

    result = ControlledReworkStage(stage).run(_request(tmp_path))

    assert result.status == "review_failed"
    assert result.rework_executed is False
    stage.run.assert_called_once()


@pytest.mark.parametrize("final_status", ["accepted", "rework_required", "review_failed"])
def test_rework_runs_the_existing_stage_exactly_once_more_and_preserves_results(tmp_path, final_status):
    initial = _result("rework_required", "initial")
    rework = _result(final_status, "rework")
    stage = Mock()
    stage.run.side_effect = [initial, rework]
    request = _request(tmp_path)

    result = ControlledReworkStage(stage).run(request)

    assert result.initial_result is initial
    assert result.rework_result is rework
    assert result.final_result is rework
    assert result.status == final_status
    assert result.rework_executed is True
    assert result.rework_request is initial.testing_stage_result.rework_request
    assert result.rework_development_result is rework.development_result
    assert result.rework_test_changes is rework.test_changes
    assert result.rework_apply_result is rework.apply_result
    assert result.rework_test_result is rework.test_result
    assert result.rework_testing_stage_result is rework.testing_stage_result
    assert stage.run.call_count == 2
    rework_request = stage.run.call_args_list[1].args[0]
    assert isinstance(rework_request, ReworkDevelopmentRequest)
    assert rework_request.original_request is request
    assert rework_request.project_path == request.project_path
    assert rework_request.rework_request is result.rework_request
    assert "failing assertion" in rework_request.task


@pytest.mark.parametrize("error", ["developer failed", "apply failed", "runner failed", "review failed"])
def test_rework_technical_errors_propagate_without_a_third_cycle(tmp_path, error):
    initial = _result("rework_required", "initial")
    stage = Mock()
    stage.run.side_effect = [initial, RuntimeError(error)]

    with pytest.raises(RuntimeError, match=error):
        ControlledReworkStage(stage).run(_request(tmp_path))

    assert stage.run.call_count == 2


def test_rework_requires_the_actual_structured_rework_request(tmp_path):
    initial = _result("rework_required", "initial")
    initial.testing_stage_result.rework_request = None
    stage = Mock()
    stage.run.return_value = initial

    with pytest.raises(ValueError, match="missing a ReworkRequest"):
        ControlledReworkStage(stage).run(_request(tmp_path))

    stage.run.assert_called_once()
