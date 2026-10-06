"""Queue opted-in Wednesday TT reminders; run before 13:00 Johannesburg time."""

from pathlib import Path
import sys

# Support direct execution from the repository root by scheduled services.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.incomplete_reminder_service import queue_incomplete_submission_reminders


def main():
    result = queue_incomplete_submission_reminders()
    print(
        "Incomplete TT reminders: "
        f"event_date={result['event_date']} "
        f"eligible={result['queued']} "
        f"outside_window={result['outside_window']}"
    )


if __name__ == "__main__":
    main()
