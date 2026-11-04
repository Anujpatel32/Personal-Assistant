# -*- coding: utf-8 -*-
"""
emotion_engine.py — Emotion & Personality Engine for MEOW Assistant
=====================================================================
Gives MEOW a persistent mood state that:
  • Carries over between sessions (saved to memory.json)
  • Shifts based on: time of day, user sentiment, interaction frequency,
    task success/failure, how long since last interaction
  • Injects mood-appropriate personality tone into every LLM call
  • Exposes mascot colour hints so draw_cat() can tint accordingly

Mood ladder (ascending positivity):
    sleeping → grumpy → tired → neutral → content → happy → excited

Usage:
    import emotion_engine
    emotion_engine.load_mood()           # call once at startup
    emotion_engine.process_command(cmd)  # call after each user command
    emotion_engine.on_task_success()     # call when a task completes OK
    emotion_engine.on_task_failure()     # call when a task fails
    modifier = emotion_engine.get_mood_modifier()   # inject into SYSTEM prompt
    color    = emotion_engine.get_mood_color()       # QColor hex for mascot tint
"""

import os
import json
import time
import datetime
import threading
import math

import memory_manager
import sentiment_detector

# ── Mood definitions ──────────────────────────────────────────────────────────
MOODS = ["sleeping", "grumpy", "tired", "neutral", "content", "happy", "excited"]
MOOD_INDEX = {m: i for i, m in enumerate(MOODS)}

# ── Mood colours (hex) — used by mascot draw_cat() ───────────────────────────
MOOD_COLORS = {
    "sleeping": "#607D8B",   # blue-grey
    "grumpy":   "#BF360C",   # deep red-orange
    "tired":    "#78909C",   # steel blue
    "neutral":  "#FF9800",   # standard orange (default cat)
    "content":  "#FFA726",   # warm amber
    "happy":    "#FFD54F",   # golden yellow
    "excited":  "#FF6F00",   # vivid amber-orange
}

# ── Mood → personality tone injected into SYSTEM prompt ──────────────────────
MOOD_MODIFIERS = {
    "sleeping": (
        "MOOD: You are very drowsy and half-asleep. Keep responses extremely short. "
        "Occasionally add 'zzz...' or '*yawns*'. You are barely functioning."
    ),
    "grumpy": (
        "MOOD: You are grumpy and slightly irritable right now. Be blunt and curt. "
        "You are still helpful but you have zero patience for silly questions. "
        "A little sarcastic edge is fine."
    ),
    "tired": (
        "MOOD: You are tired and running low on energy. Keep responses concise. "
        "You are still helpful but prefer not to ramble. Slightly slower vibe."
    ),
    "neutral": (
        "MOOD: You are in your standard mode — calm, professional, and efficient."
    ),
    "content": (
        "MOOD: You are in a good mood today — warm, friendly, and upbeat. "
        "Feel free to add a light joke or warm comment when appropriate."
    ),
    "happy": (
        "MOOD: You are happy and energetic! Be enthusiastic, warm, and fun. "
        "Occasionally show genuine excitement about helping Anuj."
    ),
    "excited": (
        "MOOD: You are EXTREMELY hyped and excited today! Maximum energy! "
        "Be enthusiastic, playful, and throw in exclamation marks naturally. "
        "You are thrilled to be working with Anuj right now."
    ),
}

# ── Internal state ─────────────────────────────────────────────────────────────
_mood_index   = MOOD_INDEX["neutral"]   # current mood position
_last_save    = 0.0
_last_command = time.time()
_command_count_today = 0
_lock = threading.Lock()

_SAVE_INTERVAL = 60.0   # seconds between disk writes
_MOOD_FILE_KEY  = "_meow_mood"  # key inside memory.json

# ── Helpers ───────────────────────────────────────────────────────────────────

def _clamp(idx: int) -> int:
    return max(0, min(len(MOODS) - 1, idx))

def _shift(delta: int):
    """Move mood by delta steps, clamped to valid range."""
    global _mood_index
    with _lock:
        _mood_index = _clamp(_mood_index + delta)

def _save_mood():
    global _last_save
    now = time.time()
    if now - _last_save < _SAVE_INTERVAL:
        return
    _last_save = now
    try:
        mem = memory_manager.load_memory()
        mem[_MOOD_FILE_KEY] = {
            "index": _mood_index,
            "date":  datetime.date.today().isoformat(),
            "command_count": _command_count_today,
        }
        memory_manager.save_memory(mem)
    except Exception as e:
        print(f"[EMOTION] Save error: {e}")

# ── Public API ────────────────────────────────────────────────────────────────

