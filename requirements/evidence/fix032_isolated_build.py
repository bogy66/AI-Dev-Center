"""Build fresh Requirements views from explicitly supplied independent evidence.

Never modifies operative evidence, normative source, catalogs or existing builds.
The output directory must not exist. Historical TEST results in the copy are
reset before ingest so unexecuted obligations cannot inherit historical IO.
"""
from pathlib import Path
import argparse
import os
import re
import shutil
import subprocess

from .ingest import ingest_all_runs


def build(stores, output):
    root = Path(__file__).resolve().parents[2]
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Preserve the repository's requirements/ layout: build hooks resolve
    # model paths relative to the parent of this directory.
    source = output / 'source' / 'requirements'
    shutil.copytree(root / 'requirements', source,
                    ignore=shutil.ignore_patterns('_evidence', '_build', '__pycache__', '*.pyc', '*.mo'))
    merged = output / 'evidence'
    for store in stores:
        for run in (Path(store) / 'runs').iterdir():
            shutil.copytree(run, merged / 'runs' / run.name)
    catalog = source / 'verification' / 'tests.rst'
    text = catalog.read_text()
    text = re.sub(r'(?m)^(\s*:verification_result:)\s*.*$', r'\1 NOT_RUN', text)
    catalog.write_text(text)
    report = ingest_all_runs(store_root=str(merged), tests_rst_path=str(catalog),
                            evidence_generated_path=str(source / 'verification' / 'evidence_generated.rst'))
    if report.malformed_events_skipped:
        raise RuntimeError(report.malformed_events_skipped)
    for language in ('en', 'de'):
        subprocess.run([str(root / '.requirements-venv/bin/sphinx-build'), '-E', '-a', '-W',
                        '-b', 'html', '-d', str(output / ('doctrees-' + language)),
                        str(source), str(output / 'html' / language)], check=True,
                       env={**os.environ, 'ADC_REQUIREMENTS_LANGUAGE': language})
    print('INDEPENDENT_REQUIREMENTS_BUILD=IO')
    print('OWN_EVIDENCE_TEST_RESULTS=', report.test_ids_updated)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', action='append', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    build(args.store, args.output)
