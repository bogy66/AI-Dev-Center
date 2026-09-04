// ADC Documentation — comprehensive architecture and system documentation
// Language: German

const DOC_DIAGRAMS = {};
const DOC_TOC = [
  { id: "sec-01", title: "1. ADC in 10 Minuten verstehen" },
  { id: "sec-02", title: "2. Produktziel und Einsatzbereich" },
  { id: "sec-03", title: "3. Gesamtarchitektur" },
  { id: "sec-04", title: "4. Zentraler Workflow" },
  { id: "sec-05", title: "5. Die sechs Subsysteme" },
  { id: "sec-06", title: "6. Units und ihre Verantwortlichkeiten" },
  { id: "sec-07", title: "7. Unit- und Subsystem-Abhängigkeiten" },
  { id: "sec-08", title: "8. Zustands- und Datenfluss" },
  { id: "sec-09", title: "9. Requirement Intelligence" },
  { id: "sec-10", title: "10. Engineering Decision" },
  { id: "sec-11", title: "11. Engineering Council und Chairman" },
  { id: "sec-12", title: "12. Environment & Setup" },
  { id: "sec-13", title: "13. Setup Effects und Setup Capabilities" },
  { id: "sec-14", title: "14. Capability Registry und Controlled Execution" },
  { id: "sec-15", title: "15. Human Approval und Sicherheitsgrenzen" },
  { id: "sec-16", title: "16. Development & Change" },
  { id: "sec-17", title: "17. Quality & Verification" },
  { id: "sec-18", title: "18. Delivery & Outcome" },
  { id: "sec-19", title: "19. Diagnostic Trace" },
  { id: "sec-20", title: "20. Project Intelligence / Definitions / Context" },
  { id: "sec-21", title: "21. Communication Adapter und Frontends" },
  { id: "sec-22", title: "22. MCP-Zielarchitektur" },
  { id: "sec-23", title: "23. LLM / Provider / Model-Architektur" },
  { id: "sec-24", title: "24. Testarchitektur" },
  { id: "sec-25", title: "25. Wichtige Code-Units/Dateien" },
  { id: "sec-26", title: "26. Heutige Implementierung vs. Zielarchitektur" },
  { id: "sec-27", title: "27. Glossar" },
];
const docSections = {};

// ---------------------------------------------------------------------------
// A. Overall ADC Architecture Diagram
// ---------------------------------------------------------------------------
DOC_DIAGRAMS.overall = '<svg viewBox="0 0 900 580" xmlns="http://www.w3.org/2000/svg" class="arch-diagram">' +
  '<defs>' +
  '<marker id="arr-h" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#3182ce"/></marker>' +
  '<marker id="arr-hg" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#718096"/></marker>' +
  '<linearGradient id="sg" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#ebf4ff"/><stop offset="100%" stop-color="#ebf8ff"/></linearGradient>' +
  '</defs>' +
  '<text x="450" y="22" text-anchor="middle" font-size="14" font-weight="700" fill="#1a202c">ADC Gesamtarchitektur</text>' +
  '<rect x="350" y="40" width="200" height="28" rx="4" fill="#edf2f7" stroke="#cbd5e0"/>' +
  '<text x="450" y="59" text-anchor="middle" font-size="11" fill="#2d3748">User Input</text>' +
  '<rect x="80" y="82" width="100" height="24" rx="4" fill="#f7fafc" stroke="#a0aec0"/>' +
  '<text x="130" y="98" text-anchor="middle" font-size="10" fill="#4a5568">Web GUI</text>' +
  '<rect x="195" y="82" width="100" height="24" rx="4" fill="#f7fafc" stroke="#a0aec0"/>' +
  '<text x="245" y="98" text-anchor="middle" font-size="10" fill="#4a5568">Signal</text>' +
  '<rect x="310" y="82" width="100" height="24" rx="4" fill="#f7fafc" stroke="#a0aec0"/>' +
  '<text x="360" y="98" text-anchor="middle" font-size="10" fill="#4a5568">API / CLI</text>' +
  '<rect x="425" y="82" width="100" height="24" rx="4" fill="#f7fafc" stroke="#a0aec0"/>' +
  '<text x="475" y="98" text-anchor="middle" font-size="10" fill="#4a5568">MCP Client</text>' +
  '<rect x="540" y="82" width="90" height="24" rx="4" fill="#e2e8f0" stroke="#cbd5e0" stroke-dasharray="4,2"/>' +
  '<text x="585" y="98" text-anchor="middle" font-size="9" fill="#718096">MCP Ziel-Arch.</text>' +
  '<rect x="645" y="82" width="90" height="24" rx="4" fill="#e2e8f0" stroke="#cbd5e0" stroke-dasharray="4,2"/>' +
  '<text x="690" y="98" text-anchor="middle" font-size="9" fill="#718096">Signal Ziel-Arch.</text>' +
  '<line x1="400" y1="68" x2="130" y2="82" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="420" y1="68" x2="250" y2="82" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="450" y1="68" x2="360" y2="82" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="480" y1="68" x2="475" y2="82" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="500" y1="68" x2="580" y2="82" stroke="#a0aec0" stroke-width="1" stroke-dasharray="4,2"/>' +
  '<line x1="510" y1="68" x2="680" y2="82" stroke="#a0aec0" stroke-width="1" stroke-dasharray="4,2"/>' +
  '<rect x="230" y="122" width="240" height="28" rx="4" fill="#e8f4fd" stroke="#3182ce"/>' +
  '<text x="350" y="140" text-anchor="middle" font-size="11" font-weight="600" fill="#2b6cb0">Communication Adapter</text>' +
  '<line x1="130" y1="106" x2="200" y2="122" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="245" y1="106" x2="260" y2="122" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="360" y1="106" x2="340" y2="122" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="475" y1="106" x2="440" y2="122" stroke="#a0aec0" stroke-width="1"/>' +
  '<rect x="255" y="165" width="190" height="26" rx="4" fill="#f7fafc" stroke="#a0aec0"/>' +
  '<text x="350" y="182" text-anchor="middle" font-size="10" fill="#4a5568">Common Request / Intent</text>' +
  '<line x1="350" y1="150" x2="350" y2="165" stroke="#3182ce" stroke-width="1.5" marker-end="url(#arr-h)"/>' +
  '<rect x="240" y="206" width="220" height="30" rx="4" fill="#3182ce" opacity="0.15" stroke="#3182ce"/>' +
  '<text x="350" y="226" text-anchor="middle" font-size="12" font-weight="700" fill="#2b6cb0">Zentraler ADC Workflow</text>' +
  '<line x1="350" y1="191" x2="350" y2="206" stroke="#3182ce" stroke-width="1.5" marker-end="url(#arr-h)"/>' +
  '<rect x="10" y="255" width="140" height="68" rx="4" fill="url(#sg)" stroke="#3182ce"/>' +
  '<text x="80" y="274" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">1. Requirement</text>' +
  '<text x="80" y="288" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">Intelligence</text>' +
  '<text x="80" y="306" text-anchor="middle" font-size="8" fill="#4a5568">Projektanalyse</text>' +
  '<text x="80" y="318" text-anchor="middle" font-size="8" fill="#4a5568">Anforderungen</text>' +
  '<rect x="158" y="255" width="140" height="68" rx="4" fill="url(#sg)" stroke="#3182ce"/>' +
  '<text x="228" y="274" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">2. Engineering</text>' +
  '<text x="228" y="288" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">Decision</text>' +
  '<text x="228" y="306" text-anchor="middle" font-size="8" fill="#4a5568">Council</text>' +
  '<text x="228" y="318" text-anchor="middle" font-size="8" fill="#4a5568">Technische Entscheidung</text>' +
  '<rect x="306" y="255" width="140" height="68" rx="4" fill="url(#sg)" stroke="#3182ce"/>' +
  '<text x="376" y="274" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">3. Environment</text>' +
  '<text x="376" y="288" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">&amp; Setup</text>' +
  '<text x="376" y="306" text-anchor="middle" font-size="8" fill="#4a5568">SetupPlan</text>' +
  '<text x="376" y="318" text-anchor="middle" font-size="8" fill="#4a5568">Kontrollierte Ausführung</text>' +
  '<rect x="454" y="255" width="140" height="68" rx="4" fill="url(#sg)" stroke="#3182ce"/>' +
  '<text x="524" y="274" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">4. Development</text>' +
  '<text x="524" y="288" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">&amp; Change</text>' +
  '<text x="524" y="306" text-anchor="middle" font-size="8" fill="#4a5568">Strukturierte Änderungen</text>' +
  '<text x="524" y="318" text-anchor="middle" font-size="8" fill="#4a5568">File Applier</text>' +
  '<rect x="602" y="255" width="140" height="68" rx="4" fill="url(#sg)" stroke="#3182ce"/>' +
  '<text x="672" y="274" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">5. Quality</text>' +
  '<text x="672" y="288" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">&amp; Verification</text>' +
  '<text x="672" y="306" text-anchor="middle" font-size="8" fill="#4a5568">Tests</text>' +
  '<text x="672" y="318" text-anchor="middle" font-size="8" fill="#4a5568">VerificationPlan</text>' +
  '<rect x="750" y="255" width="140" height="68" rx="4" fill="url(#sg)" stroke="#3182ce"/>' +
  '<text x="820" y="274" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">6. Delivery</text>' +
  '<text x="820" y="288" text-anchor="middle" font-size="9" font-weight="600" fill="#2b6cb0">&amp; Outcome</text>' +
  '<text x="820" y="306" text-anchor="middle" font-size="8" fill="#4a5568">Controlled Git</text>' +
  '<text x="820" y="318" text-anchor="middle" font-size="8" fill="#4a5568">Publish</text>' +
  '<line x1="150" y1="289" x2="158" y2="289" stroke="#3182ce" stroke-width="1.5" marker-end="url(#arr-h)"/>' +
  '<line x1="298" y1="289" x2="306" y2="289" stroke="#3182ce" stroke-width="1.5" marker-end="url(#arr-h)"/>' +
  '<line x1="446" y1="289" x2="454" y2="289" stroke="#3182ce" stroke-width="1.5" marker-end="url(#arr-h)"/>' +
  '<line x1="594" y1="289" x2="602" y2="289" stroke="#3182ce" stroke-width="1.5" marker-end="url(#arr-h)"/>' +
  '<line x1="742" y1="289" x2="750" y2="289" stroke="#3182ce" stroke-width="1.5" marker-end="url(#arr-h)"/>' +
  '<line x1="80" y1="236" x2="80" y2="255" stroke="#3182ce" stroke-width="1"/>' +
  '<line x1="228" y1="236" x2="228" y2="255" stroke="#3182ce" stroke-width="1"/>' +
  '<line x1="376" y1="236" x2="376" y2="255" stroke="#3182ce" stroke-width="1"/>' +
  '<line x1="524" y1="236" x2="524" y2="255" stroke="#3182ce" stroke-width="1"/>' +
  '<line x1="672" y1="236" x2="672" y2="255" stroke="#3182ce" stroke-width="1"/>' +
  '<line x1="820" y1="236" x2="820" y2="255" stroke="#3182ce" stroke-width="1"/>' +
  '<line x1="350" y1="236" x2="80" y2="236" stroke="#3182ce" stroke-width="1"/>' +
  '<line x1="350" y1="236" x2="820" y2="236" stroke="#3182ce" stroke-width="1"/>' +
  '<rect x="300" y="340" width="280" height="26" rx="4" fill="#edf2f7" stroke="#3182ce"/>' +
  '<text x="440" y="357" text-anchor="middle" font-size="11" font-weight="600" fill="#2b6cb0">Project / Outcome State</text>' +
  '<line x1="80" y1="323" x2="180" y2="340" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="228" y1="323" x2="280" y2="340" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="376" y1="323" x2="380" y2="340" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="524" y1="323" x2="500" y2="340" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="672" y1="323" x2="610" y2="340" stroke="#a0aec0" stroke-width="1"/>' +
  '<line x1="820" y1="323" x2="700" y2="340" stroke="#a0aec0" stroke-width="1"/>' +
  '<rect x="10" y="385" width="175" height="22" rx="4" fill="#fbd38d" opacity="0.3" stroke="#d69e2e"/>' +
  '<text x="97" y="400" text-anchor="middle" font-size="9" fill="#975a16">Diagnostic Trace</text>' +
  '<rect x="195" y="385" width="175" height="22" rx="4" fill="#fbd38d" opacity="0.3" stroke="#d69e2e"/>' +
  '<text x="282" y="400" text-anchor="middle" font-size="9" fill="#975a16">Human Approval</text>' +
  '<rect x="380" y="385" width="215" height="22" rx="4" fill="#fbd38d" opacity="0.3" stroke="#d69e2e"/>' +
  '<text x="487" y="400" text-anchor="middle" font-size="9" fill="#975a16">Project Intelligence / Definitions</text>' +
  '<rect x="605" y="385" width="190" height="22" rx="4" fill="#fbd38d" opacity="0.3" stroke="#d69e2e"/>' +
  '<text x="700" y="400" text-anchor="middle" font-size="9" fill="#975a16">Capability / Execution Policy</text>' +
  '<rect x="10" y="425" width="880" height="55" rx="4" fill="#f7fafc" stroke="#e2e8f0"/>' +
  '<text x="20" y="443" font-size="9" font-weight="600" fill="#2d3748">Legende:</text>' +
  '<rect x="20" y="451" width="14" height="10" rx="2" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="38" y="460" font-size="8" fill="#4a5568">Subsysteme (durchgezogen)</text>' +
  '<rect x="190" y="451" width="14" height="10" rx="2" fill="#fbd38d" opacity="0.3" stroke="#d69e2e"/>' +
  '<text x="208" y="460" font-size="8" fill="#4a5568">Querschnittlich</text>' +
  '<rect x="310" y="451" width="14" height="10" rx="2" fill="#e2e8f0" stroke="#cbd5e0" stroke-dasharray="4,2"/>' +
  '<text x="328" y="460" font-size="8" fill="#4a5568">Zielarchitektur (gestrichelt)</text>' +
  '<rect x="490" y="451" width="14" height="10" rx="2" fill="#f7fafc" stroke="#a0aec0"/>' +
  '<text x="508" y="460" font-size="8" fill="#4a5568">Heute implementiert</text>' +
  '</svg>';

