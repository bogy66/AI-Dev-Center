"""CLAUDE-ARCH-S2-014C (F2): closes the "recognition proves capability"
gap independently reproduced in CDX-REVIEW-S2-014A.

Root cause: `app.verification.trusted_verification_identity_groups()`
(CLAUDE-ARCH-S2-013G) granted trust to EVERY name Project Intelligence
recognized (via RUNNER_MAP/BUILD_RUNNER_MAP/FIRMWARE_RUNNER_MAP name
mapping) regardless of that mapping's OWN `policy` field
("controlled_execution" | "deferred" | "unsupported") -- e.g. ctest and
jest are independently DETECTABLE (RUNNER_MAP contains them) but have NO
registered controlled runner anywhere in
app.verification.build_default_registry() (RUNNER_MAP marks them
"deferred"). Recognition/name-mapping alone was therefore silently
treated as capability proof, and PlatformIO's OWN `has_untrusted_hooks`
flag (which the ACTUAL VerificationStep policy in
build_verification_plan() already respects) was not consulted at all in
the trust computation, so an untrusted-hooks PlatformIO project could
still be trusted.

Fix: `trusted_verification_identity_groups()` now only emits a group
when the underlying RUNNER_MAP/BUILD_RUNNER_MAP entry's policy is
exactly "controlled_execution" (reusing that map's OWN policy field --
never a second, competing notion of "controllable"), and PlatformIO
firmware trust additionally requires `DetectedFirmware.has_untrusted_
hooks is False` (fail-closed on an unreadable/missing flag). Also closes
a SEPARATE malformed-state gap: `ToolchainItem.state` was checked as
`!= "unavailable"` (a negative denylist) rather than membership in a
POSITIVE allowlist of the only states the Chairman/Phase-1 prompt schema
documents -- so a hallucinated/garbage state value silently passed as
"controllable". `_CONTROLLABLE_TOOLCHAIN_STATES` closes that.

RED-before-fix evidence: every FAIL test below (mandatory cases 1-5)
passed unmodified pre-014C code -- i.e. FAILED to reject -- because
`trusted_verification_identity_groups()` ignored policy entirely and
`_verification_coverage_is_compatible()` only excluded the literal
string "unavailable" (confirmed before implementing the policy filter
and the state allowlist; see the completion report, R6).

S2.3 still never executes S5 verification -- app.engineering_decision
never imports app.verification; the caller (app.dev_workflow,
app.engineering_council) computes trusted_verification_groups and
passes it in as plain data (see TestS2_3StillDoesNotExecute below).
"""
import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem, VerificationCoverage
from app.engineering_decision import validate_candidates
from app.project_intelligence import DetectedFirmware, ProjectIntelligence
from app.verification import trusted_verification_identity_groups

from tests.test_engineering_decision import (
    _binding_preflight,
    _pip_item,
    _requirement_needing_verification,
)


def _controlled_item(req_id, technical_identity, mechanism, state="needs_install"):
    return ToolchainItem(
        requirement_ref=req_id, name=technical_identity, type="executable",
        technical_identity=technical_identity, provides_verification=(mechanism,),
        state=state,
    )


class TestCase1CtestRecognizedButDeferredFails:
    """1: ctest recognized (RUNNER_MAP contains it) but its route is
    "deferred" -- no registered controlled runner -- FAIL."""

    def test_ctest_recognized_but_no_controlled_runner_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "ctest", "ctest")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="ctest", evidence="ctest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        trusted = trusted_verification_identity_groups(
            {"test_systems": ["ctest"], "build_systems": [], "firmware_indicators": []},
        )
        assert trusted == (), "ctest must never be trusted -- RUNNER_MAP marks it deferred"
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is False


class TestCase2JestRecognizedButNoControlledRunnerFails:
    """2: jest recognized but no controlled runner -- FAIL."""

    def test_jest_recognized_but_no_controlled_runner_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "jest", "jest")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="jest", evidence="jest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        trusted = trusted_verification_identity_groups(
            {"test_systems": ["jest"], "build_systems": [], "firmware_indicators": []},
        )
        assert trusted == (), "jest must never be trusted -- RUNNER_MAP marks it deferred"
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is False

    @pytest.mark.parametrize("name", ["vitest", "mocha", "make"])
    def test_every_other_deferred_name_is_also_never_trusted(self, name):
        trusted = trusted_verification_identity_groups(
            {"test_systems": [name], "build_systems": [name], "firmware_indicators": []},
        )
        assert trusted == (), name


