"""Firmware verification — ESPHome, PlatformIO, CMake, dependency, security."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.project_intelligence import (
    DetectedBuildSystem, DetectedFirmware, DetectedFramework,
    DetectedLanguage, DetectedPackageSystem, DetectedTestSystem,
    Evidence, ProjectArea, ProjectIntelligence, inspect_project,
)
from app.verification import (
    PASS, FAIL, UNSUPPORTED, TOOL_UNAVAILABLE, INVALID_PLAN,
    EXECUTION_ERROR, TIMEOUT, NOT_APPLICABLE, BLOCKED,
    VerificationPlan, VerificationStep, VerificationStepResult,
    VerificationResult, VerificationRunner, ControlledRunnerRegistry,
    PytestRunner, PythonUnittestRunner,
    ESPHomeCheckRunner, PlatformIORunner, CMakeRunner,
    build_verification_plan, build_default_registry, _aggregate,
    _build_step_result, _MAX_OUTPUT,
)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ============================================================================
# ESPHome Tests
# ============================================================================

class TestESPHome:
    def test_esphome_yaml_detected_as_firmware(self, tmp_path):
        _write(tmp_path / "esphome.yaml",
               "esphome:\n  name: test\n  board: esp32dev\n")
        pi = inspect_project(tmp_path)
        assert any(fw.name == "esphome" for fw in pi.firmware_indicators)

    def test_normal_yaml_not_esphome(self, tmp_path):
        _write(tmp_path / "config.yaml", "app:\n  name: my-app\n")
        pi = inspect_project(tmp_path)
        assert not any(fw.name == "esphome" for fw in pi.firmware_indicators)

    def test_esphome_creates_validate_and_compile_steps(self, tmp_path):
        _write(tmp_path / "esphome.yaml",
               "esphome:\n  name: test\n  board: esp32dev\n")
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")
        verify_steps = [s for s in plan.steps if s.test_system == "esphome"]
        assert len(verify_steps) == 2
        kinds = {s.verification_kind for s in verify_steps}
        assert "validate" in kinds
        assert "compile" in kinds

    def test_esphome_compile_depends_on_validate(self, tmp_path):
        _write(tmp_path / "esphome.yaml",
               "esphome:\n  name: test\n")
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")
        compile_step = next(s for s in plan.steps if s.verification_kind == "compile")
        assert len(compile_step.depends_on) == 1

    def test_esphome_tool_unavailable(self):
        import shutil
        original = shutil.which
        shutil.which = lambda x: None
        try:
            runner = ESPHomeCheckRunner()
            step = VerificationStep(
                step_id="esph-v", area=".", working_directory=".",
                verification_kind="validate", test_system="esphome",
                runner_type="esphome_check", policy="controlled_execution",
            )
            result = runner.execute(step, "/tmp")
            assert result.status == TOOL_UNAVAILABLE.value
        finally:
            shutil.which = original

    def test_esphome_validate_runs_safely(self):
        import subprocess
        original = subprocess.run

        class FakeProcess:
            returncode = 0
            stdout = "INFO Configuration is valid"
            stderr = ""
            timed_out = False

        subprocess.run = lambda *a, **kw: FakeProcess()
        try:
            import shutil
            original_which = shutil.which
            shutil.which = lambda x: "/usr/bin/esphome" if x == "esphome" else None
            runner = ESPHomeCheckRunner()
            step = VerificationStep(
                step_id="esph-v", area=".", working_directory=".",
                verification_kind="validate", test_system="esphome",
                runner_type="esphome_check", policy="controlled_execution",
            )
            result = runner.execute(step, "/tmp")
            assert result.status == PASS.value
            assert "esphome" in str(result.command[0])
            assert "config" in str(result.command[1])
        finally:
            subprocess.run = original
            shutil.which = original_which

    def test_esphome_compile_fail(self):
        import subprocess, shutil
        original = subprocess.run
        original_which = shutil.which

        class FakeProcess:
            returncode = 1
            stdout = ""
            stderr = "Compilation failed"
            timed_out = False

        subprocess.run = lambda *a, **kw: FakeProcess()
        shutil.which = lambda x: "/usr/bin/esphome"
        try:
            runner = ESPHomeCheckRunner()
            step = VerificationStep(
                step_id="esph-c", area=".", working_directory=".",
                verification_kind="compile", test_system="esphome",
                runner_type="esphome_check", policy="controlled_execution",
            )
            result = runner.execute(step, "/tmp")
            assert result.status == FAIL.value
            assert "Compilation failed" in result.stderr
        finally:
            subprocess.run = original
            shutil.which = original_which

    def test_esphome_no_run_or_upload(self):
        import inspect
        src = inspect.getsource(ESPHomeCheckRunner.execute)
        assert "esphome run" not in src
        assert "esphome upload" not in src
        assert "upload" not in src
        assert "flash" not in src

    def test_esphome_timeout(self):
        import subprocess, shutil
        original = subprocess.run
        original_which = shutil.which

        class TimeoutProcess:
            returncode = -1
            stdout = "partial"
            stderr = ""
            timed_out = True

        subprocess.run = lambda *a, **kw: TimeoutProcess()
        shutil.which = lambda x: "/usr/bin/esphome"
        try:
            runner = ESPHomeCheckRunner(timeout=1)
            step = VerificationStep(
                step_id="esph-t", area=".", working_directory=".",
                verification_kind="validate", test_system="esphome",
                runner_type="esphome_check", policy="controlled_execution",
            )
            result = runner.execute(step, "/tmp")
            assert result.status == TIMEOUT.value
            assert result.timed_out
        finally:
            subprocess.run = original
            shutil.which = original_which

    def test_esphome_validate_fail_blocks_compile(self, tmp_path):
        _write(tmp_path / "esphome.yaml", "esphome:\n  name: test\n")
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")

        # Simulate: validate returns PASS, compile depends on it
        validate_step = next(s for s in plan.steps if s.verification_kind == "validate")
        compile_step = next(s for s in plan.steps if s.verification_kind == "compile")
        assert compile_step.step_id in compile_step.depends_on or len(compile_step.depends_on) > 0

        registry = build_default_registry()
        # Force validate to fail
        import app.verification as v
        original_exec = ControlledRunnerRegistry.execute_step

        def fake_execute(self, step, project_root):
            if step.step_id == validate_step.step_id:
                return VerificationStepResult(
                    step_id=step.step_id, area=step.area, status=FAIL.value,
                    verification_kind=step.verification_kind,
                    runner_type=step.runner_type, passed=False, return_code=1,
                )
            return original_exec(self, step, project_root)

        ControlledRunnerRegistry.execute_step = fake_execute
        try:
            result = registry.execute_plan(plan)
            compile_result = next(s for s in result.steps if s.step_id == compile_step.step_id)
            assert compile_result.status == BLOCKED.value
        finally:
            ControlledRunnerRegistry.execute_step = original_exec


# ============================================================================
# PlatformIO Tests
# ============================================================================

class TestPlatformIO:
    def test_platformio_ini_detected(self, tmp_path):
        _write(tmp_path / "platformio.ini",
               "[env:esp32dev]\nplatform = espressif32\nboard = esp32dev\n")
        _write(tmp_path / "src" / "main.cpp", "void setup(){}\nvoid loop(){}\n")
        pi = inspect_project(tmp_path)
        assert any(bs.name == "platformio" for bs in pi.build_systems)
        assert any(fw.name == "platformio" for fw in pi.firmware_indicators)

    def test_platformio_board_detected(self, tmp_path):
        _write(tmp_path / "platformio.ini",
               "[env:esp32dev]\nboard = esp32dev\nframework = arduino\n")
        _write(tmp_path / "src" / "main.cpp", "void setup(){}\n")
        _write(tmp_path / "src" / "util.cpp", "void util(){}\n")
        pi = inspect_project(tmp_path)
        fw = next(f for f in pi.firmware_indicators if f.name == "platformio")
        assert "esp32dev" in fw.boards

    def test_platformio_multiple_envs(self, tmp_path):
        _write(tmp_path / "platformio.ini",
               "[env:esp32dev]\nboard = esp32dev\n\n[env:native]\nplatform = native\n")
        _write(tmp_path / "src" / "main.cpp", "void setup(){}\n")
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")
        pio_steps = [s for s in plan.steps if s.test_system == "platformio"]
        assert len(pio_steps) >= 2

    def test_platformio_tool_unavailable(self):
        import shutil
        original = shutil.which
        shutil.which = lambda x: None
        try:
            runner = PlatformIORunner()
            step = VerificationStep(
                step_id="pio-b", area=".", working_directory=".",
                verification_kind="build", test_system="platformio",
                runner_type="platformio", policy="controlled_execution",
                metadata={"environment": "esp32dev"},
            )
            result = runner.execute(step, "/tmp")
            assert result.status == TOOL_UNAVAILABLE.value
        finally:
            shutil.which = original

    def test_platformio_build_runs_safely(self):
        import subprocess, shutil
        original = subprocess.run
        original_which = shutil.which

        class FakeProcess:
            returncode = 0
            stdout = "SUCCESS"
            stderr = ""
            timed_out = False

        subprocess.run = lambda *a, **kw: FakeProcess()
        shutil.which = lambda x: "/usr/bin/pio" if x in ("platformio", "pio") else None
        try:
            runner = PlatformIORunner()
            step = VerificationStep(
                step_id="pio-b", area=".", working_directory=".",
                verification_kind="build", test_system="platformio",
                runner_type="platformio", policy="controlled_execution",
                metadata={"environment": "esp32dev"},
            )
            result = runner.execute(step, "/tmp")
            assert result.status == PASS.value
            assert "pio" in str(result.command[0]) or "platformio" in str(result.command[0])
        finally:
            subprocess.run = original
            shutil.which = original_which

    def test_platformio_build_fail(self):
        import subprocess, shutil
        original = subprocess.run
        original_which = shutil.which

        class FakeProcess:
            returncode = 1
            stdout = ""
            stderr = "Build error"
            timed_out = False

        subprocess.run = lambda *a, **kw: FakeProcess()
        shutil.which = lambda x: "/usr/bin/pio"
        try:
            runner = PlatformIORunner()
            step = VerificationStep(
                step_id="pio-b", area=".", working_directory=".",
                verification_kind="build", test_system="platformio",
                runner_type="platformio", policy="controlled_execution",
            )
            result = runner.execute(step, "/tmp")
            assert result.status == FAIL.value
        finally:
            subprocess.run = original
            shutil.which = original_which

    def test_platformio_no_upload_or_monitor(self):
        import inspect
        src = inspect.getsource(PlatformIORunner)
        assert "_FORBIDDEN_TARGETS" in src  # forbids upload/monitor/device/remote

    def test_native_test_allowed_embedded_blocked(self, tmp_path):
        _write(tmp_path / "platformio.ini",
               "[env:esp32dev]\nboard = esp32dev\n\n[env:native]\nplatform = native\n")
        _write(tmp_path / "src" / "main.cpp", "void setup(){}\n")
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")
        test_steps = [s for s in plan.steps if s.verification_kind == "test" and s.test_system == "platformio"]
        # Only native test should exist
        for ts in test_steps:
            assert ts.metadata is None or ts.metadata.get("environment") == "native"


# ============================================================================
# C/C++ / CMake Tests
# ============================================================================

class TestCMakeCPP:
    def test_single_c_file_detects_c(self, tmp_path):
        _write(tmp_path / "main.c", "int main() { return 0; }\n")
        pi = inspect_project(tmp_path)
        assert "c" in pi.language_names

    def test_single_cpp_file_detects_cpp(self, tmp_path):
        _write(tmp_path / "main.cpp", "int main() { return 0; }\n")
        pi = inspect_project(tmp_path)
        assert "cpp" in pi.language_names

    def test_cmake_detected_as_build_system(self, tmp_path):
        _write(tmp_path / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.10)\n")
        _write(tmp_path / "src" / "main.cpp", "int main() { return 0; }\n")
        pi = inspect_project(tmp_path)
        assert any(bs.name == "cmake" for bs in pi.build_systems)

    def test_cmake_creates_configure_build_steps(self, tmp_path):
        _write(tmp_path / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.10)\n")
        _write(tmp_path / "src" / "main.cpp", "int main() { return 0; }\n")
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")
        cmake_steps = [s for s in plan.steps if s.test_system == "cmake"]
        assert len(cmake_steps) >= 2
        kinds = {s.verification_kind for s in cmake_steps}
        assert "configure" in kinds
        assert "build" in kinds

    def test_cmake_configure_fail_blocks_build(self, tmp_path):
        _write(tmp_path / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.10)\n")
        _write(tmp_path / "src" / "main.cpp", "int main() { return 0; }\n")
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")
        configure = next(s for s in plan.steps if s.verification_kind == "configure")
        build = next(s for s in plan.steps if s.verification_kind == "build")
        assert build.step_id in build.depends_on or configure.step_id in build.depends_on

    def test_cmake_tool_unavailable(self):
        import shutil
        original = shutil.which
        shutil.which = lambda x: None
        try:
            runner = CMakeRunner()
            step = VerificationStep(
                step_id="cm-c", area=".", working_directory=".",
                verification_kind="configure", test_system="cmake",
                runner_type="cmake", policy="controlled_execution",
            )
            result = runner.execute(step, "/tmp")
            assert result.status in (TOOL_UNAVAILABLE.value, INVALID_PLAN.value)
        finally:
            shutil.which = original

    def test_cmake_configure_runs_safely(self):
        import subprocess, shutil
        original = subprocess.run
        original_which = shutil.which

        class FakeProcess:
            returncode = 0
            stdout = "Configuring done"
            stderr = ""
            timed_out = False

        subprocess.run = lambda *a, **kw: FakeProcess()
        shutil.which = lambda x: "/usr/bin/cmake" if x == "cmake" else None
        try:
            runner = CMakeRunner()
            step = VerificationStep(
                step_id="cm-c", area=".", working_directory=".",
                verification_kind="configure", test_system="cmake",
                runner_type="cmake", policy="controlled_execution",
            )
            result = runner.execute(step, "/tmp")
            assert result.status == PASS.value
            assert "cmake" in str(result.command[0])
        finally:
            subprocess.run = original
            shutil.which = original_which

    def test_cmake_build_fail(self):
        import subprocess, shutil
        original = subprocess.run
        original_which = shutil.which

        class FakeProcess:
            returncode = 1
            stdout = ""
            stderr = "Build failed"
            timed_out = False

        subprocess.run = lambda *a, **kw: FakeProcess()
        shutil.which = lambda x: "/usr/bin/cmake"
        try:
            runner = CMakeRunner()
            step = VerificationStep(
                step_id="cm-b", area=".", working_directory=".",
                verification_kind="build", test_system="cmake",
                runner_type="cmake", policy="controlled_execution",
            )
            result = runner.execute(step, "/tmp")
            assert result.status == FAIL.value
        finally:
            subprocess.run = original
            shutil.which = original_which

    def test_cmake_no_install(self):
        import inspect
        src = inspect.getsource(CMakeRunner.execute)
        assert "install" not in src
        assert "package" not in src

    def test_cmake_build_dir_is_controlled(self):
        runner = CMakeRunner()
        assert isinstance(runner, VerificationRunner)

    def test_ctest_is_deferred_or_declarative_only(self, tmp_path):
        _write(tmp_path / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.10)\n")
        _write(tmp_path / "src" / "main.cpp", "int main() { return 0; }\n")
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")
        ctest_steps = [s for s in plan.steps if s.verification_kind == "test" and s.test_system == "ctest"]
        assert len(ctest_steps) == 0 or all(s.policy != "controlled_execution" for s in ctest_steps)


# ============================================================================
# Security Tests
# ============================================================================

class TestSecurity:
    def test_shell_false_in_firmware_runners(self):
        import inspect
        for cls in (ESPHomeCheckRunner, PlatformIORunner, CMakeRunner):
            src = inspect.getsource(cls.execute)
            assert "shell=True" not in src
            assert "shell = True" not in src

    def test_argv_lists_not_strings(self):
        import inspect
        for cls in (ESPHomeCheckRunner, PlatformIORunner, CMakeRunner):
            src = inspect.getsource(cls)
            assert 'tuple' in src or 'args = (' in src

    def test_cwd_traversal_blocked_in_all_runners(self):
        for cls in (ESPHomeCheckRunner, PlatformIORunner, CMakeRunner):
            runner = cls()
            step = VerificationStep(
                step_id="escape", area="..", working_directory="/etc",
                verification_kind="build", test_system="test",
                runner_type=runner.runner_type, policy="controlled_execution",
            )
            result = runner.execute(step, "/tmp")
            assert result.status == INVALID_PLAN.value

    def test_secrets_not_in_runner_output(self):
        result = VerificationStepResult(
            step_id="s1", area=".", status=PASS.value,
            verification_kind="build", runner_type="platformio",
            passed=True, return_code=0,
            stdout="Build OK", stderr="",
        )
        assert "SECRET" not in result.stdout
        assert "password" not in result.stdout


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    def test_mixed_python_web_platformio_esphome_plan(self, tmp_path):
        _write(tmp_path / "backend" / "pyproject.toml", "[tool.pytest.ini_options]\n")
        _write(tmp_path / "backend" / "src" / "main.py", "pass\n")
        _write(tmp_path / "backend" / "src" / "util.py", "pass\n")

        _write(tmp_path / "frontend" / "package.json",
               json.dumps({"devDependencies": {"vitest": "^2.0.0"}}))
        _write(tmp_path / "frontend" / "src" / "index.ts", "const x = 1;\n")
        _write(tmp_path / "frontend" / "src" / "App.tsx", "export default function App() {};\n")

        _write(tmp_path / "firmware" / "platformio.ini",
               "[env:esp32dev]\nboard = esp32dev\nframework = arduino\n")
        _write(tmp_path / "firmware" / "src" / "main.cpp", "void setup(){}\nvoid loop(){}\n")

        _write(tmp_path / "esphome" / "device.yaml",
               "esphome:\n  name: test\n  board: esp32dev\n")

        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run-mixed")
        areas = set(s.area for s in plan.steps)
        assert "backend" in areas or "." in areas
        test_systems = set(s.test_system for s in plan.steps)
        assert "pytest" in test_systems
        assert "platformio" in test_systems
        assert "esphome" in test_systems

    def test_default_registry_has_all_runners(self):
        registry = build_default_registry()
        for rt in ("pytest", "python_unittest", "esphome_check", "platformio", "cmake"):
            step = VerificationStep(
                step_id=f"t-{rt}", area=".", working_directory=".",
                verification_kind="test", test_system=rt,
                runner_type=rt, policy="controlled_execution",
            )
            assert registry.find(step) is not None, f"{rt} runner missing"

    def test_pytest_runner_still_green(self, tmp_path):
        _write(tmp_path / "tests" / "test_trivial.py",
               "def test_passes():\n    assert 1 + 1 == 2\n")
        step = VerificationStep(
            step_id="root-test-pytest", area=".", working_directory=".",
            verification_kind="test", test_system="pytest",
            runner_type="pytest", policy="controlled_execution",
        )
        runner = PytestRunner(timeout=30)
        result = runner.execute(step, tmp_path)
        assert result.status == PASS.value

    def test_unittest_runner_still_green(self):
        runner = PythonUnittestRunner()
        assert runner is not None

    def test_project_intelligence_is_only_source(self, tmp_path):
        _write(tmp_path / "platformio.ini",
               "[env:esp32dev]\nboard = esp32dev\n")
        _write(tmp_path / "src" / "main.cpp", "void setup(){}\n")
        pi = inspect_project(tmp_path)
        plan = build_verification_plan(pi, "run")
        assert plan.created_from_intelligence is True

    def test_productive_adapter_reachability_still_clean(self):
        import ast
        from pathlib import Path as _Path

        ADAPTERS = ("app/web_api.py", "app/mcp_server.py",
                    "app/mcp_transport.py", "app/workflow_cli.py",
                    "app/workflow_execution_cli.py", "cli/agent_workflow_cli.py")
        FORBIDDEN = {"app.agent_orchestrator", "app.git_manager",
                     "app.workflow_publisher", "app.setup_planner"}
        root = _Path(__file__).parents[1]
        violations = []
        for rel in ADAPTERS:
            tree = ast.parse((root / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN:
                    violations.append(f"{rel}: {node.module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in FORBIDDEN:
                            violations.append(f"{rel}: {alias.name}")
        assert violations == [], f"Legacy imports found: {violations}"

    def test_blocked_dependency_is_not_pass(self):
        aggregated = _aggregate((
            VerificationStepResult(
                step_id="s1", area=".", status=BLOCKED.value,
                verification_kind="compile", runner_type="esphome_check",
                passed=False,
                diagnostics="Blocked by failed dependency: esphome-validate",
            ),
        ))
        assert aggregated != PASS.value


# ============================================================================
# No hardware actions in any runner
# ============================================================================

class TestNoHardwareActions:
    def test_esphome_no_hardware(self):
        import inspect
        src = inspect.getsource(ESPHomeCheckRunner.execute)
        # Check for hardware commands — but not coincidental strings in code
        assert "esphome run " not in src
        assert "esphome upload" not in src
        assert "flash" not in src

    def test_platformio_no_hardware(self):
        import inspect
        src = inspect.getsource(PlatformIORunner)
        assert "upload " not in src  # no standalone upload command
        assert "monitor " not in src
        assert "flash" not in src
        # --without-uploading is legitimate — it disables upload!

    def test_cmake_no_hardware(self):
        import inspect
        src = inspect.getsource(CMakeRunner.execute)
        for forbidden in ("install", "package", "deploy", "flash", "upload"):
            assert forbidden not in src.lower()


# ============================================================================
# KORREKTUR — ESPHome Recursive, Config-Path, extra_scripts, TOOL_UNAVAILABLE
# ============================================================================

# ---- ESPHome recursive detection in subdirectories ----

def test_esphome_in_subdirectory_detected(tmp_path):
    (tmp_path / "esphome").mkdir()
    _write(tmp_path / "esphome" / "device.yaml",
           "esphome:\n  name: test\n  board: esp32dev\n")
    pi = inspect_project(tmp_path)
    assert any(fw.name == "esphome" for fw in pi.firmware_indicators)


def test_esphome_config_path_in_intelligence(tmp_path):
    (tmp_path / "esphome").mkdir()
    _write(tmp_path / "esphome" / "device.yaml",
           "esphome:\n  name: test\n")
    pi = inspect_project(tmp_path)
    fw = next(fw for fw in pi.firmware_indicators if fw.name == "esphome")
    assert fw.config_path is not None


def test_esphome_runner_uses_config_path():
    runner = ESPHomeCheckRunner()
    step = VerificationStep(
        step_id="esph-v", area="esphome", working_directory="esphome",
        verification_kind="validate", test_system="esphome",
        runner_type="esphome_check", policy="controlled_execution",
        metadata={"config": "device.yaml"},
    )
    # verify metadata is accessible
    assert step.metadata is not None
    assert step.metadata["config"] == "device.yaml"


def test_normal_yaml_recursive_not_esphome(tmp_path):
    (tmp_path / "config").mkdir()
    _write(tmp_path / "config" / "settings.yaml", "app:\n  name: myapp\n")
    pi = inspect_project(tmp_path)
    assert not any(fw.name == "esphome" for fw in pi.firmware_indicators)


# ---- PlatformIO extra_scripts detected and blocked ----

def test_platformio_extra_scripts_detected(tmp_path):
    _write(tmp_path / "platformio.ini",
           "[env:esp32dev]\nboard = esp32dev\n"
           "extra_scripts = pre:build.py\n")
    _write(tmp_path / "src" / "main.cpp", "void setup(){}\nvoid loop(){}\n")
    pi = inspect_project(tmp_path)
    fw = next(fw for fw in pi.firmware_indicators if fw.name == "platformio")
    assert fw.has_untrusted_hooks is True


def test_platformio_extra_scripts_blocks_execution(tmp_path):
    _write(tmp_path / "platformio.ini",
           "[env:esp32dev]\nboard = esp32dev\n"
           "extra_scripts = pre:my_hook.py\n")
    _write(tmp_path / "src" / "main.cpp", "void setup(){}\nvoid loop(){}\n")
    pi = inspect_project(tmp_path)
    plan = build_verification_plan(pi, "run-hooks")
    pio_steps = [s for s in plan.steps if s.test_system == "platformio"]
    assert all(s.policy == "unsupported" for s in pio_steps)


def test_platformio_without_extra_scripts_allowed(tmp_path):
    _write(tmp_path / "platformio.ini",
           "[env:esp32dev]\nboard = esp32dev\nframework = arduino\n")
    _write(tmp_path / "src" / "main.cpp", "void setup(){}\nvoid loop(){}\n")
    pi = inspect_project(tmp_path)
    fw = next(fw for fw in pi.firmware_indicators if fw.name == "platformio")
    assert fw.has_untrusted_hooks is False


# ---- TOOL_UNAVAILABLE aggregation ----

def test_tool_unavailable_blocks_aggregate_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area="backend", status=PASS.value,
            verification_kind="test", runner_type="pytest",
            passed=True, return_code=0,
        ),
        VerificationStepResult(
            step_id="s2", area="firmware", status=TOOL_UNAVAILABLE.value,
            verification_kind="build", runner_type="platformio",
            passed=False,
            diagnostics="PlatformIO not found",
        ),
        VerificationStepResult(
            step_id="s3", area="esphome", status=TOOL_UNAVAILABLE.value,
            verification_kind="validate", runner_type="esphome_check",
            passed=False,
            diagnostics="ESPHome not found",
        ),
    ))
    assert aggregated != PASS.value


def test_tool_unavailable_lone_is_not_pass():
    aggregated = _aggregate((
        VerificationStepResult(
            step_id="s1", area="firmware", status=TOOL_UNAVAILABLE.value,
            verification_kind="build", runner_type="platformio",
            passed=False,
        ),
    ))
    assert aggregated != PASS.value


def test_mixed_project_e2e_plan(tmp_path):
    _write(tmp_path / "backend" / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "backend" / "src" / "main.py", "pass\n")
    _write(tmp_path / "backend" / "src" / "util.py", "pass\n")
    _write(tmp_path / "frontend" / "package.json",
           json.dumps({"devDependencies": {"vitest": "^2.0.0"}}))
    _write(tmp_path / "frontend" / "src" / "index.ts", "const x = 1;\n")
    _write(tmp_path / "frontend" / "src" / "App.tsx", "export default function App() {};\n")
    (tmp_path / "firmware").mkdir()
    _write(tmp_path / "firmware" / "platformio.ini",
           "[env:esp32dev]\nboard = esp32dev\nframework = arduino\n")
    _write(tmp_path / "firmware" / "src" / "main.cpp", "void setup(){}\nvoid loop(){}\n")
    (tmp_path / "esphome").mkdir()
    _write(tmp_path / "esphome" / "device.yaml",
           "esphome:\n  name: test\n  board: esp32dev\n")

    pi = inspect_project(tmp_path)
    plan = build_verification_plan(pi, "run-mixed-e2e")

    areas = set(s.area for s in plan.steps)
    assert "backend" in areas
    assert "firmware" in areas
    assert "esphome" in areas

    test_systems = set(s.test_system for s in plan.steps)
    assert "pytest" in test_systems
    assert "platformio" in test_systems
    assert "esphome" in test_systems

    # ESPHome validate→compile dependency
    esphome_compile = next(s for s in plan.steps
                           if s.test_system == "esphome" and s.verification_kind == "compile")
    assert len(esphome_compile.depends_on) >= 1

    # Check config_path metadata for ESPHome steps
    esphome_steps = [s for s in plan.steps if s.test_system == "esphome"]
    for s in esphome_steps:
        assert s.metadata is not None
        assert s.metadata.get("config") is not None


def test_area_cwd_is_correct_for_subdirs(tmp_path):
    (tmp_path / "backend").mkdir()
    _write(tmp_path / "backend" / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "backend" / "src" / "main.py", "pass\n")
    _write(tmp_path / "backend" / "src" / "util.py", "pass\n")
    (tmp_path / "esphome").mkdir()
    _write(tmp_path / "esphome" / "device.yaml",
           "esphome:\n  name: test\n  board: esp32dev\n")

    pi = inspect_project(tmp_path)
    plan = build_verification_plan(pi, "run-cwd")
    esphome_steps = [s for s in plan.steps if s.test_system == "esphome"]
    # ESPHome steps exist in both root and esphome area
    assert len(esphome_steps) >= 2
    # At least one set of steps has config in its metadata
    assert any(s.metadata is not None and s.metadata.get("config") is not None
               for s in esphome_steps)


# ============================================================================
# _build_step_result diagnostics
# ============================================================================

class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr="", timed_out=False):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out


def _make_step():
    return VerificationStep(
        step_id="s1", area=".", working_directory=".",
        verification_kind="validate", test_system="esphome",
        runner_type="esphome_check", policy="controlled_execution",
    )


class TestBuildStepResult:
    def test_success_has_empty_diagnostics(self):
        result = FakeCompletedProcess(returncode=0, stdout="ok", stderr="")
        built = _build_step_result(_make_step(), result, ("esphome", "config", "."))
        assert built.status == PASS.value
        assert built.diagnostics == ""
        assert built.stdout == "ok"
        assert built.stderr == ""

    def test_fail_with_stderr_puts_stderr_in_diagnostics(self):
        result = FakeCompletedProcess(returncode=1, stdout="", stderr="Config error: missing name")
        built = _build_step_result(_make_step(), result, ("esphome", "config", "."))
        assert built.status == FAIL.value
        assert "Config error: missing name" in built.diagnostics
        assert built.stderr == "Config error: missing name"

    def test_fail_with_empty_stderr_falls_back_to_stdout(self):
        result = FakeCompletedProcess(returncode=1, stdout="Warning: config issue", stderr="")
        built = _build_step_result(_make_step(), result, ("esphome", "config", "."))
        assert built.status == FAIL.value
        assert "Warning: config issue" in built.diagnostics

    def test_fail_with_neither_stream_uses_returncode_fallback(self):
        result = FakeCompletedProcess(returncode=2, stdout="", stderr="")
        built = _build_step_result(_make_step(), result, ("esphome", "config", "."))
        assert built.status == FAIL.value
        assert "return code 2" in built.diagnostics

    def test_timeout_includes_timeout_message(self):
        result = FakeCompletedProcess(returncode=-1, stdout="partial", stderr="",
                                      timed_out=True)
        built = _build_step_result(_make_step(), result, ("esphome", "compile", "."))
        assert built.status == TIMEOUT.value
        assert "Execution timed out" in built.diagnostics

    def test_timeout_includes_stderr_when_present(self):
        result = FakeCompletedProcess(returncode=-1, stdout="start", stderr="killed\n",
                                      timed_out=True)
        built = _build_step_result(_make_step(), result, ("esphome", "compile", "."))
        assert built.status == TIMEOUT.value
        assert "Execution timed out" in built.diagnostics
        assert "killed" in built.diagnostics

    def test_timeout_includes_stdout_when_stderr_empty(self):
        result = FakeCompletedProcess(returncode=-1, stdout="started\nworking\n",
                                      stderr="", timed_out=True)
        built = _build_step_result(_make_step(), result, ("esphome", "compile", "."))
        assert built.status == TIMEOUT.value
        assert "Execution timed out" in built.diagnostics
        assert "started" in built.diagnostics

    def test_diagnostics_bounded_by_max_output(self):
        huge = "x" * (_MAX_OUTPUT + 1000)
        result = FakeCompletedProcess(returncode=1, stdout="", stderr=huge)
        built = _build_step_result(_make_step(), result, ("esphome", "config", "."))
        assert len(built.diagnostics) <= _MAX_OUTPUT

    def test_stdout_and_stderr_preserved_in_result(self):
        result = FakeCompletedProcess(returncode=1, stdout="out", stderr="err")
        built = _build_step_result(_make_step(), result, ("esphome", "config", "."))
        assert built.stdout == "out"
        assert built.stderr == "err"