"""ADC Requirement traffic-light node-background coloring for generated
needflow SVGs.

CLAUDE-ADC-SPHINX-TRACE-GRAPH-STATUS-BACKGROUND-001, superseding the
accepted small-dot presentation from OC-ADC-SPHINX-TRACE-GRAPH-STATUS-
DOT-SVG-001 (requirements/svg_status_dot.py, now removed) because the dot
was too small to read at a glance in the real, large traceability graph.

Architecture unchanged from that accepted predecessor: Sphinx-Needs 8.5.0
has no supported way to decorate individual needflow Graphviz node labels
from computed per-Need state at doctree/env time (in-memory Need-title
mutation -- do not attempt that again). This module post-processes the
already-generated SVG files as plain XML, once, at build-finished -- after
Graphviz has rendered them and needs.json exists (see setup() in conf.py).

It never touches Requirement titles, RST, or the traceability graph
topology -- it only sets the `fill` attribute of each Requirement node's
existing <polygon> (or <ellipse>) shape, using the SAME central status
computation (status_model.compute_all_requirement_states) that drives
Requirement cards, the dashboard, and requirement_status.json.
Non-Requirement node types (ziel, arch, impl, test, evidence) are left
completely untouched because they simply never appear as keys in that
computation's output.
"""

import glob
import json
import logging
import os
import tempfile
import time
import xml.etree.ElementTree as ET

import status_model

try:
    # Real Sphinx builds run under requirements/.requirements-venv, where
    # this makes a parse failure on the real needflow SVG properly promoted
    # to a build failure under `sphinx-build -W` (a plain stdlib warning is
    # NOT counted by -W at all). This module is also imported directly by
    # this file's own pytest suite under the separate product venv, which
    # has no sphinx installed -- plain stdlib logging there is harmless,
    # since no real Sphinx build (and so no -W promotion) is involved.
    from sphinx.util import logging as sphinx_logging
    _logging_module = sphinx_logging
except ImportError:
    _logging_module = logging

_SVG_NS = "http://www.w3.org/2000/svg"
_XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", _SVG_NS)
ET.register_namespace("xlink", _XLINK_NS)


def _svg_tag(local):
    return f"{{{_SVG_NS}}}{local}"


# Background fills, defined centrally here (never scattered per-Requirement).
# Light traffic-light tints so the existing black node text stays readable;
# the node's own black border/stroke is left untouched for contrast and to
# keep every node's boundary visually consistent regardless of status.
BACKGROUND_FILL = {
    status_model.NOT_IMPLEMENTED: "#ffcdd2",       # light red
    status_model.IMPLEMENTED_TEST_NIO: "#fff9c4",  # light yellow
    status_model.IMPLEMENTED_TEST_IO: "#c8e6c9",   # light green
}
# Fail-closed fallback for a state value compute_all_requirement_states did
# not itself define (defensive only -- that function's own _STATES list is
# the sole source of state strings, so this branch is not expected to be
# reachable in practice, but a postprocessor over generated data must never
# assume its upstream input is exhaustively validated). Renders as an
# explicit light neutral grey, deliberately distinct from every real status
# tint so it is never mistaken for a real RED/YELLOW/GREEN reading, and
# never silently defaults to green.
BACKGROUND_FILL_UNKNOWN = "#e0e0e0"  # light grey -- "unknown state", never green

BACKGROUND_CLASS = "adc-requirement-status-bg"
# Legacy marker from the superseded dot presentation. Actively stripped (not
# just omitted-by-rebuild) so that re-running this postprocessor over an SVG
# that still happens to carry an old dot -- e.g. one produced by a stale
# copy of the previous module -- always leaves a clean result with no
# leftover status circles, per this task's DOT_RENDERING_REMOVED
# requirement.
_LEGACY_DOT_CLASS = "adc-requirement-status-dot"

NEEDFLOW_SVG_GLOB = "needflow-*.svg"

logger = _logging_module.getLogger(__name__)


def _shape_element(container):
    """Return the node's own background shape element (<polygon> or
    <ellipse>), or None if neither is found."""
    polygon = container.find(_svg_tag("polygon"))
    if polygon is not None:
        return polygon
    ellipse = container.find(_svg_tag("ellipse"))
    if ellipse is not None:
        return ellipse
    return None


def _strip_legacy_dots(container):
    for child in list(container):
        if child.get("class") == _LEGACY_DOT_CLASS:
            container.remove(child)


