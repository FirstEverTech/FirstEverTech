#!/usr/bin/env python3
import os
import sys
import requests
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime, timedelta, timezone
from pathlib import Path

USERNAME = os.environ.get("USERNAME", "FirstEverTech")
TOKEN    = os.environ.get("GITHUB_TOKEN")
HEADERS  = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"Bearer {TOKEN}",
}

# ---------- Pobieranie danych aktywności ----------
def fetch_daily_contributions(username, days=31):
    """
    Pobiera publiczne zdarzenia użytkownika i zlicza je na dzień.
    Zwraca słownik {data: liczba_zdarzeń} dla ostatnich `days` dni.
    """
    url = f"https://api.github.com/users/{username}/events/public"
    params = {"per_page": 100}
    all_events = []
    page = 1
    while True:
        r = requests.get(url, headers=HEADERS, params={**params, "page": page}, timeout=30)
        if r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        all_events.extend(data)
        page += 1
        # Bezpiecznik – max 10 stron (1000 zdarzeń)
        if page > 10:
            break

    # Typy zdarzeń uznawane za aktywność
    relevant_types = {
        "PushEvent", "PullRequestEvent", "IssuesEvent", "IssueCommentEvent",
        "PullRequestReviewEvent", "PullRequestReviewCommentEvent", "CreateEvent",
        "DeleteEvent", "ForkEvent", "WatchEvent"
    }

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    daily_counts = {}
    for ev in all_events:
        if ev["type"] not in relevant_types:
            continue
        created = datetime.fromisoformat(ev["created_at"].rstrip("Z")).replace(tzinfo=timezone.utc)
        if created < cutoff:
            continue
        day_key = created.date()
        daily_counts[day_key] = daily_counts.get(day_key, 0) + 1

    # Uzupełnij brakujące dni zerami
    start_date = datetime.now(timezone.utc).date() - timedelta(days=days-1)
    for i in range(days):
        d = start_date + timedelta(days=i)
        if d not in daily_counts:
            daily_counts[d] = 0

    return {d: daily_counts[d] for d in sorted(daily_counts.keys())}

# ---------- Rysowanie heatmapy ----------
def generate_heatmap(daily_data, username, out):
    dates = list(daily_data.keys())
    counts = list(daily_data.values())
    days = len(dates)  # oczekiwane 31

    # Dzień tygodnia pierwszej daty (pon=0, niedz=6)
    first_weekday = dates[0].weekday()

    # Macierz 7 wierszy (dni tygodnia) x liczba dni
    rows = 7
    cols = days
    matrix = np.zeros((rows, cols))
    for i, d in enumerate(dates):
        wd = d.weekday()
        row = (wd - first_weekday) % rows
        matrix[row, i] = daily_data[d]

    max_count = max(counts) if counts else 1

    # Niebieska paleta kolorów (od jasnego do ciemnego)
    colors = ["#ebedf0", "#c8d9f0", "#79b8ff", "#2188ff", "#0366d6"]

    fig, ax = plt.subplots(figsize=(10, 3.2), dpi=150)
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")

    cell_size = 0.9
    for row in range(rows):
        for col in range(cols):
            val = matrix[row, col]
            if val == 0:
                color_idx = 0
            else:
                norm = val / max_count
                idx = min(int(norm * 4) + 1, 4)
                color_idx = idx
            rect = mpatches.Rectangle(
                (col - 0.5, row - 0.5), cell_size, cell_size,
                facecolor=colors[color_idx], edgecolor="none", linewidth=0
            )
            ax.add_patch(rect)

    ax.set_xlim(-0.5, cols - 0.5)
    ax.set_ylim(-0.5, rows - 0.5)
    ax.set_aspect("equal")

    # Etykiety dni tygodnia po lewej (skrócone)
    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for row in range(rows):
        actual_wd = (row + first_weekday) % 7
        ax.text(-0.8, row, weekday_names[actual_wd][:2], ha="right", va="center",
                fontsize=7, color="#58a6ff", fontweight="bold")

    # Etykiety numerów dni na dole (co 5 dni)
    for col in range(cols):
        if col % 5 == 0 or col == cols - 1:
            day_num = dates[col].day
            ax.text(col, -0.8, str(day_num), ha="center", va="top",
                    fontsize=7, color="#58a6ff", fontweight="bold")

    ax.axis("off")

    ax.set_title(
        f"{username} · Activity (last {days} days)",
        color="#58a6ff", fontsize=10, fontweight="normal",
        fontfamily="DejaVu Sans", pad=10
    )

    plt.tight_layout(pad=0.8)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)

if __name__ == "__main__":
    username = USERNAME
    days = 31
    data = fetch_daily_contributions(username, days)
    if not data:
        sys.exit(0)
    generate_heatmap(data, username, Path("assets/contribution-graph.svg"))