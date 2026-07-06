"""
GitHub repo tracking: curated lists in inputs/github_repos/ plus optional
code-search discovery.

Each CSV in inputs/github_repos/ is one group — the filename is the package
the repos import (e.g. openff-toolkit.csv).  Columns: repo, url, status,
notes.  `status` is `manual` (human-added), `auto` (seeded from discovery),
or `exclude` (kept in the file for the record but skipped by collection).

Workflow:
  openff-stats add-github-repo OWNER/REPO [--group NAME]
                                            → append to inputs/github_repos/<group>.csv
  openff-stats discover-github-repos --package X --import-name Y
                                            → code search, writes
                                              candidates/github_repos.csv for
                                              human review (new repos first)
  openff-stats github-stars                 → star counts + per-group import sums

Discovery uses sharded queries to work around GitHub's hard 1000-result cap on
any single code-search request: when a query returns >= 1000 hits the search
is automatically re-run split across file-size buckets, and the results are
unioned.  Buckets recurse up to depth 2 before giving up on that shard.

Discovery and star collection require the GITHUB_TOKEN environment variable
(a personal access token; no special scopes needed for public repos).
`add-github-repo` works without a token.
"""

import os
import pathlib
import time

import pandas as pd
import requests

from openff_stats import curated

GITHUB_SEARCH_URL = "https://api.github.com/search/code"

# File-size buckets (bytes) used to shard a query that hits the 1 000-result
# cap.  Tune these if a bucket still overflows — just subdivide it further.
_SIZE_BUCKETS = [
    "0..500",
    "501..2000",
    "2001..8000",
    "8001..30000",
    "30001..150000",
    ">150000",
]

def _build_queries(package_name: str, import_name: str) -> list[str]:
    """Code-search queries covering the ways a package may appear in a repo.

    Runtime-import queries use *import_name* (e.g. ``openff.toolkit``);
    declared-dependency queries use *package_name* (e.g. ``openff-toolkit``).
    """
    return [
        # Runtime imports
        f"import {import_name} language:python",
        f"from {import_name} language:python",
        f"import {import_name} extension:ipynb",
        f"from {import_name} extension:ipynb",
        # Declared dependencies
        f"{package_name} filename:setup.cfg",
        f"{package_name} filename:pyproject.toml",
        f"{package_name} filename:requirements.txt",
        f"{package_name} filename:environment.yml",
        f"{package_name} filename:setup.py",
        f"{package_name} filename:pixi.toml",
    ]


def load_curated_repos(inputs_dir: str) -> pd.DataFrame:
    """Load the curated repo group CSVs, dropping rows with status == 'exclude'.

    Reads every CSV in *inputs_dir* (filename = group classification, i.e.
    which package the repos import; a single CSV also works) and tags rows
    with ``group``.
    """
    df = curated.load_groups(inputs_dir, ["repo", "url", "status", "notes"])
    if "status" in df.columns:
        excluded = df["status"].fillna("").astype(str).str.strip().str.lower() == "exclude"
        if excluded.any():
            print(f"Skipping {excluded.sum()} repo(s) with status=exclude.")
        df = df[~excluded]
    return df.reset_index(drop=True)


def _normalize_repo_name(repo: str) -> str:
    """Return 'owner/repo' from a plain name or a github.com URL."""
    import re

    value = str(repo).strip()
    value = re.sub(r"^https?://(www\.)?github\.com/", "", value)
    value = value.rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", value):
        raise ValueError(
            f"Invalid repo {repo!r}: expected OWNER/REPO or a github.com URL."
        )
    return value


