from dataclasses import dataclass


@dataclass(frozen=True)
class TestStrategy:
    __test__ = False
    """Holds the strategy parameters for executing tests.

    Fields
    ------
    stack : str
        The test framework / stack, e.g. "pytest", "esphome", "esp-idf",
        "arduino", "jest", "junit", "go", "rust".
    level : str
        The test level, e.g. "unit", "integration", "system", "hardware/hil".
    environment : str
        The execution environment, e.g. "host", "container", "target",
        "physical_hardware".
    command : str
        The concrete command to run the tests.
    """
    stack: str
    level: str
    environment: str
    command: str
