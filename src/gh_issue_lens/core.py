"""Core logic for gh-issue-lens."""

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import requests

DEFAULT_CACHE_DB = ".gh_issue_lens_cache.db"


def get_graphql_query():
    """
    GraphQL query used to fetch open issues.

    The page size is intentionally small to reduce the chance of timeouts
    and GitHub 502 responses on very large repositories.
    """
    return """
query($owner: String!, $repo: String!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    issues(
      first: 20,
      after: $cursor,
      states: OPEN,
      orderBy: {
        field: CREATED_AT,
        direction: DESC
      }
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        title
        url
        createdAt
        body
        labels(first: 10) {
          nodes {
            name
          }
        }
        assignees(first: 10) {
          nodes {
            login
          }
        }
        comments(first: 20) {
          nodes {
            author {
              login
              __typename
            }
            body
          }
        }
        timelineItems(itemTypes: [CROSS_REFERENCED_EVENT], first: 10) {
          nodes {
            ... on CrossReferencedEvent {
              source {
                ... on PullRequest {
                  state
                  number
                  createdAt
                  updatedAt
                  merged
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


### Helpers
def parse_iso_datetime(value):
    """Parse a GitHub ISO-8601 timestamp into a timezone-aware datetime."""
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def days_since(value, now=None):
    """Whole days elapsed since an ISO timestamp. Unknown timestamps count as fresh (0)."""
    parsed = parse_iso_datetime(value)

    if parsed is None:
        return 0

    if now is None:
        now = datetime.now(timezone.utc)

    return max(0, (now - parsed).days)


def classify_availability(linked_prs, stale_pr_days):
    """
    Classify how available an issue is for a newcomer, based on its linked PRs.

    Returns:
        (has_fresh_open_pr, has_stale_open_pr, has_closed_unmerged_pr, availability)
    """
    open_prs = [pr for pr in linked_prs if pr["state"] == "OPEN"]

    fresh_open_prs = [pr for pr in open_prs if days_since(pr["updated_at"]) < stale_pr_days]

    stale_open_prs = [pr for pr in open_prs if days_since(pr["updated_at"]) >= stale_pr_days]

    merged_prs = [pr for pr in linked_prs if pr["merged"] or pr["state"] == "MERGED"]

    closed_unmerged_prs = [pr for pr in linked_prs if pr["state"] == "CLOSED" and not pr["merged"]]

    if fresh_open_prs:
        availability = "likely_taken"
    elif stale_open_prs:
        availability = "stale_pr_open"
    elif merged_prs:
        availability = "merged_pr_linked"
    elif closed_unmerged_prs:
        availability = "pr_closed_unmerged"
    else:
        availability = "no_linked_pr"

    return (
        bool(fresh_open_prs),
        bool(stale_open_prs),
        bool(closed_unmerged_prs),
        availability,
    )


def init_cache(cache_db):
    """Create or open the SQLite cache."""
    conn = sqlite3.connect(cache_db)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cached_issues (
            repo TEXT NOT NULL,
            issue_number INTEGER NOT NULL,
            url TEXT,
            cached_at TEXT NOT NULL,
            PRIMARY KEY (repo, issue_number)
        )
        """
    )

    conn.commit()
    return conn


def is_issue_cached(conn, repo_full_name, issue_number):
    """Return True if this issue number is already cached."""
    cur = conn.execute(
        """
        SELECT 1
        FROM cached_issues
        WHERE repo = ? AND issue_number = ?
        LIMIT 1
        """,
        (repo_full_name.lower(), issue_number),
    )

    return cur.fetchone() is not None


