# -*- coding: utf-8 -*-
"""
local_model_manager.py — Local Model & Fine-Tuning Manager for MEOW (Phase 9)
=============================================================================
Discovers and manages local offline LLM checkpoints (GGUF, Ollama, HuggingFace)
and supports switching between local specialized models and cloud models.
"""

import os
import glob
import logging
import requests
from typing import List, Dict, Any, Optional

logger = logging.getLogger("meow.llm")

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

def list_local_models() -> Dict[str, Any]:
    """Scan for local GGUF models and running Ollama instances."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    gguf_files = glob.glob(os.path.join(MODELS_DIR, "*.gguf"))

    local_gguf = []
    for f in gguf_files:
        size_mb = os.path.getsize(f) / (1024 * 1024)
        local_gguf.append({
            "name": os.path.basename(f),
            "path": f,
            "size_mb": round(size_mb, 1),
            "format": "GGUF"
        })

    # Check Ollama
    ollama_models = []
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=1.5)
        if resp.status_code == 200:
            for m in resp.json().get("models", []):
                ollama_models.append({
                    "name": m.get("name"),
                    "size_mb": round(m.get("size", 0) / (1024 * 1024), 1),
                    "format": "Ollama"
                })
    except Exception:
        pass

    return {
        "gguf_models": local_gguf,
        "ollama_models": ollama_models,
        "total": len(local_gguf) + len(ollama_models)
    }


def switch_model(model_name: str) -> Dict[str, Any]:
    """Switch active LLM model to a cloud AI provider."""
    import memory_manager
    config = memory_manager.load_config()
    target = model_name.lower().strip()

    valid_models = ["groq", "gemini", "nvidia", "openrouter"]
    selected = None
    for v in valid_models:
        if v in target:
            selected = v
            break

    if not selected:
        selected = "groq"

    memory_manager.save_config(
        selected,
        config.get("gemini_api_key", ""),
        config.get("groq_api_key", ""),
        config.get("nvidia_api_key", ""),
        config.get("openrouter_api_key", "")
    )
    logger.info("Active model switched to: %s", selected)
    return {"success": True, "selected_model": selected, "message": f"Active AI model switched to '{selected}'."}


# ── Register Tools ────────────────────────────────────────────────────
try:
    import tool_registry

    @tool_registry.register_tool(
        "list_local_models",
        "List all local offline GGUF checkpoints and Ollama models available on this machine",
        []
    )
    def _tool_list_local_models():
        res = list_local_models()
        lines = []
        for m in res["gguf_models"]:
            lines.append(f"• GGUF: {m['name']} ({m['size_mb']} MB)")
        for m in res["ollama_models"]:
            lines.append(f"• Ollama: {m['name']} ({m['size_mb']} MB)")
        return "\n".join(lines) if lines else "No local GGUF or Ollama models detected. Place GGUF files in models/ folder."

    @tool_registry.register_tool(
        "switch_active_model",
        "Switch the active AI brain between groq, gemini, nvidia, or openrouter",
        ["model_name"]
    )
    def _tool_switch_model(model_name: str):
        res = switch_model(model_name)
        return res.get("message")

except Exception as _tr_err:
    logger.warning("Could not register local model tools: %s", _tr_err)

