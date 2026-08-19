from unittest.mock import MagicMock

from app.tester_agent import TesterAgent as AgentTester


def _changes():
    return {
        "changes": [
            {
                "file": "app/example.py",
                "action": "create",
                "content": 'print("hello")'
            }
        ]
    }


def test_tester_passes_when_tests_and_specification_pass():
    runner = MagicMock()

    runner.run.return_value = {
        "success": True,
        "stdout": "",
        "stderr": ""
    }

    specification_tester = MagicMock()

    specification_tester.check.return_value = {
        "success": True,
        "errors": []
    }

    agent = AgentTester()
    agent.runner = runner
    agent.specification_tester = specification_tester

    result = agent.test(
        "mock_project",
        _changes()
    )

    assert result["status"] == "completed"
    assert result["result"] == "PASS"


def test_tester_fails_when_test_runner_fails():
    runner = MagicMock()

    runner.run.return_value = {
        "success": False,
        "stdout": "",
        "stderr": "SyntaxError"
    }

    agent = AgentTester()
    agent.runner = runner

    result = agent.test(
        "mock_project",
        _changes()
    )

    assert result["status"] == "failed"
    assert "SyntaxError" in result["result"]


def test_tester_fails_when_specification_fails():
    runner = MagicMock()

    runner.run.return_value = {
        "success": True,
        "stdout": "",
        "stderr": ""
    }

    specification_tester = MagicMock()

    specification_tester.check.return_value = {
        "success": False,
        "errors": [
            "Inhalt stimmt nicht: app/example.py"
        ]
    }

    agent = AgentTester()
    agent.runner = runner
    agent.specification_tester = specification_tester

    result = agent.test(
        "mock_project",
        _changes()
    )

    assert result["status"] == "failed"
    assert "Inhalt stimmt nicht" in result["result"]