def add_github_repo(
    repo: str,
    inputs_dir: str = "inputs/github_repos",
    group: str = "openff-toolkit",
) -> None:
    """Add a repo to the curated group CSV, validating it via the GitHub API.

    Works without GITHUB_TOKEN (unauthenticated requests are fine at this
    volume); if the API is unreachable the repo is appended anyway after a
    syntax check, with a warning.

    Parameters
    ----------
    repo
        Repo as ``owner/repo`` or a github.com URL.
    inputs_dir
        Directory of group CSVs (filename = the package the repos import).
    group
        Group file to append to (``<inputs_dir>/<group>.csv``).  The
        duplicate check spans every group file.
    """
    name = _normalize_repo_name(repo)
    url = f"https://github.com/{name}"

    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Authorization": f"token {token}"} if token else {}
    try:
        r = requests.get(f"https://api.github.com/repos/{name}", headers=headers, timeout=30)
        if r.status_code == 404:
            raise ValueError(f"Repo not found on GitHub: {name}")
        r.raise_for_status()
        data = r.json()
        name = data["full_name"]  # canonical capitalisation
        url = data["html_url"]
        print(f"{name}: {data.get('stargazers_count', 0)} stars — {data.get('description') or '(no description)'}")
    except ValueError:
        raise
    except Exception as exc:
        print(f"Warning: could not validate {name} via the GitHub API ({exc}); adding anyway.")

    columns = ["repo", "url", "status", "notes"]
    all_groups = curated.load_groups(inputs_dir, columns)
    existing = (
        all_groups["repo"].fillna("").astype(str).str.strip().str.lower() == name.lower()
    )
    if existing.any():
        found_group = all_groups.loc[existing, "group"].iloc[0]
        print(f"Repo already present in group '{found_group}', no changes made: {name}")
        return

    inputs_csv = curated.group_path(inputs_dir, group)
    df = curated.load(inputs_csv, columns)
    df = curated.append_row(df, {"repo": name, "url": url, "status": "manual"})
    df = df.sort_values("repo", key=lambda s: s.str.lower(), kind="mergesort")
    curated.save(df, inputs_csv)
    print(f"Added {name} to {inputs_csv}")


