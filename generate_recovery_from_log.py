import re
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = "logs.1767723813025.log"
OUTPUT_SQL = "recovery_submissions.sql"

PHONE_RE = re.compile(r"\b27\d{9}\b")
DIST_RE = re.compile(r"\b(4|6|8)\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")
TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")

def time_to_seconds(t: str) -> int:
    parts = list(map(int, t.split(":")))
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    raise ValueError("Invalid time format")

records = []
seen = set()  # (phone, distance, time)

with open(LOG_FILE, "r", errors="ignore") as f:
    for line in f:
        phone_m = PHONE_RE.search(line)
        dist_m = DIST_RE.search(line)
        time_m = TIME_RE.search(line)

        if not (phone_m and dist_m and time_m):
            continue

        phone = phone_m.group()
        distance = f"{dist_m.group(1)}km"
        time_text = time_m.group(1)
        seconds = time_to_seconds(time_text)

        key = (phone, distance, time_text)
        if key in seen:
            continue
        seen.add(key)

        ts_m = TS_RE.search(line)
        ts = (
            datetime.strptime(ts_m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if ts_m else datetime.now(timezone.utc)
        )

        records.append({
            "phone": phone,
            "distance": distance,
            "time_text": time_text,
            "seconds": seconds,
            "ts": ts.isoformat()
        })

sql = []
sql.append("-- AUTO-GENERATED TT RECOVERY FILE")
sql.append("BEGIN;")

for r in records:
    sql.append(f"""
INSERT INTO submissions (
    member_id,
    activity,
    distance_text,
    time_text,
    seconds,
    mode,
    created_at
)
SELECT
    m.id,
    'TT',
    '{r["distance"]}',
    '{r["time_text"]}',
    {r["seconds"]},
    NULL,
    '{r["ts"]}'
FROM members m
WHERE m.phone = '{r["phone"]}'
AND NOT EXISTS (
    SELECT 1
    FROM submissions s
    WHERE s.member_id = m.id
      AND s.activity = 'TT'
      AND s.distance_text = '{r["distance"]}'
      AND s.time_text = '{r["time_text"]}'
);
""".strip())

sql.append("COMMIT;")

Path(OUTPUT_SQL).write_text("\n".join(sql))
print(f"Recovered {len(records)} submissions")
print(f"Written to {OUTPUT_SQL}")
