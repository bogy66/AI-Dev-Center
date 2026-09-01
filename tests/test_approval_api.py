import pytest

from app.api import ApprovalRequest, approve_approval, get_approval_status
from app.api import reject_approval


def test_legacy_approval_status_contract_is_deprecated():
    response = get_approval_status()
    assert response.status_code == 409
    assert b'deprecated_unsafe_contract' in response.body


@pytest.mark.parametrize("action", [approve_approval, reject_approval])
def test_legacy_approval_mutations_cannot_bypass_plan_specific_approval(action):
    payload = ApprovalRequest(approved_by="Udo", comment="reviewed")
    response = action(payload)
    assert response.status_code == 409
    assert b'run/plan-specific' in response.body
