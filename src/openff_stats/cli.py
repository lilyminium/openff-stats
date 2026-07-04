"""
openff-stats command-line interface.

Entry point: `openff-stats`

The source lists in inputs/ are manually curated. Add new sources with:
  openff-stats add-publication-doi 10.1021/acs.jpcb.4c01558 [--scholar]
  openff-stats add-github-repo owner/repo
  openff-stats add-zenodo 10.5281/zenodo.18842670

Google Scholar lookup by DOI (find/store the Scholar cluster ID):
  openff-stats scholar-lookup 10.1021/acs.jpcb.4c01558 [--save]

Data collection commands (read curated inputs/, write data/):
  openff-stats citations
  openff-stats downloads
  openff-stats zenodo-citations
  openff-stats github-stars         (requires GITHUB_TOKEN env var)
  openff-stats github-descriptions  (requires GITHUB_TOKEN env var)

Optional bulk discovery (writes candidates/ for human review; never
feeds collection directly):
  openff-stats discover-publications --orcid-csv inputs/orcids.csv
  openff-stats discover-packages
  openff-stats discover-dependents
  openff-stats discover-zenodo
  openff-stats discover-github-repos (requires GITHUB_TOKEN env var)
  openff-stats scholar-clusters      (bulk-fill scholar_cluster_id by title)

Visualisation:
  openff-stats plot-downloads
  openff-stats plot-github-bubbles

Run all collection + the downloads plot (never discovery):
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
    metavar="ORCID",
    help=(
        "ORCID identifier to query (e.g. 0000-0002-1544-1476). "
        "May be repeated for multiple authors."
    ),
)
@click.option(
    "--orcid-csv",
    type=click.Path(exists=True),
    help=(
        "Path to a CSV file with Name and ORCID columns. "
        "If provided, ORCIDs will be loaded from this file. "
        "Individual --orcid flags can also be used to add more."
    ),
)
@click.option(
    "--output",
    default="candidates/publications.csv",
    show_default=True,
    help="Path for the candidates CSV (for human review).",
)
def discover_publications(
    orcids: tuple[str, ...],
    orcid_csv: str | None,
    output: str,
) -> None:
    """Discover publications via ORCID + Crossref and write a candidates CSV.

    The output requires human verification before being saved to
    inputs/publications.csv. Not all papers found will be OpenFF-related.
    Publications are sorted by the number of authors that overlap with
    the provided ORCID list, as more overlaps indicate OpenFF publications.
    """
    import pandas as pd
    from openff_stats.publications import discover_publications as _discover

    # Load ORCIDs and author names
    all_orcids = list(orcids)
    author_names: list[str] = []

    if orcid_csv:
        df = pd.read_csv(orcid_csv)
        for _, row in df.iterrows():
            orcid = str(row.get("ORCID", "")).strip()
            name = str(row.get("Name", "")).strip()
            if orcid:
                all_orcids.append(orcid)
            if name:
                author_names.append(name)

    if not all_orcids:
        raise click.UsageError("No ORCIDs provided via --orcid or --orcid-csv.")

    _discover(all_orcids, output, author_names)


@cli.command("add-publication-doi")
@click.argument("doi")
@click.option(
    "--input",
    "input_csv",
    default="inputs/publications.csv",
    show_default=True,
    help="Path to existing publications CSV.",
)
@click.option(
    "--output",
    "output_csv",
    default="inputs/publications.csv",
    show_default=True,
    help="Path to write updated publications CSV.",
)
@click.option(
    "--update-existing",
    is_flag=True,
    default=False,
    help="Update title/authors/year if DOI is already present.",
)
@click.option(
    "--scholar",
    "fetch_scholar",
    is_flag=True,
    default=False,
    help=(
        "Also look up the Google Scholar cluster ID (Selenium; best-effort — "
        "the publication is added even if Scholar fails)."
    ),
)
def add_publication_doi(
    doi: str,
    input_csv: str,
    output_csv: str,
    update_existing: bool,
    fetch_scholar: bool,
) -> None:
    """Add a publication to the curated CSV from a DOI via Crossref metadata."""
    from openff_stats.publications import add_publication_by_doi

    try:
        add_publication_by_doi(
            doi=doi,
            input_csv=input_csv,
            output_csv=output_csv,
            update_existing=update_existing,
            fetch_scholar=fetch_scholar,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc))


@cli.command("add-github-repo")
@click.argument("repo")
@click.option(
    "--input",
    "inputs_csv",
    default="inputs/github_repos.csv",
    show_default=True,
    help="Path to the curated GitHub repos CSV.",
)
def add_github_repo_cmd(repo: str, inputs_csv: str) -> None:
    """Add a GitHub repo (OWNER/REPO or URL) to the curated CSV.

    Validates the repo via the GitHub API (no token required) and appends it
    with status=manual.
    """
    from openff_stats.github import add_github_repo

    try:
        add_github_repo(repo, inputs_csv)
    except ValueError as exc:
        raise click.ClickException(str(exc))


@cli.command("add-zenodo")
@click.argument("id_or_doi")
@click.option(
    "--input",
    "inputs_csv",
    default="inputs/zenodo.csv",
    show_default=True,
    help="Path to the curated Zenodo CSV.",
)
def add_zenodo_cmd(id_or_doi: str, inputs_csv: str) -> None:
    """Add a Zenodo record (numeric ID, DOI, or URL) to the curated CSV."""
    from openff_stats.zenodo import add_zenodo_record

    try:
        add_zenodo_record(id_or_doi, inputs_csv)
    except ValueError as exc:
        raise click.ClickException(str(exc))


@cli.command("scholar-lookup")
@click.argument("doi")
@click.option(
    "--input",
    "publications_csv",
    default="inputs/publications.csv",
    show_default=True,
    help="Publications CSV to update when --save is given.",
)
@click.option(
    "--save",
    is_flag=True,
    default=False,
    help="Write the matched cluster ID into the publications CSV.",
)
def scholar_lookup_cmd(doi: str, publications_csv: str, save: bool) -> None:
    """Look up the Google Scholar cluster ID (and citations) for a DOI.

    Searches Scholar for the DOI, falling back to the Crossref title; every
    candidate is printed with its title similarity, and only a confident
    match is saved.
    """
    from openff_stats.publications import scholar_lookup

    scholar_lookup(doi, publications_csv=publications_csv, save=save)


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


@cli.command("discover-dependents")
@click.option(
    "--output",
    default="candidates/dependents.csv",
    show_default=True,
    help="Path for the candidates CSV (for human review).",
)
@click.option(
    "--subdir",
    "subdirs",
    multiple=True,
    default=["noarch", "linux-64"],
    show_default=True,
    help=(
        "conda-forge subdir(s) to scan (e.g. noarch, linux-64, osx-arm64). "
        "May be repeated."
    ),
)
@click.option(
    "--dep",
    "dep_name",
    default="openff-toolkit",
    show_default=True,
    help="Dependency name to search for.",
)
def discover_dependents(output: str, subdirs: tuple[str, ...], dep_name: str) -> None:
    """Find conda-forge packages that declare openff-toolkit as a dependency.

    Downloads repodata.json for each subdir, scans all package entries, and
    writes a candidates CSV of packages whose run-dependencies include
    openff-toolkit.  Requires human verification before use.
    """
    from openff_stats.downloads import discover_dependents as _discover
    _discover(output, list(subdirs), dep_name)


@cli.command("dep-tree")
@click.option(
    "--root",
    "roots",
    multiple=True,
    default=["openff-toolkit"],
    show_default=True,
    help="Root package(s) for the tree. May be repeated. -base variants are merged automatically.",
)
@click.option(
    "--depth",
    default=2,
    show_default=True,
    help="Number of BFS levels beyond the roots.",
)
@click.option(
    "--subdir",
    "subdirs",
    multiple=True,
    default=["noarch", "linux-64"],
    show_default=True,
    help="conda-forge subdir(s) to scan. May be repeated.",
)
@click.option(
    "--output",
    default="data/dep_tree.csv",
    show_default=True,
    help="Path for the tree CSV.",
)
def dep_tree(roots: tuple[str, ...], depth: int, subdirs: tuple[str, ...], output: str) -> None:
    """Build a reverse-dependency tree rooted at openff-toolkit packages.

    Fetches conda-forge repodata, BFS-expands the reverse dep graph, and
    records Anaconda download counts for each node.  Re-plot with different
    thresholds using plot-dep-tree without re-running this command.
    """
    from openff_stats.downloads import collect_dep_tree
    collect_dep_tree(list(roots), depth, list(subdirs) or None, output)


@cli.command("plot-dep-tree")
@click.option(
    "--input",
    "dep_tree_csv",
    default="data/dep_tree.csv",
    show_default=True,
    help="Path to the tree CSV produced by dep-tree.",
)
@click.option(
    "--output",
    "output_path",
    default="data/plots/openff_dep_tree.png",
    show_default=True,
    help="Path to save the PNG plot.",
)
def plot_dep_tree_cmd(dep_tree_csv: str, output_path: str) -> None:
    """Plot the reverse-dependency tree as a dendrogram.

    Pure branch style, all nodes labelled.  Re-run without re-fetching repodata.
    """
    from openff_stats.plotting import plot_dep_tree
    plot_dep_tree(dep_tree_csv, output_path)


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


@cli.command("scholar-clusters")
@click.option(
    "--input",
    "input_csv",
    default="inputs/publications.csv",
    show_default=True,
    help="Path to publications CSV containing title and scholar_cluster_id columns.",
)
@click.option(
    "--output",
    "output_csv",
    default="inputs/publications.csv",
    show_default=True,
    help="Path to write updated CSV with scholar_cluster_id values.",
)
@click.option(
    "--overwrite-existing",
    is_flag=True,
    default=False,
    help="Re-query rows that already have scholar_cluster_id values.",
)
def scholar_clusters(input_csv: str, output_csv: str, overwrite_existing: bool) -> None:
    """Populate scholar_cluster_id values by searching Google Scholar by title."""
    from openff_stats.publications import populate_scholar_cluster_ids
    populate_scholar_cluster_ids(input_csv, output_csv, overwrite_existing)


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


@cli.command("github-stars")
@click.option(
    "--input",
    "repos_csv",
    default="inputs/github_repos.csv",
    show_default=True,
    help="Path to the curated GitHub repos CSV.",
)
@click.option(
    "--output",
    "output_csv",
    default="data/github_repo_stars.csv",
    show_default=True,
    help="Path for the star counts output CSV.",
)
def github_stars(repos_csv: str, output_csv: str) -> None:
    """Fetch GitHub star counts for all repos in the repos CSV.

    Makes one API request per repo.  Requires GITHUB_TOKEN.
    """
    from openff_stats.github import collect_repo_stars
    collect_repo_stars(repos_csv, output_csv)


@cli.command("discover-github-repos")
@click.option(
    "--output",
    "output_csv",
    default="candidates/github_repos.csv",
    show_default=True,
    help="Path for the candidates CSV (for human review).",
)
@click.option(
    "--inputs",
    "inputs_csv",
    default="inputs/github_repos.csv",
    show_default=True,
    help="Curated repos CSV used to flag which candidates are new.",
)
def discover_github_repos_cmd(output_csv: str, inputs_csv: str) -> None:
    """Search GitHub for repos that import or depend on openff.toolkit.

    Uses sharded code-search queries to work around GitHub's 1000-result cap.
    Writes a candidates CSV with new repos flagged and sorted first; merge
    approved rows into inputs/github_repos.csv.  Requires GITHUB_TOKEN.
    """
    from openff_stats.github import discover_github_repos
    discover_github_repos(output_csv, inputs_csv)


@cli.command("github-repos", hidden=True)
@click.option("--output", "output_csv", default="candidates/github_repos.csv")
@click.option("--inputs", "inputs_csv", default="inputs/github_repos.csv")
def github_repos_deprecated(output_csv: str, inputs_csv: str) -> None:
    """Deprecated alias for discover-github-repos."""
    click.echo(
        "`github-repos` is deprecated; use `discover-github-repos`. "
        f"Output now goes to {output_csv} for human review."
    )
    from openff_stats.github import discover_github_repos
    discover_github_repos(output_csv, inputs_csv)


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


@cli.command("plot-dependents")
@click.option(
    "--input",
    "dependents_csv",
    default="candidates/dependents.csv",
    show_default=True,
    help="Path to the dependents CSV.",
)
@click.option(
    "--output",
    "output_path",
    default="data/plots/openff_dependents.png",
    show_default=True,
    help="Path to save the PNG plot.",
)
def plot_dependents(dependents_csv: str, output_path: str) -> None:
    """Plot conda-forge packages that depend on openff-toolkit."""
    from openff_stats.plotting import plot_dependents as _plot
    _plot(dependents_csv, output_path)


@cli.command("github-descriptions")
@click.option("--input", "repos_csv", default="inputs/github_repos.csv", show_default=True)
@click.option("--stars", "stars_csv", default="data/github_repo_stars.csv", show_default=True)
@click.option("--output", "output_csv", default="data/github_repo_descriptions.csv", show_default=True)
@click.option("--star-threshold", default=30, show_default=True,
              help="Minimum stars for a repo to be included.")
def github_descriptions(repos_csv, stars_csv, output_csv, star_threshold):
    """Fetch GitHub descriptions and README summaries, auto-classify by topic."""
    from openff_stats.github import collect_repo_descriptions
    collect_repo_descriptions(repos_csv, stars_csv, output_csv, star_threshold)


@cli.command("plot-github-bubbles")
@click.option("--input", "github_csv", default="inputs/github_repos.csv", show_default=True)
@click.option("--stars", "stars_csv", default="data/github_repo_stars.csv", show_default=True)
@click.option("--output", "output_path", default="data/plots/openff_github_bubbles.png", show_default=True)
@click.option("--star-threshold", default=30, show_default=True,
              help="Min stars to appear on outer ring.")
@click.option("--label-threshold", default=100, show_default=True,
              help="Min stars to show full org/repo label (below shows repo name only).")
@click.option("--exclude-org", "exclude_orgs", multiple=True)
@click.option("--descriptions", "descriptions_csv", default="data/github_repo_descriptions.csv",
              show_default=True, help="Repo descriptions CSV for category coloring.")
def plot_github_bubbles(github_csv, stars_csv, output_path, star_threshold, label_threshold,
                        exclude_orgs, descriptions_csv):
    """Radial bubble chart sized by stars, colored by topic category."""
    import pathlib
    from openff_stats.plotting import plot_github_bubbles as _plot
    desc = descriptions_csv if pathlib.Path(descriptions_csv).exists() else None
    _plot(github_csv, stars_csv, output_path, star_threshold, label_threshold,
          list(exclude_orgs) or None, desc)


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
@click.option(
    "--github-input", default="inputs/github_repos.csv", show_default=True,
    help="Curated GitHub repos CSV.",
)
@click.option(
    "--refresh-scholar-clusters",
    is_flag=True,
    default=False,
    help=(
        "Populate/update scholar_cluster_id values in the publications input "
        "before collecting citations."
    ),
)
@click.option(
    "--skip-github",
    is_flag=True,
    default=False,
    help="Skip GitHub star collection (useful if GITHUB_TOKEN is not set).",
)
def run_all(
    publications_input: str,
    packages_input: str,
    zenodo_input: str,
    github_input: str,
    refresh_scholar_clusters: bool,
    skip_github: bool,
) -> None:
    """Run the full data-collection pipeline (citations, downloads, zenodo, plot).

    Reads the curated input files and writes all outputs to data/.
    Discovery steps are NOT run here — they require separate human
    verification.  GitHub descriptions and the bubble plot are also manual
    (`github-descriptions` needs its category column reviewed before
    `plot-github-bubbles`).
    """
    import os
    import pathlib

    from openff_stats.publications import (
        collect_all_citations,
        populate_scholar_cluster_ids,
    )
    from openff_stats.downloads import collect_all_downloads
    from openff_stats.zenodo import collect_zenodo_citations
    from openff_stats.plotting import plot_downloads_per_year

    # --- Citations ---
    if pathlib.Path(publications_input).exists():
        if refresh_scholar_clusters:
            click.echo("\n=== Scholar cluster IDs ===")
            populate_scholar_cluster_ids(
                publications_input,
                publications_input,
                overwrite_existing=True,
            )

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

    # --- GitHub stars (for the curated repo list) ---
    if skip_github:
        click.echo("\nSkipping GitHub stars (--skip-github).")
    elif not pathlib.Path(github_input).exists():
        click.echo(f"Skipping GitHub stars: {github_input} not found.")
    elif not os.environ.get("GITHUB_TOKEN"):
        click.echo(
            "\nSkipping GitHub stars: GITHUB_TOKEN is not set. "
            "Run `openff-stats github-stars` manually once the token is "
            "available, or re-run with GITHUB_TOKEN set."
        )
    else:
        click.echo("\n=== GitHub stars ===")
        from openff_stats.github import collect_repo_stars
        collect_repo_stars(github_input, "data/github_repo_stars.csv")

    # --- Plot ---
    yearly_csv = "data/downloads_yearly.csv"
    if pathlib.Path(yearly_csv).exists():
        click.echo("\n=== Download plot ===")
        plot_downloads_per_year(yearly_csv, "data/plots/openff_downloads_per_year.png")
    else:
        click.echo(f"Skipping plot: {yearly_csv} not found.")

    click.echo("\nDone.")
