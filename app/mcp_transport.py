"""Minimal JSON-RPC 2.0 / MCP transport over stdio.

This module contains *no* business logic.
It delegates every tool call to the existing :class:`MCPServer` and
serialises results in a JSON‑compatible format, respecting all
security boundaries defined by the application layer.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from typing import Any, BinaryIO, Optional, TextIO

from app.mcp_server import MCPServer, ToolDefinition
from app.setup_approval import SetupApprovalError
from app.workflow_plan_store import WorkflowPlanStoreError

# ---------------------------------------------------------------------------
# Concrete dependencies – imported at module level so tests can patch them.
# ---------------------------------------------------------------------------
from app.project_scanner import ProjectScanner
from app.ai_config import load_ai_config
from app.ai_requirement_discovery import AIRequirementDiscovery
from app.engineering_council import EngineeringCouncil
from app.llm_provider_factory import create_llm_provider
from app.local_secret_store import LocalSecretStore
from app.requirement_preflight import RequirementPreflight
from app.workflow_plan_store import WorkflowPlanStore
from app.setup_approval import SetupApproval
from app.dev_workflow import DevelopmentWorkflow, WorkflowExecutionError
from app.python_package_executor import PythonPackageExecutor
from app.requirement_validator import RequirementValidator
from app.toolchain_materializer import ToolchainMaterializer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "result": result, "id": id_}


def _error(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": id_}


def _to_json_compatible(obj: Any) -> Any:
    """Recursively convert *obj* to a JSON‑serialisable value.

    Dataclasses are expanded with :func:`dataclasses.asdict`.
    Other objects are converted via ``vars()`` or ``str()`` as a last resort.
    The function is intentionally generic – it never depends on concrete
    domain models.
    """
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (list, tuple)):
        return [_to_json_compatible(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _to_json_compatible(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        return _to_json_compatible(dataclasses.asdict(obj))
    if hasattr(obj, "__dict__"):
        return _to_json_compatible(vars(obj))
    return str(obj)


# ---------------------------------------------------------------------------
# MCP request handler
# ---------------------------------------------------------------------------

class MCPRequestHandler:
    """Process a single JSON‑RPC request and return a response dict.

    The handler is intentionally stateless apart from the ``initialized``
    flag that enforces the MCP lifecycle.
    """

    def __init__(self, server: MCPServer) -> None:
        self._server = server
        self._tools: dict[str, ToolDefinition] = {
            t.name: t for t in server.list_tools()
        }
        self._initialized = False

    # -- public API ---------------------------------------------------------

    def handle(self, request: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process a single JSON‑RPC request.

        Returns ``None`` for notifications (no ``id`` field) that do not
        require a response.
        """
        method = request.get("method")
        id_ = request.get("id")
        params = request.get("params", {})

        if not isinstance(params, dict):
            return _error(id_, -32602, "Invalid params: must be an object")

        # -- lifecycle ------------------------------------------------------
        if method == "initialize":
            return self._handle_initialize(id_, params)
        if method == "notifications/initialized":
            self._initialized = True
            return None  # notification, no response

        if not self._initialized:
            return _error(id_, -32603, "Server not initialized")

        # -- tools ----------------------------------------------------------
        if method == "tools/list":
            return self._handle_tools_list(id_)
        if method == "tools/call":
            return self._handle_tools_call(id_, params)

        return _error(id_, -32601, f"Method not found: {method}")

    # -- lifecycle ----------------------------------------------------------

    def _handle_initialize(self, id_: Any, params: dict[str, Any]) -> dict[str, Any]:
        self._initialized = True
        return _result(
            id_,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ai-dev-center", "version": "0.1.0"},
            },
        )

    # -- tools/list ---------------------------------------------------------

    def _handle_tools_list(self, id_: Any) -> dict[str, Any]:
        tools = [dataclasses.asdict(t) for t in self._server.list_tools()]
        return _result(id_, {"tools": tools})

    # -- tools/call ---------------------------------------------------------

    def _handle_tools_call(self, id_: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not name:
            return _error(id_, -32602, "Missing required parameter: name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error(id_, -32602, "Invalid arguments: must be an object")

        tool_def = self._tools.get(name)
        if tool_def is None:
            return _error(id_, -32602, f"Unknown tool: {name}")

        # Validate arguments against the tool’s schema
        validation_err = self._validate_arguments(tool_def, arguments)
        if validation_err:
            return _error(id_, -32602, validation_err)

        try:
            # Dispatch to the corresponding MCPServer method.
            # The method name is guaranteed to be one of the tool names.
            method = getattr(self._server, name)
            result = method(**arguments)
        except WorkflowPlanStoreError as exc:
            return _error(id_, -32000, str(exc))
        except SetupApprovalError as exc:
            return _error(id_, -32000, str(exc))
        except Exception as exc:
            # Generic catch‑all for unexpected errors (e.g. WorkflowExecutionError,
            # missing resources, …).  DO NOT leak secrets.
            return _error(id_, -32000, str(exc))

        # Serialize the result to a JSON‑compatible text response.
        content = _to_json_compatible(result)
        return _result(
            id_,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(content, ensure_ascii=False),
                    }
                ]
            },
        )

    # -- argument validation ------------------------------------------------

    @staticmethod
    def _validate_arguments(
        tool_def: ToolDefinition, arguments: dict[str, Any]
    ) -> Optional[str]:
        """Return an error message if *arguments* violate the tool’s schema."""
        schema = tool_def.input_schema
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for req in required:
            if req not in arguments:
                return f"Missing required parameter: {req}"

        for key, value in arguments.items():
            prop = properties.get(key)
            if prop is None:
                continue
            expected_type = prop.get("type")
            if expected_type == "string" and not isinstance(value, str):
                return f"Invalid type for parameter '{key}': expected string"
            if expected_type in ("number", "integer") and not isinstance(
                value, (int, float)
            ):
                return (
                    f"Invalid type for parameter '{key}': expected number"
                )
            if expected_type == "object" and not isinstance(value, dict):
                return f"Invalid type for parameter '{key}': expected object"
            if expected_type == "array" and not isinstance(value, list):
                return f"Invalid type for parameter '{key}': expected array"
            if expected_type == "boolean" and not isinstance(value, bool):
                return f"Invalid type for parameter '{key}': expected boolean"

        return None


