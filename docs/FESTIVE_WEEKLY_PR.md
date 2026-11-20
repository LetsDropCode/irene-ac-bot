# Generate festive weekly announcements from approved live runs

Captains currently compile each festive weekly schedule manually. This adds deterministic WhatsApp-ready editions for the four Mondays from 7–28 December 2026, using the existing public festive calendar and authenticated five-minute runner. Posted revisions remain immutable; approved changes create a new review revision and a cumulative correction message.

Delivery mode A is implemented: admin-only WEEKLY previews, refresh, copy/native forwarding, future drafts, history and explicit posting confirmation. Optional opted-in captain template notices are separately gated. Official group posting is rejected: the read-only audit did not establish an eligible official group destination. No live messages or production changes were made.

The additive migration creates digest revisions, captain subscriptions and notification receipts. Existing TT submissions, cutoff rules, members, league integration and festive bookings are unchanged. All weekly enablement, proactive notifications and group posting remain off by default.

Validation: baseline 441 unit tests (2 existing device skips); final workspace 471 unit tests (2 existing device skips), 104 real PostgreSQL integration tests, including 57 new tests. Python 3.13.5, compilation, dependency checks and new-file lint pass. PostgreSQL tests use an isolated local database and mocked WhatsApp requests. Read-only deployment check/preview commands pass locally.

Review [release/UAT/rollback instructions](docs/FESTIVE_WEEKLY_RELEASE.md) and the [read-only preview CLI](scripts/festive_weekly.py). All four production-source samples are retained locally, outside this public PR. Apply the additive migration before deploying with the weekly flag disabled. Physical-device UAT, production activation and any optional template notification test require their documented gates. This PR does not enable production publication.
