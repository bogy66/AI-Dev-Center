"""Run identity generation for the ADC Evidence Contract.

A run identity must be unique per formal ADC test invocation and must not
rely on timestamp alone (two runs can start within the same second).
"""
import re
import uuid
from datetime import datetime, timezone

RUN_ID_PATTERN = re.compile(r"^ADC-RUN-\d{8}T\d{6}Z-[a-f0-9]{8}$")


def generate_run_id(now=None):
    """Return a new run id of the form ADC-RUN-<UTC timestamp>-<short id>.

    `now`: optional injected datetime (UTC) for deterministic testing.
    The trailing short id is a random 8-hex-digit token, not derived from
    the timestamp, so two runs starting in the same second still get
    distinct, collision-safe ids.
    """
    moment = now or datetime.now(timezone.utc)
    ts = moment.strftime("%Y%m%dT%H%M%SZ")
    short_id = uuid.uuid4().hex[:8]
    return f"ADC-RUN-{ts}-{short_id}"


def is_valid_run_id(run_id):
    return bool(RUN_ID_PATTERN.match(run_id or ""))
