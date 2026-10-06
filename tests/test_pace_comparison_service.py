import os
import unittest
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.services import pace_comparison_service as service


def run(seconds, distance="4"):
    return {"seconds": seconds, "distance_text": distance}


class Cursor:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.query = None
        self.params = None

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows


@contextmanager
def context(cursor, commit=True):
    yield cursor


class PaceComparisonTests(unittest.TestCase):
    def test_last_tt_and_rolling_pace_improvement_are_numeric(self):
        lines = service.pace_comparison_lines(
            run(1200), [run(1240), run(1280), run(1320)]
        )
        self.assertEqual(lines, [
            "Compared with your last 4 km TT: 0:40 faster.",
            "Rolling 3-TT pace: 5:10/km (improving by 0:10/km vs prior 3-TT window).",
        ])

    def test_slowing_and_steady_are_based_on_rounded_pace(self):
        slowing = service.pace_comparison_lines(
            run(1320), [run(1280), run(1240), run(1200)]
        )
        steady = service.pace_comparison_lines(
            run(1200), [run(1200), run(1200), run(1200)]
        )
        self.assertIn("0:40 slower", slowing[0])
        self.assertIn("slowing by 0:10/km", slowing[1])
        self.assertIn("the same time", steady[0])
        self.assertIn("steady", steady[1])

    def test_requires_same_distance_and_four_results_for_rolling_trend(self):
        lines = service.pace_comparison_lines(
            run(1200), [run(1240, "4.0"), run(900, "3"), run(1280)]
        )
        self.assertIn("0:40 faster", lines[0])
        self.assertEqual(lines[1], "Rolling pace trend: needs four comparable TT results.")

    def test_invalid_or_missing_history_is_handled_without_inventing_comparison(self):
        self.assertEqual(service.pace_comparison_lines(run(1200, "bad"), []), [])
        self.assertEqual(service.pace_comparison_lines(run(1200), []), [
            "Compared with your last 4 km TT: first comparable result."
        ])

    def test_query_is_limited_to_older_completed_same_distance_tt_runs(self):
        cursor = Cursor(rows=[run(1240, "4.0")])
        current = {"id": 101, "event_date": date(2026, 10, 6), **run(1200)}
        with patch.object(service, "get_cursor", return_value=context(cursor)):
            self.assertEqual(service.get_previous_comparable_runs(42, current), cursor.rows)
        self.assertIn("activity = 'TT'", cursor.query)
        self.assertIn("status = 'COMPLETE'", cursor.query)
        self.assertIn("(event_date, id) < (%s, %s)", cursor.query)
        self.assertEqual(cursor.params, (42, Decimal("4"), date(2026, 10, 6), 101, 3))


if __name__ == "__main__":
    unittest.main()
