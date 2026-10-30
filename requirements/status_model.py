"""ADC Requirements — Traffic-Light Implementation/Verification Status Model.

Central derivation logic. Never manually entered on Requirement directives.
"""

import json
import os
from collections import deque

NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
IMPLEMENTED_TEST_NIO = "IMPLEMENTED_TEST_NIO"
IMPLEMENTED_TEST_IO = "IMPLEMENTED_TEST_IO"

_STATES = [NOT_IMPLEMENTED, IMPLEMENTED_TEST_NIO, IMPLEMENTED_TEST_IO]

REQUIREMENT_TYPES = {"sysreq", "arcreq", "subreq", "ifreq"}

TRAFFIC_LIGHT_ICON = {
    NOT_IMPLEMENTED: "\U0001F534",       # red circle
    IMPLEMENTED_TEST_NIO: "\U0001F7E1",  # yellow circle
    IMPLEMENTED_TEST_IO: "\U0001F7E2",   # green circle
}


def compute_all_requirement_states(needs):
    """Compute implementation_state for every Requirement in the needs dict.

    Args:
        needs: dict of {need_id: need_dict} (all needs)

    Returns:
        dict of {need_id: implementation_state}
    """
    cycles = _detect_cycles(needs)

    # Compute leaf states first
    leaf_states = {}
    for need_id, need in needs.items():
        if need.get("type") not in REQUIREMENT_TYPES:
            continue
        if _has_child_requirements(need_id, needs, cycles):
            continue
        state, _ = _leaf_requirement_state(need_id, needs)
        leaf_states[need_id] = state

    # Aggregate parents (can be called in any order; we iterate until stable)
    all_states = dict(leaf_states)
    parent_queue = deque(
        nid for nid, need in needs.items()
        if need.get("type") in REQUIREMENT_TYPES and nid not in all_states
    )

    max_iterations = len(needs) + 1
    iteration = 0
    while parent_queue and iteration < max_iterations:
        iteration += 1
        nid = parent_queue.popleft()
        child_states = _gather_child_states(nid, needs, all_states, cycles)
        if child_states is None:
            parent_queue.append(nid)
            continue
        if not child_states:
            state, _ = _leaf_requirement_state(nid, needs)
        else:
            state = _aggregate_child_states(child_states)
        all_states[nid] = state

    for nid in needs:
        if needs[nid].get("type") in REQUIREMENT_TYPES and nid not in all_states:
            state, _ = _leaf_requirement_state(nid, needs)
            all_states[nid] = state

    return all_states


def _leaf_requirement_state(need_id, needs):
    """Compute state for a Requirement with no child Requirements (leaf).

    Returns (state, reason_dict).
    """
    need = needs[need_id]
    impl_ids = _incoming_ids(need_id, needs, "implements")
    if not impl_ids:
        return NOT_IMPLEMENTED, {"reason": "no implementing objects", "implementations": []}

    test_ids = _incoming_ids(need_id, needs, "verifies")
    if not test_ids:
        return IMPLEMENTED_TEST_NIO, {"reason": "no verifying tests", "implementations": impl_ids}

    all_io = True
    missing_evidence = False
    for tid in test_ids:
        test = needs.get(tid, {})
        vresult = test.get("verification_result", "NOT_RUN")
        if vresult != "IO":
            all_io = False
        if vresult == "IO":
            evidence_ids = _incoming_ids(tid, needs, "evidences")
            if not evidence_ids:
                missing_evidence = True

    if all_io and not missing_evidence:
        return IMPLEMENTED_TEST_IO, {
            "reason": "all tests IO with evidence",
            "implementations": impl_ids, "tests": test_ids,
        }
    return IMPLEMENTED_TEST_NIO, {
        "reason": _yellow_reason(test_ids, needs, missing_evidence),
        "implementations": impl_ids, "tests": test_ids,
    }


def _yellow_reason(test_ids, needs, missing_evidence):
    reasons = []
    for tid in test_ids:
        test = needs.get(tid, {})
        vresult = test.get("verification_result", "NOT_RUN")
        if vresult == "NOT_RUN":
            reasons.append(f"test {tid} NOT_RUN")
        elif vresult == "NIO":
            reasons.append(f"test {tid} NIO")
        elif vresult == "IO":
            ev = _incoming_ids(tid, needs, "evidences")
            if not ev:
                reasons.append(f"test {tid} IO but no evidence")
    if missing_evidence:
        reasons.append("at least one IO test lacks evidence")
    return "; ".join(reasons) if reasons else "incomplete verification"


