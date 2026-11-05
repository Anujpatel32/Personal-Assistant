
from flask import Flask, render_template, request, jsonify, make_response, Response
import json
import hashlib
import os
import sys
import threading
import copy
import urllib.parse
import memory_manager
import knowledge_manager
try:
    import gesture_control
except Exception as _ge_err:
    print(f"[WARN] Gesture control unavailable: {_ge_err}")
    gesture_control = None
import accessibility
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
app.config["TEMPLATES_AUTO_RELOAD"] = True   # always serve latest index.html

# Ensure RAG documents dir exists
knowledge_manager.ensure_dirs()

# --- GLOBAL STATE (SHARED WITH COMPANION) ---
assistant_state = {
    "status": "offline",
    "mood": "neutral",
    "chat_log": memory_manager.load_chat_history(),
    "display_data": None,
    "music_status": {
        "playing": False,
        "title": "No playlist playing",
        "source": ""
    },
    "pc_stats": {
        "cpu": 0.0,
        "ram": 0.0,
        "ram_used_gb": 0.0,
        "ram_total_gb": 0.0,
        "disk": 0.0,
        "battery": None,
        "battery_plugged": None,
        "processes": 0,
        "os": "Unknown",
        "gpu": 0.0,
        "gpu_mem_used": 0.0,
        "gpu_mem_total": 0.0,
        "gpu_mem_pct": 0.0,
        "gpu_name": "N/A"
    }
}
state_lock = threading.Lock()
active_mode = False
stop_speaking_flag = False
active_engine = None
active_engine_lock = threading.Lock()

# Reference to the mascot widget, set by companion.py on startup
mascot_widget_ref = None

# --- GESTURE CONTROL BACKEND STATE ---
gesture_running = False
gesture_thread = None

# --- GLOBAL WINDOWS MEDIA MONITOR ---
def get_current_media_info():
    import win32gui
    import win32process
    import psutil
    
    media_info = None
    
    def enum_windows_callback(hwnd, extra):
        nonlocal media_info
        if media_info:
            return
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = psutil.Process(pid)
                pname = proc.name().lower()
                
                # Spotify check
                if "spotify" in pname:
                    if title not in ["Spotify", "Spotify Free", "Spotify Premium", "Spotify Helper"]:
                        parts = title.split(" - ", 1)
                        if len(parts) == 2:
                            media_info = {
                                "playing": True,
                                "artist": parts[0].strip(),
                                "title": parts[1].strip()
                            }
                        else:
                            media_info = {
                                "playing": True,
                                "artist": "Spotify",
                                "title": title
                            }
                # YouTube browser check
                elif any(b in pname for b in ["chrome", "msedge", "firefox", "opera", "brave"]):
                    if "youtube" in title.lower() and " - youtube" in title.lower():
                        cleaned = title
                        for tag in [" - Google Chrome", " - Microsoft Edge", " - Mozilla Firefox", " - Brave", " - Opera"]:
                            cleaned = cleaned.replace(tag, "")
                        cleaned = cleaned.replace(" - YouTube", "").replace("YouTube - ", "")
                        
                        artist = "YouTube"
                        song_title = cleaned
                        if " - " in cleaned:
                            parts = cleaned.split(" - ", 1)
                            artist = parts[0].strip()
                            song_title = parts[1].strip()
                        
                        media_info = {
                            "playing": True,
                            "artist": artist,
                            "title": song_title
                        }
                # VLC check
                elif "vlc" in pname:
                    if title != "VLC media player" and " - VLC media player" in title:
                        cleaned = title.replace(" - VLC media player", "")
                        artist = "VLC Player"
                        song_title = cleaned
                        if " - " in cleaned:
                            parts = cleaned.split(" - ", 1)
                            artist = parts[0].strip()
                            song_title = parts[1].strip()
                        
                        media_info = {
                            "playing": True,
                            "artist": artist,
                            "title": song_title
                        }
            except Exception:
                pass
                
    win32gui.EnumWindows(enum_windows_callback, None)
    return media_info

# --- API Routes ---
@app.route('/')
def index():
    resp = make_response(render_template('index.html', local_ip=get_local_ip()))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma']        = 'no-cache'
    resp.headers['Expires']       = '0'
    return resp

@app.route('/api/state', methods=['GET'])
def get_state():
    state_snapshot = _build_state_snapshot()
    # ETag short-circuit: skip JSON re-parse if nothing changed
    state_json = json.dumps(state_snapshot, sort_keys=True, default=str)
    etag = hashlib.md5(state_json.encode()).hexdigest()
    if request.headers.get("If-None-Match") == etag:
        return "", 304
    response = make_response(state_json, 200)
    response.headers["Content-Type"] = "application/json"
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    return response

