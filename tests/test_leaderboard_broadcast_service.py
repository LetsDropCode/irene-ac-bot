import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import leaderboard_broadcast_service as service


class LeaderboardBroadcastServiceTests(unittest.TestCase):
    def test_build_next_day_leaderboard_message_uses_yesterday_title(self):
        with patch.object(
            service,
            "get_runner_leaderboard",
            return_value=[
                {
                    "member_id": 1,
                    "first_name": "Lindsay",
                    "last_name": "Bull",
                    "distance_text": "4",
                    "time_text": "27:41",
                    "seconds": 1661,
                    "position": 1,
                }
            ],
        ), patch.object(service, "get_walker_feed", return_value=[]):
            message = service.build_next_day_leaderboard_message(date(2026, 6, 9))

        self.assertIn("Morning TT crew", message)
        self.assertIn("Yesterday's TT Leaderboard (09 Jun)", message)
        self.assertIn("Lindsay Bull", message)

    def test_send_next_day_leaderboard_sends_only_to_checked_in_members(self):
        sent = []

        with patch.object(service, "get_checked_in_tt_member_phones", return_value=["2771", "2772"]), patch.object(
            service,
            "build_next_day_leaderboard_message",
            return_value="Leaderboard message",
        ), patch.object(service, "send_text", side_effect=lambda phone, _message: sent.append(phone) or True):
            result = service.send_next_day_leaderboard(date(2026, 6, 9))

        self.assertEqual(sent, ["2771", "2772"])
        self.assertEqual(result, {"event_date": "2026-06-09", "sent": 2, "skipped": 0})

    def test_send_next_day_leaderboard_skips_when_no_results(self):
        with patch.object(service, "get_checked_in_tt_member_phones", return_value=["2771"]), patch.object(
            service,
            "build_next_day_leaderboard_message",
            return_value=None,
        ), patch.object(service, "send_text") as send_text:
            result = service.send_next_day_leaderboard(date(2026, 6, 9))

        send_text.assert_not_called()
        self.assertEqual(result, {"event_date": "2026-06-09", "sent": 0, "skipped": 1})


if __name__ == "__main__":
    unittest.main()
