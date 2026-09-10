# app/whatsapp.py

import logging
import os
import requests
from typing import Dict, Any

from app.services.validation import time_to_seconds
from app.services.insight_services import seconds_to_pace
from app.branding import SHORT_BRAND_NAME, TAGLINE, WHATSAPP_FOOTER
from app.config import PHONE_NUMBER_ID, WHATSAPP_TOKEN

CONNECT_TIMEOUT = float(os.getenv("WHATSAPP_CONNECT_TIMEOUT", "2"))
READ_TIMEOUT = float(os.getenv("WHATSAPP_READ_TIMEOUT", "5"))

_session = requests.Session()
logger = logging.getLogger(__name__)


def _mask_phone(value: str | None) -> str:
    if not value:
        return "unknown"
    if len(value) <= 4:
        return "****"
    return f"***{value[-4:]}"


def _graph_url() -> str:
    return f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"


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
        return False

    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = _session.post(
            _graph_url(),
            json=payload,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )

        if not response.ok:
            logger.warning(
                "WhatsApp send failed: status=%s to=%s",
                response.status_code,
                _mask_phone(recipient),
            )
        else:
            logger.info(
                "WhatsApp send succeeded: status=%s to=%s",
                response.status_code,
                _mask_phone(recipient),
            )

        return response.ok

    except requests.RequestException as e:
        logger.exception("WhatsApp send exception to=%s: %s", _mask_phone(recipient), e)
        return False


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
            "id": "menu_progress",
            "title": "My progress",
            "description": "See your latest activity, PBs and milestones.",
        },
        {
            "id": "menu_leaderboard",
            "title": "Leaderboards",
            "description": "Choose tonight, overall PBs or my ranking.",
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
                                "title": "TT status",
                                "description": "Checked in, submitted and pending.",
                            },
                            {
                                "id": "admin_pending",
                                "title": "Pending",
                                "description": "Checked-in members still pending.",
                            },
                            {
                                "id": "admin_recover_tonight",
                                "title": "Resend prompts",
                                "description": "Prompt checked-in members with no result.",
                            },
                        ],
                    },
                    {
                        "title": "Members",
                        "rows": [
                            {
                                "id": "admin_find",
                                "title": "Find member",
                                "description": "Find a member for history or corrections.",
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
    """Keep both admin leaderboard views reachable within list row limits."""
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
                    {"type": "reply", "reply": {"id": "admin_menu", "title": "Admin tools"}},
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
                                "id": "leaderboard_overall",
                                "title": "Overall PBs",
                                "description": "Fastest 8km, 6km and 4km PBs.",
                            },
                            {
                                "id": "leaderboard_my_ranking",
                                "title": "My ranking",
                                "description": "Your PB rank for each distance.",
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
            "body": {"text": "How do you usually participate?"},
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
                    "This is separate from storing your TT profile and results."
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