class TestCase3PlatformIOUntrustedHooksFails:
    """3: PlatformIO with untrusted build-code hooks -- S5's OWN policy
    is "unsupported" for this exact shape (see
    app.verification.build_verification_plan()'s firmware branch) -- the
    trust computation must agree, not silently trust it anyway."""

    def test_platformio_with_untrusted_hooks_is_never_trusted(self):
        intelligence = ProjectIntelligence(
            project_root="/tmp/proj", project_kind="existing", areas=(),
            languages=(), frameworks=(), package_systems=(),
            build_systems=(), test_systems=(),
            firmware_indicators=(
                DetectedFirmware("platformio", (), has_untrusted_hooks=True),
            ),
            ci_indicators=(), doc_indicators=(),
            git_repository_present=True, sensitive_configuration_present=False,
            warnings=(), truncated=False, total_files_traversed=1,
            total_files_excluded=0, inspection_limit_exceeded=False,
        )
        trusted = trusted_verification_identity_groups(intelligence)
        assert trusted == ()

    def test_platformio_end_to_end_stays_inadmissible_with_untrusted_hooks(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "platformio", "platformio")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="platformio", evidence="platformio",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        intelligence = ProjectIntelligence(
            project_root="/tmp/proj", project_kind="existing", areas=(),
            languages=(), frameworks=(), package_systems=(),
            build_systems=(), test_systems=(),
            firmware_indicators=(
                DetectedFirmware("platformio", (), has_untrusted_hooks=True),
            ),
            ci_indicators=(), doc_indicators=(),
            git_repository_present=True, sensitive_configuration_present=False,
            warnings=(), truncated=False, total_files_traversed=1,
            total_files_excluded=0, inspection_limit_exceeded=False,
        )
        trusted = trusted_verification_identity_groups(intelligence)
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is False

    def test_platformio_without_untrusted_hooks_is_trusted(self):
        """Confirms the fix is a real gate, not a blanket PlatformIO ban:
        the SAME firmware indicator, with has_untrusted_hooks=False, IS
        trusted -- matching S5's own build_verification_plan() policy."""
        intelligence = ProjectIntelligence(
            project_root="/tmp/proj", project_kind="existing", areas=(),
            languages=(), frameworks=(), package_systems=(),
            build_systems=(), test_systems=(),
            firmware_indicators=(
                DetectedFirmware("platformio", (), has_untrusted_hooks=False),
            ),
            ci_indicators=(), doc_indicators=(),
            git_repository_present=True, sensitive_configuration_present=False,
            warnings=(), truncated=False, total_files_traversed=1,
            total_files_excluded=0, inspection_limit_exceeded=False,
        )
        trusted = trusted_verification_identity_groups(intelligence)
        assert any("platformio" in group.identities for group in trusted)

    def test_dict_summary_shape_never_trusts_platformio_at_all(self):
        """The dict summary (CouncilInput.project_intelligence) LOSES
        has_untrusted_hooks entirely -- fail-closed means PlatformIO can
        never be trusted from that lossy shape, regardless of what name
        list it carries."""
        trusted = trusted_verification_identity_groups(
            {"test_systems": [], "build_systems": ["platformio"], "firmware_indicators": ["platformio"]},
        )
        assert not any("platformio" in group.identities for group in trusted)


class TestCase4MalformedStateFailsClosed:
    """4: a malformed/unknown ToolchainItem.state such as "garbage" --
    FAIL CLOSED, not silently treated as controllable."""

    @pytest.mark.parametrize("state", ["garbage", "installed", "unknown", "", "Needs_Install"])
    def test_malformed_state_fails_closed(self, state):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "pytest", "pytest", state=state)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        trusted = trusted_verification_identity_groups(
            {"test_systems": ["pytest"], "build_systems": [], "firmware_indicators": []},
        )
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is False, state


