import shutil
from pathlib import Path
import subprocess


class WorkspaceManager:
    """Manages isolated workspaces for Developer and Tester using Git worktrees."""
    
    def __init__(self, project_path):
        self.project_path = Path(project_path).resolve()
        self.worktrees_dir = self.project_path / ".worktrees"
    
    def _ensure_worktrees_dir(self):
        """Ensure the worktrees directory exists."""
        self.worktrees_dir.mkdir(exist_ok=True)
    
    def create_developer_workspace(self, workflow_id):
        """Create an isolated workspace for the developer."""
        self._ensure_worktrees_dir()
        
        workspace_dir = self.worktrees_dir / "developer" / workflow_id
        branch_name = f"dev-{workflow_id}"
        
        # Create the worktree
        try:
            subprocess.run(
                ["git", "worktree", "add", str(workspace_dir), "-b", branch_name],
                cwd=self.project_path,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"Failed to create developer workspace: {error.stderr}"
            )
        
        return {
            "path": str(workspace_dir),
            "branch": branch_name
        }
    
    def create_tester_workspace(self, workflow_id):
        """Create an isolated workspace for the tester."""
        self._ensure_worktrees_dir()
        
        workspace_dir = self.worktrees_dir / "tester" / workflow_id
        branch_name = f"test-{workflow_id}"
        
        # Create the worktree
        try:
            subprocess.run(
                ["git", "worktree", "add", str(workspace_dir), "-b", branch_name],
                cwd=self.project_path,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"Failed to create tester workspace: {error.stderr}"
            )
        
        return {
            "path": str(workspace_dir),
            "branch": branch_name
        }
    
    def cleanup_workspace(self, workflow_id):
        """Clean up a workspace after workflow completion."""
        developer_dir = self.worktrees_dir / "developer" / workflow_id
        tester_dir = self.worktrees_dir / "tester" / workflow_id
        
        # Remove worktrees
        for workspace_dir in [developer_dir, tester_dir]:
            if workspace_dir.exists():
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", str(workspace_dir)],
                        cwd=self.project_path,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                except subprocess.CalledProcessError:
                    # Try to remove directory directly if git worktree remove fails
                    try:
                        shutil.rmtree(workspace_dir)
                    except Exception:
                        pass
        
        # Clean up empty directories
        try:
            if developer_dir.parent.exists() and not any(developer_dir.parent.iterdir()):
                developer_dir.parent.rmdir()
            if self.worktrees_dir.exists() and not any(self.worktrees_dir.iterdir()):
                self.worktrees_dir.rmdir()
        except Exception:
            pass
    
    def get_developer_workspace(self, workflow_id):
        """Get the path to the developer workspace."""
        return str(self.worktrees_dir / "developer" / workflow_id)
    
    def get_tester_workspace(self, workflow_id):
        """Get the path to the tester workspace."""
        return str(self.worktrees_dir / "tester" / workflow_id)
