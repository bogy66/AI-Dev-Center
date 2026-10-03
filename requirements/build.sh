#!/usr/bin/env bash
# Central bilingual build entry point for the ADC Requirements site
# (OC-ADC-REQUIREMENTS-BILINGUAL-EN-DE-001).
#
# Usage:
#   requirements/build.sh              # build every language in
#                                       # ADC_ENABLED_LANGUAGES (en + de)
#   requirements/build.sh en           # build only English (dev/debug)
#   requirements/build.sh de           # build only German (dev/debug)
#
# Set ADC_REQUIREMENTS_BUILD_ROOT to keep fresh build outputs and doctrees
# in an isolated verification directory (default: requirements/_build).
#
# Each language is a SEPARATE, independent sphinx-build invocation against
# the SAME single source tree and conf.py -- there is exactly one logical
# Requirements/traceability model; language is a presentation switch read
# by conf.py from ADC_REQUIREMENTS_LANGUAGE, not a second source tree. Each
# language gets its own doctree cache (translation substitution happens at
# doctree-resolution time and must not be shared across languages) and its
# own output directory, as siblings under requirements/_build/html/, which
# is what the language-switch links (i18n_language_switch.py) assume.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

VENV=".requirements-venv/bin/sphinx-build"
SRC="requirements"
BUILD_ROOT="${ADC_REQUIREMENTS_BUILD_ROOT:-requirements/_build}"
OUT_ROOT="${BUILD_ROOT}/html"
DOCTREE_ROOT="${BUILD_ROOT}/doctrees"

# Sphinx compiles .po catalogs to .mo even during otherwise read-only builds.
# Give each invocation a private writable locale tree; never rewrite tracked
# catalogs in the source tree, and never share these scratch files across runs.
LOCALE_SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/adc-requirements-locale.XXXXXX")"
trap 'rm -rf -- "$LOCALE_SCRATCH"' EXIT
cp -a "${SRC}/locale/." "${LOCALE_SCRATCH}/"
find "${LOCALE_SCRATCH}" -type f -name '*.mo' -delete

build_one() {
  local lang="$1"
  echo "==> Building ADC Requirements site: ${lang}"
  ADC_REQUIREMENTS_LANGUAGE="${lang}" "${VENV}" -W -b html \
    -d "${DOCTREE_ROOT}-${lang}" -D "locale_dirs=${LOCALE_SCRATCH}" \
    "${SRC}" "${OUT_ROOT}/${lang}"
}

publish_default_english_mirror() {
  # Older bookmarks and local static servers use html/ directly rather than
  # html/en/. Keep that entry point current as an English mirror after an EN
  # build; otherwise it can silently keep showing a stale Change History and
  # stale requirement statuses while the bilingual sites are fresh.
  echo "==> Refreshing default English dashboard/site mirror"
  cp -a "${OUT_ROOT}/en/." "${OUT_ROOT}/"
  python - "${OUT_ROOT}" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
switch = re.compile(
    r'(<div class="adc-language-switch">\s*<a href=")((?:\.\./)+)de/'
)
for page in root.rglob("*.html"):
    if page.is_relative_to(root / "en") or page.is_relative_to(root / "de"):
        continue
    content = page.read_text(encoding="utf-8")
    content = switch.sub(lambda m: m.group(1) + m.group(2)[:-3] + "de/", content)
    page.write_text(content, encoding="utf-8")
PY
}

if [ "$#" -eq 0 ]; then
  build_one en
  build_one de
  publish_default_english_mirror
elif [ "$#" -eq 1 ] && { [ "$1" = "en" ] || [ "$1" = "de" ]; }; then
  build_one "$1"
  if [ "$1" = "en" ]; then
    publish_default_english_mirror
  fi
else
  echo "Usage: $0 [en|de]" >&2
  exit 2
fi
