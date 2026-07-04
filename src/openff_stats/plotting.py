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
    fig.savefig(output_path, dpi=150)
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
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
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
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved dependents plot to {output_path}")


_DEFAULT_EXCLUDE_ORGS = ["openforcefield", "lilyminium", "ntBre", "jaclark5"]


def plot_github_tree(
    github_csv: str,
    output_path: str,
    exclude_orgs: list[str] | None = None,
    stars_csv: str | None = None,
) -> None:
    """Plot all GitHub repos as a radial dendrogram grouped by organisation.

    Repos are arranged in a circle; each org occupies an angular sector.
    openff-* orgs are coloured distinctly from external orgs.  Labels sit
    along their radial spokes.  If *stars_csv* is provided, spoke line weight
    and label font size are scaled by log(stars+1).

    Parameters
    ----------
    github_csv
        Path to the GitHub repos CSV (columns: repo, url).
    output_path
        Path to save the PNG.
    exclude_orgs
        List of org/user names to exclude entirely.  Defaults to
        ``_DEFAULT_EXCLUDE_ORGS``.
    stars_csv
        Optional path to a CSV with columns ``repo`` and ``stars``.  When
        supplied, high-starred repos are drawn with thicker lines and larger
        labels.
    """
    import math
    from collections import defaultdict

    if exclude_orgs is None:
        exclude_orgs = _DEFAULT_EXCLUDE_ORGS

    df = pd.read_csv(github_csv)
    if df.empty:
        print("No GitHub repos found; skipping radial tree plot.")
        return

    df["owner"] = df["repo"].str.split("/").str[0]
    df = df[~df["owner"].isin(exclude_orgs)].reset_index(drop=True)
    if exclude_orgs:
        print(f"  Excluded orgs: {exclude_orgs} ({len(df)} repos remaining)")

    # Star counts (optional)
    import numpy as np
    stars: dict[str, int] = {}
    if stars_csv:
        sdf = pd.read_csv(stars_csv)
        stars = dict(zip(sdf["repo"], sdf["stars"].fillna(0).astype(int)))
    max_log_stars = math.log1p(max(stars.values(), default=1))

    def _star_weight(repo: str) -> float:
        """0–1 weight based on log(stars+1)."""
        return math.log1p(stars.get(repo, 0)) / max_log_stars if max_log_stars > 0 else 0.0

    # Sort orgs: openff-* first (alphabetically), then external (by repo count desc)
    org_counts = df["owner"].value_counts()
    openff_orgs = sorted(o for o in org_counts.index if o.startswith("openff"))
    other_orgs = [o for o in org_counts.sort_values(ascending=False).index
                  if not o.startswith("openff")]
    ordered_orgs = openff_orgs + other_orgs

    # Within each org sort repos by stars desc, then name
    org_repos: dict[str, list[str]] = defaultdict(list)
    for repo, owner in zip(df["repo"], df["owner"]):
        org_repos[owner].append(repo)
    for org in org_repos:
        org_repos[org].sort(key=lambda r: (-stars.get(r, 0), r))

    # Assign angular positions — one slot per repo, small gap between orgs
    gap_frac = 0.8
    n_repos = len(df)
    n_orgs = len(ordered_orgs)
    total_slots = n_repos + gap_frac * n_orgs

    leaf_angles: dict[str, float] = {}
    org_mid_angles: dict[str, float] = {}
    slot = 0.0
    for org in ordered_orgs:
        repos = org_repos[org]
        start_slot = slot
        for repo in repos:
            angle = 2 * math.pi * (slot / total_slots) - math.pi / 2
            leaf_angles[repo] = angle
            slot += 1
        end_slot = slot - 1
        mid_angle = 2 * math.pi * ((start_slot + end_slot) / 2 / total_slots) - math.pi / 2
        org_mid_angles[org] = mid_angle
        slot += gap_frac

    R_ORG = 0.42
    R_LEAF = 1.0
    R_LABEL = 1.06

    openff_color = "#1f77b4"
    external_color = "#aec7e8"
    org_colors = {
        org: openff_color if org.startswith("openff") else external_color
        for org in ordered_orgs
    }

    # Size based on circumference needed for labels, not linear in n_repos.
    # Circumference ≈ n_repos * label_pitch; diameter = circumference / π.
    label_pitch = 0.14  # inches per repo slot at 150 dpi
    fig_size = max(26, (n_repos * label_pitch) / 3.14159)
    fig, ax = plt.subplots(figsize=(fig_size, fig_size))

    # Draw connections: root → org → repos
    for org in ordered_orgs:
        repos = org_repos[org]
        col = org_colors[org]
        mid = org_mid_angles[org]
        ox = R_ORG * math.cos(mid)
        oy = R_ORG * math.sin(mid)
        ax.plot([0, ox], [0, oy], color=col, lw=1.2, alpha=0.5, zorder=1)

        for repo in repos:
            angle = leaf_angles[repo]
            rx = R_LEAF * math.cos(angle)
            ry = R_LEAF * math.sin(angle)
            w = _star_weight(repo)
            lw = 0.5 + 3.0 * w   # 0.5 → 3.5
            alpha = 0.35 + 0.5 * w
            ax.plot([ox, rx], [oy, ry], color=col, lw=lw, alpha=alpha, zorder=1)

    # Org labels — rotated to sit along their spoke
    for org in ordered_orgs:
        mid = org_mid_angles[org]
        # Place label halfway between root and leaf ring
        r_mid = (R_ORG + R_LEAF) / 2 * 0.78
        ox = r_mid * math.cos(mid)
        oy = r_mid * math.sin(mid)
        col = "#0a5c99" if org.startswith("openff") else "#444444"
        deg = math.degrees(mid)
        if -90 <= deg <= 90:
            ha, rotation = "center", deg
        else:
            ha, rotation = "center", deg + 180
        ax.text(ox, oy, org, ha=ha, va="center", fontsize=9,
                fontweight="bold", color=col, zorder=3,
                rotation=rotation, rotation_mode="anchor",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.75))

    # Leaf labels — rotated along spoke, size scaled by stars
    for repo, angle in leaf_angles.items():
        owner = repo.split("/")[0]
        repo_name = repo.split("/", 1)[1]
        rx = R_LABEL * math.cos(angle)
        ry = R_LABEL * math.sin(angle)
        deg = math.degrees(angle)
        if -90 <= deg <= 90:
            ha, rotation = "left", deg
        else:
            ha, rotation = "right", deg + 180
        w = _star_weight(repo)
        fontsize = 6 + 5 * w   # 6 → 11
        weight = "bold" if w > 0.4 else "normal"
        col = "#1a5276" if owner.startswith("openff") else "#222222"
        ax.text(rx, ry, repo_name, ha=ha, va="center",
                fontsize=fontsize, fontweight=weight,
                rotation=rotation, rotation_mode="anchor",
                color=col, zorder=2)

    # Central hub
    ax.plot(0, 0, "o", ms=10, color="#e74c3c", zorder=5)
    ax.text(0, 0.04, "openff-toolkit", ha="center", va="bottom",
            fontsize=11, fontweight="bold", color="#e74c3c")

    ax.set_xlim(-1.6, 1.6)
    ax.set_ylim(-1.6, 1.6)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(
        f"GitHub Repos Using openff-toolkit  ({n_repos:,} repos · {n_orgs} orgs)",
        fontsize=13, pad=14,
    )

    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved GitHub radial tree to {output_path}")


