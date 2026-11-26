---
name: backport-pr-codereview
description: Review a Dash Core backport PR against its upstream Bitcoin Core PRs to verify every hunk landed, catch missing prerequisites, and classify risk. Use when reviewing or auditing a Dash PR that backports upstream Bitcoin commits.
---

# Backport PR Codereview

## Overview

Use this skill to review an **open** (or merged) Dash backport PR whose commits
carry upstream markers (`Merge bitcoin#N`, `Merge bitcoin/bitcoin#N`,
`partial Merge bitcoin-core/gui#N`, `fix: follow-up for bitcoin#N`, …).

The script answers one question per upstream hunk: **did this change actually
land in the PR head tree?** It compares upstream *net change* against Dash
*tree state* (count-based, per line), so it tolerates context drift, moved
lines, Dash adaptations, and coverage split across commits within the PR —
while catching genuinely dropped content, silently omitted files/tests, and
missing prerequisites.

## Invocation

Run from inside a Dash Core checkout (any worktree). `scripts/` is relative
to this skill's own directory:

```bash
python3 <skill-dir>/scripts/review_backport_pr.py <pr_number>
python3 <skill-dir>/scripts/review_backport_pr.py 7551 --json
python3 <skill-dir>/scripts/review_backport_pr.py 6888 --keep-refs
```

Flags: `--repo` (default `dashpay/dash`), `--base` (default `origin/develop`),
`--json` (structured output), `--keep-refs` (keep `refs/backport-check/*`
fetched upstream merge commits for follow-up digging; deleted by default).

`gh` must be authenticated. Each mapped upstream merge commit is fetched
read-only into `refs/backport-check/`.

## Per-file statuses

Findings are per upstream file (net expectations aggregated across hunks, so
moved lines cancel even across hunks):

- `LANDED` — net change fully present in the PR head tree (not reported).
- `ALREADY_PRESENT` — content pre-existed at the PR base: prior coverage
  (not reported).
- `PARTIAL(n/m)` — some lines landed; the report quotes the exact missing /
  still-present lines. Usually an intentional Dash adaptation — confirm it.
- `DROPPED` — nothing from the file's changes landed. Port or justify.
- `FILE_ABSENT` — upstream file has no counterpart in the PR head tree, and
  no renamed Dash counterpart was found by content similarity.
- `PREREQ_MISSING?` — upstream edits context Dash never had. Either a
  prerequisite PR is missing (check the `introduced upstream by:` hint) or
  Dash carries an adapted equivalent — verify which.
- `REFERENCED_PR_NOT_BACKPORTED` — a follow-up commit references an upstream
  PR with no backport marker anywhere in history at the PR base.
- `UNDECLARED_PARTIAL` — the per-commit coverage table (below) found whole
  upstream commits absent from the Dash tree, but the subject claims a full
  `Merge`. Per Dash convention the subject should say `partial Merge …` and
  every omission must be documented. This is the finding reviews most often
  miss — never wave it off.
- `LATE_ADAPTATION` (in the "Commit stack" section) — a non-`Merge` commit
  rewrites a line introduced by a commit more than one position earlier in
  the same PR. The intermediate commits likely do not build (the canonical
  case is a one-line signature/compile fix landing at the end of the stack).
  Resolution: fold the fix into the earlier commit, move it immediately
  after, or have the PR declare the non-building range explicitly
  (atomic-commit rule). Always carry this into your report — in a model eval,
  every reviewer dropped this finding once it was no longer script-emitted.

Findings may carry annotations that resolve common false positives for you:

- `dash counterpart (renamed): <path>` — the upstream file was matched to a
  renamed Dash file by content similarity; checks ran against it.
- `content found in <path>` — a DROPPED file's distinctive lines were found
  in a different file (rename/move); confirm and treat as landed.

## Per-commit coverage table

Each backport section includes `upstream commit coverage: k/n fully landed`,
listing PARTIAL/ABSENT upstream commits with line counts. Coverage is
presence-based on distinctive lines — content that arrived via an earlier
partial backport still counts as covered, but braces/includes don't inflate
dropped commits. `ABSENT` upstream commits in a subject without `partial`
raise `UNDECLARED_PARTIAL` automatically.

## Commit-marker semantics

- `Merge bitcoin#N` / `backport:` subjects are **backport** claims: the PR
  must land N's hunks. Checked against the PR head tree.
- `follow-up` / `fixup` subjects are **references**: N must already be in
  history at the PR base (checked via `git log --grep`). Symbol-level probing
  is deliberately NOT used here — Dash adaptations (e.g. no-segwit rewrites)
  make upstream symbols legitimately absent.
- A `partial` keyword in the subject marks findings "declared partial":
  expected omissions, but confirm the omitted part is the intended one.
- `bitcoin-core/gui#N` resolves against bitcoin-core/gui — never treat the
  digits as a bitcoin/bitcoin PR number.
- The PR title's claimed markers are cross-checked against commit markers;
  stale title metadata is reported (it has caused bad reviews before).

## How to review the output (agent instructions)

The script finds *what* differs; you judge *why*.

**Resolution protocol — non-negotiable.** Every reported finding must be
individually resolved into exactly one of:

