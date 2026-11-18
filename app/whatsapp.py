# app/whatsapp.py

import logging
import os
import hashlib
import json
import requests
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, Any

from app.services.validation import time_to_seconds
from app.services.insight_services import seconds_to_pace
from app.branding import SHORT_BRAND_NAME, TAGLINE, WHATSAPP_FOOTER
from app import config
from app.meta_api import graph_base_url, MetaSendError, response_error
from app.native_messages import reply_buttons, selection_list
from app.config import PHONE_NUMBER_ID, WHATSAPP_TOKEN, WHATSAPP_ADMIN_DATE_FLOW_ID

CONNECT_TIMEOUT = float(os.getenv("WHATSAPP_CONNECT_TIMEOUT", "2"))
READ_TIMEOUT = float(os.getenv("WHATSAPP_READ_TIMEOUT", "5"))

_session = requests.Session()
logger = logging.getLogger(__name__)
_outbound_job_id = ContextVar("outbound_job_id", default=None)


@contextmanager
def outbound_job(job_id):
    token = _outbound_job_id.set(job_id)
    try:
        yield
    finally:
        _outbound_job_id.reset(token)


_inbound_delivery = ContextVar("inbound_delivery", default=None)


@contextmanager
def queue_inbound_replies(message_id: str | None):
    """Collect durable reply IDs and give messages stable keys across retries."""
    state = {"message_id": message_id, "sequence": 0, "job_ids": []}
    token = _inbound_delivery.set(state)
    try:
        yield state["job_ids"]
    finally:
        _inbound_delivery.reset(token)


def current_reply_key():
    state = _inbound_delivery.get()
    if state and state["message_id"]:
        return f"{state['message_id']}:{state['sequence']}"
    return None


def collect_reply_job(job_id):
    state = _inbound_delivery.get()
    if state:
        state["job_ids"].append(job_id)
        state["sequence"] += 1


def _mask_phone(value: str | None) -> str:
    if not value:
        return "unknown"
    if len(value) <= 4:
        return "****"
    return f"***{value[-4:]}"


def _graph_url() -> str:
    return f"{graph_base_url(config.WHATSAPP_GRAPH_API_VERSION)}/{PHONE_NUMBER_ID}/messages"


def _format_confirmation_body(distance: str, time: str) -> str:
    lines = [
        "Ready to save this TT result?",
        "",
        f"Distance: {distance} km",
        f"Time: {time}",
    ]

    try:
        pace = seconds_to_pace(time_to_seconds(time), distance)
    except (TypeError, ValueError):
        pace = None

    if pace:
        lines.append(f"Pace: {pace}")

    lines.extend([
        "",
        "Confirm to lock it in, or edit if anything looks off.",
    ])
    return "\n".join(lines)


# ─────────────────────────────────────────────
# INTERNAL SEND HELPER (HARD LOGGING)
# ─────────────────────────────────────────────
def _send(payload: Dict[str, Any]) -> bool:
    state = _inbound_delivery.get()
    # Every outbound path, including CLI campaigns and generated follow-ups,
    # first persists a queue row. Context adds a stable key where available.
    sequence = state["sequence"] if state else None
    dedupe_key = None
    if state and state["message_id"]:
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        dedupe_key = f"outbound:{state['message_id']}:{sequence}:{payload_hash}"
    from app.services.job_queue_service import enqueue_whatsapp_send

    job_id = enqueue_whatsapp_send(payload, dedupe_key=dedupe_key)
    if job_id is None:
        raise RuntimeError("Could not queue WhatsApp reply")
    if state:
        state["sequence"] = sequence + 1
        state["job_ids"].append(job_id)
    return True


