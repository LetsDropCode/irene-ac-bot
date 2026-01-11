# app/services/time_utils.py
def time_to_seconds(time_str: str) -> int:
    parts = [int(p) for p in time_str.split(":")]

    if len(parts) == 2:
        m, s = parts
        return m * 60 + s

    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s

    raise ValueError("Invalid time format")