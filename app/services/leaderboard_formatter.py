def format_leaderboard(event, distance, rows):
    if not rows:
        return "📭 No submissions yet this week."

    lines = [f"🏆 *{event} WEEKLY LEADERBOARD* ({distance})\n"]

    for idx, r in enumerate(rows, start=1):
        name = f"{r['first_name']} {r['last_name'][0]}."
        lines.append(f"{idx}️⃣ {name} — {r['time']}")

    return "\n".join(lines)