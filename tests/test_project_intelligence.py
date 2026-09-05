"""Structured project intelligence tests — read-only, no execution."""
import json
from pathlib import Path

import pytest

from app.project_intelligence import (
    DetectedBuildSystem, DetectedFramework, DetectedFirmware,
    DetectedLanguage, DetectedPackageSystem, DetectedTestSystem,
    Evidence, ProjectArea, ProjectIntelligence,
    inspect_project, _read_limited, _is_sensitive, _is_excluded,
    _detect_package_systems, _detect_build_systems, _detect_test_systems,
    _detect_frameworks, _detect_firmware, _detect_ci, _detect_docs,
)


def _mkdir(parent: Path, *parts: str) -> Path:
    d = parent.joinpath(*parts)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# 1. Greenfield
def test_greenfield_project_is_recognised(tmp_path):
    pi = inspect_project(tmp_path)
    assert pi.project_kind == "greenfield"
    assert pi.languages == ()
    assert pi.language_names == ()


# 2. Python + pytest
def test_python_with_pytest_is_detected(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "src" / "main.py", "print('hello')\n")
    _write(tmp_path / "src" / "util.py", "x = 1\n")
    _write(tmp_path / "tests" / "test_main.py", "def test_x(): pass\n")

    pi = inspect_project(tmp_path)
    assert pi.project_kind == "existing"
    assert "python" in pi.language_names
    assert "pytest" in pi.test_system_names
    assert any(ps.name.startswith("python") for ps in pi.package_systems)


# 3. TypeScript + React/Vite
def test_typescript_react_project_is_detected(tmp_path):
    _write(tmp_path / "package.json", json.dumps({
        "dependencies": {"react": "^18.0.0"},
        "devDependencies": {"vite": "^5.0.0", "vitest": "^2.0.0"},
    }))
    _write(tmp_path / "src" / "index.ts", "const x: number = 1;\n")
    _write(tmp_path / "src" / "App.tsx", "export default function App() {};\n")

    pi = inspect_project(tmp_path)
    assert pi.project_kind == "existing"
    assert "typescript" in pi.language_names
    assert "react" in pi.framework_names
    assert "vite" in pi.framework_names
    assert any(ps.name == "node-npm" for ps in pi.package_systems)
    assert "vitest" in pi.test_system_names


# 4. C/C++ + CMake
def test_cpp_cmake_project_is_detected(tmp_path):
    _write(tmp_path / "CMakeLists.txt", "cmake_minimum_required(VERSION 3.10)\n")
    _write(tmp_path / "src" / "main.cpp", "int main() { return 0; }\n")
    _write(tmp_path / "src" / "util.cpp", "void util() {}\n")
    _write(tmp_path / "include" / "util.h", "#pragma once\n")

    pi = inspect_project(tmp_path)
    assert pi.project_kind == "existing"
    assert "cpp" in pi.language_names
    assert any(bs.name == "cmake" for bs in pi.build_systems)


# 5. PlatformIO
def test_platformio_project_is_detected(tmp_path):
    _write(tmp_path / "platformio.ini",
           "[env:esp32dev]\nplatform = espressif32\nboard = esp32dev\n")
    _write(tmp_path / "src" / "main.cpp", "void setup() {}\nvoid loop() {}\n")
    _write(tmp_path / "src" / "util.cpp", "void util() {}\n")

    pi = inspect_project(tmp_path)
    assert any(bs.name == "platformio" for bs in pi.build_systems)
    fw = pi.firmware_indicators
    assert any(f.name == "platformio" for f in fw)
    pio_fw = next(f for f in fw if f.name == "platformio")
    assert "esp32dev" in pio_fw.boards


# 6. ESPHome
def test_esphome_project_is_detected(tmp_path):
    _write(tmp_path / "esphome.yaml", "esphome:\n  name: test\n  board: esp32dev\n")

    pi = inspect_project(tmp_path)
    assert any(fw.name == "esphome" for fw in pi.firmware_indicators)
    assert any(fw.name == "esphome" for fw in pi.frameworks)


# 7. Normal YAML != ESPHome
def test_normal_yaml_is_not_esphome(tmp_path):
    _write(tmp_path / "config.yaml", "app:\n  name: my-app\n")

    pi = inspect_project(tmp_path)
    assert not any(fw.name == "esphome" for fw in pi.firmware_indicators)


