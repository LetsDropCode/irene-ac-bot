"""Transactional festive domain. All mutations share a locked slot row.

Published snapshots remain visible while amendments await review. No TT table
is read or written. Callers pass their cursor so session receipts and domain
changes commit together.
"""

import ipaddress
import re
from datetime import datetime, time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from psycopg2.extras import Json

from app.config import ADMIN_NUMBERS
from app.migrations.versions.v20261118_festive_runs import DATES

TZ = ZoneInfo("Africa/Johannesburg")
TRANSITIONS = {
    "OPEN": {"HOST_ASSIGNED", "CANCELLED"},
    "HOST_ASSIGNED": {"DETAILS_PENDING", "PENDING_APPROVAL", "OPEN", "CANCELLED"},
    "DETAILS_PENDING": {"PENDING_APPROVAL", "OPEN", "CANCELLED"},
    "PENDING_APPROVAL": {"DETAILS_PENDING", "PUBLISHED", "OPEN", "CANCELLED"},
    "PUBLISHED": {"CANCELLED", "COMPLETED"},
    "CANCELLED": {"OPEN"},
    "COMPLETED": set(),
}
TEXT_FIELDS = {
    "title": 80,
    "meeting_point": 120,
    "location_description": 300,
    "route_description": 600,
    "pace_information": 160,
    "safety_notes": 500,
}
REQUIRED = (
    "meeting_point",
    "location_description",
    "start_time",
    "distances",
    "route_description",
    "safety_notes",
)


class FestiveError(ValueError):
    pass


def now():
    return datetime.now(TZ)


def member(cur, member_id, admin=False):
    cur.execute("SELECT * FROM members WHERE id = %s FOR SHARE", (member_id,))
    row = cur.fetchone()
    if not row or not row.get("popia_acknowledged") or row.get("popia_withdrawn_at"):
        raise FestiveError(
            "Please complete your member profile and consent first. Send HELP."
        )
    if row.get("first_name") in {None, "", "Unknown"}:
        raise FestiveError("Please complete your member name first. Send PROFILE.")
    if admin and row["phone"] not in ADMIN_NUMBERS:
        raise FestiveError("Club administrator access is required.")
    return row


def slot(cur, day, future=True):
    if str(day) not in DATES:
        raise FestiveError("Choose one of the 14 festive dates.")
    cur.execute(
        "SELECT * FROM festive_run_slots WHERE run_date = %s FOR UPDATE", (day,)
    )
    row = cur.fetchone()
    if not row:
        raise FestiveError("The festive calendar is not available yet.")
    if future and row["run_date"] < now().date():
        raise FestiveError("This run date has passed.")
    return row


def audit(cur, row, actor, action, bump=True):
    if bump:
        cur.execute(
            "UPDATE festive_run_slots SET revision = revision + 1, updated_at = now() WHERE id = %s RETURNING revision",
            (row["id"],),
        )
        row["revision"] = cur.fetchone()["revision"]
    cur.execute(
        "INSERT INTO festive_run_audit(run_slot_id, actor_member_id, action, revision) VALUES (%s,%s,%s,%s)",
        (row["id"], actor, action, row["revision"]),
    )


def transition(cur, row, target):
    if target == row["status"]:
        return
    if target not in TRANSITIONS[row["status"]]:
        raise FestiveError(f"Cannot change {row['status']} to {target}.")
    cur.execute(
        "UPDATE festive_run_slots SET status = %s WHERE id = %s", (target, row["id"])
    )
    row["status"] = target


def check_revision(row, revision):
    if revision is not None and row["revision"] != revision:
        raise FestiveError("This run changed. Go BACK and review the latest details.")


def validate_url(value):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        u = urlsplit(value)
        if (
            u.scheme != "https"
            or not u.hostname
            or u.username
            or u.password
            or len(value) > 500
            or any(c.isspace() for c in value)
        ):
            raise ValueError
        if (
            u.hostname.lower() == "localhost"
            or "." not in u.hostname
            or u.port not in {None, 443}
        ):
            raise ValueError
        try:
            address = ipaddress.ip_address(u.hostname)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError
    except ValueError:
        raise FestiveError("Use a public HTTPS Maps or route link.") from None
    return value


