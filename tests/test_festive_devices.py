"""Explicit physical-device acceptance gates, not simulated OS assertions.

Record device/version/date and screenshots in FESTIVE_RUN_UAT.md after executing
its device checklist against a separately approved Meta test number. Never mark
these passed from mocked provider payload tests.
"""

import unittest


class FestiveDeviceAcceptance(unittest.TestCase):
    @unittest.skip(
        "Requires approved Android test recipient, published sandbox Flows and device access; no live sends authorized"
    )
    def test_android_native_flows_accessibility_and_fallback(self):
        pass

    @unittest.skip(
        "Requires approved iOS test recipient, published sandbox Flows and device access; no live sends authorized"
    )
    def test_ios_native_flows_accessibility_and_fallback(self):
        pass
