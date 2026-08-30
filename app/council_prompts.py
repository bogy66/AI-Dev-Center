"""Prompt templates for the Multi-KI Engineering Council.

All prompts are pure text.  No LLM calls, no provider logic, no ESP32-specific
content.  Builder functions accept CouncilInput data and return prompt strings.
"""

from __future__ import annotations

import json

from app.council_models import CouncilInput


# ==========================================================================
# PHASE 1 — Rollenspezifische Prompt-Präambeln
# ==========================================================================

AGENT_ROLE_ENV_ARCHITECT = """\
Du bist der ENVIRONMENT ARCHITECT im AI Dev Center Engineering Council.

Deine PRIMÄRE Perspektive: AUSFÜHRUNGSUMGEBUNG.

Analysiere die Projektanforderungen unter diesen Gesichtspunkten:
- Hardware vs Simulation vs Hybrid — was ist für dieses Projekt sinnvoll?
- Host vs Container vs Target vs Physical Hardware
- Konnektivität (serial, jtag/swd, wifi, ota)
- Welche Hardware-Targets kommen in Frage?
- Environment-spezifische Risiken (Treiber, Ports, Zugriff)

Erwähne Tools nur aus Environment-Sicht.  Dein Fokus ist die Frage WO
die Entwicklung und Ausführung stattfinden soll, nicht WOMIT genau.

Trotzdem musst du für jede Variante vollständige ToolchainItems angeben —
denke bei der Tool-Auswahl primär an die Environment-Passung.
"""

AGENT_ROLE_TOOLCHAIN = """\
Du bist der TOOLCHAIN INTEGRATOR im AI Dev Center Engineering Council.

Deine PRIMÄRE Perspektive: WERKZEUGKETTE.

Analysiere die Projektanforderungen unter diesen Gesichtspunkten:
- Compiler, SDKs, Build-Systeme
- Paketmanager (pip, apt, brew, platformio, …)
- Flasher, Debugger, Serial-Monitore
- Abhängigkeiten zwischen Tools (z. B. python vor esphome)
- Alternative Toolchains (verschiedene Wege, dasselbe Ziel zu erreichen)
- Konkrete Installationsbefehle und Verifikation

Erwähne Environment nur aus Tool-Sicht.  Dein Fokus ist die Frage WOMIT
gearbeitet wird, nicht WO.

Du musst für JEDE Variante eine passende Environment angeben —
denke primär daran, welche Tools welche Environment erfordern.
"""

AGENT_ROLE_RISK = """\
Du bist der RISK & FEASIBILITY ASSESSOR im AI Dev Center Engineering Council.

Deine PRIMÄRE Perspektive: RISIKEN UND MACHBARKEIT.

Analysiere die Projektanforderungen unter diesen Gesichtspunkten:
- Technische Risiken (Kompatibilität, Versionen, Treiber)
- Komplexität und Setup-Aufwand
- Wartbarkeit und Langzeit-Stabilität
- Lizenz- und Kostenrisiken
- Verifikationsrisiken (kann man testen, ob die Toolchain funktioniert?)
- Was kann schiefgehen?

Dein Fokus ist die Frage: WIE SICHER IST DIESE LÖSUNG?
Entwirf Varianten primär nach Risikoprofil (minimales Risiko zuerst).

Du musst trotzdem vollständige Toolchains angeben — dein Fokus ist die
Risikobewertung, aber die Varianten müssen technisch vollständig sein.
"""

# ==========================================================================
# PHASE 1 — Prompt-Builder
# ==========================================================================

