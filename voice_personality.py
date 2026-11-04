"""
voice_personality.py — Response Style Presets for MEOW
=======================================================
Manages Meow's conversational style. The active style adjusts the LLM
system prompt and max_tokens so responses feel natural and appropriately
sized. Changed via voice ("be more concise") or Config tab.

Styles:
    casual      — friendly, natural, medium length (default)
    concise     — short & punchy, under 2 sentences
    professional — formal, thorough, structured
"""

import memory_manager

# ---------------------------------------------------------------------------
# Style definitions
# ---------------------------------------------------------------------------
STYLES = {
    "casual": {
        "label": "Casual",
        "max_tokens": 150,
        "style_hint": "Respond naturally and conversationally, like a friendly assistant. Keep responses warm and human.",
    },
    "concise": {
        "label": "Concise",
        "max_tokens": 80,
        "style_hint": "Be extremely brief. Answer in 1-2 sentences maximum. No fluff, no preamble.",
    },
    "professional": {
        "label": "Professional",
        "max_tokens": 250,
        "style_hint": "Respond formally and thoroughly. Structure your answer clearly. Use precise language.",
    },
}

_DEFAULT_STYLE = "casual"

# ---------------------------------------------------------------------------
# Getters / Setters
# ---------------------------------------------------------------------------
def get_active_style() -> str:
    """Return the currently saved style key (e.g. 'casual')."""
    mem = memory_manager.load_memory()
    style = mem.get("voice_style", _DEFAULT_STYLE)
    return style if style in STYLES else _DEFAULT_STYLE


def set_active_style(style_key: str) -> str:
    """Persist a new style and return a confirmation message."""
    if style_key not in STYLES:
        return f"Unknown style '{style_key}'. Available: {', '.join(STYLES.keys())}."
    mem = memory_manager.load_memory()
    mem["voice_style"] = style_key
    memory_manager.save_memory(mem)
    label = STYLES[style_key]["label"]
    return f"Got it! Switching to {label} mode."


def get_max_tokens() -> int:
    """Return max_tokens for the current style."""
    return STYLES[get_active_style()]["max_tokens"]


def get_style_system_suffix() -> str:
    """Return a style instruction to append to the system prompt."""
    return "\n\n" + STYLES[get_active_style()]["style_hint"]


def apply_style_to_system(base_system: str) -> str:
    """Append the active style hint to a base system prompt."""
    return base_system + get_style_system_suffix()


# ---------------------------------------------------------------------------
# Voice command parser
# ---------------------------------------------------------------------------
_CONCISE_TRIGGERS  = ["be more concise", "talk less", "shorter responses", "stop rambling", "keep it brief", "be brief"]
_CASUAL_TRIGGERS   = ["be casual", "relax", "be friendly", "normal mode", "casual mode"]
_PROFESSIONAL_TRIGGERS = ["be professional", "formal mode", "professional mode", "be formal", "give me detail", "detailed responses"]


def detect_style_change(command: str):
    """
    Check if the user's command requests a style change.
    Returns (new_style_key, confirmation_message) or (None, None).
    """
    cmd = command.strip().lower()
    if any(t in cmd for t in _CONCISE_TRIGGERS):
        return "concise", set_active_style("concise")
    if any(t in cmd for t in _CASUAL_TRIGGERS):
        return "casual", set_active_style("casual")
    if any(t in cmd for t in _PROFESSIONAL_TRIGGERS):
        return "professional", set_active_style("professional")
    return None, None