def validate_details(data, complete=False):
    if not isinstance(data, dict):
        raise FestiveError("Invalid run details.")
    clean = {}
    for key, maximum in TEXT_FIELDS.items():
        value = data.get(key, "")
        if (
            not isinstance(value, str)
            or len(value) > maximum
            or any(ord(c) < 32 and c not in "\n\t" for c in value)
        ):
            raise FestiveError(
                f"Check {key.replace('_', ' ')} (maximum {maximum} characters)."
            )
        clean[key] = value.strip()
    for key in ("maps_url", "route_url"):
        clean[key] = validate_url(data.get(key))
    clock = data.get("start_time", "")
    if clock and (
        not isinstance(clock, str)
        or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock)
    ):
        raise FestiveError(
            "Start time must be HH:MM, for example 06:00 (South Africa)."
        )
    clean["start_time"] = clock
    distances = data.get("distances", [])
    if isinstance(distances, str):
        distances = [v.strip() for v in distances.split(",") if v.strip()]
    if (
        not isinstance(distances, list)
        or len(distances) > 8
        or any(
            not isinstance(d, str)
            or not re.fullmatch(r"\d{1,3}(?:\.\d)?\s?km", d, re.IGNORECASE)
            for d in distances
        )
    ):
        raise FestiveError("List up to 8 distances, for example 5km, 10km.")
    clean["distances"] = list(
        dict.fromkeys(d.lower().replace(" ", "") for d in distances)
    )
    if any(float(d[:-2]) <= 0 for d in clean["distances"]):
        raise FestiveError("Distances must be greater than zero.")
    walkers = data.get("walkers_welcome", "no")
    if walkers not in (True, False, "yes", "no"):
        raise FestiveError("Choose yes or no for walkers.")
    clean["walkers_welcome"] = walkers in {True, "yes"}
    coffee = data.get("coffee_arrangements", "TBC")
    if coffee not in ("yes", "no", "TBC"):
        raise FestiveError("Choose yes, no or TBC for coffee.")
    clean["coffee_arrangements"] = coffee
    for field, maximum in (("latitude", 90), ("longitude", 180)):
        if data.get(field) not in (None, ""):
            try:
                value = float(data[field])
            except (TypeError, ValueError):
                raise FestiveError("Invalid location pin.") from None
            if not -maximum <= value <= maximum:
                raise FestiveError("Invalid location pin.")
            clean[field] = value
    if ("latitude" in clean) != ("longitude" in clean):
        raise FestiveError("A location pin needs both coordinates.")
    if complete:
        missing = [key.replace("_", " ") for key in REQUIRED if not clean.get(key)]
        if missing:
            raise FestiveError(
                "Still needed: "
                + ", ".join(missing)
                + ". Save a draft to finish later."
            )
    return clean


def book(cur, actor, day, role, reminders=False):
    member(cur, actor)
    row = slot(cur, day)
    if row["status"] in {"CANCELLED", "COMPLETED"} or role not in {"LEAD", "COHOST"}:
        raise FestiveError("This hosting slot is unavailable.")
    cur.execute(
        "SELECT * FROM festive_run_hosts WHERE run_slot_id = %s AND status = 'ACTIVE'",
        (row["id"],),
    )
    hosts = cur.fetchall()
    for host in hosts:
        if host["member_id"] == actor and host["host_role"] == role:
            return row
        if host["host_role"] == role or host["member_id"] == actor:
            raise FestiveError(
                "That hosting slot was just taken. Choose another date or role."
            )
    if role == "COHOST" and not any(h["host_role"] == "LEAD" for h in hosts):
        raise FestiveError("A lead host is needed before a co-host can register.")
    cur.execute(
        "INSERT INTO festive_run_hosts(run_slot_id, member_id, host_role, reminder_opt_in) VALUES (%s,%s,%s,%s)",
        (row["id"], actor, role, reminders is True),
    )
    if row["status"] == "OPEN":
        transition(cur, row, "HOST_ASSIGNED")
    audit(cur, row, actor, "BOOK_" + role, bump=role == "LEAD")
    return row


