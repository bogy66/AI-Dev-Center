from pathlib import Path
from unittest.mock import Mock

import pytest

from app.project_inspector import ProjectInspector
from app.project_files import read_project_files


def test_inspector_reuses_existing_file_reader_and_preserves_warnings(tmp_path):
    reader = Mock(return_value=([{"path": "app.py", "content": "pass"}], ["large file"]))
    inspector = ProjectInspector(file_reader=reader)

    project_info = inspector.inspect("demo", tmp_path)

    reader.assert_called_once_with(tmp_path.resolve())
    assert project_info == {
        "project_id": "demo",
        "project_path": str(tmp_path.resolve()),
        "files": [{"path": "app.py", "content": "pass"}],
        "warnings": ["large file"],
    }


def test_inspector_default_reader_is_the_neutral_project_file_reader():
    assert ProjectInspector()._file_reader is read_project_files


@pytest.mark.parametrize("project_id", ["", "   "])
def test_inspector_rejects_empty_project_id(tmp_path, project_id):
    with pytest.raises(ValueError, match="project_id"):
        ProjectInspector(file_reader=Mock()).inspect(project_id, tmp_path)


def test_inspector_rejects_missing_project_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        ProjectInspector(file_reader=Mock()).inspect("demo", tmp_path / "missing")


def test_inspector_propagates_file_reader_errors(tmp_path):
    reader = Mock(side_effect=OSError("cannot inspect"))

    with pytest.raises(OSError, match="cannot inspect"):
        ProjectInspector(file_reader=reader).inspect("demo", tmp_path)
