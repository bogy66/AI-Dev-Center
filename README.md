# AI-Dev-Center

AI-Dev-Center unterstützt die kontrollierte Entwicklung neuer und bestehender Software-, Firmware- und Hardwareprojekte – von der Projektanalyse und Anforderungsklärung über technische Entscheidungen, Setup und Implementierung bis zu Tests, Review, Freigabe und sicherer Versionsverwaltung.

**Existing Project Intelligence** analysiert vorhandene Repositories zunächst read-only: Sprachen, Frameworks, Package- und Build-Systeme, Testsysteme, Firmware-Indikatoren, CI- und Dokumentations-Hinweise werden deterministisch und evidence-basiert erkannt. Die Inspection bleibt vollständig schreibfrei — sie führt weder Projektcode noch Build-Kommandos, Dependency-Installationen oder Hardware-Aktionen aus. Bestehende Architektur, Konventionen und Toolchains werden als Fakten respektiert, nicht durch bevorzugte Zielarchitekturen ersetzt. Sensitive Inhalte wie ``.env``, private Schlüssel und Credential-Manifeste werden an der Inspection-Grenze zurückgehalten und gelangen niemals an nachgelagerte LLM-Provider oder in den Diagnostic Trace. Gemischte Repositories mit mehreren technologischen Bereichen (z. B. Python-Backend, TypeScript-Frontend, C++-Firmware, ESPHome-Konfiguration) werden in getrennten Project Areas abgebildet.

Ein Engineering Council bewertet mehrere Lösungsvarianten, bevor der ausgewählte Vorschlag in einen kontrollierten `SetupPlan` materialisiert wird. Planung installiert nichts: Änderungen brauchen zuerst eine explizite menschliche Freigabe und werden anschließend in einem separaten Schritt ausgeführt. Web, API, CLI, MCP und Signal sind Integrationsadapter über demselben zentralen Application-Workflow; sie stellen keine konkurrierenden Business-Workflows dar. Signal-Chats und Projekte stehen über eine persistierte Bindung in einer strikten 1:1-Beziehung: Jeder Chat gehört genau zu einem Projekt und jedes Projekt hat genau einen aktiven Signal-Chat. Normale Nachrichtentexte können die Bindung weder auswählen noch wechseln; Rebinding ist eine explizite administrative Aktion, und ein ungebundener Chat kann keine Projektarbeit starten. Die Bindung transportiert strukturierte Anfragen in den Project Context, speichert keinen Chat-Verlauf als Project Definitions / Memory und erteilt ebenso wenig Human-Approval-Autorität wie eine Signal-Identität oder Freigabeformulierung. Verbliebene Legacy-Klassen dienen ausschließlich Test- und Kompatibilitätszwecken und sind nicht mehr aus diesen produktiven Adaptern erreichbar. Hardware-nahe Unterstützung hebt keine Sicherheitsgrenze auf: Flash, OTA, Geräteaktivierung, Deployment und andere physische Eingriffe bleiben hinter den dafür vorgesehenen Human Approvals und sind nicht Teil des Controlled Git Stage.

Nach dem kontrollierten Setup kann die Development Stage strukturierte Entwicklungsänderungen erzeugen. Der Developer Agent liefert dabei deklarative Changes statt Shell-Aktionen; ausschließlich ein separater File Applier setzt validierte Änderungen innerhalb des Projekt-Roots um.

Teständerungen und Testausführung bleiben ebenfalls getrennt: Ein Generator liefert strukturierte Test-Changes, während ein Git-freier Runner nur eine zentral registrierte Test-Capability ausführt. Der kanonische Development-Testing-Ablauf verbindet Entwicklungsänderungen, Teständerungen, kontrolliertes Anwenden, reale Testausführung und Diagnose in dieser Reihenfolge. AI-Dev-Center führt dabei keine beliebigen LLM-generierten Shell-Kommandos aus.

**Generalized Verification** leitet aus der Project Intelligence automatisch einen strukturierten, area-spezifischen VerificationPlan ab. Für erkannte Firmware-/Embedded-Bereiche werden kontrollierte, hardwarefreie Verification-Schritte angeboten: ESPHome Config-Validierung und Compile; PlatformIO Build und native Hardware-freie Tests; CMake Configure und Build. Kein Runner führt Flash, Upload, OTA, Serial Monitor oder Device-Provisioning aus. PlatformIO `extra_scripts` und andere Build-Code-Trust-Grenzen werden erkannt und blockieren die automatische Ausführung — der VerificationStep wird `unsupported` statt blind gestartet. Fehlende Toolchains (ESPHome, PlatformIO, CMake) führen zu `tool_unavailable` — Verification installiert niemals selbst Tools. Dependency-Ordering (z.B. validate→compile, configure→build) blockiert abhängige Steps, wenn Vorgänger fehlschlagen. `tool_unavailable` und `unsupported` sind kein `PASS`.

