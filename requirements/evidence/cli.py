"""adc-evidence: the one CLI surface for publishing and ingesting ADC
Evidence, so no testbed/bench needs to duplicate JSON-writing/validation
logic itself.

    python -m requirements.evidence.cli publish <event-file.json>
    python -m requirements.evidence.cli ingest [--store <path>]
"""
import argparse
import json
import sys

from .ingest import ingest_all_runs
from .publisher import publish_test_evidence


def _cmd_publish(args):
    with open(args.event_file, encoding="utf-8") as f:
        event = json.load(f)
    result = publish_test_evidence(event, store_root=args.store)
    if result.success:
        print(f"OK run_id={result.run_id} event_id={result.event_id}")
        return 0
    print(f"REJECTED: {result.errors}", file=sys.stderr)
    return 1


def _cmd_ingest(args):
    report = ingest_all_runs(store_root=args.store)
    print(f"runs_processed={len(report.runs_processed)}")
    print(f"events_processed={report.events_processed}")
    print(f"malformed_events_skipped={len(report.malformed_events_skipped)}")
    print(f"unmapped_selectors={len(report.unmapped_selectors)}")
    print(f"test_ids_updated={len(report.test_ids_updated)}: {report.test_ids_updated}")
    print(f"evidence_objects_generated={report.evidence_objects_generated}")
    if report.malformed_events_skipped:
        for item in report.malformed_events_skipped:
            print(f"  MALFORMED: {item['path']}: {item['error']}", file=sys.stderr)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="adc-evidence")
    sub = parser.add_subparsers(dest="command", required=True)

    p_publish = sub.add_parser("publish", help="Validate and durably record one Evidence event")
    p_publish.add_argument("event_file")
    p_publish.add_argument("--store", default=None)
    p_publish.set_defaults(func=_cmd_publish)

    p_ingest = sub.add_parser("ingest", help="Process the Evidence store into the Sphinx-Needs representation")
    p_ingest.add_argument("--store", default=None)
    p_ingest.set_defaults(func=_cmd_ingest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
