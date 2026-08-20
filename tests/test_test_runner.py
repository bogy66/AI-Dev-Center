from app.test_runner import TestRunner


def test_run_detects_syntax_error_in_nested_app_file(tmp_path):
    nested = tmp_path / "app" / "nested"
    nested.mkdir(parents=True)

    (nested / "broken.py").write_text(
        "def broken(:\n    pass\n",
        encoding="utf-8",
    )

    result = TestRunner().run(tmp_path)

    assert result["success"] is False
    assert "SyntaxError" in result["stderr"]


def test_run_detects_syntax_error_in_file_outside_app_via_changes(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True)

    broken_content = "def broken(:\n    pass\n"

    (scripts_dir / "broken_script.py").write_text(
        broken_content,
        encoding="utf-8",
    )

    changes = {
        "changes": [
            {
                "file": "scripts/broken_script.py",
                "action": "create",
                "content": broken_content
            }
        ]
    }

    result = TestRunner().run(tmp_path, changes)

    assert result["success"] is False, (
        "Expected TestRunner to detect a syntax error in a Python file "
        "changed outside of app/, but it reported success. This "
        "confirms TestRunner must consider the files reported by "
        "DeveloperChanges instead of only scanning project/app."
    )

    assert "SyntaxError" in result["stderr"]
