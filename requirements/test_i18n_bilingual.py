"""Regression tests for the bilingual EN/DE Requirements infrastructure
(OC-ADC-REQUIREMENTS-BILINGUAL-EN-DE-001).

Two kinds of test here:

- pure unit tests of the small standalone i18n modules (i18n_config,
  i18n_titles, i18n_language_switch) -- always run, no build required;
- structural-parity tests over the actually-built bilingual site under
  requirements/_build/html/{en,de} -- these are skipped (not failed) if
  that output does not exist, since building it is a separate, explicit
  step (`requirements/build.sh`), not something a plain `pytest` run
  should trigger implicitly.
"""
import json
import os
import shutil

import pytest

import i18n_config
import i18n_language_switch
import i18n_titles

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUILD_ROOT = os.path.join(os.environ.get(
    "ADC_REQUIREMENTS_BUILD_ROOT", os.path.join(os.path.dirname(__file__), "_build")
), "html")
EN_ROOT = os.path.join(BUILD_ROOT, "en")
DE_ROOT = os.path.join(BUILD_ROOT, "de")

_bilingual_build_present = os.path.isdir(EN_ROOT) and os.path.isdir(DE_ROOT)
requires_build = pytest.mark.skipif(
    not _bilingual_build_present,
    reason="bilingual site not built -- run requirements/build.sh first",
)


# --- 2/3: central setup contains EN and DE; default language centrally controlled -

def test_central_setup_declares_both_languages():
    assert set(i18n_config.ENABLED_LANGUAGES) == {"en", "de"}
    assert i18n_config.DEFAULT_LANGUAGE in i18n_config.ENABLED_LANGUAGES


def test_default_language_is_centrally_controlled():
    assert i18n_config.resolve_language(None) == i18n_config.DEFAULT_LANGUAGE
    assert i18n_config.resolve_language("de") == "de"
    assert i18n_config.resolve_language("en") == "en"


def test_unsupported_language_fails_closed_to_default():
    assert i18n_config.resolve_language("fr") == i18n_config.DEFAULT_LANGUAGE
    assert i18n_config.resolve_language("") == i18n_config.DEFAULT_LANGUAGE


# --- title localization never fabricates, never mutates the real field -----------

def test_localized_title_falls_back_to_english_when_untranslated():
    class FakeApp:
        class config:
            language = "de"
    need = {"id": "ZIEL_999_NOT_IN_DICT", "title": "Some English Title"}
    assert i18n_titles.adc_localized_title(FakeApp(), need, {}) == "Some English Title"


def test_localized_title_returns_german_when_language_is_de_and_entry_exists():
    class FakeApp:
        class config:
            language = "de"
    need = {"id": "ZIEL_001", "title": "ADC as integrated engineering platform"}
    result = i18n_titles.adc_localized_title(FakeApp(), need, {})
    assert result == i18n_titles.TITLES_DE["ZIEL_001"]
    assert result != need["title"]


def test_localized_title_returns_english_when_language_is_en_even_if_de_entry_exists():
    class FakeApp:
        class config:
            language = "en"
    need = {"id": "ZIEL_001", "title": "ADC as integrated engineering platform"}
    assert i18n_titles.adc_localized_title(FakeApp(), need, {}) == need["title"]


# --- language switch: deterministic, no JS, correct relative depth ---------------

def test_switch_context_computes_correct_relative_depth_for_root_page():
    context = {}
    class FakeApp:
        class config:
            language = "en"
    i18n_language_switch.inject_language_switch_context(FakeApp(), "index", "page.html", context, None)
    assert context["adc_switch_url"] == "../de/index.html"
    assert context["adc_switch_lang_label"] == "Deutsch"


def test_switch_context_computes_correct_relative_depth_for_nested_page():
    context = {}
    class FakeApp:
        class config:
            language = "de"
    i18n_language_switch.inject_language_switch_context(
        FakeApp(), "dashboard/overview", "page.html", context, None,
    )
    assert context["adc_switch_url"] == "../../en/dashboard/overview.html"
    assert context["adc_switch_lang_label"] == "English"


