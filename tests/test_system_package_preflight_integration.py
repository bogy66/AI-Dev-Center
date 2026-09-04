"""System-level integration test for SYSTEM_PACKAGE capability-aware preflight.

This test reproduces the Real-System-E2E environment boundary without external providers:
- Creates a temporary Python venv
- Prepends venv/bin to PATH
- Confirms python3 is resolvable
- Runs the productive preflight/planning boundary
- Verifies the python3 SYSTEM_PACKAGE requirement is satisfied
- Verifies it cannot become a manual_review setup blocker
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.requirement_model import (
    Requirement,
    RequirementActivation,
    RequirementType,
)
from app.requirement_preflight import RequirementPreflight
from app.toolchain_materializer import ToolchainMaterializer


@pytest.fixture
def isolated_venv():
    """Create an isolated Python venv and prepend its bin directory to PATH."""
    with tempfile.TemporaryDirectory() as tmpdir:
        venv_path = Path(tmpdir) / "test_venv"
        
        # Create venv
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            check=True,
            capture_output=True,
        )
        
        # Determine bin directory (bin on Unix, Scripts on Windows)
        bin_dir = venv_path / ("Scripts" if sys.platform == "win32" else "bin")
        assert bin_dir.exists(), f"venv bin directory not found: {bin_dir}"
        
        # Save original PATH
        original_path = os.environ.get("PATH", "")
        
        # Prepend venv bin to PATH
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{original_path}"
        
        try:
            yield venv_path
        finally:
            # Restore original PATH
            os.environ["PATH"] = original_path


def test_system_package_python3_in_venv_satisfied_no_manual_review_blocker(isolated_venv):
    """
    Reproduce Real-System-E2E scenario:
    - python3 is available in isolated venv PATH
    - SYSTEM_PACKAGE requirement with display name "Python 3" and
      verification_executable "python3"
    - RequirementPreflight reports satisfied=True
    - ToolchainMaterializer produces no manual_review step
    """
    # Confirm python3 is resolvable in the isolated venv environment
    python3_path = shutil.which("python3")
    assert python3_path is not None, "python3 must be available in venv PATH"
    assert str(isolated_venv) in python3_path, (
        f"python3 must resolve to venv path; got {python3_path}"
    )

    # Create SYSTEM_PACKAGE requirement whose display name differs from the
    # executable identity (mimics Real-System-E2E discovery contract).
    requirement = Requirement(
        id="req-python3-venv",
        name="Python 3",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="Python 3 runtime environment for ESPHome",
        required=True,
        confidence=1.0,
        install_method="system package manager (e.g., apt, brew)",
        verification_executable="python3",
    )
    activation = RequirementActivation(
        requirement.id, active=True, blocks_current_operation=True,
        reason="current request",
    )

    # Run RequirementPreflight
    preflight = RequirementPreflight.check(
        [requirement], "project-venv", [activation],
    )

    # Verify preflight reports satisfied=True
    assert len(preflight.results) == 1
    result = preflight.results[0]
    assert result.requirement_id == requirement.id
    assert result.present is True, (
        f"python3 SYSTEM_PACKAGE must be present; got present={result.present}"
    )
    assert result.satisfied is True, (
        f"python3 SYSTEM_PACKAGE must be satisfied; got satisfied={result.satisfied}"
    )
    assert result.warning is None, (
        f"python3 SYSTEM_PACKAGE must not produce warning; got {result.warning}"
    )
    assert preflight.overall_ready is True
    assert preflight.missing_requirements == ()

    # Create ToolchainItem for python3 (mimics Council output)
    toolchain_item = ToolchainItem(
        requirement_ref=requirement.id,
        name="Python 3",
        type=RequirementType.SYSTEM_PACKAGE,
        install_method="apt install python3 python3-pip ...",
        version=None,
        state="needs_install",
    )
    variant = CouncilVariant(
        id="variant-python3",
        name="variant-python3",
        toolchain=(toolchain_item,),
    )
    council_result = CouncilResult(
        id="council-venv",
        project_id="project-venv",
        variants=(variant,),
        recommendation="variant-python3",
        council_complete=True,
    )

    # Run ToolchainMaterializer
    plan = ToolchainMaterializer().materialize(
        council_result, "project-venv", preflight=preflight,
    )

    # Verify no manual_review step is produced
    assert plan.steps == (), (
        f"Satisfied python3 SYSTEM_PACKAGE must not produce manual_review step; "
        f"got {[(s.requirement_id, s.action) for s in plan.steps]}"
    )


def test_system_package_not_in_path_produces_manual_review(isolated_venv):
    """
    SYSTEM_PACKAGE requirement whose name is NOT in PATH:
    - RequirementPreflight reports satisfied=False with warning
    - ToolchainMaterializer produces manual_review step (existing behavior)
    """
    # Confirm fictional executable is not resolvable
    fictional_path = shutil.which("fictional-system-tool-xyz")
    assert fictional_path is None, "fictional-system-tool-xyz must not be in PATH"
    
    # Create SYSTEM_PACKAGE requirement for fictional tool
    requirement = Requirement(
        id="req-fictional",
        name="fictional-system-tool-xyz",
        type=RequirementType.SYSTEM_PACKAGE,
        purpose="Fictional system package not in PATH",
        required=True,
        confidence=1.0,
        install_method="system package manager",
    )
    activation = RequirementActivation(
        requirement.id, active=True, blocks_current_operation=True,
    )
    
    # Run RequirementPreflight
    preflight = RequirementPreflight.check(
        [requirement], "project-fictional", [activation],
    )
    
    # Verify preflight reports NOT satisfied, with warning
    assert len(preflight.results) == 1
    result = preflight.results[0]
    assert result.requirement_id == requirement.id
    assert result.present is False
    assert result.satisfied is False
    assert result.warning == "requirement type not locally verifiable"
    assert preflight.overall_ready is False  # active unsatisfied blocker keeps preflight not ready
    
    # Create ToolchainItem for fictional tool
    toolchain_item = ToolchainItem(
        requirement_ref=requirement.id,
        name="fictional-system-tool-xyz",
        type=RequirementType.SYSTEM_PACKAGE,
        install_method="manual",
        version=None,
        state="needs_install",
    )
    variant = CouncilVariant(
        id="variant-fictional",
        name="variant-fictional",
        toolchain=(toolchain_item,),
    )
    council_result = CouncilResult(
        id="council-fictional",
        project_id="project-fictional",
        variants=(variant,),
        recommendation="variant-fictional",
        council_complete=True,
    )
    
    # Run ToolchainMaterializer
    plan = ToolchainMaterializer().materialize(
        council_result, "project-fictional", preflight=preflight,
    )
    
    # Verify manual_review step is produced (existing behavior)
    assert len(plan.steps) == 1
    assert plan.steps[0].requirement_id == requirement.id
    assert plan.steps[0].action == "manual_review"
