# -*- coding: utf-8 -*-
"""
tool_registry.py — Central Tool Registry for MEOW Agentic System
=================================================================
Defines all tools that the action_planner can call when executing
multi-step autonomous plans. Each tool has:
  - name: unique identifier used by the LLM plan
  - description: what the tool does (shown to LLM for selection)
  - params: list of expected parameter names
  - fn: the actual callable

Tools are auto-discoverable. Modules can register tools at import
time using @register_tool decorator.

Usage:
    from tool_registry import get_tool, list_tools, run_tool
    tools = list_tools()   # → list of {name, description, params}
    result = run_tool("open_app", {"app": "chrome"})
"""

import logging
import traceback

logger = logging.getLogger("meow.tools")

# ── Registry storage ──────────────────────────────────────────────────────────
_REGISTRY: dict = {}   # name → {description, params, fn}


def register_tool(name: str, description: str, params: list):
    """
    Decorator to register a callable as an agent tool.

    @register_tool("take_screenshot", "Capture the current screen", [])
    def take_screenshot():
        ...
    """
    def decorator(fn):
        _REGISTRY[name] = {
            "name":        name,
            "description": description,
            "params":      params,
            "fn":          fn,
        }
        return fn
    return decorator


def list_tools() -> list:
    """Return tool schemas (without the fn callables) for LLM prompting."""
    return [
        {"name": t["name"], "description": t["description"], "params": t["params"]}
        for t in _REGISTRY.values()
    ]


def get_tool(name: str) -> dict | None:
    """Return tool dict by name, or None if not found."""
    return _REGISTRY.get(name)


def run_tool(name: str, args: dict = None) -> dict:
    """
    Execute a registered tool by name with the given args dict.
    Returns {"success": bool, "output": str, "error": str|None}
    """
    tool = _REGISTRY.get(name)
    if not tool:
        return {"success": False, "output": "", "error": f"Unknown tool: '{name}'"}
    args = args or {}
    try:
        result = tool["fn"](**args)
        return {"success": True, "output": str(result) if result is not None else "Done", "error": None}
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Tool '%s' failed: %s\n%s", name, e, tb)
        return {"success": False, "output": "", "error": str(e)}


# ════════════════════════════════════════════════════════════════════════
# BUILT-IN TOOL DEFINITIONS
# ════════════════════════════════════════════════════════════════════════

# ── PC Control ────────────────────────────────────────────────────────────────
@register_tool("take_screenshot",
               "Take a screenshot and save it to the desktop",
               [])
def _tool_screenshot():
    import pc_control
    return pc_control.take_screenshot()


@register_tool("set_volume",
               "Set PC speaker volume to a percentage (0-100)",
               ["level"])
def _tool_volume(level: int):
    import pc_control
    return pc_control.set_volume_percentage(int(level))


@register_tool("set_brightness",
               "Set screen brightness to a percentage (0-100)",
               ["level"])
def _tool_brightness(level: int):
    import pc_control
    return pc_control.set_brightness(int(level))


@register_tool("open_app",
               "Open an application by name (e.g. chrome, vscode, notepad)",
               ["app"])
def _tool_open_app(app: str):
    import pc_control
    return pc_control.handle_pc_command(f"open {app}")


@register_tool("search_files",
               "Search for files matching a query on the local PC",
               ["query"])
def _tool_search_files(query: str):
    import pc_control
    results = pc_control.search_local_files_advanced(query)
    return results if results else "No files found."


@register_tool("lock_pc",
               "Lock the PC screen immediately",
               [])
def _tool_lock_pc():
    import pc_control
    return pc_control.lock_pc()


@register_tool("create_folder",
               "Create a new desktop folder with the given name",
               ["folder_name"])
def _tool_create_folder(folder_name: str):
    import pc_control
    return pc_control.create_desktop_folder(folder_name)


# ── Web & Research ────────────────────────────────────────────────────────────
@register_tool("web_search",
               "Search the web and return a summary of results for a query",
               ["query"])
def _tool_web_search(query: str):
    import internet_agent
    return internet_agent.search_web(query)


@register_tool("open_url",
               "Open a URL in the default web browser",
               ["url"])
def _tool_open_url(url: str):
    import webbrowser
    webbrowser.open(url)
    return f"Opened {url}"


# ── Memory & Knowledge ────────────────────────────────────────────────────────
@register_tool("remember_fact",
               "Save a fact or preference about the user to long-term memory",
               ["key", "value"])
def _tool_remember(key: str, value: str):
    import memory_manager
    mem = memory_manager.load_memory()
    mem[key] = value
    memory_manager.save_memory(mem)
    return f"Remembered: {key} = {value}"


@register_tool("recall_fact",
               "Retrieve a stored fact or preference from memory",
               ["key"])
def _tool_recall(key: str):
    import memory_manager
    mem = memory_manager.load_memory()
    return mem.get(key, f"No memory found for '{key}'")


@register_tool("add_task",
               "Add a task to Meow's task list",
               ["text"])
def _tool_add_task(text: str):
    import memory_manager
    memory_manager.add_task(text)
    return f"Task added: {text}"


@register_tool("search_knowledge",
               "Search the knowledge base for relevant documents",
               ["query"])
def _tool_search_kb(query: str):
    import knowledge_manager
    results = knowledge_manager.search_documents(query)
    if results:
        return "\n".join(f"[{r['title']}]: {r['snippet']}" for r in results[:3])
    return "No relevant documents found."


# ── System Info ───────────────────────────────────────────────────────────────
@register_tool("get_system_stats",
               "Return current CPU, RAM, disk and battery usage",
               [])
