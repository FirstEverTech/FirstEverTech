#!/usr/bin/env python3
"""
Stats SVG generator — FirstEverTech profile
Outputs:
  assets/github-downloads.svg    – Rep1/Rep2/Rep3 + Total, release markers, stats bar
  assets/psgallery-downloads.svg – Rep1/Rep2, release markers, stats bar
  assets/stars.svg               – daily stars total
  assets/followers.svg           – daily follower delta
  assets/profile-views.svg       – daily profile traffic
"""
import os, sys, json, math, re, requests
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from scipy.interpolate import CubicSpline

# ── Config ─────────────────────────────────────────────────────────────────
USERNAME     = os.environ.get("GH_USERNAME", "FirstEverTech")
TOKEN        = os.environ.get("GITHUB_TOKEN", "")
PROFILE_REPO = f"{USERNAME}/{USERNAME}"

HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"Bearer {TOKEN}",
}

REPOS = {
    "Rep1": "FirstEverTech/Universal-Intel-Chipset-Updater",
    "Rep2": "FirstEverTech/Universal-Intel-WiFi-BT-Updater",
    "Rep3": "FirstEverTech/Adobe-AVX2-Patch",
}

# Set as Repository Variables: Settings → Secrets and variables → Actions → Variables
PS_MODULES = {
    "Rep1": os.environ.get("PS_REP1_MODULE", ""),
    "Rep2": os.environ.get("PS_REP2_MODULE", ""),
}
PS_MODULES = {k: v for k, v in PS_MODULES.items() if v}

HISTORY_FILE  = Path("assets/data/stats_history.json")
RELEASES_FILE = Path("assets/releases.conf")
ASSETS_DIR    = Path("assets")
DAYS = 31
TODAY = date.today()

# ── Color palette ──────────────────────────────────────────────────────────
# Rep colors apply to: graph lines, release marker dots, release labels,
# AND the X-axis day number when a release lands on that day.
#
#   Rep1 = white  (clearly visible on GitHub dark-mode background)
#   Rep2 = green
#   Rep3 = red-orange
#   Total = yellow (dashed line, no release markers)
#
BLUE     = "#58a6ff"   # default / axis labels / grid
LINE     = "#1f6feb"   # single-line charts
GRID_MAJ = "#283d58"

REP_COLORS = {
    "Rep1":  "#ffffff",   # white
    "Rep2":  "#3fb950",   # green
    "Rep3":  "#f78166",   # red-orange
    "Total": "#e3b341",   # yellow
}

