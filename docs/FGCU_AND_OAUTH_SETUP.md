# FGCU, Gmail, and Microsoft OAuth Setup

## What is confirmed about FGCU

FGCU provides student and employee email through Microsoft Outlook/Microsoft 365. FGCU's public ITS pages direct students and staff to Eagle Mail/webmail and the Outlook app. That means NOVA's technical integration path is Microsoft Graph with delegated user authorization, not Gmail IMAP and not an FGCU password stored in NOVA.

FGCU's public pages do not publish the tenant's third-party application consent policy. Therefore, NOVA cannot guarantee in advance that `Mail.Read` and `Calendars.Read` will be approved for a custom desktop app. Microsoft tenants can block user consent or require administrator approval. The included connector detects that result and records `admin_approval_required`; it does not bypass it.

FGCU ITS Help Desk public contact information: helpdesk@fgcu.edu and 239-590-1188.

## Microsoft app registration

1. Create one Microsoft Entra app registration for NOVA.
2. Supported account types: choose accounts in any organizational directory **and personal Microsoft accounts** so the same public desktop client can connect personal Outlook plus FGCU school/work accounts.
3. Add the **Mobile and desktop applications** platform.
4. Enable the public client/native desktop flow. Do not create or embed a client secret.
5. Add delegated Microsoft Graph permissions only:
   - `User.Read`
   - `Mail.Read`
   - `Calendars.Read`
6. Put only the public application/client ID in NOVA's local integrations config.
7. Connect accounts one at a time. For FGCU, sign in on Microsoft's real page and complete FGCU MFA.
8. If Microsoft says admin approval is required, contact FGCU ITS. Do not enter an FGCU password into NOVA or attempt to bypass the tenant policy.

Official references:

- Microsoft delegated permissions and consent: https://learn.microsoft.com/en-us/entra/identity-platform/permissions-consent-overview
- Microsoft public desktop clients: https://learn.microsoft.com/en-us/entra/identity-platform/msal-client-applications
- Microsoft Graph permission reference: https://learn.microsoft.com/en-us/graph/permissions-reference
- Microsoft message delta: https://learn.microsoft.com/en-us/graph/delta-query-messages
- Microsoft event delta: https://learn.microsoft.com/en-us/graph/delta-query-events
- FGCU student ITS resources: https://www.fgcu.edu/its/students/
- FGCU email portal: https://www.fgcu.edu/email/

## Google setup

1. Create or select a Google Cloud project for NOVA.
2. Enable Gmail API and Google Calendar API.
3. Configure the OAuth consent screen for your own account/testing status as appropriate.
4. Create an OAuth client of type **Desktop app**.
5. Download the client JSON to `%LOCALAPPDATA%\NOVA\integrations\google_oauth_desktop_client.json`.
6. Keep that JSON local and out of Git. The desktop-client value is not used as a server secret, but it should still remain part of local configuration.
7. NOVA requests `gmail.metadata` in metadata-only mode or `gmail.readonly` when on-demand body access is enabled. Calendar uses `calendar.events.readonly` and `calendar.calendarlist.readonly`. If a Google account is upgraded from `metadata_only` later, reconnect that account once so Google can grant the broader read-only mail scope.

Official references:

- Google native-app OAuth: https://developers.google.com/identity/protocols/oauth2/native-app
- Gmail scopes: https://developers.google.com/workspace/gmail/api/auth/scopes
- Google Calendar scopes: https://developers.google.com/workspace/calendar/api/auth
- Google Calendar incremental sync: https://developers.google.com/workspace/calendar/api/guides/sync
