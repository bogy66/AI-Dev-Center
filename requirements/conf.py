project = "AI-Dev-Center Requirements"

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import status_model  # noqa: E402  (needs sys.path set up first)
import svg_status_background  # noqa: E402
import i18n_titles  # noqa: E402
import i18n_language_switch  # noqa: E402
import i18n_config  # noqa: E402
import i18n_completeness  # noqa: E402
import change_history  # noqa: E402

# ---------------------------------------------------------------------------
# Central bilingual language configuration (OC-ADC-REQUIREMENTS-BILINGUAL-
# EN-DE-001)
# ---------------------------------------------------------------------------
#
# ONE source of truth for which languages the Requirements site supports and
# which one a build produces, read once here from a single environment
# variable that the build wrapper (requirements/build.sh) sets before
# invoking sphinx-build. This is deliberately an env var rather than a
# `-D language=de` command-line override: `-D` overrides are applied by
# Sphinx to the Config object only AFTER this whole conf.py module has
# already finished executing, so conf.py-time conditionals (e.g. the
# German needs_types type-name labels below) could never see a `-D`
# override in time -- but they CAN see an environment variable, which is
# available from the very first line of this file. Setting Sphinx's own
# `language` from the same variable means every language-dependent
# decision in this file -- Sphinx's own i18n machinery, needs_types
# labels, and the title_display predicate below -- is driven from this
# exact same single value, never from independent, potentially
# inconsistent settings.
ADC_ENABLED_LANGUAGES = i18n_config.ENABLED_LANGUAGES
ADC_DEFAULT_LANGUAGE = i18n_config.DEFAULT_LANGUAGE

language = i18n_config.resolve_language(os.environ.get("ADC_REQUIREMENTS_LANGUAGE"))

locale_dirs = ["locale"]
gettext_compact = False

templates_path = ["_templates"]

extensions = [
    "sphinx_needs",
    "sphinx.ext.graphviz",
]

