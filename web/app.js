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
let activeProjects = [];
let archivedProjects = [];
let openProjectMenuId = null;
let projectPendingDelete = null;
let pollingTimer = null;
let approvalActionRendered = false;
let currentHelpSlide = 0;
let helpPitchDeckInitialized = false;
let currentTraceEvents = [];
let currentDocSection = null;
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

// ---------- Project lifecycle: Archiv / Projekte, `...` menu ----------
function findRecentByPath(path) {
    return recents.find(entry => getProjectDirectory(entry) === path) || null;
}

async function fetchAndRenderProjects() {
    try {
        const data = await fetchJson('/api/projects');
        activeProjects = Array.isArray(data.active) ? data.active : [];
        archivedProjects = Array.isArray(data.archived) ? data.archived : [];
    } catch (error) {
        console.error('Failed to load projects:', error);
        activeProjects = [];
        archivedProjects = [];
    }
    renderProjectLists();
    if (!currentProject && activeProjects.length > 0) {
        selectRegisteredProject(activeProjects[0]);
    }
}

function selectRegisteredProject(project) {
    const matchingRecent = findRecentByPath(project.project_root);
    currentProject = {
        project_id: project.project_id,
        project_name: project.display_name,
        project_directory: project.project_root,
        project_path: project.project_root,
        path_status: 'valid',
        session_id: matchingRecent ? matchingRecent.session_id : null,
        trace_level: matchingRecent ? matchingRecent.trace_level : 'INFO',
    };
    currentSessionId = currentProject.session_id;
    document.getElementById('project-name-display').textContent = currentProject.project_name;
    document.getElementById('project-path-display').textContent = getProjectPath();
    document.getElementById('global-status').textContent = currentSessionId ? 'Running' : 'Ready';
    updateSessionDisplay(currentSessionId);
    clearChat();
    if (currentSessionId) {
        loadState();
    }
    renderProjectLists();
}

function toggleProjectMenu(projectId) {
    openProjectMenuId = (openProjectMenuId === projectId) ? null : projectId;
    applyOpenProjectMenuState();
}

function closeAllProjectMenus() {
    openProjectMenuId = null;
    applyOpenProjectMenuState();
}

function applyOpenProjectMenuState() {
    document.querySelectorAll('.project-menu').forEach(menu => {
        menu.classList.toggle('hidden', menu.dataset.projectId !== openProjectMenuId);
    });
}

function buildProjectMenu(project, isArchived) {
    const menu = document.createElement('div');
    menu.className = 'project-menu hidden';
    menu.dataset.projectId = project.project_id;

    if (isArchived) {
        const restoreBtn = document.createElement('button');
        restoreBtn.type = 'button';
        restoreBtn.textContent = 'Wiederherstellen';
        restoreBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            closeAllProjectMenus();
            handleRestoreProject(project);
        });
        menu.appendChild(restoreBtn);
    }

    const renameBtn = document.createElement('button');
    renameBtn.type = 'button';
    renameBtn.textContent = 'Umbenennen';
    renameBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        closeAllProjectMenus();
        handleRenameProject(project);
    });
    menu.appendChild(renameBtn);

    if (isArchived) {
        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'danger';
        deleteBtn.textContent = 'Löschen';
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            closeAllProjectMenus();
            openDeleteProjectModal(project);
        });
        menu.appendChild(deleteBtn);
    } else {
        const archiveBtn = document.createElement('button');
        archiveBtn.type = 'button';
        archiveBtn.textContent = 'Archivieren';
        archiveBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            closeAllProjectMenus();
            handleArchiveProject(project);
        });
        menu.appendChild(archiveBtn);
    }

    return menu;
}

