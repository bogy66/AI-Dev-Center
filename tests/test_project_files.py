import app.project_files as project_files
import app.workflow_cli as workflow_cli


def test_cli_reexports_the_neutral_reader_implementation():
    assert workflow_cli.read_project_files is project_files.read_project_files
    assert workflow_cli.MAX_FILE_SIZE == project_files.MAX_FILE_SIZE


def test_reader_preserves_order_content_and_warnings(tmp_path):
    (tmp_path / "b.py").write_text("b", encoding="utf-8")
    (tmp_path / "a.py").write_text("a", encoding="utf-8")
    (tmp_path / "large.bin").write_bytes(
        b"x" * (project_files.MAX_FILE_SIZE + 1)
    )

    files, warnings = project_files.read_project_files(tmp_path)

    assert files == [
        {"path": "a.py", "content": "a"},
        {"path": "b.py", "content": "b"},
    ]
    assert warnings == [f"Skipping large file: {tmp_path / 'large.bin'}"]