// ---------------------------------------------------------------------------
// B. Subsystem Dependency Diagram
// ---------------------------------------------------------------------------
DOC_DIAGRAMS.subsystem = '<svg viewBox="0 0 900 620" xmlns="http://www.w3.org/2000/svg" class="arch-diagram">' +
  '<defs><marker id="dep-arr" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#3182ce"/></marker></defs>' +
  '<text x="450" y="20" text-anchor="middle" font-size="14" font-weight="700" fill="#1a202c">Subsysteme, Units und Abhängigkeiten</text>' +
  '<rect x="10" y="35" width="280" height="150" rx="6" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="150" y="55" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">1. Requirement Intelligence</text>' +
  '<line x1="20" y1="62" x2="280" y2="62" stroke="#3182ce" stroke-width="0.5"/>' +
  '<text x="25" y="78" font-size="8" fill="#4a5568">ProjectInspector — Projektstruktur erkennen</text>' +
  '<text x="25" y="92" font-size="8" fill="#4a5568">ProjectIntelligence — read-only Analyse</text>' +
  '<text x="25" y="106" font-size="8" fill="#4a5568">AIRequirementDiscovery — LLM-Anforderungen</text>' +
  '<text x="25" y="120" font-size="8" fill="#4a5568">RequirementValidator — Validierung</text>' +
  '<text x="25" y="134" font-size="8" fill="#4a5568">RequirementPreflight — lokale Prüfungen</text>' +
  '<text x="25" y="148" font-size="8" fill="#4a5568">RequirementsManager — REQ-xxx Parser</text>' +
  '<text x="25" y="162" font-size="8" fill="#4a5568">RequirementModel — Datenmodelle</text>' +
  '<text x="25" y="176" font-size="8" fill="#4a5568">ProjectScanner / Reader / Files</text>' +
  '<rect x="310" y="35" width="280" height="150" rx="6" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="450" y="55" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">2. Engineering Decision</text>' +
  '<line x1="320" y1="62" x2="580" y2="62" stroke="#3182ce" stroke-width="0.5"/>' +
  '<text x="325" y="78" font-size="8" fill="#4a5568">EngineeringCouncil — 3-phasiger KI-Rat (7 LLM-Calls)</text>' +
  '<text x="325" y="92" font-size="8" fill="#4a5568">CouncilModels — Input, Result, Variant</text>' +
  '<text x="325" y="106" font-size="8" fill="#4a5568">CouncilPrompts — Prompt-Templates</text>' +
  '<text x="325" y="120" font-size="8" fill="#4a5568">CouncilError — Fehlertypen</text>' +
  '<text x="325" y="134" font-size="8" fill="#4a5568">ToolchainMaterializer — SetupPlan</text>' +
  '<text x="325" y="148" font-size="8" fill="#4a5568">CapabilityRegistration — Contracts</text>' +
  '<text x="325" y="162" font-size="8" fill="#718096">A1 Umgebungsarchitekt · A2 Toolchain</text>' +
  '<text x="325" y="176" font-size="8" fill="#718096">A3 Risiko-Assessor · Chairman</text>' +
  '<line x1="290" y1="110" x2="310" y2="110" stroke="#3182ce" stroke-width="1.5" marker-end="url(#dep-arr)"/>' +
  '<rect x="610" y="35" width="280" height="150" rx="6" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="750" y="55" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">3. Environment &amp; Setup</text>' +
  '<line x1="620" y1="62" x2="880" y2="62" stroke="#3182ce" stroke-width="0.5"/>' +
  '<text x="625" y="78" font-size="8" fill="#4a5568">SetupPlanner — SetupPlan aus Anforderungen</text>' +
  '<text x="625" y="92" font-size="8" fill="#4a5568">SetupExecutor — kontrollierte Ausführung</text>' +
  '<text x="625" y="106" font-size="8" fill="#4a5568">SetupApproval — Human Approval</text>' +
  '<text x="625" y="120" font-size="8" fill="#4a5568">EnvironmentOrchestrator — voller Check</text>' +
  '<text x="625" y="134" font-size="8" fill="#4a5568">PythonPackageExecutor — pip backend</text>' +
  '<text x="625" y="148" font-size="8" fill="#4a5568">MissingToolchainSetup — Setup-Brücke</text>' +
  '<text x="625" y="162" font-size="8" fill="#4a5568">Execution — CapabilityRegistry</text>' +
  '<text x="625" y="176" font-size="8" fill="#4a5568">GreenfieldProjectMaterializer</text>' +
  '<line x1="590" y1="110" x2="610" y2="110" stroke="#3182ce" stroke-width="1.5" marker-end="url(#dep-arr)"/>' +
  '<rect x="10" y="210" width="280" height="120" rx="6" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="150" y="230" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">4. Development &amp; Change</text>' +
  '<line x1="20" y1="237" x2="280" y2="237" stroke="#3182ce" stroke-width="0.5"/>' +
  '<text x="25" y="253" font-size="8" fill="#4a5568">DevelopmentStage — planende Entwicklung</text>' +
  '<text x="25" y="267" font-size="8" fill="#4a5568">DeveloperChanges — strukturierte Änderungen</text>' +
  '<text x="25" y="281" font-size="8" fill="#4a5568">DeveloperFileApplier — Dateiänderungen</text>' +
  '<text x="25" y="295" font-size="8" fill="#4a5568">ChangeProvenance — Hash-basierte Herkunft</text>' +
  '<text x="25" y="309" font-size="8" fill="#4a5568">ControlledReworkStage — max. 1 Rework</text>' +
  '<text x="25" y="323" font-size="8" fill="#4a5568">CanonicalExecution — Projekt-Lease</text>' +
  '<path d="M750,185 L750,198 L150,198 L150,210" stroke="#3182ce" stroke-width="1.5" fill="none" marker-end="url(#dep-arr)"/>' +
  '<rect x="310" y="210" width="280" height="120" rx="6" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="450" y="230" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">5. Quality &amp; Verification</text>' +
  '<line x1="320" y1="237" x2="580" y2="237" stroke="#3182ce" stroke-width="0.5"/>' +
  '<text x="325" y="253" font-size="8" fill="#4a5568">VerificationPlan — typisierte Prüfstrategie</text>' +
  '<text x="325" y="267" font-size="8" fill="#4a5568">ProjectTestRunner — git-freie Testausführung</text>' +
  '<text x="325" y="281" font-size="8" fill="#4a5568">TestAdapters — pytest, ESPHome, CMake</text>' +
  '<text x="325" y="295" font-size="8" fill="#4a5568">TestingStage — Diagnose nach Tests</text>' +
  '<text x="325" y="309" font-size="8" fill="#4a5568">DevelopmentTestingStage — Dev+Test</text>' +
  '<text x="325" y="323" font-size="8" fill="#4a5568">TestChangeGenerator / TestStackDetector</text>' +
  '<line x1="290" y1="270" x2="310" y2="270" stroke="#3182ce" stroke-width="1.5" marker-end="url(#dep-arr)"/>' +
  '<rect x="610" y="210" width="280" height="120" rx="6" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="750" y="230" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">6. Delivery &amp; Outcome</text>' +
  '<line x1="620" y1="237" x2="880" y2="237" stroke="#3182ce" stroke-width="0.5"/>' +
  '<text x="625" y="253" font-size="8" fill="#4a5568">FinalApproval — abschließende Freigabe</text>' +
  '<text x="625" y="267" font-size="8" fill="#4a5568">ControlledGitStage — lokaler Commit</text>' +
  '<text x="625" y="281" font-size="8" fill="#4a5568">PublishApproval — Publish-Freigabe</text>' +
  '<text x="625" y="295" font-size="8" fill="#4a5568">ControlledPublishStage — Git Push</text>' +
  '<text x="625" y="309" font-size="8" fill="#4a5568">WorkflowPublisher — Veröffentlichung</text>' +
  '<text x="625" y="323" font-size="8" fill="#4a5568">GitManager — Git-Operationen</text>' +
  '<line x1="590" y1="270" x2="610" y2="270" stroke="#3182ce" stroke-width="1.5" marker-end="url(#dep-arr)"/>' +
  '<rect x="10" y="355" width="880" height="75" rx="6" fill="#fefcbf" opacity="0.4" stroke="#d69e2e"/>' +
  '<text x="450" y="375" text-anchor="middle" font-size="10" font-weight="700" fill="#975a16">Querschnittliche Units</text>' +
  '<text x="25" y="393" font-size="8" fill="#744210">DiagnosticTrace — persistente Laufzeitbeobachtung  |  ProjectContext — dauerhafte Entscheidungen</text>' +
  '<text x="25" y="407" font-size="8" fill="#744210">ApprovalManager — zentrale Freigabeverwaltung  |  ExecutionIdentity — stabile Prozessor-IDs</text>' +
  '<text x="25" y="421" font-size="8" fill="#744210">LLMProviderFactory — Provider-Instanziierung  |  CanonicalComposition — Composition-Root</text>' +
  '<rect x="10" y="445" width="880" height="65" rx="6" fill="#e2e8f0" opacity="0.5" stroke="#a0aec0"/>' +
  '<text x="450" y="463" text-anchor="middle" font-size="10" font-weight="700" fill="#4a5568">Communication Adapter (Frontends) → CommonRequest → zentraler Workflow</text>' +
  '<text x="25" y="481" font-size="8" fill="#718096">Web (web_api.py) · Signal (signal_adapter.py) · CLI (workflow_cli.py) · API (api.py) · MCP (mcp_server.py)</text>' +
  '<text x="25" y="495" font-size="8" fill="#718096">Alle Adapter münden in CanonicalComposition → dev_workflow.py</text>' +
  '<rect x="10" y="525" width="880" height="55" rx="6" fill="#e2e8f0" opacity="0.5" stroke="#a0aec0"/>' +
  '<text x="450" y="543" text-anchor="middle" font-size="10" font-weight="700" fill="#4a5568">LLM / Provider Schicht</text>' +
  '<text x="25" y="559" font-size="8" fill="#718096">LLMProvider Protocol → OpenRouterLLMProvider (aktuell) → OllamaAdapter (lokal) → LLMProviderFactory</text>' +
  '<text x="25" y="573" font-size="8" fill="#718096">Model ≠ Provider ≠ Endpoint — OpenRouter ist Provider-Konfiguration, keine architektonische Abhängigkeit</text>' +
  '</svg>';

// ---------------------------------------------------------------------------
// C. State-Flow Diagram
// ---------------------------------------------------------------------------
DOC_DIAGRAMS.stateflow = '<svg viewBox="0 0 850 520" xmlns="http://www.w3.org/2000/svg" class="arch-diagram">' +
  '<defs><marker id="sf-a" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#3182ce"/></marker></defs>' +
  '<text x="425" y="20" text-anchor="middle" font-size="14" font-weight="700" fill="#1a202c">Zustands- und Datenfluss</text>' +
  '<rect x="60" y="40" width="160" height="70" rx="8" fill="#ebf4ff" stroke="#3182ce" stroke-width="2"/>' +
  '<text x="140" y="68" text-anchor="middle" font-size="11" font-weight="700" fill="#2b6cb0">RequirementState</text>' +
  '<text x="140" y="84" text-anchor="middle" font-size="8" fill="#4a5568">discovered → required</text>' +
  '<text x="140" y="97" text-anchor="middle" font-size="8" fill="#4a5568">→ missing → installed</text>' +
  '<rect x="300" y="40" width="160" height="70" rx="8" fill="#ebf4ff" stroke="#3182ce" stroke-width="2"/>' +
  '<text x="380" y="68" text-anchor="middle" font-size="11" font-weight="700" fill="#2b6cb0">SelectedToolchain</text>' +
  '<text x="380" y="84" text-anchor="middle" font-size="8" fill="#4a5568">CouncilResult</text>' +
  '<text x="380" y="97" text-anchor="middle" font-size="8" fill="#4a5568">Variant → ToolchainItem</text>' +
  '<rect x="540" y="40" width="160" height="70" rx="8" fill="#ebf4ff" stroke="#3182ce" stroke-width="2"/>' +
  '<text x="620" y="68" text-anchor="middle" font-size="11" font-weight="700" fill="#2b6cb0">EnvironmentState</text>' +
  '<text x="620" y="84" text-anchor="middle" font-size="8" fill="#4a5568">SetupPlan</text>' +
  '<text x="620" y="97" text-anchor="middle" font-size="8" fill="#4a5568">pending → approved → executed</text>' +
  '<rect x="60" y="160" width="160" height="70" rx="8" fill="#ebf4ff" stroke="#3182ce" stroke-width="2"/>' +
  '<text x="140" y="188" text-anchor="middle" font-size="11" font-weight="700" fill="#2b6cb0">ChangedProjectState</text>' +
  '<text x="140" y="204" text-anchor="middle" font-size="8" fill="#4a5568">structured changes</text>' +
  '<text x="140" y="217" text-anchor="middle" font-size="8" fill="#4a5568">ChangeProvenance</text>' +
  '<rect x="300" y="160" width="160" height="70" rx="8" fill="#ebf4ff" stroke="#3182ce" stroke-width="2"/>' +
  '<text x="380" y="188" text-anchor="middle" font-size="11" font-weight="700" fill="#2b6cb0">AcceptedDevelopment</text>' +
  '<text x="380" y="204" text-anchor="middle" font-size="8" fill="#4a5568">VerificationResult</text>' +
  '<text x="380" y="217" text-anchor="middle" font-size="8" fill="#4a5568">accepted | rework_required</text>' +
  '<rect x="540" y="160" width="160" height="70" rx="8" fill="#c6f6d5" stroke="#38a169" stroke-width="2"/>' +
  '<text x="620" y="188" text-anchor="middle" font-size="11" font-weight="700" fill="#276749">Outcome</text>' +
  '<text x="620" y="204" text-anchor="middle" font-size="8" fill="#276749">FinalApproval → Commit</text>' +
  '<text x="620" y="217" text-anchor="middle" font-size="8" fill="#276749">→ PublishApproval → Push</text>' +
  '<line x1="220" y1="75" x2="300" y2="75" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sf-a)"/>' +
  '<line x1="460" y1="75" x2="540" y2="75" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sf-a)"/>' +
  '<path d="M140,110 L140,160" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sf-a)"/>' +
  '<path d="M380,110 L380,160" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sf-a)"/>' +
  '<path d="M620,110 L620,160" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sf-a)"/>' +
  '<line x1="220" y1="195" x2="300" y2="195" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sf-a)"/>' +
  '<line x1="460" y1="195" x2="540" y2="195" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sf-a)"/>' +
  '<path d="M380,230 L380,260 L140,260 L140,230" stroke="#e53e3e" stroke-width="1" stroke-dasharray="6,3" fill="none"/>' +
  '<text x="260" y="273" text-anchor="middle" font-size="8" fill="#e53e3e">max. 1 Rework</text>' +
  '<rect x="15" y="290" width="820" height="48" rx="4" fill="#fbd38d" opacity="0.25" stroke="#d69e2e"/>' +
  '<text x="425" y="307" text-anchor="middle" font-size="10" font-weight="700" fill="#975a16">Human Approval Boundaries</text>' +
  '<text x="425" y="322" text-anchor="middle" font-size="8" fill="#744210">Setup Approval (vor EnvironmentState)  |  Final Approval (vor Outcome)  |  Publish Approval (vor Push)</text>' +
  '<text x="425" y="335" text-anchor="middle" font-size="8" fill="#744210">Jede Freigabe ist separat — eine Freigabe autorisiert niemals eine andere Grenze</text>' +
  '<rect x="15" y="350" width="820" height="35" rx="4" fill="#e2e8f0" stroke="#a0aec0"/>' +
  '<text x="425" y="367" text-anchor="middle" font-size="9" font-weight="600" fill="#4a5568">Diagnostic Trace: persistente Laufzeitbeobachtung — beobachtet den gesamten Fluss, kann aber keine Freigabe erteilen</text>' +
  '<text x="425" y="381" text-anchor="middle" font-size="8" fill="#718096">x → f → y: strukturierte Eingabe, versionierte Prozessor-Identität, strukturierte Ausgabe</text>' +
  '<rect x="15" y="395" width="820" height="35" rx="4" fill="#f7fafc" stroke="#e2e8f0"/>' +
  '<text x="425" y="412" text-anchor="middle" font-size="9" font-weight="600" fill="#4a5568">Project Intelligence: beobachtete Realität  |  Project Definitions: explizite Entscheidungen  |  config.yml: technische Konfiguration</text>' +
  '<text x="425" y="426" text-anchor="middle" font-size="8" fill="#718096">Konflikte zwischen diesen Quellen werden sichtbar gemacht, nicht stillschweigend zusammengeführt</text>' +
  '<rect x="200" y="445" width="450" height="32" rx="4" fill="#e8f4fd" stroke="#3182ce"/>' +
  '<text x="425" y="460" text-anchor="middle" font-size="9" fill="#2b6cb0">WorkflowState ist autoritativ für Entscheidungen — DiagnosticTrace beobachtet, entscheidet nicht</text>' +
  '<text x="425" y="473" text-anchor="middle" font-size="8" fill="#4a5568">State Lock: nur eine mutierende Operation pro Projektpfad gleichzeitig</text>' +
  '</svg>';

