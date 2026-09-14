"""CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-FIX-002: replaces the
previously-accepted CLAUDE-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-001
implementation, which independent review (CDX-ADC-S23-VERIFICATION-
EVIDENCE-ARCHITECTURE-REVIEW-001) correctly rejected.

The rejected architecture treated Python distributions genuinely present
in ADC's OWN CONTROLLER PROCESS's environment
(`importlib.metadata.distributions()`, read from the running ADC process
itself) as `PROJECT_GLOBAL_SCOPE` "trusted evidence" that could
corroborate a candidate's `pip_show` verification claim
(`app.verification.installed_python_package_identity_groups()`, now
deleted). That is invalid: the controller process's own Python
environment is not, and is never provably, the SAME environment/
interpreter a candidate's install would actually target -- a package
being importable by ADC itself proves nothing about presence in a
different host interpreter or an isolated project venv, and the review
additionally found a role-ambiguity defect in how that evidence was
represented (`frozenset({distribution_name, "pip_show"})` let the fixed
mechanism token be mistaken for a package identity, or vice versa, for
any distribution that happened to literally be named "pip_show").

CORRECTED ARCHITECTURE:

  1. PRE-INSTALL trusted verification CAPABILITY (S2.3, this file's main
     subject): for `VerificationCoverage.mechanism ==
     app.verification.PACKAGE_PRESENCE_MECHANISM` ("pip_show"),
     `app.engineering_decision._python_package_verification_capability()`
     proves -- from the candidate's OWN item fields checked against
     ADC's fixed, non-candidate-authored rules, never from anything
     genuinely external -- that installing the item would materialize
     into a controlled "install" SetupStep
     (`ToolchainMaterializer.classify_item()`, unchanged) whose executor
     (`PythonPackageExecutor`, unchanged) is STATICALLY known to bind
     post-install verification to the SAME target executable used for
     installation. It never claims, and never needs, proof that the
     package already exists anywhere -- not in ADC's controller process,
     not on the host, not in any venv. This mechanism is corroborated
     ENTIRELY OUTSIDE `trusted_groups` now -- `installed_python_package_
     identity_groups()` is gone, and `all_trusted_verification_groups()`
     is a plain passthrough to the pre-existing, file-based
     `trusted_verification_identity_groups()`.

  2. POST-INSTALL presence proof (S3 execution, unchanged by this fix):
     `app.python_package_executor.PythonPackageExecutor.execute()`
     resolves exactly one target Python executable
     (`SetupStep.target_executable`, stamped by RequirementPreflight)
     and uses that SAME executable for both the pip install and the
     post-install distribution-metadata verification
     (`_run_verification()`). This file's Greenfield/cross-environment
     classes exercise that boundary directly (via injected, deterministic
     test doubles -- no real installs, no network calls).

This file supersedes every test in the prior version wholesale (they
asserted the exact behavior this fix removes); nothing here imports the
deleted `installed_python_package_identity_groups()`.
"""
from __future__ import annotations

from dataclasses import replace
import venv

import pytest

from app.council_models import CouncilResult, CouncilVariant, ToolchainItem, VerificationCoverage
from app.engineering_decision import select_engineering_variant, validate_candidates
from app.python_distribution import (
    environment_target_matches,
    parse_pip_show_requirement,
    resolve_environment_python_target,
    resolve_target_python_executable,
)
from app.python_package_executor import CommandResult, PythonPackageExecutor
from app.requirement_model import (
    PreflightRequirementResult,
    PreflightResult,
    Requirement,
    RequirementActivation,
    RequirementType,
    SetupStep,
)
from app.requirement_preflight import RequirementPreflight
from app.toolchain_materializer import ToolchainMaterializer
from app.verification import (
    PACKAGE_PRESENCE_MECHANISM,
    PROJECT_GLOBAL_SCOPE,
    TrustedVerificationGroup,
    all_trusted_verification_groups,
)

from tests.test_engineering_decision import _requirement_needing_verification


# ---------------------------------------------------------------------------
# Shared fixtures
#
# `requirement.name` and each item's `technical_identity` are always kept
# in lockstep below (both default to "acme-widgets") -- CLAUDE-ARCH-S2-
# 014C's binding-requirement semantic match
# (`_toolchain_item_matches_requirement_semantics()`) independently
# requires PEP-503 identity equivalence between the two, and this file's
# subject is verification-CAPABILITY admissibility, not that unrelated,
# already-covered binding-coverage contract -- so every scenario isolates
# the one dimension it actually tests.
# ---------------------------------------------------------------------------

def _requirement(req_id="req-pkg", name="acme-widgets"):
    return Requirement(
        id=req_id, name=name, type=RequirementType.PYTHON_PACKAGE,
        purpose="test dependency", required=True, confidence=0.9,
        verification_method=f"pip show {name}",
    )


def _binding_preflight(requirement, *, target_executable=None):
    return PreflightResult(
        id="pre-1", project_id="proj", overall_ready=False,
        results=(
            PreflightRequirementResult(
                requirement_id=requirement.id, present=False, satisfied=False,
                active=True, blocks_current_operation=True,
                target_executable=target_executable,
            ),
        ),
        missing_requirements=(requirement,),
        activations=(RequirementActivation(requirement.id, True, True),),
    )


