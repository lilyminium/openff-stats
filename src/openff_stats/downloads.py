"""
Conda-forge package discovery and download statistics collection.

Workflow:
  1. discover-packages     → outputs a candidates CSV for human review
  2. discover-dependents   → outputs packages that depend on openff-toolkit
  2. (human edits inputs/packages.csv to verify the list)
  3. downloads             → reads inputs/packages.csv, collects stats, writes data/
"""

import pathlib
import re
import time
import typing

import pandas as pd
import requests
import tqdm

# Hardcoded competitor packages to always include in discovery output
COMPETITOR_PACKAGES = ["ambertools", "parmed"]

CHANNELDATA_URL = "https://conda.anaconda.org/conda-forge/channeldata.json"


def discover_packages(output_file: str) -> pd.DataFrame:
    """Fetch conda-forge channeldata and return all openff-* packages plus competitors.

    Writes a candidates CSV for human review. The human should verify the list
    and save it to inputs/packages.csv.

    Parameters
    ----------
    output_file
        Path to write the candidates CSV.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: package, category
    """
    print(f"Fetching conda-forge channeldata from {CHANNELDATA_URL} ...")
    response = requests.get(CHANNELDATA_URL, timeout=120)
    response.raise_for_status()
    channeldata = response.json()

    all_packages = list(channeldata.get("packages", {}).keys())
    openff_packages = sorted(p for p in all_packages if p.startswith("openff-"))

    rows = [{"package": pkg, "category": "openff"} for pkg in openff_packages]
    for pkg in COMPETITOR_PACKAGES:
        rows.append({"package": pkg, "category": "competitor"})

    df = pd.DataFrame(rows)
    df.to_csv(output_file, index=False)

    print(f"\nFound {len(openff_packages)} openff-* packages on conda-forge:")
    for pkg in openff_packages:
        print(f"  {pkg}")
    print(f"\nAlso included competitors: {', '.join(COMPETITOR_PACKAGES)}")
    print(f"\nWrote {len(df)} candidates to {output_file}")
    print("Review this file and save verified entries to inputs/packages.csv")

    return df


def get_anaconda_downloads(package: str) -> int | None:
    """Return total download count from the Anaconda.org JSON API.

    Parameters
    ----------
    package
        conda-forge package name.

    Returns
    -------
    int or None
        Total download count, or None if the request failed.
    """
    url = f"https://api.anaconda.org/package/conda-forge/{package}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return int(response.json()["ndownloads"])
    except Exception as exc:
        print(f"  Warning: could not get Anaconda downloads for {package}: {exc}")
        return None


def get_condastats_monthly(package: str) -> pd.DataFrame | None:
    """Get monthly download counts from the condastats API.

    Parameters
    ----------
    package
        conda-forge package name.

    Returns
    -------
    pd.DataFrame or None
        DataFrame with columns: time, counts, year, or None on failure.
    """
    try:
        from condastats.cli import overall

        data = overall(package, monthly=True)
        df = data.to_frame().reset_index()
        df["year"] = df["time"].str.split("-", expand=True)[0]
        df["package"] = package
        return df
    except Exception as exc:
        print(f"  Warning: could not get condastats data for {package}: {exc}")
        return None


