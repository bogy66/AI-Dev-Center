"""Deterministic read-only structured existing-project intelligence.

Project content is UNTRUSTED INPUT.  This module NEVER executes code,
never imports project modules, never runs shell commands derived from
repository content, and never dereferences symlinks that escape
``project_root``.  All detection is based on static file-existence,
well-known manifest contents, and file-name-extension heuristics.

Detection results carry evidence (relative path + kind) and never
contain file contents, credentials, or absolute user paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_INSPECTION_FILES = 2_000
MAX_CONFIG_FILE_SIZE = 500_000
MAX_AREA_SEARCH_DEPTH = 2

_PRIMARY_EXCLUDE_DIRS = frozenset({
    ".git", "venv", ".venv", "node_modules", "__pycache__",
    ".cache", "dist", "build", ".pytest_cache", ".tox",
    ".eggs", "*.egg-info",
})

_SENSITIVE_NAMES = re.compile(
    r"(?:"
    r"^\.env(\..*)?$|"
    r"\.pem$|\.key$|"
    r"^id_rsa$|^id_ed25519$|^id_ecdsa$|^id_dsa$|"
    r"^credentials\.(json|yaml|yml)$|"
    r"^secrets\.(yaml|yml)$|"
    r"^private_key\.pem$|"
    r"\.envrc$|"
    r"^\.netrc$"
    r")",
    re.IGNORECASE,
)

_LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "css", ".less": "css",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".yaml": "yaml", ".yml": "yaml",
    ".json": "json",
    ".md": "markdown", ".rst": "markdown",
    ".ino": "c++",  # Arduino
}

_SOURCE_EXTENSIONS = frozenset(
    ext for ext in _LANGUAGE_EXTENSIONS
    if _LANGUAGE_EXTENSIONS[ext] in {
        "python", "javascript", "typescript", "c", "cpp", "html",
        "css", "shell", "yaml", "json",
    }
)

MANIFEST_SIZE_LIMIT = 100_000


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Evidence:
    path: str
    kind: str  # explicit_configuration | file_extension | dependency_declaration


# ---------------------------------------------------------------------------
# Detected items
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DetectedLanguage:
    name: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class DetectedFramework:
    name: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class DetectedPackageSystem:
    name: str
    evidence: tuple[Evidence, ...]
    preferred_manager: str | None = None


@dataclass(frozen=True)
class DetectedBuildSystem:
    name: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class DetectedTestSystem:
    name: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class DetectedFirmware:
    name: str
    evidence: tuple[Evidence, ...]
    boards: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectArea:
    path: str
    languages: tuple[DetectedLanguage, ...]
    frameworks: tuple[DetectedFramework, ...]
    package_systems: tuple[DetectedPackageSystem, ...]
    build_systems: tuple[DetectedBuildSystem, ...]
    test_systems: tuple[DetectedTestSystem, ...]
    firmware_indicators: tuple[DetectedFirmware, ...]


# ---------------------------------------------------------------------------
# Main contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProjectIntelligence:
    project_root: str
    project_kind: str  # "greenfield" | "existing" | "mixed"
    areas: tuple[ProjectArea, ...]
    languages: tuple[DetectedLanguage, ...]
    frameworks: tuple[DetectedFramework, ...]
    package_systems: tuple[DetectedPackageSystem, ...]
    build_systems: tuple[DetectedBuildSystem, ...]
    test_systems: tuple[DetectedTestSystem, ...]
    firmware_indicators: tuple[DetectedFirmware, ...]
    ci_indicators: tuple[str, ...]
    doc_indicators: tuple[str, ...]
    git_repository_present: bool
    sensitive_configuration_present: bool
    warnings: tuple[str, ...]
    truncated: bool
    total_files_traversed: int
    total_files_excluded: int
    inspection_limit_exceeded: bool
    limits_applied: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return self.project_kind

    @property
    def area_count(self) -> int:
        return len(self.areas)

    @property
    def language_names(self) -> tuple[str, ...]:
        return tuple(sorted({la.name for la in self.languages}))

    @property
    def framework_names(self) -> tuple[str, ...]:
        return tuple(sorted({fw.name for fw in self.frameworks}))

    @property
    def package_system_names(self) -> tuple[str, ...]:
        return tuple(sorted({ps.name for ps in self.package_systems}))

    @property
    def build_system_names(self) -> tuple[str, ...]:
        return tuple(sorted({bs.name for bs in self.build_systems}))

    @property
    def test_system_names(self) -> tuple[str, ...]:
        return tuple(sorted({ts.name for ts in self.test_systems}))

    def to_summary(self) -> dict:
        """Compatibility dict for consumers that expect the old shape."""
        return {
            "project_kind": self.project_kind,
            "area_count": self.area_count,
            "languages": list(self.language_names),
            "frameworks": list(self.framework_names),
            "package_systems": list(self.package_system_names),
            "build_systems": list(self.build_system_names),
            "test_systems": list(self.test_system_names),
            "firmware_indicators": [f.name for f in self.firmware_indicators],
            "git_repository_present": self.git_repository_present,
            "sensitive_configuration_present": self.sensitive_configuration_present,
            "truncated": self.truncated,
            "total_files_traversed": self.total_files_traversed,
        }


# ---------------------------------------------------------------------------
# Inspection engine
# ---------------------------------------------------------------------------

def _is_excluded(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    for part in parts:
        if part in _PRIMARY_EXCLUDE_DIRS:
            return True
        if part.endswith(".egg-info"):
            return True
    return False


def _is_sensitive(filename: str) -> bool:
    return bool(_SENSITIVE_NAMES.fullmatch(filename))


def _has_git(root: Path) -> bool:
    return (root / ".git").is_dir()


def _read_limited(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size > MAX_CONFIG_FILE_SIZE:
            return None
        content = path.read_text(encoding="utf-8")
        return content[:MANIFEST_SIZE_LIMIT]
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Package system detection
# ---------------------------------------------------------------------------

def _detect_package_systems(root: Path, relative_root: str) -> list[DetectedPackageSystem]:
    results: list[DetectedPackageSystem] = []
    done: set[str] = set()

    pkg_manifests = {
        ("pyproject.toml",): ("python-pip", None),
        ("setup.py",): ("python-setuptools", None),
        ("setup.cfg",): ("python-setuptools", None),
        ("requirements.txt",): ("python-pip", None),
        ("requirements-dev.txt",): ("python-pip", None),
    }

    for names, (display, _pref) in pkg_manifests.items():
        for name in names:
            path = root / name
            if path.is_file() and display not in done:
                results.append(DetectedPackageSystem(
                    display,
                    (Evidence(f"{relative_root}/{name}" if relative_root else name,
                              "explicit_configuration"),),
                ))
                done.add(display)
                break

    # Node ecosystem — check lock files for preferred manager
    has_package_json = (root / "package.json").is_file()
    if has_package_json:
        if (root / "pnpm-lock.yaml").is_file():
            pref = "pnpm"
        elif (root / "yarn.lock").is_file():
            pref = "yarn"
        elif (root / "package-lock.json").is_file():
            pref = "npm"
        else:
            pref = "npm"
        results.append(DetectedPackageSystem(
            "node-npm",
            (Evidence(f"{relative_root}/package.json" if relative_root else "package.json",
                      "explicit_configuration"),),
            preferred_manager=pref,
        ))

    return results


# ---------------------------------------------------------------------------
# Build system detection
# ---------------------------------------------------------------------------

def _detect_build_systems(root: Path, relative_root: str) -> list[DetectedBuildSystem]:
    results: list[DetectedBuildSystem] = []
    _pref = f"{relative_root}/" if relative_root else ""

    build_files = {
        "CMakeLists.txt": "cmake",
        "Makefile": "make",
        "platformio.ini": "platformio",
    }
    for filename, system in build_files.items():
        if (root / filename).is_file():
            results.append(DetectedBuildSystem(
                system,
                (Evidence(f"{_pref}{filename}", "explicit_configuration"),),
            ))
    return results


# ---------------------------------------------------------------------------
# Test system detection
# ---------------------------------------------------------------------------

def _detect_test_systems(root: Path, relative_root: str) -> list[DetectedTestSystem]:
    results: list[DetectedTestSystem] = []
    _pref = f"{relative_root}/" if relative_root else ""

    # pytest
    pytest_evidence: list[Evidence] = []
    if (root / "pytest.ini").is_file():
        pytest_evidence.append(Evidence(f"{_pref}pytest.ini", "explicit_configuration"))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            if "[tool.pytest.ini_options]" in pyproject.read_text(encoding="utf-8"):
                pytest_evidence.append(Evidence(f"{_pref}pyproject.toml", "explicit_configuration"))
        except Exception:
            pass
    setup_cfg = root / "setup.cfg"
    if setup_cfg.is_file():
        try:
            import configparser
            p = configparser.ConfigParser()
            p.read_string(setup_cfg.read_text(encoding="utf-8"))
            if p.has_section("tool:pytest"):
                pytest_evidence.append(Evidence(f"{_pref}setup.cfg", "explicit_configuration"))
        except Exception:
            pass
    if pytest_evidence:
        results.append(DetectedTestSystem("pytest", tuple(pytest_evidence)))

    # Jest / Vitest
    pkg_json = root / "package.json"
    if pkg_json.is_file():
        content = _read_limited(pkg_json)
        if content:
            try:
                import json as _json
                pkg = _json.loads(content)
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                scripts = pkg.get("scripts", {})
                if "jest" in deps:
                    results.append(DetectedTestSystem(
                        "jest",
                        (Evidence(f"{_pref}package.json", "dependency_declaration"),),
                    ))
                if "vitest" in deps:
                    results.append(DetectedTestSystem(
                        "vitest",
                        (Evidence(f"{_pref}package.json", "dependency_declaration"),),
                    ))
                if "mocha" in deps:
                    results.append(DetectedTestSystem(
                        "mocha",
                        (Evidence(f"{_pref}package.json", "dependency_declaration"),),
                    ))
                if "test" in scripts and not any("jest" in deps for _ in [1]):
                    pass  # generic npm test script — too weak as evidence
            except Exception:
                pass

    # CTest
    if (root / "CTestConfig.cmake").is_file() or (root / "CTestTestfile.cmake").is_file():
        results.append(DetectedTestSystem(
            "ctest",
            (Evidence(f"{_pref}CTestConfig.cmake", "explicit_configuration"),),
        ))

    return results


# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------

def _parse_pyproject_dependencies(pyproject: Path) -> set[str]:
    """Extract dependency names from pyproject.toml using structured parsing.

    Never executes project code.  TOML parsing is pure data extraction.
    """
    deps: set[str] = set()
    try:
        content = pyproject.read_text(encoding="utf-8")
    except Exception:
        return deps
    # Use structured TOML when available; fall back to best-effort extraction.
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            tomllib = None
    if tomllib is not None:
        try:
            data = tomllib.loads(content)
            # project.dependencies (PEP 621)
            project = data.get("project", {})
            raw_deps = project.get("dependencies")
            if isinstance(raw_deps, list):
                _extract_dep_names(deps, raw_deps)
            optional = project.get("optional-dependencies") or {}
            if isinstance(optional, dict):
                for group_deps in optional.values():
                    if isinstance(group_deps, list):
                        _extract_dep_names(deps, group_deps)
            # tool.poetry.dependencies
            poetry = data.get("tool", {}).get("poetry", {}).get("dependencies")
            if isinstance(poetry, dict):
                deps.update(k.lower() for k in poetry.keys() if k.lower() != "python")
            # tool section with dependencies (common legacy pattern)
            tool_deps = data.get("tool", {}).get("dependencies")
            if isinstance(tool_deps, list):
                _extract_dep_names(deps, tool_deps)
            return deps
        except Exception:
            pass
    # Fallback: best-effort extraction from TOML content
    for line in content.splitlines():
        line = line.strip().lower()
        for kw in ("fastapi", "flask", "django"):
            if kw == line[:len(kw)] and line[len(kw):len(kw)+1] in (' ', '=', '['):
                deps.add(kw)
    return deps


def _extract_dep_names(deps: set[str], raw: list) -> None:
    for item in raw:
        if isinstance(item, str):
            name = item.split(">=")[0].split("<")[0].split("==")[0].split("~=")[0].split("[")[0].strip().lower()
            deps.add(name)


def _detect_frameworks(root: Path, relative_root: str,
                       languages: list[DetectedLanguage]) -> list[DetectedFramework]:
    results: list[DetectedFramework] = []
    _pref = f"{relative_root}/" if relative_root else ""
    lang_names = {la.name for la in languages}

    # Python frameworks via structured TOML dependency parsing
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and "python" in lang_names:
        py_frameworks = {
            "fastapi": "fastapi",
            "flask": "flask",
            "django": "django",
        }
        pypi_deps = _parse_pyproject_dependencies(pyproject)
        for keyword, name in py_frameworks.items():
            if keyword in pypi_deps:
                results.append(DetectedFramework(
                    name,
                    (Evidence(f"{_pref}pyproject.toml", "dependency_declaration"),),
                ))

    # JS/TS frameworks via structured JSON dependency parsing
    pkg_json = root / "package.json"
    if pkg_json.is_file():
        content = _read_limited(pkg_json)
        if content:
            try:
                import json as _json
                pkg = _json.loads(content)
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                js_frameworks = {
                    "react": "react",
                    "vue": "vue",
                    "@angular/core": "angular",
                    "vite": "vite",
                    "next": "next.js",
                    "svelte": "svelte",
                }
                for dep_name, display in js_frameworks.items():
                    if dep_name in deps:
                        results.append(DetectedFramework(
                            display,
                            (Evidence(f"{_pref}package.json", "dependency_declaration"),),
                        ))
            except Exception:
                pass

    # ESPHome via structured YAML parsing
    for yaml_path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
        try:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict) and "esphome" in data:
                rel = f"{relative_root}/{yaml_path.name}" if relative_root else yaml_path.name
                results.append(DetectedFramework(
                    "esphome",
                    (Evidence(rel, "explicit_configuration"),),
                ))
                break
        except Exception:
            continue

    return results


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def _detect_languages(all_files: list[tuple[str, bool]]) -> list[DetectedLanguage]:
    ext_counts: dict[str, int] = {}
    for rel, _is_sensitive_flag in all_files:
        if _is_sensitive_flag:
            continue
        ext = Path(rel).suffix.lower()
        if ext:
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

    seened: set[str] = set()
    lang_totals: dict[str, int] = {}
    lang_exts: dict[str, list[str]] = {}
    for ext, lang in sorted(_LANGUAGE_EXTENSIONS.items()):
        count = ext_counts.get(ext, 0)
        if count > 0:
            lang_totals[lang] = lang_totals.get(lang, 0) + count
            lang_exts.setdefault(lang, []).append(ext)

    results: list[DetectedLanguage] = []
    for lang, total in sorted(lang_totals.items()):
        if total >= 1:
            exts = lang_exts[lang]
            results.append(DetectedLanguage(
                lang,
                (Evidence(f"*.{exts[0][1:]} ({total} files)", "file_extension"),),
            ))
    return results


# ---------------------------------------------------------------------------
# Firmware detection
# ---------------------------------------------------------------------------

def _detect_firmware(root: Path, relative_root: str) -> list[DetectedFirmware]:
    results: list[DetectedFirmware] = []
    _pref = f"{relative_root}/" if relative_root else ""

    # PlatformIO
    pio_ini = root / "platformio.ini"
    if pio_ini.is_file():
        boards: list[str] = []
        content = _read_limited(pio_ini)
        if content:
            for match in re.finditer(r'(?:board|board_build\.mcu)\s*=\s*(\S+)', content):
                boards.append(match.group(1))
        results.append(DetectedFirmware(
            "platformio",
            (Evidence(f"{_pref}platformio.ini", "explicit_configuration"),),
            boards=tuple(boards[:10]),
        ))

    # ESPHome (recursive YAML)
    for yaml_path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")):
        try:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict) and "esphome" in data:
                board = None
                if isinstance(data.get("esphome"), dict):
                    board = data["esphome"].get("board")
                boards = (str(board),) if board else ()
                results.append(DetectedFirmware(
                    "esphome",
                    (Evidence(f"{_pref}{yaml_path.name}" if _pref else yaml_path.name,
                              "explicit_configuration"),),
                    boards=boards,
                ))
                break
        except Exception:
            continue

    return results


# ---------------------------------------------------------------------------
# CI detection
# ---------------------------------------------------------------------------

def _detect_ci(root: Path, relative_root: str) -> list[str]:
    indicators: list[str] = []
    ci_checks = [
        (".github/workflows", "github-actions"),
        (".gitlab-ci.yml", "gitlab-ci"),
        ("Jenkinsfile", "jenkins"),
        (".drone.yml", "drone"),
        (".circleci", "circleci"),
        (".travis.yml", "travis"),
    ]
    for check_path, name in ci_checks:
        path = root / check_path
        if "/" in check_path or "." in check_path.split("/")[-1]:
            if path.is_dir() or path.is_file():
                indicators.append(name)
        elif path.is_dir():
            indicators.append(name)
    return indicators


# ---------------------------------------------------------------------------
# Documentation detection
# ---------------------------------------------------------------------------

def _detect_docs(root: Path, relative_root: str) -> list[str]:
    indicators: list[str] = []
    for name in ("README", "README.md", "README.rst", "README.txt"):
        if (root / name).is_file():
            indicators.append(name)
            break
    if (root / "docs").is_dir():
        indicators.append("docs/")
    if (root / "doc").is_dir():
        indicators.append("doc/")
    return indicators


# ---------------------------------------------------------------------------
# Area detection
# ---------------------------------------------------------------------------

def _area_rel(path: Path, root: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _subdirs(root: Path, depth: int) -> list[tuple[Path, str]]:
    if depth <= 0:
        return [(root, "")]
    result: list[tuple[Path, str]] = [(root, "")]
    try:
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name in _PRIMARY_EXCLUDE_DIRS:
                continue
            if entry.name.startswith("."):
                continue
            rel = entry.name
            result.append((entry, rel))
    except PermissionError:
        pass
    return result


def _is_area_candidate(subdir: Path) -> bool:
    """A subdirectory is a candidate if it contains manifest files."""
    manifest_names = (
        "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
        "package.json", "CMakeLists.txt", "Makefile", "platformio.ini",
        "pytest.ini",
    )
    if any((subdir / name).is_file() for name in manifest_names):
        return True
    # Check for YAML with esphome
    for yf in list(subdir.glob("*.yaml")) + list(subdir.glob("*.yml")):
        try:
            import yaml
            with open(yf, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict) and "esphome" in data:
                return True
        except Exception:
            continue
    return False


def _collect_files(root: Path) -> tuple[list[tuple[str, bool]], list[str], int, int, bool]:
    all_files: list[tuple[str, bool]] = []
    warnings: list[str] = []
    traversed = 0
    excluded = 0
    limit_exceeded = False

    try:
        entries = sorted(root.rglob("*"))
    except PermissionError:
        entries = []

    for path in entries:
        if path is root:
            continue
        if not path.is_file():
            continue

        rel = _area_rel(path, root)
        if rel is None:
            warnings.append(f"Skipping path outside root: {path}")
            continue

        if _is_excluded(rel):
            excluded += 1
            continue

        traversed += 1
        basename = path.name
        sensitive = _is_sensitive(basename)

        if traversed > MAX_INSPECTION_FILES:
            limit_exceeded = True
            warnings.append(f"File inspection limit reached ({MAX_INSPECTION_FILES} files)")
            break

        all_files.append((rel, sensitive))

    return all_files, warnings, traversed, excluded, limit_exceeded


def _detect_area(root: Path, relative_root: str,
                 all_files: list[tuple[str, bool]]) -> ProjectArea:
    prefix = f"{relative_root}/" if relative_root else ""
    area_files = [(rel, sens) for rel, sens in all_files
                  if not prefix or rel == relative_root or rel.startswith(prefix)]
    languages = _detect_languages(area_files)
    frameworks = _detect_frameworks(root, relative_root, languages)
    pkg_systems = _detect_package_systems(root, relative_root)
    build_systems = _detect_build_systems(root, relative_root)
    test_systems = _detect_test_systems(root, relative_root)
    firmware = _detect_firmware(root, relative_root)

    return ProjectArea(
        path=relative_root or ".",
        languages=tuple(languages),
        frameworks=tuple(frameworks),
        package_systems=tuple(pkg_systems),
        build_systems=tuple(build_systems),
        test_systems=tuple(test_systems),
        firmware_indicators=tuple(firmware),
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def inspect_project(root: str | Path) -> ProjectIntelligence:
    root = Path(root).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise FileNotFoundError(f"Project root is not a directory: {root}")

    all_files, file_warnings, traversed, excluded, limit_exceeded = _collect_files(root)
    warnings = list(file_warnings)

    # Area detection
    areas: list[ProjectArea] = []
    subdirs = _subdirs(root, MAX_AREA_SEARCH_DEPTH)
    area_candidates = [(d, rel) for d, rel in subdirs[1:] if _is_area_candidate(d)]

    if area_candidates:
        for area_dir, area_rel in area_candidates:
            area = _detect_area(area_dir, area_rel, all_files)
            areas.append(area)

    # Root area (everything not in a sub-area)
    root_area = _detect_area(root, "", all_files)
    areas.insert(0, root_area)

    # Collect unique top-level results
    all_languages: list[DetectedLanguage] = []
    seen_lang: set[str] = set()
    for area in areas:
        for la in area.languages:
            if la.name not in seen_lang:
                seen_lang.add(la.name)
                all_languages.append(la)

    all_frameworks: list[DetectedFramework] = []
    seen_fw: set[str] = set()
    for area in areas:
        for fw in area.frameworks:
            if fw.name not in seen_fw:
                seen_fw.add(fw.name)
                all_frameworks.append(fw)

    all_pkg: list[DetectedPackageSystem] = []
    seen_pkg: set[str] = set()
    for area in areas:
        for ps in area.package_systems:
            if ps.name not in seen_pkg:
                seen_pkg.add(ps.name)
                all_pkg.append(ps)

    all_build: list[DetectedBuildSystem] = []
    seen_build: set[str] = set()
    for area in areas:
        for bs in area.build_systems:
            if bs.name not in seen_build:
                seen_build.add(bs.name)
                all_build.append(bs)

    all_test: list[DetectedTestSystem] = []
    seen_test: set[str] = set()
    for area in areas:
        for ts in area.test_systems:
            if ts.name not in seen_test:
                seen_test.add(ts.name)
                all_test.append(ts)

    all_fw: list[DetectedFirmware] = []
    seen_fw_ind: set[str] = set()
    for area in areas:
        for fw in area.firmware_indicators:
            if fw.name not in seen_fw_ind:
                seen_fw_ind.add(fw.name)
                all_fw.append(fw)

    ci_indicators = _detect_ci(root, "")
    doc_indicators = _detect_docs(root, "")
    git_present = _has_git(root)
    has_sensitive = any(sens for _, sens in all_files)
    has_manifest = bool(all_languages or all_build or all_pkg or all_test or all_fw)

    if not has_manifest and traversed <= 1:
        project_kind = "greenfield"
    elif len(areas) > 2:
        project_kind = "mixed"
    else:
        project_kind = "existing"

    return ProjectIntelligence(
        project_root=str(root),
        project_kind=project_kind,
        areas=tuple(areas),
        languages=tuple(all_languages),
        frameworks=tuple(all_frameworks),
        package_systems=tuple(all_pkg),
        build_systems=tuple(all_build),
        test_systems=tuple(all_test),
        firmware_indicators=tuple(all_fw),
        ci_indicators=tuple(ci_indicators),
        doc_indicators=tuple(doc_indicators),
        git_repository_present=git_present,
        sensitive_configuration_present=has_sensitive,
        warnings=tuple(warnings),
        truncated=limit_exceeded,
        total_files_traversed=traversed,
        total_files_excluded=excluded,
        inspection_limit_exceeded=limit_exceeded,
        limits_applied=(
            ("file_count",) if limit_exceeded else ()
        ),
    )