def _spread_angles(angle_repo_pairs: list, min_gap: float, n_iter: int = 400) -> list:
    """Push a set of (angle, repo) pairs apart so no two are within min_gap radians.

    Uses an iterative repulsion pass on a circular arrangement.
    """
    import math

    n = len(angle_repo_pairs)
    if n <= 1:
        return angle_repo_pairs

    angles = [a for a, _ in sorted(angle_repo_pairs)]
    repos = [r for _, r in sorted(angle_repo_pairs)]

    for _ in range(n_iter):
        moved = False
        for i in range(n):
            j = (i + 1) % n
            gap = (angles[j] - angles[i]) % (2 * math.pi)
            if gap < min_gap:
                delta = (min_gap - gap) / 2
                angles[j] = (angles[j] + delta) % (2 * math.pi)
                angles[i] = (angles[i] - delta + 2 * math.pi) % (2 * math.pi)
                moved = True
        # re-sort to maintain circular order
        paired = sorted(zip(angles, repos))
        angles = [a for a, _ in paired]
        repos = [r for _, r in paired]
        if not moved:
            break

    return list(zip(angles, repos))


def plot_github_stars_radial(
    github_csv: str,
    stars_csv: str,
    output_path: str,
    star_threshold: int = 30,
    exclude_orgs: list[str] | None = None,
) -> None:
    """Radial plot highlighting repos above a star threshold.

    All repos are shown as spokes from the centre.  Repos below
    *star_threshold* are short grey spokes with tiny labels.  Repos at or
    above the threshold get longer, blue, heavier spokes with bold ``org/repo``
    labels spread apart to avoid overlap.

    Parameters
    ----------
    github_csv
        Path to the GitHub repos CSV (columns: repo, url).
    stars_csv
        Path to the star counts CSV (columns: repo, stars).
    output_path
        Path to save the PNG.
    star_threshold
        Minimum stars for a repo to get a long spoke and bold label.
    exclude_orgs
        Orgs/users to exclude.  Defaults to ``_DEFAULT_EXCLUDE_ORGS``.
    """
    import math
    from collections import defaultdict

    if exclude_orgs is None:
        exclude_orgs = _DEFAULT_EXCLUDE_ORGS

    df = pd.read_csv(github_csv)
    df["owner"] = df["repo"].str.split("/").str[0]
    df = df[~df["owner"].isin(exclude_orgs)].reset_index(drop=True)

    sdf = pd.read_csv(stars_csv)
    stars: dict[str, int] = dict(zip(sdf["repo"], sdf["stars"].fillna(0).astype(int)))
    df["stars"] = df["repo"].map(stars).fillna(0).astype(int)

    n_highlighted = int((df["stars"] >= star_threshold).sum())
    n_repos = len(df)
    print(f"  {n_highlighted} repos above {star_threshold}-star threshold")

    # Sort orgs: openff-* first, then by repo count
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

    # Initial angular layout — all repos evenly, grouped by org
    gap_frac = 0.8
    total_slots = n_repos + gap_frac * len(ordered_orgs)
    leaf_angles: dict[str, float] = {}
    slot = 0.0
    for org in ordered_orgs:
        for repo in org_repos[org]:
            leaf_angles[repo] = 2 * math.pi * (slot / total_slots) - math.pi / 2
            slot += 1
        slot += gap_frac

    # Spread highlighted repos so their labels don't overlap.
    # Enforce a minimum angular gap just large enough to fit if evenly distributed,
    # with a 10% margin.
    if n_highlighted > 1:
        min_gap = 2 * math.pi * 0.90 / n_highlighted
        high_pairs = [(leaf_angles[r], r)
                      for r in df["repo"] if stars.get(r, 0) >= star_threshold]
        high_pairs = _spread_angles(high_pairs, min_gap)
        for angle, repo in high_pairs:
            leaf_angles[repo] = angle

    max_stars = max(stars.values(), default=1)

    # Figure: circumference-based sizing so low-star labels have room too
    label_pitch = 0.13  # inches per repo slot for the dense inner ring
    fig_size = max(26, (n_repos * label_pitch) / math.pi)
    fig, ax = plt.subplots(figsize=(fig_size, fig_size))

    # Draw all spokes
    for repo, angle in leaf_angles.items():
        s = stars.get(repo, 0)
        highlighted = s >= star_threshold
        if highlighted:
            r_end = 1.05 + 0.45 * (s / max_stars) ** 0.5   # 1.05 → 1.50
            lw = 1.0 + 3.5 * (s / max_stars) ** 0.5
            col = "#1f77b4"
            alpha = 0.85
        else:
            r_end = 0.60
            lw = 0.35
            col = "#cccccc"
            alpha = 0.55
        rx, ry = r_end * math.cos(angle), r_end * math.sin(angle)
        ax.plot([0, rx], [0, ry], color=col, lw=lw, alpha=alpha, zorder=1)

    # Draw all labels — small for low-star, bold+sized for highlighted
    for repo, angle in leaf_angles.items():
        s = stars.get(repo, 0)
        highlighted = s >= star_threshold
        if highlighted:
            r_label = 1.05 + 0.45 * (s / max_stars) ** 0.5 + 0.05
            fontsize = 7.5 + 5.5 * (s / max_stars) ** 0.5   # 7.5 → 13
            fw = "bold"
            label_col = "#0a4c8a"
        else:
            r_label = 0.63
            fontsize = 4
            fw = "normal"
            label_col = "#999999"

        lx, ly = r_label * math.cos(angle), r_label * math.sin(angle)
        deg = math.degrees(angle)
        if -90 <= deg <= 90:
            ha, rotation = "left", deg
        else:
            ha, rotation = "right", deg + 180

        ax.text(lx, ly, repo, ha=ha, va="center",
                fontsize=fontsize, fontweight=fw,
                rotation=rotation, rotation_mode="anchor",
                color=label_col, zorder=2 if not highlighted else 3)

    # Central hub — dot only, no text label
    ax.plot(0, 0, "o", ms=10, color="#e74c3c", zorder=5)

    lim = 1.65
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(
        f"GitHub Repos Using openff-toolkit\n"
        f"({n_repos:,} total · {n_highlighted} with ≥{star_threshold} stars highlighted)",
        fontsize=13, pad=14,
    )
    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved GitHub stars radial to {output_path}")


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
    df = pd.read_csv(github_csv)
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
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved GitHub bubble chart to {output_path}")


