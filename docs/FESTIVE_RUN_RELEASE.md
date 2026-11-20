# Festive Run controlled release

**Status (20 November 2026): isolated iPhone draft journeys passed; NOT production-ready.** Host details submission, management edit/resubmission, RSVP creation, reminder-preference update and RSVP cancellation were verified against the test database. The test encryption key, Meta JSON validation and encrypted health check passed. After the user reported business verification, Builder draft delivery succeeded. Earlier publication rejection is historical evidence, not a fresh eligibility check. The production key was last observed as MISMATCH and has not been changed or rechecked. The stored test API token has expired; Builder delivery used the authenticated UI. Published Flow readiness, template approval, Android device testing and the full accessibility/fallback checklist remain outstanding. Production and billing remain unchanged. See [dated test evidence](FESTIVE_DRAFT_TEST_2026-11-20.md).

## Configuration

### Isolated Meta test setup (18 November 2026)

Meta test phone `+1 555 193 5738` (ID `1524654827389567`) belongs to Test Messaging Account `1638834777722587`. Its separate public key was registered and read back as **VALID**; the returned key matches the locally generated RSA pair. The approved recipient is verified. The production number's key was not changed; its read-only audit still reports MISMATCH.

Railway environment `festive-test` (`930b1b8f-9404-4bf2-8b42-20981603be2f`) was created empty. It uses a new private PostgreSQL service, `Postgres-xp5s`, with hostname `postgres-xp5s.railway.internal`; no production database was copied. The test web service uses the festive feature branch and custom start command `python -m app.festive_test_runtime` with `/ready` healthcheck.

That separate entry point refuses any other environment ID, phone ID or database host before opening the database. It applies migrations only after these checks, creates a mode-0600 temporary private-key file from the test-only `FESTIVE_FLOW_PRIVATE_KEY_B64` secret, and runs the existing app behind an inbound WABA/phone/recipient filter. It adds a verified GET `/webhook` challenge handler and requires a job token even with `ENV=test`. Production's entry point remains unchanged. Required test secrets are the existing Meta app secret, the test-only access token, separate webhook verification/job tokens, and the test encryption key. No production WhatsApp token is used.

Use a **test-WABA callback override** when subscribing this app; never edit the shared app-level production callback. Keep `FESTIVE_UAT_MODE=true` until the endpoint and three Flows pass Meta validation. Builder draft sends to the approved test recipient have exercised real device journeys while application send suppression remains enabled. Application-originated delivery testing requires separately controlled test-only sends. Do not configure a scheduled runner or import member data for this initial test setup.

Verified deployment: `f1328f627cb3dfc50783df90c0c885fcf61356df`, CI and secret scan passed. Railway reports deployment successful; `https://festive-test-web-festive-test.up.railway.app/ready` returns `{"status":"ready","checks":{"database":"ok"}}`. The test app secret and test-only credentials are stored in this service. Meta accepted the test-WABA subscription and GET readback shows the override callback `https://festive-test-web-festive-test.up.railway.app/webhook` for app `1598641271311837`; the shared app callback was not edited.

All three sandbox drafts were created with Flow JSON 7.3 / Data API 4.0 and returned `validation_errors: []`:

| Flow | Test ID | Status |
|---|---|---|
| Host | `1143642411969020` | DRAFT |
| RSVP | `1130983079810609` | DRAFT |
| Manage | `3178619158994296` | DRAFT |

In the Host draft's Endpoint tab, Meta's **Run Health check** returned **Endpoint is active / Health check request successful**, using public key from test phone `+1 (555) 193-5738`. This exercises the shared encrypted endpoint; it is not a complete device journey.

Host publication returned **Blocked by Integrity**, code `139000`, subcode `4233020`, non-transient, user message **Integrity requirements not met.**, trace ID `AJykhsYsXNxoByenLWhvNeU`. No repeat publication was attempted for the other drafts. Account health additionally reports WABA payment warning `141006` and business verification warning `141010`; these do not establish which condition caused the integrity rejection or guarantee that adding payment will fix it. No billing, business verification or production settings were changed.

