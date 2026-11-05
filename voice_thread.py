"""
voice_thread.py — Speech Queue Worker & Voice Assistant Thread for MEOW
=======================================================================
Handles background speech synthesis queueing (SpeechQueueWorker) and
the main voice assistant pipeline (VoiceAssistantThread).
Imported by companion.py.
"""

import os
import sys
import re
import time
import threading
import queue
import webbrowser
import urllib.parse
import urllib.request
import urllib.error

from PySide6.QtCore import QThread, Signal

import memory_manager
import pc_control
import knowledge_manager
import screen_memory
import tts_engine
import llm_router
import musicLibrary
import voice_personality  # Voice 2.0 style presets

# Phase 3: Tool-calling pipeline imports
import intent_router
import tool_registry
from agent_executor import AgentExecutor

# Emotion engine — safe import, no crash if missing
try:
    import emotion_engine as _emotion_mod
except Exception:
    _emotion_mod = None

# ---------------------------------------------------------------------------
# Delegate aliases — functions that lived in companion.py monolith
# ---------------------------------------------------------------------------
def query_llm(prompt, system_prompt, history=None, max_tokens=150, image_path=None):
    return llm_router.query_llm(prompt, system_prompt, history or [], max_tokens, image_path)

def query_llm_stream(prompt, system_prompt, history=None, max_tokens=150, image_path=None):
    yield from llm_router.query_llm_stream(prompt, system_prompt, history or [], max_tokens, image_path)

def play_sapi(text, on_start_speaking=None):
    tts_engine.play_sapi(text, on_start_speaking=on_start_speaking)

def play_audio_file(path, on_start_speaking=None):
    tts_engine.play_audio_file(path, on_start_speaking=on_start_speaking)

def get_kokoro():
    return tts_engine.get_kokoro()

def speak_sync_global(text, on_start_speaking=None):
    if _speak_sync_global:
        _speak_sync_global(text, on_start_speaking=on_start_speaking)
    else:
        tts_engine.speak_sync_global(text, on_start_speaking=on_start_speaking)

def _last_reasoning_details_get():
    return llm_router._last_reasoning_details

# Forward references injected at runtime from companion.py
flask_app = None
SYSTEM = ""
mascot_widget_ref = None
_speak_sync_global = None
_speak_async = None
_agent_executor = None  # Phase 3: ReAct agent executor instance

def init_voice_thread(app, system_prompt, speak_sync_fn, speak_async_fn):
    """Call once from companion.py after all modules are loaded."""
    global flask_app, SYSTEM, _speak_sync_global, _speak_async, _agent_executor
    flask_app = app
    SYSTEM = system_prompt
    _speak_sync_global = speak_sync_fn
    _speak_async = speak_async_fn
    # Phase 3: Initialize the agent executor with dashboard + speech callbacks
    _agent_executor = AgentExecutor(
        speak_fn=speak_async_fn,
        flask_app=app,
    )
# --- BACKEND VOICE WORKER ---
class SpeechQueueWorker(QThread):
    def __init__(self, speech_queue, audio_queue, status_callback=None):
        super().__init__()
        self.speech_queue = speech_queue
        self.audio_queue = audio_queue
        self.status_callback = status_callback
        self.running = True
        
    def run(self):
        import pythoncom
        import time
        
        # Start synthesis worker thread in background
        def synthesis_loop():
            import pythoncom
            pythoncom.CoInitialize()
            counter = 0
            _cached_voice_mix = None
            _cached_voice_param = None
            while self.running:
                try:
                    text = self.speech_queue.get(timeout=1.0)
                    if text == "__STOP__":
                        self.speech_queue.task_done()
                        continue
                        
                    config = memory_manager.load_config()
                    selected_tts = config.get("selected_tts", "sapi")
                    
                    if selected_tts == "sapi":
                        # SAPI is fast, pass text directly
                        self.audio_queue.put(("sapi", text))
                    elif selected_tts == "kokoro":
                        # Pre-synthesize Kokoro WAV file in background
                        try:
                            kokoro = get_kokoro()
                            kokoro_voice = config.get("kokoro_voice", "af_sarah")
                            
                            voice_param = kokoro_voice
                            if kokoro_voice == "custom_mix":
                                voice_mix = config.get("kokoro_voice_mix", {})
                                if voice_mix:
                                    if voice_mix == _cached_voice_mix and _cached_voice_param is not None:
                                        voice_param = _cached_voice_param
                                    else:
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
                                                _cached_voice_mix = dict(voice_mix)
                                                _cached_voice_param = blended_vector
                            
                            samples, sample_rate = kokoro.create(
                                text,
                                voice=voice_param,
                                speed=1.0,
                                lang="en-us"
                            )
                            import soundfile as sf
                            import os
                            temp_dir = os.environ.get("TEMP", "")
                            file_path = os.path.join(temp_dir, f"temp_kokoro_{counter}_{int(time.time())}.wav")
                            sf.write(file_path, samples, sample_rate)
                            counter = (counter + 1) % 50
                            
                            self.audio_queue.put(("file", file_path))
                        except Exception as ex:
                            print(f"[TTS SYNTHESIS ERROR] Kokoro failed: {ex}", flush=True)
                            self.audio_queue.put(("sapi", text))
                    else:
                        # ElevenLabs pre-synthesis
                        try:
                            api_key = config.get("elevenlabs_api_key", "")
                            voice_id = config.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
                            if not api_key:
                                self.audio_queue.put(("sapi", text))
                            else:
                                import urllib.request
                                import json
                                import ssl
                                import os
                                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                                headers = {
                                    "Content-Type": "application/json",
                                    "xi-api-key": api_key
                                }
                                body = {
                                    "text": text,
                                    "model_id": "eleven_monolingual_v1",
                                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
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
                                temp_dir = os.environ.get("TEMP", "")
                                file_path = os.path.join(temp_dir, f"temp_eleven_{counter}_{int(time.time())}.mp3")
                                with open(file_path, "wb") as f:
                                    f.write(audio_data)
                                counter = (counter + 1) % 50
                                self.audio_queue.put(("file", file_path))
                        except Exception as ex:
                            print(f"[TTS SYNTHESIS ERROR] ElevenLabs failed: {ex}", flush=True)
                            self.audio_queue.put(("sapi", text))
                            
                    self.speech_queue.task_done()
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"[SYNTHESIS LOOP ERROR]: {e}", flush=True)
                    continue
                    
        threading.Thread(target=synthesis_loop, daemon=True).start()
        
        # Main playback loop
        pythoncom.CoInitialize()
        while self.running:
            try:
                msg_type, data = self.audio_queue.get(timeout=1.0)
                if self.status_callback:
                    self.status_callback("speaking")
                if msg_type == "sapi":
                    play_sapi(data)
                elif msg_type == "file":
                    play_audio_file(data)
                    try:
                        import os
                        if os.path.exists(data):
                            os.remove(data)
                    except Exception:
                        pass
                self.audio_queue.task_done()
                if self.audio_queue.empty() and self.status_callback:
                    self.status_callback("idle")
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[PLAYBACK LOOP ERROR]: {e}", flush=True)
                continue
            except Exception as e:
                print(f"[PLAYBACK LOOP ERROR]: {e}", flush=True)
                continue

