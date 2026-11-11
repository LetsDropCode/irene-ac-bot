"""Calendar-year TT views. Results stay in place; event_date owns the season."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.db import get_cursor
from app.services.profile_formatter import _format_seconds

SA_TZ = ZoneInfo("Africa/Johannesburg")
HISTORY_PAGE_SIZE = 8


def current_season(now=None):
    now = now or datetime.now(SA_TZ)
    if isinstance(now, datetime):
        now = now.replace(tzinfo=SA_TZ) if now.tzinfo is None else now.astimezone(SA_TZ)
    return now.year


def season_bounds(year):
    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year < 9999:
        raise ValueError("Invalid season year")
    return date(year, 1, 1), date(year + 1, 1, 1)


def get_season_summary(member_id, year=None):
    year = current_season() if year is None else year
    start, end = season_bounds(year)
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT COUNT(*) AS total,
                COUNT(*) FILTER (WHERE mode = 'WORKOUT' OR (mode IS NULL
                    AND (distance_text IS NULL OR distance_text = ''))) AS walks
            FROM submissions
            WHERE member_id = %s AND activity = 'TT' AND status = 'COMPLETE'
              AND event_date >= %s AND event_date < %s
        """, (member_id, start, end))
        totals = cur.fetchone()
        cur.execute("""
            SELECT COUNT(DISTINCT event_date) AS total FROM attendance
            WHERE member_id = %s AND event = 'TT'
              AND event_date >= %s AND event_date < %s
        """, (member_id, start, end))
        attendance = cur.fetchone()["total"]
        cur.execute("""
            SELECT distance_text, MIN(seconds) AS best_seconds
            FROM submissions
            WHERE member_id = %s AND activity = 'TT' AND status = 'COMPLETE'
              AND event_date >= %s AND event_date < %s
              AND (mode = 'RUN' OR mode IS NULL) AND seconds > 0
              AND distance_text IS NOT NULL AND distance_text <> ''
            GROUP BY distance_text ORDER BY distance_text
        """, (member_id, start, end))
        return {"year": year, "total": totals["total"], "walks": totals["walks"],
                "attendance": attendance, "pbs": cur.fetchall()}


def get_member_seasons(member_id):
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT DISTINCT EXTRACT(YEAR FROM event_date)::int AS year
            FROM (
                SELECT event_date FROM submissions
                WHERE member_id = %s AND activity = 'TT' AND status = 'COMPLETE'
                UNION
                SELECT event_date FROM attendance WHERE member_id = %s AND event = 'TT'
            ) events ORDER BY year DESC
        """, (member_id, member_id))
        return [row["year"] for row in cur.fetchall()]


def get_member_history(member_id, year, page=1):
    start, end = season_bounds(year)
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 10000:
        raise ValueError("Invalid history page")
    with get_cursor(commit=False) as cur:
        # Include attendance without a completed result; pending drafts do not
        # become achievements. Ownership is enforced on both sides of the join.
        cur.execute("""
            WITH results AS (
                SELECT id, member_id, event_date, distance_text, time_text, mode
                FROM submissions
                WHERE member_id = %s AND activity = 'TT' AND status = 'COMPLETE'
                  AND event_date >= %s AND event_date < %s
            ), checkins AS (
                SELECT member_id, event_date FROM attendance
                WHERE member_id = %s AND event = 'TT'
                  AND event_date >= %s AND event_date < %s
            )
            SELECT r.id, COALESCE(r.event_date, a.event_date) AS event_date,
                   r.distance_text, r.time_text, r.mode
            FROM results r FULL JOIN checkins a
                ON r.member_id = a.member_id AND r.event_date = a.event_date
            ORDER BY COALESCE(r.event_date, a.event_date) DESC, r.id DESC NULLS LAST
            LIMIT %s OFFSET %s
        """, (member_id, start, end, member_id, start, end,
              HISTORY_PAGE_SIZE + 1, (page - 1) * HISTORY_PAGE_SIZE))
        rows = cur.fetchall()
        return rows[:HISTORY_PAGE_SIZE], len(rows) > HISTORY_PAGE_SIZE


def format_season_summary(data):
    year = data["year"]
    lines = [f"🌳 *Your {year} TT season*", "", f"TT check-ins: {data['attendance']}",
             f"Completed activities: {data['total']}", f"Walks / workouts: {data['walks']}",
             "", "🥇 *Season bests*"]
    lines.extend(f"{pb['distance_text']}km — {_format_seconds(pb['best_seconds'])}" for pb in data["pbs"])
    if not data["pbs"]:
        lines.append("Your first timed run this season will set your season best.")
    if not data["total"]:
        lines.extend(["", "Your first completed TT this season will appear here."])
    lines.extend(["", f"Send MY HISTORY {year} for this season's results.",
                  "MY HISTORY — previous seasons · MY PBS — all-time personal bests",
                  "MY STREAK — lifetime attendance and weekly streak"])
    return "\n".join(lines)


def format_history(year, page, rows, has_more):
    lines = [f"📚 *Your {year} TT history · page {page}*", ""]
    shortened = False
    for row in rows:
        if row["id"] is None:
            detail = "Checked in · no completed result"
        elif row.get("distance_text"):
            detail = f"{row['distance_text']}km — {row.get('time_text') or 'Time not recorded'}"
        else:
            # Keep long free-text workouts within a WhatsApp-sized page.
            note = row.get("time_text") or "Completed"
            shortened = shortened or len(note) > 200
            detail = f"Walk / workout — {note[:200]}" + ("…" if len(note) > 200 else "")
        lines.append(f"• {row['event_date']}: {detail}")
    if not rows:
        lines.append("No TT activities on this page.")
    if shortened:
        lines.append("Long workout notes are shortened here. Send MY DATA for full stored details.")
    lines.append("")
    if has_more:
        lines.append(f"Next: MY HISTORY {year} PAGE {page + 1}")
    if page > 1:
        lines.append(f"Previous: MY HISTORY {year} PAGE {page - 1}")
    lines.extend([f"SEASON {year} — season summary", "MY HISTORY — choose a year · MENU — main menu"])
    return "\n".join(lines)
