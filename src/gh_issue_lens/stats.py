"""Repository health stats to help beginners choose a community."""

import argparse
import html as html_mod
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

import requests

from .core import parse_iso_datetime

API_REST = "https://api.github.com"
API_GRAPHQL = "https://api.github.com/graphql"

STATS_QUERY = """
query(
  $owner: String!,
  $repo: String!,
  $mergedWeekQuery: String!,
  $mergedMonthQuery: String!
) {
  repository(owner: $owner, name: $repo) {
    openIssues: issues(states: OPEN, first: 1) { totalCount }
    goodFirstIssues: issues(states: OPEN, labels: ["good first issue"], first: 1) { totalCount }
    helpWantedIssues: issues(states: OPEN, labels: ["help wanted"], first: 1) { totalCount }
    recentIssues: issues(states: OPEN, first: 100, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        createdAt
        updatedAt
        author { login }
        comments(first: 5) {
          nodes {
            createdAt
            author { login __typename }
          }
        }
      }
    }
  }
  mergedWeek: search(type: ISSUE, query: $mergedWeekQuery, first: 1) { issueCount }
  mergedMonth: search(type: ISSUE, query: $mergedMonthQuery, first: 1) { issueCount }
}
"""


def parse_repo_lines(lines):
    """Parse owner/repo references, skipping blanks and # comments."""
    repos = []

    for raw in lines:
        line = raw.strip()

        if not line or line.startswith("#"):
            continue

        if line.count("/") != 1:
            raise ValueError(f"Invalid repo reference: {line!r} (expected owner/repo)")

        repos.append(line)

    seen = set()
    unique = []

    for repo in repos:
        if repo not in seen:
            seen.add(repo)
            unique.append(repo)

    return unique


def load_repos(cli_repos, repos_file):
    repos = list(cli_repos or [])

    if repos_file:
        with open(repos_file, "r", encoding="utf-8") as f:
            repos.extend(parse_repo_lines(f.readlines()))
    else:
        repos = parse_repo_lines(repos)

    return repos


def fmt_hours(hours):
    if hours is None:
        return "-"

    if hours < 48:
        return f"{hours:.0f}h"

    return f"{hours / 24:.1f}d"


def fmt_rate(rate):
    if rate is None:
        return "-"

    return f"{rate * 100:.0f}%"


