import unittest
from unittest.mock import patch

from app import whatsapp


class WhatsAppMenuTests(unittest.TestCase):
    def test_main_menu_shows_only_hide_option_for_members_sharing_results(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            result = whatsapp.send_main_menu_list(
                "27999999999", member={"leaderboard_opt_out": False}
            )

        self.assertTrue(result)
        payload = send.call_args.args[0]
        interactive = payload["interactive"]
        rows = interactive["action"]["sections"][0]["rows"]
        row_ids = [row["id"] for row in rows]

        self.assertEqual(interactive["type"], "list")
        self.assertEqual(interactive["action"]["button"], "Open menu")
        self.assertEqual(interactive["header"]["text"], "🌳 Irene AC")
        self.assertIn("Serious about our frun", interactive["body"]["text"])
        self.assertIn("menu_submit", row_ids)
        self.assertIn("menu_progress", row_ids)
        self.assertIn("menu_leaderboard", row_ids)
        self.assertIn("menu_shop", row_ids)
        self.assertIn("menu_league_standings", row_ids)
        self.assertNotIn("menu_overall_leaderboard", row_ids)
        self.assertIn("menu_opt_out", row_ids)
        self.assertNotIn("menu_opt_in", row_ids)
        sharing_row = next(row for row in rows if row["id"] == "menu_opt_out")
        self.assertEqual(sharing_row["title"], "Hide my results")
        self.assertEqual(sharing_row["description"], "Hide my results from public leaderboards.")
        self.assertNotIn("menu_edit_profile", row_ids)
        self.assertNotIn("admin_tt_code", row_ids)

    def test_main_menu_shows_only_show_option_for_members_hiding_results(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            whatsapp.send_main_menu_list(
                "27999999999", member={"leaderboard_opt_out": True}
            )

        rows = send.call_args.args[0]["interactive"]["action"]["sections"][0]["rows"]
        row_ids = [row["id"] for row in rows]

        self.assertIn("menu_opt_in", row_ids)
        self.assertNotIn("menu_opt_out", row_ids)
        sharing_row = next(row for row in rows if row["id"] == "menu_opt_in")
        self.assertEqual(sharing_row["title"], "Show my results")
        self.assertEqual(
            sharing_row["description"], "Show my results on public leaderboards again."
        )

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
        interactive = send.call_args.args[0]["interactive"]
        self.assertEqual(interactive["header"]["text"], "🌳 Irene AC leaderboards")
        self.assertEqual(interactive["footer"]["text"], "Irene AC • Serious about our frun")

    def test_profile_actions_keep_edit_and_menu_controls_compact(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            whatsapp.send_profile_buttons("27999999999", "Profile body")

        buttons = send.call_args.args[0]["interactive"]["action"]["buttons"]
        self.assertEqual(
            [button["reply"]["id"] for button in buttons],
            ["edit_name", "edit_type", "back_menu"],
        )

    def test_admin_menu_includes_admin_rows(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            whatsapp.send_main_menu_list(
                "27722135094", admin=True, member={"leaderboard_opt_out": False}
            )

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
        self.assertIn("admin_find", row_ids)
        self.assertIn("admin_correct", row_ids)
        self.assertIn("admin_jobs_status", row_ids)
        self.assertIn("admin_jobs_failed", row_ids)
        self.assertIn("admin_jobs_retry", row_ids)
        self.assertIn("admin_leaderboards", row_ids)
        self.assertEqual(len(row_ids), 10)
        self.assertEqual(
            [section["title"] for section in sections],
            ["Tonight", "Members", "System", "Leaderboards"],
        )

    def test_admin_leaderboard_submenu_keeps_both_views_available(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            result = whatsapp.send_admin_leaderboard_menu_list("27722135094")

        self.assertTrue(result)
        rows = send.call_args.args[0]["interactive"]["action"]["sections"][0]["rows"]
        self.assertEqual(
            [row["id"] for row in rows],
            ["admin_tonight_leaderboard", "admin_overall_leaderboard"],
        )

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

    def test_admin_member_center_has_member_action_buttons(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            result = whatsapp.send_admin_member_center_buttons("27722135094", "Member body")

        self.assertTrue(result)
        buttons = send.call_args.args[0]["interactive"]["action"]["buttons"]
        button_ids = [button["reply"]["id"] for button in buttons]

        self.assertEqual(button_ids, [
            "admin_member_history",
            "admin_member_correct",
            "admin_menu",
        ])

    def test_confirm_buttons_include_pace_and_clear_action_copy(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            whatsapp.send_confirm_buttons("27999999999", "4", "27:41")

        body = send.call_args.args[0]["interactive"]["body"]["text"]
        self.assertIn("Ready to save this TT result?", body)
        self.assertIn("Distance: 4 km", body)
        self.assertIn("Time: 27:41", body)
        self.assertIn("Pace: 6:55/km", body)
        self.assertIn("Confirm to lock it in", body)


if __name__ == "__main__":
    unittest.main()
