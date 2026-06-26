#!/usr/bin/env python3
"""
Stats SVG generator — FirstEverTech profile
Outputs:
  assets/github-downloads.svg    – Rep1/Rep2/Rep3 + Total, release + mention markers, stats
  assets/psgallery-downloads.svg – Rep1/Rep2, release + mention markers, stats
  assets/stars.svg               – daily stars total, stats
  assets/followers.svg           – daily follower delta, stats
  assets/profile-views.svg       – daily profile traffic, stats
"""
import os, sys, json, math, re, requests
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta, date, timezone
from pathlib import Path
from scipy.interpolate import PchipInterpolator

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

PS_MODULES = {
    "Rep1": os.environ.get("PS_REP1_MODULE", "universal-intel-chipset-device-updater"),
    "Rep2": os.environ.get("PS_REP2_MODULE", "universal-intel-wifi-bt-driver-updater"),
}

HISTORY_FILE  = Path("assets/data/stats_history.json")
RELEASES_FILE = Path("assets/releases.conf")
MENTIONS_FILE = Path("assets/mentions.conf")
ASSETS_DIR    = Path("assets")
DAYS = 31
TODAY = date.today()

# ── Color palette ──────────────────────────────────────────────────────────
BLUE     = "#58a6ff"
LINE     = "#1f6feb"
GRID_MAJ = "#283d58"

REP_COLORS = {
    "Rep1":  "#ffffff",   # white
    "Rep2":  "#3fb950",   # green
    "Rep3":  "#f78166",   # red-orange
    "Total": "#e3b341",   # yellow (dashed)
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
    try:
        r = requests.get(
            "https://www.powershellgallery.com/api/v2/FindPackagesById()",
            params={"id": f"'{module}'"},
            timeout=30,
        )
        r.raise_for_status()
        # VersionDownloadCount = per-version; DownloadCount = package total (same value repeated)
        counts = re.findall(r"<d:VersionDownloadCount[^>]*>(\d+)</d:VersionDownloadCount>", r.text)
        total = sum(int(c) for c in counts)
        print(f"[INFO] PSGallery {module}: versions={len(counts)} total={total}")
        return total
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
    followers   = fetch_followers()
    stars       = fetch_stars_total()
    gh_dl       = {alias: fetch_repo_downloads(full) for alias, full in REPOS.items()}
    ps_dl       = {alias: fetch_psgallery(mod)       for alias, mod  in PS_MODULES.items()}

    print(f"[INFO] {TODAY}  followers={followers}  stars={stars}")
    print(f"[INFO] gh_downloads={gh_dl}")
    print(f"[INFO] ps_downloads={ps_dl}")

    snap = {
        "followers":    followers,
        "stars_total":  stars,
        "gh_downloads": gh_dl,
        "ps_downloads": ps_dl,
    }

    existing = h.get(TODAY.isoformat(), {})
    h[TODAY.isoformat()] = {**existing, **snap}

    view_data = fetch_profile_views()
    print(f"[INFO] profile_views from API: {view_data}")
    for view_date, count in view_data:
        d_str = view_date.isoformat()
        if d_str not in h:
            h[d_str] = {}
        if count > 0 or "profile_views" not in h[d_str]:
            h[d_str]["profile_views"] = count

    return h

def daily_delta(h: dict, *key_path) -> list[int]:
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

# ── Annotation config files ────────────────────────────────────────────────
def _parse_conf(path: Path) -> list[tuple[str, date]]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
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

def load_releases() -> list[tuple[str, date]]:
    return _parse_conf(RELEASES_FILE)

def load_mentions() -> list[tuple[str, date]]:
    return _parse_conf(MENTIONS_FILE)

# ── Stats computation ──────────────────────────────────────────────────────
def compute_stats(counts: np.ndarray) -> tuple[str, str, str]:
    arr = counts.astype(float)
    done = arr[:-1]
    delta = done[-1] - done[-2] if len(done) >= 2 else 0.0
    avg7  = float(np.mean(done[-7:]))  if len(done) >= 7  else float(np.mean(done))
    avg31 = float(np.mean(done))
    delta_str = f"+{delta:.0f}" if delta >= 0 else f"{delta:.0f}"
    return delta_str, f"{avg7:.1f}", f"{avg31:.1f}"

def add_stats_bar(fig, counts: np.ndarray, y_pos: float = 0.04):
    delta_str, avg7, avg31 = compute_stats(counts)
    text = (
        f"▲ vs yesterday: {delta_str} / day"
        f"   │   ⌀ last 7 days: {avg7} / day"
        f"   │   ⌀ last 31 days: {avg31} / day"
    )
    fig.text(0.5, y_pos, text, ha="center", va="bottom",
             color=BLUE, fontsize=7.5, fontfamily="DejaVu Sans", fontweight="bold")

# ── SVG draw animation ─────────────────────────────────────────────────────
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
def base_fig(height: float = 3.8):
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
                  fontfamily="DejaVu Sans", fontweight="bold",
                  labelpad=10)

