import subprocess
from pathlib import Path


class TestBench:
    """Manages the test bench where Developer and Tester changes are combined and tested."""
    
    def __init__(self, project_path):
        self.project_path = Path(project_path).resolve()
        self.test_bench_dir = self.project_path / ".testbench"
    
    def _ensure_testbench_dir(self):
        """Ensure the testbench directory exists."""
        self.test_bench_dir.mkdir(exist_ok=True)
    
    def setup_testbench(self, developer_commit, tester_commit):
        """
        Set up the testbench with Developer and Tester commits.
        
        Returns the path to the testbench workspace.
        """
        self._ensure_testbench_dir()
        
        # Create a temporary worktree for the testbench
        testbench_workspace = self.test_bench_dir / "workspace"
        
        try:
            # Remove existing testbench workspace if it exists
            if testbench_workspace.exists():
                subprocess.run(
                    ["git", "worktree", "remove", str(testbench_workspace)],
                    cwd=self.project_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
        except subprocess.CalledProcessError:
            pass
        
        try:
            # Create the testbench worktree
            subprocess.run(
                ["git", "worktree", "add", str(testbench_workspace), "HEAD"],
                cwd=self.project_path,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"Failed to create testbench workspace: {error.stderr}"
            )
        
        return str(testbench_workspace)
    
    def merge_commits(self, testbench_path, developer_commit, tester_commit):
        """
        Merge Developer and Tester commits in the testbench.
        
        Returns True if merge was successful, False otherwise.
        """
        try:
            # Fetch both commits
            subprocess.run(
                ["git", "fetch", str(self.project_path), developer_commit],
                cwd=testbench_path,
                check=True,
                capture_output=True,
                text=True
            )
            subprocess.run(
                ["git", "fetch", str(self.project_path), tester_commit],
                cwd=testbench_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            # Merge Developer commit
            result = subprocess.run(
                ["git", "merge", "--no-edit", developer_commit],
                cwd=testbench_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                # Try to abort the merge
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=testbench_path,
                    capture_output=True,
                    text=True
                )
                return False
            
            # Merge Tester commit
            result = subprocess.run(
                ["git", "merge", "--no-edit", tester_commit],
                cwd=testbench_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                # Try to abort the merge
                subprocess.run(
                    ["git", "merge", "--abort"],
                    cwd=testbench_path,
                    capture_output=True,
                    text=True
                )
                return False
            
            return True
            
        except Exception:
            return False
    
    def run_tests(self, testbench_path):
        """
        Run all tests in the testbench.
        
        Returns a dict with success status and error messages.
        """
        try:
            # Run pytest
            result = subprocess.run(
                ["python", "-m", "pytest", "-q"],
                cwd=testbench_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "output": result.stdout,
                    "errors": []
                }
            else:
                return {
                    "success": False,
                    "output": result.stdout,
                    "errors": result.stderr.splitlines()
                }
                
        except Exception as error:
            return {
                "success": False,
                "output": "",
                "errors": [str(error)]
            }
    
    def cleanup_testbench(self):
        """Clean up the testbench directory."""
        try:
            testbench_workspace = self.test_bench_dir / "workspace"
            if testbench_workspace.exists():
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", str(testbench_workspace)],
                        cwd=self.project_path,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                except subprocess.CalledProcessError:
                    pass
            
            # Remove the testbench directory
            if self.test_bench_dir.exists():
                import shutil
                shutil.rmtree(self.test_bench_dir)
                
        except Exception:
            pass
