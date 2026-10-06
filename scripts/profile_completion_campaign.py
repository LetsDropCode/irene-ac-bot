"""
Profile Completion Campaign

Purpose:
Find members with missing or placeholder names and prompt them
to update their details via WhatsApp.

Safe to run anytime (no TT window required).
"""

import time
import hashlib
from app.services.member_service import get_members_needing_profile_update
from app.whatsapp import queue_inbound_replies, send_text


# ─────────────────────────────────────────────
# MESSAGE TEMPLATE
# ─────────────────────────────────────────────
CAMPAIGN_MESSAGE = (
    "👋 Hi there!\n\n"
    "We noticed your Irene AC profile is incomplete.\n\n"
    "Please reply with your *first name and surname* so we can update your records.\n"
    "_Example: John Smith_\n\n"
    "Thanks for helping us keep the club records accurate 🙌"
)


# ─────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────
def run_campaign(dry_run: bool = False, delay_seconds: float = 0.5):
    """
    dry_run=True → prints who WOULD be messaged
    delay_seconds → prevents WhatsApp rate limits
    """

    members = get_members_needing_profile_update()

    total = len(members)
    print(f"📊 Members needing profile completion: {total}")

    if total == 0:
        print("✅ No profiles need updating")
        return

    queued = 0
    campaign_id = hashlib.sha256(CAMPAIGN_MESSAGE.encode("utf-8")).hexdigest()[:16]

    for m in members:
        phone = m["phone"]
        first = m.get("first_name")
        last = m.get("last_name")

        print(f"➡️ Target: {phone} | {first} {last}")

        if not dry_run:
            try:
                with queue_inbound_replies(f"profile-campaign:{campaign_id}"):
                    if send_text(phone, CAMPAIGN_MESSAGE):
                        queued += 1
                time.sleep(delay_seconds)

            except Exception as e:
                print(f"❌ Failed to send to {phone}: {e}")

    print("────────────────────────────")
    print(f"✅ Campaign complete")
    print(f"📨 Messages queued: {queued}")
    print(f"📊 Total processed: {total}")


# ─────────────────────────────────────────────
# CLI ENTRYPOINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    run_campaign(dry_run=False)