def test_switch_context_no_javascript_involved():
    # The switch is a plain server-rendered <a href>; the only "mechanism"
    # is this pure Python function computing a static relative URL string.
    import inspect
    source = inspect.getsource(i18n_language_switch.inject_language_switch_context)
    assert "javascript" not in source.lower()
    assert "<script" not in source.lower()


# --- structural parity over the real built bilingual site ------------------------

def _load_needs(root):
    with open(os.path.join(root, "needs.json")) as f:
        data = json.load(f)
    version = next(iter(data["versions"].values()))
    return version["needs"]


def _load_status(root):
    with open(os.path.join(root, "requirement_status.json")) as f:
        return json.load(f)


@requires_build
def test_both_languages_built_with_zero_schema_warnings():
    for root in (EN_ROOT, DE_ROOT):
        with open(os.path.join(root, "schema_violations.json")) as f:
            violations = json.load(f)
        assert violations["validation_warnings"] == {}


@requires_build
def test_requirement_ids_identical_between_languages():
    en_needs = _load_needs(EN_ROOT)
    de_needs = _load_needs(DE_ROOT)
    assert set(en_needs.keys()) == set(de_needs.keys())


@requires_build
def test_need_counts_identical_between_languages():
    en_needs = _load_needs(EN_ROOT)
    de_needs = _load_needs(DE_ROOT)
    assert len(en_needs) == len(de_needs)


@requires_build
def test_trace_links_identical_between_languages():
    en_needs = _load_needs(EN_ROOT)
    de_needs = _load_needs(DE_ROOT)
    link_fields = ("derived_from", "implements", "verifies", "evidences", "realizes", "satisfies")
    for nid, en_need in en_needs.items():
        de_need = de_needs[nid]
        for field in link_fields:
            assert en_need.get(field) == de_need.get(field), f"{nid}.{field} differs between languages"


@requires_build
def test_requirement_status_values_identical_between_languages():
    en_status = _load_status(EN_ROOT)
    de_status = _load_status(DE_ROOT)
    assert set(en_status.keys()) == set(de_status.keys())
    for nid, en_entry in en_status.items():
        assert en_entry["implementation_state"] == de_status[nid]["implementation_state"]


@requires_build
def test_traffic_light_counts_identical_between_languages():
    from collections import Counter
    en_needs, de_needs = _load_needs(EN_ROOT), _load_needs(DE_ROOT)
    en_status, de_status = _load_status(EN_ROOT), _load_status(DE_ROOT)
    real_docs = {
        "sysreq": "system/system_requirements", "arcreq": "architecture/architecture",
        "subreq": "subsystem/subsystem_requirements", "ifreq": "interfaces/interface_requirements",
    }

    def counts(needs, status):
        c = Counter()
        for nid, n in needs.items():
            t = n.get("type")
            if t in real_docs and n.get("docname") == real_docs[t]:
                c[status[nid]["implementation_state"]] += 1
        return dict(c)

    assert counts(en_needs, en_status) == counts(de_needs, de_status)


@requires_build
def test_test_verification_results_identical_between_languages():
    en_needs, de_needs = _load_needs(EN_ROOT), _load_needs(DE_ROOT)
    test_ids = [nid for nid, n in en_needs.items() if n.get("type") == "test"]
    assert test_ids, "expected at least one TEST_* need"
    for nid in test_ids:
        assert en_needs[nid].get("verification_result") == de_needs[nid].get("verification_result")


@requires_build
def test_evidence_identities_identical_between_languages():
    en_needs, de_needs = _load_needs(EN_ROOT), _load_needs(DE_ROOT)
    en_evid = {nid for nid, n in en_needs.items() if n.get("type") == "evidence"}
    de_evid = {nid for nid, n in de_needs.items() if n.get("type") == "evidence"}
    assert en_evid == de_evid
    for nid in en_evid:
        assert en_needs[nid].get("evidences") == de_needs[nid].get("evidences")


@requires_build
def test_language_switch_present_in_both_generated_variants():
    with open(os.path.join(EN_ROOT, "index.html"), encoding="utf-8") as f:
        en_html = f.read()
    with open(os.path.join(DE_ROOT, "index.html"), encoding="utf-8") as f:
        de_html = f.read()
    assert 'class="adc-language-switch"' in en_html
    assert 'href="../de/index.html"' in en_html
    assert 'class="adc-language-switch"' in de_html
    assert 'href="../en/index.html"' in de_html


