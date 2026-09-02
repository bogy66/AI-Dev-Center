let currentSessionId = null;
let currentProject = null;
let recents;
try {
    const storedRecents = JSON.parse(localStorage.getItem('recents') || '[]');
    recents = Array.isArray(storedRecents) ? storedRecents : [];
} catch (_) {
    recents = [];
}
recents.forEach(p => { p.path_status = 'checking'; });
let pollingTimer = null;
let approvalActionRendered = false;
let currentHelpSlide = 0;
let helpPitchDeckInitialized = false;
const totalHelpSlides = 15;

// ---------- API helpers ----------
async function fetchJson(url, options = {}) {
    const resp = await fetch(url, options);
    let payload = null;
    try {
        payload = await resp.json();
    } catch (_) {
        payload = null;
    }
    if (!resp.ok) {
        const error = new Error(payload?.error || `HTTP ${resp.status}`);
        error.status = resp.status;
        error.payload = payload;
        throw error;
    }
    return payload;
}

function saveRecents() {
    localStorage.setItem('recents', JSON.stringify(recents));
}

function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[character]);
}

function getProjectDirectory(project) {
    if (!project) return 'No project selected';
    if (project.project_path) return project.project_path;
    if (project.project_directory) return project.project_directory;
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
        const suffix = project.path_status === 'invalid' ? ' — invalid path' : '';
        li.textContent = `${project.project_name}${suffix}`;
        li.classList.toggle('invalid', project.path_status === 'invalid');
        li.classList.toggle('active', currentProject && currentProject.project_name === project.project_name);
        li.addEventListener('click', () => selectProject(index));
        list.appendChild(li);
    });
}

async function validateProjectPath(path) {
    return fetchJson('/api/project/validate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project_path: path}),
    });
}

async function validateRecentProjects() {
    await Promise.all(recents.map(async project => {
        const path = getProjectDirectory(project);
        try {
            const result = await validateProjectPath(path);
            project.project_path = result.project_path;
            project.project_directory = result.project_path;
            project.path_status = 'valid';
        } catch (_) {
            project.path_status = 'invalid';
            project.session_id = null;
        }
    }));
    saveRecents();
    renderRecents();
    if (currentProject) {
        document.getElementById('project-path-display').textContent = getProjectPath();
        if (currentProject.path_status === 'invalid') {
            document.getElementById('global-status').textContent = 'Invalid project path';
            setLiveStatus('This recent project path is stale or invalid.');
        }
    }
}

