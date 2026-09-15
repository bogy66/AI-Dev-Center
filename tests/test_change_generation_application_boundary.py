"""Regressions for CLAUDE-ADC-S3-CHANGE-GENERATION-APPLICATION-ARCH-FIX-001.

Productive-cycle regression: proves Development Change Generation
(DeveloperAgent) -> Change Application & Provenance Attribution
(ChangeApplicationService, development phase), then Test Change
Generation (TestChangeGenerator) -> Change Application & Provenance
Attribution (ChangeApplicationService, test phase) both flow through
ONE shared ChangeApplicationService instance for the initial cycle --
and that a subsequent controlled rework cycle reuses the exact same
instance for rework_development/rework_test, rather than any alternate
mutation path. No network, no live LLM: only deterministic fakes.
"""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from app.change_application import ChangeApplicationService
from app.controlled_rework_stage import ControlledReworkStage
from app.developer_file_applier import DeveloperFileApplier
from app.development_stage import DeveloperAgent, DevelopmentRequest, DevelopmentStage
from app.development_testing_stage import DevelopmentTestingStage
from app.test_change_generator import TestChangeGenerator
from app.testing_stage import DiagnosisReviewer, TestingStage


class _RecordingChangeApplication(ChangeApplicationService):
    """A real ChangeApplicationService that also records every call --
    proves BOTH development and test changes flow through the exact
    same shared instance and real files actually land, without
    asserting any private implementation detail."""

    def __init__(self, file_applier_factory=DeveloperFileApplier):
        super().__init__(file_applier_factory)
        self.calls = []

    def apply(self, project_path, changes, kind, is_rework, provenance_recorder=None):
        self.calls.append((kind, is_rework))
        return super().apply(project_path, changes, kind, is_rework, provenance_recorder=provenance_recorder)


class _FakeExecutor:
    """Deterministic stand-in for ProviderAgentExecutor across all three
    roles this boundary uses (developer, tester, reviewer)."""

    def __init__(self):
        self._developer_calls = 0
        self._tester_calls = 0

    def run(self, role, content, context, role_again):
        if role == "developer":
            self._developer_calls += 1
            return json.dumps({
                "changes": [{
                    "file": f"dev_{self._developer_calls}.py",
                    "action": "create", "content": "print('dev')",
                }],
                "tests": [],
            })
        if role == "tester":
            self._tester_calls += 1
            return json.dumps({
                "changes": [{
                    "file": f"test_{self._tester_calls}.py",
                    "action": "create", "content": "def test_x(): pass",
                }],
                "tests": [],
            })
        if role == "reviewer":
            return json.dumps({"decision": "accepted", "summary": "generic summary"})
        raise AssertionError(f"unexpected role: {role}")


def _build_stage(shared_change_application, executor, test_results):
    development_stage = DevelopmentStage(DeveloperAgent(executor), change_application=shared_change_application)
    test_change_generator = TestChangeGenerator(executor)
    project_test_runner = Mock()
    project_test_runner.run.side_effect = test_results
    testing_stage = TestingStage(DiagnosisReviewer(executor))
    return DevelopmentTestingStage(
        development_stage, test_change_generator, DeveloperFileApplier,
        project_test_runner, testing_stage, change_application=shared_change_application,
    )


# ---------------------------------------------------------------------
# 7: productive-cycle regression -- Development Change Generation ->
# Change Application, then Test Change Generation -> Change
# Application -> downstream
# ---------------------------------------------------------------------

def test_development_and_test_changes_share_change_application_service(tmp_path):
    shared = _RecordingChangeApplication()
    executor = _FakeExecutor()
    passing = SimpleNamespace(passed=True, timed_out=False)
    stage = _build_stage(shared, executor, [passing])
    request = DevelopmentRequest("project", tmp_path, "build a thing")

    result = stage.run(request)

    assert result.status == "accepted"
    assert shared.calls == [("development", False), ("test", False)]
    assert (tmp_path / "dev_1.py").exists()
    assert (tmp_path / "test_1.py").exists()


# ---------------------------------------------------------------------
# 8: controlled-rework regression -- same Change Application
# abstraction, rework phases
# ---------------------------------------------------------------------

def test_controlled_rework_reuses_the_same_change_application_service(tmp_path):
    shared = _RecordingChangeApplication()
    executor = _FakeExecutor()
    failing = SimpleNamespace(passed=False, timed_out=False)
    passing = SimpleNamespace(passed=True, timed_out=False)
    stage = _build_stage(shared, executor, [failing, passing])
    request = DevelopmentRequest("project", tmp_path, "build a thing")

    result = ControlledReworkStage(stage).run(request)

    assert result.rework_executed is True
    assert result.status == "accepted"
    # Exactly the productive phase sequence -- no alternate mutation path.
    assert shared.calls == [
        ("development", False), ("test", False),
        ("development", True), ("test", True),
    ]
    assert (tmp_path / "dev_1.py").exists()
    assert (tmp_path / "dev_2.py").exists()
    assert (tmp_path / "test_1.py").exists()
    assert (tmp_path / "test_2.py").exists()
