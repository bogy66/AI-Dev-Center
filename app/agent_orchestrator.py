from app.agent_config import AGENT_CONFIG
from app.agent_manager import AgentManager
from app.agent_executor import AgentExecutor
from app.agent_roles import AGENT_ROLES
from app.project_reader import ProjectReader
from app.workflow_manager import WorkflowManager
from app.git_manager import GitManager
from app.tester_agent import TesterAgent
from app.reviewer_agent import ReviewerAgent
from app.developer_changes import DeveloperChanges
from app.developer_file_applier import DeveloperFileApplier


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
        developer_response = self.agent_executor.run(
            AGENT_ROLES["developer"],
            task,
            "",
            "developer",
            AGENT_CONFIG["developer"]["max_tokens"]
        )

        # Step 5: Parse developer changes
        developer_changes = DeveloperChanges.parse(
            developer_response
        )

        # Step 6: Apply developer changes
        file_applier = DeveloperFileApplier(project)

        apply_result = file_applier.apply(
            developer_changes
        )

        if not apply_result["applied"]:
            state = workflow_manager.load()
            state["status"] = "development_no_changes"
            workflow_manager.save(state)

            return workflow_manager.load()

        # Step 7: Create DEV Git commit
        commit_result = git_manager.commit_and_get_hash(
            project,
            "DEV: Development completed"
        )

        if commit_result["code"] != 0:
            state = workflow_manager.load()

            if (
                "nothing to commit" in commit_result["stdout"].lower()
                and "working tree clean" in commit_result["stdout"].lower()
            ):
                state["status"] = "development_no_changes"
                workflow_manager.save(state)

            return workflow_manager.load()

        workflow_manager.update_agent(
            "developer",
            "completed",
            commit=commit_result["commit"]
        )

        # Step 8: Run TesterAgent
        tester_state = tester_agent.test(
            project,
            str(workflow_manager.storage)
        )

        # Step 9: Check Tester state
        if (
            tester_state["tester"]["status"] != "completed"
            or tester_state["tester"]["result"] != "PASS"
        ):
            return tester_state

        # Step 10: Run ReviewerAgent
        reviewer_state = reviewer_agent.review(
            project,
            str(workflow_manager.storage)
        )

        # Step 11: Check Reviewer state
        if reviewer_state.get("status") != "approved":
            return reviewer_state

        # Step 12: Wait for user approval
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
            files_context += (
                f"\n\n===== {name} =====\n\n"
                f"{content}\n\n"
            )

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

            previous_results += (
                f"\n\n===== {role} =====\n\n"
                f"{response[:limit]}\n\n"
            )

        return responses
