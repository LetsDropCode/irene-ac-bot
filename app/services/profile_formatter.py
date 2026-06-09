def _format_seconds(seconds):
    if seconds is None:
        return "n/a"

    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


def format_profile(member, data):

    msg = "👤 *Your TT Profile*\n\n"

    msg += f"Name: {member['first_name']} {member['last_name']}\n"
    msg += f"Participation: {member.get('participation_type') or 'Not set'}\n\n"

    msg += f"🏃 Runs: {data['total_runs']}\n\n"

    # PBs
    msg += "🥇 *Personal Bests*\n"
    if data["pbs"]:
        for pb in data["pbs"]:
            msg += f"{pb['distance_text']}km — {_format_seconds(pb['best_seconds'])}\n"
    else:
        msg += "No PBs yet\n"

    # Recent runs
    msg += "\n📊 *Last 3 Runs*\n"
    if data["recent"]:
        for r in data["recent"]:
            msg += f"• {r['distance_text']} — {r['time_text']}\n"
    else:
        msg += "No runs yet\n"

    return msg.strip()
