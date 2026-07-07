"""
openff-stats command-line interface.

Entry point: `openff-stats`

The source lists in inputs/ are manually curated.  Each kind is a directory
of CSVs where the filename is the group classification (e.g.
inputs/publications/force-field.csv).  Add new sources with:
  openff-stats add-doi DOI... [--file dois.txt] [--group NAME]
                                                  (auto-routes Zenodo vs paper)
  openff-stats add-publication-doi 10.1021/acs.jpcb.4c01558 [--scholar] [--group NAME]
  openff-stats add-github-repo owner/repo [--group PACKAGE]
  openff-stats add-zenodo 10.5281/zenodo.18842670 [--group NAME]

Google Scholar lookup by DOI (find/store the Scholar cluster ID):
  openff-stats scholar-lookup 10.1021/acs.jpcb.4c01558 [--save] [--open]
  openff-stats scholar-clusters                                   (fill all DOIs)
  openff-stats verify-doi 10.1021/acs.jpcb.4c01558   (check a DOI resolves)

Data collection commands (read curated inputs/, write data/):
  openff-stats citations
  openff-stats downloads
  openff-stats zenodo-citations
  openff-stats github-stars         (requires GITHUB_TOKEN env var)
  openff-stats classify-repos       (re-tag an existing stars CSV, no token needed)
  openff-stats github-descriptions  (requires GITHUB_TOKEN env var)

Optional bulk discovery (writes candidates/ for human review; never
feeds collection directly):
  openff-stats discover-publications --orcid-csv inputs/orcids.csv
  openff-stats discover-packages
  openff-stats discover-dependents
  openff-stats discover-zenodo

GitHub repo discovery is different: it verifies each candidate against its
matched files and writes straight to data/github_repos/<package>.csv (no
candidates/ review step). With no --package it sweeps every row of
inputs/github_packages.csv:
  openff-stats discover-github-repos [--package X --import-name Y] (requires GITHUB_TOKEN env var)

Run all collection (never discovery):
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
    inputs/publications/<group>.csv. Not all papers found will be OpenFF-related.
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
    "--inputs-dir",
    "inputs_dir",
    default="inputs/publications",
    show_default=True,
    help="Directory of curated publication group CSVs.",
)
@click.option(
    "--group",
    default="general",
    show_default=True,
    help="Group file to append to (filename = classification, e.g. force-field).",
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
@click.option(
    "--verify/--no-verify",
    "verify",
    default=True,
    show_default=True,
    help="Check the DOI resolves via doi.org before adding.",
)
def add_publication_doi(
    doi: str,
    inputs_dir: str,
    group: str,
    update_existing: bool,
    fetch_scholar: bool,
    verify: bool,
) -> None:
    """Add a publication to a curated group CSV from a DOI via Crossref metadata.

    The DOI is checked against doi.org first (skip with --no-verify); the
    duplicate check spans every group file in the directory.
    """
    from openff_stats.publications import add_publication_by_doi

    try:
        add_publication_by_doi(
            doi=doi,
            inputs_dir=inputs_dir,
            group=group,
            update_existing=update_existing,
            fetch_scholar=fetch_scholar,
            verify=verify,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc))


@cli.command("add-github-repo")
@click.argument("repo")
@click.option(
    "--inputs-dir",
    "inputs_dir",
    default="data/github_repos",
    show_default=True,
    help="Directory of curated repo group CSVs.",
)
@click.option(
    "--group",
    default="openff-toolkit",
    show_default=True,
    help="Group file to append to (filename = the package the repo imports).",
)
def add_github_repo_cmd(repo: str, inputs_dir: str, group: str) -> None:
    """Add a GitHub repo (OWNER/REPO or URL) to a curated group CSV.

    Validates the repo via the GitHub API (no token required) and appends it
    with status=manual.  The duplicate check spans every group file.
    """
    from openff_stats.github import add_github_repo

    try:
        add_github_repo(repo, inputs_dir, group)
    except ValueError as exc:
        raise click.ClickException(str(exc))


@cli.command("add-zenodo")
@click.argument("id_or_doi")
@click.option(
    "--inputs-dir",
    "inputs_dir",
    default="inputs/zenodo",
    show_default=True,
    help="Directory of curated Zenodo group CSVs.",
)
@click.option(
    "--group",
    default="general",
    show_default=True,
    help="Group file to append to (filename = classification, e.g. qcsubmit).",
)
def add_zenodo_cmd(id_or_doi: str, inputs_dir: str, group: str) -> None:
    """Add a Zenodo record (numeric ID, DOI, or URL) to a curated group CSV.

    The duplicate check spans every group file.
    """
    from openff_stats.zenodo import add_zenodo_record

    try:
        add_zenodo_record(id_or_doi, inputs_dir, group)
    except ValueError as exc:
        raise click.ClickException(str(exc))


@cli.command("add-doi")
@click.argument("dois", nargs=-1)
@click.option(
    "--file",
    "doi_file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Text file with one DOI per line (blank lines and # comments skipped).",
)
@click.option(
    "--publications-dir",
    default="inputs/publications",
    show_default=True,
    help="Directory of curated publication group CSVs (non-Zenodo DOIs go here).",
)
@click.option(
    "--zenodo-dir",
    default="inputs/zenodo",
    show_default=True,
    help="Directory of curated Zenodo group CSVs (10.5281/zenodo.* DOIs go here).",
)
@click.option(
    "--group",
    default="general",
    show_default=True,
    help="Group file to append to in either directory (filename = classification).",
)
@click.option(
    "--scholar",
    "fetch_scholar",
    is_flag=True,
    default=False,
    help="Also look up the Google Scholar cluster ID for publications (Selenium; best-effort).",
)
def add_doi(
    dois: tuple[str, ...],
    doi_file: str | None,
    publications_dir: str,
    zenodo_dir: str,
    group: str,
    fetch_scholar: bool,
) -> None:
    """Add DOIs to the right curated group CSV, auto-detecting Zenodo DOIs.

    DOIs with the 10.5281/zenodo. prefix are Zenodo records and go to
    inputs/zenodo/<group>.csv; everything else is treated as a publication
    and added via Crossref metadata to inputs/publications/<group>.csv.
    Pass DOIs as arguments and/or a --file with one DOI per line.
    Already-present DOIs are skipped (checked across all groups), so
    re-running is safe; failures don't stop the batch.
    """
    import pathlib

    import requests

    from openff_stats.publications import _normalize_doi, add_publication_by_doi
    from openff_stats.zenodo import add_zenodo_record

    all_dois = list(dois)
    if doi_file:
        for line in pathlib.Path(doi_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                all_dois.append(line)
    if not all_dois:
        raise click.ClickException("No DOIs given. Pass DOIs as arguments and/or --file.")

    counts = {"publication": 0, "zenodo": 0}
    failures: list[tuple[str, str]] = []
    for doi in all_dois:
        normalized = _normalize_doi(doi)
        kind = "zenodo" if normalized.lower().startswith("10.5281/zenodo.") else "publication"
        click.echo(f"\n{normalized}  →  {kind} ({group})")
        try:
            if kind == "zenodo":
                add_zenodo_record(doi, zenodo_dir, group)
            else:
                add_publication_by_doi(
                    doi=doi,
                    inputs_dir=publications_dir,
                    group=group,
                    fetch_scholar=fetch_scholar,
                )
            counts[kind] += 1
        except (ValueError, requests.RequestException) as exc:
            failures.append((normalized, str(exc)))
            click.echo(f"  FAILED: {exc}")

    click.echo(
        f"\nProcessed {counts['publication']} publication(s) and "
        f"{counts['zenodo']} Zenodo record(s); {len(failures)} failed."
    )
    if failures:
        raise click.ClickException(
            "Failed DOIs:\n" + "\n".join(f"  {d}: {msg}" for d, msg in failures)
        )


@cli.command("scholar-lookup")
@click.argument("doi")
@click.option(
    "--input",
    "inputs_dir",
    default="inputs/publications",
    show_default=True,
    help="Directory of publication group CSVs to update when --save is given.",
)
@click.option(
    "--save",
    is_flag=True,
    default=False,
    help="Write the matched cluster ID into the publications CSV.",
)
@click.option(
    "--open",
    "open_links",
    is_flag=True,
    default=False,
    help="Open the DOI page and the matched Scholar cluster page in a browser.",
)
def scholar_lookup_cmd(doi: str, inputs_dir: str, save: bool, open_links: bool) -> None:
    """Look up the Google Scholar cluster ID (and citations) for a DOI.

    Searches Scholar for the DOI, falling back to the Crossref title; every
    candidate is printed with its title similarity and a clickable Scholar
    URL, and only a confident match is saved (into whichever group CSV holds
    the DOI).  Use --open to launch the DOI and Scholar pages in a browser
    for hands-on verification.
    """
    from openff_stats.publications import scholar_lookup

    scholar_lookup(doi, inputs_dir=inputs_dir, save=save, open_links=open_links)


@cli.command("verify-doi")
@click.argument("doi")
@click.option(
    "--open",
    "open_link",
    is_flag=True,
    default=False,
    help="Also open the DOI page in a browser.",
)
def verify_doi_cmd(doi: str, open_link: bool) -> None:
    """Check that a DOI resolves and print its registered title/publisher.

    Uses doi.org content negotiation (works for Crossref- and DataCite-
    registered DOIs).  Exits non-zero if the DOI does not resolve.
    """
    from openff_stats.publications import verify_doi, doi_url, _open_in_browser

    resolution = verify_doi(doi)
    if resolution is None:
        raise click.ClickException(f"DOI does not resolve: {doi}")

    click.echo(f"Resolves:  {doi_url(doi)}")
    click.echo(f"Title:     {resolution['title']}")
    click.echo(f"Publisher: {resolution['publisher']}")
    click.echo(f"Type:      {resolution['type']}")
    if open_link:
        _open_in_browser([doi_url(doi)])


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
    inputs/packages/<group>.csv.
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
    inputs/zenodo/<group>.csv.
    """
    from openff_stats.zenodo import discover_zenodo as _discover
    _discover(output)


