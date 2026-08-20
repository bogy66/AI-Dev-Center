existing_state = workflow_manager.load()

if (
    existing_state.get("status") == "approval_waiting"
    and existing_state.get("developer", {}).get("commit")
):
    return existing_state
