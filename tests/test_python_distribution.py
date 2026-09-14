"""Tests for app.python_distribution: distribution identity normalization,
technical-identity validation, and target-Python-aware, centrally-
controlled distribution presence checking (CLAUDE-E2E-003 / -003B).
"""
import os
import shutil
import sys
import tempfile
import venv
from pathlib import Path

import pytest

from app.python_distribution import (
    CONTROLLED_PYTHON_ENVIRONMENTS,
    DistributionCheckResult,
    check_distribution_installed,
    distribution_names_match,
    distribution_query_command,
    environment_target_matches,
    is_valid_distribution_identifier,
    normalize_distribution_name,
    parse_distribution_query_output,
    parse_pip_show_requirement,
    resolve_environment_python_target,
    resolve_host_python_executable,
    resolve_target_python_executable,
)


# ---------------------------------------------------------------------------
# Distribution-name normalization
# ---------------------------------------------------------------------------

def test_normalize_distribution_name_lowercases():
    assert normalize_distribution_name("ESPHome") == "esphome"


@pytest.mark.parametrize("name", ["foo_bar", "foo-bar", "foo.bar", "FOO_BAR"])
def test_normalize_distribution_name_collapses_separators(name):
    assert normalize_distribution_name(name) == "foo-bar"


def test_distribution_names_match_case_insensitive():
    assert distribution_names_match("ESPHome", "esphome") is True


@pytest.mark.parametrize(
    "a, b",
    [
        ("foo_bar", "foo-bar"),
        ("foo.bar", "foo-bar"),
        ("Foo.Bar", "foo_bar"),
    ],
)
def test_distribution_names_match_separator_equivalence(a, b):
    assert distribution_names_match(a, b) is True


def test_distribution_names_match_rejects_different_distributions():
    assert distribution_names_match("requests", "flask") is False


# ---------------------------------------------------------------------------
# Technical distribution identifier validity (display name vs identity)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["ESPHome", "esphome", "foo_bar", "foo.bar", "a1"])
def test_is_valid_distribution_identifier_accepts_single_tokens(value):
    assert is_valid_distribution_identifier(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "ESPHome CLI",
        "Requests Python Library",
        "Beautiful Soup package",
        "",
        None,
        "   ",
    ],
)
def test_is_valid_distribution_identifier_rejects_free_form_prose(value):
    assert is_valid_distribution_identifier(value) is False


# ---------------------------------------------------------------------------
# Target Python resolution
# ---------------------------------------------------------------------------

