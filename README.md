# AI-Dev-Center

AI-Dev-Center analysiert Softwareprojekte und leitet daraus nachvollziehbare technische Setup-Pläne ab. Ein Engineering Council bewertet mehrere Lösungsvarianten, bevor der ausgewählte Vorschlag in einen kontrollierten `SetupPlan` materialisiert wird. Planung installiert nichts: Änderungen brauchen zuerst eine explizite menschliche Freigabe und werden anschließend in einem separaten Schritt ausgeführt. Web, CLI, MCP und Agenten sind Integrationsadapter über einem kanonischen Application-Workflow. Das Ziel ist eine reproduzierbare, nachvollziehbare und kontrollierbare KI-gestützte Entwicklungsumgebung.

Nach dem kontrollierten Setup kann die Development Stage strukturierte Entwicklungsänderungen erzeugen. Der Developer Agent liefert dabei deklarative Changes statt Shell-Aktionen; ausschließlich ein separater File Applier setzt validierte Änderungen innerhalb des Projekt-Roots um.

Teständerungen und Testausführung bleiben ebenfalls getrennt: Ein Generator liefert strukturierte Test-Changes, während ein Git-freier, allowlist-basierter Runner nur die vorgesehene Testaktion ausführt. Der kanonische Development-Testing-Ablauf verbindet Entwicklungsänderungen, Teständerungen, kontrolliertes Anwenden, reale Testausführung und Diagnose in dieser Reihenfolge. AI-Dev-Center führt dabei keine beliebigen LLM-generierten Shell-Kommandos aus.

Nach erfolgreich ausgeführtem und zuvor freigegebenem Setup kann der kanonische Ablauf diese Stufen verbinden: strukturierte Entwicklungsänderungen, strukturierte Teständerungen, kontrolliertes Anwenden, reale Tests und Diagnosis/Review. Reale Testergebnisse haben Vorrang vor KI-Diagnosen: Bei einem strukturierten `rework_required` darf genau ein kontrollierter, erneut real getesteter Rework-Durchlauf folgen; ein weiteres `rework_required` beendet den Lauf. Ein finales `accepted` wartet anschließend auf eine davon getrennte menschliche Final Approval; erst deren ausdrückliches `approved` bedeutet `ready_for_git`. Ein unbegrenzter Auto-Retry, Git und Publish gehören nicht zu diesem Stage. Bestehende Projekte bleiben bei ihren Konventionen, während weitere kontrollierte Toolchain-Runner eine spätere Erweiterung ermöglichen.

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
