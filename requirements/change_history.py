"""Central "latest meaningful Requirements/Engineering-model change"
timestamp for the Engineering Dashboard's Change History section
(CLAUDE-ADC-REQUIREMENTS-DASHBOARD-CHANGE-HISTORY-001).

One language-neutral source of truth: `compute_latest_model_change()`
returns a single, timezone-aware `datetime` -- the most recent moment at
which any authoritative, model-bearing Requirements source file
(ZIEL/SYS_REQ/ARC/ARC_REQ/SUB_REQ/IF_REQ/IMPL/TEST/EVID content) actually
changed. It is deliberately NEVER:

  - the current wall-clock time;
  - the Sphinx build time;
  - the time an HTML output file happened to be (re)generated;
  - advanced by a no-op rebuild, a generated-artifact change (HTML,
    `.doctrees`, CSS, dashboard/pilot/locale presentation files), or any
    source outside `MODEL_SOURCE_FILES`.

Per source file, "when did this file's content actually last change" is
answered the same way `requirements/evidence/provenance.py` already
answers "what commit is this" for Evidence: prefer the file's real
filesystem mtime whenever it is uncommitted/dirty (a commit timestamp
cannot describe content that was never committed) or when git itself is
unavailable (no repository, git not installed); otherwise use the last
commit that actually touched this file, since a clean file's own mtime
reflects nothing more than when it was last checked out, not when its
content actually changed. The overall result is the max across every
model source file, so it is correct for both a fully-committed
checkout and the current, genuinely dirty working tree, without ever
needing git history to be rewritten or consulted destructively (only
read-only `git status`/`git log`).

Localized PRESENTATION only happens at injection time
(`inject_change_history`, a `build-finished` hook exactly like
`status_model._inject_dashboard_summary`) -- the same single `datetime`
is formatted per `app.config.language`, never a second, per-language
computation of "when did this change".
"""
from __future__ import annotations

import datetime
from html import escape
import os
import posixpath
import re
import subprocess

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# The authoritative, model-bearing Requirements source files -- every
# .rst file that actually carries ZIEL/SYS_REQ/ARC/ARC_REQ/SUB_REQ/
# IF_REQ/IMPL/TEST/EVID directives. Deliberately excludes: dashboard/*
# (presentation only, this very feature's own home), pilot/* (synthetic,
# already excluded from every other real-content view in this project),
# locale/* (translations, not model content), _static/* and _templates/*
# (styling), and of course all generated/_build output.
MODEL_SOURCE_FILES = (
    "requirements/zielbild/zielbild.rst",
    "requirements/system/system_requirements.rst",
    "requirements/architecture/architecture.rst",
    "requirements/subsystem/subsystem_requirements.rst",
    "requirements/interfaces/interface_requirements.rst",
    "requirements/implementation/implementation.rst",
    "requirements/verification/tests.rst",
    "requirements/verification/evidence_generated.rst",
    "requirements/verification/evidence.rst",
)

CHANGE_HISTORY_MARKER = "ADC_CHANGE_HISTORY_PLACEHOLDER"
CHANGE_HISTORY_DETAILS_MARKER = "ADC_CHANGE_HISTORY_DETAILS_PLACEHOLDER"

_REQUIREMENT_DIRECTIVE = re.compile(
    r"(?m)^\.\. (ziel|sysreq|arcreq|subreq|ifreq)::\s*(.*?)\s*$"
)
_REQUIREMENT_ID = re.compile(r"(?m)^\s+:id:\s*([A-Z][A-Z0-9_]+)\s*$")

