from pathlib import Path


class AgentManager:

    AGENTS = [
        "project_manager",
        "architect",
        "developer",
        "reviewer",
        "tester"
    ]


    def load_agents(self, project_path):

        project = Path(project_path)

        ai_folder = project / ".ai"

        if not ai_folder.exists():
            raise Exception(
                ".ai Verzeichnis nicht gefunden"
            )


        agents = {}

        for agent in self.AGENTS:

            file = ai_folder / f"{agent}.md"

            if file.exists():

                agents[agent] = (
                    file.read_text(
                        encoding="utf-8"
                    )
                )


        return {
            "project": str(project),
            "agents": agents
        }
