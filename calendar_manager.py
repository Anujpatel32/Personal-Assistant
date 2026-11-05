# -*- coding: utf-8 -*-
"""
calendar_manager.py — Local Calendar & Schedule Management for MEOW (Phase 7)
=============================================================================
Manages events, reminders, and schedules stored in the SQLite database.
Supports:
  - Adding events with start/end time and description
  - Querying upcoming events
  - Exporting events to standard .ics (iCalendar) format
  - Tool integration for agentic scheduling
"""

import os
import sqlite3
import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional

logger = logging.getLogger("meow.core")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "meow.db")

def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

_init_db()


def add_event(title: str, start_time: str, end_time: str = "", description: str = "") -> Dict[str, Any]:
    """Add a calendar event."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "INSERT INTO calendar_events (title, start_time, end_time, description) VALUES (?, ?, ?, ?)",
            (title.strip(), start_time.strip(), end_time.strip() if end_time else None, description.strip() if description else None)
        )
        conn.commit()
        event_id = cursor.lastrowid
        return {
            "id": event_id,
            "title": title,
            "start_time": start_time,
            "end_time": end_time,
            "description": description
        }


def get_events(query_date: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve upcoming events. If query_date is provided (YYYY-MM-DD or 'today'), filter by it."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if query_date:
            target = date.today().isoformat() if query_date.lower() == "today" else query_date
            rows = conn.execute(
                "SELECT * FROM calendar_events WHERE start_time LIKE ? ORDER BY start_time ASC LIMIT ?",
                (f"{target}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM calendar_events ORDER BY start_time ASC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def delete_event(event_id: int) -> bool:
    """Delete a calendar event by ID."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
        conn.commit()
        return cursor.rowcount > 0


def export_to_ics(filepath: Optional[str] = None) -> str:
    """Export all events to an iCalendar (.ics) file for Google/Outlook import."""
    events = get_events(limit=500)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//MEOW AI Assistant//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    for ev in events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:meow-event-{ev['id']}@assistant")
        clean_start = ev['start_time'].replace("-", "").replace(":", "").replace(" ", "T")
        lines.append(f"DTSTART:{clean_start}")
        if ev.get("end_time"):
            clean_end = ev['end_time'].replace("-", "").replace(":", "").replace(" ", "T")
            lines.append(f"DTEND:{clean_end}")
        lines.append(f"SUMMARY:{ev['title']}")
        if ev.get("description"):
            lines.append(f"DESCRIPTION:{ev['description']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    content = "\r\n".join(lines) + "\r\n"

    target_path = filepath or os.path.join(os.path.dirname(DB_PATH), "meow_calendar.ics")
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)
    return target_path


# ── Register Tools ────────────────────────────────────────────────────
try:
    import tool_registry

    @tool_registry.register_tool(
        "add_calendar_event",
        "Schedule an event or reminder with title, start_time (YYYY-MM-DD HH:MM), and optional description",
        ["title", "start_time"]
    )
    def _tool_add_event(title: str, start_time: str, end_time: str = "", description: str = ""):
        ev = add_event(title, start_time, end_time, description)
        return f"Event scheduled: '{ev['title']}' on {ev['start_time']}"

    @tool_registry.register_tool(
        "get_calendar_events",
        "Get upcoming calendar events and appointments (optional date: YYYY-MM-DD or 'today')",
        ["query_date"]
    )
    def _tool_get_events(query_date: str = "today"):
        events = get_events(query_date=query_date)
        if not events:
            return f"No events found for {query_date}."
        formatted = [f"• #{e['id']}: {e['title']} at {e['start_time']}" + (f" ({e['description']})" if e.get('description') else "") for e in events]
        return "\n".join(formatted)

except Exception as _tr_err:
    logger.warning("Could not register calendar tools: %s", _tr_err)
