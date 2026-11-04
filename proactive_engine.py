# -*- coding: utf-8 -*-
"""
proactive_engine.py — Proactive Intelligence for MEOW Assistant
================================================================
Monitors Anuj's PC activity and proactively surfaces useful nudges
WITHOUT being asked. All nudges go through speak_async so they
feel natural and are never blocking.

Nudges implemented:
  1. CPU spike alert       — CPU > 90% for 10s → warns Anuj
  2. RAM pressure alert    — RAM > 88% → suggests closing apps
  3. Coding focus nudge    — VS Code / editor active > 45 min → break reminder
  4. Long session nudge    — Any active window > 2 hours → hydration reminder
  5. Morning brief         — First interaction after 5 AM → weather + tasks + greeting
  6. Idle comeback         — If Anuj comes back after 20+ min idle → welcome back
  7. Battery low alert     — Battery < 15% and not charging → plug-in reminder

All nudges have per-type cooldowns so they never repeat annoyingly.

Usage (called from mascot_widget telemetry timer):
    import proactive_engine
    proactive_engine.init(speak_fn, get_weather_fn)
    proactive_engine.check_nudges(pc_stats)        # called every ~3 seconds
"""

import os
import time
import datetime
import threading
import psutil

# ── Internal state ────────────────────────────────────────────────────────────
_speak              = None   # injected speak_async function
_get_weather        = None   # injected lambda → weather string
_last_nudge         = {}     # type → last epoch when nudge was spoken
_morning_done       = False  # flag: morning brief fired today
_session_start      = time.time()
_last_activity      = time.time()
_focus_app_start    = {}     # app_name → epoch when focus started
_cpu_high_since     = None   # epoch when CPU went > threshold
_initialized        = False

# ── Cooldowns (seconds) ───────────────────────────────────────────────────────
COOLDOWNS = {
    "cpu":         600,    # 10 minutes
    "ram":         600,
    "coding":      2700,   # 45 minutes
    "session":     3600,   # 1 hour
    "morning":     43200,  # 12 hours
    "idle_return": 1800,   # 30 minutes
    "battery":     600,
}

CPU_SPIKE_THRESHOLD   = 90.0   # %
CPU_SPIKE_DURATION    = 10.0   # seconds sustained before alert
RAM_THRESHOLD         = 88.0   # %
BATTERY_LOW           = 15.0   # %
CODING_APPS = {
    "code", "code.exe", "pycharm", "pycharm64.exe",
    "cursor", "cursor.exe", "idea64.exe", "rider64.exe",
    "notepad++.exe", "sublime_text.exe", "vim", "nvim",
}
FOCUS_NUDGE_AFTER     = 45 * 60   # 45 minutes
SESSION_NUDGE_AFTER   = 2  * 3600  # 2 hours


def init(speak_fn, get_weather_fn=None):
    """Call once at startup to wire up speak and weather functions."""
    global _speak, _get_weather, _initialized
    _speak        = speak_fn
    _get_weather  = get_weather_fn
    _initialized  = True
    print("[PROACTIVE] Proactive intelligence engine initialized.")


def _can_nudge(nudge_type: str) -> bool:
    """Return True if enough time has passed since last nudge of this type."""
    cooldown = COOLDOWNS.get(nudge_type, 600)
    last     = _last_nudge.get(nudge_type, 0)
    return (time.time() - last) >= cooldown


def _fire(nudge_type: str, message: str):
    """Speak a nudge and record the time."""
    global _last_nudge
    if _speak:
        _last_nudge[nudge_type] = time.time()
        print(f"[PROACTIVE] [{nudge_type.upper()}] {message}")
        threading.Thread(target=_speak, args=(message,), daemon=True).start()