// ---------------------------------------------------------------------------
// D. Environment & Setup Diagram
// ---------------------------------------------------------------------------
DOC_DIAGRAMS.envsetup = '<svg viewBox="0 0 880 540" xmlns="http://www.w3.org/2000/svg" class="arch-diagram">' +
  '<defs><marker id="es-a" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#3182ce"/></marker></defs>' +
  '<text x="440" y="22" text-anchor="middle" font-size="14" font-weight="700" fill="#1a202c">Environment &amp; Setup — SetupEffect, Policy und kontrollierte Ausführung</text>' +
  '<rect x="30" y="42" width="200" height="48" rx="4" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="130" y="60" text-anchor="middle" font-size="9" font-weight="700" fill="#2b6cb0">Requirement Intelligence</text>' +
  '<text x="130" y="76" text-anchor="middle" font-size="8" fill="#4a5568">Anforderungen + PreflightResult</text>' +
  '<rect x="260" y="42" width="200" height="48" rx="4" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="360" y="60" text-anchor="middle" font-size="9" font-weight="700" fill="#2b6cb0">Engineering Decision</text>' +
  '<text x="360" y="76" text-anchor="middle" font-size="8" fill="#4a5568">CouncilResult</text>' +
  '<line x1="230" y1="66" x2="260" y2="66" stroke="#3182ce" stroke-width="1" marker-end="url(#es-a)"/>' +
  '<rect x="140" y="112" width="600" height="36" rx="4" fill="#f7fafc" stroke="#a0aec0"/>' +
  '<text x="440" y="125" text-anchor="middle" font-size="10" font-weight="600" fill="#4a5568">classify_setup_effect() → SetupEffect</text>' +
  '<text x="440" y="141" text-anchor="middle" font-size="8" fill="#718096">PYTHON_PACKAGE_INSTALL · PROJECT_TOOL_INSTALL · SYSTEM_PACKAGE_INSTALL · CONTAINER_RUNTIME_SETUP · SYSTEM_CONFIGURATION · DEVICE_ACCESS · MANUAL</text>' +
  '<path d="M130,90 L130,112" stroke="#3182ce" stroke-width="1" marker-end="url(#es-a)"/>' +
  '<path d="M360,90 L360,112" stroke="#3182ce" stroke-width="1" marker-end="url(#es-a)"/>' +
  '<rect x="240" y="165" width="400" height="52" rx="4" fill="#fbd38d" opacity="0.3" stroke="#d69e2e"/>' +
  '<text x="440" y="182" text-anchor="middle" font-size="9" font-weight="700" fill="#975a16">is_controlled_setup_effect() — Backend/Policy-Prüfung</text>' +
  '<text x="440" y="197" text-anchor="middle" font-size="8" fill="#744210">CONTROLLED_SETUP_EFFECTS = {python_package_install}  — Heute implementiert</text>' +
  '<text x="440" y="211" text-anchor="middle" font-size="8" fill="#744210">Andere Effekte: erkannt &amp; vorbereitet, aber noch ohne kontrolliertes Backend (Zielarchitektur)</text>' +
  '<line x1="440" y1="148" x2="440" y2="165" stroke="#d69e2e" stroke-width="1.5" marker-end="url(#es-a)"/>' +
  '<rect x="50" y="242" width="250" height="42" rx="4" fill="#c6f6d5" stroke="#38a169"/>' +
  '<text x="175" y="258" text-anchor="middle" font-size="9" font-weight="700" fill="#276749">Kontrolliertes Backend verfügbar</text>' +
  '<text x="175" y="274" text-anchor="middle" font-size="8" fill="#276749">→ SetupPlan (action="install")</text>' +
  '<rect x="380" y="242" width="250" height="42" rx="4" fill="#fed7d7" stroke="#e53e3e"/>' +
  '<text x="505" y="258" text-anchor="middle" font-size="9" font-weight="700" fill="#9b2c2c">Kein kontrolliertes Backend</text>' +
  '<text x="505" y="274" text-anchor="middle" font-size="8" fill="#9b2c2c">→ SetupPlan (action="manual_review")</text>' +
  '<line x1="300" y1="217" x2="175" y2="242" stroke="#38a169" stroke-width="1.5" marker-end="url(#es-a)"/>' +
  '<line x1="440" y1="217" x2="440" y2="242" stroke="#e53e3e" stroke-width="1.5"/>' +
  '<rect x="120" y="308" width="640" height="48" rx="4" fill="#fbd38d" opacity="0.35" stroke="#d69e2e" stroke-width="2"/>' +
  '<text x="440" y="326" text-anchor="middle" font-size="10" font-weight="700" fill="#975a16">Human Approval (Setup)</text>' +
  '<text x="440" y="342" text-anchor="middle" font-size="8" fill="#744210">SetupApproval — separate Freigabe vor jeder Setup-Ausführung</text>' +
  '<path d="M175,284 L175,296 L250,296 L250,308" stroke="#d69e2e" stroke-width="1.5" marker-end="url(#es-a)"/>' +
  '<path d="M505,284 L505,296 L650,296 L650,308" stroke="#e53e3e" stroke-width="1"/>' +
  '<rect x="140" y="380" width="280" height="56" rx="4" fill="#ebf4ff" stroke="#3182ce" stroke-width="2"/>' +
  '<text x="280" y="398" text-anchor="middle" font-size="9" font-weight="700" fill="#2b6cb0">Controlled Execution</text>' +
  '<text x="280" y="413" text-anchor="middle" font-size="8" fill="#4a5568">SetupExecutor → PythonPackageExecutor</text>' +
  '<text x="280" y="427" text-anchor="middle" font-size="8" fill="#4a5568">shell=False, list args, timeout, output limits</text>' +
  '<rect x="460" y="380" width="280" height="56" rx="4" fill="#fed7d7" stroke="#e53e3e"/>' +
  '<text x="600" y="398" text-anchor="middle" font-size="9" font-weight="700" fill="#9b2c2c">Manuelle Überprüfung</text>' +
  '<text x="600" y="413" text-anchor="middle" font-size="8" fill="#9b2c2c">Kein automatisierter Backend-Pfad</text>' +
  '<text x="600" y="427" text-anchor="middle" font-size="8" fill="#9b2c2c">Human muss selbst einrichten</text>' +
  '<line x1="280" y1="356" x2="280" y2="380" stroke="#3182ce" stroke-width="1.5" marker-end="url(#es-a)"/>' +
  '<line x1="600" y1="356" x2="600" y2="380" stroke="#e53e3e" stroke-width="1.5"/>' +
  '<rect x="280" y="460" width="320" height="34" rx="4" fill="#c6f6d5" stroke="#38a169"/>' +
  '<text x="440" y="475" text-anchor="middle" font-size="9" font-weight="600" fill="#276749">Verification: Verfügbarkeit prüfen → EnvironmentState aktualisieren</text>' +
  '<text x="440" y="490" text-anchor="middle" font-size="8" fill="#276749">Erfolgreiche Installation erteilt keine Capability-Autorität</text>' +
  '<line x1="280" y1="436" x2="380" y2="460" stroke="#38a169" stroke-width="1.5" marker-end="url(#es-a)"/>' +
  '<line x1="600" y1="436" x2="530" y2="460" stroke="#a0aec0" stroke-width="1.5"/>' +
  '<rect x="120" y="508" width="640" height="24" rx="4" fill="#f7fafc" stroke="#e2e8f0"/>' +
  '<text x="440" y="524" text-anchor="middle" font-size="8" fill="#718096">Kontrolliertes Backend = python_package_install (Heute). Alle anderen SetupEffects = vorbereitet/erkannt (Zielarchitektur). Kein sudo, kein NOPASSWD, keine root-Shell.</text>' +
  '</svg>';

// ---------------------------------------------------------------------------
// E. Security / Authority Diagram
// ---------------------------------------------------------------------------
DOC_DIAGRAMS.security = '<svg viewBox="0 0 860 520" xmlns="http://www.w3.org/2000/svg" class="arch-diagram">' +
  '<defs><marker id="sec-a" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#3182ce"/></marker></defs>' +
  '<text x="430" y="22" text-anchor="middle" font-size="14" font-weight="700" fill="#1a202c">Sicherheits- und Autoritätsarchitektur</text>' +
  '<rect x="100" y="45" width="200" height="55" rx="6" fill="#e8f4fd" stroke="#3182ce"/>' +
  '<text x="200" y="66" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">LLM Vorschlag</text>' +
  '<text x="200" y="81" text-anchor="middle" font-size="8" fill="#4a5568">Natürlichsprachlich oder</text>' +
  '<text x="200" y="94" text-anchor="middle" font-size="8" fill="#4a5568">strukturiert (Tool Call)</text>' +
  '<line x1="300" y1="72" x2="360" y2="72" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sec-a)"/>' +
  '<rect x="370" y="45" width="200" height="55" rx="6" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="470" y="66" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">Strukturierte Aktion</text>' +
  '<text x="470" y="81" text-anchor="middle" font-size="8" fill="#4a5568">SetupEffect / ToolDefinition</text>' +
  '<text x="470" y="94" text-anchor="middle" font-size="8" fill="#4a5568">Kein beliebiges Shell-Kommando</text>' +
  '<line x1="570" y1="72" x2="630" y2="72" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sec-a)"/>' +
  '<rect x="640" y="45" width="200" height="55" rx="6" fill="#fbd38d" opacity="0.35" stroke="#d69e2e"/>' +
  '<text x="740" y="66" text-anchor="middle" font-size="10" font-weight="700" fill="#975a16">Policy-Validierung</text>' +
  '<text x="740" y="81" text-anchor="middle" font-size="8" fill="#744210">is_controlled_setup_effect()</text>' +
  '<text x="740" y="94" text-anchor="middle" font-size="8" fill="#744210">CapabilityRegistry Prüfung</text>' +
  '<path d="M200,100 L200,140 L430,140 L430,160" stroke="#d69e2e" stroke-width="1.5" marker-end="url(#sec-a)" fill="none"/>' +
  '<path d="M470,100 L470,160" stroke="#d69e2e" stroke-width="1.5" marker-end="url(#sec-a)" fill="none"/>' +
  '<path d="M740,100 L740,140 L430,140" stroke="#d69e2e" stroke-width="1.5" fill="none"/>' +
  '<rect x="310" y="165" width="240" height="55" rx="6" fill="#fbd38d" opacity="0.45" stroke="#d69e2e" stroke-width="2"/>' +
  '<text x="430" y="186" text-anchor="middle" font-size="10" font-weight="700" fill="#975a16">Human Approval</text>' +
  '<text x="430" y="201" text-anchor="middle" font-size="8" fill="#744210">Separate Freigabe-Grenze</text>' +
  '<text x="430" y="214" text-anchor="middle" font-size="8" fill="#744210">Setup ≠ Capability ≠ Git ≠ Publish</text>' +
  '<line x1="430" y1="220" x2="430" y2="245" stroke="#3182ce" stroke-width="1.5" marker-end="url(#sec-a)"/>' +
  '<rect x="310" y="250" width="240" height="55" rx="6" fill="#ebf4ff" stroke="#3182ce" stroke-width="2"/>' +
  '<text x="430" y="271" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">Controlled Execution</text>' +
  '<text x="430" y="286" text-anchor="middle" font-size="8" fill="#4a5568">SetupExecutor / PythonPackageExecutor</text>' +
  '<text x="430" y="299" text-anchor="middle" font-size="8" fill="#4a5568">shell=False · Timeout · Output-Limits</text>' +
  '<line x1="430" y1="305" x2="430" y2="330" stroke="#38a169" stroke-width="1.5" marker-end="url(#sec-a)"/>' +
  '<rect x="310" y="335" width="240" height="40" rx="6" fill="#c6f6d5" stroke="#38a169"/>' +
  '<text x="430" y="353" text-anchor="middle" font-size="10" font-weight="700" fill="#276749">Verification</text>' +
  '<text x="430" y="368" text-anchor="middle" font-size="8" fill="#276749">Erfolg ≠ Capability-Autorität</text>' +
  '<rect x="30" y="395" width="800" height="112" rx="6" fill="#f7fafc" stroke="#e2e8f0"/>' +
  '<text x="430" y="415" text-anchor="middle" font-size="11" font-weight="700" fill="#2d3748">Sicherheitsprinzipien</text>' +
  '<text x="50" y="436" font-size="9" fill="#4a5568">• LLM-generierte Kommandos oder Setup-Vorschläge sind nicht grundsätzlich verboten</text>' +
  '<text x="50" y="452" font-size="9" fill="#4a5568">• Die Sicherheitsgrenze ist: Vorgeschlagene Aktionen dürfen keine unkontrollierte Ausführungsautorität erhalten</text>' +
  '<text x="50" y="468" font-size="9" fill="#4a5568">• sudo ist keine Capability und keine Autorität — ADC läuft normalerweise unprivilegiert</text>' +
  '<text x="50" y="484" font-size="9" fill="#4a5568">• Privilegierte Aktionen erfordern strukturierte Klassifizierung/Policy und Human Approval; Authentifizierung bleibt beim OS</text>' +
  '<text x="50" y="500" font-size="9" fill="#4a5568">• ADC speichert kein sudo-Passwort · keine permanente root-Shell · kein uneingeschränktes NOPASSWD: ALL</text>' +
  '</svg>';

// ===================================================================
// Documentation Sections
// ===================================================================

