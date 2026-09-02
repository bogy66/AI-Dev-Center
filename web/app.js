let currentSessionId = null;
let currentProject = null;
let recents = JSON.parse(localStorage.getItem('recents') || '[]');
// Ensure existing projects without the field behave as false.
recents.forEach(p => { if (p.create_github_repository === undefined) p.create_github_repository = false; });
let pollingTimer = null;
let approvalActionRendered = false;
let currentHelpSlide = 0;
let helpPitchDeckInitialized = false;
const totalHelpSlides = 10;

// ---------- API helpers ----------
async function fetchJson(url, options = {}) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `HTTP ${resp.status}`);
    }
    return resp.json();
}

function saveRecents() {
    localStorage.setItem('recents', JSON.stringify(recents));
}

function isLikelyProjectDirectory(path, projectName) {
    if (!path || !projectName) return false;
    const normalized = path.replace(/\/+$/, '');
    const parts = normalized.split('/');
    return parts[parts.length - 1] === projectName;
}

function resolveProjectDirectory(baseDir, projectName) {
    const cleanBase = baseDir.replace(/\/+$/, '');
    if (cleanBase.endsWith('/' + projectName)) {
        return cleanBase;
    }
    return `${cleanBase}/${projectName}`;
}

function getProjectDirectory(project) {
    if (!project) return 'No project selected';

    const name = project.project_name;

    // Prefer an existing explicit project_path/project_directory
    // only when it already appears to be the full project directory.
    if (project.project_path && isLikelyProjectDirectory(project.project_path, name)) {
        return project.project_path;
    }

    if (project.project_directory && isLikelyProjectDirectory(project.project_directory, name)) {
        return project.project_directory;
    }

    // If only a workspace/base directory is stored, combine it with the project name.
    // This handles the /home/udo/Testprojekt + _p1 -> /home/udo/Testprojekt/_p1 case.
    if (project.project_path) {
        return resolveProjectDirectory(project.project_path, name);
    }

    if (project.project_directory) {
        return resolveProjectDirectory(project.project_directory, name);
    }

    if (project.workspace) {
        return resolveProjectDirectory(project.workspace, name);
    }

    return 'No project selected';
}

function getProjectPath() {
    return getProjectDirectory(currentProject);
}

function renderRecents() {
    const list = document.getElementById('recents-list');
    list.innerHTML = '';
    recents.forEach((project, index) => {
        const li = document.createElement('li');
        li.textContent = project.project_name;
        li.classList.toggle('active', currentProject && currentProject.project_name === project.project_name);
        li.addEventListener('click', () => selectProject(index));
        list.appendChild(li);
    });
}

async function loadState() {
    if (!currentSessionId) return;

    try {
        const state = await fetchJson(`/api/state/${currentSessionId}`);
        updateFromState(state);
    } catch (error) {
        console.error("Failed to load state:", error);

        if (String(error.message).includes('"error":"unknown session"')) {
            currentSessionId = null;

            if (currentProject) {
                currentProject.session_id = null;
                saveRecents();
            }

            updateSessionDisplay(null);
            document.getElementById("global-status").textContent = "Ready";
            setLiveStatus("Ready");
            renderRecents();
            return;
        }

        setLiveStatus(`Error: ${error.message}`);
    }
}

function selectProject(index) {
    currentProject = recents[index];
    // Ensure backward compatibility for projects without the field.
    if (currentProject.create_github_repository === undefined) {
        currentProject.create_github_repository = false;
    }
    currentSessionId = currentProject.session_id || null;
    document.getElementById('project-name-display').textContent = currentProject.project_name;
    document.getElementById('project-path-display').textContent = getProjectPath();
    document.getElementById('global-status').textContent = currentSessionId ? 'Running' : 'Ready';
    updateSessionDisplay(currentSessionId);
    clearChat();
    if (currentSessionId) {
        loadState();
    }
    renderRecents();
}

function clearChat() {
    document.getElementById('chat-messages').innerHTML = '<div id="empty-chat-state" class="empty-chat">Start a conversation...</div>';
    document.getElementById('live-status').textContent = '';
    document.getElementById('approval-action-container').innerHTML = '';
    approvalActionRendered = false;
}

