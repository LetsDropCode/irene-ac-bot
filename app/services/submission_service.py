# app/services/submission_service.py

from datetime import datetime
from typing import Optional

from app.db import get_db
from app.models import Submission


def get_or_create_submission(
    phone: str,
    tt_date: Optional[str] = None,
):
    """
    Fetch the user's active TT submission for the day,
    or create one if it doesn't exist yet.
    """

    db = get_db()

    if not tt_date:
        tt_date = datetime.utcnow().strftime("%Y-%m-%d")

    submission = (
        db.query(Submission)
        .filter(
            Submission.phone == phone,
            Submission.tt_date == tt_date,
        )
        .first()
    )

    if submission:
        return submission

    submission = Submission(
        phone=phone,
        tt_date=tt_date,
        distance_km=None,
        time_str=None,
        confirmed=False,
        created_at=datetime.utcnow(),
    )

    db.add(submission)
    db.commit()
    db.refresh(submission)

    return submission


def update_distance(submission: Submission, distance_km: int):
    submission.distance_km = distance_km
    submission.updated_at = datetime.utcnow()


def update_time(submission: Submission, time_str: str):
    submission.time_str = time_str
    submission.updated_at = datetime.utcnow()


def confirm_submission(submission: Submission):
    submission.confirmed = True
    submission.updated_at = datetime.utcnow()