def _send_direct(payload: Dict[str, Any]) -> bool:
    message_type = payload.get("type")
    recipient = payload.get("to")
    logger.info(
        "WhatsApp send attempt: type=%s to=%s",
        message_type,
        _mask_phone(recipient),
    )

    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        logger.error(
            "WhatsApp env vars missing: token_present=%s phone_number_id_present=%s",
            bool(WHATSAPP_TOKEN),
            bool(PHONE_NUMBER_ID),
        )
        raise MetaSendError("configuration", permanent=True)

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    job_id = _outbound_job_id.get()
    if config.WHATSAPP_DELIVERY_STATUS_ENABLED and job_id is not None:
        payload = {**payload, "biz_opaque_callback_data": f"job:{job_id}"}
    try:
        response = _session.post(
            _graph_url(),
            json=payload,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )

        try:
            data = response.json()
        except (ValueError, TypeError):
            data = {}
        if not response.ok:
            raise response_error(response.status_code, data)
        logger.info("WhatsApp API accepted message: type=%s", message_type)
        if config.WHATSAPP_DELIVERY_STATUS_ENABLED and job_id is not None:
            from app.services.delivery_status_service import record_acceptance
            try:
                messages = data.get("messages", []) if isinstance(data, dict) else []
                for message in messages:
                    record_acceptance(job_id, message.get("id"))
            except Exception:
                # The send succeeded. A diagnostic write failure must never
                # retry the message; signed callbacks can repair correlation.
                logger.error("Could not record API acceptance; awaiting status callback")
        return True
    except requests.RequestException:
        # Exception strings may contain URLs, headers or echoed request data.
        raise MetaSendError("network") from None


# ─────────────────────────────────────────────
# BASIC TEXT MESSAGE
# ─────────────────────────────────────────────
def send_text(to: str, text: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": text
        },
    }
    return _send(payload)


def send_image(to: str, image_url: str, caption: str | None = None) -> bool:
    """Send a publicly accessible image in the active WhatsApp conversation."""
    image = {"link": image_url}
    if caption:
        image["caption"] = caption
    return _send({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": image,
    })


# ─────────────────────────────────────────────
# MAIN MENU LIST
# ─────────────────────────────────────────────
def send_main_menu_list(to: str, admin: bool = False, member: dict | None = None) -> bool:
    """Send the member menu using the already-loaded sharing preference."""
    if config.WHATSAPP_NATIVE_UX_ENABLED:
        return send_native_main_menu(to, admin=admin)
    rows = [
        {
            "id": "menu_submit",
            "title": "Submit result",
            "description": "Check in and submit tonight's TT.",
        },
        {
            "id": "menu_profile",
            "title": "My profile",
            "description": "View or edit your details.",
        },
        {
            "id": "menu_season",
            "title": "My season",
            "description": "This calendar year: attendance and season bests.",
        },
        {
            "id": "menu_leaderboard",
            "title": "Leaderboards",
            "description": "Tonight, season bests, all-time PBs and rankings.",
        },
        {
            "id": "menu_shop",
            "title": "The Irene Shop",
            "description": "Shop Irene AC gear and products.",
        },
        {
            "id": "menu_league_standings",
            "title": "League standings",
            "description": "Open The Irene League standings.",
        },
        {
            "id": "menu_history",
            "title": "My history",
            "description": "Browse your TT results by calendar year.",
        },
        {
            "id": "menu_privacy",
            "title": "Privacy choices",
            "description": "Consent, sharing, MY DATA and deletion.",
        },
    ]

    if member and member.get("leaderboard_opt_out"):
        rows.append({
            "id": "menu_opt_in",
            "title": "Show my results",
            "description": "Show my results on public leaderboards again.",
        })
    else:
        rows.append({
            "id": "menu_opt_out",
            "title": "Hide my results",
            "description": "Hide my results from public leaderboards.",
        })

    if admin:
        rows.extend([
            {
                "id": "admin_menu",
                "title": "Admin tools",
                "description": "Code, status, pending and resend tools.",
            },
        ])

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": f"🌳 {SHORT_BRAND_NAME}"},
            "body": {"text": f"{TAGLINE}. What would you like to do?"},
            "footer": {"text": "Type HELP anytime."},
            "action": {
                "button": "Open menu",
                "sections": [
                    {
                        "title": "Member options",
                        "rows": rows,
                    }
                ],
            },
        },
    }
    return _send(payload)


