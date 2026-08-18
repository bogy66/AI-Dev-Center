class AgentOrchestrator:
    def __init__(self, agent_manager, agent_executor):
        self.agent_manager = agent_manager
        self.agent_executor = agent_executor

    def run(self, project, task):
        # Load agents using AgentManager
        agents = self.agent_manager.load_agents()

        # Load project context
        project_context = self.agent_manager.load_project_context(project)

        # Execute agents using AgentExecutor
        responses = {}
        for role in ["project_manager", "architect", "developer", "tester", "reviewer"]:
            response = self.agent_executor.execute(agents[role], project_context, task)
            responses[role] = response

        return responses
