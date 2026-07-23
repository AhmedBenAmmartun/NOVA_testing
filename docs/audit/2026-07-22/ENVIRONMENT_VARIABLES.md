# Environment Variables — 2026-07-22

Method: variable **names only** were read from the real `.env` (never values —
`.env` contents were not printed anywhere in this audit). Code was grepped for
every `os.environ`/`os.getenv` read site to determine what's actually
consumed. Cross-referenced against `.env.example` and
`FEATURE_AUDIT_AI_TOOLS_PERMISSIONS.md`.

Legend for "Default behavior when missing": what the code does if the var is
absent — crash, silent skip, graceful fallback message, etc.

## Core / LiveKit
| Variable | Purpose | Required? | Used by | In `.env`? | In `.env.example`? | Default when missing |
|---|---|---|---|---|---|---|
| `LIVEKIT_URL` | LiveKit Cloud project URL | Required | `agent.py` (via LiveKit SDK) | Yes | Yes | Agent fails to connect |
| `LIVEKIT_API_KEY` | LiveKit auth | Required | `agent.py` | Yes | Yes | Agent fails to connect |
| `LIVEKIT_API_SECRET` | LiveKit auth | Required | `agent.py` | Yes | Yes | Agent fails to connect |

## Google / Gemini
| Variable | Purpose | Required? | Used by | In `.env`? | In `.env.example`? | Default when missing |
|---|---|---|---|---|---|---|
| `GOOGLE_API_KEY` | Gemini Realtime auth | Required | `google.realtime.RealtimeModel` (implicit SDK read) | Yes | Yes | Session construction fails |
| `NOVA_REALTIME_MODEL` | Intended override for Gemini model name | Optional | **Not read** — `agent.py` hardcodes the model | Yes | Yes | **Dead var** — documented known issue, Ahmed's tuning is intentionally hardcoded (DEVELOPMENT.md) |
| `NOVA_VOICE` | Intended override for TTS voice | Optional | **Not read** — hardcoded `"Puck"` | Yes | Yes | Dead var, same reason |
| `NOVA_TEMPERATURE` | Intended override for LLM temperature | Optional | **Not read** — hardcoded `0.5` | Yes | Yes | Dead var, same reason |

## OpenAI specialist provider
| Variable | Purpose | Required? | Used by | In `.env`? | In `.env.example`? | Default when missing |
|---|---|---|---|---|---|---|
| `OPENAI_API_KEY` | `ask_gpt56`/`OpenAIProvider` auth | Optional (opt-in tool) | `tools/models.py`, `providers/openai_provider.py` | Yes | Yes | Graceful "not configured" message, no crash |
| `NOVA_ENABLE_OPENAI` | Enables OpenAI in the `nova_core` router | Optional | `nova_core/configuration.py` | Not confirmed in `.env` | Yes | Router treats provider as disabled |
| `NOVA_OPENAI_MODEL` | Model override for `nova_core` router's OpenAI provider | Optional | `nova_core/configuration.py` | Not confirmed | Yes | Falls back to router default |

## Groq
| Variable | Purpose | Required? | Used by | In `.env`? | In `.env.example`? | Default when missing |
|---|---|---|---|---|---|---|
| `GROQ_API_KEY` | `ask_groq` auth | Optional | `tools/models.py` | Yes | Yes | Graceful "not configured" message |
| `GROQ_MODEL` | Model override | Optional | `tools/models.py` | Yes | Yes | Falls back to `llama-3.3-70b-versatile` |
| `NOVA_ENABLE_GROQ` | Enables Groq in `nova_core` router | Optional | `nova_core/configuration.py` | Not confirmed | Yes | **Moot** — see note below |

> **Note:** even with `NOVA_ENABLE_GROQ=true`, `providers/groq_provider.py` is
> an empty file (0 bytes) — the `nova_core` router has no real Groq
> implementation to enable. Only `tools/models.py`'s `ask_groq` works, and per
> `FEATURE_AUDIT_AI_TOOLS_PERMISSIONS.md` that tool is currently **not
> registered in `agent.py`'s live tool list**, so it's unreachable from voice
> regardless of keys present. See ISSUES.md / IMPLEMENTATION_ROADMAP.md.

