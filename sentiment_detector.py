# -*- coding: utf-8 -*-

import logging
logger = logging.getLogger("meow.core")

"""
sentiment_detector.py — Lightweight zero-dependency sentiment scorer for MEOW
===============================================================================
Scores user commands as positive / negative / neutral using curated keyword
lexicons. No external packages required — pure Python.

Usage:
    from sentiment_detector import score_sentiment
    result = score_sentiment("you did great, thank you!")
    # result: {"compound": 0.72, "label": "positive"}
"""

# ── Positive signal words ─────────────────────────────────────────────────────
_POS = {
    "thanks", "thank", "great", "awesome", "amazing", "good", "nice",
    "excellent", "perfect", "brilliant", "love", "cool", "fantastic",
    "wonderful", "well done", "well", "done", "best", "yes", "yep",
    "sure", "correct", "right", "helpful", "smart", "genius", "wow",
    "impressive", "happy", "glad", "pleased", "appreciate", "beautiful",
    "superb", "incredible", "outstanding", "terrific", "lovely",
    "successful", "success", "worked", "works", "working", "fixed",
}

# ── Negative signal words ─────────────────────────────────────────────────────
_NEG = {
    "wrong", "bad", "stupid", "useless", "terrible", "awful", "worst",
    "hate", "broken", "error", "failed", "failure", "crash", "bug",
    "slow", "ugly", "lazy", "dumb", "idiot", "rubbish", "trash",
    "garbage", "annoying", "frustrated", "angry", "angry", "disappointed",
    "disappointing", "horrible", "pathetic", "poor", "mess", "messed",
    "no", "not", "never", "stop", "quit", "shut up", "be quiet",
    "useless", "pointless", "fix this", "again", "again?",
}

# ── Booster words (amplify score) ────────────────────────────────────────────
_BOOSTER = {
    "very", "really", "so", "extremely", "super", "totally",
    "absolutely", "completely", "incredibly", "utterly", "quite",
}

# ── Negation words (flip next word's score) ──────────────────────────────────
_NEGATE = {"not", "never", "no", "don't", "cant", "cannot", "won't", "doesn't"}


def score_sentiment(text: str) -> dict:
    """
    Score sentiment of text.
    Returns dict: {"compound": float [-1,1], "label": "positive"|"neutral"|"negative"}
    """
    if not text:
        return {"compound": 0.0, "label": "neutral"}

    words = text.lower().split()
    score = 0.0
    i = 0
    while i < len(words):
        w = words[i]
        # Check two-word phrases first
        bigram = f"{w} {words[i+1]}" if i + 1 < len(words) else ""
        is_negated = (i > 0 and words[i - 1] in _NEGATE)
        boost = 1.5 if (i > 0 and words[i - 1] in _BOOSTER) else 1.0

        if bigram in _POS:
            score += 1.0 * boost * (-1 if is_negated else 1)
            i += 2
            continue
        if bigram in _NEG:
            score -= 1.0 * boost * (-1 if is_negated else 1)
            i += 2
            continue

        if w in _POS:
            score += 1.0 * boost * (-1 if is_negated else 1)
        elif w in _NEG:
            score -= 1.0 * boost * (-1 if is_negated else 1)
        i += 1

    # Normalise to [-1, 1]
    word_count = max(len(words), 1)
    compound = max(-1.0, min(1.0, score / (word_count ** 0.5)))

    if compound >= 0.1:
        label = "positive"
    elif compound <= -0.1:
        label = "negative"
    else:
        label = "neutral"

    return {"compound": round(compound, 4), "label": label}


if __name__ == "__main__":
    tests = [
        "thanks that was great",
        "you are so stupid and useless",
        "open chrome",
        "that's not right at all",
        "you did really well done",
        "this is broken again",
    ]
    for t in tests:
        r = score_sentiment(t)
        logger.info(f"  {r['label']:8s} {r['compound']:+.3f}  '{t}'")