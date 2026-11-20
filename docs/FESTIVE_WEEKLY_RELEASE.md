# Festive weekly announcements — release and UAT

Prepared 20 November 2026, Africa/Johannesburg.
Repository: `LetsDropCode/irene-ac-bot`. Feature branch: `codex/festive-weekly-announcements`.

**Delivery mode A: automatic generation + administrator sharing.** Optional mode B (approved-template captain notification) is implemented but disabled and not provisioned. Mode C (automatic group posting) is unavailable for the audited account and is not implemented. No live announcement or test message was sent. Production code, configuration and data remain unchanged by this enhancement.

## Discovery and production evidence

Read-only Railway inspection confirmed production `web` successfully deployed at `e48f0f9520f06a6f77a17fd4c48a02abe05af156`, with the existing FastAPI/uvicorn start command, PostgreSQL, and a successful `jobs-runner` service on `*/5 * * * *` UTC. That runner calls authenticated `POST /jobs/run`. No second scheduler is needed.

A read-only production audit confirmed that the existing festive feature is live, the fourteen programme dates match, and the provider is direct Meta WhatsApp Business Cloud API, Graph v22.0. Public event details are read from the last approved snapshot. Distance-specific timing notes are retained alongside the main start time. Production-derived sample messages and the detailed source mapping are retained as local operator deliverables rather than committed to this public repository.

The read-only capability audit did not establish an eligible official group destination. The verified bot display-number link is supplied through configuration; no production phone number is embedded in code or documentation. Do not substitute the Graph phone object ID for the display number.

Meta's [Groups API documentation](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups/) requires an Official Business Account, describes API-created invite-only groups, and currently limits groups to eight participants. Existing community-group posting is not established for the deployment. No test-group send was attempted. Setting the group-post flag causes validation to fail closed. Nothing uses WhatsApp Web or unofficial clients.

Meta permits [text messages up to 4096 characters](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/text-messages). Digests split at section/line boundaries with numbered parts and a 3900-character content budget. Captain menu replies are prompted by inbound messages and expire after 23 hours in the durable queue. Optional unsolicited notices use approved templates exclusively, with separate explicit weekly opt-in; no free-form fallback. Provider acceptance is recorded as ACCEPTED, never claimed as delivered or group-posted.

## Files and data mapping

| File | Change |
| --- | --- |
| `app/services/festive_weekly_service.py` | Four-week schedule, public projection, deterministic formatting, comparison, revision persistence, safe refresh and posting confirmation |
| `app/services/festive_weekly_notifications.py` | Separate captain opt-in, template gates, durable notice receipts and guarded provider delivery |
| `app/flows/festive_weekly_flow.py` | Native six-option WEEKLY menu, text fallback, history, previews, copy/forward instructions, exact-revision posting confirmation |
| `app/flows/festive_flow.py` | Additive weekly command routing through existing festive adapter |
| `app/main.py` | Call weekly scheduler from existing authenticated runner, isolate failures from TT jobs |
| `app/services/job_queue_service.py` | Dispatch two weekly job types through existing durable queue |
| `app/migrations/__init__.py`, `app/migrations/versions/v20261120_festive_weekly.py` | Register additive digest/notice/subscription tables |
| `scripts/festive_weekly.py` | Read-only deployment check and production-source preview CLI |
| `tests/test_festive_weekly.py`, `tests/integration/festive_weekly_integration.py` | Controlled-time contracts, database concurrency and regression coverage |
| `docs/FESTIVE_WEEKLY_RELEASE.md`, `docs/FESTIVE_WEEKLY_PR.md` | Release report and PR description; production samples remain local |

The public projection reuses `festive_service.calendar(cursor)` with **no actor/admin argument**. It never consumes the separate private draft or RSVP identities. New tables store only digest information that did not previously exist; the festive programme is not rebuilt.

