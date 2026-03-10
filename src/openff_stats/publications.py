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

from difflib import SequenceMatcher
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
# Selenium driver for Google Scholar (lazy-initialized, shared across calls)
# ---------------------------------------------------------------------------

_scholar_driver = None


def _get_scholar_driver():
    """Get or create a shared headless Firefox driver for Scholar scraping."""
    global _scholar_driver
    if _scholar_driver is None:
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options

        options = Options()
        # Hide automation signals
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference("useAutomationExtension", False)
        # Realistic browser identity
        options.set_preference(
            "general.useragent.override",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) "
            "Gecko/20100101 Firefox/124.0",
        )
        options.set_preference("intl.accept_languages", "en-US, en")

        _scholar_driver = webdriver.Firefox(options=options)
    return _scholar_driver


def close_scholar_driver() -> None:
    """Quit the shared Scholar driver if open."""
    global _scholar_driver
    if _scholar_driver is not None:
        _scholar_driver.quit()
        _scholar_driver = None


def _scholar_get(url: str) -> str | None:
    """Navigate to url with the shared driver and return page source.

    Returns None if a CAPTCHA is detected.
    """
    import random

    driver = _get_scholar_driver()
    driver.get(url)
    time.sleep(random.uniform(1.5, 3.0))
    source = driver.page_source
    lower = source.lower()
    if "unusual traffic" in lower or "captcha" in lower or "recaptcha" in lower:
        print(f"  Warning: CAPTCHA detected at {url}")
        return None
    return source


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
    """Try to find a Google Scholar cluster ID by searching for a title.

    Searches Scholar for the title using Selenium, then extracts the cluster ID
    from the first result's "Cited by" link.
    """
    import urllib.parse

    query = urllib.parse.quote_plus(" ".join(title.split()[:8]))
    url = f"https://scholar.google.com/scholar?q={query}&hl=en"
    try:
        source = _scholar_get(url)
        if source is None:
            return None
        for pattern in (r'cites=(\d+)', r'[?&]cluster=(\d+)'):
            match = re.search(pattern, source)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def _normalize_doi(doi: str) -> str:
    """Return a normalized DOI string without URL prefixes."""
    value = str(doi).strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    return value.upper()


def _normalize_text(value: str) -> str:
    """Return lowercased text with punctuation collapsed to spaces."""
    text = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    return " ".join(text.split())


def _name_variants(name: str) -> list[str]:
    """Return normalized variants for fuzzy name matching."""
    norm = _normalize_text(name)
    if not norm:
        return []

    parts = norm.split()
    variants = {norm}
    if len(parts) >= 2:
        first = parts[0]
        last = parts[-1]
        variants.add(f"{first} {last}")
        variants.add(f"{first[0]} {last}")
    return sorted(variants)


def _max_name_similarity(name_a: str, name_b: str) -> float:
    """Return max pairwise similarity between generated name variants."""
    variants_a = _name_variants(name_a)
    variants_b = _name_variants(name_b)
    if not variants_a or not variants_b:
        return 0.0

    best = 0.0
    for variant_a in variants_a:
        for variant_b in variants_b:
            ratio = SequenceMatcher(None, variant_a, variant_b).ratio()
            if ratio > best:
                best = ratio
    return best


def _title_similarity(title_a: str, title_b: str) -> float:
    """Return similarity score between two titles."""
    norm_a = _normalize_text(title_a)
    norm_b = _normalize_text(title_b)
    if not norm_a or not norm_b:
        return 0.0
    return SequenceMatcher(None, norm_a, norm_b).ratio()


def _authors_match_count(authors_a: str, authors_b: str, threshold: float = 0.86) -> int:
    """Count fuzzy name matches between two semicolon-separated author lists."""
    list_a = [value.strip() for value in str(authors_a).split(";") if value.strip()]
    list_b = [value.strip() for value in str(authors_b).split(";") if value.strip()]
    if not list_a or not list_b:
        return 0

    matched_b: set[int] = set()
    count = 0
    for author_a in list_a:
        best_index = None
        best_score = 0.0
        for index_b, author_b in enumerate(list_b):
            if index_b in matched_b:
                continue
            score = _max_name_similarity(author_a, author_b)
            if score > best_score:
                best_score = score
                best_index = index_b

        if best_index is not None and best_score >= threshold:
            matched_b.add(best_index)
            count += 1

    return count


