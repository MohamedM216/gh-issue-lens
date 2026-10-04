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

def fetch_issues(owner, repo, labels, depth, token):
    url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
    }
    
    # We use a standard string now, no f-string formatting needed
    query = get_graphql_query()
    
    has_labels = bool(labels and len(labels) > 0)
    target_labels_lower = [l.lower() for l in labels] if has_labels else []
    
    extracted_data = []
    has_next_page = True
    cursor = None
    page_num = 1
    
    label_text = f" (Filtering by ANY of: {', '.join(labels)})" if has_labels else ""
    print(f"Starting extraction for {owner}/{repo}{label_text}...")
    print(f"Target depth: {depth} matches.")

    while has_next_page and len(extracted_data) < depth:
        variables = {
            "owner": owner,
            "repo": repo,
            "cursor": cursor
        }
        
        print(f" -> Scanning page {page_num} (Fetching up to 100 open issues from GitHub)...")
        response = requests.post(url, json={"query": query, "variables": variables}, headers=headers)
        
        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.text}")
            sys.exit(1)
            
        data = response.json()
        
        if "errors" in data:
            print(f"GraphQL Error: {data['errors'][0]['message']}")
            sys.exit(1)
            
        repository = data.get("data", {}).get("repository")
        if not repository:
            print(f"Repository {owner}/{repo} not found.")
            sys.exit(1)
            
        issues_data = repository.get("issues", {})
        nodes = issues_data.get("nodes", [])
        
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
                    
            extracted_data.append({
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
            
            # Stop parsing immediately if we hit our depth target
            if len(extracted_data) >= depth:
                break
            
        page_info = issues_data.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        page_num += 1
        
    return extracted_data

def main():
    parser = argparse.ArgumentParser(description="Fetch open issues from a GitHub repository to find beginner-friendly tasks.")
    parser.add_argument("owner", help="GitHub repository owner (e.g., 'headlamp-k8s')")
    parser.add_argument("repo", help="GitHub repository name (e.g., 'plugins')")
    parser.add_argument("-l", "--labels", nargs="+", help="Filter by up to 5 labels. Labels are ORed (e.g., -l 'bug' 'good first issue')", default=[])
    parser.add_argument("-d", "--depth", type=int, help="Maximum number of issues to fetch (default: 100)", default=100)
    parser.add_argument("-o", "--output", help="Output JSON filename", default=None)
    
    args = parser.parse_args()
    
    if len(args.labels) > 5:
        print("Error: You can specify a maximum of 5 labels.")
        sys.exit(1)
    
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable not set.")
        print("Please run: export GITHUB_TOKEN='your_personal_access_token'")
        sys.exit(1)

    final_data = fetch_issues(args.owner, args.repo, args.labels, args.depth, token)
    
    output_filename = args.output if args.output else f"{args.repo}_issues.json"
    
    with open(output_filename, "w", encoding="utf-8") as file:
        json.dump(final_data, file, indent=4)
        
    print(f"\nDone! Scraped {len(final_data)} issues.")
    print(f"Data saved to {output_filename}")

if __name__ == "__main__":
    main()