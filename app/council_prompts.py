"""Prompt templates for the Multi-KI Engineering Council.

All prompts are pure text.  No LLM calls, no provider logic, no ESP32-specific
content.  Builder functions accept CouncilInput data and return prompt strings.
"""

from __future__ import annotations

import json

from app.council_models import CouncilInput


def _build_intelligence_section(pi: dict | None) -> str:
    """Build a deterministic structured context from project intelligence.

    Never includes source content, secrets, absolute paths or credentials.
    """
    if not isinstance(pi, dict) or not pi:
        return ""
    lines: list[str] = []
    kind = pi.get("project_kind") or ""
    if kind:
        lines.append(f"Projekttyp: {kind}")
    areas = pi.get("area_count")
    if isinstance(areas, int) and areas > 1:
        lines.append(f"Projektbereiche: {areas}")
    langs = pi.get("languages") or ()
    if langs:
        lines.append(f"Sprachen: {', '.join(str(l) for l in langs)}")
    fws = pi.get("frameworks") or ()
    if fws:
        lines.append(f"Frameworks: {', '.join(str(f) for f in fws)}")
    pkgs = pi.get("package_systems") or ()
    if pkgs:
        lines.append(f"Package-Systeme: {', '.join(str(p) for p in pkgs)}")
    blds = pi.get("build_systems") or ()
    if blds:
        lines.append(f"Build-Systeme: {', '.join(str(b) for b in blds)}")
    tests = pi.get("test_systems") or ()
    if tests:
        lines.append(f"Testsysteme: {', '.join(str(t) for t in tests)}")
    fw_inds = pi.get("firmware_indicators") or ()
    if fw_inds:
        lines.append(f"Firmware-Indikatoren: {', '.join(str(f) for f in fw_inds)}")
    truncated = pi.get("truncated")
    if truncated:
        lines.append("(Projektanalyse war unvollständig — Dateilimit erreicht)")
    return "\n".join(lines)


# ==========================================================================
# PHASE 1 — Rollenspezifische Prompt-Präambeln
# ==========================================================================

AGENT_ROLE_ENV_ARCHITECT = """\
AI-Dev-Center ist ein kontrolliertes Engineering-System für die Entwicklung
und Wartung von Software-, Firmware- und Hardware-Projekten.
Du bist Engineering Council Agent A1 (Environment Architect) von AI-Dev-Center.
Deine Verantwortung: analysiere und schlage technische Lösungen aus der
Perspektive der Ausführungsumgebung vor. Du führst keine Änderungen aus und
erteilst keine Human Approval.

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
AI-Dev-Center ist ein kontrolliertes Engineering-System für die Entwicklung
und Wartung von Software-, Firmware- und Hardware-Projekten.
Du bist Engineering Council Agent A2 (Toolchain Integrator) von AI-Dev-Center.
Deine Verantwortung: analysiere und schlage technische Lösungen aus der
Perspektive der Werkzeugkette vor. Du führst keine Änderungen aus und
erteilst keine Human Approval.

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
AI-Dev-Center ist ein kontrolliertes Engineering-System für die Entwicklung
und Wartung von Software-, Firmware- und Hardware-Projekten.
Du bist Engineering Council Agent A3 (Risk & Feasibility Assessor) von AI-Dev-Center.
Deine Verantwortung: analysiere und schlage technische Lösungen aus der
Perspektive von Risiken und Machbarkeit vor. Du führst keine Änderungen aus
und erteilst keine Human Approval.

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
          "requirement_ref": "<existing Requirement.id realized by this item>",
          "name": "python",
          "type": "executable|python_package|system_package|sdk|toolchain|flasher|…",
          "install_method": "pip install esphome" | null,
          "version": "3.12" | null,
          "purpose": "Wofür wird dieses Tool in dieser Variante gebraucht?",
          "depends_on": ["python"],
          "state": "already_installed|needs_install|unavailable",
          "environment_constraint": null,
          "provided_by": null
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
            {"requirement_id": r.id, "name": r.name, "type": r.type}
            for r in preflight.missing_requirements
        ],
        "results": [
            {
                "requirement_id": r.requirement_id,
                "present": r.present,
                "satisfied": r.satisfied,
                "detected_version": r.detected_version,
            }
            for r in preflight.results
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

    intelligence_section = _build_intelligence_section(council_input.project_intelligence)

    return f"""{role_prompt}

