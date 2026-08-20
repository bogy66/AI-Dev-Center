import threading
from pathlib import Path


_registry_lock = threading.Lock()
_running_projects = set()


def _project_key(project):
    return str(Path(project).resolve())


def try_start(project):
    """
    Attempts to mark a project as having an in-progress workflow run
    (run_workflow() or rework_workflow()).

    Returns True if this call successfully acquired the guard, i.e.
    no other run is currently in progress for this project. Returns
    False if a run is already in progress for this project.

    This only serializes the *entry* into a workflow run. It never
    holds a lock while the actual (potentially long-running) LLM,
    Git, tester or reviewer calls execute - the lock protecting the
    internal registry is held only for the brief moment needed to
    check and set membership in a set.

    Callers must call finish(project) - typically in a finally block
    - once their run completes, to release the guard for subsequent
    calls.

    The guard is shared between run_workflow() and rework_workflow()
    for the same resolved project path, so the two cannot run
    concurrently for the same project either. Different projects use
    independent keys and never block each other.
    """
    key = _project_key(project)

    with _registry_lock:
        if key in _running_projects:
            return False

        _running_projects.add(key)
        return True


def finish(project):
    """
    Releases the in-progress guard for a project, allowing a
    subsequent run_workflow()/rework_workflow() call for the same
    project to proceed.

    Safe to call even if the project was never registered (e.g. if
    try_start() had returned False for this call).
    """
    key = _project_key(project)

    with _registry_lock:
        _running_projects.discard(key)