def _package_item(
    req_id: str, technical_identity: str = "acme-widgets", *,
    item_type: str = RequirementType.PYTHON_PACKAGE,
    install_method: str | None = "pip",
    mechanism: str = PACKAGE_PRESENCE_MECHANISM,
    state: str = "needs_install",
) -> ToolchainItem:
    """A zero-file Greenfield python_package candidate item: a valid,
    exact technical_identity, a controlled, already-accepted
    install_method, self-declaring `mechanism` as a capability it
    supports -- exactly the shape a self-certifying LLM candidate would
    produce."""
    return ToolchainItem(
        requirement_ref=req_id, name=technical_identity, type=item_type,
        technical_identity=technical_identity, install_method=install_method,
        state=state, provides_verification=(mechanism,),
    )


def _package_variant(
    req_id: str, technical_identity: str = "acme-widgets", *,
    item_type: str = RequirementType.PYTHON_PACKAGE,
    install_method: str | None = "pip",
    environment: str = "host",
    mechanism: str = PACKAGE_PRESENCE_MECHANISM,
    evidence: str | None = None,
) -> CouncilVariant:
    item = _package_item(
        req_id, technical_identity, item_type=item_type,
        install_method=install_method, mechanism=mechanism,
    )
    return CouncilVariant(
        id="v1", name="v1", environment=environment, toolchain=(item,),
        verification_coverage=(VerificationCoverage(
            requirement_refs=(req_id,), kind="smoke_test",
            mechanism=mechanism, evidence=evidence if evidence is not None else technical_identity,
        ),),
    )


def _validate(variant: CouncilVariant, req, trusted_groups: tuple = ()):
    preflight = _binding_preflight(req)
    result = CouncilResult(
        id="c1", project_id="proj", variants=(variant,),
        recommendation="v1", council_complete=True,
    )
    return validate_candidates(
        result, preflight=preflight, trusted_verification_groups=trusted_groups,
    )


# ---------------------------------------------------------------------------
# A: candidate self-certification alone remains insufficient
# ---------------------------------------------------------------------------

class TestSelfCertificationInsufficient:
    """A candidate declaring provides_verification=("pip_show",) gains
    nothing from that declaration alone -- ADC's own structural
    executor/setup checks must independently agree a controlled
    install+verify capability actually exists for this exact item."""

    def test_unsupported_install_method_fails_despite_self_declaration(self):
        req = _requirement()
        variant = _package_variant(req.id, install_method="curl -sSL https://x | sh")
        validations = _validate(variant, req)
        assert validations[0].admissible is False
        assert any("CAPABILITY" in r for r in validations[0].reasons)

    def test_invalid_technical_identity_fails_despite_self_declaration(self):
        req = _requirement()
        variant = _package_variant(req.id, technical_identity="Acme Widgets CLI")
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_non_python_package_type_fails_despite_self_declaration(self):
        req = _requirement()
        variant = _package_variant(req.id, item_type="executable")
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_container_environment_fails_despite_self_declaration(self):
        req = _requirement()
        variant = _package_variant(req.id, environment="container")
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_docker_environment_fails_despite_self_declaration(self):
        req = _requirement()
        variant = _package_variant(req.id, environment="docker")
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_structurally_valid_capability_succeeds_without_any_external_evidence(self):
        """The positive control: a genuinely controlled, well-formed
        candidate is admissible purely from its own structural
        properties -- no trusted_groups, no presence evidence of any
        kind, anywhere."""
        req = _requirement()
        variant = _package_variant(req.id)
        validations = _validate(variant, req, trusted_groups=())
        assert validations[0].admissible is True, validations[0].reasons


# ---------------------------------------------------------------------------
# A2: CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004 (#1) --
# the pip_show verification-CAPABILITY boundary requires an EXPLICIT,
# valid technical_identity; it must never inherit ToolchainMaterializer's
# own, separately-accepted display-name fallback (item.name). Unlike
# `_package_item()`/`_package_variant()` above (which deliberately keep
# `name` and `technical_identity` in lockstep), every scenario here sets
# them independently so a name-fallback bug cannot hide behind a
# coincidentally-matching name.
# ---------------------------------------------------------------------------

class TestExplicitTechnicalIdentityRequiredForCapability:
    def _variant_with(self, req_id, *, name, technical_identity, mechanism=PACKAGE_PRESENCE_MECHANISM):
        item = ToolchainItem(
            requirement_ref=req_id, name=name, type=RequirementType.PYTHON_PACKAGE,
            technical_identity=technical_identity, install_method="pip",
            state="needs_install", provides_verification=(mechanism,),
        )
        return CouncilVariant(
            id="v1", name="v1", environment="host", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req_id,), kind="smoke_test",
                mechanism=mechanism, evidence=name,
            ),),
        )

    def test_missing_technical_identity_with_valid_looking_name_is_inadmissible(self):
        """technical_identity=None, name="acme-widgets" (itself a
        perfectly valid-looking distribution identifier), verification=
        "pip show acme-widgets" -- must NOT establish capability merely
        because ToolchainMaterializer's OWN, unrelated install-step
        fallback would have accepted item.name as the package identity."""
        req = _requirement(name="acme-widgets")
        variant = self._variant_with(req.id, name="acme-widgets", technical_identity=None)
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_invalid_technical_identity_with_valid_looking_name_is_inadmissible(self):
        """An invalid (free-form) technical_identity must be rejected
        even when item.name independently happens to be a valid-looking
        distribution identifier -- the display-name fallback must never
        be consulted for this trust decision at all, regardless of
        which field it would have picked."""
        req = _requirement(name="acme-widgets")
        variant = self._variant_with(
            req.id, name="acme-widgets", technical_identity="Acme Widgets CLI",
        )
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_explicit_valid_technical_identity_is_admissible(self):
        """The positive control: an explicit, valid technical_identity
        (PEP-503-equivalent to the requirement's own verification_method
        distribution) establishes capability on its own merits, entirely
        independent of item.name."""
        req = _requirement(name="acme-widgets")
        variant = self._variant_with(
            req.id, name="Acme Widgets CLI", technical_identity="acme_widgets",
        )
        validations = _validate(variant, req)
        assert validations[0].admissible is True, validations[0].reasons


