"""Self-test for ADC requirement status model.

Run with: .requirements-venv/bin/python requirements/test_status_model.py
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from status_model import (
    compute_all_requirement_states,
    NOT_IMPLEMENTED,
    IMPLEMENTED_TEST_NIO,
    IMPLEMENTED_TEST_IO,
    REQUIREMENT_TYPES,
    _detect_cycles,
    filter_red,
    filter_yellow,
    filter_green,
)

PASS, FAIL = 0, 0


def make_needs(specs):
    """Build a needs dict. Each spec: (id, type, link_dict, extra).

    link_dict: maps link field name to list of target IDs.
    e.g. {'implements': ['IF_REQ_A']}
    """
    needs = {}
    for spec in specs:
        nid, ntype, link_dict, *rest = spec
        extra = rest[0] if rest else {}
        need = {"id": nid, "type": ntype, "status": "approved"}
        for field in ["implements", "verifies", "evidences", "derived_from",
                      "satisfies", "realizes", "refines"]:
            need[field] = link_dict.get(field, [])[:]
        need.update(extra)
        needs[nid] = need
    return needs


def expect(label, actual, expected):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  PASS: {label}")
    else:
        FAIL += 1
        print(f"  FAIL: {label} — expected {expected}, got {actual}")


def test_no_implementation():
    needs = make_needs([("IF_REQ_A", "ifreq", {})])
    states = compute_all_requirement_states(needs)
    expect("no implementation → RED", states.get("IF_REQ_A"), NOT_IMPLEMENTED)


def test_implementation_no_test():
    needs = make_needs([
        ("IF_REQ_A", "ifreq", {}),
        ("IMPL_A", "impl", {"implements": ["IF_REQ_A"]}),
    ])
    states = compute_all_requirement_states(needs)
    expect("impl no test → YELLOW", states.get("IF_REQ_A"), IMPLEMENTED_TEST_NIO)


def test_impl_test_not_run():
    needs = make_needs([
        ("IF_REQ_A", "ifreq", {}),
        ("IMPL_A", "impl", {"implements": ["IF_REQ_A"]}),
        ("TEST_A", "test", {"verifies": ["IF_REQ_A"]}, {"verification_result": "NOT_RUN"}),
    ])
    states = compute_all_requirement_states(needs)
    expect("test NOT_RUN → YELLOW", states.get("IF_REQ_A"), IMPLEMENTED_TEST_NIO)


def test_impl_test_nio():
    needs = make_needs([
        ("IF_REQ_A", "ifreq", {}),
        ("IMPL_A", "impl", {"implements": ["IF_REQ_A"]}),
        ("TEST_A", "test", {"verifies": ["IF_REQ_A"]}, {"verification_result": "NIO"}),
    ])
    states = compute_all_requirement_states(needs)
    expect("test NIO → YELLOW", states.get("IF_REQ_A"), IMPLEMENTED_TEST_NIO)


def test_impl_test_io_no_evidence():
    needs = make_needs([
        ("IF_REQ_A", "ifreq", {}),
        ("IMPL_A", "impl", {"implements": ["IF_REQ_A"]}),
        ("TEST_A", "test", {"verifies": ["IF_REQ_A"]}, {"verification_result": "IO"}),
    ])
    states = compute_all_requirement_states(needs)
    expect("test IO no evidence → YELLOW", states.get("IF_REQ_A"), IMPLEMENTED_TEST_NIO)


def test_impl_test_io_with_evidence():
    needs = make_needs([
        ("IF_REQ_A", "ifreq", {}),
        ("IMPL_A", "impl", {"implements": ["IF_REQ_A"]}),
        ("TEST_A", "test", {"verifies": ["IF_REQ_A"]}, {"verification_result": "IO"}),
        ("EVID_A", "evidence", {"evidences": ["TEST_A"]}),
    ])
    states = compute_all_requirement_states(needs)
    expect("test IO + evidence → GREEN", states.get("IF_REQ_A"), IMPLEMENTED_TEST_IO)


def test_multi_test_one_nio():
    needs = make_needs([
        ("IF_REQ_A", "ifreq", {}),
        ("IMPL_A", "impl", {"implements": ["IF_REQ_A"]}),
        ("TEST_A", "test", {"verifies": ["IF_REQ_A"]}, {"verification_result": "IO"}),
        ("TEST_B", "test", {"verifies": ["IF_REQ_A"]}, {"verification_result": "NIO"}),
        ("EVID_A", "evidence", {"evidences": ["TEST_A"]}),
    ])
    states = compute_all_requirement_states(needs)
    expect("multi-test one NIO → YELLOW", states.get("IF_REQ_A"), IMPLEMENTED_TEST_NIO)


def test_parent_red_child():
    needs = make_needs([
        ("ARC_REQ_P", "arcreq", {"derived_from": []}),
        ("ARC_REQ_C1", "arcreq", {"derived_from": ["ARC_REQ_P"]}),
        ("ARC_REQ_C2", "arcreq", {"derived_from": ["ARC_REQ_P"]}),
        ("IMPL_C2", "impl", {"implements": ["ARC_REQ_C2"]}),
        ("TEST_C2", "test", {"verifies": ["ARC_REQ_C2"]}, {"verification_result": "IO"}),
        ("EVID_C2", "evidence", {"evidences": ["TEST_C2"]}),
    ])
    states = compute_all_requirement_states(needs)
    expect("parent RED child → RED", states.get("ARC_REQ_P"), NOT_IMPLEMENTED)


def test_parent_yellow_child():
    needs = make_needs([
        ("ARC_REQ_P", "arcreq", {"derived_from": []}),
        ("ARC_REQ_C1", "arcreq", {"derived_from": ["ARC_REQ_P"]}),
        ("ARC_REQ_C2", "arcreq", {"derived_from": ["ARC_REQ_P"]}),
        ("IMPL_C1", "impl", {"implements": ["ARC_REQ_C1"]}),
        ("TEST_C1", "test", {"verifies": ["ARC_REQ_C1"]}, {"verification_result": "IO"}),
        ("EVID_C1", "evidence", {"evidences": ["TEST_C1"]}),
        ("IMPL_C2", "impl", {"implements": ["ARC_REQ_C2"]}),
        ("TEST_C2", "test", {"verifies": ["ARC_REQ_C2"]}, {"verification_result": "NOT_RUN"}),
    ])
    states = compute_all_requirement_states(needs)
    expect("parent YELLOW child → YELLOW", states.get("ARC_REQ_P"), IMPLEMENTED_TEST_NIO)


def test_parent_green_children():
    needs = make_needs([
        ("ARC_REQ_P", "arcreq", {"derived_from": []}),
        ("ARC_REQ_C1", "arcreq", {"derived_from": ["ARC_REQ_P"]}),
        ("ARC_REQ_C2", "arcreq", {"derived_from": ["ARC_REQ_P"]}),
        ("IMPL_C1", "impl", {"implements": ["ARC_REQ_C1"]}),
        ("TEST_C1", "test", {"verifies": ["ARC_REQ_C1"]}, {"verification_result": "IO"}),
        ("EVID_C1", "evidence", {"evidences": ["TEST_C1"]}),
        ("IMPL_C2", "impl", {"implements": ["ARC_REQ_C2"]}),
        ("TEST_C2", "test", {"verifies": ["ARC_REQ_C2"]}, {"verification_result": "IO"}),
        ("EVID_C2", "evidence", {"evidences": ["TEST_C2"]}),
    ])
    states = compute_all_requirement_states(needs)
    expect("parent all GREEN → GREEN", states.get("ARC_REQ_P"), IMPLEMENTED_TEST_IO)


def test_cycle_detection():
    needs = make_needs([
        ("ARC_REQ_A", "arcreq", {"derived_from": ["ARC_REQ_B"]}),
        ("ARC_REQ_B", "arcreq", {"derived_from": ["ARC_REQ_A"]}),
    ])
    cycles = _detect_cycles(needs)
    expect("cycle detected", len(cycles) >= 2, True)


def test_sysreq_aggregates_through_arch_bridge():
    """Regression test for CLAUDE-ADC-SPHINX-IMPLEMENTATION-TEST-EVIDENCE-
    MAPPING-001: a sysreq has no `derived_from` edge of its own (an `arch`
    `satisfies` it, never `derived_from`s it), and `arch` itself is not a
    REQUIREMENT_TYPE. Before this fix, every sysreq was therefore always
    treated as a childless leaf and evaluated only against its own
    (always-empty) implements links — permanently NOT_IMPLEMENTED
    regardless of real, evidenced progress on the arcreq/subreq/ifreq
    chain beneath it. `_get_derived_children` must bridge sysreq ->
    (arch it satisfies) -> arcreq for aggregation purposes."""
    needs = make_needs([
        ("SYS_REQ_A", "sysreq", {}),
        ("ARC_A", "arch", {"satisfies": ["SYS_REQ_A"]}),
        ("ARC_REQ_A", "arcreq", {"derived_from": ["ARC_A"]}),
        ("IMPL_A", "impl", {"implements": ["ARC_REQ_A"]}),
        ("TEST_A", "test", {"verifies": ["ARC_REQ_A"]}, {"verification_result": "IO"}),
        ("EVID_A", "evidence", {"evidences": ["TEST_A"]}),
    ])
    states = compute_all_requirement_states(needs)
    expect(
        "sysreq aggregates GREEN through its satisfying arch's arcreq child",
        states.get("SYS_REQ_A"), IMPLEMENTED_TEST_IO,
    )


def test_sysreq_without_arcreq_descendant_stays_a_leaf():
    """A sysreq satisfied only by an arch with no arcreq beneath it has no
    aggregation children and correctly falls back to leaf evaluation
    (RED, since nothing implements a sysreq directly) — the bridge must
    not fabricate coverage that doesn't exist."""
    needs = make_needs([
        ("SYS_REQ_B", "sysreq", {}),
        ("ARC_B", "arch", {"satisfies": ["SYS_REQ_B"]}),
    ])
    states = compute_all_requirement_states(needs)
    expect(
        "sysreq with no arcreq descendant stays RED, not fabricated coverage",
        states.get("SYS_REQ_B"), NOT_IMPLEMENTED,
    )