Ein `tool_unavailable`-Ergebnis bleibt im zentralen Workflow ein strukturiertes Setup-Bedürfnis und startet niemals selbst eine Installation. Nur ein aus Project Intelligence und Chairman-Council-Daten materialisierter, separat durch einen Menschen genehmigter SetupPlan darf einen registrierten strukturierten Installer ausführen. Vorher und nachher wird die Verfügbarkeit geprüft. Danach kann ausschließlich der persistierte ursprüngliche VerificationPlan über die bestehende Verification-Architektur erneut ausgeführt werden. Setup-Erfolg erteilt keine Capability-Autorisierung.

Nach erfolgreich ausgeführtem und zuvor freigegebenem Setup kann der kanonische Ablauf diese Stufen verbinden: strukturierte Entwicklungsänderungen, strukturierte Teständerungen, kontrolliertes Anwenden, reale Tests und Diagnosis/Review. Reale Testergebnisse haben Vorrang vor KI-Diagnosen: Bei einem strukturierten `rework_required` darf genau ein kontrollierter, erneut real getesteter Rework-Durchlauf folgen; ein weiteres `rework_required` beendet den Lauf. Ein finales `accepted` wartet anschließend auf eine davon getrennte menschliche Final Approval; erst deren ausdrückliches `approved` bedeutet `ready_for_git`. Danach kann ein eigener, expliziter Controlled Git Stage ausschließlich die sicher zu diesem Run gehörenden Dateien lokal committen. Ein unbegrenzter Auto-Retry und Publish gehören nicht zu diesem Ablauf. Bestehende Projekte bleiben bei ihren Konventionen, während weitere kontrollierte Toolchain-Runner eine spätere Erweiterung ermöglichen.

Für jede kontrolliert angewendete Datei hält AI-Dev-Center run-spezifische Change-Provenance fest: ursprünglicher Zustand, resultierender Hash, Phase und vorhandener Git-Zustand. Der lokale Commit wird blockiert, sobald Mixed Provenance, vorherige Benutzeränderungen, fremde Index-Inhalte oder ein abweichender finaler Hash vorliegen. Gestaged werden nur vollständig validierte Whole Files dieses Runs; automatische Hunk-Auswahl findet nicht statt.

Ein erfolgreicher lokaler Commit erzeugt lediglich `ready_for_publish` und eine davon getrennte, zunächst `pending` Publish Approval. Erst deren ausdrückliches `approved` erlaubt einen weiteren expliziten Controlled Publish Stage: Er pusht exakt den persistierten Run-Commit über eine explizite Branch-Refspec zu einem bereits konfigurierten Git-Remote. Ein fehlendes Remote, Detached HEAD, ein fremder lokaler Folge-Commit, Authentifizierungsfehler oder Non-Fast-Forward führen fail-safe zu `failed`. Es gibt weder Force Push noch automatische Merge-/Rebase-Reparatur. Publish bedeutet hier ausschließlich Git-Remote-Push – nicht Release, Pull Request, Merge, Deployment, Hardware-Flash, OTA oder Package-/Artifact-Publishing.

Der Central Diagnostic Trace ergänzt den fachlichen Workflow als persistente, run-spezifische und geordnete Diagnose-Timeline. Er dokumentiert erreichte Phasen, strukturierte Resultate, getrennte Approval-Grenzen sowie Git-/Publish-Endzustände mit monotoner Sequenz und vollständiger ISO-8601-UTC-Zeit. Für lange Provider- und Council-Arbeit werden sichere Aktivitätszustände wie preparing, thinking, waiting, reviewing, completed und failed einschließlich Rolle, Provider- und Modellbezeichnung aufgezeichnet; thinking bezeichnet nur Aktivität und enthält keine interne Modellbegründung. Die Web-Oberfläche projiziert daraus die aktuelle Stage/Rolle und zeigt Trace-Zeitpunkte lokal kompakt als `HH:MM:SS`, während API und Persistenz die vollständige Zeit behalten. Workflow State bleibt Eigentümer aller fachlichen Entscheidungen; Python Logging bleibt Entwickler-Logging; der Trace ersetzt weder Approval noch Business State. Persistiert werden ausschließlich allowlist-basierte, redigierte Metadaten – keine Datei-Inhalte, Environment-Dumps, Request Header, Prompts, Tokens oder Credential-URLs. Die Timeline bleibt nach Prozess-Neustarts lesbar, ist aber weder Event-Sourcing-System noch kryptographische Audit Chain oder Distributed-Tracing-Backend.

