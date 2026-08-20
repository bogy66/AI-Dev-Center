import py_compile
from pathlib import Path


class TestRunner:

    def run(self, project):

        app_dir = Path(project) / "app"

        errors = []

        for file in sorted(app_dir.rglob("*.py")):

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
