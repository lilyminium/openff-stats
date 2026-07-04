"""
Zenodo record curation and DataCite citation count collection.

The curated list is inputs/zenodo.csv; maintain it with:
  openff-stats add-zenodo ID_OR_DOI
       → fetches record metadata from the Zenodo API, appends a row

Collection:
  openff-stats zenodo-citations
       → queries DataCite for citation counts, writes data/zenodo_citations.csv

Optional bulk discovery (candidates/ for human review):
  openff-stats discover-zenodo

inputs/zenodo.csv columns:
  zenodo_id, doi, title, creators, publication_year, resource_type
"""

import pathlib
import time

import pandas as pd
import requests
import tqdm

from openff_stats import curated

ZENODO_BASE = "https://zenodo.org/api"
DATACITE_BASE = "https://api.datacite.org/dois"


def _record_to_row(hit: dict) -> dict:
    """Build an inputs/zenodo.csv row from a Zenodo API record."""
    meta = hit.get("metadata", {})
    creators = meta.get("creators", [])
    creator_names = "; ".join(
        c.get("name", "") or f"{c.get('given', '')} {c.get('family', '')}".strip()
        for c in creators
    )
    return {
        "zenodo_id": hit.get("id", ""),
        "doi": hit.get("doi") or meta.get("doi", ""),
        "title": meta.get("title", ""),
        "creators": creator_names,
        "publication_year": meta.get("publication_date", "")[:4] if meta.get("publication_date") else "",
        "resource_type": meta.get("resource_type", {}).get("type", ""),
    }


def _parse_zenodo_id(id_or_doi: str) -> str:
    """Extract the numeric record ID from an ID, DOI, or zenodo.org URL."""
    import re

    value = str(id_or_doi).strip()
    if value.isdigit():
        return value
    match = re.search(r"zenodo[./](\d+)$", value, flags=re.IGNORECASE) or re.search(
        r"records?/(\d+)", value
    )
    if match:
        return match.group(1)
    raise ValueError(
        f"Could not parse a Zenodo record ID from {id_or_doi!r}; expected a "
        "numeric ID, a 10.5281/zenodo.NNN DOI, or a zenodo.org record URL."
    )


def add_zenodo_record(id_or_doi: str, inputs_csv: str = "inputs/zenodo.csv") -> None:
    """Add a Zenodo record to the curated CSV via the Zenodo API.

    Parameters
    ----------
    id_or_doi
        Numeric record ID, Zenodo DOI (10.5281/zenodo.NNN), or record URL.
    inputs_csv
        Path to the curated Zenodo CSV.
    """
    record_id = _parse_zenodo_id(id_or_doi)
    response = requests.get(f"{ZENODO_BASE}/records/{record_id}", timeout=60)
    if response.status_code == 404:
        raise ValueError(f"Zenodo record not found: {record_id}")
    response.raise_for_status()
    row = _record_to_row(response.json())
    print(f"{row['zenodo_id']}: {row['title']} ({row['resource_type']}, {row['publication_year']})")

    df = curated.load(inputs_csv, list(row))
    if (df["zenodo_id"].fillna("").astype(str).str.strip() == str(row["zenodo_id"])).any():
        print(f"Record already present, no changes made: {row['zenodo_id']}")
        return

    df = curated.append_row(df, row)
    df["_year_sort"] = pd.to_numeric(df["publication_year"], errors="coerce")
    df = df.sort_values(
        "_year_sort", ascending=False, na_position="last", kind="mergesort"
    ).drop(columns="_year_sort")
    curated.save(df, inputs_csv)
    print(f"Added record {row['zenodo_id']} to {inputs_csv}")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _search_zenodo(base_params: dict, max_records: int = 400) -> list[dict]:
    """Execute a Zenodo search with pagination."""
    url = f"{ZENODO_BASE}/records"
    # Zenodo unauthenticated requests currently allow max page size of 25.
    size = 25
    page = 1
    results: list[dict] = []

    while len(results) < max_records:
        params = {**base_params, "size": size, "page": page, "sort": "newest"}
        try:
            response = requests.get(url, params=params, timeout=60)
            response.raise_for_status()
        except Exception as exc:
            print(f"  Warning: Zenodo search failed ({params}): {exc}")
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

    rows = [_record_to_row(hit) for hit in hits_by_doi.values()]

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
