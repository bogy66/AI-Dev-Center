import pytest
import subprocess
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_project_registry(tmp_path_factory, monkeypatch):
    """Prevent any test from writing into the real .project-definitions store.

    app.web_api.get_project_registry defaults to the productive
    ".project-definitions/definitions.json" path (the same store used by
    the real ProjectDefinitionStore()). A test that exercises an endpoint
    depending on it — e.g. POST /api/workflow/start — without its own
    explicit override must not silently create or mutate real repository
    state.

    This patches the module-level default path constant directly (via
    monkeypatch, auto-restored per test) rather than FastAPI's
    dependency_overrides dict, because several existing test fixtures in
    this suite call app.dependency_overrides.clear() as part of their own
    session-cleanup, which would silently wipe an override placed there
    instead. Tests that need specific registry behavior still set their
    own app.dependency_overrides[get_project_registry] explicitly, which
    takes precedence over this default when present.

    Uses tmp_path_factory (not the per-test tmp_path fixture) so this
    never appears as an unexpected extra entry for tests that assert
    exclusive ownership of their own tmp_path.
    """
    import app.web_api as web_api_module

    store_path = tmp_path_factory.mktemp("project-registry") / "definitions.json"
    monkeypatch.setattr(web_api_module, "PROJECT_DEFINITIONS_PATH", str(store_path))


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
