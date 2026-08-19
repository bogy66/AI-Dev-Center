import subprocess


class GitManager:


    def run(self, command, cwd):

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

        return self.run(
            f'git add . && git commit -m "{message}"',
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
