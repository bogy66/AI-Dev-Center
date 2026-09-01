from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.development_stage import DevelopmentRequest
from app.development_testing_stage import DevelopmentTestingStage, DevelopmentTestingResult


def _request(tmp_path):
    return DevelopmentRequest("project", tmp_path, "add a feature")


def _stage(status="accepted", order=None):
    order = order if order is not None else []
    development_result = SimpleNamespace(status="success")
    test_changes = {"changes": [{"file": "test_feature.py", "action": "create", "content": ""}]}
    apply_result = {"applied": ["test_feature.py"], "skipped": []}
    test_result = SimpleNamespace(passed=True, timed_out=False)
    testing_result = SimpleNamespace(status=status, rework_request=object() if status == "rework_required" else None)

    development_stage = Mock()
    development_stage.run.side_effect = lambda request: (order.append("development"), development_result)[1]
    generator = Mock()
    generator.generate.side_effect = lambda request: (order.append("test_generation"), test_changes)[1]
    applier = Mock()
    applier.apply.side_effect = lambda changes: (order.append("test_apply"), apply_result)[1]
    factory = Mock(return_value=applier)
    runner = Mock()
    runner.run.side_effect = lambda request: (order.append("test_run"), test_result)[1]
    testing_stage = Mock()
    testing_stage.run.side_effect = lambda development, test: (order.append("testing_review"), testing_result)[1]

    return (
        DevelopmentTestingStage(development_stage, generator, factory, runner, testing_stage),
        development_stage,
        generator,
        factory,
        applier,
        runner,
        testing_stage,
        development_result,
        test_changes,
        apply_result,
        test_result,
        testing_result,
    )


def test_runs_canonical_stages_once_in_order_and_preserves_real_results(tmp_path):
    order = []
    values = _stage(order=order)
    stage, development, generator, factory, applier, runner, testing, dev_result, changes, apply_result, test_result, testing_result = values
    request = _request(tmp_path)

    result = stage.run(request)

    assert isinstance(result, DevelopmentTestingResult)
    assert order == ["development", "test_generation", "test_apply", "test_run", "testing_review"]
    development.run.assert_called_once_with(request)
    generator.generate.assert_called_once_with(request)
    factory.assert_called_once_with(tmp_path)
    applier.apply.assert_called_once_with(changes)
    runner.run.assert_called_once()
    assert runner.run.call_args.args[0].project_root == tmp_path
    testing.run.assert_called_once_with(dev_result, test_result)
    assert result.development_result is dev_result
    assert result.test_changes is changes
    assert result.apply_result is apply_result
    assert result.test_result is test_result
    assert result.testing_stage_result is testing_result
    assert result.status == "accepted"


def test_uses_the_same_project_root_for_test_changes_and_test_execution(tmp_path):
    values = _stage()
    stage, _, _, factory, _, runner, *_ = values

    stage.run(_request(tmp_path))

    assert factory.call_args.args[0] == tmp_path
    assert runner.run.call_args.args[0].project_root == tmp_path


def test_rework_result_is_returned_without_retrying_any_stage(tmp_path):
    values = _stage(status="rework_required")
    stage, development, generator, _, applier, runner, testing, *_, testing_result = values

    result = stage.run(_request(tmp_path))

    assert result.status == "rework_required"
    assert result.testing_stage_result.rework_request is testing_result.rework_request
    for call in (development.run, generator.generate, applier.apply, runner.run, testing.run):
        assert call.call_count == 1


def test_review_failed_is_returned_without_accepted_fallback_or_retry(tmp_path):
    values = _stage(status="review_failed")
    stage, development, generator, _, applier, runner, testing, *_, testing_result = values

    result = stage.run(_request(tmp_path))

    assert result.status == "review_failed"
    for call in (development.run, generator.generate, applier.apply, runner.run, testing.run):
        assert call.call_count == 1


@pytest.mark.parametrize("failing_component", ["development", "generator", "applier", "runner"])
def test_upstream_failure_stops_without_synthesizing_results(tmp_path, failing_component):
    values = _stage()
    stage, development, generator, _, applier, runner, testing, *_ = values
    failures = {
        "development": development.run,
        "generator": generator.generate,
        "applier": applier.apply,
        "runner": runner.run,
    }
    failures[failing_component].side_effect = RuntimeError(f"{failing_component} failed")

    with pytest.raises(RuntimeError, match=f"{failing_component} failed"):
        stage.run(_request(tmp_path))

    expected_calls = {
        "development": (1, 0, 0, 0, 0),
        "generator": (1, 1, 0, 0, 0),
        "applier": (1, 1, 1, 0, 0),
        "runner": (1, 1, 1, 1, 0),
    }[failing_component]
    actual_calls = (development.run.call_count, generator.generate.call_count, applier.apply.call_count, runner.run.call_count, testing.run.call_count)
    assert actual_calls == expected_calls
