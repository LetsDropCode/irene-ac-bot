# app/services/event_resolver.py
from datetime import datetime

def get_today_events(now=None):
    now = now or datetime.now()
    weekday = now.weekday()  # Monday = 0

    if weekday == 1:   # Tuesday
        return ["TT"]
    if weekday == 2:   # Wednesday
        return ["WEDLSD"]
    if weekday == 6:   # Sunday
        return ["SUNSOCIAL"]

    return []