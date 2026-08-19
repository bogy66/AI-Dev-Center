from app.agent_config import AGENT_CONFIG
from app.agent_manager import AgentManager
from app.agent_executor import AgentExecutor
from app.agent_roles import AGENT_ROLES
from app.project_reader import ProjectReader
from app.workflow_manager import WorkflowManager
from app.tester_agent import TesterAgent
from app.reviewer_agent import ReviewerAgent

class AgentOrchestrator:

    def __init__(
        self,
        agent_manager: AgentManager,
        agent_executor: AgentExecutor
    ):
        self.agent_manager = agent_manager
        self.agent_executor = agent_executor
        self.project_reader = ProjectReader()

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
            # Simulate DEV commit
            workflow_manager.update_agent("developer", "committed")
            state["status"] = "developer_committed"

        if state["status"] == "developer_committed":
            tester_agent = TesterAgent()
            state = tester_agent.test(project, workflow_manager.storage)
            state["status"] = "tester_completed"

        if state["status"] == "tester_completed":
            # Simulate TEST commit
            workflow_manager.update_agent("tester", "committed")
            state["status"] = "tester_committed"

        if state["status"] == "tester_committed":
            reviewer_agent = ReviewerAgent()
            state = reviewer_agent.review(project, workflow_manager.storage)
            state["status"] = "reviewer_completed"

        if state["status"] == "reviewer_completed":
            state["status"] = "approval_waiting"

        workflow_manager.save(state)
        return state
