import subprocess


class TestRunner:


    def run(
        self,
        project
    ):

        result = subprocess.run(
            "python -m py_compile app/*.py",
            cwd=project,
            shell=True,
            text=True,
            capture_output=True
        )


        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
