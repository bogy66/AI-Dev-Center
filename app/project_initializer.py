from pathlib import Path


class ProjectInitializer:

    def initialize(self, project_path):

        project = Path(project_path)

        folders = [
            ".ai",
            "docs",
            "tasks"
        ]

        for folder in folders:
            (project / folder).mkdir(
                parents=True,
                exist_ok=True
            )

        self.create_files(project)

        return {
            "project": str(project),
            "status": "initialized"
        }


    def create_files(self, project):

        files = {

            ".ai/rules.md":
            "# AI Development Rules\n\n"
            "- Analyse vor Änderung\n"
            "- Tests erstellen\n"
            "- Architektur beachten\n",


            ".ai/project_manager.md":
            "# Project Manager Agent\n\n"
            "Plant Aufgaben und koordiniert Agenten.\n",


            ".ai/architect.md":
            "# Architect Agent\n\n"
            "Prüft Architektur und Datenfluss.\n",


            ".ai/developer.md":
            "# Developer Agent\n\n"
            "Implementiert bestätigte Aufgaben.\n",


            ".ai/reviewer.md":
            "# Reviewer Agent\n\n"
            "Prüft Änderungen.\n",


            ".ai/tester.md":
            "# Tester Agent\n\n"
            "Erstellt Tests.\n",


            "docs/ARCHITECTURE.md":
            "# Architecture\n\n",


            "docs/WORKFLOW.md":
            "# Workflow\n\n",


            "tasks/BACKLOG.md":
            "# Backlog\n\n",


            "tasks/CURRENT_TASK.md":
            "# Current Task\n\n",


            "README.md":
            "# Project\n\n"
        }


        for filename, content in files.items():

            path = project / filename

            if not path.exists():
                path.write_text(
                    content,
                    encoding="utf-8"
                )
