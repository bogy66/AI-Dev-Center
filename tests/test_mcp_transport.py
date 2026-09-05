import io
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import app.mcp_transport as transport
from app.mcp_server import MCPServer, ToolDefinition
from app.mcp_transport import (
    MCPRequestHandler,
    MCPStdioServer,
    _to_json_compatible,
    _error,
    _result,
)
from app.setup_approval import SetupApprovalError
from app.workflow_plan_store import WorkflowPlanStoreError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(method: str, id_: int = 1, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "method": method, "id": id_, "params": params or {}}


def _make_server(**overrides):
    """Create an :class:`MCPServer` whose collaborators are all mocks."""
    project_scanner = overrides.get("project_scanner", Mock())
    discovery = overrides.get("discovery", Mock())
    preflight = overrides.get("preflight", Mock())
    planner = overrides.get("planner", Mock())
    plan_store = overrides.get("plan_store", Mock())
    approval = overrides.get("approval", Mock())
    development_workflow = overrides.get("development_workflow", Mock())

    return MCPServer(
        project_scanner=project_scanner,
        discovery=discovery,
        preflight=preflight,
        planner=planner,
        plan_store=plan_store,
        approval=approval,
        development_workflow=development_workflow,
    )


# ---------------------------------------------------------------------------
# Tests for _to_json_compatible
# ---------------------------------------------------------------------------

class TestToJsonCompatible:
    def test_primitive(self):
        assert _to_json_compatible(5) == 5
        assert _to_json_compatible("hello") == "hello"

    def test_list(self):
        assert _to_json_compatible([1, "a", None]) == [1, "a", None]

    def test_dict(self):
        assert _to_json_compatible({"x": 1}) == {"x": 1}

    def test_bytes(self):
        assert _to_json_compatible(b"abc") == "abc"

    def test_dataclass(self):
        td = ToolDefinition("t", "desc", {"type": "object"})
        result = _to_json_compatible(td)
        assert result == {
            "name": "t",
            "description": "desc",
            "input_schema": {"type": "object"},
        }

    def test_regular_object(self):
        class Obj:
            def __init__(self):
                self.a = 1

        assert _to_json_compatible(Obj()) == {"a": 1}


# ---------------------------------------------------------------------------
# Tests for MCPRequestHandler
# ---------------------------------------------------------------------------

