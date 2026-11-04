# -*- coding: utf-8 -*-
"""
logging_config.py — Structured Logging Configuration for MEOW Assistant
=========================================================================
Configures Python's logging module with project-wide loggers, a console
handler (INFO), and a rotating file handler (DEBUG → logs/meow.log).

Usage:
    from config.logging_config import setup_logging
    setup_logging()            # default: root at DEBUG
    setup_logging(level="INFO") # override root level
"""

import os
import logging
from logging.handlers import RotatingFileHandler

# ── Log directory (auto-created) ──────────────────────────────────────────────
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")

# ── Logger hierarchy ─────────────────────────────────────────────────────────
_LOGGER_NAMES = [
    "meow",           # root for the project
    "meow.core",      # companion.py, app.py, emotion_engine.py, etc.
    "meow.llm",       # llm_router.py
    "meow.voice",     # voice_thread.py, tts_engine.py, voice_personality.py
    "meow.tools",     # tool_registry.py, action_planner.py, pc_control.py
    "meow.web",       # app.py Flask routes
    "meow.gesture",   # gesture_control.py
    "meow.memory",    # memory_manager.py, knowledge_manager.py
    "meow.vision",    # vision_control.py, screen_memory.py
]

_CONSOLE_FMT = "[%(name)s] %(levelname)s: %(message)s"
_FILE_FMT    = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

_MAX_BYTES    = 10 * 1024 * 1024   # 10 MB
_BACKUP_COUNT = 3


def setup_logging(level: str = "DEBUG") -> None:
    """
    Configure project-wide logging.

    Parameters
    ----------
    level : str
        Root logger level (default ``"DEBUG"``).  Accepts any standard
        level name: ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, ``CRITICAL``.
    """
    # Ensure logs/ directory exists
    os.makedirs(_LOG_DIR, exist_ok=True)

    root_level = getattr(logging, level.upper(), logging.DEBUG)

    # ── Console handler (INFO) ────────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(_CONSOLE_FMT))

    # ── Rotating file handler (DEBUG) ─────────────────────────────────────────
    file_handler = RotatingFileHandler(
        os.path.join(_LOG_DIR, "meow.log"),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FMT))

    # ── Configure each project logger ─────────────────────────────────────────
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(root_level)
        # Avoid duplicate handlers on repeated calls
        if not logger.handlers:
            logger.addHandler(console_handler)
            logger.addHandler(file_handler)
        # Prevent propagation to root to avoid double output
        logger.propagate = False
