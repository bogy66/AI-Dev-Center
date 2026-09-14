"""CLAUDE-ARCH-S2-014D: closes the trusted-verification SCOPE leak
CLAUDE-ARCH-S2-013G/014C's own reviews did not cover.

Root cause: `trusted_verification_identity_groups()` (Generalized
Verification module) built every trusted group from ProjectIntelligence's
project-wide `test_system_names`/`build_system_names`/`firmware_indicators`
properties -- a DEDUPED UNION across every `ProjectArea` that discards
which area a capability was actually detected in. Concretely: Area A has
pytest, Area B has nothing to do with pytest at all -- the project-wide
union still handed S2.3 a single, unscoped `{"pytest", "pytest"}` group
that could corroborate ANY candidate's claim, including one that (by
`VerificationCoverage.area`) is for Area B.

RED-before-fix evidence: a standalone reconstruction of the exact pre-fix
`trusted_verification_identity_groups()`/`_independently_corroborated()`
bodies (copied from the Read-tool capture taken during investigation, run
against this exact Area A/Area B fixture) confirmed
`_independently_corroborated("pytest", "pytest", <pre-fix groups>)`
returned True even though the two-area ProjectIntelligence clearly shows
pytest exists ONLY in "area-a" -- i.e. the false pass this file's
`TestAreaALeakClosed` class now proves is CLOSED. See the completion
report for the full pre-fix reproduction transcript (this task deliberately
never uses git checkout/stash to toggle old/new code, per its own
no-git-write-ops constraint).

The fix: `trusted_verification_identity_groups()` now returns
`TrustedVerificationGroup(identities, scope)` entries -- `scope` is the
exact `ProjectArea.path` the capability was detected in, or
`PROJECT_GLOBAL_SCOPE` (".") for the project root (the one honest,
mechanically-derived "project-global" case: the root's own working
directory is an ancestor of every other area by simple filesystem
containment, never a default applied to area-local evidence).
`VerificationCoverage.area` (new, optional, default None) lets a
candidate declare which area/path its evidence pertains to;
`app.engineering_decision._scope_is_covered()` requires an exact match, a
real path-ancestor match (Project > Area > Path containment), or a
root-scoped ("global") group -- never bare string-prefix overlap and
never an implicit project-wide fallback for area-local evidence.
"""
from app.council_models import CouncilResult, CouncilVariant, ToolchainItem, VerificationCoverage
from app.engineering_decision import validate_candidates
from app.project_intelligence import (
    DetectedBuildSystem,
    DetectedTestSystem,
    ProjectArea,
    ProjectIntelligence,
)
from app.verification import trusted_verification_identity_groups

from tests.test_engineering_decision import (
    _binding_preflight,
    _pip_item,
    _requirement_needing_verification,
)


def _area(path, test_systems=(), build_systems=(), firmware=()):
    return ProjectArea(
        path=path, languages=(), frameworks=(), package_systems=(),
        build_systems=tuple(DetectedBuildSystem(n, ()) for n in build_systems),
        test_systems=tuple(DetectedTestSystem(n, ()) for n in test_systems),
        firmware_indicators=tuple(firmware),
    )


def _intelligence(*areas):
    all_test = tuple({ts.name: ts for a in areas for ts in a.test_systems}.values())
    all_build = tuple({bs.name: bs for a in areas for bs in a.build_systems}.values())
    all_fw = tuple({fw.name: fw for a in areas for fw in a.firmware_indicators}.values())
    return ProjectIntelligence(
        project_root="/tmp/proj", project_kind="mixed", areas=tuple(areas),
        languages=(), frameworks=(), package_systems=(),
        build_systems=all_build, test_systems=all_test, firmware_indicators=all_fw,
        ci_indicators=(), doc_indicators=(), git_repository_present=True,
        sensitive_configuration_present=False, warnings=(), truncated=False,
        total_files_traversed=1, total_files_excluded=0,
        inspection_limit_exceeded=False,
    )


