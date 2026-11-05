import pytest
import intent_router

def test_system_command_open():
    res = intent_router.route_command("open chrome")
    assert res["intent"] == "system_command"
    assert res["confidence"] == "fast_path"

def test_system_command_volume():
    res = intent_router.route_command("volume up")
    assert res["intent"] == "system_command"
    assert res["confidence"] == "fast_path"

def test_system_command_mute():
    res = intent_router.route_command("mute")
    assert res["intent"] == "system_command"
    assert res["confidence"] == "fast_path"

def test_system_command_screenshot():
    res = intent_router.route_command("take a screenshot")
    assert res["intent"] == "system_command"
    assert res["confidence"] == "fast_path"

def test_system_command_lock():
    res = intent_router.route_command("lock my pc")
    assert res["intent"] == "system_command"
    assert res["confidence"] == "fast_path"

def test_music_intent():
    res = intent_router.route_command("play some music")
    assert res["intent"] == "music"
    assert res["confidence"] == "fast_path"

def test_chat_fast_path():
    res = intent_router.route_command("hello")
    assert res["intent"] == "chat"
    assert res["confidence"] == "fast_path"

    res = intent_router.route_command("how are you doing")
    assert res["intent"] == "chat"
    assert res["confidence"] == "fast_path"