function renderProjectListInto(containerId, projects, isArchived, emptyText) {
    const list = document.getElementById(containerId);
    list.innerHTML = '';
    if (projects.length === 0) {
        const hint = document.createElement('li');
        hint.className = 'project-list-empty-hint';
        hint.textContent = emptyText;
        list.appendChild(hint);
        return;
    }
    projects.forEach(project => {
        const li = document.createElement('li');
        li.className = 'project-row';
        li.classList.toggle('active', !!currentProject && currentProject.project_id === project.project_id);

        const nameSpan = document.createElement('span');
        nameSpan.className = 'project-row-name';
        nameSpan.textContent = project.display_name;
        li.appendChild(nameSpan);

        const menuBtn = document.createElement('button');
        menuBtn.type = 'button';
        menuBtn.className = 'project-menu-btn';
        menuBtn.setAttribute('aria-label', 'Project actions');
        menuBtn.textContent = '⋯';
        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleProjectMenu(project.project_id);
        });
        li.appendChild(menuBtn);
        li.appendChild(buildProjectMenu(project, isArchived));

        li.addEventListener('click', () => {
            if (isArchived) {
                setLiveStatus('This project is archived. Restore it before starting development.');
                return;
            }
            selectRegisteredProject(project);
        });

        list.appendChild(li);
    });
}

function renderProjectLists() {
    renderProjectListInto('archive-list', archivedProjects, true, 'Keine archivierten Projekte');
    renderProjectListInto('recents-list', activeProjects, false, 'Keine Projekte');
    applyOpenProjectMenuState();
}

async function registerCurrentProjectPath(projectPath, displayName) {
    try {
        return await fetchJson('/api/projects/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({project_path: projectPath, display_name: displayName}),
        });
    } catch (error) {
        console.error('Failed to register project:', error);
        return null;
    }
}

async function handleRenameProject(project) {
    const newName = prompt(`Neuer Name für "${project.display_name}":`, project.display_name);
    if (newName === null) return;
    try {
        await fetchJson(`/api/projects/${encodeURIComponent(project.project_id)}/rename`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({new_name: newName}),
        });
        if (currentProject && currentProject.project_id === project.project_id) {
            currentProject.project_name = newName.trim();
            document.getElementById('project-name-display').textContent = currentProject.project_name;
        }
        await fetchAndRenderProjects();
    } catch (error) {
        alert(`Umbenennen fehlgeschlagen: ${error.message}`);
    }
}

async function handleArchiveProject(project) {
    try {
        await fetchJson(`/api/projects/${encodeURIComponent(project.project_id)}/archive`, {
            method: 'POST',
        });
        if (currentProject && currentProject.project_id === project.project_id) {
            currentProject = null;
            currentSessionId = null;
            document.getElementById('project-name-display').textContent = 'No project selected';
            document.getElementById('project-path-display').textContent = 'No project selected';
            document.getElementById('global-status').textContent = 'Ready';
            updateSessionDisplay(null);
            clearChat();
        }
        await fetchAndRenderProjects();
    } catch (error) {
        alert(`Archivieren fehlgeschlagen: ${error.message}`);
    }
}

async function handleRestoreProject(project) {
    try {
        await fetchJson(`/api/projects/${encodeURIComponent(project.project_id)}/restore`, {
            method: 'POST',
        });
        await fetchAndRenderProjects();
    } catch (error) {
        alert(`Wiederherstellen fehlgeschlagen: ${error.message}`);
    }
}

function openDeleteProjectModal(project) {
    projectPendingDelete = project;
    document.getElementById('delete-project-title').textContent =
        `Projekt "${project.display_name}" aus AI-Dev-Center löschen?`;
    document.getElementById('delete-project-modal').classList.remove('hidden');
}

function closeDeleteProjectModal() {
    projectPendingDelete = null;
    document.getElementById('delete-project-modal').classList.add('hidden');
}

async function confirmDeleteProject() {
    if (!projectPendingDelete) return;
    const project = projectPendingDelete;
    try {
        await fetchJson(`/api/projects/${encodeURIComponent(project.project_id)}/remove`, {
            method: 'POST',
        });
        closeDeleteProjectModal();
        await fetchAndRenderProjects();
    } catch (error) {
        closeDeleteProjectModal();
        alert(`Löschen fehlgeschlagen: ${error.message}`);
    }
}

document.addEventListener('click', () => {
    if (openProjectMenuId !== null) {
        closeAllProjectMenus();
    }
});

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
            renderProjectLists();
            return;
        }

        setLiveStatus(`Error: ${error.message}`);
    }
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

const diagnosticDetailRank = {
    NONE: -1, NORMAL: 0, INFO: 1, VERBOSE: 2, VERY_VERBOSE: 3,
};

