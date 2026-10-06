import os
import unittest
from unittest.mock import patch

from app.services.proactive_template_service import proactive_template_payload


class ProactiveTemplateTests(unittest.TestCase):
    def test_missing_template_is_a_visible_failure(self):
        with patch.dict(os.environ, {"WHATSAPP_REMINDER_TEMPLATE_NAME": ""}):
            with self.assertRaisesRegex(RuntimeError, "WHATSAPP_REMINDER_TEMPLATE_NAME"):
                proactive_template_payload("27123456789", "WHATSAPP_REMINDER_TEMPLATE_NAME", ["A"])

    def test_approved_template_payload_uses_configured_language_and_parameters(self):
        with patch.dict(os.environ, {
            "WHATSAPP_MILESTONE_TEMPLATE_NAME": "tt_milestone",
            "WHATSAPP_TEMPLATE_LANGUAGE": "en_ZA",
        }):
            payload = proactive_template_payload(
                "27123456789", "WHATSAPP_MILESTONE_TEMPLATE_NAME", ["5", "3"]
            )
        self.assertEqual(payload["type"], "template")
        self.assertEqual(payload["template"]["language"]["code"], "en_ZA")
        self.assertEqual(
            [item["text"] for item in payload["template"]["components"][0]["parameters"]],
            ["5", "3"],
        )


if __name__ == "__main__":
    unittest.main()