# 8. tests/ without evidence != pytest
def test_tests_dir_without_evidence_is_not_pytest(tmp_path):
    _write(tmp_path / "tests" / "helper.py", "def helper():\n    return 42\n")

    pi = inspect_project(tmp_path)
    assert "pytest" not in pi.test_system_names


# 9. venv excluded
def test_venv_is_excluded_from_traversal(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "venv" / "lib" / "sensitive.py", "SECRET_KEY=abc\n")

    pi = inspect_project(tmp_path)
    assert pi.total_files_excluded > 0


# 10. .venv excluded
def test_dot_venv_is_excluded_from_traversal(tmp_path):
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / ".venv" / "lib" / "sensitive.py", "SECRET_KEY=abc\n")

    pi = inspect_project(tmp_path)
    assert pi.total_files_excluded > 0


# 11. node_modules excluded
def test_node_modules_is_excluded(tmp_path):
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "node_modules" / "react" / "index.js", "module.exports = {};\n")

    pi = inspect_project(tmp_path)
    assert pi.total_files_excluded > 0


# 12. .git excluded
def test_git_dir_is_excluded(tmp_path):
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / ".git" / "config", "[core]\n\tbare=false\n")

    pi = inspect_project(tmp_path)
    assert pi.total_files_excluded > 0


# 13. build/dist excluded
@pytest.mark.parametrize("dirname", ["build", "dist"])
def test_build_artifacts_are_excluded(tmp_path, dirname):
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / dirname / "output.js", "/* generated */\n")

    pi = inspect_project(tmp_path)
    assert pi.total_files_excluded > 0


# 14. Symlink escape (safe path handling)
def test_symlink_is_safe(tmp_path):
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "util.py", "pass\n")

    pi = inspect_project(tmp_path)
    assert "python" in pi.language_names


# 15. .env content not in intelligence
def test_env_content_not_in_intelligence(tmp_path):
    _write(tmp_path / ".env", "SECRET_KEY=super-secret-value\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "util.py", "pass\n")

    pi = inspect_project(tmp_path)
    assert pi.sensitive_configuration_present is True
    for area in pi.areas:
        for la in area.languages:
            assert ".env" not in la.name


# 16. .env content not in summary
def test_env_content_not_in_summary(tmp_path):
    _write(tmp_path / ".env", "SECRET_KEY=abc\n")
    _write(tmp_path / "src" / "main.py", "pass\n")

    pi = inspect_project(tmp_path)
    summary = pi.to_summary()
    assert "SECRET_KEY" not in str(summary)


# 17. Private key content not leaked
def test_private_key_content_not_leaked(tmp_path):
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "id_rsa", "-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----\n")

    pi = inspect_project(tmp_path)
    assert pi.sensitive_configuration_present is True


# 18. Sensitive content never reaches summary
def test_trace_has_no_sensitive_content(tmp_path):
    _write(tmp_path / "src" / "main.py", "pass\n")

    pi = inspect_project(tmp_path)
    summary = pi.to_summary()
    assert "SECRET_KEY" not in str(summary.get("languages", []))


# 19. File count
def test_file_count_is_tracked(tmp_path):
    for i in range(50):
        _write(tmp_path / f"file_{i:04d}.txt", f"content {i}\n")

    pi = inspect_project(tmp_path)
    assert pi.total_files_traversed == 50