class TestRequestHandler:
    def _handler(self, **overrides) -> MCPRequestHandler:
        return MCPRequestHandler(_make_server(**overrides))

    # -- initialize ---------------------------------------------------------

    def test_initialize(self):
        handler = self._handler()
        resp = handler.handle(_make_request("initialize", params={"clientInfo": {}}))
        assert resp["id"] == 1
        result = resp["result"]
        assert result["protocolVersion"] == "2024-11-05"
        assert result["capabilities"] == {"tools": {}}
        assert "serverInfo" in result

    def test_initialized_notification(self):
        handler = self._handler()
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        resp = handler.handle(notification)
        assert resp is None
        # After the notification the server is initialized
        resp2 = handler.handle(_make_request("tools/list"))
        assert resp2["id"] == 1
        assert "result" in resp2

    def test_call_before_initialize(self):
        handler = self._handler()
        resp = handler.handle(_make_request("tools/list"))
        assert resp["error"]["code"] == -32603

    # -- tools/list ---------------------------------------------------------

    def test_tools_list(self):
        handler = self._handler()
        handler.handle(_make_request("initialize"))
        resp = handler.handle(_make_request("tools/list"))
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert names == {
            "inspect_project",
            "discover_requirements",
            "get_preflight",
            "create_setup_plan",
            "plan_project_setup",
            "get_setup_plan",
            "approve_setup_plan",
            "execute_setup_plan",
        }

    # -- tools/call: inspect_project ----------------------------------------

    def test_tools_call_inspect(self):
        scanner = Mock()
        scanner.scan.return_value = ["a.py", "b.yaml"]
        handler = self._handler(project_scanner=scanner)
        handler.handle(_make_request("initialize"))

        resp = handler.handle(
            _make_request(
                "tools/call",
                params={
                    "name": "inspect_project",
                    "arguments": {"project_path": "/tmp/test"},
                },
            )
        )
        scanner.scan.assert_called_once_with("/tmp/test")
        content = resp["result"]["content"][0]
        assert content["type"] == "text"
        payload = json.loads(content["text"])
        assert payload["project_path"] == "/tmp/test"
        assert payload["files"] == ["a.py", "b.yaml"]

    # -- tools/call: execute_setup_plan (success) ---------------------------

    def test_execute_setup_plan_success(self):
        plan_store = Mock()
        plan = Mock(status="approved")
        plan_store.load.return_value = plan
        plan_store.load_project_root.return_value = "/tmp/p1-root"
        dev = Mock()
        dev.execute_approved.return_value = {"stage": "executed", "ok": True}
        handler = self._handler(plan_store=plan_store, development_workflow=dev)
        handler.handle(_make_request("initialize"))

        resp = handler.handle(
            _make_request(
                "tools/call",
                params={
                    "name": "execute_setup_plan",
                    "arguments": {"project_id": "p1", "plan_id": "plan-x"},
                },
            )
        )
        plan_store.load.assert_called_once_with("p1", "plan-x")
        plan_store.load_project_root.assert_called_once_with("p1")
        dev.execute_approved.assert_called_once_with(plan, "/tmp/p1-root")
        content = resp["result"]["content"][0]
        assert "executed" in content["text"]

    # -- tools/call: execute_setup_plan (not approved) ----------------------

    def test_execute_setup_plan_not_approved(self):
        plan_store = Mock()
        plan = Mock(status="pending_approval")
        plan_store.load.return_value = plan
        handler = self._handler(plan_store=plan_store)
        handler.handle(_make_request("initialize"))

        resp = handler.handle(
            _make_request(
                "tools/call",
                params={
                    "name": "execute_setup_plan",
                    "arguments": {"project_id": "p1", "plan_id": "plan-x"},
                },
            )
        )
        assert resp["error"]["code"] == -32000
        assert "not approved" in resp["error"]["message"]

    # -- tools/call: plan not found -----------------------------------------

    def test_plan_not_found(self):
        plan_store = Mock()
        plan_store.load.side_effect = WorkflowPlanStoreError("not found")
        handler = self._handler(plan_store=plan_store)
        handler.handle(_make_request("initialize"))

        resp = handler.handle(
            _make_request(
                "tools/call",
                params={
                    "name": "get_setup_plan",
                    "arguments": {"project_id": "p1", "plan_id": "missing"},
                },
            )
        )
        assert resp["error"]["code"] == -32000
        assert "not found" in resp["error"]["message"]

    # -- tools/call: unknown tool -------------------------------------------

    def test_unknown_tool(self):
        handler = self._handler()
        handler.handle(_make_request("initialize"))
        resp = handler.handle(
            _make_request("tools/call", params={"name": "nosuch", "arguments": {}})
        )
        assert resp["error"]["code"] == -32602
        assert "Unknown tool" in resp["error"]["message"]

    # -- tools/call: missing required parameter -----------------------------

    def test_missing_required_param(self):
        handler = self._handler()
        handler.handle(_make_request("initialize"))
        resp = handler.handle(
            _make_request(
                "tools/call",
                params={"name": "inspect_project", "arguments": {}},
            )
        )
        assert resp["error"]["code"] == -32602
        assert "Missing required parameter" in resp["error"]["message"]

    # -- tools/call: invalid argument type ----------------------------------

    def test_invalid_argument_type(self):
        handler = self._handler()
        handler.handle(_make_request("initialize"))
        resp = handler.handle(
            _make_request(
                "tools/call",
                params={
                    "name": "inspect_project",
                    "arguments": {"project_path": 123},
                },
            )
        )
        assert resp["error"]["code"] == -32602
        assert "Invalid type" in resp["error"]["message"]

    # -- JSON-RPC error shapes ----------------------------------------------

    def test_parse_error(self):
        handler = self._handler()
        # The handler does not parse JSON; the transport does.
        err = _error(1, -32700, "Parse error")
        assert err["jsonrpc"] == "2.0"
        assert err["error"]["code"] == -32700

    def test_method_not_found(self):
        handler = self._handler()
        handler.handle(_make_request("initialize"))
        resp = handler.handle(_make_request("some/unknown"))
        assert resp["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# Smoke test via stdio transport (local end‑to‑end)
# ---------------------------------------------------------------------------

class TestStdioSmoke:
    def test_full_roundtrip(self):
        """Simulate a complete MCP session using in‑memory streams."""
        server = _make_server()
        # Pre‑configure the project scanner for deterministic output.
        server._project_scanner.scan.return_value = ["f1", "f2"]

        input_stream = io.BytesIO()
        output_stream = io.StringIO()

        mcp = MCPStdioServer(
            server,
            input_stream=input_stream,
            output_stream=output_stream,
        )

        # Build a payload that mimics a real client session.
        session = [
            _make_request("initialize", id_=1, params={"clientInfo": {}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _make_request("tools/list", id_=2),
            _make_request(
                "tools/call",
                id_=3,
                params={
                    "name": "inspect_project",
                    "arguments": {"project_path": "/tmp/test"},
                },
            ),
        ]
        for req in session:
            line = json.dumps(req, ensure_ascii=False) + "\n"
            input_stream.write(line.encode("utf-8"))
        input_stream.seek(0)

        mcp.run()

        output = output_stream.getvalue().strip()
        responses = [
            json.loads(line) for line in output.split("\n") if line.strip()
        ]

        # 1 – initialize
        assert responses[0]["id"] == 1
        assert responses[0]["result"]["capabilities"]["tools"] == {}
        # 2 – tools/list (id=2)
        assert responses[1]["id"] == 2
        tools = responses[1]["result"]["tools"]
        assert any(t["name"] == "inspect_project" for t in tools)
        # 3 – tools/call (id=3)
        assert responses[2]["id"] == 3
        content = responses[2]["result"]["content"][0]["text"]
        payload = json.loads(content)
        assert payload["files"] == ["f1", "f2"]


# ---------------------------------------------------------------------------
# Entry point test (python -m app.mcp_transport)
# ---------------------------------------------------------------------------

class TestMCPCompositionRoot:
    @pytest.mark.parametrize("council_config", [None, SimpleNamespace(enabled=False)])
    def test_create_mcp_server_rejects_missing_or_disabled_council(
        self, monkeypatch, council_config
    ):
        """Configuration errors must occur before secret or AI setup."""
        config = SimpleNamespace(council=council_config)
        load_config = Mock(return_value=config)
        secret_store = Mock()
        provider_factory = Mock()
        council_factory = Mock()

        monkeypatch.setattr(transport, "load_ai_config", load_config)
        monkeypatch.setattr(transport, "LocalSecretStore", secret_store)
        monkeypatch.setattr(transport, "create_llm_provider", provider_factory)
        monkeypatch.setattr(transport, "EngineeringCouncil", council_factory)

        with pytest.raises(
            transport.WorkflowExecutionError,
            match="Engineering Council configuration must be enabled",
        ):
            transport._create_mcp_server()

        load_config.assert_called_once_with("config/ai-dev-center.yml")
        secret_store.assert_not_called()
        provider_factory.assert_not_called()
        council_factory.assert_not_called()

    def test_create_mcp_server_wires_one_secret_resolver_without_side_effects(
        self, monkeypatch
    ):
        """The composition root shares its resolver and uses injected fakes only."""
        council_config = SimpleNamespace(enabled=True)
        config = SimpleNamespace(council=council_config, model="test-model")
        resolver = Mock()
        provider = Mock()
        executor = Mock()
        discovery = Mock()
        council = Mock()
        materializer = Mock()
        workflow = Mock()
        server = Mock()
        scanner = Mock()
        plan_store = Mock()

        load_config = Mock(return_value=config)
        secret_store = Mock(return_value=resolver)
        provider_factory = Mock(return_value=provider)
        executor_factory = Mock(return_value=executor)
        discovery_factory = Mock(return_value=discovery)
        council_factory = Mock(return_value=council)
        materializer_factory = Mock(return_value=materializer)
        workflow_factory = Mock(return_value=workflow)
        server_factory = Mock(return_value=server)
        scanner_factory = Mock(return_value=scanner)
        plan_store_factory = Mock(return_value=plan_store)

        monkeypatch.setattr(transport, "load_ai_config", load_config)
        monkeypatch.setattr(transport, "LocalSecretStore", secret_store)
        monkeypatch.setattr(transport, "create_llm_provider", provider_factory)
        monkeypatch.setattr(transport, "PythonPackageExecutor", executor_factory)
        monkeypatch.setattr(transport, "AIRequirementDiscovery", discovery_factory)
        monkeypatch.setattr(transport, "EngineeringCouncil", council_factory)
        monkeypatch.setattr(transport, "ToolchainMaterializer", materializer_factory)
        monkeypatch.setattr(transport, "DevelopmentWorkflow", workflow_factory)
        monkeypatch.setattr(transport, "MCPServer", server_factory)
        monkeypatch.setattr(transport, "ProjectScanner", scanner_factory)
        monkeypatch.setattr(transport, "WorkflowPlanStore", plan_store_factory)

        assert transport._create_mcp_server() is server

        secret_store.assert_called_once_with()
        provider_factory.assert_called_once_with(config, resolver)
        council_factory.assert_called_once_with(
            council_config=council_config,
            secret_resolver=resolver,
        )
        discovery_factory.assert_called_once_with(
            llm_provider=provider,
            ai_model="test-model",
        )

        workflow_kwargs = workflow_factory.call_args.kwargs
        assert workflow_kwargs["discovery"] is discovery
        assert workflow_kwargs["executor"] is executor
        assert workflow_kwargs["council"] is council
        assert workflow_kwargs["materializer"] is materializer

        server_kwargs = server_factory.call_args.kwargs
        assert server_kwargs["discovery"] is discovery
        assert server_kwargs["development_workflow"] is workflow
        assert server_kwargs["planner"] is None

class TestEntryPoint:
    def test_entry_point_processes_initialize_and_tools_list(self):
        """Simulate running the module as a script and verify the basic
        MCP handshake and tools/list response."""
        from app.mcp_transport import main

        # Prepare a minimal session
        session = [
            {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "method": "tools/list", "id": 2},
        ]
        input_bytes = io.BytesIO()
        for req in session:
            line = json.dumps(req) + "\n"
            input_bytes.write(line.encode("utf-8"))
        input_bytes.seek(0)

        output = io.StringIO()

        class FakeStdin:
            def __init__(self, buffer):
                self.buffer = buffer

        # Patch every concrete dependency used by _create_mcp_server()
        # so that no real side‑effects (file‑system, network, …) occur.
        with patch("app.mcp_transport.ProjectScanner") as mock_scanner_cls, \
             patch("app.mcp_transport.AIRequirementDiscovery") as mock_discovery_cls, \
             patch("app.mcp_transport.RequirementPreflight") as mock_preflight_cls, \
             patch("app.mcp_transport.RequirementValidator") as mock_validator_cls, \
             patch("app.mcp_transport.WorkflowPlanStore") as mock_store_cls, \
             patch("app.mcp_transport.SetupApproval") as mock_approval_cls, \
             patch("app.mcp_transport.PythonPackageExecutor") as mock_executor_cls, \
             patch("app.mcp_transport.DevelopmentWorkflow") as mock_dev_cls, \
             patch("sys.stdin", FakeStdin(input_bytes)), \
             patch("sys.stdout", output):

            # Configure the mocks so that the server can be built without
            # touching the real world.
            mock_scanner = Mock()
            mock_scanner.scan.return_value = []
            mock_scanner_cls.return_value = mock_scanner

            mock_discovery_cls.return_value = Mock()
            mock_preflight_cls.return_value = Mock()
            mock_validator_cls.return_value = Mock()
            mock_store_cls.return_value = Mock()
            mock_approval_cls.return_value = Mock()
            mock_executor_cls.return_value = Mock()
            mock_dev_cls.return_value = Mock()

            main()

        output.seek(0)
        lines = [line for line in output.read().splitlines() if line.strip()]
        responses = [json.loads(line) for line in lines]

        # initialize response
        assert responses[0]["id"] == 1
        assert responses[0]["result"]["capabilities"]["tools"] == {}
        # tools/list response
        assert responses[1]["id"] == 2
        tools = responses[1]["result"]["tools"]
        assert any(t["name"] == "inspect_project" for t in tools)
