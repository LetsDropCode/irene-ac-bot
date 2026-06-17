# app/config.py
from dotenv import load_dotenv
import os

load_dotenv()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ENV = os.getenv("ENV", "development")
WHATS_NEW_VERSION = os.getenv("WHATS_NEW_VERSION", "2026-06-shop-menu")
WHATS_NEW_MESSAGE = os.getenv(
    "WHATS_NEW_MESSAGE",
    (
        "✨ *What’s new at Irene AC TT*\n\n"
        "Your bot now does more than capture results:\n"
        "• View *My progress* for milestones, PBs and trends\n"
        "• Open *The Irene Shop* straight from the menu\n"
        "• Check your *profile* and update your details\n"
        "• See runner results and walker activity on the leaderboard\n\n"
        "Send *HELP* anytime to explore the menu."
    ),
)

ADMIN_NUMBERS = {
    "27722135094", #Lindsay
    "27738870757", #Jacqueline
    "27829370733", #Wynand
    "27818513864", #Johan
    "27828827067", #Janine
}
