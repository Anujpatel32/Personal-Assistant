import sys
import ctypes
from ctypes import wintypes
import win32con
from PySide6.QtCore import Qt, QThread, Signal, QUrl, QEvent
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtWebEngineWidgets import QWebEngineView

import logging
logger = logging.getLogger("meow.core")


class GlobalHotkeyThread(QThread):
    """Listens for system-wide hotkey (Ctrl+Alt+M or fallback) using Windows API."""
    hotkey_pressed = Signal()

    def __init__(self):
        super().__init__()
        self.running = True
        self.thread_id = 0
        self.active_hotkey_str = "Ctrl+Alt+M"

    def run(self):
        import time as _time
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        MOD_NOREPEAT = 0x4000
        ctrl_alt = win32con.MOD_CONTROL | win32con.MOD_ALT | MOD_NOREPEAT
        ctrl_shift = win32con.MOD_CONTROL | win32con.MOD_SHIFT | MOD_NOREPEAT

        # Candidates: Ctrl+Alt+M (primary, M for Meow), Ctrl+Shift+M, Ctrl+Alt+Space
        candidates = [
            (ctrl_alt, ord('M'), "Ctrl+Alt+M"),
            (ctrl_shift, ord('M'), "Ctrl+Shift+M"),
            (ctrl_alt, win32con.VK_SPACE, "Ctrl+Alt+Space")
        ]

        registered = False
        for mods, vk, name in candidates:
            result = ctypes.windll.user32.RegisterHotKey(None, 1, mods, vk)
            if result:
                registered = True
                self.active_hotkey_str = name
                logger.info(f"[HOTKEY] {name} registered successfully as global assistant hotkey.")
                break
            else:
                err = ctypes.windll.kernel32.GetLastError()
                logger.error(f"[HOTKEY] {name} registration failed (error {err}). Trying next candidate...")
        if not registered:
            logger.info("[HOTKEY] Could not register global launcher hotkey — all candidates in use.")
            return

        msg = wintypes.MSG()
        try:
            while self.running:
                if ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == win32con.WM_HOTKEY:
                        self.hotkey_pressed.emit()
                    ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                    ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            logger.error(f"[HOTKEY ERROR] Thread crashed: {e}")
        finally:
            ctypes.windll.user32.UnregisterHotKey(None, 1)

class MeowStudioLauncher(QWidget):
    """Translucent glassmorphic control center dashboard loading index.html via QWebEngineView."""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(1100, 680)
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.web_view = QWebEngineView(self)
        self.web_view.setContextMenuPolicy(Qt.NoContextMenu)
        
        # Enable transparent page background rendering
        self.web_view.setStyleSheet("background: transparent;")
        self.web_view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.web_view.page().setBackgroundColor(Qt.transparent)
        
        # Load local Flask web dashboard
        self.web_view.load(QUrl("http://127.0.0.1:5005/"))
        layout.addWidget(self.web_view)

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange:
            if not self.isActiveWindow():
                self.hide()
        super().changeEvent(event)

    def refresh_tasks(self):
        # Kept for compatibility with test runner checks
        pass