from pathlib import Path
from app.test_adapters import PythonPytestAdapter, ESPHomeAdapter


class TestStackDetector:
    """Detects the test stack used by a project and returns a corresponding
    TestAdapter instance.
    """

    def detect(self, project_root: str) -> PythonPytestAdapter | ESPHomeAdapter | None:
        """
        Examine the project at *project_root* and return a TestAdapter
        if a supported test stack is recognised, otherwise None.

        Currently supports:
        - Python / pytest (via PythonPytestAdapter)
        - ESPHome (via ESPHomeAdapter)
        """
        root = Path(project_root)
        if not root.is_dir():
            return None

        # 1. Try Python/pytest detection
        if self._has_pytest_ini(root):
            return PythonPytestAdapter()

        if self._has_pyproject_with_pytest(root):
            return PythonPytestAdapter()

        if self._has_setup_cfg_with_pytest(root):
            return PythonPytestAdapter()

        if self._has_requirements_with_pytest(root):
            return PythonPytestAdapter()

        if self._has_plausible_tests_dir(root):
            return PythonPytestAdapter()

        # 2. Try ESPHome detection (uses ESPHomeAdapter.detect)
        esphome_adapter = ESPHomeAdapter()
        if esphome_adapter.detect(str(root)):
            return esphome_adapter

        return None

    # ------------------------------------------------------------------
    # Internal helpers (unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    def _has_pytest_ini(root: Path) -> bool:
        return (root / "pytest.ini").exists()

    @staticmethod
    def _has_pyproject_with_pytest(root: Path) -> bool:
        pyproject = root / "pyproject.toml"
        if not pyproject.exists():
            return False
        try:
            text = pyproject.read_text(encoding="utf-8")
            return "[tool.pytest.ini_options]" in text
        except Exception:
            return False

    @staticmethod
    def _has_setup_cfg_with_pytest(root: Path) -> bool:
        setup_cfg = root / "setup.cfg"
        if not setup_cfg.exists():
            return False
        try:
            import configparser
            parser = configparser.ConfigParser()
            parser.read_string(setup_cfg.read_text(encoding="utf-8"))
            return parser.has_section("tool:pytest")
        except Exception:
            return False

    @staticmethod
    def _has_requirements_with_pytest(root: Path) -> bool:
        for req in root.glob("requirements*.txt"):
            try:
                if "pytest" in req.read_text(encoding="utf-8"):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _has_plausible_tests_dir(root: Path) -> bool:
        tests_dir = root / "tests"
        if not tests_dir.is_dir():
            return False
        # Look for at least one .py file that looks like a pytest test
        for py_file in tests_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                if "def test_" in content or "class Test" in content:
                    return True
            except Exception:
                continue
        return False
