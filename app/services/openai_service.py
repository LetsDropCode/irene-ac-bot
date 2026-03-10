import os
import logging
from typing import Optional, TYPE_CHECKING

# ─────────────────────────────────────────────
# Optional typing import (removes Pylance warning)
# ─────────────────────────────────────────────
if TYPE_CHECKING:
    from openai import OpenAI

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT", "8"))
MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "120"))

SYSTEM_PROMPT = """
You are a friendly but focused athletics club coach.
Tone: Encouraging, clear, WhatsApp-friendly.
Never invent data. Keep replies under 4 lines.
"""

logger = logging.getLogger("openai_service")

_client: Optional["OpenAI"] = None


# ─────────────────────────────────────────────
# Client factory (cached)
# ─────────────────────────────────────────────
def _client_safe() -> Optional["OpenAI"]:
    global _client

    if _client:
        return _client

    key = os.getenv("OPENAI_API_KEY")
    if not key or OpenAI is None:
        logger.warning("OpenAI client unavailable (missing key or package)")
        return None

    _client = OpenAI(api_key=key, timeout=TIMEOUT_SECONDS)
    return _client


# ─────────────────────────────────────────────
# Main reply function
# ─────────────────────────────────────────────
def coach_reply(prompt: str) -> str:
    client = _client_safe()
    if not client:
        return fallback(prompt)

    try:
        res = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=MAX_TOKENS,
        )

        # Safe extraction
        if not res or not res.choices:
            logger.warning("OpenAI empty response")
            return fallback(prompt)

        content = res.choices[0].message.content
        if not content:
            logger.warning("OpenAI blank message")
            return fallback(prompt)

        return content.strip()

    except Exception as e:  # never crash webhook
        logger.exception("OpenAI call failed: %s", e)
        return fallback(prompt)


# ─────────────────────────────────────────────
# Deterministic fallback logic
# ─────────────────────────────────────────────
def fallback(prompt: str) -> str:
    p = prompt.lower()

    if "welcome" in p:
        return "👋 Welcome! Please send tonight’s TT code to continue."

    if "participate" in p or "how do you usually" in p:
        return "👍 How do you usually participate?"

    if "distance" in p:
        return "👍 Select your TT distance."

    if "time" in p:
        return "⏱ Please send your time (mm:ss or hh:mm:ss)."

    if "confirm" in p or "recorded" in p or "congratulate" in p:
        return "🔥 Well done! Your TT is recorded."

    return ""