def _has_child_requirements(need_id, needs, cycles):
    """Check if a requirement has lower-level derived Requirement children."""
    return bool(_get_derived_children(need_id, needs, set()))


def _gather_child_states(need_id, needs, states, cycles):
    """Collect states of direct child Requirements. Returns list or None if incomplete."""
    children = _get_derived_children(need_id, needs, set())
    child_states = []
    for child_id in children:
        if child_id not in cycles and child_id in states:
            child_states.append(states[child_id])
        elif child_id not in cycles:
            return None
    return child_states


def _aggregate_child_states(child_states):
    """RED if any child RED, else YELLOW if any child YELLOW, else GREEN."""
    if NOT_IMPLEMENTED in child_states:
        return NOT_IMPLEMENTED
    if IMPLEMENTED_TEST_NIO in child_states:
        return IMPLEMENTED_TEST_NIO
    return IMPLEMENTED_TEST_IO


def _incoming_ids(need_id, needs, link_type):
    """Find needs that link TO need_id with given link_type (incoming).

    Uses Sphinx-Needs resolved field names:
    - implements: list of target IDs the need implements
    - verifies: list of target IDs the test verifies
    - evidences: list of target IDs the evidence evidences
    - derived_from: list of parent IDs
    """
    ids = []
    for other_id, other in needs.items():
        targets = other.get(link_type, [])
        if not isinstance(targets, list):
            continue
        if need_id in targets and other_id != need_id:
            ids.append(other_id)
    return ids


def _outgoing_ids(need_id, needs, link_type):
    """Find targets that need_id links TO with given link_type (outgoing)."""
    targets = needs.get(need_id, {}).get(link_type, [])
    if not isinstance(targets, list):
        return []
    return [t for t in targets if t != need_id]


def _get_derived_children(need_id, needs, req_ids):
    """Find Requirements that derive from need_id for status-aggregation
    purposes.

    For arcreq/subreq/ifreq this is the direct `derived_from` reverse
    edge. For sysreq there is, by design, no direct `derived_from` edge
    at all (an Architecture Decision `satisfies` a sysreq, it never
    `derived_from`s one) -- and `arch` itself carries no implementation
    state (it is excluded from REQUIREMENT_TYPES). Without bridging
    through that non-Requirement `arch` layer, every sysreq would always
    be treated as a childless leaf and evaluated only against its own
    (always-empty, since IMPL never targets a sysreq directly) implements
    links -- permanently NOT_IMPLEMENTED regardless of how much real,
    evidenced work exists on the arcreq/subreq/ifreq chain beneath it.
    For sysreq, "children" are therefore the arcreq objects that derive
    from any arch which satisfies this sysreq.
    """
    need = needs.get(need_id, {})
    if need.get("type") == "sysreq":
        children = []
        for arch_id, arch_need in needs.items():
            if arch_need.get("type") != "arch":
                continue
            if need_id not in arch_need.get("satisfies", []):
                continue
            for other_id, other in needs.items():
                if other.get("type") not in REQUIREMENT_TYPES:
                    continue
                if arch_id in other.get("derived_from", []):
                    children.append(other_id)
        return children

    children = []
    for other_id, other in needs.items():
        parents = other.get("derived_from", [])
        if not isinstance(parents, list):
            continue
        if need_id in parents and other.get("type") in REQUIREMENT_TYPES:
            children.append(other_id)
    return children


def _detect_cycles(needs):
    """Detect cycles in derived_from graph among Requirements. Returns set of IDs in cycles."""
    req_ids = {nid for nid, n in needs.items() if n.get("type") in REQUIREMENT_TYPES}

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in req_ids}
    cycles = set()

    def dfs(nid, path):
        color[nid] = GRAY
        for target in needs.get(nid, {}).get("derived_from", []):
            if target in req_ids:
                if color.get(target) == GRAY:
                    for p in path[path.index(target):]:
                        cycles.add(p)
                    cycles.add(target)
                elif color.get(target) == WHITE:
                    dfs(target, path + [target])
        color[nid] = BLACK

    for nid in req_ids:
        if color[nid] == WHITE:
            dfs(nid, [nid])
    return cycles


# ---------------------------------------------------------------------------
# Sphinx-Needs filter functions
# ---------------------------------------------------------------------------

