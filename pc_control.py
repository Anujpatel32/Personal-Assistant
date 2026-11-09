import os
import re
import ctypes
import subprocess
import time
import pyautogui
import pygetwindow as gw

def get_desktop_path():
    """Returns the true, active Windows Desktop path (OneDrive-aware and registry-verified)."""
    # 1. Primary source of truth: Windows Shell registry (where Windows Explorer actually renders the desktop)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        )
        val, _ = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        reg_path = os.path.expandvars(val)
        if os.path.exists(reg_path) and os.access(reg_path, os.W_OK):
            return reg_path
    except Exception:
        pass

    # 2. Check OneDrive Desktop (common on Windows 10/11)
    user_home = os.path.expanduser("~")
    onedrive_desktop = os.path.join(user_home, "OneDrive", "Desktop")
    if os.path.exists(onedrive_desktop) and os.access(onedrive_desktop, os.W_OK):
        return onedrive_desktop

    # 3. Check standard User Desktop
    local_desktop = os.path.join(user_home, "Desktop")
    if os.path.exists(local_desktop) and os.access(local_desktop, os.W_OK):
        return local_desktop

    return onedrive_desktop if os.path.exists(onedrive_desktop) else local_desktop

def ensure_dirs():
    pass

def lock_pc():
    try:
        ctypes.windll.user32.LockWorkStation()
        return "Locking your workstation, Boss."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Lock failed: {e}")
        return "I was unable to lock your PC."

def take_screenshot():
    try:
        desktop_path = get_desktop_path()
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        filepath = os.path.join(desktop_path, filename)
        
        # Take screenshot via PyAutoGUI
        pyautogui.screenshot(filepath)
        
        # Open it instantly in Windows default viewer for active feedback
        if os.path.exists(filepath):
            os.startfile(filepath)
            return f"I have taken a screenshot and saved it to your desktop as {filename}."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Screenshot failed: {e}")
    return "I was unable to capture your screen."

def adjust_volume(action):
    try:
        if action == "mute":
            pyautogui.press("volumemute")
            return "Toggling mute state."
        elif action == "up":
            # Press volumeup key 5 times (increases volume by 10%)
            for _ in range(5):
                pyautogui.press("volumeup")
            return "Increasing volume, Boss."
        elif action == "down":
            # Press volumedown key 5 times (decreases volume by 10%)
            for _ in range(5):
                pyautogui.press("volumedown")
            return "Decreasing volume, Boss."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Volume failed: {e}")
    return "I was unable to adjust the volume."

def set_volume_percentage(level):
    try:
        level = max(0, min(100, int(level)))
        ps_code = f"""
Add-Type -TypeDefinition '
using System;
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {{
    int f(); int g(); int h(); int i();
    int SetMasterVolumeLevelScalar(float fLevel, Guid pguidEventContext);
    int j(); int GetMasterVolumeLevelScalar(out float pfLevel);
}}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {{ int Activate(ref Guid id, int clsCtx, int activationParams, out IAudioEndpointVolume aev); }}
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {{ int f(); int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint); }}
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject {{ }}
public class Audio {{
    public static void SetVolume(float level) {{
        var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
        IMMDevice dev = null;
        enumerator.GetDefaultAudioEndpoint(0, 1, out dev);
        IAudioEndpointVolume epv = null;
        var epvid = typeof(IAudioEndpointVolume).GUID;
        dev.Activate(ref epvid, 23, 0, out epv);
        epv.SetMasterVolumeLevelScalar(level / 100f, Guid.Empty);
    }}
}}
'; [Audio]::SetVolume({level})
"""
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run(["powershell", "-Command", ps_code], creationflags=creationflags, timeout=5)
        return f"Setting system volume to {level} percent, Boss."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Set volume failed: {e}")
        return "I was unable to adjust the system volume to that level."

def get_brightness():
    cmd = "powershell -Command \"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness\""
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        res = subprocess.run(cmd, shell=True, creationflags=creationflags, stdout=subprocess.PIPE, text=True, timeout=3)
        val = res.stdout.strip()
        if val:
            return int(val)
    except Exception:
        pass
    return 50

def set_brightness(level):
    try:
        level = max(0, min(100, int(level)))
        cmd = f"powershell -Command \"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {level})\""
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run(cmd, shell=True, creationflags=creationflags, timeout=4)
        return f"Setting screen brightness to {level} percent, Boss."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Brightness set failed: {e}")
        return "I couldn't adjust your screen brightness. This feature is typically only supported on laptops."

def adjust_brightness(action, val=None):
    if val is not None:
        return set_brightness(val)
    
    current = get_brightness()
    if action == "up":
        return set_brightness(current + 10)
    elif action == "down":
        return set_brightness(current - 10)
    return "Invalid brightness action."

def control_window(action):
    try:
        import os, win32process
        my_pid = os.getpid()
        active_window = gw.getActiveWindow()
        if active_window:
            try:
                if hasattr(active_window, '_hWnd') and active_window._hWnd:
                    _, win_pid = win32process.GetWindowThreadProcessId(active_window._hWnd)
                    if win_pid == my_pid:
                        active_window = None  # Don't manipulate our own mascot window!
            except Exception:
                pass

        if not active_window:
            # Fallback to key simulation if Window object failed
            if action == "close":
                pyautogui.hotkey("alt", "f4")
                return "Closing the active window."
            return "No target active window detected."
            
        title = active_window.title or "window"
        if len(title) > 25:
            title = title[:22] + "..."
            
        if action == "close":
            active_window.close()
            return f"Closing window: {title}."
        elif action == "minimize":
            active_window.minimize()
            return f"Minimizing window: {title}."
        elif action == "maximize":
            active_window.maximize()
            return f"Maximizing window: {title}."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Window control failed: {e}")
        # fallback Alt+F4 for close
        if action == "close":
            pyautogui.hotkey("alt", "f4")
            return "Closing active window."
    return "I was unable to modify the active window."

