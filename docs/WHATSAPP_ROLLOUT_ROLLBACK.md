# Rollout and rollback

Disposition: **READY_FOR_REVIEW**. No production deployment, merge, account mutation, configuration change or message delivery is authorized by the offline test results.

## Review and staging

1. Review this branch against main, the additive migration and the offline evidence in `WHATSAPP_UX_TEST_MATRIX.md`. Verify the existing calendar asset is unchanged. Review the current remote main again if other work lands before merging.
2. Obtain authorization for staging configuration and live compatibility checks. Use a separate database, account/test number and consenting synthetic recipients. Do not load production member data.
3. Set `ENV` and the existing security configuration, leave new flags false, and keep `WHATSAPP_GRAPH_API_VERSION=v22.0`. Run `python -m app.migrations upgrade` before starting the new release. The migration creates two auxiliary tables/indexes; it neither rewrites deployed migrations nor modifies historical TT rows.
4. Confirm readiness and the scheduled `/jobs/run` worker. Check existing TT run/walk/BOTH, 4/6/8 km, event-code/cutoff rules, historical missed entry, privacy, deduplication and approved-template schedules.
5. Subject to the Meta readiness checklist, trial v27.0 with all feature flags still off. Exercise text/image/list/button/template/Flow payloads where eligible, including scheduled messages and error cases. Record real Meta acceptance and callback evidence separately from mocked tests. Account-model and phone/BSUID restrictions are explicit go/no-go checks.
6. Enable native UX for the staging deployment, then delivery tracking. Check a member versus an administrator, contextual navigation and long-summary fallback. Do not infer delivery from a DONE queue row: DONE means the send job completed.
7. Enable Flows only with an operator-verified published ID and publication flag. Test abandoned, expired, replayed, cross-member and revoked-admin completion; typed-date fallback; and final confirmation before result creation. Do not enable carousel campaigns; the flag is reserved.
8. Production rollout, migration application, configuration changes, deployment and merges each remain subject to explicit authorization. These instructions prepare that action; they do not perform it.

## Rollback

- Switch `WHATSAPP_NATIVE_UX_ENABLED=false` to restore the original menu/confirmation presentation. Existing buttons and lists continue working. Stable navigation aliases remain resolvable for old menus.
- Switch `WHATSAPP_FLOWS_ENABLED=false` to stop new launches and reject completions safely. Users continue by typed date or restart. Clear the publication attestation if readiness is lost. Expired sessions never become valid merely because a flag is re-enabled.
- Switch `WHATSAPP_DELIVERY_STATUS_ENABLED=false` to stop recording new diagnostics; normal queue processing continues. Keep `/jobs/run` scheduled for retention cleanup. No diagnostic failure can undo a saved TT result.
- Revert the Graph version to the previously verified version only while Meta still supports it. Confirm the current lifecycle before use; the exact expiry was not verified here. Both configuration scripts obey the same setting.
- If reverting the application commit, leave the new auxiliary tables and migration record in place. Old code ignores them. No destructive down migration is needed. Arrange equivalent diagnostic cleanup during a prolonged old-code rollback because that code does not run the new retention routine.
- Before restarting queued native work after a full code rollback, inspect pending Flow launch/completion jobs in the authorized environment. Do not send stale forms. Stop the worker while the operator cancels only those reviewed jobs; never bulk-reset TT results, attendance, or unrelated jobs. The next inbound MENU/date remains the recovery path.

## Operational interpretation

Permanent credential/permission/payload errors go to FAILED immediately. Fix the cause before using the existing manual retry command. Transient errors remain bounded; do not reset failed jobs continuously. Signed delivery failures are diagnostics and do not schedule automatic resends.

A worker crash after Meta acceptance still has the inherited at-least-once send risk. On an uncertain delivery, inspect the callback evidence before retrying manually. If status recording fails after acceptance, wait for the signed callback to repair the mapping rather than resending.
