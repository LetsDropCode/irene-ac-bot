import unittest
from unittest.mock import patch

from app import whatsapp


class WhatsAppMenuTests(unittest.TestCase):
    def test_main_menu_list_payload_has_clean_member_options(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            result = whatsapp.send_main_menu_list("27999999999")

        self.assertTrue(result)
        payload = send.call_args.args[0]
        interactive = payload["interactive"]
        rows = interactive["action"]["sections"][0]["rows"]
        row_ids = [row["id"] for row in rows]

        self.assertEqual(interactive["type"], "list")
        self.assertEqual(interactive["action"]["button"], "Open menu")
        self.assertIn("menu_submit", row_ids)
        self.assertIn("menu_progress", row_ids)
        self.assertIn("menu_leaderboard", row_ids)
        self.assertIn("menu_shop", row_ids)
        self.assertNotIn("menu_overall_leaderboard", row_ids)
        self.assertIn("menu_opt_out", row_ids)
        self.assertNotIn("admin_tt_code", row_ids)

    def test_leaderboard_menu_has_member_leaderboard_options(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            result = whatsapp.send_leaderboard_menu_list("27999999999")

        self.assertTrue(result)
        rows = send.call_args.args[0]["interactive"]["action"]["sections"][0]["rows"]
        row_ids = [row["id"] for row in rows]

        self.assertEqual(row_ids, [
            "leaderboard_tonight",
            "leaderboard_overall",
            "leaderboard_my_ranking",
        ])

    def test_admin_menu_includes_admin_rows(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            whatsapp.send_main_menu_list("27722135094", admin=True)

        rows = send.call_args.args[0]["interactive"]["action"]["sections"][0]["rows"]
        row_ids = [row["id"] for row in rows]

        self.assertIn("admin_menu", row_ids)
        self.assertNotIn("admin_tt_code", row_ids)

    def test_admin_tools_menu_includes_operational_actions(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            result = whatsapp.send_admin_menu_list("27722135094")

        self.assertTrue(result)
        sections = send.call_args.args[0]["interactive"]["action"]["sections"]
        row_ids = [
            row["id"]
            for section in sections
            for row in section["rows"]
        ]

        self.assertIn("admin_tt_code", row_ids)
        self.assertIn("admin_tt_status", row_ids)
        self.assertIn("admin_pending", row_ids)
        self.assertIn("admin_recover_tonight", row_ids)
        self.assertIn("admin_tonight_leaderboard", row_ids)
        self.assertIn("admin_overall_leaderboard", row_ids)

    def test_admin_pending_actions_has_follow_up_buttons(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            result = whatsapp.send_admin_pending_actions("27722135094", "Pending body")

        self.assertTrue(result)
        buttons = send.call_args.args[0]["interactive"]["action"]["buttons"]
        button_ids = [button["reply"]["id"] for button in buttons]

        self.assertEqual(button_ids, [
            "admin_recover_tonight",
            "admin_tt_status",
            "admin_menu",
        ])


if __name__ == "__main__":
    unittest.main()
