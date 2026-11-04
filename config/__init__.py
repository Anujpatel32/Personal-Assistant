"""
config — Centralised configuration for the MEOW Personal Assistant.

Quick start:
    from config import settings

    key = settings.gemini_api_key
    settings.reload()           # re-read .env + memory.json
    settings.save_api_keys()    # write keys back to memory.json
"""

from config.settings import settings

__all__ = ["settings"]
