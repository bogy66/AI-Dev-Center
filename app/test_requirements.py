from dataclasses import dataclass, field


@dataclass(frozen=True)
class TestRequirements:
    __test__ = False
    """Describes the requirements a test adapter needs to run.

    This is a pure data model, stack‑agnostic and free of any
    Python/pytest, ESPHome, ESP32 or other framework logic.
    """
    executables: list[str] = field(default_factory=list)
    python_packages: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    target: str = ""
    connection: str = ""
