import app.project_files as project_files


def test_cli_uses_shared_reader_module():
    assert project_files.MAX_FILE_SIZE == 1_000_000
    assert project_files.read_project_files is not None


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
    assert warnings == [f"Skipping large file: large.bin"]