def control_named_window(action: str, app_name: str) -> str:
    """Switch to a named window then perform action (minimize/maximize/close)."""
    import win32gui, win32con, ctypes, time
    try:
        # Re-use scored switch logic to find the hwnd
        import pc_control as _self
        windows = list_open_windows()
        name_raw = app_name.strip().lower()
        name_nospace = name_raw.replace(" ", "")
        _BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe"}

        def _score(w):
            s = 0
            proc = w["process"].lower()
            proc_ns = proc.replace(" ", "").replace(".exe", "")
            title = w["title"].lower()
            title_ns = title.replace(" ", "")
            if name_nospace == proc_ns: s += 50
            elif name_nospace in proc_ns: s += 40
            if title.startswith(name_raw) or title_ns.startswith(name_nospace): s += 20
            elif name_raw in title or name_nospace in title_ns: s += 10
            if proc in _BROWSERS: s -= 15
            return s

        scored = sorted([(w, _score(w)) for w in windows], key=lambda x: x[1], reverse=True)
        if not scored or scored[0][1] < 5:
            return f"I couldn't find a window matching '{app_name}'."
        hwnd = scored[0][0]["hwnd"]
        title = scored[0][0]["title"][:30]

        if action == "minimize":
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            return f"Minimised {title}."
        elif action == "maximize":
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(-1)
                ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            return f"Maximised {title}."
        elif action == "close":
            win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # WM_CLOSE
            return f"Closing {title}."
        return "Unknown action."
    except Exception as e:
        print(f"[PC CONTROL] control_named_window error: {e}")
        return f"I ran into an issue performing '{action}' on '{app_name}'."

# ═══════════════════════════════════════════════════════════
# WINDOW MANAGER — Phase 4
# ═══════════════════════════════════════════════════════════

def list_open_windows():
    """Return a list of visible window dicts: {title, pid}."""
    try:
        import win32gui, win32process, psutil, os
        my_pid = os.getpid()
        results = []
        def _enum(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                if len(title) < 3:
                    return
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if pid == my_pid:
                        return  # Ignore assistant mascot/overlay window
                    proc = psutil.Process(pid)
                    results.append({"title": title, "process": proc.name(), "pid": pid, "hwnd": hwnd})
                except Exception:
                    results.append({"title": title, "process": "unknown", "pid": 0, "hwnd": hwnd})
        win32gui.EnumWindows(_enum, None)
        # Deduplicate by title
        seen = set()
        unique = []
        for r in results:
            if r["title"] not in seen:
                seen.add(r["title"])
                unique.append(r)
        return unique
    except Exception as e:
        print(f"[WINDOW MANAGER] list_open_windows error: {e}")
        return []

def switch_to_window(app_name: str) -> str:
    """Bring the best-matching window to the foreground using scored ranking."""
    try:
        import win32gui
        import win32con
        import ctypes
        import time

        name_raw     = app_name.strip().lower()
        name_nospace = name_raw.replace(" ", "")
        windows      = list_open_windows()

        # ── Score every visible window ──────────────────────────────────────
        # Higher score = better match. Browser-tab windows are penalised so
        # a Chrome tab "Google Antigravity Auth…" loses to "Antigravity.exe".
        _BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "opera.exe",
                     "brave.exe", "vivaldi.exe"}

        def _score(w):
            s = 0
            proc  = w["process"].lower()
            proc_ns = proc.replace(" ", "").replace(".exe", "")
            title = w["title"].lower()
            title_ns = title.replace(" ", "")

            # Process name hits are the strongest signal (it's the actual app)
            if name_nospace == proc_ns or name_raw == proc.replace(".exe",""):
                s += 50
            elif name_nospace in proc_ns or name_raw in proc:
                s += 40

            # Title starts with search term (very specific)
            if title.startswith(name_raw) or title_ns.startswith(name_nospace):
                s += 20
            # Title contains search term
            elif name_raw in title or name_nospace in title_ns:
                s += 10

            # Penalise browser windows — tab titles often contain random words
            if proc in _BROWSERS:
                s -= 15

            return s

        scored = [(w, _score(w)) for w in windows]
        scored.sort(key=lambda x: x[1], reverse=True)

        # Require at least a score of 5 to avoid wild mismatches
        if not scored or scored[0][1] < 5:
            return f"I couldn't find a window matching '{app_name}'. Is it open?"

        match = scored[0][0]
        hwnd  = match["hwnd"]

        # ── Windows foreground-lock bypass ──────────────────────────────────
        ctypes.windll.user32.AllowSetForegroundWindow(ctypes.wintypes.DWORD(-1))
        pyautogui.keyDown('alt')
        time.sleep(0.05)
        pyautogui.keyUp('alt')
        time.sleep(0.05)
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.05)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.1)

        return f"Switched to {match['title']}."
    except Exception as e:
        print(f"[WINDOW MANAGER] switch_to_window error: {e}")
        return f"I ran into an issue switching to '{app_name}'."

def enable_focus_mode() -> str:
    """Minimize all windows except the current foreground window, enable DND."""
    try:
        import win32gui
        import automation_control
        foreground = win32gui.GetForegroundWindow()
        def _minimize(hwnd, _):
            if hwnd != foreground and win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                win32gui.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        win32gui.EnumWindows(_minimize, None)
        automation_control.toggle_dnd(True)
        return "Focus mode on! All other windows minimized and notifications silenced."
    except Exception as e:
        print(f"[WINDOW MANAGER] enable_focus_mode error: {e}")
        return "I ran into an issue enabling focus mode."

def disable_focus_mode() -> str:
    """Restore all minimized windows, disable DND."""
    try:
        import automation_control
        automation_control.toggle_dnd(False)
        return "Focus mode off — notifications restored."
    except Exception as e:
        return "Focus mode disabled."

def snap_window(direction: str) -> str:
    """Snap active window left or right using Win+Arrow."""
    try:
        key = "left" if "left" in direction.lower() else "right"
        pyautogui.hotkey("win", key)
        return f"Window snapped to the {key}."
    except Exception as e:
        print(f"[WINDOW MANAGER] snap error: {e}")
        return "Could not snap the window."

def close_app_by_name(app_name: str) -> str:
    """Close a window (and its process) by title match or active target."""
    try:
        name_clean = app_name.strip().lower()
        if name_clean in {"this app", "this", "active app", "active window", "current app", "current window", "window", "it"}:
            return control_window("close")

        app_aliases = {
            "vs code": ["vscode", "code.exe", "code", "visual studio code", "antigravity"],
            "vscode": ["vscode", "code.exe", "code", "visual studio code", "antigravity"],
            "visual studio code": ["vscode", "code.exe", "code", "visual studio code", "antigravity"],
            "code": ["vscode", "code.exe", "code", "visual studio code", "antigravity"],
            "antigravity": ["antigravity ide", "antigravity"],
            "browser": ["chrome", "edge", "msedge", "firefox", "browser", "brave", "opera"],
            "calculator": ["calculator", "calc"],
            "cmd": ["cmd", "command prompt", "terminal"],
            "terminal": ["cmd", "powershell", "terminal", "wt"]
        }

        search_terms = app_aliases.get(name_clean, [name_clean])

        import win32gui
        windows = list_open_windows()
        match = None
        for w in windows:
            title_l = w["title"].lower()
            proc_l = w["process"].lower()
            if any(term in title_l or term in proc_l for term in search_terms):
                match = w
                break

        if not match:
            return f"I couldn't find an open window or app matching '{app_name}'."

        win32gui.PostMessage(match["hwnd"], 0x0010, 0, 0)  # WM_CLOSE
        return f"Closing {match['title']}."
    except Exception as e:
        print(f"[WINDOW MANAGER] close_app_by_name error: {e}")
        return f"I ran into an issue closing '{app_name}'."

