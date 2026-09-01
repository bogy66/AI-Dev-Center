# AI-Dev-Center

AI-Dev-Center unterstützt die kontrollierte Entwicklung neuer und bestehender Software-, Firmware- und Hardwareprojekte – von der Projektanalyse und Anforderungsklärung über technische Entscheidungen, Setup und Implementierung bis zu Tests, Review, Freigabe und sicherer Versionsverwaltung. Dazu gehören Greenfield-Entwicklung, bestehende Git/GitHub-Repositories, Multi-Language- und Multi-Toolchain-Projekte sowie ESPHome-, Embedded- und Mikrocontroller-Projekte. Bei bestehenden Projekten respektiert AI-Dev-Center deren Architektur, Konventionen, Frameworks, Build-Systeme, Tests und Toolchains, statt sie in eine bevorzugte Zielarchitektur zu zwingen.

Ein Engineering Council bewertet mehrere Lösungsvarianten, bevor der ausgewählte Vorschlag in einen kontrollierten `SetupPlan` materialisiert wird. Planung installiert nichts: Änderungen brauchen zuerst eine explizite menschliche Freigabe und werden anschließend in einem separaten Schritt ausgeführt. Web, CLI, MCP und Agenten sind Integrationsadapter über einem kanonischen Application-Workflow. Hardware-nahe Unterstützung hebt keine Sicherheitsgrenze auf: Flash, OTA, Geräteaktivierung, Deployment und andere physische Eingriffe bleiben hinter den dafür vorgesehenen Human Approvals und sind nicht Teil des Controlled Git Stage.

Nach dem kontrollierten Setup kann die Development Stage strukturierte Entwicklungsänderungen erzeugen. Der Developer Agent liefert dabei deklarative Changes statt Shell-Aktionen; ausschließlich ein separater File Applier setzt validierte Änderungen innerhalb des Projekt-Roots um.

Teständerungen und Testausführung bleiben ebenfalls getrennt: Ein Generator liefert strukturierte Test-Changes, während ein Git-freier, allowlist-basierter Runner nur die vorgesehene Testaktion ausführt. Der kanonische Development-Testing-Ablauf verbindet Entwicklungsänderungen, Teständerungen, kontrolliertes Anwenden, reale Testausführung und Diagnose in dieser Reihenfolge. AI-Dev-Center führt dabei keine beliebigen LLM-generierten Shell-Kommandos aus.

Nach erfolgreich ausgeführtem und zuvor freigegebenem Setup kann der kanonische Ablauf diese Stufen verbinden: strukturierte Entwicklungsänderungen, strukturierte Teständerungen, kontrolliertes Anwenden, reale Tests und Diagnosis/Review. Reale Testergebnisse haben Vorrang vor KI-Diagnosen: Bei einem strukturierten `rework_required` darf genau ein kontrollierter, erneut real getesteter Rework-Durchlauf folgen; ein weiteres `rework_required` beendet den Lauf. Ein finales `accepted` wartet anschließend auf eine davon getrennte menschliche Final Approval; erst deren ausdrückliches `approved` bedeutet `ready_for_git`. Danach kann ein eigener, expliziter Controlled Git Stage ausschließlich die sicher zu diesem Run gehörenden Dateien lokal committen. Ein unbegrenzter Auto-Retry und Publish gehören nicht zu diesem Ablauf. Bestehende Projekte bleiben bei ihren Konventionen, während weitere kontrollierte Toolchain-Runner eine spätere Erweiterung ermöglichen.

Für jede kontrolliert angewendete Datei hält AI-Dev-Center run-spezifische Change-Provenance fest: ursprünglicher Zustand, resultierender Hash, Phase und vorhandener Git-Zustand. Der lokale Commit wird blockiert, sobald Mixed Provenance, vorherige Benutzeränderungen, fremde Index-Inhalte oder ein abweichender finaler Hash vorliegen. Gestaged werden nur vollständig validierte Whole Files dieses Runs; automatische Hunk-Auswahl findet nicht statt.

Ein erfolgreicher lokaler Commit erzeugt lediglich `ready_for_publish` und eine davon getrennte, zunächst `pending` Publish Approval. Erst deren ausdrückliches `approved` erlaubt einen weiteren expliziten Controlled Publish Stage: Er pusht exakt den persistierten Run-Commit über eine explizite Branch-Refspec zu einem bereits konfigurierten Git-Remote. Ein fehlendes Remote, Detached HEAD, ein fremder lokaler Folge-Commit, Authentifizierungsfehler oder Non-Fast-Forward führen fail-safe zu `failed`. Es gibt weder Force Push noch automatische Merge-/Rebase-Reparatur. Publish bedeutet hier ausschließlich Git-Remote-Push – nicht Release, Pull Request, Merge, Deployment, Hardware-Flash, OTA oder Package-/Artifact-Publishing.

Der Central Diagnostic Trace ergänzt den fachlichen Workflow als persistente, run-spezifische und geordnete Diagnose-Timeline. Er dokumentiert erreichte Phasen, strukturierte Resultate, getrennte Approval-Grenzen sowie Git-/Publish-Endzustände mit monotoner Sequenz und UTC-Zeit. Workflow State bleibt Eigentümer aller fachlichen Entscheidungen; Python Logging bleibt Entwickler-Logging; der Trace ersetzt weder Approval noch Business State. Persistiert werden ausschließlich allowlist-basierte, redigierte Metadaten – keine Datei-Inhalte, Environment-Dumps, Request Header, Prompts, Tokens oder Credential-URLs. Die Timeline bleibt nach Prozess-Neustarts lesbar, ist aber weder Event-Sourcing-System noch kryptographische Audit Chain oder Distributed-Tracing-Backend.

Read-only kann der Central Trace für eine Web-Session über `GET /api/workflow/<session_id>/diagnostic-trace` abgerufen werden. Der Adapter delegiert dabei an den kanonischen Application Service und öffnet keine frei wählbaren Trace-Dateien.

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
