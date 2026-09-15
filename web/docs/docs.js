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
  '<text x="325" y="295" font-size="8" fill="#4a5568">TestingStage — Diagnose nach Tests</text>' +
  '<text x="325" y="309" font-size="8" fill="#4a5568">DevelopmentTestingStage — Dev+Test</text>' +
  '<text x="325" y="323" font-size="8" fill="#4a5568">TestChangeGenerator</text>' +
  '<line x1="290" y1="270" x2="310" y2="270" stroke="#3182ce" stroke-width="1.5" marker-end="url(#dep-arr)"/>' +
  '<rect x="610" y="210" width="280" height="120" rx="6" fill="#ebf4ff" stroke="#3182ce"/>' +
  '<text x="750" y="230" text-anchor="middle" font-size="10" font-weight="700" fill="#2b6cb0">6. Delivery &amp; Outcome</text>' +
  '<line x1="620" y1="237" x2="880" y2="237" stroke="#3182ce" stroke-width="0.5"/>' +
  '<text x="625" y="253" font-size="8" fill="#4a5568">FinalApproval — abschließende Freigabe</text>' +
  '<text x="625" y="267" font-size="8" fill="#4a5568">ControlledGitStage — lokaler Commit</text>' +
  '<text x="625" y="281" font-size="8" fill="#4a5568">PublishApproval — Publish-Freigabe</text>' +
  '<text x="625" y="295" font-size="8" fill="#4a5568">ControlledPublishStage — Git Push</text>' +
  '<line x1="590" y1="270" x2="610" y2="270" stroke="#3182ce" stroke-width="1.5" marker-end="url(#dep-arr)"/>' +
  '<rect x="10" y="355" width="880" height="75" rx="6" fill="#fefcbf" opacity="0.4" stroke="#d69e2e"/>' +
  '<text x="450" y="375" text-anchor="middle" font-size="10" font-weight="700" fill="#975a16">Querschnittliche Units</text>' +
  '<text x="25" y="393" font-size="8" fill="#744210">DiagnosticTrace — persistente Laufzeitbeobachtung  |  ProjectContext — dauerhafte Entscheidungen</text>' +
  '<text x="25" y="407" font-size="8" fill="#744210">ExecutionIdentity — stabile Prozessor-IDs</text>' +
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
    '<p><span class="target-badge">Zielarchitektur</span> Docker ist die vorgesehene Laufzeitumgebung. Der Core-Container läuft non‑root, ohne privileged mode und ohne Docker-Socket- oder Device-Mounts. <span class="current-badge">Heute implementiert</span> ADC läuft direkt auf dem Host.</p>' +
    '<h3>Zielarchitektur: ADC-Selbstentwicklung (Themenspeicher)</h3>' +
    '<p><span class="target-badge">Zielarchitektur — nicht implementiert</span> Langfristiges Ziel ist, dass ADC sich selbst warten kann: eigene Defekte diagnostizieren, sich selbst reparieren, neue ADC-Features entwickeln und eigene Änderungen testen/verifizieren — mit derselben Architektur, denselben Approval-, Sicherheits- und Evidenz-Regeln, die für externe Projekte gelten (kein separater, privilegierterer Pfad für ADC als Ziel-Projekt seiner selbst). Dieser Abschnitt beschreibt ausschließlich die Zielrichtung; kein Teil der ADC-Selbstentwicklung ist heute implementiert oder getestet.</p>'
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
    '<p><strong>Verantwortung:</strong> Multi-Agenten Council (A1/A2/A3) erzeugt und bewertet technische Alternativen, Chairman synthetisiert eine Empfehlung, der Benutzer trifft (Zielarchitektur) die finale Engineering-Auswahl. S2 erzeugt eine EngineeringDecision, keinen SetupPlan — der SetupPlan entsteht erst in S3 (Environment &amp; Setup). Intern gegliedert in die Subsubsysteme S2.1–S2.5 (Pilot, siehe Abschnitt 10).</p>' +
    '<p><strong>Eingabe:</strong> ProjectIntelligence + Requirements + Preflight</p>' +
    '<p><strong>Ausgabe:</strong> CouncilResult, EngineeringDecision</p></div>' +
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
    '<tr><td>TestingStage</td><td>testing_stage.py</td><td>Diagnose nach Tests</td></tr>' +
    '<tr><td>DevelopmentTestingStage</td><td>development_testing_stage.py</td><td>Dev+Test-Koordination</td></tr>' +
    '<tr><td>TestChangeGenerator</td><td>test_change_generator.py</td><td>Test-Änderungen generieren</td></tr></table>' +
    '<h4>6. Delivery &amp; Outcome</h4>' +
    '<table class="doc-table"><tr><th>Unit</th><th>Datei</th><th>Verantwortung</th></tr>' +
    '<tr><td>FinalApproval</td><td>final_approval.py</td><td>Abschließende Human-Freigabe</td></tr>' +
    '<tr><td>ControlledGitStage</td><td>controlled_git_stage.py</td><td>Fail-Safe lokaler Commit</td></tr>' +
    '<tr><td>PublishApproval</td><td>publish_approval.py</td><td>Separate Publish-Freigabe</td></tr>' +
    '<tr><td>ControlledPublishStage</td><td>controlled_publish_stage.py</td><td>Kontrollierter Git Push</td></tr></table>' +
    '<h4>Querschnittliche Units</h4>' +
    '<table class="doc-table"><tr><th>Unit</th><th>Datei</th><th>Verantwortung</th></tr>' +
    '<tr><td>DiagnosticTrace</td><td>diagnostic_trace.py</td><td>Persistente Workflow-Beobachtung</td></tr>' +
    '<tr><td>ProjectContext / Definitions</td><td>project_context.py</td><td>Dauerhafte Entscheidungen</td></tr>' +
    '<tr><td>LLMProviderFactory</td><td>llm_provider_factory.py</td><td>Provider-Instanziierung</td></tr>' +
    '<tr><td>CommonRequest</td><td>common_request.py</td><td>Adapter-neutrales Request-Format</td></tr>' +
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
    '<h4>Producer → Artifact → Consumer: LLM-Antwort → strukturierte Requirements (CLAUDE-E2E-NIO-005A)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> Producer: der konfigurierte LLM-Provider (<code>complete_structured</code>/<code>complete</code>). Artifact: der rohe Antworttext, erwartungsgemäß ein einzelnes JSON-Objekt mit dem Schlüssel <code>"requirements"</code>. Consumer: <code>AIRequirementDiscovery._parse_response()</code>, das daraus die strukturierte Requirements-Liste extrahiert, die <code>DevelopmentWorkflow.run()</code> anschließend konsumiert. Ein realer Real-System-E2E-Lauf blockierte hier real mit "LLM response is not valid JSON.", weil die Fenced-Code-Erkennung einen strikten Ganztext-Abgleich auf genau einen <code>```json</code>-getaggten Block voraussetzte — ein Block ohne "json"-Tag oder mit Prosa davor/danach (beides real reproduzierte, plausible Provider-Formatierungen) ließ diesen Abgleich fehlschlagen und wurde fälschlich als <code>InvalidDiscoveryJSONError</code> eingestuft, der einzigen Fehlerklasse, für die <code>discover()</code> nie einen Repair-Versuch unternimmt. Seit diesem Fix sucht die Extraktion einen Fenced-Block an beliebiger Stelle im Text, mit optionalem Sprach-Tag, bevor sie als nicht-JSON gilt — echte, unstrukturierte Antworten bleiben weiterhin korrekt abgelehnt.</p>' +
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
    '<h4>Entscheidungsprinzip (Zielarchitektur, ADC_Zielbild Abschnitt 2/3)</h4>' +
    '<p><strong>Council schlägt Alternativen vor. Chairman synthetisiert und empfiehlt. Der Benutzer trifft die finale Engineering-Auswahl. Human Approval ist eine eigene, spätere Freigabe für die mutierende Setup-Ausführung.</strong></p>' +
    '<p>Diese vier Begriffe sind bewusst verschieden und dürfen nicht verwechselt werden:</p>' +
    '<ul><li><strong>Chairman-Empfehlung:</strong> „Diese Lösung halte ich technisch für die beste Variante.“ — eine Synthese-Aussage, keine Entscheidung.</li>' +
    '<li><strong>Menschliche Engineering-Auswahl (Ziel):</strong> Der Benutzer nimmt die Empfehlung an, wählt eine andere zulässige Alternative, lehnt ab, verschiebt oder verlangt Rework.</li>' +
    '<li><strong>Setup-/Mutations-Freigabe (Human Approval):</strong> „Diese konkrete mutierende Aktion darf ausgeführt werden.“ — unabhängig davon, wer die Variante gewählt hat.</li>' +
    '<li><strong>Ausführungsautorisierung:</strong> die separate, capability-gebundene Freigabe der konkreten Executor-Bindung (Abschnitt 14).</li></ul>' +
    '<p>Die automatische Erkennung technischer Eignung ist nicht gleichbedeutend mit automatischer Setup-Fähigkeit.</p>' +
    '<h4>Fehlerbehandlung</h4>' +
    '<ul><li>Unvollständiger Council blockiert zentral vor Materialisierung</li>' +
    '<li>CouncilFailedError, CouncilChairmanError, AgentParseError</li>' +
    '<li>Partiell erfolgreiche Vorschläge/Reviews bleiben inspizierbar</li></ul>' +
    '<p><span class="current-badge">Heute implementiert</span> Der vollständige 3-Phasen-Council mit A1/A2/A3 und Chairman ist produktiv. Der Real-System-E2E-Test übt ihn mit echten Provider/Model-Aufrufen.</p>' +
    '<h4>Subsubsystem-Architektur S2.1–S2.5 (Pilot, siehe ADC_Zielbild Abschnitt 4A)</h4>' +
    '<p>S2 ist intern in fünf Subsubsystem-Verantwortungen gegliedert. Die Nummerierungsregel gilt verbindlich für die gesamte ADC-Architektur: <strong>Subsystem = Sx</strong> (S1…S6), <strong>Subsubsystem = Sx.y</strong> (z. B. S2.1…S2.5) — <strong>Sx.y ist die tiefste nummerierte Ebene</strong>, ein weiteres <code>Sx.y.z</code> wird nie eingeführt. Unterhalb von Sx.y stehen ausschließlich benannte Units/Komponenten/Funktionen/Typen.</p>' +
    '<div class="subsystem-card"><h4>S2.1 Engineering Alternatives</h4>' +
    '<p>Erzeugt mehrere unabhängige, technisch sinnvolle Alternativen (Phase 1) und sammelt Cross-Review-Evidenz (Phase 2). Nutzt Projekt-/Umgebungsevidenz (siehe unten). Besitzt keine Empfehlungs-, keine Zulässigkeits- und keine finale Auswahl-Autorität und erzeugt keine EngineeringDecision.</p>' +
    '<p><span class="current-badge">Heute implementiert</span></p></div>' +
    '<div class="subsystem-card"><h4>S2.2 Engineering Synthesis &amp; Recommendation</h4>' +
    '<p>Chairman-Synthese und Empfehlung an den Benutzer. Vergleicht Vorschläge anhand von Scores/Konsens; ein Ranking (Rang, Gesamt-Score) wird, wo verfügbar, gebildet. Bei technisch unzulässiger eigener Empfehlung: EIN gebundener, gezielter Reparaturversuch anhand der von S2.3 gelieferten Evidenz (EngineeringReworkRequest) — maximal zwei Chairman-Synthesen insgesamt. Implementiert keine eigene technische Zulässigkeitspolitik; fragt dafür ausschließlich S2.3 ab.</p>' +
    '<p><strong>CLAUDE-ARCH-S2-014C (F3 — eindeutige Varianten-Identität):</strong> der Synthese-Protokoll-Parser (<code>_parse_chairman_result</code>) lehnt ein Chairman-Ergebnis mit zwei oder mehr Varianten, die dieselbe <code>id</code> teilen, jetzt strukturell ab (<code>CouncilChairmanError</code>, category=<code>duplicate_variant_id</code>) — bevor S2.3, S2.4 oder ein Mensch die Kandidaten je zu sehen bekommen. Zuvor konnte eine SET-Berechnung doppelte IDs stillschweigend zusammenfassen, während die zugrunde liegende Liste beide unterschiedlichen Kandidaten weiterhin enthielt — nachgelagerter Code, der per „erstes Match“ auflöst, und Code, der per Dictionary „letztes Match gewinnt“ auflöst, konnten sich dann auf ZWEI verschiedene Objekte für dieselbe ID einigen: „Mensch sieht Variante A, sendet deren ID, Auflösung liefert Variante B“. Weder Umbenennen noch Auswahl der ersten/letzten Dopplung — eine mehrdeutige Identität wird ausschließlich abgelehnt, und S2.3s eigenes <code>validate_variants()</code> lehnt zusätzlich, unabhängig vom Parser, jede Variante mit geteilter ID als unzulässig ab.</p>' +
    '<p><span class="current-badge">Heute implementiert</span></p></div>' +
    '<div class="subsystem-card"><h4>S2.3 Engineering Admissibility</h4>' +
    '<p>Die EINZIGE technische Zulässigkeitsautorität innerhalb S2. Prüft: bindende Requirements-Abdeckung, Constraints/Plattform-Kompatibilität, Operationsrelevanz (blockierend vs. nicht-blockierend), grundsätzliche kontrollierte Materialisierbarkeit (ein reines Go/No-Go-Signal, keine SetupPlan-Erzeugung), Setup-/Executor-Kompatibilität und Verification Feasibility. Bewahrt mehrere zulässige Alternativen, rankt, wählt, mutiert, merged und repariert niemals selbst einen Kandidaten.</p>' +
    '<p><strong>CLAUDE-ARCH-S2-014C (F4 — semantische Requirement-Erfüllung):</strong> „Bindende Requirements-Abdeckung“ bedeutet mehr als ein übereinstimmender <code>requirement_ref</code> — <code>requirement_ref</code> ist ein Verweis, kein Beweis semantischer Erfüllung. Für jedes bindende Requirement muss mindestens ein referenzierendes ToolchainItem zusätzlich mechanisch zu Typ, technischer Identität (bei Python-Paketen über dieselbe PyPI-Normalisierung, die bereits die Preflight-Prüfung nutzt) und — soweit strukturiert vorhanden — Version der Requirement passen; ein unrelated Executable mit demselben <code>requirement_ref</code> zählt nicht mehr als Abdeckung. Ein fehlendes <code>technical_identity</code>-Feld am ToolchainItem bei Python-Paketen bleibt unentschieden (keine erfundene Fehlpassung) und der bereits bestehenden Materialisierbarkeits-Diagnose (Real-System-E2E #8/012D) vorbehalten.</p>' +
    '<p><span class="current-badge">Heute implementiert</span></p>' +
    '<h5>Verification Feasibility (CLAUDE-ARCH-S2-013E, mechanisch verschärft in CLAUDE-ARCH-S2-013F/013G/014C)</h5>' +
    '<p>S2.3 beantwortet ausschließlich: <strong>„Kann dieser Kandidat später kontrolliert und aussagekräftig verifiziert werden?“</strong> — niemals „hat die Verification bestanden?“ (das bleibt ausschließlich S5 Quality &amp; Verification vorbehalten; S2.3 führt nichts aus, startet keinen Prozess, ruft app.verification nicht auf). Ein bloßer, nicht-leerer Freitext im Feld <code>verification</code> (z. B. „Tests laufen lassen“) reicht seit CLAUDE-ARCH-S2-013E NICHT mehr aus. Verlangt wird stattdessen die strukturierte Kette Requirement → <code>VerificationCoverage</code> (technologie-neutrale <code>kind</code> aus test_command/build_command/static_analysis/probe/smoke_test/config_validation/manual_review, ein einzelnes technisches <code>mechanism</code>-Token wie „pytest“, „npm_test“, „cargo_test“, „go_test“, „esphome_validate“ — nie ein Shell-Kommando, nie freier Text) → <code>evidence</code>, die eine bereits in derselben Variante vorhandene Toolchain-Identität benennt. Keine geschlossene Python-only-Liste: jede konkrete, einzeltokenige Technologie-Kennung ist zulässig.</p>' +
    '<p><strong>CLAUDE-ARCH-S2-013F</strong> schließt die von der unabhängigen Prüfung von 013E gefundene mechanische Lücke: eine strukturell begründete, aber ökosystem-fremde Kombination (z. B. <code>mechanism="pytest"</code> mit einem echten npm-Toolchain-Item als <code>evidence</code>) zählte zuvor fälschlich als Abdeckung. Jedes ToolchainItem erklärt jetzt selbst, strukturiert, im Feld <code>provides_verification</code>, welche Mechanismen es tatsächlich ausführen kann — exakt dieselbe Muster-Beziehung, die <code>provided_by</code> bereits für Installationsabhängigkeiten nutzt. S2.3 prüft Kompatibilität dadurch als reine Mengen-Zugehörigkeit (<code>mechanism</code> ∈ <code>provides_verification</code> des per <code>evidence</code> referenzierten Items) — niemals über eine fest verdrahtete Mechanismus-/Ökosystem-Tabelle und niemals über String-Heuristiken wie „pytest enthält py“. Kontrollierbarkeit/Beobachtbarkeit wird über das bereits bestehende Feld <code>ToolchainItem.state</code> nachgewiesen: <code>state="unavailable"</code> bedeutet, ADC kann das Werkzeug gar nicht erst beschaffen und damit den Mechanismus weder kontrollieren noch beobachten. Eine manuelle Prüfung (<code>kind="manual_review"</code>) hat nichts Installierbares, gegen das Kompatibilität geprüft werden könnte; sie zählt stattdessen nur, wenn <code>VerificationCoverage.human_governed</code> explizit <code>true</code> ist — ein stillschweigend angenommener manueller Schritt zählt nie.</p>' +
    '<p><strong>CLAUDE-ARCH-S2-013G</strong> schließt die von der unabhängigen Prüfung von 013F gefundene Selbstzertifizierungslücke: <code>provides_verification</code> und <code>human_governed</code> werden vom SELBEN Agenten-/Chairman-Lauf erklärt, der auch den Kandidaten erzeugt — ein LLM konnte also weiterhin eine erfundene oder unpassende Verifikationsfähigkeit einfach selbst behaupten (z. B. <code>mechanism="pytest"</code> UND <code>provides_verification=("pytest",)</code> auf einem Kandidaten, der nichts mit pytest zu tun hat). Eine bloße Produzenten-Erklärung reicht seither NICHT mehr aus: <code>mechanism</code> ∈ <code>provides_verification</code> ist weiterhin erforderlich, muss aber zusätzlich durch unabhängige, von ADC selbst — bereits VOR dem Council-Lauf, deterministisch — erzeugte Evidenz gedeckt sein. Diese stammt aus der bestehenden Existing-Project-Intelligence-Erkennung (Test-/Build-Systeme, Firmware-Indikatoren) und wird über <code>app.verification.trusted_verification_identity_groups()</code> bereitgestellt, die die bereits bestehende, bereits getestete Zuordnung aus der Generalized-Verification-Architektur wiederverwendet (nie eine zweite, konkurrierende Tabelle). Analog braucht <code>manual_review</code> zusätzlich zu <code>human_governed=true</code> einen von ADC selbst (nicht vom Council) anerkannten, tatsächlich existierenden Human-Verification-Pfad (<code>governed_manual_verification_ids</code>) — produktiv füllt diesen Kanal aktuell noch niemand, sodass <code>manual_review</code> ehrlich fail-closed bleibt, bis ein späterer Task ihn tatsächlich verdrahtet. S2.3 selbst importiert dabei weiterhin nichts aus der S5-Ausführungsmaschinerie: die aufrufende Seite (<code>DevelopmentWorkflow</code>, <code>EngineeringCouncil</code>) berechnet die vertrauenswürdigen Gruppen und übergibt sie als reine, bereits fertige Daten. Eine Ablehnung benennt exakt das betroffene Requirement, die Kandidaten-Identität, den erklärten Mechanismus, den referenzierten Beleg und den genauen Kompatibilitäts-/Kontroll-/Governance-Grund (<code>EngineeringReworkRequest.verification_feasibility_conflict_detail</code>) und ist für die bestehende gebundene S2.2-Reparatur nutzbar.</p>' +
    '<p><strong>CLAUDE-ARCH-S2-014C (F1 — Phantom-/Fremd-Referenzen)</strong> schließt eine unabhängig reproduzierte Lücke: für <code>manual_review</code>/<code>probe</code>/<code>config_validation</code> galt bislang <code>evidence</code> ∈ <code>requirement_refs</code> als ausreichende Erdung — eine Tautologie, die derselbe LLM-Lauf vollständig kontrolliert (er erklärt beide Felder selbst), sodass ein erfundener oder aus einem anderen Kontext kopierter Requirement-Verweis unbemerkt Abdeckung erzeugen konnte, sogar wenn er neben einem echten Verweis im selben Eintrag „mitreiste“. Jetzt muss JEDE in <code>requirement_refs</code> genannte ID unabhängig, deterministisch von S1/Preflight als tatsächlich bindend bestätigt sein, bevor Erdung/Kompatibilität überhaupt geprüft werden — einheitlich über alle Verification-Kinds hinweg. Ein Eintrag mit auch nur einer Phantom-/Fremd-ID wird vollständig verworfen, niemals nur teilweise für den echten Verweis honoriert.</p>' +
    '<p><strong>CLAUDE-ARCH-S2-014C (F2 — Erkennung beweist keine Fähigkeit)</strong> schließt eine zweite unabhängig reproduzierte Lücke in <code>trusted_verification_identity_groups()</code>: bislang genügte reine NAMENSERKENNUNG durch Project Intelligence (z. B. „ctest“ oder „jest“), um Vertrauen zu erzeugen — unabhängig davon, ob RUNNER_MAP/BUILD_RUNNER_MAP für diesen Namen überhaupt einen registrierten, kontrollierten Runner vorsieht (ctest/jest/vitest/mocha/make sind dort ausdrücklich „deferred“, ohne jeden registrierten Runner in <code>app.verification.build_default_registry()</code>), und PlatformIOs eigenes <code>has_untrusted_hooks</code>-Flag wurde in der Vertrauensberechnung gar nicht erst konsultiert. Vertrauen setzt jetzt zusätzlich voraus, dass die zugrunde liegende Zuordnung <code>policy=="controlled_execution"</code> trägt (dieselbe Richtlinien-Angabe, die auch <code>build_verification_plan()</code> für S5 verwendet — keine zweite, konkurrierende Vorstellung von „kontrollierbar“), und dass PlatformIO-Firmware zusätzlich <code>has_untrusted_hooks=False</code> aufweist. Ebenso wird <code>ToolchainItem.state</code> jetzt gegen eine POSITIVE Zulassungsliste (<code>needs_install</code>/<code>already_installed</code>) statt nur gegen den Ausschluss von „unavailable“ geprüft, damit ein unbekannter/fehlerhafter Statuswert nicht stillschweigend als kontrollierbar durchgeht.</p>' +
    '<p><strong>CLAUDE-ARCH-S2-014D (Scope-Bindung — Projekt/Area/Pfad)</strong> schließt eine dritte, unabhängig gefundene Lücke: <code>trusted_verification_identity_groups()</code> erzeugte Vertrauensgruppen bislang aus der PROJEKTWEITEN, über alle Areas hinweg deduplizierten Namensliste (<code>ProjectIntelligence.test_system_names</code>/<code>build_system_names</code>) — eine in Area A entdeckte Fähigkeit (z. B. pytest) konnte dadurch die Verification-Anforderung einer damit vollkommen unzusammenhängenden Area B mitbestätigen. Jede Vertrauensgruppe trägt jetzt zusätzlich den exakten <code>ProjectArea.path</code>, aus dem sie tatsächlich stammt; nur am Projekt-Root (".") entdeckte Evidenz gilt — mechanisch durch Dateisystem-Containment, nie durch Annahme — als ehrlich projektweit. <code>VerificationCoverage.area</code> (neu, optional) erklärt, für welche Area/welchen Pfad ein Kandidat seine Evidenz beansprucht; S2.3 akzeptiert dabei ausschließlich exakte Übereinstimmung, echte Pfad-Containment (Projekt &gt; Area &gt; Pfad, niemals bloßer String-Präfix-Vergleich) oder eine root-gebundene Gruppe — nie einen impliziten projektweiten Fallback für area-lokale Evidenz. Bestehende Projekte ohne Area-Aufschlüsselung (Einzel-Area-Fall, die weit überwiegende Mehrheit) bleiben unverändert produktiv.</p>' +
    '<p><span class="current-badge">Heute implementiert</span></p></div>' +
    '<div class="subsystem-card"><h4>S2.4 Human Engineering Authority</h4>' +
    '<p><strong>Zielarchitektur:</strong> Der Benutzer ist die finale Engineering-Entscheidungsautorität. Er kann die Chairman-Empfehlung annehmen, eine andere von S2.3 als zulässig ausgewiesene Alternative wählen, ablehnen, aufschieben oder Rework anfordern.</p>' +
    '<p><span class="current-badge">Heute implementiert (CLAUDE-ARCH-S2-013C)</span> Der produktive Workflow (<code>DevelopmentWorkflow.run()</code>) stoppt jetzt tatsächlich an dieser Grenze: sobald S2.3 mindestens einen zulässigen Kandidaten findet, liefert <code>run()</code> ausschließlich eine anzeigefertige <code>EngineeringVariantSelection</code> (Chairman-Empfehlung + alle zulässigen Alternativen) zurück — <strong>keine</strong> EngineeringDecision, <strong>kein</strong> SetupPlan. Erst ein expliziter Aufruf von <code>DevelopmentWorkflow.resolve_engineering_selection()</code> mit einer echten menschlichen <code>human_selected_variant_id</code> (auch das Annehmen der Empfehlung übergibt diese ID explizit) löst S2.4 tatsächlich auf und liefert <code>selection_authority="human"</code>. Produktiv über Web/API erreichbar via <code>GET</code>/<code>POST /api/workflow/&#123;session_id&#125;/engineering-decision</code> (Aktionen: accept, select, reject, defer, rework). Eine unbekannte oder technisch unzulässige Kandidaten-ID wird sicher abgelehnt, niemals stillschweigend akzeptiert. <span class="target-badge">Zielarchitektur — teilweise offen</span> "Rework" (eine komplett neue Council-/Chairman-Runde auf menschliche Anforderung) ist bewusst nicht implementiert: die Zielarchitektur definiert dafür noch keine ausreichend präzise Semantik (welche Evidenz nutzt ein neuer Chairman-Prompt? wie viele Versuche?); die Aktion wird sicher aufgezeichnet, ohne die bestehende, gebundene automatische S2.3→S2.2-Reparatur zu berühren oder eine neue Council-Runde zu erfinden.</p></div>' +
    '<div class="subsystem-card"><h4>S2.5 Engineering Decision &amp; S3 Handoff</h4>' +
    '<p>Erzeugt das finale EngineeringDecision-Artefakt aus einer bereits gültigen S2.4-Auswahl, bewahrt exakte Kandidaten-Identität, Auswahl-Autorität und Validierungs-Provenienz. EngineeringDecision ist das einzige Artefakt, das die S2→S3-Grenze im Normalfall überquert. <code>ToolchainMaterializer.materialize_decision()</code> gehört zu S3, nicht zu S2.5 — S2.5 endet mit der Veröffentlichung des Artefakts.</p>' +
    '<p><span class="current-badge">Heute implementiert</span></p></div>' +
    '<p><strong>Python-Pakete:</strong> Der Anzeigename (z. B. ESPHome CLI) bleibt vom expliziten Distributionsnamen (<code>technical_identity</code>, z. B. esphome) getrennt. Fehlende oder mehrdeutige Paketidentität wird nicht aus dem Anzeigenamen geraten und blockiert die automatische Zulässigkeit. Die Paketpräsenz wird über <code>pip_show</code> für genau diese Distribution im kontrollierten Ziel-Python geprüft. Auch ein leeres Greenfield-Projekt kann damit eine installierbare HOST-Variante erhalten; tatsächlich vorhanden ist das Paket erst nach erfolgreicher Prüfung im Installationsziel. Projektvalidierung und Kompilierung ersetzen diesen Paketnachweis nicht.</p>' +
    '<h4>Bereits vorhandene Umgebung (Project Intelligence + Preflight)</h4>' +
    '<p>S2.1 und S2.2 erhalten strukturiert bereits bekannte Projekt-/Umgebungsevidenz (Project Intelligence: Projekttyp, Sprachen, Frameworks, Package-Systeme; Preflight: bereits installierte/fehlende Requirements) und verwenden sie in den Agenten-/Chairman-Prompts. S2.3 zählt ein bereits erfülltes Requirement nicht als offene Abdeckungspflicht — eine Variante, die eine bereits vorhandene Capability nicht erneut installiert, wird dafür nicht abgelehnt. Unnötiges Setup soll dadurch vermieden werden, wo eine Capability bereits nachweislich vorhanden ist.</p>' +
    '<p><span class="current-badge">Heute implementiert</span> (strukturierter Datenfluss und S2.3-Auswertung). Ob ein einzelner LLM-Lauf diese Evidenz inhaltlich optimal nutzt, ist Laufzeitverhalten und nicht deterministisch garantierbar.</p>' +
    '<h4>Alternativen, Pro/Contra und Ranking (Zielbild Abschnitt 25)</h4>' +
    '<p>Für jede finale Variante stehen strukturiert zur Verfügung: Vorteile/Nachteile, Risiken, Verification-Strategie, Confidence/Feasibility, Konsens-Level, Rang und Gesamt-Score. Für die Chairman-Empfehlung zusätzlich: gewählte Variante, technische Begründung, erfüllte Requirements, benötigte Umgebung/Änderungen.</p>' +
    '<p><span class="current-badge">Heute implementiert (CLAUDE-ARCH-S2-013C)</span> <code>GET /api/workflow/&#123;session_id&#125;/engineering-decision</code> liefert genau diese Struktur: die Chairman-Empfehlung (mit <code>is_recommendation: true</code>) sowie jede weitere zulässige Alternative, jeweils mit Vorteilen/Nachteilen, Risiken, Verification-Feld, Rang/Score, Requirement-Abdeckung und Toolchain. Unzulässige Kandidaten werden separat als <code>rejected_candidates</code> (reine Diagnose-Information, nicht auswählbar) mitgeliefert. Eine dedizierte grafische Entscheidungs-Oberfläche (statt der reinen API) ist noch <span class="target-badge">Zielarchitektur</span>.</p>'
};

