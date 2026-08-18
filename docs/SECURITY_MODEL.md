# NOVA Email/Calendar Security Model

- OAuth 2.0 delegated user authorization only.
- No Gmail, Outlook, FGCU, school, or work password is requested or stored.
- No app-only/daemon permission and no tenant-wide mailbox access.
- Initial permissions are read-only.
- OAuth caches and sync cursors are stored through the operating-system keyring (Windows Credential Manager on Windows). There is no plaintext fallback.
- SQLite stores normalized metadata only. Complete email bodies and attachments are not cached.
- Initial mail synchronization is a silent baseline, so historical messages do not produce a notification storm.
- Notifications are deduplicated across restarts by provider + account + stable message ID.
- Account content modes:
  - `metadata_only`: cloud voice receives counts, times, labels, and redacted records.
  - `local_private`: full content is reserved for NOVA's offline/local pipeline.
  - `cloud_allowed`: selected full content can reach cloud voice only after a one-time permission-engine approval.
- Sending, replying, forwarding, deleting, archiving, marking read, accepting invitations, and changing calendar events are not implemented.
- Provider links are restricted to approved HTTPS Outlook or Gmail domains.
- Logs and audit records never include OAuth tokens, email bodies, attachments, calendar descriptions, attendee lists, or raw provider error responses.
- Provider-controlled sender names, subjects, event titles, locations, and message bodies are treated as untrusted data. Tool output labels them accordingly; bodies are bounded and attachments are never fetched.
- External dashboard/Valo projects are outside NOVA. A safe local event stream may be consumed through a future explicit interface.