def _get_headers() -> dict[str, str]:
    """Build request headers, raising immediately if GITHUB_TOKEN is absent.

    The GitHub code search endpoint requires authentication; unauthenticated
    requests return 401 Unauthorized rather than falling back to a lower rate
    limit.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN environment variable is not set. "
            "The GitHub code search API requires authentication. "
            "Set GITHUB_TOKEN to a personal access token (no special scopes "
            "are needed for searching public repos), or pass "
            "secrets.GITHUB_TOKEN in a GitHub Actions workflow."
        )
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_search(query: str, page: int, headers: dict[str, str]) -> dict:
    """Make one search request, retrying automatically on rate-limit responses."""
    while True:
        r = requests.get(
            GITHUB_SEARCH_URL,
            headers=headers,
            params={"q": query, "per_page": 100, "page": page},
            timeout=30,
        )
        remaining = int(r.headers.get("X-RateLimit-Remaining", 1))
        reset_at = int(r.headers.get("X-RateLimit-Reset", 0))

        if r.status_code == 401:
            raise RuntimeError(
                "GitHub API returned 401 Unauthorized. "
                "Check that GITHUB_TOKEN is valid and has not expired."
            )

        if r.status_code == 422:
            print(f"    Invalid query ({r.json().get('message')}): {query!r}")
            return {}

        if r.status_code in (403, 429) or remaining == 0:
            wait = max(reset_at - time.time(), 0) + 3
            print(f"    Rate limited — sleeping {wait:.0f}s …")
            time.sleep(wait)
            continue

        if r.status_code == 408:
            print(f"    Timeout — retrying in 10s …")
            time.sleep(10)
            continue

        r.raise_for_status()
        return r.json()


def _fetch_all_pages(
    query: str,
    headers: dict[str, str],
) -> tuple[dict[str, str], int]:
    """Exhaust all pages for a query (maximum 1 000 results from the API).

    Parameters
    ----------
    query
        GitHub code-search query string.
    headers
        Request headers including the auth token.

    Returns
    -------
    tuple[dict[str, str], int]
        Mapping of ``{full_name: html_url}`` and the ``total_count`` reported
        by the API for the first page.
    """
    repos: dict[str, str] = {}
    total_count = 0

    for page in range(1, 11):  # 10 pages × 100 results = 1 000 max
        data = _gh_search(query, page, headers)
        items = data.get("items", [])

        if page == 1:
            total_count = data.get("total_count", 0)

        for item in items:
            repo = item["repository"]
            repos[repo["full_name"]] = repo["html_url"]

        if len(items) < 100:
            break

        time.sleep(2)  # stay well clear of secondary rate limits

    return repos, total_count


def _search(
    query: str,
    headers: dict[str, str],
    depth: int = 0,
) -> dict[str, str]:
    """Return all repos matching *query*, sharding by file size if needed.

    When ``total_count >= 1 000`` (the GitHub API cap) the query is re-run
    once per size bucket and the results are unioned.  Recurses up to
    ``depth == 2`` before falling back to a best-effort result.

    Parameters
    ----------
    query
        GitHub code-search query string.
    headers
        Request headers including the auth token.
    depth
        Current recursion depth (callers should leave this at the default).

    Returns
    -------
    dict[str, str]
        Mapping of ``{full_name: html_url}`` for every matching repo found.
    """
    pad = "  " * depth
    repos, total = _fetch_all_pages(query, headers)
    flag = "⚠ " if total >= 800 else "✓ "
    print(f"  {pad}{flag}[{total:>6}] {query}")

    if total < 800 or depth >= 2:
        if depth >= 2 and total >= 800:
            print(
                f"  {pad}  still at cap after 2 levels of sharding — "
                f"returning best-effort {len(repos)} repos for this shard"
            )
        return repos

    # Only shard by file size if the query doesn't already have a size: filter
    # (adding a second size: filter produces conflicting constraints and timeouts)
    if "size:" in query:
        return repos

    print(f"  {pad}  → sharding into {len(_SIZE_BUCKETS)} size buckets …")
    all_repos = dict(repos)
    for bucket in _SIZE_BUCKETS:
        sub = _search(f"{query} size:{bucket}", headers, depth=depth + 1)
        all_repos.update(sub)
        time.sleep(1)

    return all_repos


def collect_repo_stars(inputs_dir: str, output_csv: str) -> pd.DataFrame:
    """Fetch star counts for every curated repo via the GitHub Repos API.

    Makes one request per repo.  Skips repos that return a non-200 status
    (private, deleted, or renamed) and records stars=0 for them.  Prints
    per-group sums (the group = which package the repos import, so the repo
    count per group is the "GitHub repo imports" number).

    Requires the ``GITHUB_TOKEN`` environment variable.

    Parameters
    ----------
    inputs_dir
        Directory of curated repo group CSVs (a single CSV also works).
    output_csv
        Path to write the results CSV (columns: ``group``, ``repo``, ``stars``).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``group``, ``repo``, and ``stars``.
    """
    import tqdm

    headers = _get_headers()
    df = load_curated_repos(inputs_dir)
    rows = []

    for _, curated_row in tqdm.tqdm(df.iterrows(), total=len(df), desc="Fetching stars"):
        repo = curated_row["repo"]
        url = f"https://api.github.com/repos/{repo}"
        while True:
            r = requests.get(url, headers=headers, timeout=30)
            remaining = int(r.headers.get("X-RateLimit-Remaining", 1))
            reset_at = int(r.headers.get("X-RateLimit-Reset", 0))

            if r.status_code in (403, 429) or remaining == 0:
                wait = max(reset_at - time.time(), 0) + 3
                print(f"\n  Rate limited — sleeping {wait:.0f}s …")
                time.sleep(wait)
                continue

            stars = r.json().get("stargazers_count", 0) if r.status_code == 200 else 0
            rows.append({"group": curated_row["group"], "repo": repo, "stars": stars})
            break

        time.sleep(0.05)  # stay clear of secondary rate limits

    result = pd.DataFrame(rows)
    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False)
    print(f"\nSaved star counts for {len(result)} repos to {output_csv}")
    print("\nGitHub repo imports per group:")
    for group_name, subset in result.groupby("group"):
        print(f"  {group_name}: {len(subset)} repos, {int(subset['stars'].sum()):,} total stars")
    return result


_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "openff": [
        "openff", "open force field", "smirnoff", "openff-toolkit",
    ],
    "free-energy": [
        "free energy", "free-energy", "fep", "rbfe", "abfe", "alchemical",
        "perturbation", "kartograf", "gufe", "lomap", "cinnabar", "femto",
        "transformato", "alchemtest",
    ],
    "benchmark": [
        "benchmark", "posex", "posebusters", "posebench", "docking challenge",
        "scoring function", "evaluation", "dataset", "spice",
    ],
    "pose-generation": [
        "docking", "pose generation", "pose prediction", "diffdock", "flowr",
        "gnina", "vina", "glide", "conformer",
    ],
    "ml-potential": [
        "neural network potential", "machine learning potential", "mlff",
        "espaloma", "ani-", "mace", "nequip", "allegro", "painn", "schnet",
        "equivariant", "graph neural network force",
    ],
    "md-automation": [
        "molecular dynamics", "md simulation", "md workflow", "openmm",
        "gromacs", "amber", "namd", "lammps", "simulation pipeline",
        "enhanced sampling", "replica exchange", "setup", "parameterization",
        "Meeko"
    ],
    "cheminformatics": [
        "cheminformatics", "rdkit", "smiles", "inchi", "fingerprint",
        "molecular property", "qsar", "featuriz", "descriptor",
    ],
}


def _classify_repo(description: str, readme: str) -> str:
    """Return the best-matching topic category for a repo."""
    text = (description + " " + readme).lower()
    scores: dict[str, int] = {}
    for topic, keywords in _TOPIC_KEYWORDS.items():
        scores[topic] = sum(1 for kw in keywords if kw in text)
    best = max(scores, key=lambda t: scores[t])
    return best if scores[best] > 0 else "other"


def _fetch_readme_summary(owner_repo: str, headers: dict[str, str]) -> str:
    """Return the first substantive paragraph of a repo's README, or ''."""
    import base64

    url = f"https://api.github.com/repos/{owner_repo}/readme"
    r = requests.get(url, headers=headers, timeout=30)
    if r.status_code != 200:
        return ""
    try:
        content = base64.b64decode(r.json()["content"]).decode("utf-8", errors="replace")
    except Exception:
        return ""

    # Walk lines, skip headings/badges/blank, return first real paragraph
    paragraph: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("![")\
                or stripped.startswith("<") or stripped.startswith("[!["):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
        if len(" ".join(paragraph)) > 300:
            break

    summary = " ".join(paragraph)
    # Truncate at sentence boundary around 300 chars
    if len(summary) > 320:
        end = summary.rfind(". ", 0, 320)
        summary = summary[: end + 1] if end > 0 else summary[:320] + "…"
    return summary