## Ollama (local) — naming is inconsistent across 3 code paths
| Variable | Purpose | Required? | Used by | In `.env`? | In `.env.example`? | Default when missing |
|---|---|---|---|---|---|---|
| `OLLAMA_MODEL` (bare) | Model name | Optional | `tools/models.py:221`, `nova_core/configuration.py:588` | Yes (real `.env` uses this bare name) | **No** | Falls back to `mistral:latest` |
| `OLLAMA_BASE_URL` (bare) | Ollama server URL | Optional | `tools/models.py:88-89`, `nova_core/configuration.py:597` | Not confirmed | **No** | Falls back to `http://localhost:11434/v1` |
| `NOVA_OLLAMA_MODEL` | Same intent, different name | Optional | **Not read anywhere in tracked code** (grep found zero read sites) | Not confirmed | Yes | **Dead var in `.env.example`** |
| `NOVA_OLLAMA_BASE_URL` | Same intent, different name | Optional | `nova_guardian/ambient_vision.py:111` only | Not confirmed | No | Guardian falls back to its own default if unset |
| `NOVA_ENABLE_OLLAMA` | Enables Ollama in `nova_core` router | Optional | `nova_core/configuration.py` | Not confirmed | Yes | Router treats provider as disabled |

> **Finding:** three different naming conventions for the same concept
> (`OLLAMA_MODEL` vs `NOVA_OLLAMA_MODEL` vs the guardian's separate
> `NOVA_OLLAMA_BASE_URL`) exist simultaneously, none fully reconciled.
> `.env.example` currently documents the `NOVA_`-prefixed names, but the two
> code paths that actually run today (`tools/models.py`'s live `ask_ollama`
> — though currently unreachable per the tools audit — and
> `nova_core/configuration.py`) read the **bare** names. This is a real,
> low-risk-to-fix naming inconsistency; see ISSUES.md. Not fixed here since
> renaming touches multiple files and should be a deliberate decision, not a
> silent hygiene change.

## Provider routing (nova_core)
| Variable | Purpose | Required? | Used by | In `.env.example`? |
|---|---|---|---|---|
| `NOVA_PROFILE` | `local`/`cloud`/`hybrid` routing profile | Optional | `nova_core/configuration.py` | Yes |
| `NOVA_FALLBACK_ENABLED` | Allow provider fallback on failure | Optional | `nova_core/configuration.py` | Yes |

## Cloud-usage protection
| Variable | Purpose | Required? | Used by | In `.env.example`? |
|---|---|---|---|---|
| `NOVA_CLOUD_BUDGET_ENABLED` | Enable daily cloud-call budget | Optional | `nova_core/cloud_budget.py` | Yes |
| `NOVA_CLOUD_DAILY_REQUEST_LIMIT` | Daily request cap | Optional | `nova_core/cloud_budget.py` | Yes |
| `NOVA_CLOUD_USAGE_FILE` | Override path for usage-tracking file | Optional | `nova_core/cloud_budget.py:83`, `Dashboard/feeds.py:419` | **No — missing from `.env.example`, added below** |

## NOVA Guardian
| Variable | Purpose | Required? | Used by | In `.env.example`? |
|---|---|---|---|---|
| `NOVA_GUARDIAN_ENABLED` | Master on/off, default False | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_SECURITY_MONITOR_ENABLED` | Process/firewall/Defender checks | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_WINDOW_MONITOR_ENABLED` | Window-title tracking | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_GUARDIAN_AUTO_RESPONSE` | Auto-react to threats (default False, never auto-kills/deletes) | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_SECURITY_SCAN_INTERVAL_SECONDS` | Scan cadence | Optional | `nova_guardian/config.py` | Yes |

## Local ambient vision
| Variable | Purpose | Required? | Used by | In `.env.example`? |
|---|---|---|---|---|
| `NOVA_VISION_MODE` | `off`/`on_demand`/`ambient`/`temporary_session`, default off | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_LOCAL_VISION_ONLY` | Hard block on ever sending frames to cloud, default True | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_PAUSE_ON_SENSITIVE_WINDOWS` | Skip capture on password/login/payment windows | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_LOCAL_VISION_MODEL` | Ollama vision model name | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_LOCAL_VISION_TIMEOUT_SECONDS`, `NOVA_LOCAL_VISION_MAX_DIMENSION`, `NOVA_LOCAL_VISION_MAX_OUTPUT_TOKENS`, `NOVA_LOCAL_VISION_CONTEXT_SIZE`, `NOVA_LOCAL_VISION_KEEP_ALIVE` | Local vision tuning | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_VISION_CAPTURE_INTERVAL_SECONDS`, `NOVA_VISION_CHANGE_THRESHOLD` | Ambient-mode cadence | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_MAX_VISION_SESSION_MINUTES` | Session auto-expiry (also caps `start_guardian_vision`) | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_STORE_VISION_SCREENSHOTS`, `NOVA_SCREENSHOT_RETENTION_SECONDS` | Persistence (default: never store) | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_VISION_EXCLUDED_PROCESSES` | Password-manager process exclusion list | Optional | `nova_guardian/config.py` | Yes |
| `NOVA_SENSITIVE_WINDOW_KEYWORDS` | Window-title keywords that pause capture | Optional | `nova_guardian/config.py` | Yes |

