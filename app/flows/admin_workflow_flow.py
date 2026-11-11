"""Small admin views with date/member IDs in buttons, never list positions."""

from datetime import datetime, timedelta, timezone

from app.services import admin_workflow_service as service
from app.services.tt_status_service import latest_tt_date, get_event_summary, format_event_summary
from app.services.submission_gate import SA_TZ
from app.services.member_service import set_profile_state, clear_profile_state
from app.whatsapp import send_text, send_admin_workflow_buttons, send_admin_workflow_list


def _name(row):
    return f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()[:70]


def _buttons(sender, body, buttons):
    if not send_admin_workflow_buttons(sender, body, buttons):
        send_text(sender, body + "\n\n" + "\n".join(f"{label}: {key}" for key, label in buttons))


def show_event(sender, event_date=None):
    service.require_admin(sender)
    day = event_date or latest_tt_date()
    buttons = []
    if day - timedelta(days=7) >= datetime(2000, 1, 1).date():
        buttons.append((f"adm_event:{day - timedelta(days=7)}", "Previous TT"))
    if day < latest_tt_date():
        buttons.append((f"adm_event:{day + timedelta(days=7)}", "Next TT"))
    buttons.append((f"adm_pending:{day}:1", "Outstanding results"))
    _buttons(sender, "📋 *TT event summary*\n\n" + format_event_summary(get_event_summary(day)), buttons)


def show_pending(sender, day=None, page=1):
    day = day or latest_tt_date()
    rows, more = service.pending_members(sender, day, page)
    if not rows:
        _buttons(sender, f"✅ No outstanding results on this page for {day:%d %B %Y}.",
                 [(f"adm_event:{day}", "Event summary")])
        return 0
    options = [(f"adm_person:{day}:{r['id']}", f"{_name(r)}"[:24], service.pending_stage(r)) for r in rows]
    if page > 1:
        options.append((f"adm_pending:{day}:{page-1}", "Previous page", "More outstanding members"))
    if more:
        options.append((f"adm_pending:{day}:{page+1}", "Next page", "More outstanding members"))
    options.append((f"adm_event:{day}", "Event summary", "Back to this TT"))
    body = f"⏳ *Outstanding results — {day:%d %B %Y}*\nSelect a member to see the unfinished step and follow-up options."
    if not send_admin_workflow_list(sender, body, options):
        send_text(sender, body + "\n\n" + "\n".join(f"{title}: {key}" for key, title, _ in options))
    return len(rows)


def show_person(sender, day, member_id):
    rows, _ = service.pending_members(sender, day, member_id=member_id)
    if not rows:
        send_text(sender, "This member no longer has an outstanding result. Send PENDING to refresh.")
        return
    row = rows[0]
    status_label = {"PENDING": "Queued", "RUNNING": "Sending", "DONE": "Processed", "FAILED": "Failed", "SENT": "Sent to WhatsApp"}
    body = (f"*{_name(row)} — {day:%d %B %Y}*\n"
            f"{service.pending_stage(row)}\n"
            f"Reminder: {status_label.get(row.get('reminder_status'), 'None recorded')}\n"
            f"Admin prompt: {status_label.get(row.get('prompt_status'), 'None recorded')}")
    allowed, reason = service.prompt_eligibility(row, day)
    buttons = [(f"adm_open:{day}:{member_id}", "Open member")]
    if allowed and not row.get("prompt_status"):
        buttons.append((f"adm_resend:{day}:{member_id}", "Resend prompt"))
    elif reason:
        body += "\n\n" + reason
    buttons.append((f"adm_pending:{day}:1", "Back to list"))
    _buttons(sender, body, buttons)


def show_changes(sender, member_id=None, page=1):
    rows, more = service.recent_changes(sender, member_id, page)
    body = "📝 *Recent result changes*\nSelect a change to see who made it and the before/after values."
    if not rows:
        send_text(sender, "No recorded changes on this page. Send ADMIN for tools.")
        return
    options = [(f"adm_change:{r['id']}", f"#{r['id']} {r['first_name']}"[:24],
                f"{r['event_date']} · {r.get('reason') or 'correction'}"[:72]) for r in rows]
    if page > 1:
        options.append((f"adm_changes:{member_id or 0}:{page-1}", "Previous page", "Newer changes"))
    if more:
        options.append((f"adm_changes:{member_id or 0}:{page+1}", "Next page", "Older changes"))
    if not send_admin_workflow_list(sender, body, options):
        send_text(sender, body + "\n\n" + "\n".join(f"{title}: {key}" for key, title, _ in options))


def _value(distance, time_text):
    return (f"{distance} km — " if distance else "") + (time_text or "Not entered")[:250]


def show_change(sender, change_id):
    rows, _ = service.recent_changes(sender, correction_id=change_id)
    if not rows:
        send_text(sender, "That change is no longer available.")
        return
    r = rows[0]
    stamp = r["created_at"]
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    admin_name = " ".join(filter(None, [r.get("admin_first_name"), r.get("admin_last_name")])) or "Former admin"
    admin_name = admin_name[:70]
    body = (f"*Change #{r['id']} — {_name(r)}*\n"
            f"TT: {r['event_date']}\nBy: {admin_name}\nWhen: {stamp.astimezone(SA_TZ):%d %b %Y %H:%M} SAST\n"
            f"Before: {_value(r['old_distance_text'], r['old_time_text'])}\n"
            f"After: {_value(r['new_distance_text'], r['new_time_text'])}")
    buttons = []
    if service.can_undo(r):
        buttons.append((f"adm_undo:{r['id']}", "Undo correction"))
    else:
        body += "\n\nUndo unavailable for older records, later edits or an undo entry."
    buttons.append((f"adm_changes:{r['member_id']}:1", "Member changes"))
    _buttons(sender, body, buttons)


