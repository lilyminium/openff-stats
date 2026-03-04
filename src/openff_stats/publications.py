"""
Publication discovery and citation count collection.

Workflow:
  1. discover-publications --orcid XXXX ...
       → queries ORCID + Crossref + ChemRxiv, outputs a candidates CSV for human review
  2. (human edits inputs/publications.csv to verify the list)
  3. citations --input inputs/publications.csv --output data/citations.csv
       → queries Scholar, Crossref, ChemRxiv for each paper, writes citation counts

inputs/publications.csv columns:
  DOI, title, scholar_cluster_id, chemrxiv_id
  (scholar_cluster_id and chemrxiv_id may be blank if not applicable)
"""

from __future__ import annotations

import re
import time
import pathlib

import pandas as pd
import requests
import tqdm

CROSSREF_BASE = "https://api.crossref.org/works"
ORCID_BASE = "https://pub.orcid.org/v3.0"
CHEMRXIV_BASE = "https://chemrxiv.org/engage/chemrxiv/public-api/v1"

# Used in Crossref polite pool requests
MAILTO = "openff-stats@example.com"


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _get_orcid_dois(orcid: str) -> list[str]:
    """Return all DOIs associated with an ORCID profile."""
    url = f"{ORCID_BASE}/{orcid}/works"
    headers = {"Accept": "application/json"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()

    dois: list[str] = []
    for group in data.get("group", []):
        for summary in group.get("work-summary", []):
            for ext_id in summary.get("external-ids", {}).get("external-id", []):
                if ext_id.get("external-id-type") == "doi":
                    val = ext_id.get("external-id-value", "").strip()
                    if val:
                        dois.append(val)
    return dois


def _get_crossref_metadata(doi: str) -> dict | None:
    """Fetch title, authors, year, and citation count from Crossref for a DOI."""
    url = f"{CROSSREF_BASE}/{doi}?mailto={MAILTO}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        msg = response.json()["message"]

        title_list = msg.get("title", [])
        title = title_list[0] if title_list else ""

        authors = []
        for author in msg.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            authors.append(f"{given} {family}".strip())

        year = None
        published = msg.get("published-print") or msg.get("published-online") or msg.get("published")
        if published:
            date_parts = published.get("date-parts", [[]])[0]
            if date_parts:
                year = date_parts[0]

        return {
            "title": title,
            "authors": "; ".join(authors),
            "year": year,
        }
    except Exception as exc:
        print(f"  Warning: Crossref lookup failed for {doi}: {exc}")
        return None


def _search_chemrxiv_by_title(title: str) -> str | None:
    """Try to find a ChemRxiv record ID by searching for a title."""
    url = f"{CHEMRXIV_BASE}/items"
    params = {"term": title, "limit": 5}
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        hits = response.json().get("itemHits", [])
        for hit in hits:
            item = hit.get("item", {})
            item_title = item.get("title", "")
            # Simple heuristic: first 40 chars match (case-insensitive)
            if title[:40].lower() in item_title.lower():
                return item.get("id") or item.get("itemId")
    except Exception:
        pass
    return None


def _search_scholar_cluster(title: str) -> str | None:
    """Try to find a Google Scholar cluster ID by searching for a title."""
    query = "+".join(title.split()[:8])
    url = f"https://scholar.google.com/scholar?q={query}&hl=en"
    try:
        response = requests.get(url, timeout=30)
        # Look for a cites=NNNNN pattern indicating the cluster ID
        match = re.search(r'cites=(\d+)', response.text)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def discover_publications(orcids: list[str], output_file: str) -> pd.DataFrame:
    """Discover publications for a list of ORCID IDs.

    Queries ORCID for all works, fetches metadata from Crossref, and
    attempts to match ChemRxiv preprints and Google Scholar cluster IDs.
    Writes a candidates CSV for human review.

    Parameters
    ----------
    orcids
        List of ORCID identifiers (e.g. "0000-0002-1544-1476").
    output_file
        Path to write the candidates CSV.
    """
    print(f"Querying ORCID for {len(orcids)} author(s) ...")

    # Collect DOIs per ORCID, tracking which ORCID each came from
    doi_to_orcids: dict[str, list[str]] = {}
    for orcid in orcids:
        print(f"  {orcid} ...")
        try:
            dois = _get_orcid_dois(orcid)
            for doi in dois:
                doi_upper = doi.upper()
                doi_to_orcids.setdefault(doi_upper, []).append(orcid)
        except Exception as exc:
            print(f"  Warning: ORCID query failed for {orcid}: {exc}")

    print(f"\nFound {len(doi_to_orcids)} unique DOIs across all authors.")
    print("Fetching Crossref metadata ...")

    rows: list[dict] = []
    for doi_upper, source_orcids in tqdm.tqdm(doi_to_orcids.items()):
        meta = _get_crossref_metadata(doi_upper)
        if meta is None:
            continue

        # Best-effort: look for ChemRxiv preprint
        chemrxiv_id = _search_chemrxiv_by_title(meta["title"])
        # Best-effort: look for Scholar cluster ID (slow, may fail)
        scholar_cluster_id = None  # skip during discovery to avoid blocking

        rows.append({
            "DOI": doi_upper,
            "title": meta["title"],
            "authors": meta["authors"],
            "year": meta["year"],
            "scholar_cluster_id": scholar_cluster_id or "",
            "chemrxiv_id": chemrxiv_id or "",
            "source_orcids": "; ".join(source_orcids),
        })

        time.sleep(0.1)  # polite rate limiting

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("year", ascending=False)

    pathlib.Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False)

    print(f"\nWrote {len(df)} candidate publications to {output_file}")
    print(
        "NOTE: Not all papers will be OpenFF-related.\n"
        "Review this file and save only verified OpenFF entries to inputs/publications.csv\n"
        "(keep or fill in scholar_cluster_id and chemrxiv_id columns as needed)."
    )
    return df


