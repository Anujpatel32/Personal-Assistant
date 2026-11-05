import pytest
import os
import calendar_manager
import email_manager
import tool_registry

def test_calendar_event_lifecycle():
    ev = calendar_manager.add_event("Sprint Planning", "2026-12-01 10:00", description="Biweekly planning")
    assert ev["id"] is not None
    assert ev["title"] == "Sprint Planning"

    events = calendar_manager.get_events()
    assert any(e["id"] == ev["id"] for e in events)

    ics_path = calendar_manager.export_to_ics()
    assert os.path.exists(ics_path)

    ok = calendar_manager.delete_event(ev["id"])
    assert ok is True

def test_email_drafting():
    res = email_manager.draft_email("anuj@example.com", "Roadmap Review", "MEOW Phase 7 is live.")
    assert res["success"] is True
    assert os.path.exists(res["filepath"])

def test_calendar_and_email_tools_registered():
    tools = tool_registry.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "add_calendar_event" in tool_names
    assert "get_calendar_events" in tool_names
    assert "send_email" in tool_names
    assert "draft_email" in tool_names

def test_pwa_assets_exist():
    assert os.path.exists("static/manifest.json")
    assert os.path.exists("static/sw.js")

