"""Festive command adapter. Returns None before any DB access when disabled."""

import json

from psycopg2.extras import Json

from app.db import get_cursor
from app.services import festive_flow_service as flows
from app.services import festive_service as domain
from app.services import festive_transport as transport
from app.services.festive_config import capabilities, enabled

COMMANDS = {
    "RUNS",
    "HOST",
    "MY HOSTS",
    "HOST SCHEDULE",
    "JOIN",
    "MY RUNS",
    "FESTIVE ADMIN",
    "FESTIVE SIMPLE",
    "FESTIVE TEXT",
    "FESTIVE HELP",
}
HELP = "🎄 Irene AC Festive Run Adventures\nDifferent hosts. Different routes. One Irene family. 💚\nRUNS · calendar\nHOST · volunteer\nMY HOSTS · edit or withdraw hosting\nHOST SCHEDULE · public host schedule\nJOIN · optional RSVP\nMY RUNS · change or cancel RSVP\nFESTIVE SIMPLE · lists/buttons fallback\nFESTIVE TEXT · numbered fallback\nBACK · start this form again\nCANCEL · stop (saved drafts are kept)"


def chat_state(actor):
    with get_cursor() as cur:
        cur.execute(
            "SELECT data FROM festive_chat_sessions WHERE member_id=%s AND expires_at>now()",
            (actor,),
        )
        row = cur.fetchone()
        return row["data"] if row else {}


def save_chat(actor, data):
    with get_cursor() as cur:
        cur.execute(
            """INSERT INTO festive_chat_sessions(member_id,data) VALUES (%s,%s)
            ON CONFLICT(member_id) DO UPDATE SET data=EXCLUDED.data,expires_at=now()+interval '2 hours'""",
            (actor, Json(data)),
        )


def say(sender, body):
    # Paragraph boundaries keep long admin summaries/route notes readable.
    while body:
        split = body.rfind("\n", 0, 3900) if len(body) > 3900 else len(body)
        if split < 1:
            split = min(3900, len(body))
        transport.send(transport.text_payload(sender, body[:split]))
        body = body[split:].lstrip("\n")


