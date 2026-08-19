from pathlib import Path


class SpecificationTester:

    def _safe_path(self, project_root, file_path):
        root = Path(project_root).resolve()
        path = (root / file_path).resolve()

        try:
            path.relative_to(root)
        except ValueError:
            return None

        return path

    def check(self, project, changes):
        errors = []

        for change in changes.get("changes", []):
            file_path = change.get("file", "")
            action = change.get("action")
            expected_content = change.get("content", "")

            path = self._safe_path(
                project,
                file_path
            )

            if path is None:
                errors.append(
                    f"Unsicherer Dateipfad: {file_path}"
                )
                continue

            if action in ("create", "update"):

                if not path.exists():
                    errors.append(
                        f"Datei fehlt: {file_path}"
                    )
                    continue

                if not path.is_file():
                    errors.append(
                        f"Kein regulärer Dateipfad: {file_path}"
                    )
                    continue

                actual_content = path.read_text(
                    encoding="utf-8"
                )

                if actual_content != expected_content:
                    errors.append(
                        f"Inhalt stimmt nicht: {file_path}"
                    )

            elif action == "delete":

                if path.exists():
                    errors.append(
                        f"Datei wurde nicht gelöscht: {file_path}"
                    )

            else:

                errors.append(
                    f"Unbekannte Aktion: {action}"
                )

        return {
            "success": not errors,
            "errors": errors
        }