def collect_all_downloads(
    input_csv: str,
    output_csv: str,
    yearly_csv: str,
) -> None:
    """Collect download stats for all packages in the input CSV.

    Reads inputs/packages.csv (columns: package, category) and writes:
      - output_csv: per-package totals from both methods
      - yearly_csv: per-package per-year counts from condastats

    Parameters
    ----------
    input_csv
        Path to the curated packages CSV (inputs/packages.csv).
    output_csv
        Path for the per-package totals output CSV.
    yearly_csv
        Path for the per-package per-year output CSV.
    """
    packages_df = pd.read_csv(input_csv)

    totals_rows: list[dict] = []
    all_monthly: list[pd.DataFrame] = []

    for _, row in tqdm.tqdm(packages_df.iterrows(), total=len(packages_df), desc="Packages"):
        pkg = row["package"]
        cat = row["category"]

        print(f"\n{pkg} ({cat})")

        anaconda_total = get_anaconda_downloads(pkg)
        monthly_df = get_condastats_monthly(pkg)

        condastats_total: int | None = None
        if monthly_df is not None:
            condastats_total = int(monthly_df["counts"].sum())
            monthly_df["category"] = cat
            all_monthly.append(monthly_df)

        totals_rows.append({
            "package": pkg,
            "category": cat,
            "anaconda_total": anaconda_total,
            "condastats_total": condastats_total,
        })

    # Write totals
    totals_df = pd.DataFrame(totals_rows)
    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    totals_df.to_csv(output_csv, index=False)
    print(f"\nSaved per-package totals to {output_csv}")

    openff_anaconda = totals_df[totals_df.category == "openff"]["anaconda_total"].sum()
    openff_condastats = totals_df[totals_df.category == "openff"]["condastats_total"].sum()
    print(f"Total openff downloads (Anaconda):   {openff_anaconda:,.0f}")
    print(f"Total openff downloads (condastats): {openff_condastats:,.0f}")

    # Write yearly breakdown
    if all_monthly:
        combined = pd.concat(all_monthly, ignore_index=True)
        yearly = (
            combined.groupby(["package", "category", "year"])["counts"]
            .sum()
            .reset_index()
            .rename(columns={"counts": "condastats_downloads"})
        )
        pathlib.Path(yearly_csv).parent.mkdir(parents=True, exist_ok=True)
        yearly.to_csv(yearly_csv, index=False)
        print(f"Saved per-package yearly stats to {yearly_csv}")
    else:
        print("Warning: no condastats data collected; yearly CSV not written.")


# ---------------------------------------------------------------------------
# Dependent-package discovery
# ---------------------------------------------------------------------------

def _canonical(name: str) -> str:
    """Return the canonical package name, stripping any -base suffix."""
    return name[:-5] if name.endswith("-base") else name


def _version_gt(v1: str, v2: str) -> bool:
    """Return True if version string v1 is greater than v2."""
    def _parts(v: str) -> list:
        parts = []
        for segment in re.split(r"[.\-]", str(v)):
            try:
                parts.append((0, int(segment)))
            except ValueError:
                parts.append((1, segment))
        return parts

    try:
        return _parts(v1) > _parts(v2)
    except Exception:
        return str(v1) > str(v2)


def _fetch_latest_packages(subdirs: list[str] | None = None) -> dict[str, dict]:
    """Download conda-forge repodata and return the latest version of each package.

    Parameters
    ----------
    subdirs
        conda-forge subdirectories to fetch (default: ``["noarch", "linux-64"]``).

    Returns
    -------
    dict
        ``{package_name: {"name", "version", "depends": [...], "subdir"}}``
        keeping only the highest-version entry seen across all subdirs.
    """
    if subdirs is None:
        subdirs = ["noarch", "linux-64"]

    latest: dict[str, dict] = {}

    for subdir in subdirs:
        url = f"https://conda.anaconda.org/conda-forge/{subdir}/repodata.json"
        print(f"Fetching {url} ...")
        response = requests.get(url, timeout=300)
        response.raise_for_status()
        repodata = response.json()

        all_pkgs: dict = {}
        all_pkgs.update(repodata.get("packages", {}))
        all_pkgs.update(repodata.get("packages.conda", {}))

        print(f"  Scanning {len(all_pkgs):,} package entries ...")
        for _filename, pkg in all_pkgs.items():
            name = pkg.get("name", "")
            if not name:
                continue
            version = pkg.get("version", "")
            if name not in latest or _version_gt(version, latest[name]["version"]):
                latest[name] = {
                    "name": name,
                    "version": version,
                    "depends": pkg.get("depends", []),
                    "subdir": subdir,
                }

    return latest


def discover_dependents(
    output_file: str = "candidates/dependents.csv",
    subdirs: list[str] | None = None,
    dep_name: str = "openff-toolkit",
) -> pd.DataFrame:
    """Find conda-forge packages that declare openff-toolkit as a dependency.

    Downloads repodata.json for each requested subdir, scans every package
    entry's ``depends`` list, and keeps the latest version of each package
    that names ``dep_name`` as a run dependency.

    The output requires human verification before use — some packages may be
    internal build artefacts or test environments.

    Parameters
    ----------
    output_file
        Path to write the candidates CSV.
    subdirs
        conda-forge subdirectories to scan.  Defaults to
        ``["noarch", "linux-64"]``.
    dep_name
        Dependency name to search for.

    Returns
    -------
    pd.DataFrame
        Columns: package, version, openff_dep, subdir
    """
    latest = _fetch_latest_packages(subdirs)

    found: dict[str, dict] = {}
    for name, pkg in latest.items():
        for dep in pkg["depends"]:
            if dep == dep_name or dep.startswith(dep_name + " "):
                found[name] = {
                    "package": name,
                    "version": pkg["version"],
                    "openff_dep": dep,
                    "subdir": pkg["subdir"],
                }
                break

    df = pd.DataFrame(list(found.values()))
    if not df.empty:
        df = df.sort_values("package").reset_index(drop=True)

    pathlib.Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False)

    print(f"\nFound {len(df)} conda-forge packages depending on {dep_name!r}")
    print(f"Wrote candidates to {output_file}")
    print(
        "NOTE: Review this file and copy verified entries to inputs/packages.csv "
        "(set category to 'dependent' or similar)."
    )
    return df


