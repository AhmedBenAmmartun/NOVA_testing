# A1 Definition of Done

A1 is complete only when all of the following are true on the actual NOVA A1
worktree.

## Source

- exact verified A0 commit is the parent/base;
- all planned A1 source files are present;
- no unfinished implementation markers remain in A1 source;
- no new capability ID was added for Core Intelligence;
- `Assistant` owns one `ContextBroker` per session;
- the intrinsic tool is exposed without a capability mode;
- prompt rules clearly label SHADOW_ONLY/UNKNOWN behavior.

## Safety

- runtime A1 code has no Git-write command;
- runtime A1 code has no arbitrary shell;
- no approval/release/production tool was added;
- package contains no `.env`, credential cache, private recording, log dump, or
  secret token;
- NOVA/Valo separation remains intact;
- shadow journal is local-only.

## Verification gates

- Python compile passes;
- targeted A1 tests pass;
- A1 simulations pass;
- architecture/invariant checks pass;
- full NOVA pytest suite passes;
- NOVA tool-driver passes;
- mandatory live chat smoke test passes;
- security/secrets scan passes;
- `git diff --check` passes;
- exact changed-file set matches the manifest;
- integration checks pass.

## Checkpoint

Only after every gate passes:

- selectively stage the exact manifest file set;
- verify staged diff;
- commit;
- verify commit tree matches tested/staged tree;
- push A1 branch to `testing`;
- verify remote SHA equals local SHA;
- write local test evidence for the exact commit.

If any gate fails, do not commit or push.

## A1 runtime success criteria

A1 should be able to:

- report current branch/HEAD/dirty status with provenance;
- return UNKNOWN instead of guessing missing project evidence;
- distinguish stale test evidence from current evidence;
- surface explicitly documented failed approaches;
- keep project packet SHADOW_ONLY by default;
- keep influence disabled until the evaluation bar and trusted opt-in both
  succeed.

Automatic REMEMBER is not an A1 completion criterion; it belongs to A2.