# ---------------------------------------------------------------------------
# B: no PROJECT_GLOBAL / controller-environment evidence leakage
# ---------------------------------------------------------------------------

class TestNoProjectGlobalPackagePresenceLeakage:
    """Even a maximally adversarial, contaminated trusted_groups tuple
    (mimicking exactly what the REMOVED installed_python_package_
    identity_groups() producer used to generate) must have zero effect
    on pip_show admissibility -- it is never consulted at all."""

    def test_contaminated_group_does_not_rescue_a_structurally_invalid_item(self):
        req = _requirement()
        variant = _package_variant(req.id, install_method="curl -sSL https://x | sh")
        # A group shaped exactly like the deleted producer's output: the
        # candidate's own exact technical_identity, PLUS the mechanism
        # token, both members of one unordered set, scoped project-wide.
        contaminated = (
            TrustedVerificationGroup(
                frozenset({"acme-widgets", PACKAGE_PRESENCE_MECHANISM}), PROJECT_GLOBAL_SCOPE,
            ),
        )
        without = _validate(variant, req, trusted_groups=())
        with_contaminated = _validate(variant, req, trusted_groups=contaminated)
        assert without[0].admissible is False
        assert with_contaminated[0].admissible is False

    def test_contaminated_group_has_no_effect_on_a_structurally_valid_item(self):
        req = _requirement()
        variant = _package_variant(req.id)
        contaminated = (
            TrustedVerificationGroup(
                frozenset({"acme-widgets", PACKAGE_PRESENCE_MECHANISM}), PROJECT_GLOBAL_SCOPE,
            ),
        )
        without = _validate(variant, req, trusted_groups=())
        with_contaminated = _validate(variant, req, trusted_groups=contaminated)
        assert without[0].admissible is True, without[0].reasons
        assert with_contaminated[0].admissible is True, with_contaminated[0].reasons
        assert without[0].admissible == with_contaminated[0].admissible


# ---------------------------------------------------------------------------
# C: package identity / mechanism role collision closed
# ---------------------------------------------------------------------------

class TestPackageIdentityMechanismRoleCollisionClosed:
    """CDX-ADC-S23-VERIFICATION-EVIDENCE-ARCHITECTURE-REVIEW-001's role-
    ambiguity finding: an installed distribution named "requests" must
    never corroborate a candidate whose OWN package identity happens to
    be the literal string "pip_show" merely because both the (removed)
    evidence group and the candidate's mechanism token were "pip_show".
    A real distribution literally named "pip_show"/"pip-show" must still
    be handled correctly, with no cross-role ambiguity."""

    def test_requests_evidence_cannot_corroborate_identity_pip_show(self):
        req = _requirement(name="pip_show")
        # The candidate's OWN package identity is literally "pip_show",
        # but its install_method is NOT one ADC's controlled executor
        # recognizes -- so it has no real capability on its own.
        variant = _package_variant(
            req.id, technical_identity="pip_show",
            install_method="pip-compile requirements.in",
        )
        # The exact shape the deleted producer would have built from an
        # environment where "requests" is installed: a group whose
        # unordered identity set contains BOTH "requests" and the fixed
        # mechanism token "pip_show" -- the old role-ambiguity defect
        # would let item_identity="pip_show" match this group by pure
        # set membership.
        old_style_requests_group = (
            TrustedVerificationGroup(
                frozenset({"requests", PACKAGE_PRESENCE_MECHANISM}), PROJECT_GLOBAL_SCOPE,
            ),
        )
        validations = _validate(variant, req, trusted_groups=old_style_requests_group)
        assert validations[0].admissible is False

    def test_real_distribution_literally_named_pip_show_admitted_on_its_own_merits(self):
        req = _requirement(name="pip_show")
        variant = _package_variant(req.id, technical_identity="pip_show", install_method="pip")
        validations = _validate(variant, req, trusted_groups=())
        assert validations[0].admissible is True, validations[0].reasons

    def test_real_distribution_literally_named_pip_dash_show_admitted_on_its_own_merits(self):
        req = _requirement(name="pip-show")
        variant = _package_variant(req.id, technical_identity="pip-show", install_method="pip install pip-show")
        validations = _validate(variant, req, trusted_groups=())
        assert validations[0].admissible is True, validations[0].reasons


# ---------------------------------------------------------------------------
# D: mechanism matching stays byte-exact; PEP 503 never applies to it
# ---------------------------------------------------------------------------

class TestMechanismByteExactPep503NeverAppliesToIt:
    def test_near_miss_mechanism_capitalization_is_rejected(self):
        req = _requirement()
        item = _package_item(req.id, mechanism=PACKAGE_PRESENCE_MECHANISM)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="smoke_test",
                mechanism="Pip_Show", evidence="acme-widgets",
            ),),
        )
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_pep503_equivalent_install_method_spelling_still_resolves_capability(self):
        """Package IDENTITY matching (install_method <-> technical_identity,
        an existing, unrelated contract -- is_supported_python_package_
        install_method()) legitimately uses PEP 503 equivalence; this is
        never mechanism matching, which stays byte-exact (see above)."""
        req = _requirement()
        variant = _package_variant(
            req.id, technical_identity="acme_widgets",
            install_method="pip install acme-widgets",
        )
        validations = _validate(variant, req)
        assert validations[0].admissible is True, validations[0].reasons


