# Irene AC Festive Run Adventures 2026/2027

Different hosts. Different routes. One Irene family. 💚

Implementation date: 18 November 2026 (Africa/Johannesburg). This is an isolated social-run programme in `LetsDropCode/irene-ac-bot`, branch `feature/festive-run-adventures-2026`. It creates no TT submissions, attendance, results, points or league rankings. Feature and production activation remain off by default. See [release controls](FESTIVE_RUN_RELEASE.md) and [executed UAT / acceptance gates](FESTIVE_RUN_UAT.md).

## Repository discovery and baseline

- Starting branch: `main`; remote `https://github.com/LetsDropCode/irene-ac-bot.git`.
- FastAPI entry: `app/main.py`; webhook ingress/signature verification: `app/webhook.py`; command router: `app/flows/webhook_dispatch.py`.
- Provider: direct Meta WhatsApp Business Platform **Cloud API**, not Twilio or Meta Business Agent. The configured messages endpoint is `graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages`.
- Existing identity: `members.id`, keyed by WhatsApp sender phone; POPIA consent and withdrawal fields. Admins are the existing `ADMIN_NUMBERS` allowlist. Festive operations additionally require a completed member name and active consent.
- PostgreSQL/psycopg2; explicit transactional migration registry in `app/migrations/__init__.py`, advisory migration lock, startup schema validation. No ORM or new migration framework.
- Existing scheduled runner: protected `POST /jobs/run`; durable PostgreSQL `job_queue`, dedupe keys and atomic claims. Festive jobs use this infrastructure.
- Tests: `unittest`, fake transports, separate disposable PostgreSQL integration suite. Baseline before edits: **409 unit tests passed** under the existing Python 3.11.14 local venv. Required deployment runtime is Python 3.13.5; final verification uses a separate 3.13.5 environment.
- Railway entry remains `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. No Railway configuration or production data was changed.
- The command audit found no existing exact `RUNS`, `HOST`, `MY HOSTS`, `HOST SCHEDULE`, `JOIN` or `MY RUNS` commands. Existing HELP/menu and TT workflows remain available. Numeric replies belong to the most recently opened festive menu until BACK/CANCEL or a recognised ordinary bot command.
- Unrelated local CI/reporting/manual changes present at discovery were preserved and excluded from the festive commit.

## WhatsApp capability audit

The provider supports native Flows. Meta currently recommends Flow JSON **7.3**, Data API **4.0**, and message version **3**. These are independent of Graph API version. The existing Graph v22.0 remains supported until **20 May 2027**, covering this programme; the feature does not force an unrelated TT API upgrade. [Meta Flow versions](https://developers.facebook.com/documentation/business-messaging/whatsapp/flows/changelogs), [Graph versions](https://developers.facebook.com/docs/graph-api/changelog/versions/).

Production's read-only audit on 18 November 2026 reports encryption **MISMATCH** and remains unchanged. The separately authorised Meta test number now has a **VALID** matching key and an isolated Railway service. Meta accepted all three Flow JSON drafts without validation errors, verified the test-WABA callback override, and passed its encrypted endpoint health check. Host publication is blocked by **Integrity requirements not met (139000 / 4233020)**. Drafts remain unpublished and sends suppressed. Account health also reports payment/business-verification restrictions; the exact integrity cause is not established. See [release evidence and next action](FESTIVE_RUN_RELEASE.md).

| FEATURE | SUPPORTED | IMPLEMENTED | TESTED | LIMITATION |
|---|---|---|---|---|
| Native host registration Flow | Yes, Cloud API | Yes; date/role, booking confirmation, details, draft/submit, summary | Local payload, state machine, PostgreSQL journey and Meta JSON validation | Test publication blocked by Meta integrity 139000 / 4233020; production key unchanged |
| Native RSVP Flow | Yes | Yes; published runs, offered distances, reminder consent, review | Local payload, simulated complete journey and Meta JSON validation | Same publication blocker |
| Native manage Flow | Yes | Yes; own hosting/RSVP, permitted edits, withdrawal, confirmation | Local payload, simulated management journey and Meta JSON validation | Same publication blocker |
| Dynamic encrypted exchange | Yes | FastAPI `/festive/flows`, RSA-OAEP SHA256/AES-GCM, HMAC and HS256 token signature | Local encryption/signature/expiry/retry tests; Meta encrypted endpoint health PASS | Full device data exchange still pending |
| Interactive discovery lists | Yes | 8 content rows per page plus previous/next | All 14 dates, row/title limits, numbered selection | 10 total rows per message, titles 24 characters |
| Reply buttons | Yes | Booking/review/reminder decisions | Payload limits and fallback journey | At most 3; labels 20 characters |
| Location messages / Maps links | Yes | Receive draft pin; send approved pin or HTTPS link | Payload, coordinates, privacy, saved-pin retention | Pin entry uses chat fallback; Maps URL is available in native form |
| Approved template buttons | Yes | One quick-reply button on scheduled utility-template payload | Mock scheduling/delivery, missing template, provider timeout | Template approval and real delivery not verified |
| Interrupted form recovery | Yes, application-managed | Durable 2-hour sessions, BACK, CANCEL, saved drafts | PostgreSQL resume/back/cancel, stale actions | Unsaved client input is lost if the user closes before submitting a screen |
| Unsupported-client fallback | Client-dependent | `FESTIVE SIMPLE` lists/buttons; `FESTIVE TEXT` numbered menus and batch fields | Simulated host/runner/admin journey | Webhooks do not reveal reliable client OS or Flow support; user chooses fallback |
| Android / iOS rendering | Supported by WhatsApp clients | Same documented native payloads | iPhone host/RSVP/manage core journeys passed 20 November; full device gates still skipped | Android hardware unavailable; full accessibility/fallback acceptance remains pending |
| Meta Business Agent UI additions | Separate product | Not used | Not applicable | No Business Agent capabilities are inferred for this integration |

Meta confirms the [10-row list limit](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-list-messages), [three reply buttons](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-reply-buttons-messages) and [template button combinations](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/components). Templates have their own limits; the implementation uses only one quick reply. It does not confuse their limits with ordinary reply buttons. The [Flow endpoint contract](https://developers.facebook.com/docs/whatsapp/flows/guides/implementingyourflowendpoint/) documents encryption, request signatures, token signatures and endpoint error codes.

The best available alternative before provisioning is paginated native lists and reply buttons with a compact, multi-field draft message. This fallback is not described as the latest native Flow experience.

## Commands and journeys

| Command | Behaviour |
|---|---|
| RUNS | All 14 dates in two pages; status and approved run details |
| HOST | Host Flow when configured; otherwise available dates and a booking confirmation |
| MY HOSTS | Manage own hosting and RSVP selections; lead hosts edit their draft |
| HOST SCHEDULE | Calendar with public host names and open opportunities |
| JOIN | Published run discovery, offered distance, reminder preference and confirmation |
| MY RUNS | Own selections, approved details, changes/cancellations and RSVP withdrawal |
| HELP | Existing help plus a short festive command entry while enabled |
| FESTIVE HELP | Full festive command help |
| FESTIVE ADMIN | Existing phone-authorised captain dashboard and guarded actions |
| FESTIVE SIMPLE / FESTIVE TEXT | Explicit native-message / accessible numbered fallback |
| BACK / CANCEL | Previous form step / end the chat session; already saved registrations remain |

**Host:** choose date and LEAD/COHOST → review registration → confirm booking transaction → lead enters multi-field details → save incomplete draft or submit for review → confirmation. Co-host confirmation ends the form. One member may host several dates; a member cannot occupy both roles on one date. A co-host requires a lead host. A booking never publishes a run.

**Runner:** choose published run → see current approved details → select one offered distance and opt into reminders/change alerts → review → confirm. RSVP is optional for attendance. Repeat JOIN updates the one member/run record. MY RUNS supports withdrawal and change. Directions/route options only appear for approved valid links or pins.

**Manage:** choose one of the member's existing hosting/RSVP selections → permitted action → edit or withdraw → confirmation. Public changes remain a separate draft until another administrator approval. A stale review cannot overwrite newer run details.

**Captain:** the admin-only bot dashboard avoids introducing another authentication system or frontend. It reports totals, hosted/vacant dates, publications, RSVPs and attention counts. Per-date review includes lead/co-host, draft venue/time/routes/safety, approval status, outstanding fields, distance counts and cancellation warnings. Actions are approve, request changes, cancel, reopen, reassign lead using an existing member ID, and complete a past run. Every action rechecks admin status server-side. Cancel/reopen is required before reassigning a published run.

Example messages (illustrative; no messages were sent):

> Member: HOST
>
> Bot: 🎄 Irene AC Festive Run Adventures — Open festive form.
>
> Member taps 13 December, Lead host, Confirm; enters venue/time/distances; chooses Save unfinished draft.
>
> Bot: Draft saved. Return with MY HOSTS to finish later.

> Member: RUNS
>
> Bot: Sun 13 Dec 2026 — Ready to join
>
> Member taps the run, I'm joining, 5km, reminders on, Confirm.
>
> Bot: You're joining on 2026-12-13: 5km. Saved in MY RUNS. RSVP is optional.

The bot's actual wa.me link must use the **display phone number**, not `PHONE_NUMBER_ID` (a Graph object ID) and not `PUBLIC_BASE_URL` (the FastAPI host). Obtain `display_phone_number` from WhatsApp Manager or an authenticated read of `GET /v22.0/{PHONE_NUMBER_ID}?fields=display_phone_number`; strip non-digits and use `https://wa.me/<digits>?text=RUNS`. No number is invented or committed here.

