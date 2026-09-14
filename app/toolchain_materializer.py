from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.execution import is_controlled_setup_effect, is_install_method_compatible_with_controlled_executor
from app.python_distribution import (
    EnvironmentTargetResolution,
    is_valid_distribution_identifier,
    resolve_environment_python_target,
)
from app.requirement_model import (
    RequirementType,
    SetupPlan,
    SetupStep,
    PreflightResult,
    classify_setup_effect,
)


class ToolchainMaterializationError(Exception):
    """Raised when Council output cannot be safely materialized."""


class ToolchainMaterializer:
    """Convert the recommended Council variant into a safe SetupPlan."""

    SATISFIED = "satisfied"
    MATERIALIZABLE = "materializable"
    MANUAL_REVIEW = "manual_review"
    DEFERRED = "deferred"
    PROVIDED = "provided"

    # Baseline classes that can serve as valid provisioning roots.
    _VALID_PROVISIONING_ROOTS = frozenset({SATISFIED, MATERIALIZABLE})

    def classify_item(
        self, item: ToolchainItem, target_executable: str | None = None,
        environment_resolution: EnvironmentTargetResolution | None = None,
    ) -> SetupStep:
        """Public entry point for classifying a single ToolchainItem the
        exact same way materialize() itself would (CLAUDE-PRE-E2E-009B):
        reused by app.engineering_decision to determine, BEFORE a
        Council recommendation becomes the binding S2 EngineeringDecision,
        whether a given candidate's toolchain would actually materialize
        into a genuinely automatable ("install") step or a
        "manual_review" one -- without duplicating any of this
        classification logic in S2.

        `environment_resolution` (CLAUDE-ADC-S23-STRICT-IDENTITY-
        ENVIRONMENT-BINDING-FIX-004): optional and additive, forwarded
        unchanged to `_materialize_item()` -- lets a caller that has
        already resolved the candidate's own selected environment (e.g.
        S2.3's pip_show verification-capability check) ask "would this
        PYTHON_PACKAGE item actually reach a real, resolved target",
        exactly the same way materialize_decision() itself does, without
        duplicating that resolution logic."""
        return self._materialize_item(item, target_executable, environment_resolution)

    def materialize(
        self,
        council_result: CouncilResult,
        project_id: str,
        preflight: PreflightResult | None = None,
        platform: str | None = None,
        project_intelligence: object | None = None,
        project_root: str | None = None,
    ) -> SetupPlan:
        """CLAUDE-ARCH-S2-012A: S2/S3 compatibility path. Resolves the S2
        EngineeringDecision itself (S2.3 validate -> S2.4 authority ->
        S2.5 decision, via app.engineering_decision.select_engineering_
        variant()) and then delegates to materialize_decision() -- the
        actual, pure-S3 entry point that owns no S2 selection logic of
        its own. Kept for every existing caller that only has a raw
        CouncilResult + recommendation available (e.g. the narrower
        Missing-Toolchain retry path); the ONE real production call site
        (app/dev_workflow.py::run()) now calls select_engineering_
        variant() (S2) and materialize_decision() (S3) explicitly, as two
        separate steps owned by two separate Subsystems -- see
        materialize_decision()'s own docstring for the S3-only contract.
        """
        if not council_result.council_complete:
            raise ToolchainMaterializationError(
                "Council result is incomplete and cannot be materialized."
            )

        recommendation = council_result.recommendation
        if not recommendation:
            raise ToolchainMaterializationError(
                "Council result does not contain a recommendation."
            )

        # CLAUDE-PRE-E2E-009C: the recommendation must refer to a variant
        # the Council actually proposed (unchanged pre-check, same error
        # as before every prior test already relies on); the Chairman's
        # own recommendation is then honored AS THE SELECTION whenever it
        # is technically admissible -- ADC's documented governance is that
        # the deterministic layer validates admissibility, it does not
        # pick which admissible candidate wins. Only when the recommended
        # variant is genuinely INADMISSIBLE does this raise
        # ChairmanRecommendationInadmissibleError, exposing the remaining
        # admissible alternatives, rather than silently substituting a
        # different candidate for it. See app.engineering_decision for the
        # full producer -> artifact -> consumer rationale.
        self._find_recommended_variant(council_result, recommendation)
        from app.engineering_decision import select_engineering_variant
        from app.verification import all_trusted_verification_groups
        decision = select_engineering_variant(
            council_result, preflight, platform,
            chairman_recommendation=recommendation,
            trusted_verification_groups=all_trusted_verification_groups(project_intelligence),
            project_root=project_root,
        )
        return self.materialize_decision(decision, project_id, preflight, project_root=project_root)

    def materialize_decision(
        self,
        decision: "EngineeringDecision",
        project_id: str,
        preflight: PreflightResult | None = None,
        project_root: str | None = None,
    ) -> SetupPlan:
        """CLAUDE-ARCH-S2-012A: the pure S3 entry point. Consumes ONLY an
        already-resolved app.engineering_decision.EngineeringDecision --
        the artifact S2.5 (Engineering Decision & S3 Handoff) publishes
        once S2.3 (admissibility) and S2.4 (Human Engineering Authority)
        have already run. This method performs NO S2 selection,
        admissibility, Chairman-recommendation interpretation, or Human-
        choice logic of any kind -- it only materializes the ALREADY
        CHOSEN variant into a SetupPlan and independently protects S3's
        OWN contracts (SetupPlan correctness, controlled/manual step
        classification, unsupported-effect detection). This is the ONLY
        function that should ever grow new S3-owned defensive checks;
        S2 concerns belong in app.engineering_decision instead.

        `project_root` (CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-
        BINDING-FIX-003): optional and additive. When supplied, THIS is
        the "setup/target resolution" stage of RequirementPreflight ->
        candidate selection -> setup/target resolution ->
        ToolchainMaterializer -> PythonPackageExecutor: the SAME already-
        selected `decision.variant.environment` ("host" | "venv") is
        resolved, exactly once for this whole materialization, to one
        concrete Python executable target via
        app.python_distribution.resolve_environment_python_target() --
        never a second, competing resolution rule -- and that ONE
        resolved target (or its absence) then determines every
        PYTHON_PACKAGE SetupStep.target_executable below, superseding
        whatever generic, pre-candidate target RequirementPreflight
        itself stamped (Preflight runs before a candidate/environment
        even exists, so its own stamped target is only ever a valid
        binding for "host", coincidentally, via the same underlying
        policy -- never authoritative for "venv"). Omitting
        `project_root` (every pre-existing caller) preserves the exact
        prior behavior: each PYTHON_PACKAGE item's target comes from its
        own Preflight result, unchanged."""
        variant = decision.variant

        preflight_map = self._build_preflight_map(preflight)
        toolchain_refs = {item.requirement_ref for item in variant.toolchain}

        # CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004:
        # resolved whenever this call can actually know the real target
        # ('project_root' supplied), OR whenever the candidate's own
        # environment is "venv" -- a "venv" candidate can NEVER validly
        # resolve without a project_root (resolve_environment_python_
        # target() itself already fails closed for that combination), so
        # omitting project_root must never silently skip this resolution
        # and fall back to whatever per-item target Preflight happened to
        # stamp (always a host-style target, since Preflight runs before
        # any candidate/environment is even chosen) -- that was exactly
        # the "venv candidate + omitted project_root -> inherited host
        # target -> install" escape hatch this fix closes. A "host"
        # candidate with no project_root keeps the exact prior behavior
        # (environment_resolution stays None, each item's own Preflight-
        # stamped target is used unchanged) -- host resolution needs no
        # project_root at all, so there is nothing unsafe about deferring
        # it to Preflight's own target for callers that never pass one.
        environment_resolution: EnvironmentTargetResolution | None = None
        if project_root is not None or variant.environment == "venv":
            environment_resolution = resolve_environment_python_target(
                variant.environment, project_root,
            )

        classified = self._classify_with_provided_resolution(
            variant.toolchain, preflight_map, toolchain_refs, environment_resolution,
        )

        provided_ids = tuple(dict.fromkeys(
            item.requirement_ref
            for item, status in classified
            if status == self.PROVIDED
        ))
        # Per-item, not per-plan: each item's execution target (if it
        # even has one) comes from that item's OWN Preflight result, so
        # a project mixing multiple ecosystems in one plan never forces
        # a single global target onto every step -- UNLESS
        # environment_resolution is set (project_root supplied), in
        # which case the candidate's own selected environment is the
        # single source of truth for every PYTHON_PACKAGE item's target
        # (see _materialize_item()).
        steps = tuple(
            self._materialize_item(
                item,
                preflight_map[item.requirement_ref].target_executable
                if item.requirement_ref in preflight_map else None,
                environment_resolution=environment_resolution,
            )
            for item, status in classified
            if status not in {self.SATISFIED, self.DEFERRED, self.PROVIDED}
        )
        deferred_ids = tuple(dict.fromkeys(
            [
                requirement.id
                for requirement in (preflight.inactive_requirements if preflight else ())
            ]
            + [
                item.requirement_ref
                for item, status in classified
                if status == self.DEFERRED
            ]
        ))
        deferred_id_set = set(deferred_ids)
        deferred_requirements = tuple(
            requirement for requirement in (
                preflight.project_requirements if preflight else ()
            )
            if requirement.id in deferred_id_set
        )

        unsupported_effects: set[str] = set()
        for item, status in classified:
            if status not in {self.SATISFIED, self.DEFERRED, self.PROVIDED}:
                effect = classify_setup_effect(item.type, item.name, item.install_method)
                if effect and effect != "manual" and not is_controlled_setup_effect(effect):
                    unsupported_effects.add(effect)

        return SetupPlan(
            id=f"plan-{project_id}",
            project_id=project_id,
            steps=steps,
            requires_user_approval=True,
            rollback_steps=(),
            warnings=(),
            status="pending_approval",
            requirement_activations=(preflight.activations if preflight else ()),
            deferred_requirement_ids=deferred_ids,
            deferred_requirements=deferred_requirements,
            provided_requirement_ids=provided_ids,
            unsupported_backend_effects=tuple(sorted(unsupported_effects)),
        )

    @staticmethod
    def _build_preflight_map(
        preflight: PreflightResult | None,
    ) -> dict[str, object]:
        if preflight is None or not preflight.results:
            return {}
        return {
            result.requirement_id: result
            for result in preflight.results
        }

    def assess_item(
        self,
        item: ToolchainItem,
        preflight: PreflightResult | None = None,
    ) -> dict[str, object]:
        """Return the controlled baseline classification for one item."""
        status = self._classify_item_baseline(
            item, self._build_preflight_map(preflight)
        )
        effect = classify_setup_effect(item.type, item.name, item.install_method)
        controlled = is_controlled_setup_effect(effect)
        return {
            "requirement_ref": item.requirement_ref,
            "status": status,
            "setup_effect": effect if effect and effect != "manual" else None,
            "controlled_backend_available": controlled,
            "automatically_materializable": (
                status != self.MANUAL_REVIEW
            ),
        }

    def assess_variant(
        self,
        variant: CouncilVariant,
        preflight: PreflightResult | None = None,
    ) -> dict[str, object]:
        """Assess a variant using the same policy as materialization."""
        preflight_map = self._build_preflight_map(preflight)
        toolchain_refs = {item.requirement_ref for item in variant.toolchain}

        classified = self._classify_with_provided_resolution(
            variant.toolchain, preflight_map, toolchain_refs
        )
        status_by_ref = {
            item.requirement_ref: status for item, status in classified
        }
        items = tuple(
            {
                "requirement_ref": item.requirement_ref,
                "status": status_by_ref[item.requirement_ref],
                "setup_effect": (
                    effect if (effect := classify_setup_effect(item.type, item.name, item.install_method)) and effect != "manual" else None
                ),
                "controlled_backend_available": is_controlled_setup_effect(
                    classify_setup_effect(item.type, item.name, item.install_method)
                ),
                "automatically_materializable": (
                    status_by_ref[item.requirement_ref] != self.MANUAL_REVIEW
                ),
            }
            for item in variant.toolchain
        )
        automatically_materializable = all(
            item["automatically_materializable"] for item in items
        )
        return {
            "status": (
                "automatically_materializable"
                if automatically_materializable
                else self.MANUAL_REVIEW
            ),
            "automatically_materializable": automatically_materializable,
            "items": items,
        }

    # ------------------------------------------------------------------
    # Two-pass classification with provisioning-graph resolution
    # ------------------------------------------------------------------

    def _classify_with_provided_resolution(
        self,
        items: tuple[ToolchainItem, ...],
        preflight_map: dict[str, object],
        toolchain_refs: set[str],
        environment_resolution: EnvironmentTargetResolution | None = None,
    ) -> tuple[tuple[ToolchainItem, str], ...]:
        """Pass 1: baseline.  Pass 2: resolve provided chains.

        An item may be classified as PROVIDED only when its provided_by
        reference leads, through a non-cyclic chain, to a provider whose
        baseline classification is SATISFIED or MATERIALIZABLE.

        `environment_resolution`, when supplied, is forwarded unchanged
        to `_classify_item_baseline()` for every item -- see that
        method's own docstring (CLAUDE-ADC-S23-STRICT-IDENTITY-
        ENVIRONMENT-BINDING-FIX-004).
        """
        baseline = tuple(
            (item, self._classify_item_baseline(item, preflight_map, environment_resolution))
            for item in items
        )
        baseline_map = {item.requirement_ref: cls for item, cls in baseline}
        provided = self._resolve_provided_chains(items, baseline_map, toolchain_refs)

        return tuple(
            (item, self.PROVIDED if item.requirement_ref in provided else cls)
            for item, cls in baseline
        )

    def _classify_item_baseline(
        self,
        item: ToolchainItem,
        preflight_map: dict[str, object],
        environment_resolution: EnvironmentTargetResolution | None = None,
    ) -> str:
        """Classify one item ignoring provided_by (safe baseline).

        CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004: a
        Preflight "satisfied" result may suppress a PYTHON_PACKAGE item
        only when it is PROVEN to refer to the SAME effective target this
        materialization actually selected. RequirementPreflight always
        stamps a pre-candidate, host-style target (it runs before any
        candidate/environment is even chosen) -- that is only
        coincidentally the same target a "venv" candidate's own
        materialization-time `environment_resolution` will actually use.
        Reproduced defect this closes: a host preflight reports the
        package already present, the selected candidate's environment is
        "venv", and the selected venv target is missing -- the OLD code
        trusted `satisfied=True` unconditionally and suppressed the item
        entirely, so materialization silently skipped the target that
        actually needed it. See `_preflight_satisfaction_is_target_bound()`.
        """
        if item.requirement_ref in preflight_map:
            result = preflight_map[item.requirement_ref]
            if result.satisfied and self._preflight_satisfaction_is_target_bound(
                item, result, environment_resolution,
            ):
                return self.SATISFIED
            if not result.active:
                return self.DEFERRED
        elif item.state == "already_installed":
            return self.SATISFIED

        effect = classify_setup_effect(item.type, item.name, item.install_method)
        controlled = is_controlled_setup_effect(effect)

        if (
            item.requirement_ref in preflight_map
            and not preflight_map[item.requirement_ref].blocks_current_operation
            and not controlled
        ):
            return self.DEFERRED
        return self.MATERIALIZABLE if controlled else self.MANUAL_REVIEW

    @staticmethod
    def _preflight_satisfaction_is_target_bound(
        item: ToolchainItem,
        result: object,
        environment_resolution: EnvironmentTargetResolution | None,
    ) -> bool:
        """CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004:
        True when a PYTHON_PACKAGE `result.satisfied=True` is safe to
        trust for THIS materialization -- i.e. `preflight target ==
        selected materialization target`.

        Every non-PYTHON_PACKAGE requirement type, and every call that
        does not supply `environment_resolution` (assess_item()/
        assess_variant()'s own diagnostic-only path, and every "host"
        caller that omits project_root, unchanged since before this fix)
        keeps the exact prior, unconditional trust in `result.satisfied`
        -- this new binding only ever narrows PYTHON_PACKAGE target
        provenance, never any other requirement type's semantics.

        When `environment_resolution` IS supplied, the preflight-stamped
        target must be proven identical to the actually-selected target:
        an unresolved environment_resolution (e.g. a "venv" candidate
        with no real venv) or any other, non-matching target means the
        satisfied claim was proven about a DIFFERENT target than the one
        this candidate actually installs into/verifies against, so it
        must never suppress this item -- package presence for the
        selected target is then unknown/absent, and normal controlled-
        or-manual classification decides what happens next."""
        if item.type != RequirementType.PYTHON_PACKAGE or environment_resolution is None:
            return True
        return (
            environment_resolution.resolved
            and bool(result.target_executable)
            and result.target_executable == environment_resolution.target_executable
        )

    def _resolve_provided_chains(
        self,
        items: tuple[ToolchainItem, ...],
        baseline_map: dict[str, str],
        toolchain_refs: set[str],
    ) -> set[str]:
        """Return the requirement_refs that have valid provisioning chains.

        A chain is valid when following provided_by references from the
        item reaches a terminal provider whose *own* baseline classification
        is in _VALID_PROVISIONING_ROOTS (SATISFIED or MATERIALIZABLE).

        Self-references, cycles, chains that dead-end on a MANUAL_REVIEW or
        DEFERRED item, and chains referencing a missing provider all yield
        False for the entire chain.
        """
        graph: dict[str, str] = {}
        for item in items:
            provided_by = item.provided_by
            if (
                provided_by
                and isinstance(provided_by, str)
                and provided_by.strip()
                and provided_by in toolchain_refs
            ):
                graph[item.requirement_ref] = provided_by.strip()

        reachable: dict[str, bool] = {}

        def _can_reach_valid_root(ref: str, visited: frozenset[str]) -> bool:
            if ref in reachable:
                return reachable[ref]
            if ref in visited:
                reachable[ref] = False
                return False
            next_ref = graph.get(ref)
            if next_ref is None:
                result = baseline_map.get(ref) in self._VALID_PROVISIONING_ROOTS
                reachable[ref] = result
                return result
            result = _can_reach_valid_root(next_ref, visited | {ref})
            reachable[ref] = result
            return result

        provided: set[str] = set()
        for item in items:
            ref = item.requirement_ref
            baseline = baseline_map.get(ref)
            if baseline in self._VALID_PROVISIONING_ROOTS:
                continue
            if ref not in graph:
                continue
            if _can_reach_valid_root(ref, frozenset()):
                provided.add(ref)

        return provided

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_recommended_variant(
        self,
        council_result: CouncilResult,
        recommendation: str,
    ) -> CouncilVariant:
        for variant in council_result.variants:
            if variant.id == recommendation:
                return variant

        raise ToolchainMaterializationError(
            f"Recommended Council variant not found: {recommendation}"
        )

    def _materialize_item(
        self, item: ToolchainItem, target_executable: str | None = None,
        environment_resolution: EnvironmentTargetResolution | None = None,
    ) -> SetupStep:
        effect = classify_setup_effect(item.type, item.name, item.install_method)
        controlled = is_controlled_setup_effect(effect)

        if item.type == RequirementType.PYTHON_PACKAGE:
            # item.name is a human/display label (e.g. "ESPHome CLI") and
            # must never be guessed at as a technical identity.
            # technical_identity is Council's explicit, structured
            # technical identity (for this adapter: a PyPI distribution
            # name); a compatibility fallback to item.name is only used
            # when item.name is itself already a valid single structured
            # identifier token (e.g. "ESPHome"). When neither yields a
            # usable identity, this item cannot be a controlled install,
            # regardless of what classify_setup_effect concluded from
            # type/install_method alone.
            if is_valid_distribution_identifier(item.technical_identity):
                package = item.technical_identity
            elif is_valid_distribution_identifier(item.name):
                package = item.name
            else:
                # Neither a structured technical identity nor a
                # display name shaped like one is available: this
                # cannot become a controlled, automatable install no
                # matter what classify_setup_effect concluded from
                # type/install_method alone, and it must not carry a
                # setup_effect that implies otherwise.
                package = None
                controlled = False
                effect = None
        elif controlled:
            package = item.name
        else:
            package = None

        # CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003:
        # when the candidate's own selected environment has already been
        # resolved to a concrete Python target (materialize_decision()
        # supplied project_root), THAT resolution -- never the generic,
        # pre-candidate target Preflight happened to stamp -- is the
        # single source of truth for this item's target. A "venv"
        # candidate with no actual, existing venv interpreter (and a
        # "host"/"venv" candidate with any other unsupported/unresolved
        # environment) never silently falls back to a different target;
        # it fails closed to manual_review instead, exactly like an
        # incompatible install_method already does below.
        resolved_target_executable = target_executable
        if item.type == RequirementType.PYTHON_PACKAGE and environment_resolution is not None:
            if not environment_resolution.resolved:
                package = None
                controlled = False
                effect = None
                resolved_target_executable = None
            else:
                resolved_target_executable = environment_resolution.target_executable

        if controlled and package and not is_install_method_compatible_with_controlled_executor(
            effect, item.install_method, package,
        ):
            # CLAUDE-E2E-NIO-008A: a package/type combination that would
            # otherwise become a controlled, automatable install, but
            # whose install_method the controlled executor for this
            # exact effect cannot actually run (e.g. a free-form,
            # compound shell command sequence rather than a structured
            # pip install) must never become an approvable "install"
            # action -- it requires a new materialization with a
            # genuinely structured install_method, or manual handling,
            # exactly like any other requirement this materializer
            # cannot safely automate.
            controlled = False
            effect = None

        action = "install" if controlled else "manual_review"

        return SetupStep(
            id=f"step-{item.requirement_ref}",
            requirement_id=item.requirement_ref,
            action=action,
            install_method=item.install_method,
            package=package,
            version=item.version,
            command=None,
            verification_after=None,
            is_approved=False,
            setup_effect=effect if effect and effect != "manual" else None,
            target_executable=(
                resolved_target_executable if item.type == RequirementType.PYTHON_PACKAGE else None
            ),
        )