# ── GitHub API ─────────────────────────────────────────────────────────────
def gh(path, params=None):
    r = requests.get(f"https://api.github.com{path}", headers=HEADERS,
                     params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def fetch_followers() -> int:
    return gh(f"/users/{USERNAME}")["followers"]

def fetch_stars_total() -> int:
    return sum(gh(f"/repos/{full}")["stargazers_count"] for full in REPOS.values())

def fetch_repo_downloads(full_repo: str) -> int:
    releases = gh(f"/repos/{full_repo}/releases", {"per_page": 100})
    return sum(a.get("download_count", 0)
               for rel in releases for a in rel.get("assets", []))

def fetch_profile_views() -> list[tuple[date, int]]:
    """Traffic API returns last 14 days of daily counts. Requires push access (own repo = ok)."""
    try:
        data = gh(f"/repos/{PROFILE_REPO}/traffic/views")
        return [
            (datetime.fromisoformat(v["timestamp"].rstrip("Z")).date(), v["count"])
            for v in data.get("views", [])
        ]
    except Exception as e:
        print(f"[WARN] profile views: {e}", file=sys.stderr)
        return []

def fetch_psgallery(module: str) -> int:
    """PSGallery v2 OData — sums DownloadCount across all versions of the module."""
    try:
        r = requests.get(
            "https://www.powershellgallery.com/api/v2/FindPackagesById()",
            params={"id": f"'{module}'", "$select": "DownloadCount"},
            timeout=30,
        )
        counts = re.findall(r"<d:DownloadCount[^>]*>(\d+)</d:DownloadCount>", r.text)
        return sum(int(c) for c in counts)
    except Exception as e:
        print(f"[WARN] PSGallery {module}: {e}", file=sys.stderr)
        return 0

# ── History ────────────────────────────────────────────────────────────────
def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {}

def save_history(h: dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(h, indent=2))

def take_snapshot(h: dict) -> dict:
    snap = {
        "followers":    fetch_followers(),
        "stars_total":  fetch_stars_total(),
        "gh_downloads": {alias: fetch_repo_downloads(full) for alias, full in REPOS.items()},
        "ps_downloads": {alias: fetch_psgallery(mod) for alias, mod in PS_MODULES.items()},
    }
    h[TODAY.isoformat()] = snap
    return h

def daily_delta(h: dict, *key_path) -> list[int]:
    """31-element list of non-negative daily deltas within the rolling window."""
    def get_val(day_key: str):
        node = h.get(day_key, {})
        for k in key_path:
            if not isinstance(node, dict):
                return None
            node = node.get(k)
        return node

    sorted_keys = sorted(h.keys())
    start = TODAY - timedelta(days=DAYS - 1)
    result = []

    for i in range(DAYS):
        d_key = (start + timedelta(days=i)).isoformat()
        curr  = get_val(d_key)
        prev  = next(
            (get_val(k) for k in reversed(sorted_keys)
             if k < d_key and get_val(k) is not None),
            None,
        )
        if curr is None or prev is None:
            result.append(0)
        else:
            result.append(max(0, curr - prev))

    return result

def date_range() -> list[date]:
    start = TODAY - timedelta(days=DAYS - 1)
    return [start + timedelta(days=i) for i in range(DAYS)]

# ── Release config ─────────────────────────────────────────────────────────
def load_releases() -> list[tuple[str, date]]:
    """
    Parses assets/releases.conf:
        Rep1 = 4/06
        Rep2 = 10/06
    Returns list of (alias, date). Year = current year.
    """
    if not RELEASES_FILE.exists():
        return []
    result = []
    for line in RELEASES_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"(\w+)\s*=\s*(\d{1,2})/(\d{2})$", line)
        if m:
            alias, day, month = m.group(1), int(m.group(2)), int(m.group(3))
            try:
                result.append((alias, date(TODAY.year, month, day)))
            except ValueError:
                pass
    return result

# ── Stats computation ──────────────────────────────────────────────────────
def compute_stats(total_counts: np.ndarray) -> tuple[str, str, str]:
    """
    Returns (delta_vs_yesterday, avg_7day, avg_31day) as formatted strings.
    total_counts: 31-element array of daily totals.
    """
    arr = total_counts.astype(float)
    delta = arr[-1] - arr[-2] if len(arr) >= 2 else arr[-1] if len(arr) else 0.0
    avg7  = float(np.mean(arr[-7:]))  if len(arr) >= 7  else float(np.mean(arr))
    avg31 = float(np.mean(arr))

    delta_str = f"+{delta:.0f}" if delta >= 0 else f"{delta:.0f}"
    return delta_str, f"{avg7:.1f}", f"{avg31:.1f}"

def add_stats_bar(fig, total_counts: np.ndarray):
    """Adds a one-line stats strip at the very bottom of the figure."""
    delta_str, avg7, avg31 = compute_stats(total_counts)
    text = (
        f"▲ vs yesterday: {delta_str} / day   "
        f"│   ⌀ last 7 days: {avg7} / day   "
        f"│   ⌀ last 31 days: {avg31} / day"
    )
    fig.text(0.5, 0.005, text, ha="center", va="bottom",
             color=BLUE, fontsize=7.5, fontfamily="DejaVu Sans", fontweight="bold")