docSections["sec-01"] = {
  title: "ADC in 10 Minuten verstehen",
  html: '<h3>Schnelleinstieg</h3>' +
    '<p>ADC (AI Dev Center) ist eine KI-gestützte Entwicklungsumgebung, die den gesamten Entwicklungsprozess — von der Anforderungsanalyse bis zur kontrollierten Auslieferung — in einem <strong>zentralen Workflow</strong> orchestriert.</p>' +
    '<h4>Was ADC macht</h4>' +
    '<ul><li>Bestehende Projekte analysieren, ohne sie auszuführen</li>' +
    '<li>Anforderungen aus natürlicher Sprache erkennen und validieren</li>' +
    '<li>Technische Entscheidungen über einen Multi-Agenten Engineering Council treffen</li>' +
    '<li>Setup-Bedarf erkennen und <strong>nur mit Human Approval</strong> kontrolliert ausführen</li>' +
    '<li>Strukturierte Code-Änderungen planen und anwenden</li>' +
    '<li>Tests ausführen und Ergebnisse verifizieren</li>' +
    '<li>Ergebnisse reviewen und kontrolliert per Git versionieren</li></ul>' +
    '<h4>Die sechs Subsysteme</h4>' +
    '<div class="flow-row"><span class="flow-step">Requirement Intelligence</span>' +
    '<span class="flow-arrow">→</span><span class="flow-step">Engineering Decision</span>' +
    '<span class="flow-arrow">→</span><span class="flow-step">Environment &amp; Setup</span>' +
    '<span class="flow-arrow">→</span><span class="flow-step">Development &amp; Change</span>' +
    '<span class="flow-arrow">→</span><span class="flow-step">Quality &amp; Verification</span>' +
    '<span class="flow-arrow">→</span><span class="flow-step">Delivery &amp; Outcome</span></div>' +
    '<h4>Kernprinzipien</h4>' +
    '<ul><li><strong>Human in Control:</strong> Setup, Capabilities, Git und Publish haben je eigene Human-Approval-Grenzen</li>' +
    '<li><strong>Keine automatische Installation:</strong> Fehlende Tools werden gemeldet, nicht selbstständig installiert</li>' +
    '<li><strong>Kontrollierte Ausführung:</strong> Alle Aktionen durchlaufen Policy-Prüfung und strukturierte Backends</li>' +
    '<li><strong>Nachvollziehbarkeit:</strong> Der Diagnostic Trace zeichnet den gesamten Workflow-Verlauf auf</li>' +
    '<li><strong>Projekt-Respekt:</strong> Bestehende Architektur, Konventionen und Toolchains bleiben autoritativ</li></ul>'
};

docSections["sec-02"] = {
  title: "Produktziel und Einsatzbereich",
  html: '<h3>Was ADC ist</h3>' +
    '<p>ADC ist eine orchestrierte Entwicklungsumgebung, in der spezialisierte KI-Rollen zu einem gemeinsamen zentralen Projekt-Workflow beitragen. Es verbindet Analyse, technische Planung, Entwicklung, Verifikation, Review und sichere Auslieferung in einem durchgängigen Prozess.</p>' +
    '<h3>Was ADC nicht ist</h3>' +
    '<ul><li>Kein einfacher Chatbot, der Code-Snippets generiert</li>' +
    '<li>Kein autonomer Agent ohne menschliche Kontrolle</li>' +
    '<li>Kein Release-Automatisierungs- oder CI/CD-System</li>' +
    '<li>Kein Deployment-Tool (Publish bedeutet hier ausschließlich Git Remote Push)</li></ul>' +
    '<h3>Einsatzbereich</h3>' +
    '<ul><li>Software-Projekte (Python, Web, Embedded)</li>' +
    '<li>Firmware und hardware-nahe Entwicklung (ESP32, PlatformIO, CMake)</li>' +
    '<li>Bestehende Projekte verstehen, Features hinzufügen, Bugs beheben, Refactoring</li>' +
    '<li>Tests hinzufügen und Änderungen reviewen</li></ul>' +
    '<p><strong>Physical Hardware Actions</strong> (flashen, OTA, Geräte aktivieren) liegen außerhalb des aktuellen produktiven Scopes und erfordern eine eigene separate Human-Approval-Grenze.</p>' +
    '<h3>Systemgrenzen</h3>' +
    '<ul><li>ADC ändert keine bestehende Architektur gegen den Willen des Projekts</li>' +
    '<li>ADC installiert keine Tools ohne explizite Human Approval</li>' +
    '<li>ADC führt keine beliebigen Shell-Kommandos aus</li>' +
    '<li>ADC speichert keine Secrets, Passwörter oder API-Keys im Diagnostic Trace</li>' +
    '<li>Nur eine mutierende Operation pro Projektpfad gleichzeitig</li></ul>' +
    '<h3>Docker</h3>' +
    '<p><span class="target-badge">Zielarchitektur</span> Docker ist die vorgesehene Laufzeitumgebung. Der Core-Container läuft non‑root, ohne privileged mode und ohne Docker-Socket- oder Device-Mounts. <span class="current-badge">Heute implementiert</span> ADC läuft direkt auf dem Host.</p>'
};

docSections["sec-03"] = {
  title: "Gesamtarchitektur",
  html: '<h3>ADC Architekturdiagramm</h3>' + DOC_DIAGRAMS.overall +
    '<h4>Erläuterung</h4>' +
    '<p>Die ADC-Architektur folgt einem klaren Schichtenmodell:</p>' +
    '<ol><li><strong>Frontends / Communication Adapter:</strong> Web GUI, Signal, API, CLI und MCP sind Adapter zum selben zentralen Workflow — keine separaten Business-Pipelines.</li>' +
    '<li><strong>Common Request / Intent:</strong> Alle Adapter normalisieren ihre Eingabe in ein einheitliches Request-Format.</li>' +
    '<li><strong>Zentraler ADC Workflow:</strong> Orchestriert die sechs Subsysteme in einer festgelegten Reihenfolge.</li>' +
    '<li><strong>Sechs Subsysteme:</strong> Jeweils mit spezifischen Units und Verantwortlichkeiten.</li>' +
    '<li><strong>Project / Outcome State:</strong> Autoritative Zustandsverwaltung für Entscheidungen.</li></ol>' +
    '<h4>Querschnittliche Belange</h4>' +
    '<ul><li><strong>Diagnostic Trace:</strong> Persistente, strukturierte Laufzeitbeobachtung über alle Subsysteme hinweg</li>' +
    '<li><strong>Human Approval:</strong> Separate Freigabegrenzen für Setup, Capabilities, Final und Publish</li>' +
    '<li><strong>Project Intelligence / Definitions:</strong> Beobachtete Realität vs. explizite dauerhafte Entscheidungen</li>' +
    '<li><strong>Capability / Execution Policy:</strong> Kontrollierte Ausführung mit erlaubten Operationen und Timeout-Limits</li></ul>'
};

docSections["sec-04"] = {
  title: "Zentraler Workflow",
  html: '<h3>Der zentrale Geschäftsablauf</h3>' +
    '<p>Der zentrale Workflow ist die verbindliche Abfolge, die jede ADC-Anfrage durchläuft:</p>' +
    '<div class="vertical-flow">' +
    '<span class="flow-step">User Input → Communication Adapter → Common Request</span>' +
    '<span class="flow-arrow">↓</span>' +
    '<span class="flow-step">1. Requirement Intelligence: Projekt analysieren, Anforderungen erkennen</span>' +
    '<span class="flow-arrow">↓</span>' +
    '<span class="flow-step">2. Engineering Decision: Council bewertet Ansätze, Chairman wählt aus</span>' +
    '<span class="flow-arrow">↓</span>' +
    '<span class="flow-step">3. Environment &amp; Setup: SetupPlan, Human Approval, kontrollierte Ausführung</span>' +
    '<span class="flow-arrow">↓</span>' +
    '<span class="flow-step">4. Development &amp; Change: Strukturierte Änderungen planen und anwenden</span>' +
    '<span class="flow-arrow">↓</span>' +
    '<span class="flow-step">5. Quality &amp; Verification: Tests ausführen, Ergebnisse verifizieren</span>' +
    '<span class="flow-arrow">↓</span>' +
    '<span class="flow-step">6. Delivery &amp; Outcome: Final Approval, Controlled Git, Publish Approval, Push</span>' +
    '<span class="flow-arrow">↓</span>' +
    '<span class="flow-step">Project / Outcome State</span></div>' +
    '<h4>Workflow-Eigenschaften</h4>' +
    '<ul><li><strong>Read-only Analyse zuerst:</strong> Das Projekt wird zunächst nur gelesen und analysiert, nicht verändert</li>' +
    '<li><strong>Planung vor Ausführung:</strong> Jeder Schritt wird geplant, bevor er ausgeführt wird</li>' +
    '<li><strong>Human Approval vor kritischen Aktionen:</strong> Setup, Final und Publish erfordern explizite Freigabe</li>' +
    '<li><strong>Maximal ein Rework:</strong> Nach einem rework_required-Ergebnis ist genau ein kontrollierter Rework-Zyklus erlaubt</li>' +
    '<li><strong>Keine parallelen Mutationen:</strong> Nur eine mutierende Operation pro Projektpfad gleichzeitig</li>' +
    '<li><strong>Recovery:</strong> Nach Abbruch wird der Zustand als recovery_required markiert — keine automatische Wiederholung</li></ul>' +
    '<h4>Entry Points</h4>' +
    '<p>Der zentrale Workflow wird durch <code>dev_workflow.py</code> / <code>DevelopmentWorkflow</code> orchestriert. Die <code>canonical_composition.py</code> / <code>build_canonical_components()</code> stellt die gemeinsame Composition-Root für alle Adapter bereit.</p>'
};

docSections["sec-05"] = {
  title: "Die sechs Subsysteme",
  html: '<h3>Offizielle Subsystem-Namen</h3>' +
    '<p>Die ADC-Architektur definiert sechs offizielle Subsysteme mit klaren Verantwortlichkeiten:</p>' +
    '<div class="subsystem-card"><h4>1. Requirement Intelligence</h4>' +
    '<p><strong>Verantwortung:</strong> Projekt lesen, Struktur erkennen, Anforderungen aus Task-Beschreibung ableiten, validieren und Preflight-Prüfungen durchführen.</p>' +
    '<p><strong>Eingabe:</strong> Projektpfad + Task-Beschreibung</p>' +
    '<p><strong>Ausgabe:</strong> RequirementState, PreflightResult, ProjectIntelligence</p></div>' +
    '<div class="subsystem-card"><h4>2. Engineering Decision</h4>' +
    '<p><strong>Verantwortung:</strong> Multi-Agenten Council (A1/A2/A3) bewertet technische Alternativen, Chairman synthetisiert Empfehlung und erzeugt SetupPlan.</p>' +
    '<p><strong>Eingabe:</strong> ProjectIntelligence + Requirements</p>' +
    '<p><strong>Ausgabe:</strong> CouncilResult, SelectedToolchain, CapabilityRegistration</p></div>' +
    '<div class="subsystem-card"><h4>3. Environment &amp; Setup</h4>' +
    '<p><strong>Verantwortung:</strong> SetupPlan materialisieren, Human Approval einholen, kontrollierte Ausführung durch registrierte Backends, Umgebungszustand prüfen.</p>' +
    '<p><strong>Eingabe:</strong> CouncilResult + RequirementState</p>' +
    '<p><strong>Ausgabe:</strong> EnvironmentState, ausgeführte SetupSteps</p></div>' +
    '<div class="subsystem-card"><h4>4. Development &amp; Change</h4>' +
    '<p><strong>Verantwortung:</strong> Strukturierte Änderungen planen (Developer), validieren und über den FileApplier sicher in das Projekt schreiben.</p>' +
    '<p><strong>Eingabe:</strong> EnvironmentState + CouncilResult</p>' +
    '<p><strong>Ausgabe:</strong> ChangedProjectState, ChangeProvenance</p></div>' +
    '<div class="subsystem-card"><h4>5. Quality &amp; Verification</h4>' +
    '<p><strong>Verantwortung:</strong> VerificationPlan aus ProjectIntelligence ableiten, Tests mit allowlist-basierten Runnern ausführen, Ergebnisse diagnostizieren.</p>' +
    '<p><strong>Eingabe:</strong> ChangedProjectState</p>' +
    '<p><strong>Ausgabe:</strong> VerificationResult, AcceptedDevelopmentState</p></div>' +
    '<div class="subsystem-card"><h4>6. Delivery &amp; Outcome</h4>' +
    '<p><strong>Verantwortung:</strong> Final Approval, kontrollierten Git-Commit aus Run-Provenance erstellen, Publish Approval, kontrollierten Git Push ausführen.</p>' +
    '<p><strong>Eingabe:</strong> AcceptedDevelopmentState</p>' +
    '<p><strong>Ausgabe:</strong> Outcome (committed, published)</p></div>'
};

