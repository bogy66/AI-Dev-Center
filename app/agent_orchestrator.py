from app.agent_manager import AgentManager
from app.agent_executor import AgentExecutor


class AgentOrchestrator:

    def __init__(
        self,
        agent_manager: AgentManager,
        agent_executor: AgentExecutor
    ):
        self.agent_manager = agent_manager
        self.agent_executor = agent_executor


    def run(
        self,
        project,
        task
    ):

        # Agenten laden
        agents = self.agent_manager.load_agents(
            project
        )

        # Projektkontext laden
        project_context = self.agent_manager.load_context(
            project
        )

        responses = {}

        for role in [
            "project_manager",
            "architect",
            "developer",
            "tester",
            "reviewer"
        ]:

            response = self.agent_executor.run(
                agents["agents"][role],
                task,
                project_context
            )

            responses[role] = response


        return responses