# ═══════════════════════════════════════════════════════════

def open_system_or_named_folder(folder_name: str) -> str:
    """Open standard system folder or search and open a named folder in Windows Explorer."""
    try:
        user_home = os.path.expanduser("~")
        clean_name = folder_name.strip().lower()
        clean_name = re.sub(r'^(?:the|my|a|an)\s+', '', clean_name)
        clean_name = re.sub(r'\s+folder$', '', clean_name).strip()
        
        system_folders = {
            "downloads": os.path.join(user_home, "Downloads"),
            "download": os.path.join(user_home, "Downloads"),
            "documents": os.path.join(user_home, "Documents"),
            "document": os.path.join(user_home, "Documents"),
            "desktop": get_desktop_path(),
            "pictures": os.path.join(user_home, "Pictures"),
            "photos": os.path.join(user_home, "Pictures"),
            "images": os.path.join(user_home, "Pictures"),
            "videos": os.path.join(user_home, "Videos"),
            "movies": os.path.join(user_home, "Videos"),
            "music": os.path.join(user_home, "Music"),
            "songs": os.path.join(user_home, "Music"),
            "c drive": "C:\\",
            "c:": "C:\\",
            "home": user_home,
            "user": user_home,
        }
        
        if clean_name in system_folders:
            target_path = system_folders[clean_name]
            if os.path.exists(target_path):
                os.startfile(target_path)
                return f"Opening your {clean_name.capitalize()} folder."

        # Search for folder across user locations
        scan_paths = [
            get_desktop_path(),
            os.path.join(user_home, "Downloads"),
            os.path.join(user_home, "Documents"),
            os.path.join(user_home, "Pictures"),
            os.path.join(user_home, "Videos"),
            os.path.join(user_home, "Music"),
            user_home
        ]
        
        clean_target = re.sub(r'[^a-zA-Z0-9\s]', ' ', clean_name).lower()
        query_words = clean_target.split()
        if not query_words:
            return "Please specify a folder name to open."
            
        for base_dir in scan_paths:
            if not os.path.exists(base_dir):
                continue
            for root, dirs, _ in os.walk(base_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in {"appdata", "node_modules", "venv", "llama_env"}]
                for d in dirs:
                    d_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', d).lower()
                    if all(word in d_clean for word in query_words):
                        found_path = os.path.join(root, d)
                        os.startfile(found_path)
                        return f"Opening folder '{d}' in File Explorer."
                rel_depth = len(os.path.relpath(root, base_dir).split(os.sep))
                if rel_depth >= 3:
                    dirs.clear()

        return f"I couldn't find a folder named '{folder_name}' on your PC."
    except Exception as e:
        print(f"[PC CONTROL] open_system_or_named_folder error: {e}")
        return f"I ran into an issue opening the folder '{folder_name}'."

def open_named_file(file_name: str) -> str:
    """Search and open a file matching file_name with default application."""
    try:
        user_home = os.path.expanduser("~")
        clean_name = file_name.strip().lower()
        clean_name = re.sub(r'^(?:the|my|a|an)\s+', '', clean_name)
        clean_name = re.sub(r'\s+file$', '', clean_name).strip()
        
        scan_paths = [
            get_desktop_path(),
            os.path.join(user_home, "Downloads"),
            os.path.join(user_home, "Documents"),
            os.path.join(user_home, "Pictures"),
            os.path.join(user_home, "Videos"),
            os.path.join(user_home, "Music"),
            user_home
        ]
        
        clean_query = re.sub(r'[^a-zA-Z0-9\s]', ' ', clean_name).lower()
        query_words = clean_query.split()
        if not query_words:
            return "Please specify a file name to open."
            
        for base_dir in scan_paths:
            if not os.path.exists(base_dir):
                continue
            for root, dirs, files in os.walk(base_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in {"appdata", "node_modules", "venv", "llama_env"}]
                for file in files:
                    file_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', file).lower()
                    if all(word in file_clean for word in query_words):
                        found_path = os.path.join(root, file)
                        os.startfile(found_path)
                        return f"Opening file '{file}'."
                rel_depth = len(os.path.relpath(root, base_dir).split(os.sep))
                if rel_depth >= 3:
                    dirs.clear()

        return f"I couldn't find a file matching '{file_name}' on your PC."
    except Exception as e:
        print(f"[PC CONTROL] open_named_file error: {e}")
        return f"I ran into an issue opening the file '{file_name}'."

def delete_named_folder(folder_name: str) -> str:
    """Find a folder/project matching folder_name and move it to the Windows Recycle Bin or delete it."""
    try:
        user_home = os.path.expanduser("~")
        raw_name = folder_name.strip()
        sanitized = re.sub(r'[\\/*?:"<>|]', "", raw_name).strip()
        clean_name = re.sub(r'^(?:the|my|a|an|folder|project|directory|workspace|app)\s+', '', sanitized.lower())
        clean_name = re.sub(r'\s+(?:folder|project|directory|workspace|app)$', '', clean_name).strip()

        if not clean_name:
            return "Please specify a project or folder name to delete."

        scan_paths = [
            r"C:\Users\anujp\OneDrive\Desktop\P Space\Meow",
            get_desktop_path(),
            os.path.join(user_home, "Downloads"),
            os.path.join(user_home, "Documents"),
            os.path.join(user_home, "Pictures"),
            user_home
        ]

        target_dir_path = None
        target_dir_name = None

        clean_query = re.sub(r'[^a-zA-Z0-9\s]', ' ', clean_name).lower()
        query_words = clean_query.split()

        for base_dir in scan_paths:
            if not os.path.exists(base_dir):
                continue
            for item in os.listdir(base_dir):
                full = os.path.join(base_dir, item)
                if os.path.isdir(full):
                    item_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', item).lower()
                    if item_clean == clean_name or (query_words and all(w in item_clean for w in query_words)):
                        target_dir_path = full
                        target_dir_name = item
                        break
            if target_dir_path:
                break
                
            for root, dirs, _ in os.walk(base_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in {"appdata", "node_modules", "venv", "llama_env"}]
                for d in dirs:
                    d_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', d).lower()
                    if d_clean == clean_name or (query_words and all(w in d_clean for w in query_words)):
                        target_dir_path = os.path.join(root, d)
                        target_dir_name = d
                        break
                if target_dir_path:
                    break
                rel_depth = len(os.path.relpath(root, base_dir).split(os.sep))
                if rel_depth >= 3:
                    dirs.clear()
            if target_dir_path:
                break

        if not target_dir_path:
            return f"I couldn't find a project or folder named '{folder_name}' to delete."

        escaped_path = target_dir_path.replace("'", "''")
        ps_cmd = f'Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(\'{escaped_path}\', \'OnlyErrorDialogs\', \'SendToRecycleBin\')'
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        res = subprocess.run(["powershell", "-Command", ps_cmd], creationflags=creationflags, timeout=6)

        if res.returncode == 0 and not os.path.exists(target_dir_path):
            return f"I have moved the project '{target_dir_name}' to your Recycle Bin."
        else:
            import shutil
            shutil.rmtree(target_dir_path, ignore_errors=True)
            return f"I have deleted the project '{target_dir_name}'."
    except Exception as e:
        print(f"[PC CONTROL] delete_named_folder error: {e}")
        return f"I ran into an issue deleting '{folder_name}': {e}"

