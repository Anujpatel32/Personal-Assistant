"""
tts_engine.py — Text-to-Speech Engine for MEOW Assistant
=========================================================
Handles all speech synthesis: SAPI (default), ElevenLabs, and Kokoro ONNX.
Imported by companion.py. Do NOT import companion.py from here (circular).
"""

import os
import re
import time
import threading
import urllib.request
import ssl
import json

import memory_manager
# flask_app is injected at runtime via init_tts(app) to avoid circular imports
flask_app = None

def init_tts(app):
    """Call this once from companion.py after flask_app is created."""
    global flask_app
    flask_app = app


# ---------------------------------------------------------------------------
# Text Sanitizer
# ---------------------------------------------------------------------------
def clean_text_for_tts(text):
    """Strip URLs, markdown, emojis and other non-speakable artifacts."""
    # Remove raw URLs (http, https, www) — never read links aloud
    text = re.sub(r'https?://[^\s)>"]+', 'link shown on screen', text)
    text = re.sub(r'www\.[^\s)>"]+', 'link shown on screen', text)
    # Remove markdown code blocks
    text = re.sub(r'```.*?```', ' code block displayed on dashboard ', text, flags=re.DOTALL)
    # Remove inline code
    text = re.sub(r'`([^`]*)`', r'\1', text)
    # Remove markdown table rows (lines with pipes)
    text = re.sub(r'^\|.*\|$', '', text, flags=re.MULTILINE)
    # Remove table separator lines (|---|---|)
    text = re.sub(r'^\|?[\s\-:]+\|[\s\-:|]+$', '', text, flags=re.MULTILINE)
    # Remove horizontal rules (---, ***, ___)
    text = re.sub(r'^[\s]*[-*_]{3,}[\s]*$', '', text, flags=re.MULTILINE)
    # Remove markdown headers (# ## ### etc)
    text = re.sub(r'#{1,6}\s*', '', text)
    # Remove bold/italic markers (** __ * _)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', text)
    # Remove markdown links [text](url) -> text
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Remove markdown images ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Remove bullet point markers (- * +)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    # Remove numbered list markers (1. 2. etc)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Remove blockquote markers
    text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE)
    # Remove emojis and special unicode symbols
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002700-\U000027BF"  # dingbats
        "\U0000FE00-\U0000FE0F"  # variation selectors
        "\U0000200D"             # zero width joiner
        "\U000020E3"             # combining enclosing keycap
        "\U00002600-\U000026FF"  # misc symbols
        "\U00002300-\U000023FF"  # misc technical
        "\U0000200B-\U0000200F"  # zero width spaces
        "\U0000205F-\U00002060"  # word joiner
        "\U0001F900-\U0001F9FF"  # supplemental symbols
        "\U0001FA00-\U0001FA6F"  # chess symbols
        "\U0001FA70-\U0001FAFF"  # symbols extended-A
        "\U00002702-\U000027B0"  # dingbats
        "\U0000231A-\U0000231B"  # watch/hourglass
        "\U000025AA-\U000025AB"  # squares
        "\U000025FB-\U000025FE"  # squares
        "\U00010000-\U0010FFFF"  # all supplementary planes
        "]+", flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)
    # Remove any remaining non-ASCII characters
    text = text.encode('ascii', 'ignore').decode('ascii')
    # Clean up double spaces/newlines
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ---------------------------------------------------------------------------
# SAPI (Windows built-in TTS)
# ---------------------------------------------------------------------------
_main_sapi_voice = None
_main_sapi_voice_lock = threading.Lock()

def get_main_sapi_voice():
    global _main_sapi_voice
    if _main_sapi_voice is None:
        with _main_sapi_voice_lock:
            if _main_sapi_voice is None:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                try:
                    _main_sapi_voice = win32com.client.Dispatch("SAPI.SpVoice")
                    # Set David voice
                    voices = _main_sapi_voice.GetVoices()
                    for v in voices:
                        if "david" in v.GetDescription().lower():
                            _main_sapi_voice.Voice = v
                            break
                    _main_sapi_voice.Rate = 1
                except Exception as e:
                    print(f"[MAIN SAPI VOICE INIT ERROR]: {e}", flush=True)
    return _main_sapi_voice

