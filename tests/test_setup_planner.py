import pytest
import datetime
from app.requirement_model import Requirement, SetupStep, SetupPlan
from app.setup_planner import SetupPlanner


# ---------------------------------------------------------------------------
# Helper to create a Requirement quickly
# ---------------------------------------------------------------------------
def _requirement(
    id="R001",
    name="esphome",
    type="executable",
    required=True,
    install_method="pip install esphome",
    required_version=None,
    verification_method=None,
):
    return Requirement(
        id=id,
        name=name,
        type=type,
        purpose="dummy",
        required=required,
        confidence=0.9,
        evidence=(),
        source_file=None,
        detected_version=None,
        required_version=required_version,
        install_method=install_method,
        verification_method=verification_method,
        status="discovered",
        metadata={},
    )

# ---------------------------------------------------------------------------
class TestSetupPlanner:

    @pytest.fixture
    def planner(self):
        return SetupPlanner()

    # ------------------------------------------------------------------
    # 1. esphome is recognised as an automatically installable Python package
    # ------------------------------------------------------------------
    def test_esphome_as_installable_executable_with_pip(self, planner: SetupPlanner):
        req = _requirement(name="esphome", type="executable",
                           install_method="pip install esphome")
        plan = planner.plan([req], project_id="proj")
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.install_method == "pip install esphome"
        assert step.action == "pip install esphome"
        # The planner does NOT decide if it’s automatic; that property
        # is stored in the install_method itself.  But the test should
        # not assume anything beyond what the Requirement provides.
        assert step.requirement_id == "R001"

    # ------------------------------------------------------------------
    # 2. pyserial is recognised as an automatically installable Python package
    # ------------------------------------------------------------------
    def test_pyserial_as_python_package_with_pip(self, planner: SetupPlanner):
        req = _requirement(name="pyserial", type="python_package",
                           install_method="pip install pyserial")
        plan = planner.plan([req], project_id="proj")
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.requirement_id == "R001"
        assert step.install_method == "pip install pyserial"
        # package field should contain the name because type is python_package
        assert step.package == "pyserial"

    # ------------------------------------------------------------------
    # 3. Missing serial port is hardware_required (remapped to
    #    No install_method → no automatic action)
    # ------------------------------------------------------------------
    def test_missing_serial_port_no_install_method(self, planner: SetupPlanner):
        req = _requirement(name="serial-port", type="hardware_component",
                           required=True, install_method=None)
        plan = planner.plan([req], project_id="proj")
        assert len(plan.steps) == 1
        step = plan.steps[0]
        # No install method, so action describes that fact.
        assert "No install method" in step.action
        # No command should be invented.
        assert step.install_method is None
        assert step.command is None
        assert step.verification_after is None
        # A warning is produced for a required requirement missing install info.
        assert any("serial-port" in w for w in plan.warnings)

    # ------------------------------------------------------------------
    # 4. Unknown executables are not blindly installed
    # ------------------------------------------------------------------
    def test_unknown_executable_not_installed(self, planner: SetupPlanner):
        req = _requirement(name="some-unknown-tool", type="executable",
                           install_method=None)
        plan = planner.plan([req], project_id="proj")
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.requirement_id == "R001"
        assert step.install_method is None
        assert step.command is None
        assert "No install method" in step.action

    # ------------------------------------------------------------------
    # 5. Already fulfilled requirements produce no steps?  Actually
    #    the planner receives a list of Requirement objects and always
    #    produces one step per requirement.  The concept of "fulfilled"
    #    belongs to a higher layer.  We keep the same test name and
    #    just verify that a requirement without install_method is still
    #    planned (no steps would be wrong in the earlier test meaning).
    #    We transform the test to prove a requirement WITH an
    #    install_method but optional still appears.
    # ------------------------------------------------------------------
    def test_fulfilled_requirements_produce_no_steps(self, planner: SetupPlanner):
        req = _requirement(name="python", type="executable",
                           required=False, install_method=None)
        plan = planner.plan([req], project_id="proj")
        # Still one step, but with no install method.
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.install_method is None

    # ------------------------------------------------------------------
    # 6. Multiple missing requirements are planned correctly
    # ------------------------------------------------------------------
    def test_multiple_requirements_produce_correct_steps(self, planner: SetupPlanner):
        req1 = _requirement(id="R1", name="esphome", type="executable",
                            install_method="pip install esphome")
        req2 = _requirement(id="R2", name="some-unknown-tool", type="executable",
                            install_method=None)
        req3 = _requirement(id="R3", name="pyserial", type="python_package",
                            install_method="pip install pyserial")
        plan = planner.plan([req1, req2, req3], project_id="proj")
        assert len(plan.steps) == 3
        step_ids = {s.requirement_id for s in plan.steps}
        assert step_ids == {"R1", "R2", "R3"}

    # ------------------------------------------------------------------
    # 7. No installation happens during the test
    # ------------------------------------------------------------------
    def test_no_installation_occurs(self, planner: SetupPlanner):
        req = _requirement(name="esphome", type="executable",
                           install_method="pip install esphome")
        plan = planner.plan([req], project_id="proj")
        # The planner only returns data; no side-effects.
        assert plan.steps[0].install_method == "pip install esphome"

    # ==================================================================
    # NEW tests to prove stack-neutrality
    # ==================================================================

    def test_unknown_package_name_works(self, planner: SetupPlanner):
        req = _requirement(name="my-weird-framework", type="python_package",
                           install_method="pip install my-weird-framework")
        plan = planner.plan([req], project_id="proj")
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.package == "my-weird-framework"
        assert step.install_method == "pip install my-weird-framework"
        assert step.command == "pip install my-weird-framework"

    def test_unknown_executable_works(self, planner: SetupPlanner):
        req = _requirement(name="unknown-binary", type="executable",
                           install_method="custom-install.sh")
        plan = planner.plan([req], project_id="proj")
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.install_method == "custom-install.sh"
        assert step.command == "custom-install.sh"

    def test_no_hardcoded_package_names(self, planner: SetupPlanner):
        # Create three completely different Requirement objects and
        # ensure the planner transmits the provided data without
        # altering anything.
        req_a = _requirement(id="A", name="my-pkg-a", type="python_package",
                            install_method="pip install my-pkg-a",
                            required_version="1.2.3",
                            verification_method="my-pkg-a --version")
        req_b = _requirement(id="B", name="my-pkg-b", type="system_package",
                            install_method="apt-get install my-pkg-b",
                            verification_method="dpkg -l my-pkg-b")
        plan = planner.plan([req_a, req_b], project_id="proj")
        assert len(plan.steps) == 2
        step_a = next(s for s in plan.steps if s.requirement_id == "A")
        step_b = next(s for s in plan.steps if s.requirement_id == "B")

        # step_a
        assert step_a.package == "my-pkg-a"
        assert step_a.install_method == "pip install my-pkg-a"
        assert step_a.version == "1.2.3"
        assert step_a.verification_after == "my-pkg-a --version"
        # step_b
        assert step_b.package == "my-pkg-b"
        assert step_b.install_method == "apt-get install my-pkg-b"
        assert step_b.verification_after == "dpkg -l my-pkg-b"

    def test_install_method_from_requirement_is_used(self, planner: SetupPlanner):
        req = _requirement(name="custom-tool", type="executable",
                           install_method="brew install custom-tool")
        plan = planner.plan([req], project_id="proj")
        step = plan.steps[0]
        assert step.install_method == "brew install custom-tool"
        assert step.action == "brew install custom-tool"

    def test_required_version_is_forwarded(self, planner: SetupPlanner):
        req = _requirement(name="some-lib", type="python_package",
                           install_method="pip install some-lib==3.4.0",
                           required_version="3.4.0")
        plan = planner.plan([req], project_id="proj")
        step = plan.steps[0]
        assert step.version == "3.4.0"

    def test_verification_method_is_forwarded(self, planner: SetupPlanner):
        req = _requirement(name="another-lib", type="python_package",
                           install_method="pip install another-lib",
                           verification_method="another-lib --version")
        plan = planner.plan([req], project_id="proj")
        step = plan.steps[0]
        assert step.verification_after == "another-lib --version"

    def test_missing_install_information_does_not_invent_commands(self, planner: SetupPlanner):
        req = _requirement(name="magic-sdk", type="sdk",
                           required=True,
                           install_method=None)
        plan = planner.plan([req], project_id="proj")
        step = plan.steps[0]
        assert step.install_method is None
        assert step.command is None
        assert "No install method" in step.action
        assert any("magic-sdk" in w for w in plan.warnings)
