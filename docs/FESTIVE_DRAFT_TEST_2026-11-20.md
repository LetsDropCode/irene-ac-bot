# Draft Flow test — 20 November 2026

## Verified procedure

Meta's [Testing and Debugging Flows](https://developers.facebook.com/documentation/business-messaging/whatsapp/flows/guides/testingdebugging) (updated 2 July 2026, inspected in Safari) documents:

1. Send a message from the test device to the sender to open the 24-hour customer-service window.
2. Open a Draft Flow in WhatsApp Manager, then select the three-dot menu → Send.
3. Choose the sender and recipient, supply a Flow token and select Request data for a dynamic initial screen.
4. Alternatively send an interactive Flow message through Cloud API with `mode: "draft"`.

Our application requires a server-created session token. An arbitrary token from the generic documentation example is insufficient.

The [sending guide](https://developers.facebook.com/documentation/business-messaging/whatsapp/flows/guides/sendingaflow) (updated 4 November 2026) still lists business verification and high message quality as prerequisites. No free-test-number exception was established by this review. The previous AI support reply is not evidence of an exemption.

## Scope and observations

- Test WABA: `1638834777722587`; sender phone ID: `1524654827389567`.
- Railway environment: `930b1b8f-9404-4bf2-8b42-20981603be2f`; service: `8130cb56-6611-4d41-8d88-551498a5e8c4`.
- Runtime isolation validation passed. `FESTIVE_UAT_MODE=true`, `FESTIVE_FLOWS_READY=false`, `FESTIVE_RUNS_ENABLED=true`; these settings were not changed.
- The user confirmed sending HOST from the approved recipient and identified the device as iPhone. Model, OS and WhatsApp version were not collected because delivery failed.
- All three test Flows were visibly Draft in WhatsApp Manager.
- Test database had 14 calendar slots and no member for the approved recipient. Created a clearly labelled UAT Test fixture with test consent state and leaderboard opt-out, then a HOST session with 14 date options. This is synthetic test setup, not production consent evidence.
- No real event was booked, no RSVP submitted, and no reminders enabled.

## Results

| Check | Result | Evidence |
|---|---|---|
| Existing test API credential | BLOCKED | Meta HTTP 401, code 190/subcode 463: temporary token expired. No credential was replaced. |
| Host Draft send via Builder | BLOCKED | Selected test sender, approved recipient, valid HOST session token, Request data. Meta displayed “Flow sending failed — Integrity requirements not met.” No successful delivery was confirmed. |
| Host interactive Builder preview | BLOCKED | Correct isolated endpoint and test phone selected. INIT returned HTTP 432 with `Invalid Flow token signature`. |
| INIT request displayed in Builder | OBSERVED | `action`, `data`, `flow_token`, `version: "4.0"`; no `flow_token_signature` shown. |
| iPhone complete journey | NOT PASSED | Draft message could not be sent. |
| Android, RSVP and Manage device journeys | NOT RUN | No claim of compatibility or completion. |

The Builder send is independent of the expired service API credential. Draft mode did not bypass the account integrity restriction in this attempt.

## Endpoint follow-up

Meta's [endpoint guide](https://developers.facebook.com/documentation/business-messaging/whatsapp/flows/guides/implementingyourflowendpoint) (updated 28 June 2026) describes `flow_token_signature` as an HS256 JWT for Flow JSON >=7.3/Data API >=4.0, with the app secret as signing key and the Flow token in its payload. It says businesses can choose to validate this additional signature. Separately, the HTTP `X-Hub-Signature-256` authenticates requests from Meta.

Our handler requires the additional JWT for every non-ping request. The preview's HTTP signature and encryption passed far enough to reach that check. A supported preview authentication design remains unresolved; no signature checks were removed or bypassed, and no runtime code was changed.

Next steps: ask Meta to identify the failing draft-send integrity check using this concrete Builder reproduction, and clarify whether its interactive preview supplies the token JWT. A test-only preview design may be needed, retaining HTTP authentication, encryption, unguessable expiring sessions and database isolation. Renew the test API credential before API-based sends. Do not submit shared-portfolio verification or add payment details based on the generic AI reply.

Production, billing, verification, shared callbacks, production keys and deployment settings were unchanged.

## Follow-up after business verification and iPhone retry

After the user reported business verification, the Builder accepted the same test-only Host draft send. The user's iPhone screenshot confirms delivery and opening, followed by HTTP 432 `Invalid Flow token signature`. This establishes that the earlier send-time integrity restriction no longer blocked that attempt; it does not establish production readiness.

Test-only diagnostics confirmed that the iPhone request omitted the additional JWT. The outer HTTP HMAC and encryption checks passed. The isolated runtime now permits absence of that optional field only after validating its exact test environment/phone/database boundary, UAT mode, an existing unexpired session, allowed session kind, member eligibility and recipient allowlist. A present but invalid JWT remains rejected. The production endpoint and entry point were not changed.

Deployment `20a60f4c-29c9-4cc0-b9de-87a7f1e3d2a5` passed its health check on festive-test-web. Uploaded source was a clean archive of tracked HEAD plus the test-runtime fix, excluding local credentials and unrelated working changes.

Validation: 26 festive unit tests passed; 2 physical-device acceptance gates remain skipped. Live encrypted requests against the isolated HTTPS endpoint returned:

| Request | HTTP result |
|---|---|
| Valid allowlisted host session, missing optional JWT | 200, CHOOSE, all 14 dates |
| Present forged JWT | 432 |
| Invalid HTTP signature | 432 |
| Unknown session | 432 |

The user confirmed the date selector loads on their iPhone after retrying this deployment. This verifies the initial Host screen on one iPhone; complete host/RSVP/manage journeys and Android compatibility remain unverified. No production deploy, billing change, verification submission or credential change occurred. Normal festive sends remain suppressed; no scheduler was enabled.

## Validation-error data loss found during host journey

The user's initial completion report did not match database evidence: the 15 December booking existed, but the details record was an empty DRAFT. Session receipts proved that entered fields reached the server. Errors for time formatting and incomplete meeting/route instructions returned old init-values, clearing the form and resetting submit intent to draft. Therefore the earlier conversational claim that submission-for-review passed is withdrawn.

Fixed the DETAILS validation-error response to preserve submitted text fields and save mode. A regression test checks venue, invalid time, submit intent, error and updated revision. Targeted suites: 27 passed, 2 physical-device gates skipped. Deployment `fb4df671-5138-4b4b-8c8f-e8fa514ea9d1` passed its health check in the isolated test service. A live service check confirmed validation errors retain inputs without saving event details. Production was not deployed.

Sent the Manage draft through Meta Builder to the existing allowlisted iPhone recipient, with a new server session exposing the existing 15 December lead-host booking. Meta reported message sent successfully. Awaiting physical edit/resubmission before reviewer approval and RSVP testing; no pending event was approved prematurely.

The subsequent iPhone resubmission was verified in the database: 15 December was PENDING_APPROVAL at revision 3, with complete details (05:30, 15km and the user's venue/route fields preserved). Approved via the normal `admin_action` service with the configured test admin and expected revision 3, producing PUBLISHED revision 4 in the isolated test database. This is event approval, not publication of the Meta Flow or production release.

Created a JOIN session which dynamically listed that approved test event and sent the RSVP draft through Meta Builder to the allowlisted tester; Meta reported successful send. RSVP completion remains pending. No scheduled or production messages were enabled.

RSVP completion subsequently verified after the user's iPhone confirmation: JOIN session reached DONE; database contains an ACTIVE RSVP for 15 December, 15km, with reminder opt-in true. Reminder preference persistence passed; actual reminder delivery remains untested and suppressed by UAT mode. Host booking, management edit/resubmission and RSVP creation have now been exercised on this iPhone; RSVP modification/cancellation and Android acceptance remain outstanding.

Manage RSVP modification subsequently verified in the test database: 15km RSVP remains ACTIVE and reminder opt-in changed from true to false. Sent a fresh Manage draft for cancellation testing; Meta reported successful send. Cancellation awaits the user's device interaction and database verification.

Cancellation subsequently verified after the user's iPhone confirmation: Manage session reached DONE with “RSVP cancelled.” The RSVP is WITHDRAWN, reminders remain false, the lead-host registration remains ACTIVE and the test event remains PUBLISHED. This passes RSVP modification and cancellation on the tested iPhone without withdrawing hosting. Android, actual reminder delivery, broader recovery/accessibility checks and production acceptance remain outstanding.

## Automated follow-up without Android hardware

436 unit tests passed, with 2 explicit physical-device skips. All 76 local PostgreSQL integration tests passed with mocked transports, including a new invalid-time / reopen / correct / submit journey. Initial sandbox execution could not connect to localhost; rerunning with permitted local database access passed. Android hardware is unavailable and Android device acceptance remains unverified. These checks sent no WhatsApp messages and changed no production or billing settings.