docSections["sec-06"] = {
  title: "Units und ihre Verantwortlichkeiten",
  html: '<h3>Unit-Übersicht pro Subsystem</h3>' +
    '<h4>1. Requirement Intelligence</h4>' +
    '<table class="doc-table"><tr><th>Unit</th><th>Datei</th><th>Verantwortung</th></tr>' +
    '<tr><td>ProjectInspector</td><td>project_inspector.py</td><td>Baut strukturierte Projektinformationen auf</td></tr>' +
    '<tr><td>ProjectIntelligence</td><td>project_intelligence.py</td><td>Deterministische read-only Analyse</td></tr>' +
    '<tr><td>ProjectScanner</td><td>project_scanner.py</td><td>Dateiauflistung via rglob</td></tr>' +
    '<tr><td>ProjectReader</td><td>project_reader.py</td><td>Begrenztes Datei-Lesen</td></tr>' +
    '<tr><td>ProjectFiles</td><td>project_files.py</td><td>Sicheres Textdatei-Lesen</td></tr>' +
    '<tr><td>AIRequirementDiscovery</td><td>ai_requirement_discovery.py</td><td>LLM-gestützte Anforderungserkennung</td></tr>' +
    '<tr><td>RequirementValidator</td><td>requirement_validator.py</td><td>Deterministische Validierung</td></tr>' +
    '<tr><td>RequirementPreflight</td><td>requirement_preflight.py</td><td>Lokale Verfügbarkeitsprüfungen</td></tr>' +
    '<tr><td>RequirementsManager</td><td>requirements_manager.py</td><td>REQ-xxx Muster-Parser</td></tr>' +
    '<tr><td>RequirementModel</td><td>requirement_model.py</td><td>Datenmodelle</td></tr></table>' +
    '<h4>2. Engineering Decision</h4>' +
    '<table class="doc-table"><tr><th>Unit</th><th>Datei</th><th>Verantwortung</th></tr>' +
    '<tr><td>EngineeringCouncil</td><td>engineering_council.py</td><td>3-phasiger KI-Rat (7 LLM-Aufrufe)</td></tr>' +
    '<tr><td>CouncilModels</td><td>council_models.py</td><td>Datenmodelle</td></tr>' +
    '<tr><td>CouncilPrompts</td><td>council_prompts.py</td><td>Prompt-Template-Builder</td></tr>' +
    '<tr><td>CouncilError</td><td>council_error.py</td><td>Council-spezifische Fehlertypen</td></tr>' +
    '<tr><td>ToolchainMaterializer</td><td>toolchain_materializer.py</td><td>SetupPlan aus Council-Ergebnis</td></tr>' +
    '<tr><td>CapabilityRegistration</td><td>capability_registration.py</td><td>Registrierungs-Contracts</td></tr></table>' +
    '<h4>3. Environment &amp; Setup</h4>' +
    '<table class="doc-table"><tr><th>Unit</th><th>Datei</th><th>Verantwortung</th></tr>' +
    '<tr><td>SetupPlanner</td><td>setup_planner.py</td><td>SetupPlan aus Anforderungen + Preflight</td></tr>' +
    '<tr><td>SetupExecutor</td><td>setup_executor.py</td><td>Kontrollierte Schritt-Ausführung</td></tr>' +
    '<tr><td>SetupApproval</td><td>setup_approval.py</td><td>Human Approval für Setup</td></tr>' +
    '<tr><td>EnvironmentOrchestrator</td><td>environment_orchestrator.py</td><td>Voller Umgebungs-Check</td></tr>' +
    '<tr><td>EnvironmentResolver</td><td>environment_resolver.py</td><td>Bereitschaftsprüfung</td></tr>' +
    '<tr><td>MissingToolchainSetup</td><td>missing_toolchain_setup.py</td><td>TOOL_UNAVAILABLE → Setup → Retry</td></tr>' +
    '<tr><td>PythonPackageExecutor</td><td>python_package_executor.py</td><td>Kontrollierte pip-Installation</td></tr>' +
    '<tr><td>ProjectSetupApplication</td><td>project_setup_application.py</td><td>Application-Core Setup-Planung</td></tr>' +
    '<tr><td>GreenfieldProjectMaterializer</td><td>greenfield_project.py</td><td>Neues Projekt-Root + Git-Repo</td></tr>' +
    '<tr><td>CapabilityRegistry</td><td>execution.py</td><td>Explizite Capability-Verwaltung</td></tr></table>' +
    '<h4>4. Development &amp; Change</h4>' +
    '<table class="doc-table"><tr><th>Unit</th><th>Datei</th><th>Verantwortung</th></tr>' +
    '<tr><td>DevelopmentStage</td><td>development_stage.py</td><td>Planende Entwicklung</td></tr>' +
    '<tr><td>DeveloperChanges</td><td>developer_changes.py</td><td>Strukturierte Änderungen parsen</td></tr>' +
    '<tr><td>DeveloperFileApplier</td><td>developer_file_applier.py</td><td>Sichere Datei-Änderungen</td></tr>' +
    '<tr><td>ChangeProvenance</td><td>change_provenance.py</td><td>Hash-basierte Änderungsherkunft</td></tr>' +
    '<tr><td>ControlledReworkStage</td><td>controlled_rework_stage.py</td><td>Max. 1 Rework-Zyklus</td></tr></table>' +
    '<h4>5. Quality &amp; Verification</h4>' +
    '<table class="doc-table"><tr><th>Unit</th><th>Datei</th><th>Verantwortung</th></tr>' +
    '<tr><td>VerificationPlan</td><td>verification.py</td><td>Typisierte Prüfstrategie</td></tr>' +
    '<tr><td>ProjectTestRunner</td><td>project_test_runner.py</td><td>Git-freie Testausführung</td></tr>' +
    '<tr><td>TestAdapters</td><td>test_adapters.py</td><td>pytest, ESPHome, CMake Adapter</td></tr>' +
    '<tr><td>TestingStage</td><td>testing_stage.py</td><td>Diagnose nach Tests</td></tr>' +
    '<tr><td>DevelopmentTestingStage</td><td>development_testing_stage.py</td><td>Dev+Test-Koordination</td></tr>' +
    '<tr><td>TestChangeGenerator</td><td>test_change_generator.py</td><td>Test-Änderungen generieren</td></tr>' +
    '<tr><td>TestStackDetector</td><td>test_stack_detector.py</td><td>Test-Stack erkennen</td></tr>' +
    '<tr><td>TestStrategy</td><td>test_strategy.py</td><td>Test-Strategie Datenmodell</td></tr></table>' +
    '<h4>6. Delivery &amp; Outcome</h4>' +
    '<table class="doc-table"><tr><th>Unit</th><th>Datei</th><th>Verantwortung</th></tr>' +
    '<tr><td>FinalApproval</td><td>final_approval.py</td><td>Abschließende Human-Freigabe</td></tr>' +
    '<tr><td>ControlledGitStage</td><td>controlled_git_stage.py</td><td>Fail-Safe lokaler Commit</td></tr>' +
    '<tr><td>PublishApproval</td><td>publish_approval.py</td><td>Separate Publish-Freigabe</td></tr>' +
    '<tr><td>ControlledPublishStage</td><td>controlled_publish_stage.py</td><td>Kontrollierter Git Push</td></tr>' +
    '<tr><td>WorkflowPublisher</td><td>workflow_publisher.py</td><td>Veröffentlichung nach Freigabe</td></tr>' +
    '<tr><td>GitManager</td><td>git_manager.py</td><td>Git-Operationen</td></tr></table>' +
    '<h4>Querschnittliche Units</h4>' +
    '<table class="doc-table"><tr><th>Unit</th><th>Datei</th><th>Verantwortung</th></tr>' +
    '<tr><td>DiagnosticTrace</td><td>diagnostic_trace.py</td><td>Persistente Workflow-Beobachtung</td></tr>' +
    '<tr><td>ProjectContext / Definitions</td><td>project_context.py</td><td>Dauerhafte Entscheidungen</td></tr>' +
    '<tr><td>ApprovalManager</td><td>approval_manager.py</td><td>Freigabeverwaltung</td></tr>' +
    '<tr><td>LLMProviderFactory</td><td>llm_provider_factory.py</td><td>Provider-Instanziierung</td></tr>' +
    '<tr><td>CommonRequest</td><td>common_request.py</td><td>Adapter-neutrales Request-Format</td></tr>' +
    '<tr><td>WorkflowExecutionGuard</td><td>workflow_execution_guard.py</td><td>Prozess-lokaler Mutex</td></tr>' +
    '<tr><td>CanonicalComposition</td><td>canonical_composition.py</td><td>Gemeinsame Composition-Root</td></tr></table>'
};

docSections["sec-07"] = {
  title: "Unit- und Subsystem-Abhängigkeiten",
  html: '<h3>Abhängigkeitsdiagramm</h3>' + DOC_DIAGRAMS.subsystem +
    '<h4>Flussrichtung</h4>' +
    '<p>Der zentrale Fluss verläuft von links nach rechts und oben nach unten:</p>' +
    '<ol><li><strong>Requirement Intelligence</strong> → liefert Anforderungen und Projektwissen an alle nachfolgenden Subsysteme</li>' +
    '<li><strong>Engineering Decision</strong> → konsumiert ProjectIntelligence, produziert CouncilResult</li>' +
    '<li><strong>Environment &amp; Setup</strong> → konsumiert CouncilResult + Anforderungen, produziert EnvironmentState</li>' +
    '<li><strong>Development &amp; Change</strong> → konsumiert EnvironmentState, produziert ChangedProjectState</li>' +
    '<li><strong>Quality &amp; Verification</strong> → konsumiert ChangedProjectState, produziert VerificationResult</li>' +
    '<li><strong>Delivery &amp; Outcome</strong> → konsumiert VerificationResult, produziert Outcome</li></ol>' +
    '<h4>Kritische Abhängigkeiten</h4>' +
    '<ul><li>Engineering Decision <strong>benötigt</strong> gültige ProjectIntelligence — ohne Analyse keine Entscheidung</li>' +
    '<li>Environment &amp; Setup <strong>benötigt</strong> CouncilResult für ToolchainMaterializer</li>' +
    '<li>Development &amp; Change <strong>benötigt</strong> erfolgreiches Setup bevor Änderungen möglich sind</li>' +
    '<li>Delivery &amp; Outcome <strong>benötigt</strong> akzeptiertes VerificationResult</li></ul>'
};

docSections["sec-08"] = {
  title: "Zustands- und Datenfluss",
  html: '<h3>Zustandsdiagramm</h3>' + DOC_DIAGRAMS.stateflow +
    '<h4>Zustandsübergänge im Detail</h4>' +
    '<p><strong>RequirementState:</strong> discovered → suspected → required/optional → installed (via Preflight) oder missing → installed (via Setup) → failed/rejected</p>' +
    '<p><strong>SelectedToolchain:</strong> 3 Agent-Vorschläge (A1, A2, A3) → Chairman synthetisiert → CouncilResult.recommendation → ToolchainMaterializer → SetupPlan</p>' +
    '<p><strong>EnvironmentState:</strong> SetupPlan pending → SetupApproval → approved → SetupExecutor → executed. Verfügbarkeitsprüfung vor und nach Setup.</p>' +
    '<p><strong>ChangedProjectState:</strong> DeveloperChanges → DeveloperFileApplier → ChangeProvenance. Jede Dateiänderung mit Original- und Result-Hash.</p>' +
    '<p><strong>AcceptedDevelopmentState:</strong> VerificationResult pass → accepted. fail → rework_required (max. 1×). Erneutes rework_required → Run beendet.</p>' +
    '<p><strong>Outcome:</strong> FinalApproval → ControlledGitStage → committed. PublishApproval → ControlledPublishStage → published.</p>' +
    '<h4>Datenquellen</h4>' +
    '<ul><li><strong>Project Intelligence:</strong> Beobachtete Realität (Sprachen, Frameworks, Toolchains, Struktur)</li>' +
    '<li><strong>Project Definitions:</strong> Explizite dauerhafte Entscheidungen, Regeln, Terminologie</li>' +
    '<li><strong>config.yml:</strong> Technische Konfiguration (Provider, Model, Endpoint, Timeout)</li>' +
    '<li><strong>WorkflowState:</strong> Autoritativ für Workflow-Entscheidungen</li>' +
    '<li><strong>DiagnosticTrace:</strong> Beobachtet, entscheidet nicht</li></ul>'
};

docSections["sec-09"] = {
  title: "Requirement Intelligence",
  html: '<h3>Subsystem 1: Anforderungsintelligenz</h3>' +
    '<h4>Ablauf</h4>' +
    '<ol><li><strong>Projekt-Analyse (read-only):</strong> ProjectScanner/ProjectReader/ProjectFiles lesen das Projekt ohne Ausführung. Sprachen, Frameworks, Package Manager, Build-Systeme, Test-Systeme, Firmware-Indikatoren und CI-Hinweise werden deterministisch erkannt.</li>' +
    '<li><strong>ProjectIntelligence:</strong> Strukturierte, deterministische Projektbeschreibung — kein LLM-Output.</li>' +
    '<li><strong>AIRequirementDiscovery:</strong> LLM-gestützte Anforderungserkennung aus Task-Beschreibung + ProjectIntelligence.</li>' +
    '<li><strong>RequirementValidator:</strong> Deterministische Validierung der Anforderungsliste.</li>' +
    '<li><strong>RequirementPreflight:</strong> Prüft lokal verifizierbare Anforderungen (EXECUTABLE, PYTHON_PACKAGE, SYSTEM_PACKAGE) auf tatsächliche Verfügbarkeit.</li></ol>' +
    '<h4>Wichtige Datenmodelle</h4>' +
    '<ul><li><code>Requirement</code> — id, type, name, status, required_version, install_method, evidence</li>' +
    '<li><code>RequirementType</code> — EXECUTABLE, PYTHON_PACKAGE, SYSTEM_PACKAGE, SDK, TOOLCHAIN, FLASHER, etc.</li>' +
    '<li><code>Status</code> — DISCOVERED, SUSPECTED, REQUIRED, MISSING, INSTALLED, FAILED, etc.</li>' +
    '<li><code>PreflightResult</code> — aktivierte, fehlende, inaktive Anforderungen</li>' +
    '<li><code>RequirementActivation</code> — blocks_current_operation, activation_reason</li></ul>' +
    '<h4>Requirement Activation</h4>' +
    '<p>Nicht jede erkannte Anforderung blockiert den aktuellen Workflow:</p>' +
    '<ul><li><strong>Aktiviert + blockierend:</strong> Fehlen verhindert Fortschritt → muss via Setup behoben werden</li>' +
    '<li><strong>Aktiviert + nicht blockierend:</strong> Kann deferred werden</li>' +
    '<li><strong>Inaktiv:</strong> Wird für diesen Run nicht benötigt</li></ul>'
};

docSections["sec-10"] = {
  title: "Engineering Decision",
  html: '<h3>Subsystem 2: Technische Entscheidungsfindung</h3>' +
    '<h4>Der Engineering Council</h4>' +
    '<p>Ein 3-phasiger Multi-KI-Rat mit insgesamt 7 LLM-Aufrufen:</p>' +
    '<ol><li><strong>Phase 1 — Proposals:</strong> Drei spezialisierte Agenten (A1, A2, A3) erstellen unabhängige technische Vorschläge</li>' +
    '<li><strong>Phase 2 — Reviews:</strong> Jeder Agent bewertet die Vorschläge der anderen</li>' +
    '<li><strong>Phase 3 — Chairman:</strong> Synthetisiert eine Empfehlung aus allen Vorschlägen und Bewertungen</li></ol>' +
    '<h4>Council-Rollen</h4>' +
    '<ul><li><strong>A1 — Environment Architect:</strong> Fokus auf Umgebung, Toolchain-Kompatibilität, Systemvoraussetzungen</li>' +
    '<li><strong>A2 — Toolchain Integrator:</strong> Fokus auf Build-Systeme, Package Manager, Test-Frameworks</li>' +
    '<li><strong>A3 — Risk &amp; Feasibility Assessor:</strong> Fokus auf Risiken, Machbarkeit, Alternativen</li>' +
    '<li><strong>Chairman:</strong> Synthese und Auswahl der Empfehlung</li></ul>' +
    '<h4>Entscheidungsprinzip</h4>' +
    '<p><strong>Council schlägt vor. Chairman wählt aus/empfiehlt. Human Approval bleibt Ausführungsautorität.</strong></p>' +
    '<p>Die automatische Erkennung technischer Eignung ist nicht gleichbedeutend mit automatischer Setup-Fähigkeit.</p>' +
    '<h4>Fehlerbehandlung</h4>' +
    '<ul><li>Unvollständiger Council blockiert zentral vor Materialisierung</li>' +
    '<li>CouncilFailedError, CouncilChairmanError, AgentParseError</li>' +
    '<li>Partiell erfolgreiche Vorschläge/Reviews bleiben inspizierbar</li></ul>' +
    '<p><span class="current-badge">Heute implementiert</span> Der vollständige 3-Phasen-Council mit A1/A2/A3 und Chairman ist produktiv. Der Real-System-E2E-Test übt ihn mit echten Provider/Model-Aufrufen.</p>'
};

