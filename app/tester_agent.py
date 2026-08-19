from app.test_runner import TestRunner
from app.git_manager import GitManager
from app.workflow_manager import WorkflowManager


class TesterAgent:


    def __init__(self):

        self.runner = TestRunner()
        self.git = GitManager()


    def test(
        self,
        project,
        workflow_file
    ):

        workflow = WorkflowManager(
            workflow_file
        )


        result = self.runner.run(
            project
        )


        if result["success"]:

            commit = self.git.commit_and_get_hash(
                project,
                "TEST: Validation passed"
            )


            workflow.update_agent(
                "tester",
                "completed",
                commit=commit["commit"],
                result="PASS"
            )

        else:

            workflow.update_agent(
                "tester",
                "failed",
                result=result["stderr"]
            )


        return workflow.load()
