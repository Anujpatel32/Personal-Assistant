"""
mascot_widget.py — MascotWidget Qt class for MEOW Assistant
============================================================
The interactive floating cat mascot widget: rendering, animation,
hotkeys, telemetry, backend wiring. Imported by companion.py.
"""

import os
import sys
import time
import math
import threading
import ctypes

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread, QPoint, QPointF, QRect, QRectF
from PySide6.QtGui  import (QPainter, QPen, QBrush, QColor, QFont, QCursor,
                             QIcon, QAction, QPainterPath, QLinearGradient,
                             QRadialGradient)
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                                QHBoxLayout, QPushButton, QMenu, QProgressBar,
                                QTextEdit)

import memory_manager
import studio_launcher
import screen_memory
import tts_engine
import voice_thread as _vt_mod
import llm_router

# Expose names used within MascotWidget
VoiceAssistantThread = _vt_mod.VoiceAssistantThread
get_main_sapi_voice  = tts_engine.get_main_sapi_voice

# Injected by companion.py at runtime
flask_app         = None
speak_async       = None
speak_sync_global = None
mascot_instance   = None
_append_chat      = None   # set by init_mascot

def append_chat(text, sender="assistant", is_stream=False):
    """Forward to companion.append_chat — wired via init_mascot."""
    if _append_chat:
        _append_chat(text, sender=sender, is_stream=is_stream)

def init_mascot(app, speak_async_fn, speak_sync_fn, llm_instance, append_chat_fn=None):
    """Call once from companion.py after all modules are loaded."""
    global flask_app, speak_async, speak_sync_global, _append_chat
    flask_app         = app
    speak_async       = speak_async_fn
    speak_sync_global = speak_sync_fn
    _append_chat      = append_chat_fn