function addMessage(role, content) {
    const container = document.getElementById('chat-messages');
    const empty = document.getElementById('empty-chat-state');
    if (empty) empty.remove();

    const div = document.createElement('div');
    div.classList.add('chat-message', role === 'user' ? 'user-message' : 'assistant-message');
    div.textContent = content;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function setLiveStatus(text) {
    document.getElementById('live-status').textContent = text;
}

function updateSessionDisplay(sessionId) {
    const code = document.getElementById('session-id-display');
    const copyBtn = document.getElementById('copy-session-btn');

    if (sessionId) {
        code.textContent = sessionId;
        copyBtn.disabled = false;
    } else {
        code.textContent = '—';
        copyBtn.disabled = true;
    }
}

function updatePathDisplay() {
    document.getElementById('project-path-display').textContent = getProjectPath();
}

function appendTrace(traceEvents) {
    const container = document.getElementById('trace-list-container');
    const filter = document.getElementById('trace-filter').value;
    const selectedLevel = document.getElementById('trace-level-select').value;

    const levelRank = {
        'DEBUG': 0,
        'INFO': 1,
        'WARNING': 2,
        'ERROR': 3,
    };

    const detailThreshold = {
        'INFO': 1,
        'DEBUG': 0,
        'VERBOSE': -1,
        'VERY_VERBOSE': -2,
    };

    const threshold = detailThreshold[selectedLevel] !== undefined ? detailThreshold[selectedLevel] : 1;

    const filtered = traceEvents.filter(e => {
        const componentOk = filter === 'all' || e.component === filter;
        if (!componentOk) return false;
        const eventRank = levelRank[e.level] !== undefined ? levelRank[e.level] : 99;
        return eventRank >= threshold;
    });

    container.innerHTML = filtered.map(e => {
        const meta = e.metadata || {};
        const rolePart = meta.role ? ` role=${meta.role}` : '';
        const toolPart = meta.tool_name ? ` tool=${meta.tool_name}` : '';
        return `[${e.timestamp}] ${e.level} ${e.component}${rolePart}${toolPart} ${e.event} ${e.action} ${e.status}`;
    }).join('\n');
}

function startPolling(sessionId) {
    if (pollingTimer) clearInterval(pollingTimer);
    pollingTimer = setInterval(async () => {
        try {
            const state = await fetchJson(`/api/state/${sessionId}`);
            updateFromState(state);
        } catch (err) {
            console.error('Polling error', err);
        }
    }, 1500);
}

function stopPolling() {
    if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
    }
}

function updateFromState(state) {
    const info = state.transparency || {};
    const action = info.current_mcp_tool || info.current_action || '';
    const backendRole = info.current_role;

    let statusText;
    if (state.approval_required) {
        statusText = 'Waiting for approval...';
        if (!approvalActionRendered) {
            renderApprovalAction();
            approvalActionRendered = true;
        }
    } else if (state.workflow_status === 'completed') {
        statusText = 'Completed';
        stopPolling();
        removeApprovalAction();
    } else if (state.blocked) {
        statusText = 'Blocked';
        stopPolling();
        removeApprovalAction();
    } else {
        if (backendRole && action) {
            statusText = `${backendRole} · ${action}`;
        } else if (action) {
            statusText = action;
        } else if (backendRole) {
            statusText = `${backendRole} · Thinking…`;
        } else {
            statusText = currentSessionId ? 'Working…' : 'Thinking…';
        }
        removeApprovalAction();
    }

    setLiveStatus(statusText);
    appendTrace(state.trace || []);
    if (state.error_message) {
        setLiveStatus(`Error: ${state.error_message}`);
    }
}