# ---------------------------------------------------------------------------
# E: true zero-file Greenfield, initially-absent package, end to end
# ---------------------------------------------------------------------------

class _RecordingRunner:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[list[str]] = []

    def run(self, args):
        self.calls.append(args)
        return CommandResult(self.returncode, self.stdout, self.stderr)


class _TargetBoundVerifier:
    """A deterministic fake post-install verifier that reports package
    presence keyed by the EXACT target executable it is asked about --
    proving PythonPackageExecutor's verification is bound to whichever
    target the SetupStep actually names, never to any other environment
    (ADC's own controller process included)."""

    def __init__(self, present_on: dict[str, set[str]]):
        self._present_on = present_on
        self.calls: list[tuple] = []

    def __call__(self, step: SetupStep) -> bool:
        self.calls.append((step.target_executable, step.package))
        return step.package in self._present_on.get(step.target_executable, set())


class TestGreenfieldPackagePresenceArchitecture:
    """The actual, previously-missing productive path: a true zero-file
    Greenfield project, a required python_package absent from the target,
    a controlled install_method, and a pip_show verification requirement.

    A. Candidate needs no package-presence evidence before installation.
    B. S2.3 accepts purely on capability.
    C. Selection proceeds.
    D. The exact target executable/environment is resolved (Preflight).
    E. Controlled installation is represented through a deterministic
       fake of the existing safe execution boundary.
    F. Post-install verification runs against the SAME target.
    G. Success completes the path.
    H. A failed post-install check fails closed (never claimed
       "already installed").
    """

    TARGET = "/fake/greenfield-project/.venv/bin/python"

    def _zero_file_project_intelligence(self):
        return None  # exactly what a true zero-file inspection carries through here

    def test_a_and_b_capability_accepted_without_presence_evidence(self):
        req = _requirement()
        variant = _package_variant(req.id)
        trusted_groups = all_trusted_verification_groups(self._zero_file_project_intelligence())
        assert trusted_groups == ()  # zero file evidence -- nothing to leak
        validations = _validate(variant, req, trusted_groups=trusted_groups)
        assert validations[0].admissible is True, validations[0].reasons

    def test_c_through_g_same_target_install_and_verify_succeeds(self):
        req = _requirement()
        variant = _package_variant(req.id)
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        preflight = _binding_preflight(req, target_executable=self.TARGET)

        decision = select_engineering_variant(
            result, preflight,
            trusted_verification_groups=all_trusted_verification_groups(
                self._zero_file_project_intelligence(),
            ),
        )
        assert decision.variant.id == "v1"

        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight)
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.action == "install"
        assert step.package == "acme-widgets"
        assert step.target_executable == self.TARGET  # D: exact target resolved

        approved_step = replace(step, is_approved=True)
        runner = _RecordingRunner(returncode=0)
        verifier = _TargetBoundVerifier(present_on={self.TARGET: {"acme-widgets"}})
        executor = PythonPackageExecutor(runner=runner, verifier=verifier)

        execution_result = executor.execute(approved_step)

        assert runner.calls == [[self.TARGET, "-m", "pip", "install", "acme-widgets"]]
        assert verifier.calls == [(self.TARGET, "acme-widgets")]
        assert execution_result.success is True
        assert execution_result.verification_passed is True

    def test_h_post_install_verification_absent_fails_closed(self):
        req = _requirement()
        variant = _package_variant(req.id)
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        preflight = _binding_preflight(req, target_executable=self.TARGET)
        decision = select_engineering_variant(
            result, preflight,
            trusted_verification_groups=all_trusted_verification_groups(
                self._zero_file_project_intelligence(),
            ),
        )
        plan = ToolchainMaterializer().materialize_decision(decision, "proj", preflight)
        approved_step = replace(plan.steps[0], is_approved=True)

        runner = _RecordingRunner(returncode=0)
        # The target still reports the package absent after "install" --
        # never monkeypatched to "already installed", never fed fake
        # Project Intelligence evidence.
        verifier = _TargetBoundVerifier(present_on={self.TARGET: set()})
        executor = PythonPackageExecutor(runner=runner, verifier=verifier)

        execution_result = executor.execute(approved_step)

        assert execution_result.success is False
        assert execution_result.verification_passed is False


# ---------------------------------------------------------------------------
# F: cross-environment negatives
# ---------------------------------------------------------------------------

