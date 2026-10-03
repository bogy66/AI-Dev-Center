"""Regression tests for the Engineering Dashboard's Change History
section (CLAUDE-ADC-REQUIREMENTS-DASHBOARD-CHANGE-HISTORY-001).

Two tiers, matching the existing bilingual test-suite convention
(test_i18n_bilingual.py):

- pure unit tests of `change_history.py`'s own logic, against isolated
  scratch git repositories under tmp_path -- always run, never touch the
  real repository, never require a Sphinx build;
- structural tests over the actually-built bilingual site under
  requirements/_build/html/{en,de} -- skipped (not failed) when that
  output does not exist, since building it is a separate, explicit step.
"""
import datetime
import os
import re
import subprocess

import pytest

import change_history

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUILD_ROOT = os.path.join(os.environ.get(
    "ADC_REQUIREMENTS_BUILD_ROOT", os.path.join(os.path.dirname(__file__), "_build")
), "html")
EN_ROOT = os.path.join(BUILD_ROOT, "en")
DE_ROOT = os.path.join(BUILD_ROOT, "de")
DEFAULT_ROOT = BUILD_ROOT

_bilingual_build_present = os.path.isdir(EN_ROOT) and os.path.isdir(DE_ROOT)
requires_build = pytest.mark.skipif(
    not _bilingual_build_present,
    reason="bilingual site not built -- run requirements/build.sh first",
)


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
    )


