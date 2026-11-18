# WhatsApp UX test matrix and evidence

Verified locally on 18 November 2026 with Python 3.11, macOS and an isolated PostgreSQL 17 cluster. These are offline tests, not Meta account certification.

## Actual results

| Command/check | Result |
|---|---|
| `python -m pip check` | PASS; no broken requirements. Local pip cache-permission warning only |
| `python -m compileall -q app scripts tests` | PASS |
| `python -m unittest discover -s tests`, Graph v22.0 | **407 tests, 0 failures/errors, 0 skipped** |
| Same command, Graph v27.0 | **407 tests, 0 failures/errors, 0 skipped** |
| `python -m app.migrations upgrade`, empty local DB | PASS; **10 migration modules applied** |
| Migration command repeated | PASS; **0 applied** |
| `python -m unittest discover -s tests/integration -p '*_integration.py'` | **59 tests, 0 failures/errors, 0 skipped** |
| `git diff --check` | PASS |
| Calendar asset diff against main | Empty; existing JSON 7.3 preserved |

The unit suite contains 385 existing tests (with expectations updated for intentional routing/privacy changes) and 22 new tests. The integration suite retains 41 existing tests and adds 18. Running the same 407 tests under two configured versions is not 814 distinct tests. CI now covers both versions on Ubuntu 24.04 and macOS 15; PostgreSQL CI remains version 16. Local PostgreSQL 17 results do not substitute for that CI result.

Early runs exposed four old assertions affected by secured Flow routing, publication gating and an additional privacy cleanup query; one existing PostgreSQL journey also needed a real session launch. A new inspection-script test initially needed its mocked headers initialized. All were corrected and the final suites above passed. Negative-path tests deliberately log signature rejection, sanitized Meta failure and a false-send exception; these are expected test evidence, not unresolved failures.

## Coverage

| Area | Evidence |
|---|---|
| Configurable version; preserved text, image, list, button, template, Flow, TT and admin payloads | `test_native_whatsapp.py` iterates representative payloads at v22/v27 using mocked HTTP and checks queue use |
| Rejected payloads, expired credentials, permission failure, rate limit/server/network errors | Same file tests sanitized error categories and terminal versus bounded retry behavior |
| API acceptance versus delivery; diagnostic DB failure; direct erasure exception | Same file plus `native_whatsapp_integration.py`; successful HTTP is never reported as delivered |
| Native limits, stable IDs, menu separation, text aliases, contextual one-message replies and rollback fallback | `test_native_whatsapp.py`, `test_whatsapp_menu.py`, existing routing/state tests |
| Flow publication/configuration gating, malformed response parser, read-only inspection | `test_native_whatsapp.py`; inspection test asserts only GET calls and configured Graph URLs |
| Valid/invalid completion, expiration, replay, wrong owner, unknown token, revoked admin and manual-state invalidation | `native_whatsapp_integration.py` uses real DB rows and locks |
| Concurrent duplicate completion, launch deduplication and callback rollback | Same integration file asserts one state transition, one queued reply and no premature TT write |
| Rejected/undeliverable Flow fallback, deduplication, expiry recheck at actual delivery | Same integration file; stale queued forms and fallback texts do not reach transport |
| Signed status ingress; unknown/mixed webhook batches; status events excluded from commands | Unit tests including valid/invalid signed status payloads; existing webhook security coverage |
| Repeated/out-of-order status, callback before acceptance, failure versus saved result | PostgreSQL tests assert monotonic evidence and unchanged COMPLETE TT / DONE job |
| Privacy erasure/withdrawal; status/session retention and late callback suppression | PostgreSQL tests and updated privacy unit tests |
| Tuesday/event-code/cutoff, 4/6/8 km, runner/walker/BOTH, historical dates, one result/event, corrections, POPIA, progress/history, queue retry/dedupe, Railway endpoint authentication | Full existing suites, including `test_webhook_state_flow.py`, `postgres_integration.py`, admin and monthly integration suites |

## Reproduction

Use a fresh checkout without production `.env` and a disposable local database whose name contains `test` or `integration`. The integration harness drops/recreates its public schema. Never point it at production. The HTTP guard blocks real requests-based transport, including Meta; tests patch above that boundary.

```sh
export ENV=test
export PYTHONPATH=tests/offline_guard
export DATABASE_URL=postgresql://test:test@localhost/test
python -m pip check
python -m compileall -q app scripts tests
WHATSAPP_GRAPH_API_VERSION=v22.0 python -m unittest discover -s tests
WHATSAPP_GRAPH_API_VERSION=v27.0 python -m unittest discover -s tests

# Supply only an isolated database URL in this environment variable.
export DATABASE_URL="$INTEGRATION_DATABASE_URL"
python -m app.migrations upgrade
WHATSAPP_GRAPH_API_VERSION=v27.0 python -m unittest discover -s tests/integration -p '*_integration.py'
python -m app.migrations upgrade
git diff --check
```

Local runs used the existing project `venv/bin/python` from the isolated worktree. The database was newly initialized on loopback port 55441 with synthetic data; no production database dump was loaded. The sandbox required permission to access PostgreSQL shared memory/local sockets. No real Meta request was used in a test, and no template/Flow asset was submitted.

## Outstanding release checks

Actual Meta acceptance, device rendering, subscription/account permissions, publication/health, template approval, supported-version dates, costs and account-model/BSUID implications require authorized administrator/staging checks. Carousel send contracts remain unverified. Those limits are external, not claimed test passes. See `WHATSAPP_META_READINESS.md` and the rollout document.