# ---------------------------------------------------------------------------
# Stdio transport
# ---------------------------------------------------------------------------

class MCPStdioServer:
    """Read JSON‑RPC requests from an input stream, process them with
    :class:`MCPRequestHandler`, and write responses to an output stream.

    By default the streams are ``sys.stdin.buffer`` and ``sys.stdout``,
    which makes the server suitable for a local stdio‑based MCP transport.
    """

    def __init__(
        self,
        server: MCPServer,
        *,
        input_stream: Optional[BinaryIO] = None,
        output_stream: Optional[TextIO] = None,
    ) -> None:
        self._handler = MCPRequestHandler(server)
        self._input = (
            input_stream if input_stream is not None else sys.stdin.buffer
        )
        self._output = output_stream if output_stream is not None else sys.stdout

    def run(self) -> None:
        """Blocking loop that reads lines from *input_stream*, processes
        each JSON‑RPC message, and writes the corresponding response.
        """
        for line_bytes in self._input:
            line = line_bytes.decode("utf-8").strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                self._write(_error(None, -32700, "Parse error"))
                continue
            if not isinstance(request, dict):
                self._write(_error(None, -32600, "Invalid Request"))
                continue

            response = self._handler.handle(request)
            if response is None:
                continue
            self._write(response)

    def _write(self, response_dict: dict[str, Any]) -> None:
        json_str = json.dumps(response_dict, ensure_ascii=False)
        self._output.write(json_str + "\n")
        self._output.flush()


# ---------------------------------------------------------------------------
# Module entry point (python -m app.mcp_transport)
# ---------------------------------------------------------------------------

def _create_mcp_server() -> MCPServer:
    """Build an MCPServer wired to the real AI-Dev-Center components."""
    config = load_ai_config("config/ai-dev-center.yml")
    council_config = config.council
    if council_config is None or not council_config.enabled:
        raise WorkflowExecutionError(
            "Engineering Council configuration must be enabled."
        )

    secret_resolver = LocalSecretStore()
    provider = create_llm_provider(config, secret_resolver)
    executor = PythonPackageExecutor()
    discovery = AIRequirementDiscovery(
        llm_provider=provider,
        ai_model=config.model,
    )
    council = EngineeringCouncil(
        council_config=council_config,
        secret_resolver=secret_resolver,
    )
    workflow = DevelopmentWorkflow(
        discovery=discovery,
        validator=RequirementValidator,
        preflight=RequirementPreflight,
        executor=executor,
        council=council,
        materializer=ToolchainMaterializer(),
    )

    return MCPServer(
        project_scanner=ProjectScanner(),
        discovery=discovery,
        preflight=RequirementPreflight,
        planner=None,
        plan_store=WorkflowPlanStore(),
        approval=SetupApproval,
        development_workflow=workflow,
    )


def main() -> None:
    """Entry point for ``python -m app.mcp_transport``."""
    server = _create_mcp_server()
    transport = MCPStdioServer(server)
    transport.run()


if __name__ == "__main__":
    main()
