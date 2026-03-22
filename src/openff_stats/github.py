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

from __future__ import annotations

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
    "import openff.toolkit language:jupyter-notebook",
    "from openff.toolkit language:jupyter-notebook",
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
    flag = "⚠ " if total >= 1000 else "✓ "
    print(f"  {pad}{flag}[{total:>6}] {query}")

    if total < 1000 or depth >= 2:
        if depth >= 2 and total >= 1000:
            print(
                f"  {pad}  still at cap after 2 levels of sharding — "
                f"returning best-effort {len(repos)} repos for this shard"
            )
        return repos

    # Shard by file size and recurse
    print(f"  {pad}  → sharding into {len(_SIZE_BUCKETS)} size buckets …")
    all_repos = dict(repos)
    for bucket in _SIZE_BUCKETS:
        sub = _search(f"{query} size:{bucket}", headers, depth=depth + 1)
        all_repos.update(sub)
        time.sleep(1)

    return all_repos


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
