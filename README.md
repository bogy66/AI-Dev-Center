# AI-Dev-Center

AI-Dev-Center unterstützt die kontrollierte Entwicklung neuer und bestehender Software-, Firmware- und Hardwareprojekte – von der Projektanalyse und Anforderungsklärung über technische Entscheidungen, Setup und Implementierung bis zu Tests, Review, Freigabe und sicherer Versionsverwaltung.

**Existing Project Intelligence** analysiert vorhandene Repositories zunächst read-only: Sprachen, Frameworks, Package- und Build-Systeme, Testsysteme, Firmware-Indikatoren, CI- und Dokumentations-Hinweise werden deterministisch und evidence-basiert erkannt. Die Inspection bleibt vollständig schreibfrei — sie führt weder Projektcode noch Build-Kommandos, Dependency-Installationen oder Hardware-Aktionen aus. Bestehende Architektur, Konventionen und Toolchains werden als Fakten respektiert, nicht durch bevorzugte Zielarchitekturen ersetzt. Sensitive Inhalte wie ``.env``, private Schlüssel und Credential-Manifeste werden an der Inspection-Grenze zurückgehalten und gelangen niemals an nachgelagerte LLM-Provider oder in den Diagnostic Trace. Gemischte Repositories mit mehreren technologischen Bereichen (z. B. Python-Backend, TypeScript-Frontend, C++-Firmware, ESPHome-Konfiguration) werden in getrennten Project Areas abgebildet.

Ein Engineering Council bewertet mehrere Lösungsvarianten, bevor der ausgewählte Vorschlag in einen kontrollierten `SetupPlan` materialisiert wird. Planung installiert nichts: Änderungen brauchen zuerst eine explizite menschliche Freigabe und werden anschließend in einem separaten Schritt ausgeführt. Web, API, CLI und MCP sind Integrationsadapter über demselben kanonischen Application-Workflow; sie stellen keine konkurrierenden Business-Workflows dar. Verbliebene Legacy-Klassen dienen ausschließlich Test- und Kompatibilitätszwecken und sind nicht mehr aus diesen produktiven Adaptern erreichbar. Hardware-nahe Unterstützung hebt keine Sicherheitsgrenze auf: Flash, OTA, Geräteaktivierung, Deployment und andere physische Eingriffe bleiben hinter den dafür vorgesehenen Human Approvals und sind nicht Teil des Controlled Git Stage.

Nach dem kontrollierten Setup kann die Development Stage strukturierte Entwicklungsänderungen erzeugen. Der Developer Agent liefert dabei deklarative Changes statt Shell-Aktionen; ausschließlich ein separater File Applier setzt validierte Änderungen innerhalb des Projekt-Roots um.

Teständerungen und Testausführung bleiben ebenfalls getrennt: Ein Generator liefert strukturierte Test-Changes, während ein Git-freier Runner nur eine zentral registrierte Test-Capability ausführt. Der kanonische Development-Testing-Ablauf verbindet Entwicklungsänderungen, Teständerungen, kontrolliertes Anwenden, reale Testausführung und Diagnose in dieser Reihenfolge. AI-Dev-Center führt dabei keine beliebigen LLM-generierten Shell-Kommandos aus.

**Generalized Verification** leitet aus der Project Intelligence automatisch einen strukturierten, area-spezifischen VerificationPlan ab. Für erkannte Firmware-/Embedded-Bereiche werden kontrollierte, hardwarefreie Verification-Schritte angeboten: ESPHome Config-Validierung und Compile; PlatformIO Build und native Hardware-freie Tests; CMake Configure und Build. Kein Runner führt Flash, Upload, OTA, Serial Monitor oder Device-Provisioning aus. PlatformIO `extra_scripts` und andere Build-Code-Trust-Grenzen werden erkannt und blockieren die automatische Ausführung — der VerificationStep wird `unsupported` statt blind gestartet. Fehlende Toolchains (ESPHome, PlatformIO, CMake) führen zu `tool_unavailable` — Verification installiert niemals selbst Tools. Dependency-Ordering (z.B. validate→compile, configure→build) blockiert abhängige Steps, wenn Vorgänger fehlschlagen. `tool_unavailable` und `unsupported` sind kein `PASS`.

Nach erfolgreich ausgeführtem und zuvor freigegebenem Setup kann der kanonische Ablauf diese Stufen verbinden: strukturierte Entwicklungsänderungen, strukturierte Teständerungen, kontrolliertes Anwenden, reale Tests und Diagnosis/Review. Reale Testergebnisse haben Vorrang vor KI-Diagnosen: Bei einem strukturierten `rework_required` darf genau ein kontrollierter, erneut real getesteter Rework-Durchlauf folgen; ein weiteres `rework_required` beendet den Lauf. Ein finales `accepted` wartet anschließend auf eine davon getrennte menschliche Final Approval; erst deren ausdrückliches `approved` bedeutet `ready_for_git`. Danach kann ein eigener, expliziter Controlled Git Stage ausschließlich die sicher zu diesem Run gehörenden Dateien lokal committen. Ein unbegrenzter Auto-Retry und Publish gehören nicht zu diesem Ablauf. Bestehende Projekte bleiben bei ihren Konventionen, während weitere kontrollierte Toolchain-Runner eine spätere Erweiterung ermöglichen.