# Cache to avoid repeated computation during a single build
_state_cache = None


def _compute_states(needs_list):
    """Compute states from a list of need dicts, using module-level cache."""
    global _state_cache
    needs_dict = {n["id"]: n for n in needs_list}
    if _state_cache != id(needs_list):
        _state_cache = id(needs_list)
        _state_cache = compute_all_requirement_states(needs_dict)
    return _state_cache


def _filter_requirements_by_state(needs, results, target_state):
    """Shared body for filter_red/yellow/green.

    Sphinx-Needs' `:filter-func:` contract (see sphinx_needs.filter_common):
    `needs` is the FULL, unfiltered list of every need in the project;
    `results` starts as an empty list that the function must POPULATE IN
    PLACE — its return value is discarded by the caller. `:filter:` options
    on the same needtable are not applied automatically once `:filter-func:`
    is given, so real-Requirement-type/non-pilot scoping is done here too
    (via REAL_REQUIREMENT_DOCS, the same real/pilot distinction used
    throughout this module), not left to the directive's `:filter:` text.
    """
    states = compute_all_requirement_states({n["id"]: n for n in needs})
    for n in needs:
        ntype = n.get("type")
        if REAL_REQUIREMENT_DOCS.get(ntype) != n.get("docname"):
            continue
        if states.get(n["id"]) == target_state:
            # Never overwrite `implementation_state` here: it is already
            # correctly set (icon + state text) by the adc_impl_state_display
            # dynamic function via the field's predicate default. Doing so
            # here would just re-clobber it with the bare state constant.
            results.append(n)


def filter_red(needs, results, **kwargs):
    _filter_requirements_by_state(needs, results, NOT_IMPLEMENTED)


def filter_yellow(needs, results, **kwargs):
    _filter_requirements_by_state(needs, results, IMPLEMENTED_TEST_NIO)


def filter_green(needs, results, **kwargs):
    _filter_requirements_by_state(needs, results, IMPLEMENTED_TEST_IO)


# ---------------------------------------------------------------------------
# Card-level presentation (Sphinx-Needs dynamic function + dashboard summary)
# ---------------------------------------------------------------------------

# Separate cache from _state_cache above: this one is keyed by the live
# NeedsView identity Sphinx-Needs passes into dynamic functions, not by the
# needs_filter_func's own needs_list identity.
_display_cache_key = None
_display_cache_states = None


def _states_for_needs_view(needs):
    """compute_all_requirement_states(), cached per distinct `needs` view.

    `needs` is whatever Sphinx-Needs passes in (a NeedsView Mapping, or a
    plain dict/list of need dicts in other call sites) — normalized to a
    plain {id: need} dict before computing.
    """
    global _display_cache_key, _display_cache_states
    key = id(needs)
    if _display_cache_key != key:
        if hasattr(needs, "items"):
            needs_dict = dict(needs.items())
        else:
            needs_dict = {n["id"]: n for n in needs}
        _display_cache_key = key
        _display_cache_states = compute_all_requirement_states(needs_dict)
    return _display_cache_states


def adc_impl_state_display(app, need, needs, *args, **kwargs):
    """Sphinx-Needs dynamic function: traffic-light icon + state text for a
    Requirement, e.g. "\U0001F534 NOT_IMPLEMENTED".

    Registered in conf.py as the `implementation_state` field's predicate
    default for sysreq/arcreq/subreq/ifreq needs — resolved automatically
    for every such need. Never set manually on a Requirement directive, and
    never applied to ziel/arch/impl/test/evidence (they keep the field's
    plain "" default, which the card layout simply omits from view).
    """
    states = _states_for_needs_view(needs)
    state = states.get(need.get("id"), NOT_IMPLEMENTED)
    return f"{TRAFFIC_LIGHT_ICON[state]} {state}"


REAL_REQUIREMENT_DOCS = {
    "sysreq": "system/system_requirements",
    "arcreq": "architecture/architecture",
    "subreq": "subsystem/subsystem_requirements",
    "ifreq": "interfaces/interface_requirements",
}