def setup_x_axis(ax, dates: list[date]) -> np.ndarray:
    x_num = mdates.date2num([datetime.combine(d, datetime.min.time()) for d in dates])
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d"))
    ax.tick_params(axis="x", pad=2)
    ax.grid(True, axis="x", color=GRID_MAJ, linewidth=0.7, linestyle=":")
    return x_num

def setup_y_axis(ax, y_max_val: float):
    N = 8
    if y_max_val <= 0:
        step = 1
    else:
        step = math.ceil(y_max_val / (N - 1))
    nice_max = step * (N - 1)
    if nice_max < N - 1:
        nice_max = N - 1
    ax.set_yticks(np.linspace(0, nice_max, N))
    ax.set_ylim(0, nice_max + step * 0.5)
    ax.grid(True, axis="y", color=GRID_MAJ, linewidth=0.7, linestyle=":")

def smooth(x_num: np.ndarray, y) -> tuple[np.ndarray, np.ndarray]:
    y = np.array(y, float)
    if len(x_num) < 3:
        return x_num, np.maximum(y, 0)
    interp = PchipInterpolator(x_num, y)
    xs = np.linspace(x_num[0], x_num[-1], 300)
    return xs, np.maximum(interp(xs), 0)

def save_svg(fig, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format="svg", bbox_inches="tight",
                transparent=True, pad_inches=0.3)
    plt.close(fig)
    add_draw_animation(out)

# ── Annotation markers ─────────────────────────────────────────────────────
def _alias_to_short(alias: str, prefix: str) -> str:
    num = re.sub(r"(?i)rep", "", alias)
    return f"{prefix}{num}"

def apply_annotations(ax, fig, dates: list[date],
                       releases: list[tuple[str, date]],
                       mentions:  list[tuple[str, date]],
                       allowed: set | None = None):
    date_set = set(dates)
    x_nums   = {d: mdates.date2num(datetime.combine(d, datetime.min.time())) for d in dates}
    x_start  = min(x_nums.values())
    x_end    = max(x_nums.values())
    y_bot    = ax.get_ylim()[0]

    tick_colors: dict[date, str] = {}

    def draw_marker(alias, rel_date, marker_symbol, y_offset, label_prefix):
        if allowed and alias not in allowed:
            return
        rx = mdates.date2num(datetime.combine(rel_date, datetime.min.time()))
        if not (x_start <= rx <= x_end):
            return
        color = REP_COLORS.get(alias, BLUE)
        label = _alias_to_short(alias, label_prefix)
        ax.plot(rx, y_bot, marker_symbol, color=color,
                markersize=5, clip_on=False, zorder=6)
        ax.annotate(
            label, xy=(rx, y_bot), xycoords="data",
            xytext=(0, y_offset), textcoords="offset points",
            fontsize=6, color=color, ha="center", va="top",
            fontweight="bold", annotation_clip=False,
        )
        tick_colors[rel_date] = color

    # R1/R2 i M1/M2 – znaczniki tuż pod osią
    for alias, d in releases:
        draw_marker(alias, d, "v", -10, "R")
    for alias, d in mentions:
        draw_marker(alias, d, "*", -18, "M")

    if not tick_colors:
        return
    fig.canvas.draw()
    for lbl in ax.get_xticklabels():
        if not lbl.get_text():
            continue
        try:
            tick_date = mdates.num2date(lbl.get_position()[0]).date()
        except (ValueError, OverflowError):
            continue
        if tick_date in tick_colors:
            lbl.set_color(tick_colors[tick_date])
            lbl.set_fontweight("bold")
            lbl.set_fontsize(8)

