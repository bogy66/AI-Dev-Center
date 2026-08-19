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

        # 1. Workflow erstellen
        workflow_manager.create(
            task,
            "dev_branch"
        )

        # 2. Project Manager
        self.agent_executor.run(
            AGENT_ROLES["project_manager"],
            task,
            "",
            "project_manager",
            AGENT_CONFIG["project_manager"]["max_tokens"]
        )

        # 3. Architect
        self.agent_executor.run(
            AGENT_ROLES["architect"],
            task,
            "",
            "architect",
            AGENT_CONFIG["architect"]["max_tokens"]
        )

        # 4. Developer
        developer_response = self.agent_executor.run(
            AGENT_ROLES["developer"],
            task,
            "",
            "developer",
            AGENT_CONFIG["developer"]["max_tokens"]
        )

        # 5. Developer-Antwort parsen
        developer_changes = DeveloperChanges.parse(
            developer_response
        )

        # 6. Änderungen anwenden
        file_applier = DeveloperFileApplier(
            project
        )

        apply_result = file_applier.apply(
            developer_changes
        )

        if not apply_result.get("applied"):

            state = workflow_manager.load()

            state["status"] = "development_no_changes"

            workflow_manager.save(
                state
            )

            return workflow_manager.load()

        # 7. DEV Commit
        commit_result = git_manager.commit_and_get_hash(
            project,
            "DEV: Development completed"
        )

        if commit_result.get("code") != 0:

            state = workflow_manager.load()

            stdout = commit_result.get(
                "stdout",
                ""
            ).lower()

            if (
                "nothing to commit" in stdout
                and "working tree clean" in stdout
            ):
                state["status"] = "development_no_changes"

                workflow_manager.save(
                    state
                )

            return workflow_manager.load()

        workflow_manager.update_agent(
            "developer",
            "completed",
            commit=commit_result["commit"]
        )

        # 8. Tester
        tester_state = tester_agent.test(
            project,
            str(workflow_manager.storage)
        )

        # Tester-Ergebnis in den zentralen Workflow-State
        # übernehmen. Das macht den Orchestrator unabhängig
        # davon, ob TesterAgent selbst persistiert oder nicht.

        state = workflow_manager.load()

        tester_info = tester_state.get(
            "tester",
            {}
        )

        if tester_info:

            state["tester"] = {
                **state.get("tester", {}),
                **tester_info
            }

            workflow_manager.save(
                state
            )

        state = workflow_manager.load()

        tester_info = state.get(
            "tester",
            {}
        )

        if tester_info.get("status") != "completed":
            return state

        if tester_info.get("result") != "PASS":
            return state

        # 9. Reviewer
        reviewer_state = reviewer_agent.review(
            project,
            str(workflow_manager.storage)
        )

        # Reviewer-Ergebnis ebenfalls zentral persistieren.

        state = workflow_manager.load()

        reviewer_info = reviewer_state.get(
            "reviewer",
            {}
        )

        if reviewer_info:

            state["reviewer"] = {
                **state.get("reviewer", {}),
                **reviewer_info
            }

        reviewer_status = reviewer_state.get(
            "status"
        )

        if reviewer_status != "approved":

            workflow_manager.save(
                state
            )

            return state

        # Reviewer kann entweder einen vollständigen
        # Workflow-State oder nur {"status": "approved"}
        # zurückgeben.

        reviewer = state.get(
            "reviewer",
            {}
        )

        reviewer["status"] = "approved"

        if reviewer_info.get("result") is not None:
            reviewer["result"] = reviewer_info["result"]

        state["reviewer"] = reviewer

        workflow_manager.save(
            state
        )

        # 10. Auf Benutzerfreigabe warten

        state = workflow_manager.load()

        state["status"] = "approval_waiting"

        workflow_manager.save(
            state
        )

        return workflow_manager.load()

    def run(
        self,
        project,
        task
    ):
        self.agent_manager.load_agents(
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
