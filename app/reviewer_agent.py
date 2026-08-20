from app.git_manager import GitManager


class ReviewerAgent:

    def __init__(self):
        self.git = GitManager()

    def review(self, project, state):

        if state["tester"]["status"] != "completed":
            return {
                "status": "changes_required",
                "result": "Testergebnis fehlt"
            }

        if state["tester"]["result"] != "PASS":
            return {
                "status": "changes_required",
                "result": "Tests nicht erfolgreich"
            }

        diff = self.git.diff(project)

        if diff["code"] != 0:
            return {
                "status": "review_failed",
                "result": diff["stderr"]
            }

        return {
            "status": "approved",
            "result": "Review erfolgreich"
        }