def plot_github_force_directed(
    github_csv: str,
    stars_csv: str,
    output_path: str,
    star_threshold: int = 30,
    exclude_orgs: list[str] | None = None,
) -> None:
    """Force-directed graph of GitHub repos using openff-toolkit.

    Repos are nodes; edges connect each repo to its org hub, and org hubs to
    a central openff-toolkit node.  Node size is proportional to log(stars+1).
    Only repos with ≥ *star_threshold* stars are labelled.

    Parameters
    ----------
    github_csv
        Path to the GitHub repos CSV.
    stars_csv
        Path to the star counts CSV.
    output_path
        Path to save the PNG.
    star_threshold
        Minimum stars to label a repo node.
    exclude_orgs
        Orgs/users to exclude.  Defaults to ``_DEFAULT_EXCLUDE_ORGS``.
    """
    import math
    import networkx as nx

    if exclude_orgs is None:
        exclude_orgs = _DEFAULT_EXCLUDE_ORGS

    df = pd.read_csv(github_csv)
    df["owner"] = df["repo"].str.split("/").str[0]
    df = df[~df["owner"].isin(exclude_orgs)].reset_index(drop=True)

    sdf = pd.read_csv(stars_csv)
    stars: dict[str, int] = dict(zip(sdf["repo"], sdf["stars"].fillna(0).astype(int)))
    df["stars"] = df["repo"].map(stars).fillna(0).astype(int)

    G = nx.Graph()
    root = "openff-toolkit"
    G.add_node(root, kind="root", stars=0)

    orgs = df["owner"].unique()
    for org in orgs:
        G.add_node(org, kind="org", stars=0)
        G.add_edge(root, org, weight=2.0)

    for _, row in df.iterrows():
        G.add_node(row["repo"], kind="repo", stars=row["stars"])
        G.add_edge(row["owner"], row["repo"], weight=1.0)

    print(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print("  Computing layout …")
    pos = nx.spring_layout(G, seed=42, k=0.4, iterations=60, weight="weight")

    fig, ax = plt.subplots(figsize=(26, 26))

    # Edges
    nx.draw_networkx_edges(G, pos, ax=ax, alpha=0.15, width=0.4, edge_color="#aaaaaa")

    # Repo nodes
    repo_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "repo"]
    repo_sizes = [max(20, math.log1p(G.nodes[n]["stars"]) * 80) for n in repo_nodes]
    repo_colors = ["#1f77b4" if n.split("/")[0].startswith("openff") else "#aec7e8"
                   for n in repo_nodes]
    nx.draw_networkx_nodes(G, pos, nodelist=repo_nodes, node_size=repo_sizes,
                           node_color=repo_colors, ax=ax, alpha=0.7)

    # Org nodes
    org_nodes = [n for n, d in G.nodes(data=True) if d["kind"] == "org"]
    nx.draw_networkx_nodes(G, pos, nodelist=org_nodes, node_size=300,
                           node_color="#ff7f0e", ax=ax, alpha=0.9)
    nx.draw_networkx_labels(G, pos, labels={n: n for n in org_nodes},
                            font_size=7, font_weight="bold", ax=ax)

    # Root node
    nx.draw_networkx_nodes(G, pos, nodelist=[root], node_size=600,
                           node_color="#e74c3c", ax=ax)
    nx.draw_networkx_labels(G, pos, labels={root: root},
                            font_size=9, font_weight="bold", ax=ax)

    # Labels for high-starred repos
    high_repos = {n: n.split("/")[1] for n in repo_nodes
                  if G.nodes[n]["stars"] >= star_threshold}
    nx.draw_networkx_labels(G, pos, labels=high_repos,
                            font_size=6, font_color="#8b0000", ax=ax)

    ax.axis("off")
    n_repos = len(repo_nodes)
    n_labeled = len(high_repos)
    ax.set_title(
        f"GitHub Repos Using openff-toolkit — Force-Directed\n"
        f"({n_repos:,} repos · {n_labeled} labelled with ≥{star_threshold} stars)",
        fontsize=13,
    )
    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved GitHub force-directed graph to {output_path}")