# ─────────────────────────────────────────────
# ADMIN MENU LIST
# ─────────────────────────────────────────────
def send_admin_menu_list(to: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": f"🌳 {SHORT_BRAND_NAME} admin"},
            "body": {"text": "Keep Tuesday night running smoothly."},
            "footer": {"text": WHATSAPP_FOOTER},
            "action": {
                "button": "Open tools",
                "sections": [
                    {
                        "title": "Tonight",
                        "rows": [
                            {
                                "id": "admin_tt_code",
                                "title": "TT code",
                                "description": "Generate tonight's TT code.",
                            },
                            {
                                "id": "admin_tt_status",
                                "title": "Latest TT",
                                "description": "Browse events, results and outstanding entries.",
                            },
                            {
                                "id": "admin_pending",
                                "title": "Pending",
                                "description": "Checked-in members still pending.",
                            },
                            {
                                "id": "admin_recent_changes",
                                "title": "Recent changes",
                                "description": "Who changed a result, with guarded undo.",
                            },
                        ],
                    },
                    {
                        "title": "Members",
                        "rows": [
                            {
                                "id": "admin_find",
                                "title": "Find member",
                                "description": "History, corrections or add a missed TT.",
                            },
                            {
                                "id": "admin_correct",
                                "title": "Correct result",
                                "description": "Find a member and correct a result.",
                            },
                        ],
                    },
                    {
                        "title": "System",
                        "rows": [
                            {
                                "id": "admin_jobs_status",
                                "title": "Queue status",
                                "description": "See pending, running and failed jobs.",
                            },
                            {
                                "id": "admin_jobs_failed",
                                "title": "Failed jobs",
                                "description": "Review jobs that need attention.",
                            },
                            {
                                "id": "admin_jobs_retry",
                                "title": "Retry failed",
                                "description": "Retry all failed jobs.",
                            },
                        ],
                    },
                    {
                        "title": "Leaderboards",
                        "rows": [
                            {
                                "id": "admin_leaderboards",
                                "title": "Leaderboard views",
                                "description": "Tonight's results and overall PBs.",
                            },
                        ],
                    },
                ],
            },
        },
    }
    return _send(payload)


def send_admin_leaderboard_menu_list(to: str) -> bool:
    """Keep admin leaderboard views reachable within list row limits."""
    return _send({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "🌳 Irene AC leaderboards"},
            "body": {"text": "Choose a leaderboard view."},
            "footer": {"text": WHATSAPP_FOOTER},
            "action": {
                "button": "Choose view",
                "sections": [{
                    "title": "Leaderboards",
                    "rows": [
                        {
                            "id": "admin_tonight_leaderboard",
                            "title": "Tonight leaderboard",
                            "description": "Show tonight's TT results.",
                        },
                        {
                            "id": "admin_overall_leaderboard",
                            "title": "Overall PBs",
                            "description": "Show fastest 8km, 6km and 4km PBs.",
                        },
                        {
                            "id": "admin_date_range_leaderboard",
                            "title": "Date range",
                            "description": "Pull past Tuesday leaderboards.",
                        },
                    ],
                }],
            },
        },
    })


# ─────────────────────────────────────────────
# ADMIN PENDING ACTION BUTTONS
# ─────────────────────────────────────────────
def send_admin_pending_actions(to: str, body: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "admin_recover_tonight",
                            "title": "Resend prompts",
                        },
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "admin_tt_status",
                            "title": "Status",
                        },
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "admin_menu",
                            "title": "Admin tools",
                        },
                    },
                ],
            },
        },
    }
    return _send(payload)


def send_admin_edit_field_buttons(to: str, body: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "admin_edit_time", "title": "Time"}},
                    {"type": "reply", "reply": {"id": "admin_edit_distance", "title": "Distance"}},
                    {"type": "reply", "reply": {"id": "admin_edit_both", "title": "Both"}},
                ],
            },
        },
    }
    return _send(payload)


def send_admin_confirm_correction_buttons(to: str, body: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "admin_confirm_correction", "title": "Yes"}},
                    {"type": "reply", "reply": {"id": "admin_cancel_correction", "title": "No"}},
                ],
            },
        },
    }
    return _send(payload)


def send_admin_date_calendar(to: str, member_name: str, flow_token: str) -> bool:
    if not (config.WHATSAPP_FLOWS_ENABLED and config.WHATSAPP_ADMIN_DATE_FLOW_PUBLISHED
            and WHATSAPP_ADMIN_DATE_FLOW_ID):
        return False
    from app.services.flow_session_service import launch_admin_calendar
    return launch_admin_calendar(to, member_name, flow_token, WHATSAPP_ADMIN_DATE_FLOW_ID)


def send_admin_submission_buttons(to: str, body: str, choices: list[tuple[str, str]]) -> bool:
    return _send(reply_buttons(to, body, choices))


def send_admin_member_center_buttons(to: str, body: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "admin_member_history", "title": "History"}},
                    {"type": "reply", "reply": {"id": "admin_member_correct", "title": "Correct result"}},
                    {"type": "reply", "reply": {"id": "admin_add_tt", "title": "Add missed TT"}},
                ],
            },
        },
    }
    return _send(payload)