============================================================
PROJEKT: {council_input.project_id}
STACK: {council_input.detected_stack or "unbekannt"}
PLATTFORM: {council_input.platform}
MAXIMALE ANZAHL VARIANTEN: {max_variants}
============================================================

EXISTING-PROJECT INTELLIGENCE:
{intelligence_section or "(keine)"}

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

VERBINDLICHER REQUIREMENT-TO-IMPLEMENTATION-VERTRAG:
- Jedes ToolchainItem.requirement_ref MUSS exakt eine vorhandene Requirement.id
  aus CouncilInput referenzieren.
- Das ToolchainItem MUSS eine technische Realisierung genau dieses referenzierten
  Requirements sein. Eine gültige Requirement.id ist kein Platzhalter für eine
  andere Voraussetzung.
- Erfinde keine Requirement IDs und verstecke keine neu entdeckten
  Voraussetzungen unter einer unpassenden requirement_ref.
- Meldet Preflight ein Requirement als satisfied=true, gilt es für das Setup als
  bereits erfüllt. Schlage dafür keine Installation vor und widersprich der
  autoritativen Preflight-Aussage nicht mit state="needs_install".
- Eine explizit unbefriedigte Requirement darf technisch realisiert werden.
- Zusätzliche Voraussetzungen ohne validiertes Requirement müssen ehrlich als
  limitation, disadvantage oder risk beschrieben werden. Sie dürfen weder eine
  erfundene ID erhalten noch unter einer anderen Requirement.id versteckt werden.
- TRANSITIVE BEREITSTELLUNG (provided_by):
  Wenn eine Requirement (z.B. SDK/Framework) durch eine andere in derselben
  Variante existierende Requirement vollständig bereitgestellt und verwaltet wird,
  setze im ToolchainItem der bereitgestellten Requirement das Feld "provided_by"
  auf die requirement_ref des bereitstellenden Items.
  "provided_by" referenziert eine requirement_ref, die in der Toolchain dieser
  Variante vorhanden sein muss. Verwende provided_by nur, wenn die bereitstellende
  Requirement explizit in dieser Variante enthalten ist.
  Ein mit provided_by versehenes ToolchainItem erhält keinen eigenen Setup-Schritt;
  seine Bereitstellung wird durch das referenzierte Item sichergestellt.

Antworte NUR mit validem JSON — kein Begleittext, keine Erklärungen.

JSON-SCHEMA:
{_PHASE1_JSON_SCHEMA}
"""


# ==========================================================================
# PHASE 2 — Cross-Review Prompt-Präambeln
# ==========================================================================

AGENT_ROLE_ENV_ARCHITECT_REVIEW = """\
AI-Dev-Center ist ein kontrolliertes Engineering-System für Software-, Firmware-
und Hardware-Projekte. Du bist Engineering Council Agent A1 (Environment Architect)
von AI-Dev-Center im CROSS-REVIEW des Councils. Du führst keine Änderungen aus
und erteilst keine Human Approval.

Bewerte JEDE der folgenden Varianten AUSSCHLIESSLICH aus Environment-Sicht.
Bewerte deine eigenen Vorschläge genauso kritisch wie die der anderen Agenten.
"""

AGENT_ROLE_TOOLCHAIN_REVIEW = """\
AI-Dev-Center ist ein kontrolliertes Engineering-System für Software-, Firmware-
und Hardware-Projekte. Du bist Engineering Council Agent A2 (Toolchain Integrator)
von AI-Dev-Center im CROSS-REVIEW des Councils. Du führst keine Änderungen aus
und erteilst keine Human Approval.

