"""Research-paper monitoring across arXiv, bioRxiv, and high-impact journals.

Watchlist keywords come from USER.md's "Paper Watchlist" section. arXiv is
searched directly. Recent bioRxiv records and PubMed records from Cell, Nature,
Science, and a curated set of high-impact biotech/methods journals are fetched
in batches, then matched locally against the same watchlist. Each source fails
independently so an arXiv outage cannot suppress bioRxiv or journal discovery.

State persists source-qualified IDs so only NEW papers surface.

Usage via query.py:
  python .claude/scripts/query.py papers new
  python .claude/scripts/query.py papers search "CRISPR base editing"
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import (MEMORY, STATE_DIR, atomic_write_json,  # noqa: E402
                    file_lock, log_line, now, read_json, with_retry)

ARXIV_API = "http://export.arxiv.org/api/query"
BIORXIV_API = "https://api.biorxiv.org/details/biorxiv"
NCBI_EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ATOM = "{http://www.w3.org/2005/Atom}"
STATE_FILE = STATE_DIR / "papers-state.json"
USER_AGENT = "SecondBrain/1.0 (personal research monitor)"
REQUEST_GAP_S = 3.0
_last_request = [0.0]

HIGH_IMPACT_JOURNALS = (
    "Nature", "Science", "Cell",
    "Nature Biotechnology", "Nature Methods",
    "Nature Biomedical Engineering", "Nature Chemical Biology",
    "Nature Communications", "Nature Machine Intelligence",
    "Science Advances", "Science Translational Medicine",
    "Cell Systems", "Cell Genomics", "Cell Reports Methods",
)

_STOPWORDS = {
    "and", "for", "from", "into", "novo", "of", "the", "to", "using", "with",
}

# False-positive guards for ambiguous watchlist entries. The watchlist itself
# comes from the "Paper Watchlist" section of USER.md; these guards only say
# "this query is too ambiguous on its own". Each entry is
# (tokens that must all appear in the query, terms of which at least one must
# also appear in the paper text). The placeholder below shows the shape -
# replace it with the ambiguous terms in your own watchlist, or leave the tuple
# empty for no guards.
AMBIGUOUS_QUERY_GUARDS = (
    (("example", "acronym"), ("example acronym", "example context")),
)


def _guard_blocks(tokens: list[str], text: str, words: set[str]) -> bool:
    """True when an ambiguous query lacks the context a real match needs."""
    for needed, context in AMBIGUOUS_QUERY_GUARDS:
        if not all(token in tokens for token in needed):
            continue
        if not any(term in text or term in words for term in context):
            return True
    return False


@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: str
    summary: str
    published: str
    url: str
    query: str = ""
    source: str = "arxiv"
    journal: str = ""


def _throttle():
    elapsed = time.monotonic() - _last_request[0]
    if elapsed < REQUEST_GAP_S:
        time.sleep(REQUEST_GAP_S - elapsed)
    _last_request[0] = time.monotonic()


def search_arxiv(query: str, max_results: int = 15) -> list[Paper]:
    # Quote multi-word queries so arXiv phrase-matches instead of OR-ing terms.
    q = query.strip()
    search = f'all:"{q}"' if " " in q else f"all:{q}"
    params = urllib.parse.urlencode({
        "search_query": search,
        "sortBy": "submittedDate", "sortOrder": "descending",
        "start": 0, "max_results": max_results})
    req = urllib.request.Request(f"{ARXIV_API}?{params}",
                                 headers={"User-Agent": USER_AGENT})

    def _fetch():
        _throttle()
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.read()

    root = ET.fromstring(with_retry(_fetch, retries=0))
    papers = []
    for entry in root.findall(f"{ATOM}entry"):
        raw_id = entry.findtext(f"{ATOM}id", "").strip()
        authors = [a.findtext(f"{ATOM}name", "").strip()
                   for a in entry.findall(f"{ATOM}author")]
        papers.append(Paper(
            arxiv_id=raw_id.rsplit("/", 1)[-1],
            title=" ".join((entry.findtext(f"{ATOM}title", "")).split()),
            authors=", ".join(a for a in authors if a),
            summary=" ".join((entry.findtext(f"{ATOM}summary", "")).split()),
            published=entry.findtext(f"{ATOM}published", "")[:10],
            url=raw_id, query=query, source="arxiv", journal="arXiv"))
    return papers


def _fetch_json(url: str, *, gap_s: float = 0.4) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    def _fetch():
        elapsed = time.monotonic() - _last_request[0]
        if elapsed < gap_s:
            time.sleep(gap_s - elapsed)
        _last_request[0] = time.monotonic()
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return with_retry(_fetch, retries=2)


def search_biorxiv(days: int = 7, max_records: int = 600) -> list[Paper]:
    """Fetch recent bioRxiv metadata; relevance is filtered locally."""
    end = now().date()
    start = end - timedelta(days=days)
    interval = f"{start.isoformat()}/{end.isoformat()}"
    papers, cursor = [], 0
    while cursor < max_records:
        # The API documentation describes relative intervals such as ``7d``,
        # but the live endpoint currently treats them as malformed dates and
        # returns an empty collection. Explicit ISO dates are accepted and
        # keep the routine scan honest.
        payload = _fetch_json(f"{BIORXIV_API}/{interval}/{cursor}")
        rows = payload.get("collection") or []
        if not rows:
            break
        for row in rows:
            doi = str(row.get("doi") or "").strip()
            if not doi:
                continue
            category = str(row.get("category") or "").strip()
            papers.append(Paper(
                arxiv_id=doi,
                title=" ".join(str(row.get("title") or "").split()),
                authors=" ".join(str(row.get("authors") or "").split()),
                summary=" ".join(str(row.get("abstract") or "").split()),
                published=str(row.get("date") or "")[:10],
                url=f"https://doi.org/{doi}",
                source="biorxiv",
                journal=f"bioRxiv{f' ({category})' if category else ''}",
            ))
        cursor += len(rows)
        messages = payload.get("messages") or []
        try:
            total = int((messages[0] if messages else {}).get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        if len(rows) < 30 or (total and cursor >= total):
            break
    return papers


def _xml_text(node) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def _pubmed_date(article) -> str:
    date_node = article.find(".//ArticleDate")
    if date_node is None:
        date_node = article.find(".//JournalIssue/PubDate")
    if date_node is None:
        return ""
    medline = date_node.findtext("MedlineDate")
    if medline:
        return medline[:10]
    parts = [
        date_node.findtext("Year", ""),
        date_node.findtext("Month", ""),
        date_node.findtext("Day", ""),
    ]
    return "-".join(p for p in parts if p)


def search_high_impact_journals(
    days: int = 7,
    max_results: int = 250,
) -> list[Paper]:
    """Fetch recent CNS and major biotech/methods papers from PubMed."""
    start = (now().date() - timedelta(days=days)).isoformat().replace("-", "/")
    end = now().date().isoformat().replace("-", "/")
    journal_clause = " OR ".join(f'"{j}"[jour]' for j in HIGH_IMPACT_JOURNALS)
    term = (
        f"({journal_clause}) AND "
        f'("{start}"[Date - Publication] : "{end}"[Date - Publication])'
    )
    params = urllib.parse.urlencode({
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": max_results,
        "sort": "pub date",
        "tool": "second_brain",
    })
    search = _fetch_json(f"{NCBI_EUTILS}/esearch.fcgi?{params}")
    ids = (search.get("esearchresult") or {}).get("idlist") or []
    if not ids:
        return []
    return fetch_pubmed_by_ids(ids)


def fetch_pubmed_by_ids(ids: list[str]) -> list[Paper]:
    """Fetch PubMed records for explicit PMIDs, abstracts included.

    Split out from the journal search so a PMID recorded elsewhere (a digest
    that needs re-reviewing under a new template, say) can be resolved back to
    its abstract without re-running a date-windowed search that would no longer
    return it.
    """
    ids = [str(i).strip() for i in ids if str(i).strip()]
    if not ids:
        return []

    fetch_params = urllib.parse.urlencode({
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "xml",
        "tool": "second_brain",
    })
    req = urllib.request.Request(
        f"{NCBI_EUTILS}/efetch.fcgi?{fetch_params}",
        headers={"User-Agent": USER_AGENT},
    )

    def _fetch_xml():
        time.sleep(0.4)  # stay below NCBI's unauthenticated 3 req/s limit
        with urllib.request.urlopen(req, timeout=45) as resp:
            return ET.fromstring(resp.read())

    root = with_retry(_fetch_xml, retries=2)
    papers = []
    for record in root.findall(".//PubmedArticle"):
        citation = record.find("MedlineCitation")
        article = record.find(".//Article")
        if citation is None or article is None:
            continue
        pmid = (citation.findtext("PMID") or "").strip()
        title = _xml_text(article.find("ArticleTitle"))
        if not pmid or not title:
            continue
        abstract = " ".join(
            _xml_text(node) for node in article.findall(".//AbstractText")
            if _xml_text(node)
        )
        authors = []
        for author in article.findall(".//Author"):
            name = " ".join(filter(None, (
                author.findtext("ForeName", "").strip(),
                author.findtext("LastName", "").strip(),
            )))
            if name:
                authors.append(name)
        journal = _xml_text(article.find("./Journal/Title"))
        papers.append(Paper(
            arxiv_id=pmid,
            title=title,
            authors=", ".join(authors),
            summary=abstract,
            published=_pubmed_date(article),
            url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            source="pubmed",
            journal=journal,
        ))
    return papers


def load_watchlist() -> list[str]:
    """Parse bullet queries from the 'Paper Watchlist' section of USER.md.

    Keeps only real entries - skips '(TBD ...)' placeholders. Each bullet may be
    'label: term1, term2' or a plain phrase; we extract quoted/free keywords.
    """
    try:
        text = (MEMORY / "USER.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    m = re.search(r"##\s*Paper Watchlist(.*?)(?:\n##\s|\Z)", text, re.S)
    if not m:
        return []
    entries, current = [], ""
    for raw_line in m.group(1).splitlines():
        line = raw_line.strip()
        if line.startswith("-"):
            if current:
                entries.append(current)
            current = line.lstrip("-* ").strip()
        elif current and raw_line[:1].isspace() and line:
            current = f"{current} {line}"
        elif current:
            entries.append(current)
            current = ""
    if current:
        entries.append(current)

    queries = []
    for item in entries:
        if not item or item.lower().startswith("(tbd"):
            continue
        item = re.sub(r"[*_`]", "", item)
        # 'project A: kw1, kw2' -> use the part after the colon if present
        item = item.split(":", 1)[1].strip() if ":" in item else item
        for term in item.split(","):
            term = term.strip().strip('"')
            if len(term) >= 3:
                queries.append(term)
    return queries


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _matched_queries(paper: Paper, queries: list[str]) -> list[str]:
    """Local relevance gate for batch sources without keyword search."""
    text = _normalized(f"{paper.title} {paper.summary} {paper.journal}")
    words = set(text.split())
    matches = []
    for query in queries:
        phrase = _normalized(query)
        if not phrase:
            continue
        tokens = [
            token for token in phrase.split()
            if len(token) >= 2 and token not in _STOPWORDS
        ]
        required = (
            len(tokens) if len(tokens) <= 3
            else (len(tokens) * 3 + 3) // 4  # at least 75% of longer phrases
        )
        matched = phrase in text or (
            tokens and sum(token in words for token in tokens) >= required
        )
        if not matched:
            continue

        # Short acronyms and generic multi-word phrases have unrelated meanings
        # across broad journals. AMBIGUOUS_QUERY_GUARDS requires extra context
        # before such a query can create a digestion job.
        if _guard_blocks(tokens, text, words):
            continue
        if tokens:
            matches.append(query)
    return matches


def _identity(paper: Paper) -> str:
    return f"{paper.source}:{paper.arxiv_id}"


def _balanced(papers: list[Paper], limit: int | None) -> list[Paper]:
    """Interleave sources so arXiv cannot crowd out bioRxiv and journals."""
    if limit is None:
        return sorted(papers, key=lambda p: p.published, reverse=True)
    by_source: dict[str, list[Paper]] = {}
    for paper in sorted(papers, key=lambda p: p.published, reverse=True):
        by_source.setdefault(paper.source, []).append(paper)
    selected = []
    source_order = ("biorxiv", "pubmed", "arxiv")
    while len(selected) < limit and any(by_source.values()):
        progressed = False
        for source in source_order:
            bucket = by_source.get(source) or []
            if bucket and len(selected) < limit:
                selected.append(bucket.pop(0))
                progressed = True
        if not progressed:
            break
    return selected


def new_papers(
    max_per_query: int = 15,
    max_total: int | None = None,
) -> list[Paper]:
    """New relevant papers, with independent failure isolation per source."""
    with file_lock(STATE_FILE):
        seen = set(read_json(STATE_FILE, {}).get("seen_ids", []))
    candidates: list[Paper] = []
    candidate_ids: set[str] = set()
    matched_by_source = {"arxiv": 0, "biorxiv": 0, "pubmed": 0}
    queries = load_watchlist()

    arxiv_failures = 0
    for query in queries:
        try:
            results = search_arxiv(query, max_per_query)
        except Exception as e:
            log_line("producer", f"research: arxiv query {query!r} failed: {e!r}")
            arxiv_failures += 1
            # arXiv outages commonly affect every query. Stop after one failed
            # request; the next daily run retries, while bioRxiv and PubMed get
            # their turn promptly today.
            if arxiv_failures >= 1:
                log_line("producer", "research: arxiv circuit opened for this run")
                break
            continue
        arxiv_failures = 0
        for paper in results:
            ident = _identity(paper)
            # Accept legacy unqualified arXiv IDs from the existing state.
            if ident in seen or paper.arxiv_id in seen or ident in candidate_ids:
                continue
            candidates.append(paper)
            candidate_ids.add(ident)
            matched_by_source["arxiv"] += 1

    for source, fetch in (
        ("biorxiv", search_biorxiv),
        ("pubmed", search_high_impact_journals),
    ):
        try:
            results = fetch()
        except Exception as e:
            log_line("producer", f"research: {source} fetch failed: {e!r}")
            continue
        for paper in results:
            ident = _identity(paper)
            if ident in seen or ident in candidate_ids:
                continue
            matches = _matched_queries(paper, queries)
            if not matches:
                continue
            paper.query = ", ".join(matches[:3])
            candidates.append(paper)
            candidate_ids.add(ident)
            matched_by_source[source] += 1

    fresh = _balanced(candidates, max_total)
    newly_seen = set(seen)
    newly_seen.update(_identity(paper) for paper in fresh)
    with file_lock(STATE_FILE):
        atomic_write_json(STATE_FILE, {"seen_ids": sorted(newly_seen)})
    log_line(
        "producer",
        "research literature matches: "
        + ", ".join(f"{source}={count}"
                    for source, count in matched_by_source.items())
        + f"; selected={len(fresh)}",
    )
    return fresh


def format_context(papers: list[Paper]) -> str:
    if not papers:
        return "No new papers matching the watchlist."
    lines = [f"{len(papers)} new paper(s):"]
    for p in papers:
        source = p.journal or p.source
        lines.append(f"- [{p.query}] {p.title} ({p.published}; {source})\n"
                     f"  {p.authors[:120]}\n  {p.url}\n  {p.summary[:280]}")
    return "\n".join(lines)
