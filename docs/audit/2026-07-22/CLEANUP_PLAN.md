# Cleanup Plan — 2026-07-22

Based on `GIT_STATE_BEFORE.md` and `PROJECT_STRUCTURE.md`. **Nothing listed
here has been deleted.** Every item was checked against: not imported, not
referenced by a build script, not referenced by documentation as the current
source of truth, not the only copy of important work.

## Safe to delete (verified unreferenced, low value to keep)

| Item | Evidence it's safe | Notes |
|---|---|---|
| `Dashboard/appicons.py` | `PROJECT_STRUCTURE.md` §9.4 — `app_registry.py` imports `app_icons` (the live module); repo-wide reference search found zero importers of `appicons` (no underscore). Earlier draft left behind. | Small, mechanical delete. Confirm with `git grep -n "import appicons\|from appicons"` returns nothing before removing (already checked by the structure agent). |
| `nova-file-inventory.txt` (348 KB, repo root) | Untracked, gitignored, not referenced by any script or doc found. A one-time inventory dump from an earlier development assistant integration pass. | Safe to delete directly — it's a generated snapshot, not source. |

## Safe to archive outside the repository (not delete — has investigative value)

| Item | Why archive, not delete | Suggested destination |
|---|---|---|
| `NOVA-Integration-Source-20260721-160110.zip` (5.3 MB) | Untracked source snapshot from the 2026-07-21 integration pass. Superseded by the now-staged working-tree content, but may be useful if the staged changes need to be diffed against or rolled back to a known-good pre-merge point. | Move to a local backup folder outside the repo (e.g. `~/NOVA-archives/`), or delete once Ahmed confirms the staged changes are committed and verified. |
| `NOVA-Missing-Source-20260721-161704.zip` (168 KB) | Same reasoning — a supplementary "missing pieces" snapshot from the same integration pass. | Same as above. |
| `NOVA-Email-Calendar-Integration-for-development assistant.zip` (59 KB) | Looks like the source bundle that seeded the `nova_integrations/` work for this development assistant session. Low ongoing value once that work is committed and reviewed, but cheap to keep a copy short-term. | Same as above. |
| `.nova-patch-backup/` (5 timestamped snapshots, 2026-07-21) | Evidence of iterative in-place patch-and-restore cycles on `Dashboard/` during the desktop-integration work. Gitignored, not tracked. Useful for forensic diffing if something in the current `Dashboard/` regressed silently during those patches. | Keep locally until the current staged `Dashboard/` changes are committed and manually smoke-tested per `DEVELOPMENT.md`'s run-ai-agent driver; archive or delete after. |
| `.nova_integration_backup/` (3 timestamped snapshots, 2026-07-21/22) | Same reasoning, covers `agent.py`/`tools/`/`nova_integrations/` patch cycles. | Same as above. |

**Recommendation:** don't delete any of the 3 ZIPs or 2 backup folders in this
pass. They're all gitignored (zero git-history cost) and represent very
recent work — wait until Ahmed has committed and verified the current staged
tree, then clear them in one deliberate pass.

## Duplicate but requires comparison (do not touch without Ahmed's decision)