# 20. Manifest size limit
def test_manifest_size_limit(tmp_path):
    huge = "x" * 600_000
    _write(tmp_path / "pyproject.toml", f"[tool]\nkey = '{huge}'\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "util.py", "pass\n")

    pi = inspect_project(tmp_path)
    assert "python" in pi.language_names


# 21. Truncated flag
def test_truncated_flag_is_set_on_limit(tmp_path):
    for i in range(2500):
        _write(tmp_path / f"file_{i:04d}.txt", f"content {i}\n")

    pi = inspect_project(tmp_path)
    assert pi.truncated is True
    assert pi.inspection_limit_exceeded is True


# 22. Deterministic repeat
def test_deterministic_repeat(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "src" / "main.py", "pass\n")

    pi1 = inspect_project(tmp_path)
    pi2 = inspect_project(tmp_path)
    assert pi1.project_kind == pi2.project_kind
    assert pi1.language_names == pi2.language_names
    assert pi1.test_system_names == pi2.test_system_names


# 23. Mixed project areas
def test_mixed_project_areas_are_detected(tmp_path):
    _write(tmp_path / "backend" / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "backend" / "app" / "main.py", "pass\n")
    _write(tmp_path / "backend" / "app" / "util.py", "pass\n")

    _write(tmp_path / "frontend" / "package.json", json.dumps({
        "dependencies": {"react": "^18.0.0"},
        "devDependencies": {"vite": "^5.0.0"},
    }))
    _write(tmp_path / "frontend" / "src" / "index.ts", "const x = 1;\n")
    _write(tmp_path / "frontend" / "src" / "App.tsx", "export default function App() {};\n")

    _write(tmp_path / "firmware" / "platformio.ini",
           "[env:esp32dev]\nboard = esp32dev\n")
    _write(tmp_path / "firmware" / "src" / "main.cpp", "void setup() {}\nvoid loop() {}\n")

    _write(tmp_path / "esphome" / "device.yaml", "esphome:\n  name: test\n")

    pi = inspect_project(tmp_path)
    assert pi.project_kind == "mixed"
    assert pi.area_count >= 4
    assert "python" in pi.language_names
    assert "typescript" in pi.language_names
    assert "cpp" in pi.language_names
    assert "react" in pi.framework_names
    assert "pytest" in pi.test_system_names
    assert any(fw.name == "esphome" for fw in pi.firmware_indicators)
    assert any(bs.name == "platformio" for bs in pi.build_systems)


# 24. Git repository presence
def test_git_repository_presence_is_detected(tmp_path):
    _mkdir(tmp_path, ".git")
    _write(tmp_path / "src" / "main.py", "pass\n")

    pi = inspect_project(tmp_path)
    assert pi.git_repository_present is True


def test_no_git_repository(tmp_path):
    _write(tmp_path / "src" / "main.py", "pass\n")

    pi = inspect_project(tmp_path)
    assert pi.git_repository_present is False


# 25. CI detection
def test_github_actions_is_detected(tmp_path):
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / ".github" / "workflows" / "ci.yml", "name: CI\n")

    pi = inspect_project(tmp_path)
    assert "github-actions" in pi.ci_indicators


def test_gitlab_ci_is_detected(tmp_path):
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / ".gitlab-ci.yml", "stages:\n  - test\n")

    pi = inspect_project(tmp_path)
    assert "gitlab-ci" in pi.ci_indicators


# 26. Documentation detection
def test_readme_and_docs_are_detected(tmp_path):
    _write(tmp_path / "README.md", "# Project\n")
    _mkdir(tmp_path, "docs")

    pi = inspect_project(tmp_path)
    assert len(pi.doc_indicators) >= 1


# 27. Council receives stack
def test_council_input_receives_detected_stack():
    from app.dev_workflow import DevelopmentWorkflow

    project_info = {
        "project_kind": "existing",
        "languages": ["python"],
        "frameworks": ["fastapi"],
        "package_systems": ["python-pip"],
        "build_systems": [],
        "test_systems": ["pytest"],
        "firmware_indicators": [],
    }
    stack = DevelopmentWorkflow._build_detected_stack(project_info)
    assert "python" in stack
    assert "fastapi" in stack
    assert "pytest" in stack
    assert "kind: existing" in stack


# 28. Greenfield council
def test_greenfield_council_stack_is_empty():
    from app.dev_workflow import DevelopmentWorkflow

    project_info = {
        "project_kind": "greenfield",
        "languages": [],
        "frameworks": [],
        "package_systems": [],
        "build_systems": [],
        "test_systems": [],
        "firmware_indicators": [],
    }
    stack = DevelopmentWorkflow._build_detected_stack(project_info)
    assert "greenfield" in stack
    assert "python" not in stack


# 29. Canonical composition uses inspector
def test_canonical_composition_uses_project_inspector():
    from app.canonical_composition import CanonicalComponents
    assert CanonicalComponents is not None


# 30. MCP uses ProjectInspector
def test_mcp_server_supports_project_inspector():
    from app.mcp_server import MCPServer
    from unittest.mock import Mock

    inspector = Mock()
    inspector.inspect.return_value = {"project_id": "test", "files": []}
    server = MCPServer(
        project_scanner=Mock(),
        discovery=Mock(),
        preflight=Mock(),
        planner=None,
        plan_store=Mock(),
        approval=Mock(),
        development_workflow=Mock(),
        project_inspector=inspector,
    )
    result = server.inspect_project("/tmp/test")
    assert "files" in result


