let currentSessionId = null;
let currentProject = null;
let recents = JSON.parse(localStorage.getItem('recents') || '[]');
let pollingTimer = null;

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
    currentSessionId = currentProject.session_id || null;
    document.getElementById('project-name-display').textContent = currentProject.project_name;
    document.getElementById('global-status').textContent = currentSessionId ? 'Connected' : 'Ready';
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
    const info = document.getElementById('session-info');
    const code = document.getElementById('session-id-display');
    if (sessionId) {
        code.textContent = sessionId;
        info.style.display = 'inline-flex';
    } else {
        info.style.display = 'none';
        code.textContent = '';
    }
}

function appendTrace(traceEvents) {
    const container = document.getElementById('trace-list-container');
    const filter = document.getElementById('trace-filter').value;
    const level = document.getElementById('trace-level-select').value;

    const filtered = traceEvents.filter(e => {
        const levelOk = level === 'DEBUG' || e.level === level;
        const componentOk = filter === 'all' || e.component === filter;
        return levelOk && componentOk;
    });

    container.innerHTML = filtered.map(e =>
        `[${e.timestamp}] ${e.level} ${e.component} ${e.event} ${e.action} ${e.status}`
    ).join('\n');
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
    document.getElementById('project-name-display').textContent = state.project_id;
    if (state.approval_required) {
        setLiveStatus('Waiting for approval...');
    } else if (state.workflow_status === 'completed') {
        setLiveStatus('Completed');
        stopPolling();
    } else if (state.blocked) {
        setLiveStatus('Blocked');
        stopPolling();
    } else {
        const info = state.transparency || {};
        const action = info.current_action || info.current_mcp_tool || '';
        setLiveStatus(action ? `Thinking… ${action}` : 'Thinking…');
    }
    appendTrace(state.trace || []);
    if (state.error_message) {
        setLiveStatus(`Error: ${state.error_message}`);
    }
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
        const delta = startY - e.clientY; // up increases height
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

function handleCreateProject() {
    const name = document.getElementById('project-name-input').value.trim();
    const dir = document.getElementById('project-dir-input').value.trim();
    const traceLevel = document.getElementById('new-project-trace-level').value;
    if (!name || !dir) {
        alert('Project name and directory are required');
        return;
    }

    const project = {
        project_name: name,
        project_directory: dir,
        project_path: dir,
        trace_level: traceLevel,
        session_id: null,
    };
    recents.push(project);
    saveRecents();
    currentProject = project;
    currentSessionId = null;
    closeModal();
    renderRecents();
    document.getElementById('project-name-display').textContent = name;
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
        // First message starts the workflow
        setLiveStatus('Starting workflow...');
        try {
            const resp = await fetchJson('/api/workflow/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    project_name: currentProject.project_name,
                    project_directory: currentProject.project_path,
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
        // For now, additional messages are just displayed.
        setLiveStatus('Message noted (backend does not support follow-ups yet)');
    }
}

// ---------- Event binding ----------
document.getElementById('new-project-btn').addEventListener('click', openModal);
document.getElementById('cancel-project-btn').addEventListener('click', closeModal);
document.getElementById('create-project-btn').addEventListener('click', handleCreateProject);
document.getElementById('choose-directory-btn').addEventListener('click', () => {
    document.getElementById('project-directory-picker').click();
});
document.getElementById('project-directory-picker').addEventListener('change', (event) => {
    const files = event.target.files;
    if (files.length > 0) {
        const first = files[0];
        const path = first.webkitRelativePath || first.name;
        document.getElementById('project-dir-input').value = path;
    }
});
document.getElementById('send-btn').addEventListener('click', handleSend);
document.getElementById('chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
    }
    // Shift+Enter creates a newline naturally.
});
document.getElementById('copy-session-btn').addEventListener('click', () => {
    const sid = document.getElementById('session-id-display').textContent;
    if (sid) {
        navigator.clipboard.writeText(sid).catch(() => {
            // fallback
            const ta = document.createElement('textarea');
            ta.value = sid;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        });
    }
});
document.getElementById('trace-filter').addEventListener('change', () => {
    // refresh trace; will be handled in polling or state load
});
document.getElementById('trace-level-select').addEventListener('change', () => {
    // same
});
document.getElementById('clear-trace-btn').addEventListener('click', () => {
    document.getElementById('trace-list-container').innerHTML = '';
});
document.getElementById('copy-all-btn').addEventListener('click', () => {
    const text = document.getElementById('trace-list-container').innerText;
    navigator.clipboard.writeText(text || '(empty)').catch(() => {
        // fallback
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

// Initial render
initTraceDrag();
renderRecents();
if (recents.length > 0) {
    selectProject(0);
}
