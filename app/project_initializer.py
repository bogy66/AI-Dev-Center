from pathlib import Path
import shutil


class ProjectInitializer:

    def __init__(self):
        self.template = (
            Path(__file__).parent.parent
            / "templates"
            / "project_template"
        )


    def initialize(self, project_path):

        project = Path(project_path)

        if not self.template.exists():
            raise Exception(
                "Template nicht gefunden"
            )

        project.mkdir(
            parents=True,
            exist_ok=True
        )

        self.copy_template(project)

        return {
            "project": str(project),
            "status": "initialized"
        }


    def copy_template(self, project):

        for item in self.template.iterdir():

            target = project / item.name

            if item.is_dir():
                shutil.copytree(
                    item,
                    target,
                    dirs_exist_ok=True
                )

            else:
                shutil.copy2(
                    item,
                    target
                )
