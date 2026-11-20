"""Deterministic approved-calendar digests; one transactional revision per change.

No TT mutations, provider calls, draft consumption or in-process scheduler. All dates
are programme dates, not an unbounded recurring schedule.
"""

import hashlib
import json
import os
import re
from datetime import date, datetime, time, timedelta

from psycopg2 import Error as DatabaseError
from psycopg2.extras import Json

from app.db import get_cursor
from app.services import festive_service as domain
from app.services.festive_config import enabled, flag

WEEKS = tuple(date(2026, 12, d) for d in (7, 14, 21, 28))
END = date(2027, 1, 3)
FIELDS = (
    "title",
    "start_time",
    "meeting_point",
    "location_description",
    "maps_url",
    "route_url",
    "distances",
    "walkers_welcome",
    "coffee_arrangements",
    "route_description",
    "pace_information",
    "safety_notes",
    "latitude",
    "longitude",
)
LABELS = {
    "status": "Run status",
    "hosts": "Host / co-host",
    "title": "Run title",
    "start_time": "Start time",
    "meeting_point": "Meeting point",
    "location_description": "Meeting notes",
    "maps_url": "Map link",
    "route_url": "Route link",
    "distances": "Distances",
    "walkers_welcome": "Walkers",
    "coffee_arrangements": "Coffee afterwards",
    "route_description": "Route notes",
    "pace_information": "Pace",
    "safety_notes": "Safety notes",
    "latitude": "Map pin",
    "longitude": "Map pin",
}
HEADER = (
    "🎄🏃‍♀️ *YOUR FESTIVE RUNS THIS WEEK!* 🏃‍♂️🎄\n"
    "*IRENE AC FESTIVE RUN ADVENTURES*\n"
    "Different hosts. Different routes. One Irene family. 🩵"
)


def active(phone=None):
    return enabled(phone) and flag("FESTIVE_WEEKLY_DIGEST_ENABLED")


def settings():
    zone = os.getenv("FESTIVE_WEEKLY_DIGEST_TIMEZONE", "Africa/Johannesburg")
    clock = os.getenv("FESTIVE_WEEKLY_DIGEST_TIME", "06:00")
    if zone != "Africa/Johannesburg" or not re.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d", clock
    ):
        raise domain.FestiveError(
            "Weekly schedule requires Africa/Johannesburg and HH:MM."
        )
    # Fail closed: a flag alone cannot authorize an unsupported destination.
    if flag("FESTIVE_WEEKLY_AUTO_GROUP_POST"):
        raise domain.FestiveError(
            "Official group delivery is not verified. Disable FESTIVE_WEEKLY_AUTO_GROUP_POST."
        )
    link = os.getenv("FESTIVE_WEEKLY_BOT_LINK", "").strip()
    if not re.fullmatch(r"https://wa\.me/[1-9]\d{7,14}(?:\?text=RUNS)?", link):
        raise domain.FestiveError(
            "Configure FESTIVE_WEEKLY_BOT_LINK with the verified bot display number."
        )
    return time.fromisoformat(clock), link


def local_now(value=None):
    value = value or domain.now()
    if value.tzinfo is None:
        raise ValueError("An aware scheduling time is required")
    return value.astimezone(domain.TZ)


def due_weeks(value=None):
    now = local_now(value)
    clock, _ = settings()
    if now.date() > END:
        return ()
    return tuple(w for w in WEEKS if datetime.combine(w, clock, domain.TZ) <= now)


def week_for(value=None):
    day = local_now(value).date()
    return day - timedelta(days=day.weekday())


def clean_text(value):
    """Do not echo contact details accidentally embedded in approved free text."""
    text = " ".join(str(value or "").split())
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[contact omitted]", text)
    text = re.sub(r"(?<!\w)\+?\d(?:[\s().-]*\d){8,14}(?!\w)", "[contact omitted]", text)
    return text.replace("*", "").replace("`", "").replace("_", "")


def public_link(value):
    if not value:
        return ""
    link = domain.validate_url(value)
    # A map field is not an alternative channel for a personal contact link.
    if re.search(r"(?:wa\.me|whatsapp\.com|mailto:|tel:)", link, re.IGNORECASE):
        return ""
    return link