function renderApprovalAction() {
    const container = document.getElementById('approval-action-container');
    container.innerHTML = '';

    const wrapper = document.createElement('div');
    wrapper.className = 'approval-message';
    wrapper.textContent = 'Setup plan is ready and requires your approval.';

    const btnContainer = document.createElement('div');
    btnContainer.className = 'approval-buttons';

    const approveBtn = document.createElement('button');
    approveBtn.className = 'approve-btn';
    approveBtn.textContent = 'Approve';
    approveBtn.addEventListener('click', () => handleApproval('approval'));

    const rejectBtn = document.createElement('button');
    rejectBtn.className = 'reject-btn';
    rejectBtn.textContent = 'Reject';
    rejectBtn.addEventListener('click', () => handleApproval('reject'));

    btnContainer.appendChild(approveBtn);
    btnContainer.appendChild(rejectBtn);
    wrapper.appendChild(btnContainer);
    container.appendChild(wrapper);

    container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function removeApprovalAction() {
    const container = document.getElementById('approval-action-container');
    if (container.innerHTML) {
        container.innerHTML = '';
    }
    approvalActionRendered = false;
}

async function handleApproval(action) {
    if (!currentSessionId) return;

    const endpoint = action === 'approval' ? 'approval' : 'reject';
    setLiveStatus(`Processing ${action}...`);
    try {
        await fetchJson(`/api/workflow/${currentSessionId}/${endpoint}`, {
            method: 'POST',
        });
        setLiveStatus(action === 'approval' ? 'Approval granted. Execute setup when ready.' : 'Approval rejected.');
        addMessage('assistant', action === 'approval' ? 'Approval granted. Execute setup when ready.' : 'Approval rejected.');
        if (action === 'approval') {
            renderExecutionAction();
        } else {
            removeApprovalAction();
        }
        startPolling(currentSessionId);
    } catch (err) {
        console.error(err);
        setLiveStatus(`Approval error: ${err.message}`);
    }
}

function renderExecutionAction() {
    const container = document.getElementById('approval-action-container');
    container.innerHTML = '';
    const executeBtn = document.createElement('button');
    executeBtn.className = 'approve-btn';
    executeBtn.textContent = 'Execute approved setup';
    executeBtn.addEventListener('click', handleExecution);
    container.appendChild(executeBtn);
}

async function handleExecution() {
    if (!currentSessionId) return;
    setLiveStatus('Executing approved setup...');
    try {
        await fetchJson(`/api/workflow/${currentSessionId}/execute`, { method: 'POST' });
        setLiveStatus('Setup execution completed.');
        addMessage('assistant', 'Setup execution completed.');
        removeApprovalAction();
        startPolling(currentSessionId);
    } catch (err) {
        console.error(err);
        setLiveStatus(`Execution error: ${err.message}`);
    }
}

// ---------- Help view ----------
function hideAllMainViews() {
    document.getElementById('project-header').classList.add('hidden');
    document.getElementById('chat-panel').classList.add('hidden');
    document.getElementById('trace-drag-handle').classList.add('hidden');
    document.getElementById('trace-panel').classList.add('hidden');
    document.getElementById('help-view').classList.add('hidden');
    document.getElementById('setup-view').classList.add('hidden');
}

function showNormalMainView() {
    document.getElementById('project-header').classList.remove('hidden');
    document.getElementById('chat-panel').classList.remove('hidden');
    document.getElementById('trace-drag-handle').classList.remove('hidden');
    document.getElementById('trace-panel').classList.remove('hidden');
    document.getElementById('help-view').classList.add('hidden');
    document.getElementById('setup-view').classList.add('hidden');
}

function showHelp() {
    hideAllMainViews();
    currentHelpSlide = 0;
    helpPitchDeckInitialized = false;
    showHelpOverview();
    document.getElementById('help-view').classList.remove('hidden');
}

function hideHelp() {
    document.getElementById('help-view').classList.add('hidden');
    showNormalMainView();
    helpPitchDeckInitialized = false;
}

function showHelpOverview() {
    document.getElementById('help-overview-content').classList.remove('hidden');
    document.getElementById('help-pitch-content').classList.add('hidden');
    document.getElementById('help-overview-btn').classList.add('active');
    document.getElementById('help-pitch-btn').classList.remove('active');
}

function showHelpPitch() {
    document.getElementById('help-overview-content').classList.add('hidden');
    document.getElementById('help-pitch-content').classList.remove('hidden');
    document.getElementById('help-overview-btn').classList.remove('active');
    document.getElementById('help-pitch-btn').classList.add('active');

    if (!helpPitchDeckInitialized) {
        currentHelpSlide = 0;
        helpPitchDeckInitialized = true;
    }

    renderHelpDeck();
}

function updateHelpPagination() {
    const indicator = document.getElementById('help-page-indicator');
    if (indicator) {
        indicator.textContent = `${currentHelpSlide + 1} / ${totalHelpSlides}`;
    }
    const prevBtn = document.getElementById('help-prev-btn');
    const nextBtn = document.getElementById('help-next-btn');
    if (prevBtn) prevBtn.disabled = currentHelpSlide === 0;
    if (nextBtn) nextBtn.disabled = currentHelpSlide === totalHelpSlides - 1;
}

function nextHelpSlide() {
    if (currentHelpSlide < totalHelpSlides - 1) {
        currentHelpSlide++;
        renderHelpDeck();
    }
}

function prevHelpSlide() {
    if (currentHelpSlide > 0) {
        currentHelpSlide--;
        renderHelpDeck();
    }
}

function getProjectDisplayName() {
    return currentProject ? currentProject.project_name : 'No project selected';
}

function renderHelpDeck() {
    const deck = document.getElementById('help-deck');
    if (!deck) return;

    const slide = helpSlides[currentHelpSlide];
    const slideHtml = slide.html();

    deck.innerHTML = `
      <div class="pitch-slide">
        <div class="pitch-slide-title">${slide.title}</div>
        <div class="pitch-slide-body">${slideHtml}</div>
      </div>
    `;
    updateHelpPagination();
}

// ---------- Setup view ----------
function showSetup() {
    hideAllMainViews();
    populateSetupForm();
    document.getElementById('setup-view').classList.remove('hidden');
}

function hideSetup() {
    document.getElementById('setup-view').classList.add('hidden');
    showNormalMainView();
}

// ---------- Trace drag handle ----------
function initTraceDrag() {
    const handle = document.getElementById('trace-drag-handle');
    const panel = document.getElementById('trace-panel');
    const savedHeight = localStorage.getItem('trace-height');
    if (savedHeight) {
        panel.style.height = savedHeight + 'px';
    } else {
        panel.style.height = '180px';
    }

    let isDragging = false;
    let startY = 0;
    let startHeight = 0;

    handle.addEventListener('mousedown', (e) => {
        isDragging = true;
        startY = e.clientY;
        startHeight = panel.offsetHeight;
        document.body.style.cursor = 'row-resize';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const delta = startY - e.clientY;
        const newHeight = Math.min(Math.max(startHeight + delta, 100), 600);
        panel.style.height = newHeight + 'px';
    });

    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            document.body.style.cursor = '';
            localStorage.setItem('trace-height', panel.style.height.replace('px', ''));
        }
    });
}

