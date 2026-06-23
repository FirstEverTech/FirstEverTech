#!/usr/bin/env python3
"""
Stats SVG generator — FirstEverTech profile
Outputs:
  assets/github-downloads.svg   – 3 repo lines + Total (dashed), release markers
  assets/psgallery-downloads.svg – Rep1/Rep2 PSGallery lines, release markers
  assets/stars.svg               – daily star gain (total across repos)
  assets/followers.svg           – daily follower delta
  assets/profile-views.svg       – daily traffic views on profile repo
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

# Set these as Repository Variables in GitHub:
#   Settings → Secrets and variables → Actions → Variables
#   PS_REP1_MODULE  e.g. "Universal-Intel-Chipset-Updater"
#   PS_REP2_MODULE  e.g. "Universal-Intel-WiFi-BT-Updater"
PS_MODULES = {
    "Rep1": os.environ.get("PS_REP1_MODULE", ""),
    "Rep2": os.environ.get("PS_REP2_MODULE", ""),
}
PS_MODULES = {k: v for k, v in PS_MODULES.items() if v}  # drop blanks

HISTORY_FILE  = Path("assets/data/stats_history.json")
RELEASES_FILE = Path("assets/releases.conf")
ASSETS_DIR    = Path("assets")
DAYS = 31
TODAY = date.today()

# ── Visual style — identical palette to contribution-graph.py ──────────────
BLUE     = "#58a6ff"
LINE     = "#1f6feb"
GRID_MAJ = "#283d58"

LINE_COLORS = {
    "Rep1":  "#58a6ff",
    "Rep2":  "#3fb950",
    "Rep3":  "#f78166",
    "Total": "#e3b341",
}

# ── GitHub API helpers ─────────────────────────────────────────────────────
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
    """GitHub traffic API — last 14 days, requires push access (GITHUB_TOKEN is fine for own repo)."""
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
    """
    PSGallery v2 OData (NuGet). Sums DownloadCount across all versions of a module.
    Note: DownloadCount per entry = per-version count, not cumulative total.
    """
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
    """31-element list of (today_val - nearest_prev_val) for each day in window."""
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
        curr = get_val(d_key)
        prev = next(
            (get_val(k) for k in reversed(sorted_keys)
             if k < d_key and get_val(k) is not None),
            None
        )
        if curr is None or prev is None:
            result.append(0)
        else:
            result.append(max(0, curr - prev))

    return result

def date_range() -> list[date]:
    start = TODAY - timedelta(days=DAYS - 1)
    return [start + timedelta(days=i) for i in range(DAYS)]

# ── Release markers ────────────────────────────────────────────────────────
def load_releases() -> list[tuple[str, date]]:
    """
    Parses assets/releases.conf:
        Rep1 = 4/06
        Rep2 = 10/06
    Returns list of (alias, date). Year is always current year.
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

def draw_release_markers(ax, releases: list, x_start: float, x_end: float,
                          allowed: set | None = None):
    """
    Draws ▼ + label (R1/R2/R3) below X-axis for each release within the 31-day window.
    Must be called AFTER tight_layout so ylim is final.
    """
    y_bot = ax.get_ylim()[0]
    for alias, rel_date in releases:
        if allowed and alias not in allowed:
            continue
        rx = mdates.date2num(datetime.combine(rel_date, datetime.min.time()))
        if not (x_start <= rx <= x_end):
            continue
        label = re.sub(r"(?i)rep", "R", alias)
        ax.plot(rx, y_bot, "v", color=BLUE, markersize=5, clip_on=False, zorder=6)
        ax.annotate(
            label, xy=(rx, y_bot), xycoords="data",
            xytext=(0, -14), textcoords="offset points",
            fontsize=6, color=BLUE, ha="center", va="top",
            fontweight="bold", annotation_clip=False,
        )

# ── SVG draw animation (same implementation as contribution-graph.py) ──────
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

    target_colors = [LINE] + list(LINE_COLORS.values())
    for color in target_colors:
        pat = rf'<path[^>]*stroke="{re.escape(color)}"[^>]*>'
        def add_cls(mo, _color=color):
            o = mo.group(0)
            return (o.replace('class="', 'class="draw-line ', 1)
                    if 'class="' in o
                    else o.replace("<path", '<path class="draw-line"', 1))
        content = re.sub(pat, add_cls, content)

    svg_path.write_text(content, encoding="utf-8")

