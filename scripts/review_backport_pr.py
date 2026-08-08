#!/usr/bin/env python3
"""Backport PR reviewer: verify each upstream hunk actually landed in the PR head tree.

Design (validated against dashpay/dash#6888 and #7551):

- The unit of comparison is the upstream PR's *net change* (merge-commit
  first-parent -> merge result), checked hunk-by-hunk against the Dash PR
  *head tree state* — NOT diff-text vs diff-text. This tolerates context
  drift, moved lines, Dash adaptations, and cross-commit coverage inside
  the PR, while catching genuinely dropped content.
- Count-based line accounting: for every added line the net occurrence count
  must rise; for every removed line it must fall. Moved lines (in both adds
  and dels) and repeated lines are handled by counting, not set membership.
- Commit markers are classified: a "Merge bitcoin#N"-style subject is a
  *backport* (this PR must land N); a "follow-up for bitcoin#N" subject is a
  *reference* (N must already be in history at the PR base). Symbol-probing
  references is wrong — Dash adaptations (e.g. no-segwit rewrites) false
  positive — so references are checked against backport markers in history.
- `bitcoin-core/gui#N` markers resolve against bitcoin-core/gui, not
  bitcoin/bitcoin (the digits after "gui#" are NOT a bitcoin/bitcoin PR).

Requires: gh (authenticated), run from inside a Dash Core checkout.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict

DEFAULT_UPSTREAM = "bitcoin/bitcoin"


def git(*args, check=True):
    r = subprocess.run(["git"] + list(args), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def gh(*args):
    return subprocess.run(["gh"] + list(args), capture_output=True, text=True)


def norm(s):
    return " ".join(s.split())


# ---- marker parsing -------------------------------------------------------
# Handles: bitcoin#N | bitcoin/bitcoin#N | Merge bitcoin/bitcoin##N |
# bitcoin-core/gui#N | (partial) Merge #N
MARKER = re.compile(
    r"(?i)(?:"
    r"(?P<guim>bitcoin-core/gui)\s*#\s*(?P<guinum>\d+)"
    r"|(?:bitcoin(?:/bitcoin)?)\s*#+\s*(?P<bnum>\d+)"
    r"|\bMerge\s+#\s*(?P<plainnum>\d+)\b"
    r")"
)
FOLLOWUP = re.compile(r"(?i)\b(follow[- ]?up|fix[- ]?up|followup for|amend|address\s+review)\b")
PARTIAL = re.compile(r"(?i)\bpartial\b")


def parse_markers(subject):
    """Return list of {repo, num, kind, partial} parsed from a commit subject.

    kind 'backport': this commit claims to land the upstream PR.
    kind 'reference': a follow-up/fix that only mentions it — the upstream PR
    is expected to already be present at the PR base.
    """
    is_followup = bool(FOLLOWUP.search(subject))
    is_partial = bool(PARTIAL.search(subject))
    out = []
    for m in MARKER.finditer(subject):
        if m.group("guim"):
            repo, num = "bitcoin-core/gui", int(m.group("guinum"))
        elif m.group("bnum"):
            repo, num = DEFAULT_UPSTREAM, int(m.group("bnum"))
        else:
            repo, num = DEFAULT_UPSTREAM, int(m.group("plainnum"))
        out.append({
            "repo": repo, "num": num,
            "kind": "reference" if is_followup else "backport",
            "partial": is_partial,
        })
    return out


# ---- upstream merge-commit resolution -------------------------------------
def find_upstream_merge(repo, number):
    """Return the upstream merge-commit sha for PR #number (pulls API primary,
    gh commit-search fallback for edge cases)."""
    r = gh("api", f"/repos/{repo}/pulls/{number}", "--jq", ".merge_commit_sha")
    if r.returncode == 0 and r.stdout.strip() and r.stdout.strip() != "null":
        return r.stdout.strip()
    for query in (f"Merge {repo}#{number}", f"Merge #{number}"):
        r = gh("search", "commits", "--repo", repo, query,
               "--json", "sha,commit", "--limit", "10")
        if r.returncode != 0 or not r.stdout.strip():
            continue
        try:
            hits = json.loads(r.stdout)
        except json.JSONDecodeError:
            continue
        for h in hits:
            msg = (h.get("commit", {}).get("message", "") or "").splitlines()[0]
            if msg.lower().startswith("merge") and re.search(rf"#{number}\b", msg):
                return h["sha"]
    return None


# ---- diff parsing ---------------------------------------------------------
def parse_diff_files(diff_text):
    """Unified diff -> {path: [(added_lines, removed_lines), ...]} per hunk."""
    files = defaultdict(list)
    cur = None
    adds, dels = [], []

    def flush_hunk():
        nonlocal adds, dels
        if cur is not None and (adds or dels):
            files[cur].append((adds, dels))
        adds, dels = [], []

    def flush_file():
        nonlocal cur
        flush_hunk()
        cur = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            flush_file()
            continue
        if line.startswith("@@"):
            flush_hunk()
            continue
        m = re.match(r"^\+\+\+ b/(.*)$", line)
        if m:
            flush_hunk()
            cur = m.group(1)
            continue
        if cur is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            adds.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            dels.append(line[1:])
    flush_file()
    return files


def blob_counts(ref, path):
    r = git("show", f"{ref}:{path}", check=False)
    if r.returncode != 0:
        return None
    counts = defaultdict(int)
    for l in r.stdout.splitlines():
        n = norm(l)
        if n:
            counts[n] += 1
    return counts


def count_in(blob, line):
    return 0 if blob is None else blob.get(line, 0)


def hunk_status(na, nd, base_blob, head_blob):
    """Count-based landed check for one hunk.

    Returns (status, missing_adds, lingering_dels, landed, total). Statuses:
      LANDED           net change fully present in head tree
      ALREADY_PRESENT  added content pre-existed at base (prior coverage)
      PARTIAL(n/m)     some lines landed
      DROPPED          nothing landed
      PREREQ_MISSING?  upstream-removed lines never existed in Dash — the
                       upstream context this hunk edits is absent (either a
                       missing prerequisite or a Dash-adapted equivalent)
    """
    landed = total = 0
    missing_adds, lingering_dels = [], []
    for a in sorted(set(na), key=na.index):
        moved = nd.count(a)
        need = na.count(a) - moved
        if need <= 0:
            continue
        total += need
        base = count_in(base_blob, a)
        have = max(0, min(need, count_in(head_blob, a) - base + moved))
        landed += have
        if have < need:
            missing_adds.append(a)
    for d in sorted(set(nd), key=nd.index):
        moved = na.count(d)
        need = nd.count(d) - moved
        if need <= 0:
            continue
        total += need
        base = count_in(base_blob, d)
        gone = max(0, min(need, base - count_in(head_blob, d) + moved))
        landed += gone
        if gone < need:
            lingering_dels.append(d)
    if total == 0 or landed == total:
        return "LANDED", missing_adds, lingering_dels, landed, total
    if landed > 0:
        return f"PARTIAL({landed}/{total})", missing_adds, lingering_dels, landed, total
    if nd and base_blob is not None and not any(count_in(base_blob, d) for d in nd):
        return "PREREQ_MISSING?", missing_adds, lingering_dels, landed, total
    if na and base_blob is not None and all(count_in(base_blob, a) for a in na):
        return "ALREADY_PRESENT", missing_adds, lingering_dels, landed, total
    return "DROPPED", missing_adds, lingering_dels, landed, total


_rename_cache = {}


def resolve_renamed(tree, path, upstream_pre_blob):
    """When `path` doesn't exist in `tree`, find Dash's renamed counterpart by
    content similarity against the upstream pre-PR file (same directory, same
    extension, most shared distinctive lines). Returns a path or None."""
    key = (tree, path)
    if key in _rename_cache:
        return _rename_cache[key]
    result = None
    if upstream_pre_blob:
        distinctive = {l for l in upstream_pre_blob if len(l) >= 20}
        if len(distinctive) >= 10:
            directory = path.rsplit("/", 1)[0] if "/" in path else "."
            ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
            ls = git("ls-tree", "--name-only", f"{tree}:{directory}", check=False)
            best, best_score = None, 0
            for name in ls.stdout.splitlines():
                if not name.endswith(ext):
                    continue
                cand = f"{directory}/{name}"
                blob = blob_counts(tree, cand)
                if blob is None:
                    continue
                score = sum(1 for l in distinctive if l in blob)
                if score > best_score:
                    best, best_score = cand, score
            if best is not None and best_score >= max(10, len(distinctive) // 4):
                result = best
    _rename_cache[key] = result
    return result


def file_expectations(hunks, up_final=None):
    """Aggregate a file's hunks into net per-line expectations.

    Moved lines cancel across hunks (not just within one), and when `up_final`
    is given, only expectations that survive to the upstream PR's own final
    tree are kept — supersession by later commits in the same upstream PR is
    not Dash drift.
    """
    ca, cd = Counter(), Counter()
    for adds, dels in hunks:
        for a in adds:
            n = norm(a)
            if n:
                ca[n] += 1
        for d in dels:
            n = norm(d)
            if n:
                cd[n] += 1
    na, nd = [], []
    for line in set(ca) | set(cd):
        net = ca[line] - cd[line]
        if net > 0 and (up_final is None or count_in(up_final, line) > 0):
            na.extend([line] * net)
        elif net < 0 and (up_final is None or count_in(up_final, line) == 0):
            nd.extend([line] * (-net))
    return na, nd


def find_elsewhere(head, missing_lines):
    """When a hunk looks DROPPED/FILE_ABSENT, check whether its distinctive
    added lines actually landed in a *different* file (renames, moved tests,
    Dash file layout). Returns the most common other path, or None."""
    hits = Counter()
    probed = 0
    for line in missing_lines:
        l = line.strip()
        if len(l) < 20 or not re.search(r"[A-Za-z_]{4,}", l):
            continue
        probed += 1
        if probed > 4:
            break
        g = git("grep", "-F", "-l", "-e", l, head, "--", ".", check=False)
        if g.returncode == 0:
            for p in g.stdout.strip().splitlines():
                hits[p.split(":", 1)[1] if ":" in p else p] += 1
    if not hits:
        return None
    path, n = hits.most_common(1)[0]
    return path if n >= max(1, probed // 2) else None


def upstream_commit_coverage(ref, head, merge_base, cross_filter=None, key=None):
    """Per-upstream-commit landed coverage for the PR merged at `ref`.

    Returns a list of {sha, subject, landed, total, coverage, status} where
    status is FULL / PARTIAL / ABSENT (ABSENT = <10% of lines landed).
    A full 'Merge bitcoin#N' Dash subject with ABSENT upstream commits is an
    undeclared partial backport — the finding most easily missed in review.
    """
    shas = git("rev-list", "--reverse", "--no-merges",
               f"{ref}^1..{ref}", check=False).stdout.split()
    out = []
    for sha in shas:
        subj = git("log", "-1", "--format=%s", sha, check=False).stdout.strip()
        files = parse_diff_files(git("diff", f"{sha}~1", sha, check=False).stdout)
        landed = total = 0
        for path, hunks in files.items():
            # Only lines that survive to the upstream PR's own final tree are
            # expected in Dash — later commits in the same upstream PR often
            # rewrite earlier ones, and that supersession is not Dash drift.
            up_final = blob_counts(ref, path)
            if up_final is None:
                continue
            head_blob = blob_counts(head, path)
            base_blob = blob_counts(merge_base, path)
            if head_blob is None:
                renamed = resolve_renamed(head, path, blob_counts(f"{ref}~1", path))
                if renamed:
                    head_blob = blob_counts(head, renamed)
                    base_blob = blob_counts(merge_base, renamed)
            na2, nd2 = file_expectations(hunks, up_final)
            if cross_filter is not None:
                na2, nd2, _ = cross_filter(key, na2, nd2)
            if not na2 and not nd2:
                continue
            if head_blob is None:
                total += len(na2) + len(nd2)
                continue
            # Presence-based: coverage asks "is this upstream content in the
            # Dash head tree at all" — content that arrived via an earlier
            # partial backport still counts as covered. Only distinctive
            # lines are counted; braces/includes match pre-existing content
            # and would inflate coverage of genuinely dropped commits.
            def distinctive(line):
                return len(line) >= 12 and re.search(r"[A-Za-z_]{4,}", line)
            for line in set(na2):
                if not distinctive(line):
                    continue
                need = na2.count(line)
                total += need
                landed += min(need, count_in(head_blob, line))
            for line in set(nd2):
                if not distinctive(line):
                    continue
                need = nd2.count(line)
                total += need
                landed += need if count_in(head_blob, line) == 0 else 0
        cov = (landed / total) if total else 1.0
        status = "FULL" if cov >= 0.95 else ("ABSENT" if cov < 0.10 else "PARTIAL")
        out.append({"sha": sha[:11], "subject": subj[:80], "landed": landed,
                    "total": total, "coverage": round(cov, 2), "status": status})
    return out


def file_class(path):
    p = path.lower()
    if p.startswith("doc/"):
        return "DOCS_ONLY", "LOW"
    if p.startswith("test/"):
        return ("TEST_FRAMEWORK", "MEDIUM") if "test_framework" in p else ("TEST_ONLY", "LOW")
    if p.startswith(("src/rpc/", "src/rest/")) or any(
        k in p for k in ("versionbits", "deployment", "consensus", "chainparams", "fork")
    ):
        return "SRC_RPC_OR_CONSENSUS", "HIGH"
    if p.startswith("src/"):
        return "SRC_NONCRITICAL", "MEDIUM"
    return "OTHER", "LOW"


def prereq_hint(missing_line, search_refs):
    """Best-effort: which fetched upstream commit introduced a missing line."""
    token = missing_line.strip()[:60]
    if len(token) < 8 or not re.search(r"[A-Za-z_]{4,}", token) or not search_refs:
        return None
    r = git("log", "--oneline", "-S", token, "-1", *search_refs, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.strip().splitlines()[0]


# ---- report ---------------------------------------------------------------
def verdict_for(report_entries):
    worst = "APPROVE"
    for e in report_entries:
        if e.get("error"):
            return "ERROR"
        for f in e.get("findings", []):
            if f.get("declared_partial"):
                worst = max_verdict(worst, "REQUIRES_REVIEW")
            elif f["risk"] == "HIGH":
                return "BLOCK"
            else:
                worst = max_verdict(worst, "REQUIRES_REVIEW")
    return worst


def max_verdict(a, b):
    order = {"APPROVE": 0, "REQUIRES_REVIEW": 1, "BLOCK": 2, "ERROR": 3}
    return a if order[a] >= order[b] else b


def emit_markdown(result):
    lines = [f"# Backport review: {result['repo']} PR #{result['pr']}",
             "",
             f"- head `{result['head']}` / base `{result['merge_base']}`",
             f"- verdict: **{result['verdict']}**"]
    if result.get("title_markers_missing_in_commits"):
        lines.append(
            "- WARNING: PR title claims backports not found in any commit: "
            + ", ".join(result["title_markers_missing_in_commits"])
            + " (stale PR metadata?)")
    if result.get("non_marker_commits"):
        lines.append("- commits without upstream markers: "
                     + ", ".join(result["non_marker_commits"]))
    lines.append("")
    for e in result["report"]:
        kind = e["kind"] + (" (declared partial)" if e["partial"] else "")
        lines.append(f"## {e['upstream']} — {kind}")
        for sha, subj in e.get("dash_commits", [(e["dash_commit"], e["subject"])]):
            lines.append(f"- dash commit `{sha}`: {subj}")
        if e.get("error"):
            lines.append(f"- ERROR: {e['error']}")
        elif e.get("dependency_ok"):
            lines.append(f"- referenced PR already backported: `{e['backported_in']}`")
        elif not e["findings"]:
            lines.append("- all upstream hunks landed (or were previously covered)")
        if e.get("superseded_lines"):
            lines.append(f"- {e['superseded_lines']} expectation line(s) superseded by "
                         "other upstream PRs backported in this same Dash PR (excluded)")
        if e.get("upstream_commits"):
            partials = [c for c in e["upstream_commits"] if c["status"] != "FULL"]
            n_full = len(e["upstream_commits"]) - len(partials)
            lines.append(f"- upstream commit coverage: {n_full}/{len(e['upstream_commits'])} fully landed")
            for c in partials:
                lines.append(f"    - {c['status']} `{c['sha']}` {c['subject']} "
                             f"({c['landed']}/{c['total']} lines)")
        for f in e["findings"]:
            note = " — declared partial, confirm the omission is the intended one" if f.get("declared_partial") else ""
            lines.append(f"- **{f['status']}** [{f['risk']}/{f['class']}] `{f['path']}`{note}")
            if f.get("dash_path"):
                lines.append(f"    - dash counterpart (renamed): `{f['dash_path']}`")
            if f.get("landed_elsewhere"):
                lines.append(f"    - content found in `{f['landed_elsewhere']}` — likely rename/move, confirm")
            for a in f["missing_adds"]:
                lines.append(f"    - missing: `{a[:120]}`")
            for d in f["lingering_dels"]:
                lines.append(f"    - still present: `{d[:120]}`")
            if f.get("prereq_hint"):
                lines.append(f"    - introduced upstream by: {f['prereq_hint']}")
        lines.append("")
    lines.append("## Review guidance")
    lines.append("- DROPPED/FILE_ABSENT: upstream content this PR claims to land is missing — "
                 "port it or justify the omission in the PR description (release notes and tests included).")
    lines.append("- PARTIAL: inspect the exact missing lines above; adaptations are fine, silent drops are not.")
    lines.append("- PREREQ_MISSING?: upstream edits context Dash never had — check for a missing "
                 "prerequisite PR or verify the Dash-adapted equivalent covers the same behavior.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pr_number")
    ap.add_argument("--repo", default="dashpay/dash")
    ap.add_argument("--base", default="origin/develop")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    ap.add_argument("--keep-refs", action="store_true",
                    help="keep fetched refs/backport-check/* refs for follow-up digging")
    args = ap.parse_args()

    pr = json.loads(gh("pr", "view", args.pr_number, "--repo", args.repo,
                       "--json", "title,commits,headRefOid,mergeCommit").stdout)
    head = pr["headRefOid"]
    merge_base = git("merge-base", head, args.base).stdout.strip()
    # For an already-merged PR the head is an ancestor of the base branch, so
    # merge-base(head, base) == head and every hunk would look un-landed.
    # Use the merge commit's first parent (state of develop just before the
    # merge) as the base instead.
    if merge_base == head and pr.get("mergeCommit"):
        mc = pr["mergeCommit"]["oid"]
        git("fetch", "--quiet", "origin", mc, check=False)
        merge_base = git("rev-parse", f"{mc}^1", check=False).stdout.strip() or merge_base

    # Group by upstream PR: several Dash commits may reference the same
    # upstream PR (main backport + adaptation/follow-up commits). Analyze each
    # upstream PR once; 'backport' kind wins over 'reference'.
    groups = {}
    non_marker = []
    for c in pr["commits"]:
        subj = c["messageHeadline"]
        mks = parse_markers(subj)
        if not mks:
            non_marker.append(c["oid"][:11])
        for mk in mks:
            key = (mk["repo"], mk["num"])
            g = groups.setdefault(key, {"repo": mk["repo"], "num": mk["num"],
                                        "kind": mk["kind"], "partial": mk["partial"],
                                        "commits": []})
            if mk["kind"] == "backport":
                g["kind"] = "backport"
            g["partial"] = g["partial"] or mk["partial"]
            g["commits"].append((c["oid"][:11], subj))
    mappings = [(g, g["commits"][0][0], g["commits"][0][1]) for g in groups.values()]

    # stale-metadata check: markers in the PR title must appear in some commit
    title_markers = {(m["repo"], m["num"]) for m in parse_markers(pr["title"])}
    commit_markers = {(mk["repo"], mk["num"]) for mk, _, _ in mappings}
    stale = sorted(f"{r}#{n}" for r, n in title_markers - commit_markers)

    resolved = {}
    fetched_refs = []
    for mk, _, _ in mappings:
        key = (mk["repo"], mk["num"])
        if key in resolved:
            continue
        resolved[key] = None
        sha = find_upstream_merge(mk["repo"], mk["num"])
        if sha:
            ref = f"refs/backport-check/{mk['repo'].replace('/', '_')}-{mk['num']}"
            fr = git("fetch", "--quiet", f"https://github.com/{mk['repo']}.git",
                     f"{sha}:{ref}", check=False)
            if fr.returncode == 0:
                resolved[key] = ref
                fetched_refs.append(ref)

    # Cross-PR supersession within this Dash PR: stacked backports routinely
    # rewrite each other (e.g. #25685 refactors lines #25647 introduced). An
    # expectation of PR A that another PR in the same set deletes (or, for
    # removals, re-adds) is satisfied by the composed final tree, not drift.
    net_adds, net_dels = {}, {}
    for key, ref in resolved.items():
        if not ref:
            continue
        adds, dels = set(), set()
        for _path, hunks in parse_diff_files(git("diff", f"{ref}~1", ref).stdout).items():
            a, d = file_expectations(hunks)
            adds.update(a)
            dels.update(d)
        net_adds[key], net_dels[key] = adds, dels

    key_order = {}
    for mk, _, _ in mappings:
        key_order.setdefault((mk["repo"], mk["num"]), len(key_order))

    def cross_filter(key, na, nd):
        """Drop expectations superseded by *later* upstream PRs in this set
        (composition order = Dash commit order). An earlier PR cannot
        supersede a later one — a later PR's deletion of an earlier add, or
        re-add of an earlier removal, stands in the final tree.
        Returns (na, nd, superseded_count)."""
        mine = key_order.get(key, 0)
        later_dels = set().union(*(net_dels[k] for k in net_dels
                                   if key_order.get(k, 0) > mine), set())
        later_adds = set().union(*(net_adds[k] for k in net_adds
                                   if key_order.get(k, 0) > mine), set())
        na2 = [a for a in na if a not in later_dels]
        nd2 = [d for d in nd if d not in later_adds]
        return na2, nd2, (len(na) - len(na2)) + (len(nd) - len(nd2))

    report = []
    for mk, dash_sha, subj in mappings:
        ref = resolved.get((mk["repo"], mk["num"]))
        entry = {"upstream": f"{mk['repo']}#{mk['num']}", "kind": mk["kind"],
                 "dash_commits": mk.get("commits", []),
                 "partial": mk["partial"], "dash_commit": dash_sha[:11],
                 "subject": subj, "findings": []}

        if mk["kind"] == "reference":
            # follow-up commits assert their referenced PR is already in history
            marker = ("gui" if mk["repo"].endswith("/gui") else "bitcoin") + f"#{mk['num']}"
            r = git("log", "--oneline", "-1", f"--grep={marker}\\b", merge_base, check=False)
            if r.stdout.strip():
                entry["dependency_ok"] = True
                entry["backported_in"] = r.stdout.strip().splitlines()[0]
            else:
                entry["findings"].append({
                    "path": "(history)",
                    "status": "REFERENCED_PR_NOT_BACKPORTED",
                    "class": "SRC_NONCRITICAL", "risk": "MEDIUM",
                    "missing_adds": [f"no commit matching '{marker}' at PR base; "
                                     "a follow-up for an un-backported PR is suspicious"],
                    "lingering_dels": []})
            report.append(entry)
            continue

        if not ref:
            entry["error"] = "could not resolve/fetch upstream merge commit"
            report.append(entry)
            continue

        up_files = parse_diff_files(git("diff", f"{ref}~1", ref).stdout)
        for path, hunks in sorted(up_files.items()):
            head_blob = blob_counts(head, path)
            base_blob = blob_counts(merge_base, path)
            renamed_to = None
            if head_blob is None:
                renamed_to = resolve_renamed(head, path, blob_counts(f"{ref}~1", path))
                if renamed_to:
                    head_blob = blob_counts(head, renamed_to)
                    base_blob = blob_counts(merge_base, renamed_to)
            na, nd = file_expectations(hunks)
            na, nd, n_sup = cross_filter((mk["repo"], mk["num"]), na, nd)
            if n_sup:
                entry["superseded_lines"] = entry.get("superseded_lines", 0) + n_sup
            if not na and not nd:
                continue
            if head_blob is None:
                status, ma, ld = "FILE_ABSENT", na, []
            else:
                status, ma, ld, _, _ = hunk_status(na, nd, base_blob, head_blob)
            if status in ("LANDED", "ALREADY_PRESENT"):
                continue
            cls, risk = file_class(path)
            finding = {"path": path, "status": status,
                       "class": cls, "risk": risk,
                       "declared_partial": mk["partial"],
                       "missing_adds": ma[:6], "lingering_dels": ld[:4]}
            if renamed_to:
                finding["dash_path"] = renamed_to
            if status in ("DROPPED", "FILE_ABSENT") and ma:
                elsewhere = find_elsewhere(head, ma)
                if elsewhere and elsewhere != path:
                    finding["landed_elsewhere"] = elsewhere
                    finding["risk"] = "LOW"
            if status == "PREREQ_MISSING?" and ld:
                hint = prereq_hint(ld[0], fetched_refs)
                if hint:
                    finding["prereq_hint"] = hint
            entry["findings"].append(finding)

        # per-upstream-commit coverage: catches undeclared partial backports
        # (subject claims a full Merge but whole upstream commits never landed)
        coverage = upstream_commit_coverage(ref, head, merge_base,
                                            cross_filter=cross_filter,
                                            key=(mk["repo"], mk["num"]))
        entry["upstream_commits"] = coverage
        absent = [c for c in coverage if c["status"] == "ABSENT"]
        if absent and not mk["partial"]:
            entry["findings"].insert(0, {
                "path": "(commit metadata)",
                "status": "UNDECLARED_PARTIAL", "class": "METADATA",
                "risk": "MEDIUM", "declared_partial": False,
                "missing_adds": [
                    f"{c['sha']} {c['subject']} — {c['landed']}/{c['total']} lines landed"
                    for c in absent],
                "lingering_dels": []})
        report.append(entry)

    result = {"repo": args.repo, "pr": args.pr_number, "head": head[:11],
              "merge_base": merge_base[:11], "report": report,
              "non_marker_commits": non_marker,
              "title_markers_missing_in_commits": stale}
    result["verdict"] = verdict_for(report)

    if not args.keep_refs:
        for ref in fetched_refs:
            git("update-ref", "-d", ref, check=False)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(emit_markdown(result))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"review_backport_pr.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
