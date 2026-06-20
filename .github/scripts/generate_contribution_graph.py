#!/usr/bin/env python3
import os, sys, math, requests, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta, timezone
from pathlib import Path
from scipy.interpolate import CubicSpline

USERNAME = os.environ.get("USERNAME", "FirstEverTech")
TOKEN    = os.environ.get("GITHUB_TOKEN")
HEADERS  = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"Bearer {TOKEN}",
}

def fetch_activity(username, days=31):
    """Pobiera dzienną liczbę zdarzeń (aktywność) dla ostatnich 'days' dni."""
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
        if page > 10:   # bezpiecznik – max 1000 zdarzeń
            break

    # Zdarzenia uznawane za aktywność
    relevant = {
        "PushEvent", "PullRequestEvent", "IssuesEvent", "IssueCommentEvent",
        "PullRequestReviewEvent", "PullRequestReviewCommentEvent", "CreateEvent",
        "DeleteEvent", "ForkEvent", "WatchEvent"
    }

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    daily = {}
    for ev in all_events:
        if ev["type"] not in relevant:
            continue
        created = datetime.fromisoformat(ev["created_at"].rstrip("Z")).replace(tzinfo=timezone.utc)
        if created < cutoff:
            continue
        day = created.date()
        daily[day] = daily.get(day, 0) + 1

    # Generuj pełną listę dni od start do dziś
    start = datetime.now(timezone.utc).date() - timedelta(days=days-1)
    dates = []
    counts = []
    for i in range(days):
        d = start + timedelta(days=i)
        dates.append(d)
        counts.append(daily.get(d, 0))
    return dates, counts

# ---------- KOLORY ----------
BLUE     = "#58a6ff"
LINE     = "#1f6feb"
GRID_MAJ = "#283d58"   # nowy kolor siatki

def generate(dates, counts, username, out):
    x_dates = [datetime.combine(d, datetime.min.time()) for d in dates]
    y = counts

    # Numeryczne reprezentacje dat
    x_num = mdates.date2num(x_dates)

    # Wygładzanie splajnem
    cs = CubicSpline(x_num, y, bc_type='natural')
    x_smooth = np.linspace(x_num[0], x_num[-1], 300)
    y_smooth = cs(x_smooth)

    fig, ax = plt.subplots(figsize=(10, 3.2), dpi=150)
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")

    # Linia + wypełnienie (wygładzone)
    ax.plot(x_smooth, y_smooth, color=LINE, linewidth=2.5, zorder=3)
    ax.fill_between(x_smooth, y_smooth, color=LINE, alpha=0.15, zorder=2)

    # Kropki na każdym dniu (31 punktów)
    ax.scatter(x_num, y, color=BLUE, s=30, zorder=4, linewidths=0)

    # Marginesy aby kropki nie były ucinane
    ax.set_xlim(x_num[0] - 0.5, x_num[-1] + 0.5)
    y_max = max(y) if y else 1
    ax.set_ylim(0, y_max * 1.05)

    # Siatka pionowa co dzień – etykiety to numery dni
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d"))
    ax.grid(True, which='major', axis='x', color=GRID_MAJ, linewidth=0.7, linestyle='-')

    # Siatka pozioma – 8 linii
    NUM_Y_LINES = 8
    if y_max > 0:
        nice_max = math.ceil(y_max / (NUM_Y_LINES-1)) * (NUM_Y_LINES-1)
        if nice_max < NUM_Y_LINES-1:
            nice_max = NUM_Y_LINES-1
    else:
        nice_max = 7
    ax.set_yticks(np.linspace(0, nice_max, NUM_Y_LINES))
    ax.grid(True, which='major', axis='y', color=GRID_MAJ, linewidth=0.7, linestyle='-')

    # Stylizacja osi
    ax.tick_params(axis='both', which='both', colors=BLUE, labelsize=7)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontweight("bold")
        lbl.set_color(BLUE)

    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_MAJ)

    ax.set_ylabel("Contributions", color=BLUE, fontsize=8,
                  fontfamily="DejaVu Sans", fontweight="bold")
    ax.set_xlabel("Day", color=BLUE, fontsize=8,
                  fontfamily="DejaVu Sans", fontweight="bold")

    # Tytuł – nowa treść, większa czcionka
    ax.set_title(
        "Marcin Grygiel aka FirstEver's Contribution Graph",
        color=BLUE, fontsize=11, fontweight="normal",
        fontfamily="DejaVu Sans", pad=10,
    )

    plt.tight_layout(pad=0.8)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)

if __name__ == "__main__":
    username = USERNAME
    days = 31
    dates, counts = fetch_activity(username, days)
    if not counts:
        sys.exit(0)
    generate(dates, counts, username, Path("assets/contribution-graph.svg"))
