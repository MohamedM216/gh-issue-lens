# Find First Issue

A lightning-fast CLI tool that queries the GitHub GraphQL API to find open issues in any repository. It bypasses API rate limits by grabbing issues, linked Pull Requests, assignees, and non-bot comments in a single network pass. 

## Setup

**Install requirements:**
```bash
pip3 install requests
```

**Export your GitHub Personal Access Token:**

First of all, create your personal github token from your github account then use it.

```bash
export GITHUB_TOKEN="your_personal_access_token"
```

**Fetch 100 issues from a repository:**

100 issues is the default depth you can change it using the -d option.

```bash
python3 find_issues.py kubernetes kubernetes
```

**Filter by up to 5 labels (ORed) and set a depth limit:**

This fetches a maximum of 50 issues that have EITHER the "good first issue", "help wanted", or "bug" label.

```bash
python3 find_issues.py kubernetes kubernetes -l "good first issue" "help wanted" "bug" -d 50
```

**Save to a custom JSON file:**

If you want to use a custom name for the output file, you can run:

```bash
python3 find_issues.py kubernetes kubernetes -l "feature" -d 10 -o custom_dataset.json
```