html_theme = "furo"
html_title = {
    "en": "AI-Dev-Center Requirements",
    "de": "AI-Dev-Center Anforderungen",
}[language]

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
    # Localized Need title (OC-ADC-REQUIREMENTS-BILINGUAL-EN-DE-001). Never
    # the Need's own `title` field itself -- purely additive, see
    # i18n_titles.py's module docstring for why titles need this instead of
    # the standard gettext .po/.mo mechanism that covers ordinary body
    # prose. Applies to every real Need type (not just Requirement types)
    # since ZIEL/ARC/IMPL/TEST/EVID titles need localizing too; falls back
    # to the original English title whenever no German entry exists yet,
    # for every language including "en" itself.
    "title_display": {
        "default": "",
        "predicates": [
            (
                'type in ["ziel", "sysreq", "arch", "arcreq", "subreq", "ifreq", "impl", "test", "evidence"]',
                "[[ adc_localized_title() ]]",
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
# Card meta-line labels ("Lifecycle: ", "Implementation: ", "Verification
# Result: ") -- plain Python f-string prefixes baked into the layout at
# conf.py-load time, same reasoning/mechanism as _NEEDS_TYPE_LABELS above:
# these are not Need fields, so they cannot be dynamic functions, but the
# whole build is single-language, decided once, so a static per-language
# lookup here is both correct and sufficient.
_META_LABELS = {
    "en": {"lifecycle": "Lifecycle: ", "implementation": "Implementation: ", "verification_result": "Verification Result: "},
    "de": {"lifecycle": "Lebenszyklus: ", "implementation": "Implementierung: ", "verification_result": "Verifikationsergebnis: "},
}[language]

needs_layouts = {
    "adc_card": {
        "grid": "simple",
        "layout": {
            "head": [
                '<<meta("type_name")>>: **<<meta("title_display")>>** <<meta_id()>>  '
                '<<collapse_button("meta", collapsed="icon:arrow-down-circle", '
                'visible="icon:arrow-right-circle", initial=False)>> '
            ],
            "meta": [
                f'<<meta("status", prefix="{_META_LABELS["lifecycle"]}")>>',
                f'<<meta("implementation_state", prefix="{_META_LABELS["implementation"]}")>>',
                f'<<meta("verification_result", prefix="{_META_LABELS["verification_result"]}")>>',
                '<<meta_all(no_links=True, exclude=["status", "verification_result", '
                '"implementation_state", "title_display"])>>',
                "<<meta_links_all()>>",
            ],
        },
    },
}
needs_default_layout = "adc_card"

# Need-TYPE display labels (e.g. "System Requirement" on every SYS_REQ
# card's head line, via <<meta("type_name")>>) -- distinct from an
# individual Need's own title (see title_display/i18n_titles.py below).
# Selected once from the single `language` value resolved above, same
# reasoning as there: this is plain conf.py-time Python, not a Need field,
# so it cannot be made a dynamic function -- but it never needs to be,
# since the whole build (and so the whole generated site) is single-
# language, decided once per sphinx-build invocation.
_NEEDS_TYPE_LABELS = {
    "en": {
        "ziel": "Zielbild", "sysreq": "System Requirement", "arch": "Architecture Decision",
        "arcreq": "Architecture-derived Requirement", "subreq": "Subsystem Requirement",
        "ifreq": "Interface Requirement", "impl": "Implementation", "test": "Test",
        "evidence": "Evidence",
    },
    "de": {
        "ziel": "Zielbild", "sysreq": "Systemanforderung", "arch": "Architekturentscheidung",
        "arcreq": "Architektur-Anforderung", "subreq": "Subsystem-Anforderung",
        "ifreq": "Schnittstellenanforderung", "impl": "Implementierung", "test": "Test",
        "evidence": "Evidenz",
    },
}[language]

needs_types = [
    {"directive": "ziel", "title": _NEEDS_TYPE_LABELS["ziel"], "prefix": "ZIEL_", "color": "", "style": "node"},
    {"directive": "sysreq", "title": _NEEDS_TYPE_LABELS["sysreq"], "prefix": "SYS_REQ_", "color": "", "style": "node"},
    {"directive": "arch", "title": _NEEDS_TYPE_LABELS["arch"], "prefix": "ARC_", "color": "", "style": "node"},
    {"directive": "arcreq", "title": _NEEDS_TYPE_LABELS["arcreq"], "prefix": "ARC_REQ_", "color": "", "style": "node"},
    {"directive": "subreq", "title": _NEEDS_TYPE_LABELS["subreq"], "prefix": "SUB_REQ_", "color": "", "style": "node"},
    {"directive": "ifreq", "title": _NEEDS_TYPE_LABELS["ifreq"], "prefix": "IF_REQ_", "color": "", "style": "node"},
    {"directive": "impl", "title": _NEEDS_TYPE_LABELS["impl"], "prefix": "IMPL_", "color": "", "style": "artifact"},
    {"directive": "test", "title": _NEEDS_TYPE_LABELS["test"], "prefix": "TEST_", "color": "", "style": "node"},
    {"directive": "evidence", "title": _NEEDS_TYPE_LABELS["evidence"], "prefix": "EVID_", "color": "", "style": "artifact"},
]

# Link-type DISPLAY labels only -- the semantic field names themselves
# (realizes/satisfies/derived_from/refines/implements/verifies/evidences,
# the dict keys below) are never translated: they are the actual
# Sphinx-Needs option/field names parsed from every Requirement directive
# and must stay byte-identical across languages for the trace graph to
# remain one logical model. Only "incoming"/"outgoing" (the human-facing
# verb phrase shown next to a linked Need on its card) is localized.
_LINK_LABELS = {
    "en": {
        "realizes": {"incoming": "realized by", "outgoing": "realizes"},
        "satisfies": {"incoming": "satisfied by", "outgoing": "satisfies"},
        "derived_from": {"incoming": "derives", "outgoing": "derived from"},
        "refines": {"incoming": "refined by", "outgoing": "refines"},
        "implements": {"incoming": "implemented by", "outgoing": "implements"},
        "verifies": {"incoming": "verified by", "outgoing": "verifies"},
        "evidences": {"incoming": "evidenced by", "outgoing": "evidences"},
    },
    "de": {
        "realizes": {"incoming": "realisiert durch", "outgoing": "realisiert"},
        "satisfies": {"incoming": "erfüllt durch", "outgoing": "erfüllt"},
        "derived_from": {"incoming": "leitet ab", "outgoing": "abgeleitet von"},
        "refines": {"incoming": "verfeinert durch", "outgoing": "verfeinert"},
        "implements": {"incoming": "implementiert durch", "outgoing": "implementiert"},
        "verifies": {"incoming": "verifiziert durch", "outgoing": "verifiziert"},
        "evidences": {"incoming": "belegt durch", "outgoing": "Evidenz für"},
    },
}[language]

needs_links = {
    "realizes": _LINK_LABELS["realizes"],
    "satisfies": _LINK_LABELS["satisfies"],
    "derived_from": _LINK_LABELS["derived_from"],
    "refines": _LINK_LABELS["refines"],
    "implements": _LINK_LABELS["implements"],
    "verifies": _LINK_LABELS["verifies"],
    "evidences": _LINK_LABELS["evidences"],
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

exclude_patterns = ["_build/**", "_evidence/**"]

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
    add_dynamic_function(app, i18n_titles.adc_localized_title)
    app.connect("build-finished", status_model.export_requirement_status)
    app.connect("build-finished", svg_status_background.postprocess_needflow_svgs)
    app.connect("html-page-context", i18n_language_switch.inject_language_switch_context)
    app.connect("build-finished", i18n_completeness.run_completeness_gate)
    app.connect("build-finished", change_history.inject_change_history)