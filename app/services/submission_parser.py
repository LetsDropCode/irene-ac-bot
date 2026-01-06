# app/services/submission_parser.py

import re


def parse_submission(text: str):
    """
    Parses submission text.
    Returns dict or None if invalid.

    RUN examples:
    - 5km 24:30 TT123
    - 6km 31:10 ABC

    WALK examples:
    - 45:30
    """

    text = text.strip().upper()

    # -------------------------
    # WALK: time only (MM:SS or HH:MM:SS)
    # -------------------------
    walk_match = re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", text)
    if walk_match:
        return {
            "type": "WALK",
            "time": text
        }

    # -------------------------
    # RUN: distance + time + code
    # -------------------------
    run_match = re.fullmatch(
        r"(\d+(?:\.\d+)?KM)\s+(\d{1,2}:\d{2})\s+([A-Z0-9]+)",
        text
    )

    if run_match:
        return {
            "type": "RUN",
            "distance": run_match.group(1),
            "time": run_match.group(2),
            "code": run_match.group(3)
        }

    return None