# Git State Before Audit — 2026-07-22

## Repository root
`C:\Users\ahmed\OneDrive\Desktop\AI Agent`

## Branch
`codex-nova-desktop-integration` (up to date with `origin/codex-nova-desktop-integration`)

## Remote
```
origin  https://github.com/BEN-Ammar-Ahmed/NOVA.git (fetch/push)
```

## Recent commits (HEAD -> older)
```
1da0f5a Expand Obsidian vault memory access
3241809 Park dashboard draft outside tracked repo
8e01dbb Add NOVA Build Week tools and desktop skin
626d49d Add Groq specialist model to NOVA
3d43e9a Add Groq integration dependency
821f101 Refactor tools into modules and improve project safety
5cb5b82 Spotify live: exact-match is_app_running, driver loads .env, roadmap update
baa5ea8 Remove website (parked at Ahmed's request; code preserved in fea9a3f)
fea9a3f Phase 5 v1: NOVA web console (Next.js + LiveKit)
9185fa3 Guard Optional returns from spotipy in play_spotify_song (Pylance fix)
```
Full 30-entry log saved to `_git_log_raw.txt` in this folder.

## Working tree state (as found, untouched)

**This is a large, mostly-staged pending change set** — appears to be a bulk merge
of Codex-produced work (email/calendar integration, `nova_guardian`, `nova_core`,
`providers/`, `nova_integrations/`, the Tauri `Dashboard/nova-app` desktop shell,
`Dashboard/` server + tests) that has not yet been committed.

- **Staged (`git add`'ed, ready to commit):** ~145 files — mostly new files
  (`Dashboard/*`, `nova_core/*`, `nova_guardian/*`, `nova_integrations/*`,
  `nova_policy/*`, `providers/*`, `tools/email_calendar.py`, `tools/guardian.py`,
  `tools/permissions.py`, `tools/specialist.py`, root docs) plus modifications to
  `agent.py`, `prompts.py`, `requirements.txt`, `tools/desktop.py`, `tools/vision.py`,
  `README.md`, `ROADMAP.md`, `HACKATHON_LOG.md`, `HACKATHON_SUBMISSION.md`,
  `THIRD_PARTY_SERVICES.md`, `.gitignore`, `.env.example`.
- **Unstaged modifications on top of the staged set:** `Dashboard/integration_feeds.py`,
  `Dashboard/tests/run-python-tests.mjs`, `Dashboard/tests/test_integration_feeds.py`,
  `requirements.txt`.
- Full raw `git status --porcelain=v2` output saved to `_git_status_raw.txt`.

**No changes were discarded, staged, unstaged, committed, or reset by this audit.**
The audit only *reads* this state and writes new files under `docs/audit/`.

## Sensitive-file tracking check

| Item | Tracked by git? | Notes |
|---|---|---|
| `.env` | **No** | Present on disk, correctly untracked. Only `.env.example` is tracked. |
| `.spotify_cache` | No | Present on disk, untracked, covered by `.gitignore`. |
| `*.zip` (3 files in root) | No | `NOVA-Email-Calendar-Integration-for-Claude.zip`, `NOVA-Integration-Source-20260721-160110.zip` (5.3 MB), `NOVA-Missing-Source-20260721-161704.zip` — all untracked, covered by `*.zip` in `.gitignore`. See CLEANUP_PLAN.md. |
| `nova-file-inventory.txt` (348 KB) | No | Untracked, covered by `.gitignore`. |
| `.nova-patch-backup/`, `.nova_integration_backup/` | No | Timestamped backup snapshots from prior Codex integration work, untracked, covered by `.gitignore`. |
| OAuth/token/credential caches | No occurrences found tracked | grep for `token|credential|.cache|oauth|client_secret` in tracked files only matched `docs/FGCU_AND_OAUTH_SETUP.md` (a setup guide, not a credential file). |
| `venv/`, `.venv/`, `node_modules/`, `.pnpm-store/` | No | Present, untracked, ignored. |

**Initial read: no live secrets are currently tracked by git.** Full history-wide
secret scan is done in `SECURITY_REPORT.md` (Phase 7).

## Untracked root-level items worth flagging (see CLEANUP_PLAN.md for disposition)
- 3 root-level ZIP archives (total ~5.6 MB)
- `nova-file-inventory.txt` (348 KB)
- `.nova-patch-backup/`, `.nova_integration_backup/` (5 timestamped backup snapshots total)
- `nova_tools.log`, `logs/`, `screenshots/`, `conversation_logs/` — runtime output, correctly ignored
