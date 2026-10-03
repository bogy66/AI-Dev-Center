from pathlib import Path
from unittest.mock import Mock

import pytest

from app.greenfield_project import GreenfieldProjectApproval, GreenfieldProjectMaterializer


def test_greenfield_materialization_requires_exact_explicit_approval(tmp_path):
    materializer = GreenfieldProjectMaterializer()
    with pytest.raises(ValueError, match="approval"):
        materializer.materialize(GreenfieldProjectApproval(
            "run", "project", str(tmp_path / "target"), "", "pending",
        ))


def test_greenfield_materialization_rejects_existing_target(tmp_path):
    with pytest.raises(ValueError, match="absent"):
        GreenfieldProjectMaterializer().materialize(GreenfieldProjectApproval(
            "run", "project", str(tmp_path), "tester",
        ))


def test_greenfield_materialization_uses_fixed_git_initialization(tmp_path, monkeypatch):
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr("app.greenfield_project.subprocess.run", run)
    target = tmp_path / "owned-project"
    result = GreenfieldProjectMaterializer().materialize(GreenfieldProjectApproval(
        "run", "project", str(target), "real-e2e-operator",
    ))
    assert result == target.resolve()
    assert target.is_dir()
    run.assert_called_once_with(
        ["git", "init", "--", str(target.resolve())],
        capture_output=True, text=True, check=False,
    )