def compute_score(stats):
    """
    Beginner-friendliness score, 0-100.

    - up to 30: median time to first human reply on recent issues
    - up to 20: beginner funnel (good first issue + help wanted)
    - up to 15: share of recent issues that got an answer
    - up to 15: share of recent issues that are not stale
    - up to 12: merged PRs in the last 7 days (community merge pace)
    - up to 8:  recency of the last code push
    """
    if stats.get("error"):
        return None

    score = 0

    median_reply = stats.get("median_first_reply_hours")

    if median_reply is not None:
        if median_reply <= 12:
            score += 30
        elif median_reply <= 48:
            score += 24
        elif median_reply <= 168:
            score += 15
        else:
            score += 5

    funnel = (stats.get("good_first_issues") or 0) + (stats.get("help_wanted_issues") or 0)
    score += min(20, funnel // 5)

    unanswered = stats.get("unanswered_rate")

    if unanswered is not None:
        score += round((1 - unanswered) * 15)

    stale = stats.get("stale_rate")

    if stale is not None:
        score += round((1 - stale) * 15)

    merged_week = stats.get("merged_prs_last_7_days") or 0

    if merged_week >= 20:
        score += 12
    elif merged_week >= 7:
        score += 10
    elif merged_week >= 3:
        score += 7
    elif merged_week >= 1:
        score += 4

    pushed_days = stats.get("pushed_days_ago")

    if pushed_days is not None:
        if pushed_days <= 7:
            score += 8
        elif pushed_days <= 30:
            score += 5
        elif pushed_days <= 90:
            score += 2

    return min(100, score)


def verdict_for_score(score):
    """Return (emoji, short label, plain-English label) for a score."""
    if score is None:
        return ("❓", "?", "Unknown")

    if score >= 75:
        return ("🌱", "GREAT", "Great place to start")

    if score >= 55:
        return ("👍", "GOOD", "Good option")

    if score >= 35:
        return ("⚠️", "MIXED", "Mixed signals")

    return ("🧊", "COLD", "Hard to get help")


def fetch_repo_stats(repo_full_name, token, stale_days=180, now=None):
    """Fetch community-health stats for one repository (2 API calls)."""
    owner, repo = repo_full_name.split("/", 1)

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "gh-issue-lens",
        "Accept": "application/vnd.github+json",
    }

    rest = requests.get(f"{API_REST}/repos/{owner}/{repo}", headers=headers, timeout=30)

    if rest.status_code == 404:
        return {"repo": repo_full_name, "error": "repository not found or no access"}

    if rest.status_code in (403, 429):
        return {"repo": repo_full_name, "error": f"rate limited (HTTP {rest.status_code})"}

    if rest.status_code != 200:
        return {"repo": repo_full_name, "error": f"HTTP {rest.status_code}"}

    meta = rest.json()

    if now is None:
        now = datetime.now(timezone.utc)

    week_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    variables = {
        "owner": owner,
        "repo": repo,
        "mergedWeekQuery": f"repo:{owner}/{repo} is:pr is:merged merged:>{week_date}",
        "mergedMonthQuery": f"repo:{owner}/{repo} is:pr is:merged merged:>{month_date}",
    }

    gql = requests.post(
        API_GRAPHQL,
        json={"query": STATS_QUERY, "variables": variables},
        headers=headers,
        timeout=60,
    )

    if gql.status_code != 200:
        return {"repo": repo_full_name, "error": f"GraphQL HTTP {gql.status_code}"}

    data = gql.json()

    if "errors" in data:
        return {"repo": repo_full_name, "error": data["errors"][0]["message"]}

    payload = data["data"]
    repo_data = payload["repository"]

    recent = [node for node in repo_data["recentIssues"]["nodes"] if node]

    reply_hours = []
    unanswered = 0
    stale = 0

    for issue in recent:
        updated = parse_iso_datetime(issue.get("updatedAt"))

        if updated and (now - updated) >= timedelta(days=stale_days):
            stale += 1

        author_login = (issue.get("author") or {}).get("login")
        first_human_comment = None

        for comment in issue.get("comments", {}).get("nodes", []) or []:
            comment_author = comment.get("author") or {}

            if comment_author.get("__typename") == "Bot":
                continue

            if comment_author.get("login") == author_login:
                continue

            first_human_comment = comment
            break

        created = parse_iso_datetime(issue.get("createdAt"))

        if first_human_comment and created:
            comment_created = parse_iso_datetime(first_human_comment.get("createdAt"))

            if comment_created:
                reply_hours.append((comment_created - created).total_seconds() / 3600.0)
        else:
            unanswered += 1

    sample = len(recent)

    pushed = parse_iso_datetime(meta.get("pushed_at"))

    stats = {
        "repo": repo_full_name,
        "stars": meta.get("stargazers_count"),
        "forks": meta.get("forks_count"),
        "language": meta.get("language"),
        "archived": meta.get("archived", False),
        "pushed_at": meta.get("pushed_at"),
        "pushed_days_ago": (now - pushed).days if pushed else None,
        "active_last_30_days": bool(pushed and (now - pushed) <= timedelta(days=30)),
        "open_issues": repo_data["openIssues"]["totalCount"],
        "good_first_issues": repo_data["goodFirstIssues"]["totalCount"],
        "help_wanted_issues": repo_data["helpWantedIssues"]["totalCount"],
        "merged_prs_last_7_days": payload.get("mergedWeek", {}).get("issueCount", 0),
        "merged_prs_last_30_days": payload.get("mergedMonth", {}).get("issueCount", 0),
        "sample_size": sample,
        "median_first_reply_hours": round(statistics.median(reply_hours), 1)
        if reply_hours
        else None,
        "unanswered_rate": round(unanswered / sample, 2) if sample else None,
        "stale_rate": round(stale / sample, 2) if sample else None,
    }

    stats["beginner_score"] = compute_score(stats)

    return stats


def render_table(stats_list):
    header = (
        f"{'REPO':<30}{'SCORE':>6}{'VERDICT':>9}{'OPEN':>7}{'GFI':>6}{'HW':>6}"
        f"{'REPLY':>8}{'UNANSW':>8}{'STALE':>7}{'PR/WK':>7}"
    )

    lines = [header, "-" * len(header)]

    for stats in stats_list:
        if stats.get("error"):
            lines.append(f"{stats['repo']:<30}ERROR: {stats['error']}")
            continue

        _, short, _ = verdict_for_score(stats["beginner_score"])

        lines.append(
            f"{stats['repo']:<30}"
            f"{stats['beginner_score']:>6}"
            f"{short:>9}"
            f"{stats['open_issues']:>7}"
            f"{stats['good_first_issues']:>6}"
            f"{stats['help_wanted_issues']:>6}"
            f"{fmt_hours(stats['median_first_reply_hours']):>8}"
            f"{fmt_rate(stats['unanswered_rate']):>8}"
            f"{fmt_rate(stats['stale_rate']):>7}"
            f"{stats['merged_prs_last_7_days']:>7}"
        )

    lines.append("")
    lines.append("VERDICT: GREAT >= 75 | GOOD >= 55 | MIXED >= 35 | COLD < 35")

    return "\n".join(lines)