docSections["sec-11"] = {
  title: "Engineering Council und Chairman",
  html: '<h3>Council-Architektur im Detail</h3>' +
    '<h4>Rollen und Provider</h4>' +
    '<p>Die Council-Rollen werden in config.yml konfiguriert. Jede Rolle kann einen eigenen Provider, Model, Timeout und Temperature haben:</p>' +
    '<pre class="doc-code">council:\n  roles:\n    a1_environment_architect:\n      provider: openrouter\n      model: deepseek/deepseek-v4-pro\n      timeout_seconds: 120\n      temperature: 0.3\n    a2_toolchain_integrator:\n      provider: openrouter\n      model: deepseek/deepseek-v4-pro\n      timeout_seconds: 120\n      temperature: 0.3\n    a3_risk_feasibility_assessor:\n      provider: openrouter\n      model: deepseek/deepseek-v4-pro\n      timeout_seconds: 120\n      temperature: 0.3\n    chairman:\n      provider: openrouter\n      model: deepseek/deepseek-v4-pro\n      timeout_seconds: 180\n      temperature: 0.2</pre>' +
    '<h4>Chairman-Funktion</h4>' +
    '<p>Der Chairman ist kein zusätzlicher Agent mit eigener Meinung, sondern ein Synthese-Schritt: „Synthese und Auswahl der Empfehlung.“ (ADC_Zielbild Abschnitt 2).</p>' +
    '<ul><li>Konsolidiert die drei Agent-Vorschläge (A1, A2, A3)</li>' +
    '<li>Berücksichtigt die Cross-Reviews aus Phase 2</li>' +
    '<li>Empfiehlt eine Variante (CouncilVariant) — wählt sie NICHT final aus</li>' +
    '<li>Erzeugt strukturierte ToolchainItem-Empfehlungen</li>' +
    '<li>Die Chairman-Empfehlung ist die Grundlage für die nachfolgende technische Zulässigkeitsprüfung (S2.3) und — im Zielbild — für die menschliche Engineering-Auswahl (S2.4)</li></ul>' +
    '<h4>Sicherheit und Autoritätsgrenzen</h4>' +
    '<p>Der Council hat keine Ausführungsautorität. Seine Ausgabe ist eine <strong>Empfehlung</strong>. Vier Begriffe bleiben strikt getrennt: Chairman-Empfehlung ≠ menschliche Engineering-Auswahl ≠ Setup-Mutations-Freigabe (Human Approval) ≠ Ausführungsautorisierung. Eine Chairman-Empfehlung ist keine automatische Ausführungsfreigabe.</p>' +
    '<p><span class="target-badge">Zielarchitektur — nicht produktiv</span> Im Zielbild wählt der Benutzer explizit zwischen Annehmen der Empfehlung, Wahl einer anderen zulässigen Alternative, Ablehnung, Aufschieben oder Rework-Anforderung (S2.4 Human Engineering Authority), BEVOR ein SetupPlan erzeugt wird. Produktiv (<code>DevelopmentWorkflow.run()</code>) wird die zulässige Chairman-Empfehlung heute ohne diese Zwischen-Interaktion direkt zur EngineeringDecision — der ToolchainMaterializer erzeugt daraus unmittelbar den SetupPlan, für den anschließend die (separate) Setup-Freigabe eingeholt wird. Details siehe Abschnitt 10 (S2.4).</p>'
};

