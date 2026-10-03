"""Thin ADC Evidence adapter for the Real-System-E2E (RSE) runner.

CLAUDE-ADC-TESTBED-EVIDENCE-INFRASTRUCTURE-001, section K: RSE should
eventually be able to publish factual phase/test Evidence through the same
Evidence Contract every other ADC testbed uses -- WITHOUT this task
executing RSE, and WITHOUT changing RSE's own pass/fail semantics merely
for the sake of reporting.

This module is deliberately NOT wired into
tests/real_system/real_system_e2e.py's actual call flow in this task: that
file already carries its own pending, uncommitted changes from unrelated
work, RSE makes real paid provider calls, and this task is explicitly
forbidden from executing it. Wiring in an unexecuted call site would be
pure guesswork about hook placement with no way to verify it here.

What follows is real, independently testable code (see
test_evidence_infrastructure.py's adapter tests) that a future task can
call from RSE's own milestone/failure points with a one-line import, e.g.:

    from requirements.evidence.adapters.rse_adapter import RSEEvidenceRun
    ...
    with RSEEvidenceRun(enabled=os.environ.get("ADC_EVIDENCE_RUN") == "1") as rse_run:
        ...
        rse_run.record_phase("council", "IO")
        ...

Every method is a no-op (returns a null-ish result, never raises) when
`enabled` is False or when publishing fails -- an Evidence-publishing
problem must never be able to change RSE's own control flow or outcome.
"""
import os

from ..provenance import python_tool_versions, repository_identity, runtime_environment
from ..publisher import finalize_run, publish_test_evidence
from ..run_identity import generate_run_id

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class RSEEvidenceRun:
    """One Real-System-E2E invocation's worth of Evidence, published one
    phase at a time. `record_phase()` never raises: a publish failure is
    recorded in `self.publish_failures` and reported by the caller however
    it likes (e.g. a log line), but it can never affect RSE's own
    assertions, retries, or pass/fail outcome."""

    def __init__(self, enabled=True, producer="ADC", store_root=None, artifact_identity=None):
        self.enabled = enabled
        self.producer = producer
        self.store_root = store_root
        self.artifact_identity = artifact_identity
        self.run_id = generate_run_id() if enabled else None
        self.publish_failures = []
        self._repo_identity = None
        self._environment = None
        self._tool_versions = None

    def __enter__(self):
        if self.enabled:
            self._repo_identity = repository_identity(_REPO_ROOT)
            self._environment = runtime_environment("real_system_e2e")
            self._tool_versions = python_tool_versions()
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.enabled or self.run_id is None:
            return False
        run_status = "completed" if exc_type is None else "aborted"
        finalize_run(self.run_id, store_root=self.store_root, run_status=run_status)
        return False  # never swallow the caller's own exception

    def record_phase(self, phase, result, *, timestamp_start, timestamp_end,
                      duration=None, failure_type=None, observed_checkpoint=None,
                      command_or_procedure="tests/real_system/real_system_e2e.py"):
        """Publish one phase's Evidence. `result` must be "IO", "NIO", or
        "NOT_RUN" -- an unrecognized value is rejected by the underlying
        Contract, never silently treated as passing."""
        if not self.enabled:
            return None
        event = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "producer": self.producer,
            "test_selector": f"real_system_e2e::{phase}",
            "mapped_test_id": None,
            "result": result,
            "timestamp_start": timestamp_start,
            "timestamp_end": timestamp_end,
            "duration": duration,
            "command_or_procedure": command_or_procedure,
            "exit_code": None,
            "repository_identity": self._repo_identity,
            "artifact_identity": self.artifact_identity,
            "environment": self._environment,
            "tool_versions": self._tool_versions,
            "evidence_payload": {
                "phase": phase,
                "failure_type": failure_type,
                "observed_checkpoint": observed_checkpoint,
            },
            "raw_output_reference": None,
        }
        result_obj = publish_test_evidence(event, store_root=self.store_root)
        if not result_obj.success:
            self.publish_failures.append((phase, result_obj.errors))
        return result_obj