function readableDiagnosticKey(key) {
    return String(key).replaceAll('_', ' ')
        .replace(/^./, character => character.toUpperCase());
}

function selectedInterfaceProjection(interfaceData, selectedLevel) {
    const key = selectedLevel === 'VERY_VERBOSE'
        ? 'very_verbose' : selectedLevel.toLowerCase();
    return interfaceData[key] || interfaceData.info || interfaceData.normal || {};
}

function appendInterfaceLines(lines, interfaceData, selectedLevel) {
    const projection = selectedInterfaceProjection(interfaceData, selectedLevel);
    if (diagnosticDetailRank[selectedLevel] <= diagnosticDetailRank.NORMAL) return;
    const appendEndpoint = (label, endpoint) => {
        const value = endpoint || {};
        lines.push(`${label}: ${value.type || 'unavailable'} / ${value.interface || 'unavailable'}`);
        if (diagnosticDetailRank[selectedLevel] >= diagnosticDetailRank.VERBOSE) {
            lines.push(`Source: ${value.source || 'unavailable'}`);
            lines.push(`Destination: ${value.destination || 'unavailable'}`);
            lines.push('Data:');
            lines.push(JSON.stringify(value.data ?? {available: false}, null, 2));
        }
    };
    lines.push('x — Input');
    appendEndpoint('Input', projection.x);
    lines.push('f — Processor');
    const processor = projection.f || {};
    lines.push(`Entity: ${processor.entity || 'unavailable'}`);
    if (processor.entity_version !== undefined) lines.push(`Version: ${processor.entity_version}`);
    if (processor.implementation_version) lines.push(`Implementation: ${processor.implementation_version}`);
    if (processor.provider) lines.push(`Provider: ${processor.provider}`);
    if (processor.model) lines.push(`Model: ${processor.model}`);
    if (processor.model_version) lines.push(`Model version: ${processor.model_version}`);
    lines.push('y — Output');
    appendEndpoint('Output', projection.y);
}

function formatInterfaceOutput(event, selectedLevel) {
    const meta = event.metadata || {};
    const projection = selectedInterfaceProjection(meta.interface_data || {}, selectedLevel);
    const identity = projection.f || (meta.interface_data || {}).info?.f || {};
    const version = identity.entity_version !== undefined ? ` v${identity.entity_version}` : '';
    const lines = [
        `[${formatTraceTime(event.timestamp)}] ${readableDiagnosticKey(meta.interface_stage || event.action)}${version}`,
        event.result_summary || projection.summary || 'Interface transformation recorded.',
    ];
    appendInterfaceLines(lines, meta.interface_data || {}, selectedLevel);
    return lines.join('\n');
}

function formatCouncilOutput(event, selectedLevel) {
    if (diagnosticDetailRank[selectedLevel] <= diagnosticDetailRank.NORMAL) return '';
    const meta = event.metadata || {};
    const projections = meta.council_output || {};
    const projectionKey = selectedLevel === 'VERY_VERBOSE'
        ? 'very_verbose' : selectedLevel.toLowerCase();
    const output = projections[projectionKey] || projections.info || {};
    const phaseNames = {
        phase1: 'Phase 1 — Proposals',
        phase2: 'Phase 2 — Reviews',
        phase3: 'Phase 3 — Chairman',
    };
    const identity = selectedInterfaceProjection(meta.interface_data || {}, selectedLevel).f
        || (meta.interface_data || {}).info?.f || {};
    const version = identity.entity_version !== undefined ? ` v${identity.entity_version}` : '';
    const lines = [
        `[${formatTraceTime(event.timestamp)}] ${phaseNames[meta.council_phase] || 'Engineering Council'}`,
        `${meta.actor || 'Council'}${version}${meta.actor_role ? ` · ${readableDiagnosticKey(meta.actor_role)}` : ''}`,
        event.result_summary || 'No usable structured result produced.',
    ];
    appendInterfaceLines(lines, meta.interface_data || {}, selectedLevel);
    if (diagnosticDetailRank[selectedLevel] >= diagnosticDetailRank.VERBOSE) {
        lines.push(`Provider: ${meta.provider || 'unavailable'}`);
        lines.push(`Model: ${meta.model || 'unavailable'}`);
        lines.push(`Phase: ${meta.council_phase || 'unavailable'}`);
        lines.push(`Duration: ${Number(meta.duration_ms || 0).toFixed(1)} ms`);
    }
    Object.entries(output).forEach(([key, value]) => {
        if (key === 'summary') return;
        const rendered = typeof value === 'string' || typeof value === 'number'
            || typeof value === 'boolean' || value === null
            ? String(value ?? 'none') : JSON.stringify(value, null, 2);
        lines.push(`${readableDiagnosticKey(key)}: ${rendered}`);
    });
    return lines.join('\n');
}