docSections["sec-12"] = {
  title: "Environment & Setup",
  html: '<h3>Subsystem 3: Umgebung und Einrichtung</h3>' +
    DOC_DIAGRAMS.envsetup +
    '<h4>Ablauf</h4>' +
    '<ol><li><strong>SetupPlan-Erstellung:</strong> SetupPlanner erzeugt SetupPlan aus Requirements + PreflightResult + kontrollierten SetupEffects</li>' +
    '<li><strong>Human Approval:</strong> SetupApproval erfordert explizite Freigabe vor jeder Ausführung</li>' +
    '<li><strong>Kontrollierte Ausführung:</strong> SetupExecutor führt nur genehmigte Schritte mit registrierten Backends aus</li>' +
    '<li><strong>Verifikation:</strong> Nach der Ausführung wird die Verfügbarkeit erneut geprüft</li></ol>' +
    '<h4>SetupPlan</h4>' +
    '<pre class="doc-code">SetupPlan:\n  project_id: str\n  steps: tuple[SetupStep, ...]\n  status: str  # pending | approved | executed | rejected\n\nSetupStep:\n  id: str\n  action: str           # "install" | "manual_review"\n  setup_effect: str     # SetupEffect identity\n  is_approved: bool</pre>' +
    '<h4>MissingToolchainSetup</h4>' +
    '<p>Die Brücke zwischen TOOL_UNAVAILABLE und Verification-Retry: Tool fehlt → SetupPlan → Human Approval → Setup → Retry des originalen VerificationPlan. Installationserfolg erteilt keine Capability-Autorität.</p>' +
    '<h4>Persistierter Ausführungs-Status und Retry-/Restart-Sicherheit (CLAUDE-E2E-003H)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> Jeder einzelne SetupStep-Ausführungsversuch wird projekt-/plan-/step-gebunden persistiert (<code>app/setup_execution_state.py</code>, ökosystem-neutral — keine pip/Python-spezifischen Felder), bevor die eigentliche externe Mutation beginnt. Das generische Zustandsmodell: <code>not_started → in_progress → succeeded | failed</code>, mit <code>recovery_required</code> für eine nach Neustart vorgefundene, unaufgelöste <code>in_progress</code>-Aufzeichnung.</p>' +
    '<p><strong>Verbindliche Sicherheitsregel:</strong> Ein bekannt erfolgreicher Setup-Mutations-Schritt wird niemals stillschweigend erneut ausgeführt, nur weil eine Ausführungsanfrage wiederholt wird — weder in derselben ADC-Prozessinstanz noch nach einem Neustart mit frischem Store. Ein bekannt fehlgeschlagener Schritt wird ebenso wenig automatisch wiederholt. Eine nach Unterbrechung vorgefundene <code>in_progress</code>-Aufzeichnung gilt als Ergebnis-unsicher und schlägt kontrolliert fehl (<code>SetupExecutionStateError</code>), statt geraten zu werden.</p>' +
    '<p><span class="security-principle">ADC beansprucht ausdrücklich KEINE generische "exactly once"-Garantie über beliebige Prozessabstürze hinweg.</span> Stirbt ADC nach dem Start der echten mutierenden Operation aber vor der Persistierung des Ergebnisses, bleibt der Zustand <code>in_progress</code> und wird beim nächsten Zugriff als erholungsbedürftig behandelt — nicht automatisch wiederholt, nicht stillschweigend als sicher angenommen. Backend-Idempotenz (z.B. dass ein erneutes <code>pip install</code> harmlos wäre) wird nicht als zentraler Sicherheitsmechanismus vorausgesetzt; der reale Beleg ist ein tatsächlich beobachteter Startzähler, nicht angenommene Idempotenz.</p>' +
    '<p>Die Zustandsprüfung (<code>DevelopmentWorkflow._execute_with_state_guard</code>) liegt zentral zwischen Autorisierung (Abschnitt 14) und tatsächlicher Ausführung und wird von Web/API und MCP über denselben zentralen Pfad geerbt — keine adapter-eigene Retry-Logik in web_api.py oder mcp_server.py. Diagnostic Trace kann diese Übergänge beobachten, ist aber niemals die Autorität dafür; autoritativ ist ausschließlich der persistierte Ausführungs-Status selbst.</p>' +
    '<h4>Verbindliche Execution-State-Authority und Setup-Generation (CLAUDE-E2E-003I)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> Eine konfinierte, produktive Setup-Ausführung (mit <code>project_root</code>) erfordert zwingend einen konfigurierten <code>execution_state_store</code> — <code>DevelopmentWorkflow.execute_approved()</code> schlägt kontrolliert fehl (<code>WorkflowExecutionError</code>), statt ohne Replay-Schutz auszuführen, wenn keiner konfiguriert ist. Web- und MCP-Produktions-Composition (<code>canonical_composition.py</code>, <code>mcp_transport.py</code>) verdrahten immer einen echten Store; nur ein bewusst unkonfinierter Low-Level-Aufruf ohne <code>project_root</code> (nie über Web/MCP/den Application Service erreichbar) bleibt ohne diese Autorität zulässig.</p>' +
    '<p>Retry-Schutz allein reicht jedoch nicht: Ein einmal erfolgreich eingerichtetes Environment kann später wieder ungültig werden (Tool extern entfernt, venv gelöscht, Container neu gebaut, SDK korrupt). Deshalb führt ADC eine zentrale, generisch persistierte <strong>Setup-Generation</strong> (<code>SetupPlan.generation_id</code>) ein, unabhängig von der pro Projekt stabilen <code>plan.id</code>: Jede echte Neu-Materialisierung (<code>ToolchainMaterializer.materialize()</code>) erhält eine neue, zentral erzeugte, niemals client-vorgebbare Generation; Genehmigung, erneute Ausführung (Retry) und Neustart derselben materialisierten Entscheidung behalten dieselbe Generation. Der Execution-State (Abschnitt oben) ist an project + generation + step + Inhalt gebunden, nicht an plan.id allein — eine bereits erfolgreiche Generation A blockiert eine spätere, neu genehmigte Generation B für denselben logischen Schritt nicht dauerhaft.</p>' +
    '<p><strong>Generation-gebundene Human Approval:</strong> <code>human_approval_ref</code> und die zugehörige DiagnosticTrace-Aufzeichnung binden die Generation-ID ein, damit eine Freigabe für Generation A niemals mit einer Freigabe für Generation B verwechselt werden kann — auch wenn Projekt, Plan, Schritt und Zielausführbare identisch sind. <code>CapabilityRegistry.supersede_approved()</code> erlaubt es einer neuen Generation ausdrücklich, eine alte Registrierung für exakt dieselbe Capability/dasselbe Ziel mit frischer, vollständiger Provenance zu ersetzen — dieselbe Validierung wie <code>register_approved()</code>, keine Abschwächung, kein zweiter Autorisierungsweg.</p>' +
    '<h4>Approved-Plan-Content-Immutability vor der ersten Ausführung (CLAUDE-E2E-003I-B)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> <strong>REQ-S3-APPROVED-PLAN-CONTENT-IMMUTABILITY:</strong> Human Approval autorisiert den execution-relevanten Inhalt der exakt materialisierten Setup-Generation. Eine mechanische Reproduktion vor jeder Codeänderung bestätigte real: Solange noch keine erste Ausführung stattgefunden hat, existiert noch kein <code>SetupExecutionState</code>-Datensatz — und die generationsbasierte Content-Immutability aus CLAUDE-E2E-003I-A (unten) kann folglich noch nichts vergleichen. Eine für Generation G1/Schritt S1/Inhalt A erteilte Freigabe autorisierte in diesem Fenster stillschweigend auch einen auf Inhalt B geänderten Schritt, solange Generation-ID, Schritt-ID und Status "approved" unverändert blieben. <code>app.approved_plan_content.ApprovedPlanContentStore</code> schließt dies: <code>record_approved()</code> zeichnet genau bei der echten Human-Approval-Transition (<code>approve_setup_plan()</code>) den execution-relevanten Inhalt-Fingerabdruck jedes Schritts persistent auf; <code>verify()</code> — aufgerufen vom selben zentralen <code>authorize_setup_plan_targets()</code>-Gate, das auch die Capability-Registrierung entscheidet — schlägt kontrolliert fehl (<code>ApprovedPlanContentError</code>), sobald der aktuelle Inhalt vom aufgezeichneten abweicht oder für die Generation überhaupt kein aufgezeichneter Inhalt existiert. Diese Bindung ist rein generation-basiert (keine Projekt-Bindung nötig, da <code>generation_id</code> bereits global eindeutig ist), restart-stabil (persistierte Datei, keine In-Memory-Rekonstruktion nötig) und schützt auch Mehr-Schritt-Pläne: Ein einzelner geänderter Schritt lässt die Autorisierung des gesamten Plans fehlschlagen, bevor irgendein Schritt registriert wird. Ergänzt, aber ersetzt nicht, die Cross-Process-Claim-Sicherheit und die generationsbasierte Content-Immutability unten.</p>' +
    '<h4>Same-Generation-Content-Immutability (CLAUDE-E2E-003I-A)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> <strong>REQ-S3-GENERATION-CONTENT-IMMUTABILITY:</strong> Der execution-relevante Inhalt eines genehmigten SetupSteps darf sich innerhalb derselben Setup-Generation nicht ändern. Eine unabhängige Prüfung von CLAUDE-E2E-003I fand real, dass ein Inhalts-Mismatch unter demselben (Projekt, Generation, Schritt)-Schlüssel zuvor stillschweigend als NOT_STARTED behandelt wurde — eine geänderte Mutation hätte unter einer Freigabe starten können, die für diesen Inhalt nie erteilt wurde. Seit CLAUDE-E2E-003I-A schlägt <code>SetupExecutionStateStore.get()</code>/<code>begin()</code> in diesem Fall kontrolliert fehl (<code>SetupExecutionStateError</code>), statt den Vorgang als frisch startbar misszuverstehen. Ein tatsächlich geänderter Vorgang erfordert zwingend eine neue Materialisierung → neue Generation → neue Human Approval → neue Autorisierung → neuen Execution State. Diese Regel greift ausschließlich AB dem Zeitpunkt, an dem ein erster Execution-State-Datensatz existiert — das vorgelagerte Zeitfenster (Genehmigung bis erste Ausführung) schützt die Approved-Plan-Content-Immutability oben.</p>' +
    '<h4>Legacy-Execution-State-Upgrade-Sicherheit (CLAUDE-E2E-003I-A)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> Ein echter, vor CLAUDE-E2E-003I persistierter Execution-State-Datensatz (Schlüssel: die rohe <code>plan.id</code>, ohne "legacy-"-Präfix, da dieses Konzept damals nicht existierte) wurde nach der Umstellung auf generationsbasierte Identität unsichtbar — die real reproduzierte zweite, unabhängig gefundene Lücke. <code>SetupExecutionStateStore._find_raw_record()</code> führt seither einen rein lesenden Kompatibilitäts-Lookup durch: Wird unter der aufgelösten Legacy-Generation ("legacy-{plan.id}") nichts gefunden, wird zusätzlich unter der rohen <code>plan.id</code> gesucht. Es findet keine physische Migration und kein Schreibvorgang statt — dadurch ist der Lookup trivial idempotent und führt zu keiner neuen Cross-Process-Race-Fläche.</p>' +
    '<h4>Cross-Process-Claim-Sicherheit (CLAUDE-E2E-003I)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> Der reine In-Prozess-Lock (<code>threading.RLock</code>) schützt nur gegen gleichzeitige Threads in einem Python-Prozess. <code>SetupExecutionStateStore.claim_or_report()</code> hält zusätzlich einen echten Betriebssystem-Advisory-File-Lock (<code>fcntl.flock</code>), pro exakter (Projekt, Generation, Schritt)-Identität, für die gesamte Prüf-und-Beanspruchungs-Entscheidung. Damit können zwei echte, getrennte OS-Prozesse nicht beide NOT_STARTED beobachten und beide claimen — nur einer erhält den Claim, der andere schlägt kontrolliert fehl oder erhält das bereits persistierte Ergebnis. Der Lock ist reiner Nebenläufigkeits-Mechanismus: Verschwindet er, weil der haltende Prozess abgestürzt ist, bedeutet das NICHT, dass die Mutation sicher nicht stattgefunden hat — die persistierte Execution State bleibt allein maßgeblich, der Lock entscheidet niemals über Replay-/Recovery-Sicherheit.</p>' +
    '<h4>Zielarchitektur: Kontinuierliche Environment-Validierung</h4>' +
    '<p><span class="target-badge">Zielarchitektur — teilweise implementiert</span> S3 ist nicht nur für die initiale Einrichtung zuständig, sondern für die technische Entwicklungsumgebung über den gesamten Projekt-Lebenszyklus. Die Zielarchitektur sieht vor, dass S3 das erforderliche Environment-Soll gegen den tatsächlichen Environment-Ist-Zustand an relevanten Workflow-Kontrollpunkten wiederholt prüft, unter anderem: Projekt-Aktivierung, neue Entwicklungsaufgabe, geänderte Anforderungen, neue Engineering-Entscheidung, geänderte Build-/Toolchain-Konfiguration, vor Build/Compile, vor relevanten Tests/Verifikation, nach Environment-/Tool-Fehlern, nach Setup-Änderungen und nach ADC-/Prozess-Neustart. Werden fehlende oder geänderte Voraussetzungen erkannt, folgt derselbe Ablauf wie bei initialem Setup: Setup-Bedarf feststellen → Human Approval, wo Mutation erforderlich ist → kontrollierte Ausführung → Verifikation → aktualisierten Environment-Status persistieren.</p>' +
    '<p><span class="current-badge">Heute implementiert</span> ist ausschließlich die einmalige Preflight-Prüfung vor genehmigter Ausführung plus die in diesem Abschnitt beschriebene Retry-/Restart-Sicherheit für den Ausführungsversuch selbst. Eine wiederkehrende, automatische Soll-/Ist-Prüfung an den oben genannten Kontrollpunkten ist <strong>nicht</strong> implementiert und darf nicht als bereits vorhanden dargestellt werden.</p>'
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
    '<p><span class="current-badge">Heute implementiert</span> Globale Bootstrap-Registrierungen sind Kompatibilitäts-Defaults. <span class="target-badge">Zielarchitektur</span> Dynamische Registrierungen sind immer projektgebunden.</p>' +
    '<h4>Setup-Ausführungsziel-Autorisierung (CLAUDE-E2E-003E/F/G)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> Zusätzlich zur separaten Capability-Approval-Grenze oben registriert <strong>Setup Approval selbst</strong> das bereits während Preflight aufgelöste, exakte <code>target_executable</code> jedes genehmigten SetupSteps als projekt-gebundene <code>CapabilityRegistration</code> — über dieselbe, unveränderte <code>CapabilityRegistry.register_approved()</code>-Prüfung, keine zweite Autorisierungs-Mechanik. Dadurch übersteht ein einmal genehmigtes Ausführungsziel spätere PATH-Änderungen des Hosts, ohne die Bootstrap-Capability zu erweitern und ohne beliebige Pfade zu autorisieren. <code>engineering_council_ref</code>/<code>chairman_approval_ref</code> stammen aus der echten, in <code>WorkflowPlanStore</code> persistierten Council-Referenz (nie von einem Adapter/Client mitgeliefert); <code>human_approval_ref</code> referenziert ein reales, im zentralen Diagnostic-Trace-Store aufgezeichnetes Freigabe-Ereignis. Maßgeblich für die Autorisierungsentscheidung bleibt jedoch der persistierte SetupPlan-Status selbst — Diagnostic Trace ist Beleg, nicht Autorität.</p>'
};

