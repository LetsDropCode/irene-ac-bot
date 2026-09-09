AWAITING_WORKOUT = "awaiting_workout"
AWAITING_WORKOUT_CONFIRM = "awaiting_workout_confirm"
AWAITING_BOTH_CHOICE = "awaiting_both_choice"
AWAITING_DISTANCE = "awaiting_distance"
AWAITING_TIME = "awaiting_time"
AWAITING_CONFIRM = "awaiting_confirm"


def resolve_pending_submission_state(member: dict, submission: dict) -> str:
    participation_type = member.get("participation_type") or "RUNNER"

    is_workout = participation_type == "WALKER" or (
        participation_type == "BOTH"
        and (
            submission.get("mode") == "WORKOUT"
            or (not submission.get("distance_text") and submission.get("time_text"))
        )
    )

    if is_workout:
        return AWAITING_WORKOUT_CONFIRM if submission.get("time_text") else AWAITING_WORKOUT

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