class TestCrossEnvironmentNegatives:
    """Presence bound to one target/environment must never corroborate a
    different one -- proven at the real execution boundary
    (PythonPackageExecutor), which is the only place presence is ever
    checked now."""

    def test_a_package_present_in_controller_process_absent_in_different_target(self):
        # Precondition: "pytest" is genuinely importable in THIS
        # process's own environment -- ADC's controller, in this test's
        # analogy -- proving the negative is not merely vacuous.
        from importlib import metadata as _metadata
        _metadata.version("pytest")

        target = "/fake/host-interpreter/bin/python"
        runner = _RecordingRunner(returncode=0)
        verifier = _TargetBoundVerifier(present_on={})  # absent everywhere but the controller
        executor = PythonPackageExecutor(runner=runner, verifier=verifier)
        step = SetupStep(
            id="step-1", requirement_id="req-1", action="install",
            install_method="pip", package="pytest", is_approved=True,
            target_executable=target,
        )

        execution_result = executor.execute(step)

        assert verifier.calls == [(target, "pytest")]
        assert execution_result.success is False

    def test_b_package_present_on_host_absent_in_isolated_project_venv(self):
        host = "/fake/host/bin/python"
        venv = "/fake/project/.venv/bin/python"
        runner = _RecordingRunner(returncode=0)
        verifier = _TargetBoundVerifier(present_on={host: {"acme-widgets"}})
        executor = PythonPackageExecutor(runner=runner, verifier=verifier)
        step = SetupStep(
            id="step-1", requirement_id="req-1", action="install",
            install_method="pip", package="acme-widgets", is_approved=True,
            target_executable=venv,
        )

        execution_result = executor.execute(step)

        assert verifier.calls == [(venv, "acme-widgets")]
        assert execution_result.success is False

    def test_c_container_environment_candidate_has_no_controlled_support(self):
        req = _requirement()
        variant = _package_variant(req.id, environment="container")
        validations = _validate(variant, req)
        assert validations[0].admissible is False
        assert any(
            "CAPABILITY" in r or "container" in r.lower()
            for r in validations[0].reasons
        )

    def test_d_capability_bound_to_target_a_cannot_verify_target_b(self):
        target_a = "/fake/target-a/bin/python"
        target_b = "/fake/target-b/bin/python"
        runner = _RecordingRunner(returncode=0)
        verifier = _TargetBoundVerifier(present_on={target_a: {"acme-widgets"}})
        executor = PythonPackageExecutor(runner=runner, verifier=verifier)
        step = SetupStep(
            id="step-1", requirement_id="req-1", action="install",
            install_method="pip", package="acme-widgets", is_approved=True,
            target_executable=target_b,
        )

        execution_result = executor.execute(step)

        assert verifier.calls == [(target_b, "acme-widgets")]
        assert execution_result.success is False


# ---------------------------------------------------------------------------
# G: existing trust paths (esphome_validate) remain unaffected
# ---------------------------------------------------------------------------

class TestExistingEsphomeValidatePathUnaffected:
    """The independent esphome_validate/firmware-indicator verification
    category (CLAUDE-ARCH-S2-014E) is untouched by this fix -- it never
    used the removed package-presence evidence source, and does not use
    the new item-scoped python-package capability path either."""

    def test_esphome_validate_still_requires_firmware_indicator_evidence(self):
        from app.verification import trusted_verification_identity_groups

        req = _requirement_needing_verification("req-esphome-fw")
        preflight = _binding_preflight(req)
        item = ToolchainItem(
            requirement_ref=req.id, name="esphome", type="executable",
            technical_identity="esphome", provides_verification=("esphome_validate",),
            state="needs_install",
        )
        pip_item = _package_item(req.id, "esphome")
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item, pip_item),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="build_command",
                mechanism="esphome_validate", evidence="esphome",
            ),),
        )
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False

        intelligence = {"firmware_indicators": ["esphome"]}
        validations = validate_candidates(
            result, preflight=preflight,
            trusted_verification_groups=trusted_verification_identity_groups(intelligence),
        )
        assert validations[0].admissible is True, validations[0].reasons


# ---------------------------------------------------------------------------
# H: CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003
# identity binding -- the requirement's own verification_method must name
# the SAME Python distribution as the selected package item
# ---------------------------------------------------------------------------

class TestIdentityBindingToTechnicalIdentity:
    def test_esphome_identity_rejects_requests_requirement(self):
        req = Requirement(
            id="req-a", name="esphome", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
            verification_method="pip show requests",
        )
        variant = _package_variant(req.id, technical_identity="esphome")
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_requests_identity_rejects_esphome_requirement(self):
        req = Requirement(
            id="req-a", name="requests", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
            verification_method="pip show esphome",
        )
        variant = _package_variant(req.id, technical_identity="requests")
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_pep503_equivalent_spelling_is_valid(self):
        req = Requirement(
            id="req-a", name="acme-widgets", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
            verification_method="pip show Acme_Widgets",
        )
        variant = _package_variant(req.id, technical_identity="acme-widgets")
        validations = _validate(variant, req)
        assert validations[0].admissible is True, validations[0].reasons

    def test_no_verification_method_at_all_never_establishes_capability(self):
        req = Requirement(
            id="req-a", name="acme-widgets", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
        )
        variant = _package_variant(req.id)
        preflight = _binding_preflight(req)
        from app.engineering_decision import _python_package_verification_capability
        item = variant.toolchain[0]
        assert _python_package_verification_capability(item, variant, preflight) is False


# ---------------------------------------------------------------------------
# H2: CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004 (#2) --
# every requirement_ref a pip_show coverage entry claims to cover must be
# proven independently, against the item that actually claims THAT ref,
# never inherited from a sibling ref riding alongside it in the same
# entry.
# ---------------------------------------------------------------------------

