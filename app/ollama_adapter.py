"""Thin adapter: OllamaClient → LLMProvider Protocol.

Makes the existing OllamaClient (which exposes ``generate()``) compatible
with the ``LLMProvider`` protocol (which requires ``complete()``).
"""

from __future__ import annotations

from app.ollama_client import OllamaClient


class OllamaAdapter:
    """Adapts OllamaClient to the LLMProvider Protocol.

    Usage::

        adapter = OllamaAdapter(url="http://localhost:11434", model="llama3.2:3b")
        response = adapter.complete("Hello world")
    """

    def __init__(self, url: str = "http://localhost:11434", model: str = "llama3.2:3b", timeout: int = 300):
        self._client = OllamaClient(url=url, model=model)

    def complete(self, prompt: str) -> str:
        return self._client.generate(prompt)