docSections["sec-15"] = {
  title: "Human Approval und Sicherheitsgrenzen",
  html: '<h3>Sicherheitsarchitektur</h3>' + DOC_DIAGRAMS.security +
    '<h4>Human Approval Grenzen</h4>' +
    '<p>ADC definiert <strong>vier separate</strong> Human-Approval-Grenzen. Eine Freigabe an einer Grenze autorisiert niemals eine andere:</p>' +
    '<table class="doc-table"><tr><th>Grenze</th><th>Wann</th><th>Was sie autorisiert</th></tr>' +
    '<tr><td><strong>Setup Approval</strong></td><td>Vor Setup-Ausführung</td><td>Ausführung des genehmigten SetupPlans; autorisiert zusätzlich das bereits aufgelöste Ausführungsziel jedes Schritts projekt-gebunden gegen spätere PATH-Änderungen (siehe Abschnitt 14)</td></tr>' +
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
    '<p>Nach einem rework_required-Ergebnis ist genau <strong>ein</strong> kontrollierter Rework-Zyklus erlaubt. Ein weiteres rework_required beendet den Run.</p>' +
    '<h4>Producer → Artifact → Consumer: Working-Tree-Baseline (CLAUDE-E2E-NIO-006B/006C)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> Producer: <code>RunChangeProvenance.capture_working_tree_baseline()</code>, aufgerufen genau einmal von <code>ProjectSetupApplicationService.execute_approved_setup_and_development()</code> unmittelbar nach der Konstruktion von <code>RunChangeProvenance</code> — also bevor irgendeine eigene mutierende Aktion dieses Runs (Setup-Ausführung, Entwicklung, Verifikation) beginnt. Artifact: <code>{Pfad: {status, content_hash}}</code> für jeden zu diesem Zeitpunkt bereits untracked/geänderten Pfad im Projekt-Working-Tree — seit CLAUDE-E2E-NIO-006C bewusst der volle Zustand pro Pfad (echte <code>git status</code>-Klasse plus echter Inhalts-Hash), nicht mehr nur die Pfad-Zugehörigkeit selbst: Ein bereits bei Run-Start dirty gewesener Pfad kann während des Runs durch einen nicht genehmigten Seiteneffekt ERNEUT verändert werden, während der Pfad selbst unverändert bleibt — eine reine Pfadmenge könnte das nicht erkennen. Persistiert über <code>WorkflowManager.capture_working_tree_baseline()</code>, werkzeug-/artefakt-neutral (ausschließlich echter <code>git status</code> und echter Inhalts-Hash, niemals Dateiname, Endung oder Zeitstempel). Consumer: <code>ControlledGitStage.run()</code> (Subsystem 6, siehe unten), das einen zum Commit-Zeitpunkt verbleibenden untracked/geänderten Pfad außerhalb der genehmigten Provenance nur dann als unverändertes, vorbestehendes Fremdelement behandelt, wenn sowohl Status als auch Inhalts-Hash exakt der Baseline entsprechen — jede Abweichung (oder das vollständige Fehlen in der Baseline) bleibt ein benannter Blocker. Damit produziert S4 die Baseline, während S6 sie am Auslieferungs-Entscheidungspunkt konsumiert — bewusst kein rein S6-internes Konzept.</p>'
};

