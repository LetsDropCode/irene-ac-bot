import math


def seconds_to_pace(seconds, distance_km):
    if not seconds or not distance_km:
        return None

    pace_sec = seconds / float(distance_km)
    mins = int(pace_sec // 60)
    secs = int(pace_sec % 60)

    return f"{mins}:{secs:02d}/km"


def _positive_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _comparable_times(recent_runs, distance_km=None):
    """Keep newest-first history for one distance; unknown distances never match.

    Callers may supply the confirmed result's distance. Progress defaults to
    the latest run's distance. Both signals require three valid matching runs
    in the supplied recent history, including the run being compared.
    """
    if not recent_runs:
        return []
    if distance_km is None:
        distance_km = recent_runs[0].get("distance_text")
    distance = _positive_number(distance_km)
    if distance is None:
        return []

    times = []
    for run in recent_runs:
        if _positive_number(run.get("distance_text")) != distance:
            continue
        seconds = _positive_number(run.get("seconds"))
        if seconds is not None:
            times.append(seconds)
    return times


def detect_trend(recent_runs, distance_km=None):
    times = _comparable_times(recent_runs, distance_km)

    if len(times) < 3:
        return "Not enough comparable runs yet."

    # Compare the latest three valid runs over the same distance.
    if times[0] < times[1] < times[2]:
        return "🔥 Improving"
    elif times[0] > times[1] > times[2]:
        return "⚠️ Slowing down"
    else:
        return "➡️ Consistent"


def detect_fatigue(recent_runs, distance_km=None):
    times = _comparable_times(recent_runs, distance_km)

    if len(times) < 3:
        return None

    # Compare only against previous runs over the same distance (>5%).
    latest = times[0]
    avg_prev = sum(times[1:]) / len(times[1:])

    if latest > avg_prev * 1.05:
        return "😴 Possible fatigue detected"

    return None