function formatTraceLine(event, selectedLevel = 'NORMAL') {
    if (selectedLevel === 'NONE') return '';
    const meta = event.metadata || {};
    const actor = String(meta.actor || meta.role || '').trim();
    const runtimeState = String(meta.runtime_state || '').trim();
    const timestamp = formatTraceTime(event.timestamp);

    if (meta.council_output) {
        return formatCouncilOutput(event, selectedLevel);
    }

    if (meta.interface_data) {
        return formatInterfaceOutput(event, selectedLevel);
    }

    if (runtimeState) {
        const activityActor = actor || String(event.component || 'Workflow');
        const identity = meta.execution_identity || {};
        const version = identity.entity_version !== undefined ? ` v${identity.entity_version}` : '';
        const failure = runtimeState === 'failed'
            && diagnosticDetailRank[selectedLevel] >= diagnosticDetailRank.INFO
            && meta.failure_category
            ? ` (${meta.failure_category})` : '';
        return `[${timestamp}] ${activityActor}${version} — ${runtimeState}${failure}`;
    }

    const rolePart = actor ? ` actor=${actor}` : '';
    const toolPart = meta.tool_name ? ` tool=${meta.tool_name}` : '';
    return `[${timestamp}] ${event.level} ${event.component}${rolePart}${toolPart} ${event.event} ${event.action} ${event.status}`;
}

function appendTrace(traceEvents) {
    currentTraceEvents = traceEvents;
    const container = document.getElementById('trace-list-container');
    const filter = document.getElementById('trace-filter').value;
    const selectedLevel = document.getElementById('trace-level-select').value;

    const filtered = traceEvents.filter(e => {
        const componentOk = filter === 'all' || e.component === filter;
        if (!componentOk) return false;
        const requiredLevel = (e.metadata || {}).diagnostic_level;
        if (!requiredLevel) return true;
        return diagnosticDetailRank[selectedLevel] >= diagnosticDetailRank[requiredLevel];
    });

    container.textContent = filtered
        .map(event => formatTraceLine(event, selectedLevel))
        .filter(line => line)
        .join('\n\n');
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
    currentDocSection = null;
    showHelpOverview();
    document.getElementById('help-view').classList.remove('hidden');
}

function hideHelp() {
    document.getElementById('help-view').classList.add('hidden');
    showNormalMainView();
    helpPitchDeckInitialized = false;
    currentDocSection = null;
}

function showHelpOverview() {
    document.getElementById('help-overview-content').classList.remove('hidden');
    document.getElementById('help-pitch-content').classList.add('hidden');
    document.getElementById('help-docs-content').classList.add('hidden');
    document.getElementById('help-overview-btn').classList.add('active');
    document.getElementById('help-pitch-btn').classList.remove('active');
    document.getElementById('help-docs-btn').classList.remove('active');
}

