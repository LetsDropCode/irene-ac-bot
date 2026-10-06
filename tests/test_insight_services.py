import unittest

from app.services.insight_services import detect_fatigue, detect_trend


def run(distance, seconds):
    return {"distance_text": distance, "seconds": seconds}


class InsightServiceTests(unittest.TestCase):
    def test_shorter_distance_does_not_create_false_improvement(self):
        recent = [run("6", 2267), run("8", 2508), run("8", 2600),
                  run("8", 2652), run("6", 1834)]

        self.assertEqual(detect_trend(recent), "Not enough comparable runs yet.")
        self.assertIsNone(detect_fatigue(recent))

    def test_longer_distance_does_not_create_false_fatigue(self):
        recent = [run("8", 2400), run("4", 1300), run("4", 1400)]

        self.assertEqual(detect_trend(recent), "Not enough comparable runs yet.")
        self.assertIsNone(detect_fatigue(recent))

    def test_interleaved_distances_use_only_latest_distance(self):
        recent = [run("6", 1800), run("8", 1400), run("6", 1900),
                  run("4", 1200), run("6", 2000)]

        self.assertEqual(detect_trend(recent), "🔥 Improving")
        self.assertIsNone(detect_fatigue(recent))

    def test_explicit_submission_distance_overrides_latest_history_distance(self):
        recent = [run("8", 1500), run("6", 2200), run("6", 2000), run("6", 1900)]

        self.assertEqual(detect_trend(recent, "6"), "⚠️ Slowing down")
        self.assertEqual(detect_fatigue(recent, "6"), "😴 Possible fatigue detected")

    def test_same_distance_trends_are_preserved(self):
        cases = [([1800, 1900, 2000], "🔥 Improving"),
                 ([2000, 1900, 1800], "⚠️ Slowing down"),
                 ([1800, 1800, 1800], "➡️ Consistent")]
        for times, expected in cases:
            with self.subTest(times=times):
                self.assertEqual(detect_trend([run("6", t) for t in times]), expected)

    def test_equivalent_numeric_distances_match(self):
        recent = [run("6", 1800), run(6, 1900), run("6.0", 2000)]
        self.assertEqual(detect_trend(recent), "🔥 Improving")

    def test_unknown_distance_cannot_establish_comparability(self):
        recent = [{"seconds": 1800}, {"seconds": 1900}, {"seconds": 2000}]
        self.assertEqual(detect_trend(recent), "Not enough comparable runs yet.")
        self.assertIsNone(detect_fatigue(recent))

    def test_invalid_measurements_are_not_used(self):
        for invalid in (None, "", "invalid", 0, -1, float("nan"), float("inf"), True):
            with self.subTest(invalid=invalid):
                recent = [run("6", 2000), run("6", 1900), run("6", invalid)]
                self.assertEqual(detect_trend(recent), "Not enough comparable runs yet.")
                self.assertIsNone(detect_fatigue(recent))
                recent = [run(invalid, 2000), run("6", 1900), run("6", 1800)]
                self.assertEqual(detect_trend(recent), "Not enough comparable runs yet.")
                self.assertIsNone(detect_fatigue(recent))

    def test_fatigue_threshold_uses_only_comparable_history(self):
        for latest, expected in ((2100, None), (2101, "😴 Possible fatigue detected")):
            with self.subTest(latest=latest):
                recent = [run("6", latest), run("4", 1000), run("6", 2000), run("6", 2000)]
                self.assertEqual(detect_fatigue(recent), expected)

    def test_empty_history_has_no_trend_or_fatigue(self):
        self.assertEqual(detect_trend([]), "Not enough comparable runs yet.")
        self.assertIsNone(detect_fatigue([]))


if __name__ == "__main__":
    unittest.main()