| Item A | Item B | Comparison needed |
|---|---|---|
| `core/` (task.py, router.py, orchestrator.py) | `nova_core/` (configuration.py, provider_registry.py, cloud_budget.py, router.py) | `core/` is confirmed dead (imported by nothing, repo-wide grep). `DEVELOPMENT.md`'s own rule says "don't delete it; wire it up or ask Ahmed." Per `FEATURE_AUDIT_AI_TOOLS_PERMISSIONS.md`, `nova_core/` is the newer, more complete design and `core/` adds nothing `nova_core/` lacks. **Recommend deleting `core/` once Ahmed confirms `nova_core/` is the intended long-term router** — but this is an explicit ask-first item per the project's own DEVELOPMENT.md rule, not something to auto-delete. |
| `tools/models.py` (`ask_gpt56`/`ask_groq`/`ask_ollama`) | `tools/specialist.py` + `nova_core`/`providers` (`ask_specialist`) | Not a file-duplicate cleanup — both are live source, and per the AI/tools audit, **neither is currently reachable from the voice agent**. This is a routing decision (which system to wire into `agent.py`), not a cleanup decision. See IMPLEMENTATION_ROADMAP.md Stage 1. |
| `requirements.txt` | `requirements-email-calendar.txt` | Confirmed NOT a stale duplicate — `requirements-email-calendar.txt`'s packages are a strict subset already folded into `requirements.txt`, kept intentionally as a standalone installer per its own header comment. **Must keep both.** |
| `.development assistant/skills/` | `.agents/skills/` | `PROJECT_STRUCTURE.md` notes `.agents/skills/` "mirrors run-ai-agent plus nova-code-review, nova-tool-pattern — appears to be a development assistant-side skills copy." Not independently verified byte-for-byte in this pass. **Needs manual review**: if `.agents/skills/` is development assistant's own skill directory (a different tool's config, analogous to `.development assistant/` for this tool), it is NOT a duplicate to clean up — it's a separate assistant's config living alongside this one. Flagging as unknown rather than guessing. |

## Possibly obsolete (needs manual review, not touched)

| Item | Why flagged | Recommendation |
|---|---|---|
| `providers/groq_provider.py` (0 bytes) | Empty file, not imported anywhere (`providers/__init__.py` exports only OpenAI + Ollama). Per the AI/tools audit, this is a genuinely unfinished piece, not dead weight to delete — `nova_core/configuration.py` already defines a full `ProviderName.GROQ` config block that expects this file to eventually exist. | **Keep and finish it, don't delete.** See IMPLEMENTATION_ROADMAP.md. Deleting it would also require removing `ProviderName.GROQ` from `nova_core/configuration.py`, which is an architecture decision for Ahmed. |
| `nova_policy/engine.py`'s `send_to_recycle_bin` / `send_email` / `permanent_delete` / `arbitrary_shell_command` / `install_software` / `disable_security` policies | Per `FEATURE_AUDIT_AI_TOOLS_PERMISSIONS.md` §3.1, these are forward-declared `ActionPolicy` registrations with **no tool implementing any of them** — harmless (they can never fire since nothing calls them), but dead plumbing for features that don't exist yet. | Not a cleanup risk (inert), just noted for awareness. No action needed unless Ahmed wants the policy list trimmed to match reality. |

## Must keep (verified in active use, do not touch)

- All 5 new top-level packages (`nova_core/`, `nova_guardian/`, `nova_integrations/`, `nova_policy/`, `providers/` minus the empty groq file) — real, imported, working code per the feature audits, just not yet committed.
- `Dashboard/` in full (server, feeds, actions, web/, nova-app/, tests/) — the real, live dashboard.
- Root `tests/` and `Dashboard/tests/` — two legitimately separate suites (root covers `nova_integrations`, Dashboard covers the dashboard itself).
- `config/nova_integrations.example.json`, `scripts/start_integrations.ps1` — real config/launch surface for the new integrations work.
- `docs/FGCU_AND_OAUTH_SETUP.md`, `docs/SECURITY_MODEL.md` — current, relevant docs for the in-flight integration work.

## Unknown — manual review required

| Item | Question for Ahmed |
|---|---|
| `.agents/skills/` vs `.development assistant/skills/` | Is `.agents/` development assistant's own tool-config directory (keep, not a duplicate) or a genuinely stale copy from an earlier setup (candidate for removal)? |
| `PROJECT_TASKS.md` (21 KB, root) | Per prior session memory, this was adapted from a Downloads-zip development assistant kit that targets the *old* Flask Nova, not this repo — still a useful reference doc, or ready to retire now that the real integration work described in it has landed? |
