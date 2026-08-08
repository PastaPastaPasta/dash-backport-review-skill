# Validation history

PR-specific ground truth from the skill's validation runs. **This file is an
answer key: every PR named here is burned for model evaluation.** Model evals
must use PRs not mentioned anywhere in this repo — agents load the skill
directory, so PR-specific findings placed in SKILL.md or references/ leak
into the reviewer's context (this actually happened: rounds 2-3 of the model
eval ran after round-1 ground truth for dash#7479 was committed to
references/, invalidating the cross-model comparison on that PR).

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
- `bitcoin#18628`: **CORRECTED in round 7** — originally recorded here as
  "genuinely never-landed tests, likely review misses". Wrong: at the PR base
  Dash already covered every flagged behavior in adapted/richer form
  (`test_oversized_{inv,getdata,headers}_msg` subsumes `test_large_inv`;
  `test_spurious_notfound` at p2p_tx_download.py:198; `create_old_version(31799)`
  obsolete-version disconnect at p2p_leak.py:162; `test_size_limits` with
  `MAX_BLOOM_FILTER_SIZE`+Misbehaving in p2p_filter.py). Line-absence is not
  coverage-absence — the exact lesson the resolution protocol encodes.
  Cross-commit coverage (orphan test landed via the 19393 commit, adapted
  `mapOrphan`→`orphanage`) is handled by checking the PR head tree, not the
  per-commit diff.

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

## Validation round 6 (2026-08-07, third model eval on #7479 — contaminated)

Composer, muse, deepseek-v4-flash reran with the round-5 skill. Surface
results: composer and muse delivered essentially ground-truth reviews
(including in-report evidence tables); deepseek softened UNDECLARED_PARTIAL
to "a note, not a blocker" and dropped the test-coverage finding again.

**Contamination discovered**: rounds 2-3 (validation rounds 4-6) ran after
this file's round-1 notes — containing #7479's full ground truth, down to
commit hashes and the blockConnected line — were committed to references/,
which reviewing agents read. Conclusions that DO survive:

- Script-emitted findings get carried by every model; model-initiative
  findings decay (structural, not knowledge-dependent).
- All three models correctly adjudicated cde726cc5e1 as a benign
  LATE_ADAPTATION (additive, not a compile fix) — that judgment was NOT in
  the notes, so it is genuine evidence models can adjudicate mechanical
  findings.
- Report-hygiene adoption (structural).
- Deepseek failing the judgment calls WITH the answer key available is a
  strong negative signal; dropping it stands.

Conclusions that do NOT survive: composer's and muse's apparent judgment-call
redemption on #7479. Model selection requires a clean-PR run (any backport PR
not named in this repo), composer vs a premium model, before standardizing on
the cheap tier.

## Validation round 7 (2026-08-07, model eval on #7551 — burned PR, but self-invalidating contamination test)

Muse, composer, deepseek reran on #7551 — which is named in this repo, so
nominally burned. However, all three models CONTRADICTED this file's recorded
18628 ground truth ("genuinely never-landed tests") with specific citations —
and tree verification proved the MODELS right: every flagged 18628 behavior
existed at the PR base in adapted/richer form (see corrected entry above).
Contradicting the answer key with correct evidence is strong indication none
of them read the quarantined file, and it corrected an error in our own
ground truth. The judgment layer working as designed: line-absence ≠
coverage-absence, resolved by tree inspection.

Outcomes:
- **Composer**: correct on everything, held UNDECLARED_PARTIAL severity,
  noticed the PR was already MERGED and reframed the release-note fix as a
  post-merge follow-up PR (best situational awareness), found the
  release-notes-6499 precedent. Second consecutive strong round.
- **Muse**: correct on everything, thorough per-item resolution tables with
  verified citations; did not notice the PR was merged ("before merge"
  asks). Strong.
- **Deepseek**: right substance on 25204 but softened UNDECLARED_PARTIAL to
  "non-blocking per Dash precedent" (invented precedent; third consecutive
  round of softening pinned severities) and claimed the 25785 descriptors
  bench was "byte-equivalent... exact match" — factually false (Dash adapts
  to sh(multi(15,...)) + PriorityLevel::HIGH). Right conclusions via wrong
  facts. Dropped from rotation, final.

Model selection: composer primary for thepastaclaw's backport agent, muse as
alternate, premium-tier (sol-class) spot-check on consensus-path PRs or every
Nth review. A truly clean-PR run (PR absent from this repo) remains the ideal
confirmation, but composer contradicting-and-correcting the answer key while
holding severities is the strongest signal available short of that.

## Validation round 8 (2026-08-07, clean-PR eval on #7525 — final model decision)

First eval on a PR absent from this repo (#7525, kernel-3 batch, script verdict
BLOCK from a HIGH getmempoolinfo finding). Ground truth verified in-tree:
the BLOCK is a false positive — the "missing" incrementalrelayfee field comes
from bitcoin#25439, which Dash never backported (not a hole in #25648); the
two fields Dash has are correctly rewired to pool.m_*. Feefilter is genuinely
absent from Dash net_processing (Dash-N/A). The non-marker cleanup commit
83ba97c4a83 correctly removes #26933 makeup (backported earlier via #7237 /
0d8920cb407, sha verified) that referenced the ::minRelayTxFee global removed
in this PR.

- **Composer**: correct verdict with the sharpest causal resolution (traced
  the HIGH finding to un-backported 25439 — prerequisite-graph reasoning),
  all N/As verified, noted merged status and thin PR body. Third consecutive
  strong round; first on a clean PR. Selected as primary.
- **Muse**: correct on everything with verified per-item citations; slightly
  less precise on the HIGH finding's origin but adds useful behavioral
  evidence (m_incremental_relay_feerate stored and used for eviction).
  Alternate.
- **Gemini**: accurate content (shas spot-checked) but zero engagement with
  the script's findings — never mentions the BLOCK or resolves the HIGH
  finding, no severity ranking. APPROVE-by-summary is the wholesale-dismissal
  anti-pattern even when the conclusion is right. Out.

Eval also exposed a script bug, now fixed: "remove make-up code from backport
bitcoin#N" was classified as a backport CLAIM for N (bogus 26933 section,
muse called it "mis-mapped"). Claims are now only Merge-style or
"backport: [partial] bitcoin#N" subjects; all other marker mentions are
references checked against history.

Final rotation: composer primary, muse alternate, sol-class spot-check on
consensus-path PRs; gemini and deepseek out.
