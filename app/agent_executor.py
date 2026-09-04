from app.ollama_client import OllamaClient
from app.logger import get_logger
import time


logger = get_logger("agent")


class AgentExecutor:

    def __init__(
        self,
        model="llama3.2:3b"
    ):
        self.llm = OllamaClient(
            model=model
        )

    def run(
        self,
        agent_role,
        task,
        project_context="",
        role_name="",
        max_tokens=400
    ):

        start = time.time()

        logger.info(
            f"START role={agent_role[:50]} task={task[:80]}"
        )

        prompt = f"""
Du bist Teil eines professionellen KI-Entwicklerteams.

Deine Rolle:

{agent_role}

Deine interne Rolle heißt:

{role_name}

Projektkontext:

{project_context}

Aufgabe:

{task}

Arbeite nach diesen Regeln:

- Erst analysieren
- Bestehende Architektur beachten
- Keine unnötigen Technologien vorschlagen
- Vorhandene Komponenten bevorzugen
- Konkrete technische Änderungen erstellen
"""

        if role_name == "developer":
            prompt += """
Du bist der Entwickler.

Du arbeitest direkt am bestehenden Projekt.

Deine Aufgabe ist es, konkrete Änderungen am Code vorzubereiten.

Regeln:

- Analysiere zuerst die bestehende Struktur.
- Verwende vorhandene Dateien und Komponenten.
- Erfinde keine Dateien ohne Begründung.
- Gib bei Änderungen den vollständigen neuen Dateiinhalt aus.
- Erzeuge keine allgemeinen Empfehlungen.
- Beschreibe keine hypothetische Architektur.
- Liefere konkrete, umsetzbare Änderungen.

Verwende exakt dieses Ausgabeformat:

## Analyse

Beschreibe kurz, was geändert werden muss und warum.

## Dateien

Für jede Änderung:

### Datei:
Relativer Pfad zur Datei.

### Aktion:
create / update / delete

### Inhalt:
Bei create oder update der vollständige Dateiinhalt.
Bei delete keinen Inhalt ausgeben.

## Tests

Liste die Tests auf, die nach der Änderung ausgeführt werden müssen.
"""

        else:
            prompt += """
Arbeite deine Aufgabe strukturiert ab.

Verwende dieses Ausgabeformat:

## Analyse

Beschreibe das Problem und die Auswirkungen.

## Betroffene Bereiche

Liste Module, Dateien oder Komponenten auf.

## Empfehlung

Beschreibe die sinnvollste technische Lösung.

## Nächste Schritte

Erstelle eine Reihenfolge der Umsetzung.
"""

        logger.info(
            f"PROMPT chars={len(prompt)}"
        )

        result = self.llm.generate(
            prompt,
            max_tokens=max_tokens
        )

        duration = time.time() - start

        logger.info(
            f"END duration={duration:.2f}s response_chars={len(result)}"
        )

        return result


class ProviderAgentExecutor(AgentExecutor):
    """Use the configured productive provider for non-Council agent roles."""

    _STRUCTURED_CHANGE_PROMPT = (
        "Return ONLY a valid JSON object with exactly this structure:\n\n"
        "{\n"
        '  "changes": [\n'
        '    {"file": "relative/path", "action": "create", "content": "complete file content"},\n'
        '    {"file": "relative/path", "action": "update", "content": "complete file content"},\n'
        '    {"file": "relative/path", "action": "delete", "content": ""}\n'
        "  ],\n"
        '  "tests": ["test description or command"]\n'
        "}\n\n"
        "Rules:\n"
        "- Use relative project paths only. No absolute paths, no path traversal.\n"
        "- action must be exactly create, update or delete.\n"
        "- For create/update, provide the complete resulting file content.\n"
        "- For delete, provide an empty string as content.\n"
        "- No markdown, no commentary outside the JSON.\n"
        "- Do not propose execution commands as file changes.\n"
    )

    _DEVELOPER_PROMPT = (
        "You are the Developer of AI-Dev-Center.\n"
        "Your responsibility is to propose concrete file changes.\n"
        "You never apply changes yourself.\n\n"
    ) + _STRUCTURED_CHANGE_PROMPT

    def __init__(self, provider):
        self._provider = provider

    def run(self, agent_role, task, project_context="", role_name="", max_tokens=None):
        if role_name == "developer":
            prompt = (
                f"Role: {agent_role}\nInternal role: {role_name}\n"
                f"Project context:\n{project_context}\nTask:\n{task}\n"
            )
            prompt += self._DEVELOPER_PROMPT
        elif role_name == "tester":
            prompt = (
                self._STRUCTURED_CHANGE_PROMPT
                + "You are the Tester of AI-Dev-Center.\n"
                "Your responsibility is to create or update test files "
                "for the project.\n"
                "You never execute tests yourself.\n\n"
                "Create new test files or update existing test files "
                "to cover the task below.\n"
                "Use the existing project structure and conventions.\n\n"
                f"Project context:\n{project_context}\n"
                f"Task:\n{task}\n"
            )
        elif role_name == "reviewer":
            prompt = (
                'Return ONLY a valid JSON object with exactly this structure:\n\n'
                '{\n'
                '  "decision": "accepted" | "rework_required",\n'
                '  "summary": "non-empty diagnostic summary"\n'
                '}\n\n'
                "You are the Diagnosis Reviewer of AI-Dev-Center.\n"
                "Your responsibility is to review a test result and decide "
                "whether the current development result should be accepted "
                "or whether rework is required.\n"
                "You do not execute tests or apply changes.\n\n"
                "Review the test result below and return a decision.\n"
                "- accepted: tests passed, output is acceptable.\n"
                "- rework_required: tests failed, timed out, or output indicates a problem.\n\n"
                f"Test result:\n{task}\n"
            )
        else:
            prompt = (
                f"Role: {agent_role}\nInternal role: {role_name}\n"
                f"Project context:\n{project_context}\nTask:\n{task}\n"
            )
            prompt += "Return a concise structured professional result."
        return self._provider.complete(prompt, max_tokens=max_tokens)
