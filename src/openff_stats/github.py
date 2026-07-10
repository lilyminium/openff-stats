"""
GitHub repo tracking: script-generated lists in data/github_repos/ plus a
manual add path.

Each CSV in data/github_repos/ is one group — the filename is the package
the repos import (e.g. openff-toolkit.csv).  Columns: repo, url, status,
notes.  `status` is `manual` (human-added via add-github-repo), `auto`
(passed verification during discovery), or `exclude` (kept in the file for
the record — failed verification or blacklisted — but skipped by
collection).

Workflow:
  openff-stats add-github-repo OWNER/REPO [--group NAME]
                                            → append to data/github_repos/<group>.csv
  openff-stats discover-github-repos [--package X --import-name Y]
                                            → code search + per-file
                                              verification, writes
                                              data/github_repos/<package>.csv
                                              directly (status=auto/exclude,
                                              no human review step).  With no
                                              --package, sweeps every row of
                                              inputs/github_packages.csv.
  openff-stats github-stars                 → star counts + per-group import sums

Discovery uses sharded queries to work around GitHub's hard 1000-result cap on
any single code-search request: when a query returns >= 1000 hits the search
is automatically re-run split across file-size buckets, and the results are
unioned.  Buckets recurse up to depth 2 before giving up on that shard.  Each
resulting candidate repo is then verified against the files that actually
matched (dependency manifests, .py imports, or .ipynb code-cell imports —
see `_verify_repo`) before being tagged auto/exclude.

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

def _build_queries(
    package_name: str,
    import_name: str,
    include_requirements: bool = False,
    search_mode: str = "full",
) -> list[str]:
    """Code-search queries covering the ways a package may appear in a repo.

    Runtime-import queries use *import_name* (e.g. ``openff.toolkit``);
    declared-dependency queries use *package_name* (e.g. ``openff-toolkit``).
    The ``requirements.txt`` query is opt-in: GitHub tokenizes on punctuation,
    so short package names match tens of thousands of hyphenated lookalikes
    (``gradient-descent`` matches a ``descent`` search) and the query mostly
    adds sharded paging time.

    ``search_mode="environment-only"`` restricts the search to conda
    environment files — the last-resort mode for generic package names where
    even the other manifest and import queries are dominated by same-token
    noise (see inputs/github_packages.csv).

    ``search_mode="manifest-yaml-conservative"`` targets generic package names
    by searching YAML files for the conda list syntax (``"- <package>"``) plus
    modern configs (pyproject.toml, pixi.toml), avoiding the noise of
    requirements.txt and Python imports. Covers all YAML file names (not just
    environment.yml / environment.yaml). Verification handles YAML, YML, and
    TOML dependency formats.
    """
    if search_mode == "manifest-yaml-conservative":
        return [
            # YAML list syntax: search specific environment filenames
            f'"- {package_name}" extension:yaml',
            f'"- {package_name}" extension:yml',
            # Modern configs
            f"{package_name} filename:pyproject.toml",
            f"{package_name} filename:pixi.toml",
        ]
    if search_mode == "environment-only":
        return [
            f"{package_name} filename:environment.yml",
            f"{package_name} filename:environment.yaml",
        ]
    queries = [
        # Declared dependencies first: high-precision, cheap to verify
        f"{package_name} filename:setup.cfg",
        f"{package_name} filename:pyproject.toml",
        f"{package_name} filename:environment.yml",
        f"{package_name} filename:setup.py",
        f"{package_name} filename:pixi.toml",
    ]
    if include_requirements:
        queries.append(f"{package_name} filename:requirements.txt")
    queries += [
        # Runtime imports second: noisy for generic import names, verified
        # from search text-match fragments
        f"import {import_name} language:python",
        f"from {import_name} language:python",
        f"import {import_name} extension:ipynb",
        f"from {import_name} extension:ipynb",
    ]
    return queries


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
    inputs_dir: str = "data/github_repos",
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
            # text-match fragments let candidates be verified without
            # fetching each matched file
            headers={**headers, "Accept": "application/vnd.github.text-match+json"},
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
            wait = min(max(reset_at - time.time(), 0) + 3, 120)  # cap: bogus reset stamps must not sleep for hours
            print(f"    Rate limited — sleeping {wait:.0f}s …")
            time.sleep(wait)
            continue

        if r.status_code == 408:
            print(f"    Timeout — retrying in 10s …")
            time.sleep(10)
            continue

        r.raise_for_status()
        return r.json()


def _merge_repos(base: dict[str, dict], extra: dict[str, dict]) -> None:
    """Merge *extra*'s ``{full_name: {"url", "paths"}}`` info into *base*, in place.

    Parameters
    ----------
    base
        Mapping to merge into; mutated in place.
    extra
        Mapping of the same shape to merge from.
    """
    for full_name, info in extra.items():
        entry = base.setdefault(full_name, {"url": info["url"], "paths": {}})
        for path, path_info in info["paths"].items():
            existing = entry["paths"].setdefault(path, {"url": path_info["url"], "fragments": []})
            existing["fragments"].extend(path_info["fragments"])


def _fetch_all_pages(
    query: str,
    headers: dict[str, str],
) -> tuple[dict[str, dict], int]:
    """Exhaust all pages for a query (maximum 1 000 results from the API).

    Parameters
    ----------
    query
        GitHub code-search query string.
    headers
        Request headers including the auth token.

    Returns
    -------
    tuple[dict[str, dict], int]
        Mapping of ``{full_name: {"url": html_url, "paths": {path: contents_api_url}}}``
        and the ``total_count`` reported by the API for the first page.
    """
    repos: dict[str, dict] = {}
    total_count = 0

    for page in range(1, 11):  # 10 pages × 100 results = 1 000 max
        data = _gh_search(query, page, headers)
        items = data.get("items", [])

        if page == 1:
            total_count = data.get("total_count", 0)

        for item in items:
            repo = item["repository"]
            entry = repos.setdefault(repo["full_name"], {"url": repo["html_url"], "paths": {}})
            fragments = [m.get("fragment", "") for m in item.get("text_matches", [])]
            path_entry = entry["paths"].setdefault(item["path"], {"url": item["url"], "fragments": []})
            path_entry["fragments"].extend(fragments)

        if len(items) < 100:
            break

        time.sleep(2)  # stay well clear of secondary rate limits

    return repos, total_count


def _search(
    query: str,
    headers: dict[str, str],
    depth: int = 0,
) -> dict[str, dict]:
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
    dict[str, dict]
        Mapping of ``{full_name: {"url": html_url, "paths": {...}}}`` for
        every matching repo found.
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
    all_repos: dict[str, dict] = {}
    _merge_repos(all_repos, repos)
    for bucket in _SIZE_BUCKETS:
        sub = _search(f"{query} size:{bucket}", headers, depth=depth + 1)
        _merge_repos(all_repos, sub)
        time.sleep(1)

    return all_repos


def load_owner_blacklist(path: str = "inputs/github_owner_blacklist.csv") -> dict[str, str]:
    """Load the owner blacklist as ``{owner_lowercase: reason}``.

    Parameters
    ----------
    path
        CSV with columns ``owner``, ``reason``.
    """
    df = pd.read_csv(path)
    return {
        str(owner).strip().lower(): str(reason) for owner, reason in zip(df["owner"], df["reason"])
    }


def classify_repos(df: pd.DataFrame, blacklist: dict[str, str]) -> pd.DataFrame:
    """Tag each repo ``external``/``reason`` based on whether its owner is blacklisted.

    Repos owned by the OpenFF org/maintainers (self) or by conda-forge (meta,
    packaging) are excluded from external-adoption counts via ``external=False``.

    Parameters
    ----------
    df
        DataFrame with a ``repo`` column (``owner/name``).
    blacklist
        Mapping of ``{owner_lowercase: reason}``, e.g. from `load_owner_blacklist`.

    Returns
    -------
    pd.DataFrame
        *df* with ``external`` (bool) and ``reason`` (str, ``""`` when external) columns added.
    """
    df = df.copy()
    owners = df["repo"].astype(str).str.split("/", n=1).str[0].str.lower()
    reasons = owners.map(blacklist)
    df["external"] = reasons.isna()
    df["reason"] = reasons.fillna("")
    return df


def apply_fork_rule(df: pd.DataFrame, group_priority: list[str] | None = None) -> pd.DataFrame:
    """Invalidate cross-group duplicates and forks of higher-starred repos.

    Two passes, neither of which touches rows that are already external=False
    (their ``self``/``meta``/... reason is left alone):

    1. **Duplicates** — the same repo listed in more than one group only
       counts once: the row in the highest-priority group (the order of
       *group_priority*, e.g. the row order of inputs/github_packages.csv;
       file order when not given) keeps its external status, every other row
       becomes ``external=False``, ``reason="duplicate"``.
    2. **Forks** — among the remaining one-row-per-repo set, repos are
       grouped by fork family (``fork_of`` for forks, else the repo's own
       name).  The member with the highest star count keeps its existing
       ``external``/``reason``; every other member is set ``external=False``,
       ``reason="fork"``.  A fork whose family has no other tracked member
       is left as-is.

    Parameters
    ----------
    df
        DataFrame with ``group``, ``repo``, ``fork_of``, ``stars``,
        ``external``, and ``reason`` columns (as produced by
        `collect_repo_stars`).
    group_priority
        Group names in decreasing priority, deciding which group keeps a
        duplicated repo.

    Returns
    -------
    pd.DataFrame
        *df* with ``external``/``reason`` updated for demoted rows.
    """
    df = df.copy()

    if group_priority:
        priority = {g: i for i, g in enumerate(group_priority)}
        rank = df["group"].map(lambda g: priority.get(g, len(priority)))
        order = rank.sort_values(kind="mergesort").index
    else:
        order = df.index

    primary_rows: dict[str, int] = {}
    for idx in order:
        key = str(df.at[idx, "repo"]).lower()
        if key in primary_rows:
            if df.at[idx, "external"]:
                df.at[idx, "external"] = False
                df.at[idx, "reason"] = "duplicate"
        else:
            primary_rows[key] = idx

    primary = df.loc[list(primary_rows.values())]
    fork_of = primary["fork_of"].fillna("").astype(str)
    family = fork_of.where(fork_of != "", primary["repo"]).str.lower()
    winners = set(primary.groupby(family)["stars"].idxmax())
    for idx in primary.index:
        if idx in winners or not df.at[idx, "external"]:
            continue
        df.at[idx, "external"] = False
        df.at[idx, "reason"] = "fork"
    return df


def collect_repo_stars(inputs_dir: str, output_csv: str) -> pd.DataFrame:
    """Fetch star counts for every curated repo via the GitHub Repos API.

    Makes one request per repo to fetch star counts and fork information.
    Also checks for the presence of ``setup.py`` or ``pyproject.toml`` in each
    repo during the same loop and records a ``has_python_config`` column
    (True if either file exists). Classifies each repo's owner against
    `load_owner_blacklist` — ``external=False`` marks self-owned (OpenFF
    org/maintainers) or packaging (conda-forge) repos — then applies
    `apply_fork_rule` so only the highest-starred member of a fork family
    counts as external. Both are excluded from external-adoption counts.
    Prints per-group sums (the group = which package the repos import, so
    the repo count per group is the "GitHub repo imports" number).

    Requires the ``GITHUB_TOKEN`` environment variable.

    Parameters
    ----------
    inputs_dir
        Directory of curated repo group CSVs (a single CSV also works).
    output_csv
        Path to write the results CSV (columns: ``group``, ``repo``,
        ``stars``, ``fork_of``, ``has_python_config``, ``external``,
        ``reason``).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``group``, ``repo``, ``stars``, ``fork_of``,
        ``has_python_config``, ``external``, and ``reason``.
    """
    import tqdm

    headers = _get_headers()
    df = load_curated_repos(inputs_dir)
    rows = []

    for _, curated_row in tqdm.tqdm(df.iterrows(), total=len(df), desc="Fetching stars and Python configs"):
        repo = curated_row["repo"]
        url = f"https://api.github.com/repos/{repo}"
        while True:
            r = requests.get(url, headers=headers, timeout=30)
            remaining = int(r.headers.get("X-RateLimit-Remaining", 1))
            reset_at = int(r.headers.get("X-RateLimit-Reset", 0))

            if r.status_code in (403, 429) or remaining == 0:
                wait = min(max(reset_at - time.time(), 0) + 3, 120)  # cap: bogus reset stamps must not sleep for hours
                print(f"\n  Rate limited — sleeping {wait:.0f}s …")
                time.sleep(wait)
                continue

            fork_of = ""
            if r.status_code == 200:
                data = r.json()
                stars = data.get("stargazers_count", 0)
                if data.get("fork"):
                    fork_of = (data.get("source") or {}).get("full_name") or ""
            else:
                stars = 0

            # Check for pyproject.toml or setup.py during the same repo loop
            has_python_config = False
            for filename in ["pyproject.toml", "setup.py"]:
                check_url = f"https://api.github.com/repos/{repo}/contents/{filename}"
                try:
                    check_r = requests.get(check_url, headers=headers, timeout=30)
                    if check_r.status_code == 200:
                        has_python_config = True
                        break
                except Exception:
                    pass
                time.sleep(0.01)  # modest rate limiting for each check

            rows.append({
                "group": curated_row["group"],
                "repo": repo,
                "stars": stars,
                "fork_of": fork_of,
                "has_python_config": has_python_config,
            })
            break

        time.sleep(0.05)  # stay clear of secondary rate limits

    result = pd.DataFrame(rows)
    result = classify_repos(result, load_owner_blacklist())
    result = apply_fork_rule(result, group_priority=list(load_github_packages()))
    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False)
    print(f"\nSaved star counts for {len(result)} repos to {output_csv}")
    print("\nGitHub repo imports per group:")
    for group_name, subset in result.groupby("group"):
        n_external = int(subset["external"].sum())
        external_stars = int(subset.loc[subset["external"], "stars"].sum())
        n_with_config = int(subset["has_python_config"].sum())
        print(
            f"  {group_name}: {len(subset)} repos ({n_external} external), "
            f"{int(subset['stars'].sum()):,} stars ({external_stars:,} external) | "
            f"{n_with_config} with Python config"
        )
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
                wait = min(max(reset_at - time.time(), 0) + 3, 120)  # cap: bogus reset stamps must not sleep for hours
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


def load_github_packages(path: str = "inputs/github_packages.csv") -> dict[str, dict]:
    """Load the packages swept by discover-github-repos, with per-package settings.

    Parameters
    ----------
    path
        CSV with columns ``package`` (distribution name), ``import_name``
        (Python import path), and optionally ``search_mode`` — one row per
        package that gets GitHub repo discovery.  ``search_mode`` is ``full``
        (all manifest + import queries; the default when blank/absent) or
        ``environment-only`` (conda environment files only — for packages
        like ``descent`` whose generic name makes every other query drown in
        same-token noise).

    Returns
    -------
    dict[str, dict]
        Mapping of ``{package_name: {"import_name": ..., "search_mode": ...}}``,
        in file order.  Empty if *path* does not exist.
    """
    if not pathlib.Path(path).exists():
        return {}
    df = pd.read_csv(path)
    modes = df["search_mode"] if "search_mode" in df.columns else [""] * len(df)
    return {
        str(pkg).strip(): {
            "import_name": str(imp).strip(),
            "search_mode": (str(mode).strip() or "full") if pd.notna(mode) else "full",
        }
        for pkg, imp, mode in zip(df["package"], df["import_name"], modes)
    }


# Manifest/dependency-declaration filenames checked during verification.
_MANIFEST_BASENAMES = {
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
    "requirements.txt",
    "environment.yml",
    "environment.yaml",
    "pixi.toml",
    "meta.yaml",
}


def _manifest_regex(package_name: str):
    """Compile a regex matching a manifest line that declares *package_name* itself.

    Matches an optional leading YAML-list dash, optional quotes, the package
    name, and an optional version specifier/trailing comma — case-insensitive.
    Rejects lines where the package name is merely a substring of a longer
    token (e.g. a hyphenated sibling package).
    """
    import re

    escaped = re.escape(package_name)
    pattern = rf"""^\s*(-\s*)?["']?{escaped}["']?\s*([=<>!~^ ].*)?[,"']?\s*$"""
    return re.compile(pattern, re.IGNORECASE)


def _fetch_file_text(url: str, headers: dict[str, str]) -> str | None:
    """Fetch a GitHub contents-API URL and return its decoded UTF-8 text, or None.

    Retries automatically on rate-limit responses; returns None for any other
    non-200 status or a body that isn't decodable base64/UTF-8.
    """
    import base64

    while True:
        r = requests.get(url, headers=headers, timeout=30)
        remaining = int(r.headers.get("X-RateLimit-Remaining", 1))
        reset_at = int(r.headers.get("X-RateLimit-Reset", 0))

        if r.status_code in (403, 429) or remaining == 0:
            wait = min(max(reset_at - time.time(), 0) + 3, 120)  # cap: bogus reset stamps must not sleep for hours
            print(f"    Rate limited — sleeping {wait:.0f}s …")
            time.sleep(wait)
            continue
        break

    if r.status_code != 200:
        return None
    try:
        return base64.b64decode(r.json()["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None


def _notebook_has_import(content: str, import_name: str) -> bool:
    """Return True if a notebook's code-cell *source* (not output) imports *import_name*."""
    import json

    try:
        notebook = json.loads(content)
    except Exception:
        return False

    needles = (f"import {import_name}", f"from {import_name}")
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        if any(needle in source for needle in needles):
            return True
    return False


