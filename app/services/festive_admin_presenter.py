"""Captain-facing labels and review copy; domain permissions remain authoritative."""

from app.services import festive_service as domain

STATUS = {
    "OPEN": "Host needed",
    "HOST_ASSIGNED": "Host assigned",
    "DETAILS_PENDING": "Details in progress",
    "PENDING_APPROVAL": "Ready for review",
    "PUBLISHED": "Published",
    "CANCELLED": "Cancelled",
    "COMPLETED": "Completed",
}
FIELDS = {
    "title": "Run title",
    "start_time": "Start time",
    "meeting_point": "Meeting point",
    "location_description": "Meeting notes",
    "distances": "Distances",
    "walkers_welcome": "Walkers welcome",
    "coffee_arrangements": "Coffee / breakfast",
    "maps_url": "Map link",
    "route_url": "Route link",
    "route_description": "Route notes",
    "pace_information": "Pace",
    "safety_notes": "Safety notes",
    "latitude": "Latitude",
    "longitude": "Longitude",
}
ACTIONS = {
    "APPROVE": ("Approve & publish", "Make these reviewed details visible in RUNS"),
    "CHANGES": ("Request changes", "Return the submitted details to the host's draft"),
    "CANCEL": (
        "Cancel this run",
        "Remove from RUNS; keep RSVPs for the cancellation notice",
    ),
    "REOPEN": (
        "Reopen hosting slot",
        "Clear hosts, details and active RSVPs; open the date again",
    ),
    "REASSIGN": ("Choose lead host", "Find an existing member by name or member ID"),
    "COMPLETE": ("Mark completed", "Close a published run after its date has passed"),
}
FILTERS = {
    "review": "Ready for review",
    "open": "Hosts needed",
    "pending": "Details in progress",
    "published": "Published runs",
    "all": "All festive dates",
}


def day_label(day):
    return day.strftime("%a %d %b %Y")


def host_name(host):
    return (
        " ".join(
            str(host.get(k) or "").strip() for k in ("first_name", "last_name")
        ).strip()
        or "Name unavailable"
    )


def matches(row, queue):
    future = row["run_date"] >= domain.now().date()
    active = row["status"] not in {"CANCELLED", "COMPLETED"}
    return {
        "review": future and active and row.get("approval_status") == "PENDING",
        "open": future and row["status"] == "OPEN",
        "pending": future
        and active
        and row["status"] in {"HOST_ASSIGNED", "DETAILS_PENDING"},
        "published": row["status"] == "PUBLISHED",
        "all": True,
    }.get(queue, False)


def dashboard(rows):
    counts = {key: sum(matches(r, key) for r in rows) for key in FILTERS}
    return (
        "🎄 *FESTIVE CAPTAIN DESK*\n\n"
        f"📝 {counts['review']} ready for review\n🙋 {counts['open']} hosting dates open\n"
        f"⏳ {counts['pending']} awaiting host details\n✅ {counts['published']} published runs\n"
        f"🏃 {sum(r['rsvp_count'] for r in rows)} active RSVPs across {len(rows)} dates\n\n"
        "Choose a queue below. Open a date to review its details and available actions."
    ), counts


def options(row):
    status = row["status"]
    future = row["run_date"] >= domain.now().date()
    keys = []
    if (
        future
        and status in {"PENDING_APPROVAL", "PUBLISHED"}
        and row.get("approval_status") == "PENDING"
    ):
        keys += ["APPROVE", "CHANGES"]
    if future and status in {
        "OPEN",
        "HOST_ASSIGNED",
        "DETAILS_PENDING",
        "PENDING_APPROVAL",
    }:
        keys.append("REASSIGN")
    if future and status == "CANCELLED":
        keys.append("REOPEN")
    if not future and status == "PUBLISHED":
        keys.append("COMPLETE")
    if future and status not in {"CANCELLED", "COMPLETED"}:
        keys.append("CANCEL")
    return [
        {"id": k, "title": ACTIONS[k][0], "description": ACTIONS[k][1]} for k in keys
    ]


def value(key, data):
    item = data.get(key)
    if item is None or item == "" or item == []:
        return "Not supplied"
    if key == "walkers_welcome":
        return "Yes" if item else "No"
    if key == "coffee_arrangements":
        return {"yes": "Yes", "no": "No", "TBC": "To be confirmed"}.get(item, str(item))
    if isinstance(item, list):
        return ", ".join(str(v) for v in item)
    return str(item)