def handle_admin_workflow(actions, sender, text, button, menu_action, admin_member):
    # Called only after the admin gate; service reads/writes recheck authorization.
    key = (button or {}).get("id", "")
    if not key and text and text.lower().startswith("adm_"):
        key = text.lower()
    state = (admin_member or {}).get("profile_state") or ""
    if menu_action == "ADMIN_TT_STATUS":
        actions.clear_admin_edit_state_if_needed(admin_member)
        show_event(sender)
        return {"status": "status"}
    if menu_action == "ADMIN_PENDING":
        actions.clear_admin_edit_state_if_needed(admin_member)
        count = show_pending(sender)
        return {"status": "pending_list" if count else "no_pending"}
    if text in {"CHANGES", "RECENT CHANGES"} or key == "admin_recent_changes":
        selected = int(state.split("|")[1]) if state.startswith("ADMIN_MEMBER|") else None
        actions.clear_admin_edit_state_if_needed(admin_member)
        show_changes(sender, selected)
        return {"status": "admin_changes"}
    if state.startswith(("ADMIN_UNDO|", "ADMIN_PROMPT|")) and text in {"CANCEL", "NO"}:
        clear_profile_state(admin_member["id"])
        send_text(sender, "Cancelled. No change made and no prompt sent.")
        return {"status": "admin_action_cancelled"}
    if not key.startswith("adm_"):
        return None
    if not admin_member or not admin_member.get("popia_acknowledged"):
        send_text(sender, "An active admin profile is required.")
        return {"status": "admin_profile_required"}
    try:
        parts = key.split(":")
        action = parts[0]
        if action in {"adm_event", "adm_pending", "adm_person", "adm_open", "adm_resend", "adm_send"}:
            day = service.parse_event(parts[1])
            if action == "adm_event":
                actions.clear_admin_edit_state_if_needed(admin_member)
                show_event(sender, day)
            elif action == "adm_pending":
                actions.clear_admin_edit_state_if_needed(admin_member)
                show_pending(sender, day, int(parts[2]))
            else:
                mid = int(parts[2])
                if action == "adm_person":
                    actions.clear_admin_edit_state_if_needed(admin_member)
                    show_person(sender, day, mid)
                elif action == "adm_open":
                    rows, _ = service.pending_members(sender, day, member_id=mid)
                    if not rows:
                        raise ValueError("This result is no longer outstanding.")
                    from app.flows.admin_flow import _send_member_center
                    row = dict(rows[0], today_status=rows[0].get("status"))
                    # Member centre is general; don't label a historical pending result as today's.
                    if day != datetime.now(SA_TZ).date():
                        row.update(today_status=None, tt_code_verified=False)
                    _send_member_center(sender, admin_member, row)
                elif action == "adm_resend":
                    rows, _ = service.pending_members(sender, day, member_id=mid)
                    if not rows:
                        raise ValueError("This result is no longer outstanding.")
                    allowed, reason = service.prompt_eligibility(rows[0], day)
                    if not allowed:
                        raise ValueError(reason)
                    set_profile_state(admin_member["id"], f"ADMIN_PROMPT|{day}|{mid}")
                    _buttons(sender, f"Resend one resume prompt to {_name(rows[0])} for {day}?",
                             [(f"adm_send:{day}:{mid}", "Confirm resend"), (f"adm_person:{day}:{mid}", "Cancel")])
                else:
                    if state != f"ADMIN_PROMPT|{day}|{mid}":
                        raise ValueError("This confirmation expired. Open the pending member again.")
                    _, message = service.queue_member_prompt(sender, mid, day)
                    clear_profile_state(admin_member["id"])
                    send_text(sender, message)
        elif action == "adm_changes":
            actions.clear_admin_edit_state_if_needed(admin_member)
            show_changes(sender, int(parts[1]) or None, int(parts[2]))
        elif action == "adm_change":
            actions.clear_admin_edit_state_if_needed(admin_member)
            show_change(sender, int(parts[1]))
        elif action == "adm_undo":
            cid = int(parts[1])
            rows, _ = service.recent_changes(sender, correction_id=cid)
            if not rows or not service.can_undo(rows[0]):
                raise ValueError("Undo is no longer available. Refresh Recent changes.")
            row = rows[0]
            set_profile_state(admin_member["id"], f"ADMIN_UNDO|{cid}")
            _buttons(sender, f"Undo change #{cid} for {_name(row)}?\n"
                     f"Restore: {_value(row['old_distance_text'], row['old_time_text'])}",
                     [(f"adm_undo_confirm:{cid}", "Confirm undo"), (f"adm_change:{cid}", "Cancel")])
        elif action == "adm_undo_confirm":
            cid = int(parts[1])
            if state != f"ADMIN_UNDO|{cid}":
                raise ValueError("This confirmation expired. Open Recent changes again.")
            _, message = service.undo_correction(sender, cid)
            clear_profile_state(admin_member["id"])
            send_text(sender, message)
        else:
            raise ValueError("This admin action is no longer available.")
    except (ValueError, IndexError):
        send_text(sender, "That action is unavailable or expired. Send TT STATUS, PENDING or CHANGES to refresh.")
        return {"status": "admin_action_unavailable"}
    return {"status": "admin_workflow"}
