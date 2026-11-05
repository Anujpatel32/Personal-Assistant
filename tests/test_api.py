import pytest
import server

def run_coro(coro):
    """Step a coroutine without creating socketpair event loop."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value

def test_health():
    data = run_coro(server.health_check())
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"
    assert data["tools_loaded"] >= 20

def test_list_tools():
    data = run_coro(server.list_tools())
    assert "tools" in data
    assert data["count"] >= 20

def test_execute_tool():
    req = server.ToolExecuteRequest(tool_name="get_system_stats", args={})
    res = run_coro(server.execute_tool(req))
    assert res.success is True
    assert "CPU:" in res.output

def test_execute_unknown_tool():
    req = server.ToolExecuteRequest(tool_name="fake_tool_xyz", args={})
    with pytest.raises(server.HTTPException) as excinfo:
        run_coro(server.execute_tool(req))
    assert excinfo.value.status_code == 404

def test_get_config():
    data = run_coro(server.get_config())
    assert "selected_model" in data

def test_state_endpoint():
    data = run_coro(server.get_state())
    assert "status" in data

def test_auth_verification():
    # When MEOW_API_KEY is not set, auth passes
    auth_res = run_coro(server.verify_auth(None, None))
    assert auth_res is True
