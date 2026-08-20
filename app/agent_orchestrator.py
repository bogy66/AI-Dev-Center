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
from app.state_lock import get_state_lock
from app.workflow_execution_guard import try_start, finish


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

    def _save_preserving_approval(
        self,
        workflow_manager,
        state,
        new_approval=None
    ):
        """
        Reloads the current persisted state and writes back only the
        fields the orchestrator itself owns (status, developer, tester,
        reviewer), while preserving whatever user_approval is currently
        persisted.

        This closes the lost-update window where the orchestrator
        holds a stale full-state copy in memory across long-running
        LLM/Git/review calls, and would otherwise overwrite a
        concurrently saved approve()/reject() decision.

        If new_approval is given, the orchestrator is explicitly
        establishing a new approval phase at this point (e.g. reaching
        approval_waiting for a freshly completed commit), and the
        current user_approval is intentionally replaced.

        The critical section (reload + merge + save) is kept short and
        never spans LLM calls or git subprocess calls.
        """
        lock = get_state_lock(workflow_manager.storage)

        with lock:
            current = workflow_manager.load()

            merged = dict(current)

            for key in ("status", "developer", "tester", "reviewer"):
                if key in state:
                    merged[key] = state[key]

            if new_approval is not None:
                merged["user_approval"] = new_approval
            else:
                merged["user_approval"] = current.get(
                    "user_approval",
                    state.get("user_approval")
                )

            workflow_manager.save(merged)

            return merged

    def _existing_files_context(self, project, max_chars=2000):
        """
        Builds a bounded context string listing files that already
        exist in the project, so the developer LLM can distinguish
        between "create" (new file) and "update" (existing file)
        actions during rework.

        Reuses the existing ProjectReader instead of introducing a new
        scanning mechanism. Only file paths are listed (not their
        content) to keep the context small and cheap.
        """
        try:
            project_files = self.project_reader.read_files(project)
        except Exception:
            return ""

        if not project_files:
            return ""

        file_list = "\n".join(sorted(project_files.keys()))

        context = (
            "Bereits vorhandene Dateien im Projekt "
            "(verwende 'update' statt 'create' fuer diese Dateien):\n\n"
            f"{file_list}"
        )

        return context[:max_chars]

    def run_workflow(
        self,
        project,
        task
    ):
        if not try_start(project):
            return {
                "status": "workflow_already_running",
                "project": project,
                "message": (
                    "A workflow run is already in progress for this "
                    "project. Please wait until it completes before "
                    "starting a new one."
                )
            }

        try:
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

            try:
                developer_changes = DeveloperChanges.parse(
                    developer_response
                )
            except ValueError as error:
                state = self._ensure_workflow_state(
                    workflow_manager.load()
                )

                state["status"] = "development_failed"
                state["developer"]["error"] = str(error)

                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )

                return state

            file_applier = DeveloperFileApplier(
                project
            )

            apply_result = file_applier.apply(
                developer_changes
            )

            skipped = apply_result.get("skipped") or []

            if skipped:
                state = self._ensure_workflow_state(
                    workflow_manager.load()
                )

                state["status"] = "development_incomplete"
                state["developer"]["skipped"] = skipped

                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )

                return state

            if not apply_result.get("applied"):
                state = self._ensure_workflow_state(
                    workflow_manager.load()
                )

                state["status"] = "development_no_changes"

                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )

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

                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )

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
                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )
                return state

            state = self._save_preserving_approval(
                workflow_manager,
                state
            )

            reviewer_result = reviewer_agent.review(
                project,
                state
            )

            state = self._merge_reviewer_result(
                workflow_manager.load(),
                reviewer_result
            )

            if state["reviewer"]["status"] != "approved":
                state["status"] = "review_failed"
                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )
                return state

            state = self._save_preserving_approval(
                workflow_manager,
                state
            )

            state["status"] = "approval_waiting"

            new_approval = {
                "status": "waiting",
                "approved_by": None,
                "approved_at": None,
                "comment": None
            }

            state["user_approval"] = new_approval

            state = self._save_preserving_approval(
                workflow_manager,
                state,
                new_approval=new_approval
            )

            return state
        finally:
            finish(project)

    def rework_workflow(self, project):
        if not try_start(project):
            return {
                "status": "workflow_already_running",
                "project": project,
                "message": (
                    "A workflow run is already in progress for this "
                    "project. Please wait until it completes before "
                    "starting a new one."
                )
            }

        try:
            workflow_manager = self.workflow_manager or WorkflowManager()
            git_manager = GitManager()
            tester_agent = TesterAgent()
            reviewer_agent = ReviewerAgent()

            state = self._ensure_workflow_state(
                workflow_manager.load()
            )

            if state.get("user_approval", {}).get("status") != "rejected":
                return state

            workflow_manager.save(state)

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

            existing_files_context = self._existing_files_context(
                project
            )

            developer_response = self.agent_executor.run(
                AGENT_ROLES["developer"],
                developer_task,
                existing_files_context,
                "developer",
                AGENT_CONFIG["developer"]["max_tokens"]
            )

            try:
                developer_changes = DeveloperChanges.parse(
                    developer_response
                )
            except ValueError as error:
                state = self._ensure_workflow_state(
                    workflow_manager.load()
                )

                state["status"] = "rework_failed"
                state["developer"]["error"] = str(error)

                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )

                return state

            file_applier = DeveloperFileApplier(
                project
            )

            apply_result = file_applier.apply(
                developer_changes
            )

            skipped = apply_result.get("skipped") or []

            if skipped:
                state = self._ensure_workflow_state(
                    workflow_manager.load()
                )

                state["status"] = "development_incomplete"
                state["developer"]["skipped"] = skipped

                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )

                return state

            if not apply_result.get("applied"):
                state = self._ensure_workflow_state(
                    workflow_manager.load()
                )

                state["status"] = "development_no_changes"

                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )

                return workflow_manager.load()

            commit_result = git_manager.commit_and_get_hash(
                project,
                "DEV: Rework completed"
            )

            if commit_result.get("code") != 0:
                state = self._ensure_workflow_state(
                    workflow_manager.load()
                )

                state["status"] = "rework_failed"
                state["developer"]["error"] = (
                    commit_result.get("stdout")
                    or commit_result.get("stderr")
                    or ""
                )

                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )

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
                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )
                return state

            state = self._save_preserving_approval(
                workflow_manager,
                state
            )

            reviewer_result = reviewer_agent.review(
                project,
                state
            )

            state = self._merge_reviewer_result(
                workflow_manager.load(),
                reviewer_result
            )

            if state["reviewer"]["status"] != "approved":
                state["status"] = "review_failed"
                state = self._save_preserving_approval(
                    workflow_manager,
                    state
                )
                return state

            state = self._save_preserving_approval(
                workflow_manager,
                state
            )

            state["status"] = "approval_waiting"

            new_approval = {
                "status": "waiting",
                "approved_by": None,
                "approved_at": None,
                "comment": comment
            }

            state["user_approval"] = new_approval

            state = self._save_preserving_approval(
                workflow_manager,
                state,
                new_approval=new_approval
            )

            return state
        finally:
            finish(project)

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