// ---------- Modal ----------
function openModal() {
    document.getElementById('new-project-modal').classList.remove('hidden');
    document.getElementById('project-dir-input').value = '';
    document.getElementById('project-name-input').value = '';
    document.getElementById('new-project-trace-level').value = 'INFO';
    document.getElementById('create-github-repo-checkbox').checked = false;
}

function closeModal() {
    document.getElementById('new-project-modal').classList.add('hidden');
}

function handleCreateProject() {
    const name = document.getElementById('project-name-input').value.trim();
    const dir = document.getElementById('project-dir-input').value.trim();
    const traceLevel = document.getElementById('new-project-trace-level').value;
    const createGithubRepo = document.getElementById('create-github-repo-checkbox').checked;
    if (!name || !dir) {
        alert('Project name and directory are required');
        return;
    }

    // Resolve to the actual project directory.  If the user entered
    // the workspace/base directory, combine it with the project name.
    const projectDirectory = resolveProjectDirectory(dir, name);

    const project = {
        project_name: name,
        project_directory: projectDirectory,
        project_path: projectDirectory,
        trace_level: traceLevel,
        create_github_repository: createGithubRepo,
        session_id: null,
    };
    recents.push(project);
    saveRecents();
    currentProject = project;
    currentSessionId = null;
    closeModal();
    renderRecents();
    document.getElementById('project-name-display').textContent = name;
    document.getElementById('project-path-display').textContent = projectDirectory;
    document.getElementById('global-status').textContent = 'Ready';
    updateSessionDisplay(null);
    clearChat();
}

