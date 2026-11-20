# Festive captain desk

This update improves the WhatsApp administrator journey for the existing live festive programme. It uses the same ADMIN_NUMBERS authorization, persistent chat/form sessions, approval snapshots and domain operations. No database migration, Flow asset publication, new environment variable, or scheduler change is required.

## Captain journey

Send **FESTIVE ADMIN** for the captain desk, or **FESTIVE ADMIN TEXT** for numbered replies.

The dashboard shows clear counts and opens focused queues:

1. Ready for review — future submitted details, including changes to published runs.
2. Hosts needed — future OPEN dates; cancelled dates are not counted as vacancies.
3. Details in progress — assigned hosts still preparing their details.
4. Published runs — includes past published runs that can be marked completed.
5. All festive dates — all fourteen dates, including cancelled and completed runs.
6. Weekly announcements — shown when the existing weekly feature is enabled.

Dates have readable day/date labels, status descriptions and lead-host names. Empty queues explain that there is nothing to review and offer a return to the captain desk. Lists retain the existing pagination and numbered fallback.

A run review displays the lead/co-host, aggregate RSVPs, and labeled venue, time, distances, maps, route, coffee and safety information. No raw JSON or internal enum names are presented in normal reviews. Private drafts, submitted details and approved member-visible details have distinct headings. Pending amendments highlight **Was / Now** values, while the screen explains that members still see the previous approved version. Missing required details are listed. Cancelled runs retain saved details for reference.

Only actions appropriate to the run's state and date are displayed. Submitted details can be approved or returned to draft; eligible dates allow host assignment; cancelled dates can reopen; past published runs can be completed. Existing server-side validation remains authoritative.

Choosing a lead host now offers a member-name or member-ID search. Results show names and member IDs to distinguish duplicates, never phone numbers. Only existing members with active consent and a usable name are shown. Searches are literal and bounded to nine matches; a more specific search finds additional matches. Choosing a match opens a confirmation that names the person and explains that old run details will be cleared. Nothing changes until confirmation. Choosing the current lead leaves their details intact and explains why no reassignment is needed.

Confirmations explain the effect of approval, requesting changes, cancelling, reopening, reassignment and completion. **Cancel this run** and **Close menu** are separate choices. Requesting changes explicitly tells the captain to contact the host; it does not falsely claim that a personal message was sent. Completion feedback offers **Next review**, **All dates**, and **Captain desk**. The WEEKLY menu identifies the command to return to the captain desk.

## Review safeguards

The admin UI uses the existing durable form tokens and domain revision checks. It now also:

- Retains the source revision actually reviewed when moving from actions to confirmation. A host edit during review requires reopening the updated run.
- Refreshes the review when going back from confirmation, so the captain sees the new details before another approval attempt.
- Binds admin action/confirmation callbacks to the form session as well as its step revision. A button from an older session cannot confirm a new session with the same step number.
- Rechecks administrator authorization on dashboard, search, queue and member-selection actions.
- Sends long reviews in full as text before a short action list; it does not silently truncate details at the interactive-menu boundary.

An administrator using an old menu during deployment may need to send FESTIVE ADMIN again. Host/member commands and ordinary TT command escape behavior remain available. Private participant lists are not added.

## Verification and release

Baseline: 471 workspace unit tests, OK with two existing physical-device skips. The change adds 10 presenter tests and 18 real PostgreSQL admin-journey tests. Existing end-to-end festive booking/approval tests now navigate the captain dashboard and use the session-bound callback IDs.

Final workspace validation: 481 unit tests passed (two existing physical-device skips), and all 122 PostgreSQL integration tests passed. Ruff, Python compilation and whitespace checks passed. Automated checks use an isolated local PostgreSQL database, controlled dates and mocked provider calls. They do not certify physical Android/iPhone rendering or send live messages.

Before deployment, review the PR and its CI. Deploy the reviewed main commit through the existing Railway web service; no migration or Meta Flow publication is needed. Preserve all live festive, weekly and TT flags. Do not upload the working directory, which contains unrelated local work and production-derived local artifacts. Roll back by redeploying the previous release if necessary; no data rollback is required.

Suggested captain UAT on an authorized test account:

1. Open native and text dashboards; check queue counts, empty queues and both calendar pages.
2. Review an initial submission and a published run's amendment; compare time/venue changes and missing details.
3. Search by partial name, exact member ID and duplicate name; try a nonconsenting member and confirm only the intended host.
4. Use BACK during search and confirmation, and verify that no booking changes until confirmation.
5. Change a draft while its review is open; confirm that approval is blocked until the latest details are reopened.
6. Try an old confirmation from a previous session; verify it cannot act on the current review.
7. Check cancellation/reopening warnings, action-specific feedback, and next-review navigation.
8. Open WEEKLY from the dashboard and return using FESTIVE ADMIN. Check RUNS, HOST, JOIN and TT navigation still work normally.