# --- Server-Sent Events state stream (replaces 500ms polling) ---
def _build_state_snapshot():
    """Build and return the state dict (reused by both /api/state and /api/events)."""
    media_info = get_current_media_info()
    with state_lock:
        if media_info:
            assistant_state["music_status"] = media_info
        else:
            assistant_state["music_status"] = {
                "playing": False,
                "title": "No media playing",
                "artist": "Windows Media"
            }
        snapshot = copy.deepcopy(assistant_state)
    snapshot["tasks"]           = memory_manager.load_tasks()
    snapshot["config"]          = memory_manager.load_config()
    snapshot["gesture_running"] = gesture_control._active if gesture_control else False
    snapshot["gesture_preview"] = gesture_control.get_preview_state() if gesture_control else False
    # Include live mood data
    try:
        import emotion_engine as _em
        snapshot["mood"]       = _em.current_mood()
        snapshot["mood_index"] = _em.get_mood_index()
        snapshot["mood_color"] = _em.get_mood_color()
    except Exception:
        pass
    # Include active agent plan progress
    snapshot["agent_plan"] = assistant_state.get("agent_plan", None)
    return snapshot

@app.route('/api/events')
def api_events():
    """SSE stream: pushes state updates only when something changes."""
    import time

    def event_stream():
        last_etag = None
        while True:
            try:
                snapshot  = _build_state_snapshot()
                payload   = json.dumps(snapshot, sort_keys=True, default=str)
                etag      = hashlib.md5(payload.encode()).hexdigest()
                if etag != last_etag:
                    last_etag = etag
                    yield f"data: {payload}\n\n"
                else:
                    yield ": keep-alive\n\n"  # prevent proxy timeout
            except GeneratorExit:
                break
            except Exception as e:
                yield f"data: {{\"error\": \"{e}\"}}\n\n"
            time.sleep(0.8)  # push at most ~1.25 updates/s

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

# --- MEMORY BROWSER ---
@app.route('/api/memory', methods=['GET'])
def api_get_memory():
    """Return facts and entities from long-term memory."""
    mem = memory_manager.load_memory()
    return jsonify({
        "name":     mem.get("name", ""),
        "facts":    mem.get("facts", []),
        "entities": mem.get("entities", []),
    })

@app.route('/api/memory/facts/<int:idx>', methods=['DELETE'])
def api_delete_fact(idx):
    """Delete a fact by index."""
    mem = memory_manager.load_memory()
    facts = mem.get("facts", [])
    if 0 <= idx < len(facts):
        facts.pop(idx)
        mem["facts"] = facts
        memory_manager.save_memory(mem)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Index out of range"}), 404

@app.route('/api/memory/entities/<entity_id>', methods=['DELETE'])
def api_delete_entity(entity_id):
    """Delete an entity by its id field."""
    mem = memory_manager.load_memory()
    entities = mem.get("entities", [])
    mem["entities"] = [e for e in entities if e.get("id") != entity_id]
    memory_manager.save_memory(mem)
    return jsonify({"success": True})

@app.route('/api/tasks', methods=['GET'])
def api_get_tasks():
    return jsonify(memory_manager.load_tasks())

@app.route('/api/tasks', methods=['POST'])
def api_add_task():
    data = request.json or {}
    text = data.get("text", "")
    new_task = memory_manager.add_task(text)
    if new_task:
        return jsonify(new_task), 201
    return jsonify({"error": "Invalid task text"}), 400

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    success = memory_manager.delete_task(task_id)
    if success:
        return jsonify({"success": True})
    return jsonify({"error": "Task not found"}), 404

@app.route('/api/tasks/<int:task_id>/toggle', methods=['POST'])
def api_toggle_task(task_id):
    success = memory_manager.toggle_task(task_id)
    if success:
        return jsonify({"success": True})
    return jsonify({"error": "Task not found"}), 404

@app.route('/api/wake', methods=['POST'])
def wake_up():
    global active_mode
    active_mode = True
    if mascot_widget_ref is not None:
        try:
            # Emit the signal thread-safely to trigger wake up in PySide6 GUI thread
            mascot_widget_ref.web_wake_trigger.emit()
        except Exception as e:
            print(f"[WAKE ERROR]: {e}")
    return jsonify({"success": True})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    global stop_speaking_flag
    stop_speaking_flag = True
    if mascot_widget_ref is not None:
        try:
            mascot_widget_ref.interrupt_speech()
        except Exception as e:
            print(f"[API STOP MASCOT ERROR]: {e}")
    return jsonify({"success": True})


