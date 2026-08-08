# dash-backport-review-skill

An agent skill + deterministic checker for reviewing Dash Core backport PRs
against their upstream Bitcoin Core PRs. It answers, per upstream hunk:
**did this change actually land in the PR head tree?** — and surfaces dropped
content, undeclared partial backports, missing prerequisites, and stale PR
metadata with line-exact evidence.

The skill has two layers:

- `scripts/review_backport_pr.py` — the mechanical layer. Compares each
  referenced upstream PR's *net change* against the Dash PR's *tree state*
  (count-based per line), emitting per-file findings, a per-upstream-commit
  coverage table, and a verdict (`APPROVE` / `REQUIRES_REVIEW` / `BLOCK`).
- `SKILL.md` — the judgment layer. Instructions for the reviewing agent:
  a mandatory per-finding resolution protocol (landed-elsewhere / Dash-N/A
  with causal reason / declared omission), rules for dropped tests and
  release notes, and anti-dismissal guidance derived from a real missed
  review.

## What it catches (validated on real PRs)

- **Undeclared partial backports** — a `Merge bitcoin#N` subject where whole
  upstream commits never landed (dashpay/dash#7479: bitcoin#26699 landed
  1 of 6 commits; the initial human+bot review ACKed it).
- **Dropped release notes and tests** (dashpay/dash#7551: the bitcoin#25204
  release note and several bitcoin#18628 tests were confirmed review misses).
- **Missing prerequisites** — upstream edits to context Dash never had, with
  a `git log -S` hint naming the upstream commit that introduced it.
- **Stale PR-title metadata** — markers claimed in the title but absent from
  commits.

## What it deliberately tolerates (no noise)

- Context drift, moved lines (cross-hunk), Dash adaptations, renamed files
  (content-similarity matching), coverage split across commits in the PR,
  prior partial backports, and stacked upstream PRs superseding each other
  within the same Dash PR (order-aware composition).

## Requirements

- `gh` CLI, authenticated
- Run from inside a Dash Core checkout (fetches upstream merge commits
  read-only into `refs/backport-check/*`; cleaned up unless `--keep-refs`)

## Usage

```bash
python3 scripts/review_backport_pr.py 7479                  # markdown report
python3 scripts/review_backport_pr.py 7479 --json           # structured output
python3 scripts/review_backport_pr.py 7479 --keep-refs      # keep upstream refs for digging
python3 scripts/review_backport_pr.py 7479 --base origin/develop --repo dashpay/dash
```

## Installing as an agent skill

Symlink (or clone) this repo into your agent's skill directory:

```bash
# Claude Code
ln -s /path/to/dash-backport-review-skill ~/.claude/skills/backport-pr-codereview

# Codex
ln -s /path/to/dash-backport-review-skill ~/.codex/skills/backport-pr-codereview
```

`agents/openai.yaml` carries the Codex interface metadata.

## Integrating with an automated review bot

The `--json` output is designed to be a deterministic pre-filter for an LLM
review agent: the bot verifies the mechanical findings instead of re-deriving
hunk coverage, and spends its judgment on adaptation-vs-drop questions.
Alignment guidance for the bot's prompt:

1. Enumerate every commit of each referenced upstream PR and classify each
   landed/partial/absent *before* any hunk analysis — reviewing by headline
   purpose is how undeclared partials get ACKed.
2. Declared-vs-actual partial is a finding on its own (provenance accuracy),
   independent of runtime correctness.
3. A PR-body justification must address the *omission* (e.g. untested
   user-visible behavior), not a neighboring implementation detail.
4. Resolve each finding on its own evidence. After correctly dismissing a few
   false positives, an agent becomes more permissive, not more accurate.

## Provenance

`references/diff-evaluation-rules.md` holds the design rationale, risk
taxonomy, and script-implementation pitfalls. PR-specific validation history
(ground truth from dry runs on dashpay/dash #6888, #7551, #7479) lives in
`docs/validation-history.md`, deliberately outside `references/`: agents read
`references/` at review time, and PR-specific findings there hand the
reviewer an answer key. Treat the documented cases as regression tests when
modifying the script — and **never evaluate models on a PR named anywhere in
this repo**; those PRs are burned.