class TestPerRequirementIndependentBinding:
    @staticmethod
    def _two_requirement_preflight(req_a, req_b):
        return PreflightResult(
            id="pre-2", project_id="proj", overall_ready=False,
            results=(
                PreflightRequirementResult(
                    requirement_id=req_a.id, present=False, satisfied=False,
                    active=True, blocks_current_operation=True,
                ),
                PreflightRequirementResult(
                    requirement_id=req_b.id, present=False, satisfied=False,
                    active=True, blocks_current_operation=True,
                ),
            ),
            missing_requirements=(req_a, req_b),
            activations=(
                RequirementActivation(req_a.id, True, True),
                RequirementActivation(req_b.id, True, True),
            ),
        )

    @staticmethod
    def _item(req_id, technical_identity):
        return ToolchainItem(
            requirement_ref=req_id, name=technical_identity,
            type=RequirementType.PYTHON_PACKAGE,
            technical_identity=technical_identity, install_method="pip",
            state="needs_install", provides_verification=(PACKAGE_PRESENCE_MECHANISM,),
        )

    def test_one_incompatible_requirement_does_not_ride_along_with_a_compatible_one(self):
        """Requirement A (package acme-widgets, 'pip show acme-widgets')
        genuinely matches its own item; Requirement B (package requests,
        'pip show esphome') does not match its own item at all. One
        coverage entry referencing both must NOT make the candidate
        fully admissible -- Requirement A's own compatibility must never
        corroborate Requirement B."""
        req_a = Requirement(
            id="req-a", name="acme-widgets", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
            verification_method="pip show acme-widgets",
        )
        req_b = Requirement(
            id="req-b", name="requests", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
            verification_method="pip show esphome",
        )
        item_a = self._item(req_a.id, "acme-widgets")
        item_b = self._item(req_b.id, "requests")
        variant = CouncilVariant(
            id="v1", name="v1", environment="host", toolchain=(item_a, item_b),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req_a.id, req_b.id), kind="smoke_test",
                mechanism=PACKAGE_PRESENCE_MECHANISM, evidence="acme-widgets",
            ),),
        )
        preflight = self._two_requirement_preflight(req_a, req_b)
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is False
        assert any("req-b" in reason for reason in validations[0].reasons)

    def test_two_independently_valid_requirements_in_one_entry_both_pass(self):
        """Both requirements independently match their own claiming
        item's technical identity -- a legitimate case this fix must
        still allow to pass."""
        req_a = Requirement(
            id="req-a", name="acme-widgets", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
            verification_method="pip show acme-widgets",
        )
        req_b = Requirement(
            id="req-b", name="requests", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
            verification_method="pip show requests",
        )
        item_a = self._item(req_a.id, "acme-widgets")
        item_b = self._item(req_b.id, "requests")
        variant = CouncilVariant(
            id="v1", name="v1", environment="host", toolchain=(item_a, item_b),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req_a.id, req_b.id), kind="smoke_test",
                mechanism=PACKAGE_PRESENCE_MECHANISM, evidence="acme-widgets",
            ),),
        )
        preflight = self._two_requirement_preflight(req_a, req_b)
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        validations = validate_candidates(result, preflight=preflight)
        assert validations[0].admissible is True, validations[0].reasons


# ---------------------------------------------------------------------------
# I: verification-requirement SHAPE rejections -- the controlled
# "pip show <distribution>" grammar, never arbitrary shell parsing
# ---------------------------------------------------------------------------

class TestVerificationRequirementShapeRejections:
    @pytest.mark.parametrize("verification_method", [
        "pip show acme-widgets && echo x",
        "pip show acme-widgets | cat",
        "docker exec foo pip show acme-widgets",
        "source .venv/bin/activate && pip show acme-widgets",
        "pip show acme-widgets --verbose",
        "pip show acme-widgets extra-package",
        "pip show",
        "pip show ",
        "Pip Show acme-widgets",
        "run the test suite",
    ])
    def test_rejected_shapes_never_establish_capability(self, verification_method):
        req = Requirement(
            id="req-a", name="acme-widgets", type=RequirementType.PYTHON_PACKAGE,
            purpose="test", required=True, confidence=0.9,
            verification_method=verification_method,
        )
        assert parse_pip_show_requirement(verification_method) is None
        variant = _package_variant(req.id)
        validations = _validate(variant, req)
        assert validations[0].admissible is False

    def test_wrong_mechanism_token_case_never_matches(self):
        req = _requirement()
        item = _package_item(req.id, mechanism=PACKAGE_PRESENCE_MECHANISM)
        variant = CouncilVariant(
            id="v1", name="v1", toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=(req.id,), kind="smoke_test",
                mechanism="PIP_SHOW", evidence="acme-widgets",
            ),),
        )
        validations = _validate(variant, req)
        assert validations[0].admissible is False


# ---------------------------------------------------------------------------
# J: environment/target binding at materialization
# ---------------------------------------------------------------------------

