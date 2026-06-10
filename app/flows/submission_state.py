AWAITING_WORKOUT = "awaiting_workout"
AWAITING_BOTH_CHOICE = "awaiting_both_choice"
AWAITING_DISTANCE = "awaiting_distance"
AWAITING_TIME = "awaiting_time"
AWAITING_CONFIRM = "awaiting_confirm"


def resolve_pending_submission_state(member: dict, submission: dict) -> str:
    participation_type = member.get("participation_type") or "RUNNER"

    if participation_type == "WALKER" and not submission.get("time_text"):
        return AWAITING_WORKOUT

    if (
        participation_type == "BOTH"
        and not submission.get("distance_text")
        and not submission.get("time_text")
    ):
        return AWAITING_BOTH_CHOICE

    if not submission.get("distance_text"):
        return AWAITING_DISTANCE

    if not submission.get("time_text"):
        return AWAITING_TIME

    return AWAITING_CONFIRM
