def seconds_to_pace(seconds, distance_km):
    if not seconds or not distance_km:
        return None

    pace_sec = seconds / float(distance_km)
    mins = int(pace_sec // 60)
    secs = int(pace_sec % 60)

    return f"{mins}:{secs:02d}/km"


def detect_trend(recent_runs):
    if len(recent_runs) < 3:
        return "Not enough data yet."

    times = [r["seconds"] for r in recent_runs if r["seconds"]]

    if len(times) < 3:
        return "Not enough valid runs."

    # Compare last 3 runs
    if times[0] < times[1] < times[2]:
        return "🔥 Improving"
    elif times[0] > times[1] > times[2]:
        return "⚠️ Slowing down"
    else:
        return "➡️ Consistent"


def detect_fatigue(recent_runs):
    if len(recent_runs) < 3:
        return None

    times = [r["seconds"] for r in recent_runs if r["seconds"]]

    if len(times) < 3:
        return None

    # If last run is significantly worse (>5%)
    latest = times[0]
    avg_prev = sum(times[1:]) / len(times[1:])

    if latest > avg_prev * 1.05:
        return "😴 Possible fatigue detected"

    return None