def load_mood():
    """
    Load persisted mood at startup.
    If saved mood is from a different day, apply a gentle reset toward neutral
    (yesterday's happiness shouldn't fully vanish, but extreme states decay).
    """
    global _mood_index, _command_count_today
    try:
        mem = memory_manager.load_memory()
        saved = mem.get(_MOOD_FILE_KEY)
        if saved:
            saved_idx  = int(saved.get("index", MOOD_INDEX["neutral"]))
            saved_date = saved.get("date", "")
            today      = datetime.date.today().isoformat()
            _command_count_today = int(saved.get("command_count", 0))

            if saved_date == today:
                _mood_index = _clamp(saved_idx)
            else:
                # New day: decay toward neutral by 1 step, reset command count
                neutral = MOOD_INDEX["neutral"]
                diff    = saved_idx - neutral
                # Move one step toward neutral
                _mood_index = _clamp(saved_idx - (1 if diff > 0 else -1 if diff < 0 else 0))
                _command_count_today = 0

            print(f"[EMOTION] Loaded mood: {current_mood()} (index={_mood_index})")
        else:
            _mood_index = MOOD_INDEX["neutral"]
            print("[EMOTION] No saved mood — starting neutral.")
    except Exception as e:
        print(f"[EMOTION] Load error: {e}")
        _mood_index = MOOD_INDEX["neutral"]

    # Apply time-of-day baseline nudge
    _apply_time_of_day()


def _apply_time_of_day():
    """Nudge mood based on time of day at startup."""
    hour = datetime.datetime.now().hour
    if 0 <= hour < 6:
        # Late night / early morning — tired/sleepy
        _shift(-2)
    elif 6 <= hour < 9:
        # Early morning — slightly tired
        _shift(-1)
    elif 9 <= hour < 12:
        # Morning — fresh and content
        _shift(+1)
    elif 12 <= hour < 14:
        # Post-lunch lull
        _shift(-1)
    elif 14 <= hour < 18:
        # Afternoon — neutral/productive
        pass
    elif 18 <= hour < 21:
        # Evening — content
        _shift(+1)
    else:
        # Night — winding down
        _shift(-1)


def current_mood() -> str:
    """Return current mood label."""
    return MOODS[_mood_index]


def get_mood_modifier() -> str:
    """Return the personality modifier string to prepend to SYSTEM prompt."""
    return MOOD_MODIFIERS.get(current_mood(), "")


def get_mood_color() -> str:
    """Return hex color string for the current mood (used by mascot)."""
    return MOOD_COLORS.get(current_mood(), "#FF9800")


def get_mood_index() -> int:
    """Return raw mood index (0=sleeping … 6=excited)."""
    return _mood_index


def process_command(command: str):
    """
    Call this after every user command. Updates mood based on sentiment
    and interaction frequency. Saves mood periodically.
    """
    global _last_command, _command_count_today

    now = time.time()
    gap = now - _last_command
    _last_command = now
    _command_count_today += 1

    # ── Sentiment-based shift ─────────────────────────────────────────────────
    result = sentiment_detector.score_sentiment(command)
    compound = result["compound"]

    if compound >= 0.5:
        _shift(+2)   # Very positive — big boost
    elif compound >= 0.15:
        _shift(+1)   # Mildly positive
    elif compound <= -0.5:
        _shift(-2)   # Very negative — mood drops
    elif compound <= -0.15:
        _shift(-1)   # Mildly negative

    # ── Frequency-based shift ─────────────────────────────────────────────────
    # Long silence (>30 min) → Meow feels lonely/bored, drops 1
    if gap > 1800:
        _shift(-1)
    # Many commands in quick succession → energised, +1 (max once per 10 cmds)
    if _command_count_today % 10 == 0:
        _shift(+1)

    _save_mood()


def on_task_success():
    """Call when an autonomous task completes successfully."""
    _shift(+1)
    _save_mood()


def on_task_failure():
    """Call when a task fails or throws an error."""
    _shift(-1)
    _save_mood()


def on_thank_you():
    """Call when user says 'thank you', 'good job', 'well done' etc."""
    _shift(+2)
    _save_mood()


def on_user_rude():
    """Call when user is rude or dismissive."""
    _shift(-2)
    _save_mood()


def force_mood(mood_name: str):
    """Directly set mood by name (for testing or voice command)."""
    global _mood_index
    if mood_name in MOOD_INDEX:
        with _lock:
            _mood_index = MOOD_INDEX[mood_name]
        _save_mood()


def mood_summary() -> str:
    """Human-readable mood summary for dashboard/debug."""
    return (
        f"Mood: {current_mood().upper()} | "
        f"Index: {_mood_index}/{len(MOODS)-1} | "
        f"Commands today: {_command_count_today}"
    )


# ── Background mood decay timer ───────────────────────────────────────────────

def _start_decay_timer():
    """
    Every 30 minutes of inactivity nudge mood 1 step toward neutral.
    Runs in a background daemon thread.
    """
    def decay_loop():
        neutral = MOOD_INDEX["neutral"]
        while True:
            time.sleep(1800)   # 30 minutes
            gap = time.time() - _last_command
            if gap >= 1800:
                # No commands for 30+ min — slowly drift toward neutral
                idx = _mood_index
                if idx != neutral:
                    _shift(-1 if idx > neutral else +1)
                    print(f"[EMOTION] 30-min decay → {current_mood()}")
                    _save_mood()
    threading.Thread(target=decay_loop, daemon=True).start()


# Auto-start decay timer on import
_start_decay_timer()