Next account-owner action: review the test account's Flow eligibility with Meta support, supplying the app/WABA/Flow IDs and trace above, and ask whether free test-number dynamic Flows require further verification. Keep `FESTIVE_UAT_MODE=true` and `FESTIVE_FLOWS_READY=false` until resolved. Draft IDs are recorded here, not configured as published runtime IDs. No festive sends or scheduled runner are enabled. Local key material and the detailed setup record are Git-ignored under `.env.festive-test.d/`.

| Setting | Default / purpose |
|---|---|
| `FESTIVE_RUNS_ENABLED` | `false`; command, data-endpoint, scheduler and delivery kill switch |
| `FESTIVE_UAT_MODE` | `true`; restrict incoming feature access to allowlist and suppress every festive network send |
| `FESTIVE_UAT_ALLOWLIST` | Empty; comma-separated sender IDs using existing phone format |
| `FESTIVE_INTERACTIVE_ENABLED` | `true`; set false to exercise numbered fallback |
| `FESTIVE_FLOWS_READY` | `false`; set true only after endpoint/account/Flow validation |
| `FESTIVE_HOST_FLOW_ID` | Published host Flow ID |
| `FESTIVE_JOIN_FLOW_ID` | Published RSVP Flow ID |
| `FESTIVE_MANAGE_FLOW_ID` | Published management Flow ID |
| `FESTIVE_FLOW_PRIVATE_KEY_PATH` | Secure mounted RSA private-key file matching the phone number's uploaded public key |
| `FESTIVE_FLOW_PRIVATE_KEY_B64` | Alternative secret containing base64 PEM, decoded in memory; mounted path takes precedence |
| `FESTIVE_FLOW_PRIVATE_KEY_PASSWORD` | Optional private-key passphrase; secret |
| `FESTIVE_NOTIFICATION_TEMPLATE` | Approved utility template matching the exact two-body-parameter / one-quick-reply contract |
| `WHATSAPP_TEMPLATE_LANGUAGE` | Existing setting; defaults to `en_US`; must match approval |

Existing `ENV`, `DATABASE_URL`, `WHATSAPP_APP_SECRET`/`META_APP_SECRET`, `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, `ADMIN_NUMBERS`, `JOB_RUNNER_TOKEN` and deployment URL settings retain their meaning. No credentials or feature flags were written to `.env`. Only `cryptography` and its pinned runtime dependencies were added to requirements, for authenticated Flow encryption; formatting/runtime tools were installed outside the project in temporary directories.

## Meta preparation checklist (execution status above)

1. Inspect the existing business public key and its owner before rotating anything. Read-only audit returned MISMATCH. Resolve the mismatch with the account administrator; use a dedicated sandbox/test number first. Never rotate a production phone's key blindly, because other dynamic Flows may depend on it.
2. Securely generate/load an RSA key pair, keep the private key outside Git and logs, upload/sign the matching public key through Meta's business-encryption API, and verify `business_public_key_signature_status=VALID`. Configure the matching private-key mount/password and Meta App secret in the test deployment.
3. Deploy the branch only to the approved isolated test environment, apply its additive migration and expose `POST <PUBLIC_BASE_URL>/festive/flows` over HTTPS. The endpoint accepts signed, encrypted Data API 4.0 requests; no plaintext bypass exists. Verify encrypted ping and endpoint health/latency.
4. Regenerate assets locally with `python scripts/build_festive_flows.py`. In Meta's Flow Builder/API create **three sandbox drafts**, upload `festive_host.json`, `festive_join.json`, `festive_manage.json`, associate the correct Meta app and endpoint URI. Run Meta validation and resolve every validation error. Local structure tests are not a substitute.
5. Test drafts through Meta Builder with approved test recipients and valid server sessions; publication is not required for this draft-testing route. Before enabling published runtime delivery, publish only those approved sandbox Flows, record their IDs and set `FESTIVE_FLOWS_READY=true` after health checks. Use Flow JSON 7.3, Data API 4.0, message version 3. Check actual client BACK and empty-choice behaviour against the Meta compiler/device tests.
6. Create and obtain approval for a utility notification template. Required body shape: `Irene AC Festive Run Adventures — {{1}}. {{2}} Manage your booking and reminder preferences below.` where 1 is date and 2 is the run/reminder/change summary. Include one QUICK_REPLY button labelled `View festive runs`. Runtime button index 0 carries `festive:calendar:0`. If Meta categorises/rejects the proposed template, revise it and obtain approval; do not bypass with free text. The programme currently uses this one contract for host/admin/runner reminders and change/cancellation alerts.
7. Complete every device gate in `FESTIVE_RUN_UAT.md` using an independently approved test environment and test recipients. This implementation's default UAT mode suppresses actual sends. For an authorised device test, use test-only `PHONE_NUMBER_ID`, token and member database; switch UAT suppression off only in that isolated test environment. Do not point this test at production credentials or invite real members.
8. Save Meta validation/health/template evidence and device results with the release record. Only then request explicit production deployment/activation approval.

Read-only audit commands:

```sh
python scripts/audit_festive_whatsapp.py
python scripts/audit_festive_whatsapp.py --remote
```

No audit command sends messages, uploads Flow JSON, publishes a Flow or changes account configuration.

## Local validation

Use Python **3.13.5** and a disposable PostgreSQL database; never substitute the production database. Install `requirements.txt`; the user's separate local reporting tests also need `requirements-reporting.txt` in the shared workspace. The festive feature itself has no reporting dependency.

```sh
python -m pip install -r requirements.txt
python -m pip check
ENV=test DATABASE_URL=postgresql://test:test@localhost/test python -m unittest discover -s tests
# Explicit local disposable database, with a test/integration name:
ENV=test INTEGRATION_DATABASE_URL=postgresql://<local-user>@127.0.0.1:55442/irene_festive_integration \
  python -m unittest discover -s tests/integration -p '*_integration.py'
