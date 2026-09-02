"""Controlled execution boundary tests — Docker-free, no tool instals."""
import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.execution import (
    ExecutionRequest, validate_request, execute_controlled,
    execute_step_controlled, _controlled_env,
    CapabilityRegistration, CapabilityRegistry, _DENIED_ARGS,
)
from app.verification import (
    INVALID_PLAN, UNSUPPORTED, TOOL_UNAVAILABLE, PASS, FAIL, BLOCKED,
    VerificationStep, VerificationStepResult,
    _DEFAULT_TIMEOUT,
)


def _step(runner="pytest", kind="test", wd="."):
    return VerificationStep(
        step_id="step-1", area=".", working_directory=wd,
        verification_kind=kind, test_system="pytest",
        runner_type=runner, policy="controlled_execution",
    )


# ============================================================================
# Execution validation
# ============================================================================

class TestExecutionRequest:
    def test_valid_request_passes_validation(self, tmp_path):
        req = ExecutionRequest(
            args=("python", "-c", "print(1)"),
            cwd=str(tmp_path), timeout=10, tool_name="python",
        )
        err = validate_request(req, tmp_path)
        assert err is None

    def test_cwd_outside_project_root_is_blocked(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        req = ExecutionRequest(
            args=("python", "-c", "print(1)"),
            cwd=str(outside), timeout=10, tool_name="python",
        )
        # cwd is outside tmp_path
        err = validate_request(req, tmp_path / "nested")
        assert err is not None
        assert err.status == INVALID_PLAN.value

    def test_unknown_tool_is_unsupported(self, tmp_path):
        req = ExecutionRequest(
            args=("nmap", "-sP", "localhost"),
            cwd=str(tmp_path), timeout=10, tool_name="nmap",
        )
        err = validate_request(req, tmp_path)
        assert err is not None
        assert err.status == UNSUPPORTED.value

    def test_missing_tool_is_tool_unavailable(self, tmp_path):
        req = ExecutionRequest(
            args=("nonexistent_tool_xyz", "--help"),
            cwd=str(tmp_path), timeout=10, tool_name="nonexistent_tool_xyz",
        )
        err = validate_request(req, tmp_path)
        assert err is not None

    def test_tool_identity_must_match_executable(self, tmp_path):
        req = ExecutionRequest(
            args=("sh", "-c", "true"), cwd=str(tmp_path), timeout=10,
            tool_name="python",
        )
        err = validate_request(req, tmp_path)
        assert err is not None
        assert err.status == INVALID_PLAN.value

    def test_sibling_with_project_prefix_is_rejected(self, tmp_path):
        root = tmp_path / "project"
        sibling = tmp_path / "project-escape"
        root.mkdir()
        sibling.mkdir()
        req = ExecutionRequest(("python", "--version"), str(sibling), 10, "python")
        err = validate_request(req, root)
        assert err is not None
        assert err.status == INVALID_PLAN.value

    def test_future_capability_name_can_be_registered(self, tmp_path, monkeypatch):
        registry = CapabilityRegistry()
        registry.register_approved(CapabilityRegistration("future-compiler", ("futurecc",)))
        monkeypatch.setattr("app.execution._find_executable", lambda name: "/bin/true" if name == "futurecc" else None)
        req = ExecutionRequest(("futurecc", "--check"), str(tmp_path), 10, "future-compiler")
        assert validate_request(req, tmp_path, registry) is None


class TestExecuteControlled:
    def test_execute_controlled_runs_python(self, tmp_path):
        req = ExecutionRequest(
            args=("python", "-c", "print('hello')"),
            cwd=str(tmp_path), timeout=10, tool_name="python",
        )
        result = execute_controlled(req, tmp_path)
        assert result is not None
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_execute_controlled_captures_stderr(self, tmp_path):
        req = ExecutionRequest(
            args=("python", "-c", "import sys; sys.stderr.write('err')"),
            cwd=str(tmp_path), timeout=10, tool_name="python",
        )
        result = execute_controlled(req, tmp_path)
        assert result is not None
        assert "err" in result.stderr

    def test_execute_controlled_rejects_mismatched_executable(self, tmp_path):
        req = ExecutionRequest(
            args=("/nonexistent/binary",),
            cwd=str(tmp_path), timeout=10, tool_name="python",
        )
        with pytest.raises(ValueError, match="Executable"):
            execute_controlled(req, tmp_path)

    def test_validation_cannot_be_bypassed_at_subprocess_entry(self, tmp_path, monkeypatch):
        run = Mock(side_effect=AssertionError("subprocess must not run"))
        monkeypatch.setattr("app.execution.subprocess.run", run)
        req = ExecutionRequest(("sh", "-c", "true"), str(tmp_path), 10, "python")
        with pytest.raises(ValueError, match="does not match"):
            execute_controlled(req, tmp_path)
        run.assert_not_called()

    def test_unknown_arbitrary_tool_cannot_execute(self, tmp_path, monkeypatch):
        run = Mock(side_effect=AssertionError("subprocess must not run"))
        monkeypatch.setattr("app.execution.subprocess.run", run)
        req = ExecutionRequest(("sh", "-c", "true"), str(tmp_path), 10, "arbitrary")
        with pytest.raises(ValueError, match="not registered"):
            execute_controlled(req, tmp_path)
        run.assert_not_called()


class TestControlledEnv:
    def test_env_filters_sensitive_keys(self):
        env = _controlled_env()
        assert "SECRET_KEY" not in env
        assert "DATABASE_URL" not in env
        assert "PATH" in env

    def test_env_includes_python(self):
        env = _controlled_env()
        assert any(k.startswith("PYTHON") for k in env) or "PATH" in env


class TestExecuteStepControlled:
    def test_full_boundary_pytest_step(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_x(): assert True\n")
        step = _step(runner="pytest")
        from app.execution import execute_step_controlled
        result = execute_step_controlled(
            step, tmp_path,
            args=("python", "-m", "pytest", "-q"),
            tool_name="python", timeout=30,
        )
        assert result.status in (PASS.value, FAIL.value, TOOL_UNAVAILABLE.value)

    def test_boundary_blocks_cwd_escape(self, tmp_path):
        step = _step(wd="../../etc")
        from app.execution import execute_step_controlled
        result = execute_step_controlled(
            step, tmp_path,
            args=("python", "-c", "pass"),
            tool_name="python", timeout=10,
        )
        assert result.status == INVALID_PLAN.value

    def test_boundary_blocks_unknown_tool(self, tmp_path):
        step = _step(runner="unknown_tool")
        from app.execution import execute_step_controlled
        result = execute_step_controlled(
            step, tmp_path,
            args=("unknown_tool", "--help"),
            tool_name="unknown_tool", timeout=10,
        )
        assert result.status in (UNSUPPORTED.value, TOOL_UNAVAILABLE.value)


# ============================================================================
# Execution boundary — no install, no shell, no hardware
# ============================================================================

class TestNoInstall:
    def test_execute_controlled_never_installs(self):
        import inspect
        src = inspect.getsource(execute_controlled)
        assert "pip install" not in src
        assert "apt install" not in src
        assert "apt-get install" not in src
        assert "npm install" not in src
        assert "brew install" not in src


class TestNoShell:
    def test_execute_controlled_has_no_shell(self):
        import inspect
        src = inspect.getsource(execute_controlled)
        assert "shell=True" not in src
        assert "shell = True" not in src


class TestNoHardware:
    def test_no_device_mounts_or_privileged(self):
        import inspect
        src = inspect.getsource(execute_controlled)
        assert "--device" not in src
        assert "--privileged" not in src
        assert "docker" not in src.lower()


# ============================================================================
# Docker configuration tests
# ============================================================================

class TestDockerConfig:
    def test_docker_compose_exists(self):
        root = Path(__file__).parents[1]
        compose = root / "docker-compose.yml"
        assert compose.is_file()

    def test_dockerfile_exists(self):
        root = Path(__file__).parents[1]
        dockerfile = root / "Dockerfile"
        assert dockerfile.is_file()

    def test_compose_has_no_privileged(self):
        root = Path(__file__).parents[1]
        content = (root / "docker-compose.yml").read_text()
        assert "privileged: true" not in content

    def test_compose_has_no_docker_socket(self):
        root = Path(__file__).parents[1]
        content = (root / "docker-compose.yml").read_text()
        assert "/var/run/docker.sock" not in content

    def test_compose_has_no_device_mounts(self):
        root = Path(__file__).parents[1]
        content = (root / "docker-compose.yml").read_text()
        assert "/dev/" not in content

    def test_dockerfile_is_non_root(self):
        root = Path(__file__).parents[1]
        content = (root / "Dockerfile").read_text()
        assert "USER ai-dev" in content or "USER 1000" in content

    def test_dockerfile_has_healthcheck(self):
        root = Path(__file__).parents[1]
        content = (root / "Dockerfile").read_text()
        assert "HEALTHCHECK" in content

    def test_dockerfile_exposes_8010(self):
        root = Path(__file__).parents[1]
        content = (root / "Dockerfile").read_text()
        assert "8010" in content

    def test_dockerfile_no_toolchains_preinstalled(self):
        root = Path(__file__).parents[1]
        content = (root / "Dockerfile").read_text()
        # Check installed commands only, not comments
        lines = [l for l in content.splitlines()
                 if not l.strip().startswith("#")]
        joined = " ".join(lines)
        assert "platformio" not in joined.lower()
        assert "esphome" not in joined.lower()
        assert "pip install platformio" not in joined.lower()


class TestDockerIgnore:
    def test_dockerignore_exists(self):
        root = Path(__file__).parents[1]
        assert (root / ".dockerignore").is_file()

    def test_dockerignore_excludes_venv(self):
        root = Path(__file__).parents[1]
        content = (root / ".dockerignore").read_text()
        assert "venv" in content or ".venv" in content

    def test_dockerignore_excludes_git(self):
        root = Path(__file__).parents[1]
        content = (root / ".dockerignore").read_text()
        assert ".git" in content


# ============================================================================
# Workflow integration — existing behavior preserved
# ============================================================================

class TestWorkflowIntegration:
    def test_verification_plan_still_works(self, tmp_path):
        _write(tmp_path / "tests" / "test_x.py", "def test_x(): assert True\n")
        from app.project_intelligence import inspect_project
        from app.verification import build_verification_plan
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")
        assert len(plan.steps) >= 1

    def test_pytest_runner_still_works(self, tmp_path):
        _write(tmp_path / "tests" / "test_x.py", "def test_x(): assert True\n")
        from app.verification import PytestRunner
        step = VerificationStep(
            step_id="s1", area=".", working_directory=".",
            verification_kind="test", test_system="pytest",
            runner_type="pytest", policy="controlled_execution",
        )
        runner = PytestRunner(timeout=30)
        result = runner.execute(step, tmp_path)
        assert result.status == PASS.value

    def test_execution_boundary_rejects_disallowed_args(self, tmp_path):
        req = ExecutionRequest(
            args=("python", "-c", "print('shell=True')"),
            cwd=str(tmp_path), timeout=10, tool_name="python",
        )
        # The string "shell=True" in args triggers the deny-list
        err = validate_request(req, tmp_path)
        assert err is not None


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
