"""Deterministic, same-distance TT pace comparisons."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.db import get_cursor


def _positive_decimal(value):
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


def _rounded_seconds(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _duration(seconds: int) -> str:
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes}:{remainder:02d}"


def get_previous_comparable_runs(member_id: int, current: dict, limit: int = 3):
    """Fetch older completed TT runs at the current result's numeric distance."""
    distance = _positive_decimal(current.get("distance_text"))
    if not current.get("id") or not current.get("event_date") or distance is None:
        return []
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT id, event_date, distance_text, seconds
            FROM submissions
            WHERE member_id = %s AND activity = 'TT' AND status = 'COMPLETE'
              AND (mode = 'RUN' OR mode IS NULL)
              AND CASE WHEN distance_text ~ '^[0-9]+([.][0-9]+)?$'
                  THEN distance_text::numeric ELSE NULL END = %s
              AND seconds > 0
              AND (event_date, id) < (%s, %s)
            ORDER BY event_date DESC, id DESC
            LIMIT %s
            """,
            (member_id, distance, current["event_date"], current["id"], limit),
        )
        return cur.fetchall()


def pace_comparison_lines(current: dict, previous_runs: list[dict]) -> list[str]:
    """Compare this run with the last and two overlapping three-run windows.

    Runs are newest-first, all at the same distance. The latest window is this
    result plus two older results; the preceding window is those three older
    results. Decimal arithmetic and half-up rounding make output reproducible.
    """
    distance = _positive_decimal(current.get("distance_text"))
    current_seconds = _positive_decimal(current.get("seconds"))
    if distance is None or current_seconds is None:
        return []
    prior = [
        value for run in previous_runs
        if _positive_decimal(run.get("distance_text")) == distance
        if (value := _positive_decimal(run.get("seconds"))) is not None
    ][:3]
    if not prior:
        return [f"Compared with your last {current['distance_text']} km TT: first comparable result."]

    change = _rounded_seconds(abs(current_seconds - prior[0]))
    direction = "faster" if current_seconds < prior[0] else "slower" if current_seconds > prior[0] else "the same time"
    if direction == "the same time":
        comparison = f"Compared with your last {current['distance_text']} km TT: the same time."
    else:
        comparison = (
            f"Compared with your last {current['distance_text']} km TT: "
            f"{_duration(change)} {direction}."
        )
    lines = [comparison]
    if len(prior) < 3:
        lines.append("Rolling pace trend: needs four comparable TT results.")
        return lines

    latest_average = (current_seconds + prior[0] + prior[1]) / (3 * distance)
    previous_average = sum(prior) / (3 * distance)
    latest_pace = _rounded_seconds(latest_average)
    previous_pace = _rounded_seconds(previous_average)
    if latest_pace < previous_pace:
        movement = f"improving by {_duration(previous_pace - latest_pace)}/km"
    elif latest_pace > previous_pace:
        movement = f"slowing by {_duration(latest_pace - previous_pace)}/km"
    else:
        movement = "steady"
    lines.append(
        f"Rolling 3-TT pace: {_duration(latest_pace)}/km ({movement} vs prior 3-TT window)."
    )
    return lines