class VoiceAssistantThread(QThread):
    status_changed = Signal(str)      # 'idle', 'listening', 'thinking', 'speaking', 'happy', 'sad', 'angry', 'sleeping'
    speech_detected = Signal(str)     # user text
    response_generated = Signal(str, bool)  # Mark's response text (text, is_stream)

    def __init__(self):
        super().__init__()
        self.running = True
        self.active_mode = False
        self.is_resting = True
        self.dictation_mode = False
        
        self.speech_queue = queue.Queue()
        self.audio_queue = queue.Queue()
        self.speech_worker = SpeechQueueWorker(
            self.speech_queue,
            self.audio_queue,
            status_callback=lambda s: self.status_changed.emit(s)
        )
        self.speech_worker.start()
        
        # Initialize thread chat history from the persistent chat log
        persisted = memory_manager.load_chat_history()
        self.chat_history = []
        for msg in persisted:
            self.chat_history.append({"sender": msg["sender"], "text": msg["text"]})
        self.chat_history = self.chat_history[-20:]  # keep last 20 messages (was 6)

        # Voice 2.0 — stay awake window after each response (seconds since epoch)
        self._awake_until = 0.0
        self._STAY_AWAKE_SECS = 8  # seconds to stay active after a response
        
        import speech_recognition as sr
        self.recognizer = sr.Recognizer()
        # Fine-tune recognizer parameters for better accuracy and stability
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.dynamic_energy_adjustment_damping = 0.15
        self.recognizer.dynamic_energy_ratio = 1.5
        self.recognizer.pause_threshold = 1.0  # Allow slightly longer pauses (default 0.8)

    def add_to_history(self, user_text, assistant_text, reasoning_details=None):
        self.chat_history.append({"sender": "user", "text": user_text})
        ast_msg = {"sender": "assistant", "text": assistant_text}
        if reasoning_details:
            ast_msg["reasoning_details"] = reasoning_details
        self.chat_history.append(ast_msg)
        if len(self.chat_history) > 20:
            self.chat_history = self.chat_history[-20:]  # was 6
        # Extend the stay-awake window after every exchange
        self._awake_until = time.time() + self._STAY_AWAKE_SECS

    def clear_speech(self):
        flask_app.stop_speaking_flag = True
        
        # Clear speech queue
        while not self.speech_queue.empty():
            try: self.speech_queue.get_nowait()
            except Exception: pass
            
        # Clear audio queue and delete temporary synthesized files
        while not self.audio_queue.empty():
            try:
                msg_type, data = self.audio_queue.get_nowait()
                if msg_type == "file":
                    import os
                    if os.path.exists(data):
                        os.remove(data)
            except Exception: pass
            
        import pygame
        try:
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception: pass
        import time
        time.sleep(0.15)
        flask_app.stop_speaking_flag = False

    def run(self):
        import speech_recognition as sr
        import pythoncom
        pythoncom.CoInitialize()

        source = sr.Microphone()
        try:
            with source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1.5)
            print("[MARK COMPANION] Microphone ready. Waiting for 'hey mark'...", flush=True)
        except Exception as e:
            print(f"[MARK COMPANION MIC ERROR]: {e}", flush=True)
            self.status_changed.emit("sad")
            return

        with source:
            while self.running:
                self.active_mode = flask_app.active_mode

                if self.active_mode:
                    self.status_changed.emit("listening")
                else:
                    if self.is_resting:
                        self.status_changed.emit("idle")
                    else:
                        self.status_changed.emit("sleeping")

                try:
                    print(f"[COMPANION THREAD] Listening... (active_mode={self.active_mode})", flush=True)
                    audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=12)
                    print(f"[COMPANION THREAD] Audio captured, transcribing...", flush=True)
                    command = self.recognizer.recognize_google(audio, language='en-in').lower()
                    print(f"[MARK HEARD]: {command}", flush=True)
                except sr.WaitTimeoutError:
                    print("[COMPANION THREAD] Listen timeout", flush=True)
                    continue
                except sr.UnknownValueError:
                    # No speech detected in audio — normal, don't spam logs
                    continue
                except sr.RequestError as e:
                    print(f"[COMPANION THREAD] Speech API error: {e}", flush=True)
                    continue
                except Exception as e:
                    print(f"[COMPANION THREAD] Unexpected error: {type(e).__name__}: {e}", flush=True)
                    continue

                if not self.active_mode:
                    # Voice 2.0 — re-enter active mode if within the stay-awake window
                    if time.time() < self._awake_until:
                        self.active_mode = True
                        flask_app.active_mode = True
                    else:
                        target_cmd = command.lower().strip()
                        from config.settings import settings as _cfg_settings
                        _configured_wake = _cfg_settings.wake_word.lower()
                        wake_triggers = [
                            "wake up baby", "wake up", "wake up meow", "hello meow",
                            "hey meow", "ok meow", "meow", "hey mark", "ok mark"
                        ]
                        if _configured_wake:
                            wake_triggers.extend([_configured_wake, f"hey {_configured_wake}", f"wake up {_configured_wake}"])

                        if any(w in target_cmd for w in wake_triggers):
                            self.active_mode = True
                            flask_app.active_mode = True
                            self.speech_detected.emit(command)
                            self.clear_speech()
                            self.status_changed.emit("speaking")
                            self.speech_queue.put("Hello Anuj! How can I help?")
                        continue

                # Active mode conversation processing
                self.speech_detected.emit(command)

                if self.dictation_mode:
                    target_cmd = command.lower()
                    if any(phrase in target_cmd for phrase in ["stop typing", "stop writing", "stop dictation", "deactivate dictation"]):
                        self.dictation_mode = False
                        self.clear_speech()
                        self.status_changed.emit("speaking")
                        self.speech_queue.put("Dictation mode deactivated, Boss.")
                        continue
                    elif len(target_cmd.split()) <= 2 and any(w in target_cmd for w in ["save", "safe", "sav"]):
                        import pyautogui
                        pyautogui.hotkey('ctrl', 's')
                        self.clear_speech()
                        self.status_changed.emit("speaking")
                        self.speech_queue.put("Saving, Boss.")
                        continue
                    elif len(target_cmd.split()) <= 2 and any(w in target_cmd for w in ["send", "sent"]):
                        import pyautogui
                        pyautogui.press('enter')
                        self.clear_speech()
                        self.status_changed.emit("speaking")
                        self.speech_queue.put("Sending, Boss.")
                        continue
                    else:
                        import pyautogui
                        pyautogui.typewrite(command + " ")
                        continue

                target_cmd = command.lower()
                if any(phrase in target_cmd for phrase in ["start typing", "write what i am saying", "start dictation", "dictation mode"]):
                    self.dictation_mode = True
                    self.clear_speech()
                    self.status_changed.emit("speaking")
                    self.speech_queue.put("Dictation mode activated. I will type whatever you say in the active application, Boss.")
                    continue

                if any(phrase in target_cmd for phrase in ["go to sleep", "sleep baby", "you can sleep", "sleep now", "take a nap", "stand down", "stop listening", "go offline"]) or target_cmd.strip() in ["sleep", "offline"]:
                    self.active_mode = False
                    flask_app.active_mode = False
                    self.is_resting = False
                    self.clear_speech()
                    self.status_changed.emit("speaking")
                    self.speech_queue.put("Going offline. Say wake up to wake me up.")
                    continue

                if "you are free" in target_cmd or "rest" in target_cmd:
                    self.active_mode = False
                    flask_app.active_mode = False
                    self.is_resting = True
                    self.clear_speech()
                    self.status_changed.emit("speaking")
                    self.speech_queue.put("Okay, I will rest now.")
                    continue

                if any(phrase in command for phrase in ["restart yourself", "reboot yourself", "restart meow"]):
                    self.active_mode = False
                    flask_app.active_mode = False
                    self.clear_speech()
                    self.status_changed.emit("speaking")
                    self.speech_queue.put("Restarting myself, Boss. See you in a moment!")
                    self.running = False
                    time.sleep(2.0)
                    import subprocess
                    import sys
                    import os
                    try:
                        subprocess.Popen([sys.executable] + sys.argv)
                    except Exception as e:
                        print(f"[RESTART ERROR] Failed to relaunch: {e}")
                    os._exit(0)

                if any(phrase in command for phrase in ["shutdown yourself", "turn off meow", "turn off yourself", "shutdown"]):
                    self.active_mode = False
                    flask_app.active_mode = False
                    self.clear_speech()
                    self.status_changed.emit("speaking")
                    self.speech_queue.put("Shutting down. Bye bye!")
                    self.running = False
                    self.status_changed.emit("sleeping")
                    time.sleep(2.0)
                    import os
                    os._exit(0)

                # Clear any ongoing speaking before starting thinking
                self.clear_speech()
                self.status_changed.emit("thinking")

                # Voice 2.0 — check for style-change command before LLM call
                style_key, style_msg = voice_personality.detect_style_change(command)
                if style_key:
                    self.status_changed.emit("speaking")
                    self.speech_queue.put(style_msg)
                    continue

                try:
                    response = self.process_assistant_logic(command)
                    
                    import types
                    if isinstance(response, types.GeneratorType):
                        # Real-time streaming response loop
                        accumulated_text = ""
                        sentence_buffer = ""
                        first_dispatched = False
                        
                        try:
                            for chunk in response:
                                if flask_app.stop_speaking_flag:
                                    break
                                accumulated_text += chunk
                                sentence_buffer += chunk
                                
                                # Emit to UI in real-time token-by-token
                                self.response_generated.emit(accumulated_text, True)
                                
                                # Fast-start: dispatch first phrase early on comma or punctuation to eliminate silence
                                if not first_dispatched:
                                    if re.search(r'[.!?]', sentence_buffer) or (len(sentence_buffer.split()) >= 4 and re.search(r'[,;:\n]', sentence_buffer)):
                                        parts = re.split(r'(?<=[.!?,;:\n])', sentence_buffer, maxsplit=1)
                                        if len(parts) > 1 and parts[0].strip():
                                            self.speech_queue.put(parts[0].strip())
                                            sentence_buffer = parts[1]
                                            first_dispatched = True
                                            continue

                                # Split completed sentences immediately upon finding punctuation (excluding common abbreviations)
                                sentences = re.split(r'(?<=[.!?])', sentence_buffer)
                                if len(sentences) > 1:
                                    new_buffer = ""
                                    for s in sentences[:-1]:
                                        s_clean = s.strip()
                                        words = s_clean.split()
                                        if words and words[-1].lower() in ["mr.", "mrs.", "dr.", "ms.", "st.", "e.g.", "i.e.", "vs."]:
                                            new_buffer += s
                                        else:
                                            if s_clean:
                                                self.speech_queue.put(s_clean)
                                                first_dispatched = True
                                    sentence_buffer = new_buffer + sentences[-1]
                        except Exception as loop_err:
                            print(f"[THREAD GENERATOR LOOP ERROR]: {loop_err}")
                            if not accumulated_text.strip():
                                accumulated_text = "Sorry, I encountered an error receiving the response stream."
                                self.response_generated.emit(accumulated_text, False)
                                self.speech_queue.put(accumulated_text)
                            
                        # Flush remaining buffer
                        if sentence_buffer.strip() and not flask_app.stop_speaking_flag:
                            self.speech_queue.put(sentence_buffer.strip())

                            
                        # Save response to history
                        self.add_to_history(command, accumulated_text, llm_router._last_reasoning_details)
                        
                        # Auto-jump cursor to line number if mentioned in the response (and not already executed by an explicit navigation command)
                        is_nav_command = any(phrase in command.lower() for phrase in ["jump to", "go to", "highlight", "move to", "navigate to"]) or re.search(r"\bline\s+(?:number\s+)?(\d+)\b", command.lower())
                        if not is_nav_command:
                            line_match = re.search(r"\bline\s+(?:number\s+|no\.\s+)?(\d+)\b", accumulated_text.lower())
                            if line_match:
                                line_num = line_match.group(1)
                                def delayed_jump():
                                    import time
                                    time.sleep(2.5)
                                    import pc_control
                                    pc_control.navigate_to_editor_line(line_num)
                                threading.Thread(target=delayed_jump, daemon=True).start()
                    else:
                        # Flat string response (PC control command, news, SAPI switcher, etc.)
                        emotion = "speaking"
                        if any(w in response.lower() for w in ["sorry", "error", "unable", "couldn't"]):
                            emotion = "sad"
                        elif any(w in response.lower() for w in ["perfect", "yes", "success", "great", "welcome"]):
                            emotion = "happy"
                            
                        self.status_changed.emit(emotion)
                        self.response_generated.emit(response, False)
                        self.speech_queue.put(response)
                        
                        # Auto-jump cursor to line number if mentioned in the response (and not already executed by an explicit navigation command)
                        is_nav_command = any(phrase in command.lower() for phrase in ["jump to", "go to", "highlight", "move to", "navigate to"]) or re.search(r"\bline\s+(?:number\s+)?(\d+)\b", command.lower())
                        if not is_nav_command:
                            line_match = re.search(r"\bline\s+(?:number\s+|no\.\s+)?(\d+)\b", response.lower())
                            if line_match:
                                line_num = line_match.group(1)
                                def delayed_jump():
                                    import time
                                    time.sleep(2.5)
                                    import pc_control
                                    pc_control.navigate_to_editor_line(line_num)
                                threading.Thread(target=delayed_jump, daemon=True).start()
                except Exception as logic_err:
                    print(f"[THREAD LOGIC ERROR]: {logic_err}")
                    err_msg = "Sorry, I encountered an error processing your command."
                    self.status_changed.emit("sad")
                    self.response_generated.emit(err_msg, False)
                    self.speech_queue.put(err_msg)

                # Extract learned facts in background only if not a system/vision command
                cmd_clean = command.strip().lower()
                is_pc = pc_control.handle_pc_command(command) is not None
                is_screen = any(phrase in cmd_clean for phrase in ["screen", "desktop", "ocr", "active window", "display"])
                is_cam = any(phrase in cmd_clean for phrase in ["you see", "see me", "look at", "look me", "camera", "webcam", "my room", "doing", "hand", "wearing", "holding"])
                if not (is_pc or is_screen or is_cam):
                    memory_manager.extract_memory_in_background(
                        command,
                        lambda p, s, max_tokens=150: query_llm(p, s, max_tokens=max_tokens)
                    )

    def process_assistant_logic(self, command):
        cmd_clean = command.strip().lower()

        # ── Emotion engine: update mood from this command ────────────────────
        if _emotion_mod:
            try:
                _emotion_mod.process_command(cmd_clean)
                # Gratitude detection
                if any(p in cmd_clean for p in [
                    "thank you", "thanks", "good job", "well done",
                    "great job", "nice work", "you're amazing", "love you",
                    "perfect", "brilliant"
                ]):
                    _emotion_mod.on_thank_you()
                # Rudeness detection
                elif any(p in cmd_clean for p in [
                    "shut up", "you're useless", "you're stupid",
                    "you're dumb", "be quiet", "stop talking", "i hate you"
                ]):
                    _emotion_mod.on_user_rude()
            except Exception:
                pass
        # ────────────────────────────────────────────────────────────────────

        # Intercept "fix that" to re-execute last command
        if cmd_clean in ["fix that", "fix it"]:
            last_user_cmd = None
            for msg in reversed(self.chat_history):
                text = msg.get("text", "").strip()
                if msg.get("sender") == "user" and text.lower() not in ["fix that", "fix it"]:
                    last_user_cmd = text
                    break
            if last_user_cmd:
                self.speak_sync(f"Re-executing your last request: {last_user_cmd}")
                return self.process_assistant_logic(last_user_cmd)
            else:
                return "I couldn't find a previous command to fix, Boss."

        # Phase 9: Query dynamic plugins first
        try:
            import plugin_manager
            plugin_resp = plugin_manager.handle_command(command)
            if plugin_resp is not None:
                return plugin_resp
        except Exception as e:
            print(f"[COMPANION PLUGINS EXEC ERROR]: {e}")

        # ── Phase 3: Intelligent Intent Router ────────────────────────────────
        # Classify the command using fast-path regex + LLM fallback.
        # Dispatch tool_call and multi_step intents to the new pipeline.
        # system_command, chat, music, style_change fall through to legacy handlers.
        try:
            _intent = intent_router.route_command(command)
            _intent_type = _intent.get("intent", "chat")

            if _intent_type == "tool_call":
                # Single-tool execution via tool_registry
                _tool_name = _intent["data"].get("tool")
                if _tool_name and tool_registry.get_tool(_tool_name):
                    self.response_generated.emit(
                        f"Executing tool: {_tool_name}...", False
                    )
                    _tool_result = tool_registry.run_tool(_tool_name, _intent["data"].get("args", {}))
                    if _tool_result["success"]:
                        return f"{_tool_result['output']}"
                    else:
                        return f"Tool '{_tool_name}' failed: {_tool_result['error']}"
                # If tool name not recognized, fall through to legacy handlers

            elif _intent_type == "multi_step":
                # Complex goal -> ReAct agent executor
                _goal = _intent["data"].get("goal", command)
                if _agent_executor:
                    self.response_generated.emit(
                        f"Starting autonomous execution: {_goal[:80]}...", False
                    )
                    # Run synchronously so we can return the result
                    _agent_result = _agent_executor.run(_goal, background=False)
                    return _agent_result or "Task completed."
                else:
                    # Agent executor not initialized, fall through
                    pass

            elif _intent_type == "style_change":
                _style_data = _intent.get("data", {})
                return _style_data.get("message", "Style updated, Boss.")

            elif _intent_type == "music":
                # Let the existing music handler below handle it
                pass

            # For 'chat' and 'system_command', fall through to legacy handlers
        except Exception as _ir_err:
            import logging as _log_mod
            _log_mod.getLogger("meow.core").warning(
                "Intent router error: %s — falling back to legacy handlers", _ir_err
            )
        # ── End Phase 3 Intent Router ─────────────────────────────────────────

        # Intercept PC control commands (Jarvis Mode)
        pc_response = pc_control.handle_pc_command(command)
        if pc_response is not None:
            return pc_response

        # Intercept Vision commands (Phase 4)
        config = memory_manager.load_config()
        active_model = config.get("selected_model", "llama")
        if active_model in ["nvidia", "gemini"]:
            import vision_control
            vision_response = vision_control.handle_vision_command(
                command,
                config.get(f"{active_model}_api_key"),
                SYSTEM,
                self.chat_history,
                model_type=active_model
            )
            if vision_response is not None:
                return vision_response

        # Intercept Smart Automation commands (Phase 5)
        # 1. Good Morning routine
        if any(phrase in cmd_clean for phrase in ["good morning", "start morning routine", "morning routine"]):
            import automation_control
            return automation_control.run_good_morning_routine()
            
        # 2. Night routine
        if any(phrase in cmd_clean for phrase in ["good night", "start night routine", "night routine"]):
            import automation_control
            return automation_control.run_night_routine()
            
        # 3. Set Alarm (Matches: set alarm for 7:30 am, alarm for 8:00)
        alarm_match = re.search(r"(?:set alarm for|set an alarm for|alarm for|set alarm at)\s+(.+)", cmd_clean)
        if alarm_match:
            import automation_control
            time_input = alarm_match.group(1).strip()
            alarm_resp = automation_control.set_alarm(time_input)
            if alarm_resp:
                return alarm_resp
            else:
                return "I couldn't parse the time for the alarm, Boss. Please say it like '7:30 AM' or '19:45'."

        # Intercept Agent commands (Phase 7)
        is_agent = (
            ("find" in cmd_clean and "shortlist" in cmd_clean) or
            ("research" in cmd_clean and "shortlist" in cmd_clean) or
            ("shortlist" in cmd_clean and "spreadsheet" in cmd_clean) or
            ("shortlist" in cmd_clean and "csv" in cmd_clean) or
            ("find internships" in cmd_clean) or
            ("research" in cmd_clean and "spreadsheet" in cmd_clean)
        )
        if is_agent:
            agent_model = active_model
            api_key = config.get(f"{active_model}_api_key")
            if agent_model not in ["nvidia", "gemini"]:
                if config.get("gemini_api_key"):
                    agent_model = "gemini"
                    api_key = config.get("gemini_api_key")
                elif config.get("nvidia_api_key"):
                    agent_model = "nvidia"
                    api_key = config.get("nvidia_api_key")
            
            if agent_model in ["nvidia", "gemini"] and api_key:
                self.speak_sync("Starting my research agent, Boss. Let me scan the web.")
                import agent_mode
                def progress_cb(msg):
                    self.status_changed.emit("thinking")
                    self.response_generated.emit(f"[Agent Status]: {msg}", False)
                    self.speak_sync(msg)
                    
                agent_response = agent_mode.run_agent_flow(
                    command,
                    api_key,
                    model_type=agent_model,
                    progress_callback=progress_cb
                )
                return agent_response
            else:
                return "Please configure a Gemini or Nvidia API key in the settings to enable my autonomous research agent, Boss."

        if "dashboard" in command:
            threading.Thread(target=webbrowser.open_new_tab, args=("http://127.0.0.1:5005",), daemon=True).start()
            return "Opening Meao Assistant Dashboard."

        # Voice commands to switch model
        if any(phrase in command.lower() for phrase in ["switch model to", "change model to", "use model", "switch to model", "change to model"]):
            target = command.lower()
            new_model = None
            if "llama" in target or "local" in target or "offline" in target:
                new_model = "llama"
            elif "gemini" in target:
                new_model = "gemini"
            elif "groq" in target:
                new_model = "groq"
            elif "nvidia" in target:
                new_model = "nvidia"
            elif "open router" in target or "openrouter" in target:
                new_model = "openrouter"
            
            if new_model:
                config = memory_manager.load_config()
                memory_manager.save_config(
                    new_model, 
                    config["gemini_api_key"], 
                    config["groq_api_key"], 
                    config.get("nvidia_api_key"), 
                    config.get("openrouter_api_key")
                )
                if mascot_widget_ref is not None:
                    try:
                        mascot_widget_ref.sync_menu_trigger.emit()
                    except Exception:
                        pass
                return f"Model configured to {new_model}, Boss."
            else:
                return "Which model would you like to switch to? You can say local LLaMA, Gemini, Groq, Nvidia, or OpenRouter."

        if "open google" in command or "search" in command:
            query = command.replace("search", "").replace("open google", "").strip()
            url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}" if query else "https://www.google.com"
            threading.Thread(target=webbrowser.open_new_tab, args=(url,), daemon=True).start()
            return f"Opening Google and searching for {query}." if query else "Opening Google."

        if "open facebook" in command or command.strip() == "facebook":
            threading.Thread(target=webbrowser.open_new_tab, args=("https://www.facebook.com",), daemon=True).start()
            return "Opening Facebook."

        if "open linkedin" in command or command.strip() == "linkedin":
            threading.Thread(target=webbrowser.open_new_tab, args=("https://www.linkedin.com",), daemon=True).start()
            return "Opening LinkedIn."

        if "meaning of" in command or "what is the meaning" in command:
            word = command.replace("what is", "").replace("meaning of", "").replace("meaning", "").strip()
            try:
                from wordhoard import Definitions
                definitions = Definitions(search_string=word)
                meaning = definitions.find_definitions()
                if meaning and isinstance(meaning, list) and len(meaning) > 0:
                    return f"The meaning of {word} is: {meaning[0]}"
            except Exception as e:
                print(f"[WORDHOARD ERROR]: {e}")
            return f"Sorry, I couldn't find the meaning of {word}."

        if "news" in command:
            topic = command.replace("news", "").replace("about", "").replace("of", "").replace("related", "").replace("show", "").replace("me", "").strip()
            if not topic:
                topic = "latest"
            try:
                import xml.etree.ElementTree as ET
                import html
                url = f"https://news.google.com/rss/search?q={urllib.parse.quote(topic)}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                response = urllib.request.urlopen(req)
                xml_data = response.read()
                root = ET.fromstring(xml_data)
                items = root.findall('.//item')
                if items:
                    video_id = ""
                    try:
                        yt_req = urllib.request.Request(
                            f"https://www.youtube.com/results?search_query={urllib.parse.quote(topic + ' news')}",
                            headers={'User-Agent': 'Mozilla/5.0'}
                        )
                        yt_html = urllib.request.urlopen(yt_req).read().decode()
                        video_ids = re.findall(r"watch\?v=([a-zA-Z0-9_-]{11})", yt_html)
                        if video_ids:
                            video_id = video_ids[0]
                    except Exception:
                        pass

                    articles_html = ""
                    for i, item in enumerate(items[:5]):
                        title_text = html.escape(item.find('title').text or '')
                        articles_html += f"<div style='background:#161b22; padding:15px; margin-bottom:15px; border-radius:8px; border-left:4px solid #00e5ff;'><h3>{title_text}</h3></div>"
                    
                    flask_app.assistant_state["display_data"] = {
                        "type": "news",
                        "topic": topic,
                        "video_id": video_id,
                        "articles_html": articles_html
                    }
                    return f"Here are the top headlines for {topic}."
            except Exception as e:
                print(f"[NEWS ERROR]: {e}")
            threading.Thread(target=webbrowser.open_new_tab, args=(f"https://news.google.com/search?q={urllib.parse.quote(topic)}",), daemon=True).start()
            return f"Searching news about {topic}."

        if command.strip().startswith("open "):
            app_name = command.strip()[5:].strip().lower()
            _generic_skip = {"dashboard", "folder", "file", "it", "this", "app", "window"}
            if app_name and app_name not in _generic_skip:
                try:
                    from AppOpener import open as app_open
                    app_open(app_name, match_closest=False, throw_error=True)
                    return f"Opening {app_name}."
                except Exception:
                    fallback_protocols = {
                        "whatsapp": "whatsapp:",
                        "spotify": "spotify:",
                        "settings": "ms-settings:",
                        "calculator": "calculator:",
                        "mail": "outlookmail:"
                    }
                    for key, protocol in fallback_protocols.items():
                        if key == app_name or key in app_name.split():
                            os.startfile(protocol)
                            return f"Opening {app_name}."

        # Handle memory commands
        mem_response = memory_manager.handle_memory_commands(command)
        if mem_response is not None:
            return mem_response

        # Intercept screen reading commands
        has_screen_trigger = any(phrase in command for phrase in ["screen", "error", "traceback", "debug this", "what is this", "what's this", "what is going on", "see my", "look at my"])
        is_historical = any(phrase in command for phrase in ["earlier", "past", "history", "before", "previously", "yesterday", "ago"])
        if has_screen_trigger and not is_historical:
            screen_text = memory_manager.capture_and_ocr()

            if not screen_text:
                return "Sorry, I was unable to capture or read your screen."

            if len(screen_text) > 700:
                screen_text = screen_text[:700] + "\n...[TRUNCATED FOR BREVITY]..."

            try:
                system_prompt = SYSTEM + memory_manager.get_system_prompt_addition(command)
                doc_context = knowledge_manager.get_context_for_query(command)
                if doc_context:
                    system_prompt += "\n" + doc_context
                user_prompt = f"User Voice Command: {command}\n\nExtracted Screen Content (OCR):\n{screen_text}"
                return query_llm_stream(user_prompt, system_prompt, self.chat_history, max_tokens=384)
            except Exception as e:
                print(f"[THREAD OCR ERROR]: {e}")
                return "Sorry, I encountered an error analyzing your screen."

        # Intercept stop music / clear display
        if any(phrase in cmd_clean for phrase in ["stop music", "clear display", "close player", "stop playing"]):
            flask_app.assistant_state["display_data"] = None
            flask_app.assistant_state["music_status"] = {"playing": False, "title": "No playlist playing", "source": ""}
            import pygame
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
            except Exception:
                pass
            return "Stopped playback and cleared display, Boss."

        # Intercept music play — musicLibrary shortcut playlists only.
        # Named song search is handled upstream by pc_control.handle_pc_command().
        if "play" in command:
            query = command.replace("play", "").strip()
            if not query or query in ["music", "some music", "a song", "random music"]:
                import random
                song_url = random.choice(list(musicLibrary.music.values()))
                webbrowser.open(song_url)
                flask_app.assistant_state["music_status"] = {"playing": True, "title": "random playlist", "source": "youtube"}
                return "Opening a random playlist in your browser, Boss."
            else:
                for key in musicLibrary.music:
                    if key in query:
                        song_url = musicLibrary.music[key]
                        webbrowser.open(song_url)
                        flask_app.assistant_state["music_status"] = {"playing": True, "title": f"{key} playlist", "source": "youtube"}
                        return f"Opening {key} playlist in your browser, Boss."
                # Not a known library key — fall through to LLM/web search

        # Intercept live web search commands
        is_explicit_search = any(phrase in command.lower() for phrase in ["search the web for", "search online for", "google for", "google about", "find online about", "duckduckgo for", "duckduckgo about"])
        
        # Extended search triggers: sports, vs/versus comparisons, current weather/news, prices
        search_keywords = [
            "weather", "news", "president", "prime minister", "cricket", "football", "match", 
            "score", "won", "winner", "versus", "versis", "vs", "against", "price", "cost", 
            "how much", "rate", "stock", "value", "current", "latest", "release date"
        ]
        has_search_intent = is_explicit_search or \
                            any(w in command.lower() for w in search_keywords) or \
                            (any(w in command.lower() for w in ["who won", "score of", "weather in", "price of", "latest news", "current president", "current prime minister", "cricket match"]) and \
                             any(w in command.lower() for w in ["india", "pakistan", "match", "vs", "won", "weather", "news", "president", "minister", "today", "yesterday"]))
        
        if has_search_intent:
            query = command
            if is_explicit_search:
                query_lower = command.lower()
                for phrase in ["search the web for", "search online for", "google for", "google about", "find online about", "duckduckgo for", "duckduckgo about"]:
                    query_lower = query_lower.replace(phrase, "")
                query = query_lower.strip()
            
            # Clean common spelling mistakes for better web search hits
            query_clean = query.lower().replace("versis", "vs").replace("versus", "vs").replace("against", "vs")
            
            if not query_clean:
                return "What would you like me to search the web for, Boss?"
            
            self.response_generated.emit(f"Searching the web for '{query}'...", False)
            self.speech_queue.put("Searching the web")
            
            try:
                import internet_agent
                results = internet_agent.search_web(query_clean)
                if not results:
                    return f"I performed a web search for '{query}' but found no results."
                    
                context_str = f"Live Search Results for '{query}':\n"
                for i, res in enumerate(results[:3]):
                    context_str += f"{i+1}. {res['title']}\nLink: {res['link']}\nSnippet: {res['snippet']}\n\n"
                    
                system_prompt = SYSTEM + f"\n\nUse the following real-time web search results to answer the user's question. Quote sources if necessary:\n{context_str}"
                return query_llm_stream(command, system_prompt, self.chat_history, max_tokens=384)
            except Exception as e:
                print(f"[THREAD SEARCH ERROR]: {e}")
                return "Sorry, I encountered an error searching the web."

        # Intercept Train Ticket Booking commands (Phase 7 / Internet Agent)
        train_match = re.search(r"(?:book|search)\s+(?:my\s+)?(?:ticket\s+of\s+)?train\s+(?:from\s+)?([a-zA-Z\s]+)\s+to\s+([a-zA-Z\s]+)", cmd_clean)
        if not train_match:
            train_match = re.search(r"train\s+(?:ticket\s+)?from\s+([a-zA-Z\s]+)\s+to\s+([a-zA-Z\s]+)", cmd_clean)
            
        if train_match:
            source = train_match.group(1).strip().title()
            destination = train_match.group(2).strip().title()
            
            self.response_generated.emit(f"Launching train booking automation from {source} to {destination}...", False)
            self.speech_queue.put("Searching for train tickets")
            
            # 1. Open pre-filled ConfirmTkt search page in default browser
            confirmtkt_url = f"https://www.confirmtkt.com/trains/{source.lower()}-to-{destination.lower()}-train-tickets"
            webbrowser.open(confirmtkt_url)
            
            # 2. Run background Playwright headful automation on IRCTC search page
            try:
                import internet_agent
                threading.Thread(
                    target=internet_agent.automate_irctc_search,
                    args=(source, destination),
                    daemon=True
                ).start()
                
                return f"I have launched the IRCTC automation helper on your screen, pre-filling your trip from {source} to {destination}. I also opened ConfirmTkt in your browser to check availability, Boss!"
            except Exception as e:
                print(f"[TRAIN AUTOMATION LAUNCH ERROR]: {e}")
                return f"I opened ConfirmTkt in your default browser to search for trains from {source} to {destination}."

        # Intercept Playwright browser automation
        if any(phrase in command.lower() for phrase in ["open website", "open url", "browse to", "navigate to site"]):
            url = None
            url_match = re.search(r"(https?://\S+)", command)
            if url_match:
                url = url_match.group(1)
            else:
                words = command.lower().split()
                for w in words:
                    if "." in w and not w.endswith("."):
                        url = w
                        break
                if url:
                    if not url.startswith("http"):
                        url = "https://" + url
            if not url:
                return "Which URL would you like me to navigate to, Boss?"
                
            self.response_generated.emit(f"Launching Chromium browser to navigate to {url}...", False)
            self.speech_queue.put("Opening browser now")
            
            try:
                import internet_agent
                threading.Thread(target=internet_agent.open_browser_and_navigate, args=(url,), daemon=True).start()
                return f"I am opening a browser window to navigate to {url}."
            except Exception as e:
                return f"Failed to start browser: {e}"

        # Intercept background price tracking commands (Phase 10 / Internet Agent)
        track_match = re.search(r"keep\s+checking\s+([a-zA-Z0-9_\-\s]+)\s+until\s+([a-zA-Z0-9_\-\s]+)\s+(?:drops?|goes?|fall?s?)\s+(?:below|under|to|at)\s*(\d+(?:\.\d+)?)", cmd_clean)
        if not track_match:
            track_match = re.search(r"keep\s+checking\s+(?:until\s+)?([a-zA-Z0-9_\-\s]+)\s+(?:drops?|goes?|fall?s?)\s+(?:below|under|to|at)\s*(\d+(?:\.\d+)?)\s*(?:on|via|in)\s*([a-zA-Z0-9_\-\s]+)?", cmd_clean)
        
        if track_match:
            groups = track_match.groups()
            if len(groups) == 3:
                if track_match.re.pattern.startswith("keep\\s+checking\\s+([a-zA-Z0-9_"):
                    retailer = groups[0].strip()
                    product = groups[1].strip()
                    price_val = float(groups[2])
                else:
                    product = groups[0].strip()
                    price_val = float(groups[1])
                    retailer = groups[2].strip() if groups[2] else "web"
            else:
                product = "product"
                price_val = 100.0
                retailer = "web"
                
            if " on " in product:
                parts = product.split(" on ")
                product = parts[0].strip()
                retailer = parts[1].strip()
            elif " in " in product:
                parts = product.split(" in ")
                product = parts[0].strip()
                retailer = parts[1].strip()
                
            self.speak_sync(f"Scanning the web to find {product} on {retailer}, Boss. Please wait.")
            search_query = f"{product} site:{retailer}.com" if retailer not in ["web", "internet", "online"] else product
            
            try:
                import internet_agent
                import agent_mode
                search_results = agent_mode.search_duckduckgo(search_query, max_results=1)
                if not search_results:
                    search_results = agent_mode.search_duckduckgo(f"{product} {retailer}", max_results=1)
                    
                if search_results:
                    url = search_results[0]["url"]
                    title = search_results[0]["title"]
                    name = title.split("|")[0].split("-")[0].strip()
                    if not name:
                        name = product.title()
                        
                    selector = ".price"
                    if "flipkart" in url.lower():
                        selector = "._30jeq3, .Nx9r88, ._16Jk6d, .price"
                    elif "amazon" in url.lower():
                        selector = ".a-price-whole, #priceblock_ourprice, #priceblock_dealprice, #price_inside_buybox, .price"
                        
                    internet_agent.add_tracker(name, url, selector, price_val)
                    return f"I found CMF Buds 2A on {retailer}. I've set a background task to monitor the price and will notify you when it drops below ₹{price_val:,.2f}, Boss!"
                else:
                    return f"I couldn't find any search results for '{product}' on {retailer} to track."
            except Exception as e:
                print(f"[PRICE TRACKER INTERCEPT ERROR]: {e}")
                return f"I encountered an error trying to set up the price tracker: {e}"

        # Intercept Price Tracking commands
        if "track price" in command.lower():
            words = command.lower().split()
            url = None
            for w in words:
                if w.startswith("http") or ("." in w and "/" in w):
                    url = w
                    break
            if not url:
                return "Please specify a product webpage URL to track, Boss."
                
            price_match = re.search(r"(?:under|below|at|threshold)\s*(\d+(?:\.\d+)?)", command.lower())
            threshold = float(price_match.group(1)) if price_match else 100.0
            
            selector = ".price"
            selector_match = re.search(r"selector\s+(\S+)", command.lower())
            if selector_match:
                selector = selector_match.group(1)
            elif "amazon" in url:
                selector = "#priceblock_ourprice, #priceblock_dealprice, .a-price-whole"
            elif "ebay" in url:
                selector = ".x-price-primary"
                
            product_name = "Product"
            domain_match = re.search(r"https?://(?:www\.)?([^/]+)", url)
            if domain_match:
                product_name = f"{domain_match.group(1)} Item"
                
            try:
                import internet_agent
                internet_agent.add_tracker(product_name, url, selector, threshold)
                return f"Successfully added price tracker for {product_name} under threshold ${threshold}."
            except Exception as e:
                return f"Failed to add price tracker: {e}"

        # ── Agentic task trigger ──────────────────────────────────────────────
        # "run task: <goal>" / "do task: <goal>" / "execute task <goal>"
        # Now routes through the Phase 3 AgentExecutor (ReAct loop) instead
        # of the legacy action_planner.
        _AGENT_TRIGGERS = [
            "run task:", "do task:", "execute task:", "run agentic task:",
            "run task ", "do task ", "agent task ", "execute autonomously ",
        ]
        for _trig in _AGENT_TRIGGERS:
            if cmd_clean.startswith(_trig) or _trig.strip() in cmd_clean:
                _goal = command
                for _t in _AGENT_TRIGGERS:
                    _goal = _goal.lower().replace(_t, "").strip()
                if _goal and _agent_executor:
                    try:
                        self.response_generated.emit(
                            f"Starting autonomous task: {_goal[:80]}...", False
                        )
                        _result = _agent_executor.run(_goal, background=False)
                        return _result or f"Completed task: {_goal}"
                    except Exception as _ae:
                        return f"Couldn't start agentic task: {_ae}"
                elif _goal:
                    # Fallback to legacy action_planner if executor unavailable
                    try:
                        import action_planner
                        action_planner.run_agentic_task(_goal, mascot=None)
                        return f"I'm planning and executing: {_goal}"
                    except Exception as _ae:
                        return f"Couldn't start agentic task: {_ae}"
                break
        # ── ─────────────────────────────────────────────────────────────────

        # Fallback LLM logic
        try:
            system_prompt = SYSTEM + memory_manager.get_system_prompt_addition(command)
            
            # Silent real-time web search context augmentation
            words_count = len(command.split())
            is_simple_query = words_count < 3 and any(w in cmd_clean for w in ["hi", "hello", "hey", "bye", "thanks", "thank you", "ok", "okay"])
            if not is_simple_query:
                try:
                    import internet_agent
                    search_results = internet_agent.search_web(command)
                    if search_results:
                        context_str = "\n\nLive Real-time Web Search Results (Use this to answer accurately, and ignore outdated knowledge cutoff values):\n"
                        for i, res in enumerate(search_results[:3]):
                            context_str += f"- Title: {res['title']}\n  Link: {res['link']}\n  Summary: {res['snippet']}\n"
                        
                        # Extra smart check: if query is price-related, attempt to scrape the actual live selling price from the first URL
                        is_price_query = any(w in cmd_clean for w in ["price", "cost", "how much", "rate", "buy", "deal"])
                        if is_price_query:
                            first_url = search_results[0]["link"]
                            if any(domain in first_url.lower() for domain in ["flipkart.com", "amazon.in", "amazon.com", "ebay.com"]):
                                print(f"[COMPANION] Price query detected. Scraping live price from: {first_url}...")
                                selector = ".price"
                                if "flipkart" in first_url.lower():
                                    selector = "._30jeq3, .Nx9r88, ._16Jk6d, .price"
                                elif "amazon" in first_url.lower():
                                    selector = ".a-price-whole, #priceblock_ourprice, #priceblock_dealprice, #price_inside_buybox, .price"
                                    
                                live_price = internet_agent.check_price_of_url(first_url, selector)
                                if live_price is not None:
                                    currency = "₹" if "flipkart" in first_url.lower() or "amazon.in" in first_url.lower() else "$"
                                    context_str += f"\n[CRITICAL ACTUAL LIVE PRICE DATA] The live scraped selling price of the product on the page right now is {currency}{live_price:,.2f}. Prioritize this value over the search snippets.\n"
                                    print(f"[COMPANION] Successfully injected live scraped price: {currency}{live_price}")
                        
                        system_prompt += context_str
                except Exception as se:
                    print(f"[FALLBACK SEARCH ERROR]: {se}")
                    
            doc_context = knowledge_manager.get_context_for_query(command)
            if doc_context:
                system_prompt += "\n" + doc_context
            try:
                screen_context = screen_memory.get_screen_context_for_query(command)
                if screen_context:
                    system_prompt += "\n" + screen_context
            except Exception as se:
                print(f"[SCREEN RAG ERROR]: {se}")
            return query_llm_stream(command, system_prompt, self.chat_history, max_tokens=300)

        except Exception as e:
            print(f"[THREAD LLM ERROR]: {e}")
            return "I encountered an error trying to process that."

    def speak_sync(self, text, on_start_speaking=None):
        speak_sync_global(text, on_start_speaking=on_start_speaking)


