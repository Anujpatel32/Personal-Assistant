import pytest
import voice_clone
import local_model_manager
import tool_registry

def test_local_models_scan():
    res = local_model_manager.list_local_models()
    assert "gguf_models" in res
    assert "ollama_models" in res
    assert isinstance(res["total"], int)

def test_switch_model_logic():
    res = local_model_manager.switch_model("gemini")
    assert res["success"] is True
    assert res["selected_model"] == "gemini"

def test_kokoro_blend():
    res = voice_clone.create_kokoro_blend("custom_duo", {"af_sarah": 0.6, "af_bella": 0.4})
    assert res["success"] is True
    assert res["blend"]["af_sarah"] == 0.6

def test_phase9_tools_registered():
    tools = tool_registry.list_tools()
    names = [t["name"] for t in tools]
    assert "clone_voice" in names
    assert "create_voice_blend" in names
    assert "list_local_models" in names
    assert "switch_active_model" in names