# ─────────────────────────────────────────────
# LEADERBOARD SUBMENU
# ─────────────────────────────────────────────
def send_leaderboard_menu_list(to: str) -> bool:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": f"🌳 {SHORT_BRAND_NAME} leaderboards"},
            "body": {"text": "Celebrate the miles, moments and milestones."},
            "footer": {"text": WHATSAPP_FOOTER},
            "action": {
                "button": "Choose view",
                "sections": [
                    {
                        "title": "Leaderboard options",
                        "rows": [
                            {
                                "id": "leaderboard_tonight",
                                "title": "Tonight leaderboard",
                                "description": "Tonight's TT results.",
                            },
                            {
                                "id": "leaderboard_season",
                                "title": "Season leaderboard",
                                "description": "This year's bests; type SEASON LEADERBOARD 2026 for a past year.",
                            },
                            {
                                "id": "leaderboard_overall",
                                "title": "Overall PBs",
                                "description": "Fastest 8km, 6km and 4km PBs.",
                            },
                            {
                                "id": "leaderboard_my_ranking",
                                "title": "My ranking",
                                "description": "Your all-time PB rank for each distance.",
                            },
                        ],
                    }
                ],
            },
        },
    }
    return _send(payload)


# ─────────────────────────────────────────────
# PARTICIPATION BUTTONS (RUNNER / WALKER / BOTH)
# ─────────────────────────────────────────────
def send_participation_buttons(to: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "How do you usually participate? Tap a button or type Runner, Walker or Both."},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "RUNNER", "title": "🏃 Runner"}},
                    {"type": "reply", "reply": {"id": "WALKER", "title": "🚶 Walker"}},
                    {"type": "reply", "reply": {"id": "BOTH", "title": "🔄 Both"}},
                ]
            },
        },
    }
    _send(payload)