@app.route('/api/command', methods=['POST'])
def api_command():
    data = request.json or {}
    command = data.get("command", "").strip()
    if command and mascot_widget_ref is not None:
        try:
            mascot_widget_ref.trigger_remote_command(command)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})
    return jsonify({"success": False, "error": "Invalid command or mascot offline"})

@app.route('/api/media/control', methods=['POST'])
def api_media_control():
    data = request.json or {}
    action = data.get("action", "")
    try:
        import pyautogui
        if action == "play" or action == "pause":
            pyautogui.press('playpause')
        elif action == "next":
            pyautogui.press('nexttrack')
        elif action == "prev":
            pyautogui.press('prevtrack')
        elif action == "stop":
            pyautogui.press('stop')
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/config', methods=['POST'])
def api_save_config():
    data = request.json or {}
    selected_model = data.get("selected_model", "groq")
    gemini_api_key = data.get("gemini_api_key", "")
    groq_api_key = data.get("groq_api_key", "")
    nvidia_api_key = data.get("nvidia_api_key", "")
    openrouter_api_key = data.get("openrouter_api_key", "")
    selected_tts = data.get("selected_tts", "sapi")
    elevenlabs_api_key = data.get("elevenlabs_api_key", "")
    elevenlabs_voice_id = data.get("elevenlabs_voice_id", "21m00Tcm4TlvDq8ikWAM")
    kokoro_voice = data.get("kokoro_voice", "af_sarah")
    kokoro_voice_mix = data.get("kokoro_voice_mix", {})
    
    memory_manager.save_config(
        selected_model, gemini_api_key, groq_api_key, nvidia_api_key, openrouter_api_key,
        selected_tts=selected_tts, elevenlabs_api_key=elevenlabs_api_key, elevenlabs_voice_id=elevenlabs_voice_id, kokoro_voice=kokoro_voice,
        kokoro_voice_mix=kokoro_voice_mix
    )
    
    if mascot_widget_ref is not None:
        try:
            mascot_widget_ref.sync_menu_trigger.emit()
        except Exception as e:
            print(f"[CONFIG SYNC ERROR]: {e}")
            
    return jsonify({"success": True})

def set_gesture_control_state(enable):
    global gesture_running, gesture_thread
    import time
    if not gesture_control:
        return False, "Gesture control is not supported (missing cv2/mediapipe)."
    if enable:
        if not gesture_control._active:
            gesture_running = True
            gesture_thread = threading.Thread(target=gesture_control.start_capture_loop, daemon=True)
            gesture_thread.start()
            # Wait for thread to attempt to open camera
            time.sleep(0.4)
            if not gesture_control._active:
                gesture_running = False
                return False, "I was unable to open the webcam. Ensure it is connected and not in use."
            print("[APP] Started gesture control capture thread")
            return True, "Gesture control activated"
        return True, "Gesture control already active"
    else:
        if gesture_control._active or gesture_running:
            gesture_control.stop_capture_loop()
            gesture_running = False
            if gesture_thread:
                gesture_thread.join(timeout=1.0)
            print("[APP] Stopped gesture control capture thread")
            return True, "Gesture control deactivated"
        return True, "Gesture control not active"

@app.route('/api/gesture/status', methods=['GET'])
def get_gesture_status():
    global gesture_running
    gesture_running = gesture_control._active if gesture_control else False
    return jsonify({"running": gesture_running})

@app.route('/api/gesture/toggle', methods=['POST'])
def toggle_gesture_control():
    data = request.json or {}
    enable = data.get("enable", False)
    success, msg = set_gesture_control_state(enable)
    return jsonify({"success": success, "message": msg})

@app.route('/api/gesture/preview', methods=['POST'])
def toggle_gesture_preview():
    if not gesture_control or not gesture_control._active:
        return jsonify({"success": False, "message": "Gesture control is not running. Enable it first."})
    new_state = gesture_control.toggle_preview()
    return jsonify({"success": True, "preview": new_state})

# --- AUTOSTART ---
@app.route('/api/startup', methods=['GET'])
def get_startup_status():
    """Returns whether Meow is registered in Windows startup registry."""
    enabled = accessibility.get_startup_status()
    return jsonify({"enabled": enabled})

