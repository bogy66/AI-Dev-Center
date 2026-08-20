import pytest
from unittest.mock import MagicMock, patch
import tempfile
import shutil
from pathlib import Path

from app.requirements_manager import RequirementsManager
from app.workspace_manager import WorkspaceManager
from app.test_bench import TestBench


def test_requirements_manager_parse_requirements_from_task_with_reqs():
    task = "Implement REQ-001 and REQ-002"
    requirements = RequirementsManager.parse_requirements_from_task(task)
    
    assert len(requirements) == 2
    assert requirements[0]["id"] == "REQ-001"
    assert requirements[1]["id"] == "REQ-002"


def test_requirements_manager_parse_requirements_from_task_without_reqs():
    task = "Implement a new feature"
    requirements = RequirementsManager.parse_requirements_from_task(task)
    
    assert len(requirements) == 1
    assert requirements[0]["id"] == "REQ-001"


def test_requirements_manager_validate_requirements():
    requirements = [
        {"id": "REQ-001", "description": "Test", "status": "pending", "tests": []}
    ]
    
    assert RequirementsManager.validate_requirements(requirements) is True
    
    invalid_requirements = [
        {"id": "INVALID", "description": "Test"}
    ]
    
    assert RequirementsManager.validate_requirements(invalid_requirements) is False


def test_workspace_manager_create_workspaces(tmp_path):
    # Initialize git repo
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    
    # Create initial commit
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, check=True, capture_output=True)
    
    workspace_manager = WorkspaceManager(str(tmp_path))
    
    developer_workspace = workspace_manager.create_developer_workspace("test123")
    tester_workspace = workspace_manager.create_tester_workspace("test123")
    
    assert Path(developer_workspace["path"]).exists()
    assert Path(tester_workspace["path"]).exists()
    assert developer_workspace["branch"] == "dev-test123"
    assert tester_workspace["branch"] == "test-test123"
    
    # Cleanup
    workspace_manager.cleanup_workspace("test123")


def test_test_bench_setup_and_cleanup(tmp_path):
    # Initialize git repo
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    
    # Create initial commit
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmp_path, check=True, capture_output=True)
    
    test_bench = TestBench(str(tmp_path))
    
    # Create developer and tester commits
    dev_workspace = tmp_path / ".worktrees" / "developer" / "test123"
    test_workspace = tmp_path / ".worktrees" / "tester" / "test123"
    
    dev_workspace.parent.mkdir(parents=True, exist_ok=True)
    test_workspace.parent.mkdir(parents=True, exist_ok=True)
    
    # Setup testbench
    testbench_path = test_bench.setup_testbench("HEAD", "HEAD")
    
    assert Path(testbench_path).exists()
    
    # Cleanup
    test_bench.cleanup_testbench()
    assert not Path(testbench_path).exists()
