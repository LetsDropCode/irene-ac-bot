"""Captain dashboard and named host search using existing chat/session storage."""

from app.db import get_cursor
from app.services import festive_admin_presenter as presenter
from app.services import festive_service as domain
from app.services import festive_weekly_service as weekly

PREFIX = "festive:admin:"
COMMANDS = {"FESTIVE ADMIN", "FESTIVE ADMIN TEXT"}


def home(sender, actor, state):
    from app.flows import festive_flow as chat

    with get_cursor() as cur:
        rows = domain.calendar(cur, actor, admin=True)
    body, counts = presenter.dashboard(rows)
    choices = [
        (PREFIX + "queue:" + k, title, f"{counts[k]} dates")
        for k, title in presenter.FILTERS.items()
    ]
    if weekly.active(sender):
        choices.append(
            (
                PREFIX + "weekly",
                "Weekly announcements",
                "Preview, refresh and share the weekly edition",
            )
        )
    state.update(mode="admin_home", kind="ADMIN", token=None, replacement_pending=False)
    chat.menu(sender, actor, state, body, choices)


def selection(actor, state, response):
    """Filter only presentation; every chosen date is revalidated by the session."""
    with get_cursor() as cur:
        rows = domain.calendar(cur, actor, admin=True)
    queue = state.get("admin_filter", "all")
    visible = {str(r["run_date"]): r for r in rows if presenter.matches(r, queue)}
    choices = []
    for option in response["data"]["options"]:
        row = visible.get(option["id"])
        if row:
            host = next((h for h in row["hosts"] if h["host_role"] == "LEAD"), None)
            description = presenter.STATUS[row["status"]] + (
                " · " + presenter.host_name(host) if host else ""
            )
            choices.append(
                {
                    **option,
                    "title": presenter.day_label(row["run_date"]),
                    "description": description,
                }
            )
    title = presenter.FILTERS.get(queue, "All festive dates")
    summary = f"🎄 *{title}*\n{len(choices)} dates · choose a run to review."
    if not choices:
        summary = f"🎄 *{title}*\nYou're all caught up here. Choose another queue from the captain desk."
    return {
        **response,
        "data": {**response["data"], "options": choices, "summary": summary},
    }


def search_prompt(sender, actor, state):
    from app.flows import festive_flow as chat

    # Keep the review's session/revision; selecting a person cannot approve a
    # different version of a run that changed while the captain was searching.
    state.update(
        mode="admin_search", replacement_pending=True, shown=[], search_results=[]
    )
    chat.save_chat(actor, state)
    chat.say(
        sender,
        "🔎 *Choose a lead host*\nSend at least 2 letters of their name, or their member ID.\nOnly existing members with active consent can be selected.\nBACK returns to the run; CANCEL closes this session.",
    )


def search(sender, actor, state, text):
    from app.flows import festive_flow as chat

    text = (text or "").strip()
    if not text or len(text) > 80 or (not text.isdigit() and len(text) < 2):
        raise domain.FestiveError(
            "Enter at least 2 letters of the name, or a member ID."
        )
    with get_cursor() as cur:
        domain.member(cur, actor, admin=True)
        if text.isdigit():
            if len(text) > 10:
                raise domain.FestiveError("Check the member ID and try again.")
            cur.execute(
                "SELECT id,first_name,last_name FROM members WHERE id=%s AND popia_acknowledged AND popia_withdrawn_at IS NULL AND first_name NOT IN ('','Unknown')",
                (int(text),),
            )
        else:
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            cur.execute(
                """SELECT id,first_name,last_name FROM members
                WHERE popia_acknowledged AND popia_withdrawn_at IS NULL AND first_name NOT IN ('','Unknown')
                AND concat_ws(' ',first_name,last_name) ILIKE %s
                ORDER BY first_name,last_name,id LIMIT 9""",
                ("%" + escaped + "%",),
            )
        members = cur.fetchall()
    if not members:
        chat.say(
            sender,
            "No eligible member found. Try another part of their name or member ID. BACK returns to the run.",
        )
        return
    state.update(mode="admin_search_results", search_results=[m["id"] for m in members])
    tag = chat.callback_revision(state)
    options = [
        (
            PREFIX + f"assign:{tag}:{m['id']}",
            presenter.host_name(m),
            f"Member {m['id']} · review before confirming",
        )
        for m in members
    ]
    options += [
        (PREFIX + "search", "Search again", "Try a different name"),
        ("festive:back", "Back to run", "Keep the current host"),
    ]
    body = "🔎 *Choose the member*\nNames can be similar; check the member ID. Nothing changes until you confirm."
    if len(members) == 9:
        body += "\nShowing the first 9 matches. Search again with more of the name to narrow it down."
    chat.menu(sender, actor, state, body, options)


