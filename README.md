# Find Your First Issue

A lightning-fast CLI tool that queries the GitHub GraphQL API to find open issues in any repository for quick analysis or LLM processing. It bypasses API rate limits by grabbing issues, linked Pull Requests, assignees, and non-bot comments in a single network pass.

## How to use it?

**Clone the repo:**

```bash
git clone https://github.com/MohamedM216/gh-issues-filter-tool.git
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
## What's next?

The generated JSON file is suitable to be used as context for Large Language Models (like Gemini, Claude, or ChatGPT). You can upload the output file to an LLM and use targeted prompts to find the perfect issue to work on.

**Example Prompts to try:**

> "I am a newcomer to this repository. Based on the attached JSON, find an issue that is easy to implement, has no active PRs, and doesn't have a long, debated comment history."

> "Filter these issues and list only the ones related to [backend / frontend / database / specific component]."

> "Read the comments on these issues. Which maintainers seem the most responsive and welcoming to beginners? Point me to issues authored or reviewed by them."

> "Summarize the technical requirements for issue #123 based on its description and comment thread. What files should I look at first?"

*Happy hacking!*
