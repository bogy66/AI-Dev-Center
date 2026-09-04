"""Generate structured test changes without executing or applying them."""
from app.developer_changes import DeveloperChanges


class TestChangeGenerator:
    __test__ = False
    def __init__(self, executor):
        self._executor = executor

    def generate(self, request):
        response = self._executor.run("tester", request.task, "", "tester")
        try:
            return DeveloperChanges.parse_structured(response)
        except ValueError as structured_error:
            repair_response = self._executor.run(
                "tester",
                (
                    "Your previous response violated the required output format. "
                    "Return ONLY a valid JSON object with exactly this structure: "
                    '{"changes": [{"file": "relative/path", "action": "create|update|delete", '
                    '"content": "complete file content"}], "tests": ["test"]}. '
                    "Include all previously identified test-file changes. "
                    "No markdown, no commentary outside the JSON."
                ),
                "",
                "tester",
            )
            try:
                return DeveloperChanges.parse_structured(repair_response)
            except ValueError:
                raise structured_error