docSections["sec-17"] = {
  title: "Quality & Verification",
  html: '<h3>Subsystem 5: Qualität und Verifikation</h3>' +
    '<p><strong>Abgrenzung zu S2.3 Verification Feasibility (Abschnitt 10):</strong> S2.3 beantwortet vor jeder Ausführung nur, OB ein technisch zulässiger Kandidat grundsätzlich kontrolliert verifizierbar ist (eine strukturierte Machbarkeits-/Abdeckungsprüfung, kein Ausführungsschritt). S5 hier ist die einzige Instanz, die tatsächlich verifiziert und über bestanden/fehlgeschlagen entscheidet — S2.3 trifft diese Aussage nie und führt selbst nichts aus.</p>' +
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
    '<li>Fremder gestagter Content · Finaler Hash-Mismatch · Nicht-Fast-Forward-Push · Authentifizierungsfehler</li>' +
    '<li><strong>Neuer oder erneut mutierter unaccounted change (CLAUDE-E2E-NIO-006A/006B/006C)</strong> · Ein zum Commit-Zeitpunkt verbleibender untracked/geänderter Pfad außerhalb der genehmigten Provenance, der entweder gar nicht in der Run-Working-Tree-Baseline vorkommt oder dort mit abweichendem Status/Inhalts-Hash vorliegt</li></ul>' +
    '<h4>Producer → Artifact → Consumer: Committed-Outcome-Wahrhaftigkeit (CLAUDE-E2E-NIO-006A/006B/006C)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> Producer eines unerklärten Seiteneffekts: jedes von ADC während des Runs kontrolliert ausgeführte externe Tool (z. B. <code>esphome compile</code> während der Verifikation), dessen eigene Seiteneffekte (z. B. eine von ESPHome selbst erzeugte <code>.gitignore</code>) niemals über ChangeProvenance nachverfolgt werden. Ein realer Real-System-E2E-Lauf erreichte 93&nbsp;% und scheiterte real daran, dass <code>commit_approved_run()</code> <code>"committed"</code> meldete, obwohl <code>git status --porcelain</code> weiterhin <code>?? .gitignore</code> zeigte. CLAUDE-E2E-NIO-006A schloss dies zunächst mit einer globalen Post-Staging-Sauberkeitsprüfung — die jedoch zu breit war: Sie hätte auch einen Commit über bereits vorbestehenden, fremden, projektunabhängigen Inhalt in einem realen Bestandsprojekt blockiert, den ADC unverändert lassen und trotzdem erfolgreich committen können muss. CLAUDE-E2E-NIO-006B stellt die Unterscheidung wieder her, ohne die reale E2E-Lektion abzuschwächen: <code>ControlledGitStage.run()</code> prüft weiterhin nach dem Staging der genehmigten Pfade den gesamten Working-Tree-Status im Projekt-Scope, blockiert aber nur noch einen Pfad, der WEDER Teil der genehmigten Provenance NOCH Teil der bei Run-Start erfassten Working-Tree-Baseline (siehe Subsystem 4 oben) ist. Vorbestehender fremder Inhalt bleibt vollständig unangetastet und blockiert nichts; ein echt neuer, während des Runs eingeführter, nicht genehmigter Pfad blockiert weiterhin — niemals stillschweigend als Erfolg gemeldet, niemals automatisch gestaged, committed oder gelöscht.</p>'
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
    '<p>Der MCPServer enthält keine Business-Logik. Jedes Tool delegiert an eine existierende Komponente der umgebenden Applikation.</p>' +
    '<h4>Zentraler Planungs-/Freigabe-/Ausführungspfad (CLAUDE-E2E-003G)</h4>' +
    '<p><span class="current-badge">Heute implementiert</span> <code>plan_project_setup</code>, <code>approve_setup_plan</code> und <code>execute_setup_plan</code> rufen denselben zentralen <code>ProjectSetupApplicationService</code>-Vertrag auf, den auch die Web GUI verwendet — nie einen schmaleren, MCP-eigenen Pfad. Project Intelligence/Context, Requirement Discovery/Validation/Preflight, Engineering Council und Toolchain Materialization laufen für einen MCP-erzeugten SetupPlan exakt wie für einen Web-erzeugten. Fehlt der zentrale Service, schlägt jedes dieser drei Tools kontrolliert fehl (<code>MCPCentralServiceRequiredError</code>) statt auf einen älteren, ungeprüften Pfad zurückzufallen.</p>' +
    '<p>Die projekt-gebundene Ausführungsziel-Autorisierung (siehe Abschnitt 14) greift für einen MCP-genehmigten SetupPlan identisch: <code>execute_setup_plan</code> liest die Engineering-Council-Referenz aus derselben <code>WorkflowPlanStore</code>-Persistenz, die auch die Web GUI schreibt — nie aus einem vom Client mitgelieferten Wert.</p>' +
    '<p><span class="target-badge">Verbleibende Einschränkung</span> <code>execute_setup_plan</code> führt bewusst nur die genehmigten Setup-Schritte aus (kein Development/Testing/Rework-Zyklus) — ein schmalerer, aber weiterhin zentraler Vertrag (<code>DevelopmentWorkflow.execute_approved()</code>, denselben die Web GUI intern für ihre eigene Setup-Phase verwendet), nicht eine zweite, abweichende Autorisierungslogik.</p>'
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
    '<p>ADC definiert eine klare Test-Hierarchie mit spezifischen Zwecken und Grenzen pro Ebene (seit CLAUDE-E2E-003G verbindlich präzisiert):</p>' +
    '<table class="doc-table"><tr><th>Ebene</th><th>Zweck</th><th>Grenze</th></tr>' +
    '<tr><td><strong>Unit</strong></td><td>Einzelne Funktionen/Klassen testen</td><td>Keine externen Abhängigkeiten, keine LLM-Calls, kein Dateisystem</td></tr>' +
    '<tr><td><strong>6 offizielle Subsystem-Suiten</strong></td><td>Jeweils risikogetriebene Testfälle für genau eines der sechs offiziellen Subsysteme (Abschnitt 5): Requirement Intelligence, Engineering Decision, Environment &amp; Setup, Development &amp; Change, Quality &amp; Verification, Delivery &amp; Outcome</td><td>Echte ADC-Komponenten wo praktikabel; nur LLM/externe/nicht-deterministische Grenzen ersetzbar. Eine Suite gilt erst als abgedeckt, wenn sie mehrere relevante Testfälle über mehrere Dimensionen (Happy Path, Negativ/Fail-Closed, Boundary/Identity, Persistence/State, Security/Isolation, Recovery/Retry — nur die relevanten) enthält, nicht schon bei einem einzelnen grünen Test</td></tr>' +
    '<tr><td><strong>System-Suite</strong></td><td>Mehrere Testfälle, die den vollständigen produktiven Lebenszyklus über einen echten, extern erreichbaren ADC-Adapter (Web/API, MCP) prüfen — nie eine direkte ApplicationService-Aufrufkette mit versteckten, testseitig übergebenen Berechtigungsnachweisen</td><td>Gemockter LLM/Council-Grenzwert erlaubt; interne ADC-Komponenten bleiben echt. Ein einzelner grüner Testfall bedeutet nicht, dass die System-Suite vollständig ist</td></tr>' +
    '<tr><td><strong>Real-System-E2E</strong></td><td>Separate Abnahme-Ebene: vollständigen produktiven Workflow mit echten Providern/Modellen</td><td>Opt-in via --real-system-e2e Flag, nie Teil der normalen Suite, nie Ersatz für Unit/Subsystem/System-Nachweise</td></tr>' +
    '<tr><td><strong>Browser-GUI-E2E</strong></td><td>Web-GUI-Interaktion testen</td><td>Headless Browser, gemocktes Backend</td></tr>' +
    '<tr><td><strong>Manual Smoke</strong></td><td>Manuelle Überprüfung der produktiven Umgebung</td><td>Keine Automatisierung</td></tr></table>' +
    '<p><span class="security-principle">"6/6" bezieht sich ausschließlich auf die sechs offiziellen Subsysteme aus Abschnitt 5 — nicht auf interne Test-Scope-Bezeichnungen wie "Target Selection", "Materialization", "Persistence", "Approval/Capability", "Execution" oder "Full Setup". Diese sind Units bzw. Szenarien innerhalb/um Subsystem 3 (Environment &amp; Setup), keine eigenen offiziellen Subsysteme.</span></p>' +
    '<h4>Real-System-E2E</h4>' +
    '<p>Der Real-System-E2E-Test übt den vollständigen produktiven Workflow mit echten externen Provider/Model-Aufrufen, Engineering Council, Toolchain-Setup, ESPHome-Validierung/Compile, Final Approval und kontrolliertem Git-Commit. Er erfordert das explizite --real-system-e2e pytest-Flag und ist nie Teil der normalen Test-Suite.</p>' +
    '<p><span class="current-badge">Heute implementiert</span> Der Real-System-E2E-Test ist produktiv und wird manuell ausgeführt.</p>' +
    '<h4>Pre-E2E-Realismus-Prinzip (CLAUDE-E2E-003I)</h4>' +
    '<p>Verbindliche Regel: Subsystem- und System-Tests sollen so viel des realen Fehlerraums wie praktikabel bereits VOR einem bezahlten/externen Real-System-E2E emulieren. Subsystem-Testing ist nicht gleichbedeutend mit umfangreichem Mocking — echte lokale Komponenten (echte ausführbare Dateien, reale PATH-Manipulation, mehrere Executable-Versionen, echte Subprozesse, lokale Package-Repositories, echte Prozess-Neustarts, echte OS-Prozess-Nebenläufigkeit) werden bevorzugt, wo praktikabel. Mocks/Ersetzungen sind nur für genuin externe, nicht-deterministische, teure oder anderweitig ungeeignete Grenzen zulässig. Eine gemockte kritische interne ADC-Grenze ist niemals als alleiniger Abnahmenachweis ausreichend.</p>' +
    '<h4>Permutationsbasiertes Pre-E2E-Testing</h4>' +
    '<p>Die Pre-E2E-Teststrategie deckt Kombinationen relevanter Risikodimensionen systematisch ab (z.B. Tool-Zustand, Ziel-Identität, PATH-Zustand, Paket/Abhängigkeit, Netzwerk, Berechtigungen, Persistenz-Zustand, Execution State, Approval-Zustand, Projekt/Toolchain-Familie) — NICHT als vollständiges kartesisches Produkt. Stattdessen risikogetrieben: (1) kritische Sicherheitsinvarianten möglichst erschöpfend, (2) wichtige Interaktionsdimensionen paarweise, (3) hochriskante Sicherheits-/Persistenz-Interaktionen selektiv 3-fach, (4) jeder historische Real-E2E-Fund als permanenter exakter Regressionsfall. <span class="security-principle">Diese vollständige Permutationsmatrix ist NICHT bereits vollständig implementiert — CLAUDE-E2E-003I etabliert die Regel und deckt nur die für sein eigenes Execution-Generation-/Nebenläufigkeits-Scope direkt relevanten Kombinationen ab.</span></p>' +
    '<h4>Historical-E2E-Regression-Regel</h4>' +
    '<p>Verbindliche Regel: Jeder künftige Real-System-E2E-NIO-Befund wird nach Root-Cause-Analyse klassifiziert. Ist er lokal reproduzierbar, wird er zwingend zu einem permanenten deterministischen Subsystem- oder System-Regressionstestfall (abhängig davon, ob die Ursache in einem Subsystem isoliert ist oder erst über mehrere Subsysteme/Adapter hinweg auftritt) — dieser muss die reale NIO-Bedingung so originalgetreu wie praktikabel emulieren, gegen die defekte Implementierung fehlschlagen, nach dem Fix bestehen und dauerhaft in der Regressionssuite verbleiben. Nur wenn eine reale Fehlerbedingung lokal nicht sinnvoll reproduzierbar ist, darf sie Real-E2E-only bleiben — dann muss dokumentiert werden, warum, und welcher externe Faktor tatsächlich Real-E2E-spezifisch bleibt. Ziel: Ein einmal durch Real E2E entdeckter Fehler soll, wo technisch möglich, nie wieder einen Real E2E benötigen, um dieselbe Regression zu erkennen.</p>' +
    '<h4>TC = ausführbares Requirement/Contract (CLAUDE-E2E-003I-A)</h4>' +
    '<p>Verbindliches Zähl- und Berichtsprinzip: Ein Testfall (TC) ist der ausführbare Nachweis eines oder mehrerer Requirements/Contracts. Ein Requirement kann durch mehrere TCs abgedeckt sein; ein einzelner TC kann mehrere Requirements/Contracts gleichzeitig beweisen. Daraus folgt zwingend: <strong>Requirement-/Contract-Anzahl ist NICHT gleich TC-Anzahl.</strong> Ein einzelner, tatsächlich neu von pytest gesammelter Testfall darf im Bericht niemals mehrfach gezählt werden, nur weil er mehrere Contracts gleichzeitig abdeckt — maßgeblich für "neu hinzugefügte Testfälle" ist ausschließlich das mechanische <code>pytest --collect-only</code>-Delta, "abgedeckte Contracts" wird als separate, davon unabhängige Kennzahl berichtet.</p>'
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
    '<tr><td>Controlled Publish</td><td>app/controlled_publish_stage.py</td><td>ControlledPublishStage</td></tr></table>' +
    '<h4>Querschnittlich</h4>' +
    '<table class="doc-table"><tr><th>Konzept</th><th>Datei</th><th>Klasse/Funktion</th></tr>' +
    '<tr><td>Diagnostic Trace</td><td>app/diagnostic_trace.py</td><td>DiagnosticTraceRecorder</td></tr>' +
    '<tr><td>Project Context</td><td>app/project_context.py</td><td>ProjectDefinitionStore</td></tr>' +
    '<tr><td>LLM Provider</td><td>app/llm_provider_factory.py</td><td>create_llm_provider()</td></tr>' +
    '<tr><td>Web GUI</td><td>app/web_api.py</td><td>FastAPI app</td></tr>' +
    '<tr><td>MCP Server</td><td>app/mcp_server.py</td><td>MCPServer</td></tr>' +
    '<tr><td>Agent-Rollen</td><td>app/agent_roles.py</td><td>AGENT_ROLES</td></tr></table>'
};

