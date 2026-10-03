"""Approval-scoped creation of an empty central workflow project root."""
from dataclasses import dataclass
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class GreenfieldProjectApproval:
    run_id: str
    project_id: str
    project_root: str
    approved_by: str
    status: str = "approved"


class GreenfieldProjectMaterializer:
    """Create only one explicitly approved absent project and local Git repo."""

    def materialize(self, approval: GreenfieldProjectApproval) -> Path:
        if approval.status != "approved" or not approval.approved_by.strip():
            raise ValueError("Explicit greenfield approval is required")
        if not approval.run_id.strip() or not approval.project_id.strip():
            raise ValueError("Greenfield run and project identity are required")
        root = Path(approval.project_root).expanduser().resolve()
        if root.exists() or not root.parent.is_dir():
            raise ValueError("Approved greenfield root must be absent under an existing parent")
        root.mkdir()
        initialized = subprocess.run(
            ["git", "init", "--", str(root)], capture_output=True, text=True,
            check=False,
        )
        if initialized.returncode:
            root.rmdir()
            raise RuntimeError("Greenfield Git initialization failed")
        return root