class TestCase5StateAloneNeverProvesCapability:
    """5: state != "unavailable" alone MUST NOT prove capability -- a
    genuinely valid state ("needs_install") on an UNTRUSTED identity
    still fails."""

    def test_needs_install_state_without_trusted_evidence_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "totally-untrusted", "pytest", state="needs_install")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="totally-untrusted",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        # Even granting trust for an UNRELATED identity -- proving the
        # failure is about THIS identity's lack of trust, not merely an
        # absent trusted_verification_groups argument.
        trusted = trusted_verification_identity_groups(
            {"test_systems": ["pytest"], "build_systems": [], "firmware_indicators": []},
        )
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is False


class TestCase6LegitimatePytestControlledRoutePasses:
    """6: legitimate pytest with an actual controlled, applicable route
    -- PASS."""

    def test_pytest_with_real_controlled_route_passes(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "pytest", "pytest")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        trusted = trusted_verification_identity_groups(
            {"test_systems": ["pytest"], "build_systems": [], "firmware_indicators": []},
        )
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is True


class TestCase7SupportedRoutesOnlyWhenControllable:
    """7: legitimate supported ESPHome/PlatformIO/CMake routes pass only
    when the actual ADC capability contract (RUNNER_MAP/
    FIRMWARE_RUNNER_MAP policy, has_untrusted_hooks) says
    controllable/applicable -- proven across all three."""

    def test_esphome_passes(self):
        req = _requirement_needing_verification("req-esphome-fw")
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "esphome", "esphome_check")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_check", evidence="esphome",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        trusted = trusted_verification_identity_groups(
            {"test_systems": [], "build_systems": [], "firmware_indicators": ["esphome"]},
        )
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is True

    def test_platformio_passes_only_when_hooks_are_trusted(self):
        req = _requirement_needing_verification("req-pio-fw")
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "platformio", "platformio")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="platformio", evidence="platformio",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        intelligence = ProjectIntelligence(
            project_root="/tmp/proj", project_kind="existing", areas=(),
            languages=(), frameworks=(), package_systems=(),
            build_systems=(), test_systems=(),
            firmware_indicators=(DetectedFirmware("platformio", (), has_untrusted_hooks=False),),
            ci_indicators=(), doc_indicators=(),
            git_repository_present=True, sensitive_configuration_present=False,
            warnings=(), truncated=False, total_files_traversed=1,
            total_files_excluded=0, inspection_limit_exceeded=False,
        )
        trusted = trusted_verification_identity_groups(intelligence)
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is True

    def test_cmake_passes(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "cmake", "cmake")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="cmake", evidence="cmake",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        trusted = trusted_verification_identity_groups(
            {"test_systems": [], "build_systems": ["cmake"], "firmware_indicators": []},
        )
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is True


class TestCase8CorrectIdentityWrongScopeFails:
    """8: correct capability identity but wrong project area/scope --
    FAIL. A candidate claiming "pytest" when Project Intelligence's
    trusted evidence is scoped to a DIFFERENT project/run (an empty or
    unrelated evidence set) must not inherit trust from elsewhere."""

    def test_pytest_claim_with_evidence_scoped_to_a_different_project_fails(self):
        req = _requirement_needing_verification()
        preflight = _binding_preflight(req)
        item = _controlled_item(req.id, "pytest", "pytest")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, _pip_item(req.id)),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="test_command",
                mechanism="pytest", evidence="pytest",
            ),),
        )
        result = CouncilResult(id="c1", project_id="proj", variants=(variant,),
                                recommendation="v1", council_complete=True)
        # Trust scoped to a DIFFERENT capability entirely (cmake) --
        # simulating evidence from the wrong project/area/scope.
        trusted = trusted_verification_identity_groups(
            {"test_systems": [], "build_systems": ["cmake"], "firmware_indicators": []},
        )
        validations = validate_candidates(result, preflight=preflight, trusted_verification_groups=trusted)
        assert validations[0].admissible is False


class TestS2_3StillDoesNotExecute:
    def test_no_app_verification_import_and_no_subprocess(self):
        import inspect
        import app.engineering_decision as ed_module
        source = inspect.getsource(ed_module)
        assert "subprocess" not in source
        assert "app.verification" not in source
        assert "app.testing_stage" not in source
