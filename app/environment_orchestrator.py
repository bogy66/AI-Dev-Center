from pathlib import Path
from app.test_stack_detector import TestStackDetector
from app.esp32_preflight import ESP32Preflight
from app.environment_resolver import EnvironmentResolver, EnvironmentPlan


class EnvironmentOrchestrator:
    """Orchestrates the environment check for a project.

    The orchestrator is stack‑neutral and uses the existing
    TestStackDetector, TestAdapter, ESP32Preflight, and
    EnvironmentResolver components.

    Dependencies can be injected via the constructor to facilitate
    testing.
    """

    def __init__(
        self,
        detector: TestStackDetector | None = None,
        preflight: ESP32Preflight | None = None,
        resolver: EnvironmentResolver | None = None,
    ):
        self._detector = detector or TestStackDetector()
        self._preflight = preflight or ESP32Preflight()
        self._resolver = resolver or EnvironmentResolver()

    def check_environment(self, project_root: str) -> dict:
        """Run the full environment check for a project.

        Returns a dict with keys:
            adapter (TestAdapter | None): The detected adapter or None.
            requirements (TestRequirements | None): The adapter's requirements or None.
            preflight (PreflightResult): The preflight check result.
            plan (EnvironmentPlan): The resolved environment plan.
        """
        root = Path(project_root)
        adapter = self._detector.detect(str(root))

        requirements = None
        if adapter is not None:
            requirements = adapter.get_requirements()

        preflight = self._preflight.check()

        if requirements is not None:
            plan = self._resolver.resolve(requirements, preflight)
        else:
            # No adapter detected – create a plan with preflight only
            plan = EnvironmentPlan(
                ready=False,
                missing=["Kein unterstützter Test-Stack erkannt."],
                warnings=[]
            )

        return {
            "adapter": adapter,
            "requirements": requirements,
            "preflight": preflight,
            "plan": plan,
        }