def plot_github_lollipop(
    github_csv: str,
    stars_csv: str,
    output_path: str,
    star_threshold: int = 30,
    exclude_orgs: list[str] | None = None,
) -> None:
    """Lollipop chart of GitHub repos above a star threshold.

    Repos with ≥ *star_threshold* stars are shown as horizontal lollipops
    sorted by star count descending.  openff-* org repos are coloured blue;
    external repos are red.

    Parameters
    ----------
    github_csv
        Path to the GitHub repos CSV.
    stars_csv
        Path to the star counts CSV.
    output_path
        Path to save the PNG.
    star_threshold
        Minimum stars to include.
    exclude_orgs
        Orgs/users to exclude.  Defaults to ``_DEFAULT_EXCLUDE_ORGS``.
    """
    if exclude_orgs is None:
        exclude_orgs = _DEFAULT_EXCLUDE_ORGS

    df = pd.read_csv(github_csv)
    df["owner"] = df["repo"].str.split("/").str[0]
    df = df[~df["owner"].isin(exclude_orgs)].reset_index(drop=True)

    sdf = pd.read_csv(stars_csv)
    stars_map: dict[str, int] = dict(zip(sdf["repo"], sdf["stars"].fillna(0).astype(int)))
    df["stars"] = df["repo"].map(stars_map).fillna(0).astype(int)

    plot_df = df[df["stars"] >= star_threshold].sort_values("stars").reset_index(drop=True)
    if plot_df.empty:
        print(f"No repos with ≥{star_threshold} stars; skipping lollipop.")
        return

    colors = ["#1f77b4" if o.startswith("openff") else "#d62728"
              for o in plot_df["owner"]]

    fig_h = max(8, len(plot_df) * 0.32)
    fig, ax = plt.subplots(figsize=(12, fig_h))

    y = range(len(plot_df))
    ax.hlines(y, 0, plot_df["stars"], colors=colors, linewidth=1.5, alpha=0.7)
    ax.scatter(plot_df["stars"], y, color=colors, s=60, zorder=3)

    ax.set_yticks(list(y))
    ax.set_yticklabels(plot_df["repo"], fontsize=9)
    ax.set_xlabel("GitHub Stars", fontsize=11)
    ax.set_title(
        f"GitHub Repos Using openff-toolkit with ≥{star_threshold} Stars\n"
        f"({len(plot_df)} repos shown · blue = openff org · red = external)",
        fontsize=12,
    )
    ax.grid(axis="x", alpha=0.3)
    ax.set_xlim(left=0)

    # Annotate star counts
    for i, (stars_val, repo) in enumerate(zip(plot_df["stars"], plot_df["repo"])):
        ax.text(stars_val + plot_df["stars"].max() * 0.01, i, str(stars_val),
                va="center", fontsize=8)

    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved GitHub lollipop chart to {output_path}")


