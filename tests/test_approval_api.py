import pytest
from fastapi.testclient import TestClient
from app.api import app


client = TestClient(app)


def test_get_approval_status():
    response = client.get("/approval")
    assert response.status_code == 200
    assert "status" in response.json()



def test_approve_approval():
    response = client.post("/approval/approve", json={"approved_by": "Udo", "comment": "Looks good"})
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["approved_by"] == "Udo"
    assert response.json()["comment"] == "Looks good"


def test_reject_approval():
    response = client.post("/approval/reject", json={"approved_by": "Udo", "comment": "Needs changes"})
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["approved_by"] == "Udo"
    assert response.json()["comment"] == "Needs changes"
