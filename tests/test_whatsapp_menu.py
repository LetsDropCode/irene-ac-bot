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
        self.assertIn("menu_opt_out", row_ids)
        self.assertNotIn("admin_tt_code", row_ids)

    def test_admin_menu_includes_admin_rows(self):
        with patch.object(whatsapp, "_send", return_value=True) as send:
            whatsapp.send_main_menu_list("27722135094", admin=True)

        rows = send.call_args.args[0]["interactive"]["action"]["sections"][0]["rows"]
        row_ids = [row["id"] for row in rows]

        self.assertIn("admin_tt_code", row_ids)
        self.assertIn("admin_tt_status", row_ids)
        self.assertIn("admin_pending", row_ids)


if __name__ == "__main__":
    unittest.main()