_PHASE1_JSON_SCHEMA = """\
{
  "variants": [
    {
      "variant_id": "<agent>-var-1",
      "name": "Kurzer, sprechender Name",
      "description": "1-2 Sätze Beschreibung",
      "environment": "host|container|target|physical_hardware|simulation",
      "hardware_target": "esp32" | null,
      "connection": "serial|jtag/swd|wifi|ota" | null,
      "capabilities": ["build", "flash", "debug", …],
      "toolchain": [
        {
          "requirement_ref": "req-xxx",
          "name": "python",
          "type": "executable|python_package|system_package|sdk|toolchain|flasher|…",
          "install_method": "pip install esphome" | null,
          "version": "3.12" | null,
          "purpose": "Wofür wird dieses Tool in dieser Variante gebraucht?",
          "depends_on": ["python"],
          "state": "already_installed|needs_install|unavailable",
          "environment_constraint": null
        }
      ],
      "advantages": ["Vorteil 1", "Vorteil 2"],
      "disadvantages": ["Nachteil 1"],
      "risks": ["Risiko 1"],
      "confidence": 0.8,
      "feasibility": "high|medium|low",
      "verification": "esphome version && esphome compile",
      "agent_reasoning": "Warum schlägst du als Environment Architect diese Variante vor?"
    }
  ]
}"""


def _serialize_requirement(req) -> dict:
    return {
        "id": req.id,
        "name": req.name,
        "type": req.type,
        "purpose": req.purpose,
        "required": req.required,
        "confidence": req.confidence,
        "install_method": req.install_method,
        "verification_method": req.verification_method,
        "required_version": req.required_version,
    }


def _serialize_preflight(preflight) -> dict | None:
    if preflight is None:
        return None
    return {
        "overall_ready": preflight.overall_ready,
        "missing": [
            {"name": r.name, "type": r.type} for r in preflight.missing_requirements
        ],
        "installed": [
            {"requirement_id": r.requirement_id, "version": r.detected_version}
            for r in preflight.results
            if r.present
        ],
        "warnings": list(preflight.warnings),
    }


def build_phase1_prompt(
    council_input: CouncilInput,
    role_prompt: str,
    max_variants: int = 3,
) -> str:
    """Build a Phase-1 prompt for one agent.

    The prompt contains the agent's role context plus ALL CouncilInput data.
    It contains NO references to other agents or their proposals.
    """

    reqs_json = json.dumps(
        [_serialize_requirement(r) for r in council_input.requirements],
        indent=2,
        ensure_ascii=False,
    )
    preflight_json = json.dumps(
        _serialize_preflight(council_input.preflight),
        indent=2,
        ensure_ascii=False,
    ) if council_input.preflight else "{}"

    adapter_info = ""
    if council_input.adapter_requirements:
        adapter_info = json.dumps(council_input.adapter_requirements, indent=2, ensure_ascii=False)

    files = "\n".join(council_input.project_files) if council_input.project_files else "(keine)"

    return f"""{role_prompt}

============================================================
PROJEKT: {council_input.project_id}
STACK: {council_input.detected_stack or "unbekannt"}
PLATTFORM: {council_input.platform}
MAXIMALE ANZAHL VARIANTEN: {max_variants}
============================================================

REQUIREMENTS (aus Discovery + Validation):
{reqs_json}

PREFLIGHT (was ist bereits installiert?):
{preflight_json}

ADAPTER INFORMATION (von der Stack-Erkennung):
{adapter_info or "(keine)"}

PROJEKTDATEIEN:
{files}

============================================================
AUFGABE:

Erzeuge {max_variants} technisch UNTERSCHIEDLICHE Toolchain-Varianten
aus DEINER Perspektive.  Jede Variante muss eine vollständige,
ausführbare Toolchain beschreiben.

Jede Variante muss im JSON das Feld "variant_id" enthalten.
Verwende IDs wie: "<dein-agent>-var-1", "<dein-agent>-var-2", etc.

Antworte NUR mit validem JSON — kein Begleittext, keine Erklärungen.

JSON-SCHEMA:
{_PHASE1_JSON_SCHEMA}
"""


# ==========================================================================
# PHASE 2 — Cross-Review Prompt-Präambeln
# ==========================================================================

AGENT_ROLE_ENV_ARCHITECT_REVIEW = """\
Du bist der Environment Architect im CROSS-REVIEW des Councils.

Bewerte JEDE der folgenden Varianten AUSSCHLIESSLICH aus Environment-Sicht.
Bewerte deine eigenen Vorschläge genauso kritisch wie die der anderen Agenten.
"""