# ── Shared plot primitives ─────────────────────────────────────────────────
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

# ── Single-line graph ──────────────────────────────────────────────────────
def gen_single(dates: list[date], counts: list[int],
               title: str, ylabel: str, out: Path):
    y = np.array(counts, float)
    fig, ax = base_fig()
    x_num = setup_x_axis(ax, dates)
    setup_y_axis(ax, y.max() if y.size else 0)
    ax.margins(x=0.02, y=0.05)
    ax.set_ylim(bottom=-0.5)

    xs, ys = smooth(x_num, y)
    ax.plot(xs, ys, color=LINE, linewidth=2.5, zorder=3)
    ax.fill_between(xs, ys, color=LINE, alpha=0.15, zorder=2)
    ax.scatter(x_num, y, color=BLUE, s=30, zorder=4, linewidths=0)

    style_ax(ax, title, ylabel)
    plt.tight_layout(pad=0.8)
    save_svg(fig, out)

# ── Multi-line graph with optional total + release markers ─────────────────
def gen_multi(dates: list[date], series: dict[str, list[int]],
              title: str, ylabel: str, out: Path,
              show_total: bool = False,
              releases: list | None = None,
              allowed_aliases: set | None = None):
    fig, ax = base_fig(height=3.8)
    x_num = setup_x_axis(ax, dates)
    ax.margins(x=0.02, y=0.05)
    ax.set_ylim(bottom=-0.5)

    all_y: list[float] = []
    total = np.zeros(len(dates))

    for alias, counts in series.items():
        y = np.array(counts, float)
        total += y
        all_y.extend(counts)
        color = LINE_COLORS.get(alias, BLUE)
        xs, ys = smooth(x_num, y)
        ax.plot(xs, ys, color=color, linewidth=2.0, zorder=3, label=alias)
        ax.scatter(x_num, y, color=color, s=18, zorder=4, linewidths=0)

    if show_total and len(series) > 1:
        tc = LINE_COLORS["Total"]
        xs, ys = smooth(x_num, total)
        ax.plot(xs, ys, color=tc, linewidth=2.5, linestyle="--", zorder=3, label="Total")
        ax.scatter(x_num, total, color=tc, s=22, zorder=4, linewidths=0, marker="D")
        all_y.extend(total.tolist())

    setup_y_axis(ax, max(all_y) if all_y else 0)

    ncols = len(series) + (1 if show_total and len(series) > 1 else 0)
    ax.legend(fontsize=7, framealpha=0, labelcolor=BLUE,
              loc="upper left", ncol=ncols)
    style_ax(ax, title, ylabel)
    plt.tight_layout(pad=0.8)

    # markers AFTER tight_layout — ylim is stable now
    if releases:
        draw_release_markers(ax, releases, x_num[0], x_num[-1], allowed_aliases)

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

    # ── Stars (total across all repos — single line)
    gen_single(dates, daily_delta(h, "stars_total"),
               f"{name} — Daily Stars",
               "New Stars",
               ASSETS_DIR / "stars.svg")

    # ── Profile views (GitHub traffic API already returns daily counts)
    view_map = dict(fetch_profile_views())
    start    = TODAY - timedelta(days=DAYS - 1)
    views    = [view_map.get(start + timedelta(days=i), 0) for i in range(DAYS)]
    gen_single(dates, views,
               f"{name} — Profile Views",
               "Views / day",
               ASSETS_DIR / "profile-views.svg")

    # ── GitHub Downloads — Rep1/Rep2/Rep3 + Total (dashed), all release markers
    gh_dl = {alias: daily_delta(h, "gh_downloads", alias) for alias in REPOS}
    gen_multi(dates, gh_dl,
              f"{name} — GitHub Downloads / day",
              "Downloads / day",
              ASSETS_DIR / "github-downloads.svg",
              show_total=True,
              releases=releases,
              allowed_aliases=set(REPOS.keys()))

    # ── PSGallery Downloads — Rep1/Rep2 only, Rep1/Rep2 release markers
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
        print("[INFO] PS_MODULES empty — skipping psgallery-downloads.svg", file=sys.stderr)

if __name__ == "__main__":
    main()
