# app/services/leaderboard_formatter.py
def format_full_leaderboard(runners, walkers):

    msg = ""

    # ───────── RUNNERS ─────────
    if runners:
        msg += "🏁 *Tonight's TT Leaderboard*\n\n"

        current_distance = None
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}

        for r in runners:

            distance = r["distance_text"]

            if distance != current_distance:
                msg += f"\n📏 *{distance} km*\n"
                current_distance = distance

            medal = medals.get(r["position"], f"{r['position']}.")
            msg += f"{medal} {r['first_name']} {r['last_name']} – {r['time_text']}\n"

    else:
        msg += "🏁 No runner results yet.\n"

    # ───────── WALKERS ─────────
    if walkers:
        msg += "\n\n🚶 *Walker Activity*\n\n"

        for w in walkers:
            detail = w["time_text"] if w["time_text"] else "Workout logged"
            msg += f"• {w['first_name']} {w['last_name']} — {detail}\n"

    return msg.strip()

def format_season_pb_leaderboard(rows):

    if not rows:
        return "🏆 No season results yet."

    msg = "🏆 *Season PB Leaderboard*\n\n"

    current_distance = None
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for r in rows:

        if r["distance_text"] != current_distance:
            msg += f"\n📏 *{r['distance_text']} km*\n"
            current_distance = r["distance_text"]

        medal = medals.get(r["position"], f"{r['position']}.")

        mins = int(r["best_seconds"] // 60)
        secs = int(r["best_seconds"] % 60)
        time_str = f"{mins}:{secs:02d}"

        msg += f"{medal} {r['first_name']} {r['last_name']} — {time_str}\n"

    return msg.strip()

def format_fastest_improver(row):
    if not row:
        return ""

    mins = row["improvement"] // 60
    secs = row["improvement"] % 60

    return f"\n\n🚀 *Most Improved*\n{row['first_name']} {row['last_name']} ({row['distance_text']}km) -{mins}:{secs:02d}"

def format_winners(rows):
    if not rows:
        return ""

    msg = "\n\n🏆 *TT Winners*\n\n"

    for r in rows:
        msg += f"{r['distance_text']}km — {r['first_name']} {r['last_name']} ({r['time_text']})\n"

    return msg.strip()

def format_user_summary(summary, position_rows):
    if not summary:
        return ""

    msg = "\n\n📊 *Your TT Summary*\n\n"
    msg += f"{summary['distance_text']}km — {summary['time_text']}\n"

    for p in position_rows:
        if p["distance_text"] == summary["distance_text"]:
            msg += f"📈 Rank: #{p['position']}\n"

    return msg.strip()