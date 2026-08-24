from app.requirement_model import (
    PreflightResult,
    Requirement,
    RequirementType,
)
from app.setup_planner import SetupPlanner


def _requirement(
    id="R1",
    name="pkg",
    type=RequirementType.PYTHON_PACKAGE,
    required=True,
    install_method="pip install pkg",
    required_version=None,
    verification_method=None,
):
    return Requirement(
        id=id,
        name=name,
        type=type,
        purpose="test",
        required=required,
        confidence=0.9,
        evidence=(),
        source_file=None,
        detected_version=None,
        required_version=required_version,
        install_method=install_method,
        verification_method=verification_method,
        status="missing",
        metadata={},
    )


def _preflight(
    missing=(),
    already_installed=(),
    project_id="proj",
):
    return PreflightResult(
        id="preflight-1",
        project_id=project_id,
        overall_ready=False,
        results=(),
        missing_requirements=tuple(missing),
        already_installed=tuple(already_installed),
        warnings=(),
    )


def test_single_missing_python_package_creates_install_step():
    req = _requirement(
        id="R1",
        name="mypkg",
        type=RequirementType.PYTHON_PACKAGE,
        install_method="pip install mypkg",
        required_version="1.0",
        verification_method="mypkg --version",
    )
    preflight = _preflight([req])

    plan = SetupPlanner().plan([], preflight, "proj")

    assert len(plan.steps) == 1

    step = plan.steps[0]

    assert step.id == "step-R1"
    assert step.requirement_id == "R1"
    assert step.action == "install"
    assert step.install_method == "pip install mypkg"
    assert step.package == "mypkg"
    assert step.version == "1.0"
    assert step.command is None
    assert step.verification_after == "mypkg --version"
    assert step.is_approved is False

    assert plan.requires_user_approval is True
    assert plan.status == "pending_approval"
    assert plan.rollback_steps == ()


def test_python_package_without_install_method_requires_manual_review():
    req = _requirement(
        id="R1",
        name="mypkg",
        type=RequirementType.PYTHON_PACKAGE,
        install_method=None,
    )
    preflight = _preflight([req])

    plan = SetupPlanner().plan([], preflight, "proj")

    step = plan.steps[0]

    assert step.action == "manual_review"
    assert step.package == "mypkg"
    assert step.install_method is None


def test_python_package_without_name_requires_manual_review():
    req = _requirement(
        id="R1",
        name="",
        type=RequirementType.PYTHON_PACKAGE,
        install_method="pip install something",
    )
    preflight = _preflight([req])

    plan = SetupPlanner().plan([], preflight, "proj")

    step = plan.steps[0]

    assert step.action == "manual_review"
    assert step.package == ""


def test_non_python_requirement_requires_manual_review():
    req = _requirement(
        id="R2",
        name="exe2",
        type=RequirementType.EXECUTABLE,
        install_method="brew install exe2",
    )
    preflight = _preflight([req])

    plan = SetupPlanner().plan([], preflight, "proj")

    step = plan.steps[0]

    assert step.action == "manual_review"
    assert step.package is None
    assert step.install_method == "brew install exe2"


def test_multiple_missing_requirements():
    req1 = _requirement(
        id="R1",
        name="pkg1",
        type=RequirementType.PYTHON_PACKAGE,
        install_method="pip install pkg1",
    )
    req2 = _requirement(
        id="R2",
        name="exe2",
        type=RequirementType.EXECUTABLE,
        install_method="brew install exe2",
    )

    preflight = _preflight([req1, req2])
    plan = SetupPlanner().plan([], preflight, "proj")

    assert len(plan.steps) == 2

    ids = {step.id for step in plan.steps}
    assert ids == {"step-R1", "step-R2"}

    req_ids = {
        step.requirement_id
        for step in plan.steps
    }
    assert req_ids == {"R1", "R2"}

    step_python = next(
        step for step in plan.steps
        if step.requirement_id == "R1"
    )
    step_executable = next(
        step for step in plan.steps
        if step.requirement_id == "R2"
    )

    assert step_python.action == "install"
    assert step_executable.action == "manual_review"