def _toml_has_package(content: str, package_name: str) -> bool:
    """Return True if a TOML file (pyproject.toml, pixi.toml) declares *package_name*.
    
    Searches common dependency sections:
    - [project] dependencies
    - [build-system] requires
    - [tool.poetry.dependencies]
    - [tool.pixi.dependencies]
    - [tool.pixi.pypi-dependencies]
    
    Extracts package names from version specifiers (e.g. "descent>=0.5" → "descent")
    and matches case-insensitively, rejecting substring-only matches.
    """
    try:
        import tomllib
    except ImportError:
        # Python < 3.11
        try:
            import tomli as tomllib
        except ImportError:
            # No TOML parser available; fall back to regex search
            return False
    
    try:
        data = tomllib.loads(content)
    except Exception:
        return False
    
    package_name_lower = package_name.lower()
    
    def extract_package_name(dep_str: str) -> str:
        """Extract package name from a dependency string (e.g. 'descent>=0.5' → 'descent')."""
        dep = str(dep_str).split("[")[0]  # Remove extras
        dep = dep.split(";")[0]  # Remove environment markers
        dep = dep.split(">")[0].split("<")[0].split("=")[0].split("!")[0].split("~")[0].strip()
        return dep.lower()
    
    # Check [project] dependencies (PEP 621)
    project_deps = data.get("project", {}).get("dependencies", [])
    if isinstance(project_deps, list):
        if any(extract_package_name(dep) == package_name_lower for dep in project_deps):
            return True
    
    # Check [build-system] requires
    build_deps = data.get("build-system", {}).get("requires", [])
    if isinstance(build_deps, list):
        if any(extract_package_name(dep) == package_name_lower for dep in build_deps):
            return True
    
    # Check [tool.poetry.dependencies]
    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    if isinstance(poetry_deps, dict):
        if any(str(k).lower() == package_name_lower for k in poetry_deps.keys()):
            return True
    
    # Check [tool.pixi.dependencies]
    pixi_deps = data.get("tool", {}).get("pixi", {}).get("dependencies", {})
    if isinstance(pixi_deps, dict):
        if any(str(k).lower() == package_name_lower for k in pixi_deps.keys()):
            return True
    
    # Check [tool.pixi.pypi-dependencies] (for git installs and PyPI packages)
    pixi_pypi_deps = data.get("tool", {}).get("pixi", {}).get("pypi-dependencies", {})
    if isinstance(pixi_pypi_deps, dict):
        if any(str(k).lower() == package_name_lower for k in pixi_pypi_deps.keys()):
            return True
    
    return False


