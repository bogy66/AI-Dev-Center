from pathlib import PurePosixPath


class DeveloperChanges:

    ALLOWED_ACTIONS = {
        "create",
        "update",
        "delete"
    }

    @staticmethod
    def _clean_content(content):
        content = content.strip()

        if content.startswith("```"):
            lines = content.splitlines()

            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            content = "\n".join(lines).strip()

        return content


    @staticmethod
    def _valid_path(file_path):
        if not file_path:
            return False

        path = PurePosixPath(file_path)

        if path.is_absolute():
            return False

        if ".." in path.parts:
            return False

        return True

    @staticmethod
    def parse(response):
        changes = []

        files_section = response.split("## Dateien", 1)

        if len(files_section) != 2:
            return {
                "changes": [],
                "tests": []
            }

        files_text = files_section[1]

        tests_section = files_text.split("## Tests", 1)

        files_text = tests_section[0]

        tests = []

        if len(tests_section) == 2:
            tests = [
                line.strip()
                for line in tests_section[1].splitlines()
                if line.strip()
            ]

        blocks = files_text.split("### Datei:")

        for block in blocks[1:]:

            lines = block.strip().splitlines()

            if not lines:
                continue

            file_path = lines[0].strip()

            if not DeveloperChanges._valid_path(file_path):
                continue

            action_marker = "### Aktion:"

            if action_marker not in block:
                continue

            action_part = block.split(
                action_marker,
                1
            )[1]

            action_lines = action_part.strip().splitlines()

            if not action_lines:
                continue

            action = action_lines[0].strip().lower()

            if action not in DeveloperChanges.ALLOWED_ACTIONS:
                continue

            content_marker = "### Inhalt:"

            content = ""

            if content_marker in action_part:
                content = action_part.split(
                    content_marker,
                    1
                )[1].strip()

            content = DeveloperChanges._clean_content(
                content
            )

            changes.append({
                "file": file_path,
                "action": action,
                "content": content
            })

        return {
            "changes": changes,
            "tests": tests
        }

    @staticmethod
    def _clean_content(content):
        content = content.strip()

        if content.startswith("```"):
            lines = content.splitlines()

            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            content = "\n".join(lines).strip()

        return content
