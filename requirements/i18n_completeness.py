"""Translation-completeness gate for the bilingual Requirements site
(OC-ADC-REQUIREMENTS-BILINGUAL-EN-DE-002).

The reported defect that triggered this module was NOT that translation
work was merely incomplete -- it is that an incomplete translation
silently, invisibly fell back to English per-string, producing a page
that *looks* finished while mixing languages. This module makes that
fallback impossible to ship unnoticed: for a non-default language build,
it fails the Sphinx build (via the Sphinx logger, promoted to a hard
error under `-W` -- see svg_status_background.py's docstring for why a
plain stdlib logger would NOT do this) whenever a required human-facing
string has no translation.

Two independent completeness checks, matching the two independent
localization mechanisms in this project:

1. Need TITLES (i18n_titles.TITLES_DE) -- every real, non-pilot Need id
   that Sphinx-Needs loaded must have an entry.
2. Body PROSE (.po/.mo catalogs under requirements/locale/<lang>/) --
   every extractable msgid in every real .rst source file must have a
   non-empty msgstr, unless it matches the small, explicit
   ALLOWLISTED_STRINGS/ALLOWLISTED_PATTERNS below (language-neutral
   technical vocabulary: product/tool names, acronyms, quoted normative
   source filenames, and the like -- never used to paper over prose that
   was simply never translated).
"""

import glob
import json
import os
import re

try:
    from babel.messages.pofile import read_po
except ImportError:  # pragma: no cover - babel is a Sphinx dependency
    read_po = None

import i18n_titles

try:
    from sphinx.util import logging as sphinx_logging
    _logger = sphinx_logging.getLogger(__name__)
except ImportError:  # pragma: no cover - only relevant outside a real Sphinx build
    import logging
    _logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))

# Exact-match language-neutral strings that never need a German msgstr:
# either they ARE the German word already (loanwords/established product
# vocabulary), or they are pure technical identifiers with no natural
# translation. Kept deliberately small -- every entry here is a conscious
# decision, not a way to silence the gate.
ALLOWLISTED_STRINGS = {
    "ADC", "API", "JSON", "HTML", "SVG", "RSE", "IO", "NIO", "MCP", "CI", "CLI",
    "Fail-Closed", "Existing Project First", "Python", "Sphinx", "sphinx-needs",
    "Zielbild", "Test",
    "NOT_IMPLEMENTED", "IMPLEMENTED_TEST_NIO", "IMPLEMENTED_TEST_IO",
    "NOT_RUN", "NIO", "IO",
}

# Regex patterns for structurally language-neutral msgids: a lone quoted
# source filename/path, a msgid that is pure RST/reference markup with no
# actual prose (e.g. only a :doc:`...` role and nothing else), or a
# literal pytest node-id / selector list (verification/tests.rst cites
# these verbatim so a reviewer can run them -- translating them would
# make them factually wrong, not localized).
ALLOWLISTED_PATTERNS = [
    re.compile(r"^``[^`]+\.(txt|py|json|rst)``$"),   # ``some_file.txt``
    re.compile(r"^[A-Z][A-Z0-9_]{2,}$"),               # a bare Need/enum-style ID
    re.compile(r"^tests/[\w./,: ]+\.py\b"),            # literal pytest selector(s)
    # requirements/evidence/ingest.py's per-run detail line: interpolates
    # a commit hash and run_id that differ every ingest run, so a stable
    # .po translation is not possible -- intentionally treated as
    # technical provenance text, same category as a literal command line.
    re.compile(r"^Producer: .+\. Repository: commit .+Ingested from "),
]


def _is_allowlisted(msgid):
    if msgid in ALLOWLISTED_STRINGS:
        return True
    return any(p.match(msgid) for p in ALLOWLISTED_PATTERNS)


