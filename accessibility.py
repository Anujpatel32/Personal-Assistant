import os
import sys
import winreg
import psutil

try:
    import win32gui
    import win32process
    import win32con
    import win32com.client
except ImportError:
    win32gui = None
    win32process = None
    win32con = None
    win32com.client = None

def get_open_windows():
    """Lists all currently visible top-level windows paired with their process names."""
    if not win32gui:
        return []
        
    def callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    proc = psutil.Process(pid)
                    process_name = proc.name()
                except Exception:
                    process_name = "unknown"
                extra.append({
                    "hwnd": hwnd,
                    "title": title,
                    "process": process_name
                })
        return True
        
    windows = []
    win32gui.EnumWindows(callback, windows)
    return windows

def activate_window(target):
    """Activates a window by HWND (int) or substring in title/process name."""
    if not win32gui:
        return False
        
    hwnd = None
    if isinstance(target, int):
        hwnd = target
    else:
        # Search by title or process name
        target_clean = str(target).lower()
        windows = get_open_windows()
        for w in windows:
            if target_clean in w["title"].lower() or target_clean in w["process"].lower():
                hwnd = w["hwnd"]
                break
                
    if not hwnd:
        print(f"[ACCESSIBILITY] No window found matching: {target}")
        return False
        
    try:
        # If iconic (minimized), restore it
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            
        # Win32 hack to force SetForegroundWindow permission bypass
        shell = win32com.client.Dispatch("WScript.Shell")
        shell.SendKeys('%') # Alt key trigger
        
        win32gui.SetForegroundWindow(hwnd)
        print(f"[ACCESSIBILITY] Successfully activated window HWND {hwnd}")
        return True
    except Exception as e:
        print(f"[ACCESSIBILITY ERROR] SetForegroundWindow failed: {e}")
        # Secondary fallback
        try:
            win32gui.BringWindowToTop(hwnd)
            return True
        except Exception:
            return False

def configure_startup(enable=True):
    """Enables or disables Meow startup boot trigger inside Windows Registry Run HKEY."""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_dir = os.path.dirname(os.path.abspath(__file__))
    bat_path = os.path.join(app_dir, "Launch_MEAO.bat")

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enable:
            # Save bat path in registry
            winreg.SetValueEx(key, "MeowAssistant", 0, winreg.REG_SZ, f'"{bat_path}" --startup')
            print("[ACCESSIBILITY] Added Meow to startup registry.")
            return "Meow Assistant is configured to boot automatically on startup, Boss."
        else:
            try:
                winreg.DeleteValue(key, "MeowAssistant")
                print("[ACCESSIBILITY] Removed Meow from startup registry.")
                return "Meow Assistant was removed from startup, Boss."
            except FileNotFoundError:
                return "Meow Assistant was not in the startup list."
    except Exception as e:
        print(f"[ACCESSIBILITY REGISTRY ERROR] Modify failed: {e}")
        return f"Failed to modify startup registry: {e}"


def get_startup_status():
    """Returns True if Meow is currently registered in Windows startup registry."""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, "MeowAssistant")
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False