// ---------- Chat ----------
async function handleSend() {
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;

    addMessage('user', text);
    input.value = '';

    if (!currentProject) {
        alert('Select or create a project first');
        return;
    }

    if (!currentSessionId) {
        setLiveStatus('Starting workflow...');
        try {
            const resp = await fetchJson('/api/workflow/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    project_name: currentProject.project_name,
                    project_directory: getProjectDirectory(currentProject),
                    task_description: text,
                    trace_level: currentProject.trace_level || 'INFO',
                }),
            });
            currentSessionId = resp.session_id;
            currentProject.session_id = currentSessionId;
            saveRecents();
            document.getElementById('global-status').textContent = 'Running';
            updateSessionDisplay(currentSessionId);
            startPolling(currentSessionId);
        } catch (err) {
            console.error(err);
            setLiveStatus(`Error: ${err.message}`);
        }
    } else {
        setLiveStatus('Message noted (backend does not support follow-ups yet)');
    }
}

// ---------- Open project directory ----------
async function handleOpenProjectPath() {
    const path = getProjectPath();

    if (!path || path === 'No project selected') {
        setLiveStatus('No project path available');
        return;
    }

    try {
        await fetchJson('/api/project/open', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ project_path: path }),
        });
        setLiveStatus('Project directory opened');
    } catch (err) {
        console.error(err);
        setLiveStatus(`Error opening project directory: ${err.message}`);
    }
}

// ---------- Setup form handling ----------
function populateSetupForm() {
    // Values reflect the current local configuration (config/ai-dev-center.yml)
    document.getElementById('setup-provider').value = 'openrouter';
    document.getElementById('setup-model').value = 'deepseek/deepseek-v4-pro';
    document.getElementById('setup-endpoint').value = 'https://openrouter.ai/api/v1';
    document.getElementById('setup-auth-type').value = 'secret_reference';
    document.getElementById('setup-secret-ref').value = 'openrouter-api';
    document.getElementById('setup-timeout').value = '30';
    document.getElementById('setup-discovery-enabled').checked = true;
    document.getElementById('setup-require-json').checked = true;
    document.getElementById('setup-max-requirements').value = '50';
}

function handleSetupSave(event) {
    event.preventDefault();
    const msg = document.getElementById('setup-message');
    msg.textContent = 'Saving configuration is not yet supported through the web interface.';
}

