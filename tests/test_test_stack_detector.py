import pytest
from pathlib import Path
from app.test_stack_detector import TestStackDetector
from app.test_adapters import PythonPytestAdapter
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
        adapter = detector.detect(str(project))
        assert adapter is not None
        assert isinstance(adapter, PythonPytestAdapter)
        strategy = adapter.get_strategy()
        assert strategy.stack == "pytest"

    # ------------------------------------------------------------------
    # 2. pyproject.toml with [tool.pytest.ini_options]
    # ------------------------------------------------------------------
    def test_pyproject_toml(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\n"
        )
        adapter = detector.detect(str(project))
        assert adapter is not None
        assert isinstance(adapter, PythonPytestAdapter)

    # ------------------------------------------------------------------
    # 3. setup.cfg with [tool:pytest]
    # ------------------------------------------------------------------
    def test_setup_cfg(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "setup.cfg").write_text(
            "[tool:pytest]\n"
        )
        adapter = detector.detect(str(project))
        assert adapter is not None
        assert isinstance(adapter, PythonPytestAdapter)

    # ------------------------------------------------------------------
    # 4. requirements.txt with pytest
    # ------------------------------------------------------------------
    def test_requirements_txt(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "requirements.txt").write_text("pytest\n")
        adapter = detector.detect(str(project))
        assert adapter is not None
        assert isinstance(adapter, PythonPytestAdapter)

    # ------------------------------------------------------------------
    # 5. plausible tests/ directory
    # ------------------------------------------------------------------
    def test_plausible_tests_dir(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "tests").mkdir()
        (project / "tests" / "test_example.py").write_text(
            "def test_hello():\n    assert 1 + 1 == 2\n"
        )
        adapter = detector.detect(str(project))
        assert adapter is not None
        assert isinstance(adapter, PythonPytestAdapter)

    # ------------------------------------------------------------------
    # 6. No indicators -> None
    # ------------------------------------------------------------------
    def test_no_indicators(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        adapter = detector.detect(str(project))
        assert adapter is None

    # ------------------------------------------------------------------
    # 7. Single .py file alone does NOT trigger detection
    # ------------------------------------------------------------------
    def test_single_py_file_does_not_trigger(self, tmp_path: Path, detector: TestStackDetector):
        project = tmp_path / "project"
        project.mkdir()
        (project / "main.py").write_text("print('hello')\n")
        adapter = detector.detect(str(project))
        assert adapter is None

    # ------------------------------------------------------------------
    # 8. Returned adapter is an instance of PythonPytestAdapter
    # ------------------------------------------------------------------
    def test_adapter_instance(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pytest.ini").write_text("[pytest]\n")
        adapter = detector.detect(str(project))
        assert isinstance(adapter, PythonPytestAdapter)

    # ------------------------------------------------------------------
    # 9. Over the adapter, get_strategy can be called
    # ------------------------------------------------------------------
    def test_get_strategy_via_adapter(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pytest.ini").write_text("[pytest]\n")
        adapter = detector.detect(str(project))
        strategy = adapter.get_strategy()
        assert isinstance(strategy, TestStrategy)

    # ------------------------------------------------------------------
    # 10. get_strategy() yields stack="pytest"
    # ------------------------------------------------------------------
    def test_strategy_stack_pytest(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pytest.ini").write_text("[pytest]\n")
        adapter = detector.detect(str(project))
        strategy = adapter.get_strategy()
        assert strategy.stack == "pytest"
        assert strategy.level == "unit"
        assert strategy.environment == "host"
        assert strategy.command == "python -m pytest -q"

    # ------------------------------------------------------------------
    # Edge case: tests/ directory exists but contains no test functions
    # ------------------------------------------------------------------
    def test_tests_dir_without_test_functions(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "tests").mkdir()
        (project / "tests" / "helper.py").write_text("def helper():\n    return 42\n")
        adapter = detector.detect(str(project))
        assert adapter is None

    # ------------------------------------------------------------------
    # Edge case: requirements file does not contain pytest
    # ------------------------------------------------------------------
    def test_requirements_without_pytest(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "requirements.txt").write_text("numpy\n")
        adapter = detector.detect(str(project))
        assert adapter is None

    # ------------------------------------------------------------------
    # Edge case: pyproject.toml without pytest section
    # ------------------------------------------------------------------
    def test_pyproject_without_pytest(self, tmp_path: Path, detector: TestStackDetector):
        project = self._create_project(tmp_path)
        (project / "pyproject.toml").write_text("[tool.black]\n")
        adapter = detector.detect(str(project))
        assert adapter is None
