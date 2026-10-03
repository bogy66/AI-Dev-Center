from pathlib import Path


class ProjectScanner:


    def scan(self, project_path):

        root = Path(project_path)

        files = []

        for file in root.rglob("*"):

            if file.is_file():

                files.append(
                    str(
                        file.relative_to(root)
                    )
                )


        return files
