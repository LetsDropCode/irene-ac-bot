from app.services.insight_services import detect_trend, seconds_to_pace
from app.services.profile_formatter import _format_seconds

MILESTONES = (1, 5, 10, 25, 50, 100)


def _next_milestone(total: int):
    for milestone in MILESTONES:
        if total < milestone:
            return milestone

    return None


def _format_latest(latest):
    if not latest:
        return "No TT activities logged yet."

    distance = latest.get("distance_text")
    time_text = latest.get("time_text")

    if distance:
        pace = seconds_to_pace(latest.get("seconds"), distance)
        detail = f"{distance}km — {time_text}"
        if pace:
            detail += f" ({pace})"
        return detail

    return time_text or "Workout logged"


def _is_walker(member: dict) -> bool:
    return member.get("participation_type") == "WALKER"


def _format_walker_progress(first_name: str, total: int, latest) -> str:
    lines = [
        f"🚶 *{first_name}, your walking progress*",
        "",
        f"Activities logged: {total}",
        f"Latest: {_format_latest(latest)}",
    ]

    next_milestone = _next_milestone(total)
    if next_milestone:
        remaining = next_milestone - total
        lines.append(f"Next milestone: {next_milestone} walks ({remaining} to go)")
    else:
        lines.append("Next milestone: keep showing up strong")

    if total == 0:
        lines.extend(["", "Log your next walk after TT and I’ll track your consistency here."])
    elif total < 5:
        lines.extend(["", "Nice start. Keep stacking those walks."])
    else:
        lines.extend(["", "Great consistency. Your walking streak is becoming part of the rhythm."])

    return "\n".join(lines).strip()


def format_progress(member: dict, data: dict) -> str:
    first_name = member.get("first_name") or "Runner"
    total = data.get("total_runs") or 0
    latest = data.get("latest")
    recent = data.get("recent") or []
    pbs = data.get("pbs") or []

    if _is_walker(member):
        return _format_walker_progress(first_name, total, latest)

    lines = [
        f"📈 *{first_name}, your progress*",
        "",
        f"TT activities: {total}",
        f"Latest: {_format_latest(latest)}",
    ]

    next_milestone = _next_milestone(total)
    if next_milestone:
        remaining = next_milestone - total
        lines.append(f"Next milestone: {next_milestone} activities ({remaining} to go)")
    else:
        lines.append("Next milestone: keep building that legacy")

    if pbs:
        lines.extend(["", "🥇 *PBs*"])
        for pb in pbs:
            lines.append(f"{pb['distance_text']}km — {_format_seconds(pb['best_seconds'])}")

    if recent:
        lines.extend(["", f"Trend: {detect_trend(recent)}"])

    return "\n".join(lines).strip()
