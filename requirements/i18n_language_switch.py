"""Deterministic, build-time EN/Deutsch language switch links.

OC-ADC-REQUIREMENTS-BILINGUAL-EN-DE-001. Every page of one language build
gets a link to the *same logical page* in the other language build --
computed once per page from its docname, never client-side JavaScript,
never dynamic text replacement. Requires the two language builds to be
written to sibling output directories that share the same relative page
structure (e.g. `_build/html/en/` and `_build/html/de/` -- see
requirements/build.sh), since Sphinx has no knowledge of the "other"
build within a single invocation: this module works entirely by relative
path arithmetic from the current page's own docname.
"""

_SWITCH_LABEL = {
    "en": "Deutsch",   # shown on the English site, links to German
    "de": "English",   # shown on the German site, links to English
}
_OTHER_LANGUAGE = {"en": "de", "de": "en"}


def inject_language_switch_context(app, pagename, templatename, context, doctree):
    """Sphinx `html-page-context` handler.

    `pagename` is the docname of the page currently being rendered (e.g.
    "index", "dashboard/overview"). The other language's copy of this
    exact page lives at the same relative path one directory further up
    (out of this build's own `en/`/`de/` output root) and back down into
    the sibling language directory -- so the number of `../` segments
    needed is exactly `pagename.count("/") + 1`.
    """
    language = app.config.language
    other = _OTHER_LANGUAGE.get(language)
    if other is None:
        return

    depth = pagename.count("/") + 1
    relative_prefix = "../" * depth
    context["adc_switch_url"] = f"{relative_prefix}{other}/{pagename}.html"
    context["adc_switch_lang_label"] = _SWITCH_LABEL.get(language, other)
