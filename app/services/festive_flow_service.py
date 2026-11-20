"""One durable state machine for native Flows and accessible chat fallback."""

import hashlib
import json
import secrets
from datetime import date

from psycopg2.extras import Json

from app.db import get_cursor
from app.services import festive_admin_presenter as admin_ui
from app.services import festive_service as domain
from app.services.festive_config import enabled

DETAIL_FIELDS = list(domain.TEXT_FIELDS) + [
    "maps_url",
    "route_url",
    "start_time",
    "distances",
    "walkers_welcome",
    "coffee_arrangements",
]


def token_hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def choices(values):
    return [{"id": str(key), "title": str(title)[:30]} for key, title in values]


def get_rows(cur, session):
    return domain.calendar(cur, session["member_id"], admin=session["kind"] == "ADMIN")


def selection_view(cur, session):
    rows = get_rows(cur, session)
    kind, actor = session["kind"], session["member_id"]
    options = []
    for row in rows:
        day = str(row["run_date"])
        if (
            kind != "MANAGE"
            and kind != "ADMIN"
            and row["run_date"] < domain.now().date()
        ):
            continue
        if (
            kind == "HOST"
            and row["status"] not in {"CANCELLED", "COMPLETED"}
            and len(row["hosts"]) < 2
        ):
            roles = {h["host_role"] for h in row["hosts"]}
            label = "lead host" if "LEAD" not in roles else "co-host"
            options.append((day, f"{day} · {label}"))
        elif kind == "JOIN" and row["status"] == "PUBLISHED":
            options.append(
                (day, day + " · " + (row["published"].get("title") or "Social run"))
            )
        elif kind == "MANAGE":
            for h in row["hosts"]:
                if h["member_id"] == actor:
                    options.append(("h:" + day, day + " · " + h["host_role"].title()))
            if row["mine"] and row["mine"]["status"] == "ACTIVE":
                options.append(
                    ("r:" + day, day + " · " + row["mine"]["selected_distance"])
                )
        elif kind == "ADMIN":
            options.append((day, admin_ui.day_label(row["run_date"])))
    return view(
        "CHOOSE",
        options=choices(options),
        summary="Choose a festive date."
        if options
        else "No selections available. Close this form or send RUNS.",
        role="LEAD",
        reminders=False,
    )


def view(screen, **data):
    return {"screen": screen, "data": {"error": "", **data}}


def create_session(actor, kind):
    token = "festive." + secrets.token_urlsafe(32)
    with get_cursor() as cur:
        m = domain.member(cur, actor, admin=kind == "ADMIN")
        if not enabled(m["phone"]):
            raise domain.FestiveError("Festive runs are not enabled for this account.")
        session = {"member_id": actor, "kind": kind}
        state = selection_view(cur, session)
        state["data"]["revision"] = "0"
        cur.execute(
            "INSERT INTO festive_run_sessions(token_hash,member_id,kind,state) VALUES (%s,%s,%s,%s)",
            (token_hash(token), actor, kind, Json(state)),
        )
    return token, state


def load_session(cur, token, actor=None):
    if (
        not isinstance(token, str)
        or not token.startswith("festive.")
        or len(token) > 100
    ):
        raise domain.FestiveError(
            "Invalid festive form. Send HOST, JOIN or MY RUNS to restart."
        )
    cur.execute(
        "SELECT * FROM festive_run_sessions WHERE token_hash=%s AND expires_at>now() FOR UPDATE",
        (token_hash(token),),
    )
    session = cur.fetchone()
    if not session or (actor is not None and session["member_id"] != actor):
        raise domain.FestiveError(
            "This form expired or belongs to another member. Start again."
        )
    m = domain.member(cur, session["member_id"], admin=session["kind"] == "ADMIN")
    if not enabled(m["phone"]):
        raise domain.FestiveError("Festive runs are currently unavailable.")
    return session


