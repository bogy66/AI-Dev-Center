from unittest.mock import Mock
import pytest
from app.test_change_generator import TestChangeGenerator


def test_generator_returns_structured_changes_without_running_tests():
    executor = Mock()
    executor.run.return_value = "## Dateien\n### Datei: tests/test_x.py\ncreate\n### Inhalt:\ndef test_x(): pass"
    request = Mock(task="add test")
    result = TestChangeGenerator(executor).generate(request)
    executor.run.assert_called_once_with("tester", "add test", "", "tester", 0)
    assert result["changes"][0]["file"] == "tests/test_x.py"


def test_generator_propagates_invalid_output():
    executor = Mock()
    executor.run.return_value = "invalid"
    with pytest.raises(ValueError):
        TestChangeGenerator(executor).generate(Mock(task="x"))
