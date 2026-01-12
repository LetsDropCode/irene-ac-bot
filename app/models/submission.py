from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Submission:
    phone: str
    tt_code_verified: bool = False
    tt_code: Optional[str] = None
    distance: Optional[str] = None
    time: Optional[str] = None
    seconds: Optional[int] = None
    confirmed: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None