AGENT_ROLE_TOOLCHAIN_REVIEW = """\
Du bist der Toolchain Integrator im CROSS-REVIEW des Councils.

Bewerte JEDE der folgenden Varianten AUSSCHLIESSLICH aus Toolchain-Sicht.
Bewerte deine eigenen Vorschläge genauso kritisch wie die der anderen Agenten.
"""

AGENT_ROLE_RISK_REVIEW = """\
Du bist der Risk & Feasibility Assessor im CROSS-REVIEW des Councils.

Bewerte JEDE der folgenden Varianten AUSSCHLIESSLICH aus Risiko-Sicht.
Bewerte deine eigenen Vorschläge genauso kritisch wie die der anderen Agenten.
"""

_PHASE2_SCORING_INSTRUCTION = """\
BEWERTUNGSKRITERIEN (jeweils 1–5, wobei 1 = schlecht, 5 = hervorragend):

- plausibility:     Ist diese Variante technisch realistisch umsetzbar?
- completeness:     Deckt die Toolchain alle Requirements ab?
- complexity:       Wie aufwändig ist der Setup? (1 = sehr komplex, 5 = trivial)
- risk:             Wie riskant ist diese Variante? (1 = sehr riskant, 5 = kaum Risiko)
- ci_cd_fitness:    Wie gut passt diese Variante in CI/CD-Workflows?
- maintainability:  Wie gut ist sie langfristig wartbar?
- cost_efficiency:  Wie kosteneffizient (Tools, Lizenzen, Zeit)?

ZUSÄTZLICH (pro Variante):
- concerns:         Was bereitet dir Sorgen an dieser Variante?
- would_recommend:  Würdest du diese Variante empfehlen? (true/false)
- reasoning:        Warum (nicht)? Kurze Begründung.
"""


def build_phase2_review_prompt(
    variants_json: str,
    role_review_prompt: str,
) -> str:
    """Build a Phase-2 cross-review prompt for one agent.

    Contains ALL variant proposals (from all agents) and the agent's
    role-specific review instruction.  Does NOT contain other agents' votes.
    """

    return f"""{role_review_prompt}

{_PHASE2_SCORING_INSTRUCTION}

============================================================
ALLE VARIANTEN (aus Phase 1 — von allen Agenten):
{variants_json}
============================================================

AUFGABE: Bewerte JEDE Variante aus deiner Perspektive.
Antworte NUR mit validem JSON — kein Begleittext.

JSON-SCHEMA:
{{
  "agent_role": "deine-rolle",
  "votes": [
    {{
      "variant_id": "A1-var-1",
      "scores": {{
        "plausibility": 4,
        "completeness": 3,
        "complexity": 2,
        "risk": 3,
        "ci_cd_fitness": 4,
        "maintainability": 3,
        "cost_efficiency": 4
      }},
      "would_recommend": true,
      "reasoning": "Warum diese Bewertung?",
      "concerns": ["Sorge 1", "Sorge 2"]
    }}
  ]
}}
"""


# ==========================================================================
# PHASE 3 — Chairman Prompt
# ==========================================================================

