# Easier open source contribution process for newcomers

Stop digging through stale GitHub issues. **gh-issue-lens** finds unassigned, beginner-friendly open source issues in any repository and prepares them for LLM analysis in seconds. It bypasses API rate limits by grabbing issues, linked Pull Requests, assignees, and non-bot comments in a single network pass.

# How to use it?

## Option 1: Install from PyPI

```bash
pip install gh-issue-lens
```
**Export your GitHub Personal Access Token:**

First of all, create your personal github token from your github account then use it.

```bash
export GITHUB_TOKEN="your_personal_access_token"
```

**Fetch issues:**

```bash
gh-issue-lens kubernetes kubernetes -d 200
```

**Filter by labels:**

```bash
gh-issue-lens kubernetes kubernetes -l "good first issue" "help wanted" -d 50
```

And for more commands, you can see the sections below. The guidelines are the same. The only difference is to use `gh-issue-lens` directly instead of `python3 cli.py`.

## Option 2: Build it manually

**Clone the repo:**

```bash
git clone https://github.com/MohamedM216/gh-issue-lens.git
```

**Install requirements:**

```bash
pip3 install requests
```

**Export your GitHub Personal Access Token:**

First of all, create your personal github token from your github account then use it.

```bash
export GITHUB_TOKEN="your_personal_access_token"
```

**Verify it works:**

```bash
cd src/gh_issue_lens/
python3 cli.py --help
```

**Fetch 100 issues from a repository:**

100 issues is the default depth you can change it using the -d option.

```bash
python3 cli.py kubernetes kubernetes
```

### Filter by up to 5 labels (ORed) and set a depth limit:

This fetches a maximum of 50 issues that have EITHER the "good first issue", "help wanted", or "bug" label.

```bash
python3 cli.py kubernetes kubernetes -l "good first issue" "help wanted" "bug" -d 50
```

### Save to a custom JSON file:

If you want to use a custom name for the output file, you can run:

```bash
python3 cli.py kubernetes kubernetes -l "feature" -d 10 -o custom_dataset.json
```

### Incremental Saving & Resumability (Checkpointing):

When scraping massive repositories (like Kubernetes), hitting GitHub's API rate limits or network timeouts is common. You no longer have to worry about losing your progress!
* **JSONL Format:** Issues are now saved line-by-line instantly as they are fetched, ensuring zero data loss.
* **Auto-Resume:** The tool creates a hidden `.checkpoint` file tracking your progress. If the script crashes or you stop it, simply run the **exact same command** again. It will automatically resume from the exact page it left off, saving your API budget and time. The checkpoint stores a signature of the options that affect results (labels, depth, filters, cache mode, output file). If you re-run with different options after a crash, gh-issue-lens detects the mismatch, discards the old checkpoint and starts clean; no silently mixed result sets.

### Exclude issues with open PRs:

```bash
python3 cli.py kubernetes kubernetes --exclude-open-prs
```

### Is this issue actually available? (Stale PR detection)

An issue with a fresh open PR is probably taken. An issue whose only PR was
abandoned months ago, or closed without merging is usually still up for grabs.

Every exported issue now includes an `availability` field:

- `likely_taken`: a fresh open PR exists (updated within `--stale-pr-days`)
- `stale_pr_open`: open PRs exist but all are stale, usually still approachable
- `merged_pr_linked`: a linked PR was merged
- `pr_closed_unmerged`: a previous attempt failed, the issue is open again
- `no_linked_pr`: nobody has opened a PR yet

```bash
gh-issue-lens kubernetes kubernetes --stale-pr-days 60
```

Note: `--exclude-open-prs` now skips only issues with a *fresh* open PR,
so abandoned-PR issues are no longer hidden from you.

### SQLite caching:

`gh-issue-lens` can cache already-exported issues in a local SQLite database. This prevents duplicate issues from being written again when you run the same export multiple times.

Enable caching:

```bash
python3 cli.py kubernetes kubernetes -d 200 --cache
```

By default, the cache is stored in `.gh_issue_lens_cache.db`. Use a custom cache database:

```bash
python3 cli.py kubernetes kubernetes -d 200 --cache --cache-db my_cache.db
```

Run again with caching enabled. Issues that were already exported in previous runs will be skipped. You can also enable early stopping when the tool keeps finding only cached issues:

```bash
python3 cli.py kubernetes kubernetes -d 200 --cache --cache-stop
```

This is useful when re-running the tool against the same repository and you only want newly discovered issues. To reset the cache, delete the cache file:

```bash
rm .gh_issue_lens_cache.db
```

Caching is different from checkpointing: checkpointing helps resume a crashed or interrupted run, while caching helps avoid exporting the same issues again across separate runs.

## Compare repositories: which community should you start with?

`gh-issue-lens stats` answers the question every beginner asks first:
*which repo should I even try?*

    gh-issue-lens stats kubernetes/kubernetes pandas-dev/pandas

Or from a file (one `owner/repo` per line, `#` comments allowed):

    gh-issue-lens stats --repos-file repos.txt

Three output layers:

- **Terminal (default):** comparison table + bar chart, plus a 0-100 beginner score.
- **HTML report:** `--html report.html` writes a self-contained page with bar charts.
- **Raw JSON for LLMs:** `--json stats.json`, or `--json -` to print to stdout and pipe anywhere.

### What the numbers mean

- **VERDICT (decide in 2 seconds):** 🌱 GREAT (≥75) · 👍 GOOD (≥55) · ⚠️ MIXED (≥35) · 🧊 COLD (<35).
- **beginner score (0-100):** responsiveness (30) + beginner-issue funnel (20) + answered-issue share (15) + freshness (15) + merged-PR pace per week (12) + push recency (8).
- **REPLY:** median time until the first non-bot, non-author comment on the 100 most recent open issues.
- **UNANSW / STALE:** share of those 100 issues with no human reply / untouched for `--stale-days` (default 180).
- **PR/WK:** pull requests merged in the last 7 days (the monthly count is in the JSON and HTML report).
- The HTML report (`--html`) adds a summary per repo: how fast people answer, how many beginner issues are open, and how active the merge pace is.

## What's next?

The generated JSON file is suitable to be used as context for Large Language Models (like Gemini, Claude, or ChatGPT). You can upload the output file to an LLM and use targeted prompts to find the perfect issue to work on.

**Example Prompts to try:**

> "I am a newcomer to this repository. Based on the attached JSON, find an issue that is easy to implement, has no active PRs, and doesn't have a long, debated comment history."

> "Filter these issues and list only the ones related to [backend / frontend / database / specific component]."

> "Read the comments on these issues. Which maintainers seem the most responsive and welcoming to beginners? Point me to issues authored or reviewed by them."

> "Summarize the technical requirements for issue #123 based on its description and comment thread. What files should I look at first?"

*Don't forget to STAR the repository :)*

*Happy hacking!*