Für jede kontrolliert angewendete Datei hält AI-Dev-Center run-spezifische Change-Provenance fest: ursprünglicher Zustand, resultierender Hash, Phase und vorhandener Git-Zustand. Der lokale Commit wird blockiert, sobald Mixed Provenance, vorherige Benutzeränderungen, fremde Index-Inhalte oder ein abweichender finaler Hash vorliegen. Gestaged werden nur vollständig validierte Whole Files dieses Runs; automatische Hunk-Auswahl findet nicht statt.

Ein erfolgreicher lokaler Commit erzeugt lediglich `ready_for_publish` und eine davon getrennte, zunächst `pending` Publish Approval. Erst deren ausdrückliches `approved` erlaubt einen weiteren expliziten Controlled Publish Stage: Er pusht exakt den persistierten Run-Commit über eine explizite Branch-Refspec zu einem bereits konfigurierten Git-Remote. Ein fehlendes Remote, Detached HEAD, ein fremder lokaler Folge-Commit, Authentifizierungsfehler oder Non-Fast-Forward führen fail-safe zu `failed`. Es gibt weder Force Push noch automatische Merge-/Rebase-Reparatur. Publish bedeutet hier ausschließlich Git-Remote-Push – nicht Release, Pull Request, Merge, Deployment, Hardware-Flash, OTA oder Package-/Artifact-Publishing.

Der Central Diagnostic Trace ergänzt den fachlichen Workflow als persistente, run-spezifische und geordnete Diagnose-Timeline. Er dokumentiert erreichte Phasen, strukturierte Resultate, getrennte Approval-Grenzen sowie Git-/Publish-Endzustände mit monotoner Sequenz und UTC-Zeit. Workflow State bleibt Eigentümer aller fachlichen Entscheidungen; Python Logging bleibt Entwickler-Logging; der Trace ersetzt weder Approval noch Business State. Persistiert werden ausschließlich allowlist-basierte, redigierte Metadaten – keine Datei-Inhalte, Environment-Dumps, Request Header, Prompts, Tokens oder Credential-URLs. Die Timeline bleibt nach Prozess-Neustarts lesbar, ist aber weder Event-Sourcing-System noch kryptographische Audit Chain oder Distributed-Tracing-Backend.

Read-only kann der Central Trace für eine Web-Session über `GET /api/workflow/<session_id>/diagnostic-trace` abgerufen werden. Der Adapter delegiert dabei an den kanonischen Application Service und öffnet keine frei wählbaren Trace-Dateien.

Mutierende kanonische Ausführungen sind pro normalisiertem Projektpfad exklusiv: Setup, Development/Testing/Rework, Controlled Git und Controlled Publish können für denselben Projektbestand nicht gleichzeitig laufen. Ihr run- und stage-spezifischer Lifecycle (`started`, `completed`, `failed`, `recovery_required`) wird im bestehenden Workflow State persistiert. Bleibt nach Prozessabbruch ein `started`-Zustand ohne lokalen Owner zurück, wird die Mutation nicht automatisch wiederholt; ein erneuter Request stoppt kontrolliert mit `recovery_required`. Damit werden insbesondere nicht-idempotente Setup-, LLM- und Dateioperationen nicht blind erneut ausgeführt. Planning bleibt davon getrennt und read-only. Final Approval und Publish Approval bleiben eigenständige menschliche Grenzen.

Controlled Git markiert einen erzeugten Run-Commit zusätzlich lokal und bindet eine eng begrenzte Crash-Recovery an den vorher persistierten HEAD, die exakten Provenance-Pfade und deren finale Hashes. Ein beliebiger aktueller oder fremder Commit genügt nie als Recovery-Beweis. Der aktuelle Web-Start nutzt einen einzelnen Uvicorn-Worker; die Projekt-Ownership ist daher eine Garantie des unterstützten lokalen Single-Process-Betriebs und kein Distributed-Lock- oder Multi-Node-Consensus-System.

## Kanonischer Setup-Flow

```text
User Input → Adapter → Application Service → Project Inspection → CommonRequest
→ DevelopmentWorkflow → Discovery → Validation → Preflight → Engineering Council
→ ToolchainMaterializer → SetupPlan → Human Approval → Execution
```

Der Council empfiehlt, der Materializer erzeugt den Plan, und nur die getrennte Execution nach Approval kann Installationen ausführen. Die drei Grenzen Setup Approval, Final Approval und Publish Approval bleiben voneinander unabhängig. Legacy-Agentklassen bleiben für Tests und Kompatibilität erhalten, sind jedoch kein produktiver alternativer Orchestrierungspfad.

## Docker runtime

Docker is the intended production runtime. The core image provides AI‑Dev‑Center with healthcheck, non‑root execution and persistent volumes for workflow state, diagnostic traces and plan storage.

Toolchains (ESPHome, PlatformIO, CMake) are **not** preinstalled in the core image. Verification reports `tool_unavailable` when a required tool is missing; tool installation follows the central SetupPlan–Human‑Approval–Execution path.

```bash
docker compose build
docker compose up -d
```

The core container runs without privileged mode, without Docker‑socket access and without device mounts. Project code and build tool invocations are treated as untrusted and execute behind a controlled boundary: central approval-based capability registration bound to executable identity, denied‑argument patterns, timeout and output limits. Future toolchains enter through Project Intelligence → Engineering Council → Chairman approval → Human Approval → controlled capability registration → controlled execution; approval never authorizes arbitrary shell commands, images, argv, mounts or devices.

## Web local (development)

```bash
python -m uvicorn app.web_api:app --host 127.0.0.1 --port 8010
```

## Web (Docker)

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
