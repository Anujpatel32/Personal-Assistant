import os
import re
import time
import json
import threading
import subprocess
import webbrowser
import urllib.request
import winsound

import memory_manager
import pc_control

ROUTINES_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "routines_config.json")

_ROUTINE_DEFAULTS = {
    "morning": {
        "enabled": True,
        "greeting_text": "Good morning, Boss!",
        "include_time": True,
        "include_weather": True,
        "city": "Pune",
        "include_tasks": True,
        "include_news": True,
        "farewell": "Have a wonderful day!"
    },
    "night": {
        "enabled": True,
        "dim_brightness_to": 10,
        "enable_dnd": True,
        "farewell_text": "Sleep well, Boss!"
    }
}

def load_routines_config():
    """Load routines_config.json, falling back to defaults for missing keys."""
    try:
        if os.path.exists(ROUTINES_CONFIG_FILE):
            with open(ROUTINES_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults to ensure all keys exist
            merged = {
                "morning": {**_ROUTINE_DEFAULTS["morning"], **data.get("morning", {})},
                "night":   {**_ROUTINE_DEFAULTS["night"],   **data.get("night",   {})},
            }
            return merged
    except Exception as e:
        print(f"[ROUTINES] Could not load config: {e}")
    return dict(_ROUTINE_DEFAULTS)

def save_routines_config(config: dict):
    """Persist routines config to disk."""
    try:
        with open(ROUTINES_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ROUTINES] Could not save config: {e}")
        return False

def get_top_news():
    url = "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
            titles = re.findall(r'<title>(.*?)</title>', html)
            headlines = []
            for t in titles:
                clean_title = re.sub(r'\s-\s.*$', '', t)
                clean_title = clean_title.replace('&quot;', '"').replace('&amp;', '&').replace('&#39;', "'")
                if clean_title.strip().lower() in ["google news", "news", "top stories"]:
                    continue
                headlines.append(clean_title)
                if len(headlines) == 3:
                    break
            return headlines
    except Exception as e:
        print(f"[AUTOMATION ERROR] Could not fetch news: {e}")
        return ["Could not load headlines at the moment."]

def toggle_dnd(enable=True):
    try:
        val = 0 if enable else 1
        reg_cmd = (
            f'Set-ItemProperty -Path "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings" '
            f'-Name "NOC_GLOBAL_SETTING_TOASTS_ENABLED" -Value {val} -ErrorAction SilentlyContinue'
        )
        creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        subprocess.run(["powershell", "-NoProfile", "-Command", reg_cmd], creationflags=creationflags)
        print(f"[AUTOMATION] Focus Assist DND state set to: {enable}")
        return True
    except Exception as e:
        print(f"[AUTOMATION ERROR] Failed to toggle DND: {e}")
        return False

def run_good_morning_routine():
    """Build and speak the morning brief, driven by routines_config.json."""
    print("[AUTOMATION] Running Good Morning Routine...")
    cfg = load_routines_config().get("morning", _ROUTINE_DEFAULTS["morning"])

    parts = []

    # Greeting
    parts.append(cfg.get("greeting_text", "Good morning, Boss!"))

    # Time
    if cfg.get("include_time", True):
        current_time = time.strftime("%I:%M %p")
        parts.append(f"The current time is {current_time}.")

    # Weather
    if cfg.get("include_weather", True):
        city = cfg.get("city", "Pune")
        weather = memory_manager.fetch_weather(city) or "not available offline"
        parts.append(f"The weather in {city} is currently {weather}.")

    # Tasks
    if cfg.get("include_tasks", True):
        tasks = memory_manager.load_tasks()
        incomplete = [t for t in tasks if not t.get("completed", False)]
        task_count = len(incomplete)
        if task_count > 0:
            parts.append(f"You have {task_count} incomplete task{'s' if task_count > 1 else ''}.")
        else:
            parts.append("You have no pending tasks today.")

    # News
    if cfg.get("include_news", True):
        news = get_top_news()
        if news and news[0] != "Could not load headlines at the moment.":
            parts.append("Here are the top news headlines for India: " + ". ".join(news) + ".")

    # Farewell
    parts.append(cfg.get("farewell", "Have a wonderful day!"))

    return " ".join(parts)

def run_night_routine():
    """Run the night routine driven by routines_config.json."""
    print("[AUTOMATION] Running Night Routine...")
    cfg = load_routines_config().get("night", _ROUTINE_DEFAULTS["night"])

    # Dim screen
    brightness = int(cfg.get("dim_brightness_to", 10))
    pc_control.set_brightness(brightness)

    # Toggle DND
    if cfg.get("enable_dnd", True):
        toggle_dnd(True)

    farewell = cfg.get("farewell_text", "Sleep well, Boss!")
    return (
        f"Night routine complete! I've dimmed your screen to {brightness} percent"
        + (", silenced your Windows notifications," if cfg.get("enable_dnd", True) else "")
        + f" and everything is set. {farewell}"
    )

def _alarm_worker(target_hour, target_minute):
    print(f"[ALARM] Scheduled for {target_hour:02d}:{target_minute:02d}")
    triggered = False
    while not triggered:
        now = time.localtime()
        if now.tm_hour == target_hour and now.tm_min == target_minute:
            print("[ALARM] Triggering alarm sound!")
            # Play a Windows beep sequence (3 long beeps)
            for _ in range(5):
                winsound.Beep(880, 600)  # A5 note, 600ms
                time.sleep(0.3)
            triggered = True
            break
        time.sleep(10)  # check every 10s

def set_alarm(time_str):
    """
    Parses a time string like '7:30 AM', '19:45', or '7 AM' and sets a background alarm.
    """
    time_str = time_str.strip().upper()
    try:
        # Match "7:30 AM", "12:00 PM"
        match_am_pm = re.match(r"(\d+)(?::(\d+))?\s*(AM|PM)", time_str)
        if match_am_pm:
            hour = int(match_am_pm.group(1))
            minute = int(match_am_pm.group(2)) if match_am_pm.group(2) else 0
            period = match_am_pm.group(3)
            
            if period == "PM" and hour < 12:
                hour += 12
            elif period == "AM" and hour == 12:
                hour = 0
        else:
            # Match 24 hour formats "19:30", "07:00"
            match_24 = re.match(r"(\d+):(\d+)", time_str)
            if match_24:
                hour = int(match_24.group(1))
                minute = int(match_24.group(2))
            else:
                # Match simple hour "7 AM" or "7 PM"
                match_simple = re.match(r"(\d+)\s*(AM|PM)?", time_str)
                if match_simple:
                    hour = int(match_simple.group(1))
                    minute = 0
                    period = match_simple.group(2)
                    if period == "PM" and hour < 12:
                        hour += 12
                    elif period == "AM" and hour == 12:
                        hour = 0
                else:
                    return None
                    
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
            
        # Spawn thread
        threading.Thread(target=_alarm_worker, args=(hour, minute), daemon=True).start()
        
        # Return friendly string
        am_pm_hour = hour % 12
        if am_pm_hour == 0:
            am_pm_hour = 12
        period = "PM" if hour >= 12 else "AM"
        return f"Alarm set successfully for {am_pm_hour}:{minute:02d} {period}, Boss."
    except Exception as e:
        print(f"[ALARM ERROR] Could not set alarm: {e}")
        return None
