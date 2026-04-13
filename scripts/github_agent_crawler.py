import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone


def fetch_github_repos():
    query = "q=AI+agent+llm&sort=stars&order=desc&per_page=100"
    url = "https://api.github.com/search/repositories?" + query
    req = urllib.request.Request(url, headers={"User-Agent": "NanoCoder-Crawler/1.0"})
    print("[1/3] Fetching from GitHub API ...")
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read())
    print(f"      Got {len(data['items'])} repos total")
    return data["items"]


def filter_repos(repos):
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    filtered = [
        repo for repo in repos
        if datetime.strptime(repo["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        ) > seven_days_ago
    ]
    print(f"[2/3] After 7-day filter: {len(filtered)} repos -> taking top 20")
    return filtered[:20]


def save_results(repos):
    os.makedirs("data", exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    json_path = f"data/github_agents_{today}.json"
    md_path = "data/github_agents_latest.md"

    fields = ["name", "full_name", "description", "stargazers_count",
              "html_url", "language", "updated_at"]
    records = [{f: repo.get(f) for f in fields} for repo in repos]

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("| Name | Full Name | Description | Stars | URL | Language | Updated At |\n")
        f.write("|------|-----------|-------------|-------|-----|----------|------------|\n")
        for r in records:
            name = r["name"] or ""
            full_name = r["full_name"] or ""
            desc = (r["description"] or "")[:80].replace("|", "/")
            stars = r["stargazers_count"] or 0
            url = r["html_url"] or ""
            lang = r["language"] or ""
            updated = r["updated_at"] or ""
            f.write(f"| {name} | {full_name} | {desc} | {stars} | {url} | {lang} | {updated} |\n")

    print(f"[3/3] Saved results:")
    print(f"      JSON -> {json_path}")
    print(f"      MD   -> {md_path}")
    return json_path, md_path


if __name__ == "__main__":
    repos = fetch_github_repos()
    top20 = filter_repos(repos)
    json_path, md_path = save_results(top20)
    print(f"\nDone! Fetched {len(top20)} agent-related repos.")