def snapshot(rows, week):
    result = []
    for row in sorted(rows, key=lambda r: str(r["run_date"])):
        day = date.fromisoformat(str(row["run_date"]))
        if not week <= day <= week + timedelta(days=6) or str(day) not in domain.DATES:
            continue
        status = row["status"]
        # Draft transitions do not change the public announcement.
        if status in {"HOST_ASSIGNED", "DETAILS_PENDING", "PENDING_APPROVAL"}:
            status = "DETAILS_PENDING"
        item = {"date": str(day), "status": status, "hosts": [], "details": {}}
        if status not in {"OPEN", "CANCELLED", "COMPLETED"}:
            item["hosts"] = sorted(
                [
                    {
                        "role": h["host_role"],
                        "name": clean_text(
                            f"{h.get('first_name', '')} {h.get('last_name', '')}"
                        ),
                    }
                    for h in row.get("hosts", [])
                ],
                key=lambda h: (h["role"] != "LEAD", h["name"]),
            )
        if status == "PUBLISHED":
            public = row.get("published") or {}
            for field in FIELDS:
                if field not in public or public[field] in (None, "", []):
                    continue
                value = public[field]
                if field in {"maps_url", "route_url"}:
                    value = public_link(value)
                elif isinstance(value, str):
                    value = clean_text(value)
                elif field == "distances":
                    value = [clean_text(v) for v in value]
                if value != "":
                    item["details"][field] = value
        result.append(item)
    return result


def date_label(day):
    d = date.fromisoformat(day)
    return f"{d.strftime('%A').upper()}, {d.day} {d.strftime('%B').upper()}"


def run_section(item):
    lines = ["📅 *" + date_label(item["date"]) + "*"]
    status, d = item["status"], item["details"]
    if status == "CANCELLED":
        return "\n".join(
            lines + ["❌ This run has been cancelled. Please do not attend."]
        )
    if status == "COMPLETED":
        return "\n".join(lines + ["This run is now completed."])
    if status == "OPEN":
        return "\n".join(
            lines + ["🙋 *HOST NEEDED!*", "Fancy choosing the route for this one?"]
        )
    for host in item["hosts"]:
        label = "🏃 Hosted by" if host["role"] == "LEAD" else "🩵 Co-host"
        if status != "PUBLISHED":
            label = "👤 Host" if host["role"] == "LEAD" else "👤 Co-host"
        if host["name"]:
            lines.append(f"{label}: {host['name']}")
    if status != "PUBLISHED" or not d:
        return "\n".join(lines + ["📍 Run details to follow!"])
    if d.get("title"):
        lines.append(d["title"])
    for key, label in (
        ("start_time", "⏰ Start"),
        ("meeting_point", "📍 Meet"),
        ("location_description", "📍 Meeting notes"),
    ):
        if d.get(key):
            lines.append(f"{label}: {d[key]}")
    if d.get("distances"):
        lines.append("🏃 Distances: " + ", ".join(d["distances"]))
    if "walkers_welcome" in d:
        lines.append("🚶 Walkers: " + ("Yes" if d["walkers_welcome"] else "No"))
    if d.get("coffee_arrangements") in {"yes", "no"}:
        lines.append(
            "☕ Coffee afterwards: "
            + ("Yes" if d["coffee_arrangements"] == "yes" else "No")
        )
    for key, label in (
        ("route_description", "Route"),
        ("pace_information", "Pace"),
        ("safety_notes", "Please note"),
        ("maps_url", "📍 Map"),
        ("route_url", "Route link"),
    ):
        if d.get(key):
            lines.append(f"{label}: {d[key]}")
    if not d.get("maps_url") and "latitude" in d and "longitude" in d:
        lines.append(
            f"📍 Map: https://www.google.com/maps/search/?api=1&query={d['latitude']},{d['longitude']}"
        )
    return "\n".join(lines)


def split_messages(blocks, limit=3900):
    """Prefer whole run sections; split oversized sections by line, never truncate."""
    chunks, current = [], ""
    for block in blocks:
        pieces = [block] if len(block) <= limit else block.splitlines()
        for piece in pieces:
            while len(piece) > limit:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(piece[:limit])
                piece = piece[limit:]
            candidate = current + ("\n\n" if current else "") + piece
            if len(candidate) > limit:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    if len(chunks) > 1:
        chunks = [
            f"*Festive runs · {i}/{len(chunks)}*\n\n{part}"
            for i, part in enumerate(chunks, 1)
        ]
    return chunks


