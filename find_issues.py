import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import requests

DEFAULT_CACHE_DB = ".gh_issue_lens_cache.db"


def init_cache(cache_db):
    conn = sqlite3.connect(cache_db)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cached_issues (
            repo TEXT NOT NULL,
            issue_number INTEGER NOT NULL,
            url TEXT,
            cached_at TEXT NOT NULL,
            PRIMARY KEY (repo, issue_number)
        )
    """)

    conn.commit()
    return conn


def is_issue_cached(conn, repo_full_name, issue_number):
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
    if not issues:
        return

    now = datetime.now(timezone.utc).isoformat()

    rows = [(repo_full_name.lower(), issue["number"], issue.get("url"), now) for issue in issues]

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


def get_graphql_query():
    """
    Fetches open issues in maximum batch sizes.
    We request the issue labels here so we can perform the OR logic filter locally in Python,
    bypassing GitHub's strict AND logic for label filtering.
    """
    return """
    query($owner: String!, $repo: String!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        issues(
        first: 20,
        after: $cursor,
        states: OPEN,
        orderBy: {field: CREATED_AT, direction: DESC}
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
            labels(first: 5) {
              nodes {
                name
              }
            }
            assignees(first: 2) {
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
):
    url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
    }

    query = get_graphql_query()
    has_labels = bool(labels and len(labels) > 0)
    target_labels_lower = [label.lower() for label in labels] if has_labels else []

    has_next_page = True
    cursor = None
    page_num = 1
    extracted_count = 0

    # Define the hidden checkpoint file
    checkpoint_file = f".checkpoint_{owner}_{repo}.json"

    conn = init_cache(cache_db) if use_cache else None
    repo_key = f"{owner}/{repo}".lower()
    cached_skipped = 0
    no_new_pages = 0

    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r") as f:
                cp_data = json.load(f)
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
            variables = {"owner": owner, "repo": repo, "cursor": cursor}

            print(f" -> Scanning page {page_num} (Fetching up to 20 open issues from GitHub)...")

            response = requests.post(
                url, json={"query": query, "variables": variables}, headers=headers
            )
            if response.status_code != 200:
                print(f"Error {response.status_code}: {response.text}")
                print("Progress saved to checkpoint. Run the script again to resume.")
                sys.exit(1)

            data = response.json()
            if "errors" in data:
                print(f"GraphQL Error: {data['errors'][0]['message']}")
                print("Progress saved to checkpoint. Run the script again to resume.")
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

                # 1. Evaluate Labels (OR condition implemented locally)
                issue_labels = [
                    label_node["name"].lower()
                    for label_node in issue.get("labels", {}).get("nodes", [])
                    if label_node
                ]

                if has_labels:
                    # Skip this issue entirely if it doesn't contain ANY of our target labels
                    if not any(label in issue_labels for label in target_labels_lower):
                        continue

                # 2. Parse Assignees
                assignees = [a["login"] for a in issue.get("assignees", {}).get("nodes", []) if a]

                # 3. Parse Comments (Filtering out Bots)
                comments = []

                for comment in issue.get("comments", {}).get("nodes", []):
                    if not comment:
                        continue

                    author = comment.get("author")

                    if author and author.get("__typename") != "Bot":
                        comments.append(
                            {"author": author.get("login"), "body": comment.get("body")}
                        )

                # 4. Check for open Pull Requests mentioning this issue
                has_open_pr = False

                for event in issue.get("timelineItems", {}).get("nodes", []):
                    if not event:
                        continue

                    source = event.get("source")

                    if source and source.get("state") == "OPEN":
                        has_open_pr = True
                        break

                if exclude_open_prs and has_open_pr:
                    continue

                eligible_before_cache += 1

                # 5. SQLite cache check
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
                        "labels": issue_labels,
                        "body": issue.get("body"),
                        "comments": comments,
                    }
                )

                # Stop parsing if we hit the depth target mid-page
                if extracted_count + len(page_issues) >= depth:
                    break

            # Write the fully parsed page to the file all at once
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
                # Save state for the NEXT iteration
                with open(checkpoint_file, "w") as f:
                    json.dump(
                        {
                            "cursor": cursor,
                            "page_num": page_num,
                            "extracted_count": extracted_count,
                        },
                        f,
                    )
            else:
                # Finished or reached depth, clean up checkpoint
                if os.path.exists(checkpoint_file):
                    os.remove(checkpoint_file)

            if cache_should_stop:
                print("Stopping early: 3 consecutive pages contained only cached eligible issues.")
                break

    finally:
        if conn is not None:
            conn.close()

    if use_cache:
        print(f"Cached issues skipped: {cached_skipped}")

    return extracted_count


def main():
    parser = argparse.ArgumentParser(
        description="Fetch open issues from a GitHub repository to find beginner-friendly tasks."
    )
    parser.add_argument("owner", help="GitHub repository owner (e.g., 'kubernetes')")
    parser.add_argument("repo", help="GitHub repository name (e.g., 'kubernetes')")
    parser.add_argument(
        "-l",
        "--labels",
        nargs="+",
        help="Filter by up to 5 labels. Labels are ORed (e.g., -l 'bug' 'good first issue')",
        default=[],
    )
    parser.add_argument(
        "-d",
        "--depth",
        type=int,
        help="Maximum number of issues to fetch (default: 100)",
        default=100,
    )
    parser.add_argument("-o", "--output", help="Output JSONL filename", default=None)
    parser.add_argument(
        "--exclude-open-prs",
        action="store_true",
        help="Skip issues that already have an open pull request against them.",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Enable SQLite caching to avoid exporting issues seen in previous runs.",
    )
    parser.add_argument(
        "--cache-db",
        default=DEFAULT_CACHE_DB,
        help=f"Path to SQLite cache file. Default: {DEFAULT_CACHE_DB}",
    )
    parser.add_argument(
        "--cache-stop",
        action="store_true",
        help="Stop early when multiple consecutive pages contain only cached eligible issues.",
    )
    args = parser.parse_args()

    if len(args.labels) > 5:
        print("Error: You can specify a maximum of 5 labels.")
        sys.exit(1)

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable not set.")
        print("Please run: export GITHUB_TOKEN='your_personal_access_token'")
        sys.exit(1)

    # Determine output and checkpoint files
    # Note: We default to .jsonl to reflect the JSON Lines format
    output_filename = args.output if args.output else f"{args.repo}_issues.jsonl"
    checkpoint_file = f".checkpoint_{args.owner}_{args.repo}.json"

    # If no checkpoint exists, this is a fresh run.
    # Without cache, clear the output file to avoid appending to old data.
    # With cache, keep the old output and append only newly discovered issues.
    if not os.path.exists(checkpoint_file) and not args.cache:
        open(output_filename, "w").close()

    try:
        total_fetched = fetch_issues(
            args.owner,
            args.repo,
            args.labels,
            args.depth,
            token,
            output_filename,
            args.exclude_open_prs,
            args.cache,
            args.cache_db,
            args.cache_stop,
        )
        print(f"\nDone! Scraped {total_fetched} issues in this run.")
        print(f"Data saved to {output_filename} (JSONL format)")
    except KeyboardInterrupt:
        print(
            "\nProcess interrupted by user. Progress has been safely saved to the checkpoint file."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