# ── Single-line graph ──────────────────────────────────────────────────────
def gen_single(dates: list[date], counts: list[int],
               title: str, ylabel: str, out: Path,
               releases: list | None = None,
               mentions:  list | None = None,
               allowed_aliases: set | None = None):
    y = np.array(counts, float)
    fig, ax = base_fig(height=3.8)
    x_num = setup_x_axis(ax, dates)
    setup_y_axis(ax, float(y.max()) if y.size else 0)
    ax.margins(x=0.02, y=0.05)

    xs, ys = smooth(x_num, y)
    ax.plot(xs, ys, color=LINE, linewidth=2.5, zorder=3)
    ax.fill_between(xs, ys, color=LINE, alpha=0.15, zorder=2)
    ax.scatter(x_num, y, color=BLUE, s=30, zorder=4, linewidths=0)

    style_ax(ax, title, ylabel)
    plt.tight_layout(pad=0.8)
    plt.subplots_adjust(bottom=0.18)

    add_stats_bar(fig, y)   # domyślnie y_pos=0.04

    if releases or mentions:
        apply_annotations(ax, fig, dates,
                          releases or [], mentions or [],
                          allowed_aliases)
    save_svg(fig, out)

# ── Multi-line graph ───────────────────────────────────────────────────────
def gen_multi(dates: list[date], series: dict[str, list[int]],
              title: str, ylabel: str, out: Path,
              show_total: bool = False,
              releases: list | None = None,
              mentions:  list | None = None,
              allowed_aliases: set | None = None):
    fig, ax = base_fig(height=4.3)
    x_num = setup_x_axis(ax, dates)
    ax.margins(x=0.02, y=0.05)

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

    # LEGENDA PRZYWRÓCONA DO ORYGINAŁU (górny lewy róg)
    handles, labels = ax.get_legend_handles_labels()
    leg = ax.legend(handles, labels, fontsize=7, framealpha=0,
                    loc="upper left",
                    ncol=len(series) + (1 if show_total and len(series) > 1 else 0))
    all_aliases = list(series.keys()) + (["Total"] if show_total and len(series) > 1 else [])
    for text, alias in zip(leg.get_texts(), all_aliases):
        text.set_color(REP_COLORS.get(alias, BLUE))

    style_ax(ax, title, ylabel)
    # Override xlabel labelpad to push "Last Month" below the R/M annotation markers
    ax.set_xlabel("Last Month", color=BLUE, fontsize=8,
                  fontfamily="DejaVu Sans", fontweight="bold",
                  labelpad=20)
    plt.tight_layout(pad=0.8)
    plt.subplots_adjust(bottom=0.28)

    add_stats_bar(fig, total, y_pos=0.10)

    if releases or mentions:
        apply_annotations(ax, fig, dates,
                          releases or [], mentions or [],
                          allowed_aliases)
    save_svg(fig, out)

