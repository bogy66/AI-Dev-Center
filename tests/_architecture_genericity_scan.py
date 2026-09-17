"""Shared, policy-free AST scanning primitives for Sx.y Genericity /
Non-Specialization regressions (CLAUDE-ADC-S3-S4-S5-ARCHITECTURE-PERSIST-
001, closing the §4J/Part 29B review finding: the pre-existing S3
genericity scan (tests/test_s3_legacy_hygiene_wiring.py) only inspected
`ast.Compare` string-literal operands, which misses a hard-coded
ecosystem name hidden behind a `match`/`case` literal pattern or behind
an anonymous inline dict-literal-then-subscript dispatch table.

This module is intentionally mechanical: it only WALKS an AST and
reports raw findings (line, literal value, or node). It carries no
opinion about which files are "central orchestration", which literals
are "forbidden ecosystem names", or which findings are acceptable --
every one of those judgments belongs to the test file that calls these
functions and supplies its own file list / forbidden-name set, exactly
like the pre-existing S3 scan already did for its own narrower check.
A NAMED, module-level dict constant (e.g. app.verification.RUNNER_MAP)
is deliberately NOT what `inline_dict_subscript_dispatch` flags --
that is the documented, generic, table-driven pattern the architecture
explicitly wants (see RUNNER_MAP's own docstring); this only flags an
UNNAMED dict literal used immediately as a subscript dispatch table at
its use site, which is a way to hide branch-by-name logic that neither
the pre-existing Compare scan nor a "no hardcoded dict of ecosystem
names" rule would otherwise catch.
"""
from __future__ import annotations

import ast
from pathlib import Path


def parse(relative_path: str, root: Path) -> ast.Module:
    return ast.parse((root / relative_path).read_text(encoding="utf-8"), filename=relative_path)


def string_literal_comparison_operands(tree: ast.Module) -> list[tuple[int, str]]:
    """Every string constant appearing as an `ast.Compare` operand.

    Catches `if fw_name == "esphome":`, `x in ("cmake", "make")`, etc.
    Does NOT catch enum/constant attribute access (e.g.
    `RequirementType.PYTHON_PACKAGE`) since that is never a string
    Constant node -- generic structured vocabulary is never flagged by
    construction, not by an exclusion list.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for operand in (node.left, *node.comparators):
                if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                    found.append((node.lineno, operand.value))
    return found


def match_case_string_patterns(tree: ast.Module) -> list[tuple[int, str]]:
    """Every literal string pattern in a `match`/`case` statement.

    `ast.Match` only exists from Python 3.10; walking for it is a no-op
    (never an error) on any source file that uses no such statement.
    """
    found: list[tuple[int, str]] = []
    match_type = getattr(ast, "Match", None)
    if match_type is None:
        return found
    match_value_type = getattr(ast, "MatchValue", None)
    for node in ast.walk(tree):
        if isinstance(node, match_type):
            for case in node.cases:
                pattern = case.pattern
                if match_value_type is not None and isinstance(pattern, match_value_type):
                    value_node = pattern.value
                    if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                        found.append((case.lineno, value_node.value))
    return found


def inline_dict_subscript_dispatch(tree: ast.Module) -> list[tuple[int, tuple[str, ...]]]:
    """Every `{...}[key]` where the dict is an ANONYMOUS literal at the
    subscript site (never a named module-level table looked up via
    `.get()`/`[...]` elsewhere -- that pattern is the accepted,
    documented, generic table-driven mechanism, e.g. RUNNER_MAP).

    Returns each occurrence's line and the tuple of its literal string
    keys (non-string keys are omitted from the tuple but the
    occurrence itself is still reported, since a mixed-key dispatch
    dict is exactly as suspicious).
    """
    found: list[tuple[int, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Dict):
            keys = tuple(
                key.value for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
            found.append((node.lineno, keys))
    return found


def literal_string_constants(tree: ast.Module) -> list[tuple[int, str]]:
    """Every bare string Constant anywhere in the module (superset used
    for the filename/extension-literal check, which does not live
    inside an `ast.Compare` -- e.g. `path.endswith(".yaml")`)."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
    return found


def call_names(tree: ast.Module) -> list[str]:
    """Every function/method name a `Call` node invokes (reused wiring-
    proof primitive, mirrors tests/test_s3_legacy_hygiene_wiring.py's
    own `_call_names`)."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.append(node.func.attr)
    return names


def scan_forbidden_ecosystem_dispatch(
    relative_paths: tuple[str, ...], root: Path, forbidden_names: frozenset[str],
) -> list[tuple[str, int, str]]:
    """The one combined check a test file calls: for every file in
    `relative_paths`, report every (file, line, literal) where a
    forbidden ecosystem name appears as a Compare operand, a match/case
    literal pattern, or a key in an anonymous inline dispatch dict.
    """
    violations: list[tuple[str, int, str]] = []
    for relative in relative_paths:
        tree = parse(relative, root)
        for lineno, literal in string_literal_comparison_operands(tree):
            if literal.strip().lower() in forbidden_names:
                violations.append((relative, lineno, literal))
        for lineno, literal in match_case_string_patterns(tree):
            if literal.strip().lower() in forbidden_names:
                violations.append((relative, lineno, literal))
        for lineno, keys in inline_dict_subscript_dispatch(tree):
            for key in keys:
                if key.strip().lower() in forbidden_names:
                    violations.append((relative, lineno, key))
    return violations


def class_subtree(tree: ast.Module, class_name: str) -> ast.ClassDef:
    """The AST subtree for exactly one top-level class in `tree`.

    Lets a test scope a strict "zero forbidden literal" check to one
    specific class (e.g. ControlledRunnerRegistry) inside a file that
    also legitimately contains OTHER, adapter-level classes (the
    VerificationRunner subclasses) the architecture explicitly permits
    to know their own ecosystem's name -- scoping by class is more
    precise than excluding the whole file.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise ValueError(f"class {class_name!r} not found")


def scan_forbidden_extension_literals(
    relative_paths: tuple[str, ...], root: Path, forbidden_extensions: frozenset[str],
) -> list[tuple[str, int, str]]:
    """Every (file, line, literal) where a hard-coded filename extension
    (e.g. ".py", ".cpp", ".yaml") appears as a bare string constant --
    central orchestration selecting behavior by file extension is the
    same "one-stack-only" problem as selecting it by ecosystem name."""
    violations: list[tuple[str, int, str]] = []
    for relative in relative_paths:
        tree = parse(relative, root)
        for lineno, literal in literal_string_constants(tree):
            if literal.strip().lower() in forbidden_extensions:
                violations.append((relative, lineno, literal))
    return violations
