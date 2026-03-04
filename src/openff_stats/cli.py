"""
openff-stats command-line interface.

Entry point: `openff-stats`

Discovery commands (output candidates for human review):
  openff-stats discover-publications --orcid XXXX [--orcid YYYY ...]
  openff-stats discover-packages
  openff-stats discover-zenodo

Data collection commands (read curated inputs/, write data/):
  openff-stats citations
  openff-stats downloads
  openff-stats zenodo-citations

Visualisation:
  openff-stats plot-downloads

Run everything (except discovery):
  openff-stats run-all
"""

import click


@click.group()
def cli() -> None:
    """Collect and tabulate OpenFF publication and download statistics."""


# ---------------------------------------------------------------------------
# Discovery commands
# ---------------------------------------------------------------------------

@cli.command("discover-publications")
@click.option(
    "--orcid",
    "orcids",
    multiple=True,
    required=True,
    metavar="ORCID",
    help=(
        "ORCID identifier to query (e.g. 0000-0002-1544-1476). "
        "May be repeated for multiple authors."
    ),
)
@click.option(
    "--output",
    default="candidates/publications.csv",
    show_default=True,
    help="Path for the candidates CSV (for human review).",
)
def discover_publications(orcids: tuple[str, ...], output: str) -> None:
    """Discover publications via ORCID + Crossref and write a candidates CSV.

    The output requires human verification before being saved to
    inputs/publications.csv. Not all papers found will be OpenFF-related.
    """
    from openff_stats.publications import discover_publications as _discover
    _discover(list(orcids), output)


@cli.command("discover-packages")
@click.option(
    "--output",
    default="candidates/packages.csv",
    show_default=True,
    help="Path for the candidates CSV (for human review).",
)
def discover_packages(output: str) -> None:
    """Discover openff-* packages on conda-forge and write a candidates CSV.

    The output requires human verification before being saved to
    inputs/packages.csv.
    """
    from openff_stats.downloads import discover_packages as _discover
    _discover(output)


@cli.command("discover-zenodo")
@click.option(
    "--output",
    default="candidates/zenodo.csv",
    show_default=True,
    help="Path for the candidates CSV (for human review).",
)
def discover_zenodo(output: str) -> None:
    """Search Zenodo for OpenFF records and write a candidates CSV.

    The output requires human verification before being saved to
    inputs/zenodo.csv.
    """
    from openff_stats.zenodo import discover_zenodo as _discover
    _discover(output)


# ---------------------------------------------------------------------------
# Data collection commands
# ---------------------------------------------------------------------------

@cli.command("citations")
@click.option(
    "--input",
    "input_csv",
    default="inputs/publications.csv",
    show_default=True,
    help="Path to the curated publications CSV.",
)
@click.option(
    "--output",
    "output_csv",
    default="data/citations.csv",
    show_default=True,
    help="Path for the citations output CSV.",
)
def citations(input_csv: str, output_csv: str) -> None:
    """Collect citation counts from Crossref, Google Scholar, and ChemRxiv."""
    from openff_stats.publications import collect_all_citations
    collect_all_citations(input_csv, output_csv)


@cli.command("downloads")
@click.option(
    "--input",
    "input_csv",
    default="inputs/packages.csv",
    show_default=True,
    help="Path to the curated packages CSV.",
)
@click.option(
    "--output",
    "output_csv",
    default="data/downloads.csv",
    show_default=True,
    help="Path for the per-package totals output CSV.",
)
@click.option(
    "--yearly-output",
    "yearly_csv",
    default="data/downloads_yearly.csv",
    show_default=True,
    help="Path for the per-package per-year output CSV.",
)
def downloads(input_csv: str, output_csv: str, yearly_csv: str) -> None:
    """Collect conda-forge download stats via Anaconda scraping and condastats."""
    from openff_stats.downloads import collect_all_downloads
    collect_all_downloads(input_csv, output_csv, yearly_csv)


@cli.command("zenodo-citations")
@click.option(
    "--input",
    "input_csv",
    default="inputs/zenodo.csv",
    show_default=True,
    help="Path to the curated Zenodo CSV.",
)
@click.option(
    "--output",
    "output_csv",
    default="data/zenodo_citations.csv",
    show_default=True,
    help="Path for the Zenodo citation counts output CSV.",
)
def zenodo_citations(input_csv: str, output_csv: str) -> None:
    """Collect citation counts for Zenodo records via the DataCite API."""
    from openff_stats.zenodo import collect_zenodo_citations
    collect_zenodo_citations(input_csv, output_csv)


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

@cli.command("plot-downloads")
@click.option(
    "--input",
    "yearly_csv",
    default="data/downloads_yearly.csv",
    show_default=True,
    help="Path to the yearly downloads CSV.",
)
@click.option(
    "--output",
    "output_path",
    default="data/plots/openff_downloads_per_year.png",
    show_default=True,
    help="Path to save the PNG plot.",
)
def plot_downloads(yearly_csv: str, output_path: str) -> None:
    """Plot total OpenFF conda-forge downloads per year."""
    from openff_stats.plotting import plot_downloads_per_year
    plot_downloads_per_year(yearly_csv, output_path)


# ---------------------------------------------------------------------------
# run-all
# ---------------------------------------------------------------------------

@cli.command("run-all")
@click.option(
    "--publications-input", default="inputs/publications.csv", show_default=True,
    help="Curated publications CSV.",
)
@click.option(
    "--packages-input", default="inputs/packages.csv", show_default=True,
    help="Curated packages CSV.",
)
@click.option(
    "--zenodo-input", default="inputs/zenodo.csv", show_default=True,
    help="Curated Zenodo CSV.",
)
def run_all(
    publications_input: str,
    packages_input: str,
    zenodo_input: str,
) -> None:
    """Run the full data-collection pipeline (citations, downloads, zenodo, plot).

    Reads the three curated input files and writes all outputs to data/.
    Discovery steps are NOT run here — they require separate human verification.
    """
    import pathlib

    from openff_stats.publications import collect_all_citations
    from openff_stats.downloads import collect_all_downloads
    from openff_stats.zenodo import collect_zenodo_citations
    from openff_stats.plotting import plot_downloads_per_year

    # --- Citations ---
    if pathlib.Path(publications_input).exists():
        click.echo("\n=== Citation counts ===")
        collect_all_citations(publications_input, "data/citations.csv")
    else:
        click.echo(f"Skipping citations: {publications_input} not found.")

    # --- Downloads ---
    if pathlib.Path(packages_input).exists():
        click.echo("\n=== Download stats ===")
        collect_all_downloads(
            packages_input,
            "data/downloads.csv",
            "data/downloads_yearly.csv",
        )
    else:
        click.echo(f"Skipping downloads: {packages_input} not found.")

    # --- Zenodo ---
    if pathlib.Path(zenodo_input).exists():
        click.echo("\n=== Zenodo citations ===")
        collect_zenodo_citations(zenodo_input, "data/zenodo_citations.csv")
    else:
        click.echo(f"Skipping Zenodo citations: {zenodo_input} not found.")

    # --- Plot ---
    yearly_csv = "data/downloads_yearly.csv"
    if pathlib.Path(yearly_csv).exists():
        click.echo("\n=== Download plot ===")
        plot_downloads_per_year(yearly_csv, "data/plots/openff_downloads_per_year.png")
    else:
        click.echo(f"Skipping plot: {yearly_csv} not found.")

    click.echo("\nDone.")