def exchange(request, actor=None):
    if request.get("action") == "ping":
        return {"version": "4.0", "data": {"status": "active"}}
    token = request.get("flow_token")
    with get_cursor() as cur:
        session = load_session(cur, token, actor)
        state = session["state"]
        if request.get("action") == "INIT":
            if state["screen"] == "CHOOSE":
                state = selection_view(cur, session)
                state["data"]["revision"] = str(session["revision"])
                cur.execute(
                    "UPDATE festive_run_sessions SET state=%s WHERE token_hash=%s",
                    (Json(state), session["token_hash"]),
                )
            return {"version": "4.0", **{k: state[k] for k in ("screen", "data")}}
        data = request.get("data") or {}
        if not isinstance(data, dict) or request.get("action") not in {
            "data_exchange",
            "BACK",
        }:
            raise domain.FestiveError("Invalid form action.")
        if request.get("action") == "BACK":
            history = state.get("history", [])
            updated = history[-1] if history else selection_view(cur, session)
            if updated["screen"] == "CHOOSE":
                updated = selection_view(cur, session)
            elif session["kind"] == "ADMIN" and updated["screen"] == "ACTION":
                selected = updated["selected"]
                updated = admin_view(
                    current_row(cur, session, selected["day"]), selected
                )
            updated["history"] = history[:-1]
        else:
            revision = str(data.get("revision", ""))
            digest = hashlib.sha256(
                json.dumps(
                    {"screen": request.get("screen"), "data": data}, sort_keys=True
                ).encode()
            ).hexdigest()
            receipt = session["receipts"].get(revision)
            if receipt:
                if receipt["digest"] != digest:
                    raise domain.FestiveError(
                        "This step was already submitted. Reopen the form to continue."
                    )
                return receipt["response"]
            if (
                revision != str(session["revision"])
                or request.get("screen") != state["screen"]
            ):
                raise domain.FestiveError(
                    "This form is out of date. Reopen it to continue."
                )
            cur.execute("SAVEPOINT festive_action")
            try:
                updated = advance(cur, session, data)
            except domain.FestiveError as exc:
                cur.execute("ROLLBACK TO SAVEPOINT festive_action")
                # Returned data supplies init-values when the native client
                # renders this screen again. Keep the submitted form on errors,
                # including submit-vs-draft intent, rather than resetting it.
                entered = (
                    {
                        k: v
                        for k, v in data.items()
                        if k in DETAIL_FIELDS + ["save_mode"]
                        and isinstance(v, str)
                        and len(v) <= 4096
                    }
                    if state["screen"] == "DETAILS"
                    else {}
                )
                updated = {
                    **state,
                    "data": {**state["data"], **entered, "error": str(exc)},
                }
            except (TypeError, KeyError):
                cur.execute("ROLLBACK TO SAVEPOINT festive_action")
                updated = {
                    **state,
                    "data": {
                        **state["data"],
                        "error": "Invalid field values. Please review this form.",
                    },
                }
            cur.execute("RELEASE SAVEPOINT festive_action")
            if updated["screen"] != state["screen"]:
                previous = {k: v for k, v in state.items() if k != "history"}
                if state["screen"] == "DETAILS":
                    previous["data"] = {
                        **state["data"],
                        **{
                            k: v
                            for k, v in data.items()
                            if k in DETAIL_FIELDS + ["save_mode"]
                        },
                    }
                updated["history"] = state.get("history", []) + [previous]
            else:
                updated["history"] = state.get("history", [])
        revision_number = session["revision"] + 1
        updated["data"]["revision"] = str(revision_number)
        response = {"version": "4.0", **{k: updated[k] for k in ("screen", "data")}}
        receipts = session["receipts"]
        if request.get("action") != "BACK":
            receipts[str(session["revision"])] = {
                "digest": digest,
                "response": response,
            }
        # Bound the session document; old retries safely reject instead of executing.
        receipts = dict(list(receipts.items())[-40:])
        cur.execute(
            "UPDATE festive_run_sessions SET state=%s,revision=%s,receipts=%s WHERE token_hash=%s",
            (Json(updated), revision_number, Json(receipts), session["token_hash"]),
        )
        return response


def current_row(cur, session, day):
    return next(
        (row for row in get_rows(cur, session) if str(row["run_date"]) == day), None
    )


def admin_view(row, selected):
    if not row:
        raise domain.FestiveError(
            "This run is no longer available. Return to FESTIVE ADMIN."
        )
    return {
        **view(
            "ACTION",
            summary=admin_ui.review(row),
            options=admin_ui.options(row),
            replacement="",
        ),
        "selected": {**selected, "revision": row["revision"]},
    }