def plot_github_treemap(github_csv: str, output_path: str, min_repos: int = 2) -> None:
    """Plot a treemap of GitHub organisations by number of repos using openff-toolkit.

    Each rectangle represents an organisation; area is proportional to repo count.
    Orgs with fewer than *min_repos* are grouped into an "other" tile.

    Parameters
    ----------
    github_csv
        Path to the GitHub repos CSV (columns: repo, url).
    output_path
        Path to save the PNG.
    min_repos
        Minimum repo count for an org to get its own tile.
    """
    import squarify

    df = pd.read_csv(github_csv)
    if df.empty:
        print("No GitHub repos found; skipping treemap.")
        return

    df["owner"] = df["repo"].str.split("/").str[0]
    counts = df["owner"].value_counts()

    main = counts[counts >= min_repos].sort_values(ascending=False)
    other_count = counts[counts < min_repos].sum()

    labels = list(main.index)
    sizes = list(main.values)
    if other_count > 0:
        labels.append(f"other ({(counts < min_repos).sum()} orgs)")
        sizes.append(int(other_count))

    # Colours: openff-* in blue, external in steel-blue tones, "other" in grey
    palette = sns.color_palette("Blues_d", len(labels))
    colors = []
    for i, label in enumerate(labels):
        if label.startswith("openff"):
            colors.append("#1f4e79")
        elif label.startswith("other"):
            colors.append("#cccccc")
        else:
            colors.append(palette[min(i, len(palette) - 1)])

    fig, ax = plt.subplots(figsize=(16, 10))
    squarify.plot(
        sizes=sizes,
        label=[f"{lbl}\n{sz}" for lbl, sz in zip(labels, sizes)],
        color=colors,
        alpha=0.85,
        ax=ax,
        text_kwargs={"fontsize": 7, "color": "white", "fontweight": "bold"},
    )
    ax.set_title(
        f"GitHub Orgs Using openff-toolkit  ({len(df):,} repos total)",
        fontsize=13,
    )
    ax.axis("off")
    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved GitHub treemap to {output_path}")


