import py_compile
from pathlib import Path


class TestRunner:

    def run(self, project, changes=None):

        project_root = Path(project)

        python_files = self._resolve_python_files(
            project_root,
            changes
        )

        errors = []

        for file in python_files:

            try:
                py_compile.compile(
                    str(file),
                    doraise=True
                )
            except py_compile.PyCompileError as error:
                errors.append(str(error))

        success = not errors

        return {
            "success": success,
            "stdout": "",
            "stderr": "\n".join(errors)
        }

    def _resolve_python_files(self, project_root, changes):

        if changes:
            changed_files = self._changed_python_files(
                project_root,
                changes
            )

            if changed_files:
                return changed_files

        app_dir = project_root / "app"

        return sorted(app_dir.rglob("*.py"))

    def _changed_python_files(self, project_root, changes):

        resolved_root = project_root.resolve()

        files = []

        for change in changes.get("changes", []):

            if change.get("action") == "delete":
                continue

            file_path = change.get("file", "")

            if not file_path.endswith(".py"):
                continue

            candidate = (project_root / file_path).resolve()

            try:
                candidate.relative_to(resolved_root)
            except ValueError:
                continue

            if candidate.is_file():
                files.append(candidate)

        return sorted(files)
