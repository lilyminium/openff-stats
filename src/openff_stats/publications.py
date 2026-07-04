"""
Publication curation and citation count collection.

The curated list is inputs/publications.csv; maintain it with:
  openff-stats add-publication-doi DOI [--scholar]
       → fetches Crossref metadata, appends a row (optionally fills the
         Scholar cluster ID too)
  openff-stats scholar-lookup DOI [--save]
       → finds the Google Scholar cluster ID for one DOI (DOI search with
         title fallback, validated against the Crossref title)
  openff-stats scholar-clusters
       → the same lookup in bulk: fills scholar_cluster_id for every DOI in
         the publications CSV that is still missing one

Collection:
  openff-stats citations
       → queries Crossref, Scholar, ChemRxiv for each paper, writes
         data/citations.csv

Optional bulk discovery (candidates/ for human review):
  openff-stats discover-publications --orcid-csv inputs/orcids.csv

inputs/publications.csv columns:
  DOI, force_field_paper, title, authors, year, scholar_cluster_id, chemrxiv_id
  (scholar_cluster_id and chemrxiv_id may be blank if not applicable)
"""

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

# scholar_cluster_id / chemrxiv_id are long numeric IDs.  A Scholar cluster ID
# has up to 20 digits, so if pandas infers the column as float64 (which happens
# whenever any row is blank) it silently rounds the ID.  Always read these as
# strings so round-trips stay exact.
_ID_DTYPES = {"scholar_cluster_id": str, "chemrxiv_id": str}

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


def _search_scholar(query: str) -> list[dict]:
    """Search Google Scholar and parse the first result page.

    Returns one dict per result block, with keys ``title``, ``cluster_id``
    (from the "Cited by" / "All versions" link, may be None), and ``cited_by``
    (int or None).  Returns an empty list on CAPTCHA or failure.
    """
    import urllib.parse

    url = f"https://scholar.google.com/scholar?q={urllib.parse.quote_plus(query)}&hl=en"
    source = _scholar_get(url)
    if source is None:
        return []

    results: list[dict] = []
    # Each organic result is a <div class="gs_ri"> holding an <h3 class="gs_rt">
    # title link.  The cluster ID is the d=<id> field of that link's data-clk
    # attribute (present on every result, unlike the "Cited by" footer link).
    for chunk in re.split(r'<div class="gs_ri"', source)[1:]:
        title_match = re.search(r'<h3 class="gs_rt".*?</h3>', chunk, flags=re.DOTALL)
        title = ""
        if title_match:
            h3 = re.sub(r'<span class="gs_ctc".*?</span>', "", title_match.group(0), flags=re.DOTALL)
            title = " ".join(re.sub(r"<[^>]+>", " ", h3).split())

        cluster_match = (
            re.search(r'data-clk="[^"]*[?&;]d=(\d+)', chunk)
            or re.search(r"[?&;]cites=(\d+)", chunk)
            or re.search(r"[?&;]cluster=(\d+)", chunk)
        )
        cited_match = re.search(r"Cited by ([\d,]+)", chunk)

        if not title and cluster_match is None:
            continue
        results.append({
            "title": title,
            "cluster_id": cluster_match.group(1) if cluster_match else None,
            "cited_by": int(cited_match.group(1).replace(",", "")) if cited_match else None,
        })
    return results


def _best_scholar_match(results: list[dict], title: str) -> tuple[dict, float] | None:
    """Return the (result, title similarity) pair that best matches *title*."""
    scored = [
        (result, _title_similarity(result["title"], title))
        for result in results
        if result["cluster_id"]
    ]
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[1])


