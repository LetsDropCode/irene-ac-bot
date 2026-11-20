"""Captain-only weekly previews and native list/text sharing workflow."""

from datetime import datetime, timedelta

from app.db import get_cursor
from app.services import festive_service as domain
from app.services import festive_transport as transport
from app.services import festive_weekly_service as weekly
from app.services.festive_config import capabilities, flag
from app.services.job_queue_service import enqueue_job

PREFIX = "festive:weekly:"
COMMANDS = {"WEEKLY", "WEEKLY TEXT", "WEEKLY ALERTS ON", "WEEKLY ALERTS OFF"}
OPTIONS = (
    "Preview this week",
    "Refresh announcement",
    "Copy/share announcement",
    "Next week's draft",
    "Previous announcements",
    "Mark as posted",
)


def send(payload):
    from app.whatsapp import _inbound_delivery

    state = _inbound_delivery.get()
    key = None
    if state and state["message_id"]:
        key = f"festive:weekly:reply:{state['message_id']}:{state['sequence']}"
        state["sequence"] += 1
    job = enqueue_job(
        "festive_weekly_reply",
        {
            "payload": payload,
            "expires_at": (domain.now() + timedelta(hours=23)).isoformat(),
        },
        dedupe_key=key,
    )
    if state:
        state["job_ids"].append(job)


def say(sender, body):
    for part in weekly.split_messages([body]):
        send(transport.text_payload(sender, part))


def deliver_reply(payload):
    if not weekly.active(payload["payload"]["to"]) or flag("FESTIVE_UAT_MODE", "true"):
        return
    if domain.now() >= datetime.fromisoformat(payload["expires_at"]):
        return
    # Authorization can change while a response waits in the durable queue.
    if payload["payload"]["to"] not in domain.ADMIN_NUMBERS:
        return
    from app.whatsapp import _send_direct

    if not _send_direct(payload["payload"]):
        raise RuntimeError("Weekly admin reply delivery failed")