Bewerte JEDE der folgenden Varianten AUSSCHLIESSLICH aus Toolchain-Sicht.
Bewerte deine eigenen Vorschläge genauso kritisch wie die der anderen Agenten.
"""

AGENT_ROLE_RISK_REVIEW = """\
AI-Dev-Center ist ein kontrolliertes Engineering-System für Software-, Firmware-
und Hardware-Projekte. Du bist Engineering Council Agent A3 (Risk & Feasibility Assessor)
von AI-Dev-Center im CROSS-REVIEW des Councils. Du führst keine Änderungen aus
und erteilst keine Human Approval.

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
AI-Dev-Center ist ein kontrolliertes Engineering-System für die Entwicklung
und Wartung von Software-, Firmware- und Hardware-Projekten.
Du bist der Chairman des AI-Dev-Center Engineering Council.
Deine Verantwortung: vergleiche, synthetisiere und ranke die Council-Vorschläge;
wähle/empfehle eine technische Variante innerhalb des Workflows.
Du führst keine Änderungen aus und erteilst keine Human Approval.

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
   Bestimme zuerst die Menge der zulässigen finalen Varianten anhand ihrer
   controlled_setup-Bewertung.  Eine Variante ist zulässig, wenn
   "automatically_materializable": true ist.
   Existiert mindestens eine automatisch materialisierbare finale Variante,
   MUSS die Empfehlung aus dieser Menge stammen.  Das Vote-Ranking gilt
   innerhalb der zulässigen Menge.
   Eine manual_review-Variante darf nur empfohlen werden, wenn KEINE
   automatisch materialisierbare finale Variante existiert.
   Empfiehl die bestplatzierte zulässige Variante (recommendation = variant_id).
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
    intelligence_section = (
        _build_intelligence_section(council_input.project_intelligence)
        if council_input and council_input.project_intelligence else ""
    )
    requirements_json = json.dumps(
        [_serialize_requirement(r) for r in council_input.requirements],
        indent=2,
        ensure_ascii=False,
    ) if council_input else "[]"
    preflight_json = json.dumps(
        _serialize_preflight(council_input.preflight),
        indent=2,
        ensure_ascii=False,
    ) if council_input and council_input.preflight else "{}"

    return f"""{CHAIRMAN_SYSTEM_PROMPT}

============================================================
PROJEKT: {project_id}
STACK: {stack}
============================================================

EXISTING-PROJECT INTELLIGENCE:
{intelligence_section or "(keine)"}

VALIDIERTE REQUIREMENTS (autoritative IDs und Semantik):
{requirements_json}

AUTHORITATIVE PREFLIGHT BY REQUIREMENT ID:
{preflight_json}

REQUIREMENT-TO-IMPLEMENTATION-VERTRAG FÜR SYNTHESE UND MERGES:
- Bewahre die Bedeutung jeder requirement_ref: Ein ToolchainItem realisiert das
  referenzierte validierte Requirement; die ID ist kein allgemeiner Platzhalter.
- Erfinde keine Requirement IDs, verschiebe kein ToolchainItem zu einer
  unpassenden requirement_ref und erzeuge bei einem Merge keine neuen
  ToolchainItems für Voraussetzungen, die in den Vorschlägen nicht als gültige
  Realisierungen vorhanden waren.
- Requirements mit Preflight satisfied=true bleiben für das Setup erfüllt und
  dürfen nicht wieder zu Installationsanforderungen werden.
- Zusätzliche, nicht modellierte Voraussetzungen bleiben als limitations,
  disadvantages oder risks sichtbar. Verstecke sie niemals unter einer anderen
  Requirement ID.
- KONTROLLIERTES-SETUP-FREIGABEREGEL (ZULASSUNGSREGEL, keine Präferenz):
  Bestimme zuerst, welche finalen Varianten für die Empfehlung unter
  kontrolliertem Setup zulässig sind.  Eine Variante ist zulässig, wenn ihre
  controlled_setup-Bewertung "automatically_materializable": true meldet.
  Existiert mindestens eine automatisch materialisierbare finale Variante,
  MUSS die Empfehlung aus dieser Menge stammen.  Vote-Ranking gilt innerhalb
  der zulässigen Menge.  Eine manual_review-Variante darf nur dann empfohlen
  werden, wenn KEINE automatisch materialisierbare finale Variante existiert.
  Diese Regel erteilt keine Ausführungsautorität; Human Approval und
  kontrollierte Ausführung bleiben unverändert.
- Bei Merges: Bewahre provided_by-Beziehungen aus den ursprünglichen ToolchainItems.
  Entferne kein provided_by ohne technischen Grund.

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
          "environment_constraint": null,
          "provided_by": null
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
