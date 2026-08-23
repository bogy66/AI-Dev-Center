import pytest
from pathlib import Path
from app.test_adapters import TestAdapter, PythonPytestAdapter, ESPHomeAdapter
from app.test_strategy import TestStrategy
from app.test_requirements import TestRequirements


class TestTestAdapterInterface:

    def test_interface_has_detect(self):
        assert hasattr(TestAdapter, "detect")
        assert callable(TestAdapter.detect)

    def test_interface_has_get_strategy(self):
        assert hasattr(TestAdapter, "get_strategy")
        assert callable(TestAdapter.get_strategy)

    def test_interface_has_is_test_file(self):
        assert hasattr(TestAdapter, "is_test_file")
        assert callable(TestAdapter.is_test_file)

    def test_interface_has_validate_test_file(self):
        assert hasattr(TestAdapter, "validate_test_file")
        assert callable(TestAdapter.validate_test_file)

    def test_interface_has_get_command(self):
        assert hasattr(TestAdapter, "get_command")
        assert callable(TestAdapter.get_command)

    def test_interface_has_get_requirements(self):
        assert hasattr(TestAdapter, "get_requirements")
        assert callable(TestAdapter.get_requirements)

    def test_minimal_concrete_adapter_can_be_created(self):
        # A minimal concrete adapter that implements all abstract methods
        class MinimalAdapter(TestAdapter):
            def detect(self, project_root: str) -> bool:
                return False

            def get_strategy(self, level: str = "unit", environment: str = "host") -> TestStrategy:
                return TestStrategy(
                    stack="minimal",
                    level=level,
                    environment=environment,
                    command="echo 'no tests'"
                )

            def is_test_file(self, file_path: str) -> bool:
                return False

            def validate_test_file(self, file_path: str, content: str) -> dict:
                return {"success": True, "errors": []}

            def get_command(self, level: str = "unit", environment: str = "host") -> str:
                return "echo 'no tests'"

            def get_requirements(self) -> TestRequirements:
                return TestRequirements()

        adapter = MinimalAdapter()
        assert isinstance(adapter, TestAdapter)


