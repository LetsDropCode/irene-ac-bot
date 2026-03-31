def format_profile(member, data):

    msg = "👤 *Your TT Profile*\n\n"

    msg += f"🏃 Runs: {data['total_runs']}\n\n"

    # PBs
    msg += "🥇 *Personal Bests*\n"
    if data["pbs"]:
        for pb in data["pbs"]:
            msg += f"{pb['distance_text']} — {pb['best_seconds']}s\n"
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