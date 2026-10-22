#!/usr/bin/env python3
import requests
import re
import os
import time

USERNAME = "FirstEverTech"
REPOS = [
    "Universal-Intel-Chipset-Updater",
    "Universal-Intel-WiFi-BT-Updater",
    "Adobe-AVX2-Patch",
]

headers = {
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
    "Accept": "application/vnd.github.v3+json",
}


# ── FIX 1: paginacja + retry + jasna sygnalizacja błędu ────────────────────
def fetch_all_releases(repo, max_retries=3):
    """
    Pobiera WSZYSTKIE release'y z paginacją (per_page=100, page=N).
    Zwraca listę release'ów albo None, jeśli nie udało się pobrać.
    """
    url = f"https://api.github.com/repos/{USERNAME}/{repo}/releases"
    all_releases = []
    page = 1

    while True:
        data = None

        for attempt in range(max_retries):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params={"per_page": 100, "page": page},
                    timeout=30,
                )

                if response.status_code == 200:
                    data = response.json()
                    break

                elif response.status_code == 403:
                    # Rate limit – sprawdź nagłówki i poczekaj
                    remaining = response.headers.get("x-ratelimit-remaining")
                    reset = response.headers.get("x-ratelimit-reset")
                    if remaining == "0" and reset:
                        wait = max(1, int(reset) - int(time.time()))
                        wait = min(wait, 120)  # nie czekaj dłużej niż 2 min
                    else:
                        wait = 5
                    print(f"[WARN] {repo}: rate limit (403), czekam {wait}s "
                          f"(próba {attempt + 1}/{max_retries})")
                    time.sleep(wait)

                elif response.status_code == 404:
                    print(f"[ERROR] {repo}: 404 – repo nie istnieje lub brak dostępu")
                    return None

                else:
                    print(f"[WARN] {repo}: HTTP {response.status_code} "
                          f"(próba {attempt + 1}/{max_retries})")
                    time.sleep(2)

            except requests.exceptions.RequestException as e:
                print(f"[WARN] {repo}: błąd sieci: {e} "
                      f"(próba {attempt + 1}/{max_retries})")
                time.sleep(2)

        if data is None:
            print(f"[ERROR] {repo}: nie udało się pobrać po {max_retries} próbach")
            return None

        if not data:
            break

        all_releases.extend(data)

        if len(data) < 100:
            break

        page += 1
        if page > 50:  # safety limit
            print(f"[WARN] {repo}: przekroczono 50 stron, przerywam")
            break

    return all_releases


# ── FIX 2: zbieranie danych z obsługą błędów ──────────────────────────────
total_downloads = 0
failed_repos = []
per_repo_counts = {}

for repo in REPOS:
    releases = fetch_all_releases(repo)
    if releases is None:
        failed_repos.append(repo)
        continue

    repo_total = sum(
        asset.get("download_count", 0)
        for release in releases
        for asset in release.get("assets", [])
    )
    per_repo_counts[repo] = repo_total
    total_downloads += repo_total
    print(f"[INFO] {repo}: {repo_total} pobrań z {len(releases)} release'ów")

print(f"[INFO] Suma wszystkich repo: {total_downloads}")

# ── FIX 4: sanity check – licznik pobrań jest kumulatywny, nie może maleć ──
# GitHub potrafi zwrócić HTTP 200 + pustą listę release'ów (incydent 22.10.2026),
# więc status 200 nie gwarantuje poprawnych danych. Porównaj z historią.
ALIAS = {
    "Universal-Intel-Chipset-Updater": "Rep1",
    "Universal-Intel-WiFi-BT-Updater": "Rep2",
    "Adobe-AVX2-Patch": "Rep3",
}
try:
    import json
    with open("assets/data/stats_history.json", encoding="utf-8") as f:
        _hist = json.load(f)
except (OSError, ValueError):
    _hist = {}
for repo, count in per_repo_counts.items():
    known = max(
        (day.get("gh_downloads", {}).get(ALIAS[repo], 0) for day in _hist.values()),
        default=0,
    )
    if count < known:
        print(f"[ERROR] {repo}: API={count} < ostatnia znana wartość {known} "
              f"– odrzucam (puste/niepełne dane z API)")
        failed_repos.append(repo)

# ── FIX 3: NIE nadpisuj badge'a błędną sumą ───────────────────────────────
if failed_repos:
    print(f"[ERROR] Nie udało się pobrać danych z: {failed_repos}")
    print("[ERROR] Badge i STATS.md NIE zostały zaktualizowane – "
          "zachowano ostatnią poprawną wartość.")
    raise SystemExit(1)

# Formatowanie liczby (np. 1200 → 1.2K)
if total_downloads >= 1000:
    badge_value = f"{total_downloads / 1000:.1f}K"
else:
    badge_value = str(total_downloads)
badge_value = badge_value.replace(".0K", "K")

new_badge = (
    f"![Downloads](https://img.shields.io/badge/Downloads-{badge_value}-blue"
    f"?style=for-the-badge&label=Downloads)"
)

# Aktualizuj README.md
with open("README.md", "r", encoding="utf-8") as f:
    readme = f.read()
readme = re.sub(
    r'!\[Downloads\]\(https://img\.shields\.io/badge/Downloads-[^)]+\)',
    new_badge,
    readme,
)
with open("README.md", "w", encoding="utf-8") as f:
    f.write(readme)
print("README.md updated")

# Aktualizuj STATS.md
if os.path.exists("STATS.md"):
    with open("STATS.md", "r", encoding="utf-8") as f:
        stats = f.read()
    stats = re.sub(
        r'!\[Downloads\]\(https://img\.shields\.io/badge/Downloads-[^)]+\)',
        new_badge,
        stats,
    )
    with open("STATS.md", "w", encoding="utf-8") as f:
        f.write(stats)
    print("STATS.md updated")