def delete_named_file(file_name: str) -> str:
    """Find a file matching file_name and move it to the Windows Recycle Bin."""
    try:
        user_home = os.path.expanduser("~")
        raw_name = file_name.strip()
        sanitized = re.sub(r'[\\/*?:"<>|]', "", raw_name).strip()
        clean_name = re.sub(r'^(?:the|my|a|an|file)\s+', '', sanitized.lower())
        clean_name = re.sub(r'\s+file$', '', clean_name).strip()

        if not clean_name:
            return "Please specify a file name to delete."

        scan_paths = [
            r"C:\Users\anujp\OneDrive\Desktop\P Space\Meow",
            get_desktop_path(),
            os.path.join(user_home, "Downloads"),
            os.path.join(user_home, "Documents"),
            os.path.join(user_home, "Pictures"),
            user_home
        ]

        target_file_path = None
        target_file_name = None

        clean_query = re.sub(r'[^a-zA-Z0-9\s]', ' ', clean_name).lower()
        query_words = clean_query.split()

        for base_dir in scan_paths:
            if not os.path.exists(base_dir):
                continue
            for root, dirs, files in os.walk(base_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d.lower() not in {"appdata", "node_modules", "venv", "llama_env"}]
                for file in files:
                    file_clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', file).lower()
                    if file_clean == clean_name or (query_words and all(w in file_clean for w in query_words)):
                        target_file_path = os.path.join(root, file)
                        target_file_name = file
                        break
                if target_file_path:
                    break
                rel_depth = len(os.path.relpath(root, base_dir).split(os.sep))
                if rel_depth >= 3:
                    dirs.clear()
            if target_file_path:
                break

        if not target_file_path:
            return f"I couldn't find a file named '{file_name}' to delete."

        escaped_path = target_file_path.replace("'", "''")
        ps_cmd = f'Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(\'{escaped_path}\', \'OnlyErrorDialogs\', \'SendToRecycleBin\')'
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        res = subprocess.run(["powershell", "-Command", ps_cmd], creationflags=creationflags, timeout=6)

        if res.returncode == 0 and not os.path.exists(target_file_path):
            return f"I have moved the file '{target_file_name}' to your Recycle Bin."
        else:
            os.remove(target_file_path)
            return f"I have deleted the file '{target_file_name}'."
    except Exception as e:
        print(f"[PC CONTROL] delete_named_file error: {e}")
        return f"I ran into an issue deleting the file '{file_name}': {e}"

# ═══════════════════════════════════════════════════════════

def parse_folder_name_from_command(cmd_clean):
    """Extract folder name from natural language command like 'create a folder named anuj on the desktop'."""
    cmd_lower = cmd_clean.strip().lower()

    # Check if this command is asking to create a folder
    has_action = any(kw in cmd_lower for kw in [
        "create folder", "create a folder", "create new folder", "create a new folder",
        "make folder", "make a folder", "make new folder", "make a new folder",
        "build folder", "build a folder", "add folder", "add a folder",
        "new folder"
    ]) or bool(re.search(r"\b(create|make|build|add)\s+(?:a\s+|new\s+|a\s+new\s+)?folder\b", cmd_lower)) or bool(re.search(r"\b(create|make|build)\s+[\w\-\s]+?\s+folder\b", cmd_lower))

    if not has_action:
        return None

    # Strip desktop location phrases
    loc_removed = re.sub(r"\b(on|in|at)\s+(the\s+|my\s+)?desktop\b", "", cmd_lower).strip()

    # 1. folder named / called <name>
    m = re.search(r"\bfolder\s+(?:named|called)\s+['\"]?([^'\"]+?)['\"]?(?:\s|$)", loc_removed)
    if not m:
        # 2. named / called <name> folder
        m = re.search(r"\b(?:named|called)\s+['\"]?([^'\"]+?)['\"]?(?:\s+folder|\s|$)", loc_removed)
    if not m:
        # 3. create/make/build [a] [new] folder <name>
        m = re.search(r"(?:create|make|build|add)\s+(?:a\s+)?(?:new\s+)?folder\s+['\"]?([^'\"]+?)['\"]?$", loc_removed)
    if not m:
        # 4. create/make/build [a] [new] <name> folder
        m = re.search(r"(?:create|make|build|add)\s+(?:a\s+)?(?:new\s+)?['\"]?([^'\"]+?)['\"]?\s+folder$", loc_removed)

    if m:
        name = m.group(1).strip()
        name = re.sub(r"^(named|called)\s+", "", name).strip()
        if name and name not in ["me", "today", "schedule", "this", "it", "a", "new"]:
            return name

    return "New Folder"

def create_desktop_folder(folder_name):
    try:
        # Sanitize folder name
        folder_name = re.sub(r'[\\/*?:"<>|]', "", folder_name).strip()
        if not folder_name:
            folder_name = "New Folder"

        desktop_path = get_desktop_path()
        target_path = os.path.join(desktop_path, folder_name)

        # If folder already exists, increment if default New Folder, or report existing
        if os.path.exists(target_path):
            if folder_name.lower().startswith("new folder"):
                counter = 2
                while os.path.exists(os.path.join(desktop_path, f"{folder_name} ({counter})")):
                    counter += 1
                folder_name = f"{folder_name} ({counter})"
                target_path = os.path.join(desktop_path, folder_name)
            else:
                return f"A folder named '{folder_name}' already exists on your desktop."

        os.makedirs(target_path, exist_ok=True)

        # Notify Windows Shell so it immediately refreshes the desktop display
        try:
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x0008, 0x0005, target_path, None)
        except Exception:
            pass

        return f"I have created the folder '{folder_name}' on your desktop."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Folder creation failed: {e}")
        return f"I was unable to create the folder: {e}"

