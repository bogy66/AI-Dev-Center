"""Hermetic, network-free local Python package fixture for tests.

Builds a minimal, valid wheel by hand (no network access, no build
tool such as `pip install build`) and configures a target venv's own
`pip.conf` to install exclusively from it (`no-index` + `find-links`
pointing at a local `file://` directory). This lets a test exercise a
REAL `pip install <name>` subprocess, through the real
PythonPackageExecutor/execute_controlled boundary, with real
post-install `importlib.metadata` verification -- without any PyPI or
other network dependency (CLAUDE-E2E-003G Part 9).
"""
from __future__ import annotations

import shlex
import venv
import zipfile
from pathlib import Path

PACKAGE_NAME = "adc-fixture-pkg"
PACKAGE_IMPORT_NAME = "adc_fixture_pkg"
PACKAGE_VERSION = "0.0.1"


def build_local_wheel_index(tmp_path: Path) -> Path:
    """Build one minimal, valid wheel for PACKAGE_NAME under tmp_path
    and return the directory containing it (usable as a pip find-links
    target)."""
    wheels_dir = tmp_path / "local-wheels"
    wheels_dir.mkdir(exist_ok=True)
    wheel_path = wheels_dir / f"{PACKAGE_IMPORT_NAME}-{PACKAGE_VERSION}-py3-none-any.whl"

    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: {PACKAGE_NAME}\n"
        f"Version: {PACKAGE_VERSION}\n"
    )
    wheel_meta = (
        "Wheel-Version: 1.0\n"
        "Generator: adc-test-fixture\n"
        "Root-Is-Purelib: true\n"
        "Tag: py3-none-any\n"
    )
    dist_info = f"{PACKAGE_IMPORT_NAME}-{PACKAGE_VERSION}.dist-info"
    record = (
        f"{PACKAGE_IMPORT_NAME}/__init__.py,,\n"
        f"{dist_info}/METADATA,,\n"
        f"{dist_info}/WHEEL,,\n"
        f"{dist_info}/RECORD,,\n"
    )

    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{PACKAGE_IMPORT_NAME}/__init__.py", "")
        zf.writestr(f"{dist_info}/METADATA", metadata)
        zf.writestr(f"{dist_info}/WHEEL", wheel_meta)
        zf.writestr(f"{dist_info}/RECORD", record)

    return wheels_dir


def build_isolated_toolchain(tmp_path: Path, name: str, wheels_dir: Path) -> str:
    """A real, isolated venv with pip, configured to install exclusively
    from wheels_dir (no PyPI/network access needed). Returns the
    interpreter's absolute path."""
    toolchain_dir = tmp_path / name
    venv.EnvBuilder(with_pip=True, clear=True).create(toolchain_dir)
    (toolchain_dir / "pip.conf").write_text(
        "[global]\n"
        "no-index = true\n"
        f"find-links = file://{wheels_dir}\n"
    )
    return str(toolchain_dir / "bin" / "python")


def build_launch_counting_target(
    tmp_path: Path, name: str, wheels_dir: Path,
) -> tuple[str, Path]:
    """A real, isolated venv (as build_isolated_toolchain), fronted by a
    thin shell-script wrapper that atomically appends one line to a
    counter file before `exec`-ing the real interpreter with the exact
    same arguments it received.

    This gives a REAL, observable, subprocess.run()-independent launch
    count (CLAUDE-E2E-003H Part 9: "Do NOT satisfy this requirement
    solely by mocking subprocess.run"): every real process launch of
    this target -- pip install AND post-install verification alike --
    appends one line, regardless of what PythonPackageExecutor/
    execute_controlled do internally. The wrapper's own path is what
    gets used/registered as target_executable, so the central
    execution-target-authorization boundary (CLAUDE-E2E-003E/F/G) pins
    and validates it exactly like any other executable identity.

    Returns (wrapper_path, counter_file_path).
    """
    real_python = build_isolated_toolchain(tmp_path, name, wheels_dir)
    counter_file = tmp_path / f"{name}-launch-count.txt"
    # Named "python", inside its own bin/ directory, so a caller that
    # prepends this directory to PATH and resolves "python" via
    # shutil.which() (as RequirementPreflight does) finds the wrapper,
    # not the real interpreter directly.
    wrapper_dir = tmp_path / f"{name}-wrapper" / "bin"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = wrapper_dir / "python"
    wrapper_path.write_text(
        "#!/bin/sh\n"
        f"echo launch >> {shlex.quote(str(counter_file))}\n"
        f"exec {shlex.quote(real_python)} \"$@\"\n"
    )
    wrapper_path.chmod(0o755)
    return str(wrapper_path), counter_file


def read_launch_count(counter_file: Path) -> int:
    if not Path(counter_file).exists():
        return 0
    return len([line for line in Path(counter_file).read_text().splitlines() if line.strip()])
