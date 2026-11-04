# -*- coding: utf-8 -*-
"""
tool_schemas.py - Gemini Function Calling Schema Generator
===========================================================
Converts tool_registry tools into Gemini-compatible function declaration
format for native function calling. Also supports OpenAI-style schemas
for Groq/OpenRouter/NVIDIA.

Usage:
    from tool_schemas import get_gemini_tools, get_openai_tools
    tools = get_gemini_tools()       # for Gemini API
    tools = get_openai_tools()       # for OpenAI-compatible APIs
"""

import logging
from typing import Any

import tool_registry

logger = logging.getLogger("meow.tools")

# Tool parameter type hints (best-effort inference from tool definitions)
_PARAM_TYPES = {
    "level": {"type": "integer", "description": "A percentage value (0-100)"},
    "app": {"type": "string", "description": "Application name to open"},
    "query": {"type": "string", "description": "Search query or keywords"},
    "url": {"type": "string", "description": "A web URL"},
    "text": {"type": "string", "description": "Text content"},
    "key": {"type": "string", "description": "Memory key name"},
    "value": {"type": "string", "description": "Value to store"},
    "folder_name": {"type": "string", "description": "Name for the folder"},
    "task_description": {"type": "string", "description": "Natural language description of the task"},
    "language": {"type": "string", "description": "Programming language (e.g. python, javascript)"},
    "project_name": {"type": "string", "description": "Name for the project"},
    "file_path": {"type": "string", "description": "Path to a file on disk"},
    "error_log": {"type": "string", "description": "Error traceback or log text"},
    "package_name": {"type": "string", "description": "Package name to install"},
    "package_manager": {"type": "string", "description": "Package manager (pip or npm)"},
    "content": {"type": "string", "description": "File content to write"},
    "city": {"type": "string", "description": "City name for weather lookup"},
    "seconds": {"type": "integer", "description": "Duration in seconds"},
}


def _infer_param_schema(param_name: str) -> dict:
    """Infer a JSON schema for a tool parameter based on its name."""
    if param_name in _PARAM_TYPES:
        return _PARAM_TYPES[param_name]
    return {"type": "string", "description": f"The {param_name.replace('_', ' ')} parameter"}


def get_gemini_tools() -> list[dict]:
    """Generate Gemini function declaration format.

    Returns:
        List of function declarations for the Gemini API tools parameter.
    """
    tools_list = tool_registry.list_tools()
    declarations = []

    for tool in tools_list:
        properties = {}
        required = []

        for param in tool["params"]:
            properties[param] = _infer_param_schema(param)
            required.append(param)

        declaration = {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": {
                "type": "object",
                "properties": properties,
            }
        }
        if required:
            declaration["parameters"]["required"] = required

        declarations.append(declaration)

    logger.debug("Generated %d Gemini tool schemas", len(declarations))
    return declarations


def get_openai_tools() -> list[dict]:
    """Generate OpenAI-compatible function calling format.

    Works with Groq, NVIDIA, and OpenRouter APIs.

    Returns:
        List of tool objects in OpenAI function calling format.
    """
    tools_list = tool_registry.list_tools()
    tools = []

    for tool in tools_list:
        properties = {}
        required = []

        for param in tool["params"]:
            properties[param] = _infer_param_schema(param)
            required.append(param)

        tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        })

    logger.debug("Generated %d OpenAI-style tool schemas", len(tools))
    return tools


def get_tool_names() -> list[str]:
    """Return just the tool names for quick reference."""
    return [t["name"] for t in tool_registry.list_tools()]


def get_tool_summary() -> str:
    """Return a human-readable summary of all available tools."""
    lines = []
    for tool in tool_registry.list_tools():
        params = ", ".join(tool["params"]) if tool["params"] else "(none)"
        lines.append(f"  - {tool['name']}({params}): {tool['description']}")
    return "\n".join(lines)


# ---- Safety classification ------------------------------------------------

DANGEROUS_TOOLS = {
    "lock_pc", "run_command", "write_file", "delete_file",
    "install_dependency", "auto_debug_code",
}

SAFE_TOOLS = {
    "take_screenshot", "get_system_stats", "recall_fact", "search_knowledge",
    "search_files", "get_weather", "get_clipboard", "web_search",
}


def is_dangerous(tool_name: str) -> bool:
    """Check if a tool requires user confirmation before execution."""
    return tool_name in DANGEROUS_TOOLS
