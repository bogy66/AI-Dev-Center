"""Run-specific human approval contract for remote publication."""
from dataclasses import dataclass


class PublishApprovalError(Exception):
    pass


@dataclass(frozen=True)
class PublishApprovalResult:
    run_id: str
    status: str
    applicable: bool
    ready_for_publish: bool


def result_from_record(run_id, record):
    return PublishApprovalResult(
        run_id=run_id,
        status=record["status"],
        applicable=True,
        ready_for_publish=record.get("ready_for_publish") is True,
    )