_LABELS = {
    "en": {
        "heading": "Change History", "last_change": "Last change",
        "view_details": "View changes by version",
        "intro": "Requirement changes are shown by Git change set. Commit identifiers are repository versions; Git tags are shown only where present.",
        "working_tree": "Uncommitted working tree", "commits": "Committed change sets",
        "version": "Git version", "tag": "Tag", "added": "Added requirements",
        "changed": "Changed requirements", "removed": "Removed requirements",
        "source_files": "Changed model files", "no_ids": "No requirement identifiers changed in this commit.",
        "removed_note": "no longer present in the current requirements",
        "unavailable": "Git history is unavailable; no historical changes can be shown.",
        "no_history": "No committed requirement changes were found.",
    },
    "de": {
        "heading": "Änderungsverlauf", "last_change": "Letzte Änderung",
        "view_details": "Änderungen nach Versionsstand anzeigen",
        "intro": "Anforderungsänderungen werden je Git-Änderungsstand angezeigt. Commit-Kennungen bezeichnen Repository-Stände; Git-Tags erscheinen nur, wenn vorhanden.",
        "working_tree": "Nicht committeter Arbeitsbaum", "commits": "Committete Änderungsstände",
        "version": "Git-Stand", "tag": "Tag", "added": "Hinzugefügte Anforderungen",
        "changed": "Geänderte Anforderungen", "removed": "Entfernte Anforderungen",
        "source_files": "Geänderte Modelldateien", "no_ids": "Dieser Commit änderte keine erkannten Anforderungs-IDs.",
        "removed_note": "im aktuellen Anforderungsstand nicht mehr vorhanden",
        "unavailable": "Die Git-Historie ist nicht verfügbar; frühere Änderungen können nicht angezeigt werden.",
        "no_history": "Es wurden keine committeten Anforderungsänderungen gefunden.",
    },
}


def _run_git(repo_root, *args):
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
    except OSError:
        return None


def _is_dirty(repo_root, relative_path):
    """True/False for a real answer, None when git itself could not be
    consulted at all (no repository, git not installed) -- callers treat
    None the same as True (fall back to filesystem mtime), since absence
    of git evidence is never treated as "this file is safely committed"."""
    result = _run_git(repo_root, "status", "--porcelain", "--", relative_path)
    if result is None or result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def _last_commit_time(repo_root, relative_path):
    result = _run_git(repo_root, "log", "-1", "--format=%cI", "--", relative_path)
    if result is None or result.returncode != 0:
        return None
    stamp = result.stdout.strip()
    if not stamp:
        return None
    try:
        return datetime.datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _mtime(repo_root, relative_path):
    absolute = os.path.join(repo_root, relative_path)
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(absolute)).astimezone()
    except OSError:
        return None


def _latest_change_for(repo_root, relative_path):
    dirty = _is_dirty(repo_root, relative_path)
    if dirty is None or dirty:
        return _mtime(repo_root, relative_path)
    return _last_commit_time(repo_root, relative_path) or _mtime(repo_root, relative_path)


def compute_latest_model_change(repo_root=None, source_files=None):
    """The latest meaningful-change timestamp across every model source
    file, or None if not one of them could be inspected at all (never
    expected in a real checkout)."""
    repo_root = repo_root or REPO_ROOT
    source_files = source_files if source_files is not None else MODEL_SOURCE_FILES
    candidates = [
        moment for moment in (
            _latest_change_for(repo_root, path) for path in source_files
        )
        if moment is not None
    ]
    return max(candidates) if candidates else None


def format_change_timestamp(moment: datetime.datetime, language: str) -> str:
    if language == "de":
        return moment.strftime("%d.%m.%Y, %H:%M")
    return moment.strftime("%Y-%m-%d %H:%M")


def render_change_history_html(moment: datetime.datetime | None, language: str) -> str:
    labels = _LABELS.get(language, _LABELS["en"])
    if moment is None:
        value = "unknown"
    else:
        value = format_change_timestamp(moment, language)
    return f'<p><strong>{labels["last_change"]}:</strong> {value}</p>'


def _parse_requirement_blocks(text: str) -> dict[str, dict[str, str]]:
    """Parse user-facing Requirement directives and retain their full blocks."""
    directives = list(_REQUIREMENT_DIRECTIVE.finditer(text))
    result = {}
    for index, directive in enumerate(directives):
        end = directives[index + 1].start() if index + 1 < len(directives) else len(text)
        block = text[directive.start():end].strip()
        id_match = _REQUIREMENT_ID.search(block)
        if id_match:
            result[id_match.group(1)] = {
                "kind": directive.group(1), "title": directive.group(2).strip(),
                "block": "\n".join(line.rstrip() for line in block.splitlines()),
            }
    return result


def _classify_requirement_changes(before: dict, after: dict) -> dict[str, list[str]]:
    before_ids, after_ids = set(before), set(after)
    return {
        "added": sorted(after_ids - before_ids),
        "changed": sorted(
            requirement_id for requirement_id in before_ids & after_ids
            if before[requirement_id]["block"] != after[requirement_id]["block"]
        ),
        "removed": sorted(before_ids - after_ids),
    }


