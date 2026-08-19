from app.git_manager import GitManager
from app.workflow_manager import WorkflowManager


class ReviewerAgent:


    def __init__(self):

        self.git = GitManager()



    def review(
        self,
        project,
        workflow_file
    ):

        workflow = WorkflowManager(
            workflow_file
        )


        state = workflow.load()


        result = {
            "status": "changes_required",
            "message": ""
        }


        # Testergebnis prüfen

        if state["tester"]["status"] != "completed":

            result["message"] = (
                "Testergebnis fehlt"
            )

            workflow.update_agent(
                "reviewer",
                "changes_required",
                result=result["message"]
            )

            return workflow.load()



        if state["tester"]["result"] != "PASS":

            result["message"] = (
                "Tests nicht erfolgreich"
            )

            workflow.update_agent(
                "reviewer",
                "changes_required",
                result=result["message"]
            )

            return workflow.load()



        # Git Diff prüfen

        diff = self.git.diff(
            project
        )


        if diff["code"] != 0:

            workflow.update_agent(
                "reviewer",
                "changes_required",
                result=diff["stderr"]
            )

            return workflow.load()



        # Alles OK

        workflow.update_agent(
            "reviewer",
            "approved",
            result="Review erfolgreich"
        )


        return workflow.load()
