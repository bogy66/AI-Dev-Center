from app.test_runner import TestRunner


class TesterAgent:

    def __init__(self):
        self.runner = TestRunner()

    def test(self, project):
        result = self.runner.run(project)

        if result["success"]:
            return {
                "status": "completed",
                "result": "PASS"
            }

        return {
            "status": "failed",
            "result": result["stderr"]
        }
