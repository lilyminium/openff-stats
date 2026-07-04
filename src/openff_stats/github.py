"""
GitHub code search for repositories that import or depend on openff.toolkit.

Uses sharded queries to work around GitHub's hard 1000-result cap on any
single code-search request: when a query returns >= 1000 hits the search is
automatically re-run split across file-size buckets, and the results are
unioned.  Buckets recurse up to depth 2 before giving up on that shard.

Requires the GITHUB_TOKEN environment variable (a personal access token with
at least public_repo / read access).  The GitHub code search endpoint requires
authentication — unauthenticated requests receive a 401 Unauthorized error.

Workflow:
  openff-stats github-repos  → searches GitHub, writes data/github_repos.csv
"""

import os
import pathlib
import time

import pandas as pd
import requests

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

# Each entry covers a different way the toolkit may appear in a repo.
_BASE_QUERIES = [
    # Runtime imports
    "import openff.toolkit language:python",
    "from openff.toolkit language:python",
    "import openff.toolkit extension:ipynb",
    "from openff.toolkit extension:ipynb",
    # Declared dependencies
    "openff-toolkit filename:setup.cfg",
    "openff-toolkit filename:pyproject.toml",
    "openff-toolkit filename:requirements.txt",
    "openff-toolkit filename:environment.yml",
    "openff-toolkit filename:setup.py",
]


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


def collect_repo_stars(repos_csv: str, output_csv: str) -> pd.DataFrame:
    """Fetch star counts for every repo in *repos_csv* via the GitHub Repos API.

    Makes one request per repo.  Skips repos that return a non-200 status
    (private, deleted, or renamed) and records stars=0 for them.

    Requires the ``GITHUB_TOKEN`` environment variable.

    Parameters
    ----------
    repos_csv
        Path to the GitHub repos CSV (columns: ``repo``, ``url``).
    output_csv
        Path to write the results CSV (columns: ``repo``, ``stars``).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``repo`` and ``stars``.
    """
    import tqdm

    headers = _get_headers()
    df = pd.read_csv(repos_csv)
    rows = []

    for repo in tqdm.tqdm(df["repo"], desc="Fetching stars"):
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
            rows.append({"repo": repo, "stars": stars})
            break

        time.sleep(0.05)  # stay clear of secondary rate limits

    result = pd.DataFrame(rows)
    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False)
    print(f"\nSaved star counts for {len(result)} repos to {output_csv}")
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
    - Auto-classifies into a topic category that the user can edit before replotting.

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

    repos_df = pd.read_csv(repos_csv)
    stars_df = pd.read_csv(stars_csv)
    merged = repos_df.merge(stars_df, on="repo", how="left")
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
    print("Review and edit the 'category' column before replotting.")
    return df


def collect_github_repos(output_csv: str) -> pd.DataFrame:
    """Search GitHub for repositories that import or depend on openff.toolkit.

    Runs a set of sharded code-search queries and unions the results, working
    around the 1 000-result cap that GitHub imposes on any single query.

    Requires the ``GITHUB_TOKEN`` environment variable.

    Parameters
    ----------
    output_csv
        Path to write the results CSV (columns: ``repo``, ``url``).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``repo`` and ``url``, one row per unique repo.
    """
    headers = _get_headers()
    all_repos: dict[str, str] = {}

    for query in _BASE_QUERIES:
        repos = _search(query, headers)
        new_count = sum(1 for k in repos if k not in all_repos)
        all_repos.update(repos)
        print(f"  running total: {len(all_repos)} repos (+{new_count} new)\n")
        time.sleep(2)

    df = pd.DataFrame(
        [{"repo": name, "url": url} for name, url in sorted(all_repos.items())]
    )

    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"Saved {len(df)} repos to {output_csv}")

    return df
