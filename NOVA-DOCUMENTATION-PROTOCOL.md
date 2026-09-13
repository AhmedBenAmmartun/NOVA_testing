# NOVA Documentation & Learning Protocol

**Status:** Mandatory project operating rule<br>
**Applies to:** All meaningful NOVA development, debugging, architecture, testing, and planning work<br>
**Purpose:** Keep NOVA's code, Git history, repository documentation, and NOVA Vault knowledge synchronized so future work starts from verified project memory instead of stale chat history.

---

## 1. Mandatory Rule

Before making a significant technical recommendation or modification to NOVA:

1. Read `CHATGPT-OPERATING-PROTOCOL.md` if present.
2. Read this file: `NOVA-DOCUMENTATION-PROTOCOL.md`.
3. Inspect the newest source of truth in this order:
   - current repository/files;
   - Git state;
   - tests/logs/runtime evidence;
   - current conversation;
   - project/Vault documentation;
   - older chats.
4. Read:
   - `NOVA - Current Status`
   - `NOVA - Project Hub`
   - the detailed NOVA Vault note for the system or milestone being changed;
   - any linked OPEN issue notes;
   - any linked architecture decision records (ADRs) that constrain the work.
5. Do not assume older documentation still describes the current implementation.

If repository/runtime evidence conflicts with a Vault note, the newer verified implementation wins and the note must be corrected.

---

## 2. Required NOVA Vault References

Primary Vault navigation:

- `NOVA/00 - HUB/NOVA - Project Hub.md`
- `NOVA/00 - HUB/NOVA - Current Status.md`
- `NOVA/00 - HUB/NOVA - Roadmap.md`

Detailed areas:

- `NOVA/10 - SYSTEMS/`
- `NOVA/20 - ACTIVE WORK/`
- `NOVA/30 - ISSUES/`
- `NOVA/40 - DECISIONS/`
- `NOVA/50 - MILESTONES/`
- `NOVA/60 - HISTORY/`

The Project Hub is a map, not a detailed engineering log.

Detailed knowledge belongs in the linked system, active-work, issue, decision, milestone, or history note.

---

## 3. Before Work Starts

For meaningful NOVA work, establish and record:

### VERIFIED STARTING STATE

- repository/worktree;
- branch;
- HEAD commit;
- Git status;
- relevant current implementation;
- relevant tests/runtime behavior;
- current milestone;
- open issues affecting the work.

Classify information as needed:

- `VERIFIED CURRENT`
- `PLANNED`
- `NEEDS VERIFICATION`
- `BLOCKED`
- `HISTORICAL`
- `SUPERSEDED`
- `RESOLVED`

Never silently convert PLANNED work into VERIFIED CURRENT.

---

## 4. During Work

The active detailed note should be treated as a living engineering notebook.

Record meaningful developments such as:

### Goal
What are we trying to accomplish?

### Why
Why does NOVA need this?

### Architecture
What design are we using and why?

### Work Completed
What was actually implemented?

### Issues Encountered
For every meaningful issue, record:
- symptom;
- impact;
- investigation;
- root cause;
- attempts that failed or were rejected;
- final resolution;
- verification;
- remaining risk.

If the issue is significant or reusable, create/update a separate:

`ISSUE-XXX - <name>.md`

and link it from the active-work/system note.

### Decisions
If the work creates an architectural rule that should survive the current implementation, create/update an ADR:

`ADR-XXX - <decision>.md`

Record:
- context;
- decision;
- reason;
- alternatives considered;
- consequences.

### Blockers
Record what is preventing progress and what evidence would unblock it.

---

## 5. Learning From Failures

NOVA documentation must preserve lessons, not just final success.

When an approach fails:

1. Do not erase it from history.
2. Record what was tried.
3. Record why it failed.
4. Record how the failure was detected.
5. Record the root cause if known.
6. Record the better approach.
7. Link the issue/decision that resulted.

Future work must consult relevant resolved issues before repeating a previously rejected approach.

A resolved issue remains useful project knowledge.

---

## 6. After Work

A meaningful NOVA milestone is not documented until all applicable steps are complete:

