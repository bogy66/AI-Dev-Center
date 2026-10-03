from app.common_request import CommonRequest, RequestIntent


def test_common_request_contains_normalized_planning_input():
    project_info = {"project_id": "demo", "files": []}

    request = CommonRequest(
        project_id="demo",
        project_info=project_info,
        intent=RequestIntent.PLAN_PROJECT_SETUP,
    )

    assert request.project_id == "demo"
    assert request.project_info is project_info
    assert request.intent is RequestIntent.PLAN_PROJECT_SETUP


def test_common_request_preserves_adapter_neutral_user_intent():
    request = CommonRequest(
        project_id="demo", project_info={"project_kind": "existing"},
        intent=RequestIntent.PLAN_PROJECT_SETUP,
        user_request="Repair the existing project",
        source_interface="web",
    )

    assert request.user_request == "Repair the existing project"
    assert request.source_interface == "web"
    assert request.project_info == {"project_kind": "existing"}


def test_common_requests_do_not_share_project_info_defaults():
    first = CommonRequest("one", {"files": []}, RequestIntent.PLAN_PROJECT_SETUP)
    second = CommonRequest("two", {"files": []}, RequestIntent.PLAN_PROJECT_SETUP)

    first.project_info["files"].append({"path": "a.py"})

    assert second.project_info["files"] == []
