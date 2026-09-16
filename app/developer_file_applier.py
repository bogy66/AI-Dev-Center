"""S4.3 Change Application: apply a structured change-set to disk.

Project-root path safety is owned centrally by app.safe_project_path
(resolve_safe_path) -- this class does not implement its own,
independent notion of what counts as a safe path. An unsafe requested
path is a deterministic, fail-closed application failure: it is
reported in `skipped` (reason "unsafe_path"), never silently dropped,
and never mutates anything outside the project root.
"""
from pathlib import Path

from app.safe_project_path import resolve_safe_path


class DeveloperFileApplier:

    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()

    def apply(self, changes):
        applied = []
        skipped = []

        for change in changes.get("changes", []):
            requested = change.get("file")
            file_path = resolve_safe_path(self.project_root, requested)
            action = change.get("action")
            content = change.get("content", "")

            if file_path is None:
                skipped.append({
                    "file": requested,
                    "reason": "unsafe_path"
                })
                continue

            if action == "create":
                if file_path.exists():
                    skipped.append({
                        "file": requested,
                        "reason": "already_exists"
                    })
                    continue

                try:
                    file_path.parent.mkdir(
                        parents=True,
                        exist_ok=True
                    )
                except OSError as error:
                    skipped.append({
                        "file": requested,
                        "reason": f"mkdir_failed: {error}"
                    })
                    continue

                try:
                    file_path.write_text(
                        content,
                        encoding="utf-8"
                    )
                except OSError as error:
                    skipped.append({
                        "file": requested,
                        "reason": f"write_failed: {error}"
                    })
                    continue

                applied.append(requested)

            elif action == "update":
                if not file_path.exists():
                    skipped.append({
                        "file": requested,
                        "reason": "file_not_found"
                    })
                    continue

                file_path.write_text(
                    content,
                    encoding="utf-8"
                )
                applied.append(requested)

            elif action == "delete":
                if not file_path.exists():
                    skipped.append({
                        "file": requested,
                        "reason": "file_not_found"
                    })
                    continue

                file_path.unlink()
                applied.append(requested)

        return {
            "applied": applied,
            "skipped": skipped
        }