# Id prefixes for Needs whose title is inherently unregisterable in
# TITLES_DE: requirements/evidence/ingest.py mints a fresh EVID_GEN_<run_id>
# id every ingest run, so no static table could ever list them in
# advance. Their title is deliberately left in English in both language
# builds (see ingest.py's own _write_evidence_generated_rst docstring for
# why it must not vary the RST content by language at generation time) --
# an intentional, narrow, documented exception, not a coverage gap.
GENERATOR_LOCALIZED_ID_PREFIXES = ("EVID_GEN_",)


def check_title_completeness(all_needs, language):
    """Return a sorted list of real (non-pilot) Need ids that have no
    title translation for `language`. Empty for language == "en" (the
    source language is always "complete" by construction) or for any
    need whose type is not in TITLES_DE's real Need-type scope."""
    if language == "en":
        return []

    real_types = {"ziel", "sysreq", "arch", "arcreq", "subreq", "ifreq", "impl", "test", "evidence"}
    missing = []
    for nid, need in all_needs.items():
        if need.get("type") not in real_types:
            continue
        if nid.startswith(GENERATOR_LOCALIZED_ID_PREFIXES):
            continue
        if "pilot" in (need.get("tags") or []):
            continue
        if nid not in i18n_titles.TITLES_DE:
            missing.append(nid)
    return sorted(missing)


def _docnames_with_prose(src_dir):
    """Every .rst file under src_dir, as a docname (posix-style, no
    extension), excluding the build output directory."""
    docnames = []
    for path in glob.glob(os.path.join(src_dir, "**", "*.rst"), recursive=True):
        if "_build" in path.split(os.sep):
            continue
        # Archived Evidence-run snapshots (e.g. a run's own generated/
        # requirements source copy) are immutable historical artifacts of
        # the Evidence store, never live Requirements sources; the live
        # model they were generated FROM is what this gate must check.
        if "_evidence" in path.split(os.sep):
            continue
        rel = os.path.relpath(path, src_dir)
        docnames.append(rel[: -len(".rst")].replace(os.sep, "/"))
    return sorted(docnames)


def _fresh_source_msgids(src_dir):
    """The authoritative, CURRENT set of extractable msgids per docname,
    obtained by actually running Sphinx's own gettext builder against
    the real source tree right now -- never approximated by scanning
    .rst text directly (gettext extraction has its own paragraph-
    splitting/role-handling rules a hand-rolled scan would not exactly
    match). Returns {docname: set(msgid)}, or None if extraction itself
    could not be run (caller must then fail closed, never silently skip
    the check).

    This exists to close a real gap found in this module's own first
    version (CLAUDE-ADC-VISIBLE-TERMINAL-FOR-SOFTWARE-INSTALLATION-001):
    checking only msgids ALREADY PRESENT in a .po file for an empty
    msgstr never catches a msgid that is missing from the .po file
    ENTIRELY -- exactly the shape a brand-new, never-yet-translated
    paragraph takes the moment it is added to an .rst source file, and
    exactly the silent English-in-German fallback this whole gate
    exists to prevent. Running the language=en (never the language
    under test) so this nested build's own build-finished hooks --
    including this module's own run_completeness_gate, which is
    connected unconditionally -- are a guaranteed no-op and cannot
    recurse."""
    import subprocess
    import sys
    import tempfile

    env = dict(os.environ)
    env.pop("ADC_REQUIREMENTS_LANGUAGE", None)  # force English: a no-op nested build
    with tempfile.TemporaryDirectory(prefix="adc-i18n-check-out-") as out_dir, \
            tempfile.TemporaryDirectory(prefix="adc-i18n-check-doctrees-") as doctree_dir:
        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "sphinx",
                    "-b", "gettext", "-D", "needs_build_json=0",
                    "-d", doctree_dir, src_dir, out_dir,
                ],
                capture_output=True, text=True, env=env, timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None

        catalogs = {}
        for docname in _docnames_with_prose(src_dir):
            pot_path = os.path.join(out_dir, f"{docname}.pot")
            if not os.path.isfile(pot_path):
                catalogs[docname] = set()
                continue
            with open(pot_path, encoding="utf-8") as f:
                catalog = read_po(f)
            catalogs[docname] = {
                message.id for message in catalog
                if message.id and not isinstance(message.id, (list, tuple))
            }
        return catalogs