def _fake_item(req_id, technical_identity, mechanism, state="needs_install"):
    return ToolchainItem(
        requirement_ref=req_id, name=technical_identity, type="executable",
        technical_identity=technical_identity, provides_verification=(mechanism,),
        state=state,
    )


def _admissible(item, coverage, preflight, trusted_groups, req_id=None):
    """`req_id` (when given) also adds a plain _pip_item(req_id) to the
    toolchain -- positive-outcome cases need SOME ToolchainItem to satisfy
    the underlying binding Requirement itself, independent of the
    verification-mechanism item under test (mirrors
    tests/test_verification_feasibility_trust.py's own PASS examples)."""
    toolchain = (item, _pip_item(req_id)) if req_id else (item,)
    variant = CouncilVariant(id="v1", name="v1", toolchain=toolchain, verification_coverage=(coverage,))
    result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                            recommendation="v1", council_complete=True)
    return validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted_groups)[0].admissible


class TestAreaALeakClosed:
    """The exact reproduction scenario: Area A has pytest, Area B has
    nothing to do with pytest -- Area A's pytest must never make an Area B
    (or unscoped) requirement admissible."""

    def test_area_b_claim_using_area_a_pytest_is_inadmissible(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(_area("area-a", test_systems=["pytest"]), _area("area-b"))
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest", area="area-b",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is False

    def test_unscoped_claim_using_area_a_pytest_is_inadmissible(self):
        """No VerificationCoverage.area declared at all -- fail-closed:
        area-local evidence never covers an unscoped requirement (only
        root/project-global evidence would)."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(_area("area-a", test_systems=["pytest"]), _area("area-b"))
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is False


class TestPositiveSameAreaRemainsProductive:
    def test_area_a_claim_using_area_a_pytest_is_admissible(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(_area("area-a", test_systems=["pytest"]), _area("area-b"))
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest", area="area-a",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is True

    def test_single_area_project_with_no_declared_scope_stays_productive(self):
        """The overwhelming existing case (root-only project, areas=()) --
        untouched by this task's scope binding: no per-area breakdown at
        all falls back to PROJECT_GLOBAL_SCOPE, so a candidate that never
        declares `area` (matching every pre-014D candidate/test) still
        becomes admissible exactly as before."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = ProjectIntelligence(
            project_root="/tmp/proj", project_kind="existing", areas=(),
            languages=(), frameworks=(), package_systems=(),
            build_systems=(), test_systems=(DetectedTestSystem("pytest", ()),),
            firmware_indicators=(), ci_indicators=(), doc_indicators=(),
            git_repository_present=True, sensitive_configuration_present=False,
            warnings=(), truncated=False, total_files_traversed=1,
            total_files_excluded=0, inspection_limit_exceeded=False,
        )
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is True

    def test_project_root_capability_covers_every_area(self):
        """The one mechanically-derived "project-global" exception: pytest
        detected at the project ROOT (".") -- e.g. a top-level pytest.ini
        that recursively covers every area -- legitimately corroborates a
        claim scoped to a specific, different, non-root area."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(
            _area(".", test_systems=["pytest"]), _area("area-a"), _area("area-b"),
        )
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest", area="area-b",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is True


class TestNegativeMultiAreaAndPathCrossWiring:
    def test_cross_area_build_system_wiring_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(
            _area("backend", test_systems=["pytest"]), _area("firmware", build_systems=["cmake"]),
        )
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "cmake", "cmake")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="build_command",
            mechanism="cmake", evidence="cmake", area="backend",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is False

    def test_nested_path_under_the_same_area_is_covered(self):
        """Project > Area > Path containment: a declared scope that is a
        real sub-path of a trusted area's own path is still covered."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(_area("backend", test_systems=["pytest"]), _area("frontend"))
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest", area="backend/sub_module",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is True

    def test_unrelated_path_under_a_different_area_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(_area("backend", test_systems=["pytest"]), _area("frontend"))
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest", area="frontend/sub_module",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is False

    def test_string_prefix_overlap_without_a_real_path_separator_fails(self):
        """Guards against a naive `.startswith(group_scope)` bug: "backend"
        must never be treated as covering "backend-other" just because one
        string happens to start with the other -- only a real path
        separator counts as containment."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(_area("backend", test_systems=["pytest"]))
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest", area="backend-other",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is False


class TestMalformedScopeBadLLMRegression:
    """9 (014D): a CLASS of malformed/hallucinated scope declarations must
    always fail closed, mirroring the existing generalized bad-LLM
    self-certification class for mechanism/evidence (013G)."""

    def _run(self, area_claim):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(_area("area-a", test_systems=["pytest"]), _area("area-b"))
        trusted_groups = trusted_verification_identity_groups(intelligence)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest", area=area_claim,
        )
        return _admissible(item, coverage, preflight, trusted_groups, req_id=req.id)

    def test_hallucinated_nonexistent_area_fails(self):
        assert self._run("totally-made-up-area-xyz") is False

    def test_falsely_claiming_root_fails(self):
        """Pytest was never actually detected at the project root -- an
        LLM cannot mint a "." claim into project-global trust."""
        assert self._run(".") is False

    def test_empty_string_scope_fails(self):
        assert self._run("") is False

    def test_trailing_slash_variant_of_the_real_area_fails(self):
        """A malformed but superficially-similar scope string must not be
        silently normalized into a match."""
        assert self._run("area-a/") is False

    def test_case_variant_of_the_real_area_fails(self):
        assert self._run("Area-A") is False

    def test_path_traversal_out_of_the_trusted_area_fails(self):
        """A naive `requirement_scope.startswith(group_scope + "/")` check
        would wrongly treat "area-a/../area-b" as covered by "area-a" --
        it IS a literal string prefix match even though it actually
        resolves OUT of area-a. Segment-based comparison must reject any
        declared scope containing ".."/"." segments outright rather than
        silently resolving it."""
        assert self._run("area-a/../area-b") is False
        assert self._run("area-a/./sub") is False


class TestDictShapeParity:
    """The dict-shaped intelligence (ProjectIntelligence.to_summary(),
    used by CouncilInput.project_intelligence / the S2.2 early-rework
    admissibility check) must enforce the exact same scope binding as the
    real dataclass shape -- not a weaker, lossy one."""

    def test_to_summary_areas_key_preserves_scope_binding(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        intelligence = _intelligence(_area("area-a", test_systems=["pytest"]), _area("area-b"))
        summary = intelligence.to_summary()
        assert "areas" in summary
        trusted_groups = trusted_verification_identity_groups(summary)
        item = _fake_item(req.id, "pytest", "pytest")

        leaking_coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest", area="area-b",
        )
        assert _admissible(item, leaking_coverage, preflight, trusted_groups, req_id=req.id) is False

        legitimate_coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest", area="area-a",
        )
        assert _admissible(item, legitimate_coverage, preflight, trusted_groups, req_id=req.id) is True

    def test_legacy_dict_without_areas_key_falls_back_to_project_global(self):
        """A hand-built dict summary that predates this task (no "areas"
        key at all) must keep working exactly as before -- the fallback
        is PROJECT_GLOBAL_SCOPE, not a silent loss of all trust."""
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        legacy_summary = {"test_systems": ["pytest"], "build_systems": [], "firmware_indicators": []}
        trusted_groups = trusted_verification_identity_groups(legacy_summary)
        item = _fake_item(req.id, "pytest", "pytest")
        coverage = VerificationCoverage(
            requirement_refs=(req.id,), kind="test_command",
            mechanism="pytest", evidence="pytest",
        )
        assert _admissible(item, coverage, preflight, trusted_groups, req_id=req.id) is True