def details(data, approved=None):
    lines = []
    for key, label in FIELDS.items():
        if key not in data and (not approved or key not in approved):
            continue
        if approved and data.get(key) != approved.get(key):
            lines.append(
                f"✏️ *{label} changed*\nWas: {value(key, approved)}\nNow: {value(key, data)}"
            )
        else:
            lines.append(f"{label}: {value(key, data)}")
    return "\n".join(lines) or "No run details saved yet."


def review(row):
    lines = [f"📅 *{day_label(row['run_date'])}*", STATUS[row["status"]]]
    for host in row["hosts"]:
        lines.append(
            ("🏃 Lead: " if host["host_role"] == "LEAD" else "🩵 Co-host: ")
            + host_name(host)
        )
    if not row["hosts"]:
        lines.append("🙋 No host assigned")
    lines.append(f"🏃 {row['rsvp_count']} active RSVPs")
    if row.get("counts"):
        lines.append(
            " · ".join(f"{c['selected_distance']}: {c['count']}" for c in row["counts"])
        )
    draft, published = row.get("draft") or {}, row.get("published") or {}
    approval = row.get("approval_status")
    if row["status"] == "CANCELLED":
        lines.append(
            "\n❌ This run is cancelled. Reopening clears its hosts, details and active RSVPs."
        )
        if draft:
            lines.extend(["\n*Saved details · for reference*", details(draft)])
    elif approval == "PENDING":
        lines.append("\n📝 *Submitted for your review*")
        if published:
            lines.append(
                "Members still see the previous approved details. Changes are marked below."
            )
        else:
            lines.append(
                "These details are not visible to members until you approve them."
            )
        lines.append(details(draft, published))
    elif draft and (not published or draft != published):
        lines.append("\n⏳ *Private draft · not submitted*")
        if published:
            lines.append("Members still see the previous approved details.")
        lines.append(details(draft, published))
    elif published:
        lines.extend(["\n✅ *Approved member details*", details(published)])
    else:
        lines.append(
            "\nRun details to follow. The lead host can save them using MY HOSTS."
        )
    if draft and approval != "APPROVED":
        missing = [FIELDS[k] for k in domain.REQUIRED if not draft.get(k)]
        if missing:
            lines.append("\nStill needed: " + ", ".join(missing))
    if not options(row):
        lines.append("\nNo changes are available for this run's current status/date.")
    return "\n".join(lines)


def confirmation(row, action, replacement=None):
    impact = {
        "APPROVE": "These reviewed details will become visible to members in RUNS. Opted-in runners may receive an approved-change notice.",
        "CHANGES": "The submission will return to draft. Ask the lead host to update it using MY HOSTS. Existing approved details remain visible; this action does not send a personal message to the host.",
        "CANCEL": "The run will be cancelled and removed from normal listings. RSVPs are retained; cancellation notices will be prepared for eligible opted-in runners.",
        "REOPEN": "This clears the current hosts and saved run details, withdraws active RSVPs, and reopens the date for a new host.",
        "REASSIGN": "The lead host will change and saved run details will be cleared. The new lead can add their details using MY HOSTS.",
        "COMPLETE": "This run will be marked completed and excluded from upcoming listings.",
    }[action]
    who = (
        f"\nNew lead: *{host_name(replacement)}* · member {replacement['id']}"
        if replacement
        else ""
    )
    return f"*{ACTIONS[action][0]}?*\n📅 {day_label(row['run_date'])}{who}\n\n{impact}\n\nConfirm below, or choose Back to keep reviewing."


def success(action):
    return {
        "APPROVE": "✅ Run published. Members can see the approved details in RUNS.",
        "CHANGES": "📝 Returned to draft. Ask the lead host to revise it using MY HOSTS.",
        "CANCEL": "❌ Run cancelled. Eligible cancellation notices have been recorded.",
        "REOPEN": "🙋 Date reopened. Hosting, details and active RSVPs have been cleared.",
        "REASSIGN": "✅ Lead host saved. They can add the new run details using MY HOSTS.",
        "COMPLETE": "✅ Run marked completed. Thank you to the hosts!",
    }[action]
