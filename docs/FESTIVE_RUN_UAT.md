# Festive Run UAT and test evidence

Executed locally on 18 November 2026. All recipients are synthetic fixtures; all external message transports are mocked or suppressed. The production database and separate league repository were not used.

## Executed results

| Suite | Passed | Failed | Skipped | Environment |
|---|---:|---:|---:|---|
| Existing unit baseline before changes | 409 | 0 | 0 | Existing Python 3.11.14 venv |
| Final complete unit suite | 429 | 0 | 2 | Python 3.13.5, mocked providers |
| New festive unit contracts | 20 | 0 | 0 | Included in the 429 above |
| Physical Android/iOS acceptance gates | 0 | 0 | 2 | Explicitly unexecuted; not simulated device passes |
| Final complete PostgreSQL integration suite | 75 | 0 | 0 | Python 3.13.5, PostgreSQL 17.8, disposable localhost DB |
| New festive PostgreSQL scenarios | 34 | 0 | 0 | Included in the 75 above |
| Existing PostgreSQL regressions | 41 | 0 | 0 | Included in the 75 above |

The existing unit count includes the user's already-present local reporting tests. Those files are not part of the festive change. The isolated branch's CI count may therefore be lower. Expected test logs include deliberately simulated provider failure and rejected-signature messages; the suite exits successfully.

Executed commands:

```sh
# Activate a Python 3.13.5 venv with pinned project dependencies.
ENV=test DATABASE_URL=postgresql://test:test@localhost/test python -m unittest discover -s tests
ENV=test INTEGRATION_DATABASE_URL=postgresql://<local-user>@127.0.0.1:55442/irene_festive_integration \
  python -m unittest discover -s tests/integration -p '*_integration.py'
python -m pip check
python -m compileall -q app scripts tests
git diff --check
```

Ruff lint and format verification were run on all newly added festive Python files. Full-tree critical Python-error lint was also run. Do not run integration tests against a database containing real records: the fixtures reset the public schema. Test connection requires an explicitly supplied local database with `test` or `integration` in its name.

## Four-user UAT

A = ordinary member; B = lead host; C = co-host; D = configured club administrator. Fixtures reuse the existing `members` table and consent model. The continuous fake-transport scenario is `test_fallback_host_runner_and_admin_uat`; native host, runner and management scenarios exercise the same transaction/state services separately.

| # | Scenario | Result | Evidence |
|---|---|---|---|
| 1 | B volunteers for 13 December | PASS — simulated | Booking confirmation creates one lead |
| 2 | C registers as co-host | PASS — simulated | Separate role and unique slot constraints |
| 3 | B enters meeting point, time, distances | PASS — simulated | Multi-field draft and approval submission |
| 4 | D reviews and approves | PASS — simulated | Existing admin allowlist; approved snapshot |
| 5 | A sends RUNS | PASS — simulated | Calendar list payload |
| 6 | A selects 13 December | PASS — simulated | Public approved detail projection |
| 7 | A sends JOIN | PASS — simulated | Published-run choices only |
| 8 | A selects an offered distance | PASS — simulated | 5km selected; unsupported distances rejected |
| 9 | A receives confirmation | PASS — captured payload | No network send |
| 10 | A views MY RUNS | PASS — simulated | Own RSVP only |
| 11 | B reviews participant counts | PASS — simulated | Aggregate counts by distance; no roster |
| 12 | B changes details | PASS — simulated | Public snapshot stays unchanged while pending |
| 13 | D approves material change | PASS — simulated | Revision check and new approved snapshot |
| 14 | A gets simulated update | PASS — simulated | Notification marked SIMULATED, not SENT |
| 15 | A cancels RSVP | PASS — simulated | Idempotent withdrawal |
| 16 | B withdraws; D manages slot | PASS — simulated | Published run cancelled, admin reopens; separate reassignment test |
| 17 | Duplicate/concurrent actions | PASS | Real parallel PostgreSQL booking and Flow submission tests |
| 18 | Normal TT bot still works | PASS — automated regression | Existing 409 unit / 41 database tests retained |

## Mandatory requirement coverage

| IDs | Coverage |
|---|---|
| T01–T02 | Exactly 14 seeded dates, weekdays, year boundary, repeat migration |
| T03–T06 | Lead/co-host/multi-date registrations, duplicate booking and concurrent database constraint |
| T07–T09 | Partial drafts, own editing, unauthorised editing, draft privacy |
| T10–T17 | Approval, unpublished rejection, calendar, RSVP creation/update/listing/withdrawal |
| T18–T24 | Host withdrawal/reopen/reassignment, changes, 72/48/24-hour scheduling, dedupe, cancellation and admin denial |
| T25–T27 | Existing TT, cutoff, member and integration regressions; no league writes |
| T28 | Feature-off short circuit before festive database work; queued delivery gate |
| T29 | Real webhook retry handling, concurrent Flow replay receipts, rollback and stale revisions |
| T30 | Numbered text fallback and pagination; full native-list/button fallback journey |

Additional executed coverage includes missing templates, unknown/past dates, time/URL/distance validation, invalid coordinates, incomplete required fields, restart recovery, BACK/CANCEL, unregistered/inactive identities, consent withdrawal and erasure, native pin preservation, encryption round trips, signature rejection, token binding, missing/expired/other-member tokens, provider timeout with no automatic resend, out-of-date availability, reminder rescheduling and empty calendars.

## Account and device acceptance — NOT PASSED

Read-only Meta audit: encryption signature status **MISMATCH**. Festive Flow IDs, endpoint private-key path and approved template are absent in local configuration. No Flow uploads, validation, publication, template creation or actual test-recipient messages were performed.

Before production approval, use a separate approved Meta test number, test credentials, disposable database and only the named UAT volunteers. Keep the production number and database out of this environment. This task's UAT mode deliberately suppresses all sends; a future authorised device test must use an isolated test deployment with actual delivery enabled and controlled test recipients.

Run the following on a current Android phone and current iPhone. Record device model, OS version, WhatsApp version, date, reviewer and screenshots; replace the pending rows only after actual execution.

| Device gate | Android | iOS |
|---|---|---|
| Host Flow opens; all 14 dynamic dates reachable | NOT RUN | NOT RUN |
| Role selection, booking confirmation, draft save/resume | NOT RUN | NOT RUN |
| Multi-field keyboard, time/link fields, large text accessibility | NOT RUN | NOT RUN |
| Native BACK, close/reopen, expired session recovery | NOT RUN | NOT RUN |
| RSVP run/distance/reminder confirmation | NOT RUN | NOT RUN |
| Manage edit, cancellation confirmation and stale review | NOT RUN | NOT RUN |
| List pagination, reply buttons, approved pin/Maps/route links | NOT RUN | NOT RUN |
| FESTIVE SIMPLE and FESTIVE TEXT fallback | NOT RUN | NOT RUN |
| Approved template delivery and quick-reply callback | NOT RUN | NOT RUN |
| Network interruption, duplicate tap and retry | NOT RUN | NOT RUN |

No automated test claims to establish physical-device compatibility. The two skipped acceptance tests are deliberate release gates, not suppressed failures.
