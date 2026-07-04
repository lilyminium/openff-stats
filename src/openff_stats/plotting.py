"""
Plotting utilities for openff-stats.
"""

import pathlib

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def plot_downloads_per_year(yearly_csv: str, output_path: str) -> None:
    """Plot total OpenFF conda-forge downloads per year.

    Reads the per-package yearly download CSV (data/downloads_yearly.csv),
    filters to openff category packages, sums across all packages per year,
    and saves a seaborn bar chart.

    Parameters
    ----------
    yearly_csv
        Path to the yearly downloads CSV (columns: package, category, year,
        condastats_downloads).
    output_path
        Path to save the PNG plot.
    """
    df = pd.read_csv(yearly_csv)

    # Filter to openff packages only
    openff_df = df[df["category"] == "openff"].copy()
    if openff_df.empty:
        print("No openff-category rows found in yearly CSV; skipping plot.")
        return

    # Sum downloads across all openff packages per year
    yearly_totals = (
        openff_df.groupby("year")["condastats_downloads"]
        .sum()
        .reset_index()
        .sort_values("year")
    )
    yearly_totals["year"] = yearly_totals["year"].astype(str)

    # Drop incomplete current year if it has significantly fewer downloads
    # (heuristic: last year has <20% of the max year's downloads)
    if len(yearly_totals) >= 2:
        max_downloads = yearly_totals["condastats_downloads"].max()
        last_row = yearly_totals.iloc[-1]
        if last_row["condastats_downloads"] < 0.2 * max_downloads:
            print(
                f"Note: dropping {last_row['year']} from plot "
                f"(likely incomplete year: {last_row['condastats_downloads']:,.0f} downloads)"
            )
            yearly_totals = yearly_totals.iloc[:-1]

    fig, ax = plt.subplots(figsize=(10, 6))
    sns.barplot(
        data=yearly_totals,
        x="year",
        y="condastats_downloads",
        color="#1f77b4",
        ax=ax,
    )

    ax.set_xlabel("Year", fontsize=12)
    ax.set_ylabel("Total Downloads (condastats)", fontsize=12)
    ax.set_title("Total OpenFF conda-forge Downloads per Year", fontsize=14)
    ax.tick_params(axis="x", rotation=45)

    # Annotate bars with formatted counts
    for patch in ax.patches:
        height = patch.get_height()
        if height > 0:
            ax.annotate(
                f"{int(height):,}",
                xy=(patch.get_x() + patch.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300)
    plt.close(fig)
    print(f"Saved download plot to {output_path}")


def plot_dep_tree(
    dep_tree_csv: str,
    output_path: str,
) -> None:
    """Plot the reverse-dependency tree as a dendrogram.

    Pure branch style — no circles.  All nodes are labelled.
    openff-* packages are sorted to the left; external packages to the right.

    Parameters
    ----------
    dep_tree_csv
        Path to the tree CSV produced by ``openff-stats dep-tree``.
    output_path
        Path to save the PNG.
    """
    from collections import defaultdict

    df = pd.read_csv(dep_tree_csv)
    if df.empty:
        print("Empty tree CSV; skipping plot.")
        return

    # Node metadata keyed by package name
    meta = (
        df.drop_duplicates("package")
        .set_index("package")[["level", "anaconda_downloads"]]
    )
    meta["anaconda_downloads"] = pd.to_numeric(
        meta["anaconda_downloads"], errors="coerce"
    ).fillna(0)

    # Children map: parent → [children], sorted by downloads descending
    # so larger subtrees are placed consistently on the left
    children: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        parent = row["parent"]
        if pd.notna(parent) and str(parent).strip():
            children[str(parent)].append(row["package"])
    for parent in children:
        children[parent].sort(
            key=lambda p: (
                0 if p.startswith("openff-") else 1,           # openff-* left
                -(meta.loc[p, "anaconda_downloads"] if p in meta.index else 0),  # then downloads desc
            )
        )

    roots = df[df["level"] == 0]["package"].tolist()

    # -----------------------------------------------------------------------
    # Recursive leaf-counting layout
    # Each leaf gets a unique x slot.  Each internal node is centred over
    # its children's x range.  Separate root subtrees get a small gap.
    # -----------------------------------------------------------------------
    pos: dict[str, tuple[float, float]] = {}
    leaf_counter = [0]

    def _place(node: str) -> None:
        kids = children.get(node, [])
        level = int(meta.loc[node, "level"]) if node in meta.index else 0
        if not kids:
            pos[node] = (leaf_counter[0] + 0.5, -level)
            leaf_counter[0] += 1
        else:
            for kid in kids:
                _place(kid)
            child_xs = [pos[k][0] for k in kids]
            pos[node] = ((min(child_xs) + max(child_xs)) / 2, -level)

    for i, root in enumerate(roots):
        if i > 0:
            leaf_counter[0] += 1.5  # gap between root subtrees
        _place(root)

    total_width = leaf_counter[0]
    max_level = int(meta["level"].max())

    # -----------------------------------------------------------------------
    # Figure sizing
    # -----------------------------------------------------------------------
    fig_w = max(14, total_width * 0.55)
    fig_h = max(5, (max_level + 1) * 2.2)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    # -----------------------------------------------------------------------
    # Dendrogram-style connectors: branch point halfway between levels
    # -----------------------------------------------------------------------
    for parent, kids in children.items():
        if parent not in pos:
            continue
        kids_drawn = [k for k in kids if k in pos]
        if not kids_drawn:
            continue

        px, py = pos[parent]
        branch_y = py - 0.45  # branch point just below parent node

        # Vertical stem from parent down to branch
        ax.plot([px, px], [py, branch_y], color="#aaaaaa", lw=1.0, zorder=1)
        # Horizontal bar spanning all children
        child_xs = [pos[k][0] for k in kids_drawn]
        ax.plot(
            [min(child_xs), max(child_xs)], [branch_y, branch_y],
            color="#aaaaaa", lw=1.0, zorder=1,
        )
        # Vertical drop from bar to each child
        for k in kids_drawn:
            cx, cy = pos[k]
            ax.plot([cx, cx], [branch_y, cy], color="#aaaaaa", lw=1.0, zorder=1)

    # -----------------------------------------------------------------------
    # Labels — no circles, pure dendrogram style
    # -----------------------------------------------------------------------
    for pkg, (x, y) in pos.items():
        lvl = int(meta.loc[pkg, "level"]) if pkg in meta.index else 0
        if lvl == 0:
            ax.text(x, y + 0.15, pkg,
                    ha="center", va="bottom", fontsize=9, fontweight="bold",
                    color="#1a1a1a", zorder=4)
        else:
            # Rotated label hanging below the branch tip
            ax.text(x, y - 0.08, pkg,
                    ha="left", va="top", fontsize=7,
                    rotation=-55, rotation_mode="anchor",
                    color="#1a1a1a", zorder=4)

    # -----------------------------------------------------------------------
    # Level annotations on left margin
    # -----------------------------------------------------------------------
    for lvl in range(max_level + 1):
        label = "root" if lvl == 0 else f"depth {lvl}"
        ax.text(
            -0.5, -lvl, label,
            ha="right", va="center", fontsize=8, color="#888888",
        )

    ax.set_title(
        "conda-forge Reverse Dependency Tree\n(openff-toolkit · all packages shown)",
        fontsize=11,
    )
    ax.set_xlim(-1.2, total_width + 0.5)
    ax.set_ylim(-max_level - 2.5, 0.8)  # extra bottom room for rotated labels
    ax.axis("off")
    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved dep-tree plot to {output_path}")


def plot_dependents(dependents_csv: str, output_path: str) -> None:
    """Plot conda-forge packages that depend on openff-toolkit.

    Reads candidates/dependents.csv (columns: package, version, openff_dep,
    subdir) and saves a horizontal bar chart of packages sorted by their
    minimum required openff-toolkit version.

    Parameters
    ----------
    dependents_csv
        Path to the dependents CSV.
    output_path
        Path to save the PNG plot.
    """
    import re

    df = pd.read_csv(dependents_csv)
    if df.empty:
        print("No dependents found; skipping plot.")
        return

    # Extract minimum version from the dependency string (e.g. "openff-toolkit >=0.11")
    def _min_ver(dep: str) -> str:
        match = re.search(r">=\s*([\d.]+)", str(dep))
        return match.group(1) if match else "any"

    df["min_version"] = df["openff_dep"].apply(_min_ver)
    df = df.sort_values(["min_version", "package"], ascending=[False, True])

    # Colour bars by minimum required version
    versions = df["min_version"].unique()
    palette = dict(zip(sorted(versions, reverse=True), sns.color_palette("Blues_r", len(versions))))
    colors = [palette[v] for v in df["min_version"]]

    fig, ax = plt.subplots(figsize=(10, max(4, len(df) * 0.35)))
    bars = ax.barh(df["package"], [1] * len(df), color=colors)

    # Annotate with version constraint
    for bar, dep in zip(bars, df["openff_dep"]):
        constraint = str(dep).replace("openff-toolkit", "").strip() or "unpinned"
        ax.text(
            0.02, bar.get_y() + bar.get_height() / 2,
            constraint,
            va="center", ha="left", fontsize=8, color="white",
        )

    ax.set_xlabel("")
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.set_title("conda-forge Packages Depending on openff-toolkit", fontsize=13)
    ax.invert_yaxis()

    # Legend for version groups
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=palette[v], label=f">={v}" if v != "any" else "any") for v in sorted(versions, reverse=True)]
    ax.legend(handles=legend_elements, title="Min version", bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8)

    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved dependents plot to {output_path}")


