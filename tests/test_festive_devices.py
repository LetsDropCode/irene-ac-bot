"""Explicit physical-device acceptance gates, not simulated OS assertions.

Record device/version/date and screenshots in FESTIVE_RUN_UAT.md after executing
its device checklist against a separately approved Meta test number. Never mark
these passed from mocked provider payload tests.
"""

import unittest


class FestiveDeviceAcceptance(unittest.TestCase):
    @unittest.skip(
        "Android hardware unavailable; automated checks do not certify physical-device accessibility or fallback"
    )
    def test_android_native_flows_accessibility_and_fallback(self):
        pass

    @unittest.skip(
        "iPhone draft core journeys passed manually on 2026-11-20; full accessibility and fallback checklist remains pending"
    )
    def test_ios_native_flows_accessibility_and_fallback(self):
        pass
