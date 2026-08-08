# Diff Evaluation Rules

## Design rationale (why tree-state, not diff-vs-diff)

The previous version of this skill compared upstream patch text against Dash
patch text. That approach cannot distinguish "dropped hunk" from "context
differs" — Dash's tree is never identical to upstream's base, so even perfect
backports produced OVERLAP_MISMATCH noise, and reviewers learned to ignore
the output. Meanwhile it auto-approved genuinely dropped content
(UPSTREAM_ONLY docs/tests were "expected in backports").

The current script instead asks, per upstream hunk: did the net change land
in the PR head **tree**? Count-based per-line accounting handles moved lines,
repeated lines, and cross-commit coverage inside the PR.

## Risk taxonomy

| Class | Path pattern | Risk |
| --- | --- | --- |
| `DOCS_ONLY` | `doc/` | LOW — but a DROPPED release note is a real finding |
| `TEST_ONLY` | `test/` (not framework) | LOW — dropped tests must still be justified |
| `TEST_FRAMEWORK` | `test/functional/test_framework/` | MEDIUM |
| `SRC_RPC_OR_CONSENSUS` | `src/rpc/`, `src/rest/`, versionbits/deployment/consensus/chainparams/fork paths | HIGH |
| `SRC_NONCRITICAL` | other `src/` | MEDIUM |
| `OTHER` | everything else | LOW |

Verdict: any HIGH finding → `BLOCK` (= demands human attention);
any other finding → `REQUIRES_REVIEW`; none → `APPROVE`.

## Validation notes (2026-08-07 dry runs)

### dashpay/dash#7551 (merged) — ground truth confirmed by maintainer

- `bitcoin#25204`: `doc/release-notes.md` DROPPED — **real miss**; should have
  landed as PR-specific release notes. The old skill auto-approved this.
- `bitcoin-core/gui#613`: PARTIAL(4/7), declared partial — Dash keeps
  `wallet/walletutil.h` include; intended.
- `bitcoin#25689`: clean — upstream moved `SetMempoolConstraints` calls; Dash
  moved them identically. The old skill flagged this as drift (false positive).
- `bitcoin#25785`: PARTIAL(23/25) — intentional adaptation (descriptor string
  without segwit wrapping, `PriorityLevel::HIGH`).
- `bitcoin#21148` follow-up: reference kind; backport found in history
  (`ddc53d7afd0c` / `51ad8e4ddec4`). Symbol probing would false-positive here:
  `GetTransactionWeight`/`GetWitnessHash` legitimately don't exist in Dash
  (no segwit) — hence the history-based check for references.
- `bitcoin#18628`: several genuinely never-landed tests (`test_large_inv`,
  `test_spurious_notfound`, p2p_leak old-version check) — maintainer
  confirmed these were likely review misses. Cross-commit coverage (orphan
  test landed via the 19393 commit, adapted `mapOrphan`→`orphanage`) is
  handled by checking the PR head tree, not the per-commit diff.

### dashpay/dash#6888 (merged, heavily adapted)

Deployment/versionbits backport with deep Dash adaptations: many PARTIALs in
`src/rpc/blockchain.cpp` / `src/versionbits.*` with exact adapted lines
quoted. Verdict BLOCK = "human must confirm each adaptation", which matches
how the PR was actually reviewed. Also caught: `doc/release-notes-23508.md`
FILE_ABSENT and dropped `rpc_signrawtransaction.py` test hunks.

### Pitfalls encountered and encoded in the script

- **Merged PRs**: `merge-base(head, develop) == head`; must use the merge
  commit's first parent as base or everything looks un-landed.
- **`git grep <sha>`** in a linked worktree needs `-- .` or it returns empty
  with exit 0. (Also: piping through `head` clobbers `$?` when probing.)
- **gui#N markers**: the digits after `gui#` are NOT a bitcoin/bitcoin PR
  number; the old regex mapped `gui#613` to bitcoin#25266 via title text and
  produced a spurious BLOCK.
- **Unified-diff parsing** must reset file state on `diff --git`, or hunks
  from one file bleed into the previous file's bucket.

## Validation round 2 (2026-08-07, dashpay/dash#7479 — Codex transcript post-mortem)

A Codex session using this skill initially ACKed #7479 despite bitcoin#26699
landing only 2 of 6 upstream commits. Root causes and fixes now encoded:

- **Dismissal fatigue**: rename/adaptation false positives led the agent to
  write off the whole REQUIRES_REVIEW verdict as "context drift". Fixes:
  per-upstream-commit coverage table (mechanical "k/n commits landed" that
  cannot be waved off), `UNDECLARED_PARTIAL` metadata finding, rename
  resolution by content similarity (`dash counterpart`), `landed_elsewhere`
  annotation, and the mandatory per-finding resolution protocol in SKILL.md.
- **Grouping**: multiple Dash commits referencing the same upstream PR
  ("Merge …" + "Dash adaptations for …") previously produced duplicate
  analyses; now analyzed once per upstream PR.