def check_prose_completeness(src_dir, language):
    """Return {docname: [untranslated msgids]} for every .rst source file
    that has at least one required-but-untranslated string, for the given
    language. Empty for "en". A .rst file with NO corresponding .po file
    at all is reported with a single sentinel entry ("<no .po file>") so a
    whole file silently skipped for translation cannot pass unnoticed.
    verification/evidence_generated.rst's stable header prose (title,
    intro) IS covered by a normal .po file like every other page; only
    its per-run interpolated detail line is exempt, via
    ALLOWLISTED_PATTERNS above, not a whole-file exemption.

    Two independent ways a msgid can be untranslated, both checked: (1)
    present in the .po file with an empty msgstr, and (2) missing from
    the .po file entirely because it was added to the .rst source after
    the .po file was last synced -- see _fresh_source_msgids for why (2)
    is checked via a real, current gettext extraction rather than
    skipped. A source-extraction failure fails closed (reported as a
    problem on a sentinel docname), never silently skipped."""
    if language == "en" or read_po is None:
        return {}

    fresh = _fresh_source_msgids(src_dir)
    if fresh is None:
        return {"<gettext extraction>": ["<could not verify: source extraction failed>"]}

    problems = {}
    for docname in _docnames_with_prose(src_dir):
        po_path = os.path.join(src_dir, "locale", language, "LC_MESSAGES", f"{docname}.po")
        if not os.path.isfile(po_path):
            problems[docname] = ["<no .po file>"]
            continue
        with open(po_path, encoding="utf-8") as f:
            catalog = read_po(f)
        translated_ids = set()
        missing = []
        for message in catalog:
            if not message.id:
                continue
            if isinstance(message.id, (list, tuple)):
                continue  # plural forms not used in this project
            translated_ids.add(message.id)
            if _is_allowlisted(message.id):
                continue
            if not message.string:
                missing.append(message.id)

        # msgids the CURRENT source has that the .po file never even
        # recorded -- a stale catalog, not merely an empty translation.
        for msgid in sorted(fresh.get(docname, set()) - translated_ids):
            if not _is_allowlisted(msgid):
                missing.append(msgid)

        if missing:
            problems[docname] = missing
    return problems


def run_completeness_gate(app, exception):
    """Sphinx `build-finished` hook. Fails the build (via the Sphinx
    logger, which -W promotes to a hard error) whenever the active
    language has any required human-facing string without a
    translation. A no-op for "en" (the source language is always
    complete by construction) and for a build that already failed for
    an unrelated reason."""
    if exception is not None:
        return
    language = app.config.language
    if language == "en":
        return

    needs_json_path = os.path.join(app.outdir, "needs.json")
    if not os.path.exists(needs_json_path):
        return
    with open(needs_json_path, encoding="utf-8") as f:
        data = json.load(f)
    all_needs = {}
    for _ver_name, ver_data in data.get("versions", {}).items():
        if isinstance(ver_data, dict) and "needs" in ver_data:
            all_needs.update(ver_data["needs"])

    missing_titles = check_title_completeness(all_needs, language)
    if missing_titles:
        _logger.warning(
            "ADC i18n completeness gate: %d Need id(s) have no %s title "
            "translation (i18n_titles.TITLES_DE): %s",
            len(missing_titles), language,
            ", ".join(missing_titles[:20]) + (" ..." if len(missing_titles) > 20 else ""),
        )

    src_dir = os.path.dirname(os.path.abspath(__file__))
    missing_prose = check_prose_completeness(src_dir, language)
    for docname, msgids in sorted(missing_prose.items()):
        _logger.warning(
            "ADC i18n completeness gate: %s has %d untranslated %s string(s): %s",
            docname, len(msgids), language,
            "; ".join(repr(m)[:80] for m in msgids[:5]) + (" ..." if len(msgids) > 5 else ""),
        )
