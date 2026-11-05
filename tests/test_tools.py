import pytest
import tool_registry
import tool_schemas

def test_tool_count():
    tools = tool_registry.list_tools()
    assert len(tools) >= 20

def test_tool_schema_generation():
    names = tool_schemas.get_tool_names()
    assert "take_screenshot" in names
    assert "get_system_stats" in names
    assert "run_command" in names

    gemini_schemas = tool_schemas.get_gemini_tools()
    assert len(gemini_schemas) >= 20
    openai_schemas = tool_schemas.get_openai_tools()
    assert len(openai_schemas) >= 20

def test_safe_vs_dangerous():
    assert tool_schemas.is_dangerous("run_command")
    assert tool_schemas.is_dangerous("lock_pc")
    assert not tool_schemas.is_dangerous("get_system_stats")
    assert not tool_schemas.is_dangerous("get_weather")

def test_run_system_stats():
    res = tool_registry.run_tool("get_system_stats", {})
    assert res["success"] is True
    assert "CPU:" in res["output"]
    assert "RAM:" in res["output"]

def test_command_guardrail_blocking():
    # Destructive command should be blocked
    res = tool_registry.run_tool("run_command", {"command": "format d:"})
    assert "blocked" in res["output"].lower() or "violation" in res["output"].lower()

def test_unknown_tool():
    res = tool_registry.run_tool("completely_fake_tool_12345", {})
    assert res["success"] is False
    assert "Unknown tool" in res["error"]