def compute_real_requirement_counts(all_needs):
    """RED/YELLOW/GREEN counts across real (non-pilot) sysreq/arcreq/subreq/
    ifreq only — excludes the synthetic pilot, ziel, arch, impl, test, and
    evidence objects, per the dashboard summary's own scope."""
    states = compute_all_requirement_states(all_needs)
    counts = {NOT_IMPLEMENTED: 0, IMPLEMENTED_TEST_NIO: 0, IMPLEMENTED_TEST_IO: 0}
    for nid, need in all_needs.items():
        ntype = need.get("type")
        if ntype not in REAL_REQUIREMENT_DOCS:
            continue
        if need.get("docname") != REAL_REQUIREMENT_DOCS[ntype]:
            continue  # excludes the synthetic pilot copy of this type
        state = states.get(nid, NOT_IMPLEMENTED)
        counts[state] = counts.get(state, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Post-build JSON export
# ---------------------------------------------------------------------------

def export_requirement_status(app, exception):
    if exception is not None:
        return
    json_path = os.path.join(app.outdir, "needs.json")
    if not os.path.exists(json_path):
        return
    try:
        with open(json_path) as f:
            data = json.load(f)
    except Exception:
        return
    all_needs = {}
    for ver_name, ver_data in data.get("versions", {}).items():
        if isinstance(ver_data, dict) and "needs" in ver_data:
            all_needs.update(ver_data["needs"])

    states = compute_all_requirement_states(all_needs)

    status_report = {}
    for nid, need in all_needs.items():
        if need.get("type") not in REQUIREMENT_TYPES:
            continue

        impl_ids = _incoming_ids(nid, all_needs, "implements")
        test_ids = _incoming_ids(nid, all_needs, "verifies")
        child_ids = [
            t for t in need.get("derived_from", [])
            if all_needs.get(t, {}).get("type") in REQUIREMENT_TYPES
        ]

        state = states.get(nid, NOT_IMPLEMENTED)
        _, reason_info = _leaf_requirement_state(nid, all_needs) if nid not in _find_parents(all_needs) else (None, {})

        status_report[nid] = {
            "id": nid,
            "type": need.get("type"),
            "implementation_state": state,
            "reason": reason_info.get("reason", "aggregated from children") if state != NOT_IMPLEMENTED else "no implementation",
            "implementations": impl_ids,
            "tests": test_ids,
            "child_requirements": child_ids,
        }

    out_path = os.path.join(app.outdir, "requirement_status.json")
    with open(out_path, "w") as f:
        json.dump(status_report, f, indent=2)

    _inject_dashboard_summary(app, all_needs)


def _find_parents(needs):
    parents = set()
    for nid, need in needs.items():
        for target in need.get("derived_from", []):
            if needs.get(target, {}).get("type") in REQUIREMENT_TYPES:
                parents.add(target)
    return parents


# Marker text placed as plain prose in dashboard/overview.rst; replaced here
# with the derived summary HTML after the page has been written. Kept out of
# the .rst content as literal HTML so the RST source stays plain, reviewable
# text with no embedded markup.
DASHBOARD_SUMMARY_MARKER = "ADC_STATUS_SUMMARY_PLACEHOLDER"

_SUMMARY_LABELS = {
    NOT_IMPLEMENTED: "Not implemented",
    IMPLEMENTED_TEST_NIO: "Implemented / verification not IO",
    IMPLEMENTED_TEST_IO: "Implemented / verification IO",
}


def _inject_dashboard_summary(app, all_needs):
    """Replace DASHBOARD_SUMMARY_MARKER in the built overview page with the
    derived RED/YELLOW/GREEN counts. Runs after HTML pages are written
    (build-finished), so it edits the already-emitted HTML file directly —
    counts are always derived here, never hand-edited into the .rst."""
    overview_path = os.path.join(app.outdir, "dashboard", "overview.html")
    if not os.path.exists(overview_path):
        return
    counts = compute_real_requirement_counts(all_needs)
    items = "".join(
        f'<li class="adc-summary-item">{TRAFFIC_LIGHT_ICON[state]} '
        f'{_SUMMARY_LABELS[state]}: <strong>{counts[state]}</strong></li>'
        for state in (NOT_IMPLEMENTED, IMPLEMENTED_TEST_NIO, IMPLEMENTED_TEST_IO)
    )
    summary_html = f'<ul class="adc-status-summary">{items}</ul>'
    with open(overview_path, encoding="utf-8") as f:
        html = f.read()
    if DASHBOARD_SUMMARY_MARKER not in html:
        return
    html = html.replace(DASHBOARD_SUMMARY_MARKER, summary_html)
    with open(overview_path, "w", encoding="utf-8") as f:
        f.write(html)