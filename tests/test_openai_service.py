import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import openai_service


class OpenAIServiceTests(unittest.TestCase):
    def test_fallback_returns_coaching_for_result_prompt(self):
        reply = openai_service.fallback(
            "Lindsay ran 4km in 27:41 (pace 6:55/km). "
            "Trend: 🔥 Improving. Give short coaching feedback."
        )

        self.assertIn("trend", reply.lower())
        self.assertTrue(reply.strip())

    def test_coach_reply_uses_non_blank_fallback_without_client(self):
        with patch.object(openai_service, "_client_safe", return_value=None):
            reply = openai_service.coach_reply(
                "Lindsay ran 4km in 27:41 (pace 6:55/km). "
                "Trend: ➡️ Consistent. Give short coaching feedback."
            )

        self.assertTrue(reply.strip())
        self.assertIn("consistent", reply.lower())


if __name__ == "__main__":
    unittest.main()
