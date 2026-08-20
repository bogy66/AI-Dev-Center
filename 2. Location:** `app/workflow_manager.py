def create(self, task, branch):
    state = {
        "task": task, "branch": branch, "status": "started",
        "developer": {...}, "tester": {...}, "reviewer": {...},
        "user_approval": {...}, "created": str(datetime.now())
    }
    self.save(state)
    return state

def load(self):
    if not self.storage.exists():
        return {"status": "not_started"}
    return json.loads(...)