docSections["sec-11"] = {
  title: "Engineering Council und Chairman",
  html: '<h3>Council-Architektur im Detail</h3>' +
    '<h4>Rollen und Provider</h4>' +
    '<p>Die Council-Rollen werden in config.yml konfiguriert. Jede Rolle kann einen eigenen Provider, Model, Timeout und Temperature haben:</p>' +
    '<pre class="doc-code">council:\n  roles:\n    a1_environment_architect:\n      provider: openrouter\n      model: deepseek/deepseek-v4-pro\n      timeout_seconds: 120\n      temperature: 0.3\n    a2_toolchain_integrator:\n      provider: openrouter\n      model: deepseek/deepseek-v4-pro\n      timeout_seconds: 120\n      temperature: 0.3\n    a3_risk_feasibility_assessor:\n      provider: openrouter\n      model: deepseek/deepseek-v4-pro\n      timeout_seconds: 120\n      temperature: 0.3\n    chairman:\n      provider: openrouter\n      model: deepseek/deepseek-v4-pro\n      timeout_seconds: 180\n      temperature: 0.2</pre>' +
    '<h4>Chairman-Funktion</h4>' +
    '<p>Der Chairman ist kein zusätzlicher Agent mit eigener Meinung, sondern ein Synthese-Schritt:</p>' +
    '<ul><li>Konsolidiert die drei Agent-Vorschläge (A1, A2, A3)</li>' +
    '<li>Berücksichtigt die Cross-Reviews aus Phase 2</li>' +
    '<li>Wählt eine empfohlene Variante (CouncilVariant) aus</li>' +
    '<li>Erzeugt strukturierte ToolchainItem-Empfehlungen</li>' +
    '<li>Die Chairman-Empfehlung ist die Grundlage für den ToolchainMaterializer</li></ul>' +
    '<h4>Sicherheit</h4>' +
    '<p>Der Council hat keine Ausführungsautorität. Seine Ausgabe ist eine <strong>Empfehlung</strong>, die durch den ToolchainMaterializer in einen SetupPlan übersetzt wird und Human Approval erfordert.</p>'
};

docSections["sec-12"] = {
  title: "Environment & Setup",
  html: '<h3>Subsystem 3: Umgebung und Einrichtung</h3>' +
    DOC_DIAGRAMS.envsetup +
    '<h4>Ablauf</h4>' +
    '<ol><li><strong>Environment Detection:</strong> EnvironmentOrchestrator führt vollständigen Umgebungs-Check durch (Detection → Preflight → Resolution)</li>' +
    '<li><strong>SetupPlan-Erstellung:</strong> SetupPlanner erzeugt SetupPlan aus Requirements + PreflightResult + kontrollierten SetupEffects</li>' +
    '<li><strong>Human Approval:</strong> SetupApproval erfordert explizite Freigabe vor jeder Ausführung</li>' +
    '<li><strong>Kontrollierte Ausführung:</strong> SetupExecutor führt nur genehmigte Schritte mit registrierten Backends aus</li>' +
    '<li><strong>Verifikation:</strong> Nach der Ausführung wird die Verfügbarkeit erneut geprüft</li></ol>' +
    '<h4>SetupPlan</h4>' +
    '<pre class="doc-code">SetupPlan:\n  project_id: str\n  steps: tuple[SetupStep, ...]\n  status: str  # pending | approved | executed | rejected\n\nSetupStep:\n  id: str\n  action: str           # "install" | "manual_review"\n  setup_effect: str     # SetupEffect identity\n  is_approved: bool</pre>' +
    '<h4>MissingToolchainSetup</h4>' +
    '<p>Die Brücke zwischen TOOL_UNAVAILABLE und Verification-Retry: Tool fehlt → SetupPlan → Human Approval → Setup → Retry des originalen VerificationPlan. Installationserfolg erteilt keine Capability-Autorität.</p>'
};

docSections["sec-13"] = {
  title: "Setup Effects und Setup Capabilities",
  html: '<h3>SetupEffect — Semantische Setup-Identitäten</h3>' +
    '<p>SetupEffects beschreiben <strong>was</strong> für eine Umgebungsänderung benötigt wird, nicht <strong>wie</strong> sie auf einem bestimmten Host durchzuführen ist. Sie sind keine Shell-Kommandos, Package-Manager-Argv oder ausführbare Pfade.</p>' +
    '<h4>Definierte SetupEffects</h4>' +
    '<table class="doc-table"><tr><th>Effect</th><th>Beschreibung</th><th>Status</th></tr>' +
    '<tr><td><code>python_package_install</code></td><td>Python-Paket via pip</td><td><span class="current-badge">Heute</span> — kontrolliertes Backend</td></tr>' +
    '<tr><td><code>project_tool_install</code></td><td>Projekt-Tool/Executable</td><td><span class="target-badge">Ziel</span> — kein Backend</td></tr>' +
    '<tr><td><code>system_package_install</code></td><td>System-Paket (apt, brew)</td><td><span class="target-badge">Ziel</span> — kein Backend</td></tr>' +
    '<tr><td><code>container_runtime_setup</code></td><td>Container-Laufzeit</td><td><span class="target-badge">Ziel</span> — kein Backend</td></tr>' +
    '<tr><td><code>system_configuration</code></td><td>System-Konfiguration</td><td><span class="target-badge">Ziel</span> — kein Backend</td></tr>' +
    '<tr><td><code>device_access</code></td><td>Gerätezugriff (udev, etc.)</td><td><span class="target-badge">Ziel</span> — kein Backend</td></tr>' +
    '<tr><td><code>manual</code></td><td>Manuelle Einrichtung</td><td>N/A — immer manuell</td></tr></table>' +
    '<h4>Policy-Prüfung</h4>' +
    '<p><code>is_controlled_setup_effect()</code> in execution.py prüft, ob ADC ein kontrolliertes Backend für einen Effect hat. CONTROLLED_SETUP_EFFECTS enthält aktuell nur python_package_install. Nur Effects in dieser Menge erhalten action="install".</p>' +
    '<h4>Setup Capabilities (OC-025 Konzept)</h4>' +
    '<p><span class="target-badge">Zielarchitektur</span> Das SetupEffect/Capability-Modell trennt zwischen erkannten/vorbereiteten Effects (alle sieben), kontrollierten Backends (nur python_package_install heute) und zukünftigen Backends (registrierbar ohne Effect-Definitionen zu ändern).</p>'
};

docSections["sec-14"] = {
  title: "Capability Registry und Controlled Execution",
  html: '<h3>Capability Registry</h3>' +
    '<p>Das zentrale, freigabe-bewusste Capability-Registry bindet Capability-Identität, ausführbare Identität, erlaubte Operationstypen, Freigabe-Provenance und Projekt-Scope.</p>' +
    '<h4>CapabilityRegistration</h4>' +
    '<pre class="doc-code">CapabilityRegistration:\n  capability: str               # z.B. "esphome", "platformio"\n  executable_names: tuple[str]  # z.B. ("esphome",)\n  allowed_operations: tuple[str] # validate, compile, build, test, configure\n  approval_provenance: ApprovalProvenance\n  status: str                   # active | suspended | revoked</pre>' +
    '<h4>ApprovalProvenance</h4>' +
    '<p>Vollständige Autoritätskette: project_intelligence_ref, engineering_council_ref, chairman_approval_ref, human_approval_ref</p>' +
    '<h4>Registrierungsablauf</h4>' +
    '<ol><li>ProjectIntelligence identifiziert benötigte Capability</li>' +
    '<li>Engineering Council bewertet technische Eignung</li>' +
    '<li>Chairman genehmigt die Empfehlung</li>' +
    '<li><strong>Human Approval</strong> für die Capability-Registrierung</li>' +
    '<li>Registrierung im CapabilityRegistry</li>' +
    '<li>Kontrollierte Ausführung nur mit aktiver, vollständig genehmigter Registrierung</li></ol>' +
    '<h4>Controlled Execution</h4>' +
    '<p>Die Ausführungsumgebung in execution.py stellt sicher: shell=False, Argumente als Liste, Timeout pro Ausführung, Output-Limits, nur allowlist-basierte Operationen.</p>' +
    '<p><span class="current-badge">Heute implementiert</span> Globale Bootstrap-Registrierungen sind Kompatibilitäts-Defaults. <span class="target-badge">Zielarchitektur</span> Dynamische Registrierungen sind immer projektgebunden.</p>'
};

docSections["sec-15"] = {
  title: "Human Approval und Sicherheitsgrenzen",
  html: '<h3>Sicherheitsarchitektur</h3>' + DOC_DIAGRAMS.security +
    '<h4>Human Approval Grenzen</h4>' +
    '<p>ADC definiert <strong>vier separate</strong> Human-Approval-Grenzen. Eine Freigabe an einer Grenze autorisiert niemals eine andere:</p>' +
    '<table class="doc-table"><tr><th>Grenze</th><th>Wann</th><th>Was sie autorisiert</th></tr>' +
    '<tr><td><strong>Setup Approval</strong></td><td>Vor Setup-Ausführung</td><td>Ausführung des genehmigten SetupPlans</td></tr>' +
    '<tr><td><strong>Capability Approval</strong></td><td>Vor Capability-Registrierung</td><td>Registrierung einer spezifischen Capability</td></tr>' +
    '<tr><td><strong>Final Approval</strong></td><td>Nach akzeptierter Entwicklung</td><td>Übergang zu Controlled Git</td></tr>' +
    '<tr><td><strong>Publish Approval</strong></td><td>Nach erfolgreichem Commit</td><td>Git Push zum Remote</td></tr></table>' +
    '<h4>Sicherheitsprinzip</h4>' +
    '<p>LLM-generierte Kommandos oder Setup-Vorschläge sind <strong>nicht grundsätzlich verboten</strong>. Die Sicherheitsgrenze ist: <strong>Vorgeschlagene Aktionen dürfen keine unkontrollierte Ausführungsautorität erhalten.</strong></p>' +
    '<h4>Privilege-Handhabung</h4>' +
    '<ul><li><span class="current-badge">Heute implementiert</span> ADC läuft normalerweise unprivilegiert</li>' +
    '<li><strong>sudo ist keine Capability und keine Autorität</strong></li>' +
    '<li>Privilegierte Setup-Aktionen können von einem LLM vorgeschlagen werden, erfordern aber strukturierte Klassifizierung/Policy und Human Approval</li>' +
    '<li>Authentifizierung bleibt beim Betriebssystem</li>' +
    '<li>ADC speichert kein sudo-Passwort · keine permanente root-Shell · kein NOPASSWD: ALL</li>' +
    '<li><span class="target-badge">Zielarchitektur</span> Ein zukünftiger Privilege Broker kann sudo, polkit oder einen anderen host-spezifischen Mechanismus verwenden</li></ul>'
};

docSections["sec-16"] = {
  title: "Development & Change",
  html: '<h3>Subsystem 4: Entwicklung und Änderung</h3>' +
    '<h4>Architektur</h4>' +
    '<p>Die Entwicklung hat eine <strong>kontrollierte Grenze</strong>: Der Developer produziert strukturierte Änderungen, während der FileApplier allein validierte Dateien innerhalb des Projekt-Roots schreibt. Es werden keine beliebigen Shell-Kommandos verwendet.</p>' +
    '<h4>Ablauf</h4>' +
    '<ol><li><strong>DevelopmentStage:</strong> Developer-Agent plant Änderungen basierend auf Task, ProjectIntelligence und CouncilResult</li>' +
    '<li><strong>DeveloperChanges:</strong> Parst und validiert strukturierte Änderungen (create, update, delete)</li>' +
    '<li><strong>DeveloperFileApplier:</strong> Wendet validierte Änderungen sicher innerhalb des Projekt-Roots an</li>' +
    '<li><strong>ChangeProvenance:</strong> Verfolgt für jede geänderte Datei: Original-Hash, Result-Hash, ob sie bereits modifiziert/staged war</li></ol>' +
    '<h4>ChangeProvenance</h4>' +
    '<pre class="doc-code">RunChangeProvenance:\n  run_id: str\n  changes: dict[path, FileChange]\n\nFileChange:\n  original_hash: str\n  result_hash: str\n  was_modified: bool\n  was_staged: bool\n  action: str  # create | update | delete</pre>' +
    '<h4>Sicherheit</h4>' +
    '<ul><li>Nur der FileApplier schreibt Dateien — nicht der Developer-Agent direkt</li>' +
    '<li>Alle Pfade werden gegen den Projekt-Root validiert</li>' +
    '<li>Vorbestehende oder gemischte Provenance blockiert automatisches Staging</li>' +
    '<li>Testing, Review und Git bleiben spätere Stages</li></ul>' +
    '<h4>Rework</h4>' +
    '<p>Nach einem rework_required-Ergebnis ist genau <strong>ein</strong> kontrollierter Rework-Zyklus erlaubt. Ein weiteres rework_required beendet den Run.</p>'
};

docSections["sec-17"] = {
  title: "Quality & Verification",
  html: '<h3>Subsystem 5: Qualität und Verifikation</h3>' +
    '<h4>Generalized Verification Architecture</h4>' +
    '<p>Die zentrale Verifikationsarchitektur konvertiert ProjectIntelligence in einen typisierten, area-bewussten VerificationPlan und führt kontrollierte, allowlist-basierte Runner aus. Keine beliebigen Shell-Kommandos, keine Dependency-Installation, keine Git-Mutation.</p>' +
    '<h4>VerificationPlan</h4>' +
    '<pre class="doc-code">VerificationStep:\n  step_id: str\n  area: str              # z.B. "firmware", "backend"\n  verification_kind: str  # test | build | validate | compile\n  runner_type: str        # pytest | cmake_build | esphome_check\n  policy: str             # controlled_execution | unsupported\n  status: str             # pending → pass | fail | unsupported | tool_unavailable</pre>' +
    '<h4>Verifikations-Runner</h4>' +
    '<table class="doc-table"><tr><th>Runner</th><th>Bereich</th><th>Status</th></tr>' +
    '<tr><td>PythonPytestAdapter</td><td>Python-Projekte</td><td><span class="current-badge">Heute</span></td></tr>' +
    '<tr><td>ESPHomeAdapter</td><td>ESPHome-Firmware</td><td><span class="current-badge">Heute</span></td></tr>' +
    '<tr><td>CMake Build</td><td>C/C++ Projekte</td><td><span class="current-badge">Heute</span></td></tr>' +
    '<tr><td>PlatformIO Build</td><td>PlatformIO-Firmware</td><td><span class="current-badge">Heute</span></td></tr></table>' +
    '<h4>Sicherheit in der Verifikation</h4>' +
    '<ul><li>Kein Runner führt flash, upload, OTA, serial monitor oder device provisioning aus</li>' +
    '<li>PlatformIO extra_scripts und Build-Code-Trust-Boundaries werden erkannt und blockiert</li>' +
    '<li>Wenn sichere Verifikation unmöglich ist, meldet das System unsupported statt stillschweigend zu passieren</li>' +
    '<li>TOOL_UNAVAILABLE bleibt ein strukturierter Setup-Bedarf — keine automatische Installation</li></ul>'
};

docSections["sec-18"] = {
  title: "Delivery & Outcome",
  html: '<h3>Subsystem 6: Auslieferung und Ergebnis</h3>' +
    '<h4>Git Safety Boundary</h4>' +
    '<p>Die Auslieferung erfolgt in mehreren kontrollierten Schritten mit separaten Human-Approval-Grenzen:</p>' +
    '<ol><li><strong>FinalApproval:</strong> Nach akzeptiertem VerificationResult muss der Human das Ergebnis explizit freigeben</li>' +
    '<li><strong>ControlledGitStage:</strong> Fail-safe lokaler Commit nur aus validierten Run-Pfaden (ChangeProvenance). Vorbestehende/gemischte Änderungen, fremder gestagter Content und Hash-Mismatch blockieren.</li>' +
    '<li><strong>PublishApproval:</strong> Nach erfolgreichem Commit: separate Publish-Freigabe</li>' +
    '<li><strong>ControlledPublishStage:</strong> Push des exakten persistierten Run-Commits zu existierendem Remote mit explizitem Branch-Ref</li></ol>' +
    '<h4>Was Publish bedeutet</h4>' +
    '<p><strong>Publish = Git Remote Push.</strong> Nicht: Release-Automatisierung, Deployment, Hardware-Flash, OTA, Package-Publish oder CI/CD-Automatisierung.</p>' +
    '<h4>Fail-Safe Blocker</h4>' +
    '<ul><li>Fehlende Git-Remotes · Detached HEAD · Vorbestehende/gemischte Änderungen</li>' +
    '<li>Fremder gestagter Content · Finaler Hash-Mismatch · Nicht-Fast-Forward-Push · Authentifizierungsfehler</li></ul>'
};