def test_filter_red_yellow_green_mutate_results_in_place():
    """Regression test for the card-traffic-light task
    (OC-ADC-SPHINX-REQUIREMENT-CARD-TRAFFIC-LIGHT-001): Sphinx-Needs calls
    a `:filter-func:` as `filter_func(needs=<all needs>, results=<empty
    list>)` and DISCARDS its return value — the function must populate
    `results` in place, filtering from the full `needs` list, not from the
    (always-empty) `results` list it receives. Also verifies these
    functions must NOT overwrite `implementation_state`: that field is
    already set (icon + text) by the adc_impl_state_display dynamic
    function, and clobbering it with the bare state constant here would
    strip the icon back off on real Sphinx-Needs cards."""
    real_docname = "interfaces/interface_requirements"
    needs_dict = make_needs([
        ("IF_REQ_A", "ifreq", {}, {
            "docname": real_docname, "implementation_state": "\U0001F534 NOT_IMPLEMENTED",
        }),
        ("IF_REQ_B", "ifreq", {}, {
            "docname": real_docname, "implementation_state": "\U0001F7E1 IMPLEMENTED_TEST_NIO",
        }),
        ("IMPL_B", "impl", {"implements": ["IF_REQ_B"]}, {"docname": real_docname}),
        ("IF_REQ_PILOT", "ifreq", {}, {
            "docname": "pilot/synthetic_traceability", "tags": ["pilot"],
            "implementation_state": "\U0001F534 NOT_IMPLEMENTED",
        }),
    ])
    needs_list = list(needs_dict.values())

    red_results = []
    filter_red(needs_list, red_results)
    expect("filter_red mutates results in place", [n["id"] for n in red_results], ["IF_REQ_A"])
    expect(
        "filter_red does not overwrite implementation_state's icon",
        red_results[0]["implementation_state"], "\U0001F534 NOT_IMPLEMENTED",
    )
    expect("filter_red excludes the synthetic pilot", "IF_REQ_PILOT" not in [n["id"] for n in red_results], True)

    yellow_results = []
    filter_yellow(needs_list, yellow_results)
    expect("filter_yellow mutates results in place", [n["id"] for n in yellow_results], ["IF_REQ_B"])

    green_results = []
    filter_green(needs_list, green_results)
    expect("filter_green finds nothing here", green_results, [])


if __name__ == "__main__":
    test_no_implementation()
    test_implementation_no_test()
    test_impl_test_not_run()
    test_impl_test_nio()
    test_impl_test_io_no_evidence()
    test_impl_test_io_with_evidence()
    test_multi_test_one_nio()
    test_parent_red_child()
    test_parent_yellow_child()
    test_parent_green_children()
    test_cycle_detection()
    test_sysreq_aggregates_through_arch_bridge()
    test_sysreq_without_arcreq_descendant_stays_a_leaf()
    test_filter_red_yellow_green_mutate_results_in_place()

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(0 if FAIL == 0 else 1)