# ---------------------------------------------------------------------------
# Citation collection helpers
# ---------------------------------------------------------------------------

def get_crossref_citations(doi: str) -> int | None:
    """Return the Crossref 'is-referenced-by-count' for a DOI."""
    url = f"{CROSSREF_BASE}/{doi}?mailto={MAILTO}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()["message"]["is-referenced-by-count"]
    except Exception as exc:
        print(f"  Warning: Crossref citation lookup failed for {doi}: {exc}")
        return None


def get_scholar_citations(cluster_id: str) -> int | None:
    """Return Google Scholar citation count for a cluster ID.

    Uses raw HTTP scraping (fragile; may fail due to CAPTCHAs).
    Returns None on any failure instead of raising.
    """
    url = (
        f"https://scholar.google.com/scholar"
        f"?cluster={cluster_id}&as_sdt=2005&sciodt=0,5&hl=en"
    )
    try:
        response = requests.get(url, timeout=30)
        pattern = f"cites={cluster_id}" + r'[0-9a-zA-Z&;,=_]+">Cited by '
        parts = re.split(pattern, response.text)
        if len(parts) < 2:
            return None
        match = re.match(r"\d+", parts[1])
        if match:
            return int(match.group(0))
    except Exception as exc:
        print(f"  Warning: Scholar scrape failed for cluster {cluster_id}: {exc}")
    return None


def get_chemrxiv_metrics(record_id: str) -> dict:
    """Return ChemRxiv metrics dict for a record ID.

    Keys are metric descriptions (e.g. 'Abstract Views', 'Citations',
    'Content Downloads'). Returns empty dict on failure.
    """
    url = f"{CHEMRXIV_BASE}/items/{record_id}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        metrics_list = response.json().get("metrics", [])
        return {item["description"]: item["value"] for item in metrics_list}
    except Exception as exc:
        print(f"  Warning: ChemRxiv metrics failed for {record_id}: {exc}")
        return {}


def collect_all_citations(input_csv: str, output_csv: str) -> None:
    """Collect citation counts for all papers in the input CSV.

    Reads inputs/publications.csv (columns: DOI, title, scholar_cluster_id,
    chemrxiv_id) and writes data/citations.csv with per-source citation counts.

    Parameters
    ----------
    input_csv
        Path to the curated publications CSV.
    output_csv
        Path for the citations output CSV.
    """
    df = pd.read_csv(input_csv)

    crossref_citations: list[int | None] = []
    scholar_citations: list[int | None] = []
    chemrxiv_views: list[int | None] = []
    chemrxiv_downloads: list[int | None] = []
    chemrxiv_citations: list[int | None] = []

    for _, row in tqdm.tqdm(df.iterrows(), total=len(df), desc="Publications"):
        doi = str(row.get("DOI", "")).strip()
        scholar_id = str(row.get("scholar_cluster_id", "")).strip()
        chemrxiv_id = str(row.get("chemrxiv_id", "")).strip()

        # Crossref
        crossref_citations.append(get_crossref_citations(doi) if doi else None)
        time.sleep(0.1)

        # Google Scholar
        if scholar_id and scholar_id.lower() not in ("", "nan"):
            scholar_citations.append(get_scholar_citations(scholar_id))
            time.sleep(1.0)  # Scholar needs more breathing room
        else:
            scholar_citations.append(None)

        # ChemRxiv
        if chemrxiv_id and chemrxiv_id.lower() not in ("", "nan"):
            metrics = get_chemrxiv_metrics(chemrxiv_id)
            chemrxiv_views.append(metrics.get("Abstract Views"))
            chemrxiv_downloads.append(metrics.get("Content Downloads"))
            chemrxiv_citations.append(metrics.get("Citations"))
            time.sleep(0.1)
        else:
            chemrxiv_views.append(None)
            chemrxiv_downloads.append(None)
            chemrxiv_citations.append(None)

    df["crossref_citations"] = crossref_citations
    df["scholar_citations"] = scholar_citations
    df["chemrxiv_views"] = chemrxiv_views
    df["chemrxiv_downloads"] = chemrxiv_downloads
    df["chemrxiv_citations"] = chemrxiv_citations

    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"\nSaved citation counts to {output_csv}")

    def _sum(col: list) -> int:
        return sum(x for x in col if x is not None)

    print(f"Total Crossref citations:    {_sum(crossref_citations)}")
    print(f"Total Scholar citations:     {_sum(scholar_citations)}")
    print(f"Total ChemRxiv views:        {_sum(chemrxiv_views)}")
    print(f"Total ChemRxiv downloads:    {_sum(chemrxiv_downloads)}")
    print(f"Total ChemRxiv citations:    {_sum(chemrxiv_citations)}")
