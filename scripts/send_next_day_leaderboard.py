from app.services.leaderboard_broadcast_service import send_next_day_leaderboard


def main():
    result = send_next_day_leaderboard()
    print(
        "Next-day leaderboard broadcast queued "
        f"for {result['event_date']}: "
        f"queued={result['queued']} skipped={result['skipped']}"
    )


if __name__ == "__main__":
    main()
