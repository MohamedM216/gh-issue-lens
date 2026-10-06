import argparse
import requests
import json
import os
import sys

def get_graphql_query():
    """
    Fetches open issues in maximum batch sizes.
    We request the issue labels here so we can perform the OR logic filter locally in Python,
    bypassing GitHub's strict AND logic for label filtering.
    """
    return """
    query($owner: String!, $repo: String!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        issues(first: 100, after: $cursor, states: OPEN, orderBy: {field: CREATED_AT, direction: DESC}) {
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
            comments(first: 50) {
              nodes {
                author {
                  login
                  __typename
                }
                body
              }
            }
            timelineItems(itemTypes: [CROSS_REFERENCED_EVENT], first: 20) {
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

def fetch_issues(owner, repo, labels, depth, token, output_filename):
    url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
    }
    
    query = get_graphql_query()
    has_labels = bool(labels and len(labels) > 0)
    target_labels_lower = [l.lower() for l in labels] if has_labels else []
    
    has_next_page = True
    cursor = None
    page_num = 1
    extracted_count = 0
    
    # Define the hidden checkpoint file
    checkpoint_file = f".checkpoint_{owner}_{repo}.json"

    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r") as f:
                cp_data = json.load(f)
                cursor = cp_data.get("cursor")
                page_num = cp_data.get("page_num", 1)
                extracted_count = cp_data.get("extracted_count", 0)
                print(f"Resuming from checkpoint. Starting at page {page_num}, {extracted_count} issues already fetched.")
        except Exception as e:
            print(f"Warning: Could not read checkpoint file: {e}")

    label_text = f" (Filtering by ANY of: {', '.join(labels)})" if has_labels else ""
    print(f"Starting extraction for {owner}/{repo}{label_text}...")
    print(f"Target depth: {depth} matches.")
    
    while has_next_page and extracted_count < depth:
        variables = {
            "owner": owner,
            "repo": repo,
            "cursor": cursor
        }

        print(f" -> Scanning page {page_num} (Fetching up to 100 open issues from GitHub)...")
        
        response = requests.post(url, json={"query": query, "variables": variables}, headers=headers)
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
        for issue in nodes:
            if not issue: continue
            
            # 1. Evaluate Labels (OR condition implemented locally)
            issue_labels = [l["name"].lower() for l in issue.get("labels", {}).get("nodes", []) if l]
            if has_labels:
                # Skip this issue entirely if it doesn't contain ANY of our target labels
                if not any(label in issue_labels for label in target_labels_lower):
                    continue
                    
            # 2. Parse Assignees
            assignees = [a["login"] for a in issue.get("assignees", {}).get("nodes", []) if a]
            
            # 3. Parse Comments (Filtering out Bots)
            comments = []
            for comment in issue.get("comments", {}).get("nodes", []):
                if not comment: continue
                author = comment.get("author")
                if author and author.get("__typename") != "Bot":
                    comments.append({
                        "author": author.get("login"),
                        "body": comment.get("body")
                    })
                    
            # 4. Check for open Pull Requests mentioning this issue
            has_open_pr = False
            for event in issue.get("timelineItems", {}).get("nodes", []):
                if not event: continue
                source = event.get("source")
                if source and source.get("state") == "OPEN":
                    has_open_pr = True
                    break
                    
            page_issues.append({
                "number": issue.get("number"),
                "title": issue.get("title"),
                "url": issue.get("url"),
                "created_at": issue.get("createdAt"),
                "is_assigned": len(assignees) > 0,
                "assigned_to": assignees,
                "has_open_pr_against_it": has_open_pr,
                "labels": issue_labels, 
                "body": issue.get("body"),
                "comments": comments
            })
            
            # Stop parsing if we hit the depth target mid-page
            if extracted_count + len(page_issues) >= depth:
                break

        # Write the fully parsed page to the file all at once
        with open(output_filename, "a", encoding="utf-8") as f:
            for item in page_issues:
                f.write(json.dumps(item) + "\n")
                
        extracted_count += len(page_issues)
        
        page_info = issues_data.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        page_num += 1
        
        if has_next_page and extracted_count < depth:
            # Save state for the NEXT iteration
            with open(checkpoint_file, "w") as f:
                json.dump({
                    "cursor": cursor, 
                    "page_num": page_num, 
                    "extracted_count": extracted_count
                }, f)
        else:
            # Finished or reached depth, clean up checkpoint
            if os.path.exists(checkpoint_file):
                os.remove(checkpoint_file)
                
    return extracted_count

def main():
    parser = argparse.ArgumentParser(description="Fetch open issues from a GitHub repository to find beginner-friendly tasks.")
    parser.add_argument("owner", help="GitHub repository owner (e.g., 'kubernetes')")
    parser.add_argument("repo", help="GitHub repository name (e.g., 'kubernetes')")
    parser.add_argument("-l", "--labels", nargs="+", help="Filter by up to 5 labels. Labels are ORed (e.g., -l 'bug' 'good first issue')", default=[])
    parser.add_argument("-d", "--depth", type=int, help="Maximum number of issues to fetch (default: 100)", default=100)
    parser.add_argument("-o", "--output", help="Output JSONL filename", default=None)
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
    
    # If no checkpoint exists, this is a fresh run. Clear the output file to avoid appending to old data.
    if not os.path.exists(checkpoint_file):
        open(output_filename, "w").close()

    try:
        total_fetched = fetch_issues(args.owner, args.repo, args.labels, args.depth, token, output_filename)
        print(f"\nDone! Scraped {total_fetched} issues in this run.")
        print(f"Data saved to {output_filename} (JSONL format)")
    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Progress has been safely saved to the checkpoint file.")
        sys.exit(0)

if __name__ == "__main__":
    main()