@app.route('/api/startup', methods=['POST'])
def set_startup_status():
    """Enables or disables Meow autostart via Windows registry."""
    data = request.json or {}
    enable = bool(data.get("enable", False))
    msg = accessibility.configure_startup(enable=enable)
    return jsonify({"success": True, "enabled": enable, "message": msg})

# --- ROUTINES CONFIG ---
@app.route('/api/routines/config', methods=['GET'])
def api_get_routines_config():
    """Return current morning/night routine configuration."""
    import automation_control
    return jsonify(automation_control.load_routines_config())

@app.route('/api/routines/config', methods=['POST'])
def api_save_routines_config():
    """Save morning/night routine configuration."""
    import automation_control
    data = request.json or {}
    ok = automation_control.save_routines_config(data)
    return jsonify({"success": ok})

@app.route('/api/routines/morning/run', methods=['POST'])
def api_run_morning_routine():
    """Manually trigger the morning routine."""
    import automation_control
    try:
        speech = automation_control.run_good_morning_routine()
        # Speak it via the assistant if speak_fn is available
        speak_fn = getattr(mascot_widget_ref, '_speak_async', None) if mascot_widget_ref else None
        if speak_fn:
            import threading
            threading.Thread(target=speak_fn, args=(speech,), daemon=True).start()
        return jsonify({"success": True, "speech": speech})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/routines/night/run', methods=['POST'])
def api_run_night_routine():
    """Manually trigger the night routine."""
    import automation_control
    try:
        speech = automation_control.run_night_routine()
        speak_fn = getattr(mascot_widget_ref, '_speak_async', None) if mascot_widget_ref else None
        if speak_fn:
            import threading
            threading.Thread(target=speak_fn, args=(speech,), daemon=True).start()
        return jsonify({"success": True, "speech": speech})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- VISION INTELLIGENCE ---
@app.route('/api/vision/describe', methods=['POST'])
def api_vision_describe():
    """Screenshot the active window and describe it with Gemini Vision."""
    import vision_control, llm_router, threading
    screenshot_path = os.path.join(os.path.dirname(__file__), "vision_temp_describe.jpg")
    try:
        vision_control.capture_active_window(screenshot_path)
        mem = memory_manager.load_memory()
        api_key = mem.get("gemini_api_key", "")
        if not api_key:
            return jsonify({"success": False, "error": "Gemini API key not configured"}), 400

        prompt = (
            "Describe ONLY what is literally visible in this screenshot. "
            "List the main application/window, visible file names, any open panels or tabs, "
            "and any text content you can read. "
            "If there is an error message, quote it exactly. "
            "CRITICAL: Do NOT invent, assume, or add any banners, warnings, or status messages "
            "that are not clearly visible in the image. Stick strictly to what you can see."
        )
        description = llm_router.call_gemini(
            api_key=api_key,
            system_prompt="You are a vision assistant describing screen content. Only describe what is literally visible. Never hallucinate or infer content that isn't clearly shown.",
            history=[],
            prompt=prompt,
            max_tokens=200,
            image_path=screenshot_path
        )
        # Speak it
        if mascot_widget_ref:
            _speak = getattr(mascot_widget_ref, '_speak_async_fn', None)
            if _speak:
                threading.Thread(target=_speak, args=(description,), daemon=True).start()

        return jsonify({"success": True, "description": description})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
        except Exception:
            pass