## Data and transactions

Migration `2026-11-18-festive-runs-v1` creates eight separate tables: `festive_run_slots`, `festive_run_hosts`, `festive_run_details`, `festive_run_rsvps`, `festive_run_notifications`, `festive_run_sessions`, `festive_chat_sessions`, `festive_run_audit`.

Exactly these dates are seeded idempotently and constrained at database level:

| December 2026 | January 2027 |
|---|---|
| Sun 13, Tue 15, Wed 16, Thu 17, Sat 19, Sun 20, Tue 22, Wed 23, Thu 24, Sun 27, Tue 29, Wed 30 | Sat 2, Sun 3 |

All domain mutations lock the slot row. Partial unique indexes enforce one active member per role and prevent the same member holding both roles. A unique member/run RSVP is updated rather than duplicated. Foreign keys reuse `members.id`. Session receipt and domain change commit in the same transaction; repeated requests return the saved response, and altered/stale replay requests fail. Receipts are bounded to the latest 40 steps; sessions expire after two hours. A deployment restart does not erase drafts or sessions.

Run states: OPEN → HOST_ASSIGNED → DETAILS_PENDING → PENDING_APPROVAL → PUBLISHED → COMPLETED, with explicit cancellation/withdrawal/reopen branches in `TRANSITIONS`. Direct submission from HOST_ASSIGNED to PENDING_APPROVAL is allowed. During an amendment the public state stays PUBLISHED, while `approval_status` on the separate draft becomes DRAFT/PENDING. Public reads use only the last approved snapshot.

