from dataclasses import dataclass


@dataclass(frozen=True)
class TestStrategy:
    __test__ = False
    """Holds the strategy parameters for executing tests."""
    stack: str          # e.g. "pytest", "jest", "mocha"
    level: str          # "unit", "integration", "system", "hardware/hil"
    environment: str    # "host", "container", "target", "physical_hardware"
    command: str        # full command to run the tests
