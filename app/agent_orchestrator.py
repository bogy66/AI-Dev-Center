from app.agent_config import AGENT_CONFIG
from app.agent_manager import AgentManager
from app.agent_executor import AgentExecutor
from app.agent_roles import AGENT_ROLES
from app.project_reader import ProjectReader
from app.workflow_manager import WorkflowManager
from app.git_manager import GitManager
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
        git_manager = GitManager()
        tester_agent = TesterAgent()
        reviewer_agent = ReviewerAgent()

        # Step 1: Create a new workflow
        workflow_manager.create(task, "dev_branch")

        # Step 2: Run Project Manager
        self.agent_executor.run(
            AGENT_ROLES["project_manager"],
            task,
            "",
            "project_manager",
            AGENT_CONFIG["project_manager"]["max_tokens"]
        )

        # Step 3: Run Architect
        self.agent_executor.run(
            AGENT_ROLES["architect"],
            task,
            "",
            "architect",
            AGENT_CONFIG["architect"]["max_tokens"]
        )

        # Step 4: Run Developer
        self.agent_executor.run(
            AGENT_ROLES["developer"],
            task,
            "",
            "developer",
            AGENT_CONFIG["developer"]["max_tokens"]
        )

        # Step 5: Create a real DEV Git commit
        git_manager.commit(project, "Development changes")

        # Step 6: Run TesterAgent
        tester_agent.test(project, str(workflow_manager.storage))

        # Step 7: Create a real TEST Git commit
        git_manager.commit(project, "Testing changes")

        # Step 8: Run ReviewerAgent
        review_result = reviewer_agent.review(project, str(workflow_manager.storage))

        # Step 9: Update workflow status if review is successful
        if review_result == "success":
            workflow_manager.update_agent("reviewer", "approved")
            state = workflow_manager.load()
            state["status"] = "approval_waiting"
            workflow_manager.save(state)

        return workflow_manager.load()

    def run(self, project, task):
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

            executor = AgentExecutor(model=AGENT_CONFIG[role]["model"])
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