def require_lead(cur, actor, row):
    cur.execute(
        "SELECT 1 FROM festive_run_hosts WHERE run_slot_id=%s AND member_id=%s AND host_role='LEAD' AND status='ACTIVE'",
        (row["id"], actor),
    )
    if not cur.fetchone():
        raise FestiveError("Only this run's lead host can edit its details.")


def save_details(cur, actor, day, data, submit=False, revision=None):
    member(cur, actor)
    row = slot(cur, day)
    check_revision(row, revision)
    require_lead(cur, actor, row)
    if row["status"] in {"CANCELLED", "COMPLETED"}:
        raise FestiveError("This run cannot be edited.")
    clean = validate_details(data, complete=submit)
    cur.execute(
        "SELECT draft FROM festive_run_details WHERE run_slot_id=%s", (row["id"],)
    )
    previous = cur.fetchone()
    previous = previous["draft"] if previous else {}
    if "latitude" not in clean and previous.get("maps_url", "") == clean.get(
        "maps_url", ""
    ):
        for key in ("latitude", "longitude"):
            if key in previous:
                clean[key] = previous[key]
    cur.execute(
        """INSERT INTO festive_run_details(run_slot_id, draft, approval_status)
        VALUES (%s,%s,%s) ON CONFLICT (run_slot_id) DO UPDATE SET
        draft=EXCLUDED.draft, approval_status=EXCLUDED.approval_status, updated_at=now()""",
        (row["id"], Json(clean), "PENDING" if submit else "DRAFT"),
    )
    if row["status"] != "PUBLISHED":
        transition(cur, row, "PENDING_APPROVAL" if submit else "DETAILS_PENDING")
    audit(cur, row, actor, "SUBMIT_DETAILS" if submit else "SAVE_DRAFT")
    return row


def rsvp(cur, actor, day, distance, reminders=False, revision=None):
    member(cur, actor)
    row = slot(cur, day)
    check_revision(row, revision)
    cur.execute(
        "SELECT published FROM festive_run_details WHERE run_slot_id=%s", (row["id"],)
    )
    details = cur.fetchone()
    if (
        row["status"] != "PUBLISHED"
        or not details
        or distance not in details["published"]["distances"]
    ):
        raise FestiveError("Choose an offered distance on a published run.")
    start = datetime.combine(
        row["run_date"], time.fromisoformat(details["published"]["start_time"]), TZ
    )
    if start <= now():
        raise FestiveError("This run has already started.")
    cur.execute(
        """INSERT INTO festive_run_rsvps(run_slot_id, member_id, selected_distance, reminder_opt_in)
        VALUES (%s,%s,%s,%s) ON CONFLICT (run_slot_id,member_id) DO UPDATE SET
        selected_distance=EXCLUDED.selected_distance, reminder_opt_in=EXCLUDED.reminder_opt_in,
        status='ACTIVE', updated_at=now()""",
        (row["id"], actor, distance, reminders is True),
    )
    # Attendance counts must not invalidate another member's review.
    cur.execute(
        "INSERT INTO festive_run_audit(run_slot_id,actor_member_id,action,revision) VALUES (%s,%s,'RSVP',%s)",
        (row["id"], actor, row["revision"]),
    )
    return row


def withdraw_rsvp(cur, actor, day):
    member(cur, actor)
    row = slot(cur, day, future=False)
    cur.execute(
        "UPDATE festive_run_rsvps SET status='WITHDRAWN', reminder_opt_in=FALSE, updated_at=now() WHERE run_slot_id=%s AND member_id=%s",
        (row["id"], actor),
    )
    return row


def participant_notices(cur, row, kind):
    cur.execute(
        """INSERT INTO festive_run_notifications(run_slot_id,recipient_member_id,notification_type,idempotency_key,scheduled_for)
        SELECT %s,member_id,%s,%s || member_id::text,now() FROM festive_run_rsvps
        WHERE run_slot_id=%s AND status='ACTIVE' AND reminder_opt_in
        ON CONFLICT (idempotency_key) DO NOTHING""",
        (row["id"], kind, f"festive:{row['id']}:{kind}:{row['revision']}:", row["id"]),
    )


