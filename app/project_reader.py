from pathlib import Path


class ProjectReader:


    def read_files(
        self,
        project_path,
        max_files=20,
        max_chars=3000
    ):

        root = Path(project_path)

        result = {}


        count = 0

        for file in root.rglob("*"):

            if count >= max_files:
                break


            if not file.is_file():
                continue


            if any(
                x in file.parts
                for x in [
                    ".git",
                    "venv",
                    "__pycache__"
                ]
            ):
                continue


            try:

                content = file.read_text(
                    encoding="utf-8"
                )


                result[str(file.relative_to(root))] = (
                    content[:max_chars]
                )


                count += 1


            except Exception:

                pass


        return result