# ── SVG animation (identical to contribution-graph.py) ────────────────────
def add_draw_animation(svg_path: Path):
    content = svg_path.read_text(encoding="utf-8")
    style = (
        "<style>\n"
        ".draw-line{stroke-dasharray:3000;stroke-dashoffset:3000;"
        "animation:draw 3s ease-out forwards}\n"
        "@keyframes draw{to{stroke-dashoffset:0}}\n"
        "</style>"
    )
    m = re.search(r"(<svg[^>]*>)", content, re.DOTALL)
    if m:
        content = content.replace(m.group(1), m.group(1) + "\n" + style, 1)
    else:
        content = content.replace("</svg>", style + "\n</svg>", 1)

    for color in [LINE] + list(REP_COLORS.values()):
        pat = rf'<path[^>]*stroke="{re.escape(color)}"[^>]*>'
        def add_cls(mo):
            o = mo.group(0)
            return (o.replace('class="', 'class="draw-line ', 1)
                    if 'class="' in o
                    else o.replace("<path", '<path class="draw-line"', 1))
        content = re.sub(pat, add_cls, content)

    svg_path.write_text(content, encoding="utf-8")

# ── Core plot helpers ──────────────────────────────────────────────────────
def base_fig(height: float = 3.2):
    fig, ax = plt.subplots(figsize=(10, height), dpi=150)
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")
    return fig, ax

def style_ax(ax, title: str, ylabel: str):
    ax.tick_params(axis="both", colors=BLUE, labelsize=7)
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontweight("bold")
        lbl.set_color(BLUE)
    for sp in ax.spines.values():
        sp.set_edgecolor(GRID_MAJ)
    ax.set_title(title, color=BLUE, fontsize=10, fontweight="bold",
                 fontfamily="DejaVu Sans", pad=10)
    ax.set_ylabel(ylabel, color=BLUE, fontsize=8,
                  fontfamily="DejaVu Sans", fontweight="bold")
    ax.set_xlabel("Last Month", color=BLUE, fontsize=8,
                  fontfamily="DejaVu Sans", fontweight="bold")

def setup_x_axis(ax, dates: list[date]) -> np.ndarray:
    x_num = mdates.date2num([datetime.combine(d, datetime.min.time()) for d in dates])
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d"))
    ax.grid(True, axis="x", color=GRID_MAJ, linewidth=0.7, linestyle=":")
    return x_num

def setup_y_axis(ax, y_max_val: float):
    N = 8
    nice_max = max(N - 1, math.ceil(y_max_val / max(1, N - 1)) * (N - 1))
    ax.set_yticks(np.linspace(0, nice_max, N))
    ax.grid(True, axis="y", color=GRID_MAJ, linewidth=0.7, linestyle=":")

def smooth(x_num: np.ndarray, y) -> tuple[np.ndarray, np.ndarray]:
    y = np.array(y, float)
    if len(x_num) < 3:
        return x_num, np.maximum(y, 0)
    cs = CubicSpline(x_num, y, bc_type="natural")
    xs = np.linspace(x_num[0], x_num[-1], 300)
    return xs, np.maximum(cs(xs), 0)

def save_svg(fig, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="svg", bbox_inches="tight",
                transparent=True, pad_inches=0.3)
    plt.close(fig)
    add_draw_animation(out)