def play_sapi(text, on_start_speaking=None):
    try:
        import pythoncom
        pythoncom.CoInitialize()
        voice = get_main_sapi_voice()
        if voice is None:
            import win32com.client
            voice = win32com.client.Dispatch("SAPI.SpVoice")

        flask_app.stop_speaking_flag = False
        with flask_app.active_engine_lock:
            flask_app.active_engine = voice

        if on_start_speaking:
            on_start_speaking()

        voice.Speak(text, 1)  # async speak

        while not flask_app.stop_speaking_flag:
            try:
                if voice.Status.RunningState != 2:
                    break
            except Exception:
                break
            time.sleep(0.05)

        if flask_app.stop_speaking_flag:
            try:
                voice.Speak("", 2)  # purge
            except Exception:
                pass
    except Exception as e:
        print(f"[SAPI PLAY ERROR]: {e}", flush=True)
    finally:
        with flask_app.active_engine_lock:
            flask_app.active_engine = None


# ---------------------------------------------------------------------------
# Audio File Playback (used by ElevenLabs & Kokoro)
# ---------------------------------------------------------------------------
def play_audio_file(file_path, on_start_speaking=None):
    import pygame
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(file_path)
        flask_app.stop_speaking_flag = False

        if on_start_speaking:
            on_start_speaking()

        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if flask_app.stop_speaking_flag:
                pygame.mixer.music.stop()
                break
            time.sleep(0.05)
        pygame.mixer.music.unload()
    except Exception as e:
        print(f"[AUDIO PLAY ERROR]: {e}", flush=True)
    finally:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Kokoro ONNX TTS
# ---------------------------------------------------------------------------
_kokoro_instance = None
_kokoro_lock = threading.Lock()

def get_kokoro():
    global _kokoro_instance
    if _kokoro_instance is None:
        with _kokoro_lock:
            if _kokoro_instance is None:
                ensure_kokoro_files()
                from kokoro_onnx import Kokoro
                print("[TTS] Loading Kokoro brain...", flush=True)
                _kokoro_instance = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
    return _kokoro_instance

def ensure_kokoro_files():
    context = ssl._create_unverified_context()
    onnx_path = "kokoro-v1.0.onnx"
    bin_path = "voices-v1.0.bin"

    def download_file(url, path, label):
        print(f"[TTS] Downloading {label} from {url}...", flush=True)
        with flask_app.state_lock:
            flask_app.assistant_state["status"] = "thinking"
            flask_app.assistant_state["chat_log"].append({
                "text": f"SYSTEM: Downloading local neural voice files for Kokoro TTS. Please wait...",
                "sender": "assistant"
            })

        temp_path = path + ".tmp"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, context=context, timeout=30) as response, open(temp_path, "wb") as out_file:
                while True:
                    chunk = response.read(1024 * 64)
                    if not chunk:
                        break
                    out_file.write(chunk)
            if os.path.exists(temp_path):
                os.rename(temp_path, path)
            print(f"[TTS] Downloaded {label} successfully!", flush=True)
        except Exception as e:
            print(f"[TTS DOWNLOAD ERROR] Failed to download {label}: {e}", flush=True)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise e

    if not os.path.exists(onnx_path):
        download_file(
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
            onnx_path,
            "Kokoro ONNX Model (~84MB)"
        )
    if not os.path.exists(bin_path):
        download_file(
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
            bin_path,
            "Kokoro Voices data (~15MB)"
        )


