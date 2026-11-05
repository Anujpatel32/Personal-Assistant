import pytest
import smart_home
import tool_registry

def test_smart_home_devices_discovery():
    devices = smart_home.get_devices()
    assert len(devices) > 0
    assert any("light" in k or "lamp" in k for k in devices.keys())

def test_smart_home_device_control():
    res = smart_home.control_device("desk lamp", "on", 90)
    assert res["success"] is True

    res = smart_home.control_device("desk lamp", "off")
    assert res["success"] is True
    assert res["state"] == "off"

def test_smart_home_tools():
    tools = tool_registry.list_tools()
    names = [t["name"] for t in tools]
    assert "control_smart_device" in names
    assert "list_smart_devices" in names
    assert "analyze_screen_image" in names
    assert "analyze_camera_image" in names

    list_res = tool_registry.run_tool("list_smart_devices", {})
    assert list_res["success"] is True
    assert "Desk Lamp" in list_res["output"] or "Light" in list_res["output"]

