import os
from typing import Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

SYSTEM_PROMPT = """
You are a friendly but focused athletics club coach.
Tone: Encouraging, clear, WhatsApp-friendly.
Never invent data. Keep replies under 4 lines.
"""

_client: Optional["OpenAI"] = None

def _client_safe():
    global _client
    if _client:
        return _client

    key = os.getenv("OPENAI_API_KEY")
    if not key or not OpenAI:
        return None

    _client = OpenAI(api_key=key)
    return _client

def coach_reply(prompt: str) -> str:
    client = _client_safe()
    if not client:
        return fallback(prompt)

    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        return res.choices[0].message.content.strip()
    except Exception:
        return fallback(prompt)

def fallback(prompt: str) -> str:
    if "welcome" in prompt.lower():
        return "👋 Welcome! Please send tonight’s TT code to continue."
    if "distance" in prompt.lower():
        return "👍 Select your TT distance."
    if "time" in prompt.lower():
        return "⏱ Please send your time (mm:ss or hh:mm:ss)."
    if "congratulate" in prompt.lower():
        return "🔥 Well done! Your TT is recorded."
    return "✅ Got it!"