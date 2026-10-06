import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import openai_service


class OpenAIServiceTests(unittest.TestCase):
    def test_fallback_returns_coaching_for_result_prompt(self):
        reply = openai_service.fallback(
            "Runner completed 4km in 27:41 (pace 6:55/km). "
            "Trend: 🔥 Improving. Give short coaching feedback."
        )

        self.assertIn("trend", reply.lower())
        self.assertTrue(reply.strip())

    def test_coach_reply_uses_non_blank_fallback_without_client(self):
        with patch.object(openai_service, "_client_safe", return_value=None):
            reply = openai_service.coach_reply(
                "Runner completed 4km in 27:41 (pace 6:55/km). "
                "Trend: ➡️ Consistent. Give short coaching feedback."
            )

        self.assertTrue(reply.strip())
        self.assertIn("consistent", reply.lower())

    def test_timeout_uses_fallback(self):
        class Responses:
            def create(self, **_kwargs):
                raise TimeoutError("timed out")

        class Client:
            responses = Responses()

        with patch.object(openai_service, "_client_safe", return_value=Client()):
            reply = openai_service.coach_reply(
                "Runner completed 4km in 27:41 (pace 6:55/km). "
                "Trend: ➡️ Consistent. Give short coaching feedback."
            )

        self.assertTrue(reply.strip())
        self.assertIn("consistent", reply.lower())

    def test_coach_for_result_sends_bounded_identity_free_context(self):
        captured = {}

        class Responses:
            def create(self, **kwargs):
                captured.update(kwargs)
                return type("Response", (), {"output_text": "  Keep it controlled.  \n\n Recover well.  "})()

        class Client:
            responses = Responses()

        context = openai_service.CoachingContext(
            distance_km="4",
            time_text="27:41",
            pace="6:55/km",
            trend="Improving",
        )
        with patch.object(openai_service, "_client_safe", return_value=Client()):
            reply = openai_service.coach_for_result(context)

        self.assertEqual(reply, "Keep it controlled.\nRecover well.")
        self.assertIn("Distance: 4 km", captured["input"])
        self.assertIn("Trend: Improving", captured["input"])
        self.assertNotIn("Lindsay", captured["input"])
        self.assertFalse(captured["store"])
        self.assertEqual(captured["instructions"], openai_service.SYSTEM_PROMPT)

    def test_reply_is_limited_to_four_lines(self):
        class Responses:
            def create(self, **_kwargs):
                return type("Response", (), {"output_text": "one\ntwo\nthree\nfour\nfive"})()

        class Client:
            responses = Responses()

        with patch.object(openai_service, "_client_safe", return_value=Client()):
            reply = openai_service.coach_reply("Trend: Improving")

        self.assertEqual(reply.splitlines(), ["one", "two", "three", "four"])

    def test_blank_response_uses_fallback(self):
        class Responses:
            def create(self, **_kwargs):
                return type("Response", (), {"output_text": "  "})()

        class Client:
            responses = Responses()

        with patch.object(openai_service, "_client_safe", return_value=Client()):
            reply = openai_service.coach_reply("Trend: Improving")

        self.assertIn("trend", reply.lower())


if __name__ == "__main__":
    unittest.main()
