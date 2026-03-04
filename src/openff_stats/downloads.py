"""
Conda-forge package discovery and download statistics collection.

Workflow:
  1. discover-packages  → outputs a candidates CSV for human review
  2. (human edits inputs/packages.csv to verify the list)
  3. downloads          → reads inputs/packages.csv, collects stats, writes data/
"""

from __future__ import annotations

import pathlib
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
