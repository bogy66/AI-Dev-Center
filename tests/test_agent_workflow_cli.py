"""Smoke coverage for the productive cli/agent_workflow_cli.py entry point.

Migrated from tests/test_agent_setup_workflow_integration.py during the
CLAUDE-002 legacy cleanup: that file exclusively covered the dead
AgentSetupWorkflow, but this one function was the only test anywhere that
imports cli/agent_workflow_cli.py, which is a productive CLI adapter over
app.canonical_composition.build_canonical_components(). It is preserved
here unchanged so the productive CLI keeps at least import/callable
smoke coverage.
"""


def test_cli_start_and_approve(tmp_path):
    # Minimal smoke test for CLI functions without subprocess.
    from cli.agent_workflow_cli import start_command, approve_command

    class Args:
        project_id = "proj1"
        project_path = str(tmp_path)

    assert callable(start_command)
    assert callable(approve_command)
