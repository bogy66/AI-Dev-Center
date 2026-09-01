# AI-Dev-Center

AI-Dev-Center analysiert Softwareprojekte und leitet daraus nachvollziehbare technische Setup-Pläne ab. Ein Engineering Council bewertet mehrere Lösungsvarianten, bevor der ausgewählte Vorschlag in einen kontrollierten `SetupPlan` materialisiert wird. Planung installiert nichts: Änderungen brauchen zuerst eine explizite menschliche Freigabe und werden anschließend in einem separaten Schritt ausgeführt. Web, CLI, MCP und Agenten sind Integrationsadapter über einem kanonischen Application-Workflow. Das Ziel ist eine reproduzierbare, nachvollziehbare und kontrollierbare KI-gestützte Entwicklungsumgebung.

Nach dem kontrollierten Setup kann die Development Stage strukturierte Entwicklungsänderungen erzeugen. Der Developer Agent liefert dabei deklarative Changes statt Shell-Aktionen; ausschließlich ein separater File Applier setzt validierte Änderungen innerhalb des Projekt-Roots um.

## Kanonischer Setup-Flow

```text
User Input → Adapter → Application Service → Project Inspection → CommonRequest
→ DevelopmentWorkflow → Discovery → Validation → Preflight → Engineering Council
→ ToolchainMaterializer → SetupPlan → Human Approval → Execution
```

Der Council empfiehlt, der Materializer erzeugt den Plan, und nur die getrennte Execution nach Approval kann Installationen ausführen. Legacy-Agentpfade bleiben für Kompatibilität erhalten, sind aber nicht die Zielarchitektur.

## Web lokal starten

Nach Installation von `requirements.txt`:

```bash
python -m uvicorn app.web_api:app --host 127.0.0.1 --port 8010
```

## Web-API-Beispiel

Planning:

```bash
curl -X POST http://127.0.0.1:8010/api/workflow/start \
  -H 'content-type: application/json' \
  -d '{"project_name":"demo","project_directory":"/path/to/demo","task_description":"Plan setup"}'
```

Mit der zurückgegebenen `session_id` erfolgen Freigabe und Ausführung getrennt:

```bash
curl -X POST http://127.0.0.1:8010/api/workflow/SESSION_ID/approval
curl -X POST http://127.0.0.1:8010/api/workflow/SESSION_ID/execute
```