def plot_github_orgs(github_csv: str, output_path: str, top_n: int = 20) -> None:
    """Plot top GitHub organisations by number of repos using openff-toolkit.

    Reads data/github_repos.csv (columns: repo, url), extracts the owner from
    each ``owner/reponame`` string, counts repos per owner, and saves a
    horizontal bar chart of the top N owners.

    Parameters
    ----------
    github_csv
        Path to the GitHub repos CSV.
    output_path
        Path to save the PNG plot.
    top_n
        Number of top owners to show.
    """
    df = pd.read_csv(github_csv)
    if df.empty:
        print("No GitHub repos found; skipping plot.")
        return

    df["owner"] = df["repo"].str.split("/").str[0]
    counts = df["owner"].value_counts().head(top_n).sort_values()

    fig, ax = plt.subplots(figsize=(10, max(4, len(counts) * 0.4)))
    counts.plot.barh(ax=ax, color="#2ca02c")

    for patch in ax.patches:
        w = patch.get_width()
        ax.text(
            w + 0.1, patch.get_y() + patch.get_height() / 2,
            str(int(w)), va="center", ha="left", fontsize=9,
        )

    ax.set_xlabel("Number of repos")
    ax.set_title(f"Top {top_n} GitHub Organisations Using openff-toolkit\n(total repos: {len(df):,})", fontsize=13)
    ax.set_xlim(0, counts.max() * 1.12)

    plt.tight_layout()
    pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved GitHub orgs plot to {output_path}")