def _blocks_for_paths(repo_root: str, paths: list[str], revision: str | None = None):
    blocks, sources = {}, {}
    for relative_path in paths:
        if revision is None:
            try:
                with open(os.path.join(repo_root, relative_path), encoding="utf-8") as source_file:
                    text = source_file.read()
            except OSError:
                continue
        else:
            result = _run_git(repo_root, "show", f"{revision}:{relative_path}")
            if result is None or result.returncode != 0:
                continue
            text = result.stdout
        for requirement_id, item in _parse_requirement_blocks(text).items():
            blocks[requirement_id] = item
            sources[requirement_id] = relative_path
    return blocks, sources


def _changed_model_paths(repo_root: str, revision: str) -> list[str]:
    result = _run_git(
        repo_root, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r",
        "-m", "--first-parent", revision, "--", *MODEL_SOURCE_FILES,
    )
    if result is None or result.returncode != 0:
        return []
    return sorted(set(line.strip() for line in result.stdout.splitlines() if line.strip()))


def _git_change_entries(repo_root: str) -> tuple[list[dict], dict]:
    log = _run_git(
        repo_root, "log", "--first-parent", "--format=%H%x1f%cI%x1f%s",
        "--", *MODEL_SOURCE_FILES,
    )
    if log is None or log.returncode != 0:
        return [], {"available": False}

    current_blocks, current_sources = _blocks_for_paths(repo_root, list(MODEL_SOURCE_FILES))
    entries = []
    for line in log.stdout.splitlines():
        fields = line.split("\x1f", 2)
        if len(fields) != 3:
            continue
        commit, timestamp, subject = fields
        paths = _changed_model_paths(repo_root, commit)
        if not paths:
            continue
        parent = _run_git(repo_root, "rev-parse", "--verify", f"{commit}^1")
        parent_revision = parent.stdout.strip() if parent and parent.returncode == 0 else None
        before, _ = _blocks_for_paths(repo_root, paths, parent_revision) if parent_revision else ({}, {})
        after, _ = _blocks_for_paths(repo_root, paths, commit)
        tags = _run_git(repo_root, "tag", "--points-at", commit)
        entries.append({
            "commit": commit, "timestamp": timestamp, "subject": subject,
            "tags": sorted(tags.stdout.splitlines()) if tags and tags.returncode == 0 else [],
            "paths": paths,
            "changes": _classify_requirement_changes(before, after),
            "snapshot": after,
        })

    head = _run_git(repo_root, "rev-parse", "--verify", "HEAD")
    working = None
    if head and head.returncode == 0:
        before, _ = _blocks_for_paths(repo_root, list(MODEL_SOURCE_FILES), head.stdout.strip())
        changes = _classify_requirement_changes(before, current_blocks)
        dirty = _run_git(repo_root, "status", "--porcelain", "--", *MODEL_SOURCE_FILES)
        if dirty and dirty.returncode == 0 and dirty.stdout.strip():
            paths = sorted({line[3:].strip() for line in dirty.stdout.splitlines() if len(line) > 3})
            working = {"paths": paths, "changes": changes}
    return entries, {
        "available": True, "blocks": current_blocks, "sources": current_sources,
        "working": working,
    }


def _requirement_link(requirement_id: str, item: dict, current_sources: dict,
                      language: str) -> str:
    title = item.get("title", "")
    if language == "de":
        try:
            import i18n_titles
            title = i18n_titles.TITLES_DE.get(requirement_id, title)
        except ImportError:
            pass
    label = escape(requirement_id + (f" — {title}" if title else ""))
    source = current_sources.get(requirement_id)
    if source:
        target = posixpath.relpath(source.removeprefix("requirements/").removesuffix(".rst") + ".html", "dashboard")
        return f'<a href="{escape(target)}#{escape(requirement_id)}">{label}</a>'
    return f"<code>{label}</code>"