# ── Release markers + colored tick labels ──────────────────────────────────
def apply_release_visuals(ax, fig, dates: list[date],
                           releases: list[tuple[str, date]],
                           allowed: set | None = None):
    """
    1. Draws ▼ + label below X-axis for each release in the 31-day window.
    2. Recolors the X-axis day number to match the rep's color.
    Colors: Rep1=white, Rep2=green, Rep3=red-orange (from REP_COLORS).
    Call AFTER tight_layout so ylim and tick positions are stable.
    """
    # Build date→color map (if two releases on same day, last entry wins)
    release_color_map: dict[date, str] = {}
    release_label_map: dict[date, str] = {}
    for alias, rel_date in releases:
        if allowed and alias not in allowed:
            continue
        if rel_date not in [d for d in dates]:
            # Still mark it even if outside dates list — but only if in window
            pass
        release_color_map[rel_date] = REP_COLORS.get(alias, BLUE)
        release_label_map[rel_date] = re.sub(r"(?i)rep", "R", alias)

    x_num = mdates.date2num([datetime.combine(d, datetime.min.time()) for d in dates])
    x_start, x_end = x_num[0], x_num[-1]

    # ── Markers below X-axis ──────────────────────────────────────────────
    y_bot = ax.get_ylim()[0]
    for alias, rel_date in releases:
        if allowed and alias not in allowed:
            continue
        rx = mdates.date2num(datetime.combine(rel_date, datetime.min.time()))
        if not (x_start <= rx <= x_end):
            continue
        color = REP_COLORS.get(alias, BLUE)
        label = re.sub(r"(?i)rep", "R", alias)
        ax.plot(rx, y_bot, "v", color=color, markersize=5, clip_on=False, zorder=6)
        ax.annotate(
            label, xy=(rx, y_bot), xycoords="data",
            xytext=(0, -14), textcoords="offset points",
            fontsize=6, color=color, ha="center", va="top",
            fontweight="bold", annotation_clip=False,
        )

    # ── Color the day-number tick labels ──────────────────────────────────
    if not release_color_map:
        return
    fig.canvas.draw()  # required to populate tick label positions
    for label in ax.get_xticklabels():
        text = label.get_text()
        if not text:
            continue
        try:
            # Resolve the tick position back to an actual date
            pos = label.get_position()[0]  # x in data coords (matplotlib date float)
            tick_date = mdates.num2date(pos).date()
        except (ValueError, OverflowError):
            continue
        if tick_date in release_color_map:
            label.set_color(release_color_map[tick_date])
            label.set_fontweight("bold")
            label.set_fontsize(8)

# ── Single-line graph ──────────────────────────────────────────────────────
def gen_single(dates: list[date], counts: list[int],
               title: str, ylabel: str, out: Path):
    y = np.array(counts, float)
    fig, ax = base_fig()
    x_num = setup_x_axis(ax, dates)
    setup_y_axis(ax, float(y.max()) if y.size else 0)
    ax.margins(x=0.02, y=0.05)
    ax.set_ylim(bottom=-0.5)

    xs, ys = smooth(x_num, y)
    ax.plot(xs, ys, color=LINE, linewidth=2.5, zorder=3)
    ax.fill_between(xs, ys, color=LINE, alpha=0.15, zorder=2)
    ax.scatter(x_num, y, color=BLUE, s=30, zorder=4, linewidths=0)

    style_ax(ax, title, ylabel)
    plt.tight_layout(pad=0.8)
    save_svg(fig, out)