def _match_scholar(
    doi: str,
    title: str,
    min_similarity: float = 0.75,
) -> tuple[list[dict], tuple[dict, float] | None]:
    """Find the Scholar result for a paper, searching by DOI then title.

    Searches Scholar for the quoted DOI string first (its results are papers
    that mention the DOI, so the paper itself is not guaranteed to appear),
    then falls back to a title search when no candidate matches *title*
    confidently.  Every candidate is scored against *title*, so a wrong hit is
    never accepted.  Leaves the shared driver open for the caller to reuse.

    Parameters
    ----------
    doi
        DOI to search for (may be empty to search by title only).
    title
        Reference title (from the curated CSV or Crossref) used to validate
        candidates.
    min_similarity
        Title similarity below which the DOI search is treated as a miss and
        the title fallback is tried.

    Returns
    -------
    tuple[list[dict], tuple[dict, float] | None]
        All candidates seen and the best (result, similarity) pair, or None.
    """
    normalized = _normalize_doi(doi) if doi else ""
    candidates = _search_scholar(f'"{normalized}"') if normalized else []
    best = _best_scholar_match(candidates, title) if title else None

    if title and (best is None or best[1] < min_similarity):
        seen = {c["cluster_id"] for c in candidates}
        for result in _search_scholar(" ".join(title.split()[:8])):
            if result["cluster_id"] not in seen:
                candidates.append(result)
        best = _best_scholar_match(candidates, title)

    return candidates, best


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
    candidates["year_numeric"] = pd.to_numeric(candidates["year"], errors="coerce").fillna(0)

    published = candidates[~candidates["is_preprint"]]
    if not published.empty:
        return published.sort_values("year_numeric", ascending=False).iloc[0]

    return candidates.sort_values("year_numeric", ascending=False).iloc[0]


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
        selected_rows.append(preferred.drop(labels=["is_preprint", "year_numeric"], errors="ignore"))

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
    fetch_scholar: bool = False,
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
    fetch_scholar
        If True, look up the Google Scholar cluster ID after the row is
        written (best-effort: a Scholar failure never loses the new row).
    """
    normalized_doi = _normalize_doi(doi)
    if not normalized_doi:
        raise ValueError("DOI cannot be empty.")

    meta = _get_crossref_metadata(normalized_doi)
    if meta is None:
        raise ValueError(f"Could not fetch Crossref metadata for DOI: {normalized_doi}")

    input_path = pathlib.Path(input_csv)
    if input_path.exists():
        df = pd.read_csv(input_path, dtype=_ID_DTYPES)
    else:
        df = pd.DataFrame()

    required_columns = ["DOI", "title", "authors", "year", "scholar_cluster_id", "chemrxiv_id"]
    for column in required_columns:
        if column not in df.columns:
            df[column] = ""

    existing_index = None
    if not df.empty and "DOI" in df.columns:
        doi_series = df["DOI"].fillna("").astype(str).map(_normalize_doi)
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

    if fetch_scholar:
        try:
            scholar_lookup(normalized_doi, publications_csv=output_csv, save=True)
        except Exception as exc:
            print(
                f"Warning: Scholar lookup failed ({exc}). The publication was "
                f"still added; fill scholar_cluster_id later with "
                f"`openff-stats scholar-lookup {normalized_doi} --save`."
            )


def scholar_lookup(
    doi: str,
    publications_csv: str = "inputs/publications.csv",
    save: bool = False,
    min_similarity: float = 0.75,
) -> str | None:
    """Look up a publication on Google Scholar by DOI.

    Searches Scholar for the quoted DOI string, falling back to a title
    search (title from Crossref) when the DOI search finds no confident
    match.  Candidates are validated against the Crossref title, so a wrong
    first hit is never silently accepted.  Prints each candidate with its
    cluster ID, "Cited by" count, and title similarity.

    Parameters
    ----------
    doi
        DOI (plain or doi.org URL).
    publications_csv
        Curated publications CSV, updated when *save* is True.
    save
        If True and a confident match is found, write the cluster ID into
        the row of *publications_csv* whose DOI matches.
    min_similarity
        Minimum title similarity (0-1) for a match to be trusted.

    Returns
    -------
    str | None
        The matched cluster ID, or None if no confident match was found.
    """
    normalized_doi = _normalize_doi(doi)
    meta = _get_crossref_metadata(normalized_doi)
    crossref_title = (meta or {}).get("title") or ""
    if crossref_title:
        print(f"Crossref title: {crossref_title}")
    else:
        print(
            "Warning: no Crossref title available — Scholar hits cannot be "
            "validated, so nothing will be saved automatically."
        )

    try:
        print(f'Searching Scholar for "{normalized_doi}" ...')
        candidates, best = _match_scholar(normalized_doi, crossref_title, min_similarity)
    finally:
        close_scholar_driver()

    if not candidates:
        print("No Scholar results found.")
        return None

    print(f"\n{'cluster_id':>22}  {'cited_by':>8}  {'match':>5}  title")
    for result in candidates:
        similarity = _title_similarity(result["title"], crossref_title)
        print(
            f"{result['cluster_id'] or '-':>22}  "
            f"{result['cited_by'] if result['cited_by'] is not None else '-':>8}  "
            f"{similarity:>5.2f}  {result['title'][:70]}"
        )

    if best is None or best[1] < min_similarity:
        print(
            f"\nNo candidate reached the similarity threshold ({min_similarity}). "
            "If one of the above is correct, set scholar_cluster_id manually."
        )
        return None

    result, similarity = best
    print(
        f"\nBest match (similarity {similarity:.2f}): cluster_id="
        f"{result['cluster_id']}, cited by {result['cited_by']}"
    )

    if save:
        df = pd.read_csv(publications_csv, dtype=_ID_DTYPES)
        doi_series = df["DOI"].fillna("").astype(str).map(_normalize_doi)
        matches = df.index[doi_series == normalized_doi]
        if len(matches) == 0:
            print(
                f"DOI {normalized_doi} is not in {publications_csv} — add it "
                f"first with `openff-stats add-publication-doi {normalized_doi}`."
            )
        else:
            if "scholar_cluster_id" not in df.columns:
                df["scholar_cluster_id"] = ""
            df["scholar_cluster_id"] = df["scholar_cluster_id"].astype("object")
            df.loc[matches, "scholar_cluster_id"] = result["cluster_id"]
            df.to_csv(publications_csv, index=False)
            print(f"Saved scholar_cluster_id to {publications_csv}.")

    return result["cluster_id"]


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
    df = pd.read_csv(input_csv, dtype=_ID_DTYPES)

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

    df["crossref_citations"] = pd.to_numeric(crossref_citations, errors="coerce").astype("Int64")
    df["scholar_citations"] = pd.to_numeric(scholar_citations, errors="coerce").astype("Int64")
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
    min_similarity: float = 0.75,
) -> None:
    """Fill scholar_cluster_id for every DOI in the publications CSV.

    For each row missing a cluster ID, searches Scholar by DOI (falling back
    to the row's title) and validates the hit against the title, exactly like
    ``scholar-lookup`` but in bulk over the whole file.  Only confident matches
    are written; rows with no confident match are left blank and reported so
    you can fill them by hand.

    Parameters
    ----------
    input_csv
        Publications CSV containing `DOI`, `title`, and optional
        `scholar_cluster_id`.
    output_csv
        Path to write the updated CSV.
    overwrite_existing
        If True, re-query even rows that already have a cluster ID.
    min_similarity
        Minimum title similarity (0-1) for a match to be trusted.
    """
    df = pd.read_csv(input_csv, dtype=_ID_DTYPES)

    if "title" not in df.columns and "DOI" not in df.columns:
        raise ValueError("Input CSV must contain a 'DOI' or 'title' column.")

    if "scholar_cluster_id" not in df.columns:
        df["scholar_cluster_id"] = ""
    df["scholar_cluster_id"] = df["scholar_cluster_id"].astype("object")

    updated = 0
    skipped_existing = 0
    failed = 0

    try:
        for index, row in tqdm.tqdm(df.iterrows(), total=len(df), desc="Scholar IDs"):
            doi = str(row.get("DOI", "")).strip()
            title = str(row.get("title", "")).strip()
            existing = str(row.get("scholar_cluster_id", "")).strip()

            if title.lower() == "nan":
                title = ""
            if doi.lower() == "nan":
                doi = ""
            if not doi and not title:
                failed += 1
                continue

            has_existing = existing and existing.lower() != "nan"
            if has_existing and not overwrite_existing:
                skipped_existing += 1
                continue

            try:
                _, best = _match_scholar(doi, title, min_similarity)
            except Exception as exc:  # a transient Scholar/Selenium error on one
                print(f"  Warning: Scholar lookup failed for {doi or title!r}: {exc}")
                best = None            # row must not abort the whole run
            if best is not None and best[1] >= min_similarity:
                df.at[index, "scholar_cluster_id"] = best[0]["cluster_id"]
                updated += 1
            else:
                failed += 1

            time.sleep(1.0)
    finally:
        close_scholar_driver()

    pathlib.Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)

    print(f"\nSaved scholar cluster IDs to {output_csv}")
    print(f"Updated rows:            {updated}")
    print(f"Skipped (had existing): {skipped_existing}")
    print(f"No confident match:     {failed}")