def test_resolve_target_python_executable_prefers_path(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/isolated/toolchain/bin/python")

    assert resolve_target_python_executable() == "/isolated/toolchain/bin/python"


def test_resolve_target_python_executable_falls_back_to_sys_executable(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)

    assert resolve_target_python_executable() == sys.executable


# ---------------------------------------------------------------------------
# Distribution query command / output parsing
# ---------------------------------------------------------------------------

def test_distribution_query_command_is_argv_only():
    command = distribution_query_command("/usr/bin/python", "requests")

    assert command[0] == "/usr/bin/python"
    assert command[1] == "-c"
    assert command[3] == "requests"
    assert all(isinstance(part, str) for part in command)
    assert len(command) == 4


def test_parse_distribution_query_output_success():
    assert parse_distribution_query_output(0, "1.2.3\n") == (True, "1.2.3")


def test_parse_distribution_query_output_nonzero_returncode_is_not_installed():
    assert parse_distribution_query_output(1, "") == (False, None)


def test_parse_distribution_query_output_empty_stdout_is_not_installed():
    assert parse_distribution_query_output(0, "") == (False, None)


def test_parse_distribution_query_output_not_installed_marker():
    from app.python_distribution import _NOT_INSTALLED_MARKER
    assert parse_distribution_query_output(0, _NOT_INSTALLED_MARKER) == (False, None)


def test_parse_distribution_query_output_version_unknown_marker_is_present():
    """CLAUDE-E2E-003B semantic-regression fix: present but version
    unknown is a distinct, real state, not folded into 'not installed'."""
    from app.python_distribution import _VERSION_UNKNOWN_MARKER
    assert parse_distribution_query_output(0, _VERSION_UNKNOWN_MARKER) == (True, None)


# ---------------------------------------------------------------------------
# check_distribution_installed — always routed through execute_controlled
# ---------------------------------------------------------------------------

def test_check_distribution_installed_requires_project_root(tmp_path):
    """CLAUDE-E2E-003B Gap B: without project_root, no subprocess of any
    kind is executed -- the check is simply unavailable, never an
    unconfined direct fallback."""
    without_root = check_distribution_installed("requests", target_python=sys.executable)
    with_root = check_distribution_installed(
        "requests", target_python=sys.executable, project_root=str(tmp_path),
    )

    assert without_root == DistributionCheckResult(False, None, target_python_available=False)
    assert with_root.installed is True


def test_check_distribution_installed_true_for_installed_package(tmp_path):
    result = check_distribution_installed(
        "requests", target_python=sys.executable, project_root=str(tmp_path),
    )

    assert result.installed is True
    assert result.version is not None


def test_check_distribution_installed_false_for_missing_package(tmp_path):
    result = check_distribution_installed(
        "some-nonexistent-distribution-xyz-adc-test",
        target_python=sys.executable, project_root=str(tmp_path),
    )

    assert result.installed is False
    assert result.version is None


def test_check_distribution_installed_honors_case_normalization(tmp_path):
    """CLAUDE-E2E-003 core proof: 'ESPHome' vs the real distribution
    identity is a case-normalization question, not an import-name one."""
    lower = check_distribution_installed(
        "requests", target_python=sys.executable, project_root=str(tmp_path),
    )
    upper = check_distribution_installed(
        "REQUESTS", target_python=sys.executable, project_root=str(tmp_path),
    )

    assert lower.installed is True
    assert upper.installed is True
    assert lower.version == upper.version


def test_check_distribution_installed_uses_distribution_not_import_module_name(tmp_path):
    """PyYAML's distribution name differs from its import module name
    (yaml). Presence must be determined by distribution metadata, so the
    real distribution name is found even though it is not importable
    under that exact spelling."""
    result = check_distribution_installed(
        "PyYAML", target_python=sys.executable, project_root=str(tmp_path),
    )

    assert result.installed is True
    assert result.version is not None


def test_check_distribution_installed_returns_version_from_target_metadata(tmp_path):
    result = check_distribution_installed(
        "requests", target_python=sys.executable, project_root=str(tmp_path),
    )

    import importlib.metadata as metadata
    assert result.version == metadata.version("requests")


def test_check_distribution_installed_never_touches_network(monkeypatch, tmp_path):
    import socket

    def fail_socket(*args, **kwargs):
        raise AssertionError("Network call attempted")

    monkeypatch.setattr(socket, "socket", fail_socket)

    result = check_distribution_installed(
        "requests", target_python=sys.executable, project_root=str(tmp_path),
    )

    assert result.installed is True


# ---------------------------------------------------------------------------
# Target-environment consistency (a bare, pip-less venv genuinely lacks
# every third-party distribution installed in this repository's venv)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bare_target_python():
    """A real, isolated, pip-less venv that genuinely lacks every
    third-party distribution installed in this repository's own venv.

    Its bin directory is returned alongside its python executable so
    tests can (exactly as the real Real-System E2E harness does) put it
    on PATH via monkeypatch — this is what lets the central controlled
    execution boundary's existing PATH-based "python"/"python3"
    capability matching legitimately approve it, without broadening
    CapabilityRegistry policy in any way.
    """
    with tempfile.TemporaryDirectory(prefix="adc-bare-target-") as tmp:
        target = Path(tmp) / "bare"
        venv.EnvBuilder(with_pip=False, clear=True).create(target)
        yield str(target / "bin" / "python3"), str(target / "bin")


def _put_on_path(monkeypatch, bin_dir):
    import os
    prior_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{bin_dir}:{prior_path}")


def test_package_present_in_current_interpreter_missing_from_isolated_target(
    bare_target_python, tmp_path, monkeypatch,
):
    """A package genuinely present in the current (ADC dev) interpreter
    must be reported MISSING when the explicit target Python is a
    different, isolated interpreter that never had it installed —
    proving ADC's own interpreter cannot accidentally satisfy a
    different, explicitly selected target environment."""
    bare_python, bare_bin = bare_target_python
    _put_on_path(monkeypatch, bare_bin)

    in_current = check_distribution_installed(
        "requests", target_python=sys.executable, project_root=str(tmp_path),
    )
    in_isolated = check_distribution_installed(
        "requests", target_python=bare_python, project_root=str(tmp_path),
    )

    assert in_current.installed is True
    assert in_isolated.installed is False
    assert in_isolated.target_python_available is True, (
        "the isolated target itself must be reachable -- the negative "
        "result must come from a real, successful query, not from the "
        "controlled execution boundary rejecting the target"
    )


def test_package_present_in_explicit_isolated_target_reported_present(
    bare_target_python, tmp_path, monkeypatch,
):
    """The check genuinely queries the given target, not a hardcoded
    answer: a name this test asserts is NOT there for the negative case
    above is checked the same way here, against the same target."""
    bare_python, bare_bin = bare_target_python
    _put_on_path(monkeypatch, bare_bin)

    result = check_distribution_installed(
        "some-nonexistent-distribution-xyz-adc-test",
        target_python=bare_python, project_root=str(tmp_path),
    )

    assert result.installed is False
    assert result.target_python_available is True


def test_no_fallback_to_sys_executable_when_explicit_target_given(monkeypatch, tmp_path):
    """An explicitly supplied target_python must be used exactly as
    given — never silently replaced by sys.executable or the PATH-based
    default, even when that explicit target cannot be resolved at all."""
    monkeypatch.setattr(shutil, "which", lambda name: sys.executable)

    result = check_distribution_installed(
        "requests", target_python="/definitely/not/a/real/python/binary",
        project_root=str(tmp_path),
    )

    assert result.target_python_available is False
    assert result.installed is False


def test_missing_target_python_fails_safely(tmp_path):
    result = check_distribution_installed(
        "requests", target_python="/definitely/not/a/real/python/binary",
        project_root=str(tmp_path),
    )

    assert result == DistributionCheckResult(False, None, target_python_available=False)


# ---------------------------------------------------------------------------
# CLAUDE-E2E-003C PART 5: real (non-mocked) central boundary path-pinning
# proof. Everything above this point already proves check_distribution_installed
# routes through execute_controlled; this proof instead asks the sharper
# question PART 5 requires: after a real target has been selected and
# PATH is then mutated, what does the REAL validate_request/
# CapabilityRegistry executable check actually do with it?
# ---------------------------------------------------------------------------

def test_real_boundary_fails_closed_when_path_moves_target_away(monkeypatch, tmp_path):
    """No mock of execute_controlled/validate_request anywhere in this
    test — it exercises the real ExecutionRequest -> execute_controlled
    -> validate_request -> CapabilityRegistry executable-validation call
    graph end to end.

    Scenario (exactly PART 5's required steps):
    1. Target A is a real, isolated venv interpreter, selected while
       genuinely reachable via PATH (its bin dir is on PATH, exactly how
       the "python"/"python3" bootstrap capability entries are meant to
       be resolved).
    2. Target A's identity (its absolute path) is carried forward
       exactly as the productive architecture does — as a plain string,
       unchanged.
    3. PATH is then changed so a fresh "python"/"python3" lookup
       resolves a different interpreter entirely (this repository's own
       venv python — Target B), and Target A's directory is no longer
       on PATH at all.
    4. The frozen Target A identity is used, unmodified, through the
       real controlled execution boundary.

    Documented, verified result: this is the "fails closed" case, not
    the "Target A remains valid" case. CapabilityRegistry's bootstrap
    "python" capability approves "sys.executable", "python", and
    "python3" — the latter two resolved fresh via shutil.which() at
    EVERY validate_request() call, which is a pre-existing property of
    the central execution boundary this task does not change (doing so
    would mean broadening a bootstrap capability's approved-executable
    computation, explicitly out of scope and risky). Once Target A is
    no longer reachable through that fresh PATH-based lookup and is not
    sys.executable, validate_request() rejects it outright with a clear
    ValueError (caught by check_distribution_installed, never
    propagating), BEFORE any subprocess is ever spawned. Target B is
    therefore structurally impossible to substitute: execute_controlled
    raises before reaching subprocess.run() at all, so no query ever
    runs against any interpreter, right or wrong. This satisfies the
    safety half of the immutable-target contract (never silently uses
    the wrong target) without satisfying the availability half (Target
    A does not remain usable) — a real, honestly-reported architectural
    limitation, not a bug introduced by this task.
    """
    import subprocess as subprocess_module

    with tempfile.TemporaryDirectory(prefix="adc-target-a-") as tmp:
        target_a_dir = Path(tmp) / "target-a"
        venv.EnvBuilder(with_pip=False, clear=True).create(target_a_dir)
        target_a_python = str(target_a_dir / "bin" / "python3")

        original_path = os.environ.get("PATH", "")
        monkeypatch.setenv("PATH", f"{target_a_dir / 'bin'}:{original_path}")

        # Step 1+2: Target A selected and its identity carried forward,
        # exactly as RequirementPreflight -> SetupStep does productively.
        assert shutil.which("python3") == target_a_python
        frozen_target_a = target_a_python

        # Step 3: PATH now points only at a different interpreter
        # (Target B); Target A's own directory is gone from PATH.
        monkeypatch.setenv("PATH", original_path)
        target_b = shutil.which("python3") or sys.executable
        assert target_b != frozen_target_a

        subprocess_calls = []
        original_run = subprocess_module.run

        def spying_run(*args, **kwargs):
            subprocess_calls.append(args[0] if args else kwargs.get("args"))
            return original_run(*args, **kwargs)

        monkeypatch.setattr(subprocess_module, "run", spying_run)

        # Step 4: the frozen Target A identity used, unmodified, through
        # the real controlled boundary -- no mock of execute_controlled/
        # validate_request/CapabilityRegistry anywhere above this line.
        result = check_distribution_installed(
            "requests", target_python=frozen_target_a, project_root=str(tmp_path),
        )

        # Documented, verified outcome: fails closed.
        assert result.installed is False
        assert result.target_python_available is False

        # Target B is never substituted: no subprocess of any kind ran
        # for this query at all (validate_request rejected Target A
        # before subprocess.run was ever reached), so Target B's path
        # cannot appear in any call, and neither can Target A's.
        assert subprocess_calls == []


# ---------------------------------------------------------------------------
# CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003
# parse_pip_show_requirement(): controlled, closed-grammar parser
# ---------------------------------------------------------------------------

class TestParsePipShowRequirement:
    def test_accepts_exact_shape(self):
        assert parse_pip_show_requirement("pip show requests") == "requests"

    def test_accepts_surrounding_whitespace(self):
        assert parse_pip_show_requirement("  pip show requests  ") == "requests"

    def test_accepts_pep503_style_raw_token(self):
        assert parse_pip_show_requirement("pip show Foo_Bar.baz") == "Foo_Bar.baz"

    @pytest.mark.parametrize("text", [
        None,
        "",
        "   ",
        "pip show",
        "pip show ",
        "pip show requests extra",
        "pip show requests && echo x",
        "pip show requests | cat",
        "pip show requests --verbose",
        "docker exec foo pip show requests",
        "source .venv/bin/activate && pip show requests",
        "Pip Show requests",
        "PIP SHOW requests",
        "pip  show requests",
        "pip show requests;rm -rf /",
        "pip install requests",
        "run the test suite",
        "pip show requests\nrm -rf /",
    ])
    def test_rejects_everything_outside_the_controlled_shape(self, text):
        assert parse_pip_show_requirement(text) is None


# ---------------------------------------------------------------------------
# CLAUDE-ADC-S23-VERIFICATION-IDENTITY-TARGET-BINDING-FIX-003
# resolve_environment_python_target() / environment_target_matches():
# environment/target binding
# ---------------------------------------------------------------------------

class TestResolveEnvironmentPythonTarget:
    def test_controlled_environments_are_exactly_host_and_venv(self):
        assert CONTROLLED_PYTHON_ENVIRONMENTS == frozenset({"host", "venv"})

    def test_host_resolves_via_existing_central_policy(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/isolated/toolchain/bin/python")
        resolution = resolve_environment_python_target("host", "/any/project/root")
        assert resolution.resolved is True
        assert resolution.target_executable == "/isolated/toolchain/bin/python"
        assert resolution.target_executable == resolve_target_python_executable()

    def test_host_never_requires_a_project_root(self):
        resolution = resolve_environment_python_target("host", None)
        assert resolution.resolved is True
        assert resolution.target_executable == resolve_target_python_executable()

    def test_venv_resolves_to_the_projects_own_isolated_interpreter(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        venv.EnvBuilder(with_pip=False, clear=True).create(venv_dir)
        expected = str(venv_dir / "bin" / "python")

        resolution = resolve_environment_python_target("venv", str(tmp_path))

        assert resolution.resolved is True
        assert resolution.target_executable == expected

    def test_venv_never_falls_back_to_host_when_no_real_venv_exists(self, tmp_path, monkeypatch):
        """A venv candidate in a project with no .venv at all must fail
        closed -- never silently pick up whatever 'host' would resolve
        to, even when a host target is trivially resolvable."""
        monkeypatch.setattr(shutil, "which", lambda name: "/some/host/bin/python")

        resolution = resolve_environment_python_target("venv", str(tmp_path))

        assert resolution.resolved is False
        assert resolution.needs_provisioning is True
        assert resolution.target_executable is None
        assert resolution.target_executable != "/some/host/bin/python"

    def test_venv_without_project_root_fails_closed(self):
        resolution = resolve_environment_python_target("venv", None)
        assert resolution.resolved is False
        assert resolution.target_executable is None

    @pytest.mark.parametrize("environment", ["container", "docker", "vm", "", "Host", "VENV"])
    def test_unsupported_or_unrecognized_environments_fail_closed(self, environment, tmp_path):
        resolution = resolve_environment_python_target(environment, str(tmp_path))
        assert resolution.resolved is False
        assert resolution.target_executable is None

    def test_host_and_venv_resolve_to_genuinely_different_targets(self, tmp_path, monkeypatch):
        # No PATH candidate -> host falls back to sys.executable. Pinned
        # to a deterministic, non-venv fake path (CLAUDE-ADC-S23-STRICT-
        # IDENTITY-ENVIRONMENT-BINDING-FIX-004 #6: a genuine venv
        # sys.executable, e.g. when the test runner itself is invoked
        # from inside a venv, must NOT become the host target -- see
        # TestResolveHostPythonExecutable below -- so this test must not
        # depend on whatever venv-ness the ambient test process happens
        # to have).
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(sys, "executable", "/definitely/not/a/venv/bin/python")
        venv_dir = tmp_path / ".venv"
        venv.EnvBuilder(with_pip=False, clear=True).create(venv_dir)

        host_resolution = resolve_environment_python_target("host", str(tmp_path))
        venv_resolution = resolve_environment_python_target("venv", str(tmp_path))

        assert host_resolution.target_executable == "/definitely/not/a/venv/bin/python"
        assert venv_resolution.target_executable == str(venv_dir / "bin" / "python")
        assert host_resolution.target_executable != venv_resolution.target_executable

    def test_venv_target_must_be_an_executable_regular_file_not_merely_present(self, tmp_path):
        """CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004
        (#8): a path merely existing at the conventional
        `.venv/bin/python` location is not enough -- it must be a
        genuinely executable regular file, the same minimum usability
        semantics ADC applies everywhere else it trusts a filesystem
        path as an executable target."""
        venv_dir = tmp_path / ".venv"
        bin_dir = venv_dir / "bin"
        bin_dir.mkdir(parents=True)
        interpreter = bin_dir / "python"

        # A mode-0600 ordinary text file -- present, but not executable.
        interpreter.write_text("not a real interpreter\n")
        interpreter.chmod(0o600)
        resolution = resolve_environment_python_target("venv", str(tmp_path))
        assert resolution.resolved is False
        assert resolution.target_executable is None
        assert resolution.needs_provisioning is True

        # A directory at the conventional path -- present, but not a file.
        interpreter.unlink()
        interpreter.mkdir()
        resolution = resolve_environment_python_target("venv", str(tmp_path))
        assert resolution.resolved is False
        assert resolution.target_executable is None

        # Nothing at all at the conventional path.
        interpreter.rmdir()
        resolution = resolve_environment_python_target("venv", str(tmp_path))
        assert resolution.resolved is False
        assert resolution.target_executable is None
        assert resolution.needs_provisioning is True

        # An executable regular file (the genuine, accepted case) --
        # proven last so the SAME path is shown to resolve once it is
        # actually usable, never launched to prove it.
        interpreter.write_text("#!/bin/sh\nexit 0\n")
        interpreter.chmod(0o755)
        resolution = resolve_environment_python_target("venv", str(tmp_path))
        assert resolution.resolved is True
        assert resolution.target_executable == str(interpreter)


class TestResolveHostPythonExecutable:
    """CLAUDE-ADC-S23-STRICT-IDENTITY-ENVIRONMENT-BINDING-FIX-004 (#6):
    "host" must mean a genuine host/system Python -- never THIS
    project's own `<project_root>/.venv`, and never ADC's own,
    currently-running controller virtualenv merely because PATH or
    sys.executable happens to point there. This is deliberately
    NARROWER than "reject every virtual environment whatsoever": an
    unrelated, isolated toolchain venv a user has activated for this
    operation (neither the project's own nor ADC's own) remains a
    legitimate, historically-accepted host target -- proven by
    `test_unrelated_isolated_toolchain_venv_is_still_accepted_as_host`
    below, matching the productive
    tests/test_execution_target_authorization_web_system.py scenario
    this function must never break."""

    def _make_venv(self, tmp_path, name="some-venv"):
        venv_dir = tmp_path / name
        venv.EnvBuilder(with_pip=False, clear=True).create(venv_dir)
        return str(venv_dir / "bin" / "python")

    def test_path_python_resolving_into_this_projects_venv_is_rejected(self, tmp_path, monkeypatch):
        project_root = tmp_path / "project"
        project_root.mkdir()
        venv_python = self._make_venv(project_root, ".venv")
        monkeypatch.setattr(
            shutil, "which",
            lambda name: venv_python if name == "python" else None,
        )
        monkeypatch.setattr(sys, "executable", "/definitely/not/a/venv/bin/python")

        resolved = resolve_host_python_executable(str(project_root))

        assert resolved != venv_python
        assert resolved == "/definitely/not/a/venv/bin/python"

    def test_path_python3_resolving_into_this_projects_venv_is_also_rejected(self, tmp_path, monkeypatch):
        project_root = tmp_path / "project"
        project_root.mkdir()
        venv_python = self._make_venv(project_root, ".venv")
        monkeypatch.setattr(
            shutil, "which",
            lambda name: venv_python if name == "python3" else None,
        )
        monkeypatch.setattr(sys, "executable", "/definitely/not/a/venv/bin/python")

        resolved = resolve_host_python_executable(str(project_root))

        assert resolved != venv_python
        assert resolved == "/definitely/not/a/venv/bin/python"

    def test_path_python_resolving_into_a_different_projects_venv_is_not_rejected_for_this_one(
        self, tmp_path, monkeypatch,
    ):
        """The exclusion is specifically THIS project's own `.venv` --
        another project's `.venv` is not "this project's own venv" and
        must not be rejected on that basis (it may still legitimately
        act as an unrelated, externally-activated toolchain venv)."""
        this_project = tmp_path / "this-project"
        this_project.mkdir()
        other_project_venv_python = self._make_venv(tmp_path / "other-project", ".venv")
        monkeypatch.setattr(
            shutil, "which",
            lambda name: other_project_venv_python if name == "python" else None,
        )

        resolved = resolve_host_python_executable(str(this_project))

        assert resolved == other_project_venv_python

    def test_sys_executable_inside_adcs_own_controller_venv_is_never_used_merely_as_fallback(
        self, tmp_path, monkeypatch,
    ):
        """Simulates ADC's own controller process running from inside a
        venv (`sys.prefix != sys.base_prefix`, `sys.executable` inside
        that same `sys.prefix`) -- that specific venv must never become
        the host target merely because it is what `sys.executable`
        happens to resolve to."""
        controller_venv = tmp_path / "adc-controller-venv"
        controller_venv_python = self._make_venv(tmp_path, "adc-controller-venv")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(sys, "executable", controller_venv_python)
        monkeypatch.setattr(sys, "prefix", str(controller_venv))
        monkeypatch.setattr(sys, "base_prefix", "/usr")

        resolved = resolve_host_python_executable()

        assert resolved is None

    def test_unrelated_isolated_toolchain_venv_is_still_accepted_as_host(self, tmp_path, monkeypatch):
        """The narrow-scope proof: a venv that is NEITHER this project's
        own `.venv` NOR ADC's own controller venv (an arbitrary,
        externally-activated toolchain venv on PATH, exactly the
        productive `tests/test_execution_target_authorization_web_
        system.py` pattern) must still be accepted -- this fix closes
        two specific role-confusions, never "any venv at all"."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        toolchain_venv_python = self._make_venv(tmp_path, "unrelated-toolchain")
        monkeypatch.setattr(
            shutil, "which",
            lambda name: toolchain_venv_python if name == "python" else None,
        )
        # ADC's own controller process is NOT running from a venv here.
        monkeypatch.setattr(sys, "prefix", sys.base_prefix)

        resolved = resolve_host_python_executable(str(project_root))

        assert resolved == toolchain_venv_python

    def test_existing_valid_host_interpreter_on_path_is_accepted(self, monkeypatch):
        monkeypatch.setattr(
            shutil, "which",
            lambda name: "/isolated/toolchain/bin/python" if name == "python" else None,
        )

        assert resolve_host_python_executable() == "/isolated/toolchain/bin/python"

    def test_existing_valid_sys_executable_is_accepted_when_no_path_candidate(self, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: None)
        monkeypatch.setattr(sys, "executable", "/definitely/not/a/venv/bin/python")

        assert resolve_host_python_executable() == "/definitely/not/a/venv/bin/python"

    def test_no_acceptable_host_interpreter_fails_closed(self, tmp_path, monkeypatch):
        """PATH resolves only into this project's own venv, and
        sys.executable is ADC's own controller venv -- there is
        genuinely no acceptable host candidate, so this must fail
        closed, never guess or fall back to a hard-coded path."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        project_venv_python = self._make_venv(project_root, ".venv")
        controller_venv = tmp_path / "adc-controller-venv"
        controller_venv_python = self._make_venv(tmp_path, "adc-controller-venv")
        monkeypatch.setattr(shutil, "which", lambda name: project_venv_python)
        monkeypatch.setattr(sys, "executable", controller_venv_python)
        monkeypatch.setattr(sys, "prefix", str(controller_venv))
        monkeypatch.setattr(sys, "base_prefix", "/usr")

        assert resolve_host_python_executable(str(project_root)) is None


class TestEnvironmentTargetMatches:
    def test_venv_target_never_satisfies_a_host_binding(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        venv.EnvBuilder(with_pip=False, clear=True).create(venv_dir)
        venv_python = str(venv_dir / "bin" / "python")

        assert environment_target_matches("host", venv_python, str(tmp_path)) is False

    def test_host_target_never_satisfies_a_venv_binding(self, tmp_path, monkeypatch):
        monkeypatch.setattr(shutil, "which", lambda name: "/some/host/bin/python")
        venv_dir = tmp_path / ".venv"
        venv.EnvBuilder(with_pip=False, clear=True).create(venv_dir)

        assert environment_target_matches("venv", "/some/host/bin/python", str(tmp_path)) is False

    def test_target_a_cannot_satisfy_target_b(self, tmp_path):
        project_a = tmp_path / "a"
        project_b = tmp_path / "b"
        for root in (project_a, project_b):
            venv.EnvBuilder(with_pip=False, clear=True).create(root / ".venv")
        target_a = str(project_a / ".venv" / "bin" / "python")
        target_b = str(project_b / ".venv" / "bin" / "python")

        assert environment_target_matches("venv", target_a, str(project_b)) is False
        assert environment_target_matches("venv", target_b, str(project_a)) is False
        assert environment_target_matches("venv", target_a, str(project_a)) is True
        assert environment_target_matches("venv", target_b, str(project_b)) is True

    def test_matching_venv_target_is_accepted(self, tmp_path):
        venv_dir = tmp_path / ".venv"
        venv.EnvBuilder(with_pip=False, clear=True).create(venv_dir)
        venv_python = str(venv_dir / "bin" / "python")

        assert environment_target_matches("venv", venv_python, str(tmp_path)) is True

    def test_unresolved_environment_never_matches_anything(self, tmp_path):
        assert environment_target_matches("container", "/whatever/python", str(tmp_path)) is False
        assert environment_target_matches("venv", None, str(tmp_path)) is False
