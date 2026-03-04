"""
Zenodo record discovery and DataCite citation count collection.

Workflow:
  1. discover-zenodo
       → searches Zenodo for OpenFF records, outputs a candidates CSV for human review
  2. (human edits inputs/zenodo.csv to verify the list)
  3. zenodo-citations --input inputs/zenodo.csv --output data/zenodo_citations.csv
       → queries DataCite for citation counts, writes CSV

inputs/zenodo.csv columns:
  zenodo_id, doi, title
"""

from __future__ import annotations

import pathlib
import time

import pandas as pd
import requests
import tqdm

ZENODO_BASE = "https://zenodo.org/api"
DATACITE_BASE = "https://api.datacite.org/dois"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _search_zenodo(base_params: dict, max_records: int = 400) -> list[dict]:
    """Execute a Zenodo search with pagination and API-compatibility fallbacks."""
    url = f"{ZENODO_BASE}/records"
    # Zenodo unauthenticated requests currently allow max page size of 25.
    size = 25
    page = 1
    results: list[dict] = []

    while len(results) < max_records:
        params_with_page = {**base_params, "size": size, "page": page}
        attempts = [
            {**params_with_page, "sort": "newest"},
            {**params_with_page, "sort": "mostrecent"},
            params_with_page,
        ]

        response = None
        last_error: Exception | None = None
        for params in attempts:
            try:
                candidate = requests.get(url, params=params, timeout=60)
                candidate.raise_for_status()
                response = candidate
                break
            except Exception as exc:
                last_error = exc

        if response is None:
            print(f"  Warning: Zenodo search failed ({params_with_page}): {last_error}")
            break

        page_hits = response.json().get("hits", {}).get("hits", [])
        if not page_hits:
            break

        results.extend(page_hits)
        if len(page_hits) < size:
            break
        page += 1

    return results[:max_records]


def discover_zenodo(output_file: str) -> pd.DataFrame:
    """Search Zenodo for OpenFF-related records and write a candidates CSV.

    Searches two ways:
      1. The openforcefield community
      2. Free-text query for "openff" or "open force field"

    Deduplicates by DOI. Writes a candidates CSV for human review.

    Parameters
    ----------
    output_file
        Path to write the candidates CSV.
    """
    print("Searching Zenodo for OpenFF records ...")

    hits_by_doi: dict[str, dict] = {}

    # 1. Community-focused search
    community_hits = _search_zenodo({"communities": "openforcefield"})
    print(f"  openforcefield community: {len(community_hits)} records")
    for hit in community_hits:
        doi = hit.get("doi") or hit.get("metadata", {}).get("doi", "")
        if doi:
            hits_by_doi[doi] = hit

    # 2. Free-text search
    for query in ["openff", '"open force field"', "openforcefield"]:
        freetext_hits = _search_zenodo({"q": query})
        print(f"  query '{query}': {len(freetext_hits)} records")
        for hit in freetext_hits:
            doi = hit.get("doi") or hit.get("metadata", {}).get("doi", "")
            if doi and doi not in hits_by_doi:
                hits_by_doi[doi] = hit

    print(f"\n{len(hits_by_doi)} unique records found (by DOI).")

    rows: list[dict] = []
    for doi, hit in hits_by_doi.items():
        meta = hit.get("metadata", {})
        record_id = hit.get("id", "")

        creators = meta.get("creators", [])
        creator_names = "; ".join(
            c.get("name", "") or f"{c.get('given', '')} {c.get('family', '')}".strip()
            for c in creators
        )

        rows.append({
            "zenodo_id": record_id,
            "doi": doi,
            "title": meta.get("title", ""),
            "creators": creator_names,
            "publication_year": meta.get("publication_date", "")[:4] if meta.get("publication_date") else "",
            "resource_type": meta.get("resource_type", {}).get("type", ""),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("publication_year", ascending=False)

    pathlib.Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False)

    print(f"Wrote {len(df)} candidates to {output_file}")
    print(
        "Review this file and save verified entries to inputs/zenodo.csv\n"
        "(keep zenodo_id, doi, and title columns)."
    )
    return df


# ---------------------------------------------------------------------------
# Citation collection
# ---------------------------------------------------------------------------

def get_datacite_citations(doi: str) -> dict:
    """Query DataCite for citation count and per-year breakdown.

    Parameters
    ----------
    doi
        Full DOI string (e.g. "10.5281/zenodo.1234567").

    Returns
    -------
    dict
        Keys: citation_count (int), citations_over_time (list of {year, total}).
        Returns zeros/empty on failure.
    """
    url = f"{DATACITE_BASE}/{doi}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        attrs = response.json()["data"]["attributes"]
        return {
            "citation_count": attrs.get("citationCount", 0) or 0,
            "citations_over_time": attrs.get("citationsOverTime", []) or [],
        }
    except Exception as exc:
        print(f"  Warning: DataCite lookup failed for {doi}: {exc}")
        return {"citation_count": 0, "citations_over_time": []}


def collect_zenodo_citations(input_csv: str, output_csv: str) -> None:
    """Collect DataCite citation counts for all Zenodo records in the input CSV.

    Reads inputs/zenodo.csv (columns: zenodo_id, doi, title) and writes
    data/zenodo_citations.csv with citation count and per-year columns.

    Parameters
    ----------
    input_csv
        Path to the curated Zenodo CSV.
    output_csv
        Path for the citations output CSV.
    """
    df = pd.read_csv(input_csv)

    citation_counts: list[int] = []
    all_years: set[str] = set()
    yearly_data: list[dict] = []

    for _, row in tqdm.tqdm(df.iterrows(), total=len(df), desc="Zenodo records"):
        doi = str(row.get("doi", "")).strip()
        result = get_datacite_citations(doi) if doi else {"citation_count": 0, "citations_over_time": []}

        citation_counts.append(result["citation_count"])

        per_year: dict[str, int] = {}
        for entry in result["citations_over_time"]:
            yr = str(entry.get("year", ""))
            total = entry.get("total", 0) or 0
            per_year[yr] = total
            all_years.add(yr)
        yearly_data.append(per_year)

        time.sleep(0.1)

    df["citation_count"] = citation_counts

    # Add one column per year (sorted)
    for year in sorted(all_years):
        df[f"citations_{year}"] = [d.get(year, 0) for d in yearly_data]

    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"\nSaved Zenodo citation counts to {output_csv}")
    print(f"Total citations (DataCite): {sum(citation_counts)}")
