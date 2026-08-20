def publish(self, project):

    state = self.workflow.load()

    if state["status"] != "approval_waiting":
        return state

    if state["user_approval"]["status"] != "approved":
        return state
    ...