Lead withdrawal before publication releases the slot and clears co-host assignment/draft. Published lead withdrawal cancels, preserves RSVP records and records eligible cancellation alerts; an admin must reopen/reassign. Consent withdrawal or erasure uses additive member triggers to withdraw hosting, cancel affected runs and queue eligible alerts. Erasure anonymises host/audit references and cascades private sessions/RSVPs/recipient notifications. No existing member data is backfilled or replaced.

## Notifications and privacy

- 72-hour host reminder: explicit host opt-in and outstanding/unapproved details.
- 48-hour admin attention alert: configured admins who have existing reminders enabled; no automatic approval.
- 24-hour runner reminder: published run, active RSVP and explicit festive reminder opt-in.
- Approved material change/cancellation: opted-in active RSVPs only. No public attendee list or phone numbers.
- Time calculations use Africa/Johannesburg. When a host has not entered a start time, host/admin deadlines use midnight at the start of the local run **date**; this is a scheduling anchor, never displayed as a run start time.
- Unsent reminder times are recalculated when approved start times change. Late jobs recheck consent, run state, due time and current revision.
- All proactive messages use an approved template, even within the conversational window; ordinary interactive replies follow incoming user messages. No out-of-window free-text workaround exists.
- Missing templates create visible BLOCKED_TEMPLATE records. Repeated scheduling and queue retries do not duplicate sends. SENDING is committed before network I/O; timeout/crash leaves UNCERTAIN/SENDING for manual reconciliation. Cloud API cannot guarantee exactly-once delivery; this intentionally favours no duplicates over automatic recovery of ambiguous attempts.
- UAT mode suppresses network sends. The delivery kill switch also applies to previously queued festive jobs.

URLs require public HTTPS syntax, no credentials/local addresses, and bounded lengths. Times and distances are validated. SQL is parameterised. No HTML surface is introduced; WhatsApp displays user strings as message text. Draft locations are private to the lead and administrators. Logs do not contain Flow tokens, keys, decrypted forms or attendee lists. Read-only audit prints only safe readiness metadata.

## Code map

- `app/services/festive_service.py`: lifecycle, identity, validation, transactions and public projections.
- `app/services/festive_flow_service.py`: persistent Flow/fallback state machine and replay receipts.
- `app/festive_endpoint.py`: signed encrypted data exchange.
- `app/flows/festive_flow.py`: commands, pagination, fallback and captain interface.
- `app/services/festive_transport.py`: validated payloads and send gates.
- `app/services/festive_notifications.py`: scheduled records, templates and guarded delivery.
- `app/services/festive_config.py`: flags and capability negotiation.
- `app/flows/assets/festive_{host,join,manage}.json`: native Flow assets, regenerated by `scripts/build_festive_flows.py`.
- `scripts/audit_festive_whatsapp.py`: local configuration audit, optional read-only `--remote` checks.

## Remaining acceptance limits

Local contract tests are not Meta's Flow compiler. Upload/validation/publication, endpoint latency and health checks, account template approval, physical Android/iOS accessibility/keyboard/back navigation and real test-number delivery remain unverified. Do not activate production until these gates pass. The implementation's primary UX becomes active only with published Flow IDs and `FESTIVE_FLOWS_READY=true`; until then native-message fallback is explicit.

Current release preparation evidence is recorded in `FESTIVE_RUN_RELEASE.md`, including production asset IDs and pending template approval. Earlier integrity restrictions above are historical; current production account/business/app eligibility reads AVAILABLE.
