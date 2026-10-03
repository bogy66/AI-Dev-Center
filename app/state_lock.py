import threading
from pathlib import Path


_registry_lock = threading.Lock()
_locks = {}


def get_state_lock(path):
    """
    Returns a shared, reentrant lock for a given storage path.

    WorkflowManager, ApprovalManager and AgentOrchestrator may all
    read-modify-write the same physical state file. To prevent lost
    updates between their operations, they must synchronize on the
    same lock instance for a given resolved path.
    """
    key = str(Path(path).resolve())

    with _registry_lock:
        if key not in _locks:
            _locks[key] = threading.RLock()

        return _locks[key]
