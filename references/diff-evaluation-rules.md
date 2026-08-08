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

## Script-implementation pitfalls (encoded in the code)

- **Merged PRs**: `merge-base(head, develop) == head`; use the merge commit's
  first parent as base or everything looks un-landed.
- **`git grep <sha>`** in a linked worktree needs `-- .` or it returns empty
  with exit 0.
- **`gui#N` markers**: the digits after `gui#` are NOT a bitcoin/bitcoin PR
  number; resolve against bitcoin-core/gui.
- **Unified-diff parsing** must reset file state on `diff --git`, or hunks
  from one file bleed into the previous file's bucket.
- **Supersession ordering**: only *later* upstream PRs in the Dash commit
  sequence may supersede an earlier PR's expectations; unordered supersession
  masks real drops.

## Validation history

PR-specific validation notes live in `docs/validation-history.md` — kept out
of this directory deliberately: agents read `references/` at review time, and
PR-specific findings here would hand the reviewer an answer key for those PRs
and burn them for model evaluation.