def details_view(row, selected):
    d = row.get("draft") or {}
    fields = {k: d.get(k, "") for k in DETAIL_FIELDS}
    fields["distances"] = ", ".join(d.get("distances", []))
    fields["walkers_welcome"] = "yes" if d.get("walkers_welcome") else "no"
    fields["coffee_arrangements"] = d.get("coffee_arrangements", "TBC")
    return {
        **view(
            "DETAILS",
            **fields,
            summary=f"{row['run_date']} · Save unfinished details as a draft.",
            save_mode="draft",
        ),
        "selected": selected,
    }


def rsvp_view(row, selected):
    if row["status"] != "PUBLISHED":
        raise domain.FestiveError("This run is not currently joinable.")
    return {
        **view(
            "RSVP",
            summary=domain.public_summary(row),
            options=choices((d, d) for d in row["published"]["distances"]),
            distance=(row["mine"] or {}).get("selected_distance", ""),
            reminders=(row["mine"] or {}).get("reminder_opt_in", False),
        ),
        "selected": selected,
    }


def advance(cur, session, data):
    state, actor, kind = session["state"], session["member_id"], session["kind"]
    screen = state["screen"]
    if data.get("intent") == "cancel":
        return view(
            "DONE",
            summary="Cancelled. Previously saved registrations and drafts are kept.",
        )
    if screen == "CHOOSE":
        key = data.get("choice")
        options = selection_view(cur, session)["data"]["options"]
        if key not in {o["id"] for o in options}:
            raise domain.FestiveError(
                "That choice is no longer available. Go BACK to refresh."
            )
        day = key[2:] if key.startswith(("h:", "r:")) else key
        row = current_row(cur, session, day)
        selected = {"day": day, "revision": row["revision"], "choice": key}
        if kind == "HOST":
            role = data.get("role", "LEAD")
            if role not in {"LEAD", "COHOST"}:
                raise domain.FestiveError("Choose lead host or co-host.")
            selected.update(role=role, reminders=data.get("reminders") is True)
            return {
                **view(
                    "BOOK",
                    summary=f"Register as {role.lower()} on {day}? You can save run details later.",
                ),
                "selected": selected,
            }
        if kind == "JOIN":
            return rsvp_view(row, selected)
        options = (
            [("edit", "Edit details"), ("withdraw_host", "Withdraw hosting")]
            if key.startswith("h:")
            else [("rsvp", "Change RSVP"), ("withdraw_rsvp", "Cancel RSVP")]
        )
        summary = domain.public_summary(row)
        if kind == "ADMIN":
            return admin_view(row, selected)
        if row.get("counts"):
            summary += "\nBy distance: " + ", ".join(
                f"{c['selected_distance']}: {c['count']}" for c in row["counts"]
            )
        return {
            **view("ACTION", summary=summary, options=choices(options), replacement=""),
            "selected": selected,
        }
    selected = dict(state.get("selected") or {})
    day = selected.get("day")
    if screen == "BOOK":
        if data.get("confirm") is not True:
            raise domain.FestiveError("Please confirm the hosting registration.")
        row = domain.book(
            cur,
            actor,
            day,
            selected["role"],
            data.get("reminders", selected["reminders"]) is True,
        )
        selected["revision"] = row["revision"]
        if selected["role"] == "COHOST":
            return view(
                "DONE", summary=f"You are registered as co-host on {day}. Thank you! 💚"
            )
        return details_view(current_row(cur, session, day), selected)
    if screen == "ACTION":
        action = data.get("choice")
        if action not in {o["id"] for o in state["data"]["options"]}:
            raise domain.FestiveError("Choose a listed action.")
        row = current_row(cur, session, day)
        if kind == "ADMIN":
            domain.check_revision(row, selected["revision"])
            if action not in {o["id"] for o in admin_ui.options(row)}:
                raise domain.FestiveError(
                    "This action is no longer available. Go BACK to refresh the run."
                )
        selected["revision"] = row["revision"]
        if action == "edit":
            domain.require_lead(cur, actor, row)
            return details_view(row, selected)
        if action == "rsvp":
            return rsvp_view(row, selected)
        selected["operation"] = action
        if action == "REASSIGN":
            try:
                selected["replacement"] = int(data.get("replacement", ""))
            except (TypeError, ValueError):
                raise domain.FestiveError(
                    "Enter the existing member ID for the new lead host."
                ) from None
        warning = (
            " Withdrawing a published lead host cancels the run; an admin must reopen it."
            if action == "withdraw_host"
            else ""
        )
        if kind == "ADMIN":
            replacement = (
                domain.member(cur, selected["replacement"])
                if action == "REASSIGN"
                else None
            )
            if replacement and any(
                h["host_role"] == "LEAD" and h["member_id"] == replacement["id"]
                for h in row["hosts"]
            ):
                raise domain.FestiveError(
                    "That member is already the lead host. Their saved details have been kept. Choose another member or go BACK."
                )
            return {
                **view(
                    "REVIEW",
                    summary=admin_ui.confirmation(row, action, replacement),
                    confirm_label=admin_ui.ACTIONS[action][0][:20],
                ),
                "selected": selected,
            }
        return {
            **view(
                "REVIEW",
                summary=f"Confirm {action.replace('_', ' ').lower()} for {day}?"
                + warning,
            ),
            "selected": selected,
        }
    if screen == "DETAILS":
        clean = domain.validate_details(
            data, complete=data.get("save_mode") == "submit"
        )
        selected.update(
            operation="details", details=clean, submit=data.get("save_mode") == "submit"
        )
        summary = (
            f"{day} · {'Submit for approval' if selected['submit'] else 'Save draft'}\n"
            + "\n".join(
                f"{k.replace('_', ' ')}: {v}" for k, v in clean.items() if v != ""
            )
        )
        return {**view("REVIEW", summary=summary), "selected": selected}
    if screen == "RSVP":
        distance = data.get("distance")
        if distance not in {o["id"] for o in state["data"]["options"]}:
            raise domain.FestiveError("Choose an offered distance.")
        selected.update(
            operation="rsvp", distance=distance, reminders=data.get("reminders") is True
        )
        row = current_row(cur, session, day)
        return {
            **view(
                "REVIEW",
                summary=f"{day} · {distance}\n{domain.public_summary(row)}\nReminders: {'on' if selected['reminders'] else 'off'}",
            ),
            "selected": selected,
        }
    if screen == "REVIEW":
        if data.get("confirm") is not True:
            raise domain.FestiveError("Please confirm or go BACK.")
        op = selected["operation"]
        if op == "details":
            domain.save_details(
                cur,
                actor,
                day,
                selected["details"],
                selected["submit"],
                selected["revision"],
            )
            summary = (
                "Details submitted for admin review."
                if selected["submit"]
                else "Draft saved. Return with MY HOSTS to finish later."
            )
        elif op == "rsvp":
            domain.rsvp(
                cur,
                actor,
                day,
                selected["distance"],
                selected["reminders"],
                selected["revision"],
            )
            approved = current_row(cur, session, day)["published"]
            summary = (
                f"You're joining on {day}: {selected['distance']}. "
                f"{approved['start_time']} at {approved['meeting_point']}. "
                f"Reminders: {'on' if selected['reminders'] else 'off'}. "
                "Saved in MY RUNS. RSVP is optional."
            )
        elif op == "withdraw_rsvp":
            domain.withdraw_rsvp(cur, actor, day)
            summary = "RSVP cancelled."
        elif op == "withdraw_host":
            domain.check_revision(domain.slot(cur, day), selected["revision"])
            domain.withdraw_host(cur, actor, day)
            summary = "Hosting withdrawn. Published lead-host withdrawals cancel the run for admin review."
        elif kind == "ADMIN":
            domain.admin_action(
                cur, actor, day, op, selected["revision"], selected.get("replacement")
            )
            return view(
                "DONE",
                summary=f"📅 {admin_ui.day_label(date.fromisoformat(day))}\n{admin_ui.success(op)}",
            )
        else:
            raise domain.FestiveError("Invalid operation.")
        return view("DONE", summary=f"{day}\n{summary}\nThank you, Irene family 💚")
    if screen == "DONE":
        return state
    raise domain.FestiveError("Invalid form screen.")


def completion(token, actor):
    with get_cursor() as cur:
        session = load_session(cur, token, actor)
        if session["state"]["screen"] != "DONE":
            raise domain.FestiveError(
                "This form is unfinished. Reopen it or send MY HOSTS / MY RUNS."
            )
        return session["state"]["data"]["summary"]