def annotate_svg_tree(root, status_map):
    """Mutate `root` (an already-parsed SVG <svg> Element) in place,
    setting the background fill of every Requirement node's shape whose
    <title> text is a key in `status_map`. Idempotent: re-applying simply
    overwrites `fill` with whatever the current status computes to, and
    strips any leftover legacy status-dot element it finds. Returns a
    stats dict: colored / skipped_no_shape / total_requirement_nodes_seen."""
    stats = {"colored": 0, "skipped_no_shape": 0, "total_requirement_nodes_seen": 0}

    for node_group in root.iter(_svg_tag("g")):
        if node_group.get("class") != "node":
            continue
        title_el = node_group.find(_svg_tag("title"))
        if title_el is None or title_el.text is None:
            continue
        node_id = title_el.text.strip()
        if node_id not in status_map:
            continue  # not a Requirement-type need (or not a Requirement at all)

        stats["total_requirement_nodes_seen"] += 1

        anchor = node_group.find(f".//{_svg_tag('a')}")
        container = anchor if anchor is not None else node_group

        _strip_legacy_dots(container)

        shape = _shape_element(container)
        if shape is None:
            stats["skipped_no_shape"] += 1
            continue

        state = status_map.get(node_id)
        fill = BACKGROUND_FILL.get(state, BACKGROUND_FILL_UNKNOWN)

        shape.set("fill", fill)
        shape.set("class", BACKGROUND_CLASS)

        stats["colored"] += 1

    return stats


def annotate_svg_file(path, status_map):
    """Parse, annotate, and atomically rewrite one SVG file in place.
    Returns the stats dict from annotate_svg_tree(), or None if the file
    could not be parsed as XML after retrying (malformed SVG fails clearly
    -- via the returned None plus a Sphinx-logged warning, which is
    promoted to a build failure under -W -- rather than silently producing
    incorrect output or silently shipping an unprocessed graph).

    A short retry is attempted first: this file is written by an earlier
    stage of the SAME build (Graphviz rendering via sphinx.ext.graphviz),
    and a parse failure immediately after that stage has, on rare
    occasions, been observed to be transient (not reproducible on an
    immediate re-read of the same, by-then-fully-written file) -- retrying
    costs nothing on the far more common case where the file is already
    complete and valid."""
    tree = None
    last_exc = None
    for attempt in range(3):
        if attempt:
            time.sleep(0.05)
        try:
            tree = ET.parse(path)
            last_exc = None
            break
        except ET.ParseError as exc:
            last_exc = exc

    if tree is None:
        logger.warning(
            "ADC status-background postprocessor: could not parse %s as XML after retrying (%s) -- left unmodified",
            path, last_exc,
        )
        return None

    root = tree.getroot()
    stats = annotate_svg_tree(root, status_map)

    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-svgbg-", suffix=".svg")
    try:
        with os.fdopen(fd, "wb") as f:
            tree.write(f, encoding="utf-8", xml_declaration=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return stats


def compute_status_map_from_needs_json(needs_json_path):
    """Load needs.json and compute the SAME implementation_state map used
    for Requirement cards, the dashboard, and requirement_status.json --
    status_model.compute_all_requirement_states() applied to the full
    real+pilot needs set, exactly like status_model.export_requirement_status
    does. Returns {} if needs.json is not present yet (defensive; the
    build-finished ordering this module relies on is documented in
    conf.py's setup())."""
    if not os.path.exists(needs_json_path):
        return {}
    try:
        with open(needs_json_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    all_needs = {}
    for _ver_name, ver_data in data.get("versions", {}).items():
        if isinstance(ver_data, dict) and "needs" in ver_data:
            all_needs.update(ver_data["needs"])

    return status_model.compute_all_requirement_states(all_needs)


def postprocess_needflow_svgs(app, exception):
    """Sphinx build-finished hook. Connected in conf.py's setup() AFTER
    status_model.export_requirement_status, so app.outdir/needs.json is
    already written by the time this runs (both by Sphinx-Needs' own
    export and by that earlier hook -- either is sufficient; this function
    reads the file directly rather than depending on the other hook having
    run, so it is correct regardless of their relative order)."""
    if exception is not None:
        return

    needs_json_path = os.path.join(app.outdir, "needs.json")
    status_map = compute_status_map_from_needs_json(needs_json_path)
    if not status_map:
        return

    images_dir = os.path.join(app.outdir, "_images")
    svg_paths = sorted(glob.glob(os.path.join(images_dir, NEEDFLOW_SVG_GLOB)))
    for path in svg_paths:
        annotate_svg_file(path, status_map)