# --- INTERACTIVE MASCOT COMPANION ---
class MascotWidget(QWidget):
    web_wake_trigger = Signal()    # Signal to wake up assistant thread-safely
    sync_menu_trigger = Signal()   # Signal to trigger voice state updates on model config changes

    def __init__(self, llm_instance):
        global mascot_instance
        super().__init__()
        mascot_instance = self
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(130, 130)
        self.state = "idle"
        self.is_dragging = False
        self.drag_position = QPoint()
        
        self.is_falling = False
        self.y_vel = 0.0

        self.random_walk_enabled = True
        self.mouse_chase_enabled = False
        self.walk_direction = 1

        # Cat animation and behavior states
        self.cat_pose = "sit"       # stand, walk, sit, sleep, drag, fall
        self.facing_left = False
        self.walk_cycle = 0.0
        self.behavior_timer = 0
        self.current_behavior = "sit" # walk, sit
        self.blink_timer = 0
        self.blink_active = False
        self.blink_duration = 0
        self.tail_phase = 0.0

        # Colors for dynamic vector art rendering
        self.COLOR_BODY = QColor("#FF9800")       # Orange
        self.COLOR_BELLY = QColor("#FFE082")      # Cream
        self.COLOR_STRIPE = QColor("#E65100")     # Rust/Dark Orange
        self.COLOR_NOSE = QColor("#FF8A80")       # Pink
        self.COLOR_EYE = QColor("#263238")        # Dark slate
        self.COLOR_PULSE = QColor(0, 229, 255)    # Default pulse color

        self.init_ui()
        self.init_backend()

    def init_ui(self):
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 50, screen.height() - self.height() - 70)

        # Telemetry Stats Update Timer (Every 5 seconds — reduced from 3s to lower CPU load)
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_telemetry_stats)
        self.stats_timer.start(5000)
        self.update_telemetry_stats()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick_loop)
        self.tick_timer.start(50)

        # Price tracker check timer (Every 5 minutes)
        self.price_timer = QTimer(self)
        self.price_timer.timeout.connect(self.check_prices_in_background)
        self.price_timer.start(300000)

        self.set_state("idle")
        
        # Connect Flask wake / change model signals
        self.web_wake_trigger.connect(self.on_web_wake)
        self.sync_menu_trigger.connect(self.on_sync_menu)


        # Startup greeting — full brief with weather + tasks (runs always at startup)
        def say_welcome():
            import datetime, random, time, threading
            import memory_manager as _mm
            import proactive_engine as _pe

            time.sleep(2.5)   # Let TTS engine finish initialising

            mem_data  = _mm.load_memory()
            user_name = mem_data.get("name", "Boss")
            hour      = datetime.datetime.now().hour

            # Time-appropriate opening
            if hour < 12:
                time_greeting = f"Good morning, {user_name}!"
            elif hour < 17:
                time_greeting = f"Good afternoon, {user_name}!"
            else:
                time_greeting = f"Good evening, {user_name}!"

            # Weather
            weather_str = ""
            try:
                w = _mm.fetch_weather("Pune")
                if w:
                    weather_str = f"Today's weather: {w[:60]}. "
            except Exception:
                pass

            # Pending tasks
            task_str = ""
            try:
                tasks   = _mm.load_tasks()
                pending = [t for t in tasks if not t.get("completed")]
                n       = len(pending)
                if n:
                    task_str = f"You have {n} pending task{'s' if n > 1 else ''}. "
                    if n <= 3:
                        task_str += "They are: " + ", ".join(t["text"] for t in pending[:3]) + ". "
                else:
                    task_str = "Your task list is clear. "
            except Exception:
                pass

            greeting = f"{time_greeting} {weather_str}{task_str}I'm ready whenever you need me."
            speak_async(greeting)

            # Mark morning brief done so proactive engine doesn't repeat it
            if 5 <= hour < 12:
                _pe._morning_done = True
                _pe._last_nudge["morning"] = time.time()

        import threading
        threading.Thread(target=say_welcome, daemon=True).start()

    def init_backend(self):
        self.backend_thread = VoiceAssistantThread()
        self.backend_thread.status_changed.connect(self.set_state)
        self.backend_thread.speech_detected.connect(self.on_user_speech)
        self.backend_thread.response_generated.connect(self.on_assistant_response)
        self.backend_thread.start()
        
        # Phase 1: Initialize Global Hotkey and Meow Studio Launcher
        try:
            self.launcher_window = studio_launcher.MeowStudioLauncher()
            self.hotkey_thread = studio_launcher.GlobalHotkeyThread()
            self.hotkey_thread.hotkey_pressed.connect(self.toggle_launcher)
            self.hotkey_thread.start()
            print("[LAUNCHER] Global hotkey thread & overlay initialized successfully.")
        except Exception as e:
            print(f"[LAUNCHER ERROR] Failed to initialize: {e}")
        
        # Phase 2: Initialize Screen Memory Daemon (Context-Aware Screen Memory RAG)
        try:
            self.screen_memory_daemon = screen_memory.ScreenMemoryDaemon()
            self.screen_memory_daemon.start()
            print("[SCREEN MEMORY] Background screen memory daemon started successfully.")
        except Exception as e:
            print(f"[SCREEN MEMORY ERROR] Failed to start daemon: {e}")

        
        # Phase 9: Initialize and Load plugins
        try:
            import plugin_manager
            import pc_control
            plugin_manager.load_plugins(self, flask_app, pc_control)
        except Exception as e:
            print(f"[COMPANION PLUGINS BOOT ERROR]: {e}")
        
        # Asynchronously scan and remember active workspace structure and styles on boot
        threading.Thread(target=memory_manager.scan_and_remember_active_workspace, daemon=True).start()
        
        # Phase 10: Initialize and Start Autonomous Task Queue Daemon
        try:
            import queue_manager
            self.task_queue_daemon = queue_manager.TaskQueueDaemon()
            self.task_queue_daemon.start()
        except Exception as e:
            print(f"[COMPANION TASK QUEUE BOOT ERROR]: {e}")

    def toggle_launcher(self):
        if hasattr(self, 'launcher_window') and self.launcher_window:
            if self.launcher_window.isVisible():
                self.launcher_window.hide()
            else:
                # Position the launcher at the center of the primary screen
                screen = QApplication.primaryScreen().geometry()
                self.launcher_window.move((screen.width() - self.launcher_window.width()) // 2,
                                          (screen.height() - self.launcher_window.height()) // 2)
                self.launcher_window.show()
                self.launcher_window.activateWindow()
                self.launcher_window.setFocus()

    def set_state(self, state):
        self.state = state
        self.update()

        # Propagate status to Meow Studio Launcher
        if hasattr(self, 'launcher_window') and self.launcher_window:
            if hasattr(self.launcher_window, 'set_mascot_state'):
                self.launcher_window.set_mascot_state(state)

        # Update mascot body colour from emotion engine
        try:
            import emotion_engine as _em
            mood_hex = _em.get_mood_color()
            mood_label = _em.current_mood()
            self.COLOR_BODY = QColor(mood_hex)
            # Adjust stripe to a darker version of the mood color
            c = QColor(mood_hex)
            self.COLOR_STRIPE = c.darker(140)
        except Exception:
            mood_label = "neutral"

        # Keep Flask app status updated + expose mood
        with flask_app.state_lock:
            flask_app.assistant_state["status"] = state
            try:
                flask_app.assistant_state["mood"] = mood_label
            except Exception:
                pass

    def update_telemetry_stats(self):
        try:
            import psutil
            import platform
            # cpu_percent(interval=None) is non-blocking but needs a prior call to warm up.
            # Use interval=0.1 to get an accurate reading without long blocking.
            cpu = psutil.cpu_percent(interval=0.1)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            gpu_data = memory_manager.get_gpu_stats()
            battery = psutil.sensors_battery()
            battery_pct = None
            battery_plugged = None
            if battery:
                battery_pct = battery.percent
                battery_plugged = battery.power_plugged
                
            with flask_app.state_lock:
                flask_app.assistant_state["pc_stats"] = {
                    "cpu": cpu,
                    "ram": ram.percent,
                    "ram_used_gb": round(ram.used / (1024 ** 3), 2),
                    "ram_total_gb": round(ram.total / (1024 ** 3), 2),
                    "disk": disk.percent,
                    "battery": battery_pct,
                    "battery_plugged": battery_plugged,
                    "processes": len(psutil.pids()),
                    "os": f"{platform.system()} {platform.release()}",
                    "gpu": gpu_data["gpu"],
                    "gpu_mem_used": gpu_data["gpu_mem_used"],
                    "gpu_mem_total": gpu_data["gpu_mem_total"],
                    "gpu_mem_pct": gpu_data["gpu_mem_pct"],
                    "gpu_name": gpu_data["gpu_name"]
                }

            # Proactive intelligence — check for nudges every telemetry tick
            try:
                import proactive_engine as _pe
                _pe.check_nudges(flask_app.assistant_state["pc_stats"])
            except Exception:
                pass

        except Exception as e:
            print(f"[TELEMETRY ERROR] {e}")


    @Slot()
    def on_web_wake(self):
        self.backend_thread.active_mode = True
        flask_app.active_mode = True
        self.trigger_emotion("happy", 2)
        speak_async("Yes boss?")

    @Slot()
    def on_sync_menu(self):
        config = memory_manager.load_config()
        model_name = config.get("selected_model", "groq")
        speak_async(f"Model configured to {model_name}, Boss.")

    @Slot(str)
    def on_user_speech(self, text):
        append_chat(text, sender="user")
        
        if hasattr(self, 'launcher_window') and self.launcher_window:
            self.launcher_window.update_chat_message(text, sender="user")

    def trigger_remote_command(self, command):
        """Allows executing commands sent remotely from the mobile app."""
        self.backend_thread.speech_detected.emit(command)
        
        import re
        def run_remote():
            self.backend_thread.clear_speech()
            self.backend_thread.status_changed.emit("thinking")
            try:
                response = self.backend_thread.process_assistant_logic(command)
                import types
                if isinstance(response, types.GeneratorType):
                    accumulated_text = ""
                    sentence_buffer = ""
                    first_dispatched = False
                    
                    try:
                        for chunk in response:
                            if flask_app.stop_speaking_flag:
                                break
                            accumulated_text += chunk
                            sentence_buffer += chunk
                            self.backend_thread.response_generated.emit(accumulated_text, True)
                            
                            # Fast-start: dispatch first phrase early on comma or punctuation to eliminate silence
                            if not first_dispatched:
                                if re.search(r'[.!?]', sentence_buffer) or (len(sentence_buffer.split()) >= 4 and re.search(r'[,;:\n]', sentence_buffer)):
                                    parts = re.split(r'(?<=[.!?,;:\n])', sentence_buffer, maxsplit=1)
                                    if len(parts) > 1 and parts[0].strip():
                                        self.backend_thread.speech_queue.put(parts[0].strip())
                                        sentence_buffer = parts[1]
                                        first_dispatched = True
                                        continue

                            # Split completed sentences immediately upon finding punctuation
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
                                            self.backend_thread.speech_queue.put(s_clean)
                                            first_dispatched = True
                                sentence_buffer = new_buffer + sentences[-1]
                    except Exception as loop_err:
                        print(f"[REMOTE GENERATOR LOOP ERROR]: {loop_err}")
                        if not accumulated_text.strip():
                            accumulated_text = "Sorry, I encountered an error receiving the response stream."
                            self.backend_thread.response_generated.emit(accumulated_text, False)
                            self.backend_thread.speech_queue.put(accumulated_text)
                            
                    if sentence_buffer.strip() and not flask_app.stop_speaking_flag:
                        self.backend_thread.speech_queue.put(sentence_buffer.strip())

                        
                    self.backend_thread.add_to_history(command, accumulated_text, llm_router._last_reasoning_details)
                else:
                    emotion = "speaking"
                    if any(w in response.lower() for w in ["sorry", "error", "unable", "couldn't"]):
                        emotion = "sad"
                    elif any(w in response.lower() for w in ["perfect", "yes", "success", "great", "welcome"]):
                        emotion = "happy"
                    self.backend_thread.status_changed.emit(emotion)
                    self.backend_thread.response_generated.emit(response, False)
                    self.backend_thread.speech_queue.put(response)
            except Exception as logic_err:
                print(f"[REMOTE LOGIC ERROR]: {logic_err}")
                err_msg = "Sorry, I encountered an error processing your remote command."
                self.backend_thread.status_changed.emit("sad")
                self.backend_thread.response_generated.emit(err_msg, False)
                self.backend_thread.speech_queue.put(err_msg)
                
        threading.Thread(target=run_remote, daemon=True).start()

    @Slot(str, bool)
    def on_assistant_response(self, text, is_stream=False):
        append_chat(text, sender="assistant", is_stream=is_stream)
        
        if hasattr(self, 'launcher_window') and self.launcher_window:
            self.launcher_window.update_chat_message(text, sender="assistant", is_stream=is_stream)

    def trigger_emotion(self, emotion, duration=2):
        self.set_state(emotion)
        QTimer.singleShot(duration * 1000, lambda: self.set_state("idle") if self.state == emotion else None)

    def align_overlays(self):
        pass

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 1. Draw status/interaction rings first
        if self.state in ["listening", "thinking", "speaking"]:
            t = time.time()
            if self.state == "listening":
                color = QColor(255, 0, 85)
                pulse = int(150 + 105 * math.sin(t * 12))
            elif self.state == "thinking":
                color = QColor(0, 229, 255)
                pulse = 255
            else:
                color = QColor(0, 255, 136)
                pulse = int(150 + 105 * math.sin(t * 15))
                
            color.setAlpha(pulse)
            pen = QPen(color, 3, Qt.DashLine)
            painter.setPen(pen)
            
            rect = QRect(4, 4, self.width() - 8, self.height() - 8)
            if self.state == "thinking":
                angle = int((t * 220) % 360) * 16
                painter.drawArc(rect, angle, 120 * 16)
            else:
                painter.drawEllipse(rect)

        # 2. Draw the cat body and poses
        painter.save()
        # Transform coordinate space if the cat is facing left
        if self.facing_left:
            painter.translate(self.width(), 0)
            painter.scale(-1, 1)
            
        self.draw_cat(painter)
        painter.restore()

    def draw_cat(self, painter):
        # We assume the default facing is RIGHT.
        # Bottom of widget is Y=130, ground_y = 114.
        ground_y = 114
        
        # Calculate mouth speech / meowing animation amount
        # Only animate mouth when audio is genuinely playing through the hardware
        meow = 0
        if tts_engine.is_speaking():
            meow = abs(math.sin(time.time() * 20)) * 5

        # 0. Draw soft ground shadow
        shadow_opacity = 50
        shadow_width = 85
        shadow_x = 24
        if self.cat_pose == "sleep":
            shadow_width = 75
            shadow_x = 28
        elif self.cat_pose == "sit":
            shadow_width = 65
            shadow_x = 30
        elif self.cat_pose == "drag":
            shadow_opacity = 15
            shadow_width = 60
            shadow_x = 35
        elif self.cat_pose == "fall":
            # Shadow grows fainter as the cat falls
            screen_geo = QApplication.primaryScreen().geometry()
            bottom_limit = screen_geo.height() - self.height() - 40
            height_diff = max(0, bottom_limit - self.y())
            shadow_opacity = max(5, 50 - height_diff // 4)
            shadow_width = max(40, 85 - height_diff // 6)
            shadow_x = 65 - shadow_width / 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, shadow_opacity)))
        painter.drawEllipse(QRectF(shadow_x, ground_y - 2, shadow_width, 5))

        # Define parts based on the pose
        if self.cat_pose == "sleep":
            # Curved body
            breath = math.sin(time.time() * 3) * 1.5
            
            # Draw tail first (behind body) with gradient
            tail_path = QPainterPath()
            tail_path.moveTo(85, 95)
            tail_path.cubicTo(100, 110, 60, 112, 45, 98)
            tail_grad = QLinearGradient(85, 95, 45, 98)
            tail_grad.setColorAt(0.0, QColor("#D35400")) # connection dark orange
            tail_grad.setColorAt(0.8, QColor("#E67E22")) # body orange
            tail_grad.setColorAt(1.0, QColor("#FFF9C4")) # cream tip
            painter.setPen(QPen(tail_grad, 7, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(tail_path)
            
            # Draw body with gradient
            body_grad = QLinearGradient(35, 76, 97, 110)
            body_grad.setColorAt(0.0, QColor("#D35400"))
            body_grad.setColorAt(0.6, QColor("#E67E22"))
            body_grad.setColorAt(1.0, QColor("#F39C12"))
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            painter.setBrush(QBrush(body_grad))
            painter.drawEllipse(QRectF(35, 76 - breath/2, 62, 34 + breath))
            
            # Belly patch
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#FFF9C4")))
            painter.drawEllipse(QRectF(45, 84 - breath/2, 38, 20 + breath))
            
            # Head (tucked down)
            head_rect = QRectF(30, 75 - breath/2, 34, 30)
            head_grad = QRadialGradient(47, 90, 17)
            head_grad.setColorAt(0.0, QColor("#E67E22"))
            head_grad.setColorAt(1.0, QColor("#D35400"))
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            painter.setBrush(QBrush(head_grad))
            painter.drawEllipse(head_rect)
            
            hx = 47
            hy = 90 - breath/2
            
            # Ears folded back
            # Left Ear
            left_ear = QPainterPath()
            left_ear.moveTo(hx - 12, hy - 8)
            left_ear.lineTo(hx - 18, hy + 2)
            left_ear.lineTo(hx - 6, hy - 4)
            painter.setBrush(QBrush(QColor("#D35400")))
            painter.drawPath(left_ear)
            # Right Ear
            right_ear = QPainterPath()
            right_ear.moveTo(hx - 4, hy - 12)
            right_ear.lineTo(hx + 2, hy - 4)
            right_ear.lineTo(hx + 6, hy - 10)
            painter.drawPath(right_ear)
            
            # Closed eyes (arcs)
            painter.setPen(QPen(QColor("#2E1C0C"), 1.8, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(QRectF(hx - 10, hy - 4, 6, 4), 0, 180 * 16)
            painter.drawArc(QRectF(hx + 2, hy - 4, 6, 4), 0, 180 * 16)
            
            # Nose
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#E91E63")))
            painter.drawEllipse(QRectF(hx - 1, hy + 2, 3, 2))
            
        elif self.cat_pose == "sit":
            # Sitting pose
            # Tail wrapping around feet
            tail_path = QPainterPath()
            tail_path.moveTo(40, 95)
            tail_path.cubicTo(45, 114 + 2 * math.sin(self.tail_phase), 75, 114, 82, 104 + 2 * math.sin(self.tail_phase))
            
            tail_grad = QLinearGradient(40, 95, 82, 104)
            tail_grad.setColorAt(0.0, QColor("#D35400"))
            tail_grad.setColorAt(0.7, QColor("#E67E22"))
            tail_grad.setColorAt(1.0, QColor("#FFF9C4"))
            painter.setPen(QPen(tail_grad, 7, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(tail_path)
            
            # Back leg fold (ellipse)
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            leg_fold_grad = QRadialGradient(49, 95, 13)
            leg_fold_grad.setColorAt(0.0, QColor("#E67E22"))
            leg_fold_grad.setColorAt(1.0, QColor("#D35400"))
            painter.setBrush(QBrush(leg_fold_grad))
            painter.drawEllipse(QRectF(36, 82, 26, 26))
            
            # Body
            body_grad = QLinearGradient(38, 58, 82, 106)
            body_grad.setColorAt(0.0, QColor("#D35400"))
            body_grad.setColorAt(0.6, QColor("#E67E22"))
            body_grad.setColorAt(1.0, QColor("#F39C12"))
            painter.setBrush(QBrush(body_grad))
            painter.drawEllipse(QRectF(38, 58, 44, 48))
            
            # Belly patch
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#FFF9C4")))
            painter.drawEllipse(QRectF(44, 70, 32, 34))
            
            # Front Legs (straight down with gradient for socks)
            self.draw_leg_direct(painter, 64, 85, 64, ground_y)
            self.draw_leg_direct(painter, 54, 85, 54, ground_y)
            
            # Front paws
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#FFF9C4")))
            painter.drawEllipse(QRectF(60.5, ground_y - 2, 8, 5))
            painter.drawEllipse(QRectF(50.5, ground_y - 2, 8, 5))
            # Back paw
            painter.drawEllipse(QRectF(42, ground_y - 2, 9, 5))
            
            # Head
            hx = 65
            hy = 48
            head_rect = QRectF(hx - 21, hy - 18, 42, 36)
            head_grad = QRadialGradient(hx, hy, 21, hx - 2, hy - 4)
            head_grad.setColorAt(0.0, QColor("#FFCC80"))
            head_grad.setColorAt(0.6, QColor("#E67E22"))
            head_grad.setColorAt(1.0, QColor("#C0392B"))
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            painter.setBrush(QBrush(head_grad))
            painter.drawEllipse(head_rect)
            
            # Face Features
            self.draw_face_features(painter, hx, hy, meow)
            
        elif self.cat_pose == "drag":
            # Suspended pose
            body_y = 52
            
            # Tail dangling
            tail_path = QPainterPath()
            tail_path.moveTo(42, body_y + 10)
            tail_path.cubicTo(30, body_y + 20, 25, body_y + 40, 30, body_y + 55)
            tail_grad = QLinearGradient(42, body_y + 10, 30, body_y + 55)
            tail_grad.setColorAt(0.0, QColor("#D35400"))
            tail_grad.setColorAt(1.0, QColor("#FFF9C4"))
            painter.setPen(QPen(tail_grad, 7, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(tail_path)
            
            # Body
            body_grad = QLinearGradient(40, body_y - 20, 82, body_y + 28)
            body_grad.setColorAt(0.0, QColor("#D35400"))
            body_grad.setColorAt(0.6, QColor("#E67E22"))
            body_grad.setColorAt(1.0, QColor("#F39C12"))
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            painter.setBrush(QBrush(body_grad))
            painter.drawEllipse(QRectF(40, body_y - 20, 42, 48))
            
            # Belly patch
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#FFF9C4")))
            painter.drawEllipse(QRectF(46, body_y - 8, 30, 32))
            
            # Dangling legs wiggling
            t = time.time()
            leg_wiggle1 = math.sin(t * 25) * 6
            leg_wiggle2 = math.cos(t * 25) * 6
            
            self.draw_leg_direct(painter, 48, body_y + 20, 44 + leg_wiggle1, body_y + 48)
            self.draw_leg_direct(painter, 58, body_y + 20, 56 + leg_wiggle2, body_y + 48)
            self.draw_leg_direct(painter, 68, body_y + 20, 70 + leg_wiggle1, body_y + 46)
            self.draw_leg_direct(painter, 74, body_y + 20, 80 + leg_wiggle2, body_y + 46)
            
            # Dangling paws
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#FFF9C4")))
            painter.drawEllipse(QRectF(41 + leg_wiggle1, body_y + 45, 7, 5))
            painter.drawEllipse(QRectF(53 + leg_wiggle2, body_y + 45, 7, 5))
            painter.drawEllipse(QRectF(67 + leg_wiggle1, body_y + 43, 7, 5))
            painter.drawEllipse(QRectF(77 + leg_wiggle2, body_y + 43, 7, 5))
            
            # Head
            hx = 61
            hy = body_y - 25
            head_rect = QRectF(hx - 21, hy - 18, 42, 36)
            head_grad = QRadialGradient(hx, hy, 21, hx - 2, hy - 4)
            head_grad.setColorAt(0.0, QColor("#FFCC80"))
            head_grad.setColorAt(0.6, QColor("#E67E22"))
            head_grad.setColorAt(1.0, QColor("#C0392B"))
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            painter.setBrush(QBrush(head_grad))
            painter.drawEllipse(head_rect)
            
            # Face Features (Surprised!)
            self.draw_face_features(painter, hx, hy, meow=6, surprised=True)

        elif self.cat_pose == "fall":
            # Falling pose, wiggling fast
            body_y = 52
            t = time.time()
            
            # Tail puffing up / spinning
            tail_path = QPainterPath()
            tail_path.moveTo(42, body_y + 10)
            tail_path.cubicTo(20 + 10 * math.sin(t * 30), body_y + 15, 15, body_y - 15, 25 + 15 * math.cos(t * 30), body_y - 25)
            tail_grad = QLinearGradient(42, body_y + 10, 25, body_y - 25)
            tail_grad.setColorAt(0.0, QColor("#D35400"))
            tail_grad.setColorAt(1.0, QColor("#FFF9C4"))
            painter.setPen(QPen(tail_grad, 8, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(tail_path)
            
            # Body
            body_grad = QLinearGradient(40, body_y - 20, 82, body_y + 28)
            body_grad.setColorAt(0.0, QColor("#D35400"))
            body_grad.setColorAt(0.6, QColor("#E67E22"))
            body_grad.setColorAt(1.0, QColor("#F39C12"))
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            painter.setBrush(QBrush(body_grad))
            painter.drawEllipse(QRectF(40, body_y - 20, 42, 48))
            
            # Belly patch
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#FFF9C4")))
            painter.drawEllipse(QRectF(46, body_y - 8, 30, 32))
            
            # Flailing limbs
            leg_wiggle1 = math.sin(t * 40) * 12
            leg_wiggle2 = math.cos(t * 40) * 12
            
            self.draw_leg_direct(painter, 48, body_y + 20, 44 + leg_wiggle1, body_y + 44)
            self.draw_leg_direct(painter, 58, body_y + 20, 56 + leg_wiggle2, body_y + 44)
            self.draw_leg_direct(painter, 68, body_y + 20, 70 + leg_wiggle2, body_y + 42)
            self.draw_leg_direct(painter, 74, body_y + 20, 80 + leg_wiggle1, body_y + 42)
            
            # Flailing paws
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#FFF9C4")))
            painter.drawEllipse(QRectF(41 + leg_wiggle1, body_y + 41, 7, 5))
            painter.drawEllipse(QRectF(53 + leg_wiggle2, body_y + 41, 7, 5))
            painter.drawEllipse(QRectF(67 + leg_wiggle2, body_y + 39, 7, 5))
            painter.drawEllipse(QRectF(77 + leg_wiggle1, body_y + 39, 7, 5))
            
            # Head
            hx = 61
            hy = body_y - 25
            head_rect = QRectF(hx - 21, hy - 18, 42, 36)
            head_grad = QRadialGradient(hx, hy, 21, hx - 2, hy - 4)
            head_grad.setColorAt(0.0, QColor("#FFCC80"))
            head_grad.setColorAt(0.6, QColor("#E67E22"))
            head_grad.setColorAt(1.0, QColor("#C0392B"))
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            painter.setBrush(QBrush(head_grad))
            painter.drawEllipse(head_rect)
            
            # Face Features (Scared / dizzy)
            self.draw_face_features(painter, hx, hy, meow=8, scared=True)

        else: # stand or walk
            # Compute body / head bobbing for walking
            body_bob = 0
            head_bob = 0
            if self.cat_pose == "walk":
                body_bob = (1.0 - math.cos(self.walk_cycle * 2)) * 1.5
                head_bob = math.sin(self.walk_cycle * 2) * 1.5

            body_rect = QRectF(32, 57 - body_bob, 56, 36)
            head_rect = QRectF(71, 39 - head_bob, 42, 36)
            
            # Draw tail (behind body) with gradient
            tail_path = QPainterPath()
            tail_path.moveTo(34, 70 - body_bob)
            if self.state == "happy":
                tail_path.cubicTo(15, 62 + 8 * math.sin(time.time() * 25), 8, 42 - 8 * math.sin(time.time() * 25), 18 + 6 * math.sin(time.time() * 25), 22)
            elif self.cat_pose == "walk":
                tail_path.cubicTo(15, 62 + 8 * math.sin(self.walk_cycle), 8, 42 - 8 * math.sin(self.walk_cycle), 18 + 5 * math.sin(self.walk_cycle), 22)
            else:
                tail_path.cubicTo(15, 62 + 4 * math.sin(self.tail_phase), 8, 42 - 4 * math.sin(self.tail_phase), 18 + 3 * math.sin(self.tail_phase), 22)
            
            tail_grad = QLinearGradient(34, 70 - body_bob, 18, 22)
            tail_grad.setColorAt(0.0, QColor("#D35400"))
            tail_grad.setColorAt(0.8, QColor("#E67E22"))
            tail_grad.setColorAt(1.0, QColor("#FFF9C4"))
            painter.setPen(QPen(tail_grad, 7, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(tail_path)

            # Draw legs (behind body: Back-Right & Front-Right)
            self.draw_leg(painter, leg_name="BR", bob=body_bob, ground_y=ground_y)
            self.draw_leg(painter, leg_name="FR", bob=body_bob, ground_y=ground_y)

            # Draw body
            body_grad = QLinearGradient(32, 57 - body_bob, 88, 93 - body_bob)
            body_grad.setColorAt(0.0, QColor("#D35400"))
            body_grad.setColorAt(0.5, QColor("#E67E22"))
            body_grad.setColorAt(1.0, QColor("#F39C12"))
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            painter.setBrush(QBrush(body_grad))
            painter.drawEllipse(body_rect)

            # Draw body stripes (3 cute stripes on back, semi-transparent)
            stripe_pen = QPen(QColor(186, 74, 0, 190), 2.5, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(stripe_pen)
            bx = 60
            by = 75 - body_bob
            painter.drawLine(QPointF(bx - 8, by - 18), QPointF(bx - 8, by - 8))
            painter.drawLine(QPointF(bx, by - 18), QPointF(bx, by - 6))
            painter.drawLine(QPointF(bx + 8, by - 18), QPointF(bx + 8, by - 8))

            # Belly patch
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#FFF9C4")))
            painter.drawEllipse(QRectF(44, 66 - body_bob, 36, 24))

            # Draw front legs (in front of body: Back-Left & Front-Left)
            self.draw_leg(painter, leg_name="BL", bob=body_bob, ground_y=ground_y)
            self.draw_leg(painter, leg_name="FL", bob=body_bob, ground_y=ground_y)

            # Head
            hx = 92
            hy = 57 - head_bob
            head_rect = QRectF(hx - 21, hy - 18, 42, 36)
            head_grad = QRadialGradient(hx, hy, 21, hx - 2, hy - 4)
            head_grad.setColorAt(0.0, QColor("#FFCC80"))
            head_grad.setColorAt(0.6, QColor("#E67E22"))
            head_grad.setColorAt(1.0, QColor("#C0392B"))
            painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
            painter.setBrush(QBrush(head_grad))
            painter.drawEllipse(head_rect)

            # Face Features
            self.draw_face_features(painter, hx, hy, meow)

    def draw_leg_direct(self, painter, x1, y1, x2, y2):
        leg_grad = QLinearGradient(x1, y1, x2, y2)
        leg_grad.setColorAt(0.0, QColor("#E67E22"))
        leg_grad.setColorAt(0.7, QColor("#F39C12"))
        leg_grad.setColorAt(1.0, QColor("#FFF9C4")) # cream paw socks
        painter.setPen(QPen(leg_grad, 6, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def draw_leg(self, painter, leg_name, bob, ground_y):
        pivots = {
            "BL": (46, 84),
            "BR": (38, 84),
            "FL": (80, 84),
            "FR": (72, 84)
        }
        px, py = pivots[leg_name]
        py -= bob
        
        if self.cat_pose == "walk":
            if leg_name in ["FL", "BR"]:
                phase = self.walk_cycle
            else:
                phase = self.walk_cycle + math.pi
                
            swing = 10 * math.sin(phase)
            # Lift the paw only when swinging forward
            lift = 6 * math.sin(phase) if math.sin(phase) > 0 else 0
            paw_x = px + swing
            paw_y = ground_y - lift
        else:
            paw_x = px
            paw_y = ground_y
            
        leg_grad = QLinearGradient(px, py, paw_x, paw_y)
        leg_grad.setColorAt(0.0, QColor("#E67E22"))
        leg_grad.setColorAt(0.7, QColor("#F39C12"))
        leg_grad.setColorAt(1.0, QColor("#FFF9C4")) # cream paw socks
        painter.setPen(QPen(leg_grad, 7, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(px, py), QPointF(paw_x, paw_y))
        
        # Paws
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#FFF9C4")))
        painter.drawEllipse(QRectF(paw_x - 4, paw_y - 2.5, 8, 5))

    def draw_eye(self, painter, ex, ey, scared=False, surprised=False, happy=False, blink=False, sad=False):
        if blink:
            painter.setPen(QPen(QColor("#2E1C0C"), 2.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(ex - 4, ey), QPointF(ex + 4, ey))
            return

        if scared:
            painter.setPen(QPen(QColor("#2E1C0C"), 2.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(ex - 3, ey - 3), QPointF(ex + 1, ey))
            painter.drawLine(QPointF(ex - 3, ey + 3), QPointF(ex + 1, ey))
            return
            
        if happy:
            painter.setPen(QPen(QColor("#2E1C0C"), 2.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(ex - 4, ey + 1), QPointF(ex, ey - 3))
            painter.drawLine(QPointF(ex, ey - 3), QPointF(ex + 4, ey + 1))
            return
            
        if sad:
            painter.setPen(QPen(QColor("#2E1C0C"), 2.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(ex - 4, ey - 3), QPointF(ex + 2, ey + 1))
            return

        # Detailed glassy cat eye
        # Dark surrounding eyeliner
        painter.setPen(QPen(QColor("#1A0A00"), 1.2))
        painter.setBrush(QBrush(QColor("#2E1C0C")))
        painter.drawEllipse(QRectF(ex - 5.5, ey - 5.5, 11, 11))

        # Colored Iris (radial gradient)
        iris_grad = QRadialGradient(ex, ey, 5, ex - 1.5, ey - 1.5)
        iris_grad.setColorAt(0.0, QColor("#EEFF41")) # bright yellow-green
        iris_grad.setColorAt(0.7, QColor("#C0CA33")) # olive green
        iris_grad.setColorAt(1.0, QColor("#558B2F")) # dark forest green
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(iris_grad))
        painter.drawEllipse(QRectF(ex - 4.5, ey - 4.5, 9, 9))

        # Pupil (vertical slit)
        p_w = 1.6
        p_h = 7.0
        if surprised:
            p_w = 4.5
            p_h = 6.5
        painter.setBrush(QBrush(QColor("#1A0A00")))
        painter.drawEllipse(QRectF(ex - p_w/2, ey - p_h/2, p_w, p_h))

        # Specular Highlight reflections
        painter.setBrush(QBrush(Qt.white))
        painter.drawEllipse(QRectF(ex - 3.2, ey - 3.2, 2.5, 2.5))
        painter.drawEllipse(QRectF(ex + 1.2, ey + 1.2, 1.0, 1.0))

    def draw_face_features(self, painter, hx, hy, meow, surprised=False, scared=False):
        # Left Ear
        outer_left = QPainterPath()
        outer_left.moveTo(hx - 15, hy - 14)
        outer_left.lineTo(hx - 14, hy - 29)
        outer_left.lineTo(hx - 4, hy - 17)
        ear_grad_l = QLinearGradient(hx - 15, hy - 14, hx - 14, hy - 29)
        ear_grad_l.setColorAt(0.0, QColor("#E67E22"))
        ear_grad_l.setColorAt(1.0, QColor("#D35400"))
        painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
        painter.setBrush(QBrush(ear_grad_l))
        painter.drawPath(outer_left)
        
        inner_left = QPainterPath()
        inner_left.moveTo(hx - 12, hy - 15)
        inner_left.lineTo(hx - 12, hy - 25)
        inner_left.lineTo(hx - 6, hy - 17)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#FFCDD2"))) # soft pink
        painter.drawPath(inner_left)

        # Right Ear
        outer_right = QPainterPath()
        outer_right.moveTo(hx + 4, hy - 17)
        outer_right.lineTo(hx + 14, hy - 29)
        outer_right.lineTo(hx + 15, hy - 14)
        ear_grad_r = QLinearGradient(hx + 4, hy - 17, hx + 14, hy - 29)
        ear_grad_r.setColorAt(0.0, QColor("#E67E22"))
        ear_grad_r.setColorAt(1.0, QColor("#D35400"))
        painter.setPen(QPen(QColor(186, 74, 0, 180), 1.2))
        painter.setBrush(QBrush(ear_grad_r))
        painter.drawPath(outer_right)
        
        inner_right = QPainterPath()
        inner_right.moveTo(hx + 6, hy - 17)
        inner_right.lineTo(hx + 12, hy - 25)
        inner_right.lineTo(hx + 12, hy - 15)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#FFCDD2"))) # soft pink
        painter.drawPath(inner_right)

        # Forehead stripes (semi-transparent)
        painter.setPen(QPen(QColor(186, 74, 0, 190), 2.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(hx - 3, hy - 15), QPointF(hx - 3, hy - 9))
        painter.drawLine(QPointF(hx + 3, hy - 15), QPointF(hx + 3, hy - 9))

        # Eyes
        blink = self.blink_active
        sad = (self.state == "sad")
        happy = (self.state == "happy")
        
        self.draw_eye(painter, hx - 6, hy - 2, scared=scared, surprised=surprised, happy=happy, blink=blink, sad=sad)
        self.draw_eye(painter, hx + 8, hy - 2, scared=scared, surprised=surprised, happy=happy, blink=blink, sad=sad)

        if self.state == "angry" and not blink:
            # Slanted angry eyebrows
            painter.setPen(QPen(QColor("#2E1C0C"), 2.0, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(hx - 10, hy - 7), QPointF(hx - 2, hy - 4))
            painter.drawLine(QPointF(hx + 12, hy - 7), QPointF(hx + 4, hy - 4))

        # Puffy muzzle (cheeks)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#FFF9C4")))
        painter.drawEllipse(QRectF(hx - 7, hy + 1, 7, 5))
        painter.drawEllipse(QRectF(hx, hy + 1, 7, 5))

        # Nose
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#E91E63"))) # bright pink
        nose_path = QPainterPath()
        nose_path.moveTo(hx - 1, hy + 2)
        nose_path.lineTo(hx + 3, hy + 2)
        nose_path.lineTo(hx + 1, hy + 5)
        painter.drawPath(nose_path)

        # Mouth
        if meow > 0:
            painter.setPen(QPen(QColor("#2E1C0C"), 1.2, Qt.SolidLine))
            painter.setBrush(QBrush(QColor("#E91E63")))
            painter.drawEllipse(QRectF(hx - 1, hy + 6, 4, meow))
        else:
            painter.setPen(QPen(QColor("#2E1C0C"), 1.2, Qt.SolidLine, Qt.RoundCap))
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(QRectF(hx - 3, hy + 4, 4, 3), 180 * 16, 180 * 16)
            painter.drawArc(QRectF(hx + 1, hy + 4, 4, 3), 180 * 16, 180 * 16)

        # Whiskers (thin, semi-transparent grey)
        painter.setPen(QPen(QColor(230, 230, 230, 190), 0.8, Qt.SolidLine))
        # Left cheek whiskers
        painter.drawLine(QPointF(hx - 7, hy + 4), QPointF(hx - 18, hy + 2))
        painter.drawLine(QPointF(hx - 7, hy + 6), QPointF(hx - 17, hy + 8))
        # Right cheek whiskers
        painter.drawLine(QPointF(hx + 9, hy + 4), QPointF(hx + 20, hy + 2))
        painter.drawLine(QPointF(hx + 9, hy + 6), QPointF(hx + 19, hy + 8))

    def tick_loop(self):
        import random
        screen = QApplication.primaryScreen().geometry()
        
        # Update tail sway phase continuously
        self.tail_phase = (self.tail_phase + 0.1) % (2 * math.pi)

        # Eye blinking logic
        if not self.blink_active:
            if random.random() < 0.01:  # ~1% chance per tick to start blinking
                self.blink_active = True
                self.blink_duration = random.randint(3, 5) # Blinks for 3-5 frames (150-250ms)
        else:
            self.blink_duration -= 1
            if self.blink_duration <= 0:
                self.blink_active = False

        if self.is_falling:
            self.cat_pose = "fall"
            self.walk_cycle = (self.walk_cycle + 0.4) % (2 * math.pi) # Wiggle limbs fast
            self.y_vel += 1.5
            new_y = self.y() + self.y_vel
            bottom_limit = screen.height() - self.height() - 40
            if new_y >= bottom_limit:
                new_y = bottom_limit
                self.is_falling = False
                self.y_vel = 0.0
                self.trigger_emotion("happy", 1)
            self.move(self.x(), int(new_y))
            self.align_overlays()
            self.update()
            return

        if self.is_dragging:
            self.cat_pose = "drag"
            self.update()
            return

        if self.state == "sleeping":
            self.cat_pose = "sleep"
            self.update()
            return

        is_speaking_now = False
        if self.state == "speaking":
            is_speaking_now = True
        elif tts_engine._main_sapi_voice is not None:
            try:
                if tts_engine._main_sapi_voice.Status.RunningState == 2:
                    is_speaking_now = True
            except Exception:
                pass
        if is_speaking_now or self.state in ["listening", "thinking"]:
            # Attentive sitting pose
            self.cat_pose = "sit"
            self.update()
            return

        # Chase mouse if enabled
        if self.mouse_chase_enabled and self.state == "idle":
            mouse_pos = QCursor.pos()
            dx = mouse_pos.x() - (self.x() + self.width() / 2)
            dy = mouse_pos.y() - (self.y() + self.height() / 2)
            dist = math.hypot(dx, dy)
            if dist > 60:
                step = 4.0
                self.move(int(self.x() + step * (dx / dist)), int(self.y() + step * (dy / dist)))
                self.facing_left = (dx < 0)
                self.cat_pose = "walk"
                self.walk_cycle = (self.walk_cycle + 0.25) % (2 * math.pi)
            else:
                self.cat_pose = "sit"
            self.align_overlays()
            self.update()
            return

        # Random behavior loop when idle
        if self.random_walk_enabled and self.state == "idle":
            self.behavior_timer += 1
            if self.behavior_timer >= random.randint(150, 300): # Choose a new behavior every 7.5 - 15 seconds
                self.behavior_timer = 0
                
                # Stateful behavior transition between walk and sit only
                if self.current_behavior == "walk":
                    # If walking: 55% chance to continue same direction, 15% to turn around, 30% to sit
                    roll = random.random()
                    if roll < 0.55:
                        self.current_behavior = "walk"
                    elif roll < 0.70:
                        self.current_behavior = "walk"
                        self.walk_direction = -self.walk_direction # Turn around
                    else:
                        self.current_behavior = "sit"
                else:
                    # If sitting: 80% chance to walk, 20% chance to stay sitting
                    roll = random.random()
                    if roll < 0.80:
                        self.current_behavior = "walk"
                        self.walk_direction = random.choice([1, -1])
                    else:
                        self.current_behavior = "sit"

            if self.current_behavior == "walk":
                new_x = self.x() + self.walk_direction * 2.5
                if new_x < 10:
                    new_x = 10
                    self.walk_direction = 1
                elif new_x > screen.width() - self.width() - 10:
                    new_x = screen.width() - self.width() - 10
                    self.walk_direction = -1
                self.move(new_x, self.y())
                self.facing_left = (self.walk_direction == -1)
                self.cat_pose = "walk"
                self.walk_cycle = (self.walk_cycle + 0.26) % (2 * math.pi)
            else:
                self.cat_pose = "sit"

        self.align_overlays()
        self.update()

        # Optimize tick interval based on activity to save CPU/GPU resource usage
        active_states = ["listening", "thinking", "speaking", "happy", "sad", "angry"]
        needs_fast_tick = (
            self.state in active_states or 
            self.is_falling or 
            self.is_dragging or 
            self.cat_pose in ["walk", "fall", "drag"] or
            (self.mouse_chase_enabled and self.state == "idle")
        )
        if needs_fast_tick:
            if self.tick_timer.interval() != 50:
                self.tick_timer.setInterval(50)
        else:
            if self.tick_timer.interval() != 200:
                self.tick_timer.setInterval(200)

    def is_currently_speaking(self):
        try:
            if tts_engine.is_speaking():
                return True
        except Exception:
            pass

        try:
            import pygame
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                return True
        except Exception:
            pass
            
        try:
            voice = get_main_sapi_voice()
            if voice and voice.Status.RunningState == 2:
                return True
        except Exception:
            pass

        if hasattr(self, 'backend_thread') and self.backend_thread:
            if not self.backend_thread.speech_queue.empty() or not self.backend_thread.audio_queue.empty():
                return True
            
        return self.state in ["speaking", "thinking", "happy", "sad", "angry"]

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # If the assistant is speaking/playing audio, interrupt it!
            if self.is_currently_speaking():
                self.interrupt_speech()
                event.accept()
                return

            self.is_dragging = True
            self.is_falling = False
            self.cat_pose = "drag"
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.update()
            event.accept()

    def keyPressEvent(self, event):
        if event.key() in [Qt.Key_Escape, Qt.Key_Space]:
            if self.is_currently_speaking():
                self.interrupt_speech()
                event.accept()
                return
        super().keyPressEvent(event)

    def interrupt_speech(self):
        # 1. Stop hardware audio playback immediately
        try:
            tts_engine.stop()
        except Exception as e:
            print(f"[INTERRUPT TTS STOP ERROR]: {e}", flush=True)

        # 2. Stop SAPI voice directly if active
        try:
            voice = get_main_sapi_voice()
            if voice:
                voice.Speak("", 2) # Purge speech queue
        except Exception as e:
            print(f"[INTERRUPT MAIN ERROR]: {e}", flush=True)
            
        # 3. Call backend thread's clear_speech to clear queues and cancel workers
        try:
            if hasattr(self, 'backend_thread') and self.backend_thread:
                self.backend_thread.clear_speech()
        except Exception as e:
            print(f"[INTERRUPT BACKEND ERROR]: {e}", flush=True)
            
        # 4. Reset state back to listening so user can speak immediately
        active = getattr(self.backend_thread, "active_mode", True) if hasattr(self, 'backend_thread') and self.backend_thread else True
        self.set_state("listening" if active else "idle")


    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.is_dragging:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            self.align_overlays()
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            self.is_falling = True
            self.cat_pose = "fall"
            self.y_vel = 0.0
            self.update()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.trigger_emotion("happy", 2)
            self.backend_thread.active_mode = True
            flask_app.active_mode = True
            speak_async("How may I help?")
            event.accept()

    def enterEvent(self, event):
        if self.state == "idle":
            self.trigger_emotion("happy", 1)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(15, 23, 42, 0.95);
                color: #e2e8f0;
                border: 1px solid rgba(0, 229, 255, 0.3);
                border-radius: 8px;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QMenu::item { padding: 8px 24px; }
            QMenu::item:selected { background-color: rgba(0, 229, 255, 0.15); color: #00e5ff; }
        """)

        dashboard_action = QAction("Open Dashboard", self)
        dashboard_action.triggered.connect(self.toggle_launcher)

        # Add Active Model Select options directly in context menu
        model_menu = menu.addMenu("Active Model")
        config = memory_manager.load_config()
        active_model = config.get("selected_model", "groq")

        groq_action = QAction("Groq (Ultra-Fast Cloud)", self)
        groq_action.setCheckable(True)
        groq_action.setChecked(active_model == "groq")
        groq_action.triggered.connect(lambda: self.switch_model_to("groq"))

        gemini_action = QAction("Gemini 2.0 Flash (Cloud)", self)
        gemini_action.setCheckable(True)
        gemini_action.setChecked(active_model == "gemini")
        gemini_action.triggered.connect(lambda: self.switch_model_to("gemini"))

        nvidia_action = QAction("Nvidia NIM (Cloud)", self)
        nvidia_action.setCheckable(True)
        nvidia_action.setChecked(active_model == "nvidia")
        nvidia_action.triggered.connect(lambda: self.switch_model_to("nvidia"))

        openrouter_action = QAction("OpenRouter (Cloud)", self)
        openrouter_action.setCheckable(True)
        openrouter_action.setChecked(active_model == "openrouter")
        openrouter_action.triggered.connect(lambda: self.switch_model_to("openrouter"))

        model_menu.addAction(groq_action)
        model_menu.addAction(gemini_action)
        model_menu.addAction(nvidia_action)
        model_menu.addAction(openrouter_action)

        voice_action = QAction("Toggle Voice Mode", self)
        voice_action.triggered.connect(self.toggle_voice_mode)

        mouse_action = QAction("Chase Mouse Pointer" if not self.mouse_chase_enabled else "Walk Randomly", self)
        mouse_action.triggered.connect(self.toggle_mouse_chasing)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.exit_app)

        menu.addAction(dashboard_action)
        menu.addSeparator()
        menu.addAction(voice_action)
        menu.addAction(mouse_action)
        menu.addSeparator()
        menu.addAction(exit_action)

        menu.exec(event.globalPos())

    def switch_model_to(self, model_name):
        config = memory_manager.load_config()
        memory_manager.save_config(model_name, config["gemini_api_key"], config["groq_api_key"], config.get("nvidia_api_key"), config.get("openrouter_api_key"))
        speak_async(f"Model configured to {model_name}, Boss.")

    def toggle_voice_mode(self):
        self.backend_thread.active_mode = not self.backend_thread.active_mode
        flask_app.active_mode = self.backend_thread.active_mode
        state_str = "Active" if self.backend_thread.active_mode else "Inactive"
        self.trigger_emotion("happy", 2)
        speak_async(f"Voice Mode is now {state_str}, Boss.")

    def toggle_mouse_chasing(self):
        self.mouse_chase_enabled = not self.mouse_chase_enabled
        self.random_walk_enabled = not self.mouse_chase_enabled
        status = "enabled" if self.mouse_chase_enabled else "disabled"
        speak_async(f"Mouse chasing {status}.")

    def check_prices_in_background(self):
        def run_check():
            try:
                import internet_agent
                alerts = internet_agent.check_tracker_prices()
                for alert in alerts:
                    currency = "Rs." if "flipkart" in alert['url'].lower() or ".in" in alert['url'].lower() or "amazon.in" in alert['url'].lower() else "$"
                    speak_async(f"Alert, Boss! The price of {alert['name']} has dropped to {currency}{alert['price']:,.2f}, which is below your threshold of {currency}{alert['threshold']:,.2f}!")
            except Exception as e:
                print(f"[DAEMON CHECK ERROR]: {e}")
        threading.Thread(target=run_check, daemon=True).start()

    def exit_app(self):
        print("[EXIT] Snappy shutdown initiated...")
        try:
            if hasattr(self, 'screen_memory_daemon') and self.screen_memory_daemon:
                self.screen_memory_daemon.running = False
        except Exception as e:
            print(f"[EXIT WARNING] Screen memory daemon exit: {e}")
            
        try:
            if hasattr(self, 'hotkey_thread') and self.hotkey_thread:
                self.hotkey_thread.running = False
                # Post WM_NULL (0) to wake up GetMessageW loop
                ctypes.windll.user32.PostThreadMessageW(self.hotkey_thread.thread_id, 0, 0, 0)
                self.hotkey_thread.wait(500) # wait max 500ms
        except Exception as e:
            print(f"[EXIT WARNING] Hotkey exit: {e}")
            
        try:
            if hasattr(self, 'backend_thread') and self.backend_thread:
                self.backend_thread.running = False
                self.backend_thread.wait(500) # wait max 500ms
        except Exception as e:
            print(f"[EXIT WARNING] Backend exit: {e}")

            
        # Perform OS-level hard-exit to bypass any other hanging daemon threads (Kokoro ONNX, audio streams, Flask, etc.)
        import os
        os._exit(0)

# --- MAIN EXECUTION ---




