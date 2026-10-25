"""Command line interface for gh-issue-lens."""

import argparse
import os
import sys

from . import __version__
from .core import DEFAULT_CACHE_DB, command_signature, fetch_issues


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] == "stats":
        from .stats import stats_main

        return stats_main(argv[1:])

    return scan_main(argv)


def scan_main(argv):
    parser = argparse.ArgumentParser(
        prog="gh-issue-lens",
        description=(
            "Easier open source contribution process for newcomers. "
            "Fetch open issues from a GitHub repository and export them "
            "as JSONL for LLM analysis."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "owner",
        help="GitHub repository owner (e.g., 'kubernetes')",
    )

    parser.add_argument(
        "repo",
        help="GitHub repository name (e.g., 'kubernetes')",
    )

    parser.add_argument(
        "-l",
        "--labels",
        nargs="+",
        help=(
            "Filter by up to 5 labels. Labels are ORed (e.g., -l 'good first issue' 'help wanted')"
        ),
        default=[],
    )

    parser.add_argument(
        "-d",
        "--depth",
        type=int,
        help="Maximum number of issues to fetch (default: 100)",
        default=100,
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Output JSONL filename",
        default=None,
    )

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
        help=("Stop early when multiple consecutive pages contain only cached eligible issues."),
    )

    parser.add_argument(
        "--stale-pr-days",
        type=int,
        default=90,
        help=(
            "Open PRs untouched for this many days are considered stale "
            "(default: 90). Issues with only stale PRs stay available."
        ),
    )

    args = parser.parse_args(argv)

    if len(args.labels) > 5:
        print("Error: You can specify a maximum of 5 labels.")
        sys.exit(1)

    token = os.getenv("GITHUB_TOKEN")

    if not token:
        print("Error: GITHUB_TOKEN environment variable not set.")
        print("Please run: export GITHUB_TOKEN='your_personal_access_token'")
        sys.exit(1)

    output_filename = args.output if args.output else f"{args.repo}_issues.jsonl"
    checkpoint_file = f".checkpoint_{args.owner}_{args.repo}.json"

    signature = command_signature(
        {
            "owner": args.owner,
            "repo": args.repo,
            "labels": sorted(args.labels),
            "depth": args.depth,
            "exclude_open_prs": args.exclude_open_prs,
            "stale_pr_days": args.stale_pr_days,
            "cache": args.cache,
            "cache_stop": args.cache_stop,
            "output": output_filename,
        }
    )

    # If cache is disabled and there is no checkpoint, start with a fresh output file.
    # If cache is enabled, keep the old output file and append only new issues.
    if not os.path.exists(checkpoint_file) and not args.cache:
        open(output_filename, "w", encoding="utf-8").close()

    try:
        total_fetched = fetch_issues(
            owner=args.owner,
            repo=args.repo,
            labels=args.labels,
            depth=args.depth,
            token=token,
            output_filename=output_filename,
            exclude_open_prs=args.exclude_open_prs,
            use_cache=args.cache,
            cache_db=args.cache_db,
            cache_stop=args.cache_stop,
            stale_pr_days=args.stale_pr_days,
            signature=signature,
        )

        print(f"\nDone! Scraped {total_fetched} issues in this run.")
        print(f"Data saved to {output_filename} (JSONL format)")

    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        print("Progress has been saved to the checkpoint file.")
        print("Run the same command again to resume.")
        sys.exit(0)


if __name__ == "__main__":
    main()
