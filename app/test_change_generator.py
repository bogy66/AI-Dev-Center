"""Generate structured test changes without executing or applying them."""
from app.structured_change_generation import generate_structured_changes


class TestChangeGenerator:
    """3.2 Test Change Generation: generate structured test changes only.

    Never mutates the filesystem or provenance -- that is exclusively
    3.3's (ChangeApplicationService) responsibility.
    """
    __test__ = False
    def __init__(self, executor):
        self._executor = executor

    def generate(self, request):
        return generate_structured_changes(self._executor, "tester", request.task, "test-file changes")
