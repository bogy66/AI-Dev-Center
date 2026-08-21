from pathlib import Path
from app.test_strategy import TestStrategy


class TestStackDetector:
    """Detects the test stack used by a project and returns a TestStrategy."""

    def detect(self, project_root: str) -> TestStrategy | None:
        """
        Examine the project at *project_root* and return a TestStrategy
        if a supported test stack is recognised, otherwise None.

        Currently only Python / pytest is supported.
        """
        root = Path(project_root)
        if not root.is_dir():
            return None

        # 1. Strong indicators: configuration files
        if self._has_pytest_ini(root):
            return self._pytest_strategy()

        if self._has_pyproject_with_pytest(root):
            return self._pytest_strategy()

        if self._has_setup_cfg_with_pytest(root):
            return self._pytest_strategy()

        # 2. Requirements file mentioning pytest
        if self._has_requirements_with_pytest(root):
            return self._pytest_strategy()

        # 3. Weak indicator: existing tests/ directory with plausible pytest files
        if self._has_plausible_tests_dir(root):
            return self._pytest_strategy()

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pytest_strategy() -> TestStrategy:
        return TestStrategy(
            stack="pytest",
            level="unit",
            environment="host",
            command="python -m pytest -q"
        )

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