1. **Landed elsewhere** — name the Dash file/commit where the content lives.
2. **Dash-N/A** — state the *causal* reason (API/architecture Dash lacks) AND
   where the equivalent behavior lives or why it cannot apply. "Dash differs
   here" is not a resolution. For dropped *tests*, implementation
   inapplicability is NOT sufficient: if the user-visible behavior exists in
   Dash, the behavior needs an adapted test or an explicit justification for
   remaining untested.

   **Evidence requirement for N/A on a dropped test** — you may not assert
   "behavior unneeded in Dash"; you must show it. Enumerate each user-visible
   capability the test exercises (e.g. legacy watch-only wallet, unsigned tx
   creation, PSBT presentation, clipboard export), and for each, cite the
   Dash file that proves it exists or is absent. **The enumeration table must
   appear in your report** — YOU perform it against the tree; deferring to
   the PR body's claim that it "covers this at a high level" is not
   performing it. If ANY capability exists, the resolution is "adapt the
   test" or "explicit untested-behavior justification" — never plain N/A, and
   the finding is a **required action, not optional**: a test dropped while
   its behavior exists in Dash always demands either the adapted test or the
   explicit justification before ACK. A PR-body justification that addresses
   implementation inapplicability does not cover behavior; check whether the
   body also declares any omitted *behavior* commits — test omission and
   behavior-commit omission are separate declarations. (In model evals of
   this exact call: every model that skipped the enumeration got it wrong;
   one quoted this rule and asserted its way past it; another performed the
   enumeration, reached the right conclusion, then still labeled the finding
   "optional". Neither shortcut is acceptable.)
3. **Genuinely omitted** — then it must be declared (`partial` subject and/or
   PR-body justification). Undeclared omission = finding to report. If a
   justification exists, check that it actually covers this omission, not
   merely a neighboring implementation detail.

Do not dismiss the tool's output wholesale as "expected context drift" — that
exact reasoning caused a missed undeclared-partial in a prior review (a PR
where only 2 of 6 upstream commits landed was ACKed as faithful). After
correctly dismissing a few false positives, you are MORE likely to wrongly
dismiss the next finding, not less; resolve each one on its own evidence.
Review the backport by its full upstream commit list, never only by the PR's
headline purpose.

For each finding:

1. `DROPPED`/`FILE_ABSENT` in `doc/` — upstream release notes must land as
   PR-specific `doc/release-notes-<N>.md`. A dropped release note is a real
   finding, not "expected in backports".
2. `DROPPED`/`FILE_ABSENT` in `test/` — dropped upstream tests must be called
   out per CLAUDE.md; either port them or the PR description must justify the
   omission. Do not wave these through.
3. `PARTIAL` in `src/` — read the quoted missing lines. Dash adaptation
   (renamed helpers, no-segwit, Dash-only params) is fine; a silently lost
   behavioral line is not. When unsure, diff the region:
   `git diff refs/backport-check/<repo>-<N>~1 refs/backport-check/<repo>-<N> -- <file>`
   (run with `--keep-refs`).
4. `PREREQ_MISSING?` — follow the `introduced upstream by:` hint; check
   whether that upstream commit/PR was backported
   (`git log --grep 'bitcoin#<M>' origin/develop`). If not, that's a missing
   prerequisite: name it in the review.
5. Verdict `BLOCK` means a HIGH-risk (`src/rpc`/consensus-path) finding
   exists — it demands human attention, not necessarily rejection. Heavily
   adapted backports (e.g. deployment/versionbits work) legitimately show
   many PARTIALs; the value is the exact line list to confirm.

Report findings with file/hunk references and your adaptation-vs-drop
judgement per item. Never claim the backport is faithful based on verdict
`APPROVE` alone if the PR also contains non-marker commits — review those
separately as ordinary Dash changes.

## Report hygiene

- Lead with the verdict and blockers; rank findings by severity. Do not bury
  a blocker under per-file narration — a short, ranked report beats a long
  exhaustive one.
- `UNDECLARED_PARTIAL` is never a "nit": provenance metadata is a merge
  requirement in Dash convention. Do not soften it into "APPROVE with nits".
- Reference files by repo-relative path or GitHub URL at the head SHA —
  never local filesystem paths (worktree paths leak and break when posted).
- Do not accept author/PR-body claims (e.g. "benchmarks pass", "test is
  upstream-only") as verification; verify in the tree or say you didn't.
- AI-attribution footers belong only on content actually posted to GitHub,
  never on terminal reports.

## Known limits

- Line-level occurrence counting can mislabel a hunk when the same line is
  edited multiple times in one file with different outcomes; the quoted
  missing/present lines make this easy to spot manually.
- For merged PRs the base is the merge commit's first parent (handled
  automatically); for open PRs it is `merge-base(head, --base)`.
- Upstream PRs whose merge commit GitHub no longer reports resolve via
  commit search; a failure is reported per commit, not fatal.

## References

- `references/diff-evaluation-rules.md` — risk taxonomy, design rationale,
  and script-implementation pitfalls. (Do not go looking for per-PR answer
  material in this repo; PR-specific validation history is maintainer
  documentation, not review input.)
