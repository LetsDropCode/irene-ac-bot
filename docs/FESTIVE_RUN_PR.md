# Add gated festive social-run programme with native WhatsApp Flows

Members can volunteer for the 14 festive dates, save run details for captain approval, and optionally RSVP to published runs. Three dynamic WhatsApp Flows provide host registration, RSVP and management, with paginated lists/reply buttons and an explicit numbered fallback. Draft venues stay private; public changes require renewed approval. No TT results, cutoff rules or league data are changed.

The additive PostgreSQL migration enforces host exclusivity and one RSVP per member/run. Durable sessions reject stale submissions and replay saved responses on retries. Existing admin authorisation and job infrastructure handle captain actions and opt-in template notifications. UAT and the default-off feature flag suppress delivery; ambiguous provider attempts require manual reconciliation to prevent automatic duplicate sends.

Validation on Python 3.13.5: 439 unit tests passed, 2 physical-device gates skipped; 77 local PostgreSQL integration tests passed (76-suite plus new encrypted/no-JWT test). The iPhone host, details resubmission, RSVP, preference update and cancellation journeys passed against the isolated test database. Android hardware remains unavailable. Critical lint and whitespace checks passed.

The endpoint accepts Meta's optional additional JWT being absent while retaining mandatory HTTP HMAC, authenticated encryption and durable member-bound sessions. Present invalid JWTs and invalid sessions are rejected. Form validation errors preserve entered details and submit intent across reopening. Production can load its separate key from a secret base64 PEM value.

Production release is now authorised by the account owner, but activation remains gated. Three production drafts passed Meta JSON validation. The utility reminder template is pending review. A production backup has been retained inside Railway; no member data was exported. Keep the feature disabled until encryption, endpoint health, published Flow status and template approval are verified. No production messages or billing changes have occurred.

See `docs/FESTIVE_RUN_ADVENTURES.md` for capabilities, `docs/FESTIVE_RUN_UAT.md` for device limitations, and `docs/FESTIVE_RUN_RELEASE.md` for the release/rollback record.
