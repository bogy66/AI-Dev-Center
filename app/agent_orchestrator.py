from app.agent_config import AGENT_CONFIG
from app.agent_manager import AgentManager
from app.agent_executor import AgentExecutor
from app.agent_roles import AGENT_ROLES
from app.project_reader import ProjectReader
from app.workflow_manager import WorkflowManager
from app.tester_agent import TesterAgent
from app.reviewer_agent import ReviewerAgent
from app.git_manager import GitManager

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
        agents = self.agent_manager.load_agents(project)
        project_context = self.agent_manager.load_context(project)
        project_files = self.project_reader.read_files(project)

        files_context = ""
        for name, content in project_files.items():
            files_context += f"\n\n===== {name} =====\n\n{content}\n\n"

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

            response = self.agent_executor.run(
                AGENT_ROLES[role],
                task,
                context,
                role,
                AGENT_CONFIG[role]["max_tokens"]
            )

            responses[role] = response
            previous_results += f"\n\n===== {role} =====\n\n{response[:limit]}\n\n"

        return responses

    def run_workflow(
        self,
        project,
        task
    ):

        workflow_manager = WorkflowManager()
        state = workflow_manager.load()

        if not state or state["status"] == "started":
            state = workflow_manager.create(task, "dev-branch")

        if state["status"] == "started":
            responses = self.run_agents(project, task)
            workflow_manager.update_agent("project_manager", "completed")
            state["status"] = "project_manager_completed"

        if state["status"] == "project_manager_completed":
            responses = self.run_agents(project, task)
            workflow_manager.update_agent("architect", "completed")
            state["status"] = "architect_completed"

        if state["status"] == "architect_completed":
            responses = self.run_agents(project, task)
            workflow_manager.update_agent("developer", "completed")
            state["status"] = "developer_completed"

        if state["status"] == "developer_completed":
            git_manager = GitManager()
            commit_result = git_manager.commit_and_get_hash(project, "DEV: Development completed")
            workflow_manager.update_agent("developer", "committed", commit=commit_result["commit"])
            state["status"] = "developer_committed"

        if state["status"] == "developer_committed":
            tester_agent = TesterAgent()
            state = tester_agent.test(project, workflow_manager.storage)
            state["status"] = "tester_completed"

        if state["status"] == "tester_completed":
            git_manager = GitManager()
            commit_result = git_manager.commit_and_get_hash(project, "TEST: Testing completed")
            workflow_manager.update_agent("tester", "committed", commit=commit_result["commit"])
            state["status"] = "tester_committed"

        if state["status"] == "tester_committed":
            reviewer_agent = ReviewerAgent()
            state = reviewer_agent.review(project, workflow_manager.storage)
            state["status"] = "reviewer_completed"

        if state["status"] == "reviewer_completed":
            state["status"] = "approval_waiting"

        workflow_manager.save(state)
        return state