def render_bars(stats_list, width=30):
    ok = [s for s in stats_list if not s.get("error")]

    lines = ["Beginner score (0-100)", ""]

    for stats in sorted(ok, key=lambda item: -(item["beginner_score"] or 0)):
        score = stats["beginner_score"] or 0
        filled = round(width * score / 100)
        bar = "█" * filled + "░" * (width - filled)
        emoji, short, _ = verdict_for_score(score)
        lines.append(f"{stats['repo']:<30}{bar} {score:>3} {emoji} {short}")

    return "\n".join(lines)


def stats_to_json(stats_list, stale_days):
    return json.dumps(
        {
            "tool": "gh-issue-lens",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stale_days": stale_days,
            "note": (
                "median_first_reply_hours, unanswered_rate and stale_rate are "
                "measured on the 100 most recent open issues."
            ),
            "repos": stats_list,
        },
        indent=2,
    )


def plain_english_lines(stats, stale_days):
    """Short human sentences a beginner can scan in seconds."""
    lines = []

    median = stats.get("median_first_reply_hours")

    if median is None:
        lines.append("Most recent issues got <b>no reply at all</b> — expect slow or no help here.")
    elif median <= 48:
        lines.append(
            f"New issues usually get a first reply in about <b>{fmt_hours(median)}</b> — you won't be left alone."
        )
    elif median <= 168:
        lines.append(
            f"First replies take about <b>{fmt_hours(median)}</b> on average — reasonable, not fast."
        )
    else:
        lines.append(
            f"First replies take about <b>{fmt_hours(median)}</b> — help can be slow in this community."
        )

    lines.append(
        f"<b>{stats['good_first_issues']}</b> 'good first issue' and "
        f"<b>{stats['help_wanted_issues']}</b> 'help wanted' issues are open right now."
    )

    merged_week = stats.get("merged_prs_last_7_days") or 0
    merged_month = stats.get("merged_prs_last_30_days") or 0

    if merged_week >= 10:
        pace = "very active"
    elif merged_week >= 3:
        pace = "active"
    elif merged_week >= 1:
        pace = "slow-moving"
    else:
        pace = "quiet lately"

    lines.append(
        f"The project merged <b>{merged_week} PRs in the last 7 days</b> and "
        f"<b>{merged_month} in the last 30 days</b> — {pace}."
    )

    pushed_days = stats.get("pushed_days_ago")

    if pushed_days is not None:
        lines.append(
            f"Last code push: <b>{pushed_days} day{'s' if pushed_days != 1 else ''} ago</b>."
        )

    lines.append(
        f"<b>{fmt_rate(stats.get('unanswered_rate'))}</b> of the last {stats.get('sample_size')} issues "
        f"got no answer, and <b>{fmt_rate(stats.get('stale_rate'))}</b> are untouched for {stale_days}+ days."
    )

    return lines


