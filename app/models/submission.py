# app/models/submission.py

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Submission:
    id: Optional[int] = None
    phone: str | None = None

    tt_code_verified: bool = False
    tt_code: str | None = None

    distance: str | None = None
    time: str | None = None
    seconds: int | None = None

    confirmed: bool = False

    created_at: datetime | None = None
    updated_at: datetime | None = None