def collect_repo_descriptions(
    repos_csv: str,
    stars_csv: str,
    output_csv: str,
    star_threshold: int = 30,
) -> pd.DataFrame:
    """Fetch descriptions and README summaries for repos above *star_threshold*.

    For each qualifying repo:
    - Uses the GitHub Repos API ``description`` field.
    - Falls back to (or supplements with) the first paragraph of the README.
    - Auto-classifies into a topic category that the user can edit.

    Requires the ``GITHUB_TOKEN`` environment variable.

    Parameters
    ----------
    repos_csv
        Path to the GitHub repos CSV (columns: ``repo``, ``url``).
    stars_csv
        Path to the star counts CSV (columns: ``repo``, ``stars``).
    output_csv
        Path to write the descriptions CSV.
    star_threshold
        Minimum stars for a repo to be included.

    Returns
    -------
    pd.DataFrame
        Columns: ``repo``, ``stars``, ``description``, ``readme_summary``,
        ``category``.
    """
    import tqdm

    headers = _get_headers()

    repos_df = load_curated_repos(repos_csv)
    stars_df = pd.read_csv(stars_csv)
    merged = repos_df.merge(stars_df[["repo", "stars"]], on="repo", how="left")
    merged["stars"] = merged["stars"].fillna(0).astype(int)
    target = merged[merged["stars"] >= star_threshold].sort_values(
        "stars", ascending=False
    ).reset_index(drop=True)

    print(f"Fetching descriptions for {len(target)} repos (≥{star_threshold} stars) …")
    rows = []
    for _, row in tqdm.tqdm(target.iterrows(), total=len(target), desc="Repos"):
        repo = row["repo"]
        url = f"https://api.github.com/repos/{repo}"

        while True:
            r = requests.get(url, headers=headers, timeout=30)
            remaining = int(r.headers.get("X-RateLimit-Remaining", 1))
            reset_at = int(r.headers.get("X-RateLimit-Reset", 0))
            if r.status_code in (403, 429) or remaining == 0:
                wait = max(reset_at - time.time(), 0) + 3
                print(f"\n  Rate limited — sleeping {wait:.0f}s …")
                time.sleep(wait)
                continue
            break

        description = ""
        if r.status_code == 200:
            description = r.json().get("description") or ""

        readme = _fetch_readme_summary(repo, headers)
        category = _classify_repo(description, readme)

        rows.append({
            "repo": repo,
            "stars": int(row["stars"]),
            "description": description,
            "readme_summary": readme,
            "category": category,
        })
        time.sleep(0.15)

    df = pd.DataFrame(rows)
    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"\nSaved {len(df)} repo descriptions to {output_csv}")
    print("Review and edit the 'category' column.")
    return df