python -m compileall -q app scripts tests
git diff --check
```

The integration fixtures reset the entire **test** schema, then apply every migration, including festive, under the existing transaction runner. Idempotent second application, partial uniqueness under concurrent requests and rollback on exceptions were verified. Existing TT suites pass. See UAT for exact counts and explicit skips.

## Production enablement — only after explicit approval

1. Confirm a reviewed commit/PR, green CI, verified Meta configuration and signed-off UAT. Keep `FESTIVE_RUNS_ENABLED=false` during deployment. Preserve the existing Railway deployment region and app/DB pairing.
2. Take a restorable production backup under the existing deployment procedure. Apply only the additive migration using the existing release environment: `python -m app.migrations upgrade`. Startup deliberately requires the new revision even while the feature is off.
3. Deploy the reviewed application/dependencies with feature disabled. Verify `/live`, `/ready`, normal TT HELP/check-in/submission/cutoff, and the existing job runner. Do not use a real TT result as a smoke-test mutation without separate authorisation.
4. Configure the verified Flow IDs, secure key mount, endpoint App secret and approved template/language. Ensure the account encryption audit is VALID; the three Flows are PUBLISHED and endpoint health is green. Do not set readiness true based only on local tests.
5. For no-send smoke testing, set `FESTIVE_UAT_MODE=true`, populate only approved test IDs in `FESTIVE_UAT_ALLOWLIST`, and set `FESTIVE_RUNS_ENABLED=true`. Replies are queued but deliberately not sent. Inspect test payloads with mock transport. Restore disabled state after the smoke test if activation approval is still pending.
6. After explicit production activation approval, set `FESTIVE_UAT_MODE=false`, `FESTIVE_INTERACTIVE_ENABLED=true`, `FESTIVE_FLOWS_READY=true`, and `FESTIVE_RUNS_ENABLED=true` in Railway's runtime configuration; restart/redeploy through the existing controlled procedure. This step enables member access and real festive delivery.
7. Verify all 14 slots, one host per role, admin review, published details and notification status. Keep the existing protected `/jobs/run` schedule; no second scheduler is required.

## Immediate rollback / disablement

1. Set **`FESTIVE_RUNS_ENABLED=false`** in the running service configuration and restart/redeploy it through the existing mechanism. Verify ordinary TT behaviour. This closes festive command routing, Flow exchange, scheduling and festive reply/notification delivery, including jobs already queued.
2. If a code rollback is needed, redeploy the previously approved TT commit and dependencies while keeping the flag off. Retain the additive festive tables/data for recovery and audit. The old migration checker accepts extra revision rows; no TT-table rollback is required.
3. Do **not** drop tables, delete members, restore an entire production DB over newer TT results, rotate WhatsApp keys or unpublish shared assets as an emergency rollback. No destructive downgrade is automated. A separately approved data-retention/removal operation can later remove festive-only objects in dependency order.
4. Inspect SENDING/UNCERTAIN notification records and Meta delivery evidence before any retry. Never reset them blindly. A message may have been accepted just before a process/network failure. Document a deliberate manual retry only after resolving that ambiguity.
5. Re-enablement is another controlled release: verify pending/stale jobs and use current templates and published details. Disabled jobs may have been consumed without sending; review intended future notifications rather than bulk-replaying old messages.

## Operational checks

Use existing database/admin permissions; never expose these queries publicly:

```sql
SELECT status, count(*) FROM festive_run_slots GROUP BY status;
SELECT notification_type, status, count(*)
FROM festive_run_notifications GROUP BY notification_type, status;
SELECT count(*) FROM festive_run_sessions WHERE expires_at <= now();
```

Expired session/receipt data contains private draft information; include it in the club's existing retention process and remove expired sessions after the agreed troubleshooting window. No automatic new retention period is imposed. The existing member-erasure flow deletes private sessions and recipient records by foreign key; anonymous host/audit records are retained. Provider acknowledgements are not treated as proof of delivery to a device.

## Review package

The dedicated branch includes only festive source, migration, three Flow assets, integration hooks, dependency pins, new tests and the three requested documents. The unrelated local CI/reporting/manual work remains uncommitted by this task. PR description is prepared in `docs/FESTIVE_RUN_PR.md`; a draft PR, when created, must remain unmerged until the above gates and approvals are complete.

## Production release preparation — 20 November 2026

The account owner authorised production release preparation and execution in this chat. This supersedes earlier test-only scope; deployment remains gated by backup, green checks and provider readiness. No Android hardware is available; this is an explicit limitation, not a simulated physical-device pass.

Read-only production audit: phone `866927696513314`, WABA `4252184618398067`, message quality GREEN, existing encryption MISMATCH. The only prior Flow is an unpublished admin calendar without a data endpoint. No live dynamic Flow dependency was found. Existing production Railway web deployment is `c14f3677-c8c9-4d08-a029-1e3499f12738` at main commit `5e9a0009bfc6598427468164b31b0b248054b368`.

Created three production drafts, each with no Meta validation errors: HOST `2725714667863284`, JOIN `3082270248784761`, MANAGE `1118747054124388`. Endpoint: `https://web-production-5cec.up.railway.app/festive/flows`. Meta reports WABA, BUSINESS and APP available; Flow readiness currently requires the new public key and live endpoint health check.

Submitted utility template `irene_festive_run_update_v1`, ID `1613371004167299`, language `en_GB` matching existing production configuration. Initial wording was rejected because it ended in a variable; the literal booking-management sentence fixes that. Current status PENDING. No message was sent.

The shared endpoint now follows Meta's optional additional token JWT contract. HTTP HMAC, RSA/AES authentication and expiring member-bound database sessions remain mandatory. Present invalid JWTs are rejected. Client error acknowledgements also validate sessions. Secret base64 PEM configuration avoids writing key material into the release image. Sources: [Meta changelog](https://developers.facebook.com/documentation/business-messaging/whatsapp/flows/changelog).

Production backup remains inside Railway on the existing PostgreSQL volume at `/var/lib/postgresql/data/festive-release-backups/pre-release-20261120.dump` (504 KiB; SHA256 `3e5e940344fb373f2b75949b09dc6d21d4b0478d31b6637a9d013a880b72a72f`). The archive directory was validated with pg_restore. Local export was rejected by automatic approval review and was not performed.

Local validation on Python 3.13.5: 439 unit tests passed, two physical-device gates skipped; 76 integration tests passed plus the added encrypted endpoint/no-JWT integration test passed separately (77 total). No automated result certifies Android hardware.
