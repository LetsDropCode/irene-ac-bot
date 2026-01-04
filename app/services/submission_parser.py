# app/services/submission_parser.py

import re

SUBMISSION_PATTERN = re.compile(
    r"""
    ^\s*
    (?P<distance>\d{1,2}km)      # 4km, 6km, 10km
    \s+
    (?P<time>\d{1,2}:\d{2})      # MM:SS or M:SS
    \s+
    (?P<code>[A-Z0-9]{3,8})      # CODE (3–8 chars)
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE
)


def parse_submission(text: str) -> dict | None:
    """
    Parses a submission message.

    Expected format:
        4km 18:45 ABC

    Returns:
        {
            "distance": "4km",
            "time": "18:45",
            "code": "ABC"
        }
        or None if invalid
    """
    if not text:
        return None

    match = SUBMISSION_PATTERN.match(text.strip())
    if not match:
        return None

    return {
        "distance": match.group("distance").lower(),
        "time": match.group("time"),
        "code": match.group("code").upper()
    }