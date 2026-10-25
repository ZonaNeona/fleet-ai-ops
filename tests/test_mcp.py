"""MCP over HTTP: key, handshake, the shared tool registry, role checks and errors."""

from app.agent import tools_for
from tests.test_integration import client  # noqa: F401  (fixture)


def rpc(c, key, method, params=None, id=1):
    return c.post(f"/api/mcp?key={key}", json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})


def test_mcp_handshake_tools_and_calls(client):  # noqa: F811
    c, _ = client
    assert rpc(c, "nope", "tools/list").status_code == 401
    key = c.post("/api/v1/mcp/key").json()["key"]
    init = rpc(
        c,
        key,
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    )
    assert init.status_code == 200 and init.json()["result"]["serverInfo"]["name"] == "fleet-ai-ops"
    assert (
        c.post(f"/api/mcp?key={key}", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    )
    names = [t["name"] for t in rpc(c, key, "tools/list").json()["result"]["tools"]]
    assert names == [t["function"]["name"] for t in tools_for("owner")]  # one registry, no second copy
    economics = rpc(c, key, "tools/call", {"name": "vehicle_economics", "arguments": {"worst": 2}}).json()["result"]
    assert not economics["isError"] and "vehicles" in economics["content"][0]["text"]
    bad = rpc(c, key, "tools/call", {"name": "list_vehicles", "arguments": {"unknown": 1}}).json()["result"]
    assert bad["isError"]
    assert rpc(c, key, "resources/list").json()["error"]["code"] == -32601