def handle(sender, actor, state, command, key, raw_text):
    from app.flows import festive_flow as chat
    from app.flows import festive_weekly_flow

    if (
        not key
        and (raw_text or "").isdigit()
        and state.get("kind") == "ADMIN"
        and state.get("mode") != "admin_search"
    ):
        index = int(raw_text) - 1
        if 0 <= index < len(state.get("shown", [])):
            key = state["shown"][index]
        elif state.get("mode") == "admin_search_results":
            raise domain.FestiveError(
                "Choose one of the member numbers shown, or select Search again."
            )
    search_navigation = state.get("mode") in {
        "admin_search",
        "admin_search_results",
    } and (
        command == "BACK" or key == "festive:back" or key.startswith("festive:page:")
    )
    recognized = command in COMMANDS or key.startswith(PREFIX) or search_navigation
    searching = (
        state.get("mode") == "admin_search"
        and raw_text
        and command not in chat.COMMANDS | {"BACK", "CANCEL"}
        and not key
    )
    if not recognized and not searching:
        return None
    with get_cursor() as cur:
        domain.member(cur, actor, admin=True)
    if search_navigation:
        if key.startswith("festive:page:"):
            chat.menu(
                sender,
                actor,
                state,
                state["body"],
                state["options"],
                int(key.rsplit(":", 1)[1]),
            )
        else:
            chat.render(sender, actor, state, state["response"])
    elif command in COMMANDS or key == PREFIX + "home":
        if command == "FESTIVE ADMIN TEXT":
            state["client"] = "text"
        home(sender, actor, state)
    elif key.startswith(PREFIX + "queue:"):
        queue = key.rsplit(":", 1)[1]
        if queue not in presenter.FILTERS:
            raise domain.FestiveError("Choose a queue from FESTIVE ADMIN.")
        state.update(admin_filter=queue, replacement_pending=False)
        chat.start(sender, actor, state, "ADMIN")
    elif key == PREFIX + "weekly":
        return festive_weekly_flow.handle(sender, actor, state, "WEEKLY", "", "WEEKLY")
    elif key == PREFIX + "search":
        if (
            state.get("kind") != "ADMIN"
            or not state.get("token")
            or state.get("screen") != "ACTION"
        ):
            raise domain.FestiveError(
                "Open a run and choose its lead-host action first."
            )
        search_prompt(sender, actor, state)
    elif key.startswith(PREFIX + "assign:"):
        _, _, _, tag, target = key.split(":")
        if tag != chat.callback_revision(state) or int(target) not in state.get(
            "search_results", []
        ):
            raise domain.FestiveError(
                "That search is out of date. Open the run and search again."
            )
        state.update(mode="form", replacement_pending=False, search_results=[])
        chat.submit(sender, actor, state, {"choice": "REASSIGN", "replacement": target})
    elif searching:
        search(sender, actor, state, raw_text)
    else:
        raise domain.FestiveError("Send FESTIVE ADMIN to open the captain desk.")
    return {"status": "festive"}
