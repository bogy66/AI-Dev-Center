import pytest
from app.test_strategy import TestStrategy


class TestTestStrategy:

    def test_can_create_with_all_fields(self):
        strategy = TestStrategy(
            stack="pytest",
            level="unit",
            environment="host",
            command="python -m pytest -q"
        )
        assert strategy.stack == "pytest"
        assert strategy.level == "unit"
        assert strategy.environment == "host"
        assert strategy.command == "python -m pytest -q"

    def test_values_are_stored_correctly(self):
        strategy = TestStrategy(
            stack="jest",
            level="integration",
            environment="container",
            command="npx jest --ci"
        )
        assert strategy.stack == "jest"
        assert strategy.level == "integration"
        assert strategy.environment == "container"
        assert strategy.command == "npx jest --ci"

    def test_frozen_prevents_mutation(self):
        strategy = TestStrategy(
            stack="pytest",
            level="unit",
            environment="host",
            command="python -m pytest -q"
        )
        with pytest.raises(AttributeError):
            strategy.stack = "jest"

    def test_different_stacks_are_possible(self):
        for stack in ("pytest", "esphome", "esp-idf", "arduino", "jest", "junit", "go", "rust"):
            strategy = TestStrategy(
                stack=stack,
                level="unit",
                environment="host",
                command="echo 'test'"
            )
            assert strategy.stack == stack

    def test_level_hardware_hil(self):
        strategy = TestStrategy(
            stack="pytest",
            level="hardware/hil",
            environment="host",
            command="python -m pytest -q"
        )
        assert strategy.level == "hardware/hil"

    def test_environment_physical_hardware(self):
        strategy = TestStrategy(
            stack="pytest",
            level="unit",
            environment="physical_hardware",
            command="python -m pytest -q"
        )
        assert strategy.environment == "physical_hardware"

    def test_pytest_host_unit_example(self):
        strategy = TestStrategy(
            stack="pytest",
            level="unit",
            environment="host",
            command="python -m pytest -q"
        )
        assert strategy.stack == "pytest"
        assert strategy.level == "unit"
        assert strategy.environment == "host"
        assert strategy.command == "python -m pytest -q"

    def test_esphome_target_integration_example(self):
        strategy = TestStrategy(
            stack="esphome",
            level="integration",
            environment="target",
            command="esphome run test_config.yaml"
        )
        assert strategy.stack == "esphome"
        assert strategy.level == "integration"
        assert strategy.environment == "target"
        assert strategy.command == "esphome run test_config.yaml"

    def test_esp_idf_physical_hardware_hardware_hil_example(self):
        strategy = TestStrategy(
            stack="esp-idf",
            level="hardware/hil",
            environment="physical_hardware",
            command="idf.py test --target esp32"
        )
        assert strategy.stack == "esp-idf"
        assert strategy.level == "hardware/hil"
        assert strategy.environment == "physical_hardware"
        assert strategy.command == "idf.py test --target esp32"

    def test_contains_no_stack_specific_logic(self):
        import inspect
        source = inspect.getsource(TestStrategy)
        # The class is a frozen dataclass with no methods and no imports.
        # Check that it contains no method definitions and no import statements.
        assert "def " not in source
        # "import " (with a space) would indicate an import statement.
        assert "import " not in source
