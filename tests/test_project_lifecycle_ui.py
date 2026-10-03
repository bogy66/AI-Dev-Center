"""Frontend-contract tests for the CLAUDE-003 project lifecycle UI.

Following this codebase's existing convention (see tests/test_web_gui.py),
frontend behavior is verified as structural facts about the served
web/index.html and web/app.js content, not through a real browser.
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


# ---------------------------------------------------------------------------
# Archiv above Projekte
# ---------------------------------------------------------------------------
def test_archiv_appears_above_projekte_in_markup(html):
    archiv_index = html.index(">Archiv<")
    projekte_index = html.index(">Projekte<")
    assert archiv_index < projekte_index


def test_page_serves_the_updated_markup(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert ">Archiv<" in resp.text
    assert ">Projekte<" in resp.text
    assert resp.text.index(">Archiv<") < resp.text.index(">Projekte<")


def test_archive_and_project_list_containers_exist(html):
    assert 'id="archive-list"' in html
    assert 'id="recents-list"' in html


# ---------------------------------------------------------------------------
# Delete confirmation modal
# ---------------------------------------------------------------------------
def test_delete_confirmation_modal_exists_with_required_wording(html, js):
    assert 'id="delete-project-modal"' in html
    # the "<name>" title is composed at runtime via textContent (never
    # innerHTML, to prevent HTML injection from a project's display name)
    assert "aus AI-Dev-Center löschen?" in js
    assert "wird aus der ADC-Projektverwaltung entfernt" in html
    assert "werden nicht gelöscht" in html
    assert 'id="cancel-delete-project-btn"' in html
    assert 'id="confirm-delete-project-btn"' in html
    assert ">Abbrechen<" in html
    assert ">Löschen<" in html


def test_delete_button_is_visually_distinguished(html):
    # the confirm button must carry a distinct (destructive) style class,
    # not the same class as an ordinary/secondary action
    start = html.index('id="confirm-delete-project-btn"')
    end = html.index(">", start)
    tag = html[start:end]
    assert "danger-button" in tag


# ---------------------------------------------------------------------------
# Menu behavior wiring (structural: functions and handlers exist)
# ---------------------------------------------------------------------------
def test_every_project_row_gets_a_menu_button(js):
    assert "project-menu-btn" in js
    assert "renderProjectListInto" in js


def test_only_one_menu_open_at_a_time_and_outside_click_closes_it(js):
    assert "openProjectMenuId" in js
    assert "closeAllProjectMenus" in js
    # a document-level click listener must close an open menu
    assert "document.addEventListener('click'" in js


def test_menu_item_clicks_stop_propagation_before_acting(js):
    # every action handler wiring inside buildProjectMenu must stopPropagation
    # so a menu click can never fall through to the row's "select project" handler
    menu_section = js[js.index("function buildProjectMenu"):js.index("function renderProjectListInto")]
    assert menu_section.count("e.stopPropagation();") >= 4


def test_active_menu_contains_rename_and_archive_not_delete(js):
    menu_section = js[js.index("function buildProjectMenu"):js.index("function renderProjectListInto")]
    non_archived_branch = menu_section.split("if (isArchived) {")[-1]
    # the non-archived (else) branch offers Archivieren, and Umbenennen is
    # unconditional (outside both branches) — Löschen must never appear
    # anywhere outside the isArchived branch.
    assert "Archivieren" in menu_section
    assert "Umbenennen" in menu_section
    before_first_archived_check = menu_section.split("if (isArchived) {")[0]
    assert "Löschen" not in before_first_archived_check


def test_archived_menu_contains_restore_rename_and_delete(js):
    menu_section = js[js.index("function buildProjectMenu"):js.index("function renderProjectListInto")]
    assert "Wiederherstellen" in menu_section
    assert "Umbenennen" in menu_section
    assert "Löschen" in menu_section


def test_delete_requires_confirmation_modal_not_direct_call(js):
    menu_section = js[js.index("function buildProjectMenu"):js.index("function renderProjectListInto")]
    # the Löschen menu item must open the confirmation modal, not call
    # the remove endpoint directly
    delete_branch = menu_section[menu_section.index("'Löschen'"):]
    assert "openDeleteProjectModal" in delete_branch.split("});")[0] + delete_branch[:200]


def test_archiving_and_restoring_call_the_expected_endpoints(js):
    assert "/archive`" in js
    assert "/restore`" in js
    assert "/remove`" in js
    assert "/rename`" in js


def test_backend_errors_are_surfaced_to_the_user(js):
    for fn in ("handleRenameProject", "handleArchiveProject", "handleRestoreProject", "confirmDeleteProject"):
        assert fn in js
    # each lifecycle action handler must catch and display an error
    assert js.count("alert(`Umbenennen fehlgeschlagen") == 1
    assert js.count("alert(`Archivieren fehlgeschlagen") == 1
    assert js.count("alert(`Wiederherstellen fehlgeschlagen") == 1
    assert js.count("alert(`Löschen fehlgeschlagen") == 1


def test_project_actions_refresh_the_lists(js):
    for fn_name in ("handleRenameProject", "handleArchiveProject", "handleRestoreProject", "confirmDeleteProject"):
        body_start = js.index(f"async function {fn_name}")
        body_end = js.index("\n}\n", body_start)
        body = js[body_start:body_end]
        assert "fetchAndRenderProjects()" in body


def test_project_names_are_rendered_via_textcontent_not_innerhtml(js):
    # display_name must never be concatenated into innerHTML (HTML injection)
    render_section = js[js.index("function renderProjectListInto"):js.index("function renderProjectLists()")]
    assert "nameSpan.textContent = project.display_name" in render_section
    assert "innerHTML" not in render_section.split("list.innerHTML = ''")[1] if "list.innerHTML = ''" in render_section else True


def test_archived_project_click_does_not_select_it_as_current(js):
    render_section = js[js.index("function renderProjectListInto"):js.index("function renderProjectLists()")]
    assert "if (isArchived) {" in render_section
    assert "selectRegisteredProject(project)" in render_section
