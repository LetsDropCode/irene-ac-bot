# Festive Run controlled release

**Status: code and local automated UAT prepared; NOT production-ready.** No deployment, production activation, production data mutation or WhatsApp messages were performed. The current release blockers are Meta encryption **MISMATCH**, unprovisioned festive Flows/template, unexecuted Meta validation and physical Android/iOS acceptance.

## Configuration

### Isolated Meta test setup (18 November 2026)

Meta test phone `+1 555 193 5738` (ID `1524654827389567`) belongs to Test Messaging Account `1638834777722587`. Its separate public key was registered and read back as **VALID**; the returned key matches the locally generated RSA pair. The approved recipient is verified. The production number's key was not changed; its read-only audit still reports MISMATCH.

Railway environment `festive-test` (`930b1b8f-9404-4bf2-8b42-20981603be2f`) was created empty. It uses a new private PostgreSQL service, `Postgres-xp5s`, with hostname `postgres-xp5s.railway.internal`; no production database was copied. The test web service uses the festive feature branch and custom start command `python -m app.festive_test_runtime` with `/ready` healthcheck.

That separate entry point refuses any other environment ID, phone ID or database host before opening the database. It applies migrations only after these checks, creates a mode-0600 temporary private-key file from the test-only `FESTIVE_FLOW_PRIVATE_KEY_B64` secret, and runs the existing app behind an inbound WABA/phone/recipient filter. It adds a verified GET `/webhook` challenge handler and requires a job token even with `ENV=test`. Production's entry point remains unchanged. Required test secrets are the existing Meta app secret, the test-only access token, separate webhook verification/job tokens, and the test encryption key. No production WhatsApp token is used.

Use a **test-WABA callback override** when subscribing this app; never edit the shared app-level production callback. Keep `FESTIVE_UAT_MODE=true` until the endpoint and three Flows pass Meta validation. Real device tests require the test deployment's send suppression to be disabled deliberately, while the test-only inbound guard remains active. Do not configure a scheduled runner or import member data for this initial test setup.

Creating these resources does not establish successful deployment or Flow/device validation; record those checks only after their actual results are available. Local key material and the setup record are Git-ignored under `.env.festive-test.d/`.

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
| `FESTIVE_FLOW_PRIVATE_KEY_PASSWORD` | Optional private-key passphrase; secret |
| `FESTIVE_NOTIFICATION_TEMPLATE` | Approved utility template matching the exact two-body-parameter / one-quick-reply contract |
| `WHATSAPP_TEMPLATE_LANGUAGE` | Existing setting; defaults to `en_US`; must match approval |

Existing `ENV`, `DATABASE_URL`, `WHATSAPP_APP_SECRET`/`META_APP_SECRET`, `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, `ADMIN_NUMBERS`, `JOB_RUNNER_TOKEN` and deployment URL settings retain their meaning. No credentials or feature flags were written to `.env`. Only `cryptography` and its pinned runtime dependencies were added to requirements, for authenticated Flow encryption; formatting/runtime tools were installed outside the project in temporary directories.

## Required Meta preparation (not executed)

1. Inspect the existing business public key and its owner before rotating anything. Read-only audit returned MISMATCH. Resolve the mismatch with the account administrator; use a dedicated sandbox/test number first. Never rotate a production phone's key blindly, because other dynamic Flows may depend on it.
2. Securely generate/load an RSA key pair, keep the private key outside Git and logs, upload/sign the matching public key through Meta's business-encryption API, and verify `business_public_key_signature_status=VALID`. Configure the matching private-key mount/password and Meta App secret in the test deployment.
3. Deploy the branch only to the approved isolated test environment, apply its additive migration and expose `POST <PUBLIC_BASE_URL>/festive/flows` over HTTPS. The endpoint accepts signed, encrypted Data API 4.0 requests; no plaintext bypass exists. Verify encrypted ping and endpoint health/latency.
4. Regenerate assets locally with `python scripts/build_festive_flows.py`. In Meta's Flow Builder/API create **three sandbox drafts**, upload `festive_host.json`, `festive_join.json`, `festive_manage.json`, associate the correct Meta app and endpoint URI. Run Meta validation and resolve every validation error. Local structure tests are not a substitute.
5. Publish only those approved sandbox Flows, record their IDs and set `FESTIVE_FLOWS_READY=true` after health checks. Use Flow JSON 7.3, Data API 4.0, message version 3. Check actual client BACK and empty-choice behaviour against the Meta compiler/device tests.
6. Create and obtain approval for a utility notification template. Required body shape: `Irene AC Festive Run Adventures — {{1}}. {{2}}` where 1 is date and 2 is the run/reminder/change summary. Include one QUICK_REPLY button labelled `View festive runs`. Runtime button index 0 carries `festive:calendar:0`. If Meta categorises/rejects the proposed template, revise it and obtain approval; do not bypass with free text. The programme currently uses this one contract for host/admin/runner reminders and change/cancellation alerts.
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