def discover_github_repos(
    output_csv: str = "candidates/github_repos.csv",
    inputs_dir: str = "inputs/github_repos",
    package_name: str = "openff-toolkit",
    import_name: str = "openff.toolkit",
) -> pd.DataFrame:
    """Search GitHub for repositories that import or depend on a package.

    Runs a set of sharded code-search queries and unions the results, working
    around the 1 000-result cap that GitHub imposes on any single query.
    Writes a candidates CSV for human review; repos not already in the curated
    list are flagged ``new`` and sorted first, so review is a quick scan of
    the top rows.  Merge approved rows into inputs/github_repos/<group>.csv
    (or use ``add-github-repo --group``).

    Requires the ``GITHUB_TOKEN`` environment variable.

    Parameters
    ----------
    output_csv
        Path to write the candidates CSV (columns: ``repo``, ``url``, ``new``).
    inputs_dir
        Directory of curated repo group CSVs used to flag which candidates
        are new (checked across every group).
    package_name
        Distribution name on conda-forge/PyPI (e.g. ``openff-toolkit``); used
        in the dependency-file queries.
    import_name
        Python import path (e.g. ``openff.toolkit``); used in the
        import-statement queries.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``repo``, ``url``, and ``new``.
    """
    headers = _get_headers()
    all_repos: dict[str, str] = {}

    for query in _build_queries(package_name, import_name):
        repos = _search(query, headers)
        new_count = sum(1 for k in repos if k not in all_repos)
        all_repos.update(repos)
        print(f"  running total: {len(all_repos)} repos (+{new_count} new)\n")
        time.sleep(2)

    known_df = curated.load_groups(inputs_dir, ["repo"])
    known = set(known_df["repo"].fillna("").astype(str).str.strip().str.lower())

    df = pd.DataFrame(
        [
            {"repo": name, "url": url, "new": name.lower() not in known}
            for name, url in sorted(all_repos.items())
        ]
    )
    if not df.empty:
        df = df.sort_values(["new", "repo"], ascending=[False, True], kind="mergesort")

    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    n_new = int(df["new"].sum()) if not df.empty else 0
    print(f"Saved {len(df)} repos to {output_csv} ({n_new} not yet in {inputs_dir}).")
    print("Review the new rows, then add approved repos to the curated list.")

    return df