def render(source, week, link):
    sections = [
        run_section(item)
        for item in source
        if item["status"] not in {"CANCELLED", "COMPLETED"}
    ]
    footer = (
        "🙋 Want to host?\nSend *HOST* to our WhatsApp bot.\n\n"
        "🏃 Want to join a run?\nSend *RUNS* to explore the calendar.\n\n"
        f"📲 {link}\n\n🩵 Your route. Your adventure. Our Irene family!"
    )
    return split_messages(
        [
            HEADER,
            f"{week:%d %B %Y} – {week + timedelta(days=6):%d %B %Y}",
            *(
                sections
                or [
                    "No upcoming festive runs are currently listed for this week. Send *RUNS* for the latest calendar."
                ]
            ),
            footer,
        ]
    )


def differences(old, new):
    before, after = {r["date"]: r for r in old}, {r["date"]: r for r in new}
    changes = []
    for day in sorted(before.keys() | after.keys()):
        a, b = before.get(day), after.get(day)
        if a == b:
            continue
        if a is None or b is None:
            fields = ["Calendar listing"]
        else:
            fields = [LABELS[k] for k in ("status", "hosts") if a[k] != b[k]]
            fields += [
                LABELS[k] for k in FIELDS if a["details"].get(k) != b["details"].get(k)
            ]
        changes.append({"date": day, "fields": list(dict.fromkeys(fields))})
    return changes


def correction(old, new):
    changes = differences(old, new)
    if not changes:
        return [], []
    after = {r["date"]: r for r in new}
    blocks = ["📢 *FESTIVE RUN UPDATE*"]
    for change in changes:
        blocks.append(
            date_label(change["date"])
            + " — changed: "
            + ", ".join(change["fields"])
            + "."
        )
        row = after.get(change["date"])
        blocks.append(
            run_section(row)
            if row
            else "This date is no longer listed. Please check RUNS before attending."
        )
    blocks.append("Please use the latest details in the *RUNS* menu. 🩵")
    return changes, split_messages(blocks)


def _latest(cur, week):
    cur.execute(
        "SELECT * FROM festive_weekly_editions WHERE week_start=%s ORDER BY revision DESC LIMIT 1",
        (week,),
    )
    return cur.fetchone()