// ---------- Slide content ----------
const helpSlides = [
    {
        title: 'The Goal',
        html: () => `
            <p>AI Dev Center provides a controlled canonical development workflow reached through different communication adapters.</p>
            <p>It spans project analysis and requirements clarification, technical decisions, setup and implementation, testing, review, approval and safe version control while keeping the human in control.</p>
            <div class="flow-row">
                <span class="flow-step">Task</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Understanding</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Planning</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Implementation</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Verification</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Review</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Result</span>
            </div>
        `
    },
    {
        title: 'The Problem',
        html: () => `
            <p>A development task is rarely just a code-generation problem.</p>
            <p>It requires:</p>
            <ul>
                <li>understanding the existing project</li>
                <li>clarifying requirements</li>
                <li>deciding what should change</li>
                <li>implementing changes</li>
                <li>testing</li>
                <li>reviewing</li>
                <li>knowing what the AI actually did</li>
            </ul>
            <p>The goal of AI Dev Center is to make this complete development process explicit and observable.</p>
        `
    },
    {
        title: 'What is AI Dev Center?',
        html: () => `
            <p>AI Dev Center is not intended to be just one chatbot producing code.</p>
            <p>It is an orchestrated development workspace in which specialized AI roles contribute to one common canonical project workflow.</p>
            <p>Web, API, CLI and MCP are adapters to that workflow, not separate business pipelines. Legacy compatibility classes may remain without being productive alternatives.</p>
            <p>For an existing project, its architecture, conventions, frameworks, build systems, tests and toolchains remain authoritative; AI Dev Center does not force it into a preferred architecture.</p>
            <p>The user interacts primarily through Chat.</p>
            <p>The system handles:</p>
            <ul>
                <li>project understanding</li>
                <li>workflow orchestration</li>
                <li>tool use</li>
                <li>implementation</li>
                <li>testing</li>
                <li>review</li>
                <li>traceability</li>
            </ul>
            <p>The Development Stage has a controlled boundary: the Developer produces structured changes, while the File Applier alone writes validated files inside the project root. It does not use arbitrary shell commands; testing, review and Git remain later stages.</p>
            <p>The canonical Development-Testing flow connects structured development changes, structured test changes, controlled application, real test execution and diagnosis in that order. The TestChangeGenerator produces test changes without writing files, while the Git-free ProjectTestRunner runs only an allowed test action. It never accepts arbitrary LLM-generated shell commands; the Git-based legacy TestBench is not this canonical core path.</p>
            <p>For each controlled run, AI Dev Center records which declared files were changed, their original and resulting hashes, and whether they were already modified or staged in Git. This provenance protects existing user changes. Preexisting or mixed provenance, foreign staged content, and a final hash mismatch block automatic whole-file staging.</p>
            <p>Setup approval, final approval and publish approval are separate safety boundaries. After an approved setup has executed successfully, the canonical flow can continue through development, structured test changes, controlled application, real tests and diagnosis. A structured rework request may trigger exactly one controlled rework cycle; another rework-required result ends the run. A final accepted result waits for explicit human final approval. Its approved result means ready for Git; a further explicit Controlled Git Stage may then create a controlled local commit containing only validated run paths.</p>
            <p>A successful local commit only creates ready for publish and a separate pending Publish Approval. After explicit publish approval, the Controlled Publish Stage pushes the exact persisted run commit to an existing configured Git remote using an explicit branch ref. Missing remotes, detached HEAD, unrelated later commits, authentication failures and non-fast-forward pushes stop fail-safe. It never force-pushes or repairs history through merge or rebase. Publish means Git remote push here—not release, pull request, deployment, hardware flash, OTA, package publish or general CI/CD automation.</p>
            <p>The Central Diagnostic Trace provides a persistent run-specific timeline across workflow phases, approvals, controlled Git and controlled publish. Stable sequences and UTC timestamps make pending, failed, rework, approved, committed and published outcomes explainable after a restart. It stores only allowlisted, redacted diagnostic metadata and cannot replace Workflow State or grant an approval. It is not presented as enterprise SIEM, event sourcing, a cryptographic audit chain or distributed tracing.</p>
            <p>Project-level execution ownership prevents concurrent canonical mutations of the same workspace. A persistent execution lifecycle makes interrupted work visible and stops unsafe automatic repetition after a crash. Recovery remains deliberately bounded: it is not distributed consensus, an exactly-once LLM guarantee or a transactional rollback system.</p>
            <p>Existing projects are first inspected read-only: languages, frameworks, package managers, build systems, test systems, firmware indicators, CI hints and project areas are detected deterministically from repository evidence without executing project code, builds or dependency installations. Sensitive files never reach downstream LLM providers. Existing architectures, conventions and toolchains are respected as project facts.</p>
            <p>From Project Intelligence, a typed VerificationPlan assigns each project area its own controlled runner and working directory. Pytest and Python unittest execute directly; vitest, jest, cmake, make, platformio and esphome stay deferred or unsupported. No runner accepts shell strings, package.json scripts or arbitrary LLM commands. Unsupported detection means the system reports truthfully instead of passing silently.</p>
            <p>Multi-toolchain automation, ESPHome compilation, flashing, OTA and other physical hardware actions are outside the current productive scope.</p>
            <p>Human control remains central.</p>
        `
    },
    {
        title: 'From Task to Result',
        html: () => `
            <div class="vertical-flow">
                <span class="flow-step">User</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Project Manager</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Architect</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Developer</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Tester</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Reviewer</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Result</span>
            </div>
            <p>Setup Approval is required before setup execution. Final Approval and Publish Approval remain separate later decisions.</p>
            <p><strong>Chat</strong> = user interaction<br><strong>Trace</strong> = technical observability</p>
        `
    },
    {
        title: 'The AI Team',
        html: () => `
            <div class="role-grid">
                <div class="role-entry"><strong>Project Manager</strong> Coordinates the overall task and workflow.</div>
                <div class="role-entry"><strong>Architect</strong> Analyzes project structure and requirements and determines the architectural approach.</div>
                <div class="role-entry"><strong>Developer</strong> Implements the planned changes.</div>
                <div class="role-entry"><strong>Tester</strong> Tests and verifies the implementation.</div>
                <div class="role-entry"><strong>Reviewer</strong> Reviews the result for defects, regressions and quality.</div>
            </div>
            <p><strong>Important:</strong> The user does not manually switch between these roles. The system orchestrates them.</p>
        `
    },
    {
        title: 'Technical Architecture',
        html: () => `
            <div class="arch-layer">Web / API / CLI / MCP adapters</div>
            <div class="flow-arrow">↓</div>
            <div class="arch-layer">Canonical Application Service</div>
            <div class="flow-arrow">↓</div>
            <div class="arch-layer">Inspection / Requirements / Council / SetupPlan</div>
            <div class="flow-arrow">↓</div>
            <div class="arch-layer">Approvals / Development / Testing / Review</div>
            <div class="flow-arrow">↓</div>
            <div class="arch-layer">Controlled Git / Controlled Publish</div>
            <div class="flow-arrow">↓</div>
            <div class="arch-layer">State + Trace</div>
            <p>Setup Approval, Final Approval and Publish Approval are separate boundaries. State owns decisions; Trace observes them.</p>
        `
    },
    {
        title: 'From Conversation to Real Project Work',
        html: () => `
            <p>The AI does not have to solve everything from text alone.</p>
            <p>The workflow can call MCP tools.</p>
            <div class="flow-row">
                <span class="flow-step">Agent</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Tool request</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">MCP</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Project operation</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Tool result</span>
                <span class="flow-arrow">→</span>
                <span class="flow-step">Agent continues</span>
            </div>
            <p>This matters because the agent can inspect and operate on the actual project instead of only discussing what might be done.</p>
        `
    },
    {
        title: 'Transparency by Design',
        html: () => `
            <div class="two-column">
                <div>
                    <h3>Chat</h3>
                    <p>Thinking…<br>Project Manager · Coordinating…<br>Architect · Analyzing requirements…<br>Developer · Inspecting project…<br>Tester · Running verification…<br>Reviewer · Reviewing result…</p>
                </div>
                <div>
                    <h3>Trace</h3>
                    <p>INFO – important workflow events.<br>DEBUG – technical workflow, agent and MCP activity.<br>VERBOSE – more detailed diagnostic information.<br>VERY_VERBOSE – maximum diagnostic detail.</p>
                    <div class="trace-sample">timestamp | level | component | role | action/event | tool | status</div>
                </div>
            </div>
            <p>Never exposed: secrets, API keys, passwords, full prompts, chain-of-thought or sensitive raw arguments.</p>
        `
    },
    {
        title: 'Human in Control',
        html: () => `
            <div class="vertical-flow">
                <span class="flow-step">Create Project</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Describe task in Chat</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Analyze</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Plan</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Setup Approval</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Implement</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Test</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Review</span>
                <span class="flow-arrow">↓</span>
                <span class="flow-step">Final Approval → Controlled Git → Publish Approval</span>
            </div>
            <p>Corrections, questions and additional instructions happen through Chat.</p>
            <p>Use cases: understand an existing project, add a feature, fix a problem, refactor, create a project, add tests, review, debug the workflow.</p>
        `
    },
    {
        title: 'Project Complete / Press Release',
        html: () => `
            <h2>AI Dev Center Completes Development Project</h2>
            <p>AI Dev Center has completed a full project development lifecycle, transforming a user-defined task into a planned, implemented, tested and reviewed result.</p>
            <p>The process combined specialized AI roles, project-aware tool execution, workflow orchestration and transparent diagnostics while keeping the human in control.</p>
            <div class="completion-summary">
                <div class="summary-row"><span class="summary-label">Project</span><span class="summary-value">${getProjectDisplayName()}</span></div>
                <div class="summary-row"><span class="summary-label">Objective</span><span class="summary-value">Available when a project is complete.</span></div>
                <div class="summary-row"><span class="summary-label">Implementation</span><span class="summary-value">Available when a project is complete.</span></div>
                <div class="summary-row"><span class="summary-label">Testing</span><span class="summary-value">Available when a project is complete.</span></div>
                <div class="summary-row"><span class="summary-label">Review</span><span class="summary-value">Available when a project is complete.</span></div>
                <div class="summary-row"><span class="summary-label">Final Status</span><span class="summary-value">Available when a project is complete.</span></div>
            </div>
            <p>The closing message communicates the intention of AI Dev Center, not that an unfinished project succeeded.</p>
        `
    }
];