docSections["sec-26"] = {
  title: "Heutige Implementierung vs. Zielarchitektur",
  html: '<h3>Systematischer Vergleich</h3>' +
    '<p>Diese Gegenüberstellung dokumentiert den aktuellen Implementierungsstand im Vergleich zur Zielarchitektur. <span class="current-badge">Heute implementiert</span> kennzeichnet produktive Funktionen. <span class="target-badge">Zielarchitektur</span> kennzeichnet geplante, aber noch nicht implementierte Funktionen.</p>' +
    '<h4>Governance: Wiederkehrender Ziel-vs-Code-Audit</h4>' +
    '<p>Nach signifikanter Architekturarbeit, vor relevanten Real-System-E2E-Läufen und nach architekturbezogenen E2E-Fehlschlägen führt ADC einen strukturierten Ziel-vs-Code-Audit durch: <code>ADC_Zielbild_Ausfuehrliche_Beschreibung.txt</code> (Zielarchitektur) ↕ tatsächliche Implementierung ↕ Tests/Evidence. Jeder geprüfte Punkt wird klassifiziert als <strong>EXACT MATCH</strong>, <strong>PARTIAL MATCH</strong>, <strong>IMPLEMENTATION DEVIATION</strong>, <strong>MISSING</strong> oder <strong>TARGET AMBIGUITY</strong>.</p>' +
    '<p><span class="security-principle">Würde eine vorgeschlagene Korrektur die etablierte Zielarchitektur selbst ändern, statt den Code wieder in Konformität zu bringen, erfordert dies zuerst eine ausdrückliche Freigabe durch den Benutzer.</span> Die Zielarchitektur wird niemals still an den aktuellen Code angepasst, um eine gefundene Abweichung verschwinden zu lassen.</p>' +
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
    '<tr><td><strong>Chairman</strong></td><td>Synthese-Schritt des Councils — kein eigener Agent, sondern Empfehlungs-Selektor. Empfehlung ≠ menschliche Auswahl ≠ Setup-Freigabe ≠ Ausführungsautorisierung.</td></tr>' +
    '<tr><td><strong>Subsubsystem (Sx.y)</strong></td><td>Tiefste nummerierte Architekturebene unterhalb eines Subsystems Sx (z.&nbsp;B. S2.1…S2.5). Ein weiteres Sx.y.z wird nie eingeführt; darunter stehen nur benannte Units.</td></tr>' +
    '<tr><td><strong>Human Engineering Authority (S2.4)</strong></td><td>Zielarchitektur: der Benutzer trifft die finale Engineering-Auswahl (annehmen/andere Alternative/ablehnen/aufschieben/Rework). <span class="target-badge">Nicht produktiv</span> — der Workflow pausiert heute nicht dafür, siehe Abschnitt 10/11.</td></tr>' +
    '<tr><td><strong>EngineeringDecision</strong></td><td>Finales S2-Artefakt (Variante, Solution Class, Auswahl-Autorität) — einziges Artefakt, das die S2→S3-Grenze im Normalfall überquert</td></tr>' +
    '<tr><td><strong>CandidateValidation</strong></td><td>S2.3-Ergebnis pro Kandidat: zulässig/unzulässig mit exakten, deterministischen Gründen — nie eine Präferenz</td></tr>' +
    '<tr><td><strong>Varianten-Identität (CLAUDE-ARCH-S2-014C, F3)</strong></td><td>Jede CouncilVariant.id muss innerhalb eines CouncilResult eindeutig sein. Doppelte IDs werden am Chairman-Synthese-Parser strukturell abgelehnt (CouncilChairmanError) und, unabhängig davon, von validate_variants() als mehrdeutig/unzulässig markiert — nie umbenannt, nie durch Wahl der ersten/letzten Dopplung stillschweigend aufgelöst.</td></tr>' +
    '<tr><td><strong>Semantische Requirement-Erfüllung (CLAUDE-ARCH-S2-014C, F4)</strong></td><td>requirement_ref ist ein Verweis, kein Beweis. Coverage gilt nur, wenn mindestens ein referenzierendes ToolchainItem zusätzlich Typ, technische Identität (PyPI-normalisiert bei Python-Paketen) und — soweit vorhanden — Version der Requirement mechanisch erfüllt.</td></tr>' +
    '<tr><td><strong>VerificationCoverage (S2.3, CLAUDE-ARCH-S2-013E/013F/013G/014C/014D)</strong></td><td>Strukturierter Nachweis, dass ein Kandidat ein bindendes Requirement mit einer erkannten, begründeten Verification-Mechanik abdeckt (kind + mechanism-Token + evidence + human_governed + area) — bloßer Freitext genügt nicht mehr. Seit 013F muss evidence zusätzlich mechanisch zu einem ToolchainItem passen, das mechanism in seinem eigenen provides_verification deklariert und dessen state einer positiven Zulassungsliste (needs_install/already_installed) angehört. Seit 013G reicht diese Produzenten-Erklärung allein nicht mehr: mechanism und die Toolchain-Identität müssen zusätzlich auf dieselbe, von Project Intelligence unabhängig erkannte reale Fähigkeit zurückgehen (trusted_verification_groups), und manual_review braucht zusätzlich einen von ADC selbst anerkannten Governance-Pfad (governed_manual_verification_ids). Seit 014C muss außerdem JEDE ID in requirement_refs unabhängig als bindend bestätigt sein (keine Phantom-/Fremd-Referenzen) UND die unabhängig erkannte Fähigkeit muss über eine tatsächlich registrierte, kontrollierte Ausführungsroute verfügen (nicht nur „erkannt“). Seit 014D muss diese Fähigkeit zusätzlich am selben Ort (Projekt/Area/Pfad, über area deklariert) unabhängig erkannt worden sein — eine in einer anderen Area entdeckte Fähigkeit legitimiert nie eine unzusammenhängende Area. Beweist nur Machbarkeit, nie ein tatsächliches Bestehen (das bleibt S5).</td></tr>' +
    '<tr><td><strong>ToolchainItem.provides_verification (CLAUDE-ARCH-S2-013F, seit 013G/014C nur EIN Baustein)</strong></td><td>Vom Produzenten (Agent/Chairman) erklärte, strukturierte Menge der Verification-Mechanismus-Kennungen, die DIESES ToolchainItem tatsächlich ausführen kann — spiegelt exakt das Muster von provided_by. Grundlage für S2.3s mechanischen Kompatibilitätsnachweis; nie eine fest verdrahtete Mechanismus-/Ökosystem-Tabelle. Seit CLAUDE-ARCH-S2-013G allein NICHT mehr ausreichend — muss zusätzlich durch app.verification.trusted_verification_identity_groups() (unabhängige, vom Council nicht beeinflusste Project-Intelligence-Evidenz) bestätigt werden, sonst ist es reine Selbstzertifizierung; seit CLAUDE-ARCH-S2-014C zählt diese Evidenz nur, wenn die zugrunde liegende Zuordnung auch policy=="controlled_execution" trägt — reine Namenserkennung genügt nicht.</td></tr>' +
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
    '<tr><td><strong>Setup Execution State</strong></td><td>Persistierter, projekt-/plan-/step-gebundener Status eines Mutations-Versuchs: not_started, in_progress, succeeded, failed, recovery_required</td></tr>' +
    '<tr><td><strong>recovery_required</strong></td><td>Status einer nach Unterbrechung vorgefundenen in_progress-Aufzeichnung — Ergebnis unsicher, keine automatische Wiederholung</td></tr>' +
    '<tr><td><strong>Requirement Activation</strong></td><td>Klassifiziert Anforderungen als blockierend, nicht-blockierend oder inaktiv</td></tr>' +
    '<tr><td><strong>Recovery</strong></td><td>Zustand nach Abbruch — keine automatische Wiederholung unsicherer Aktionen</td></tr>' +
    '<tr><td><strong>State Lock</strong></td><td>Prozess-lokaler Mutex — nur eine mutierende Operation pro Projektpfad</td></tr>' +
    '<tr><td><strong>WorkflowState</strong></td><td>Autoritativ für Entscheidungen — getrennt vom beobachtenden DiagnosticTrace</td></tr>' +
    '<tr><td><strong>ToolchainMaterializer</strong></td><td>Konvertiert CouncilResult in einen SetupPlan</td></tr>' +
    '<tr><td><strong>MissingToolchainSetup</strong></td><td>Brücke: TOOL_UNAVAILABLE → SetupPlan → Human Approval → Retry</td></tr></table>'
};
