"""Frontend-contract tests for the CLAUDE-005 repository-import UI.

Follows the same structural-content approach as
tests/test_project_lifecycle_ui.py: verified as facts about the served
web/index.html and web/app.js, not through a real browser.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.web_api import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def html():
    return Path("web/index.html").read_text(encoding="utf-8")


@pytest.fixture
def js():
    return Path("web/app.js").read_text(encoding="utf-8")


def test_import_repository_action_exists(html):
    assert 'id="import-repo-btn"' in html
    assert "Repository importieren" in html


def test_page_serves_the_import_action(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Repository importieren" in resp.text


def test_import_modal_has_required_fields(html):
    assert 'id="import-repo-modal"' in html
    assert 'id="import-repo-source"' in html
    assert 'id="import-repo-parent"' in html
    assert 'id="import-repo-target-name"' in html
    assert 'id="import-repo-choose-parent-btn"' in html
    assert 'id="confirm-import-repo-btn"' in html
    assert 'id="cancel-import-repo-btn"' in html
    assert 'id="import-repo-error"' in html


def test_import_reuses_the_existing_directory_picker_endpoint(js):
    import_section = js[js.index("// ---------- Repository import"):js.index("// ---------- Chat")]
    assert "/api/project/select-directory" in js
    # the dedicated Choose-parent listener must call the same endpoint
    listener_start = js.index("import-repo-choose-parent-btn").__index__()
    nearby = js[listener_start:listener_start + 400]
    assert "/api/project/select-directory" in nearby


def test_import_posts_to_the_dedicated_import_endpoint(js):
    assert "/api/projects/import" in js


def test_import_shows_busy_state_and_prevents_duplicate_submission(js):
    assert "importRepoInFlight" in js
    handler = js[js.index("async function handleConfirmImportRepo"):js.index("// ---------- Event binding") if "// ---------- Event binding" in js else len(js)]
    assert "if (importRepoInFlight) return;" in handler
    assert "setImportRepoBusy(true)" in handler


def test_import_error_is_displayed_not_silently_swallowed(js):
    handler_start = js.index("async function handleConfirmImportRepo")
    handler_end = js.index("\n}\n", handler_start)
    handler = js[handler_start:handler_end]
    assert "showImportRepoError" in handler


def test_import_success_refreshes_active_project_list(js):
    handler_start = js.index("async function handleConfirmImportRepo")
    handler_end = js.index("\n}\n", handler_start)
    handler = js[handler_start:handler_end]
    assert "fetchAndRenderProjects()" in handler


def test_import_does_not_trigger_workflow_start(js):
    handler_start = js.index("async function handleConfirmImportRepo")
    handler_end = js.index("\n}\n", handler_start)
    handler = js[handler_start:handler_end]
    assert "/api/workflow/start" not in handler


def test_import_button_wired_to_open_modal(js):
    assert "document.getElementById('import-repo-btn').addEventListener('click', openImportRepoModal);" in js