def search_local_files_advanced(query):
    query = query.strip()
    if not query:
        return "What file would you like to search for?"
        
    user_home = os.path.expanduser("~")
    paths_to_scan = [
        os.path.join(user_home, "Downloads"),
        os.path.join(user_home, "OneDrive", "Desktop"),
        os.path.join(user_home, "Desktop"),
        os.path.join(user_home, "OneDrive", "Documents"),
        os.path.join(user_home, "Documents"),
        os.path.join(user_home, "Videos"),
        os.path.join(user_home, "Music"),
        os.path.join(user_home, "Pictures")
    ]
    
    scan_paths = []
    for p in paths_to_scan:
        if os.path.exists(p) and p not in scan_paths:
            scan_paths.append(p)
    if "C:\\" not in scan_paths and os.path.exists("C:\\"):
        scan_paths.append("C:\\")
        
    import re
    clean_query = re.sub(r'[^a-zA-Z0-9\s]', ' ', query).lower()
    clean_query_words = clean_query.split()
    if not clean_query_words:
        return "Please provide search keywords."
        
    results = []
    seen_paths = set()
    
    def should_skip_dir(dir_name):
        skip_list = {
            "windows", "program files", "program files (x86)", "appdata", "programdata",
            "system volume information", "$recycle.bin", "$sysreset", "recovery", "msocache",
            "documents and settings", "intel", "amd", "nvidia", "perflogs", "common files",
            "microsoft", "package cache", "node_modules", "venv", "llama_env", ".git", ".gemini",
            "__pycache__", ".vscode", "appopener"
        }
        if dir_name.startswith('.'):
            return True
        return dir_name.lower() in skip_list
        
    def scan_dir(dir_path):
        try:
            for root, dirs, files in os.walk(dir_path):
                dirs[:] = [d for d in dirs if not should_skip_dir(d)]
                
                # 1. Scan files
                for file in files:
                    filepath = os.path.join(root, file)
                    norm_path = os.path.normpath(os.path.abspath(filepath))
                    if norm_path not in seen_paths:
                        name, ext = os.path.splitext(file)
                        clean_name = re.sub(r'[^a-zA-Z0-9\s]', ' ', name).lower()
                        if all(word in clean_name for word in clean_query_words):
                            seen_paths.add(norm_path)
                            results.append(norm_path)
                            if len(results) >= 5:
                                return
                            
                # 2. Scan folders
                for d in dirs:
                    folderpath = os.path.join(root, d)
                    norm_path = os.path.normpath(os.path.abspath(folderpath))
                    if norm_path not in seen_paths:
                        clean_d = re.sub(r'[^a-zA-Z0-9\s]', ' ', d).lower()
                        if all(word in clean_d for word in clean_query_words):
                            seen_paths.add(norm_path)
                            results.append(norm_path)
                            if len(results) >= 5:
                                return
        except Exception:
            pass
            
    for scan_path in scan_paths:
        scan_dir(scan_path)
        if len(results) >= 5:
            break
            
    if not results:
        return f"I couldn't find any files or folders matching '{query}'."
        
    lines = [f"I found the following matching files:"]
    for idx, path in enumerate(results):
        basename = os.path.basename(path)
        parent = os.path.basename(os.path.dirname(path))
        lines.append(f"{idx+1}. {basename} (in folder '{parent}')")
        
    return " ".join(lines)