def collect_dep_tree(
    roots: list[str] | None = None,
    depth: int = 2,
    subdirs: list[str] | None = None,
    output_file: str = "data/dep_tree.csv",
) -> pd.DataFrame:
    """Build a reverse-dependency tree rooted at openff-toolkit packages.

    Packages and their ``-base`` variants are treated as a single node
    (e.g. ``openff-toolkit`` and ``openff-toolkit-base`` merge into
    ``openff-toolkit``).  Download counts are summed across both forms.

    Starting from ``roots``, does a BFS through conda-forge's reverse
    dependency graph up to ``depth`` levels.  Fetches Anaconda download
    counts for every node so the plot can be re-labelled without re-downloading
    repodata.

    Parameters
    ----------
    roots
        Root package names (default: ``["openff-toolkit"]`` — the -base form
        is automatically included via canonicalization).
    depth
        Number of BFS levels to expand beyond the roots (default 2).
    subdirs
        conda-forge subdirs to scan (default: ``["noarch", "linux-64"]``).
    output_file
        Path to write the tree CSV.

    Returns
    -------
    pd.DataFrame
        One row per directed edge in the tree:
        ``package, level, parent, anaconda_downloads``
        Roots have ``parent = ""`` and ``level = 0``.
    """
    if roots is None:
        roots = ["openff-toolkit"]

    # Canonicalize roots and deduplicate (preserving order)
    roots = list(dict.fromkeys(_canonical(r) for r in roots))

    latest = _fetch_latest_packages(subdirs)
    known_packages: set[str] = set(latest)

    # Build reverse dep map with canonical names throughout.
    # A package depending on openff-toolkit-base is treated as depending on
    # openff-toolkit; a -base package itself is a canonical dependent too.
    print("Building reverse dependency map ...")
    reverse_deps: dict[str, set[str]] = {}
    for name, pkg in latest.items():
        canonical_name = _canonical(name)
        for dep in pkg["depends"]:
            dep_pkg = _canonical(dep.split(" ")[0])
            reverse_deps.setdefault(dep_pkg, set()).add(canonical_name)

    # BFS using canonical names
    rows: list[dict] = []
    seen: set[str] = set(roots)
    current_level: set[str] = set(roots)

    for root in roots:
        rows.append({"package": root, "level": 0, "parent": ""})

    for level in range(1, depth + 1):
        next_level: set[str] = set()
        for pkg in sorted(current_level):
            for dependent in sorted(reverse_deps.get(pkg, set())):
                if dependent not in seen:
                    seen.add(dependent)
                    next_level.add(dependent)
                    rows.append({"package": dependent, "level": level, "parent": pkg})
        print(f"  Level {level}: {len(next_level)} new packages")
        current_level = next_level
        if not current_level:
            break

    # Fetch download counts — sum the canonical package and its -base form
    unique_packages = sorted({r["package"] for r in rows})
    print(f"\nFetching Anaconda download counts for {len(unique_packages)} packages ...")
    downloads: dict[str, int] = {}
    for pkg in tqdm.tqdm(unique_packages):
        main = get_anaconda_downloads(pkg) or 0
        base_name = pkg + "-base"
        base = (get_anaconda_downloads(base_name) or 0) if base_name in known_packages else 0
        downloads[pkg] = main + base or 0
        time.sleep(0.05)

    for row in rows:
        row["anaconda_downloads"] = downloads.get(row["package"], 0)

    df = pd.DataFrame(rows)
    pathlib.Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False)

    n_roots = len(roots)
    total = len(df["package"].unique()) - n_roots
    print(f"\nTree: {n_roots} root(s) + {total} dependents across {depth} level(s)")
    print(f"Saved to {output_file}")
    return df
