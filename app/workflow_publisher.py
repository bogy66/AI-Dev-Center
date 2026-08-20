from app.git_manager import GitManager
from app.workflow_manager import WorkflowManager


class WorkflowPublisher:

    def __init__(
        self,
        workflow_manager: WorkflowManager,
        git_manager: GitManager
    ):
        self.workflow = workflow_manager
        self.git = git_manager

    def publish(self, project):

        state = self.workflow.load()

        if state["status"] != "approval_waiting":
            return state

        if state["user_approval"]["status"] != "approved":
            return state

        result = self.git.push(project)

        if result["code"] != 0:
            return state

        state["status"] = "completed"

        self.workflow.save(state)

        return state