| Announcement data | Existing source and visibility rule |
| --- | --- |
| Date/day/status | `festive_run_slots.run_date/status`; restricted to existing fourteen seeded dates |
| Lead/co-host display names | Active `festive_run_hosts` joined to consenting `members`, same public display-name rules as RUNS; persist names and role only, not member ID/phone |
| Title, time, venue, location notes, route notes, distances, walkers, coffee, safety, maps/route URLs or coordinates | `festive_run_details.published`, only when slot is PUBLISHED; the last approved snapshot remains authoritative during draft amendments |
| OPEN | Date + HOST NEEDED; no fictional event information |
| HOST_ASSIGNED / DETAILS_PENDING / PENDING_APPROVAL | One normalized pending state, public assigned names + details to follow |
| CANCELLED / COMPLETED | Excluded from normal listing; cancellation/completion appears in a correction if it changes a previous edition |
| RSVP | Not included; aggregate interest would add change noise and is unnecessary for this release |
| Admin permissions | Existing `ADMIN_NUMBERS`, consenting/completed existing member identity; rechecked for every action and delivery |

Free-text contact numbers/email addresses are redacted defensively. No participant names, host phone columns, credentials or private drafts are serialized into editions. Approved host display names are deliberately retained as part of the announcement history. Map/route links must satisfy existing public HTTPS validation; personal WhatsApp contact links are suppressed.

## Schedule, persistence and recovery

| Monday, 06:00 SAST (04:00 UTC) | Inclusive week | Eligible dates |
| --- | --- | --- |
| 7 December 2026 | 7–13 December | 13 Dec |
| 14 December 2026 | 14–20 December | 15, 16, 17, 19, 20 Dec |
| 21 December 2026 | 21–27 December | 22, 23, 24, 27 Dec |
| 28 December 2026 | 28 December–3 January 2027 | 29, 30 Dec; 2, 3 Jan |

The existing runner generates on the first tick at/after 06:00, normally within five minutes. Missed weeks are caught up on a later tick through 3 January; older weeks are then archived without edit polling or stale notices. Current-week approved changes are detected on each tick. No automatic generation or change polling runs on/after 4 January. Admin previews can be created before the programme without notifications or posting confirmation. There are four edition families; a material change creates another revision within that week's family.

`festive_weekly_editions` stores week boundaries, revision, content hash, sanitized public source snapshot, message parts, changed-field list, correction parts, timestamps, status, last error and admin confirmation. A database advisory lock per week plus `UNIQUE(week_start, revision)` serializes scheduler/manual generation. Slot SHARE locks use the existing slot-lock mutation protocol to prevent inconsistent mixed source snapshots. Unchanged reruns return the existing revision and generation timestamp, including after process restart/redeployment. Source publication and booking code is unchanged.

A generated and validated revision is atomically committed as READY_FOR_REVIEW (generation is not exposed as a partial separate row). Mark-as-posted records approval and posting timestamps together after explicit confirmation, producing POSTED / ADMIN_CONFIRMED. A material change marks the previous row OUTDATED without changing its message, posted timestamp or posting administrator, then inserts READY_FOR_REVIEW. FAILED records a failed first generation; a failed refresh retains valid existing content and records `last_error`. Successful retry clears errors. GENERATED and APPROVED are reserved schema states; their logical events are represented by successful generation and the explicit approval timestamp rather than additional UI steps. No provider group message ID is fabricated.

Database outages cannot write their own failure receipts; the runner logs the failure and retries on the next tick. Rendering failures persist a generic error type, without exception content that could contain sensitive data. Failure of weekly scheduling does not stop TT queue processing. A transaction crash rolls back both the new revision and superseding status.

Corrections compare the latest approved source against the **last administrator-confirmed posted revision**, so edits accumulate until reshared. Before any edition has been posted, the comparison uses the previous preview. Unapproved edits, pending-state changes with identical public information, RSVP changes and internal revision bumps do not trigger an announcement revision. Cancellations, withdrawal, host replacement, newly filled vacancies and changes to approved time/venue/distance/notes do. Historical/outdated previews are labeled ARCHIVED — DO NOT SHARE. Posting an old revision is rejected and refreshes current content. Posted editions are never silently overwritten.

## Admin experience

Send `WEEKLY` for a native list, or `WEEKLY TEXT` for a numbered fallback:

1. Preview this week
2. Refresh announcement (selected edition, or this week)
3. Copy/share announcement (selected edition, refreshed first)
4. Next week's draft
5. Previous announcements (paginated revision history)
6. Mark as posted (second confirmation required for the exact previewed revision)

Before/after the programme, preview offers the four dated editions. Each preview shows its revision/status, optional notification receipt counts, and copy-ready message parts. Use WhatsApp's own Copy or Forward action on each part. This is client-native forwarding, not a bot-supplied group-send API or custom share button. Send BACK/CANCEL to leave. RUNS/HOST/JOIN/HELP and existing TT navigation continue through their original handlers. Weekly actions do not change any hosting reservation.

