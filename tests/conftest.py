import pytest
import subprocess
from pathlib import Path


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary Git repository with an initial commit."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    
    # Initialize git repository
    subprocess.run(
        ["git", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    
    # Configure git user for tests
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    
    # Create initial file and commit
    readme = repo_path / "README.md"
    readme.write_text("# Test Project\n")
    
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    
    return str(repo_path)


@pytest.fixture
def git_repo_a(tmp_path):
    """Create first Git repository for multi-project tests."""
    repo_path = tmp_path / "project_a"
    repo_path.mkdir()
    
    # Initialize git repository
    subprocess.run(
        ["git", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    
    # Configure git user for tests
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    
    # Create initial file and commit
    readme = repo_path / "README.md"
    readme.write_text("# Test Project A\n")
    
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    
    return str(repo_path)


@pytest.fixture
def git_repo_b(tmp_path):
    """Create second Git repository for multi-project tests."""
    repo_path = tmp_path / "project_b"
    repo_path.mkdir()
    
    # Initialize git repository
    subprocess.run(
        ["git", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    
    # Configure git user for tests
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    
    # Create initial file and commit
    readme = repo_path / "README.md"
    readme.write_text("# Test Project B\n")
    
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    
    return str(repo_path)
