import requests
import json
import os

def fetch_github_projects(query, per_page=20, sort='updated', order='desc'):
    """Fetch GitHub projects based on the query."""
    url = f"https://api.github.com/search/repositories?q={query}&sort={sort}&order={order}&per_page={per_page}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to fetch data: {response.status_code}")


def filter_ai_agent_projects(projects):
    """Filter projects related to AI-agent."""
    filtered_projects = []
    for project in projects['items']:
        description = project.get('description', '')
        if description and ('AI' in description or 'agent' in description.lower()):
            filtered_projects.append(project)
    return filtered_projects


def save_projects(projects, output_dir, filename):
    """Save projects to JSON and Markdown files."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    json_path = os.path.join(output_dir, f"{filename}.json")
    with open(json_path, 'w') as f:
        json.dump(projects, f, indent=4)
    
    markdown_path = os.path.join(output_dir, f"{filename}.md")
    with open(markdown_path, 'w') as f:
        f.write("# AI-Agent Related GitHub Projects (Latest)\n")
        for project in projects:
            f.write(f"| {project['name']} | {project['html_url']} |\n")


def main():
    query = "AI-agent language:python created:>=2023-03-01"
    projects = fetch_github_projects(query)
    ai_agent_projects = filter_ai_agent_projects(projects)
    save_projects(ai_agent_projects, 'data', 'github_agents_latest')

if __name__ == "__main__":
    main()