Optional `WEEKLY ALERTS ON` / `WEEKLY ALERTS OFF` records a separate consent preference in `festive_weekly_subscriptions`; existing member reminder settings are untouched. `festive_weekly_notices` holds one receipt per edition revision and opted-in admin. A notification says a week/revision is ready and directs the captain to WEEKLY for changes/correction. Multiple edits between runner ticks coalesce naturally; no groups receive edits automatically.

Notice statuses: PENDING, BLOCKED_TEMPLATE, SENDING, ACCEPTED, FAILED, UNCERTAIN, SUPPRESSED, SIMULATED. SENDING is committed before network I/O. Timeout, 5xx or missing provider ID is UNCERTAIN; a crash can leave SENDING. Neither is automatically resent, because Cloud API cannot guarantee exactly-once acceptance across a crash. Definitive rejection records FAILED. Review ambiguous attempts with the provider before any manual resend; a generic job retry does not clear their receipt. ACCEPTED is API acceptance, not device-delivery confirmation; this release adds no delivery-status webhook. UAT marks SIMULATED and makes no provider request. Revoked consent/admin access, obsolete editions and expired weeks suppress notices.

## Configuration and controlled release

Required new settings (all publication/notification flags stay off for release preparation):

```dotenv
FESTIVE_WEEKLY_DIGEST_ENABLED=false
FESTIVE_WEEKLY_DIGEST_TIME=06:00
FESTIVE_WEEKLY_DIGEST_TIMEZONE=Africa/Johannesburg
FESTIVE_WEEKLY_AUTO_GROUP_POST=false
FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED=false
FESTIVE_WEEKLY_BOT_LINK=https://wa.me/<verified-display-number>?text=RUNS
```

Optional mode B, only after provisioning and separate approval:

```dotenv
FESTIVE_WEEKLY_NOTIFICATION_TEMPLATE=
FESTIVE_WEEKLY_TEMPLATE_APPROVED=false
# Keep the existing language matched to the approved template:
WHATSAPP_TEMPLATE_LANGUAGE=en_GB
```

Create/approve a dedicated two-body-parameter template (no quick-reply component required), e.g.:

> Your requested Irene AC festive weekly announcement for {{1}}, revision {{2}}, is ready for review. Reply WEEKLY to preview the latest schedule and any changes. Reply WEEKLY ALERTS OFF to stop these notifications.

Parameters are ISO week start and revision number. Obtain provider category/approval, verify language and parameter contract, confirm applicable charges, and complete authorized test-number validation before setting `FESTIVE_WEEKLY_TEMPLATE_APPROVED=true`. Do not reuse the existing runner reminder template, whose semantics and quick reply differ. No new template was submitted or message sent during implementation.

Keep `FESTIVE_RUNS_ENABLED`, `FESTIVE_UAT_MODE`, existing Flow IDs, keys, template configuration, TT settings and the runner configuration at their established live values. Do not set global festive UAT mode on production to test this feature: that would suppress the already-live festive functionality.

Release sequence:

1. Review the dedicated PR and green CI. The feature uses current dependencies and Python 3.13.5; no package or cron changes are needed.
2. In the isolated test environment only, apply `python -m app.migrations upgrade`, supply the new bot-link/schedule settings, keep UAT mode on and weekly notifications/group posting off. Run the UAT below with a test admin. Local automated tests use a disposable database and mock all provider I/O.
3. Take the normal production database backup. Apply additive migration `2026-11-20-festive-weekly-v1` before deploying the new code (the old release tolerates additional tables). Deploy the reviewed commit with weekly enablement **false**. Existing startup schema validation requires this migration.
4. Run `python scripts/festive_weekly.py --check` and `python scripts/festive_weekly.py --preview-week 2026-12-07` under the web service's environment. These commands are read-only and never enqueue/send. Verify `/ready`, `/health`, current RUNS behavior and the existing runner's successful five-minute execution.
5. Obtain explicit production activation approval. Then enable only `FESTIVE_WEEKLY_DIGEST_ENABLED=true` for mode A. No group or proactive notification is enabled by that flag. On/after the first due Monday, inspect edition rows or WEEKLY. No need to create another cron or force a live `/jobs/run` merely to test this feature (that endpoint can process unrelated real jobs).
6. Enable mode B only after its independent template, consent and test gates. Mode C requires new verified official eligibility, destination, permissions, test-group delivery and club approval; this code rejects the flag.

