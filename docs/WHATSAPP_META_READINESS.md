# Meta readiness and administrator actions

As of 18 November 2026, **account readiness is UNKNOWN**. This implementation did not query live Meta credentials or account health. The historical 27 October record of calendar JSON validation, publication error 139000 and verification issue 141010 is not evidence of today's account status. No Flow ID has been activated by this work.

## Configuration

| Variable | Default | Release requirement |
|---|---|---|
| `WHATSAPP_GRAPH_API_VERSION` | `v22.0` | Set `v27.0` only for an authorized compatibility trial; retain rollback while the previous version is supported |
| `WHATSAPP_NATIVE_UX_ENABLED` | false | Enables the new member menu and contextual short confirmations |
| `WHATSAPP_FLOWS_ENABLED` | false | Enables secured static Flow launches/completions |
| `WHATSAPP_ADMIN_DATE_FLOW_ID` | empty | Operator-verified published calendar owned by the intended account |
| `WHATSAPP_ADMIN_DATE_FLOW_PUBLISHED` | false | Explicit publication attestation; it is not an automated Meta health check |
| `WHATSAPP_DELIVERY_STATUS_ENABLED` | false | Enables acceptance recording and signed status processing |
| `WHATSAPP_RICH_CAROUSELS_ENABLED` | false | Reserved; no adapter exists and enabling it has no effect |
| `WHATSAPP_TEMPLATE_LANGUAGE` | existing default `en_US` | Exact approved language; monthly setup script retains its existing `en_GB` default, so configure explicitly |
| Existing `WHATSAPP_*_TEMPLATE_NAME` variables | unchanged | Exact approved reminder/milestone/recap names; never substitute arbitrary text |

Existing token, phone ID, app secret, verify token, job-runner token and administrator allowlist remain required. Never copy their values into a PR, documentation, shell command arguments or diagnostic output. Scripts read protected environment configuration.

## Administrator checklist

1. In Meta Business Suite verify the business status and permissions of the intended system user. Check the token's messaging/management permissions, intended WABA/phone ownership, subscription to `messages`, number quality and messaging limits. App-secret signature verification remains mandatory.
2. Review the full Graph version changelog and supported-version expiry dates. Confirm account-model requirements: this bot currently assumes phone-based members and one messaging account for its phone/token. BSUID-only identity is not implemented. Do not broadly roll v27 out without resolving any applicable changes.
3. Inspect the existing calendar in WhatsApp Manager. Check status, validation errors and health, including verification/quality restrictions. The script can inspect without creating/uploading/publishing:

   ```sh
   python scripts/configure_admin_date_flow.py --waba-id "$META_WABA_ID" --inspect
   ```

4. After authorization for Meta asset changes, run the script without `--inspect` to create or validate the existing calendar asset. It reuses the named asset and refuses ambiguous duplicates. This is an external mutation, not an offline check. Publication requires a separate explicit authorization and `--publish`; do not bypass verification restrictions. Verify PUBLISHED and healthy status in the intended account afterward.
5. Only then configure the Flow ID, publication attestation and Flow feature flag in an authorized environment. Test the actual client/device behavior and typed-date recovery. Validated JSON alone is insufficient.
6. For proactive templates, inspect exact name/language, approval/category, parameters, buttons and intended opt-in. Submitting/updating templates needs separate authorization. Template builders cannot discover approval at runtime. No marketing messages or carousel campaigns were sent.
7. In a separately authorized staging trial use synthetic consenting recipients and a staging DB. Verify accepted/sent/delivered/read/failed lifecycle, revoked token errors, old/new client fallback and the service-window boundary. A successful HTTP response alone is not delivery evidence.

Business verification is a Flow publication/readiness gate described in the [Flows changelog](https://developers.facebook.com/documentation/business-messaging/whatsapp/flows/changelog); actual restrictions must be checked for this account. Ordinary session buttons/lists do not require individual template approval. Proactive template approval, Flow publication and production configuration are separate controls.

## Unresolved external checks

Detailed carousel send pages, current price tables, some Flow protocol pages and the Graph supported-version lifecycle page were unavailable through the documentation fetcher. The audit names the reachable evidence and the missing contracts. Read the current official pages while authenticated and record a sanitized compatibility result before activating these capabilities. No account block is asserted to be resolved, nor is the historical block asserted to still apply.
