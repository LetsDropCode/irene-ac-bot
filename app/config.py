# app/config.py
from dotenv import load_dotenv
import os

load_dotenv()


def _env_list(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(
        item.strip()
        for item in os.getenv(name, default).split(",")
        if item.strip()
    )

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ENV = os.getenv("ENV", "development")
ATTENDANCE_REPORT_RECIPIENTS = _env_list(
    "ATTENDANCE_REPORT_RECIPIENTS",
    "bulllindsa@icloud.com,info@irenerunner.co.za",
)
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL") or SMTP_USERNAME
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
WHATS_NEW_VERSION = os.getenv("WHATS_NEW_VERSION", "2026-06-shop-league-menu")
WHATS_NEW_MESSAGE = os.getenv(
    "WHATS_NEW_MESSAGE",
    (
        "✨ *What’s new at Irene AC TT*\n\n"
        "Your bot now does more than capture results:\n"
        "• View *My progress* for milestones, PBs and trends\n"
        "• Open *The Irene Shop* and *Irene League Standings* from the menu\n"
        "• Check your *profile* and update your details\n"
        "• See runner results and walker activity on the leaderboard\n\n"
        "Send *HELP* anytime to explore the menu."
    ),
)

ADMIN_NUMBERS = frozenset(
    _env_list(
        "ADMIN_NUMBERS",
        "27722135094,27738870757,27829370733,27818513864,27828827067",
    )
)
