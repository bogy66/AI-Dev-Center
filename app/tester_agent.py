from app.test_runner import TestRunner
from app.specification_tester import SpecificationTester


class TesterAgent:

    def __init__(self):
        self.runner = TestRunner()
        self.specification_tester = SpecificationTester()

    def test(self, project, changes):

        result = self.runner.run(project, changes)

        if not result["success"]:
            return {
                "status": "failed",
                "result": result["stderr"]
            }

        specification = self.specification_tester.check(
            project,
            changes
        )

        if not specification["success"]:
            return {
                "status": "failed",
                "result": "\n".join(
                    specification["errors"]
                )
            }

        return {
            "status": "completed",
            "result": "PASS"
        }
