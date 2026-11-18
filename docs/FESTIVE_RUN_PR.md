# Add gated festive social-run programme with native WhatsApp Flows

Members can volunteer for the 14 festive dates, save run details for captain approval, and optionally RSVP to published runs. Three dynamic WhatsApp Flows provide host registration, RSVP and management, with paginated lists/reply buttons and an explicit numbered fallback. Draft venues stay private; public changes require renewed approval. No TT results, cutoff rules or league data are changed.

The additive PostgreSQL migration enforces host exclusivity and one RSVP per member/run. Durable sessions reject stale submissions and replay saved responses on retries. Existing admin authorisation and job infrastructure handle captain actions and opt-in template notifications. UAT and the default-off feature flag suppress delivery; ambiguous provider attempts require manual reconciliation to prevent automatic duplicate sends.

Validation on Python 3.13.5: 429 unit tests passed, 2 physical-device acceptance tests skipped; 75 PostgreSQL integration tests passed (34 festive, 41 existing). New-source Ruff lint/format checks, full-tree critical-error lint, compileall, dependency consistency and diff whitespace checks passed. Migrations were exercised repeatedly on disposable PostgreSQL 17.8. The full four-role UAT was simulated with fake transports; no WhatsApp messages were sent.

**Keep this PR draft.** Read-only Meta audit reports business encryption signature MISMATCH. Festive Flow IDs, key mount and reminder template remain unconfigured. Meta Flow validation/publication, endpoint health, template approval and physical Android/iOS UAT are outstanding release gates. No production deployment or activation is authorised by this PR.

See `docs/FESTIVE_RUN_ADVENTURES.md` for the capability matrix and architecture, `docs/FESTIVE_RUN_UAT.md` for executed evidence and acceptance gates, and `docs/FESTIVE_RUN_RELEASE.md` for exact configuration, enablement and immediate flag-off rollback.