function showHelpPitch() {
    document.getElementById('help-overview-content').classList.add('hidden');
    document.getElementById('help-pitch-content').classList.remove('hidden');
    document.getElementById('help-docs-content').classList.add('hidden');
    document.getElementById('help-overview-btn').classList.remove('active');
    document.getElementById('help-pitch-btn').classList.add('active');
    document.getElementById('help-docs-btn').classList.remove('active');

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

// ---------- Documentation view ----------
function showHelpDocs() {
    document.getElementById('help-overview-content').classList.add('hidden');
    document.getElementById('help-pitch-content').classList.add('hidden');
    document.getElementById('help-docs-content').classList.remove('hidden');
    document.getElementById('help-overview-btn').classList.remove('active');
    document.getElementById('help-pitch-btn').classList.remove('active');
    document.getElementById('help-docs-btn').classList.add('active');

    if (!currentDocSection) {
        renderDocsTOC();
        showDocSection('sec-01');
    }
}

function renderDocsTOC() {
    const toc = document.getElementById('docs-toc');
    if (!toc || typeof DOC_TOC === 'undefined') return;
    toc.innerHTML = DOC_TOC.map(function(item) {
        return '<a href="#" class="docs-toc-link" data-doc-id="' + item.id + '">' + escapeHtml(item.title) + '</a>';
    }).join('');
    toc.querySelectorAll('.docs-toc-link').forEach(function(link) {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            showDocSection(e.target.getAttribute('data-doc-id'));
        });
    });
}

function showDocSection(sectionId) {
    currentDocSection = sectionId;
    var section = typeof docSections !== 'undefined' ? docSections[sectionId] : null;
    if (!section) return;
    var body = document.getElementById('docs-body');
    body.innerHTML = '<h2 class="docs-section-title">' + escapeHtml(section.title) + '</h2>' + (section.html || '');
    body.appendChild(buildDocSectionNav(sectionId));
    updateDocsBreadcrumb(sectionId);
    updateDocsTOCHighlight(sectionId);
    document.getElementById('docs-body').scrollTop = 0;
    document.querySelector('.docs-main').scrollTop = 0;
}

function buildDocSectionNav(sectionId) {
    var nav = document.createElement('div');
    nav.className = 'docs-section-nav';
    var index = DOC_TOC.findIndex(function(item) { return item.id === sectionId; });
    var prev = index > 0 ? DOC_TOC[index - 1] : null;
    var next = index >= 0 && index < DOC_TOC.length - 1 ? DOC_TOC[index + 1] : null;
    if (prev) {
        var prevBtn = document.createElement('button');
        prevBtn.className = 'back-button';
        prevBtn.textContent = '← ' + prev.title;
        prevBtn.addEventListener('click', function() { showDocSection(prev.id); });
        nav.appendChild(prevBtn);
    }
    var spacer = document.createElement('span');
    spacer.style.flex = '1';
    nav.appendChild(spacer);
    if (next) {
        var nextBtn = document.createElement('button');
        nextBtn.className = 'back-button';
        nextBtn.textContent = next.title + ' →';
        nextBtn.addEventListener('click', function() { showDocSection(next.id); });
        nav.appendChild(nextBtn);
    }
    return nav;
}

function updateDocsBreadcrumb(sectionId) {
    var breadcrumb = document.getElementById('docs-breadcrumb');
    var tocEntry = DOC_TOC.find(function(item) { return item.id === sectionId; });
    if (!tocEntry) return;
    breadcrumb.innerHTML = '<a href="#" class="docs-breadcrumb-link" id="docs-breadcrumb-home">ADC Documentation</a>' +
        ' <span class="docs-breadcrumb-sep">&rsaquo;</span> ' +
        '<span>' + escapeHtml(tocEntry.title) + '</span>';
    document.getElementById('docs-breadcrumb-home').addEventListener('click', function(e) {
        e.preventDefault();
        showDocSection('sec-01');
    });
}