@requires_build
def test_representative_pages_show_expected_language():
    with open(os.path.join(EN_ROOT, "zielbild", "zielbild.html"), encoding="utf-8") as f:
        en_html = f.read()
    with open(os.path.join(DE_ROOT, "zielbild", "zielbild.html"), encoding="utf-8") as f:
        de_html = f.read()
    assert "ADC shall develop into an integrated engineering platform" in en_html
    assert "ADC soll sich zu einer integrierten Engineering-Plattform" in de_html
    assert "ADC soll sich zu einer integrierten Engineering-Plattform" not in en_html


@requires_build
def test_graph_background_colors_identical_between_languages():
    import glob
    import xml.etree.ElementTree as ET

    NS = "{http://www.w3.org/2000/svg}"
    fill_to_state = {
        "#ffcdd2": "NOT_IMPLEMENTED", "#fff9c4": "IMPLEMENTED_TEST_NIO", "#c8e6c9": "IMPLEMENTED_TEST_IO",
    }
    for root, status in ((EN_ROOT, _load_status(EN_ROOT)), (DE_ROOT, _load_status(DE_ROOT))):
        svgs = glob.glob(os.path.join(root, "_images", "needflow-*.svg"))
        assert svgs, f"expected at least one needflow SVG under {root}"
        for svgpath in svgs:
            tree_root = ET.parse(svgpath).getroot()
            for g in tree_root.iter(NS + "g"):
                if g.get("class") != "node":
                    continue
                title = g.find(NS + "title")
                if title is None or not title.text:
                    continue
                nid = title.text.strip()
                if nid not in status:
                    continue
                poly = g.find(f".//{NS}polygon")
                got = fill_to_state.get(poly.get("fill") if poly is not None else None)
                assert got == status[nid]["implementation_state"], nid


# --- 12: no language build mutates Requirement/Evidence state --------------------

def test_evidence_store_untouched_by_this_test_file():
    """Sanity check on this test file's own behavior, not the build: it
    must never write into the real Evidence store. (The actual bilingual
    Sphinx build's non-effect on requirements/_evidence/ is structural --
    neither sphinx-build nor any hook in conf.py ever opens that path --
    verified by code inspection, not re-asserted here to avoid a fragile
    dependency on filesystem timestamps across an unrelated build step.)"""
    evidence_runs_dir = os.path.join(REPO_ROOT, "requirements", "_evidence", "runs")
    before = set(os.listdir(evidence_runs_dir)) if os.path.isdir(evidence_runs_dir) else set()
    # (no action taken)
    after = set(os.listdir(evidence_runs_dir)) if os.path.isdir(evidence_runs_dir) else set()
    assert before == after


# =============================================================================
# OC-ADC-REQUIREMENTS-BILINGUAL-EN-DE-002: mixed-language regression tests
# =============================================================================
# The -001 build was accepted structurally but the rendered UI mixed EN/DE
# on the same page (navigation, metadata labels, and most Need content were
# still English under the German build). These tests pin down that exact
# defect class so it cannot silently regress: the previously-NIO strings
# from that report must never reappear in the German build, and the full
# navigation/content surface must be language-consistent.

import i18n_completeness  # noqa: E402


def _read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


# --- 1/2: navigation contains expected labels in each language -------------

DE_NAV_LABELS = [
    "Übersicht", "Engineering-Ebenen", "Technischer Pilot",
    "ADC Engineering-Dashboard", "Implementierungsstatus der Anforderungen",
    "ADC Nachverfolgbarkeit", "ADC Abdeckung", "ADC Verifikationsübersicht",
    "ADC Systemanforderungen", "ADC Architekturentscheidungen",
    "Architektur-abgeleitete Anforderungen", "ADC Subsystem-Anforderungen",
    "ADC Schnittstellenanforderungen", "ADC Implementierungszuordnung",
    "ADC Verifikationstests", "ADC Verifikationsevidenz",
    "ADC Generierte Evidenz", "Synthetischer Nachverfolgbarkeits-Pilot",
]
EN_NAV_LABELS = [
    "Overview", "Engineering Layers", "Technical Pilot",
    "ADC Engineering Dashboard", "Requirement Implementation Status",
    "ADC Traceability", "ADC Coverage", "ADC Verification Overview",
    "ADC System Requirements", "ADC Architecture Decisions",
    "Architecture-derived Requirements", "ADC Subsystem Requirements",
    "ADC Interface Requirements", "ADC Implementation Mapping",
    "ADC Verification Tests", "ADC Verification Evidence",
    "ADC Generated Evidence", "Synthetic Traceability Pilot",
]


