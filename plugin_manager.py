import os
import sys
import importlib.util
import json

PLUGINS_DIR = os.path.join(os.path.dirname(__file__), "plugins")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "plugins_config.json")

# Ensure plugins directory exists
os.makedirs(PLUGINS_DIR, exist_ok=True)

# Registries
loaded_plugins = {}     # id -> module instance
command_handlers = {}   # id -> handler function
plugin_status = {}      # id -> bool (enabled/disabled)

def load_status():
    global plugin_status
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                plugin_status = json.load(f)
        except Exception:
            plugin_status = {}
    else:
        plugin_status = {}

def save_status():
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(plugin_status, f, indent=4)
    except Exception as e:
        print(f"[PLUGIN MANAGER CONFIG SAVE ERROR]: {e}")

def load_plugins(mascot, app, pc_control):
    """Scan and load all enabled Python plugins from the plugins/ directory."""
    load_status()
    if not os.path.exists(PLUGINS_DIR):
        return

    for filename in os.listdir(PLUGINS_DIR):
        if filename.endswith(".py") and not filename.startswith("__"):
            file_path = os.path.join(PLUGINS_DIR, filename)
            plugin_id = os.path.splitext(filename)[0]
            
            # Default to active if status is not persisted
            if plugin_id not in plugin_status:
                plugin_status[plugin_id] = True
            
            if plugin_status[plugin_id]:
                try:
                    register_plugin_module(plugin_id, file_path, mascot, app, pc_control)
                    print(f"[PLUGIN MANAGER] Loaded plugin: {plugin_id}")
                except Exception as e:
                    print(f"[PLUGIN MANAGER ERROR] Failed to load {plugin_id}: {e}")
            else:
                print(f"[PLUGIN MANAGER] Plugin disabled (skipped): {plugin_id}")
    save_status()