# ---------------------------------------------------------------------------
# Unified speak_sync_global — dispatches to the active TTS engine
# ---------------------------------------------------------------------------
def speak_sync_global(text, on_start_speaking=None):
    text = clean_text_for_tts(text)
    if not text.strip():
        if on_start_speaking:
            on_start_speaking()
        return

    config = memory_manager.load_config()
    selected_tts = config.get("selected_tts", "sapi")

    if selected_tts == "sapi":
        play_sapi(text, on_start_speaking=on_start_speaking)

    elif selected_tts == "elevenlabs":
        api_key = config.get("elevenlabs_api_key", "")
        voice_id = config.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
        if not api_key:
            print("[TTS] ElevenLabs key missing. Falling back to SAPI.", flush=True)
            play_sapi(text, on_start_speaking=on_start_speaking)
            return
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            headers = {
                "Content-Type": "application/json",
                "xi-api-key": api_key
            }
            body = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=15, context=context) as response:
                audio_data = response.read()

            temp_file = "temp_eleven.mp3"
            with open(temp_file, "wb") as f:
                f.write(audio_data)

            play_audio_file(temp_file, on_start_speaking=on_start_speaking)
        except Exception as e:
            print(f"[TTS ERROR] ElevenLabs failed: {e}. Falling back to SAPI.", flush=True)
            play_sapi(text, on_start_speaking=on_start_speaking)

    elif selected_tts == "kokoro":
        try:
            kokoro = get_kokoro()
            kokoro_voice = config.get("kokoro_voice", "af_sarah")

            voice_param = kokoro_voice
            if kokoro_voice == "custom_mix":
                voice_mix = config.get("kokoro_voice_mix", {})
                if voice_mix:
                    import numpy as np
                    blended_vector = None
                    total_weight = sum(voice_mix.values())
                    if total_weight > 0:
                        for v_name, weight in voice_mix.items():
                            normalized_weight = weight / total_weight
                            try:
                                style = kokoro.get_voice_style(v_name)
                                if blended_vector is None:
                                    blended_vector = style * normalized_weight
                                else:
                                    blended_vector += style * normalized_weight
                            except Exception:
                                pass
                        if blended_vector is not None:
                            voice_param = blended_vector

            samples, sample_rate = kokoro.create(
                text,
                voice=voice_param,
                speed=1.0,
                lang="en-us"
            )

            import soundfile as sf
            temp_file = "temp_kokoro.wav"
            sf.write(temp_file, samples, sample_rate)

            play_audio_file(temp_file, on_start_speaking=on_start_speaking)
        except Exception as e:
            print(f"[TTS ERROR] Kokoro failed: {e}. Falling back to SAPI.", flush=True)
            play_sapi(text, on_start_speaking=on_start_speaking)


def speak_async(text):
    """Fire-and-forget: speak in a background thread."""
    threading.Thread(target=speak_sync_global, args=(text,), daemon=True).start()


# ---------------------------------------------------------------------------
# Voice 2.0 — Sentence-chunked Streaming TTS
# ---------------------------------------------------------------------------
def _split_into_sentences(text: str):
    """Split text at sentence boundaries for streaming playback."""
    # Split on . ! ? followed by space or end of string
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    # Merge very short fragments (< 4 words) with next sentence to avoid
    # weird TTS starts ("Ah." "Okay." as separate clips)
    merged = []
    buf = ""
    for p in parts:
        buf = (buf + " " + p).strip() if buf else p
        if len(buf.split()) >= 4:
            merged.append(buf)
            buf = ""
    if buf:
        merged.append(buf)
    return merged if merged else [text]


def speak_streamed(text: str):
    """
    Sentence-chunked streaming TTS.
    Starts speaking sentence 1 immediately while sentence 2+ queues up.
    Reduces perceived latency from ~3s to ~0.3s.
    """
    text = clean_text_for_tts(text)
    if not text.strip():
        return

    sentences = _split_into_sentences(text)
    if len(sentences) == 1:
        # Single sentence — no benefit from chunking, just speak normally
        speak_sync_global(text)
        return

    config = memory_manager.load_config()
    selected_tts = config.get("selected_tts", "sapi")

    if selected_tts == "sapi":
        # SAPI is fast — speak each sentence sequentially on this thread
        # so stop_speaking_flag is respected between sentences
        for sentence in sentences:
            if flask_app and flask_app.stop_speaking_flag:
                break
            if sentence.strip():
                play_sapi(sentence)

    elif selected_tts == "kokoro":
        # Pre-synthesise each sentence sequentially; play immediately
        for sentence in sentences:
            if flask_app and flask_app.stop_speaking_flag:
                break
            if not sentence.strip():
                continue
            try:
                kokoro = get_kokoro()
                kokoro_voice = config.get("kokoro_voice", "af_sarah")
                samples, sample_rate = kokoro.create(sentence, voice=kokoro_voice, speed=1.0, lang="en-us")
                import soundfile as sf
                temp_file = f"temp_kokoro_chunk_{threading.get_ident()}.wav"
                sf.write(temp_file, samples, sample_rate)
                play_audio_file(temp_file)
            except Exception as e:
                print(f"[TTS STREAM ERROR] Kokoro chunk failed: {e}")
                play_sapi(sentence)

    elif selected_tts == "elevenlabs":
        # ElevenLabs has network latency — chunk by sentence still helps
        for sentence in sentences:
            if flask_app and flask_app.stop_speaking_flag:
                break
            if sentence.strip():
                speak_sync_global(sentence)
    else:
        speak_sync_global(text)