# ---------------------------------------------------------------------------
# Data collection commands
# ---------------------------------------------------------------------------

@cli.command("citations")
@click.option(
    "--input",
    "inputs_dir",
    default="inputs/publications",
    show_default=True,
    help="Directory of curated publication group CSVs (filename = group).",
)
@click.option(
    "--output",
    "output_csv",
    default="data/citations.csv",
    show_default=True,
    help="Path for the citations output CSV.",
)
def citations(inputs_dir: str, output_csv: str) -> None:
    """Collect citation counts from Crossref, Google Scholar, and ChemRxiv.

    Prints cumulative sums per group (group = input filename) and overall.
    """
    from openff_stats.publications import collect_all_citations
    collect_all_citations(inputs_dir, output_csv)


@cli.command("scholar-clusters")
@click.option(
    "--input",
    "inputs_dir",
    default="inputs/publications",
    show_default=True,
    help="Directory of publication group CSVs (updated in place).",
)
@click.option(
    "--overwrite-existing",
    is_flag=True,
    default=False,
    help="Re-query rows that already have scholar_cluster_id values.",
)
def scholar_clusters(inputs_dir: str, overwrite_existing: bool) -> None:
    """Fill scholar_cluster_id for every DOI in the publication CSVs (bulk).

    Runs the same DOI-first, title-validated lookup as `scholar-lookup` over
    every row of every group file, filling only the blanks (use
    --overwrite-existing to redo all).
    """
    from openff_stats.publications import populate_scholar_cluster_ids
    populate_scholar_cluster_ids(inputs_dir, overwrite_existing)