1. Implementation completed.
2. Tests/verification completed.
3. Git status inspected.
4. Repository docs updated.
5. Relevant NOVA Vault detailed note updated.
6. OPEN/RESOLVED issue notes updated.
7. ADRs updated if an architectural decision changed.
8. `NOVA - Current Status` updated if current state changed.
9. `NOVA - Project Hub` updated only when the high-level map/status changed.
10. `NOVA - Roadmap` updated if priorities changed.
11. Milestone/Git checkpoint recorded when a checkpoint is created.
12. Superseded architecture preserved and linked to its replacement.

---

## 7. Definition of Documentation Done

Before calling work finished, verify:

- Does the detailed note describe what actually exists?
- Are test results factual and current?
- Is the correct Git commit/branch recorded?
- Are important problems preserved?
- Are resolved issues marked RESOLVED rather than deleted?
- Are open blockers still visible?
- Are architectural decisions documented?
- Are deferred items explicitly labeled PLANNED/DEFERRED?
- Is historical information distinguished from current truth?
- Could another engineer understand why the current design exists without reading old chats?

If not, documentation is not done.

---

## 8. Source-of-Truth Conflict Rule

When sources disagree, prefer:

1. verified current repository/files;
2. current Git state;
3. current tests/logs/runtime behavior;
4. current conversation;
5. current NOVA Vault/project documentation;
6. older summaries/chats.

Then update stale documentation.

Never change working code merely to make it match stale documentation.

---

## 9. Security Rules

Never place in project documentation:

- API keys;
- passwords;
- tokens;
- `.env` contents;
- authentication cookies;
- private credentials;
- private recordings;
- unnecessary private transcripts;
- secret local paths containing sensitive data.

Do not paste huge raw logs into the Vault.

Store concise diagnostic facts and safe references instead.

---

## 10. One Unified NOVA Rule

NOVA is one unified agent.

Documentation must not introduce separate user-facing "modes" for:

- Class Intelligence;
- Vision;
- Development;
- Memory;
- Research;
- Desktop;
- or other capabilities.

Internal workers/components may exist, but documentation should describe them as parts/capabilities of the same NOVA system unless the architecture explicitly changes and an ADR approves that change.

---

## 11. NOVA and Valo Separation

NOVA documentation must not treat Valo as part of the NOVA repository.

Keep:
- NOVA source/history/documentation;
- Valo source/history/documentation

separate.

---

## 12. Mandatory Working Habit

For every meaningful NOVA task:

**READ → VERIFY → WORK → TEST → LEARN → DOCUMENT → CHECKPOINT**

Expanded:

**READ**<br>
Read current status, relevant detailed notes, issues, and decisions.

**VERIFY**<br>
Inspect actual repo/Git/runtime truth.

**WORK**<br>
Make the smallest justified architectural change that solves the root cause.

**TEST**<br>
Do not call it complete before verification.

**LEARN**<br>
Capture what worked, what failed, and why.

**DOCUMENT**<br>
Update the relevant detailed note and indexes.

**CHECKPOINT**<br>
Record the tested Git milestone when appropriate.

---

## 13. Required Instruction for AI Coding Agents

When Claude, Codex, ChatGPT, or another coding agent works on NOVA, it should receive or inherit this rule:

> Before significant NOVA work, read `CHATGPT-OPERATING-PROTOCOL.md`, `NOVA-DOCUMENTATION-PROTOCOL.md`, `NOVA - Current Status`, and the relevant linked NOVA Vault notes. Use the newest verified repository/runtime evidence as source of truth. After meaningful work, update the relevant detailed Vault note, issues/ADRs, Current Status, and roadmap/hub when applicable. Preserve lessons from failures and never erase superseded history. Do not call the task complete until testing and documentation are both complete.

---

## 14. Goal of This Protocol

This protocol exists so NOVA development accumulates knowledge.

Each development session should leave the project easier to understand than before.

Future NOVA work should be able to answer:

- What exists now?
- What are we working on?
- Why was this architecture chosen?
- What failed before?
- What is still blocking us?
- What did the tests prove?
- What commit introduced this?
- What should happen next?

without reconstructing the answer from months of chat history.