# ── Multi-line graph (downloads) ───────────────────────────────────────────
def gen_multi(dates: list[date], series: dict[str, list[int]],
              title: str, ylabel: str, out: Path,
              show_total: bool = False,
              releases: list | None = None,
              allowed_aliases: set | None = None):
    """
    series: ordered dict {alias: counts}
    Stats bar (Δ yesterday / 7-day avg / 31-day avg) appended below chart.
    """
    fig, ax = base_fig(height=4.3)   # extra height for stats bar
    x_num = setup_x_axis(ax, dates)
    ax.margins(x=0.02, y=0.05)
    ax.set_ylim(bottom=-0.5)

    all_y: list[float] = []
    total = np.zeros(len(dates))

    for alias, counts in series.items():
        y = np.array(counts, float)
        total += y
        all_y.extend(counts)
        color = REP_COLORS.get(alias, BLUE)
        xs, ys = smooth(x_num, y)
        ax.plot(xs, ys, color=color, linewidth=2.0, zorder=3, label=alias)
        ax.scatter(x_num, y, color=color, s=18, zorder=4, linewidths=0)

    if show_total and len(series) > 1:
        tc = REP_COLORS["Total"]
        xs, ys = smooth(x_num, total)
        ax.plot(xs, ys, color=tc, linewidth=2.5, linestyle="--", zorder=3, label="Total")
        ax.scatter(x_num, total, color=tc, s=22, zorder=4, linewidths=0, marker="D")
        all_y.extend(total.tolist())

    setup_y_axis(ax, max(all_y) if all_y else 0)

    ncols = len(series) + (1 if show_total and len(series) > 1 else 0)
    ax.legend(fontsize=7, framealpha=0, labelcolor="none",
              loc="upper left", ncol=ncols).remove()

    # Manual legend so we can color each entry with its rep color
    handles, labels = ax.get_legend_handles_labels()
    leg = ax.legend(handles, labels, fontsize=7, framealpha=0,
                    loc="upper left", ncol=ncols)
    for text, alias in zip(leg.get_texts(), list(series.keys()) + (["Total"] if show_total and len(series) > 1 else [])):
        text.set_color(REP_COLORS.get(alias, BLUE))

    style_ax(ax, title, ylabel)
    plt.tight_layout(pad=0.8)
    plt.subplots_adjust(bottom=0.13)   # room for stats bar

    # Stats bar
    add_stats_bar(fig, total)

    # Release markers + colored tick labels (must be after tight_layout)
    if releases:
        apply_release_visuals(ax, fig, dates, releases, allowed_aliases)

    save_svg(fig, out)

# ── Main ───────────────────────────────────────────────────────────────────
def main():
    h = load_history()
    h = take_snapshot(h)
    save_history(h)

    releases = load_releases()
    dates    = date_range()
    name     = "Marcin Grygiel aka FirstEver"

    # ── Followers
    gen_single(dates, daily_delta(h, "followers"),
               f"{name} — Daily Follower Growth",
               "New Followers",
               ASSETS_DIR / "followers.svg")

    # ── Stars (total)
    gen_single(dates, daily_delta(h, "stars_total"),
               f"{name} — Daily Stars",
               "New Stars",
               ASSETS_DIR / "stars.svg")

    # ── Profile views (GitHub traffic API: 14-day daily data)
    view_map = dict(fetch_profile_views())
    start    = TODAY - timedelta(days=DAYS - 1)
    views    = [view_map.get(start + timedelta(days=i), 0) for i in range(DAYS)]
    gen_single(dates, views,
               f"{name} — Profile Views",
               "Views / day",
               ASSETS_DIR / "profile-views.svg")

    # ── GitHub Downloads — Rep1/Rep2/Rep3 + Total + markers + stats
    gh_dl = {alias: daily_delta(h, "gh_downloads", alias) for alias in REPOS}
    gen_multi(dates, gh_dl,
              f"{name} — GitHub Downloads / day",
              "Downloads / day",
              ASSETS_DIR / "github-downloads.svg",
              show_total=True,
              releases=releases,
              allowed_aliases=set(REPOS.keys()))

    # ── PSGallery Downloads — Rep1/Rep2 + markers (Rep1/Rep2 only) + stats
    if PS_MODULES:
        ps_dl = {alias: daily_delta(h, "ps_downloads", alias) for alias in PS_MODULES}
        gen_multi(dates, ps_dl,
                  f"{name} — PSGallery Downloads / day",
                  "Downloads / day",
                  ASSETS_DIR / "psgallery-downloads.svg",
                  show_total=False,
                  releases=releases,
                  allowed_aliases={"Rep1", "Rep2"})
    else:
        print("[INFO] PS_MODULE env vars not set — skipping psgallery-downloads.svg",
              file=sys.stderr)

if __name__ == "__main__":
    main()