class TestEnvironmentTargetBindingAtMaterialization:
    def _decision_for(self, req, environment, project_root=None):
        variant = _package_variant(req.id, environment=environment)
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        preflight = _binding_preflight(req)
        decision = select_engineering_variant(result, preflight, project_root=project_root)
        return decision, preflight

    def _decision_bypassing_s2_3(self, req, environment):
        """Builds an EngineeringDecision directly, WITHOUT going through
        select_engineering_variant()/S2.3 admissibility -- used only to
        prove ToolchainMaterializer/S3's OWN independent fail-closed
        contract (CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-
        FIX-004 #7/#9), as defense in depth on top of (never a
        replacement for) the S2.3-level rejection proven separately
        below."""
        from app.engineering_decision import EngineeringDecision
        from app.engineering_solution_class import classify_engineering_solution
        variant = _package_variant(req.id, environment=environment)
        preflight = _binding_preflight(req)
        decision = EngineeringDecision(
            variant=variant,
            solution_class=classify_engineering_solution(variant),
            selection_authority="test",
        )
        return decision, preflight

    def test_venv_candidate_with_no_real_venv_is_inadmissible_at_s2_3(self, tmp_path):
        """CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004
        (#4): S2.3 itself must know whether a "venv" candidate has an
        actual, resolvable target BEFORE it is ever exposed as
        admissible -- a project_root with no real `.venv` must reject
        the candidate at select_engineering_variant() itself, never only
        degrade it later during materialization."""
        from app.engineering_decision import NoEligibleEngineeringCandidateError
        req = _requirement()
        with pytest.raises(NoEligibleEngineeringCandidateError):
            self._decision_for(req, "venv", project_root=str(tmp_path))

    def test_venv_candidate_with_no_project_root_is_inadmissible_at_s2_3(self):
        """A "venv" candidate with NO project_root at all is exactly as
        unresolvable as one with a venv-less project_root -- S2.3 must
        reject it too, never treat "unknown" as "acceptable"."""
        from app.engineering_decision import NoEligibleEngineeringCandidateError
        req = _requirement()
        with pytest.raises(NoEligibleEngineeringCandidateError):
            self._decision_for(req, "venv", project_root=None)

    def test_venv_candidate_with_no_real_venv_fails_closed_to_manual_review_at_materialization(self, tmp_path):
        """Defense in depth: even a "venv" candidate that somehow reached
        materialize_decision() without going through S2.3 (see
        _decision_bypassing_s2_3()) still independently fails closed to
        manual_review there -- S3 owns its own contract, never merely
        trusting that S2.3 already caught this."""
        req = _requirement()
        decision, preflight = self._decision_bypassing_s2_3(req, "venv")
        plan = ToolchainMaterializer().materialize_decision(
            decision, "proj", preflight, project_root=str(tmp_path),
        )
        step = plan.steps[0]
        assert step.action == "manual_review"
        assert step.target_executable is None

    def test_venv_candidate_with_a_real_venv_resolves_to_it_not_host(self, tmp_path, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda name: "/some/host/bin/python")
        venv_dir = tmp_path / ".venv"
        venv.EnvBuilder(with_pip=False, clear=True).create(venv_dir)
        req = _requirement()
        decision, preflight = self._decision_for(req, "venv", project_root=str(tmp_path))
        plan = ToolchainMaterializer().materialize_decision(
            decision, "proj", preflight, project_root=str(tmp_path),
        )
        step = plan.steps[0]
        assert step.action == "install"
        assert step.target_executable == str(venv_dir / "bin" / "python")
        assert step.target_executable != "/some/host/bin/python"

    def test_host_candidate_resolves_via_existing_central_policy_not_project_venv(self, tmp_path, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda name: "/some/host/bin/python")
        venv_dir = tmp_path / ".venv"
        venv.EnvBuilder(with_pip=False, clear=True).create(venv_dir)
        req = _requirement()
        decision, preflight = self._decision_for(req, "host", project_root=str(tmp_path))
        plan = ToolchainMaterializer().materialize_decision(
            decision, "proj", preflight, project_root=str(tmp_path),
        )
        step = plan.steps[0]
        assert step.action == "install"
        assert step.target_executable == "/some/host/bin/python"
        assert step.target_executable != str(venv_dir / "bin" / "python")

    def test_container_environment_never_reaches_a_selectable_decision(self):
        from app.engineering_decision import NoEligibleEngineeringCandidateError
        req = _requirement()
        variant = _package_variant(req.id, environment="container")
        preflight = _binding_preflight(req)
        result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )
        with pytest.raises(NoEligibleEngineeringCandidateError):
            select_engineering_variant(result, preflight)

    def test_target_bound_to_one_project_can_never_satisfy_another(self, tmp_path):
        project_a = tmp_path / "a"
        project_b = tmp_path / "b"
        for root in (project_a, project_b):
            venv.EnvBuilder(with_pip=False, clear=True).create(root / ".venv")
        target_a = str(project_a / ".venv" / "bin" / "python")
        target_b = str(project_b / ".venv" / "bin" / "python")
        assert environment_target_matches("venv", target_a, str(project_b)) is False
        assert environment_target_matches("venv", target_b, str(project_a)) is False


# ---------------------------------------------------------------------------
# K: CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003
# Productive Greenfield regression -- exercises the REAL productive chain:
# RequirementPreflight -> candidate selection -> environment-aware target
# resolution -> SetupPlan/materialization -> default PythonPackageExecutor
# path -> post-install verification. No manual target assignment after
# selection, no _TargetBoundVerifier-style echo fake seeded with an
# invented path, no monkeypatched pre-installed package, no fake trusted
# Project Intelligence evidence -- every target compared below is read
# back from what the REAL productive chain itself resolved.
# ---------------------------------------------------------------------------

class _ProductiveVerifier:
    """A deterministic post-install presence fake keyed by the
    productively-resolved target. `present_on` is populated by the TEST
    from a value the real chain itself already produced
    (plan.steps[0].target_executable, captured before this object even
    exists) -- never a value this class invents on its own."""

    def __init__(self, present_on: dict[str, set[str]]):
        self._present_on = present_on
        self.calls: list[tuple] = []

    def __call__(self, step: SetupStep) -> bool:
        self.calls.append((step.target_executable, step.package))
        return step.package in self._present_on.get(step.target_executable, set())