def register_plugin_module(plugin_id, file_path, mascot, app, pc_control):
    """Dynamically load and register a plugin script module."""
    spec = importlib.util.spec_from_file_location(plugin_id, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot build module spec for {file_path}")
        
    module = importlib.util.module_from_spec(spec)
    sys.modules[plugin_id] = module
    spec.loader.exec_module(module)
    
    # Check for register hook
    if hasattr(module, "register"):
        module.register(mascot, app, pc_control)
        
    loaded_plugins[plugin_id] = module
    
    # Store command handler if present
    if hasattr(module, "handle_command"):
        command_handlers[plugin_id] = module.handle_command
    else:
        # Default handler matching trigger terms
        if hasattr(module, "TRIGGERS") and hasattr(module, "execute_plugin"):
            triggers = getattr(module, "TRIGGERS")
            exec_func = getattr(module, "execute_plugin")
            def default_handler(command):
                if any(t in command.lower() for t in triggers):
                    return exec_func(command)
                return None
            command_handlers[plugin_id] = default_handler

def hot_load_plugin(plugin_id, mascot, app, pc_control):
    """Force load or reload an installed plugin by its ID at runtime."""
    file_path = os.path.join(PLUGINS_DIR, f"{plugin_id}.py")
    if not os.path.exists(file_path):
        return False
        
    plugin_status[plugin_id] = True
    save_status()
    
    # Clean up previous registration if reloaded
    unload_plugin(plugin_id)
    
    try:
        register_plugin_module(plugin_id, file_path, mascot, app, pc_control)
        print(f"[PLUGIN MANAGER] Hot-loaded plugin: {plugin_id}")
        return True
    except Exception as e:
        print(f"[PLUGIN MANAGER ERROR] Hot-load failed: {e}")
        return False

def unload_plugin(plugin_id):
    """Remove plugin hooks and unregister module."""
    if plugin_id in loaded_plugins:
        loaded_plugins.pop(plugin_id)
    if plugin_id in command_handlers:
        command_handlers.pop(plugin_id)
    if plugin_id in sys.modules:
        sys.modules.pop(plugin_id)

def get_installed_plugins():
    """Retrieve metadata of all installed plugins."""
    load_status()
    plugins_meta = []
    
    for filename in os.listdir(PLUGINS_DIR):
        if filename.endswith(".py") and not filename.startswith("__"):
            plugin_id = os.path.splitext(filename)[0]
            file_path = os.path.join(PLUGINS_DIR, filename)
            
            # Read metadata safely without full execution if disabled
            meta = {
                "id": plugin_id,
                "name": plugin_id.replace("_", " ").title(),
                "description": "Custom extension plugin.",
                "version": "1.0.0",
                "active": plugin_status.get(plugin_id, True)
            }
            
            # Load metadata from compiled module if loaded
            if plugin_id in loaded_plugins:
                mod = loaded_plugins[plugin_id]
                meta["name"] = getattr(mod, "PLUGIN_NAME", meta["name"])
                meta["description"] = getattr(mod, "PLUGIN_DESCRIPTION", meta["description"])
                meta["version"] = getattr(mod, "PLUGIN_VERSION", meta["version"])
            else:
                # Try parsing file headers directly
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        for line in content.split("\n"):
                            if "PLUGIN_NAME" in line and "=" in line:
                                meta["name"] = line.split("=")[1].strip().strip('"').strip("'")
                            elif "PLUGIN_DESCRIPTION" in line and "=" in line:
                                meta["description"] = line.split("=")[1].strip().strip('"').strip("'")
                            elif "PLUGIN_VERSION" in line and "=" in line:
                                meta["version"] = line.split("=")[1].strip().strip('"').strip("'")
                except Exception:
                    pass
            plugins_meta.append(meta)
    return plugins_meta

def handle_command(command):
    """Loop through registered plugin handlers to check for custom execution commands."""
    for plugin_id, handler in command_handlers.items():
        if plugin_status.get(plugin_id, True):
            try:
                response = handler(command)
                if response is not None:
                    print(f"[PLUGIN INTERCEPT] Handled by {plugin_id}: '{response}'")
                    return response
            except Exception as e:
                print(f"[PLUGIN ERROR] Handler failed for {plugin_id}: {e}")
    return None

# --- COMMUNITY PLUGINS CATALOG ---
COMMUNITY_CATALOG = {
    "crypto_tracker": {
        "name": "Crypto Tracker",
        "description": "Tracks live Bitcoin and Ethereum prices directly from public APIs.",
        "version": "1.1.0",
        "code": """# Crypto Tracker Plugin
import urllib.request
import json

PLUGIN_NAME = "Crypto Tracker"
PLUGIN_DESCRIPTION = "Tracks live Bitcoin and Ethereum prices directly from public APIs."
PLUGIN_VERSION = "1.1.0"
TRIGGERS = ["crypto price", "bitcoin", "ethereum", "crypto value", "btc rate"]

def register(mascot, app, pc_control):
    print("[CRYPTO PLUGIN] Registered successfully!")

def execute_plugin(command):
    try:
        # Query free public Coingecko API
        req = urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            btc = data.get("bitcoin", {}).get("usd", 0)
            eth = data.get("ethereum", {}).get("usd", 0)
            return f"Bitcoin is currently trading at ${btc:,} USD, and Ethereum is at ${eth:,} USD, Boss."
    except Exception as e:
        print(f"[CRYPTO PLUGIN ERROR]: {e}")
        return "I was unable to retrieve live cryptocurrency prices at the moment."

def handle_command(command):
    if any(t in command.lower() for t in TRIGGERS):
        return execute_plugin(command)
    return None
"""
    },
    "github_monitor": {
        "name": "GitHub Monitor",
        "description": "Reads the latest commit logs from public repositories.",
        "version": "1.0.0",
        "code": """# GitHub Monitor Plugin
import urllib.request
import json
import re

PLUGIN_NAME = "GitHub Monitor"
PLUGIN_DESCRIPTION = "Reads the latest commit logs from public repositories."
PLUGIN_VERSION = "1.0.0"

def register(mascot, app, pc_control):
    print("[GITHUB PLUGIN] Registered successfully!")

def handle_command(command):
    if "github commit" in command.lower() or "latest commit" in command.lower():
        try:
            # Query standard public python cpython repo commits
            req = urllib.request.Request(
                "https://api.github.com/repos/python/cpython/commits?per_page=1",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                if data:
                    latest = data[0]
                    author = latest["commit"]["author"]["name"]
                    message = latest["commit"]["message"].split("\\n")[0]
                    return f"The latest commit on python cpython was by {author}: '{message}'."
        except Exception as e:
            print(f"[GITHUB PLUGIN ERROR]: {e}")
            return "I couldn't fetch the latest commit stats from GitHub."
    return None
"""
    },
    "system_health": {
        "name": "System Health",
        "description": "Announces detailed CPU hardware architectures and file cache status.",
        "version": "1.2.0",
        "code": """# System Health Detailer Plugin
import psutil
import platform

PLUGIN_NAME = "System Health"
PLUGIN_DESCRIPTION = "Announces detailed CPU hardware architectures and file cache status."
PLUGIN_VERSION = "1.2.0"

def register(mascot, app, pc_control):
    print("[SYSTEM HEALTH PLUGIN] Registered successfully!")

def handle_command(command):
    if any(w in command.lower() for w in ["system details", "cpu health", "hardware details"]):
        cpu_cores = psutil.cpu_count(logical=False)
        logical_cores = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq().max if psutil.cpu_freq() else 0.0
        arch = platform.machine()
        system = platform.system()
        
        return f"Host Machine details: Operating System is {system} {arch}. We have {cpu_cores} physical CPU cores and {logical_cores} logical threads, running at a maximum frequency of {cpu_freq:.0f} MHz."
    return None
"""
    }
}
