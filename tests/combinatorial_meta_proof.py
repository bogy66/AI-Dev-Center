"""Independent combinatorial coverage meta-proof
(KIA-ADC-TEST-ASSURANCE-MODEL-FIX-001 section 5).

tests/env_pairwise.py's own `generate_covering_array()` tracks its
generation obligations internally via `itertools.combinations` +
`itertools.product` (see its `_all_t_way_sets` helper), removing each
obligation from a `remaining` set as it happens to get satisfied. That
internal bookkeeping is convenient for building a small array, but it
is not independent verification: a bug in how it enumerates or removes
obligations could hide a real gap from itself.

This module recomputes REQUIRED_INTERACTIONS and GENERATED_INTERACTIONS
from scratch, via plain recursion over parameter names and values (no
itertools, no shared helper with env_pairwise.py), so it cannot inherit
a defect from the generator's own obligation math. It is deliberately
"reinvent the enumeration a second, structurally different way", not
"reuse env_pairwise.py's own counting" and not "add a second competing
Evidence system" -- it is a pure, stateless, read-only checker over
whatever (param_values, strength, cases) it is given.
"""
from __future__ import annotations


def required_interactions(param_values: dict[str, tuple], strength: int) -> frozenset[tuple]:
    """Every REQUIRED strength-way interaction: for every way of
    choosing `strength` distinct parameter names (recursive name
    selection, not itertools.combinations) and one value from each
    (recursive value assignment, not itertools.product), the resulting
    (name, value) tuple is one obligation a covering array must satisfy."""
    names = list(param_values.keys())
    required: set[tuple] = set()

    def choose_names(start: int, chosen: list[str]) -> None:
        if len(chosen) == strength:
            _assign_values(tuple(chosen))
            return
        for i in range(start, len(names)):
            choose_names(i + 1, chosen + [names[i]])

    def _assign_values(chosen_names: tuple[str, ...]) -> None:
        def assign(i: int, assignment: list[tuple[str, object]]) -> None:
            if i == len(chosen_names):
                required.add(tuple(assignment))
                return
            name = chosen_names[i]
            for value in param_values[name]:
                assign(i + 1, assignment + [(name, value)])
        assign(0, [])

    if strength <= len(names):
        choose_names(0, [])
    return frozenset(required)


def generated_interactions(cases: tuple[dict, ...], strength: int) -> frozenset[tuple]:
    """Every strength-way interaction actually REALIZED by the given
    generated cases, via the same independent recursive name-selection
    (never reading env_pairwise.py's own remaining-obligations state)."""
    if not cases:
        return frozenset()
    names = list(cases[0].keys())
    generated: set[tuple] = set()

    def choose_names(start: int, chosen: list[str]) -> None:
        if len(chosen) == strength:
            key = tuple(chosen)
            for case in cases:
                generated.add(tuple((name, case[name]) for name in key))
            return
        for i in range(start, len(names)):
            choose_names(i + 1, chosen + [names[i]])

    if strength <= len(names):
        choose_names(0, [])
    return frozenset(generated)


def verify_combinatorial_coverage(
    param_values: dict[str, tuple], strength: int, cases: tuple[dict, ...],
) -> dict[str, object]:
    """The mechanical REQUIRED_INTERACTIONS / GENERATED_INTERACTIONS /
    COVERED_INTERACTIONS / MISSING_INTERACTIONS meta-proof section 5
    demands for every Pairwise/Three-Way domain. A non-empty
    `missing_interactions` means the claimed covering array does not
    actually achieve the strength-way coverage it claims -- assurance
    must fail on that, not merely report it."""
    required = required_interactions(param_values, strength)
    generated = generated_interactions(cases, strength)
    covered = required & generated
    missing = required - generated
    return {
        "required_interactions": required,
        "generated_interactions": generated,
        "covered_interactions": covered,
        "missing_interactions": missing,
        "required_count": len(required),
        "generated_count": len(generated),
        "covered_count": len(covered),
        "missing_count": len(missing),
    }