CHAIRMAN_SYSTEM_PROMPT = """\
Du bist der CHAIRMAN des AI Dev Center Engineering Councils.
Du bist ein NEUTRALER SYNTHESIZER — kein kreativer Agent.

DEINE NUR-AUFGABEN (ausschließlich diese, nichts anderes):

1. DUPLIKATERKENNUNG:
   Finde inhaltlich ähnliche Varianten.  Kriterien: gleiche Environment +
   gleicher Hardware-Target + >70 % Tool-Überschneidung.
   Dokumentiere jeden Merge in "merge_decisions".

2. MERGE:
   Führe ähnliche Varianten zusammen.  Kombiniere advantages, disadvantages,
   risks (entferne Duplikate).  Vereinige Toolchains (gleiches Tool nur
   einmal, kombiniere Informationen).  Vermerke in "merged_from" die
   ursprünglichen variant_ids.  Vermerke in "origin_agents", welche Agenten
   zur Variante beigetragen haben.

3. RANKING:
   Ranke die konsolidierten Varianten anhand der Agenten-Votes.
   Gewichtung: average_scores (60 %), consensus_level (25 %),
   agent_diversity (15 %).

   consensus_level:
   - strong_consensus:       alle Agenten empfehlen (würden empfehlen)
   - weak_consensus:         Mehrheit empfiehlt
   - controversial:          genau 50:50
   - strong_consensus_against: alle lehnen ab

4. EMPFEHLUNG:
   Empfiehl die bestplatzierte Variante (recommendation = variant_id).
   Begründe die Empfehlung im Feld "reasoning" mit konkreten Verweisen
   auf Agenten-Scores und -Aussagen.

5. DISSENS:
   Dokumentiere im Feld "minority_opinions", wenn Agenten fundamental
   uneinig sind.  Verschweige keine Minderheitsmeinung.

WICHTIGE REGELN:
- ERFINDE KEINE NEUEN VARIANTEN.  Alle variant_ids müssen aus Phase 1
  stammen oder dokumentierte Merges sein.
- Löse Konflikte nicht autoritär auf — dokumentiere sie.
- Jede Aussage muss auf konkrete Agenten-Votes zurückführbar sein.
"""


def build_chairman_prompt(
    proposals_json: str,
    votes_json: str,
    council_input: CouncilInput | None = None,
) -> str:
    """Build the Phase-3 Chairman prompt."""

    project_id = council_input.project_id if council_input else "unbekannt"
    stack = council_input.detected_stack or "unbekannt" if council_input else "unbekannt"

    return f"""{CHAIRMAN_SYSTEM_PROMPT}

============================================================
PROJEKT: {project_id}
STACK: {stack}
============================================================

VORSCHLÄGE (Phase 1 — alle Agenten):
{proposals_json}

BEWERTUNGEN (Phase 2 — alle Agenten):
{votes_json}

============================================================
AUFGABE: Synthetisiere die Vorschläge und Bewertungen.
Antworte NUR mit validem JSON — kein Begleittext.

JSON-SCHEMA:
{{
  "merge_decisions": [
    {{
      "merged_variant_ids": ["A1-var-1", "A2-var-2"],
      "resulting_variant_id": "merged-1",
      "reason": "Beide beschreiben dieselbe Environment mit >70 % Tool-Überschneidung"
    }}
  ],
  "variants": [
    {{
      "id": "merged-1",
      "name": "Sprechender Name",
      "description": "Kurzbeschreibung",
      "origin_agents": ["A1", "A2"],
      "merged_from": ["A1-var-1", "A2-var-2"],
      "rank": 1,
      "total_score": 4.3,
      "consensus_level": "strong_consensus",
      "minority_opinions": [],
      "environment": "host",
      "hardware_target": null,
      "connection": null,
      "capabilities": ["build", "compile_check"],
      "toolchain": [
        {{
          "requirement_ref": "req-1",
          "name": "python",
          "type": "executable",
          "install_method": null,
          "version": null,
          "purpose": "Python runtime",
          "depends_on": [],
          "state": "already_installed",
          "environment_constraint": null
        }}
      ],
      "advantages": ["Vorteil 1"],
      "disadvantages": ["Nachteil 1"],
      "risks": ["Risiko 1"],
      "confidence": 0.9,
      "feasibility": "high",
      "verification": "esphome version"
    }}
  ],
  "rejected_variants": [
    {{
      "id": "A3-var-2",
      "name": "Verworfene Variante",
      "description": "",
      "origin_agents": ["A3"],
      "merged_from": [],
      "rank": 99,
      "total_score": 1.5,
      "consensus_level": "strong_consensus_against",
      "minority_opinions": [],
      "environment": "host",
      "hardware_target": null,
      "connection": null,
      "capabilities": [],
      "toolchain": [],
      "advantages": [],
      "disadvantages": [],
      "risks": [],
      "confidence": 0.1,
      "feasibility": "low",
      "verification": ""
    }}
  ],
  "recommendation": "merged-1",
  "reasoning": "Begründung mit Verweis auf Agenten-Scores …"
}}
"""