def _tool_system_stats():
    import psutil
    cpu  = psutil.cpu_percent()
    ram  = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    batt = psutil.sensors_battery()
    batt_str = (
        f"{batt.percent:.0f}% ({'Charging' if batt.power_plugged else 'Discharging'})"
        if batt else "N/A"
    )
    return (
        f"CPU: {cpu:.1f}% | "
        f"RAM: {ram.percent:.1f}% ({ram.used//(1024**3):.1f}/{ram.total//(1024**3):.1f} GB) | "
        f"Disk: {disk.percent:.1f}% | "
        f"Battery: {batt_str}"
    )


@register_tool("speak",
               "Make Meow say something out loud",
               ["text"])
def _tool_speak(text: str):
    import tts_engine
    tts_engine.speak_sync(text)
    return f"Spoke: {text}"


# ── Code Builder (Agentic Coding) ─────────────────────────────────────
@register_tool("generate_code_project",
               "Generate single or multi-file code projects from a natural language description. Returns the saved file/folder path.",
               ["task_description", "language", "project_name"])
def _tool_generate_code(task_description: str, language: str = "python", project_name: str = "app"):
    import code_builder
    return code_builder.tool_generate_project(task_description, language, project_name)


@register_tool("run_code_script",
               "Execute a local code file or project and return captured stdout and stderr output",
               ["file_path", "language"])
def _tool_run_code(file_path: str, language: str = "python"):
    import code_builder
    return code_builder.tool_run_script(file_path, language)


@register_tool("auto_debug_code",
               "Fix a broken code file by analyzing its execution error traceback via LLM and rewriting the file",
               ["file_path", "error_log"])
def _tool_auto_debug(file_path: str, error_log: str):
    import code_builder
    return code_builder.tool_auto_debug(file_path, error_log)


@register_tool("install_dependency",
               "Install a missing pip or npm package required by generated code",
               ["package_name", "package_manager"])
def _tool_install_dep(package_name: str, package_manager: str = "pip"):
    import code_builder
    return code_builder.tool_install_package(package_name, package_manager)


# -- File Operations -------------------------------------------------------
@register_tool("read_file",
               "Read the contents of a file and return the text",
               ["file_path"])
def _tool_read_file(file_path: str):
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if len(content) > 3000:
            return content[:3000] + f"\n... (truncated, total {len(content)} chars)"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


@register_tool("write_file",
               "Write text content to a file (creates or overwrites)",
               ["file_path", "content"])
def _tool_write_file(file_path: str, content: str):
    import os
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Written {len(content)} chars to {file_path}"


_BLOCKED_COMMAND_PATTERNS = [
    r"\bformat\s+[a-zA-Z]:",
    r"\brmdir\s+/[sq]",
    r"\bdel\s+.*[/\\](?:windows|system32|program files)",
    r"\bshutdown\s+/[srf]",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
]

@register_tool("run_command",
               "Execute a shell command and return the stdout/stderr output",
               ["command"])
def _tool_run_command(command: str):
    import subprocess
    import re

    # Security guardrail: prevent destructive system commands
    cmd_lower = command.lower()
    for pattern in _BLOCKED_COMMAND_PATTERNS:
        if re.search(pattern, cmd_lower):
            logger.warning("Blocked potentially destructive command: %s", command)
            return "Security violation: This command is blocked by MEOW safety guardrails."

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=30, errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = result.stdout.strip()
        if result.stderr.strip():
            output += f"\nSTDERR: {result.stderr.strip()}"
        if not output:
            output = f"Command exited with code {result.returncode}"
        return output[:2000]
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds"
    except Exception as e:
        return f"Command failed: {e}"


# -- Clipboard --------------------------------------------------------------
@register_tool("copy_to_clipboard",
               "Copy text to the system clipboard",
               ["text"])
def _tool_copy_clipboard(text: str):
    import pyperclip
    pyperclip.copy(text)
    return f"Copied {len(text)} chars to clipboard"


@register_tool("get_clipboard",
               "Read the current contents of the system clipboard",
               [])
def _tool_get_clipboard():
    import pyperclip
    content = pyperclip.paste()
    return content[:2000] if content else "(clipboard is empty)"


# -- Music -------------------------------------------------------------------
@register_tool("play_music",
               "Play a music playlist by name (liked, old, english, refreshing) or random",
               ["playlist"])
def _tool_play_music(playlist: str = "random"):
    import webbrowser
    import random
    import musicLibrary
    playlist_lower = playlist.lower().strip()
    if playlist_lower in musicLibrary.music:
        webbrowser.open_new_tab(musicLibrary.music[playlist_lower])
        return f"Playing {playlist_lower} playlist"
    else:
        song = random.choice(list(musicLibrary.music.values()))
        webbrowser.open_new_tab(song)
        return "Playing random music"


# -- Timer -------------------------------------------------------------------
@register_tool("set_timer",
               "Set a countdown timer for a given number of seconds",
               ["seconds", "label"])
def _tool_set_timer(seconds: int, label: str = "Timer"):
    import threading
    import winsound

    def _timer_done():
        try:
            winsound.Beep(1000, 500)
            winsound.Beep(1000, 500)
        except Exception:
            pass

    seconds = int(seconds)
    threading.Timer(seconds, _timer_done).start()
    minutes = seconds // 60
    secs = seconds % 60
    if minutes > 0:
        return f"Timer set: {label} - {minutes}m {secs}s"
    return f"Timer set: {label} - {secs}s"


# -- Weather -----------------------------------------------------------------
@register_tool("get_weather",
               "Get current weather for a city",
               ["city"])
def _tool_get_weather(city: str = "Pune"):
    import memory_manager
    try:
        weather = memory_manager.fetch_weather(city)
        return weather if weather else f"Could not fetch weather for {city}"
    except Exception as e:
        return f"Weather error: {e}"


logger.info("Loaded %d tools: %s", len(_REGISTRY), ', '.join(_REGISTRY.keys()))