// ---------- Event binding ----------
document.getElementById('new-project-btn').addEventListener('click', openModal);
document.getElementById('cancel-project-btn').addEventListener('click', closeModal);
document.getElementById('create-project-btn').addEventListener('click', handleCreateProject);
document.getElementById('choose-directory-btn').addEventListener('click', () => {
    document.getElementById('project-directory-picker').click();
});
document.getElementById('project-directory-picker').addEventListener('change', () => {
    // no-op: do not populate from file selection
});

document.getElementById('send-btn').addEventListener('click', handleSend);
document.getElementById('chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
    }
});
document.getElementById('copy-session-btn').addEventListener('click', () => {
    const sid = document.getElementById('session-id-display').textContent;
    if (sid && sid !== '—') {
        navigator.clipboard.writeText(sid).catch(() => {
            const ta = document.createElement('textarea');
            ta.value = sid;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        });
    }
});
document.getElementById('open-path-btn').addEventListener('click', handleOpenProjectPath);
document.getElementById('trace-filter').addEventListener('change', () => {});
document.getElementById('trace-level-select').addEventListener('change', () => {});
document.getElementById('clear-trace-btn').addEventListener('click', () => {
    document.getElementById('trace-list-container').innerHTML = '';
});
document.getElementById('copy-all-btn').addEventListener('click', () => {
    const text = document.getElementById('trace-list-container').innerText;
    navigator.clipboard.writeText(text || '(empty)').catch(() => {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
    });
});
document.getElementById('export-trace-btn').addEventListener('click', async () => {
    if (!currentSessionId) {
        alert('No active trace to export');
        return;
    }
    const resp = await fetch(`/api/workflow/${currentSessionId}/export`);
    if (resp.ok) {
        const data = await resp.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `trace-${currentSessionId}.json`;
        a.click();
        URL.revokeObjectURL(url);
    } else {
        alert('Export failed');
    }
});