def cache_issues(conn, repo_full_name, issues):
    """Insert newly exported issues into the cache."""
    if not issues:
        return

    now = datetime.now(timezone.utc).isoformat()

    rows = [
        (
            repo_full_name.lower(),
            issue["number"],
            issue.get("url"),
            now,
        )
        for issue in issues
    ]

    conn.executemany(
        """
        INSERT OR IGNORE INTO cached_issues (
            repo,
            issue_number,
            url,
            cached_at
        )
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )

    conn.commit()


def command_signature(signature_inputs):
    """
    Return a stable short hash of the command options that affect
    which issues get exported.

    Used to detect when resuming would mix two different result sets.
    """
    payload = json.dumps(signature_inputs, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

def fetch_issues(
    owner,
    repo,
    labels,
    depth,
    token,
    output_filename,
    exclude_open_prs=False,
    use_cache=False,
    cache_db=DEFAULT_CACHE_DB,
    cache_stop=False,
    stale_pr_days=90,
    signature="",
):
    """
    Fetch issues from GitHub and append them to a JSONL file.

    Returns the number of newly exported issues in this run.
    """
    url = "https://api.github.com/graphql"

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "gh-issue-lens",
    }

    query = get_graphql_query()

    has_labels = bool(labels and len(labels) > 0)
    target_labels_lower = [label.lower() for label in labels] if has_labels else []

    has_next_page = True
    cursor = None
    page_num = 1
    extracted_count = 0

    checkpoint_file = f".checkpoint_{owner}_{repo}.json"

    conn = init_cache(cache_db) if use_cache else None
    repo_key = f"{owner}/{repo}".lower()

    cached_skipped = 0
    no_new_pages = 0

    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                cp_data = json.load(f)

            if cp_data.get("signature") != signature:
                print(
                    "Checkpoint found, but the command options changed since "
                    "the interrupted run."
                )
                print(
                    "Discarding the old checkpoint and starting fresh to avoid "
                    "mixing result sets."
                )
                os.remove(checkpoint_file)

                if not use_cache:
                    open(output_filename, "w", encoding="utf-8").close()
            else:
                cursor = cp_data.get("cursor")
                page_num = cp_data.get("page_num", 1)
                extracted_count = cp_data.get("extracted_count", 0)

                print(
                    f"Resuming from checkpoint. Starting at page {page_num}, "
                    f"{extracted_count} issues already fetched."
                )
        except Exception as e:
            print(f"Warning: Could not read checkpoint file: {e}")

    label_text = f" (Filtering by ANY of: {', '.join(labels)})" if has_labels else ""

    print(f"Starting extraction for {owner}/{repo}{label_text}...")
    print(f"Target depth: {depth} matches.")

    try:
        while has_next_page and extracted_count < depth:
            variables = {
                "owner": owner,
                "repo": repo,
                "cursor": cursor,
            }

            print(f" -> Scanning page {page_num} (Fetching up to 20 open issues from GitHub)...")

            try:
                response = requests.post(
                    url,
                    json={
                        "query": query,
                        "variables": variables,
                    },
                    headers=headers,
                    timeout=60,
                )
            except requests.exceptions.RequestException as exc:
                print(f"Network error: {exc}")
                print("Progress saved to checkpoint. Run the command again to resume.")
                sys.exit(1)

            if response.status_code != 200:
                print(f"Error {response.status_code}: {response.text}")
                print("Progress saved to checkpoint. Run the command again to resume.")
                sys.exit(1)

            try:
                data = response.json()
            except ValueError as exc:
                print(f"Could not parse GitHub response: {exc}")
                print("Progress saved to checkpoint. Run the command again to resume.")
                sys.exit(1)

            if "errors" in data:
                print(f"GraphQL Error: {data['errors'][0]['message']}")
                print("Progress saved to checkpoint. Run the command again to resume.")
                sys.exit(1)

            repository = data.get("data", {}).get("repository")

            if not repository:
                print(f"Repository {owner}/{repo} not found.")
                sys.exit(1)

            issues_data = repository.get("issues", {})
            nodes = issues_data.get("nodes", [])

            page_issues = []
            eligible_before_cache = 0

            for issue in nodes:
                if not issue:
                    continue

                issue_labels = [
                    label_node["name"].lower()
                    for label_node in issue.get("labels", {}).get("nodes", [])
                    if label_node
                ]

                if has_labels:
                    if not any(label in issue_labels for label in target_labels_lower):
                        continue

                assignees = [
                    assignee["login"]
                    for assignee in issue.get("assignees", {}).get("nodes", [])
                    if assignee
                ]

                comments = []

                for comment in issue.get("comments", {}).get("nodes", []):
                    if not comment:
                        continue

                    author = comment.get("author")

                    if author and author.get("__typename") != "Bot":
                        comments.append(
                            {
                                "author": author.get("login"),
                                "body": comment.get("body"),
                            }
                        )

                linked_prs = []
                for event in issue.get("timelineItems", {}).get("nodes", []):
                    if not event:
                        continue

                    source = event.get("source")
                    if not source:
                        continue

                    linked_prs.append(
                        {
                            "number": source.get("number"),
                            "state": source.get("state"),
                            "merged": bool(source.get("merged")),
                            "created_at": source.get("createdAt"),
                            "updated_at": source.get("updatedAt"),
                        }
                    )

                has_open_pr = any(pr["state"] == "OPEN" for pr in linked_prs)

                has_fresh_open_pr, has_stale_open_pr, has_closed_unmerged_pr, availability = (
                    classify_availability(linked_prs, stale_pr_days)
                )

                if exclude_open_prs and has_fresh_open_pr:
                    continue

                eligible_before_cache += 1

                if conn is not None and is_issue_cached(conn, repo_key, issue.get("number")):
                    cached_skipped += 1
                    continue

                page_issues.append(
                    {
                        "number": issue.get("number"),
                        "title": issue.get("title"),
                        "url": issue.get("url"),
                        "created_at": issue.get("createdAt"),
                        "is_assigned": len(assignees) > 0,
                        "assigned_to": assignees,
                        "has_open_pr_against_it": has_open_pr,
                        "has_fresh_open_pr": has_fresh_open_pr,
                        "has_stale_open_pr": has_stale_open_pr,
                        "availability": availability,
                        "linked_prs": linked_prs,
                        "labels": issue_labels,
                        "body": issue.get("body"),
                        "comments": comments,
                    }
                )

                if extracted_count + len(page_issues) >= depth:
                    break

            with open(output_filename, "a", encoding="utf-8") as f:
                for item in page_issues:
                    f.write(json.dumps(item) + "\n")

            if conn is not None and page_issues:
                cache_issues(conn, repo_key, page_issues)

            extracted_count += len(page_issues)

            page_info = issues_data.get("pageInfo", {})
            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
            page_num += 1

            cache_should_stop = False

            if conn is not None and cache_stop:
                if eligible_before_cache > 0 and len(page_issues) == 0:
                    no_new_pages += 1

                    if no_new_pages >= 3:
                        cache_should_stop = True
                else:
                    no_new_pages = 0

            if has_next_page and extracted_count < depth and not cache_should_stop:
                with open(checkpoint_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "cursor": cursor,
                            "page_num": page_num,
                            "extracted_count": extracted_count,
                            "signature": signature,
                        },
                        f,
                    )
            else:
                if os.path.exists(checkpoint_file):
                    os.remove(checkpoint_file)

            if cache_should_stop:
                print("Stopping early: 3 consecutive pages contained only cached eligible issues.")
                break

        if use_cache:
            print(f"Cached issues skipped: {cached_skipped}")

        return extracted_count
    finally:
        if conn is not None:
            conn.close()
