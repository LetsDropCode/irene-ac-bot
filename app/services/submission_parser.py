# app/services/submission_parser.py
import re
from app.services.time_utils import time_to_seconds

TIME_ONLY = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")

def parse_time_only(text: str):
    text = text.strip()
    if not TIME_ONLY.match(text):
        return None

    return {
        "time": text,
        "seconds": time_to_seconds(text),
    }