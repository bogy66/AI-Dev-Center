import pytest
from pathlib import Path
from app.test_stack_detector import TestStackDetector
from app.test_strategy import TestStrategy


class TestTestStackDetector:

    @pytest.fixture
    def detector(self):
        return TestStackDetector()

    # ------------------------------------------------------------------
    # Helper to create a minimal project root
    # ------------------------------------------------------------------
    @staticmethod
    def _create_project(tmp_path: Path) -> Path:
        # Create a basic structure (no test indicators)
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("x = 1\n")
        return tmp_path

    # ------------------------------------------------------------------
    # 1. pytest.ini
    # ------------------------------------------------------------------
    def test_pytest_ini(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pytest.ini").write_text("[pytest]\n")
        strategy = detector.detect(str(project))
        assert strategy is not None
        assert strategy.stack == "pytest"

    # ------------------------------------------------------------------
    # 2. pyproject.toml with [tool.pytest.ini_options]
    # ------------------------------------------------------------------
    def test_pyproject_toml(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\n"
        )
        strategy = detector.detect(str(project))
        assert strategy is not None
        assert strategy.stack == "pytest"

    # ------------------------------------------------------------------
    # 3. setup.cfg with [tool:pytest]
    # ------------------------------------------------------------------
    def test_setup_cfg(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "setup.cfg").write_text(
            "[tool:pytest]\n"
        )
        strategy = detector.detect(str(project))
        assert strategy is not None
        assert strategy.stack == "pytest"

    # ------------------------------------------------------------------
    # 4. requirements.txt with pytest
    # ------------------------------------------------------------------
    def test_requirements_txt(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "requirements.txt").write_text("pytest\n")
        strategy = detector.detect(str(project))
        assert strategy is not None
        assert strategy.stack == "pytest"

    # ------------------------------------------------------------------
    # 5. plausible tests/ directory
    # ------------------------------------------------------------------
    def test_plausible_tests_dir(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "tests").mkdir()
        (project / "tests" / "test_example.py").write_text(
            "def test_hello():\n    assert 1 + 1 == 2\n"
        )
        strategy = detector.detect(str(project))
        assert strategy is not None
        assert strategy.stack == "pytest"

    # ------------------------------------------------------------------
    # 6. No indicators -> None
    # ------------------------------------------------------------------
    def test_no_indicators(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        # No pytest.ini, no pyproject.toml, no setup.cfg, no requirements,
        # no tests/ directory with plausible test files.
        strategy = detector.detect(str(project))
        assert strategy is None

    # ------------------------------------------------------------------
    # 7. Single .py file alone does NOT trigger detection
    # ------------------------------------------------------------------
    def test_single_py_file_does_not_trigger(self, tmp_path: Path, detector: TestStackDetector):
        project = tmp_path / "project"
        project.mkdir()
        (project / "main.py").write_text("print('hello')\n")
        # No other indicators
        strategy = detector.detect(str(project))
        assert strategy is None

    # ------------------------------------------------------------------
    # 8. Returned TestStrategy contains all fields
    # ------------------------------------------------------------------
    def test_strategy_fields(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pytest.ini").write_text("[pytest]\n")
        strategy = detector.detect(str(project))
        assert strategy is not None
        assert isinstance(strategy, TestStrategy)
        assert strategy.stack == "pytest"
        assert strategy.level == "unit"
        assert strategy.environment == "host"
        assert strategy.command == "python -m pytest -q"

    # ------------------------------------------------------------------
    # 9. Multiple indicators work together (e.g. pytest.ini + tests/)
    # ------------------------------------------------------------------
    def test_multiple_indicators(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pytest.ini").write_text("[pytest]\n")
        (project / "tests").mkdir()
        (project / "tests" / "test_example.py").write_text(
            "def test_hello():\n    assert 1 + 1 == 2\n"
        )
        strategy = detector.detect(str(project))
        assert strategy is not None
        assert strategy.stack == "pytest"

    # ------------------------------------------------------------------
    # Edge case: tests/ directory exists but contains no test functions
    # ------------------------------------------------------------------
    def test_tests_dir_without_test_functions(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "tests").mkdir()
        (project / "tests" / "helper.py").write_text("def helper():\n    return 42\n")
        # No test functions -> not plausible
        strategy = detector.detect(str(project))
        assert strategy is None

    # ------------------------------------------------------------------
    # Edge case: requirements file does not contain pytest
    # ------------------------------------------------------------------
    def test_requirements_without_pytest(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "requirements.txt").write_text("numpy\n")
        strategy = detector.detect(str(project))
        assert strategy is None

    # ------------------------------------------------------------------
    # Edge case: pyproject.toml without pytest section
    # ------------------------------------------------------------------
    def test_pyproject_without_pytest(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pyproject.toml").write_text("[tool.black]\n")
        strategy = detector.detect(str(project))
        assert strategy is None
