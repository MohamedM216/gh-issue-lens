import argparse
import requests
import json
import os
import sys

def get_graphql_query(has_label):
    """
    Constructs the GraphQL query. Dynamically injects the label filter if provided.
    Fetches the issue, assignees, non-bot comments, and linked PRs in a single pass.
    """
    label_filter = "labels: [$label]," if has_label else ""
    return f"""
    query($owner: String!, $repo: String!, $cursor: String{', $label: String!' if has_label else ''}) {{
      repository(owner: $owner, name: $repo) {{
        issues(first: 50, after: $cursor, states: OPEN, {label_filter} orderBy: {{field: CREATED_AT, direction: DESC}}) {{
          pageInfo {{
            hasNextPage
            endCursor
          }}
          nodes {{
            number
            title
            url
            createdAt
            body
            assignees(first: 10) {{
              nodes {{
                login
              }}
            }}
            comments(first: 50) {{
              nodes {{
                author {{
                  login
                  __typename
                }}
                body
              }}
            }}
            timelineItems(itemTypes: [CROSS_REFERENCED_EVENT], first: 20) {{
              nodes {{
                ... on CrossReferencedEvent {{
                  source {{
                    ... on PullRequest {{
                      state
                      number
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    """

def fetch_issues(owner, repo, label, token):
    url = "https://api.github.com/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
    }
    
    has_label = bool(label)
    query = get_graphql_query(has_label)
    
    variables = {
        "owner": owner,
        "repo": repo,
        "cursor": None
    }
    
    if has_label:
        variables["label"] = label
        
    extracted_data = []
    has_next_page = True
    page_num = 1
    
    print(f"Starting GraphQL extraction for {owner}/{repo}" + (f" (Label: '{label}')" if has_label else "") + "...")

    while has_next_page:
        print(f" -> Fetching page {page_num}...")
        response = requests.post(url, json={"query": query, "variables": variables}, headers=headers)
        
        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.text}")
            sys.exit(1)
            
        data = response.json()
        
        # Handle GraphQL specific errors (e.g., repo not found, bad token)
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
            # 1. Parse Assignees
            assignees = [a["login"] for a in issue.get("assignees", {}).get("nodes", [])]
            
            # 2. Parse Comments (Filtering out Bots via GraphQL __typename)
            comments = []
            for comment in issue.get("comments", {}).get("nodes", []):
                author = comment.get("author")
                if author and author.get("__typename") != "Bot":
                    comments.append({
                        "author": author.get("login"),
                        "body": comment.get("body")
                    })
                    
            # 3. Check for open Pull Requests mentioning this issue
            has_open_pr = False
            for event in issue.get("timelineItems", {}).get("nodes", []):
                source = event.get("source")
                # Ensure the cross-reference is a Pull Request and is Open
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
                "body": issue.get("body"),
                "comments": comments
            })
            
        page_info = issues_data.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        variables["cursor"] = page_info.get("endCursor")
        page_num += 1
        
    return extracted_data

def main():
    parser = argparse.ArgumentParser(description="Fetch open issues from a GitHub repository to find beginner-friendly tasks.")
    parser.add_argument("owner", help="GitHub repository owner (e.g., 'headlamp-k8s')")
    parser.add_argument("repo", help="GitHub repository name (e.g., 'plugins')")
    parser.add_argument("-l", "--label", help="Filter by label (e.g., 'good first issue' or 'feature')", default=None)
    parser.add_argument("-o", "--output", help="Output JSON filename", default=None)
    
    args = parser.parse_args()
    
    # Security: Read token from environment variable
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable not set.")
        print("Please run: export GITHUB_TOKEN='your_personal_access_token'")
        sys.exit(1)

    final_data = fetch_issues(args.owner, args.repo, args.label, token)
    
    # Determine output filename
    output_filename = args.output if args.output else f"{args.repo}_issues.json"
    
    with open(output_filename, "w", encoding="utf-8") as file:
        json.dump(final_data, file, indent=4)
        
    print(f"\nDone! Scraped {len(final_data)} issues in seconds.")
    print(f"Data saved to {output_filename}")

if __name__ == "__main__":
    main()