def handle_pc_command(command):
    cmd_clean = command.strip().lower()
    
    # 0. Code Builder Intents (Voice-Controlled Code Generation & Execution)
    if cmd_clean in {"yes", "run it", "yes run it", "run code", "execute it", "execute code", "run the code", "execute the code", "yes please run it"}:
        try:
            import code_builder
            return code_builder.execute_last_generated_code()
        except Exception as e:
            print(f"[CODE BUILDER ROUTER ERROR]: {e}")

    # Code creation trigger detection
    code_verbs = ["create", "write", "make", "build", "generate", "develop", "code"]
    code_targets = [
        "python", "java", "javascript", "js", "html", "css", "react", "flask", 
        "django", "cpp", "c++", "csharp", "c#", "typescript", "ts", "node", 
        "script", "program", "code", "class", "app", "algorithm", "function", "api",
        "calculator", "todo", "game", "website", "webpage", "landing page", "login page"
    ]
    
    is_code_builder = False
    
    # Exclude filesystem operations like "create folder", "delete folder" unless code/script/python is mentioned
    is_fs_op = any(fs_kw in cmd_clean for fs_kw in ["folder", "directory", "file named", "delete folder", "create folder"])
    if is_fs_op and not any(k in cmd_clean for k in ["python", "script", "code", "java", "program", "app", "html", "css"]):
        is_code_builder = False
    else:
        # Check if user says verb + target (e.g., "create a calculator using python", "write python code", "make a website")
        has_verb = any(re.search(r'\b' + re.escape(v) + r'\b', cmd_clean) for v in code_verbs)
        has_target = any(re.search(r'\b' + re.escape(t) + r'\b', cmd_clean) for t in code_targets)
        
        if has_verb and has_target:
            is_code_builder = True
        elif any(phrase in cmd_clean for phrase in [
            "write a python", "write python", "write code", "write script",
            "create a python", "create python", "create a java", "create java",
            "make an html", "make html", "create an html", "create html",
            "create a react", "create react", "create a flask", "create flask",
            "generate python", "generate code", "build a python", "build python"
        ]):
            is_code_builder = True

    if is_code_builder:
        try:
            import code_builder
            return code_builder.handle_code_build_request(command)
        except Exception as e:
            print(f"[PC CONTROL] Code Builder request failed: {e}")

    # 0. Gesture Activation/Deactivation
    if any(phrase in cmd_clean for phrase in ["deactivate gesture control", "disable gesture control", "stop gesture control"]):
        try:
            import app
            success, msg = app.set_gesture_control_state(False)
            return msg
        except Exception as e:
            print(f"[PC CONTROL] Failed to deactivate gesture control: {e}")
            return "I was unable to deactivate gesture control."
            
    elif any(phrase in cmd_clean for phrase in ["activate gesture control", "enable gesture control", "start gesture control"]):
        try:
            import app
            success, msg = app.set_gesture_control_state(True)
            return msg
        except Exception as e:
            print(f"[PC CONTROL] Failed to activate gesture control: {e}")
            return "I was unable to activate gesture control."
            
    # 1. Lock Workstation
    if any(phrase in cmd_clean for phrase in ["lock my pc", "lock pc", "lock computer", "lock screen", "lock workstation"]):
        return lock_pc()
        
    # 2. Screenshot
    if any(phrase in cmd_clean for phrase in ["take screenshot", "take a screenshot", "capture screen", "screenshot screen", "screenshot my screen", "screenshot my window"]):
        return take_screenshot()
        
    # 3. Volume
    # check for set volume to X percent
    vol_match = re.search(r"volume\s+(?:to\s+)?(\d+)", cmd_clean)
    if vol_match:
        val = int(vol_match.group(1))
        # skip if relative increase/decrease command
        if not any(word in cmd_clean for word in ["up", "down", "increase", "decrease", "lower", "raise"]):
            return set_volume_percentage(val)

    if any(phrase in cmd_clean for phrase in ["mute volume", "mute computer", "mute sound", "unmute volume", "unmute computer", "mute my pc", "mute system audio", "mute audio", "unmute audio", "unmute system audio"]):
        return adjust_volume("mute")
    if any(phrase in cmd_clean for phrase in ["increase volume", "volume up", "louder", "louder please"]):
        return adjust_volume("up")
    if any(phrase in cmd_clean for phrase in ["decrease volume", "volume down", "lower volume", "lower sound"]):
        return adjust_volume("down")
        
    # 4. Brightness
    # check for set brightness to X percent
    pct_match = re.search(r"(?:set|change)\s+brightness\s+(?:to\s+)?(\d+)", cmd_clean)
    if pct_match:
        val = int(pct_match.group(1))
        return adjust_brightness("set", val)
    if any(phrase in cmd_clean for phrase in ["increase brightness", "brightness up", "brighter", "make brighter"]):
        return adjust_brightness("up")
    if any(phrase in cmd_clean for phrase in ["decrease brightness", "brightness down", "dim screen", "dim screen please"]):
        return adjust_brightness("down")
        
    # 5. Window resizing — active window AND named-app variants
    # ── Minimise ──
    _min_re = re.search(r"(?:minimize|minimise|hide)\s+(?:the\s+)?(?:window\s+)?(.+)", cmd_clean)
    if _min_re:
        target = _min_re.group(1).strip()
        if target not in {"window", "this", "it", "that", "current", "active"}:
            return control_named_window("minimize", target)
    if any(cmd_clean == phrase for phrase in [
            "minimize current window", "minimize window", "minimize active window",
            "minimise window", "minimise it", "minimise this", "minimize", "minimise"]):
        return control_window("minimize")

    # ── Maximise / Full screen ──
    # Check "open <APP> in full screen" / "<APP> in full screen" / "make <APP> full screen"
    _fs_named_re = re.search(r"(?:open|make|put|show|launch)?\s*(.+?)\s+(?:in\s+)?full\s*screen", cmd_clean)
    if _fs_named_re:
        target = _fs_named_re.group(1).strip()
        if target and target not in {"it", "this", "that", "window", "current", "active", "me", "app", "the", "in"}:
            return control_named_window("maximize", target)

    _max_re = re.search(r"(?:maximize|maximise|fullscreen|full screen)\s+(?:the\s+)?(.+)", cmd_clean)
    if _max_re:
        target = _max_re.group(1).strip()
        if target not in {"window", "this", "it", "that", "current", "active", "screen"}:
            return control_named_window("maximize", target)

    _max_triggers = {
        "maximize current window", "maximize window", "maximize active window",
        "maximise window", "maximise it", "full screen", "fullscreen",
        "open in full screen", "make it full screen", "make fullscreen",
        "open full screen", "go full screen", "maximize", "maximise"
    }
    if cmd_clean in _max_triggers:
        return control_window("maximize")

    # ── Close ──
    if any(cmd_clean == phrase for phrase in [
        "close current window", "close active window", "close window", "close",
        "close this app", "close active app", "close current app", "close this window", "close this", "close app"
    ]):
        return control_window("close")

    # 6. Project, Folder & File Deletion
    del_folder_match = re.search(r"(?:delete|remove|trash|recycle|erase)\s+(?:the\s+)?(?:folder|project|directory|workspace|app)\s+(?:named\s+)?(.+)", cmd_clean)
    if not del_folder_match:
        del_folder_match = re.search(r"(?:delete|remove|trash|recycle|erase)\s+(.+?)\s+(?:folder|project|directory|workspace|app)", cmd_clean)
    if del_folder_match:
        f_target = del_folder_match.group(1).strip()
        if f_target and f_target not in {"it", "this", "that"}:
            return delete_named_folder(f_target)

    # 6a. Explicit File Deletion
    del_file_match = re.search(r"(?:delete|remove|trash|recycle|erase)\s+(?:the\s+)?file\s+(?:named\s+)?(.+)", cmd_clean)
    if not del_file_match:
        del_file_match = re.search(r"(?:delete|remove|trash|recycle|erase)\s+(.+?)\s+file", cmd_clean)
    if del_file_match:
        f_target = del_file_match.group(1).strip()
        if f_target and f_target not in {"it", "this", "that"}:
            return delete_named_file(f_target)

    # 6a2. Fallback Generic Delete Command ("delete <name>")
    if cmd_clean.startswith(("delete ", "remove ", "trash ", "recycle ", "erase ")):
        target = cmd_clean.split(" ", 1)[1].strip()
        if target and target not in {"it", "this", "that", "all", "history", "cache", "memory", "tasks"}:
            resp = delete_named_folder(target)
            if "couldn't find" in resp.lower():
                resp_file = delete_named_file(target)
                if "couldn't find" not in resp_file.lower():
                    return resp_file
            return resp

    # 6b. Folder Creation
    detected_folder = parse_folder_name_from_command(cmd_clean)
    if detected_folder is not None:
        return create_desktop_folder(detected_folder)

    # 6c. Open System or Named Folder
    open_folder_match = re.search(r"(?:open|show|view|explore)\s+(?:the\s+)?folder\s+(?:named\s+)?(.+)", cmd_clean)
    if not open_folder_match:
        open_folder_match = re.search(r"(?:open|show|view|explore)\s+(?:the\s+)?(.+?)\s+folder", cmd_clean)
    if not open_folder_match:
        _sys_folders = {"downloads", "documents", "desktop", "pictures", "photos", "videos", "music", "c drive"}
        for sf in _sys_folders:
            if cmd_clean in {f"open {sf}", f"show {sf}", f"go to {sf}", f"open my {sf}", f"open {sf} folder"}:
                return open_system_or_named_folder(sf)
    if open_folder_match:
        f_target = open_folder_match.group(1).strip()
        if f_target and f_target not in {"this", "it"}:
            return open_system_or_named_folder(f_target)

    # 6d. Open File
    open_file_match = re.search(r"(?:open|launch|run|view|read)\s+(?:the\s+)?file\s+(?:named\s+)?(.+)", cmd_clean)
    if open_file_match:
        file_target = open_file_match.group(1).strip()
        _skip_file = {"explorer", "chrome", "vscode", "antigravity", "spotify", "window", "tab"}
        if file_target and file_target not in _skip_file:
            return open_named_file(file_target)

    # 7. File Search
    search_match = re.search(r"(?:find|search)\s+file\s+([a-zA-Z0-9_\-\s\.]+)", cmd_clean)
    if not search_match:
        search_match = re.search(r"^(?:find|search)\s+(.+)", cmd_clean)
    if search_match:
        query = search_match.group(1).strip()
        if not any(phrase in query for phrase in ["google", "web", "online", "duckduckgo", "internet", "jobs", "internships", "shortlist", "spreadsheet", "csv", "weather", "news"]):
            return search_local_files_advanced(query)
        
    # 7.1 WhatsApp Messaging
    whatsapp_match = re.search(r"(?:text|message|send message to)\s+([a-zA-Z0-9_\-\s]+)\s+(?:on|via)\s+whatsapp(?:\s+saying|\s+to)?\s+(.+)", cmd_clean)
    if not whatsapp_match:
        whatsapp_match = re.search(r"send\s+whatsapp\s+message\s+to\s+([a-zA-Z0-9_\-\s]+)\s+(?:saying|to|with)?\s+(.+)", cmd_clean)
    if whatsapp_match:
        contact = whatsapp_match.group(1).strip()
        msg_text = whatsapp_match.group(2).strip()
        return send_whatsapp_message(contact, msg_text)


        
    # 8. Editor navigation
    line_match = re.search(r"(?:jump to|go to|highlight|move to|navigate to)\s+line\s+(?:number\s+|no\.\s+)?(\d+)", cmd_clean)
    if not line_match:
        line_match = re.search(r"\bline\s+(?:number\s+)?(\d+)\b", cmd_clean)
    if line_match:
        line_num = int(line_match.group(1))
        return navigate_to_editor_line(line_num)

    # 9. Open Dashboard
    if any(phrase in cmd_clean for phrase in ["open dashboard", "open your dashboard", "show dashboard", "show my dashboard"]):
        import webbrowser
        import threading
        url = "http://127.0.0.1:5005"
        threading.Thread(target=webbrowser.open_new_tab, args=(url,), daemon=True).start()
        return "Opening your Meow Assistant dashboard in a new browser tab, Boss."

    # 10. Run Action Plan Sequence
    if any(phrase in cmd_clean for phrase in ["execute plan", "run plan", "run sequence", "execute sequence"]):
        plan_str = ""
        for keyword in ["execute plan", "run plan", "run sequence", "execute sequence"]:
            if keyword in cmd_clean:
                plan_str = command.split(keyword)[-1].strip().strip(":").strip()
                break
        if plan_str:
            steps = [s.strip() for s in re.split(r"[,;]", plan_str) if s.strip()]
            if steps:
                import action_planner
                from companion import mascot_instance
                def run_async():
                    results = action_planner.execute_plan(steps, mascot_instance)
                    if mascot_instance:
                        summary = ", ".join(results[:3])
                        if len(results) > 3:
                            summary += f", and {len(results)-3} more steps"
                        mascot_instance.backend_thread.response_generated.emit(f"[Plan Execution Summary]: {summary}.", False)
                        mascot_instance.backend_thread.speech_queue.put("Plan execution completed successfully, Boss.")
                
                import threading
                threading.Thread(target=run_async, daemon=True).start()
                return "Initializing multi-step action plan, Boss. Please watch your screen."
        
    # 11. Custom Shortcut Launchers
    if any(phrase in cmd_clean for phrase in ["open chrome", "open google chrome", "launch chrome"]):
        return open_chrome()
    if any(phrase in cmd_clean for phrase in ["open vs code", "open vscode", "launch vscode", "open visual studio code"]):
        return open_vscode()
    if any(phrase in cmd_clean for phrase in ["shutdown", "shutdown pc", "turn off computer", "shutdown computer"]):
        return shutdown_pc()
    if any(phrase in cmd_clean for phrase in ["restart", "restart pc", "reboot computer", "reboot pc"]):
        return restart_pc()
    if any(phrase in cmd_clean for phrase in ["sleep pc", "sleep computer", "put pc to sleep", "put computer to sleep", "hibernate pc"]):
        try:
            import os
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            return "Putting the computer to sleep now, Boss."
        except Exception as e:
            return f"Failed to put computer to sleep: {e}"

    # Assistant Sleep / Stand Down
    if any(phrase in cmd_clean for phrase in ["go to sleep", "sleep now", "take a nap", "stand down", "stop listening", "go offline"]) or cmd_clean in ["sleep", "offline"]:
        try:
            import app as flask_app
            flask_app.active_mode = False
        except Exception:
            pass
        return "Going to sleep, Boss. Say 'wake up' or click my mascot when you need me."

    # 12. Window Manager — switch / focus / snap / close
    switch_match = re.search(r"(?:switch to|bring up|go to|show me|take me to)\s+(.+)", cmd_clean)
    if switch_match:
        app_target = switch_match.group(1).strip()
        # Don't intercept generic open commands that other handlers already cover
        _skip = {"chrome", "vs code", "vscode", "dashboard", "camera", "gesture",
                 "whatsapp", "google", "file", "folder", "tab", "window",
                 "sleep", "bed", "rest", "offline"}
        if not any(s == app_target or s in app_target.split() for s in _skip):
            # Always return — never let the LLM fake a window switch
            return switch_to_window(app_target)

    # 12b. Bare app-name shortcut — e.g. user just says "anti gravity" or "spotify"
    # If the command is 1-3 words and not a question/greeting, try window switch.
    _NOT_APP_WORDS = {
        "what", "who", "where", "when", "why", "how", "is", "are", "can", "do",
        "does", "tell", "show", "help", "hey", "hello", "hi", "good", "okay",
        "thanks", "thank", "yes", "no", "stop", "pause", "play", "next", "prev",
        "volume", "brightness", "remind", "timer", "weather", "news", "time",
        "sleep", "offline", "nap", "awake", "wake",
    }
    words = cmd_clean.split()
    if 1 <= len(words) <= 3 and not any(w in _NOT_APP_WORDS for w in words):
        # Map common voice-recognition variants to canonical names
        _APP_ALIASES = {
            "anti gravity": "antigravity",
            "antigravity":  "antigravity",
            "anti gravity ide": "antigravity",
            "vs code":      "code",
            "vscode":       "code",
            "notepad":      "notepad",
            "spotify":      "spotify",
            "discord":      "discord",
            "telegram":     "telegram",
            "whatsapp":     "whatsapp",
            "excel":        "excel",
            "word":         "word",
            "powerpnt":     "powerpnt",
            "chrome":       "chrome",
            "edge":         "msedge",
        }
        canonical = _APP_ALIASES.get(cmd_clean, cmd_clean)
        result = switch_to_window(canonical)
        if "couldn't find" not in result:
            return result
        # Not found — let it fall through to LLM


    if any(phrase in cmd_clean for phrase in ["focus mode on", "enable focus mode", "start focus mode", "turn on focus mode"]):
        return enable_focus_mode()
    if any(phrase in cmd_clean for phrase in ["focus mode off", "disable focus mode", "end focus mode", "turn off focus mode"]):
        return disable_focus_mode()

    if any(phrase in cmd_clean for phrase in ["snap left", "snap window left", "move window left"]):
        return snap_window("left")
    if any(phrase in cmd_clean for phrase in ["snap right", "snap window right", "move window right"]):
        return snap_window("right")

    close_match = re.search(r"close\s+(.+)", cmd_clean)
    if close_match:
        app_target = close_match.group(1).strip()
        _skip_close = {"current window", "active window", "window", "this"}
        if app_target not in _skip_close:
            return close_app_by_name(app_target)

    # 12. Play Song on YouTube
    play_match = re.search(r"^(?:play|put on|start playing)\s+(.+?)(?:\s+(?:song|music|track|video))?$", cmd_clean)
    if play_match:
        song_name = play_match.group(1).strip()
        # Skip if it's a media key command (pause/prev/next/stop)
        if song_name not in ["pause", "stop", "next", "previous", "prev"]:
            return play_youtube_song(song_name)

    return None

