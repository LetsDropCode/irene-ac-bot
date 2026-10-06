"""Run with: python -m app.migrations upgrade."""

import argparse

from app.migrations import upgrade_database


def main():
    parser = argparse.ArgumentParser(description="Apply Irene AC database migrations")
    parser.add_argument("command", choices=("upgrade",))
    parser.parse_args()
    applied = upgrade_database()
    print(f"Database migrations applied: {len(applied)}")


if __name__ == "__main__":
    main()
