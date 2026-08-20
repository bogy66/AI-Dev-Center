import subprocess


class GitManager:

    def run(self, command, cwd):

        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                text=True,
                capture_output=True
            )

            return {
                "code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()
            }

        except OSError as error:
            return {
                "code": 1,
                "stdout": "",
                "stderr": str(error)
            }

    def _run_args(self, args, cwd):

        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                shell=False,
                text=True,
                capture_output=True
            )

            return {
                "code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()
            }

        except OSError as error:
            return {
                "code": 1,
                "stdout": "",
                "stderr": str(error)
            }

    def commit_and_get_hash(
        self,
        project,
        message
    ):

        result = self.commit(
            project,
            message
        )

        if result["code"] != 0:
            return result

        commit = self.last_commit(
            project
        )

        if commit["code"] != 0:
            return commit

        return {
            "code": 0,
            "commit": commit["stdout"],
            "message": message
        }

    def commit(
        self,
        project,
        message
    ):

        add_result = self._run_args(
            ["git", "add", "."],
            project
        )

        if add_result["code"] != 0:
            return add_result

        return self._run_args(
            ["git", "commit", "-m", message],
            project
        )

    def push(
        self,
        project
    ):

        return self.run(
            "git push",
            project
        )

    def last_commit(
        self,
        project
    ):

        return self.run(
            "git rev-parse HEAD",
            project
        )

    def diff(
        self,
        project
    ):

        return self.run(
            "git diff HEAD",
            project
        )
