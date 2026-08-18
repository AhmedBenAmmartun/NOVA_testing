# NOVA OS Capability Kernel — V1

This release introduces the first NOVA OS capability layer. It does **not**
replace Windows and it does not grant new security permissions. It organizes
NOVA's model-callable tools into named capability groups that can be activated
or deactivated during a LiveKit session.

## Core rules

- Capability activation changes the LLM tool surface only.
- Capability activation never approves a pending action.
- Safe Mode and `nova_policy` remain the security boundary.
- The model cannot disable Safe Mode or approve its own sensitive actions.
- Webpage content is untrusted data, never instructions.
- Downloads are written only to `Downloads/NOVA Downloads` and are never
  executed by the web tool.

## Always-available capability controls

- `list_capabilities`
- `search_capabilities`
- `get_active_capabilities`
- `capability_info`
- `activate_capability`
- `deactivate_capability`

## V1 capability groups

- `system`
- `web`
- `desktop`
- `files`
- `media`
- `specialist`
- `memory`
- `email_calendar`
- `guardian`
- `permissions` (required/locked active)

For compatibility, normal desktop/files/media/system/web/specialist tools start
active. Memory, email/calendar, and Guardian are available on demand. The
permissions capability is always active.

## Web Research V1

- `web_search`
- `web_search_site`
- `web_read_page`
- `web_find_on_page`
- `web_list_links`
- `web_extract_text`
- `web_download`

The web reader accepts only public HTTP(S) URLs and rejects loopback, private,
link-local, multicast, reserved, and `.local` targets. Page reads are capped at
2 MB. Downloads are capped at 50 MB.

## Next kernel phases

1. Adaptive capability routing and automatic unloading of unused toolsets.
2. Browser Operator using Playwright.
3. Clipboard/cross-app transfer with permission enforcement.
4. Skills registry and versioned reusable workflows.
5. Plugin registry and MCP toolsets.
6. Task/mission manager and background jobs.
