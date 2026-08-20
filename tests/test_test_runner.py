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