def _verify_repo(
    package_name: str,
    import_name: str,
    paths: dict[str, str],
    headers: dict[str, str],
) -> tuple[str, str]:
    """Verify a candidate repo against its matched files; return (status, notes).

    Stops at the first positive piece of evidence, checked in order
    (highest-precision first):

    1. Matched dependency-manifest paths (`_MANIFEST_BASENAMES`) are fetched
       and checked line-by-line (inline ``#`` comments stripped first)
       against `_manifest_regex` for *package_name* — this rejects
       substring-only matches like a ``gradient-descent`` line matching a
       ``descent`` search.
    2. Matched ``.py`` / ``.ipynb`` paths are checked against the search's
       text-match fragments for a real ``import <import_name>`` /
       ``from <import_name>`` statement — GitHub's code search matches
       *tokens*, not phrases, so a hit alone is not evidence for generic
       import names.  Fragment checks need no extra requests, and base64
       notebook outputs can never contain the space in ``import x``.
    3. A ``.py`` path that produced no fragments is fetched once and checked
       with the same import regex; ``.ipynb`` likewise via
       `_notebook_has_import` (code-cell *source* only, not cached outputs).

    A repo with no evidence from any matched file is marked ``exclude``.

    Parameters
    ----------
    package_name
        Distribution name to look for in dependency manifests.
    import_name
        Python import path to look for in import statements.
    paths
        Mapping of ``{matched file path: {"url": contents-API URL,
        "fragments": [text-match fragments]}}`` for this repo.
    headers
        Request headers including the auth token.

    Returns
    -------
    tuple[str, str]
        ``(status, notes)`` where ``status`` is ``"auto"`` or ``"exclude"``.
    """
    import re

    manifest_regex = _manifest_regex(package_name)
    # Check files by recognized names OR by YAML extension with "env" in stem
    # (catches non-standard names like conda-env.yaml, env.yaml found by YAML searches)
    manifest_paths = sorted(
        p for p in paths
        if pathlib.PurePosixPath(p).name.lower() in _MANIFEST_BASENAMES
        or (pathlib.PurePosixPath(p).suffix.lower() in (".yaml", ".yml") 
            and "env" in pathlib.PurePosixPath(p).stem.lower())
    )
    for path in manifest_paths:
        # Pre-screen on the search's text-match fragments: only fetch the
        # file when a fragment line already looks like a dependency
        # declaration.  Queries like "descent filename:requirements.txt"
        # match tens of thousands of gradient-descent-style files, and
        # fetching each one would take hours and the whole core API quota.
        fragments = paths[path]["fragments"]
        fragment_hit = any(
            manifest_regex.match(line.split("#", 1)[0])
            for frag in fragments
            for line in frag.splitlines()
        )
        if fragments and not fragment_hit:
            continue
        content = _fetch_file_text(paths[path]["url"], headers)
        time.sleep(0.5)
        if content is None:
            continue
        
        # Check TOML files using TOML parser
        if pathlib.PurePosixPath(path).suffix.lower() == ".toml":
            if _toml_has_package(content, package_name):
                return "auto", f"{package_name} in {path}"
        # Check all other formats (YAML, YML, setup.cfg, requirements.txt, etc.)
        else:
            for line in content.splitlines():
                if manifest_regex.match(line.split("#", 1)[0]):
                    return "auto", f"{package_name} in {path}"

    import_regex = re.compile(
        rf"(^|[^\w.])(import|from)\s+{re.escape(import_name)}\b", re.MULTILINE
    )

    code_paths = sorted(p for p in paths if p.endswith((".py", ".ipynb")))
    for path in code_paths:
        if any(import_regex.search(frag) for frag in paths[path]["fragments"]):
            suffix = " (notebook)" if path.endswith(".ipynb") else ""
            return "auto", f"import in {path}{suffix}"

    # Fallback for hits whose fragments missed the import line: one fetch each
    for path in code_paths:
        if paths[path]["fragments"]:
            continue
        content = _fetch_file_text(paths[path]["url"], headers)
        time.sleep(0.5)
        if content is None:
            continue
        if path.endswith(".py") and import_regex.search(content):
            return "auto", f"import in {path}"
        if path.endswith(".ipynb") and _notebook_has_import(content, import_name):
            return "auto", f"import in {path} (notebook)"

    return "exclude", "no dependency or import evidence"


