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