Rollback: set `FESTIVE_WEEKLY_DIGEST_ENABLED=false` and `FESTIVE_WEEKLY_ADMIN_NOTIFICATION_ENABLED=false`; leave the existing festive feature enabled. The weekly kill switch suppresses already-queued weekly replies/notices. If necessary redeploy the prior release `e48f0f9`; retain the three additive tables and migration receipt for audit. Do not drop tables, remove member data, change TT cutoff/submissions, or restore an old database over live registrations. Re-enabling after a queued notice was suppressed may require explicit operator reconciliation; do not assume it will send automatically.

## UAT and test evidence

Baseline before code edits: **441 unit tests, OK, 2 existing skips**, under both the local Python 3.11 environment and deployment-matched Python 3.13.5. The two pre-existing skips are physical Android/iOS festive device acceptance placeholders. Final workspace verification: **471 unit tests, OK (2 existing device skips)** and **104 real PostgreSQL integration tests, OK** under Python 3.13.5. This includes **30 new contract tests and 27 new integration tests**. All new-file Ruff checks, Python compilation, `pip check`, and the read-only deployment check/preview CLI passed. The unit totals include the user’s pre-existing uncommitted reporting tests; those files are preserved and excluded from this PR.

UAT steps (isolated test data, no real groups):

1. Enable weekly generation only in test, set test bot link, use explicit test ADMIN_NUMBERS. Non-admin WEEKLY and forged interactive actions must refuse access. Check existing RUNS, HOST, JOIN and TT submission journeys.
2. With controlled time just before/at 06:00 SAST on each listed Monday, invoke the schedule service. Verify date counts 1/5/4/4; 28 December includes 2 and 3 January. Reinvoke concurrently and after process restart; unchanged content retains one revision and one notice per opted-in admin.
3. Preview a published, vacant and assigned-incomplete date. Verify the published snapshot only. Edit a private draft and verify unchanged output; approve it and verify a new revision and correction.
4. Preview/forward in test, mark the exact revision as posted, approve another venue/time change, and verify the old text/timestamp remains with OUTDATED status. Test several edits before reposting: correction includes all differences from the last posted revision. Confirming an old button must fail safely.
5. Cancel and reassign a host, then refresh. Verify cancellation correction and new host name without phone or attendee details. Verify approved distance-specific timing notes are preserved.
6. Exercise native list, WEEKLY TEXT numbers, BACK/CANCEL, all four draft previews and history pagination. Forward/copy each part manually in an authorized test chat; mark posted only after sharing. Future drafts cannot be marked posted. Physical Android/iOS rendering of this new menu is a release UAT item, not claimed by payload tests.
7. Leave optional alerts disabled: no proactive notices. For mock tests, opt in, configure template gates, simulate acceptance/rejection/timeout/missing ID and verify precise receipt states. Replaying an accepted/uncertain notice must not send again. Revoke admin access/opt-in and verify suppression. Expired free-form replies must not be sent after 23 hours.
8. Fail generation and database access; verify next-tick recovery, retained posted content, visible failure receipts/logging and continued TT queue dispatch. Disable weekly and verify no scheduled output. Advance to 4 January and verify automatic generation stops.

Coverage mapping: T01–T12 and T22/T24–T26/T29/T30 use deterministic contract tests; T13–T21/T23/T27/T28 use real PostgreSQL, controlled clocks and mocked transport. The complete existing festive/TT integration suite also verifies bookings, RSVP, approvals, privacy, Flow sessions, TT submission/cutoff and admin workflows. New tests additionally cover cumulative corrections, stale confirmation, failed generation recovery, missing settings, separate opt-in and native/text navigation. No real group messages are permitted by these tests.

Known limitations: runner cadence is five minutes rather than second-exact delivery; new weekly physical-device UAT and real approved-template delivery remain pending; no new delivery-receipt webhook; ambiguous provider sends require manual reconciliation; changes are polled only through the programme; no RSVP counts are announced; long content may require forwarding multiple parts. No LLM API is used by generation. Publication is a human action in mode A.
