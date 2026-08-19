from app.agent_config import AGENT_CONFIG
from app.agent_manager import AgentManager
from app.agent_executor import AgentExecutor
from app.agent_roles import AGENT_ROLES
from app.project_reader import ProjectReader

class AgentOrchestrator:

    def __init__(
        self,
        agent_manager: AgentManager,
        agent_executor: AgentExecutor
    ):
        self.agent_manager = agent_manager
        self.agent_executor = agent_executor
        self.project_reader = ProjectReader()

    def run(
        self,
        project,
        task
    ):

        agents = self.agent_manager.load_agents(
            project
        )

        project_context = self.agent_manager.load_context(
            project
        )

        project_files = self.project_reader.read_files(
            project
        )


        files_context = ""

        for name, content in project_files.items():

            files_context += f"""

        ===== {name} =====

        {content}

        """

        responses = {}

        previous_results = ""


        for role in AGENT_ROLES:

            limit = AGENT_CONFIG[role]["max_context"]

            context = f"""
            Projektkontext:

            {project_context}


            Projektdateien:

            {files_context[:4000]}


            Vorherige Team-Ergebnisse:

            {previous_results[-limit:]}
            """

            executor = AgentExecutor(
                model=AGENT_CONFIG[role]["model"]
            )


            response = self.agent_executor.run(
                AGENT_ROLES[role],
                task,
                context,
                role,
                AGENT_CONFIG[role]["max_tokens"]
            )


            responses[role] = response


            limit = AGENT_CONFIG[role]["max_context"]

            previous_results += f"""

            ===== {role} =====

            {response[:limit]}

            """


        return responses