def withdraw_host(cur, actor, day):
    member(cur, actor)
    row = slot(cur, day)
    cur.execute(
        "UPDATE festive_run_hosts SET status='WITHDRAWN', updated_at=now() WHERE run_slot_id=%s AND member_id=%s AND status='ACTIVE' RETURNING host_role",
        (row["id"], actor),
    )
    removed = cur.fetchone()
    if not removed:
        return row
    if removed["host_role"] == "LEAD":
        if row["status"] == "PUBLISHED":
            transition(cur, row, "CANCELLED")
        else:
            transition(cur, row, "OPEN")
            cur.execute(
                "UPDATE festive_run_hosts SET status='WITHDRAWN' WHERE run_slot_id=%s AND status='ACTIVE'",
                (row["id"],),
            )
            cur.execute(
                "DELETE FROM festive_run_details WHERE run_slot_id=%s", (row["id"],)
            )
    audit(
        cur,
        row,
        actor,
        "WITHDRAW_" + removed["host_role"],
        bump=removed["host_role"] == "LEAD",
    )
    if row["status"] == "CANCELLED":
        participant_notices(cur, row, "CANCELLED")
    return row


def admin_action(cur, actor, day, action, revision=None, replacement=None):
    member(cur, actor, admin=True)
    row = slot(cur, day, future=action != "COMPLETE")
    check_revision(row, revision)
    if action == "APPROVE":
        cur.execute(
            "SELECT * FROM festive_run_details WHERE run_slot_id=%s", (row["id"],)
        )
        details = cur.fetchone()
        if not details or details["approval_status"] != "PENDING":
            raise FestiveError("There are no submitted details to approve.")
        cur.execute(
            "SELECT 1 FROM festive_run_hosts h JOIN members m ON m.id=h.member_id WHERE h.run_slot_id=%s AND h.host_role='LEAD' AND h.status='ACTIVE' AND m.popia_acknowledged AND m.popia_withdrawn_at IS NULL",
            (row["id"],),
        )
        if not cur.fetchone():
            raise FestiveError("An active, consenting lead host is required.")
        clean = validate_details(details["draft"], complete=True)
        transition(cur, row, "PUBLISHED")
        cur.execute(
            "UPDATE festive_run_details SET published=%s, approval_status='APPROVED', approved_by=%s, approved_at=now() WHERE run_slot_id=%s",
            (Json(clean), actor, row["id"]),
        )
        audit(cur, row, actor, action)
        if details["published"] and details["published"] != clean:
            participant_notices(cur, row, "CHANGED")
        return row
    if action == "CHANGES":
        cur.execute(
            "UPDATE festive_run_details SET approval_status='DRAFT' WHERE run_slot_id=%s",
            (row["id"],),
        )
        if row["status"] != "PUBLISHED":
            transition(cur, row, "DETAILS_PENDING")
    elif action == "CANCEL":
        transition(cur, row, "CANCELLED")
    elif action == "REOPEN":
        transition(cur, row, "OPEN")
        cur.execute(
            "UPDATE festive_run_hosts SET status='WITHDRAWN' WHERE run_slot_id=%s",
            (row["id"],),
        )
        cur.execute(
            "UPDATE festive_run_rsvps SET status='WITHDRAWN', reminder_opt_in=FALSE WHERE run_slot_id=%s",
            (row["id"],),
        )
        cur.execute(
            "DELETE FROM festive_run_details WHERE run_slot_id=%s", (row["id"],)
        )
    elif action == "REASSIGN":
        member(cur, replacement)
        if row["status"] in {"PUBLISHED", "COMPLETED", "CANCELLED"}:
            raise FestiveError(
                "Cancel and reopen this run before assigning a new lead host."
            )
        cur.execute(
            "UPDATE festive_run_hosts SET status='WITHDRAWN' WHERE run_slot_id=%s AND (host_role='LEAD' OR member_id=%s)",
            (row["id"], replacement),
        )
        cur.execute(
            "INSERT INTO festive_run_hosts(run_slot_id,member_id,host_role) VALUES (%s,%s,'LEAD')",
            (row["id"], replacement),
        )
        cur.execute(
            "DELETE FROM festive_run_details WHERE run_slot_id=%s", (row["id"],)
        )
        cur.execute(
            "UPDATE festive_run_slots SET status='HOST_ASSIGNED' WHERE id=%s",
            (row["id"],),
        )
    elif action == "COMPLETE":
        if row["run_date"] >= now().date():
            raise FestiveError("Complete a run only after its date has passed.")
        transition(cur, row, "COMPLETED")
    else:
        raise FestiveError("Unknown administrator action.")
    audit(cur, row, actor, action)
    if action == "CANCEL":
        participant_notices(cur, row, "CANCELLED")
    return row