class TestProductiveGreenfieldEnvironmentTargetBinding:
    """A true zero-file Greenfield project (a genuinely empty tmp_path): a
    required python_package, absent everywhere, a valid technical
    identity, a controlled install method, a matching
    'pip show <same package>' requirement, and a supported candidate
    environment."""

    DISTRIBUTION = "some-genuinely-nonexistent-adc-test-distribution-xyz"

    def _requirement(self):
        return Requirement(
            id="req-pkg", name=self.DISTRIBUTION, type=RequirementType.PYTHON_PACKAGE,
            purpose="greenfield dependency", required=True, confidence=0.9,
            verification_method=f"pip show {self.DISTRIBUTION}",
        )

    def _variant(self, environment):
        item = ToolchainItem(
            requirement_ref="req-pkg", name=self.DISTRIBUTION,
            type=RequirementType.PYTHON_PACKAGE,
            technical_identity=self.DISTRIBUTION, install_method="pip",
            state="needs_install", provides_verification=(PACKAGE_PRESENCE_MECHANISM,),
        )
        return CouncilVariant(
            id="v1", name="v1", environment=environment, toolchain=(item,),
            verification_coverage=(VerificationCoverage(
                requirement_refs=("req-pkg",), kind="smoke_test",
                mechanism=PACKAGE_PRESENCE_MECHANISM, evidence=self.DISTRIBUTION,
            ),),
        )

    def _run_end_to_end(self, tmp_path, environment):
        requirement = self._requirement()

        # A: real zero-file Greenfield preflight -- the package is
        # genuinely absent from the real, running interpreter (a
        # deliberately fictional distribution name), so
        # RequirementPreflight itself, unmodified, reports it missing --
        # never monkeypatched, never assumed.
        preflight = RequirementPreflight.check(
            (requirement,), "proj", project_root=str(tmp_path),
        )
        assert preflight.results[0].present is False
        assert requirement in preflight.missing_requirements

        variant = self._variant(environment)
        council_result = CouncilResult(
            id="c1", project_id="proj", variants=(variant,),
            recommendation="v1", council_complete=True,
        )

        # B: S2.3 accepts purely on structural capability + matching
        # identity -- the package is still absent; nothing here checks
        # presence. project_root is threaded through so S2.3 itself can
        # confirm this candidate's own environment (host or venv) has a
        # real, resolvable target (CLAUDE-ADC-S23-STRICT-IDENTITY-
        # ENVIRONMENT-BINDING-FIX-004 #4) -- the same project_root
        # materialization below uses.
        decision = select_engineering_variant(
            council_result, preflight,
            trusted_verification_groups=all_trusted_verification_groups(None),
            project_root=str(tmp_path),
        )
        assert decision.variant.id == "v1"

        # C/D/E/F: environment-aware target resolution + materialization,
        # through the REAL ToolchainMaterializer, given the real
        # project_root.
        plan = ToolchainMaterializer().materialize_decision(
            decision, "proj", preflight, project_root=str(tmp_path),
        )
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.action == "install"
        assert step.package == self.DISTRIBUTION

        expected_resolution = resolve_environment_python_target(environment, str(tmp_path))
        assert expected_resolution.resolved is True
        assert step.target_executable == expected_resolution.target_executable
        return step

    def test_host_end_to_end_install_and_verify_succeeds(self, tmp_path):
        step = self._run_end_to_end(tmp_path, "host")
        real_target = step.target_executable
        # D/E: host resolves via the existing central policy, not a venv.
        assert real_target == resolve_target_python_executable()

        approved_step = replace(step, is_approved=True)
        runner = _RecordingRunner(returncode=0)
        verifier = _ProductiveVerifier(present_on={real_target: {self.DISTRIBUTION}})
        executor = PythonPackageExecutor(runner=runner, verifier=verifier)

        result = executor.execute(approved_step)

        # G: installation used the exact resolved target.
        assert runner.calls == [[real_target, "-m", "pip", "install", self.DISTRIBUTION]]
        # H: verification used that SAME exact target -- install_target == verification_target.
        assert verifier.calls == [(real_target, self.DISTRIBUTION)]
        # I: post-install success completes the path.
        assert result.success is True
        assert result.verification_passed is True

    def test_venv_end_to_end_install_and_verify_succeeds(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        venv.EnvBuilder(with_pip=False, clear=True).create(venv_dir)

        step = self._run_end_to_end(tmp_path, "venv")
        real_target = step.target_executable
        # D: venv resolves to the project's own venv interpreter.
        assert real_target == str(venv_dir / "bin" / "python")

        approved_step = replace(step, is_approved=True)
        runner = _RecordingRunner(returncode=0)
        verifier = _ProductiveVerifier(present_on={real_target: {self.DISTRIBUTION}})
        executor = PythonPackageExecutor(runner=runner, verifier=verifier)

        result = executor.execute(approved_step)

        assert runner.calls == [[real_target, "-m", "pip", "install", self.DISTRIBUTION]]
        assert verifier.calls == [(real_target, self.DISTRIBUTION)]
        assert result.success is True
        assert result.verification_passed is True

    def test_post_install_presence_failure_fails_closed(self, tmp_path):
        step = self._run_end_to_end(tmp_path, "host")
        approved_step = replace(step, is_approved=True)
        runner = _RecordingRunner(returncode=0)
        # J: the target still reports the package absent after "install"
        # -- never monkeypatched to already-installed, never fed fake
        # Project Intelligence evidence.
        verifier = _ProductiveVerifier(present_on={})
        executor = PythonPackageExecutor(runner=runner, verifier=verifier)

        result = executor.execute(approved_step)

        assert result.success is False
        assert result.verification_passed is False
