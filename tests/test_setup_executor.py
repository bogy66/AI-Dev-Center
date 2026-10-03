import pytest
from app.setup_executor import SetupExecutor, ExecutionResult, StepNotApprovedError
from app.requirement_model import SetupStep


def make_step(step_id="1", is_approved=True):
    return SetupStep(
        id=step_id,
        requirement_id="req-1",
        action="install",
        install_method="pip",
        package="some-pkg",
        version="1.0",
        command="pip install some-pkg",
        verification_after="some-pkg --version",
        is_approved=is_approved,
    )


class TestSetupExecutor:
    def test_unapproved_step_raises_error(self):
        executor = SetupExecutor()
        step = make_step(is_approved=False)
        with pytest.raises(StepNotApprovedError) as exc_info:
            executor.execute_step(step)
        assert step.id in str(exc_info.value)

    def test_approved_step_returns_result(self):
        executor = SetupExecutor()
        step = make_step(is_approved=True)
        result = executor.execute_step(step)
        assert isinstance(result, ExecutionResult)
        assert result.step_id == step.id
        assert result.success is False
        assert result.verification_passed is False
        assert result.message == "execution backend not implemented"

    def test_step_not_modified(self):
        executor = SetupExecutor()
        step = make_step(is_approved=True)
        # capture original attributes
        original = {
            "id": step.id,
            "requirement_id": step.requirement_id,
            "action": step.action,
            "install_method": step.install_method,
            "package": step.package,
            "version": step.version,
            "command": step.command,
            "verification_after": step.verification_after,
            "is_approved": step.is_approved,
        }
        executor.execute_step(step)
        # step is a frozen dataclass, so it cannot be modified anyway.
        assert step.id == original["id"]
        assert step.requirement_id == original["requirement_id"]
        assert step.action == original["action"]
        assert step.install_method == original["install_method"]
        assert step.package == original["package"]
        assert step.version == original["version"]
        assert step.command == original["command"]
        assert step.verification_after == original["verification_after"]
        assert step.is_approved == original["is_approved"]

    def test_multiple_approved_steps(self):
        executor = SetupExecutor()
        step1 = make_step(step_id="1", is_approved=True)
        step2 = make_step(step_id="2", is_approved=True)
        result1 = executor.execute_step(step1)
        result2 = executor.execute_step(step2)
        assert result1.step_id == "1"
        assert result2.step_id == "2"
        assert result1.success is False
        assert result2.success is False
        assert result1.message == "execution backend not implemented"
        assert result2.message == "execution backend not implemented"

    def test_unapproved_step_error_message_contains_step_id(self):
        executor = SetupExecutor()
        step = make_step(step_id="abc", is_approved=False)
        with pytest.raises(StepNotApprovedError, match="abc"):
            executor.execute_step(step)
