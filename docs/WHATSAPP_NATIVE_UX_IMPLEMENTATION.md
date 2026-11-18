# WhatsApp native UX implementation

## Changes

The existing FastAPI, PostgreSQL, Railway and unittest architecture is retained. `app/meta_api.py` validates/configures Graph URLs and classifies sanitized send errors. Credentials, permission failures and rejected 4xx payloads stop automatic retry; transient/network failures retain the queue's attempt limit and delay. Manual retries remain explicit operator actions. All normal sends still persist in `job_queue`. The deliberate erasure-confirmation direct send remains untracked and does not recreate personal diagnostic records.

`app/native_messages.py` contains pure button, named-section list and static Flow builders. New menu navigation and short result/progress/profile confirmations replace text with one interactive message when enabled. Summaries exceeding the interactive body limit stay as one text message with command recovery. Existing imports and mock seams are preserved. Reply buttons/lists used by existing TT paths remain available with the flag off. Stable IDs are resolved by `help_flow.py`; stale action state continues through the existing guarded TT/admin state machines.

Approved-template construction validates its configured name, language and text values. Callers can supply an expected body parameter count and up to two approved URL-button variable suffixes; values are URL encoded. The caller must match the approved template's button positions. No approval call, campaign or generic component passthrough was introduced.

## Static Flow lifecycle

1. Verify the published asset and turn on the explicit flags. Missing readiness uses the existing manual date prompt. A terminal send failure or signed failed-delivery event queues one deduplicated typed-date prompt only while the session is unexpired, authorized and unchanged; delivered/read evidence suppresses that fallback. Launch/fallback delivery rechecks session state, expiry, consent and authorization under the member lock, so queue delay cannot turn it into an out-of-window follow-up. It is never used for templates.
2. Lock the consenting owner's member row. Verify admin authorization and the current date-selection draft. Atomically insert a hashed random session token and enqueue the launch. Launch retries with the same inbound key reuse the queued launch.
3. Signed `nfm_reply` completions enter the registry, not the TT command parser. Reject malformed JSON, unknown tokens, wrong owners, revoked admins, expired sessions and changed conversation state.
4. Lock the member then the session. Validate the date independently of the calendar. Atomically advance to mode selection, enqueue its prompt and consume the token. Concurrent/replayed completion has no second effect. Actual result/attendance writes still require the existing explicit final confirmation and existing duplicate-result constraints.
5. Tokens expire after 30 minutes. CANCEL, manual progression or another draft makes the old expected state invalid. Expired/abandoned rows are cleaned after one further day. Members can always type the date or restart. No member name/phone/ID is embedded in a token.

Extension contract: register a `StaticFlow(key, state_prefix, admin_only, validate, complete)` at startup. Hold the owner lock before `enqueue_flow_launch`; call the pure `static_flow` builder with a configured, verified ID and valid entry screen/data. Validators must recheck domain constraints. Completion callbacks receive the transaction cursor and must use it for every mutation and queued reply; never perform external I/O. Definitions are application code, not user-provided names. Do not add dynamic data exchange without its encrypted protocol, key lifecycle and independent security tests.

## Delivery diagnostics

`whatsapp_delivery_status` stores Meta message ID, queue ID, strongest observed state, event timestamp and numeric error code. It stores no recipient, body, credentials or raw error text. Precedence is accepted < sent < failed < delivered < read: confirmed delivery/read cannot be downgraded by a delayed failure. Duplicate/same-rank events are no-ops; this is a diagnostic summary, not a full event history. Failures never reopen a TT submission or automatically resend an accepted message.

Worker job context adds an opaque queue correlation value only with the flag enabled. API responses record acceptance; early signed callbacks can correlate via the opaque value plus the queued recipient. Diagnostic DB failure after a successful API response does not trigger a duplicate send. Unknown/unmatched events are ignored. The existing queue remains at-least-once: a worker crash after Meta accepts but before marking DONE can still cause a repeat. Meta-side exactly-once delivery is not claimed.

`/jobs/run` prunes status records older than 30 days and sessions one day after expiry, including with flags off. Old jobs cannot recreate status rows past the 30-day horizon. Queue deletion on consent withdrawal/erasure cascades status deletion; Flow sessions are explicitly removed on withdrawal and cascade on member deletion. Existing backup retention remains governed by the existing POPIA policy. Cleanup depends on the existing scheduled worker continuing to run.

## Festive hosting integration contract

No festive implementation exists in the inspected branches. This release adds no hosting tables, reservation jobs or competing deployment. The future programme must reuse the queue, registry, consent checks and stable IDs.

Eligible dates are **13, 15, 16, 17, 19, 20, 22, 23, 24, 27, 29, 30 December 2026; 2 and 3 January 2027**. Store ISO dates in the Africa/Johannesburg calendar. Members choose one or more dates. Selection is a draft until explicit review/confirmation.

The future service should expose `available_dates`, `review_selection`, `confirm_hosts`, `amend_hosts`, `cancel_hosts` and `published_schedule`, keyed by member ID and programme ID. Confirm/amend must lock allocations, recheck eligibility/availability and consent, enforce unique programme/date ownership and use an idempotency key in the same transaction as the outbox. Never trust the availability snapshot embedded in a static Flow. A conflict returns refreshed choices without partially claiming dates unless the member explicitly confirms that policy.

A published static multi-screen Flow can accept initial availability data, offer a multi-select, review, and complete entirely in WhatsApp. On completion revalidate every date and ownership server-side. Cancellation/amendment needs its own current session and confirmation. Until published, use paginated lists (maximum 10 total rows including navigation), repeated stable `host_date:YYYY-MM-DD` selections and review buttons; 14 dates cannot fit one list. Non-hosts should see only the intentionally published schedule/organiser details, with hosts' sharing permission. Private phone numbers must not be exposed. Club activities is the reserved navigation entry point.
