"""Final human approval contracts, independent of Git and toolchains."""
from dataclasses import dataclass


class FinalApprovalError(Exception):
    pass


@dataclass(frozen=True)
class FinalApprovalResult:
    run_id: str
    status: str
    applicable: bool
    ready_for_git: bool


def result_from_record(run_id, record):
    status = record["status"]
    return FinalApprovalResult(
        run_id=run_id,
        status=status,
        applicable=True,
        ready_for_git=status == "approved",
    )