# ── Contribution graph footer ──────────────────────────────────────────────
def add_contribution_footer(svg_path: Path, stats_text: str):
    if not svg_path.exists():
        print(f"[WARN] {svg_path} not found, skipping footer", file=sys.stderr)
        return

    content = svg_path.read_text(encoding="utf-8")
    content = re.sub(
        r'<!-- stats-footer -->.*?<!-- /stats-footer -->',
        '', content, flags=re.DOTALL
    )

    m_w = re.search(r'(<svg[^>]+width=["\'])([0-9.]+)(["\'])', content)
    m_h = re.search(r'(<svg[^>]+height=["\'])([0-9.]+)(["\'])', content)
    if not m_w or not m_h:
        print("[WARN] contribution SVG: cannot parse width/height, skipping footer",
              file=sys.stderr)
        return

    svg_w   = float(m_w.group(2))
    svg_h   = float(m_h.group(2))
    new_h   = svg_h + 120
    cx      = svg_w / 2

    content = content[:m_h.start()] + m_h.group(1) + str(new_h) + m_h.group(3) + content[m_h.end():]

    def _extend_vb(m):
        parts = m.group(2).split()
        if len(parts) == 4:
            parts[3] = str(float(parts[3]) + 120)
        return m.group(1) + " ".join(parts) + m.group(3)
    content = re.sub(r'(viewBox=["\'])([^"\']+)(["\'])', _extend_vb, content, count=1)

    last_month_y = svg_h + 35
    stats_y      = svg_h + 65

    footer = (
        f'\n<!-- stats-footer -->\n'
        f'<text x="{cx}" y="{last_month_y}" text-anchor="middle" '
        f'font-family="DejaVu Sans" font-size="11" font-weight="bold" '
        f'fill="{BLUE}">Last Month</text>\n'
        f'<text x="{cx}" y="{stats_y}" text-anchor="middle" '
        f'font-family="DejaVu Sans" font-size="8.5" font-weight="bold" '
        f'fill="{BLUE}">{stats_text}</text>\n'
        f'<!-- /stats-footer -->\n'
    )
    content = content.replace("</svg>", footer + "</svg>")
    svg_path.write_text(content, encoding="utf-8")
    print(f"[INFO] contribution footer written → height {svg_h} → {new_h}")

# ── Main ───────────────────────────────────────────────────────────────────
def main():
    h = load_history()
    h = take_snapshot(h)
    save_history(h)

    releases = load_releases()
    mentions  = load_mentions()
    dates     = date_range()
    name      = "Marcin Grygiel aka FirstEver"

    mention_aliases = {"Rep1", "Rep2"}

    # ── Followers
    gen_single(dates, daily_delta(h, "followers"),
               f"{name} — Daily Follower Growth", "New Followers",
               ASSETS_DIR / "followers.svg")

    # ── Stars (total)
    gen_single(dates, daily_delta(h, "stars_total"),
               f"{name} — Daily Stars", "New Stars",
               ASSETS_DIR / "stars.svg")

    # ── Profile views
    start = TODAY - timedelta(days=DAYS - 1)
    views = [
        h.get((start + timedelta(days=i)).isoformat(), {}).get("profile_views", 0)
        for i in range(DAYS)
    ]
    gen_single(dates, views,
               f"{name} — Profile Views", "Views / day",
               ASSETS_DIR / "profile-views.svg")

    # ── GitHub Downloads
    gh_dl = {alias: daily_delta(h, "gh_downloads", alias) for alias in REPOS}
    gen_multi(dates, gh_dl,
              f"{name} — GitHub Downloads / day", "Downloads / day",
              ASSETS_DIR / "github-downloads.svg",
              show_total=True,
              releases=releases,
              mentions=mentions,
              allowed_aliases=set(REPOS.keys()))

    # ── PSGallery Downloads
    ps_dl = {alias: daily_delta(h, "ps_downloads", alias) for alias in PS_MODULES}
    gen_multi(dates, ps_dl,
              f"{name} — PSGallery Downloads / day", "Downloads / day",
              ASSETS_DIR / "psgallery-downloads.svg",
              show_total=False,
              releases=releases,
              mentions=mentions,
              allowed_aliases={"Rep1", "Rep2"})

    # ── Contribution graph footer
    views_arr = np.array(views, float)
    delta_str, avg7, avg31 = compute_stats(views_arr)
    contrib_stats = (
        f"▲ vs yesterday: {delta_str} / day"
        f"   │   ⌀ last 7 days: {avg7} / day"
        f"   │   ⌀ last 31 days: {avg31} / day"
    )
    add_contribution_footer(ASSETS_DIR / "contribution-graph.svg", contrib_stats)

if __name__ == "__main__":
    main()
