"""The single central definition of which languages the ADC Requirements
site supports and which one a given build resolves to
(OC-ADC-REQUIREMENTS-BILINGUAL-EN-DE-001).

Kept as a tiny, standalone, side-effect-free module (importable without
Sphinx itself) so both conf.py and this project's regression tests use
the exact same resolution logic -- there must be exactly one place that
decides "what language is this build," never two independently-written
copies of that decision.
"""

ENABLED_LANGUAGES = ("en", "de")
DEFAULT_LANGUAGE = "en"


def resolve_language(env_value):
    """Return the language a build should use, given the raw
    ADC_REQUIREMENTS_LANGUAGE environment value (which may be None or an
    unsupported string). Always returns a value from ENABLED_LANGUAGES --
    an unset or unrecognized value fails closed to DEFAULT_LANGUAGE
    rather than raising or silently building an unsupported language."""
    if env_value in ENABLED_LANGUAGES:
        return env_value
    return DEFAULT_LANGUAGE
