#!/usr/bin/env python3
import os, sys, math, requests, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

# ---------- KOLORY (takie same jak w star-history) ----------
BLUE     = "#58a6ff"
LINE     = "#1f6feb"
GRID_MAJ = "#444444"
GRID_MIN = "#2a2a2a"

def x_axis_config(start: datetime, end: datetime):
    """Dostosowanie etykiet osi X – dla 31 dni co 5 dni."""
    days = (end - start).days
    if days < 32:
        loc = mdates.DayLocator(interval=5)
        fmt = mdates.DateFormatter("%d %b")
        lbl = "Date"
    else:
        loc = mdates.MonthLocator()
        fmt = mdates.DateFormatter("%b %y")
        lbl = "Month"
    return loc, fmt, lbl

def generate(dates, counts, username, out):
    # dates – lista obiektów date, counts – lista int
    x_dates = [datetime.combine(d, datetime.min.time()) for d in dates]
    y = counts

    now = datetime.utcnow()
    x_start = x_dates[0]
    x_end   = x_dates[-1]   # ostatni dzień (dziś)

    fig, ax = plt.subplots(figsize=(10, 3.2), dpi=150)
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")

    # Konwersja na numery dla matplotlib
    date_nums = mdates.date2num(x_dates)

    # Linia + wypełnienie (dokładnie jak w star-history)
    ax.plot(x_dates, y, color=LINE, linewidth=2.5, zorder=3)
    ax.fill_between(x_dates, y, color=LINE, alpha=0.15, zorder=2)

    # 31 równomiernie rozmieszczonych punktów
    x31 = np.linspace(mdates.date2num(x_start), mdates.date2num(x_end), 31)
    y31 = np.interp(x31, date_nums, y)
    ax.scatter(mdates.num2date(x31), y31, color=BLUE, s=30, zorder=4, linewidths=0)

    # Oś X – bez marginesu z prawej
    ax.set_xlim(x_start, x_end)

    # Oś Y – 8 poziomych linii (zmiana z 10 na 8)
    NUM_Y_LINES = 8
    nice_max = max(math.ceil(max(y) / (NUM_Y_LINES-1)) * (NUM_Y_LINES-1), NUM_Y_LINES-1) if y else 7
    ax.set_ylim(0, nice_max)
    ax.set_yticks(np.linspace(0, nice_max, NUM_Y_LINES))

    # Siatka
    ax.set_axisbelow(True)
    loc, fmt, x_lbl = x_axis_config(x_start, x_end)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(fmt)
    ax.grid(True, which="major", color=GRID_MAJ, linewidth=0.7)

    # Stylizacja
    ax.tick_params(axis="both", which="both", colors=BLUE, labelsize=7)
    fig.autofmt_xdate(rotation=0, ha="center")
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontweight("bold")
        lbl.set_color(BLUE)

    for spine in ax.spines.values():
        spine.set_edgecolor(GRID_MAJ)

    ax.set_ylabel("Contributions", color=BLUE, fontsize=8,
                  fontfamily="DejaVu Sans", fontweight="bold")
    ax.set_xlabel(x_lbl, color=BLUE, fontsize=8,
                  fontfamily="DejaVu Sans", fontweight="bold")
    ax.set_title(
        f"{username} · Activity (last {len(x_dates)} days)",
        color=BLUE, fontsize=10, fontweight="normal",
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