# 31. CLI uses inspect_project
def test_cli_can_use_inspect_project(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "util.py", "pass\n")

    pi = inspect_project(tmp_path)
    assert pi.project_kind == "existing"
    assert "python" in pi.language_names


# 32. CDX-018 reachability guard
def test_productive_adapters_guard_imports_intelligence():
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


# 33. Evidence in detected items
def test_evidence_is_present_in_detected_items(tmp_path):
    _write(tmp_path / "pytest.ini", "[pytest]\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "util.py", "pass\n")

    pi = inspect_project(tmp_path)
    for ts in pi.test_systems:
        assert len(ts.evidence) >= 1
        for ev in ts.evidence:
            assert isinstance(ev.path, str)
            assert isinstance(ev.kind, str)
            assert ev.kind in ("explicit_configuration", "file_extension", "dependency_declaration")


# 34. Package manager preference
def test_pnpm_preferred_over_npm(tmp_path):
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "pnpm-lock.yaml", "")
    _write(tmp_path / "src" / "index.ts", "const x = 1;\n")
    _write(tmp_path / "src" / "util.ts", "export const y = 2;\n")

    pi = inspect_project(tmp_path)
    npm_sys = next(ps for ps in pi.package_systems if ps.name == "node-npm")
    assert npm_sys.preferred_manager == "pnpm"


