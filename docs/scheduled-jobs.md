# Scheduled Jobs

## Next-day TT leaderboard

Run this as a scheduled job on Wednesday mornings after Tuesday TT:

```sh
venv/bin/python scripts/send_next_day_leaderboard.py
```

Recommended schedule:

```text
0 8 * * 3
```

Timezone:

```text
Africa/Johannesburg
```

The job sends yesterday's TT leaderboard only to members who checked in for that TT
and have not opted out of leaderboard sharing.