def open_chrome():
    try:
        import webbrowser
        webbrowser.open("https://google.com")
        return "Opening Google Chrome, Boss."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Launch Chrome failed: {e}")
        return "I was unable to open Chrome."

def open_vscode():
    try:
        import subprocess
        app_path = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Microsoft VS Code", "Code.exe")
        if os.path.exists(app_path):
            subprocess.Popen([app_path])
        else:
            subprocess.Popen(["code"], shell=True)
        return "Opening VS Code, Boss."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Launch VS Code failed: {e}")
        return "I was unable to open VS Code."

def shutdown_pc():
    try:
        os.system("shutdown /s /t 5")
        return "Shutting down the PC in 5 seconds."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Shutdown failed: {e}")
        return "I was unable to shut down the PC."

def restart_pc():
    try:
        os.system("shutdown /r /t 5")
        return "Restarting the PC in 5 seconds."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Restart failed: {e}")
        return "I was unable to restart the PC."

def navigate_to_editor_line(line_number):
    import pyautogui
    import time
    try:
        line_num = int(line_number)
        if line_num > 0:
            print(f"[PC CONTROL] Simulating line jump to line: {line_num}")
            # standard line navigation hotkey in VS Code, IntelliJ, Notepad++, Sublime is Ctrl+G
            pyautogui.hotkey('ctrl', 'g')
            time.sleep(0.1)
            pyautogui.typewrite(str(line_num))
            time.sleep(0.1)
            pyautogui.press('enter')
            return f"Successfully navigated to line {line_num} on your active editor, Boss."
    except Exception as e:
        print(f"[PC CONTROL ERROR] Line navigation failed: {e}")
    return "I was unable to navigate to that line number."

