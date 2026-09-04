from app.council_models import CouncilResult, CouncilVariant, ToolchainItem
from app.execution import is_controlled_setup_effect
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

    def materialize(
        self,
        council_result: CouncilResult,
        project_id: str,
        preflight: PreflightResult | None = None,
    ) -> SetupPlan:
        if not council_result.council_complete:
            raise ToolchainMaterializationError(
                "Council result is incomplete and cannot be materialized."
            )

        recommendation = council_result.recommendation
        if not recommendation:
            raise ToolchainMaterializationError(
                "Council result does not contain a recommendation."
            )

        variant = self._find_recommended_variant(
            council_result,
            recommendation,
        )

        preflight_map = self._build_preflight_map(preflight)
        toolchain_refs = {item.requirement_ref for item in variant.toolchain}

        classified = self._classify_with_provided_resolution(
            variant.toolchain, preflight_map, toolchain_refs
        )

        provided_ids = tuple(dict.fromkeys(
            item.requirement_ref
            for item, status in classified
            if status == self.PROVIDED
        ))
        steps = tuple(
            self._materialize_item(item)
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
    ) -> tuple[tuple[ToolchainItem, str], ...]:
        """Pass 1: baseline.  Pass 2: resolve provided chains.

        An item may be classified as PROVIDED only when its provided_by
        reference leads, through a non-cyclic chain, to a provider whose
        baseline classification is SATISFIED or MATERIALIZABLE.
        """
        baseline = tuple(
            (item, self._classify_item_baseline(item, preflight_map))
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
    ) -> str:
        """Classify one item ignoring provided_by (safe baseline)."""
        if item.requirement_ref in preflight_map:
            result = preflight_map[item.requirement_ref]
            if result.satisfied:
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

    def _materialize_item(self, item: ToolchainItem) -> SetupStep:
        effect = classify_setup_effect(item.type, item.name, item.install_method)
        controlled = is_controlled_setup_effect(effect)
        action = "install" if controlled else "manual_review"

        if controlled:
            package = item.name
        elif item.type == RequirementType.PYTHON_PACKAGE:
            package = item.name
        else:
            package = None

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
        )