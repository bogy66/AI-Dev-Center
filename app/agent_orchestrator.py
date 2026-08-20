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
from app.requirements_manager import RequirementsManager
from app.workspace_manager import WorkspaceManager
from app.test_bench import TestBench


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

            # Parse requirements from task
            requirements = RequirementsManager.parse_requirements_from_task(task)
            
            # Create initial state with requirements
            workflow_manager.create(
                task,
                "dev_branch"
            )

            state = self._ensure_workflow_state(
                workflow_manager.load()
            )
            
            # Add requirements to state
            state["requirements"] = requirements

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

            # Create workspaces for parallel execution
            workflow_id = "workflow_" + str(id(state))
            workspace_manager = WorkspaceManager(project)
            
            developer_workspace = workspace_manager.create_developer_workspace(workflow_id)
            tester_workspace = workspace_manager.create_tester_workspace(workflow_id)

            # Developer and Tester run in parallel
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            developer_result = None
            tester_result = None
            developer_error = None
            tester_error = None
            
            def run_developer():
                nonlocal developer_result, developer_error
                
                try:
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
                        developer_workspace["path"]
                    )

                    apply_result = file_applier.apply(
                        developer_changes
                    )

                    if apply_result.get("skipped"):
                        return {
                            "status": "developer_incomplete",
                            "skipped": apply_result.get("skipped")
                        }

                    if not apply_result.get("applied"):
                        return {
                            "status": "developer_no_changes"
                        }

                    commit_result = git_manager.commit_and_get_hash(
                        developer_workspace["path"],
                        "DEV: Development completed"
                    )

                    if commit_result.get("code") != 0:
                        stdout = commit_result.get("stdout", "").lower()
                        if "nothing to commit" in stdout and "working tree clean" in stdout:
                            return {"status": "developer_no_changes"}
                        else:
                            return {
                                "status": "developer_failed",
                                "error": commit_result.get("stdout") or commit_result.get("stderr") or ""
                            }

                    return {
                        "status": "developer_completed",
                        "commit": commit_result["commit"]
                    }
                    
                except Exception as error:
                    return {
                        "status": "developer_failed",
                        "error": str(error)
                    }

            def run_tester():
                nonlocal tester_result, tester_error
                
                try:
                    # Generate tests based on requirements
                    test_response = self.agent_executor.run(
                        AGENT_ROLES["tester"],
                        task,
                        "",
                        "tester",
                        AGENT_CONFIG["tester"]["max_tokens"]
                    )

                    # Parse test changes
                    test_changes = DeveloperChanges.parse(test_response)

                    file_applier = DeveloperFileApplier(
                        tester_workspace["path"]
                    )

                    apply_result = file_applier.apply(
                        test_changes
                    )

                    if apply_result.get("skipped"):
                        return {
                            "status": "tester_incomplete",
                            "skipped": apply_result.get("skipped")
                        }

                    if not apply_result.get("applied"):
                        return {
                            "status": "tester_no_changes"
                        }

                    commit_result = git_manager.commit_and_get_hash(
                        tester_workspace["path"],
                        "TEST: Added tests"
                    )

                    if commit_result.get("code") != 0:
                        stdout = commit_result.get("stdout", "").lower()
                        if "nothing to commit" in stdout and "working tree clean" in stdout:
                            return {"status": "tester_no_changes"}
                        else:
                            return {
                                "status": "tester_failed",
                                "error": commit_result.get("stdout") or commit_result.get("stderr") or ""
                            }

                    return {
                        "status": "tester_completed",
                        "commit": commit_result["commit"]
                    }
                    
                except Exception as error:
                    return {
                        "status": "tester_failed",
                        "error": str(error)
                    }

            # Run Developer and Tester in parallel
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(run_developer): "developer",
                    executor.submit(run_tester): "tester"
                }
                
                for future in as_completed(futures):
                    role = futures[future]
                    try:
                        result = future.result()
                        if role == "developer":
                            developer_result = result
                        else:
                            tester_result = result
                    except Exception as error:
                        if role == "developer":
                            developer_error = str(error)
                        else:
                            tester_error = str(error)

            # Check for failures
            if developer_result and developer_result.get("status") == "developer_incomplete":
                state = self._ensure_workflow_state(workflow_manager.load())
                state["status"] = "development_incomplete"
                state["developer"]["skipped"] = developer_result.get("skipped")
                state = self._save_preserving_approval(workflow_manager, state)
                workspace_manager.cleanup_workspace(workflow_id)
                return state

            if developer_result and developer_result.get("status") in ("developer_failed", "developer_no_changes"):
                state = self._ensure_workflow_state(workflow_manager.load())
                state["status"] = "development_failed"
                state["developer"]["error"] = developer_result.get("error") or "Developer failed"
                state = self._save_preserving_approval(workflow_manager, state)
                workspace_manager.cleanup_workspace(workflow_id)
                return state

            if tester_result and tester_result.get("status") in ("tester_failed", "tester_incomplete", "tester_no_changes"):
                state = self._ensure_workflow_state(workflow_manager.load())
                state["status"] = "tester_failed"
                state["tester"]["error"] = tester_result.get("error") or "Tester failed"
                state = self._save_preserving_approval(workflow_manager, state)
                workspace_manager.cleanup_workspace(workflow_id)
                return state

            # Both Developer and Tester completed successfully
            if developer_result and developer_result.get("status") == "developer_completed" and \
               tester_result and tester_result.get("status") == "tester_completed":
                
                # Setup testbench
                test_bench = TestBench(project)
                testbench_path = test_bench.setup_testbench(
                    developer_result["commit"],
                    tester_result["commit"]
                )
                
                # Merge commits
                if not test_bench.merge_commits(
                    testbench_path,
                    developer_result["commit"],
                    tester_result["commit"]
                ):
                    state = self._ensure_workflow_state(workflow_manager.load())
                    state["status"] = "testbench_failed"
                    state["testbench"] = {"error": "Failed to merge commits"}
                    state = self._save_preserving_approval(workflow_manager, state)
                    test_bench.cleanup_testbench()
                    workspace_manager.cleanup_workspace(workflow_id)
                    return state
                
                # Run tests
                test_result = test_bench.run_tests(testbench_path)
                
                if test_result["success"]:
                    # Testbench passed - proceed to Reviewer
                    state = self._ensure_workflow_state(workflow_manager.load())
                    state["status"] = "testbench_passed"
                    state["developer"]["status"] = "completed"
                    state["developer"]["commit"] = developer_result["commit"]
                    state["tester"]["status"] = "completed"
                    state["tester"]["commit"] = tester_result["commit"]
                    state = self._save_preserving_approval(workflow_manager, state)
                    
                    # Cleanup
                    test_bench.cleanup_testbench()
                    workspace_manager.cleanup_workspace(workflow_id)
                    
                    # Continue to Reviewer
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
                else:
                    # Testbench failed
                    state = self._ensure_workflow_state(workflow_manager.load())
                    state["status"] = "testbench_failed"

                    state["tester"]["status"] = "failed"
                    state["tester"]["result"] = test_result.get("output", "")

                    state["testbench"] = {
                        "errors": test_result.get("errors", []),
                        "output": test_result.get("output", "")
                    }

                    state = self._save_preserving_approval(
                        workflow_manager,
                        state
                    )
                    test_bench.cleanup_testbench()
                    workspace_manager.cleanup_workspace(workflow_id)
                    return state
            else:
                # Unexpected state
                state = self._ensure_workflow_state(workflow_manager.load())
                state["status"] = "development_failed"
                state["developer"]["error"] = "Unexpected workflow state"
                state = self._save_preserving_approval(workflow_manager, state)
                workspace_manager.cleanup_workspace(workflow_id)
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

            task = state.get("task", "")
            comment = (
                state.get("user_approval", {})
                .get("comment")
                or ""
            )

            # Create workspaces for parallel execution
            workflow_id = "workflow_" + str(id(state))
            workspace_manager = WorkspaceManager(project)
            
            developer_workspace = workspace_manager.create_developer_workspace(workflow_id)
            tester_workspace = workspace_manager.create_tester_workspace(workflow_id)

            # Developer and Tester run in parallel
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            developer_result = None
            tester_result = None
            developer_error = None
            tester_error = None
            
            def run_developer():
                nonlocal developer_result, developer_error
                
                try:
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

                    developer_changes = DeveloperChanges.parse(
                        developer_response
                    )

                    file_applier = DeveloperFileApplier(
                        developer_workspace["path"]
                    )

                    apply_result = file_applier.apply(
                        developer_changes
                    )

                    if apply_result.get("skipped"):
                        return {
                            "status": "developer_incomplete",
                            "skipped": apply_result.get("skipped")
                        }

                    if not apply_result.get("applied"):
                        return {
                            "status": "developer_no_changes"
                        }

                    commit_result = git_manager.commit_and_get_hash(
                        developer_workspace["path"],
                        "DEV: Rework completed"
                    )

                    if commit_result.get("code") != 0:
                        stdout = commit_result.get("stdout", "").lower()
                        if "nothing to commit" in stdout and "working tree clean" in stdout:
                            return {"status": "developer_no_changes"}
                        else:
                            return {
                                "status": "developer_failed",
                                "error": commit_result.get("stdout") or commit_result.get("stderr") or ""
                            }

                    return {
                        "status": "developer_completed",
                        "commit": commit_result["commit"]
                    }
                    
                except Exception as error:
                    return {
                        "status": "developer_failed",
                        "error": str(error)
                    }

            def run_tester():
                nonlocal tester_result, tester_error
                
                try:
                    # Generate tests based on requirements
                    test_response = self.agent_executor.run(
                        AGENT_ROLES["tester"],
                        task,
                        "",
                        "tester",
                        AGENT_CONFIG["tester"]["max_tokens"]
                    )

                    # Parse test changes
                    test_changes = DeveloperChanges.parse(test_response)

                    file_applier = DeveloperFileApplier(
                        tester_workspace["path"]
                    )

                    apply_result = file_applier.apply(
                        test_changes
                    )

                    if apply_result.get("skipped"):
                        return {
                            "status": "tester_incomplete",
                            "skipped": apply_result.get("skipped")
                        }

                    if not apply_result.get("applied"):
                        return {
                            "status": "tester_no_changes"
                        }

                    commit_result = git_manager.commit_and_get_hash(
                        tester_workspace["path"],
                        "TEST: Added tests"
                    )

                    if commit_result.get("code") != 0:
                        stdout = commit_result.get("stdout", "").lower()
                        if "nothing to commit" in stdout and "working tree clean" in stdout:
                            return {"status": "tester_no_changes"}
                        else:
                            return {
                                "status": "tester_failed",
                                "error": commit_result.get("stdout") or commit_result.get("stderr") or ""
                            }

                    return {
                        "status": "tester_completed",
                        "commit": commit_result["commit"]
                    }
                    
                except Exception as error:
                    return {
                        "status": "tester_failed",
                        "error": str(error)
                    }

            # Run Developer and Tester in parallel
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(run_developer): "developer",
                    executor.submit(run_tester): "tester"
                }
                
                for future in as_completed(futures):
                    role = futures[future]
                    try:
                        result = future.result()
                        if role == "developer":
                            developer_result = result
                        else:
                            tester_result = result
                    except Exception as error:
                        if role == "developer":
                            developer_error = str(error)
                        else:
                            tester_error = str(error)

            # Check for failures
            if developer_result and developer_result.get("status") == "developer_incomplete":
                state = self._ensure_workflow_state(workflow_manager.load())
                state["status"] = "development_incomplete"
                state["developer"]["skipped"] = developer_result.get("skipped")
                state = self._save_preserving_approval(workflow_manager, state)
                workspace_manager.cleanup_workspace(workflow_id)
                return state

            if developer_result and developer_result.get("status") in ("developer_failed", "developer_no_changes"):
                state = self._ensure_workflow_state(workflow_manager.load())
                state["status"] = "rework_failed"
                state["developer"]["error"] = developer_result.get("error") or "Developer failed"
                state = self._save_preserving_approval(workflow_manager, state)
                workspace_manager.cleanup_workspace(workflow_id)
                return state

            if tester_result and tester_result.get("status") in ("tester_failed", "tester_incomplete", "tester_no_changes"):
                state = self._ensure_workflow_state(workflow_manager.load())
                state["status"] = "tester_failed"
                state["tester"]["error"] = tester_result.get("error") or "Tester failed"
                state = self._save_preserving_approval(workflow_manager, state)
                workspace_manager.cleanup_workspace(workflow_id)
                return state

            # Both Developer and Tester completed successfully
            if developer_result and developer_result.get("status") == "developer_completed" and \
               tester_result and tester_result.get("status") == "tester_completed":
                
                # Setup testbench
                test_bench = TestBench(project)
                testbench_path = test_bench.setup_testbench(
                    developer_result["commit"],
                    tester_result["commit"]
                )
                
                # Merge commits
                if not test_bench.merge_commits(
                    testbench_path,
                    developer_result["commit"],
                    tester_result["commit"]
                ):
                    state = self._ensure_workflow_state(workflow_manager.load())
                    state["status"] = "testbench_failed"
                    state["testbench"] = {"error": "Failed to merge commits"}
                    state = self._save_preserving_approval(workflow_manager, state)
                    test_bench.cleanup_testbench()
                    workspace_manager.cleanup_workspace(workflow_id)
                    return state
                
                # Run tests
                test_result = test_bench.run_tests(testbench_path)
                
                if test_result["success"]:
                    # Testbench passed - proceed to Reviewer
                    state = self._ensure_workflow_state(workflow_manager.load())
                    state["status"] = "testbench_passed"
                    state["developer"]["status"] = "completed"
                    state["developer"]["commit"] = developer_result["commit"]
                    state["tester"]["status"] = "completed"
                    state["tester"]["commit"] = tester_result["commit"]
                    state = self._save_preserving_approval(workflow_manager, state)
                    
                    # Cleanup
                    test_bench.cleanup_testbench()
                    workspace_manager.cleanup_workspace(workflow_id)
                    
                    # Continue to Reviewer
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
                else:
                    # Testbench failed
                    state = self._ensure_workflow_state(workflow_manager.load())
                    state["status"] = "testbench_failed"
                    state["testbench"] = {
                        "errors": test_result["errors"],
                        "output": test_result["output"]
                    }
                    state = self._save_preserving_approval(workflow_manager, state)
                    test_bench.cleanup_testbench()
                    workspace_manager.cleanup_workspace(workflow_id)
                    return state
            else:
                # Unexpected state
                state = self._ensure_workflow_state(workflow_manager.load())
                state["status"] = "rework_failed"
                state["developer"]["error"] = "Unexpected workflow state"
                state = self._save_preserving_approval(workflow_manager, state)
                workspace_manager.cleanup_workspace(workflow_id)
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