docSections["sec-19"] = {
  title: "Diagnostic Trace",
  html: '<h3>Zentraler Diagnostic Trace</h3>' +
    '<p>Jeder zentrale Run hat eine persistente, geordnete diagnostische Zeitleiste. Der Trace zeigt erreichte Phasen, strukturierte Eingaben, versionierte Prozessor-Identitäten und Ausgaben, separate Approval-Grenzen, Blocker und Git/Publish-Ergebnisse.</p>' +
    '<h4>Trace-Modell: x → f → y</h4>' +
    '<ul><li><strong>x (Input):</strong> Typ, Interface, Source — was wurde empfangen?</li>' +
    '<li><strong>f (Processor):</strong> Entity, Version, Provider, Model — wer hat verarbeitet?</li>' +
    '<li><strong>y (Output):</strong> Typ, Interface, Destination, Data — was wurde produziert?</li></ul>' +
    '<p>ADC Entity-Versionen bleiben getrennt von konfigurierter Provider/Model-Identität.</p>' +
    '<h4>Trace-Level</h4>' +
    '<table class="doc-table"><tr><th>Level</th><th>Beschreibung</th></tr>' +
    '<tr><td><strong>NONE</strong></td><td>Unterdrückt Darstellung — zentrale Audit-Daten bleiben erhalten</td></tr>' +
    '<tr><td><strong>NORMAL</strong></td><td>Wesentlicher Workflow-Fortschritt und Ergebnisse</td></tr>' +
    '<tr><td><strong>INFO</strong></td><td>Knappe Typ/Interface- und Prozessor-Identität (x/f/y)</td></tr>' +
    '<tr><td><strong>VERBOSE</strong></td><td>Strukturierte Handoffs, Engineering-Felder, Provider/Model-Kontext</td></tr>' +
    '<tr><td><strong>VERY_VERBOSE</strong></td><td>Maximale x→f→y-Projektion; bereinigte effektive LLM-Prompts sichtbar</td></tr></table>' +
    '<h4>Sicherheit</h4>' +
    '<ul><li>Raw Provider Responses, Credentials, private Model-Reasoning und Command-Payloads bleiben auf jedem Level ausgeschlossen</li>' +
    '<li>Secrets, API-Keys, Passwörter, vollständige Prompts und Chain-of-Thought werden nicht gespeichert</li>' +
    '<li>Details sind allowlist-basiert und redacted</li></ul>' +
    '<h4>Trace vs. WorkflowState</h4>' +
    '<p><strong>WorkflowState ist autoritativ für Entscheidungen.</strong> Der DiagnosticTrace beobachtet, kann aber kein Setup, Git oder Publish genehmigen.</p>'
};

docSections["sec-20"] = {
  title: "Project Intelligence / Definitions / Context",
  html: '<h3>Drei getrennte Wissensquellen</h3>' +
    '<p>ADC trennt strikt zwischen beobachteter Realität, expliziten Entscheidungen und technischer Konfiguration:</p>' +
    '<h4>1. Project Intelligence</h4>' +
    '<p><strong>Beobachtete Realität</strong> — deterministisch, read-only, aus Repository-Evidenz: Sprachen, Frameworks, Package Manager, Build-Systeme, Test-Systeme, Firmware-Indikatoren, CI-Hinweise, Projektbereiche. Keine LLM-Interpretation.</p>' +
    '<p>Unit: <code>ProjectIntelligence</code> / <code>inspect_project()</code> in project_intelligence.py</p>' +
    '<h4>2. Project Definitions / Memory</h4>' +
    '<p><strong>Explizite dauerhafte Entscheidungen</strong> — intentionale Policy: strukturierte Entscheidungen, Regeln, Terminologie. Nie rohe Chat-History. Definitions erteilen niemals Approval oder Ausführungsautorität.</p>' +
    '<p>Unit: <code>ProjectDefinitionStore</code> in project_context.py</p>' +
    '<h4>3. config.yml</h4>' +
    '<p><strong>Technische Konfiguration</strong> — deklarativ: AI Provider, Model, Endpoint, Timeout, Council-Rollen, Discovery-Einstellungen.</p>' +
    '<h4>Project Context</h4>' +
    '<p>Der zentrale ProjectContext bewahrt alle drei Quellen typisiert und stellt Konflikte dar, statt sie stillschweigend zu überschreiben.</p>'
};

docSections["sec-21"] = {
  title: "Communication Adapter und Frontends",
  html: '<h3>Adapter-Architektur</h3>' +
    '<p>Web, Signal, API, CLI und MCP sind <strong>Frontends/Adapter</strong> zum selben zentralen Workflow — keine separaten Business-Pipelines.</p>' +
    '<div class="flow-row"><span class="flow-step">Web</span><span class="flow-step">Signal</span><span class="flow-step">API</span><span class="flow-step">CLI</span><span class="flow-step">MCP</span></div>' +
    '<div class="flow-arrow" style="text-align:center;display:block;">↓</div>' +
    '<div class="flow-row"><span class="flow-step">Communication Adapter</span></div>' +
    '<div class="flow-arrow" style="text-align:center;display:block;">↓</div>' +
    '<div class="flow-row"><span class="flow-step">Common Request / Intent</span></div>' +
    '<div class="flow-arrow" style="text-align:center;display:block;">↓</div>' +
    '<div class="flow-row"><span class="flow-step">Zentraler Workflow</span></div>' +
    '<h4>Adapter im Detail</h4>' +
    '<table class="doc-table"><tr><th>Adapter</th><th>Datei</th><th>Status</th></tr>' +
    '<tr><td><strong>Web GUI</strong></td><td>web_api.py + web/</td><td><span class="current-badge">Heute</span> — produktiv</td></tr>' +
    '<tr><td><strong>API</strong></td><td>api.py</td><td><span class="current-badge">Heute</span> — Kompatibilitäts-Adapter</td></tr>' +
    '<tr><td><strong>CLI</strong></td><td>workflow_cli.py</td><td><span class="current-badge">Heute</span> — interaktiv</td></tr>' +
    '<tr><td><strong>Signal</strong></td><td>signal_adapter.py</td><td><span class="target-badge">Ziel</span> — Adapter-Contract vorhanden, kein deployed Provider</td></tr>' +
    '<tr><td><strong>MCP</strong></td><td>mcp_server.py</td><td><span class="target-badge">Ziel</span> — Server implementiert, Client-Integration Ziel</td></tr></table>' +
    '<h4>Signal-Projektbindung</h4>' +
    '<p>Signal-Chats und Projekte haben eine strikte 1:1-Beziehung. Jeder Chat gehört zu genau einem Projekt. Chat-Text kann kein Projekt wechseln oder Approval erteilen. <span class="target-badge">Zielarchitektur</span> Konkreter Signal-Transport-Provider ist zukünftige Integrationsarbeit.</p>' +
    '<h4>Web GUI</h4>' +
    '<p>Die produktive Web GUI validiert ein vollständiges server-lokales Projekt-Root und lädt keine Dateien hoch. Chat, Trace und Approvals sind in der Web-Oberfläche verfügbar.</p>'
};

docSections["sec-22"] = {
  title: "MCP-Zielarchitektur",
  html: '<h3>MCP (Model Context Protocol) Integration</h3>' +
    '<p><span class="target-badge">Zielarchitektur</span> MCP ist die vorgesehene Capability/Integrations-Architektur für ADC.</p>' +
    '<h4>Aktueller Stand</h4>' +
    '<ul><li><span class="current-badge">Heute implementiert</span> <code>MCPServer</code> in mcp_server.py exponiert existierende Workflow-Tools als deterministische MCP-Tools</li>' +
    '<li><span class="current-badge">Heute implementiert</span> <code>mcp_transport.py</code> implementiert JSON-RPC 2.0 / MCP Transport über stdio</li>' +
    '<li><span class="target-badge">Zielarchitektur</span> Volle MCP-Client-Integration für Capability-Akquise</li></ul>' +
    '<h4>Sicherheit</h4>' +
    '<p>MCP darf nicht als Autorität oder Approval-Bypass beschrieben werden. MCP-Capabilities unterliegen letztlich den ADC Capability/Policy- und Human-Approval-Regeln.</p>' +
    '<h4>ToolDefinition</h4>' +
    '<pre class="doc-code">ToolDefinition:\n  name: str\n  description: str\n  input_schema: dict[str, Any]</pre>' +
    '<p>Der MCPServer enthält keine Business-Logik. Jedes Tool delegiert an eine existierende Komponente der umgebenden Applikation.</p>'
};

docSections["sec-23"] = {
  title: "LLM / Provider / Model-Architektur",
  html: '<h3>Konzeptionelle Trennung</h3>' +
    '<p class="security-principle">Model ≠ Provider ≠ Endpoint</p>' +
    '<p>ADC-Zielarchitektur ist Provider/Model-unabhängig. OpenRouter ist eine aktuelle Provider/Gateway-Konfiguration, keine architektonische Abhängigkeit.</p>' +
    '<h4>LLMProvider Protocol</h4>' +
    '<p>In llm_agent.py definiert: <code>LLMProvider</code> — abstrahiert den Zugriff auf verschiedene LLM-Backends. Provider werden via <code>LLMProviderFactory</code> (llm_provider_factory.py) aus AIConfig + SecretResolver instanziiert.</p>' +
    '<h4>Implementierte Provider</h4>' +
    '<table class="doc-table"><tr><th>Provider</th><th>Datei</th><th>Status</th></tr>' +
    '<tr><td><strong>OpenRouter</strong></td><td>openrouter_llm_provider.py</td><td><span class="current-badge">Heute</span> — produktiv</td></tr>' +
    '<tr><td><strong>Ollama</strong></td><td>ollama_adapter.py / ollama_client.py</td><td><span class="current-badge">Heute</span> — lokale Inferenz</td></tr></table>' +
    '<h4>Konfiguration</h4>' +
    '<pre class="doc-code">ai:\n  provider: openrouter\n  model: deepseek/deepseek-v4-pro\n  endpoint: https://openrouter.ai/api/v1\n  authentication:\n    type: secret_reference\n    secret_reference: openrouter-api\n  timeout_seconds: 30</pre>' +
    '<h4>Agent-Konfiguration</h4>' +
    '<p>Agent-Rollen (Project Manager, Architect, Developer, Tester, Reviewer) haben deutsche Prompt-Templates in agent_roles.py und Modell/Token-Limits in agent_config.py.</p>' +
    '<p><span class="target-badge">Zielarchitektur</span> Beliebig viele Provider/Model-Kombinationen pro Rolle konfigurierbar, ohne Code-Änderungen.</p>'
};

docSections["sec-24"] = {
  title: "Testarchitektur",
  html: '<h3>Test-Hierarchie</h3>' +
    '<p>ADC definiert eine klare Test-Hierarchie mit spezifischen Zwecken und Grenzen pro Ebene:</p>' +
    '<table class="doc-table"><tr><th>Ebene</th><th>Zweck</th><th>Grenze</th></tr>' +
    '<tr><td><strong>Unit</strong></td><td>Einzelne Funktionen/Klassen testen</td><td>Keine externen Abhängigkeiten, keine LLM-Calls, kein Dateisystem</td></tr>' +
    '<tr><td><strong>Subsystem / Integration</strong></td><td>Zusammenspiel mehrerer Units innerhalb eines Subsystems</td><td>Gemockte externe Provider, kein echtes Netzwerk</td></tr>' +
    '<tr><td><strong>Central Workflow System</strong></td><td>Kompletten zentralen Workflow testen</td><td>Gemockte LLM-Provider, echtes Dateisystem (temp)</td></tr>' +
    '<tr><td><strong>Real-System-E2E</strong></td><td>Vollständigen produktiven Workflow mit echten Providern/Modellen</td><td>Opt-in via --real-system-e2e Flag, nie Teil der normalen Suite</td></tr>' +
    '<tr><td><strong>Browser-GUI-E2E</strong></td><td>Web-GUI-Interaktion testen</td><td>Headless Browser, gemocktes Backend</td></tr>' +
    '<tr><td><strong>Manual Smoke</strong></td><td>Manuelle Überprüfung der produktiven Umgebung</td><td>Keine Automatisierung</td></tr></table>' +
    '<h4>Real-System-E2E</h4>' +
    '<p>Der Real-System-E2E-Test übt den vollständigen produktiven Workflow mit echten externen Provider/Model-Aufrufen, Engineering Council, Toolchain-Setup, ESPHome-Validierung/Compile, Final Approval und kontrolliertem Git-Commit. Er erfordert das explizite --real-system-e2e pytest-Flag und ist nie Teil der normalen Test-Suite.</p>' +
    '<p><span class="current-badge">Heute implementiert</span> Der Real-System-E2E-Test ist produktiv und wird manuell ausgeführt.</p>'
};

