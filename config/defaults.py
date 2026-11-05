"""
config/defaults.py — Default values for all MEOW settings.

These constants are the single source of truth for fallback values.
They are used by config.settings when neither .env nor memory.json
provides a value for a given setting.
"""

# ── LLM Provider API Keys ──────────────────────────────────────────
DEFAULT_GEMINI_API_KEY = ""
DEFAULT_GROQ_API_KEY = ""
DEFAULT_NVIDIA_API_KEY = ""
DEFAULT_OPENROUTER_API_KEY = ""

# ── Text-to-Speech ──────────────────────────────────────────────────
DEFAULT_ELEVENLABS_API_KEY = ""
DEFAULT_ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_KOKORO_VOICE = "af_sarah"
DEFAULT_KOKORO_VOICE_MIX = {
    "af_sarah": 0.5,
    "af_bella": 0,
    "af_nicole": 0,
    "bf_emma": 0,
    "am_adam": 0,
    "am_michael": 0,
    "bm_george": 0,
}

# ── Model / TTS Selection ──────────────────────────────────────────
DEFAULT_SELECTED_MODEL = "gemini"
DEFAULT_SELECTED_TTS = "sapi"

# ── Assistant Behaviour ─────────────────────────────────────────────
DEFAULT_WAKE_WORD = "mark"
DEFAULT_WEATHER_CITY = "Pune"
DEFAULT_AVATAR_TYPE = "3d_hologram"
DEFAULT_VOICE_STYLE = "casual"

# ── Security & API Server ──────────────────────────────────────────
DEFAULT_MEOW_API_KEY = ""

# ── File / Directory Paths (relative to project root) ──────────────
DEFAULT_DATA_DIR = "."          # memory.json etc. live in the project root
DEFAULT_LOG_DIR = "logs"
DEFAULT_DB_FILENAME = "meow.db"
