from pathlib import Path


class DeveloperFileApplier:

    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()

    def _safe_path(self, file_path):
        path = (self.project_root / file_path).resolve()

        try:
            path.relative_to(self.project_root)
        except ValueError:
            return None

        return path

    def apply(self, changes):
        applied = []
        skipped = []

        for change in changes.get("changes", []):
            file_path = self._safe_path(change.get("file", ""))
            action = change.get("action")
            content = change.get("content", "")

            if file_path is None:
                continue

            if action == "create":
                if file_path.exists():
                    skipped.append({
                        "file": change["file"],
                        "reason": "already_exists"
                    })
                    continue

                file_path.parent.mkdir(
                    parents=True,
                    exist_ok=True
                )
                file_path.write_text(
                    content,
                    encoding="utf-8"
                )
                applied.append(change["file"])

            elif action == "update":
                if not file_path.exists():
                    continue

                file_path.write_text(
                    content,
                    encoding="utf-8"
                )
                applied.append(change["file"])

            elif action == "delete":
                if not file_path.exists():
                    continue

                file_path.unlink()
                applied.append(change["file"])

        return {
            "applied": applied,
            "skipped": skipped
        }