document.getElementById('help-btn').addEventListener('click', showHelp);
document.getElementById('help-back-btn').addEventListener('click', hideHelp);
document.getElementById('help-overview-btn').addEventListener('click', showHelpOverview);
document.getElementById('help-pitch-btn').addEventListener('click', showHelpPitch);
document.getElementById('help-prev-btn').addEventListener('click', prevHelpSlide);
document.getElementById('help-next-btn').addEventListener('click', nextHelpSlide);
document.getElementById('setup-btn').addEventListener('click', showSetup);
document.getElementById('setup-back-btn').addEventListener('click', hideSetup);
document.getElementById('help-to-setup-btn')?.addEventListener('click', () => {
    showSetup();
});
document.getElementById('setup-config-form').addEventListener('submit', handleSetupSave);

// Keyboard navigation for pitch deck (only when Pitch Deck is visible)
document.addEventListener('keydown', (e) => {
    const helpView = document.getElementById('help-view');
    if (helpView.classList.contains('hidden')) return;

    const pitchContent = document.getElementById('help-pitch-content');
    if (pitchContent.classList.contains('hidden')) return;

    if (e.key === 'ArrowLeft') {
        e.preventDefault();
        prevHelpSlide();
    } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        nextHelpSlide();
    }
});

// Initial render
initTraceDrag();
renderRecents();
if (recents.length > 0) {
    selectProject(0);
}