docSections["sec-25"] = {
  title: "Wichtige Code-Units/Dateien",
  html: '<h3>Architekturkonzepte → Source Files Mapping</h3>' +
    '<p>Diese Übersicht mappt architektonische Konzepte auf die wichtigsten Quell-Dateien zum Verständnis von ADC. Keine mechanische Auflistung aller Dateien.</p>' +
    '<h4>Zentraler Workflow &amp; Orchestrierung</h4>' +
    '<table class="doc-table"><tr><th>Konzept</th><th>Datei</th><th>Klasse/Funktion</th></tr>' +
    '<tr><td>Haupt-Workflow</td><td>app/dev_workflow.py</td><td>DevelopmentWorkflow</td></tr>' +
    '<tr><td>Composition-Root</td><td>app/canonical_composition.py</td><td>build_canonical_components()</td></tr>' +
    '<tr><td>Projekt-Lease</td><td>app/canonical_execution.py</td><td>acquire_project_execution()</td></tr>' +
    '<tr><td>Workflow-Guard</td><td>app/workflow_execution_guard.py</td><td>try_start() / finish()</td></tr>' +
    '<tr><td>Adapter-neutraler Request</td><td>app/common_request.py</td><td>CommonRequest</td></tr></table>' +
    '<h4>Subsystem 1: Requirement Intelligence</h4>' +
    '<table class="doc-table"><tr><th>Konzept</th><th>Datei</th><th>Klasse/Funktion</th></tr>' +
    '<tr><td>Projekt-Analyse</td><td>app/project_intelligence.py</td><td>inspect_project()</td></tr>' +
    '<tr><td>Projekt-Inspektor</td><td>app/project_inspector.py</td><td>ProjectInspector</td></tr>' +
    '<tr><td>Anforderungserkennung</td><td>app/ai_requirement_discovery.py</td><td>AIRequirementDiscovery</td></tr>' +
    '<tr><td>Datenmodelle</td><td>app/requirement_model.py</td><td>Requirement, SetupEffect, etc.</td></tr></table>' +
    '<h4>Subsystem 2: Engineering Decision</h4>' +
    '<table class="doc-table"><tr><th>Konzept</th><th>Datei</th><th>Klasse/Funktion</th></tr>' +
    '<tr><td>Council-Orchestrator</td><td>app/engineering_council.py</td><td>EngineeringCouncil</td></tr>' +
    '<tr><td>Council-Datenmodelle</td><td>app/council_models.py</td><td>CouncilInput, CouncilResult</td></tr>' +
    '<tr><td>SetupPlan-Erzeugung</td><td>app/toolchain_materializer.py</td><td>ToolchainMaterializer</td></tr></table>' +
    '<h4>Subsystem 3: Environment &amp; Setup</h4>' +
    '<table class="doc-table"><tr><th>Konzept</th><th>Datei</th><th>Klasse/Funktion</th></tr>' +
    '<tr><td>Setup-Planung</td><td>app/setup_planner.py</td><td>SetupPlanner</td></tr>' +
    '<tr><td>Setup-Ausführung</td><td>app/setup_executor.py</td><td>SetupExecutor</td></tr>' +
    '<tr><td>Capability-Registry</td><td>app/execution.py</td><td>CapabilityRegistry, CONTROLLED_SETUP_EFFECTS</td></tr>' +
    '<tr><td>pip-Backend</td><td>app/python_package_executor.py</td><td>PythonPackageExecutor</td></tr></table>' +
    '<h4>Subsystem 4: Development &amp; Change</h4>' +
    '<table class="doc-table"><tr><th>Konzept</th><th>Datei</th><th>Klasse/Funktion</th></tr>' +
    '<tr><td>Entwicklungs-Stage</td><td>app/development_stage.py</td><td>DevelopmentStage</td></tr>' +
    '<tr><td>File-Applier</td><td>app/developer_file_applier.py</td><td>DeveloperFileApplier</td></tr>' +
    '<tr><td>Provenance</td><td>app/change_provenance.py</td><td>RunChangeProvenance</td></tr></table>' +
    '<h4>Subsystem 5: Quality &amp; Verification</h4>' +
    '<table class="doc-table"><tr><th>Konzept</th><th>Datei</th><th>Klasse/Funktion</th></tr>' +
    '<tr><td>Verifikationsplan</td><td>app/verification.py</td><td>VerificationPlan, VerificationStep</td></tr>' +
    '<tr><td>Test-Runner</td><td>app/project_test_runner.py</td><td>ProjectTestRunner</td></tr>' +
    '<tr><td>Test-Adapter</td><td>app/test_adapters.py</td><td>PythonPytestAdapter, ESPHomeAdapter</td></tr></table>' +
    '<h4>Subsystem 6: Delivery &amp; Outcome</h4>' +
    '<table class="doc-table"><tr><th>Konzept</th><th>Datei</th><th>Klasse/Funktion</th></tr>' +
    '<tr><td>Controlled Git</td><td>app/controlled_git_stage.py</td><td>ControlledGitStage</td></tr>' +
    '<tr><td>Controlled Publish</td><td>app/controlled_publish_stage.py</td><td>ControlledPublishStage</td></tr>' +
    '<tr><td>Git-Operationen</td><td>app/git_manager.py</td><td>GitManager</td></tr></table>' +
    '<h4>Querschnittlich</h4>' +
    '<table class="doc-table"><tr><th>Konzept</th><th>Datei</th><th>Klasse/Funktion</th></tr>' +
    '<tr><td>Diagnostic Trace</td><td>app/diagnostic_trace.py</td><td>DiagnosticTraceRecorder</td></tr>' +
    '<tr><td>Project Context</td><td>app/project_context.py</td><td>ProjectDefinitionStore</td></tr>' +
    '<tr><td>Approval Manager</td><td>app/approval_manager.py</td><td>ApprovalManager</td></tr>' +
    '<tr><td>LLM Provider</td><td>app/llm_provider_factory.py</td><td>create_llm_provider()</td></tr>' +
    '<tr><td>Web GUI</td><td>app/web_api.py</td><td>FastAPI app</td></tr>' +
    '<tr><td>MCP Server</td><td>app/mcp_server.py</td><td>MCPServer</td></tr>' +
    '<tr><td>Agent-Rollen</td><td>app/agent_roles.py</td><td>AGENT_ROLES</td></tr></table>'
};

docSections["sec-26"] = {
  title: "Heutige Implementierung vs. Zielarchitektur",
  html: '<h3>Systematischer Vergleich</h3>' +
    '<p>Diese Gegenüberstellung dokumentiert den aktuellen Implementierungsstand im Vergleich zur Zielarchitektur. <span class="current-badge">Heute implementiert</span> kennzeichnet produktive Funktionen. <span class="target-badge">Zielarchitektur</span> kennzeichnet geplante, aber noch nicht implementierte Funktionen.</p>' +
    '<h4>Setup und Umgebung</h4>' +
    '<table class="doc-table"><tr><th>Funktion</th><th>Status</th><th>Details</th></tr>' +
    '<tr><td>python_package_install Backend</td><td><span class="current-badge">Heute</span></td><td>PythonPackageExecutor mit pip, shell=False, list args</td></tr>' +
    '<tr><td>SetupPlan / SetupApproval</td><td><span class="current-badge">Heute</span></td><td>Vollständiger Approval-Workflow</td></tr>' +
    '<tr><td>Alle anderen SetupEffects</td><td><span class="target-badge">Ziel</span></td><td>Erkannt, klassifiziert, aber kein kontrolliertes Backend</td></tr>' +
    '<tr><td>System Package Install Backend</td><td><span class="target-badge">Ziel</span></td><td>apt/brew/etc. mit kontrollierter Policy</td></tr>' +
    '<tr><td>Container Runtime Setup</td><td><span class="target-badge">Ziel</span></td><td>Docker als Ziel-Laufzeitumgebung</td></tr>' +
    '<tr><td>Privilege Broker</td><td><span class="target-badge">Ziel</span></td><td>sudo/polkit/host-spezifisch für privilegierte Aktionen</td></tr>' +
    '<tr><td>Device Access Backend</td><td><span class="target-badge">Ziel</span></td><td>udev-Regeln, Geräteberechtigungen</td></tr></table>' +
    '<h4>Capability Registry</h4>' +
    '<table class="doc-table"><tr><th>Funktion</th><th>Status</th><th>Details</th></tr>' +
    '<tr><td>CapabilityRegistry</td><td><span class="current-badge">Heute</span></td><td>Mit ACTIVE/SUSPENDED/REVOKED Status</td></tr>' +
    '<tr><td>Globale Bootstrap-Registrierungen</td><td><span class="current-badge">Heute</span></td><td>Kompatibilitäts-Defaults</td></tr>' +
    '<tr><td>Dynamische projektgebundene Registrierungen</td><td><span class="target-badge">Ziel</span></td><td>ProjectIntelligence → Council → Chairman → Human → Registry</td></tr>' +
    '<tr><td>Capability Acquisition via MCP</td><td><span class="target-badge">Ziel</span></td><td>Externe Tools als MCP-Capabilities</td></tr></table>' +
    '<h4>Frontends und Kommunikation</h4>' +
    '<table class="doc-table"><tr><th>Funktion</th><th>Status</th><th>Details</th></tr>' +
    '<tr><td>Web GUI</td><td><span class="current-badge">Heute</span></td><td>Produktiv mit Chat, Trace, Approvals</td></tr>' +
    '<tr><td>API / CLI</td><td><span class="current-badge">Heute</span></td><td>Kompatibilitäts-Adapter</td></tr>' +
    '<tr><td>Signal Adapter</td><td><span class="target-badge">Ziel</span></td><td>Contract vorhanden, kein deployed Transport-Provider</td></tr>' +
    '<tr><td>MCP Client Integration</td><td><span class="target-badge">Ziel</span></td><td>Server implementiert, Client-Integration ausstehend</td></tr></table>' +
    '<h4>Laufzeitumgebung</h4>' +
    '<table class="doc-table"><tr><th>Funktion</th><th>Status</th><th>Details</th></tr>' +
    '<tr><td>Direkte Host-Ausführung</td><td><span class="current-badge">Heute</span></td><td>Aktuelle Laufzeitumgebung</td></tr>' +
    '<tr><td>Docker Container (non-root)</td><td><span class="target-badge">Ziel</span></td><td>Vorgesehene Laufzeitumgebung, ohne privileged/Docker-Socket</td></tr></table>' +
    '<h4>Physical Hardware</h4>' +
    '<table class="doc-table"><tr><th>Funktion</th><th>Status</th><th>Details</th></tr>' +
    '<tr><td>Hardware-Free Verification</td><td><span class="current-badge">Heute</span></td><td>ESPHome validate/compile, PlatformIO build</td></tr>' +
    '<tr><td>Flash / OTA / Device Ops</td><td><span class="target-badge">Ziel</span></td><td>Eigene separate Approval-Grenze erforderlich</td></tr></table>' +
    '<h4>Test-Architektur</h4>' +
    '<table class="doc-table"><tr><th>Funktion</th><th>Status</th><th>Details</th></tr>' +
    '<tr><td>Unit / Integration Tests</td><td><span class="current-badge">Heute</span></td><td>Standard pytest Suite</td></tr>' +
    '<tr><td>Real-System-E2E</td><td><span class="current-badge">Heute</span></td><td>Nur mit --real-system-e2e Flag</td></tr>' +
    '<tr><td>Browser-GUI-E2E</td><td><span class="target-badge">Ziel</span></td><td>Headless Browser-Tests</td></tr></table>'
};

docSections["sec-27"] = {
  title: "Glossar",
  html: '<h3>ADC-Begriffe</h3>' +
    '<table class="doc-table"><tr><th>Begriff</th><th>Definition</th></tr>' +
    '<tr><td><strong>ADC</strong></td><td>AI Dev Center — die Gesamtplattform</td></tr>' +
    '<tr><td><strong>Zentraler Workflow</strong></td><td>Die verbindliche Abfolge der 6 Subsysteme: Requirement Intelligence → Engineering Decision → Environment &amp; Setup → Development &amp; Change → Quality &amp; Verification → Delivery &amp; Outcome</td></tr>' +
    '<tr><td><strong>Subsystem</strong></td><td>Eines der sechs offiziellen ADC-Subsysteme mit klarer Verantwortung</td></tr>' +
    '<tr><td><strong>Unit</strong></td><td>Eine Komponente/Klasse innerhalb eines Subsystems</td></tr>' +
    '<tr><td><strong>Communication Adapter</strong></td><td>Frontend-Adapter (Web, Signal, API, CLI, MCP), der in CommonRequest mündet</td></tr>' +
    '<tr><td><strong>CommonRequest</strong></td><td>Adapter-neutrales, normalisiertes Request-Format</td></tr>' +
    '<tr><td><strong>Project Intelligence</strong></td><td>Deterministische, read-only Projektanalyse — beobachtete Realität</td></tr>' +
    '<tr><td><strong>Project Definitions</strong></td><td>Explizite dauerhafte Entscheidungen und Regeln — intentionale Policy</td></tr>' +
    '<tr><td><strong>Project Context</strong></td><td>Typisierte Vereinigung aller drei Wissensquellen mit Konflikt-Darstellung</td></tr>' +
    '<tr><td><strong>Engineering Council</strong></td><td>3-phasiger Multi-KI-Rat: A1, A2, A3 erstellen Vorschläge → Cross-Review → Chairman synthetisiert</td></tr>' +
    '<tr><td><strong>Chairman</strong></td><td>Synthese-Schritt des Councils — kein eigener Agent, sondern Empfehlungs-Selektor</td></tr>' +
    '<tr><td><strong>SetupEffect</strong></td><td>Semantische Setup-Identität (z.B. python_package_install) — beschreibt WAS, nicht WIE</td></tr>' +
    '<tr><td><strong>SetupPlan</strong></td><td>Materialisierter Plan mit SetupSteps, Status und Human-Approval-Status</td></tr>' +
    '<tr><td><strong>SetupApproval</strong></td><td>Erste Human-Approval-Grenze — vor Setup-Ausführung</td></tr>' +
    '<tr><td><strong>CapabilityRegistry</strong></td><td>Freigabe-bewusste Registrierung von ausführbaren Capabilities</td></tr>' +
    '<tr><td><strong>ApprovalProvenance</strong></td><td>Vollständige Autoritätskette: PI → Council → Chairman → Human</td></tr>' +
    '<tr><td><strong>Controlled Execution</strong></td><td>Ausführung mit shell=False, list args, Timeout, Output-Limits, allowlist-basiert</td></tr>' +
    '<tr><td><strong>Human Approval</strong></td><td>Vier separate Grenzen: Setup, Capability, Final, Publish — nicht übertragbar</td></tr>' +
    '<tr><td><strong>ChangeProvenance</strong></td><td>Hash-basierte Änderungsverfolgung pro Datei pro Run</td></tr>' +
    '<tr><td><strong>VerificationPlan</strong></td><td>Typisierte, area-bewusste Prüfstrategie aus ProjectIntelligence</td></tr>' +
    '<tr><td><strong>Diagnostic Trace</strong></td><td>Persistente Laufzeitbeobachtung — x→f→y Modell, beobachtet, entscheidet nicht</td></tr>' +
    '<tr><td><strong>Rework</strong></td><td>Maximal ein kontrollierter Wiederholungszyklus nach rework_required</td></tr>' +
    '<tr><td><strong>Publish</strong></td><td>Ausschließlich Git Remote Push — kein Deployment, Release oder CI/CD</td></tr>' +
    '<tr><td><strong>MCP</strong></td><td>Model Context Protocol — Zielarchitektur für Capability-Integration</td></tr>' +
    '<tr><td><strong>OpenRouter</strong></td><td>Aktueller Provider/Gateway — keine architektonische Abhängigkeit</td></tr>' +
    '<tr><td><strong>Privilege Broker</strong></td><td>Zielarchitektur: host-spezifischer Mechanismus (sudo/polkit) für privilegierte Aktionen</td></tr>' +
    '<tr><td><strong>Requirement Activation</strong></td><td>Klassifiziert Anforderungen als blockierend, nicht-blockierend oder inaktiv</td></tr>' +
    '<tr><td><strong>Recovery</strong></td><td>Zustand nach Abbruch — keine automatische Wiederholung unsicherer Aktionen</td></tr>' +
    '<tr><td><strong>State Lock</strong></td><td>Prozess-lokaler Mutex — nur eine mutierende Operation pro Projektpfad</td></tr>' +
    '<tr><td><strong>WorkflowState</strong></td><td>Autoritativ für Entscheidungen — getrennt vom beobachtenden DiagnosticTrace</td></tr>' +
    '<tr><td><strong>ToolchainMaterializer</strong></td><td>Konvertiert CouncilResult in einen SetupPlan</td></tr>' +
    '<tr><td><strong>MissingToolchainSetup</strong></td><td>Brücke: TOOL_UNAVAILABLE → SetupPlan → Human Approval → Retry</td></tr></table>'
};
