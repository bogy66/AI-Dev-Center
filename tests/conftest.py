import pytest
import subprocess
from pathlib import Path

# CLAUDE-ADC-TESTBED-EVIDENCE-INFRASTRUCTURE-001: registers the --adc-evidence
# option (and its hooks) for every pytest invocation. Fully inert unless a
# formal run explicitly passes --adc-evidence: without it, every hook in
# requirements/evidence/pytest_plugin.py returns immediately -- no Evidence
# Contract import cost beyond hook registration, no filesystem writes, no
# Sphinx dependency. See that module's own docstring for the opt-in contract.
# Plugin registration lives in the repository-root conftest.py.


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
    if not config.getoption("--real-system-e2e"):
        skip_real = pytest.mark.skip(reason="Real-System E2E requires --real-system-e2e")
        for item in items:
            if "real_system" in item.keywords:
                item.add_marker(skip_real)

    # KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 sections 1 and 6: equivalence-
    # class coverage is now PASS-VERIFIED from real 'call'-phase outcomes
    # (see pytest_runtest_makereport below and tests/env_scenarios.py),
    # not from import-time decorator registration. Those two meta-gate
    # modules can therefore only see accurate results if every other test
    # declaring coverage via covers() has already actually executed in
    # this same session -- move them to run last, stable-sorted so
    # relative order is otherwise unchanged.
    _LAST_MODULES = ("test_env_equivalence_classes", "test_gate1_proof_meta_gate")
    items.sort(key=lambda item: any(m in item.nodeid for m in _LAST_MODULES))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if call.when != "call":
        return
    report = outcome.get_result()
    func = getattr(item, "function", None)
    if func is None:
        return
    passed = report.outcome == "passed" and getattr(report, "wasxfail", None) is None
    from tests.env_scenarios import record_test_outcome

    record_test_outcome(func.__module__, func.__qualname__, passed=passed)


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


@pytest.fixture(autouse=True)
def _isolated_approved_plan_content(tmp_path_factory, monkeypatch):
    """Default stores in tests must never resolve to tracked operator state.

    Explicit storage paths retain their semantics. Patch the class constructor
    so every already-imported alias uses the same per-test isolated default.
    """
    from app.approved_plan_content import ApprovedPlanContentStore

    original = ApprovedPlanContentStore.__init__
    isolated = tmp_path_factory.mktemp("approved-content") / "approved_plan_content.json"

    def init(self, storage=None):
        original(self, isolated if storage is None or str(storage) == "approved_plan_content.json" else storage)

    monkeypatch.setattr(ApprovedPlanContentStore, "__init__", init)


@pytest.fixture(autouse=True)
def _isolated_default_diagnostic_trace(tmp_path_factory, monkeypatch):
    """Keep implicit service traces out of the operator's append-only store.

    Explicit scratch paths retain their persistence/restart semantics. Patch
    the class constructor so already-imported aliases use the same isolated
    path within a test. Guard the operational file as well, so an existing
    instance or a new unisolated writer cannot silently escape the fixture.
    """
    from app.diagnostic_trace import DiagnosticTraceStore

    operational = Path(__file__).resolve().parents[1] / ".diagnostic-traces" / "events.jsonl"
    isolated = tmp_path_factory.mktemp("default-diagnostic-trace") / "events.jsonl"
    original = DiagnosticTraceStore.__init__

    def fingerprint():
        if not operational.exists():
            return None
        stat = operational.stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns

    before = fingerprint()

    def init(self, path):
        target = Path(path)
        original(self, isolated if target.resolve() == operational.resolve() else path)

    monkeypatch.setattr(DiagnosticTraceStore, "__init__", init)
    yield
    assert fingerprint() == before, "test modified the operator's diagnostic trace store"
