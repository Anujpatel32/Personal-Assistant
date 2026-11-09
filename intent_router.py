# -*- coding: utf-8 -*-
"""
intent_router.py - LLM-Powered Intent Classification for MEOW
===============================================================
Classifies user input into intent categories and routes to the
appropriate handler. Replaces hardcoded keyword matching with
intelligent understanding.

Intents:
    chat           -> Regular conversation (default)
    tool_call      -> Single tool invocation
    multi_step     -> Complex goal requiring agent executor
    system_command -> Direct PC control (fast-path)
    style_change   -> Voice personality switch
    music          -> Play music

Usage:
    from intent_router import classify_intent, route_command
    intent = classify_intent("open chrome and search for python tutorials")
    # -> {"intent": "multi_step", "goal": "open chrome and search..."}
"""

import json
import logging
import re
from typing import Optional

import llm_router
import voice_personality

logger = logging.getLogger("meow.core")


# ---------------------------------------------------------------------------
# Fast-path keyword patterns (no LLM call needed)
# ---------------------------------------------------------------------------

_FAST_PATHS = {
    "system_command": {
        "open_app": [
            r"^open\s+(.+)$",
            r"^launch\s+(.+)$",
            r"^start\s+(.+)$",
        ],
        "volume": [
            r"(mute|unmute)",
            r"(volume\s*(up|down))",
            r"set\s+volume\s+to\s+(\d+)",
        ],
        "brightness": [
            r"set\s+brightness\s+to\s+(\d+)",
            r"(brightness\s*(up|down))",
        ],
        "screenshot": [
            r"(take\s+a?\s*screenshot)",
            r"(capture\s+(my\s+)?screen)",
        ],
        "lock": [
            r"lock\s+(my\s+)?(pc|computer|screen|workstation)",
        ],
    },
    "music": [
        r"play\s+(.+?)\s*(music|playlist|song)?$",
        r"play\s+(some\s+)?music",
    ],
    "style_change": [],  # Handled by voice_personality.detect_style_change()
}


def classify_intent(command: str) -> dict:
    """Classify user intent using fast-path matching then LLM fallback.

    Args:
        command: The user's text input.

    Returns:
        dict with keys:
            intent: str - one of: chat, tool_call, multi_step, system_command, style_change, music
            confidence: str - 'fast_path' or 'llm'
            data: dict - intent-specific data (e.g., app name, tool name, goal)
    """
    cmd = command.strip()
    cmd_lower = cmd.lower()

    # 1. Check for voice style changes first (lightweight)
    style_key, style_msg = voice_personality.detect_style_change(cmd)
    if style_key:
        return {
            "intent": "style_change",
            "confidence": "fast_path",
            "data": {"style": style_key, "message": style_msg},
        }

    # 2. Fast-path: system commands via regex
    for subcategory, patterns in _FAST_PATHS["system_command"].items():
        for pattern in patterns:
            match = re.search(pattern, cmd_lower)
            if match:
                return {
                    "intent": "system_command",
                    "confidence": "fast_path",
                    "data": {
                        "subcategory": subcategory,
                        "match": match.group(0),
                        "groups": match.groups(),
                        "original": cmd,
                    },
                }

    # 2b. Fast-path: folder deletion tool
    try:
        from pc_control import parse_delete_folder_name_from_command
        folder_to_delete = parse_delete_folder_name_from_command(cmd_lower)
        if folder_to_delete is not None:
            return {
                "intent": "tool_call",
                "confidence": "fast_path",
                "data": {
                    "tool": "delete_folder",
                    "args": {"folder_name": folder_to_delete},
                    "original": cmd,
                },
            }
    except Exception:
        pass

    # 2c. Fast-path: folder creation tool
    try:
        from pc_control import parse_folder_name_from_command
        folder_to_create = parse_folder_name_from_command(cmd_lower)
        if folder_to_create is not None:
            return {
                "intent": "tool_call",
                "confidence": "fast_path",
                "data": {
                    "tool": "create_folder",
                    "args": {"folder_name": folder_to_create},
                    "original": cmd,
                },
            }
    except Exception:
        pass

    # 3. Fast-path: music
    for pattern in _FAST_PATHS["music"]:
        match = re.search(pattern, cmd_lower)
        if match:
            return {
                "intent": "music",
                "confidence": "fast_path",
                "data": {"match": match.group(0), "original": cmd},
            }

    # 4. Short casual phrases -> chat (skip LLM call)
    if len(cmd.split()) <= 4 and not any(
        kw in cmd_lower for kw in [
            "search", "find", "create", "make", "build", "write",
            "save", "delete", "install", "set", "get", "show",
            "analyze", "check", "run", "execute", "help me",
        ]
    ):
        return {
            "intent": "chat",
            "confidence": "fast_path",
            "data": {"original": cmd},
        }

    # 5. LLM classification for ambiguous inputs
    return _classify_with_llm(cmd)


def _classify_with_llm(command: str) -> dict:
    """Use LLM to classify intent when fast-path doesn't match."""
    prompt = f"""Classify this user command into exactly one category.

User command: "{command}"

Categories:
- chat: casual conversation, questions, greetings, opinions
- tool_call: user wants ONE specific action (e.g., "take a screenshot", "what's the weather")
- multi_step: user wants a COMPLEX goal with MULTIPLE actions (e.g., "find AI jobs and save them", "create a folder and put my screenshots in it")
- system_command: direct PC control (open app, volume, brightness, lock)

Respond with ONLY a JSON object:
{{"intent": "<category>", "tool": "<tool_name_if_applicable>", "goal": "<full_goal_if_multi_step>"}}"""

    try:
        response = llm_router.query_llm(
            prompt=prompt,
            system_prompt="You are a command classifier. Output ONLY valid JSON, nothing else.",
            history=[],
            max_tokens=80,
        )

        # Parse JSON response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
            response = response.strip()

        data = json.loads(response)
        intent = data.get("intent", "chat")

        if intent not in ("chat", "tool_call", "multi_step", "system_command"):
            intent = "chat"

        logger.debug("LLM classified '%s' as: %s", command[:40], intent)
        return {
            "intent": intent,
            "confidence": "llm",
            "data": {
                "original": command,
                "tool": data.get("tool"),
                "goal": data.get("goal", command),
            },
        }

    except Exception as e:
        logger.warning("LLM intent classification failed: %s, defaulting to chat", e)
        return {
            "intent": "chat",
            "confidence": "fallback",
            "data": {"original": command},
        }


def route_command(command: str) -> dict:
    """Classify and return routing info for a command.

    This is the main entry point. Returns the intent classification
    with enough data for the caller to dispatch to the right handler.

    Args:
        command: User's text input.

    Returns:
        Intent classification dict (see classify_intent).
    """
    result = classify_intent(command)
    logger.info(
        "Routed: '%s' -> %s (%s)",
        command[:50], result["intent"], result["confidence"],
    )
    return result

