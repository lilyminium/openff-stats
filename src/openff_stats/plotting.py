"""
Plotting utilities for openff-stats.
"""

from __future__ import annotations

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