def menu(sender, actor, state, body=None, options=None, page=0):
    from app.flows.festive_flow import save_chat

    options = options or [
        (PREFIX + str(i), label, "") for i, label in enumerate(OPTIONS, 1)
    ]
    pages = max(1, (len(options) + 7) // 8)
    page = max(0, min(page, pages - 1))
    rows = list(options[page * 8 : page * 8 + 8])
    if page:
        rows.append((PREFIX + f"page:{page - 1}", "Previous page", ""))
    if page + 1 < pages:
        rows.append((PREFIX + f"page:{page + 1}", "Next page", ""))
    body = body or (
        "🎄 *FESTIVE WEEKLY ANNOUNCEMENTS*\n"
        "Automatic generation · captain sharing\n"
        "WEEKLY TEXT for numbered menus. WEEKLY ALERTS ON / OFF for optional template notifications.\n"
        "FESTIVE ADMIN returns to the captain desk."
    )
    state.update(
        mode="weekly",
        token=None,
        weekly_options=options,
        weekly_body=body,
        shown=[row[0] for row in rows],
    )
    save_chat(actor, state)
    if capabilities(state.get("client", "auto"))["native"] and rows:
        send(
            transport.list_payload(
                sender,
                body,
                [
                    {"id": key, "title": title[:24], "description": desc[:72]}
                    for key, title, desc in rows
                ],
            )
        )
    else:
        say(
            sender,
            body
            + "\n"
            + "\n".join(
                f"{i}. {title} {desc}" for i, (_, title, desc) in enumerate(rows, 1)
            )
            + "\nBACK / CANCEL",
        )


def show(sender, actor, state, edition, share=False):
    from app.flows.festive_flow import save_chat

    state["weekly_edition_id"] = edition["id"]
    state["weekly_week"] = str(edition["week_start"])
    save_chat(actor, state)
    if edition["status"] == "FAILED":
        say(
            sender,
            "This edition could not be generated. "
            + (edition["last_error"] or "Refresh to retry."),
        )
        menu(sender, actor, state)
        return
    label = (
        "Future draft"
        if edition["week_start"] > weekly.local_now().date()
        else "Weekly edition"
    )
    say(
        sender,
        f"{label}: {edition['week_start']} · revision {edition['revision']} · {edition['status']}\n"
        "Copy or use WhatsApp's native Forward action on each announcement message below. Mark as posted only after you share it. This bot has not posted to a group.\n"
        + weekly.delivery_summary(actor, edition["id"]),
    )
    if edition["last_error"]:
        say(sender, edition["last_error"])
    for part in edition["messages"]:
        if edition["status"] == "OUTDATED":
            part = "*ARCHIVED — DO NOT SHARE*\n\n" + part
        send(transport.text_payload(sender, part))
    if edition["correction_messages"] and edition["status"] != "OUTDATED":
        say(
            sender,
            "Changes since the last posted edition (or previous preview). Ready-to-share correction:",
        )
        for part in edition["correction_messages"]:
            send(transport.text_payload(sender, part))
    if not share:
        menu(sender, actor, state)


def handle(sender, actor, state, command, key, raw_text):
    from app.flows.festive_flow import save_chat

    recognized = command in COMMANDS or key.startswith(PREFIX)
    if not recognized and state.get("mode") != "weekly":
        return None
    if (
        not recognized
        and command not in {"BACK", "CANCEL"}
        and not (raw_text or "").isdigit()
    ):
        return None
    try:
        with get_cursor() as cur:
            domain.member(cur, actor, admin=True)
        if not weekly.active(sender):
            transport.send(
                transport.text_payload(sender, "Weekly announcements are disabled.")
            )
            return {"status": "festive_weekly_disabled"}
        if not key and (raw_text or "").isdigit():
            index = int(raw_text) - 1
            if not 0 <= index < len(state.get("shown", [])):
                raise domain.FestiveError("Choose one of the numbers shown.")
            key = state["shown"][index]
        if command == "CANCEL":
            save_chat(actor, {})
            say(sender, "Weekly menu closed.")
        elif command in {"WEEKLY", "WEEKLY TEXT", "BACK"}:
            if command == "WEEKLY TEXT":
                state["client"] = "text"
            menu(sender, actor, state)
        elif command in {"WEEKLY ALERTS ON", "WEEKLY ALERTS OFF"}:
            from app.services.festive_weekly_notifications import subscribe

            subscribe(actor, command.endswith(" ON"))
            say(
                sender,
                "Weekly alert preference saved. Alerts require the captain-notification flag and an approved template; provider charges may apply. Send WEEKLY for previews.",
            )
        elif key.startswith(PREFIX + "page:"):
            menu(
                sender,
                actor,
                state,
                state["weekly_body"],
                state["weekly_options"],
                int(key.rsplit(":", 1)[1]),
            )
        elif key == PREFIX + "5":
            editions = weekly.history(actor)
            options = [
                (
                    PREFIX + f"view:{e['id']}",
                    f"{e['week_start']} · v{e['revision']}",
                    e["status"],
                )
                for e in editions
            ]
            menu(
                sender,
                actor,
                state,
                "Previous announcements · select a revision. Old revisions are for reference only.",
                options or [(PREFIX + "1", "No editions yet", "Preview this week")],
            )
        elif key.startswith(PREFIX + "view:"):
            edition_id = int(key.rsplit(":", 1)[1])
            edition = next(
                (e for e in weekly.history(actor) if e["id"] == edition_id), None
            )
            if not edition:
                raise domain.FestiveError("That edition is unavailable.")
            show(sender, actor, state, edition)
        elif key in {PREFIX + str(i) for i in (1, 2, 3, 4)}:
            week = weekly.week_for()
            if key == PREFIX + "4":
                week += timedelta(days=7)
            elif key in {PREFIX + "2", PREFIX + "3"} and state.get("weekly_week"):
                week = weekly.date.fromisoformat(state["weekly_week"])
            if week not in weekly.WEEKS:
                say(
                    sender,
                    "The four editions cover 7 December–3 January. Choose an edition to preview:",
                )
                menu(
                    sender,
                    actor,
                    state,
                    "Programme drafts",
                    [
                        (PREFIX + "draft:" + str(w), str(w), "Preview only")
                        for w in weekly.WEEKS
                    ],
                )
            else:
                show(
                    sender,
                    actor,
                    state,
                    weekly.generate(week, actor),
                    share=key == PREFIX + "3",
                )
        elif key.startswith(PREFIX + "draft:"):
            show(
                sender,
                actor,
                state,
                weekly.generate(
                    weekly.date.fromisoformat(key.rsplit(":", 1)[1]), actor
                ),
            )
        elif key == PREFIX + "6":
            edition_id = state.get("weekly_edition_id")
            if not edition_id:
                raise domain.FestiveError("Preview the edition you shared first.")
            menu(
                sender,
                actor,
                state,
                "Have you shared this exact revision to the club? This records your confirmation; it does not send a group message.",
                [
                    (
                        PREFIX + f"posted:{edition_id}",
                        "Yes, I shared it",
                        "Record posting confirmation",
                    ),
                    (PREFIX + "1", "Back to preview", ""),
                ],
            )
        elif key.startswith(PREFIX + "posted:"):
            weekly.mark_posted(actor, int(key.rsplit(":", 1)[1]))
            say(
                sender,
                "Recorded as posted by an administrator. No provider group-delivery confirmation is claimed.",
            )
            menu(sender, actor, state)
        else:
            raise domain.FestiveError("Send WEEKLY to open the latest menu.")
    except (domain.FestiveError, ValueError) as exc:
        # Do not return any content to unauthorized callers. Existing festive
        # transport can deliver the short denial; no sensitive data in payload.
        if sender not in domain.ADMIN_NUMBERS:
            transport.send(
                transport.text_payload(sender, "Club administrator access is required.")
            )
        else:
            say(sender, str(exc))
    return {"status": "festive_weekly"}