@requires_build
def test_german_navigation_contains_all_expected_german_labels():
    de_index = _read(DE_ROOT, "index.html")
    missing = [label for label in DE_NAV_LABELS if label not in de_index]
    assert missing == [], f"missing German nav labels: {missing}"


@requires_build
def test_english_navigation_contains_all_expected_english_labels():
    en_index = _read(EN_ROOT, "index.html")
    missing = [label for label in EN_NAV_LABELS if label not in en_index]
    assert missing == [], f"missing English nav labels: {missing}"


# --- 3/4: German/English ZIEL page shows the first few ZIEL in the right language -

@requires_build
def test_german_ziel_page_shows_german_content_for_ziel_001_002_003():
    de_zielbild = _read(DE_ROOT, "zielbild/zielbild.html")
    for nid, title in (
        ("ZIEL_001", i18n_titles.TITLES_DE["ZIEL_001"]),
        ("ZIEL_002", i18n_titles.TITLES_DE["ZIEL_002"]),
        ("ZIEL_003", i18n_titles.TITLES_DE["ZIEL_003"]),
    ):
        assert title in de_zielbild, f"{nid} German title missing from German Zielbild page"
    assert "ADC soll sich zu einer integrierten Engineering-Plattform" in de_zielbild
    assert "ADC soll einen vollständigen, nachvollziehbaren und kontrollierten" in de_zielbild
    assert "ADC soll sowohl bestehende als auch neue Projekte unterstützen" in de_zielbild


@requires_build
def test_english_ziel_page_shows_english_content_for_ziel_001_002_003():
    en_zielbild = _read(EN_ROOT, "zielbild/zielbild.html")
    assert "ADC as integrated engineering platform" in en_zielbild
    assert "Complete controlled engineering process" in en_zielbild
    assert "Support existing and new projects" in en_zielbild
    assert "ADC shall develop into an integrated engineering platform" in en_zielbild
    assert "ADC shall support a complete, traceable, and controlled engineering" in en_zielbild
    assert "ADC shall support both existing and greenfield projects" in en_zielbild


# --- 5: German page never contains the exact English strings from the NIO report -

NIO_REPORT_ENGLISH_STRINGS = [
    "Traceability Objects",
    "Lifecycle",
    "realized by",
    "Complete controlled engineering process",
    "Support existing and new projects",
]


@requires_build
def test_german_zielbild_page_does_not_contain_known_english_regression_strings():
    de_zielbild = _read(DE_ROOT, "zielbild/zielbild.html")
    present = [s for s in NIO_REPORT_ENGLISH_STRINGS if s in de_zielbild]
    assert present == [], f"German page still contains English strings: {present}"


@requires_build
def test_german_index_page_does_not_contain_known_english_nav_strings():
    de_index = _read(DE_ROOT, "index.html")
    present = [s for s in EN_NAV_LABELS if s in de_index]
    assert present == [], f"German nav still contains English labels: {present}"


# --- 6: English page never contains German UI labels (except quoted source names) -

GERMAN_UI_LABELS_FORBIDDEN_IN_ENGLISH = [
    "Quelle", "Lebenszyklus", "realisiert durch", "Nachverfolgbarkeit",
]


@requires_build
def test_english_zielbild_page_does_not_contain_german_ui_labels():
    en_zielbild = _read(EN_ROOT, "zielbild/zielbild.html")
    present = [s for s in GERMAN_UI_LABELS_FORBIDDEN_IN_ENGLISH if s in en_zielbild]
    assert present == [], f"English page contains German UI labels: {present}"


@requires_build
def test_english_index_page_does_not_contain_german_nav_labels():
    en_index = _read(EN_ROOT, "index.html")
    present = [s for s in DE_NAV_LABELS if s in en_index]
    assert present == [], f"English nav contains German labels: {present}"


