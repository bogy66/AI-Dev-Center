import pytest
import subprocess
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption(
        "--real-system-e2e",
        action="store_true",
        default=False,
        help="Run Real-System E2E tests with real provider/model calls",
    )
    parser.addoption(
        "--diagnostic-level",
        action="store",
        default="NONE",
        choices=["NONE", "NORMAL", "INFO", "VERBOSE", "VERY_VERBOSE"],
        help="Diagnostic trace presentation level (default: NONE)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_system: Real-System E2E test (requires --real-system-e2e)"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--real-system-e2e"):
        return
    skip_real = pytest.mark.skip(reason="Real-System E2E requires --real-system-e2e")
    for item in items:
        if "real_system" in item.keywords:
            item.add_marker(skip_real)


@pytest.fixture(scope="session")
def diagnostic_level(request):
    return request.config.getoption("--diagnostic-level", "NONE")


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
