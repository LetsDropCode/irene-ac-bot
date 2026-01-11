import csv

INPUT_FILE = "tt_2026-01-06_cleaned.csv"
OUTPUT_FILE = "recovery_submissions.sql"

with open(INPUT_FILE, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f, delimiter=";")
    rows = list(reader)

sql = []
count = 0

for row in rows:
    phone = row["phone"].strip()
    distance = f"{row['distance_clean'].strip()}km"
    time_text = row["time_clean"].strip()

    raw_seconds = row["seconds_clean"]
    seconds_str = (
        raw_seconds
        .replace("\xa0", "")
        .replace("\t", "")
        .strip()
    )

    seconds = int(seconds_str)

    created_at = row["created_at_clean"].strip()

    stmt = f"""
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
    m.participation_type,
    '{created_at}'
FROM members m
WHERE m.phone = '{phone}';
""".strip()

    sql.append(stmt)
    count += 1

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("-- AUTO-GENERATED TT RECOVERY SQL\n\n")
    f.write("\n\n".join(sql))

print(f"Generated {count} recovery inserts")
print(f"Written to {OUTPUT_FILE}")
