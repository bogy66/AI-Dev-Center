import json
import uuid
from typing import Any, Protocol
from app.requirement_model import (
    Requirement,
    RequirementEvidence,
    DiscoveryResult,
    RequirementType,
    Status,
)


class LLMProvider(Protocol):
    """Protocol for an LLM provider that returns a string completion."""

    def complete(self, prompt: str) -> str:
        ...


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
You are an expert software project analyst.
Given the following project information, list all technical requirements
(external tools, packages, libraries, SDKs, hardware capabilities, etc.)
that this project needs in order to build, test, flash, or run.

Project information:
{project_info}

Rules:
- Only infer requirements from the provided information.
- Do NOT invent facts, packages, or prerequisites you do not see.
- For each requirement provide:
  * name (string)
  * type (one of {types})
  * purpose (short description)
  * required (boolean)
  * confidence (one of "high", "medium", "low")
  * install_method (string or null – only if you can justify it from the evidence)
  * verification_method (string or null – only if justifiable)
  * required_version (string or null)
  * metadata (object – additional contextual data if available)
  * evidence (string array – concrete file paths, snippets, or other clues that support the requirement)
- If you cannot determine the type, use "unknown".
- Return a JSON object with a single key "requirements" that is an array of requirement objects.

Return ONLY valid JSON, no additional commentary.
"""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        ai_model: str | None = None,
    ) -> None:
        self._provider = llm_provider
        self._ai_model = ai_model

    def _build_prompt(self, project_info: dict[str, Any]) -> str:
        serialized = json.dumps(project_info, indent=2, default=str)
        return self._DISCOVERY_PROMPT_TEMPLATE.format(
            project_info=serialized,
            types=", ".join(
                getattr(RequirementType, attr)
                for attr in dir(RequirementType)
                if not attr.startswith("_")
            ),
        )

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
            confidence=self._parse_confidence(data.get("confidence", "medium")),
            evidence=evidence_tuple,
            source_file=None,
            detected_version=None,
            required_version=data.get("required_version"),
            install_method=data.get("install_method"),
            verification_method=data.get("verification_method"),
            status=Status.DISCOVERED,
            metadata=metadata,
        )

    def _parse_response(self, response_text: str) -> list[dict[str, Any]]:
        """Extract requirements JSON list from provider response."""
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError:
            raise ValueError("LLM response is not valid JSON.") from None

        if isinstance(parsed, dict):
            list_candidates = parsed.get("requirements")
            if list_candidates is not None:
                parsed = list_candidates
            else:
                # Maybe the response is a single requirement object.
                if "name" in parsed:
                    parsed = [parsed]
                else:
                    raise ValueError("LLM response does not contain a 'requirements' key or a valid structure.")

        if not isinstance(parsed, list):
            raise ValueError("LLM response top-level structure is not a JSON array.")

        return parsed

    def discover(
        self,
        project_info: dict[str, Any],
        stack_context: str | None = None,
        conversation_trace_id: str | None = None,
    ) -> DiscoveryResult:
        """Run LLM‑based discovery and return a DiscoveryResult.

        Parameters:
            project_info: Dictionary containing information about the project.
            stack_context: Optional stack identifier (ignored in this version).
            conversation_trace_id: Optional trace id for debugging.

        Returns:
            DiscoveryResult with discovered requirements.
        """
        warnings: list[str] = []
        fallback_used = False
        requirements: list[Requirement] = []
        prompt = self._build_prompt(project_info)

        if self._provider is None:
            fallback_used = True
            warnings.append("No LLM provider configured. Discovery returned no requirements.")
        else:
            try:
                raw_response = self._provider.complete(prompt)
            except Exception as exc:
                fallback_used = True
                warnings.append(f"LLM provider raised an exception: {exc}")
                raw_response = None

            if raw_response is not None:
                try:
                    data = self._parse_response(raw_response)
                except Exception as exc:
                    fallback_used = True
                    warnings.append(f"Failed to parse LLM response: {exc}")
                    data = []
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

        project_id = project_info.get("project_id", "") or "unknown"
        return DiscoveryResult(
            id=f"disc-{uuid.uuid4().hex[:12]}",
            source="ai",
            project_id=project_id,
            requirements=tuple(requirements),
            conversation_trace_id=conversation_trace_id,
            ai_model=self._ai_model,
            fallback_used=fallback_used,
            warnings=tuple(warnings),
        )