def send_leaderboard_visibility_buttons(to: str):
    """Ask new members for a separate public-leaderboard preference."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    "Would you like your name and TT results to appear on "
                    "Irene AC public leaderboards?\n\n"
                    "This is separate from storing your TT profile and results. "
                    "Tap a button or type PUBLIC or PRIVATE. You can change this later."
                )
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": "onboarding_show_results", "title": "🏆 Show my results"},
                    },
                    {
                        "type": "reply",
                        "reply": {"id": "onboarding_keep_private", "title": "🔒 Keep private"},
                    },
                ]
            },
        },
    }
    _send(payload)


# ─────────────────────────────────────────────
# PROFILE ACTION BUTTONS
# ─────────────────────────────────────────────
def send_profile_buttons(to: str, body: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "edit_name", "title": "Edit name"}},
                    {"type": "reply", "reply": {"id": "edit_type", "title": "Change type"}},
                    {"type": "reply", "reply": {"id": "back_menu", "title": "Menu"}},
                ]
            },
        },
    }
    _send(payload)


# ─────────────────────────────────────────────
# DISTANCE BUTTONS (4 / 6 / 8 km)
# ─────────────────────────────────────────────
def send_distance_buttons(to: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Select your TT distance:"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "4km",
                            "title": "🏃 4 km"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "6km",
                            "title": "🏃 6 km"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "8km",
                            "title": "🏃 8 km"
                        }
                    },
                ]
            },
        },
    }
    _send(payload)


# ─────────────────────────────────────────────
# BOTH MEMBER SUBMISSION TYPE BUTTONS
# ─────────────────────────────────────────────
def send_both_submission_buttons(to: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "What would you like to submit?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "submit_distance",
                            "title": "📏 Distance"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "submit_workout",
                            "title": "🚶 Workout"
                        }
                    },
                ]
            },
        },
    }
    _send(payload)


# ─────────────────────────────────────────────
# CONFIRM / EDIT BUTTONS
# ─────────────────────────────────────────────
def send_confirm_buttons(
    to: str,
    distance: str,
    time: str,
) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": _format_confirmation_body(distance, time)
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "confirm",
                            "title": "✅ Confirm"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "edit",
                            "title": "✏️ Edit"
                        }
                    },
                ]
            },
        },
    }
    _send(payload)


def send_workout_confirm_buttons(to: str, workout: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": f"Save this workout?\n\n{workout}"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "confirm", "title": "✅ Confirm"}},
                    {"type": "reply", "reply": {"id": "edit", "title": "✏️ Edit"}},
                ]
            },
        },
    }
    _send(payload)


def send_self_correction_confirm_buttons(to: str, body: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "self_correction_confirm", "title": "✅ Confirm"}},
                    {"type": "reply", "reply": {"id": "self_correction_cancel", "title": "✖ Cancel"}},
                ]
            },
        },
    }
    _send(payload)


def send_onboarding_actions(to: str, checkin_available: bool = False):
    buttons = [
        {"type": "reply", "reply": {"id": "menu_how_tt_works", "title": "How TT works"}},
        {"type": "reply", "reply": {"id": "menu_profile", "title": "My profile"}},
    ]
    if checkin_available:
        buttons.append({"type": "reply", "reply": {"id": "menu_submit", "title": "Check in"}})
    return _send({
        "messaging_product": "whatsapp", "to": to, "type": "interactive",
        "interactive": {"type": "button", "body": {"text":
            "Ready for your first TT? Choose a next step. Optional unfinished-result reminders: "
            "REMINDERS ON. Attendance celebrations: MILESTONES ON. Both start off."},
            "action": {"buttons": buttons}},
    })


def send_admin_workflow_buttons(to, body, buttons):
    return _send({"messaging_product": "whatsapp", "to": to, "type": "interactive",
                  "interactive": {"type": "button", "body": {"text": body}, "action": {
                      "buttons": [{"type": "reply", "reply": {"id": key, "title": label}}
                                  for key, label in buttons]}}})


def send_admin_workflow_list(to, body, rows):
    return _send({"messaging_product": "whatsapp", "to": to, "type": "interactive",
                  "interactive": {"type": "list", "body": {"text": body}, "action": {
                      "button": "Choose", "sections": [{"title": "Admin options", "rows": [
                          {"id": key, "title": title, "description": description}
                          for key, title, description in rows]}]}}})


def send_native_main_menu(to, admin=False):
    options = [
        ("menu_submit", "Submit TT result", "Check in and record your run or walk."),
        ("menu_profile", "My profile", "View or edit your details."),
        ("menu_progress_hub", "My progress and season", "Progress, season and personal bests."),
        ("menu_history", "My history", "Your results across all seasons."),
        ("menu_leaderboard", "Leaderboards", "Tonight, season and all-time results."),
        ("menu_activities", "Club activities", "Tuesday TT and club programmes."),
        ("menu_shop", "Irene Shop", "Club merchandise."),
        ("menu_league_standings", "Irene League", "League standings."),
        ("menu_privacy", "Privacy choices", "Sharing, consent, data and deletion."),
    ]
    sections = [{"title": "Member options", "rows": [
        {"id": key, "title": title, "description": description} for key, title, description in options]}]
    if admin:
        sections.append({"title": "Administration", "rows": [{"id": "admin_menu", "title": "Admin tools"}]})
    return _send(selection_list(to, "What would you like to do?", sections, button="Open menu",
                                header=f"🌳 {SHORT_BRAND_NAME}", footer="Type HELP anytime."))


def send_progress_menu(to):
    if not config.WHATSAPP_NATIVE_UX_ENABLED:
        return send_text(to, "Send MY PROGRESS, MY SEASON, MY PBS or MY HISTORY. MENU returns to the main menu.")
    return _send(selection_list(to, "Explore your progress.", [{"title": "Your running", "rows": [
        {"id": "menu_progress", "title": "My progress"},
        {"id": "menu_season", "title": "My season"},
        {"id": "menu_my_pbs", "title": "My personal bests"},
        {"id": "menu_history", "title": "My history"},
        {"id": "back_menu", "title": "Main menu"},
    ]}]))


def send_club_activities(to):
    if not config.WHATSAPP_NATIVE_UX_ENABLED:
        return send_text(to, "Send HOW TT WORKS for Tuesday TT, or MENU for club links.")
    return _send(reply_buttons(to, "Tuesday TT: check in with the event code at the club. "
                              "Festive hosting registration is not open in this bot yet.", [
        ("menu_how_tt_works", "How TT works"), ("menu_submit", "Submit TT result"), ("back_menu", "Main menu")]))


def send_contextual_text(to, body, context):
    choices = {
        "result": [("menu_progress", "View progress"), ("menu_leaderboard", "Leaderboard"), ("back_menu", "Main menu")],
        "progress": [("menu_my_pbs", "My personal bests"), ("menu_history", "My history"), ("back_menu", "Main menu")],
        "profile": [("menu_profile", "View profile"), ("back_menu", "Main menu")],
    }
    # Keep a single message even when a rich summary exceeds interactive limits.
    if config.WHATSAPP_NATIVE_UX_ENABLED and len(body) <= 1024:
        return _send(reply_buttons(to, body, choices[context]))
    return send_text(to, body)
