import pytest
from pathlib import Path
from unittest.mock import MagicMock
from app.test_adapters import PythonPytestAdapter, ESPHomeAdapter
from app.test_requirements import TestRequirements
from app.esp32_preflight import PreflightResult, ESP32Preflight
from app.environment_resolver import EnvironmentPlan, EnvironmentResolver
from app.test_stack_detector import TestStackDetector
from app.environment_orchestrator import EnvironmentOrchestrator


class TestEnvironmentOrchestrator:

    # ------------------------------------------------------------------
    # Helper: a PreflightResult that is "ready"
    # ------------------------------------------------------------------
    @staticmethod
    def _ready_preflight() -> PreflightResult:
        return PreflightResult(
            ready=True,
            python_available=True,
            esphome_available=True,
            serial_ports=["/dev/ttyUSB0"],
            available_executables=["python", "esphome"],
            missing=[],
            warnings=[]
        )

    # ------------------------------------------------------------------
    # 1. The orchestrator calls the detector
    # ------------------------------------------------------------------
    def test_calls_detector(self):
        detector = MagicMock(spec=TestStackDetector)
        preflight = MagicMock(spec=ESP32Preflight)
        preflight.check.return_value = self._ready_preflight()
        resolver = MagicMock(spec=EnvironmentResolver)
        resolver.resolve.return_value = EnvironmentPlan(ready=True)

        orchest = EnvironmentOrchestrator(
            detector=detector,
            preflight=preflight,
            resolver=resolver
        )
        result = orchest.check_environment("/some/path")

        detector.detect.assert_called_once_with("/some/path")

    # ------------------------------------------------------------------
    # 2. The orchestrator calls the preflight
    # ------------------------------------------------------------------
    def test_calls_preflight(self):
        detector = MagicMock(spec=TestStackDetector)
        detector.detect.return_value = PythonPytestAdapter()
        preflight = MagicMock(spec=ESP32Preflight)
        preflight.check.return_value = self._ready_preflight()
        resolver = MagicMock(spec=EnvironmentResolver)
        resolver.resolve.return_value = EnvironmentPlan(ready=True)

        orchest = EnvironmentOrchestrator(
            detector=detector,
            preflight=preflight,
            resolver=resolver
        )
        result = orchest.check_environment("/some/path")

        preflight.check.assert_called_once()

    # ------------------------------------------------------------------
    # 3. The orchestrator calls the resolver when an adapter is found
    # ------------------------------------------------------------------
    def test_calls_resolver(self):
        detector = MagicMock(spec=TestStackDetector)
        mock_adapter = MagicMock(spec=PythonPytestAdapter)
        mock_adapter.get_requirements.return_value = TestRequirements()
        detector.detect.return_value = mock_adapter
        preflight = MagicMock(spec=ESP32Preflight)
        preflight.check.return_value = self._ready_preflight()
        resolver = MagicMock(spec=EnvironmentResolver)
        resolver.resolve.return_value = EnvironmentPlan(ready=True)

        orchest = EnvironmentOrchestrator(
            detector=detector,
            preflight=preflight,
            resolver=resolver
        )
        result = orchest.check_environment("/some/path")

        resolver.resolve.assert_called_once()

    # ------------------------------------------------------------------
    # 4. With a real adapter + mocked preflight/resolver → ready=True
    # ------------------------------------------------------------------
    def test_with_real_adapter_and_mocked_preflight_resolver(self):
        # We use a real PythonPytestAdapter as the detected adapter.
        detector = MagicMock(spec=TestStackDetector)
        real_adapter = PythonPytestAdapter()
        detector.detect.return_value = real_adapter
        preflight = MagicMock(spec=ESP32Preflight)
        preflight.check.return_value = self._ready_preflight()
        resolver = MagicMock(spec=EnvironmentResolver)
        resolver.resolve.return_value = EnvironmentPlan(ready=True)

        orchest = EnvironmentOrchestrator(
            detector=detector,
            preflight=preflight,
            resolver=resolver
        )
        result = orchest.check_environment("/some/path")

        assert result["adapter"] is real_adapter
        assert result["requirements"] is not None
        assert result["plan"].ready is True

    # ------------------------------------------------------------------
    # 5. No adapter → plan.ready=False, missing explanation
    # ------------------------------------------------------------------
    def test_no_adapter(self):
        detector = MagicMock(spec=TestStackDetector)
        detector.detect.return_value = None
        preflight = MagicMock(spec=ESP32Preflight)
        preflight.check.return_value = self._ready_preflight()
        resolver = MagicMock(spec=EnvironmentResolver)

        orchest = EnvironmentOrchestrator(
            detector=detector,
            preflight=preflight,
            resolver=resolver
        )
        result = orchest.check_environment("/some/path")

        assert result["adapter"] is None
        assert result["requirements"] is None
        assert result["plan"].ready is False
        assert any("Kein unterstützter Test-Stack" in msg for msg in result["plan"].missing)
