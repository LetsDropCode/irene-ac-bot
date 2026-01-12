# app/services/openai_service.py

import os
from typing import Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # Safety fallback


SYSTEM_PROMPT = """
You are a friendly but focused athletics club coach.
Tone:
- Encouraging
- Clear
- WhatsApp-friendly
- South African running culture
Rules:
- Never invent data
- Never override system decisions
- Keep replies under 4 lines
"""


_client: Optional["OpenAI"] = None


def _get_client() -> Optional["OpenAI"]:
    global _client

    if _client is not None:
        return _client

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or not OpenAI:
        return None

    _client = OpenAI(api_key=api_key)
    return _client


def coach_reply(prompt: str) -> str:
    """
    Returns an AI-generated coach message if OpenAI is configured.
    Falls back to safe static messaging if not.
    """
    client = _get_client()

    if not client:
        # 🔒 Phase 1 fallback (never crash)
        return fallback_message(prompt)

    try:
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()

    except Exception:
        # Absolute safety net
        return fallback_message(prompt)


# ─────────────────────────────────────────────
# PHASE 1 FALLBACK MESSAGES
# ─────────────────────────────────────────────

def fallback_message(prompt: str) -> str:
    prompt_lower = prompt.lower()

    if "welcome" in prompt_lower:
        return (
            "👋 Welcome to tonight’s Time Trial!\n\n"
            "Please send the TT code from your run leader to continue."
        )

    if "distance" in prompt_lower:
        return "👍 Great! Please select your TT distance."

    if "time" in prompt_lower:
        return "⏱ Please send your time (mm:ss or hh:mm:ss)."

    if "congratulate" in prompt_lower:
        return "🔥 Well done! Your Time Trial has been recorded."

    if "edit" in prompt_lower:
        return "⏱ Editing is closed for tonight."

    return "✅ Got it!"