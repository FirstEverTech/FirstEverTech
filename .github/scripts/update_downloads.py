import requests
import re
import os

USERNAME = "FirstEverTech"

REPOS = [
    "Universal-Intel-Chipset-Updater",
    "Universal-Intel-WiFi-BT-Updater",
    "Adobe-AVX2-Patch",
]

headers = {
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"
}

total_downloads = 0

for repo in REPOS:
    url = f"https://api.github.com/repos/{USERNAME}/{repo}/releases"

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"Error fetching {repo}")
        continue

    releases = response.json()

    for release in releases:
        for asset in release.get("assets", []):
            total_downloads += asset.get("download_count", 0)

print("Total downloads:", total_downloads)

# formatowanie
if total_downloads >= 1000:
    badge_value = f"{total_downloads / 1000:.1f}K+"
else:
    badge_value = str(total_downloads)

badge_value = badge_value.replace(".0K+", "K+")

new_badge = f"![Downloads](https://img.shields.io/badge/Downloads-{badge_value}-blue?style=for-the-badge&label=Downloads)"

with open("README.md", "r", encoding="utf-8") as f:
    readme = f.read()

readme = re.sub(
    r'!\[Downloads\]\(https://img\.shields\.io/badge/Downloads-[^)]+\)',
    new_badge,
    readme
)

with open("README.md", "w", encoding="utf-8") as f:
    f.write(readme)

print("README updated")