async function loadState() {
    if (!currentSessionId) return;

    try {
        const state = await fetchJson(`/api/state/${currentSessionId}`);
        updateFromState(state);
    } catch (error) {
        console.error("Failed to load state:", error);

        if (error.status === 404 && error.payload?.error === 'unknown session') {
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
    currentSessionId = currentProject.session_id || null;
    document.getElementById('project-name-display').textContent = currentProject.project_name;
    document.getElementById('project-path-display').textContent = getProjectPath();
    document.getElementById('global-status').textContent = currentProject.path_status === 'invalid'
        ? 'Invalid project path'
        : (currentSessionId ? 'Running' : 'Ready');
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

function formatTraceTime(timestamp) {
    const parsed = new Date(timestamp);
    if (Number.isNaN(parsed.getTime())) return String(timestamp || '');
    return parsed.toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    });
}

function formatActivity(activity) {
    if (!activity) return '';
    const stage = String(activity.stage || '')
        .split('_').filter(Boolean)
        .map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ');
    const actor = String(activity.actor || '');
    const state = String(activity.runtime_state || '')
        .replaceAll('_', ' ')
        .replace(/^./, character => character.toUpperCase());
    const subject = [stage, actor].filter(Boolean).join(' · ');
    return subject && state ? `${subject} — ${state}…` : (subject || state);
}

function formatTraceLine(event) {
    const meta = event.metadata || {};
    const actor = String(meta.actor || meta.role || '').trim();
    const runtimeState = String(meta.runtime_state || '').trim();
    const timestamp = formatTraceTime(event.timestamp);

    if (runtimeState) {
        const activityActor = actor || String(event.component || 'Workflow');
        return `[${timestamp}] ${activityActor} — ${runtimeState}`;
    }

    const rolePart = actor ? ` actor=${actor}` : '';
    const toolPart = meta.tool_name ? ` tool=${meta.tool_name}` : '';
    return `[${timestamp}] ${event.level} ${event.component}${rolePart}${toolPart} ${event.event} ${event.action} ${event.status}`;
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

    container.textContent = filtered.map(formatTraceLine).join('\n');
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
    const centralActivity = formatActivity(state.current_activity);

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
        if (centralActivity) {
            statusText = centralActivity;
        } else if (backendRole && action) {
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
    const liveTrace = [...(state.trace || []), ...(state.central_trace || [])]
        .sort((left, right) => String(left.timestamp).localeCompare(String(right.timestamp)));
    appendTrace(liveTrace);
    if (state.error_message) {
        setLiveStatus(
            state.workflow_status === 'blocked'
                ? `Blocked: ${state.error_message}`
                : `Error: ${state.error_message}`
        );
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
}

function closeModal() {
    document.getElementById('new-project-modal').classList.add('hidden');
}

async function handleCreateProject() {
    const name = document.getElementById('project-name-input').value.trim();
    const dir = document.getElementById('project-dir-input').value.trim();
    const traceLevel = document.getElementById('new-project-trace-level').value;
    if (!name || !dir) {
        alert('Project name and directory are required');
        return;
    }

    let projectDirectory;
    try {
        const validation = await validateProjectPath(dir);
        projectDirectory = validation.project_path;
    } catch (error) {
        setLiveStatus(`Invalid existing project: ${error.message}`);
        return;
    }

    const project = {
        project_name: name,
        project_directory: projectDirectory,
        project_path: projectDirectory,
        trace_level: traceLevel,
        path_status: 'valid',
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
        if (currentProject.path_status === 'invalid') {
            setLiveStatus('This recent project path is invalid. Select an existing project root.');
            return;
        }
        setLiveStatus('Starting workflow...');
        try {
            const validation = await validateProjectPath(getProjectDirectory(currentProject));
            currentProject.project_path = validation.project_path;
            currentProject.project_directory = validation.project_path;
            currentProject.path_status = 'valid';
            saveRecents();
        } catch (error) {
            currentProject.path_status = 'invalid';
            currentProject.session_id = null;
            saveRecents();
            renderRecents();
            document.getElementById('global-status').textContent = 'Invalid project path';
            setLiveStatus(`Invalid existing project: ${error.message}`);
            return;
        }
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
            if (err.payload?.session_id) {
                currentSessionId = err.payload.session_id;
                currentProject.session_id = currentSessionId;
                saveRecents();
                updateSessionDisplay(currentSessionId);
                document.getElementById('global-status').textContent = 'Failed';
                await loadState();
            }
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
async function populateSetupForm() {
    const msg = document.getElementById('setup-message');
    msg.textContent = 'Loading productive configuration…';
    try {
        const config = await fetchJson('/api/config');
        const ai = config.ai;
        document.getElementById('setup-provider').value = ai.provider;
        document.getElementById('setup-provider').disabled = true;
        document.getElementById('setup-model').value = ai.model;
        document.getElementById('setup-endpoint').value = ai.endpoint;
        document.getElementById('setup-auth-type').value = ai.authentication.type;
        document.getElementById('setup-auth-type').disabled = true;
        document.getElementById('setup-secret-ref').value = ai.authentication.secret_reference;
        document.getElementById('setup-timeout').value = ai.timeout_seconds;
        document.getElementById('setup-discovery-enabled').checked = ai.discovery.enabled;
        document.getElementById('setup-require-json').checked = ai.discovery.require_json;
        document.getElementById('setup-max-requirements').value = ai.discovery.max_requirements;
        const roles = ai.council?.roles || {};
        document.getElementById('setup-council-roles').innerHTML = Object.values(roles)
            .map(role => `<div class="form-field"><strong>${escapeHtml(role.role.replaceAll('_', ' '))}</strong><code>${escapeHtml(role.provider)} · ${escapeHtml(role.model)}</code><span class="field-note">timeout ${escapeHtml(role.timeout_seconds)}s · temperature ${escapeHtml(role.temperature)}</span></div>`)
            .join('');
        msg.textContent = 'Loaded from the productive config.yml. Council roles are read-only.';
    } catch (error) {
        msg.textContent = `Configuration error: ${error.message}`;
    }
}

async function handleSetupSave(event) {
    event.preventDefault();
    const msg = document.getElementById('setup-message');
    msg.textContent = 'Validating configuration…';
    const update = {
        model: document.getElementById('setup-model').value.trim(),
        endpoint: document.getElementById('setup-endpoint').value.trim(),
        secret_reference: document.getElementById('setup-secret-ref').value.trim(),
        timeout_seconds: Number(document.getElementById('setup-timeout').value),
        discovery_enabled: document.getElementById('setup-discovery-enabled').checked,
        require_json: document.getElementById('setup-require-json').checked,
        max_requirements: Number(document.getElementById('setup-max-requirements').value),
    };
    try {
        await fetchJson('/api/config', {
            method: 'PATCH', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(update),
        });
        msg.textContent = 'Configuration saved. New sessions use the updated values.';
        await populateSetupForm();
    } catch (error) {
        msg.textContent = `Configuration was not saved: ${error.message}`;
    }
}

// ---------- Slide content ----------
const legacyHelpSlides = [
    {
        title: 'The Goal',
        html: () => `
            <p>AI Dev Center provides a controlled central development workflow reached through different communication adapters.</p>
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
            <p>It is an orchestrated development workspace in which specialized AI roles contribute to one common central project workflow.</p>
            <p>Web, API, CLI, MCP and Signal are adapters to that central workflow, not separate business pipelines. Signal chats and projects have a strict 1:1 persisted relationship: each chat belongs to exactly one project and each project has exactly one active Signal chat. Normal message text cannot change the binding; rebinding is explicit, and an unbound chat cannot start work. Binding stores no chat history as Project Definitions / Memory and grants no Human Approval authority. Legacy compatibility classes may remain without being productive alternatives.</p>
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
            <p>The central Development-Testing flow connects structured development changes, structured test changes, controlled application, real test execution and diagnosis in that order. The TestChangeGenerator produces test changes without writing files, while the Git-free ProjectTestRunner runs only an allowed test action. It never accepts arbitrary LLM-generated shell commands; the Git-based legacy TestBench is not this central core path.</p>
            <p>For each controlled run, AI Dev Center records which declared files were changed, their original and resulting hashes, and whether they were already modified or staged in Git. This provenance protects existing user changes. Preexisting or mixed provenance, foreign staged content, and a final hash mismatch block automatic whole-file staging.</p>
            <p>Setup approval, final approval and publish approval are separate safety boundaries. After an approved setup has executed successfully, the central flow can continue through development, structured test changes, controlled application, real tests and diagnosis. A structured rework request may trigger exactly one controlled rework cycle; another rework-required result ends the run. A final accepted result waits for explicit human final approval. Its approved result means ready for Git; a further explicit Controlled Git Stage may then create a controlled local commit containing only validated run paths.</p>
            <p>A successful local commit only creates ready for publish and a separate pending Publish Approval. After explicit publish approval, the Controlled Publish Stage pushes the exact persisted run commit to an existing configured Git remote using an explicit branch ref. Missing remotes, detached HEAD, unrelated later commits, authentication failures and non-fast-forward pushes stop fail-safe. It never force-pushes or repairs history through merge or rebase. Publish means Git remote push here—not release, pull request, deployment, hardware flash, OTA, package publish or general CI/CD automation.</p>
            <p>The Central Diagnostic Trace provides a persistent run-specific timeline across workflow phases, approvals, controlled Git and controlled publish. During long-running provider and Engineering Council work it exposes safe role activity such as preparing, thinking, waiting, reviewing, completed and failed; thinking is only an activity label and never reveals private reasoning or prompts. The Web view derives current activity from this structured trace and renders full stored ISO timestamps as compact browser-local HH:MM:SS. An incomplete Council decision blocks centrally before materialization. The trace stores only allowlisted, redacted diagnostic metadata and cannot replace Workflow State or grant an approval.</p>
            <p>Project-level execution ownership prevents concurrent central mutations of the same workspace. A persistent execution lifecycle makes interrupted work visible and stops unsafe automatic repetition after a crash. Recovery remains deliberately bounded: it is not distributed consensus, an exactly-once LLM guarantee or a transactional rollback system.</p>
            <p>Existing projects are first inspected read-only: languages, frameworks, package managers, build systems, test systems, firmware indicators, CI hints and project areas are detected deterministically from repository evidence without executing project code, builds or dependency installations. Sensitive files never reach downstream LLM providers. Existing architectures, conventions and toolchains are respected as project facts.</p>
            <p>Project Definitions / Memory stores explicit structured durable decisions, rules, terminology and intended state, never raw chat history. Project Intelligence remains observed reality, Project Definitions remain intentional policy, and config.yml remains the owner of its declarative technical fields. The central Project Context preserves all three typed sources and exposes bounded structured conflicts instead of silently overwriting them. Superseded and revoked definitions remain historical and definitions never grant approval or execution authority.</p>
            <p>From Project Intelligence, a typed VerificationPlan assigns each project area its own controlled runner and working directory. Firmware/embedded verification provides hardware-free ESPHome validate/compile, PlatformIO builds and native tests, and CMake configure/build with dependency ordering that blocks follow-up steps when predecessors fail. PlatformIO extra_scripts and similar build-code trust boundaries are detected and blocked. No runner performs flash, upload, OTA or device provisioning. Unsupported detection means the system reports truthfully instead of passing silently.</p>
            <p>A tool_unavailable result remains a structured setup need in the central workflow and never installs anything automatically. Only a command-free SetupPlan materialized from Project Intelligence and the Chairman Council result, followed by separate Setup Human Approval, may invoke a registered structured installer. Availability is checked before and after setup, and only the persisted original VerificationPlan may be retried through the existing Verification architecture. Installation success never grants capability authority.</p>
            <p>Docker is the intended runtime. The core container runs non‑root and without privileged mode, Docker‑socket access or device mounts. The central approval-aware capability registry binds capability and executable identity, allowed operation type, approval provenance, normalized project scope and active registration status. Future toolchain names can be registered without extending a fixed list; today's global registrations are compatibility defaults only. Dynamic registrations are always project-bound, while the same capability may be approved independently for multiple projects. Dynamic registrations follow Project Intelligence → Engineering Council → Chairman approval → Human Approval → controlled capability registration → controlled execution. Registration cannot authorize arbitrary shell commands, argv policies, images, mounts, devices, host access or automatic installation. Denied-argument checks, timeouts and output limits remain enforced, and missing tools remain tool_unavailable.</p>
            <p>The central application service opens a capability-specific Human Approval only for metadata present in the actual Project Intelligence and completed Chairman Council result. A matching persisted approval record is required before the existing registry accepts the registration. After restart, only complete approved registrations are restored through the same registry boundary; pending and rejected approvals are not restored. This approval remains separate from setup, Git, publish and physical-hardware approvals.</p>
            <p>Hardware flashing, OTA and physical device actions are outside the current productive scope and will require their own separate human approval boundary.</p>
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
            <div class="arch-layer">Central Application Service</div>
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
                <span class="flow-step">Open Existing Project</span>
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
            <p>The productive Web GUI opens an existing validated project root; creating a new directory is not implied by selection.</p>
            <p>Use cases: understand an existing project, add a feature, fix a problem, refactor, add tests, review and debug the workflow.</p>
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

const helpSlides = [
    {title: '1. What is AI Dev Center?', html: () => `<p>A project workspace where an AI team can understand, plan, develop, verify and review work through one central workflow—with the human in control.</p>`},
    {title: '2. Beyond isolated code generation', html: () => `<p>A useful change needs project understanding, technical decisions, tools, tests, review and delivery controls. A code snippet alone does not provide that continuity.</p>`},
    {title: '3. The idea', html: () => `<p>Bring project facts, durable decisions, specialist AI roles, controlled tools and observable workflow state together around one project.</p>`},
    {title: '4. How the user works', html: () => `<p>Choose a Project, describe the desired outcome, follow live progress, inspect results and decide each Human Approval request.</p>`},
    {title: '5. Existing projects', html: () => `<p>The current Web GUI opens an exact existing project root. AI Dev Center observes its languages, frameworks, tests, toolchains and conventions before proposing change.</p>`},
    {title: '6. New projects', html: () => `<p>Greenfield projects are part of the product direction. Safe Web creation is not implemented yet, so the current interface does not pretend that selecting a path creates one.</p>`},
    {title: '7. More than conventional software', html: () => `<p>The scope includes software, firmware, embedded and hardware-near development. Physical device actions remain behind a separate appropriate approval boundary and are not automatically available.</p>`},
    {title: '8. AI team and Engineering Council', html: () => `<p>Specialist roles examine the project and alternatives. The Engineering Council compares approaches, and a Chairman participates in the technical recommendation before controlled action is considered.</p>`},
    {title: '9. Human control', html: () => `<p>Setup, capability use, final development acceptance and publish each have separate approvals. An approval never becomes permission for arbitrary shell commands or another approval boundary.</p>`},
    {title: '10. Tools when needed', html: () => `<p>Missing toolchains are reported, not self-installed. Approved structured setup and capability registration can extend future technologies without turning a fixed list into the product architecture.</p>`},
    {title: '11. One project, multiple frontends', html: () => `<p>Web, Signal, API, CLI and MCP connect to the same central workflow. Signal is an adapter contract today; a concrete deployed provider remains future integration work. Active Signal chat and project bindings are strict 1:1.</p>`},
    {title: '12. Project Definitions / Memory', html: () => `<p>Observed project reality stays separate from explicit durable decisions and technical configuration. Conflicts are visible instead of silently merged, and raw chat history is not Project Memory.</p>`},
    {title: '13. Transparency while work happens', html: () => `<p>The central Diagnostic Trace drives the live stage and Council-role activity shown in Web, including safe preparing, thinking, waiting, reviewing and failure states. Trace rows use compact local HH:MM:SS times while full ISO timestamps remain in API and persistence. Prompts, private reasoning, secrets and sensitive configuration stay out of the browser.</p>`},
    {title: '14. From development to delivery', html: () => `<p>Controlled development leads to real verification and review, then separate final approval, controlled Git and Publish Approval. Verification never installs its own tools.</p>`},
    {title: '15. Why AI Dev Center?', html: () => `<p>It combines project continuity, extensible capabilities, human control and transparent progress. Docker is the intended production direction, while unfinished integrations remain clearly identified.</p>`},
];

// ---------- Event binding ----------
document.getElementById('new-project-btn').addEventListener('click', openModal);
document.getElementById('cancel-project-btn').addEventListener('click', closeModal);
document.getElementById('create-project-btn').addEventListener('click', handleCreateProject);
document.getElementById('choose-directory-btn').addEventListener('click', async () => {
    try {
        const result = await fetchJson('/api/project/select-directory', {method: 'POST'});
        document.getElementById('project-dir-input').value = result.project_path;
        const nameInput = document.getElementById('project-name-input');
        if (!nameInput.value.trim()) {
            nameInput.value = result.project_path.split('/').filter(Boolean).pop() || '';
        }
    } catch (error) {
        setLiveStatus(`Directory selection: ${error.message}`);
    }
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
validateRecentProjects();
if (recents.length > 0) {
    selectProject(0);
}