def _render_change_group(changes: dict, snapshots: list[dict], current_sources: dict,
                         language: str) -> str:
    labels = _LABELS.get(language, _LABELS["en"])
    chunks = ['<section class="adc-history-change-group">']
    found = False
    for category in ("added", "changed", "removed"):
        identifiers = changes.get(category, [])
        if not identifiers:
            continue
        found = True
        chunks.append(
            f'<div class="adc-history-category"><strong>{escape(labels[category])}</strong><ul>'
        )
        for requirement_id in identifiers:
            item = next((snapshot[requirement_id] for snapshot in snapshots if requirement_id in snapshot), {})
            rendered = _requirement_link(requirement_id, item, current_sources, language)
            if category == "removed":
                rendered += f' <span class="adc-history-removed">({escape(labels["removed_note"])})</span>'
            chunks.append(f"<li>{rendered}</li>")
        chunks.append("</ul></div>")
    if not found:
        chunks.append(f'<p class="adc-history-empty">{escape(labels["no_ids"])}</p>')
    chunks.append("</section>")
    return "".join(chunks)


def render_change_history_details(repo_root: str, language: str) -> str:
    labels = _LABELS.get(language, _LABELS["en"])
    entries, current = _git_change_entries(repo_root)
    if not current.get("available"):
        return f'<p class="adc-history-empty">{escape(labels["unavailable"])}</p>'
    if not entries and current.get("working") is None:
        return f'<p class="adc-history-empty">{escape(labels["no_history"])}</p>'

    chunks = [f'<p class="adc-history-intro">{escape(labels["intro"])}</p>']
    current_sources = current["sources"]
    if current["working"]:
        working = current["working"]
        chunks.append(
            f'<details class="adc-history-entry" open><summary><strong>{escape(labels["working_tree"])}</strong></summary>'
        )
        chunks.append(f'<p>{escape(labels["source_files"])}: {", ".join(escape(path) for path in working["paths"])}</p>')
        chunks.append(_render_change_group(working["changes"], [current["blocks"]], current_sources, language))
        chunks.append("</details>")
    if entries:
        chunks.append(f'<h2>{escape(labels["commits"])}</h2>')
    for entry in entries:
        try:
            timestamp = format_change_timestamp(datetime.datetime.fromisoformat(entry["timestamp"]), language)
        except ValueError:
            timestamp = entry["timestamp"]
        summary = f'{labels["version"]} {entry["commit"][:8]} · {timestamp} · {entry["subject"]}'
        chunks.append(f'<details class="adc-history-entry"><summary>{escape(summary)}</summary>')
        if entry["tags"]:
            chunks.append(f'<p>{escape(labels["tag"])}: {", ".join(escape(tag) for tag in entry["tags"])}</p>')
        chunks.append(f'<p>{escape(labels["source_files"])}: {", ".join(escape(path) for path in entry["paths"])}</p>')
        chunks.append(_render_change_group(
            entry["changes"], [entry["snapshot"], current["blocks"]], current_sources, language,
        ))
        chunks.append("</details>")
    return "".join(chunks)


def inject_change_history(app, exception):
    """Sphinx `build-finished` hook. Mirrors
    `status_model._inject_dashboard_summary`: edits the already-written
    `dashboard/overview.html` directly, replacing `CHANGE_HISTORY_MARKER`
    with the localized "Last change: ..." line -- counts/timestamps are
    always derived here, never hand-edited into the .rst, and never
    generated via client-side JavaScript."""
    if exception is not None:
        return
    overview_path = os.path.join(app.outdir, "dashboard", "overview.html")
    if os.path.exists(overview_path):
        with open(overview_path, encoding="utf-8") as f:
            html = f.read()
        if CHANGE_HISTORY_MARKER in html:
            replacement = render_change_history_html(
                compute_latest_model_change(), app.config.language,
            )
            html = html.replace(CHANGE_HISTORY_MARKER, replacement)
            with open(overview_path, "w", encoding="utf-8") as f:
                f.write(html)

    details_path = os.path.join(app.outdir, "dashboard", "change_history.html")
    if os.path.exists(details_path):
        with open(details_path, encoding="utf-8") as f:
            html = f.read()
        if CHANGE_HISTORY_DETAILS_MARKER in html:
            replacement = render_change_history_details(REPO_ROOT, app.config.language)
            html = html.replace(CHANGE_HISTORY_DETAILS_MARKER, replacement)
            with open(details_path, "w", encoding="utf-8") as f:
                f.write(html)
