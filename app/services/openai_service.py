import logging
import os
from dataclasses import dataclass
from typing import Optional

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - the deterministic fallback still works
    OpenAI = None


logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_OUTPUT_TOKENS = 120
DEFAULT_TIMEOUT_SECONDS = 6.0
MAX_PROMPT_CHARS = 600
MAX_REPLY_CHARS = 480
MAX_REPLY_LINES = 4

SYSTEM_PROMPT = """You are a friendly, focused Irene Athletics Club coach.
Write one concise, practical coaching note suitable for WhatsApp.
Use only the result, pace, trend, and fatigue information supplied by the application.
Never invent facts, names, rankings, health conditions, or training history.
Do not diagnose injuries or medical conditions. Keep the response to at most 4 short lines.
Return only the coaching note, with no heading or markdown formatting."""

_client: Optional[object] = None
_client_api_key: Optional[str] = None


@dataclass(frozen=True)
class CoachingContext:
    distance_km: str
    time_text: str
    pace: Optional[str]
    trend: str
    fatigue: Optional[str] = None

    def to_prompt(self) -> str:
        fields = [
            f"Distance: {_clean_field(self.distance_km, 12)} km",
            f"Time: {_clean_field(self.time_text, 16)}",
            f"Pace: {_clean_field(self.pace or 'Unavailable', 24)}",
            f"Trend: {_clean_field(self.trend, 80)}",
        ]
        if self.fatigue:
            fields.append(f"Fatigue signal: {_clean_field(self.fatigue, 80)}")
        fields.append("Give short coaching feedback.")
        return "\n".join(fields)


def _clean_field(value: object, limit: int) -> str:
    """Keep model-facing fields single-line and bounded."""
    return " ".join(str(value).split())[:limit]


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        logger.warning("Invalid %s; using default", name)
        return default


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        logger.warning("Invalid %s; using default", name)
        return default


def _client_safe() -> Optional[object]:
    """Create and cache the client without making missing AI config fatal."""
    global _client, _client_api_key

    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key or OpenAI is None:
        return None

    if _client is not None and _client_api_key == key:
        return _client

    try:
        _client = OpenAI(
            api_key=key,
            timeout=_env_float(
                "OPENAI_TIMEOUT",
                DEFAULT_TIMEOUT_SECONDS,
                minimum=0.1,
            ),
            max_retries=1,
        )
        _client_api_key = key
        return _client
    except Exception:
        # Provider exceptions can contain request/configuration details.
        logger.error("Failed to initialize OpenAI client")
        return None


def coach_for_result(context: CoachingContext) -> str:
    """Generate feedback from the small, identity-free result context."""
    return coach_reply(context.to_prompt())


def coach_reply(prompt: str) -> str:
    """Return a safe coaching note, falling back on every provider failure."""
    safe_prompt = str(prompt or "")[:MAX_PROMPT_CHARS]
    client = _client_safe()

    if client is None:
        return fallback(safe_prompt)

    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            instructions=SYSTEM_PROMPT,
            input=safe_prompt,
            max_output_tokens=_env_int(
                "OPENAI_MAX_TOKENS",
                DEFAULT_MAX_OUTPUT_TOKENS,
                minimum=16,
            ),
            # Coaching notes contain no identity and do not need server-side
            # conversation state.
            store=False,
        )
        content = getattr(response, "output_text", None)
        normalized = _normalize_reply(content)
        if normalized:
            return normalized
        logger.warning("OpenAI returned no usable coaching text")
    except Exception:
        logger.error("OpenAI coaching request failed")

    return fallback(safe_prompt)


def _normalize_reply(content: object) -> str:
    """Make provider output predictable and safe for a WhatsApp message."""
    if not isinstance(content, str):
        return ""

    lines = []
    for raw_line in content.splitlines():
        line = " ".join(raw_line.strip().split())
        if line:
            lines.append(line)
        if len(lines) == MAX_REPLY_LINES:
            break

    return "\n".join(lines)[:MAX_REPLY_CHARS].strip()


def fallback(prompt: str) -> str:
    """Deterministic coaching when OpenAI is disabled or unavailable."""
    lowered = str(prompt or "").lower()

    if "fatigue" in lowered or "slowing down" in lowered:
        return "Solid effort. Recover well, keep the next run easy, and build back steadily."

    if "improving" in lowered:
        return "Great work. Your trend is moving the right way, so keep the pacing controlled and consistent."

    if "consistent" in lowered:
        return "Nice steady effort. Keep stacking consistent runs and look for small gains week by week."

    return "Good TT effort. Recover well and keep building one session at a time."