def _generate(cur, week):
    if week not in WEEKS:
        raise domain.FestiveError("No weekly edition is scheduled for that week.")
    _, link = settings()
    cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (20261120, week.toordinal()))
    # Every source mutation already locks its slot. Hold all programme slots so
    # calendar's multi-query public projection cannot straddle a host amendment.
    cur.execute("SELECT id FROM festive_run_slots ORDER BY run_date FOR SHARE")
    source = snapshot(domain.calendar(cur), week)
    messages = render(source, week, link)
    digest = hashlib.sha256(
        json.dumps([source, messages], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    previous = _latest(cur, week)
    if previous and previous["content_hash"] == digest:
        if previous["last_error"]:
            cur.execute(
                "UPDATE festive_weekly_editions SET last_error=NULL WHERE id=%s",
                (previous["id"],),
            )
            previous["last_error"] = None
        return previous
    cur.execute(
        "SELECT source_snapshot FROM festive_weekly_editions WHERE week_start=%s AND posted_at IS NOT NULL ORDER BY revision DESC LIMIT 1",
        (week,),
    )
    posted = cur.fetchone()
    base = posted or (previous if previous and previous["status"] != "FAILED" else None)
    changes, corrections = (
        correction(base["source_snapshot"], source) if base else ([], [])
    )
    if previous:
        cur.execute(
            "UPDATE festive_weekly_editions SET status='OUTDATED' WHERE id=%s",
            (previous["id"],),
        )
    cur.execute(
        """INSERT INTO festive_weekly_editions
        (week_start,week_end,revision,content_hash,source_snapshot,messages,changes,correction_messages,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'READY_FOR_REVIEW') RETURNING *""",
        (
            week,
            week + timedelta(days=6),
            previous["revision"] + 1 if previous else 1,
            digest,
            Json(source),
            Json(messages),
            Json(changes),
            Json(corrections),
        ),
    )
    return cur.fetchone()


def generate(week, actor=None):
    if not active():
        raise domain.FestiveError("Weekly announcements are disabled.")
    with get_cursor() as cur:
        if actor is not None:
            domain.member(cur, actor, admin=True)
        return _generate(cur, week)


def history(actor):
    with get_cursor() as cur:
        domain.member(cur, actor, admin=True)
        cur.execute(
            "SELECT * FROM festive_weekly_editions ORDER BY week_start DESC,revision DESC"
        )
        return cur.fetchall()


def delivery_summary(actor, edition_id):
    with get_cursor() as cur:
        domain.member(cur, actor, admin=True)
        cur.execute(
            "SELECT status,count(*) AS total FROM festive_weekly_notices WHERE edition_id=%s GROUP BY status ORDER BY status",
            (edition_id,),
        )
        return (
            ", ".join(f"{r['status']}: {r['total']}" for r in cur.fetchall())
            or "No proactive admin notices"
        )


def _record_failure(week, error):
    """Preserve any valid/posted content; persist a failed first attempt if possible."""
    import logging

    try:
        with get_cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s, %s)", (20261120, week.toordinal())
            )
            previous = _latest(cur, week)
            # Exception text may contain credentials or source data; store only type.
            message = f"Generation failed ({type(error).__name__}); inspect runner logs and refresh"
            if previous:
                cur.execute(
                    "UPDATE festive_weekly_editions SET last_error=%s WHERE id=%s",
                    (message, previous["id"]),
                )
            else:
                cur.execute(
                    """INSERT INTO festive_weekly_editions
                    (week_start,week_end,revision,content_hash,source_snapshot,messages,status,last_error)
                    VALUES (%s,%s,1,'','[]','[]','FAILED',%s)""",
                    (week, week + timedelta(days=6), message),
                )
    except (DatabaseError, RuntimeError) as receipt_error:
        # A database outage cannot be recorded in the unavailable database.
        logging.getLogger(__name__).warning(
            "Weekly failure receipt unavailable (%s); next runner tick will retry",
            type(receipt_error).__name__,
        )


def mark_posted(actor, edition_id, now=None):
    if not active():
        raise domain.FestiveError("Weekly announcements are disabled.")
    with get_cursor() as cur:
        domain.member(cur, actor, admin=True)
        cur.execute("SELECT * FROM festive_weekly_editions WHERE id=%s", (edition_id,))
        edition = cur.fetchone()
        if not edition:
            raise domain.FestiveError("Preview an edition first.")
        if edition["week_start"] > local_now(now).date():
            raise domain.FestiveError(
                "This is a future draft. Posting confirmation opens in its calendar week."
            )
        latest = _generate(cur, edition["week_start"])
        if latest["id"] != edition["id"]:
            # Commit the refresh before reporting stale confirmation below.
            stale = True
        else:
            stale = False
            cur.execute(
                """UPDATE festive_weekly_editions SET status='POSTED',
                approved_at=COALESCE(approved_at,now()),posted_at=COALESCE(posted_at,now()),
                posted_by=COALESCE(posted_by,%s),delivery_status='ADMIN_CONFIRMED'
                WHERE id=%s RETURNING *""",
                (actor, edition_id),
            )
            edition = cur.fetchone()
    if stale:
        raise domain.FestiveError(
            "This edition is outdated. Preview and share the latest revision first."
        )
    return edition


def schedule(now=None):
    if not active():
        return {"generated": 0}
    now = local_now(now)
    count = 0
    for week in due_weeks(now):
        try:
            with get_cursor() as cur:
                before = _latest(cur, week)
                # Completed weeks are caught up once, then archived without edit noise.
                if (
                    before
                    and before["status"] != "FAILED"
                    and week + timedelta(days=6) < now.date()
                ):
                    continue
                edition = _generate(cur, week)
                count += int(not before or before["id"] != edition["id"])
                if week <= now.date() <= week + timedelta(days=6):
                    from app.services.festive_weekly_notifications import queue_notices

                    queue_notices(cur, edition)
        except Exception as exc:
            _record_failure(week, exc)
            raise
    return {"generated": count}
