import re
from datetime import datetime

LOG_FILE = "logs.1767724371450.csv"
OUT_FILE = "recovery_submissions.sql"

PHONE_RE = re.compile(r"\b27\d{9}\b")
DIST_RE = re.compile(r"\b(\d+)\s*km\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b")

def time_to_seconds(t):
    parts = list(map(int, t.split(":")))
    if len(parts) == 2:      # MM:SS
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:    # HH:MM:SS
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    else:
        raise ValueError("Invalid time format")

sql_blocks = []
seen = set()

with open(LOG_FILE, "r", errors="ignore") as f:
    for line in f:
        phone = PHONE_RE.search(line)
        dist = DIST_RE.search(line)
        time = TIME_RE.search(line)

        # STRICT: all must exist on the SAME line
        if not phone or not dist or not time:
            continue

        phone = phone.group()
        distance = f"{dist.group(1)}km"
        time_text = time.group(1)
        seconds = time_to_seconds(time_text)

        mode = "WALKER" if "walk" in line.lower() else "RUNNER"

        dedupe_key = (phone, distance, time_text, mode)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        sql_blocks.append(f"""
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
    '{distance}',
    '{time_text}',
    {seconds},
    '{mode}',
    NOW()
FROM members m
WHERE m.phone = '{phone}';
""".strip())

with open(OUT_FILE, "w") as out:
    out.write("-- AUTO-GENERATED SAFE RECOVERY SCRIPT\n")
    out.write("BEGIN;\n\n")
    for block in sql_blocks:
        out.write(block + "\n\n")
    out.write("COMMIT;\n")

print(f"Generated {len(sql_blocks)} recovery inserts")
print(f"Written to {OUT_FILE}")