def calendar(cur, actor=None, admin=False):
    if actor:
        member(cur, actor, admin=admin)
    cur.execute("""SELECT s.*, d.published, d.draft, d.approval_status,
        (SELECT count(*) FROM festive_run_rsvps r WHERE r.run_slot_id=s.id AND r.status='ACTIVE') AS rsvp_count
        FROM festive_run_slots s LEFT JOIN festive_run_details d ON d.run_slot_id=s.id ORDER BY s.run_date""")
    rows = cur.fetchall()
    for row in rows:
        cur.execute(
            """SELECT h.member_id,h.host_role,m.first_name,m.last_name FROM festive_run_hosts h
            JOIN members m ON m.id=h.member_id WHERE h.run_slot_id=%s AND h.status='ACTIVE'
            AND m.popia_acknowledged AND m.popia_withdrawn_at IS NULL ORDER BY host_role DESC""",
            (row["id"],),
        )
        row["hosts"] = [dict(h) for h in cur.fetchall()]
        own_lead = any(
            h["member_id"] == actor and h["host_role"] == "LEAD" for h in row["hosts"]
        )
        if not admin and not own_lead:
            row.pop("draft", None)
        if row["status"] not in {"PUBLISHED", "COMPLETED"}:
            row["published"] = None
        row["mine"] = None
        if actor:
            cur.execute(
                "SELECT selected_distance,reminder_opt_in,status FROM festive_run_rsvps WHERE run_slot_id=%s AND member_id=%s",
                (row["id"], actor),
            )
            row["mine"] = cur.fetchone()
        if admin or any(h["member_id"] == actor for h in row["hosts"]):
            cur.execute(
                "SELECT selected_distance,count(*) AS count FROM festive_run_rsvps WHERE run_slot_id=%s AND status='ACTIVE' GROUP BY selected_distance",
                (row["id"],),
            )
            row["counts"] = [dict(c) for c in cur.fetchall()]
    return rows


def public_summary(row):
    labels = {
        "OPEN": "Volunteer host needed",
        "HOST_ASSIGNED": "Host assigned — details to follow",
        "DETAILS_PENDING": "Host assigned — details to follow",
        "PENDING_APPROVAL": "Host assigned — details to follow",
        "PUBLISHED": "Ready to join",
        "CANCELLED": "Cancelled",
        "COMPLETED": "Completed",
    }
    lines = [str(row["run_date"]), labels[row["status"]]]
    d = row.get("published")
    if d:
        lead = next((h for h in row["hosts"] if h["host_role"] == "LEAD"), {})
        lines += [
            d.get("title") or "Irene AC Festive Run Adventures",
            f"{d['start_time']} · {d['meeting_point']}",
            d["location_description"],
            f"Lead host: {lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
            "Distances: " + ", ".join(d["distances"]),
            d["route_description"],
            "Walkers: " + ("welcome" if d["walkers_welcome"] else "not offered"),
            "Coffee/breakfast: " + d["coffee_arrangements"],
            d.get("pace_information", ""),
            d["safety_notes"],
            f"{row['rsvp_count']} members interested. RSVP is optional; everyone is welcome.",
        ]
    else:
        lines += [
            f"{h['host_role'].title()}: {h['first_name']} {h['last_name']}"
            for h in row["hosts"]
        ]
    return "\n".join(v for v in lines if v)
