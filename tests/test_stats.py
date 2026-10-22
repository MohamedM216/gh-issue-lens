import pytest

from gh_issue_lens.stats import (
    compute_score,
    fmt_hours,
    parse_repo_lines,
    render_bars,
    render_table,
    verdict_for_score,
)


def test_parse_repo_lines_skips_comments_and_duplicates():
    lines = [
        "# comment",
        "",
        "kubernetes/kubernetes",
        "kubernetes/kubernetes",
        "pandas-dev/pandas",
    ]

    assert parse_repo_lines(lines) == [
        "kubernetes/kubernetes",
        "pandas-dev/pandas",
    ]


def test_parse_repo_lines_rejects_bad_reference():
    with pytest.raises(ValueError):
        parse_repo_lines(["just-a-repo"])


def test_compute_score_perfect_repo():
    stats = {
        "median_first_reply_hours": 5,
        "good_first_issues": 60,
        "help_wanted_issues": 60,
        "unanswered_rate": 0.0,
        "stale_rate": 0.0,
        "merged_prs_last_7_days": 25,
        "pushed_days_ago": 1,
    }

    assert compute_score(stats) == 100


def test_compute_score_dead_repo():
    stats = {
        "median_first_reply_hours": None,
        "good_first_issues": 0,
        "help_wanted_issues": 0,
        "unanswered_rate": 1.0,
        "stale_rate": 1.0,
        "merged_prs_last_7_days": 0,
        "pushed_days_ago": 200,
    }

    assert compute_score(stats) == 0


def test_compute_score_rewards_merge_pace():
    base = {
        "median_first_reply_hours": None,
        "good_first_issues": 0,
        "help_wanted_issues": 0,
        "unanswered_rate": 1.0,
        "stale_rate": 1.0,
        "pushed_days_ago": 200,
    }

    quiet = compute_score({**base, "merged_prs_last_7_days": 0})
    busy = compute_score({**base, "merged_prs_last_7_days": 25})

    assert busy - quiet == 12


def test_verdict_thresholds():
    assert verdict_for_score(80)[1] == "GREAT"
    assert verdict_for_score(60)[1] == "GOOD"
    assert verdict_for_score(40)[1] == "MIXED"
    assert verdict_for_score(10)[1] == "COLD"


def test_fmt_hours():
    assert fmt_hours(None) == "-"
    assert fmt_hours(31) == "31h"
    assert fmt_hours(120) == "5.0d"


def test_render_table_and_bars_handle_errors():
    stats_list = [
        {"repo": "a/b", "error": "repository not found or no access"},
        {
            "repo": "c/d",
            "beginner_score": 80,
            "open_issues": 10,
            "good_first_issues": 2,
            "help_wanted_issues": 3,
            "median_first_reply_hours": 20,
            "unanswered_rate": 0.1,
            "stale_rate": 0.2,
            "merged_prs_last_7_days": 12,
        },
    ]

    table = render_table(stats_list)
    bars = render_bars(stats_list)

    assert "ERROR" in table
    assert "GREAT" in table
    assert "PR/WK" in table
    assert "█" in bars
    assert "a/b" not in bars
