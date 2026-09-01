"""Generate structured test changes without executing or applying them."""
from app.developer_changes import DeveloperChanges


class TestChangeGenerator:
    __test__ = False
    def __init__(self, executor):
        self._executor = executor

    def generate(self, request):
        response = self._executor.run("tester", request.task, "", "tester", 0)
        return DeveloperChanges.parse(response)