def render_html(stats_list, stale_days):
    ok = [s for s in stats_list if not s.get("error")]
    errors = [s for s in stats_list if s.get("error")]

    max_funnel = (
        max(
            [(s["good_first_issues"] + s["help_wanted_issues"]) for s in ok],
            default=1,
        )
        or 1
    )

    cards = []

    for stats in sorted(ok, key=lambda item: -(item["beginner_score"] or 0)):
        score = stats["beginner_score"] or 0
        emoji, short, long = verdict_for_score(score)
        css_class = {"GREAT": "great", "GOOD": "good", "MIXED": "mixed", "COLD": "cold"}.get(
            short, "cold"
        )
        funnel = stats["good_first_issues"] + stats["help_wanted_issues"]
        funnel_pct = round(100 * funnel / max_funnel)

        bullets = "".join(f"<li>{line}</li>" for line in plain_english_lines(stats, stale_days))

        cards.append(
            f"""
    <div class="card">
      <h2>{html_mod.escape(stats["repo"])} <span class="score">{score}/100</span>
        <span class="badge {css_class}">{emoji} {long}</span></h2>
      <div class="bar"><div class="fill {css_class}" style="width:{score}%"></div></div>
      <ul class="plain">{bullets}</ul>
      <h3>Numbers</h3>
      <ul>
        <li>Open issues: <b>{stats["open_issues"]}</b> &middot; Stars: {stats["stars"]} &middot; Language: {html_mod.escape(str(stats["language"]))}</li>
        <li>Beginner funnel vs others: <div class="bar small"><div class="fill funnel" style="width:{funnel_pct}%"></div></div></li>
        <li>Merged PRs: <b>{stats["merged_prs_last_7_days"]}</b> last 7 days &middot; <b>{stats["merged_prs_last_30_days"]}</b> last 30 days</li>
      </ul>
    </div>"""
        )

    error_block = ""

    if errors:
        items = "".join(
            f"<li>{html_mod.escape(e['repo'])}: {html_mod.escape(e['error'])}</li>" for e in errors
        )
        error_block = f"<h2>Errors</h2><ul>{items}</ul>"

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>gh-issue-lens repo report</title>
<style>
  body {{ font-family: sans-serif; margin: 2rem; background: #0d1117; color: #e6edf3; }}
  h1 {{ font-size: 1.4rem; }}
  h3 {{ font-size: 0.85rem; text-transform: uppercase; color: #8b949e; margin-bottom: 0.3rem; }}
  .meta {{ color: #8b949e; margin-bottom: 2rem; }}
  .card {{ border: 1px solid #30363d; border-radius: 8px; padding: 1rem 1.2rem; margin-bottom: 1rem; }}
  .card h2 {{ font-size: 1.1rem; margin-top: 0; }}
  .score {{ color: #3fb950; }}
  ul {{ list-style: none; padding-left: 0; line-height: 1.7; }}
  ul.plain li {{ padding-left: 1.1rem; position: relative; }}
  ul.plain li:before {{ content: "→"; position: absolute; left: 0; color: #8b949e; }}
  .bar {{ background: #21262d; border-radius: 4px; height: 14px; overflow: hidden; margin: 0.4rem 0; }}
  .bar.small {{ display: inline-block; width: 160px; height: 10px; vertical-align: middle; }}
  .fill {{ height: 100%; background: #3fb950; }}
  .fill.good {{ background: #58a6ff; }}
  .fill.mixed {{ background: #d29922; }}
  .fill.cold {{ background: #f85149; }}
  .fill.funnel {{ background: #58a6ff; }}
  .badge {{ padding: 2px 10px; border-radius: 12px; font-size: 0.8rem; white-space: nowrap; }}
  .badge.great {{ background: #12261e; color: #3fb950; }}
  .badge.good {{ background: #12233a; color: #58a6ff; }}
  .badge.mixed {{ background: #2d2a12; color: #d29922; }}
  .badge.cold {{ background: #2d1214; color: #f85149; }}
</style>
</head>
<body>
<h1>gh-issue-lens &mdash; beginner-friendliness report</h1>
<div class="meta">Generated {generated} &middot; stale threshold: {stale_days} days &middot; rates measured on the 100 most recent open issues</div>
{"".join(cards)}
{error_block}
</body>
</html>
"""


def stats_main(argv):
    parser = argparse.ArgumentParser(
        prog="gh-issue-lens stats",
        description=(
            "Compare repositories by beginner-friendliness: maintainer "
            "responsiveness, beginner-issue funnel, merge pace and activity."
        ),
    )

    parser.add_argument(
        "repos",
        nargs="*",
        help="Repositories as owner/repo (e.g., kubernetes/kubernetes)",
    )

    parser.add_argument(
        "--repos-file",
        help="Text file with one owner/repo per line (# comments allowed)",
    )

    parser.add_argument(
        "--json",
        dest="json_out",
        help="Write raw stats JSON to this path. Use '-' to print to stdout.",
    )

    parser.add_argument(
        "--html",
        dest="html_out",
        help="Write a self-contained HTML report with bar charts.",
    )

    parser.add_argument(
        "--stale-days",
        type=int,
        default=180,
        help="Issues untouched for this many days count as stale (default: 180)",
    )

    args = parser.parse_args(argv)

    token = os.getenv("GITHUB_TOKEN")

    if not token:
        print("Error: GITHUB_TOKEN environment variable not set.")
        print("Please run: export GITHUB_TOKEN='your_personal_access_token'")
        sys.exit(1)

    try:
        repos = load_repos(args.repos, args.repos_file)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    if not repos:
        print("Error: no repositories given.")
        print("Example: gh-issue-lens stats kubernetes/kubernetes pandas-dev/pandas")
        print("Or:      gh-issue-lens stats --repos-file repos.txt")
        sys.exit(1)

    results = []

    for index, repo_name in enumerate(repos, 1):
        print(f" -> [{index}/{len(repos)}] Fetching stats for {repo_name}...")
        results.append(fetch_repo_stats(repo_name, token, stale_days=args.stale_days))

    if args.json_out == "-":
        print(stats_to_json(results, args.stale_days))
        return

    print()
    print(render_table(results))
    print()
    print(render_bars(results))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(stats_to_json(results, args.stale_days) + "\n")
        print(f"\nRaw stats saved to {args.json_out}")

    if args.html_out:
        with open(args.html_out, "w", encoding="utf-8") as f:
            f.write(render_html(results, args.stale_days))
        print(f"HTML report saved to {args.html_out}")