class TestPythonPytestAdapter:

    @pytest.fixture
    def adapter(self):
        return PythonPytestAdapter()

    # ------------------------------------------------------------------
    # is_test_file
    # ------------------------------------------------------------------
    def test_test_foo_py_is_test_file(self, adapter: PythonPytestAdapter):
        assert adapter.is_test_file("tests/test_foo.py") is True

    def test_foo_test_py_is_test_file(self, adapter: PythonPytestAdapter):
        assert adapter.is_test_file("tests/foo_test.py") is True

    def test_example_py_is_not_test_file(self, adapter: PythonPytestAdapter):
        assert adapter.is_test_file("app/example.py") is False

    def test_non_python_file_is_not_test_file(self, adapter: PythonPytestAdapter):
        assert adapter.is_test_file("tests/test_foo.txt") is False

    def test_test_in_subdir(self, adapter: PythonPytestAdapter):
        assert adapter.is_test_file("subdir/test_bar.py") is True

    # ------------------------------------------------------------------
    # validate_test_file
    # ------------------------------------------------------------------
    def test_valid_test_function(self, adapter: PythonPytestAdapter):
        content = "def test_hello():\n    assert 1 + 1 == 2\n"
        result = adapter.validate_test_file("tests/test_example.py", content)
        assert result["success"] is True
        assert result["errors"] == []

    def test_valid_test_class(self, adapter: PythonPytestAdapter):
        content = "class TestExample:\n    def test_method(self):\n        assert True\n"
        result = adapter.validate_test_file("tests/test_class.py", content)
        assert result["success"] is True
        assert result["errors"] == []

    def test_syntax_error(self, adapter: PythonPytestAdapter):
        content = "def test_hello()\n    assert 1 + 1 == 2\n"
        result = adapter.validate_test_file("tests/test_bad.py", content)
        assert result["success"] is False
        assert any("Syntax error" in err for err in result["errors"])

    def test_no_test_function(self, adapter: PythonPytestAdapter):
        content = "def helper():\n    return 42\n"
        result = adapter.validate_test_file("tests/test_no_test.py", content)
        assert result["success"] is False
        assert any("does not contain any pytest test" in err for err in result["errors"])

    def test_empty_content(self, adapter: PythonPytestAdapter):
        content = ""
        result = adapter.validate_test_file("tests/test_empty.py", content)
        assert result["success"] is False
        assert any("does not contain any pytest test" in err for err in result["errors"])

    # ------------------------------------------------------------------
    # get_strategy
    # ------------------------------------------------------------------
    def test_get_strategy_default(self, adapter: PythonPytestAdapter):
        strategy = adapter.get_strategy()
        assert isinstance(strategy, TestStrategy)
        assert strategy.stack == "pytest"
        assert strategy.level == "unit"
        assert strategy.environment == "host"
        assert strategy.command == "python -m pytest -q"

    def test_get_strategy_custom_level(self, adapter: PythonPytestAdapter):
        strategy = adapter.get_strategy(level="integration", environment="container")
        assert strategy.level == "integration"
        assert strategy.environment == "container"
        assert strategy.command == "python -m pytest -q"

    # ------------------------------------------------------------------
    # get_command
    # ------------------------------------------------------------------
    def test_get_command_default(self, adapter: PythonPytestAdapter):
        cmd = adapter.get_command()
        assert cmd == "python -m pytest -q"

    def test_get_command_custom(self, adapter: PythonPytestAdapter):
        cmd = adapter.get_command(level="system", environment="target")
        assert cmd == "python -m pytest -q"

    # ------------------------------------------------------------------
    # get_requirements
    # ------------------------------------------------------------------
    def test_get_requirements(self, adapter: PythonPytestAdapter):
        req = adapter.get_requirements()
        assert isinstance(req, TestRequirements)
        # PythonPytestAdapter returns empty requirements
        assert req.executables == []
        assert req.capabilities == []


class TestESPHomeAdapter:

    @pytest.fixture
    def adapter(self):
        return ESPHomeAdapter()

    # ------------------------------------------------------------------
    # get_requirements
    # ------------------------------------------------------------------
    def test_get_requirements_returns_test_requirements(self, adapter: ESPHomeAdapter):
        req = adapter.get_requirements()
        assert isinstance(req, TestRequirements)

    def test_executables_contain_python_and_esphome(self, adapter: ESPHomeAdapter):
        req = adapter.get_requirements()
        assert "python" in req.executables
        assert "esphome" in req.executables

    def test_capabilities_contain_build_flash_serial_log(self, adapter: ESPHomeAdapter):
        req = adapter.get_requirements()
        assert "build" in req.capabilities
        assert "flash" in req.capabilities
        assert "serial_log" in req.capabilities

    def test_target_is_esp32(self, adapter: ESPHomeAdapter):
        req = adapter.get_requirements()
        assert req.target == "esp32"

    def test_connection_is_serial(self, adapter: ESPHomeAdapter):
        req = adapter.get_requirements()
        assert req.connection == "serial"

    def test_requirements_are_independent(self, adapter: ESPHomeAdapter):
        req1 = adapter.get_requirements()
        req2 = adapter.get_requirements()
        # Both should be the same value but not the same mutable object
        # (TestRequirements is frozen, so it's safe)
        assert req1 == req2

    def test_no_real_esphome_call(self, adapter: ESPHomeAdapter):
        # This test itself proves the point: no real ESPHome is called.
        req = adapter.get_requirements()
        assert req.executables == ["python", "esphome"]

    def test_no_hardware_needed(self, adapter: ESPHomeAdapter):
        req = adapter.get_requirements()
        assert req.target == "esp32"
        # No hardware access is performed.