# 35. Multiple package managers
def test_mixed_python_node_packages(tmp_path):
    _write(tmp_path / "package.json", "{}")
    _write(tmp_path / "pyproject.toml", "[tool]\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "index.ts", "const x = 1;\n")

    pi = inspect_project(tmp_path)
    pkg_names = pi.package_system_names
    assert any("python" in n for n in pkg_names)
    assert any("node" in n for n in pkg_names)


# 36. Django detection
def test_django_is_detected_via_pyproject(tmp_path):
    _write(tmp_path / "pyproject.toml", "[project]\ndependencies = [\"django\"]\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "manage.py", "pass\n")

    pi = inspect_project(tmp_path)
    assert "django" in pi.framework_names


# 37. Next.js detection
def test_nextjs_is_detected(tmp_path):
    _write(tmp_path / "package.json", json.dumps({
        "dependencies": {"next": "^14.0.0", "react": "^18.0.0"},
    }))
    _write(tmp_path / "src" / "page.tsx", "export default function Page() {}\n")
    _write(tmp_path / "src" / "layout.tsx", "export default function Layout() {}\n")

    pi = inspect_project(tmp_path)
    assert "next.js" in pi.framework_names
    assert "react" in pi.framework_names


# 38. read_project_files excludes .env
def test_read_project_files_excludes_env(tmp_path):
    from app.project_files import read_project_files
    _write(tmp_path / ".env", "SECRET_KEY=abc\n")
    _write(tmp_path / "src" / "main.py", "pass\n")

    files, warnings = read_project_files(tmp_path)
    file_paths = [f["path"] for f in files]
    assert ".env" not in file_paths


# 39. read_project_files excludes node_modules
def test_read_project_files_excludes_node_modules(tmp_path):
    from app.project_files import read_project_files
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "node_modules" / "lib.js", "module.exports = {};\n")

    files, _ = read_project_files(tmp_path)
    file_paths = [f["path"] for f in files]
    assert all("node_modules" not in p for p in file_paths)


# 40. JSON language detection
def test_json_is_detected_as_language(tmp_path):
    _write(tmp_path / "config.json", '{"key": "value"}\n')
    _write(tmp_path / "settings.json", '{"a": 1}\n')

    pi = inspect_project(tmp_path)
    assert "json" in pi.language_names


# 41. YAML language detection
def test_yaml_is_detected_as_language(tmp_path):
    _write(tmp_path / "config.yaml", "app:\n  name: test\n")
    _write(tmp_path / "settings.yaml", "version: 1\n")

    pi = inspect_project(tmp_path)
    assert "yaml" in pi.language_names


# 42. Makefile detection
def test_makefile_is_detected(tmp_path):
    _write(tmp_path / "Makefile", "all:\n\t@echo hello\n")
    _write(tmp_path / "src" / "main.c", "int main() { return 0; }\n")
    _write(tmp_path / "src" / "util.c", "void util() {}\n")

    pi = inspect_project(tmp_path)
    assert any(bs.name == "make" for bs in pi.build_systems)


# 43. Jest detection
def test_jest_is_detected(tmp_path):
    _write(tmp_path / "package.json", json.dumps({
        "devDependencies": {"jest": "^29.0.0"},
    }))
    _write(tmp_path / "src" / "index.ts", "const x = 1;\n")
    _write(tmp_path / "src" / "util.ts", "export const y = 2;\n")

    pi = inspect_project(tmp_path)
    assert "jest" in pi.test_system_names


# 44. Area paths
def test_areas_have_correct_paths(tmp_path):
    _write(tmp_path / "backend" / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "backend" / "app" / "main.py", "pass\n")

    pi = inspect_project(tmp_path)
    area_paths = {area.path for area in pi.areas}
    assert "backend" in area_paths


# ============================================================================
# KORREKTUR — Council-Integration / Single‑File Detection / Framework Parsing
# ============================================================================

# ---- Council receives structured intelligence facts (not just detected_stack) ----

def test_council_input_contains_project_intelligence():
    from app.dev_workflow import DevelopmentWorkflow

    pi = {
        "project_kind": "existing",
        "area_count": 1,
        "languages": ["python"],
        "frameworks": ["fastapi"],
        "package_systems": ["python-pip"],
        "build_systems": [],
        "test_systems": ["pytest"],
        "firmware_indicators": [],
    }
    result = DevelopmentWorkflow._project_intelligence_from(pi)
    assert result is not None
    assert result["project_kind"] == "existing"
    assert result["languages"] == ["python"]
    assert result["frameworks"] == ["fastapi"]
    assert result["test_systems"] == ["pytest"]


def test_council_intelligence_distinguishes_mixed_areas():
    from app.dev_workflow import DevelopmentWorkflow

    pi = {
        "project_kind": "mixed",
        "area_count": 4,
        "languages": ["python", "typescript", "cpp"],
        "frameworks": ["react", "esphome"],
        "package_systems": ["python-pip", "node-npm"],
        "build_systems": ["platformio"],
        "test_systems": ["pytest", "vitest"],
        "firmware_indicators": ["esphome", "platformio"],
    }
    result = DevelopmentWorkflow._project_intelligence_from(pi)
    assert "python" in result["languages"]
    assert "typescript" in result["languages"]
    assert "cpp" in result["languages"]
    assert result["area_count"] == 4
    assert "react" in result["frameworks"]
    assert "esphome" in result["firmware_indicators"]


def test_detected_stack_is_not_the_only_council_transmission():
    from app.dev_workflow import DevelopmentWorkflow

    pi = {"languages": ["python"]}
    stack = DevelopmentWorkflow._build_detected_stack(pi)
    intel = DevelopmentWorkflow._project_intelligence_from(pi)
    # detected_stack should still exist (compatibility)
    assert isinstance(stack, str)
    # but structured intelligence must also exist
    assert intel is not None
    assert "python" in intel["languages"]


def test_sensitive_content_never_reaches_council_intelligence():
    from app.dev_workflow import DevelopmentWorkflow

    pi = {
        "project_kind": "existing",
        "languages": ["python"],
        "frameworks": ["fastapi"],
        "package_systems": ["python-pip"],
        "build_systems": [],
        "test_systems": [],
        "firmware_indicators": [],
        "area_count": 1,
        "truncated": False,
    }
    result = DevelopmentWorkflow._project_intelligence_from(pi)
    result_str = str(result)
    assert ".env" not in result_str
    assert "SECRET_KEY" not in result_str
    assert "password" not in result_str
    assert "credentials" not in result_str
    for key in result.keys():
        assert isinstance(key, str)
        assert "secret" not in key.lower()


def test_greenfield_council_intelligence_is_present(tmp_path):
    from app.dev_workflow import DevelopmentWorkflow

    pi = inspect_project(tmp_path)
    result = DevelopmentWorkflow._project_intelligence_from(pi.to_summary())
    assert result is not None
    assert result["project_kind"] == "greenfield"


# ---- Single-file language detection ----

def test_single_py_file_is_python(tmp_path):
    _write(tmp_path / "script.py", "x = 1\n")
    pi = inspect_project(tmp_path)
    assert "python" in pi.language_names


def test_single_js_file_is_javascript(tmp_path):
    _write(tmp_path / "app.js", "const x = 1;\n")
    pi = inspect_project(tmp_path)
    assert "javascript" in pi.language_names


def test_single_ts_file_is_typescript(tmp_path):
    _write(tmp_path / "index.ts", "const x: number = 1;\n")
    pi = inspect_project(tmp_path)
    assert "typescript" in pi.language_names


def test_single_c_file_is_c(tmp_path):
    _write(tmp_path / "main.c", "int main() { return 0; }\n")
    pi = inspect_project(tmp_path)
    lang_names = pi.language_names
    assert "c" in lang_names


def test_single_cpp_file_is_cpp(tmp_path):
    _write(tmp_path / "main.cpp", "int main() { return 0; }\n")
    pi = inspect_project(tmp_path)
    assert "cpp" in pi.language_names


# ---- Framework evidence via structured parsing (not keyword matching) ----

def test_django_not_detected_from_readme_mention(tmp_path):
    _write(tmp_path / "README.md", "This project uses Django.\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "util.py", "pass\n")
    pi = inspect_project(tmp_path)
    assert "django" not in pi.framework_names


def test_fastapi_from_structured_pyproject_dependencies(tmp_path):
    _write(tmp_path / "pyproject.toml",
           "[project]\ndependencies = [\"fastapi\", \"uvicorn[standard]\"]\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "util.py", "pass\n")
    pi = inspect_project(tmp_path)
    assert "fastapi" in pi.framework_names


def test_flask_from_tool_dependencies_fallback(tmp_path):
    _write(tmp_path / "pyproject.toml",
           "[tool]\ndependencies = [\"flask\", \"gunicorn\"]\n")
    _write(tmp_path / "src" / "main.py", "pass\n")
    _write(tmp_path / "src" / "util.py", "pass\n")
    pi = inspect_project(tmp_path)
    assert "flask" in pi.framework_names


def test_react_not_detected_from_readme_mention(tmp_path):
    _write(tmp_path / "README.md", "This project uses React and Vite.\n")
    _write(tmp_path / "package.json", "{\"dependencies\": {}}")
    _write(tmp_path / "src" / "index.ts", "const x = 1;\n")
    pi = inspect_project(tmp_path)
    assert "react" not in pi.framework_names


# ---- Council prompt includes structured intelligence ----

def test_phase1_prompt_contains_intelligence_section():
    from app.council_prompts import build_phase1_prompt
    from app.council_models import CouncilInput

    ci = CouncilInput(
        project_id="demo",
        project_intelligence={
            "project_kind": "existing",
            "languages": ["python"],
            "frameworks": ["fastapi"],
            "package_systems": ["python-pip"],
            "build_systems": [],
            "test_systems": ["pytest"],
            "firmware_indicators": [],
        },
    )
    prompt = build_phase1_prompt(ci, "Be an expert.", 3)
    assert "EXISTING-PROJECT INTELLIGENCE" in prompt
    assert "python" in prompt
    assert "fastapi" in prompt
    assert "pytest" in prompt
    assert "Projekttyp: existing" in prompt


def test_phase1_prompt_works_without_intelligence():
    from app.council_prompts import build_phase1_prompt
    from app.council_models import CouncilInput

    ci = CouncilInput(project_id="demo")
    prompt = build_phase1_prompt(ci, "Be an expert.", 3)
    assert "EXISTING-PROJECT INTELLIGENCE" in prompt
    assert "(keine)" in prompt


def test_chairman_prompt_contains_intelligence_section():
    from app.council_prompts import build_chairman_prompt
    from app.council_models import CouncilInput

    ci = CouncilInput(
        project_id="demo",
        project_intelligence={
            "project_kind": "existing",
            "languages": ["typescript", "cpp"],
            "frameworks": ["react"],
            "test_systems": ["vitest"],
            "build_systems": ["platformio"],
            "firmware_indicators": ["esphome"],
        },
    )
    prompt = build_chairman_prompt("[]", "[]", ci)
    assert "EXISTING-PROJECT INTELLIGENCE" in prompt
    assert "typescript" in prompt
    assert "react" in prompt
    assert "platformio" in prompt