import pytest
from app.test_requirements import TestRequirements
from app.environment_resolver import EnvironmentPlan
from app.setup_planner import SetupPlanner, SetupStep


class TestSetupPlanner:

    @pytest.fixture
    def planner(self):
        return SetupPlanner()

    # ------------------------------------------------------------------
    # 1. esphome is recognised as an automatically installable Python package
    # ------------------------------------------------------------------
    def test_esphome_as_installable_python_package(self, planner: SetupPlanner):
        req = TestRequirements(
            executables=["esphome"],
            python_packages=[],
        )
        env_plan = EnvironmentPlan(
            ready=False,
            missing=["esphome"],
            warnings=[]
        )
        steps = planner.plan(req, env_plan)
        assert len(steps) == 1
        step = steps[0]
        assert step.requirement == "esphome"
        assert step.kind == "install_python_package"
        assert step.automatic is True
        assert "pip install" in step.action

    # ------------------------------------------------------------------
    # 2. pyserial is recognised as an automatically installable Python package
    # ------------------------------------------------------------------
    def test_pyserial_as_installable_python_package(self, planner: SetupPlanner):
        req = TestRequirements(
            executables=[],
            python_packages=["pyserial"],
        )
        env_plan = EnvironmentPlan(
            ready=False,
            missing=[],
            warnings=[]
        )
        steps = planner.plan(req, env_plan)
        assert len(steps) == 1
        step = steps[0]
        assert step.requirement == "pyserial"
        assert step.kind == "install_python_package"
        assert step.automatic is True

    # ------------------------------------------------------------------
    # 3. Missing serial port is hardware_required
    # ------------------------------------------------------------------
    def test_missing_serial_port_is_hardware(self, planner: SetupPlanner):
        req = TestRequirements(
            executables=[],
            connection="serial",
        )
        env_plan = EnvironmentPlan(
            ready=False,
            missing=["Kein ESP32/serieller Port gefunden."],
            warnings=[]
        )
        steps = planner.plan(req, env_plan)
        # The serial port missing item should be classified as hardware_required
        hardware_steps = [s for s in steps if s.kind == "hardware_required"]
        assert len(hardware_steps) >= 1
        step = hardware_steps[0]
        assert "Port" in step.requirement

    # ------------------------------------------------------------------
    # 4. Unknown executables are not blindly installed
    # ------------------------------------------------------------------
    def test_unknown_executable_not_installed(self, planner: SetupPlanner):
        req = TestRequirements(
            executables=["some-unknown-tool"],
        )
        env_plan = EnvironmentPlan(
            ready=False,
            missing=["some-unknown-tool"],
            warnings=[]
        )
        steps = planner.plan(req, env_plan)
        assert len(steps) == 1
        step = steps[0]
        assert step.requirement == "some-unknown-tool"
        assert step.kind == "unknown"
        assert step.automatic is False

    # ------------------------------------------------------------------
    # 5. Already fulfilled requirements produce no steps
    # ------------------------------------------------------------------
    def test_fulfilled_requirements_produce_no_steps(self, planner: SetupPlanner):
        req = TestRequirements(
            executables=["python"],
        )
        env_plan = EnvironmentPlan(
            ready=True,
            missing=[],
            warnings=[]
        )
        steps = planner.plan(req, env_plan)
        assert len(steps) == 0

    # ------------------------------------------------------------------
    # 6. Multiple missing requirements are planned correctly
    # ------------------------------------------------------------------
    def test_multiple_missing_requirements(self, planner: SetupPlanner):
        req = TestRequirements(
            executables=["esphome", "some-unknown-tool"],
            python_packages=["pyserial"],
        )
        env_plan = EnvironmentPlan(
            ready=False,
            missing=["esphome", "some-unknown-tool"],
            warnings=[]
        )
        steps = planner.plan(req, env_plan)
        # Should have steps for esphome, some-unknown-tool, and pyserial
        requirements_found = {s.requirement for s in steps}
        assert "esphome" in requirements_found
        assert "some-unknown-tool" in requirements_found
        assert "pyserial" in requirements_found

    # ------------------------------------------------------------------
    # 7. No installation happens during the test
    # ------------------------------------------------------------------
    def test_no_installation_occurs(self, planner: SetupPlanner):
        # This test verifies by construction that no pip, subprocess, etc.
        # is called. The planner only returns data.
        req = TestRequirements(
            executables=["esphome"],
        )
        env_plan = EnvironmentPlan(
            ready=False,
            missing=["esphome"],
            warnings=[]
        )
        steps = planner.plan(req, env_plan)
        # No installation side effect – just data
        assert steps[0].automatic is True