def send_whatsapp_message(contact, message):
    import os
    import time
    import pyautogui
    try:
        print(f"[PC CONTROL] Attempting to open WhatsApp to message {contact}...")
        try:
            os.startfile("whatsapp:")
        except Exception:
            from AppOpener import open as app_open
            app_open("whatsapp")
            
        time.sleep(3.5)
        
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(0.5)
        
        pyautogui.typewrite(contact)
        time.sleep(1.2)
        
        pyautogui.press('enter')
        time.sleep(0.5)
        
        pyautogui.typewrite(message)
        time.sleep(0.5)
        pyautogui.press('enter')
        return f"Successfully sent WhatsApp message to {contact}."
    except Exception as e:
        print(f"[PC CONTROL ERROR] WhatsApp automation failed: {e}")
        return f"I ran into an issue sending the WhatsApp message: {e}"


def play_youtube_song(song_name):
    """Searches YouTube for the song and opens the first video result in the browser."""
    import webbrowser
    import urllib.request
    import urllib.parse
    import re as _re
    import ssl
    try:
        query = urllib.parse.quote_plus(f"{song_name} song")
        # Search DuckDuckGo restricted to YouTube
        search_url = "https://html.duckduckgo.com/html/"
        data = urllib.parse.urlencode({"q": f"{song_name} site:youtube.com"}).encode("utf-8")
        req = urllib.request.Request(
            search_url,
            data=data,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=context, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # Extract first YouTube watch URL
        match = _re.search(r'https://(?:www\.)?youtube\.com/watch\?v=[A-Za-z0-9_\-]+', html)
        if match:
            url = match.group(0)
        else:
            # Fallback: direct YouTube search URL
            url = f"https://www.youtube.com/results?search_query={query}"
        import threading
        threading.Thread(target=webbrowser.open_new_tab, args=(url,), daemon=True).start()
        return f"Playing {song_name} on YouTube for you, Boss."
    except Exception as e:
        print(f"[PC CONTROL ERROR] YouTube play failed: {e}")
        # Hard fallback to search page
        try:
            query = urllib.parse.quote_plus(f"{song_name} song")
            url = f"https://www.youtube.com/results?search_query={query}"
            import threading
            threading.Thread(target=webbrowser.open_new_tab, args=(url,), daemon=True).start()
            return f"Opening YouTube search for {song_name}, Boss."
        except Exception:
            return f"I was unable to play {song_name} right now."