function updateDocsTOCHighlight(sectionId) {
    document.querySelectorAll('.docs-toc-link').forEach(function(link) {
        link.classList.toggle('active', link.getAttribute('data-doc-id') === sectionId);
    });
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
    document.getElementById('project-name-display').textContent = name;
    document.getElementById('project-path-display').textContent = projectDirectory;
    document.getElementById('global-status').textContent = 'Ready';
    updateSessionDisplay(null);
    clearChat();

    const registered = await registerCurrentProjectPath(projectDirectory, name);
    if (registered) {
        currentProject.project_id = registered.project_id;
    }
    await fetchAndRenderProjects();
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
                    <p>NONE – suppress diagnostic presentation.<br>NORMAL – essential workflow progress and outcomes.<br>INFO – important workflow events with actor/provider context.<br>VERBOSE – structured handoffs, engineering fields and safe metadata.<br>VERY_VERBOSE – maximum diagnostic detail including sanitized effective LLM prompts.</p>
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
    {title: '6. New projects', html: () => `<p>Greenfield projects are part of the product direction. The central workflow creates them through a controlled GreenfieldProjectMaterializer — safe, explicit and Git-initialized. The Real-System E2E test already exercises this greenfield path end to end.</p>`},
    {title: '7. More than conventional software', html: () => `<p>The scope includes software, firmware, embedded and hardware-near development. Physical device actions remain behind a separate appropriate approval boundary and are not automatically available.</p>`},
    {title: '8. AI team and Engineering Council', html: () => `<p>Specialist roles examine the project and alternatives. The Engineering Council compares approaches, and a Chairman participates in the technical recommendation before controlled action is considered. The Real-System E2E test exercises A1/A2/A3 and Chairman with real LLM providers and models.</p>`},
    {title: '9. Human control', html: () => `<p>Setup, capability use, final development acceptance and publish each have separate approvals. An approval never becomes permission for arbitrary shell commands or another approval boundary. The Real-System E2E test provides test-owned approval for Setup, Final and toolchain boundaries without granting arbitrary execution.</p>`},
    {title: '10. Tools when needed', html: () => `<p>Missing toolchains are reported, not self-installed. Approved structured setup through the MissingToolchainSetup path and capability registration can extend future technologies without turning a fixed list into the product architecture. Only a command-free SetupPlan materialized from Project Intelligence and the Chairman Council result, followed by separate Human Approval, may invoke a registered structured installer — all exercised by the Real-System E2E test.</p>`},
    {title: '11. One project, multiple frontends', html: () => `<p>Web, Signal, API, CLI and MCP connect to the same central workflow. Signal is an adapter contract today; a concrete deployed provider remains future integration work. Active Signal chat and project bindings are strict 1:1.</p>`},
    {title: '12. Project Definitions / Memory', html: () => `<p>Observed project reality stays separate from explicit durable decisions and technical configuration. Conflicts are visible instead of silently merged, and raw chat history is not Project Memory.</p>`},
    {title: '13. Transparency while work happens', html: () => `<p>The central Diagnostic Trace records typed input x, the versioned processor identity f, and typed output y across planning handoffs. Type, interface, source and destination show the actual user intent entering through Web and reaching Requirement Discovery alongside separate observed Project Intelligence. This makes workflow execution more reproducible while keeping ADC entity versions distinct from configured AI provider and model identity. NONE suppresses diagnostic presentation without affecting central audit collection; NORMAL shows essential progress; INFO shows concise x/f/y; VERBOSE and VERY VERBOSE progressively reveal allowlisted structured data and safe metadata. At VERY VERBOSE level, sanitized effective LLM prompts (after template substitution) provide diagnostic transparency. Raw responses, private reasoning, credentials, and executable command payloads remain excluded at every level. Partial successful proposals and reviews remain inspectable after an incomplete Council. Trace rows use local HH:MM:SS.</p>`},
    {title: '14. From development to delivery', html: () => `<p>Controlled development leads to real verification and review, then separate final approval, controlled Git and Publish Approval. Verification never installs its own tools. A durable Real-System E2E test exercises this full productive workflow with real external providers, models, ESPHome validation/compile and controlled Git commit — opt-in only via --real-system-e2e.</p>`},
    {title: '15. Why AI Dev Center?', html: () => `<p>It combines project continuity, extensible capabilities, human control and transparent progress. Docker is the intended production direction, while unfinished integrations remain clearly identified.</p>`},
];

// ---------- Event binding ----------
document.getElementById('new-project-btn').addEventListener('click', openModal);
document.getElementById('cancel-project-btn').addEventListener('click', closeModal);
document.getElementById('create-project-btn').addEventListener('click', handleCreateProject);
document.getElementById('cancel-delete-project-btn').addEventListener('click', closeDeleteProjectModal);
document.getElementById('confirm-delete-project-btn').addEventListener('click', confirmDeleteProject);
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
document.getElementById('trace-level-select').addEventListener(
    'change', () => appendTrace(currentTraceEvents)
);
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
document.getElementById('help-docs-btn').addEventListener('click', showHelpDocs);
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
validateRecentProjects();
fetchAndRenderProjects();
