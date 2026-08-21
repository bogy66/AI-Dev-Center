import pytest
from pathlib import Path
from unittest.mock import MagicMock
from app.test_adapters import TestAdapter
from app.test_strategy import TestStrategy
from app.test_stack_detector import TestStackDetector
from app.tester_validator import TesterValidator


class TestTesterValidator:

    # ------------------------------------------------------------------
    # Helper: create a temporary Python project with proper indicators
    # ------------------------------------------------------------------
    @pytest.fixture
    def python_project(self, tmp_path: Path) -> Path:
        # Create a minimal Python project that the detector will
        # recognise as a pytest project.
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("x = 1\n")
        # Provide a pytest.ini (strong detection indicator)
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        return tmp_path

    # ------------------------------------------------------------------
    # Helper: project with no pytest indicators (unknown stack)
    # ------------------------------------------------------------------
    @pytest.fixture
    def unknown_project(self, tmp_path: Path) -> Path:
        # Create a project that has Python files but no pytest indication
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("x = 1\n")
        # No pytest.ini, no pyproject.toml, no requirements with pytest,
        # and no tests/ directory with .py.
        return tmp_path

    # ------------------------------------------------------------------
    # 1. Python/pytest project is detected via TestStackDetector
    # ------------------------------------------------------------------
    def test_detected_via_test_stack_detector(self, python_project: Path):
        detector = TestStackDetector()
        adapter = detector.detect(str(python_project))
        assert adapter is not None

    # ------------------------------------------------------------------
    # 2. TesterValidator uses the detected adapter
    # ------------------------------------------------------------------
    def test_uses_detected_adapter(self, python_project: Path):
        validator = TesterValidator()
        changes = [
            {
                "file": "tests/test_example.py",
                "action": "create",
                "content": "def test_hello():\n    assert 1 + 1 == 2\n"
            }
        ]
        result = validator.validate(str(python_project), changes)
        assert result["success"] is True
        assert "pytest" in str(result["strategy"])

    # ------------------------------------------------------------------
    # 3. valid test file is accepted
    # ------------------------------------------------------------------
    def test_valid_test_file(self, python_project: Path):
        validator = TesterValidator()
        changes = [
            {
                "file": "tests/test_example.py",
                "action": "create",
                "content": "def test_hello():\n    assert 1 + 1 == 2\n"
            }
        ]
        result = validator.validate(str(python_project), changes)
        assert result["success"] is True
        assert result["errors"] == []
        assert result["strategy"] is not None
        assert result["strategy"].stack == "pytest"

    # ------------------------------------------------------------------
    # 4. invalid / non-test file is rejected
    # ------------------------------------------------------------------
    def test_invalid_test_file(self, python_project: Path):
        validator = TesterValidator()
        changes = [
            {
                "file": "app/example.py",
                "action": "create",
                "content": "def test_hello():\n    pass\n"
            }
        ]
        result = validator.validate(str(python_project), changes)
        assert result["success"] is False
        assert any("not a valid test file" in err for err in result["errors"])

    # ------------------------------------------------------------------
    # 5. unknown test stack is cleanly rejected
    # ------------------------------------------------------------------
    def test_unknown_stack(self, unknown_project: Path):
        validator = TesterValidator()
        changes = [
            {
                "file": "tests/test_example.py",
                "action": "create",
                "content": "print('hello')"
            }
        ]
        result = validator.validate(str(unknown_project), changes)
        assert result["success"] is False
        assert "Kein unterstützter Test-Stack erkannt." in result["errors"]
        assert result["strategy"] is None

    # ------------------------------------------------------------------
    # 6. validator does NOT contain own pytest stack detection
    # ------------------------------------------------------------------
    def test_does_not_contain_pytest_detection(self):
        import inspect
        source = inspect.getsource(TesterValidator)
        # The validator should not contain any pytest-specific
        # detection logic.
        assert "pytest.ini" not in source
        assert "pyproject.toml" not in source
        assert "setup.cfg" not in source
        assert "requirements" not in source
        assert "def test_" not in source
        assert "test_*.py" not in source

    # ------------------------------------------------------------------
    # 7. level/environment are forwarded to adapter.get_strategy()
    # ------------------------------------------------------------------
    def test_level_environment_are_forwarded(self, python_project: Path):
        validator = TesterValidator()
        changes = [
            {
                "file": "tests/test_example.py",
                "action": "create",
                "content": "def test_hello():\n    assert 1 + 1 == 2\n"
            }
        ]
        result = validator.validate(
            str(python_project),
            changes,
            level="integration",
            environment="container"
        )
        assert result["success"] is True
        assert result["strategy"] is not None
        assert result["strategy"].level == "integration"
        assert result["strategy"].environment == "container"

    # ------------------------------------------------------------------
    # 8. adapter errors are cleanly handled
    # ------------------------------------------------------------------
    def test_adapter_errors_are_handled(self, python_project: Path):
        validator = TesterValidator()
        changes = [
            {
                "file": "tests/test_bad_syntax.py",
                "action": "create",
                "content": "def test_hello()\n    assert 1 + 1 == 2\n"
            }
        ]
        result = validator.validate(str(python_project), changes)
        assert result["success"] is False
        assert any("Syntax error" in err for err in result["errors"])