def test_already_installed_requirement_not_in_plan():
    missing = _requirement(
        id="R1",
        name="pkg1",
        type=RequirementType.PYTHON_PACKAGE,
    )
    installed = _requirement(
        id="R2",
        name="pkg2",
        type=RequirementType.PYTHON_PACKAGE,
    )

    preflight = _preflight(
        missing=[missing],
        already_installed=[installed],
    )

    plan = SetupPlanner().plan([], preflight, "proj")

    assert len(plan.steps) == 1
    assert plan.steps[0].requirement_id == "R1"


def test_requirement_id_forwarded():
    req = _requirement(
        id="R42",
        name="pkg",
        type=RequirementType.PYTHON_PACKAGE,
    )
    preflight = _preflight([req])

    plan = SetupPlanner().plan([], preflight, "proj")

    assert plan.steps[0].requirement_id == "R42"


def test_package_set_only_for_python_package():
    python_req = _requirement(
        id="R1",
        name="pypkg",
        type=RequirementType.PYTHON_PACKAGE,
    )
    exe_req = _requirement(
        id="R2",
        name="exe",
        type=RequirementType.EXECUTABLE,
    )

    preflight = _preflight([python_req, exe_req])
    plan = SetupPlanner().plan([], preflight, "proj")

    step_py = next(
        step for step in plan.steps
        if step.requirement_id == "R1"
    )
    step_exe = next(
        step for step in plan.steps
        if step.requirement_id == "R2"
    )

    assert step_py.package == "pypkg"
    assert step_exe.package is None


def test_version_forwarded():
    req = _requirement(
        id="R1",
        name="pkg",
        type=RequirementType.PYTHON_PACKAGE,
        required_version="2.5",
    )
    preflight = _preflight([req])

    plan = SetupPlanner().plan([], preflight, "proj")

    assert plan.steps[0].version == "2.5"


def test_install_method_forwarded():
    req = _requirement(
        id="R1",
        name="pkg",
        type=RequirementType.PYTHON_PACKAGE,
        install_method="pip install pkg",
    )
    preflight = _preflight([req])

    plan = SetupPlanner().plan([], preflight, "proj")

    assert plan.steps[0].install_method == "pip install pkg"


def test_verification_after_forwarded():
    req = _requirement(
        id="R1",
        name="pkg",
        type=RequirementType.PYTHON_PACKAGE,
        verification_method="pkg --version",
    )
    preflight = _preflight([req])

    plan = SetupPlanner().plan([], preflight, "proj")

    assert plan.steps[0].verification_after == "pkg --version"


def test_is_approved_false():
    req = _requirement(id="R1")

    preflight = _preflight([req])
    plan = SetupPlanner().plan([], preflight, "proj")

    assert plan.steps[0].is_approved is False


def test_requires_user_approval_true():
    req = _requirement(id="R1")

    preflight = _preflight([req])
    plan = SetupPlanner().plan([], preflight, "proj")

    assert plan.requires_user_approval is True


def test_status_pending_approval():
    req = _requirement(id="R1")

    preflight = _preflight([req])
    plan = SetupPlanner().plan([], preflight, "proj")

    assert plan.status == "pending_approval"


def test_inputs_not_mutated():
    req = _requirement(
        id="R1",
        name="pkg",
        type=RequirementType.PYTHON_PACKAGE,
        install_method="pip install pkg",
        required_version="1.0",
    )

    preflight = PreflightResult(
        id="pf1",
        project_id="proj",
        overall_ready=False,
        results=(),
        missing_requirements=(req,),
        already_installed=(),
        warnings=(),
    )

    original_missing = preflight.missing_requirements
    original_install = req.install_method

    SetupPlanner().plan([req], preflight, "proj")

    assert preflight.missing_requirements == original_missing
    assert req.install_method == original_install
