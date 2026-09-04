import json
import re
import uuid
from typing import Any, Callable, Protocol
from app.requirement_model import (
    Requirement,
    RequirementEvidence,
    RequirementActivation,
    DiscoveryResult,
    RequirementType,
    Status,
)


class LLMProvider(Protocol):
    """Protocol for an LLM provider that returns a string completion."""

    def complete(self, prompt: str) -> str:
        ...


class StructuredResponseLLMProvider(Protocol):
    """Optional provider capability for requesting a JSON response."""

    def complete_structured(self, prompt: str) -> str:
        ...


class InvalidDiscoveryJSONError(ValueError):
    pass


class InvalidDiscoveryResponseStructureError(ValueError):
    pass


# Confidence mapping from symbolic to numeric values.
_CONFIDENCE_MAP = {
    "high": 0.9,
    "medium": 0.6,
    "low": 0.3,
}


class AIRequirementDiscovery:
    """Discovers requirements for a project using an LLM provider.

    The discovery is stack‑neutral and does not contain any ESPHome, ESP32,
    pytest or other framework‑specific logic.  It only uses the central
    requirement model and an injectable LLMProvider.
    """

    _DISCOVERY_PROMPT_TEMPLATE = """\
Return a JSON object with the single key "requirements" that is an array of requirement objects.
No other top-level keys. No commentary outside the JSON.

AI-Dev-Center is a controlled engineering system for developing and
maintaining software, firmware, and hardware-related projects.
You are the Requirement Discovery Analyst of AI-Dev-Center.
Your responsibility is to discover project requirements and current-request
activation state. You do not approve or execute changes.

Given the following project information, discover all durable technical
requirements (external tools, packages, libraries, SDKs, hardware capabilities,
etc.) that this project and its useful development environment need.

Then for the current user request below, determine which of those requirements
are needed right now and which can remain forward-looking project context.

User request:
{user_request}

Observed project information:
{project_info}

For each requirement provide these fields inside the "requirements" array:
  * name (string — human/domain-facing requirement display name; may differ from the executable identity)
  * type (one of {types}; describes what kind of thing is required, not how it is installed; do not classify something by an installation mechanism merely because one installation option can provide it)
  * purpose (short description)
  * required (boolean — is this a durable project requirement?)
  * confidence (one of "high", "medium", "low")
  * evidence (string array — concrete file paths, snippets, or clues)
  * active_for_current_request (boolean — is this requirement needed for the current user request above? Be conservative: a physical target, flasher, debugger or serial connection needed for later deployment is NOT active for configure/generate/compile.)
  * blocks_current_operation (boolean — must the current operation stop if this requirement is absent? Must be false when active_for_current_request is false. A tool that is only needed for a later phase does not block configure/build/compile.)
  * activation_reason (short string grounded in the current request)
  * install_method (string or null — only if justified by evidence)
  * verification_method (string or null — only if justified)
  * required_version (string or null)
  * verification_executable (string or null — only for executable-backed requirement types; a single executable name or path used only for deterministic availability detection, e.g. "python3", NOT a shell command like "python3 --version" or "which python3")
  * metadata (object — additional contextual data if available)

Rules:
- Only infer requirements from the provided information. Do NOT invent facts.
- Discover forward-looking development requirements supported by project facts
  even when they are not needed by the current user request.
- Forward-looking requirements must have active_for_current_request=false,
  blocks_current_operation=false.
- Use "unknown" for the type if you cannot determine it.

Return ONLY the JSON object described above. No markdown fences unless the
provider requires them.
"""

    _REPAIR_PROMPT_TEMPLATE = """\
AI-Dev-Center is a controlled engineering system for developing and
maintaining software, firmware, and hardware-related projects.
You are the Requirement Discovery Analyst of AI-Dev-Center.
Your responsibility is to discover project requirements.
You do not approve or execute changes.

The previous attempt to discover requirements returned a JSON object that did
not use the required structure.

Restructure the already-gathered information into exactly this format:

{{"requirements": [array of requirement objects]}}

Context — the original task:
User request: {user_request}
Project information: {project_info}

Rules:
- Preserve every requirement you already identified. Do not omit any.
- Do NOT invent new requirements or facts.
- Return ONLY the JSON object with "requirements" as the single top-level key.
- No other keys, no additional commentary.
"""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        ai_model: str | None = None,
        require_json: bool = True,
    ) -> None:
        self._provider = llm_provider
        self._ai_model = ai_model
        self._require_json = require_json
        self._activity_callback: Callable[..., None] | None = None
        self._effective_prompt: str | None = None
        self._effective_repair_prompt: str | None = None

    def set_activity_callback(self, callback: Callable[..., None] | None) -> None:
        self._activity_callback = callback

    @property
    def effective_prompt(self) -> str | None:
        return self._effective_prompt

    @property
    def effective_repair_prompt(self) -> str | None:
        return self._effective_repair_prompt

    def _activity(self, state: str, error_category: str | None = None) -> None:
        if self._activity_callback is None:
            return
        details = {
            "actor": "Requirement discovery provider",
            "runtime_state": state,
            "model": self._ai_model or "",
            "provider": type(self._provider).__name__ if self._provider else "",
        }
        if error_category:
            details["error_category"] = error_category
        if state == "thinking" and self._effective_prompt:
            details["effective_prompt"] = self._effective_prompt
        if state == "repairing" and self._effective_repair_prompt:
            details["effective_prompt"] = self._effective_repair_prompt
        try:
            self._activity_callback(**details)
        except Exception:
            pass

    def _build_prompt(
        self, project_info: dict[str, Any], user_request: str | None = None,
    ) -> str:
        serialized = json.dumps(project_info, indent=2, default=str)
        return self._DISCOVERY_PROMPT_TEMPLATE.format(
            project_info=serialized,
            user_request=user_request or "No user request was supplied.",
            types=", ".join(
                getattr(RequirementType, attr)
                for attr in dir(RequirementType)
                if not attr.startswith("_")
            ),
        )

    def _build_repair_prompt(
        self, project_info: dict[str, Any], user_request: str | None = None,
    ) -> str:
        serialized = json.dumps(project_info, indent=2, default=str)
        return self._REPAIR_PROMPT_TEMPLATE.format(
            project_info=serialized,
            user_request=user_request or "No user request was supplied.",
        )

    def _attempt_repair(
        self,
        project_info: dict[str, Any],
        user_request: str | None = None,
    ) -> str | None:
        if self._provider is None:
            return None
        repair_prompt = self._build_repair_prompt(project_info, user_request)
        self._effective_repair_prompt = repair_prompt
        self._activity("repairing")
        structured_completion = getattr(
            self._provider, "complete_structured", None
        )
        if self._require_json and callable(structured_completion):
            return structured_completion(repair_prompt)
        return self._provider.complete(repair_prompt)

    def _parse_confidence(self, raw: Any) -> float:
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            return _CONFIDENCE_MAP.get(raw.strip().lower(), 0.5)
        return 0.5

    def _build_requirement(self, data: dict[str, Any]) -> Requirement:
        req_id = data.get("id") or f"req-{uuid.uuid4().hex[:8]}"
        evidence_raw = data.get("evidence", [])
        evidence_tuple = tuple(
            RequirementEvidence(
                id=f"ev-{idx}-{req_id}",
                source_type="llm",
                description=str(item),
                source_file=None,
                snippet=item if isinstance(item, str) else str(item),
                confidence_contribution=None,
            )
            for idx, item in enumerate(evidence_raw)
        )
        metadata = data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return Requirement(
            id=req_id,
            name=str(data.get("name", "")),
            type=str(data.get("type", RequirementType.UNKNOWN)),
            purpose=str(data.get("purpose", "")),
            required=bool(data.get("required", True)),
            confidence=self._parse_confidence(data.get("confidence", 0.5)),
            evidence=evidence_tuple,
            source_file=None,
            detected_version=None,
            required_version=data.get("required_version"),
            install_method=data.get("install_method"),
            verification_method=data.get("verification_method"),
            verification_executable=data.get("verification_executable"),
            status=Status.DISCOVERED,
            metadata=metadata,
        )

    @staticmethod
    def _build_activation(
        data: dict[str, Any], requirement: Requirement,
    ) -> RequirementActivation:
        active = data.get("active_for_current_request", requirement.required)
        if not isinstance(active, bool):
            active = requirement.required
        blocking = data.get("blocks_current_operation", active and requirement.required)
        if not isinstance(blocking, bool):
            blocking = active and requirement.required
        blocking = blocking and active
        reason = data.get("activation_reason", "")
        return RequirementActivation(
            requirement_id=requirement.id,
            active=active,
            blocks_current_operation=blocking,
            reason=str(reason) if reason is not None else "",
        )

    def _parse_response(self, response_text: str) -> list[dict[str, Any]]:
        """Extract requirements JSON list from provider response."""
        if not isinstance(response_text, str):
            raise InvalidDiscoveryResponseStructureError(
                "LLM response content must be text."
            )
        fenced = re.fullmatch(
            r"\s*```json\s*\n?(.*?)\n?```\s*",
            response_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        normalized = fenced.group(1).strip() if fenced else response_text
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError:
            raise InvalidDiscoveryJSONError(
                "LLM response is not valid JSON."
            ) from None

        if isinstance(parsed, dict):
            list_candidates = parsed.get("requirements")
            if list_candidates is not None:
                parsed = list_candidates
            else:
                # Maybe the response is a single requirement object.
                if "name" in parsed:
                    parsed = [parsed]
                else:
                    raise InvalidDiscoveryResponseStructureError(
                        "LLM response does not contain a 'requirements' key or a valid structure."
                    )

        if not isinstance(parsed, list):
            raise InvalidDiscoveryResponseStructureError(
                "LLM response top-level structure is not a JSON array."
            )

        return parsed

    def discover(
        self,
        project_info: dict[str, Any],
        stack_context: str | None = None,
        conversation_trace_id: str | None = None,
        user_request: str | None = None,
    ) -> DiscoveryResult:
        """Run LLM‑based discovery and return a DiscoveryResult.

        Parameters:
            project_info: Dictionary containing information about the project.
            stack_context: Optional stack identifier (ignored in this version).
            conversation_trace_id: Optional trace id for debugging.
            user_request: Actual adapter-neutral business request, when supplied.

        Returns:
            DiscoveryResult with discovered requirements.
        """
        warnings: list[str] = []
        fallback_used = False
        requirements: list[Requirement] = []
        activations: list[RequirementActivation] = []
        prompt = self._build_prompt(project_info, user_request)
        self._effective_prompt = prompt
        self._effective_repair_prompt = None

        if self._provider is None:
            self._activity("failed", "ProviderUnavailable")
            fallback_used = True
            warnings.append("No LLM provider configured. Discovery returned no requirements.")
        else:
            try:
                self._activity("preparing")
                self._activity("thinking")
                structured_completion = getattr(
                    self._provider, "complete_structured", None
                )
                if self._require_json and callable(structured_completion):
                    raw_response = structured_completion(prompt)
                else:
                    raw_response = self._provider.complete(prompt)
            except Exception as exc:
                self._activity("failed", "provider_failure")
                fallback_used = True
                warnings.append(
                    f"LLM provider raised an exception: {type(exc).__name__}"
                )
                raw_response = None

            if raw_response is not None:
                try:
                    self._activity("reviewing")
                    data = self._parse_response(raw_response)
                except InvalidDiscoveryJSONError as exc:
                    self._activity("failed", "invalid_json")
                    fallback_used = True
                    warnings.append(f"Failed to parse LLM response: {exc}")
                    data = []
                except InvalidDiscoveryResponseStructureError as exc:
                    data = []
                    repair_completed = False
                    try:
                        repair_response = self._attempt_repair(
                            project_info, user_request,
                        )
                    except Exception:
                        repair_response = None
                    if repair_response is not None:
                        try:
                            data = self._parse_response(repair_response)
                            repair_completed = True
                        except (InvalidDiscoveryJSONError,
                                InvalidDiscoveryResponseStructureError):
                            pass
                    if repair_completed:
                        warnings.append(
                            "Requirement discovery response was repaired successfully."
                        )
                    else:
                        self._activity("failed", "invalid_response_structure")
                        fallback_used = True
                        warnings.append(f"Failed to parse LLM response: {exc}")
                for item_data in data:
                    if not isinstance(item_data, dict):
                        warnings.append("Skipping non‑dict item in LLM response.")
                        continue
                    try:
                        req = self._build_requirement(item_data)
                    except Exception as exc:
                        warnings.append(f"Could not build requirement from item: {exc}")
                        continue
                    requirements.append(req)
                    activations.append(self._build_activation(item_data, req))
                if not fallback_used:
                    self._activity("completed")

        project_id = project_info.get("project_id", "") or "unknown"
        return DiscoveryResult(
            id=f"disc-{uuid.uuid4().hex[:12]}",
            source="ai",
            project_id=project_id,
            requirements=tuple(requirements),
            activations=tuple(activations),
            conversation_trace_id=conversation_trace_id,
            ai_model=self._ai_model,
            fallback_used=fallback_used,
            warnings=tuple(warnings),
        )
