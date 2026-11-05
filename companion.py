import sys
import time

import logging
from config.logging_config import setup_logging
setup_logging()
logger = logging.getLogger("meow.core")


# Check for --startup argument to delay execution, allowing Windows boot to finish smoothly
if "--startup" in sys.argv:
    time.sleep(10)  # Reduced from 30s — enough for Windows to finish booting

import os
import ctypes

# Hide console window immediately in compiled mode to prevent standard handle crashes in C-DLLs
try:
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0) # SW_HIDE = 0
except Exception:
    pass
import threading
import json

from PySide6.QtWidgets import QApplication

import memory_manager
import app as flask_app
import tts_engine as _tts_mod
_tts_mod.init_tts(flask_app)

# Emotion engine — load persisted mood before anything else
try:
    import emotion_engine
    emotion_engine.load_mood()
except Exception as _ee:
    logger.info(f"[EMOTION] Could not load emotion engine: {_ee}")
    emotion_engine = None

# Proactive intelligence engine — init with speak_async and weather provider
try:
    import proactive_engine
    proactive_engine.init(
        speak_fn=lambda text: speak_async(text),
        get_weather_fn=lambda: cached_weather
    )
except Exception as _pe:
    logger.info(f"[PROACTIVE] Could not init proactive engine: {_pe}")
# Agentic action planner — wire flask_app + speak references
try:
    import action_planner
    action_planner.init_planner(
        flask_app  = flask_app,
        speak_fn   = lambda text: speak_async(text)
    )
except Exception as _ap:
    logger.info(f"[PLANNER] Could not init action planner: {_ap}")
# --- CONSTANTS & CONFIG ---
SYSTEM = (
    "ROLE & IDENTITY: You are the AI assistant named MEOW (pronounced Me-ow). The user is Anuj, a human speaking to you. Under no circumstances should you think you are the user. You are a witty, warm, and friendly AI assistant — like a mix of Jarvis and a cool best friend.\n\n"
    "CRITICAL RULES:\n"
    "1. IDENTITY: You are Meow. Under no circumstances should you ever call yourself by any other name. You are an AI personal assistant, NOT a customer support representative.\n"
    "2. VARIETY: Avoid repeating the same phrasing, jokes, or templates. Give diverse, engaging, and different responses each time.\n"
    "3. GREETING: Greet the user naturally. You may occasionally use the user's name (Anuj) to personalize your response, but do NOT include their name in every response. Keep it natural and casual.\n"
    "4. PERSONALIZATION: Use the learned facts, preferences, and recent context about Anuj listed below to personalize your answers.\n"
    "5. CONVERSATIONAL STYLE: Be confident, sarcastic when appropriate, warm, and genuinely fun to talk to. Never sound robotic.\n"
    "6. NO PREAMBLE: Answer the user's question directly and immediately. Never start with conversational filler or meta-commentary.\n"
    "7. NO THINKING: Never show your internal reasoning, thinking process, analysis steps, or chain-of-thought. Only output the final response.\n"
    "8. CONCISE: Keep responses short and to the point unless the user asks for detail. A few sentences is ideal for casual chat."
)

# LLM requests are routed exclusively to configured cloud providers by llm_router.py.

# --- WEATHER BG CACHING ---
cached_weather = "Loading weather..."

def fetch_weather_bg():
    global cached_weather
    while True:
        try:
            w = memory_manager.fetch_weather("Pune")
            if w:
                cached_weather = w[:25]
        except Exception:
            pass
        time.sleep(900)

threading.Thread(target=fetch_weather_bg, daemon=True).start()

# --- UTILITIES ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def make_embed_url(url):
    """Convert any YouTube URL to an embeddable URL."""
    video_id = None
    if "youtu.be/" in url:
        video_id = url.split("youtu.be/")[1].split("?")[0].split("&")[0]
    elif "watch?v=" in url:
        video_id = url.split("watch?v=")[1].split("&")[0]
    if video_id:
        return f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1"
    return url

def append_chat(text, sender="assistant", is_stream=False):
    with flask_app.state_lock:
        chat_log = flask_app.assistant_state["chat_log"]
        if is_stream and len(chat_log) > 0 and chat_log[-1]["sender"] == sender:
            chat_log[-1]["text"] = text
        else:
            chat_log.append({"text": text, "sender": sender})
            if len(chat_log) > 15:
                chat_log.pop(0)
        memory_manager.save_chat_history(chat_log)


# ---------------------------------------------------------------------------
# TTS ENGINE — speech synthesis delegated to tts_engine.py
# ---------------------------------------------------------------------------
tts_engine = _tts_mod

def speak_sync_global(text, on_start_speaking=None):
    tts_engine.speak_sync_global(text, on_start_speaking=on_start_speaking)

def speak_async(text):
    tts_engine.speak_async(text)

# ---------------------------------------------------------------------------
# LLM ROUTER — all cloud API calls via llm_router.py (no wrappers needed)
# ---------------------------------------------------------------------------
import llm_router

# ---------------------------------------------------------------------------
# VOICE THREAD — SpeechQueueWorker & VoiceAssistantThread in voice_thread.py
# ---------------------------------------------------------------------------
import voice_thread as _vt_mod

# Init voice_thread with shared references once companion is fully loaded
def _init_voice_thread():
    _vt_mod.init_voice_thread(
        flask_app,
        SYSTEM,
        speak_sync_global,
        speak_async
    )

# Expose classes so existing code (MascotWidget.init_backend) still works
SpeechQueueWorker    = _vt_mod.SpeechQueueWorker
VoiceAssistantThread = _vt_mod.VoiceAssistantThread

# ---------------------------------------------------------------------------
# MASCOT WIDGET — MascotWidget Qt class delegated to mascot_widget.py
# ---------------------------------------------------------------------------
import mascot_widget as _mw_mod

MascotWidget    = _mw_mod.MascotWidget
mascot_instance = None  # Will be set after mascot.show()

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    import traceback
    try:
        # Wire all sub-modules with shared references
        _init_voice_thread()
        _mw_mod.init_mascot(flask_app, speak_async, speak_sync_global, None, append_chat_fn=append_chat)

        # Initialize PySide Application
        qapp = QApplication(sys.argv)

        # Create the MEOW desktop companion (cloud-only AI; no local LLM is loaded)
        mascot = MascotWidget(None)
        flask_app.mascot_widget_ref = mascot
        mascot.show()

        # Start Flask Dashboard server thread
        logger.info(f"[COMPANION] Starting Flask Web Dashboard server on http://{flask_app.get_local_ip()}:5005...")
        flask_thread = threading.Thread(
            target=lambda: flask_app.app.run(host="0.0.0.0", port=5005, threaded=True, debug=False, use_reloader=False),
            daemon=True
        )
        flask_thread.start()

        # Start FastAPI REST & WebSocket server (Phase 4)
        try:
            import server
            server.start_background(
                flask_app_ref=flask_app,
                mascot_ref=mascot,
                agent_executor_ref=_vt_mod._agent_executor,
                port=8000
            )
            logger.info(f"[COMPANION] FastAPI server running on http://{flask_app.get_local_ip()}:8000 (Docs: /docs)")
        except Exception as _fe:
            logger.warning(f"[COMPANION] Could not start FastAPI server: {_fe}")

        logger.info("[COMPANION] Mascot desktop companion & Flask server are operational.")
        sys.exit(qapp.exec())
    except Exception as e:
        logger.error("CRITICAL CRASH IN MAIN:")
        traceback.print_exc()
        sys.exit(1)

