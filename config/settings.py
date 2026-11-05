"""
config/settings.py — Centralised, thread-safe configuration for MEOW.

Priority order (highest wins):
  1.  Environment variables  (loaded from .env via python-dotenv, or real env)
  2.  Values stored in memory.json  (current legacy behaviour)
  3.  Compile-time defaults in config.defaults

Usage:
    from config.settings import settings

    key = settings.gemini_api_key
    settings.reload()                     # re-read everything
    settings.save_api_keys()              # persist keys back to memory.json
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from config.defaults import (
    DEFAULT_AVATAR_TYPE,
    DEFAULT_DB_FILENAME,
    DEFAULT_DATA_DIR,
    DEFAULT_ELEVENLABS_API_KEY,
    DEFAULT_ELEVENLABS_VOICE_ID,
    DEFAULT_GEMINI_API_KEY,
    DEFAULT_GROQ_API_KEY,
    DEFAULT_KOKORO_VOICE,
    DEFAULT_KOKORO_VOICE_MIX,
    DEFAULT_LOG_DIR,
    DEFAULT_NVIDIA_API_KEY,
    DEFAULT_OPENROUTER_API_KEY,
    DEFAULT_SELECTED_MODEL,
    DEFAULT_SELECTED_TTS,
    DEFAULT_VOICE_STYLE,
    DEFAULT_WAKE_WORD,
    DEFAULT_WEATHER_CITY,
    DEFAULT_AVATAR_TYPE,
    DEFAULT_MEOW_API_KEY,
)


class Settings:
    """Singleton configuration object for the MEOW assistant.

    Thread-safe: every public write goes through ``_lock``.
    """

    _instance: Optional["Settings"] = None
    _init_done: bool = False

    # ── Singleton ───────────────────────────────────────────────────
    def __new__(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if Settings._init_done:
            return
        self._lock = threading.Lock()
        self._base_dir = Path(__file__).resolve().parent.parent
        self._load()
        Settings._init_done = True

    # ── Internal helpers ────────────────────────────────────────────
    def _load_memory_data(self) -> Dict[str, Any]:
        """Read memory.json from disk (best-effort, returns {} on failure)."""
        mem_path = self._base_dir / "memory.json"
        if not mem_path.exists():
            return {}
        try:
            with open(mem_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            print(f"[CONFIG] Warning: could not read memory.json: {exc}")
            return {}

    def _resolve(
        self,
        env_key: str,
        memory_key: str,
        default: Any,
        memory_data: Dict[str, Any],
    ) -> Any:
        """Return the first non-empty value from env → memory → default."""
        # 1. Environment variable (highest priority)
        env_val = os.environ.get(env_key)
        if env_val is not None and env_val != "":
            return env_val

        # 2. memory.json value
        mem_val = memory_data.get(memory_key)
        if mem_val is not None and mem_val != "":
            return mem_val

        # 3. Compile-time default
        return default

    def _load(self) -> None:
        """(Re-)read all configuration sources."""
        # Load .env file if present (does NOT override real env vars)
        dotenv_path = self._base_dir / ".env"
        if dotenv_path.exists():
            load_dotenv(dotenv_path, override=False)

        mem = self._load_memory_data()

        # ── API keys ────────────────────────────────────────────────
        self._gemini_api_key: str = self._resolve(
            "GEMINI_API_KEY", "gemini_api_key", DEFAULT_GEMINI_API_KEY, mem
        )
        self._groq_api_key: str = self._resolve(
            "GROQ_API_KEY", "groq_api_key", DEFAULT_GROQ_API_KEY, mem
        )
        self._nvidia_api_key: str = self._resolve(
            "NVIDIA_API_KEY", "nvidia_api_key", DEFAULT_NVIDIA_API_KEY, mem
        )
        self._openrouter_api_key: str = self._resolve(
            "OPENROUTER_API_KEY", "openrouter_api_key", DEFAULT_OPENROUTER_API_KEY, mem
        )
        self._elevenlabs_api_key: str = self._resolve(
            "ELEVENLABS_API_KEY", "elevenlabs_api_key", DEFAULT_ELEVENLABS_API_KEY, mem
        )
        self._elevenlabs_voice_id: str = self._resolve(
            "ELEVENLABS_VOICE_ID", "elevenlabs_voice_id", DEFAULT_ELEVENLABS_VOICE_ID, mem
        )
        self._meow_api_key: str = self._resolve(
            "MEOW_API_KEY", "meow_api_key", DEFAULT_MEOW_API_KEY, mem
        )

        # ── Model / TTS selection ──────────────────────────────────
        self._selected_model: str = self._resolve(
            "SELECTED_MODEL", "selected_model", DEFAULT_SELECTED_MODEL, mem
        )
        self._selected_tts: str = self._resolve(
            "SELECTED_TTS", "selected_tts", DEFAULT_SELECTED_TTS, mem
        )

        # ── Kokoro TTS ─────────────────────────────────────────────
        self._kokoro_voice: str = self._resolve(
            "KOKORO_VOICE", "kokoro_voice", DEFAULT_KOKORO_VOICE, mem
        )
        # kokoro_voice_mix is a dict — env vars can't express it, so
        # only memory.json or the default is used.
        self._kokoro_voice_mix: dict = mem.get("kokoro_voice_mix", DEFAULT_KOKORO_VOICE_MIX)

        # ── Behaviour ──────────────────────────────────────────────
        self._wake_word: str = self._resolve(
            "WAKE_WORD", "wake_word", DEFAULT_WAKE_WORD, mem
        )
        self._weather_city: str = self._resolve(
            "WEATHER_CITY", "weather_city", DEFAULT_WEATHER_CITY, mem
        )
        self._avatar_type: str = self._resolve(
            "AVATAR_TYPE", "avatar_type", DEFAULT_AVATAR_TYPE, mem
        )
        self._voice_style: str = self._resolve(
            "VOICE_STYLE", "voice_style", DEFAULT_VOICE_STYLE, mem
        )

        # ── Directories / paths ────────────────────────────────────
        data_dir_raw = self._resolve(
            "DATA_DIR", "data_dir", DEFAULT_DATA_DIR, mem
        )
        self._data_dir: Path = (self._base_dir / data_dir_raw).resolve()

        log_dir_raw = self._resolve(
            "LOG_DIR", "log_dir", DEFAULT_LOG_DIR, mem
        )
        self._log_dir: Path = (self._base_dir / log_dir_raw).resolve()

        db_filename = self._resolve(
            "DB_FILENAME", "db_filename", DEFAULT_DB_FILENAME, mem
        )
        self._db_path: Path = (self._data_dir / db_filename).resolve()

    # ── Public read-only properties ─────────────────────────────────
    @property
    def base_dir(self) -> Path:
        """Project root directory."""
        return self._base_dir

    @property
    def data_dir(self) -> Path:
        """Directory where memory.json, tasks.json, etc. live."""
        return self._data_dir

    @property
    def log_dir(self) -> Path:
        """Directory for log files."""
        return self._log_dir

    @property
    def db_path(self) -> Path:
        """Full path to the SQLite database file."""
        return self._db_path

    # ── API keys ────────────────────────────────────────────────────
    @property
    def gemini_api_key(self) -> str:
        return self._gemini_api_key

    @property
    def groq_api_key(self) -> str:
        return self._groq_api_key

    @property
    def nvidia_api_key(self) -> str:
        return self._nvidia_api_key

    @property
    def openrouter_api_key(self) -> str:
        return self._openrouter_api_key

    @property
    def elevenlabs_api_key(self) -> str:
        return self._elevenlabs_api_key

    @property
    def elevenlabs_voice_id(self) -> str:
        return self._elevenlabs_voice_id

    @property
    def meow_api_key(self) -> str:
        return self._meow_api_key

    # ── Model / TTS ─────────────────────────────────────────────────
    @property
    def selected_model(self) -> str:
        return self._selected_model

    @property
    def selected_tts(self) -> str:
        return self._selected_tts

    # ── Kokoro ──────────────────────────────────────────────────────
    @property
    def kokoro_voice(self) -> str:
        return self._kokoro_voice

    @property
    def kokoro_voice_mix(self) -> dict:
        return dict(self._kokoro_voice_mix)  # return a copy

    # ── Behaviour ───────────────────────────────────────────────────
    @property
    def wake_word(self) -> str:
        return self._wake_word

    @property
    def weather_city(self) -> str:
        return self._weather_city

    @property
    def avatar_type(self) -> str:
        return self._avatar_type

    @property
    def voice_style(self) -> str:
        return self._voice_style

    # ── Mutation helpers ────────────────────────────────────────────
    def reload(self) -> None:
        """Re-read settings from .env and memory.json."""
        with self._lock:
            self._load()

    def save_api_keys(self) -> None:
        """Persist the current API keys and selection prefs back to memory.json.

        This keeps backward compatibility with the web dashboard settings UI,
        which reads/writes directly to memory.json.
        """
        with self._lock:
            mem_path = self._base_dir / "memory.json"

            # Read existing data so we don't clobber non-config fields
            if mem_path.exists():
                try:
                    with open(mem_path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except Exception:
                    data = {}
            else:
                data = {}

            # Write back every key that memory.json traditionally stores
            data["gemini_api_key"] = self._gemini_api_key
            data["groq_api_key"] = self._groq_api_key
            data["nvidia_api_key"] = self._nvidia_api_key
            data["openrouter_api_key"] = self._openrouter_api_key
            data["elevenlabs_api_key"] = self._elevenlabs_api_key
            data["elevenlabs_voice_id"] = self._elevenlabs_voice_id
            data["selected_model"] = self._selected_model
            data["selected_tts"] = self._selected_tts
            data["kokoro_voice"] = self._kokoro_voice
            data["kokoro_voice_mix"] = self._kokoro_voice_mix
            data["avatar_type"] = self._avatar_type
            data["voice_style"] = self._voice_style

            try:
                with open(mem_path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=4, ensure_ascii=False)
            except Exception as exc:
                print(f"[CONFIG] Error: could not write memory.json: {exc}")

    def to_dict(self) -> Dict[str, Any]:
        """Return a snapshot of all settings as a plain dict (useful for debugging)."""
        return {
            "base_dir": str(self._base_dir),
            "data_dir": str(self._data_dir),
            "log_dir": str(self._log_dir),
            "db_path": str(self._db_path),
            "gemini_api_key": "(set)" if self._gemini_api_key else "(empty)",
            "groq_api_key": "(set)" if self._groq_api_key else "(empty)",
            "nvidia_api_key": "(set)" if self._nvidia_api_key else "(empty)",
            "openrouter_api_key": "(set)" if self._openrouter_api_key else "(empty)",
            "elevenlabs_api_key": "(set)" if self._elevenlabs_api_key else "(empty)",
            "elevenlabs_voice_id": self._elevenlabs_voice_id,
            "selected_model": self._selected_model,
            "selected_tts": self._selected_tts,
            "kokoro_voice": self._kokoro_voice,
            "kokoro_voice_mix": self._kokoro_voice_mix,
            "wake_word": self._wake_word,
            "weather_city": self._weather_city,
            "avatar_type": self._avatar_type,
            "voice_style": self._voice_style,
        }

    def __repr__(self) -> str:
        return f"<Settings model={self._selected_model!r} tts={self._selected_tts!r}>"


# ── Module-level convenience singleton ──────────────────────────────
settings = Settings()
