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
        agent_executor: AgentExecutor,
        workflow_manager: WorkflowManager | None = None
    ):
        self.agent_manager = agent_manager
        self.agent_executor = agent_executor
        self.workflow_manager = workflow_manager
        self.project_reader = ProjectReader()

    def _ensure_workflow_state(self, state):
        state = dict(state or {})

        state.setdefault("status", "started")

        state.setdefault(
            "developer",
            {
                "status": "pending",
                "commit": None
            }
        )

        state.setdefault(
            "tester",
            {
                "status": "pending",
                "commit": None,
                "result": None
            }
        )

        state.setdefault(
            "reviewer",
            {
                "status": "pending",
                "result": None
            }
        )

        state.setdefault(
            "user_approval",
            {
                "status": "waiting",
                "approved_by": None,
                "approved_at": None,
                "comment": None
            }
        )

        return state

    def _merge_tester_result(
        self,
        state,
        tester_result
    ):
        state = self._ensure_workflow_state(state)
        tester_result = tester_result or {}

        if "tester" in tester_result:
            tester_info = tester_result.get("tester") or {}

            state["tester"] = {
                **state["tester"],
                **tester_info
            }

        else:
            state["tester"] = {
                **state["tester"],
                "status": tester_result.get(
                    "status",
                    state["tester"]["status"]
                ),
                "result": tester_result.get(
                    "result",
                    state["tester"]["result"]
                )
            }

            if tester_result.get("commit"):
                state["tester"]["commit"] = tester_result["commit"]

        return state

    def _merge_reviewer_result(
        self,
        state,
        reviewer_result
    ):
        state = self._ensure_workflow_state(state)
        reviewer_result = reviewer_result or {}

        if "reviewer" in reviewer_result:
            reviewer_info = reviewer_result.get("reviewer") or {}

            state["reviewer"] = {
                **state["reviewer"],
                **reviewer_info
            }

        else:
            state["reviewer"] = {
                **state["reviewer"],
                "status": reviewer_result.get(
                    "status",
                    state["reviewer"]["status"]
                ),
                "result": reviewer_result.get(
                    "result",
                    state["reviewer"]["result"]
                )
            }

        return state

    def run_workflow(
        self,
        project,
        task
    ):
        workflow_manager = self.workflow_manager or WorkflowManager()
        git_manager = GitManager()
        tester_agent = TesterAgent()
        reviewer_agent = ReviewerAgent()

        existing_state = workflow_manager.load()

        if (
            existing_state.get("status") == "approval_waiting"
            and existing_state.get("developer", {}).get("commit")
        ):
            return existing_state

        workflow_manager.create(
            task,
            "dev_branch"
        )

        state = self._ensure_workflow_state(
            workflow_manager.load()
        )

        workflow_manager.save(state)

        self.agent_executor.run(
            AGENT_ROLES["project_manager"],
            task,
            "",
            "project_manager",
            AGENT_CONFIG["project_manager"]["max_tokens"]
        )

        self.agent_executor.run(
            AGENT_ROLES["architect"],
            task,
            "",
            "architect",
            AGENT_CONFIG["architect"]["max_tokens"]
        )

        developer_response = self.agent_executor.run(
            AGENT_ROLES["developer"],
            task,
            "",
            "developer",
            AGENT_CONFIG["developer"]["max_tokens"]
        )

        developer_changes = DeveloperChanges.parse(
            developer_response
        )

        file_applier = DeveloperFileApplier(
            project
        )

        apply_result = file_applier.apply(
            developer_changes
        )

        if not apply_result.get("applied"):
            state = self._ensure_workflow_state(
                workflow_manager.load()
            )

            state["status"] = "development_no_changes"

            workflow_manager.save(state)

            return workflow_manager.load()

        commit_result = git_manager.commit_and_get_hash(
            project,
            "DEV: Development completed"
        )

        if commit_result.get("code") != 0:
            state = self._ensure_workflow_state(
                workflow_manager.load()
            )

            stdout = commit_result.get(
                "stdout",
                ""
            ).lower()

            if (
                "nothing to commit" in stdout
                and "working tree clean" in stdout
            ):
                state["status"] = "development_no_changes"
            else:
                state["status"] = "development_failed"
                state["developer"]["error"] = (
                    commit_result.get("stdout")
                    or commit_result.get("stderr")
                    or ""
                )

            workflow_manager.save(state)

            return state

        workflow_manager.update_agent(
            "developer",
            "completed",
            commit=commit_result["commit"]
        )

        tester_result = tester_agent.test(
            project,
            developer_changes
        )

        state = self._merge_tester_result(
            workflow_manager.load(),
            tester_result
        )

        if (
            state["tester"]["status"] != "completed"
            or state["tester"]["result"] != "PASS"
        ):
            state["status"] = "tester_failed"
            workflow_manager.save(state)
            return state

        workflow_manager.save(state)

        reviewer_result = reviewer_agent.review(
            project,
            state
        )

        state = self._merge_reviewer_result(
            state,
            reviewer_result
        )

        if state["reviewer"]["status"] != "approved":
            state["status"] = "review_failed"
            workflow_manager.save(state)
            return state

        workflow_manager.save(state)

        state["status"] = "approval_waiting"

        state.setdefault(
            "user_approval",
            {
                "status": "waiting",
                "approved_by": None,
                "approved_at": None,
                "comment": None
            }
        )

        state["user_approval"]["status"] = "waiting"

        workflow_manager.save(state)

        return state

    def rework_workflow(self, project):
        workflow_manager = self.workflow_manager or WorkflowManager()
        git_manager = GitManager()
        tester_agent = TesterAgent()
        reviewer_agent = ReviewerAgent()

        state = self._ensure_workflow_state(
            workflow_manager.load()
        )

        workflow_manager.save(state)

        if state.get("user_approval", {}).get("status") != "rejected":
            return state

        task = state.get("task", "")
        comment = (
            state.get("user_approval", {})
            .get("comment")
            or ""
        )

        developer_task = f"""
Ursprüngliche Aufgabe:

{task}

Der Benutzer hat die vorherige Umsetzung abgelehnt.

Begründung des Benutzers:

{comment}

Überarbeite die bestehende Implementierung entsprechend der
Rückmeldung.

Ändere nur die Dateien, die für die Aufgabe notwendig sind.
"""

        developer_response = self.agent_executor.run(
            AGENT_ROLES["developer"],
            developer_task,
            "",
            "developer",
            AGENT_CONFIG["developer"]["max_tokens"]
        )

        developer_changes = DeveloperChanges.parse(
            developer_response
        )

        file_applier = DeveloperFileApplier(
            project
        )

        apply_result = file_applier.apply(
            developer_changes
        )

        if not apply_result.get("applied"):
            state["status"] = "development_no_changes"
            workflow_manager.save(state)
            return workflow_manager.load()

        commit_result = git_manager.commit_and_get_hash(
            project,
            "DEV: Rework completed"
        )

        if commit_result.get("code") != 0:
            state["status"] = "rework_failed"
            state["developer"]["error"] = (
                commit_result.get("stdout")
                or commit_result.get("stderr")
                or ""
            )

            workflow_manager.save(state)

            return state

        workflow_manager.update_agent(
            "developer",
            "completed",
            commit=commit_result["commit"]
        )

        tester_result = tester_agent.test(
            project,
            developer_changes
        )

        state = self._merge_tester_result(
            workflow_manager.load(),
            tester_result
        )

        if (
            state["tester"]["status"] != "completed"
            or state["tester"]["result"] != "PASS"
        ):
            state["status"] = "tester_failed"
            workflow_manager.save(state)
            return state

        workflow_manager.save(state)

        reviewer_result = reviewer_agent.review(
            project,
            state
        )

        state = self._merge_reviewer_result(
            state,
            reviewer_result
        )

        if state["reviewer"]["status"] != "approved":
            state["status"] = "review_failed"
            workflow_manager.save(state)
            return state

        workflow_manager.save(state)

        state["status"] = "approval_waiting"

        state["user_approval"] = {
            "status": "waiting",
            "approved_by": None,
            "approved_at": None,
            "comment": comment
        }

        workflow_manager.save(state)

        return state

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