def _is_preprint_doi(doi: str) -> bool:
    """Heuristic for identifying preprint DOIs."""
    doi_upper = str(doi).upper()
    return (
        "CHEMRXIV" in doi_upper
        or doi_upper.startswith("10.1101/")
        or "ARXIV" in doi_upper
    )


def _extract_preprint_version(doi: str) -> int:
    """Extract a numeric preprint version from DOI suffixes (default: 0)."""
    doi_upper = str(doi).upper()
    patterns = (
        r"/V(\d+)$",
        r"\.V(\d+)$",
        r"-V(\d+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, doi_upper)
        if match:
            return int(match.group(1))
    return 0


def _same_publication_candidate(row_a: pd.Series, row_b: pd.Series) -> bool:
    """Return True if rows look like duplicate versions of the same publication."""
    title_score = _title_similarity(row_a.get("title", ""), row_b.get("title", ""))
    if title_score >= 0.93:
        return True

    if title_score < 0.78:
        return False

    author_matches = _authors_match_count(
        row_a.get("authors", ""),
        row_b.get("authors", ""),
        threshold=0.86,
    )
    return author_matches >= 2


def _choose_preferred_record(group: pd.DataFrame) -> pd.Series:
    """Pick the best record among duplicate versions of the same publication."""
    candidates = group.copy()
    candidates["is_preprint"] = candidates["DOI"].apply(_is_preprint_doi)
    candidates["preprint_version"] = candidates["DOI"].apply(_extract_preprint_version)
    candidates["year_numeric"] = pd.to_numeric(candidates["year"], errors="coerce").fillna(0)

    published = candidates[~candidates["is_preprint"]]
    if not published.empty:
        sorted_rows = published.sort_values(["year_numeric"], ascending=[False])
        return sorted_rows.iloc[0]

    sorted_rows = candidates.sort_values(
        ["preprint_version", "year_numeric"],
        ascending=[False, False],
    )
    return sorted_rows.iloc[0]


def _deduplicate_publications(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate preprint/published variants, keeping preferred records."""
    if df.empty:
        return df

    assigned = [False] * len(df)
    groups: list[list[int]] = []

    for i in range(len(df)):
        if assigned[i]:
            continue

        group = [i]
        assigned[i] = True

        for j in range(i + 1, len(df)):
            if assigned[j]:
                continue
            if _same_publication_candidate(df.iloc[i], df.iloc[j]):
                group.append(j)
                assigned[j] = True

        groups.append(group)

    selected_rows = []
    for group in groups:
        group_df = df.iloc[group]
        preferred = _choose_preferred_record(group_df)
        selected_rows.append(preferred.drop(labels=["is_preprint", "preprint_version", "year_numeric"], errors="ignore"))

    deduped = pd.DataFrame(selected_rows).reset_index(drop=True)
    dropped_count = len(df) - len(deduped)
    if dropped_count > 0:
        print(f"Deduplicated {dropped_count} likely duplicate preprint/publication record(s).")

    return deduped


def discover_publications(
    orcids: list[str],
    output_file: str,
    author_names: list[str] | None = None,
) -> pd.DataFrame:
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
    author_names
        Optional list of author names to match against in the results.
        Publications will be sorted by the number of authors that match,
        with higher matches first (more likely to be OpenFF publications).
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
        # Deduplicate likely preprint/published duplicates before ranking.
        df = _deduplicate_publications(df)

        # Count author overlaps with the provided author names using fuzzy matching.
        if author_names:
            def count_author_overlaps(authors_str: str) -> int:
                """Count matched authors using max similarity across name variants."""
                paper_authors = [value.strip() for value in str(authors_str).split(";") if value.strip()]
                if not paper_authors:
                    return 0

                matched_targets: set[int] = set()
                overlap_count = 0
                for paper_author in paper_authors:
                    best_index = None
                    best_score = 0.0
                    for index, target_author in enumerate(author_names):
                        if index in matched_targets:
                            continue
                        score = _max_name_similarity(paper_author, target_author)
                        if score > best_score:
                            best_score = score
                            best_index = index

                    if best_index is not None and best_score >= 0.86:
                        matched_targets.add(best_index)
                        overlap_count += 1

                return overlap_count

            df["author_overlap_count"] = df["authors"].apply(count_author_overlaps)
            df = df.sort_values(["author_overlap_count", "year"], ascending=[False, False])
        else:
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


def add_publication_by_doi(
    doi: str,
    input_csv: str = "inputs/publications.csv",
    output_csv: str = "inputs/publications.csv",
    update_existing: bool = False,
) -> None:
    """Add or update a publication entry by DOI using Crossref metadata.

    Parameters
    ----------
    doi
        DOI (plain or doi.org URL).
    input_csv
        Path to existing publications CSV.
    output_csv
        Path to write updated publications CSV.
    update_existing
        If True, update title/authors/year when DOI already exists.
    """
    normalized_doi = _normalize_doi(doi)
    if not normalized_doi:
        raise ValueError("DOI cannot be empty.")

    meta = _get_crossref_metadata(normalized_doi)
    if meta is None:
        raise ValueError(f"Could not fetch Crossref metadata for DOI: {normalized_doi}")

    input_path = pathlib.Path(input_csv)
    if input_path.exists():
        df = pd.read_csv(input_path)
    else:
        df = pd.DataFrame()

    required_columns = ["DOI", "title", "authors", "year", "scholar_cluster_id", "chemrxiv_id"]
    for column in required_columns:
        if column not in df.columns:
            df[column] = ""

    existing_index = None
    if not df.empty and "DOI" in df.columns:
        doi_series = df["DOI"].fillna("").astype(str).str.upper().str.strip()
        matches = df.index[doi_series == normalized_doi]
        if len(matches) > 0:
            existing_index = matches[0]

    if existing_index is not None:
        if update_existing:
            df.at[existing_index, "title"] = meta.get("title") or ""
            df.at[existing_index, "authors"] = meta.get("authors") or ""
            df.at[existing_index, "year"] = meta.get("year") or ""
            print(f"Updated existing DOI row: {normalized_doi}")
        else:
            print(f"DOI already present, no changes made: {normalized_doi}")
    else:
        new_row = {column: "" for column in df.columns}
        new_row["DOI"] = normalized_doi
        new_row["title"] = meta.get("title") or ""
        new_row["authors"] = meta.get("authors") or ""
        new_row["year"] = meta.get("year") or ""

        chemrxiv_id = _search_chemrxiv_by_title(new_row["title"])
        new_row["chemrxiv_id"] = chemrxiv_id or ""
        if "scholar_cluster_id" in new_row:
            new_row["scholar_cluster_id"] = ""

        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        print(f"Added DOI row: {normalized_doi}")

    df["_year_sort"] = pd.to_numeric(df["year"], errors="coerce")
    df["_doi_sort"] = df["DOI"].fillna("").astype(str).str.upper()
    df["_title_sort"] = df["title"].fillna("").astype(str)
    df = df.sort_values(
        by=["_year_sort", "_doi_sort", "_title_sort"],
        ascending=[False, True, True],
        na_position="last",
        kind="mergesort",
    ).drop(columns=["_year_sort", "_doi_sort", "_title_sort"])

    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"Saved updated publications CSV to {output_csv}")


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
    """Return Google Scholar citation count for a cluster ID using Selenium.

    Returns None on any failure instead of raising.
    """
    url = (
        f"https://scholar.google.com/scholar"
        f"?cluster={cluster_id}&as_sdt=2005&sciodt=0,5&hl=en"
    )
    try:
        source = _scholar_get(url)
        if source is None:
            return None
        pattern = f"cites={cluster_id}" + r'[0-9a-zA-Z&;,=_]+">Cited by '
        parts = re.split(pattern, source)
        if len(parts) >= 2:
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

    is_ff_paper = df.get("force_field_paper", pd.Series(False, index=df.index)).fillna(False).astype(bool)

    keep_cols = ["DOI", "title", "authors", "year"]
    df = df[keep_cols].copy()  # only keep core metadata + new citation columns

    df["crossref_citations"] = crossref_citations
    df["crossref_citations"] = df["crossref_citations"].astype(int)
    df["scholar_citations"] = scholar_citations
    df["scholar_citations"] = df["scholar_citations"].astype(int)
    df["chemrxiv_views"] = chemrxiv_views
    df["chemrxiv_downloads"] = chemrxiv_downloads
    df["chemrxiv_citations"] = chemrxiv_citations

    close_scholar_driver()

    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"\nSaved citation counts to {output_csv}")

    def _sum(col: list) -> int:
        return sum(x for x in col if x is not None)

    def _sum_masked(col: list, mask) -> int:
        return sum(x for x, m in zip(col, mask) if x is not None and m)

    ff_mask = is_ff_paper.tolist()

    print(f"\n--- All publications ---")
    print(f"Total Crossref citations:    {_sum(crossref_citations)}")
    print(f"Total Scholar citations:     {_sum(scholar_citations)}")
    print(f"Total ChemRxiv views:        {_sum(chemrxiv_views)}")
    print(f"Total ChemRxiv downloads:    {_sum(chemrxiv_downloads)}")
    print(f"Total ChemRxiv citations:    {_sum(chemrxiv_citations)}")

    print(f"\n--- Force field papers only ---")
    print(f"FF paper Crossref citations: {_sum_masked(crossref_citations, ff_mask)}")
    print(f"FF paper Scholar citations:  {_sum_masked(scholar_citations, ff_mask)}")
    print(f"FF paper ChemRxiv views:     {_sum_masked(chemrxiv_views, ff_mask)}")
    print(f"FF paper ChemRxiv downloads: {_sum_masked(chemrxiv_downloads, ff_mask)}")
    print(f"FF paper ChemRxiv citations: {_sum_masked(chemrxiv_citations, ff_mask)}")


def populate_scholar_cluster_ids(
    input_csv: str,
    output_csv: str,
    overwrite_existing: bool = False,
) -> None:
    """Populate scholar_cluster_id values by searching Google Scholar by title.

    Parameters
    ----------
    input_csv
        Path to publications CSV containing `title` and optional `scholar_cluster_id`.
    output_csv
        Path to write updated CSV.
    overwrite_existing
        If True, re-query even when scholar_cluster_id is already present.
    """
    df = pd.read_csv(input_csv)

    if "title" not in df.columns:
        raise ValueError("Input CSV must contain a 'title' column.")

    if "scholar_cluster_id" not in df.columns:
        df["scholar_cluster_id"] = ""

    updated = 0
    skipped_existing = 0
    failed = 0

    for index, row in tqdm.tqdm(df.iterrows(), total=len(df), desc="Scholar IDs"):
        title = str(row.get("title", "")).strip()
        existing = str(row.get("scholar_cluster_id", "")).strip()

        if not title or title.lower() == "nan":
            failed += 1
            continue

        has_existing = existing and existing.lower() != "nan"
        if has_existing and not overwrite_existing:
            skipped_existing += 1
            continue

        cluster_id = _search_scholar_cluster(title)
        if cluster_id:
            df.at[index, "scholar_cluster_id"] = cluster_id
            updated += 1
        else:
            failed += 1

        time.sleep(1.0)

    close_scholar_driver()

    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)

    print(f"\nSaved scholar cluster IDs to {output_csv}")
    print(f"Updated rows:            {updated}")
    print(f"Skipped (had existing): {skipped_existing}")
    print(f"No match / no title:    {failed}")