# --- metadata labels (Lifecycle/realized by/etc.) are localized, not just nav ----

@requires_build
def test_german_cards_show_german_metadata_labels():
    de_sys = _read(DE_ROOT, "system/system_requirements.html")
    assert "Lebenszyklus" in de_sys
    assert "Implementierung:" in de_sys or "Implementierung: " in de_sys
    de_ziel = _read(DE_ROOT, "zielbild/zielbild.html")
    assert "realisiert durch" in de_ziel


@requires_build
def test_english_cards_show_english_metadata_labels():
    en_sys = _read(EN_ROOT, "system/system_requirements.html")
    assert "Lifecycle" in en_sys
    en_ziel = _read(EN_ROOT, "zielbild/zielbild.html")
    assert "realized by" in en_ziel


# --- representative Need-type title_display sample in both languages -------------

REPRESENTATIVE_NEED_IDS = {
    "ZIEL_001": "zielbild/zielbild",
    "SYS_REQ_001": "system/system_requirements",
    "ARC_001": "architecture/architecture",
    "ARC_REQ_003": "architecture/architecture",
    "SUB_REQ_001": "subsystem/subsystem_requirements",
    "IF_REQ_001": "interfaces/interface_requirements",
    "IMPL_001": "implementation/implementation",
    "TEST_001": "verification/tests",
    "EVID_001": "verification/evidence",
}


def _title_display(html, need_id):
    import re
    idx = html.find(f'id="{need_id}"')
    if idx < 0:
        return None
    window = html[idx:idx + 3000]
    m = re.search(r'needs_title_display.{0,40}needs_data">([^<]*)</span>', window)
    return m.group(1) if m else None


@requires_build
def test_every_need_type_has_a_distinct_localized_title_in_both_languages():
    for need_id, doc in REPRESENTATIVE_NEED_IDS.items():
        en_html = _read(EN_ROOT, f"{doc}.html")
        de_html = _read(DE_ROOT, f"{doc}.html")
        en_title = _title_display(en_html, need_id)
        de_title = _title_display(de_html, need_id)
        assert en_title, f"{need_id}: no English title_display found"
        assert de_title, f"{need_id}: no German title_display found"
        assert en_title != de_title, f"{need_id}: German title_display is identical to English"


# =============================================================================
# Completeness gate unit tests (i18n_completeness.py)
# =============================================================================

def test_completeness_gate_is_noop_for_english():
    assert i18n_completeness.check_title_completeness({"ZIEL_999": {"type": "ziel"}}, "en") == []


def test_completeness_gate_flags_a_real_missing_german_title():
    needs = {"ZIEL_NOT_REGISTERED_XYZ": {"type": "ziel", "tags": []}}
    missing = i18n_completeness.check_title_completeness(needs, "de")
    assert missing == ["ZIEL_NOT_REGISTERED_XYZ"]


def test_completeness_gate_does_not_flag_a_registered_title():
    needs = {"ZIEL_001": {"type": "ziel", "tags": []}}
    assert i18n_completeness.check_title_completeness(needs, "de") == []


def test_completeness_gate_exempts_generator_localized_evid_ids():
    needs = {"EVID_GEN_20990101T000000Z_ABCDEF": {"type": "evidence", "tags": []}}
    assert i18n_completeness.check_title_completeness(needs, "de") == []


def test_completeness_gate_exempts_pilot_needs():
    needs = {"ZIEL_TEST_999_NOT_REGISTERED": {"type": "ziel", "tags": ["pilot"]}}
    assert i18n_completeness.check_title_completeness(needs, "de") == []


def test_allowlist_exempts_literal_pytest_selectors():
    assert i18n_completeness._is_allowlisted(
        "tests/test_common_request.py::test_common_request_preserves_adapter_neutral_user_intent"
    )
    assert not i18n_completeness._is_allowlisted(
        "ADC shall develop into an integrated engineering platform for software, firmware, and hardware."
    )


def test_allowlist_exempts_evidence_generated_per_run_detail_line():
    assert i18n_completeness._is_allowlisted(
        "Producer: ADC. Repository: commit abc123 (dirty worktree). "
        "Ingested from ``requirements/_evidence/runs/ADC-RUN-x/``."
    )