_DEFAULT_EXCLUDE_ORGS = ["openforcefield", "lilyminium", "ntBre", "jaclark5"]


_CATEGORY_COLORS = {
    "pose-generation":      "#e07b39",   # orange
    "free-energy":          "#5b8dd9",   # blue
    "md-setup-and-analysis": "#4caf7d",  # green
    "machine-learning":     "#9b59b6",   # purple
    "other":                "#8e9aaa",   # grey
}

_CATEGORY_LABELS = {
    "pose-generation":       "Pose Generation",
    "free-energy":           "Free Energy",
    "md-setup-and-analysis": "MD Setup & Analysis",
    "machine-learning":      "Machine Learning",
    "other":                 "Other",
}


def plot_github_bubbles(
    github_csv: str,
    stars_csv: str,
    output_path: str,
    star_threshold: int = 30,
    label_threshold: int = 100,
    exclude_orgs: list[str] | None = None,
    descriptions_csv: str | None = None,
) -> None:
    """Radial bubble chart of GitHub repos using openff-toolkit.

    Two-ring layout:
    - Inner ring (R=0.82): small grey dots for all repos, org-grouped.
    - Outer ring (R=1.15): repos with ≥ *star_threshold* stars, tangent-packed
      so adjacent bubbles are just touching, sized by log(stars).

    When *descriptions_csv* is supplied (columns: repo, category), outer
    bubbles are colored by topic category with a legend.  Otherwise all
    bubbles are a uniform blue.

    Repos with ≥ *label_threshold* stars get a full ``org/repo`` label along
    their spoke; repos below that threshold show only the repo name.
    Designed for slide presentation — large fonts throughout.

    Parameters
    ----------
    github_csv
        Path to the GitHub repos CSV (columns: repo, url).
    stars_csv
        Path to the star counts CSV (columns: repo, stars).
    output_path
        Path to save the PNG.
    star_threshold
        Minimum stars to appear on the outer ring.
    label_threshold
        Minimum stars to show the full ``org/repo`` label (vs. repo name only).
    exclude_orgs
        Orgs/users to exclude entirely.  Defaults to ``_DEFAULT_EXCLUDE_ORGS``.
    descriptions_csv
        Optional path to the descriptions CSV (columns: repo, category).
        When provided, outer bubbles are colored by category.
    """
    import math
    from collections import defaultdict
    from datetime import date

    import numpy as np
    from matplotlib.patches import Circle

    if exclude_orgs is None:
        exclude_orgs = _DEFAULT_EXCLUDE_ORGS

    # ── Data loading ──────────────────────────────────────────────────────────
    from openff_stats.github import load_curated_repos

    df = load_curated_repos(github_csv)
    df["owner"] = df["repo"].str.split("/").str[0]
    df = df[~df["owner"].isin(exclude_orgs)].reset_index(drop=True)

    sdf = pd.read_csv(stars_csv)
    stars: dict[str, int] = dict(zip(sdf["repo"], sdf["stars"].fillna(0).astype(int)))
    df["stars"] = df["repo"].map(stars).fillna(0).astype(int)

    repo_category: dict[str, str] = {}
    if descriptions_csv:
        ddf = pd.read_csv(descriptions_csv)
        repo_category = dict(zip(ddf["repo"], ddf["category"]))

    n_repos = len(df)
    n_highlighted = int((df["stars"] >= star_threshold).sum())
    max_stars = max(stars.values(), default=1)
    print(f"  {n_highlighted} repos ≥ {star_threshold} stars")

    # ── Inner ring: org-grouped ───────────────────────────────────────────────
    org_counts = df["owner"].value_counts()
    openff_orgs = sorted(o for o in org_counts.index if o.startswith("openff"))
    other_orgs = [o for o in org_counts.sort_values(ascending=False).index
                  if not o.startswith("openff")]
    ordered_orgs = openff_orgs + other_orgs

    org_repos: dict[str, list[str]] = defaultdict(list)
    for repo, owner in zip(df["repo"], df["owner"]):
        org_repos[owner].append(repo)
    for org in org_repos:
        org_repos[org].sort(key=lambda r: (-stars.get(r, 0), r))

    R_inner = 0.60
    gap_frac = 1.2
    total_slots = n_repos + gap_frac * len(ordered_orgs)
    inner_angles: dict[str, float] = {}
    org_arc: dict[str, tuple[float, float]] = {}
    slot = 0.0
    for org in ordered_orgs:
        start_slot = slot
        for repo in org_repos[org]:
            inner_angles[repo] = 2 * math.pi * (slot / total_slots) - math.pi / 2
            slot += 1
        org_arc[org] = (
            2 * math.pi * (start_slot / total_slots) - math.pi / 2,
            2 * math.pi * ((slot - 1) / total_slots) - math.pi / 2,
        )
        slot += gap_frac

    # ── Outer ring: category-sorted, tangent-packed with inter-category gaps ──
    R_outer = 0.92
    r_min_h, r_max_h = 0.018, 0.056

    def _r_h(s: int) -> float:
        t = (math.log1p(s) / math.log1p(max_stars)) ** 1.3
        return r_min_h + (r_max_h - r_min_h) * t

    def _dtheta(r1: float, r2: float, R: float) -> float:
        return 2 * math.asin(min((r1 + r2) / (2 * R), 1.0))

    # Sort highlighted repos by category, then by stars descending within each
    cat_repos: dict[str, list[str]] = defaultdict(list)
    for r in df["repo"]:
        if stars.get(r, 0) >= star_threshold:
            cat = repo_category.get(r, "other")
            cat_repos[cat].append(r)
    for cat in cat_repos:
        cat_repos[cat].sort(key=lambda r: -stars.get(r, 0))

    CATEGORY_ORDER = list(_CATEGORY_COLORS.keys())
    high_repos_ordered = [r for cat in CATEGORY_ORDER for r in cat_repos.get(cat, [])]
    n_h = len(high_repos_ordered)
    high_radii = [_r_h(stars[r]) for r in high_repos_ordered]

    # Tangent-pack: intra-category gap is smaller, inter-category gap is larger
    n_cats_present = sum(1 for cat in CATEGORY_ORDER if cat_repos.get(cat))
    total_ang = sum(
        _dtheta(high_radii[i], high_radii[(i + 1) % n_h], R_outer)
        for i in range(n_h)
    )
    if total_ang > 2 * math.pi * 0.88:
        scale = 2 * math.pi * 0.86 / total_ang
        high_radii = [r * scale for r in high_radii]
        total_ang = sum(
            _dtheta(high_radii[i], high_radii[(i + 1) % n_h], R_outer)
            for i in range(n_h)
        )
    extra = 2 * math.pi - total_ang
    # inter_gap = 4 × intra_gap; budget: n_h intra + n_cats inter
    intra_gap = extra / (n_h + 4 * n_cats_present)
    inter_gap = 4 * intra_gap

    cat_sequence = [repo_category.get(r, "other") for r in high_repos_ordered]
    is_last_in_cat = [
        i == n_h - 1 or cat_sequence[i] != cat_sequence[i + 1]
        for i in range(n_h)
    ]

    outer_angles: dict[str, float] = {}
    bubble_r: dict[str, float] = {}
    angle = -math.pi / 2
    for i, repo in enumerate(high_repos_ordered):
        outer_angles[repo] = angle
        bubble_r[repo] = high_radii[i]
        r_next = high_radii[(i + 1) % n_h]
        gap = inter_gap if is_last_in_cat[i] else intra_gap
        angle += _dtheta(high_radii[i], r_next, R_outer) + gap

    # Sector angle ranges (bubble-edge to bubble-edge)
    sector_arcs: dict[str, tuple[float, float]] = {}
    for cat in CATEGORY_ORDER:
        repos_in_cat = cat_repos.get(cat, [])
        if not repos_in_cat:
            continue
        angs = [outer_angles[r] for r in repos_in_cat]
        rads = [bubble_r[r] for r in repos_in_cat]
        a_start = angs[0] - _dtheta(rads[0], rads[0], R_outer) / 2
        a_end = angs[-1] + _dtheta(rads[-1], rads[-1], R_outer) / 2
        sector_arcs[cat] = (a_start, a_end)

    # ── Figure ────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(22, 22), facecolor="white")

    # Light spokes
    for repo in high_repos_ordered:
        ang = outer_angles[repo]
        rx, ry = R_outer * math.cos(ang), R_outer * math.sin(ang)
        ax.plot([0, rx], [0, ry], color="#eeeeee", lw=0.5, zorder=1)

    # Org labels in inner ring
    for org, (a0, a1) in org_arc.items():
        mid = (a0 + a1) / 2
        ox = 0.40 * math.cos(mid)
        oy = 0.40 * math.sin(mid)
        deg = math.degrees(mid)
        rotation = deg if -90 <= deg <= 90 else deg + 180
        col = "#1a5276" if org.startswith("openff") else "#999999"
        ax.text(ox, oy, org, ha="center", va="center", fontsize=5.5, color=col,
                rotation=rotation, rotation_mode="anchor", zorder=3)

    # Inner ring dots
    for repo, ang in inner_angles.items():
        s = stars.get(repo, 0)
        cx, cy = R_inner * math.cos(ang), R_inner * math.sin(ang)
        col = "#cccccc" if s < star_threshold else "#bbccdd"
        ax.add_patch(Circle((cx, cy), 0.006, facecolor=col, linewidth=0, zorder=2))

    # Outer bubbles colored by category
    def _bubble_color(repo: str) -> str:
        cat = repo_category.get(repo, "other") if repo_category else "other"
        return _CATEGORY_COLORS.get(cat, _CATEGORY_COLORS["other"])

    for repo in high_repos_ordered:
        ang = outer_angles[repo]
        r = bubble_r[repo]
        cx, cy = R_outer * math.cos(ang), R_outer * math.sin(ang)
        ax.add_patch(Circle((cx, cy), r, facecolor=_bubble_color(repo),
                             edgecolor="white", linewidth=0.9, alpha=0.90, zorder=4))

    # Sector arc + label — both inside the gap between the two rings
    # Arc just inside the outer bubble ring; label between arc and inner ring
    R_arc = R_outer - r_max_h - 0.04   # just inside the bubble inner edges
    R_label_inner = (R_inner + R_arc) / 2
    for cat, (a_start, a_end) in sector_arcs.items():
        color = _CATEGORY_COLORS[cat]
        theta = np.linspace(a_start, a_end, 120)
        ax.plot(R_arc * np.cos(theta), R_arc * np.sin(theta),
                color=color, lw=4, zorder=7, solid_capstyle="round", alpha=0.7)

        mid = (a_start + a_end) / 2
        lx = R_label_inner * math.cos(mid)
        ly = R_label_inner * math.sin(mid)
        deg = math.degrees(mid)
        rot = (deg + 90) % 360
        if 90 < rot <= 270:
            rot = (rot + 180) % 360
        ax.text(lx, ly, _CATEGORY_LABELS[cat], ha="center", va="center",
                fontsize=15, fontweight="bold", color=color,
                rotation=rot, rotation_mode="anchor", zorder=8)

    # Repo labels: org/repo; append (N★) for ≥ label_threshold stars
    for repo in high_repos_ordered:
        s = stars.get(repo, 0)
        ang = outer_angles[repo]
        r = bubble_r[repo]
        lx = (R_outer + r + 0.06) * math.cos(ang)
        ly = (R_outer + r + 0.06) * math.sin(ang)
        deg = math.degrees(ang)
        if -90 <= deg <= 90:
            ha, rotation = "left", deg
        else:
            ha, rotation = "right", deg + 180
        org_name, repo_name = repo.split("/", 1)
        if s >= 200:
            label = f"{org_name}\n{repo_name} ({s}★)"
        elif s >= label_threshold:
            label = f"{repo} ({s}★)"
        else:
            label = repo
        fontsize = 10 + 9 * (s / max_stars) ** 0.5   # 10 → 19
        ax.text(lx, ly, label, ha=ha, va="center",
                fontsize=fontsize, fontweight="bold",
                rotation=rotation, rotation_mode="anchor",
                color="#222222", zorder=5)

    # Central dot
    ax.plot(0, 0, "o", ms=14, color="#e74c3c", zorder=9)

    # ── Star-size legend (upper-left) ─────────────────────────────────────────
    lim = 2.10
    legend_x = -lim + 0.10
    legend_y = lim - 0.14
    legend_candidates = [50, 200, 500]
    legend_stars_leg = [sv for sv in legend_candidates if any(s >= sv for s in stars.values())]
    ax.text(legend_x, legend_y, "Stars", fontsize=14,
            fontweight="bold", color="#333333", va="top")
    cursor_y = legend_y - 0.22
    for sv in legend_stars_leg:
        r_leg = _r_h(sv)
        ax.add_patch(Circle((legend_x + r_leg, cursor_y), r_leg,
                             facecolor="#888888", alpha=0.85, zorder=8))
        ax.text(legend_x + r_leg * 2 + 0.06, cursor_y, f"{sv}★",
                va="center", fontsize=13, color="#333333")
        cursor_y -= 0.22

    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(
        f"GitHub Repos Using openff-toolkit\n"
        f"{n_repos:,} total repos  ·  {n_highlighted} with ≥{star_threshold} stars  ·  {date.today():%Y-%m-%d}",
        fontsize=24, fontweight="bold", pad=16, linespacing=1.5,
    )

    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved GitHub bubble chart to {output_path}")