def _init_repo(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _write(repo, relative_path, content):
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _commit_all(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


# ============================================================================
# Unit tests: compute_latest_model_change / _latest_change_for
# ============================================================================

def test_clean_committed_file_uses_commit_time_not_checkout_mtime(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "model/a.rst", "content A")
    _commit_all(tmp_path, "add a.rst")

    # Touch the file's mtime forward without changing/recommitting its
    # content or dirtying it -- a clean file's mtime must never be used.
    future = datetime.datetime.now().timestamp() + 10_000
    os.utime(tmp_path / "model" / "a.rst", (future, future))
    assert _git(tmp_path, "status", "--porcelain").stdout.strip() == ""  # still clean

    moment = change_history._latest_change_for(str(tmp_path), "model/a.rst")
    assert moment is not None
    assert moment.timestamp() < future  # commit time, not the forward-touched mtime


def test_dirty_uncommitted_file_uses_filesystem_mtime(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "model/a.rst", "content A")
    _commit_all(tmp_path, "add a.rst")
    _write(tmp_path, "model/a.rst", "content A changed, never committed")

    moment = change_history._latest_change_for(str(tmp_path), "model/a.rst")
    real_mtime = datetime.datetime.fromtimestamp(
        os.path.getmtime(tmp_path / "model" / "a.rst"),
    ).astimezone()
    assert moment == real_mtime


def test_no_git_repository_falls_back_to_mtime(tmp_path):
    # No git init at all -- change_history must still produce a real
    # timestamp from the filesystem rather than raising or returning None.
    _write(tmp_path, "model/a.rst", "content A, no git here")
    moment = change_history._latest_change_for(str(tmp_path), "model/a.rst")
    assert moment is not None


def test_noop_recomputation_does_not_advance_timestamp(tmp_path):
    """A "no-op rebuild" -- calling compute_latest_model_change again
    with nothing touched -- must return the exact same moment."""
    _init_repo(tmp_path)
    _write(tmp_path, "model/a.rst", "content A")
    _write(tmp_path, "unrelated/style.css", "body {}")
    _commit_all(tmp_path, "initial")
    sources = ("model/a.rst", "unrelated/style.css")

    first = change_history.compute_latest_model_change(str(tmp_path), sources)
    second = change_history.compute_latest_model_change(str(tmp_path), sources)
    assert first == second


def test_meaningful_model_change_advances_the_timestamp(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "model/a.rst", "content A")
    _write(tmp_path, "unrelated/style.css", "body {}")
    _commit_all(tmp_path, "initial")
    sources = ("model/a.rst", "unrelated/style.css")

    before = change_history.compute_latest_model_change(str(tmp_path), sources)
    _write(tmp_path, "model/a.rst", "content A -- a real semantic model change")
    after = change_history.compute_latest_model_change(str(tmp_path), sources)

    assert after is not None and before is not None
    assert after > before


def test_unrelated_artifact_change_does_not_advance_the_timestamp(tmp_path):
    """Changing a file that is NOT one of the model source files (e.g. a
    generated HTML/CSS/build artifact) must never advance the reported
    change timestamp."""
    _init_repo(tmp_path)
    _write(tmp_path, "model/a.rst", "content A")
    _write(tmp_path, "unrelated/style.css", "body {}")
    _commit_all(tmp_path, "initial")
    sources = ("model/a.rst",)  # style.css deliberately excluded from scope

    before = change_history.compute_latest_model_change(str(tmp_path), sources)
    _write(tmp_path, "unrelated/style.css", "body { color: red; }")  # dirty, unrelated
    after = change_history.compute_latest_model_change(str(tmp_path), sources)

    assert after == before


def test_real_model_source_files_are_the_defined_central_scope():
    """The real MODEL_SOURCE_FILES list is exactly the authoritative,
    model-bearing sources -- never dashboard/pilot/locale/static
    presentation files, which must not be able to advance the
    timestamp."""
    for relative in change_history.MODEL_SOURCE_FILES:
        assert not relative.startswith("requirements/dashboard/")
        assert not relative.startswith("requirements/pilot/")
        assert not relative.startswith("requirements/locale/")
        assert not relative.startswith("requirements/_static/")
        assert not relative.startswith("requirements/_build/")
        assert os.path.exists(os.path.join(REPO_ROOT, relative))


# ============================================================================
# Unit tests: localized presentation
# ============================================================================

def test_german_and_english_formatting_share_the_same_moment():
    moment = datetime.datetime(2026, 9, 20, 8, 49)
    en = change_history.format_change_timestamp(moment, "en")
    de = change_history.format_change_timestamp(moment, "de")
    assert en == "2026-09-20 08:49"
    assert de == "20.09.2026, 08:49"
    # Both strings describe the identical wall-clock moment.
    assert datetime.datetime.strptime(en, "%Y-%m-%d %H:%M") == \
        datetime.datetime.strptime(de, "%d.%m.%Y, %H:%M")


def test_render_change_history_html_localizes_label_only():
    moment = datetime.datetime(2026, 9, 20, 8, 49)
    en_html = change_history.render_change_history_html(moment, "en")
    de_html = change_history.render_change_history_html(moment, "de")
    assert "Last change" in en_html and "2026-09-20 08:49" in en_html
    assert "Letzte Änderung" in de_html and "20.09.2026, 08:49" in de_html


def test_render_change_history_html_handles_unknown_moment_gracefully():
    html = change_history.render_change_history_html(None, "en")
    assert "unknown" in html


def test_change_history_details_show_git_change_sets_and_requirement_links(tmp_path):
    _init_repo(tmp_path)
    path = "requirements/system/system_requirements.rst"
    _write(
        tmp_path, path,
        ".. sysreq:: Existing requirement\n   :id: SYS_REQ_001\n\n   Original contract.\n",
    )
    _commit_all(tmp_path, "initial requirement")
    _write(
        tmp_path, path,
        ".. sysreq:: Existing requirement\n   :id: SYS_REQ_001\n\n   Updated contract.\n\n"
        ".. subreq:: New requirement\n   :id: SUB_REQ_001\n\n   New contract.\n",
    )
    _git(tmp_path, "add", path)
    _git(tmp_path, "commit", "-q", "-m", "update and add requirements")

    html = change_history.render_change_history_details(str(tmp_path), "en")
    assert "Git version" in html
    assert "SYS_REQ_001" in html and "SUB_REQ_001" in html
    assert 'href="../system/system_requirements.html#SYS_REQ_001"' in html
    assert 'href="../system/system_requirements.html#SUB_REQ_001"' in html
    assert "initial requirement" in html
    assert "update and add requirements" in html


def test_change_history_details_show_uncommitted_requirement_changes(tmp_path):
    _init_repo(tmp_path)
    path = "requirements/interfaces/interface_requirements.rst"
    _write(
        tmp_path, path,
        ".. ifreq:: Existing interface contract\n   :id: IF_REQ_001\n\n   Before.\n",
    )
    _commit_all(tmp_path, "initial interface requirement")
    _write(
        tmp_path, path,
        ".. ifreq:: Existing interface contract\n   :id: IF_REQ_001\n\n   After.\n\n"
        ".. ifreq:: New interface contract\n   :id: IF_REQ_002\n\n   New.\n",
    )

    html = change_history.render_change_history_details(str(tmp_path), "de")
    assert "Nicht committeter Arbeitsbaum" in html
    assert "Geänderte Anforderungen" in html
    assert "Hinzugefügte Anforderungen" in html
    assert 'href="../interfaces/interface_requirements.html#IF_REQ_001"' in html
    assert 'href="../interfaces/interface_requirements.html#IF_REQ_002"' in html


# ============================================================================
# Structural tests over the actually-built bilingual site
# ============================================================================

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@requires_build
def test_german_dashboard_contains_heading_and_label():
    html = _read(os.path.join(DE_ROOT, "dashboard", "overview.html"))
    assert "Änderung History" in html
    assert "Letzte Änderung:" in html


@requires_build
def test_english_dashboard_contains_heading_and_label():
    html = _read(os.path.join(EN_ROOT, "dashboard", "overview.html"))
    assert "Change History" in html
    assert "Last change:" in html


@requires_build
def test_default_english_dashboard_mirror_is_fresh_and_switches_to_german():
    en_html = _read(os.path.join(EN_ROOT, "dashboard", "overview.html"))
    default_html = _read(os.path.join(DEFAULT_ROOT, "dashboard", "overview.html"))
    en_match = re.search(r"Last change:</strong> ([\d\-: ]+)", en_html)
    default_match = re.search(r"Last change:</strong> ([\d\-: ]+)", default_html)
    assert en_match and default_match
    assert default_match.group(1) == en_match.group(1)
    assert 'href="../de/dashboard/overview.html"' in default_html


@requires_build
def test_change_history_section_precedes_implementation_status_en():
    # Matched by section id (stable, language-independent anchor), not by
    # visible heading text: the page <head>'s Sphinx-generated prev/next
    # navigation link also carries the literal title of the NEXT page
    # ("Requirement Implementation Status" is requirement_status.rst's
    # own page title), which would otherwise produce a false early match.
    html = _read(os.path.join(EN_ROOT, "dashboard", "overview.html"))
    assert html.index('id="change-history"') < html.index('id="requirement-implementation-status"')


@requires_build
def test_change_history_section_precedes_implementation_status_de():
    html = _read(os.path.join(DE_ROOT, "dashboard", "overview.html"))
    assert html.index('id="change-history"') < html.index('id="requirement-implementation-status"')


@requires_build
def test_en_de_display_the_same_underlying_change_timestamp():
    en_html = _read(os.path.join(EN_ROOT, "dashboard", "overview.html"))
    de_html = _read(os.path.join(DE_ROOT, "dashboard", "overview.html"))

    en_match = re.search(r"Last change:</strong> ([\d\-: ]+)", en_html)
    de_match = re.search(r"Letzte Änderung:</strong> ([\d.,: ]+)", de_html)
    assert en_match and de_match

    en_moment = datetime.datetime.strptime(en_match.group(1), "%Y-%m-%d %H:%M")
    de_moment = datetime.datetime.strptime(de_match.group(1), "%d.%m.%Y, %H:%M")
    assert en_moment == de_moment


@requires_build
def test_change_history_marker_never_leaks_into_output():
    for root in (EN_ROOT, DE_ROOT):
        html = _read(os.path.join(root, "dashboard", "overview.html"))
        assert change_history.CHANGE_HISTORY_MARKER not in html
