# -*- coding: utf-8 -*-
"""
voice_clone.py — Voice Cloning & Custom Speech Profiles for MEOW (Phase 9)
==========================================================================
Enables:
  1. ElevenLabs Instant Voice Cloning via user audio samples (.wav/.mp3)
  2. Kokoro custom voice blending profile generator
  3. Registered agent tools for dynamic voice personalization
"""

import os
import json
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger("meow.voice")


def clone_voice_elevenlabs(audio_path: str, voice_name: str, description: str = "Cloned MEOW voice") -> Dict[str, Any]:
    """Clone a voice using an audio sample via ElevenLabs Voice Add API."""
    import memory_manager
    config = memory_manager.load_config()
    api_key = config.get("elevenlabs_api_key", "") or os.environ.get("ELEVENLABS_API_KEY", "")

    if not api_key:
        return {"success": False, "error": "ElevenLabs API key is not configured in settings."}

    if not os.path.exists(audio_path):
        return {"success": False, "error": f"Audio sample file '{audio_path}' not found."}

    url = "https://api.elevenlabs.io/v1/voices/add"
    headers = {"xi-api-key": api_key}
    data = {
        "name": voice_name,
        "description": description
    }

    try:
        with open(audio_path, "rb") as f:
            files = {"files": (os.path.basename(audio_path), f, "audio/mpeg")}
            response = requests.post(url, headers=headers, data=data, files=files, timeout=30)

        if response.status_code in [200, 201]:
            resp_data = response.json()
            voice_id = resp_data.get("voice_id")
            logger.info("Voice '%s' cloned successfully with ID: %s", voice_name, voice_id)
            return {"success": True, "voice_id": voice_id, "name": voice_name, "message": f"Voice '{voice_name}' successfully cloned! Voice ID: {voice_id}"}
        else:
            return {"success": False, "error": f"API error ({response.status_code}): {response.text}"}
    except Exception as e:
        logger.error("ElevenLabs voice clone failed: %s", e)
        return {"success": False, "error": str(e)}


def create_kokoro_blend(blend_name: str, weights: Dict[str, float]) -> Dict[str, Any]:
    """Save a custom Kokoro multi-speaker blend profile to configuration."""
    import memory_manager
    config = memory_manager.load_config()
    normalized = {}
    total = sum(weights.values())
    if total > 0:
        normalized = {k: round(v / total, 3) for k, v in weights.items()}

    config["kokoro_voice"] = "custom_mix"
    config["kokoro_voice_mix"] = normalized
    memory_manager.save_config(
        config.get("selected_model", "gemini"),
        config.get("gemini_api_key", ""),
        config.get("groq_api_key", ""),
        config.get("nvidia_api_key", ""),
        config.get("openrouter_api_key", ""),
        selected_tts="kokoro",
        elevenlabs_api_key=config.get("elevenlabs_api_key", ""),
        elevenlabs_voice_id=config.get("elevenlabs_voice_id", ""),
        kokoro_voice="custom_mix",
        kokoro_voice_mix=normalized
    )
    return {"success": True, "blend": normalized, "message": f"Created custom Kokoro voice blend '{blend_name}': {normalized}"}


# ── Register Tools ────────────────────────────────────────────────────
try:
    import tool_registry

    @tool_registry.register_tool(
        "clone_voice",
        "Clone a voice from an audio file (.mp3/.wav) and create a custom voice profile",
        ["audio_path", "voice_name"]
    )
    def _tool_clone_voice(audio_path: str, voice_name: str):
        res = clone_voice_elevenlabs(audio_path, voice_name)
        return res.get("message") or res.get("error")

    @tool_registry.register_tool(
        "create_voice_blend",
        "Create a custom blended voice profile (e.g. 70% Sarah, 30% Bella)",
        ["blend_name"]
    )
    def _tool_blend_voice(blend_name: str, sarah_weight: float = 0.7, bella_weight: float = 0.3):
        res = create_kokoro_blend(blend_name, {"af_sarah": sarah_weight, "af_bella": bella_weight})
        return res.get("message")

except Exception as _tr_err:
    logger.warning("Could not register voice clone tools: %s", _tr_err)