@cli.command("downloads")
@click.option(
    "--input",
    "inputs_dir",
    default="inputs/packages",
    show_default=True,
    help="Directory of curated package group CSVs (filename = group).",
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
def downloads(inputs_dir: str, output_csv: str, yearly_csv: str) -> None:
    """Collect conda-forge download stats via Anaconda scraping and condastats.

    Prints cumulative download sums per group (group = input filename).
    """
    from openff_stats.downloads import collect_all_downloads
    collect_all_downloads(inputs_dir, output_csv, yearly_csv)


@cli.command("github-stars")
@click.option(
    "--input",
    "inputs_dir",
    default="data/github_repos",
    show_default=True,
    help="Directory of curated repo group CSVs (filename = imported package).",
)
@click.option(
    "--output",
    "output_csv",
    default="data/github_repo_stars.csv",
    show_default=True,
    help="Path for the star counts output CSV.",
)
def github_stars(inputs_dir: str, output_csv: str) -> None:
    """Fetch GitHub star counts for all curated repos.

    Makes one API request per repo.  Prints per-group sums (repo count =
    GitHub repo imports, plus total stars).  Requires GITHUB_TOKEN.
    """
    from openff_stats.github import collect_repo_stars
    collect_repo_stars(inputs_dir, output_csv)


@cli.command("classify-repos")
@click.option(
    "--input",
    "input_csv",
    default="data/github_repo_stars.csv",
    show_default=True,
    help="Path to an existing star counts CSV to re-tag in place.",
)
@click.option(
    "--blacklist",
    "blacklist_csv",
    default="inputs/github_owner_blacklist.csv",
    show_default=True,
    help="Owner blacklist CSV (columns: owner, reason).",
)
def classify_repos_cmd(input_csv: str, blacklist_csv: str) -> None:
    """Re-tag an existing stars CSV with owner validity, without re-fetching from GitHub.

    Overwrites any existing valid/reason columns and prints per-group totals
    (repos, valid repos, stars, valid stars).  If the CSV has a ``fork_of``
    column, also re-applies the fork rule (only the highest-starred member of
    a fork family counts as valid).
    """
    import pandas as pd
    from openff_stats.github import (
        apply_fork_rule,
        classify_repos,
        load_github_packages,
        load_owner_blacklist,
    )

    df = pd.read_csv(input_csv)
    blacklist = load_owner_blacklist(blacklist_csv)
    df = classify_repos(df, blacklist)
    if "fork_of" in df.columns:
        df = apply_fork_rule(df, group_priority=list(load_github_packages()))
    df.to_csv(input_csv, index=False)
    print(f"Re-tagged {len(df)} repos in {input_csv}")
    for group_name, subset in df.groupby("group"):
        n_valid = int(subset["valid"].sum())
        valid_stars = int(subset.loc[subset["valid"], "stars"].sum())
        print(
            f"  {group_name}: {len(subset)} repos ({n_valid} valid), "
            f"{int(subset['stars'].sum()):,} stars ({valid_stars:,} valid)"
        )


@cli.command("discover-github-repos")
@click.option(
    "--output",
    "output_csv",
    default=None,
    help=(
        "Path for the verified repos CSV (only valid alongside --package; "
        "defaults to data/github_repos/<package>.csv)."
    ),
)
@click.option(
    "--package",
    "package_name",
    default=None,
    help=(
        "Distribution name on conda-forge/PyPI; used in dependency-file "
        "queries. Omit to sweep every package in --packages-csv instead."
    ),
)
@click.option(
    "--import-name",
    "import_name",
    default=None,
    help=(
        "Python import path; used in import-statement queries. Looked up "
        "from --packages-csv if omitted (requires --package)."
    ),
)
@click.option(
    "--packages-csv",
    "packages_csv",
    default="inputs/github_packages.csv",
    show_default=True,
    help="CSV of package,import_name pairs swept when --package is omitted.",
)
@click.option(
    "--include-requirements",
    is_flag=True,
    default=False,
    help=(
        "Also search requirements.txt files. Off by default: GitHub matches "
        "hyphenated tokens (gradient-descent matches 'descent'), so this "
        "query mostly adds tens of thousands of shard-paged hits."
    ),
)
def discover_github_repos_cmd(
    output_csv: str | None,
    package_name: str | None,
    import_name: str | None,
    packages_csv: str,
    include_requirements: bool,
) -> None:
    """Search GitHub for, and verify, repos that import or depend on a package.

    Each candidate repo is verified against the files that actually matched
    (dependency manifest, .py import, or .ipynb code-cell import) and tagged
    status=auto/exclude accordingly — no human review step, unlike the other
    discover-* commands.  Uses sharded code-search queries to work around
    GitHub's 1000-result cap.  Requires GITHUB_TOKEN.

    With no --package, sweeps every row of --packages-csv sequentially, each
    writing its own data/github_repos/<package>.csv.  With --package but no
    --import-name, the import name is looked up from --packages-csv (error if
    not listed there).  With both --package and --import-name given
    explicitly, runs a one-off discovery for that pair (and, if the pair
    isn't in --packages-csv, suggests adding it there for future sweeps).
    """
    from openff_stats.github import discover_github_repos, load_github_packages

    packages = load_github_packages(packages_csv)

    if package_name is None:
        if output_csv is not None:
            raise click.UsageError("--output requires --package (a sweep writes one file per package).")
        if not packages:
            raise click.ClickException(f"No packages found in {packages_csv}.")
        for pkg, spec in packages.items():
            click.echo(f"\n=== {pkg} ({spec['import_name']}, {spec['search_mode']}) ===")
            discover_github_repos(
                pkg,
                spec["import_name"],
                include_requirements=include_requirements,
                search_mode=spec["search_mode"],
            )
        return

    search_mode = "full"
    if import_name is None:
        if package_name not in packages:
            raise click.ClickException(
                f"--import-name not given and {package_name!r} is not listed in "
                f"{packages_csv}. Pass --import-name explicitly, or add a row "
                f"'{package_name},<import_name>' to {packages_csv}."
            )
        import_name = packages[package_name]["import_name"]
        search_mode = packages[package_name]["search_mode"]
    elif package_name in packages:
        search_mode = packages[package_name]["search_mode"]
    else:
        click.echo(
            f"Tip: add '{package_name},{import_name}' to {packages_csv} to "
            "include it in future no-argument sweeps."
        )

    discover_github_repos(
        package_name,
        import_name,
        output_csv,
        include_requirements=include_requirements,
        search_mode=search_mode,
    )


@cli.command("zenodo-citations")
@click.option(
    "--input",
    "inputs_dir",
    default="inputs/zenodo",
    show_default=True,
    help="Directory of curated Zenodo group CSVs (filename = group).",
)
@click.option(
    "--output",
    "output_csv",
    default="data/zenodo_citations.csv",
    show_default=True,
    help="Path for the Zenodo citation counts output CSV.",
)
def zenodo_citations(inputs_dir: str, output_csv: str) -> None:
    """Collect citation counts for Zenodo records via the DataCite API.

    Prints cumulative sums per group (group = input filename) and overall.
    """
    from openff_stats.zenodo import collect_zenodo_citations
    collect_zenodo_citations(inputs_dir, output_csv)


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

@cli.command("github-descriptions")
@click.option("--input", "repos_csv", default="data/github_repos", show_default=True)
@click.option("--stars", "stars_csv", default="data/github_repo_stars.csv", show_default=True)
@click.option("--output", "output_csv", default="data/github_repo_descriptions.csv", show_default=True)
@click.option("--star-threshold", default=30, show_default=True,
              help="Minimum stars for a repo to be included.")
def github_descriptions(repos_csv, stars_csv, output_csv, star_threshold):
    """Fetch GitHub descriptions and README summaries, auto-classify by topic."""
    from openff_stats.github import collect_repo_descriptions
    collect_repo_descriptions(repos_csv, stars_csv, output_csv, star_threshold)


# ---------------------------------------------------------------------------
# run-all
# ---------------------------------------------------------------------------

@cli.command("run-all")
@click.option(
    "--publications-input", default="inputs/publications", show_default=True,
    help="Directory of curated publication group CSVs.",
)
@click.option(
    "--packages-input", default="inputs/packages", show_default=True,
    help="Directory of curated package group CSVs.",
)
@click.option(
    "--zenodo-input", default="inputs/zenodo", show_default=True,
    help="Directory of curated Zenodo group CSVs.",
)
@click.option(
    "--github-input", default="data/github_repos", show_default=True,
    help="Directory of curated GitHub repo group CSVs.",
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
    """Run the full data-collection pipeline (citations, downloads, zenodo).

    Reads the curated input files and writes all outputs to data/.
    Discovery steps are NOT run here — they require separate human
    verification.  GitHub descriptions are also manual (`github-descriptions`
    needs its category column reviewed).
    """
    import os
    import pathlib

    from openff_stats.publications import (
        collect_all_citations,
        populate_scholar_cluster_ids,
    )
    from openff_stats.downloads import collect_all_downloads
    from openff_stats.zenodo import collect_zenodo_citations

    # --- Citations ---
    if pathlib.Path(publications_input).exists():
        if refresh_scholar_clusters:
            click.echo("\n=== Scholar cluster IDs ===")
            populate_scholar_cluster_ids(
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

    click.echo("\nDone.")
