# app/services/leaderboard_formatter.py
def format_leaderboard(rows):

    if not rows:
        return "🏁 No results yet."

    msg = "🏁 *Tonight's TT Leaderboard*\n\n"

    current_distance = None

    medals = {
        1: "🥇",
        2: "🥈",
        3: "🥉"
    }

    for r in rows:

        distance = r["distance_text"]

        # New section per distance
        if distance != current_distance:
            msg += f"\n📏 *{distance}*\n"
            current_distance = distance

        position = r["position"]
        medal = medals.get(position, f"{position}.")

        msg += f"{medal} {r['first_name']} {r['last_name']} – {r['time_text']}\n"

    return msg.strip()