def discover_github_repos(
    package_name: str = "openff-toolkit",
    import_name: str = "openff.toolkit",
    output_csv: str | None = None,
    include_requirements: bool = False,
    search_mode: str = "full",
) -> pd.DataFrame:
    """Search GitHub for, and verify, repos that import or depend on a package.

    Runs a set of sharded code-search queries and unions the results (repo →
    matched file paths), working around the 1 000-result cap that GitHub
    imposes on any single query.  Each candidate repo is then verified
    against its matched files via `_verify_repo` and tagged ``status=auto``
    or ``status=exclude`` accordingly; excluded rows are kept in the output
    for the record, with a ``notes`` explanation.  Writes directly to
    *output_csv* — there is no candidates/ review step for this command,
    unlike the other ``discover-*`` commands.

    Requires the ``GITHUB_TOKEN`` environment variable.

    Parameters
    ----------
    package_name
        Distribution name on conda-forge/PyPI (e.g. ``openff-toolkit``); used
        in the dependency-file queries and manifest verification.
    import_name
        Python import path (e.g. ``openff.toolkit``); used in the
        import-statement queries and notebook verification.
    output_csv
        Path to write the repos CSV (columns: ``repo``, ``url``, ``status``,
        ``notes``).  Defaults to ``data/github_repos/<package_name>.csv``.
    include_requirements
        Also search ``requirements.txt`` files.  Off by default — see
        `_build_queries` for why this query is mostly sharded paging time.
    search_mode
        ``full`` (default) or ``environment-only`` (conda environment files
        only; for generic package names — see `_build_queries`).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``repo``, ``url``, ``status``, and ``notes``.
    """
    if output_csv is None:
        output_csv = f"data/github_repos/{package_name}.csv"

    headers = _get_headers()
    all_repos: dict[str, dict] = {}

    for query in _build_queries(package_name, import_name, include_requirements, search_mode):
        try:
            if query.startswith(("import ", "from ")):
                # Import queries on generic names can report hundreds of
                # thousands of token matches (e.g. gradient descent code for
                # an ``import descent`` search); sharding those exhaustively
                # is pure paging cost.  Results are relevance-ranked, so the
                # top 1 000 hold the real import statements — fragments
                # filter the rest for free.
                repos, total = _fetch_all_pages(query, headers)
                flag = "⚠ " if total >= 800 else "✓ "
                print(f"  {flag}[{total:>6}] {query} (top 1000, unsharded)")
            else:
                repos = _search(query, headers)
        except Exception as exc:
            print(f"  Warning: query failed, skipping ({query!r}): {exc}")
            continue
        new_count = sum(1 for k in repos if k not in all_repos)
        _merge_repos(all_repos, repos)
        print(f"  running total: {len(all_repos)} repos (+{new_count} new)\n")
        time.sleep(2)

    print(f"\nVerifying {len(all_repos)} candidate repo(s) against matched files …")
    rows = []
    for full_name, info in sorted(all_repos.items()):
        try:
            status, notes = _verify_repo(package_name, import_name, info["paths"], headers)
        except Exception as exc:
            print(f"  Warning: verification failed for {full_name}: {exc}")
            status, notes = "exclude", f"verification error: {exc}"
        rows.append({"repo": full_name, "url": info["url"], "status": status, "notes": notes})

    df = pd.DataFrame(rows, columns=["repo", "url", "status", "notes"])
    if not df.empty:
        status_rank = df["status"].map({"auto": 0, "exclude": 1}).fillna(2).astype(int)
        repo_lower = df["repo"].str.lower()
        df = (
            df.assign(_status_rank=status_rank, _repo_lower=repo_lower)
            .sort_values(["_status_rank", "_repo_lower"], kind="mergesort")
            .drop(columns=["_status_rank", "_repo_lower"])
            .reset_index(drop=True)
        )

    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    n_auto = int((df["status"] == "auto").sum()) if not df.empty else 0
    n_exclude = int((df["status"] == "exclude").sum()) if not df.empty else 0
    print(f"\nSaved {len(df)} repos to {output_csv} ({n_auto} auto, {n_exclude} exclude).")

    return df
