import os
import sys
import winreg
from PIL import Image
from win32com.client import Dispatch

def get_desktop_path():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        path, _ = winreg.QueryValueEx(key, "Desktop")
        # Expand environment variables like %USERPROFILE%
        return os.path.expandvars(path)
    except Exception as e:
        print("Failed to get Desktop path from registry:", e)
        # Fallback
        return os.path.join(os.path.expanduser("~"), "Desktop")

def get_startup_path():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        path, _ = winreg.QueryValueEx(key, "Startup")
        # Expand environment variables like %USERPROFILE%
        return os.path.expandvars(path)
    except Exception as e:
        print("Failed to get Startup path from registry:", e)
        # Fallback
        return os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs", "Startup")

def main():
    project_dir = os.path.abspath(os.path.dirname(__file__))
    png_path = os.path.join(project_dir, "cat_idle.png")
    ico_path = os.path.join(project_dir, "app_icon.ico")
    
    # 1. Convert PNG to ICO
    print("Converting cat_idle.png to app_icon.ico...")
    if not os.path.exists(png_path):
        if os.path.exists(ico_path):
            print(f"Warning: Could not find {png_path}, but {ico_path} already exists. Using existing icon.")
        else:
            print(f"Error: Could not find {png_path} and no existing {ico_path}")
            sys.exit(1)
    else:
        try:
            img = Image.open(png_path)
            img.save(ico_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
            print("Success: ICO saved to:", ico_path)
        except Exception as e:
            print("Error converting PNG to ICO:", e)
            sys.exit(1)
        
    # 2. Create Desktop Shortcut
    print("Creating Desktop Shortcut...")
    desktop = get_desktop_path()
    print("Desktop Folder Path:", desktop)
    desktop_shortcut_path = os.path.join(desktop, "MEAO Personal Assistant.lnk")
    
    pythonw_path = os.path.join(project_dir, "llama_env", "Scripts", "pythonw.exe")
    script_path = os.path.join(project_dir, "companion.py")
    
    if not os.path.exists(pythonw_path):
        print(f"Warning: Local llama_env pythonw not found at {pythonw_path}. Trying default pythonw...")
        pythonw_path = "pythonw.exe"
        
    shell = Dispatch('WScript.Shell')
    
    try:
        shortcut = shell.CreateShortCut(desktop_shortcut_path)
        shortcut.Targetpath = pythonw_path
        shortcut.Arguments = f'"{script_path}"'
        shortcut.WorkingDirectory = project_dir
        shortcut.IconLocation = ico_path
        shortcut.Description = "MEAO Desktop Mascot and Personal Assistant"
        shortcut.save()
        print("Success: Desktop shortcut created at:", desktop_shortcut_path)
    except Exception as e:
        print("Error creating Desktop shortcut:", e)
        sys.exit(1)

    # 3. Create Startup Shortcut
    print("Creating Startup Shortcut for Autostart...")
    startup = get_startup_path()
    print("Startup Folder Path:", startup)
    startup_shortcut_path = os.path.join(startup, "MEAO Personal Assistant.lnk")
    
    try:
        shortcut = shell.CreateShortCut(startup_shortcut_path)
        shortcut.Targetpath = pythonw_path
        shortcut.Arguments = f'"{script_path}" --startup'
        shortcut.WorkingDirectory = project_dir
        shortcut.IconLocation = ico_path
        shortcut.Description = "MEAO Desktop Mascot and Personal Assistant (Autostart)"
        shortcut.save()
        print("Success: Startup shortcut created at:", startup_shortcut_path)
    except Exception as e:
        print("Error creating Startup shortcut:", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
