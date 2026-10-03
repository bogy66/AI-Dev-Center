from app.agent_executor import ProviderAgentExecutor


class RecordingProvider:
    def __init__(self):
        self.prompt = None
        self.max_tokens = None

    def complete(self, prompt, max_tokens=None):
        self.prompt = prompt
        self.max_tokens = max_tokens
        return "provider-result"


def test_productive_agent_executor_uses_configured_provider():
    provider = RecordingProvider()
    result = ProviderAgentExecutor(provider).run(
        "developer", "Create project files", "project facts", "developer", 400,
    )
    assert result == "provider-result"
    assert "Create project files" in provider.prompt
    assert "project facts" in provider.prompt
    assert '"changes"' in provider.prompt
    assert '"tests"' in provider.prompt


def test_productive_agent_executor_passes_max_tokens_to_provider():
    provider = RecordingProvider()
    ProviderAgentExecutor(provider).run(
        "developer", "Task", "", "developer", 1024,
    )
    assert provider.max_tokens == 1024


def test_productive_agent_executor_default_is_no_limit():
    provider = RecordingProvider()
    ProviderAgentExecutor(provider).run(
        "developer", "Task", "", "developer",
    )
    assert provider.max_tokens is None


def test_productive_developer_prompt_has_no_markdown():
    provider = RecordingProvider()
    ProviderAgentExecutor(provider).run(
        "developer", "Task", "", "developer",
    )
    assert "## Dateien" not in provider.prompt
    assert "### Aktion:" not in provider.prompt
    assert "### Inhalt:" not in provider.prompt
    assert "## Analyse" not in provider.prompt


def test_productive_developer_prompt_is_json_only():
    provider = RecordingProvider()
    ProviderAgentExecutor(provider).run(
        "developer", "Task", "", "developer",
    )
    assert '"changes"' in provider.prompt
    assert '"file"' in provider.prompt
    assert '"action"' in provider.prompt
    assert "JSON" in provider.prompt
    assert "No markdown" in provider.prompt


def test_reviewer_prompt_is_json_contract():
    provider = RecordingProvider()
    ProviderAgentExecutor(provider).run(
        "reviewer", "test output", "", "reviewer",
    )
    assert '"decision"' in provider.prompt
    assert '"summary"' in provider.prompt
    assert "Diagnosis Reviewer of AI-Dev-Center" in provider.prompt
    assert "ACCEPTED" not in provider.prompt


def test_reviewer_prompt_has_no_legacy_contract():
    provider = RecordingProvider()
    ProviderAgentExecutor(provider).run(
        "reviewer", "test output", "", "reviewer",
    )
    assert "Return exactly" not in provider.prompt