def _get_active_exe() -> str:
    """Return lowercase exe name of the currently focused foreground window."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid  = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = psutil.Process(pid.value)
        return proc.name().lower()
    except Exception:
        return ""


def check_nudges(pc_stats: dict):
    """
    Main nudge check — call this every ~3 seconds from the telemetry timer.
    pc_stats matches the structure in flask_app.assistant_state['pc_stats'].
    """
    global _cpu_high_since, _morning_done, _last_activity

    if not _initialized or not _speak:
        return

    now  = time.time()
    hour = datetime.datetime.now().hour

    # ── 1. CPU Spike Alert ────────────────────────────────────────────────────
    cpu = pc_stats.get("cpu", 0.0)
    if cpu > CPU_SPIKE_THRESHOLD:
        if _cpu_high_since is None:
            _cpu_high_since = now
        elif (now - _cpu_high_since) >= CPU_SPIKE_DURATION and _can_nudge("cpu"):
            _fire("cpu", f"Hey Anuj, your CPU has been above {int(cpu)} percent for a while. You might want to check what's running.")
    else:
        _cpu_high_since = None

    # ── 2. RAM Pressure Alert ─────────────────────────────────────────────────
    ram = pc_stats.get("ram", 0.0)
    if ram > RAM_THRESHOLD and _can_nudge("ram"):
        _fire("ram", f"RAM is at {int(ram)} percent. You might want to close some apps to free up memory.")

    # ── 3. Battery Low Alert ──────────────────────────────────────────────────
    battery     = pc_stats.get("battery")
    batt_plug   = pc_stats.get("battery_plugged")
    if battery is not None and battery < BATTERY_LOW and not batt_plug and _can_nudge("battery"):
        _fire("battery", f"Anuj, your battery is at {int(battery)} percent and draining. Please plug in your charger.")

    # ── 4. Focus App Nudge (coding break) ────────────────────────────────────
    try:
        exe = _get_active_exe()
        if any(app in exe for app in CODING_APPS):
            if exe not in _focus_app_start:
                _focus_app_start[exe] = now
            elif (now - _focus_app_start[exe]) >= FOCUS_NUDGE_AFTER and _can_nudge("coding"):
                mins = int((now - _focus_app_start[exe]) / 60)
                _fire("coding", f"You've been coding for about {mins} minutes straight, Anuj. Maybe take a quick break — stretch, breathe, hydrate.")
        else:
            # Reset focus timer when switching away
            _focus_app_start.pop(exe, None)
            if not any(app in exe for app in CODING_APPS):
                _focus_app_start.clear()
    except Exception:
        pass

    # ── 5. Long Session Nudge ─────────────────────────────────────────────────
    session_dur = now - _session_start
    if session_dur >= SESSION_NUDGE_AFTER and _can_nudge("session"):
        hrs = int(session_dur / 3600)
        _fire("session", f"You've been at your PC for over {hrs} hour{'s' if hrs > 1 else ''}. Remember to stay hydrated and rest your eyes.")

    # ── 6. Morning Brief ──────────────────────────────────────────────────────
    if 5 <= hour < 12 and not _morning_done and _can_nudge("morning"):
        _morning_done = True
        _last_nudge["morning"] = now
        threading.Thread(target=_deliver_morning_brief, daemon=True).start()

    # Reset morning flag after noon
    if hour >= 12:
        _morning_done = False


def _deliver_morning_brief():
    """Build and speak a concise morning briefing."""
    try:
        import memory_manager
        tasks   = memory_manager.load_tasks()
        pending = [t for t in tasks if not t.get("completed")]
        n_tasks = len(pending)

        weather_str = ""
        if _get_weather:
            try:
                weather_str = _get_weather() or ""
                if weather_str:
                    weather_str = f"Today's weather: {weather_str}. "
            except Exception:
                pass

        task_str = ""
        if n_tasks:
            task_str = f"You have {n_tasks} pending task{'s' if n_tasks > 1 else ''}. "
            if n_tasks <= 3:
                task_str += "They are: " + ", ".join(t['text'] for t in pending[:3]) + ". "

        greeting = f"Good morning Anuj! {weather_str}{task_str}Ready to have a great day?"
        time.sleep(3)   # let TTS engine settle after boot
        if _speak:
            _speak(greeting)
    except Exception as e:
        print(f"[PROACTIVE] Morning brief error: {e}")


def on_user_returned(idle_seconds: float):
    """
    Call this when Anuj returns after being idle for idle_seconds.
    Typically triggered from the telemetry timer comparing last mouse move time.
    """
    global _last_activity
    now = time.time()
    if idle_seconds >= 1200 and _can_nudge("idle_return"):  # 20+ min
        mins = int(idle_seconds / 60)
        _fire("idle_return", f"Welcome back Anuj! You were away for about {mins} minutes. Anything I can help you with?")
    _last_activity = now


def reset_session():
    """Call when a new session starts (e.g. after PC wake from sleep)."""
    global _session_start, _cpu_high_since, _focus_app_start
    _session_start   = time.time()
    _cpu_high_since  = None
    _focus_app_start = {}