- **Supersession**: later commits in the same upstream PR rewriting earlier
  ones is not Dash drift — coverage only counts expectations surviving to the
  upstream PR's own final tree.
- **Cross-hunk moves**: moved lines cancel at file level, not hunk level
  (bitcoin#25689's SetMempoolConstraints move was a false DROPPED).
- **Coverage counting**: presence-based on distinctive lines (≥12 chars with
  an identifier), so earlier partial backports count as covered while braces
  and includes don't inflate genuinely dropped commits.

Ground truth on #7479: #26699 UNDECLARED_PARTIAL (watch-only balance commit
ABSENT, MiniGui/test-decoupling/PSBT-watch-only test commits dropped);
QMessageBox(this) and ConfirmSend confirm_type refactors dropped in
wallettests.cpp; Dash keeps wallet::GetAvailableBalance precisely because
cd98b717398 was skipped. The PR-body justification ("upstream-only test")
addresses implementation inapplicability, not the untested user-visible
behavior — exactly the distinction the resolution protocol now demands.

## Validation round 3 (2026-08-07, cross-PR supersession)

The rerun of the Codex agent on #7479 with the round-2 skill produced the
correct review (UNDECLARED_PARTIAL blocker, watch-only PSBT test-coverage
blocker, non-buildable intermediate commits) — but had to manually resolve
"25647: 4/8, remaining differences are later #25685 refactoring". Now
mechanical: expectations of an upstream PR that a *later* upstream PR in the
same Dash PR deletes (or re-adds) are excluded as composed-tree supersession,
with an "N expectation line(s) superseded" note per section. Ordering matters:
an unordered version masked 26699's deletion of the wallet_create_tx
GetAvailableBalance line (25685 — earlier — had added it); supersession only
flows from later PRs in the Dash commit sequence.

## Validation round 4 (2026-08-07, five-model eval on #7479)

Five models ran the skill on #7479 against known ground truth. All five got
the mechanical layer right (UNDECLARED_PARTIAL, coverage tables, rename and
supersession annotations) — the script successfully floor-raised every model.
They diverged only on the judgment call: is the PR-body justification for the
dropped watch-only PSBT test sufficient?

- Correct (checked the tree for the user-visible behavior before ruling):
  Sonnet-class "5.6 sol", deepseek flash — the latter also found the sharpest
  framing: the body justifies the *test* omission but never declares the
  *behavior commit* (cd98b717398) omission; separate declarations.
- Incorrect: gemini flash accepted the body at face value; muse spark quoted
  the resolution protocol and then asserted "behavior unneeded" without
  evidence; compose fast declared "APPROVE with nits" and dismissed
  buildability.

Lessons encoded in SKILL.md: evidence requirement (enumerate + cite each
capability before any N/A on a dropped test), UNDECLARED_PARTIAL never a nit,
no local paths in reports, no attribution footer off-GitHub, don't accept
author claims as verification. Detail volume anti-correlated with verdict
quality: the two longest reports had the worst verdicts.

## Validation round 5 (2026-08-07, second model eval on #7479 — post-hardening)

Rerun with the round-4 SKILL.md (composer, muse, deepseek; no gemini):

- **Evidence requirement worked where executed**: composer — worst in round 1
  ("justification is adequate, safe to ACK") — now performs the capability
  enumeration verbatim and reaches the ground-truth conclusion on the dropped
  watch-only PSBT test. Direct skill-text → behavior change.
- **Two evasion shortcuts observed**: muse cited the evidence requirement and
  then deferred the enumeration to the PR body ("does that at a high level");
  composer performed it but labeled the finding "optional". Deepseek regressed
  to accepting the test justification it rejected in round 1. SKILL.md now
  requires the enumeration table to appear in the report and pins the finding
  as a required action.
- **Attention crowding — new failure mode**: the buildability finding
  (4/5 models in round 1) vanished from ALL THREE round-2 reports. Emphasizing
  script-finding resolution suppressed model-initiative findings. Fix is the
  same as for the undeclared partial: make the script emit it. Added
  LATE_ADAPTATION detection: a non-Merge commit whose net-deleted lines were
  net-added by a commit >1 position earlier in the same PR (threshold 1 line —
  the canonical case is bc52f0a9c79's one-line blockConnected signature fix,
  3 commits after c392040ca08). Validated: both #7479 stack issues detected
  with exact lines; zero false positives on #7551.
- **Positives that stuck**: report hygiene universally adopted (verdict-first,
  no local paths, no stray footers, deepseek explicitly disclaims unverified
  claims); the test-vs-behavior declaration distinction propagated to all
  three models via this reference doc.
- **Meta-lesson**: rules that models must *execute* (produce a table, resolve
  a script finding) transfer across models; rules that models must *remember
  to apply* (check buildability) do not. Prefer moving checks into the script
  or into required output artifacts.