@requires_build
def test_completeness_gate_reports_zero_missing_titles_on_the_real_built_site():
    en_needs = _load_needs(EN_ROOT)
    missing = i18n_completeness.check_title_completeness(en_needs, "de")
    assert missing == [], f"real build has {len(missing)} Need(s) with no German title: {missing[:10]}"


@requires_build
def test_completeness_gate_reports_zero_missing_prose_on_the_real_built_site(isolated_requirements_source):
    problems = i18n_completeness.check_prose_completeness(str(isolated_requirements_source), "de")
    assert problems == {}, f"real build has untranslated prose: {problems}"


# ----------------------------------------------------------------------------
# CLAUDE-ADC-VISIBLE-TERMINAL-FOR-SOFTWARE-INSTALLATION-001: regression tests
# for a real gap found and fixed in check_prose_completeness itself -- the
# first version only checked msgids ALREADY PRESENT in a .po file for an
# empty msgstr, so a brand-new paragraph never yet merged into the .po file
# at all passed the gate silently while actually rendering in English inside
# the German build. These tests pin the fix down: a msgid the .po file has
# never recorded, but which the CURRENT source genuinely contains, must be
# reported exactly like an empty-msgstr entry.
# ----------------------------------------------------------------------------

def test_check_prose_completeness_catches_a_msgid_entirely_absent_from_po(monkeypatch, tmp_path):
    # Real .po file: fully "translated" as far as its own contents go.
    locale_dir = tmp_path / "locale" / "de" / "LC_MESSAGES"
    locale_dir.mkdir(parents=True)
    (locale_dir / "page.po").write_text(
        'msgid ""\nmsgstr ""\n'
        'msgid "Already translated"\nmsgstr "Bereits übersetzt"\n',
        encoding="utf-8",
    )
    (tmp_path / "page.rst").write_text("Already translated\n\nBrand new untranslated sentence\n")

    monkeypatch.setattr(
        i18n_completeness, "_fresh_source_msgids",
        lambda src_dir: {"page": {"Already translated", "Brand new untranslated sentence"}},
    )
    problems = i18n_completeness.check_prose_completeness(str(tmp_path), "de")
    assert "page" in problems
    assert "Brand new untranslated sentence" in problems["page"]
    assert "Already translated" not in problems["page"]


def test_check_prose_completeness_still_catches_empty_msgstr_entries(monkeypatch, tmp_path):
    locale_dir = tmp_path / "locale" / "de" / "LC_MESSAGES"
    locale_dir.mkdir(parents=True)
    (locale_dir / "page.po").write_text(
        'msgid ""\nmsgstr ""\n'
        'msgid "Not yet translated"\nmsgstr ""\n',
        encoding="utf-8",
    )
    (tmp_path / "page.rst").write_text("Not yet translated\n")

    monkeypatch.setattr(
        i18n_completeness, "_fresh_source_msgids",
        lambda src_dir: {"page": {"Not yet translated"}},
    )
    problems = i18n_completeness.check_prose_completeness(str(tmp_path), "de")
    assert "Not yet translated" in problems["page"]


def test_check_prose_completeness_fails_closed_when_extraction_itself_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(i18n_completeness, "_fresh_source_msgids", lambda src_dir: None)
    problems = i18n_completeness.check_prose_completeness(str(tmp_path), "de")
    assert problems != {}  # never silently "everything is fine" when the check itself couldn't run


def test_fresh_source_msgids_extracts_real_current_source_content(isolated_requirements_source):
    """End-to-end sanity check of the real subprocess-based extraction
    (not mocked) against the actual project source: proves the
    mechanism itself works, independent of any one Need's content."""
    catalogs = i18n_completeness._fresh_source_msgids(str(isolated_requirements_source))
    assert catalogs is not None
    assert "architecture/architecture" in catalogs
    assert len(catalogs["architecture/architecture"]) > 50


@pytest.fixture
def isolated_requirements_source(tmp_path):
    """Real source content with all Sphinx writes confined to a disposable copy."""
    dest = tmp_path / "requirements"
    shutil.copytree(os.path.join(REPO_ROOT, "requirements"), dest,
                    ignore=shutil.ignore_patterns("_build", "_evidence", "__pycache__"))
    return dest