## Spotify
| Variable | Purpose | Required? | Used by | In `.env.example`? |
|---|---|---|---|---|
| `SPOTIFY_CLIENT_ID` | Spotify OAuth | Optional | `tools/media.py` | Yes |
| `SPOTIFY_CLIENT_SECRET` | Spotify OAuth | Optional | `tools/media.py` | Yes |
| `SPOTIFY_REDIRECT_URI` | OAuth callback | Optional | `tools/media.py` | Yes |

## Obsidian — found in real `.env`, missing from `.env.example`
| Variable | Purpose | Required? | Used by | In `.env.example`? |
|---|---|---|---|---|
| `OBSIDIAN_VAULT_PATH` | Path to Obsidian vault | Required for Obsidian tools | `tools/obsidian.py` | **No — added below** |
| `OBSIDIAN_VAULT_NAME` | Display name | Not read by any code (per DEVELOPMENT.md's existing known-issue note) | — | **No — added below, marked dead** |

## Dashboard / startup — found in real `.env` or code, missing from `.env.example`
| Variable | Purpose | Required? | Used by | In `.env.example`? |
|---|---|---|---|---|
| `NOVA_DASHBOARD_PORT` | Dashboard server port override | Optional | `Dashboard/server.py:347` | **No — added below** |
| `NOVA_CITY` | Weather lookup city override | Optional | `Dashboard/feeds.py:233` (blank = IP-geolocated) | **No — added below** |
| `NOVA_BRIDGE_DIR` | Override for the dashboard↔agent bridge directory | Optional | `nova_bridge.py:46` | **No — added below** |
| `NOVA_INTEGRATIONS_CONFIG` | Path to `nova_integrations` JSON config (see `config/nova_integrations.example.json`) | Optional | `nova_integrations/config.py:76`, `cli.py:72` | **No — added below** |

## Present in real `.env`, not read by any tracked code (orphaned)
These names exist in Ahmed's real `.env` but a full-repo grep found **zero**
read sites in tracked `.py`/`.ps1` files. They are not necessarily harmful,
but they don't currently do anything — likely leftovers from a planned or
removed feature (wake-word listener, startup-mode selection):
- `NOVA_WAKE_WORD`
- `NOVA_WAKE_WORD_ENABLED`
- `NOVA_START_MODE`
- `NOVA_START_WITH_WINDOWS`
- `NOVA_ACTIVATE_VOICE_ON_STARTUP`

`nova_wakeword.py` and `nova_startup.py` exist as real modules (see
PROJECT_STRUCTURE.md for what they actually implement) but apparently read
their config a different way (constants, a config object, or CLI flags)
rather than these particular env-var names — worth a quick manual check by
Ahmed if he expects these `.env` values to have an effect.

## Email / Calendar (Microsoft Graph / Google Workspace)
Configuration for this feature is **JSON-based**, not primarily env-var
based — see `config/nova_integrations.example.json` (tracked, placeholder
values only) and `NOVA_INTEGRATIONS_CONFIG` above, which points to the real
config file (default resolves under `%LOCALAPPDATA%\NOVA\integrations\`, not
committed). OAuth client secrets are described by the tools-audit agent as
keyring-backed (`nova_integrations/secrets.py`) rather than plaintext env
vars — recommend Ahmed keep it that way rather than adding
`GOOGLE_CLIENT_SECRET`/`MS_CLIENT_SECRET`-style env vars later.

---

## `.env.example` changes made in this audit
Appended a new section (placeholders only, no real values, existing content
untouched) covering: `OBSIDIAN_VAULT_PATH`, `NOVA_DASHBOARD_PORT`,
`NOVA_CITY`, `NOVA_BRIDGE_DIR`, `NOVA_INTEGRATIONS_CONFIG`, and the bare
`OLLAMA_MODEL`/`OLLAMA_BASE_URL` names (documented alongside the existing
`NOVA_OLLAMA_*` names with a note about the inconsistency, rather than
silently renaming anything).
