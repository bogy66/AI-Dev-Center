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


Projektkontext:

{project_context}


Aufgabe:

{task}


Arbeite nach diesen Regeln:

- Erst analysieren
- Bestehende Architektur beachten
- Keine unnötigen Technologien vorschlagen
- Änderungen begründen
- Vorhandene Komponenten bevorzugen


Gib deine Antwort strukturiert aus:

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