def menu(sender, actor, state, body, options, page=0):
    """8 content rows + two navigation rows fits Meta's 10-row limit."""
    pages = max(1, (len(options) + 7) // 8)
    page = max(0, min(page, pages - 1))
    shown = options[page * 8 : page * 8 + 8]
    if page > 0:
        shown += [(f"festive:page:{page - 1}", "Previous page", "")]
    if page + 1 < pages:
        shown += [(f"festive:page:{page + 1}", "Next page", "")]
    state.update(options=options, shown=[r[0] for r in shown], page=page, body=body)
    save_chat(actor, state)
    if not shown:
        say(sender, body + "\nNothing available. Send RUNS or BACK.")
    elif capabilities(state.get("client", "auto"))["native"]:
        transport.send(
            transport.list_payload(
                sender,
                body[:4000],
                [
                    {"id": key, "title": title[:24], "description": desc[:72]}
                    for key, title, desc in shown
                ],
            )
        )
    else:
        say(
            sender,
            body
            + "\n"
            + "\n".join(
                f"{n}. {title} {desc}" for n, (_, title, desc) in enumerate(shown, 1)
            )
            + "\nReply with a number. BACK / CANCEL.",
        )


def render(sender, actor, state, response):
    screen, data = response["screen"], response["data"]
    state.update(
        screen=screen,
        revision=data["revision"],
        response=response,
        pending_distance=None,
    )
    summary = data.get("summary", "")
    if data.get("error"):
        summary = data["error"] + "\n\n" + summary
    if screen in {"CHOOSE", "ACTION", "RSVP"}:
        options = [
            (f"festive:pick:{data['revision']}:{n}", o["title"], "")
            for n, o in enumerate(data.get("options", []))
        ]
        menu(sender, actor, state, summary, options)
    elif screen in {"BOOK", "REVIEW"}:
        state["shown"] = [
            "festive:confirm:" + data["revision"],
            "festive:back",
            "festive:cancel",
        ]
        if screen == "BOOK":
            state["shown"] = [
                "festive:confirm:" + data["revision"],
                "festive:confirm_remind:" + data["revision"],
                "festive:cancel",
            ]
        save_chat(actor, state)
        if capabilities(state.get("client", "auto"))["native"]:
            if len(summary) > 850:
                say(sender, summary)
                summary = "Review the details above, then confirm."
            buttons = [
                (state["shown"][0], "Confirm"),
                (
                    state["shown"][1],
                    "Confirm + reminders" if screen == "BOOK" else "Back",
                ),
                ("festive:cancel", "Cancel"),
            ]
            transport.send(
                transport.buttons_payload(
                    sender,
                    summary
                    + ("\nType BACK to change the date." if screen == "BOOK" else ""),
                    buttons,
                )
            )
        else:
            say(
                sender,
                summary
                + (
                    "\n1. Confirm\n2. Confirm + reminders\n3. Cancel\nBACK to change date."
                    if screen == "BOOK"
                    else "\n1. Confirm\n2. Back\n3. Cancel"
                ),
            )
    elif screen == "DETAILS":
        state["shown"] = []
        save_chat(actor, state)
        existing = {k: v for k, v in data.items() if k in flows.DETAIL_FIELDS and v}
        say(
            sender,
            summary
            + "\nSend fields together as name=value, one per line. Only changed fields are needed.\n"
            "meeting_point=...\nlocation_description=...\nstart_time=06:00\ndistances=5km, 10km\nroute_description=...\nsafety_notes=...\n"
            "Optional: title, maps_url, route_url, walkers_welcome=yes/no, pace_information, coffee_arrangements=yes/no/TBC.\n"
            "End with save_mode=draft or save_mode=submit. You may also share a location pin.\n"
            + (
                "Saved values: " + json.dumps(existing, ensure_ascii=False)
                if existing
                else ""
            )
            + "\nBACK / CANCEL",
        )
    else:
        state.update(token=None, shown=[])
        save_chat(actor, state)
        say(sender, summary)


def calendar(sender, actor, state, page=0):
    with get_cursor() as cur:
        rows = domain.calendar(cur, actor)
    labels = {
        "OPEN": "Host needed",
        "HOST_ASSIGNED": "Details pending",
        "DETAILS_PENDING": "Details pending",
        "PENDING_APPROVAL": "Details pending",
        "PUBLISHED": "Ready to join",
        "CANCELLED": "Cancelled",
        "COMPLETED": "Completed",
    }
    state.update(mode="calendar", token=None)
    menu(
        sender,
        actor,
        state,
        "🎄 Irene AC Festive Run Adventures\nDifferent hosts. Different routes. One Irene family. 💚\n14 festive dates · select a run. HOST to volunteer.",
        [
            (
                "festive:run:" + str(r["run_date"]),
                r["run_date"].strftime("%a %d %b %Y"),
                labels[r["status"]],
            )
            for r in rows
        ],
        page,
    )


def start(sender, actor, state, kind):
    token, response = flows.create_session(actor, kind)
    state.update(mode="form", token=token, kind=kind)
    caps = capabilities(state.get("client", "auto"))
    if not response["data"].get("options"):
        state.update(token=None, mode=None)
        save_chat(actor, state)
        say(sender, response["data"]["summary"])
        return
    if caps["flows"] and caps["flow_ids"].get(kind):
        save_chat(actor, state)
        transport.send(transport.flow_payload(sender, kind, token))
    else:
        render(sender, actor, state, response)


def submit(sender, actor, state, data, back=False):
    response = flows.exchange(
        {
            "flow_token": state["token"],
            "action": "BACK" if back else "data_exchange",
            "screen": state.get("screen"),
            "data": {"revision": state.get("revision"), **data},
        },
        actor,
    )
    render(sender, actor, state, response)


def handle(actions, sender, raw_text, button):
    if not enabled(sender):
        return None
    command = (raw_text or "").strip().upper()
    key = (button or {}).get("id", "")
    recognized = command in COMMANDS or key.startswith("festive:")
    if not recognized and (
        getattr(actions, "is_help_command", lambda value: value in {"HELP", "MENU"})(
            command
        )
        or getattr(actions, "resolve_menu_action", lambda *a, **k: None)(
            command, admin=False
        )
        or (button and not key.startswith("festive:"))
    ):
        m = actions.get_member(sender)
        if m:
            save_chat(m["id"], {})
        return None
    # No festive DB work for unrelated TT messages unless a festive session exists.
    m = actions.get_member(sender)
    if not m:
        if recognized:
            say(sender, "Please register with the TT bot first. Send HELP.")
            return {"status": "festive_member_required"}
        return None
    actor = m["id"]
    state = chat_state(actor)
    if not recognized and not state.get("mode"):
        return None
    if (
        not recognized
        and not state.get("token")
        and command not in {"BACK", "CANCEL"}
        and not (raw_text or "").isdigit()
    ):
        return None
    if not recognized and command in {"BACK", "CANCEL"} and not state.get("mode"):
        return None
    try:
        with get_cursor() as cur:
            domain.member(cur, actor)
        if command == "FESTIVE HELP":
            say(sender, HELP)
        elif command in {"FESTIVE SIMPLE", "FESTIVE TEXT"}:
            state["client"] = "text" if command == "FESTIVE TEXT" else "no_flow"
            if state.get("token"):
                response = flows.exchange(
                    {"flow_token": state["token"], "action": "INIT"}, actor
                )
                render(sender, actor, state, response)
            else:
                calendar(sender, actor, state)
        elif command in {"RUNS", "HOST SCHEDULE"}:
            calendar(sender, actor, state)
        elif command in {"HOST", "JOIN", "MY RUNS", "MY HOSTS", "FESTIVE ADMIN"}:
            kind = {
                "MY RUNS": "MANAGE",
                "MY HOSTS": "MANAGE",
                "FESTIVE ADMIN": "ADMIN",
            }.get(command, command)
            if kind == "ADMIN":
                with get_cursor() as cur:
                    rows = domain.calendar(cur, actor, admin=True)
                hosted = sum(bool(r["hosts"]) for r in rows)
                say(
                    sender,
                    f"Festive captain dashboard\nDates: {len(rows)} · Hosted: {hosted} · Vacant: {len(rows) - hosted}\n"
                    f"Published: {sum(r['status'] == 'PUBLISHED' for r in rows)} · RSVPs: {sum(r['rsvp_count'] for r in rows)}\n"
                    f"Need attention: {sum(r['status'] not in {'PUBLISHED', 'COMPLETED'} or r.get('approval_status') == 'PENDING' for r in rows)}\nSelect a date to review draft venue, time, hosts and counts.",
                )
            start(sender, actor, state, kind)
        elif key == "festive:completion":
            say(sender, flows.completion(button.get("flow_token"), actor))
            state.update(token=None, mode=None)
            save_chat(actor, state)
        else:
            if (
                not key
                and (raw_text or "").isdigit()
                and not state.get("replacement_pending")
            ):
                number = int(raw_text) - 1
                if not 0 <= number < len(state.get("shown", [])):
                    raise domain.FestiveError("Choose one of the numbers shown.")
                key = state["shown"][number]
            if command == "CANCEL" or key == "festive:cancel":
                if state.get("token"):
                    with get_cursor() as cur:
                        cur.execute(
                            "UPDATE festive_run_sessions SET expires_at=now() WHERE token_hash=%s AND member_id=%s",
                            (flows.token_hash(state["token"]), actor),
                        )
                save_chat(actor, {})
                say(
                    sender,
                    "Festive session cancelled. Saved registrations and drafts are kept.",
                )
            elif command == "BACK" or key == "festive:back":
                if state.get("token"):
                    submit(sender, actor, state, {}, back=True)
                else:
                    calendar(sender, actor, state)
            elif key.startswith("festive:calendar:"):
                calendar(sender, actor, state, int(key.rsplit(":", 1)[1]))
            elif key.startswith("festive:page:"):
                menu(
                    sender,
                    actor,
                    state,
                    state["body"],
                    state["options"],
                    int(key.rsplit(":", 1)[1]),
                )
            elif key.startswith("festive:run:"):
                day = key.rsplit(":", 1)[1]
                with get_cursor() as cur:
                    rows = domain.calendar(cur, actor)
                row = next((r for r in rows if str(r["run_date"]) == day), None)
                if not row:
                    raise domain.FestiveError("Choose a festive date.")
                options = [
                    ("festive:start:JOIN:" + day, "I'm joining", "Optional RSVP"),
                    ("festive:calendar:0", "Back to calendar", "All festive dates"),
                ]
                if row["status"] != "PUBLISHED":
                    options = [
                        (
                            "festive:start:HOST:" + day,
                            "Host a run",
                            "See available dates",
                        ),
                        options[-1],
                    ]
                d = row.get("published") or {}
                if d.get("maps_url") or "latitude" in d:
                    options.insert(
                        1, ("festive:directions:" + day, "Directions", "Meeting point")
                    )
                if d.get("route_url"):
                    options.insert(
                        1, ("festive:route:" + day, "View route", "Host's route link")
                    )
                menu(sender, actor, state, domain.public_summary(row), options)
            elif key.startswith(("festive:directions:", "festive:route:")):
                day = key.rsplit(":", 1)[1]
                with get_cursor() as cur:
                    row = next(
                        (
                            r
                            for r in domain.calendar(cur, actor)
                            if str(r["run_date"]) == day
                        ),
                        None,
                    )
                d = (row or {}).get("published") or {}
                if ":route:" in key and d.get("route_url"):
                    say(sender, d["route_url"])
                elif (
                    ":directions:" in key
                    and "latitude" in d
                    and capabilities(state.get("client", "auto"))["location"]
                ):
                    transport.send(transport.location_payload(sender, d))
                elif d.get("maps_url"):
                    say(sender, d["maps_url"])
                elif "latitude" in d:
                    say(
                        sender,
                        f"https://www.google.com/maps/search/?api=1&query={d['latitude']},{d['longitude']}",
                    )
                else:
                    raise domain.FestiveError(
                        "Directions are not available for this run."
                    )
            elif key.startswith("festive:start:"):
                _, _, kind, day = key.split(":", 3)
                start(sender, actor, state, kind)
                # Flow uses dynamic discovery; fallback can preselect the viewed run.
                if (
                    not capabilities(state.get("client", "auto"))["flows"]
                    and kind == "JOIN"
                ):
                    submit(sender, actor, state, {"choice": day})
            elif state.get("token"):
                if key.startswith(("festive:confirm:", "festive:confirm_remind:")):
                    if key.rsplit(":", 1)[1] != state.get("revision"):
                        raise domain.FestiveError(
                            "This confirmation is old. Use the latest form."
                        )
                    submit(
                        sender,
                        actor,
                        state,
                        {
                            "confirm": True,
                            "reminders": key.startswith("festive:confirm_remind:"),
                        },
                    )
                elif key.startswith("festive:pick:"):
                    _, _, revision, index = key.split(":")
                    if revision != state.get("revision"):
                        raise domain.FestiveError(
                            "That menu is old. Use the latest choices."
                        )
                    option = state["response"]["data"]["options"][int(index)]["id"]
                    if state["screen"] == "RSVP":
                        state["pending_distance"] = option
                        state["shown"] = ["festive:reminder:yes", "festive:reminder:no"]
                        save_chat(actor, state)
                        if capabilities(state.get("client", "auto"))["native"]:
                            transport.send(
                                transport.buttons_payload(
                                    sender,
                                    "Opt in to reminders and change/cancellation alerts for this run?",
                                    [
                                        (state["shown"][0], "Yes please"),
                                        (state["shown"][1], "No thanks"),
                                    ],
                                )
                            )
                        else:
                            say(
                                sender,
                                "Reminders and change/cancellation alerts?\n1. Yes please\n2. No thanks",
                            )
                    elif option == "REASSIGN":
                        state["replacement_pending"] = True
                        save_chat(actor, state)
                        say(
                            sender, "Send the existing member ID for the new lead host."
                        )
                    else:
                        values = {"choice": option}
                        if state["kind"] == "HOST" and state["screen"] == "CHOOSE":
                            with get_cursor() as cur:
                                row = next(
                                    r
                                    for r in domain.calendar(cur, actor)
                                    if str(r["run_date"]) == option
                                )
                            values["role"] = (
                                "COHOST"
                                if any(h["host_role"] == "LEAD" for h in row["hosts"])
                                else "LEAD"
                            )
                        submit(sender, actor, state, values)
                elif key.startswith("festive:reminder:") and state.get(
                    "pending_distance"
                ):
                    submit(
                        sender,
                        actor,
                        state,
                        {
                            "distance": state["pending_distance"],
                            "reminders": key.endswith(":yes"),
                        },
                    )
                elif state.get("replacement_pending") and (raw_text or "").isdigit():
                    state["replacement_pending"] = False
                    submit(
                        sender,
                        actor,
                        state,
                        {"choice": "REASSIGN", "replacement": raw_text},
                    )
                elif state.get("screen") == "DETAILS" and (
                    (raw_text and "=" in raw_text) or key == "festive:location"
                ):
                    values = {
                        k: v
                        for k, v in state["response"]["data"].items()
                        if k in flows.DETAIL_FIELDS
                    }
                    if key == "festive:location":
                        state["pin"] = button["location"]
                        save_chat(actor, state)
                        say(
                            sender,
                            "Pin received for your draft. Send the remaining fields with save_mode=draft or save_mode=submit.",
                        )
                    else:
                        for line in raw_text.splitlines():
                            k, separator, value = line.partition("=")
                            if not separator or k.strip() not in flows.DETAIL_FIELDS + [
                                "save_mode"
                            ]:
                                raise domain.FestiveError(
                                    "Use one field=value per line. Send BACK or CANCEL anytime."
                                )
                            values[k.strip()] = value.strip()
                        pin = state.get("pin") or {}
                        for k in ("latitude", "longitude"):
                            if k in pin:
                                values[k] = pin[k]
                        submit(sender, actor, state, values)
                else:
                    # TT commands must remain reachable during an interrupted festive form.
                    return None
            else:
                return None
    except (domain.FestiveError, ValueError, IndexError, KeyError) as exc:
        say(
            sender,
            str(exc)
            if isinstance(exc, domain.FestiveError)
            else "That choice is no longer available. Send BACK or RUNS.",
        )
    return {"status": "festive"}