@app.route('/api/vision/read', methods=['POST'])
def api_vision_read():
    """OCR the active window and return clean text."""
    import screen_memory as _sm
    import vision_control
    screenshot_path = os.path.join(os.path.dirname(__file__), "vision_temp_read.png")
    try:
        vision_control.capture_active_window(screenshot_path)
        ocr_text = _sm.perform_windows_ocr(screenshot_path)
        return jsonify({"success": True, "text": ocr_text or "(No text detected)"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
        except Exception:
            pass

@app.route('/api/vision/camera', methods=['POST'])
def api_vision_camera():
    """One-shot webcam capture → Gemini Vision description → speak."""
    import vision_control, llm_router, threading
    webcam_path = os.path.join(os.path.dirname(__file__), "vision_temp_cam.jpg")
    try:
        success = vision_control.capture_webcam_frame(webcam_path)
        if not success:
            return jsonify({"success": False, "error": "Could not open webcam"}), 500

        mem = memory_manager.load_memory()
        api_key = mem.get("gemini_api_key", "")
        if not api_key:
            return jsonify({"success": False, "error": "Gemini API key not configured"}), 400

        prompt = "Describe what you see in front of the camera in detail. Focus on people, objects, setting, and any text visible. Be concise but accurate."
        description = llm_router.call_gemini(
            api_key=api_key,
            system_prompt="You are a vision assistant describing what a webcam sees.",
            history=[],
            prompt=prompt,
            max_tokens=250,
            image_path=webcam_path
        )
        if mascot_widget_ref:
            _speak = getattr(mascot_widget_ref, '_speak_async_fn', None)
            if _speak:
                threading.Thread(target=_speak, args=(description,), daemon=True).start()

        return jsonify({"success": True, "description": description})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            if os.path.exists(webcam_path):
                os.remove(webcam_path)
        except Exception:
            pass

@app.route('/api/vision/last_screen', methods=['GET'])
def api_vision_last_screen():
    """Return the most recent screen memory entry for the HUD widget."""
    import screen_memory as _sm
    entries = _sm.load_screen_index()
    if not entries:
        return jsonify({"success": True, "entry": None})
    latest = max(entries, key=lambda e: e.get("timestamp", 0))
    return jsonify({
        "success": True,
        "entry": {
            "window_title": latest.get("window_title", "Unknown"),
            "text":         latest.get("text", "")[:400],
            "timestamp":    latest.get("timestamp", 0),
        }
    })

# --- WINDOW MANAGER ---
@app.route('/api/windows', methods=['GET'])
def api_list_windows():
    """Return list of visible windows: [{title, process, pid}]."""
    import pc_control as _pc
    wins = _pc.list_open_windows()
    # Strip hwnd (not JSON-serialisable in all contexts) before sending
    clean = [{"title": w["title"], "process": w["process"], "pid": w["pid"]} for w in wins]
    return jsonify({"success": True, "windows": clean})

@app.route('/api/windows/focus', methods=['POST'])
def api_focus_window():
    """Bring a window matching title to the foreground."""
    import pc_control as _pc
    data = request.json or {}
    title = data.get("title", "")
    if not title:
        return jsonify({"success": False, "error": "No title provided"}), 400
    result = _pc.switch_to_window(title)
    return jsonify({"success": True, "message": result})

@app.route('/api/windows/close', methods=['POST'])
def api_close_window():
    """Close an app by window title match."""
    import pc_control as _pc
    data = request.json or {}
    title = data.get("title", "")
    if not title:
        return jsonify({"success": False, "error": "No title provided"}), 400
    result = _pc.close_app_by_name(title)
    return jsonify({"success": True, "message": result})

@app.route('/api/windows/focus_mode', methods=['POST'])
def api_focus_mode():
    """Enable or disable focus mode."""
    import pc_control as _pc
    data = request.json or {}
    enable = bool(data.get("enable", True))
    result = _pc.enable_focus_mode() if enable else _pc.disable_focus_mode()
    return jsonify({"success": True, "message": result})

# --- VOICE PERSONALITY ---
@app.route('/api/voice/style', methods=['GET'])
def api_get_voice_style():
    """Return the currently active voice style."""
    import voice_personality
    return jsonify({"success": True, "style": voice_personality.get_active_style()})

@app.route('/api/voice/style', methods=['POST'])
def api_set_voice_style():
    """Set the active voice style (casual / concise / professional)."""
    import voice_personality
    data = request.json or {}
    style = data.get("style", "casual")
    msg = voice_personality.set_active_style(style)
    return jsonify({"success": True, "style": style, "message": msg})

@app.route('/api/documents', methods=['GET'])
def api_get_documents():
    return jsonify(knowledge_manager.list_documents())

@app.route('/api/documents', methods=['POST'])
def api_upload_document():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(knowledge_manager.DOCUMENTS_DIR, filename)
        file.save(filepath)
        
        success = knowledge_manager.index_document(filepath, filename)
        if success:
            return jsonify({"success": True, "filename": filename}), 201
        else:
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass
            return jsonify({"error": "Failed to extract text or index file"}), 422

@app.route('/api/documents/<filename>', methods=['DELETE'])
def api_delete_document(filename):
    safe_filename = secure_filename(filename)
    if not safe_filename:
        return jsonify({"error": "Invalid filename"}), 400
    success = knowledge_manager.delete_document_index(safe_filename)
    if success:
        return jsonify({"success": True})
    return jsonify({"error": "Document not found or delete failed"}), 404

def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# --- MOBILE COMPANION APP ENDPOINTS ---
@app.route('/mobile')
def mobile_dashboard():
    return render_template('mobile.html', local_ip=get_local_ip())

@app.route('/api/mobile/command', methods=['POST'])
def api_mobile_command():
    data = request.json or {}
    command = data.get("command", "").strip()
    if not command:
        return jsonify({"error": "Empty command"}), 400
    
    if mascot_widget_ref is not None:
        try:
            mascot_widget_ref.trigger_remote_command(command)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Desktop companion widget is not running."}), 503

@app.route('/api/mobile/clipboard', methods=['GET', 'POST'])
def api_mobile_clipboard():
    import pyperclip
    if request.method == 'POST':
        data = request.json or {}
        text = data.get("text", "")
        try:
            pyperclip.copy(text)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        try:
            text = pyperclip.paste()
            return jsonify({"text": text})
        except Exception as e:
            return jsonify({"text": "", "error": str(e)})

@app.route('/api/mobile/control', methods=['POST'])
def api_mobile_control():
    data = request.json or {}
    action = data.get("action", "")
    value = data.get("value")
    
    import pc_control
    import pyautogui
    try:
        if action == "volume" and value is not None:
            pc_control.set_volume_percentage(int(value))
        elif action == "brightness" and value is not None:
            pc_control.set_brightness(int(value))
        elif action == "play_pause":
            pyautogui.press("playpause")
        elif action == "prev":
            pyautogui.press("prevtrack")
        elif action == "next":
            pyautogui.press("nexttrack")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- PLUGIN MARKETPLACE ENDPOINTS ---
@app.route('/api/plugins', methods=['GET'])
def api_get_plugins():
    import plugin_manager
    installed = plugin_manager.get_installed_plugins()
    # Format catalog metadata
    catalog = []
    for plugin_id, details in plugin_manager.COMMUNITY_CATALOG.items():
        is_installed = any(p["id"] == plugin_id for p in installed)
        catalog.append({
            "id": plugin_id,
            "name": details["name"],
            "description": details["description"],
            "version": details["version"],
            "installed": is_installed
        })
    return jsonify({
        "installed": installed,
        "catalog": catalog
    })

@app.route('/api/plugins/install', methods=['POST'])
def api_install_plugin():
    data = request.json or {}
    plugin_id = data.get("id", "").strip()
    
    import plugin_manager
    if plugin_id not in plugin_manager.COMMUNITY_CATALOG:
        return jsonify({"error": "Plugin not found in community catalog"}), 404
        
    details = plugin_manager.COMMUNITY_CATALOG[plugin_id]
    file_path = os.path.join(plugin_manager.PLUGINS_DIR, f"{plugin_id}.py")
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(details["code"])
            
        import pc_control
        success = plugin_manager.hot_load_plugin(plugin_id, mascot_widget_ref, app, pc_control)
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Plugin file written but hot-load failed."}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/plugins/toggle', methods=['POST'])
def api_toggle_plugin():
    data = request.json or {}
    plugin_id = data.get("id", "").strip()
    active = data.get("active")
    
    import plugin_manager
    installed = [p["id"] for p in plugin_manager.get_installed_plugins()]
    if plugin_id not in installed:
        return jsonify({"error": "Plugin not installed"}), 404
            
    plugin_manager.plugin_status[plugin_id] = bool(active)
    plugin_manager.save_status()
    
    import pc_control
    if active:
        plugin_manager.hot_load_plugin(plugin_id, mascot_widget_ref, app, pc_control)
    else:
        plugin_manager.unload_plugin(plugin_id)
        
    return jsonify({"success": True})

# --- AUTONOMOUS TASK QUEUE ENDPOINTS ---
@app.route('/api/queue', methods=['GET'])
def api_get_queue():
    import queue_manager
    return jsonify(queue_manager.get_queue())

@app.route('/api/queue', methods=['POST'])
def api_add_queue_task():
    data = request.json or {}
    command = data.get("command", "").strip()
    schedule_type = data.get("schedule_type", "once")
    interval = data.get("interval", 60)
    max_retries = data.get("max_retries", 3)
    
    if not command:
        return jsonify({"error": "Command string is required."}), 400
        
    import queue_manager
    try:
        task_id = queue_manager.add_task(command, schedule_type, interval, max_retries)
        return jsonify({"success": True, "id": task_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/queue/<task_id>', methods=['DELETE'])
def api_cancel_queue_task(task_id):
    import queue_manager
    success = queue_manager.cancel_task(task_id)
    if success:
        return jsonify({"success": True})
    return jsonify({"error": "Task not found or cancellation failed."}), 404