Ein unvollständiges Engineering-Council-Ergebnis ist kein zulässiger Eingang für die Toolchain-Materialisierung. Der zentrale Workflow zeichnet diesen Zustand als blockiert auf und beendet die Planung an der Council-Grenze; er erfindet weder ein erfolgreiches Ergebnis noch umgeht er Chairman oder Human Approval.

Der produktive Web-/Workflow-Pfad besitzt einen deterministischen End-to-End-Test, der ausschließlich die externe LLM-Provider-Grenze ersetzt. Jeder Lauf erzeugt Projekt, Konfiguration, Workflow State, Central Diagnostic Trace und Plan Store unter einer eindeutigen `tmp_path`-Umgebung. Erfolgs- und Provider-Fehlerpfad behalten die echten zentralen Services und Approval-Grenzen. Das Fixture löscht in `finally` ausschließlich seinen eigenen Root und prüft dessen Entfernung; permanente Fixtures, Host-Tools sowie fremde Docker-Ressourcen werden weder verändert noch bereinigt.

**Project Definitions / Memory** speichert explizite, strukturierte und dauerhafte Projektentscheidungen, Regeln, Begriffe und Zielzustände – niemals rohe Chat-Verläufe. Project Intelligence bleibt für die beobachtete Repository-Realität zuständig, Project Definitions für bewusst festgelegte Absichten und `config.yml` für seine technischen Konfigurationsfelder. Der zentrale Project Context hält diese Quellen getrennt und meldet Widersprüche strukturiert, statt Werte still zu überschreiben. Nur aktive Definitionen sind effektiv; superseded und revoked Einträge bleiben als Historie erhalten. Definitionen erteilen keinerlei Setup-, Capability-, Execution-, Git-, Publish- oder Hardware-Autorität.

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

The core container runs without privileged mode, without Docker‑socket access and without device mounts. Project code and build tool invocations are treated as untrusted and execute behind a controlled boundary: central approval-aware capability registration binds capability and executable identity, allowed operation type, approval provenance, normalized project scope and active registration status. Future toolchain names can be registered without extending a fixed tool list. Today's global registrations are compatibility defaults, not the architectural source of truth. Dynamic registrations are always project-bound; the same capability may be approved independently for multiple projects. Dynamic registrations enter through Project Intelligence → Engineering Council → Chairman approval → Human Approval → controlled capability registration → controlled execution. Registration cannot authorize arbitrary shell commands, argv policies, images, mounts, devices, host access or automatic installation; denied-argument checks, timeout and output limits remain enforced.

The central application service now opens a capability-specific Human Approval only from the actual Project Intelligence and completed Chairman Council result. It creates `ApprovalProvenance` from those result identifiers and the matching persisted Human Approval record, then calls the existing `CapabilityRegistry.register_approved()` boundary. On restart it restores only complete approved project-bound registrations through that same boundary; pending and rejected approvals are not restored. Capability approval remains independent from setup, Git, publish and physical-hardware approvals.

## Web local (development)

The productive Web GUI opens an existing server-local project root. The typed path or server-side directory selection is validated as an existing directory and used unchanged—AI-Dev-Center does not append the project name or upload directory contents. Invalid and stale recent paths are marked unusable. New-directory creation is not implied by this flow. If central workflow start fails after a session is created, the error response retains the session ID so its safe failed state and Diagnostic Trace remain inspectable.

Web workflow start establishes an observable session first and returns `202 planning`; the existing central planning operation then continues asynchronously while the browser polls live state and the central Diagnostic Trace. Terminal planning errors remain attached to that session rather than turning the accepted start response into a false success.

Setup reads the productive `config/ai-dev-center.yml` contract. Supported primary AI and discovery fields can be validated and atomically persisted; provider/authentication type and the Engineering Council role assignments are shown read-only. Only secret reference names reach the browser—never secret contents. The currently configured Council models, including external provider/model failures, are shown as configured and are not silently replaced based on transient model availability.

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
