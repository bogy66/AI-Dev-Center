"""Small, deterministic, dependency-free combinatorial covering-array
helper (CLAUDE-ADC-TEST-ENVIRONMENT-FIDELITY-UPGRADE-001, section 3/4).

No pairwise/property-based library is installed anywhere in this
environment (verified before writing this module); this is a from
-scratch, TEST-ONLY implementation, deliberately simple: a greedy
algorithm that, given N parameters each with a fixed list of values,
produces a deterministic (seed-free, order-stable) set of tuples such
that every PAIR of values across every pair of parameters appears in at
least one generated tuple (pairwise / 2-wise covering), or every TRIPLE
of values across every triple of parameters appears in at least one
generated tuple (3-wise covering, via the same algorithm generalized).

This is NOT claimed to be an optimal (minimum-size) covering array --
only a correct, deterministic one. Determinism (same input always
produces the same output tuples in the same order) is what this
module's own tests verify, since a test suite that regenerates a
different case set on every run would defeat reproducibility.
"""
from __future__ import annotations

from itertools import combinations, product


def _all_t_way_sets(param_values: dict[str, tuple], t: int):
    """Every combination of `t` distinct parameter names, each paired
    with one of its own values, that must appear together in at least
    one generated tuple -- the full "coverage obligation" set."""
    names = tuple(param_values.keys())
    obligations = []
    for name_combo in combinations(names, t):
        value_lists = [param_values[n] for n in name_combo]
        for value_combo in product(*value_lists):
            obligations.append(tuple(zip(name_combo, value_combo)))
    return obligations


def generate_covering_array(
    param_values: dict[str, tuple], strength: int = 2,
) -> tuple[dict[str, object], ...]:
    """Deterministic greedy t-wise covering array.

    param_values: {parameter_name: (value1, value2, ...)}, insertion
    order preserved (Python dict order), which is what makes the
    output deterministic across runs.
    strength: 2 for pairwise, 3 for 3-wise.

    Returns a tuple of dicts, each a full assignment of every
    parameter to one of its values, such that every `strength`-way
    combination of (parameter, value) pairs drawn from distinct
    parameters is represented in at least one returned dict.
    """
    if strength < 1:
        raise ValueError("strength must be >= 1")
    names = tuple(param_values.keys())
    if not names:
        return ()

    # KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 4: a PAIRWISE (strength=2)
    # or THREE_WAY (strength=3) claim is degenerate -- and must be rejected,
    # not silently downgraded -- unless at least `strength` distinct
    # parameters each carry >= 2 meaningful values. Without this guard,
    # `min(strength, len(names))` below would silently accept e.g. a
    # 2-parameter dict where one parameter has only one value and quietly
    # generate what is really a 1-way (equivalence-partition) sweep while
    # still being labelled/claimed as pairwise.
    if strength >= 2:
        varying = [n for n in names if len(param_values[n]) >= 2]
        if len(varying) < strength:
            strength_name = {2: "PAIRWISE", 3: "THREE_WAY"}.get(strength, f"strength={strength}")
            raise ValueError(
                f"degenerate {strength_name} claim: requires >= {strength} genuinely "
                f"varying dimensions (>= 2 values each), but only {len(varying)} vary "
                f"({varying}) out of {list(names)}. Reclassify this domain honestly as "
                f"an equivalence-partition/boundary-value/exhaustive sweep instead of "
                f"calling generate_covering_array with strength={strength}."
            )

    obligations = _all_t_way_sets(param_values, min(strength, len(names)))
    remaining = set(obligations)
    cases: list[dict[str, object]] = []

    # Deterministic value cycle per parameter, used to fill parameters
    # not pinned by the obligation a new case is built around -- keeps
    # generation seed-free and stable.
    cycle_index = {name: 0 for name in names}

    while remaining:
        # Always take the earliest-inserted remaining obligation
        # (obligations list preserves generation order) for determinism.
        target = next(ob for ob in obligations if ob in remaining)
        assignment: dict[str, object] = dict(target)
        for name in names:
            if name not in assignment:
                values = param_values[name]
                assignment[name] = values[cycle_index[name] % len(values)]
                cycle_index[name] += 1
        cases.append(assignment)

        # Remove every obligation this new case happens to satisfy,
        # not just the one it was built around -- this is what keeps
        # the array small rather than exactly one case per obligation.
        satisfied = set()
        for ob in remaining:
            if all(assignment[name] == value for name, value in ob):
                satisfied.add(ob)
        remaining -= satisfied

    return tuple(cases)


def case_id(assignment: dict[str, object]) -> str:
    """Stable, readable identifier for one generated case, usable as a
    pytest.mark.parametrize id."""
    return "-".join(f"{k}={v}" for k, v in assignment.items())
