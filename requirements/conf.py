project = "AI-Dev-Center Requirements"

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import status_model  # noqa: E402  (needs sys.path set up first)
import svg_status_background  # noqa: E402

extensions = [
    "sphinx_needs",
    "sphinx.ext.graphviz",
]

html_theme = "furo"
html_title = "AI-Dev-Center Requirements"

html_static_path = ["_static"]
html_css_files = ["adc.css"]

html_theme_options = {
    "navigation_with_keys": True,
}

needs_build_json = True
needs_reproducible_json = True

needs_id_required = True
needs_id_regex = r"^[A-Z][A-Z0-9_]{2,}$"

needs_schema_validation_enabled = True
needs_schema_definitions_from_json = "schemas.json"

# ---------------------------------------------------------------------------
# Card presentation: derived implementation_state as a traffic light
# ---------------------------------------------------------------------------
#
# implementation_state is NEVER set manually on a Requirement directive.
# It is resolved automatically, per need, via a Sphinx-Needs dynamic
# function (`adc_impl_state_display`, registered below) wired in as a
# *predicate default* on the field itself: any need whose type is one of
# sysreq/arcreq/subreq/ifreq gets the function's output ("🔴 NOT_IMPLEMENTED"
# etc.) as its implementation_state value; every other type (ziel, arch,
# impl, test, evidence — including the synthetic pilot's own copies of
# these types) keeps the field's plain "" default, which the card layout
# below simply omits from view. This is the single, central point where
# state is derived — the same computation status_model.py also uses for
# the Requirement Implementation Status dashboard and the JSON exports.
#
# verification_result is symmetric: it is a TEST-only field. Only "test"
# needs get the "NOT_RUN" default; every other type keeps "" and the field
# stays invisible on their cards.
needs_fields = {
    "verification_result": {
        "default": "",
        "predicates": [
            ('type == "test"', "NOT_RUN"),
        ],
    },
    "implementation_state": {
        "default": "",
        "predicates": [
            (
                'type in ["sysreq", "arcreq", "subreq", "ifreq"]',
                "[[ adc_impl_state_display() ]]",
            ),
        ],
        "parse_dynamic_functions": True,
    },
}

# adc_impl_state_display is registered via the add_dynamic_function() API in
# setup() below, not via the needs_functions config list — a config value
# holding a live function object cannot be pickled for Sphinx's config
# cache and fails a strict (-W) build.

# Custom card layout for Requirement types: replaces the generic "status" /
# "verification_result" / "implementation_state" meta lines with an
# explicit, consistently-labelled "Lifecycle: <status>" /
# "Implementation: <icon> <state>" pair, followed by any other need data
# and the full set of traceability links. Applied as the project-wide
# default layout (Sphinx-Needs has no per-type default-layout config in
# this version), which is safe here because implementation_state and
# verification_result are only ever non-empty for the types they apply to
# (see needs_fields predicates above) — meta() silently omits empty fields,
# so ziel/arch/impl/evidence show no Implementation line, and only test
# shows a Verification Result line.
needs_layouts = {
    "adc_card": {
        "grid": "simple",
        "layout": {
            "head": [
                '<<meta("type_name")>>: **<<meta("title")>>** <<meta_id()>>  '
                '<<collapse_button("meta", collapsed="icon:arrow-down-circle", '
                'visible="icon:arrow-right-circle", initial=False)>> '
            ],
            "meta": [
                '<<meta("status", prefix="Lifecycle: ")>>',
                '<<meta("implementation_state", prefix="Implementation: ")>>',
                '<<meta("verification_result", prefix="Verification Result: ")>>',
                '<<meta_all(no_links=True, exclude=["status", "verification_result", '
                '"implementation_state"])>>',
                "<<meta_links_all()>>",
            ],
        },
    },
}
needs_default_layout = "adc_card"

needs_types = [
    {"directive": "ziel", "title": "Zielbild", "prefix": "ZIEL_", "color": "", "style": "node"},
    {"directive": "sysreq", "title": "System Requirement", "prefix": "SYS_REQ_", "color": "", "style": "node"},
    {"directive": "arch", "title": "Architecture Decision", "prefix": "ARC_", "color": "", "style": "node"},
    {"directive": "arcreq", "title": "Architecture-derived Requirement", "prefix": "ARC_REQ_", "color": "", "style": "node"},
    {"directive": "subreq", "title": "Subsystem Requirement", "prefix": "SUB_REQ_", "color": "", "style": "node"},
    {"directive": "ifreq", "title": "Interface Requirement", "prefix": "IF_REQ_", "color": "", "style": "node"},
    {"directive": "impl", "title": "Implementation", "prefix": "IMPL_", "color": "", "style": "artifact"},
    {"directive": "test", "title": "Test", "prefix": "TEST_", "color": "", "style": "node"},
    {"directive": "evidence", "title": "Evidence", "prefix": "EVID_", "color": "", "style": "artifact"},
]

needs_links = {
    "realizes": {"incoming": "realized by", "outgoing": "realizes"},
    "satisfies": {"incoming": "satisfied by", "outgoing": "satisfies"},
    "derived_from": {"incoming": "derives", "outgoing": "derived from"},
    "refines": {"incoming": "refined by", "outgoing": "refines"},
    "implements": {"incoming": "implemented by", "outgoing": "implements"},
    "verifies": {"incoming": "verified by", "outgoing": "verifies"},
    "evidences": {"incoming": "evidenced by", "outgoing": "evidences"},
}

needs_flow_engine = "graphviz"
needs_flow_direction = "right"
needs_flow_show_links = "outgoing"
needs_flow_link_types = [
    "realizes",
    "satisfies",
    "derived_from",
    "refines",
    "implements",
    "verifies",
    "evidences",
]
graphviz_output_format = "svg"

exclude_patterns = ["_build/**"]

# ---------------------------------------------------------------------------
# Traffic-light status integration
# ---------------------------------------------------------------------------

needs_filter_func = {
    "filter_red": "status_model.filter_red",
    "filter_yellow": "status_model.filter_yellow",
    "filter_green": "status_model.filter_green",
}

# ---------------------------------------------------------------------------
# Requirement traffic-light node-background coloring on generated needflow
# graph SVGs
# ---------------------------------------------------------------------------
#
# CLAUDE-ADC-SPHINX-TRACE-GRAPH-STATUS-BACKGROUND-001, superseding the
# accepted small-dot presentation (OC-ADC-SPHINX-TRACE-GRAPH-STATUS-DOT-SVG-
# 001) because the dot was too small to read in the real graph. Sphinx-Needs
# 8.5.0 still has no supported way to decorate individual needflow Graphviz
# node labels from computed per-Need state at doctree/env time (in-memory
# Need-title mutation). svg_status_background.py post-processes the
# already-generated SVG files as plain XML at build-finished, after
# Graphviz has rendered them and after needs.json exists -- see that
# module's own docstring. Registered after status_model.export_requirement_
# status below so ordering is never ambiguous, though svg_status_background
# reads needs.json directly and does not actually depend on that hook
# having run first.


def setup(app):
    from sphinx_needs.api import add_dynamic_function

    add_dynamic_function(app, status_model.adc_impl_state_display)
    app.connect("build-finished", status_model.export_requirement_status)
    app.connect("build-finished", svg_status_background.postprocess_needflow_svgs)