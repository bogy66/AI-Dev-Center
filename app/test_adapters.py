from abc import ABC, abstractmethod
import re
from app.test_strategy import TestStrategy


class TestAdapter(ABC):
    """Abstract base class for test-stack adapters.

    Subclasses must implement all abstract methods.
    The interface is intentionally free of any Python/pytest or
    ESPHome/ESP32 assumptions.
    """

    @abstractmethod
    def detect(self, project_root: str) -> bool:
        """Return True if the project at *project_root* uses this test stack."""
        ...

    @abstractmethod
    def get_strategy(self, level: str = "unit", environment: str = "host") -> TestStrategy:
        """Return a TestStrategy describing how tests should be run.

        *level* and *environment* are free‑form strings that the
        concrete adapter may interpret as appropriate.
        """
        ...

    @abstractmethod
    def is_test_file(self, file_path: str) -> bool:
        """Return True if *file_path* is a valid test file location for this stack."""
        ...

    @abstractmethod
    def validate_test_file(self, file_path: str, content: str) -> dict:
        """Validate the content of a single test file.

        Return a dict with keys:
            success (bool)
            errors (list[str])
        """
        ...

    @abstractmethod
    def get_command(self, level: str = "unit", environment: str = "host") -> str:
        """Return the concrete test command for the given *level* and *environment*."""
        ...


class PythonPytestAdapter(TestAdapter):
    """Adapter for Python projects using pytest."""

    def detect(self, project_root: str) -> bool:
        # For now, we do not implement detection logic here.
        # The TestStackDetector will handle detection.
        # This method is required by the interface.
        return False

    def is_test_file(self, file_path: str) -> bool:
        # Typical pytest file names: test_*.py or *_test.py
        if not file_path.endswith(".py"):
            return False
        basename = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        return bool(re.match(r"^(test_.+\.py|.+_test\.py)$", basename))

    def validate_test_file(self, file_path: str, content: str) -> dict:
        errors = []

        # 1. Syntax check
        try:
            compile(content, file_path, "exec")
        except SyntaxError as e:
            errors.append(f"Syntax error in '{file_path}': {e}")
            return {"success": False, "errors": errors}

        # 2. Presence of pytest test functions or classes
        if not re.search(r"def test_", content) and not re.search(r"class Test", content):
            errors.append(
                f"File '{file_path}' does not contain any pytest test "
                f"(no 'def test_' function or 'class Test' class)."
            )

        success = len(errors) == 0
        return {"success": success, "errors": errors}

    def get_strategy(self, level: str = "unit", environment: str = "host") -> TestStrategy:
        return TestStrategy(
            stack="pytest",
            level=level,
            environment=environment,
            command="python -m pytest -q"
        )

    def get_command(self, level: str = "unit", environment: str = "host") -> str:
        return "python -m pytest -q"
