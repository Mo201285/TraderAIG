"""External source intake adapters for the Evidence Plane (row 746, P1 slice).

n8n (or any channel) is the *delivery arm* of the extension; it never writes
the database, it POSTs events to the TrederAIG API. What arrives here are the
normalisers that turn a raw external item -- an arXiv RSS entry, a GitHub
webhook payload, a macro calendar print, a sentiment snapshot, an SSRN paper, a
news article -- into the ONE institutional evidence payload the plane stores.
They are pure functions: no
network calls, no platform imports, no database access. A channel may call
them before delivering, or hand the raw entry to the API to normalise; either
way the invariant is unchanged -- external reality becomes evidence inside
TrederAIG, and only inside TrederAIG.

Each normaliser is conservative about what it reports: missing fields stay
missing (``None``/empty), nothing is invented to fill a shape, and every call
returns a `normalized` structure that `research.evidence_plane.EvidencePlaneService.ingest`
accepts directly (`source_kind`, `external_id`, `source_uri`, `topic`,
`headline`, `relevance`/`confidence`/`source_quality`, `markets`,
`timeframes`, `regimes`, `hypothesis`, `note`).
"""

from __future__ import annotations

from typing import Any, Dict, Protocol
import hashlib


class ExternalSourceAdapter(Protocol):
    """A pure normaliser that turns one raw external item into evidence.

    Adapting is not authorising: nothing produced here is ever read as
    permission to trade (rows 741/742/744/745).
    """

    source_kind: str

    def normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Return the evidence payload for one raw item."""
        ...


def canonical_hash(*parts: Any) -> str:
    """A 64-hex digest for de-duplication: the same parts, the same evidence."""
    return hashlib.sha256("|".join(str(p or "") for p in parts)
                          .encode("utf-8")).hexdigest()


# The symbol vocabulary the normalisers map EXPLICIT tags onto (row 750 joins
# the SSRN/news adapters to it). Anything outside this list stays in the note --
# a tag that is not a market is a topic, never a position.
KNOWN_MARKET_SYMBOLS = ("BTC", "ETH", "XAUUSD", "GOLD", "CRYPTO")


def normalize_arxiv_rss(entry: Dict[str, Any]) -> Dict[str, Any]:
    """An arXiv Atom/RSS entry into an evidence payload.

    Feed shape (arXiv official feeds): the entry carries `id` (the full
    arXiv URL, stable), `title`, `summary` (the abstract), `published`, and
    RSS `category`s / Atom `category` terms a channel passes through as
    `categories`. Only categories are mapped to markets/regimes by keyword;
    unknown ones are carried in the note, never fabricated into a market.
    """
    title = str(entry.get("title") or "").strip()
    abstract = str(entry.get("summary") or "").strip()
    arxiv_id = str(entry.get("id") or "").strip().rsplit("/", 1)[-1]
    if not title and not arxiv_id:
        raise ValueError("an arXiv entry needs a title or an arXiv id")
    categories = [str(c) for c in (entry.get("categories") or []) if c]
    markets = [c.upper() for c in categories if c.upper() in ("BTC", "XAUUSD",
                                                             "GOLD", "CRYPTO")]
    regimes = [c for c in categories
               if c.lower() in ("high_volatility", "low_volatility",
                                "trending", "ranging")]
    topic = categories[0] if categories else ""
    return {
        "source_kind": "arxiv",
        "external_id": arxiv_id,
        "source_uri": str(entry.get("id") or ""),
        "topic": topic,
        "headline": title,
        "relevance": None,
        "confidence": None,
        "source_quality": None,
        "markets": markets,
        "timeframes": [],
        "regimes": regimes,
        "hypothesis": abstract,
        "note": f"categories: {', '.join(categories)}",
        "payload_hash": canonical_hash("arxiv", arxiv_id, title, abstract),
    }


def normalize_github_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """A GitHub webhook event into an evidence payload.

    `repository.full_name` is the stable id; the event yields a headline
    ("release X of repo", "PR #N merged in repo", "new repo discovered") and
    nothing is scored -- a repository is a *discovery*, and whether it matters
    to TrederAIG is a research question, not a hidden score.
    """
    action = str(event.get("action") or "event")
    repo = event.get("repository") or {}
    name = str(repo.get("full_name") or "").strip()
    if not name:
        raise ValueError("a GitHub event needs repository.full_name")
    pr = event.get("pull_request") or {}
    release = event.get("release") or {}
    url = str((release.get("html_url")
               or pr.get("html_url")
               or str(repo.get("html_url") or "")) or "")
    detail = str((release.get("name")
                  or pr.get("title")
                  or action) or "").strip()
    default_branch = str(repo.get("default_branch") or "main")
    topics = [str(t) for t in (repo.get("topics") or []) if t]
    headline = (f"{action} {detail} in {name}" if detail
                else f"{action} in {name}")
    return {
        "source_kind": "github",
        "external_id": f"{name}:{action}:{detail}",
        "source_uri": url,
        "topic": topics[0] if topics else "github",
        "headline": headline,
        "relevance": None,
        "confidence": None,
        "source_quality": None,
        "markets": [t.upper() for t in topics if t.upper() in ("BTC", "XAUUSD",
                                                               "GOLD", "CRYPTO")],
        "timeframes": [],
        "regimes": [],
        "hypothesis": "",
        "note": f"repo {name} ({default_branch}); topics: {', '.join(topics)}",
        "payload_hash": canonical_hash("github", name, action, detail),
    }


def normalize_macro_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """A macro-calendar print into an evidence payload.

    `event` carries `code` (e.g. CPI, NFP, FOMC), `region`, `currency`,
    `actual`/`forecast`/`previous`, `period` and an ISO `datetime`. Numerics stay
    numeric or None; "not reported yet" must not become zero, so an actual that
    was not printed is carried as None and the headline says it is pending.
    """
    code = str(event.get("code") or "").strip().upper()
    if not code:
        raise ValueError("a macro event needs its code (CPI, NFP, FOMC, ...)")
    region = str(event.get("region") or "").strip().upper()
    currency = str(event.get("currency") or "").strip().upper()
    actual = event.get("actual")
    period = str(event.get("period") or "").strip()
    print_time = str(event.get("datetime") or "").strip()
    headline = (f"{code} {region} {period} actual={actual}"
                if actual is not None
                else f"{code} {region} {period} pending")
    markets = ([currency.replace("USD", "XAUUSD")] if currency == "USD"
               else ([currency] if currency in ("BTC", "ETH", "XAUUSD")
                     else []))
    regimes = ["high_volatility"] if code in ("CPI", "PPI", "NFP", "FOMC",
                                              "ECB", "BANK_CANADA") else []
    return {
        "source_kind": "macro",
        "external_id": f"{code}:{period}:{region}",
        "source_uri": "",
        "topic": f"macro.{code.lower()}",
        "headline": headline,
        "relevance": None,
        "confidence": None,
        "source_quality": None,
        "markets": markets,
        "timeframes": [],
        "regimes": regimes,
        "hypothesis": "",
        "note": (f"actual={actual} forecast={event.get('forecast')} "
                 f"previous={event.get('previous')} "
                 f"datetime={print_time}").strip(),
        "payload_hash": canonical_hash("macro", code, period, region,
                                       actual, print_time),
    }


def normalize_sentiment_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """A sentiment snapshot into an evidence payload.

    `snapshot` carries `market`, an ISO `datetime`, and optional numeric
    components (news/social/funding/open_interest/fear_greed) plus an optional
    `composite`/`confidence`. A missing composite is NOT computed here -- fusing
    components is a research decision, and inventing a composite out of a
    partial feed is fabrication. The payload keeps the raw parts so a later
    research stage can fuse them with a documented method.
    """
    market = str(snapshot.get("market") or "").strip()
    if not market:
        raise ValueError("a sentiment snapshot needs its market")
    stamp = str(snapshot.get("datetime") or "").strip()
    parts = {k: snapshot[k] for k in ("news", "social", "funding",
                                      "open_interest", "fear_greed")
             if snapshot.get(k) is not None}
    composite = snapshot.get("composite")
    headline = (f"{market} sentiment composite={composite}"
                if composite is not None
                else f"{market} sentiment components only")
    return {
        "source_kind": "sentiment",
        "external_id": f"{market}:{stamp}",
        "source_uri": "",
        "topic": f"sentiment.{market.lower()}",
        "headline": headline,
        "relevance": None,
        "confidence": None,
        "source_quality": None,
        "markets": [market],
        "timeframes": [],
        "regimes": [],
        "hypothesis": "",
        "note": (f"components: {', '.join(f'{k}={v}' for k, v in parts.items())}"
                 if parts else "no numeric components reported"),
        "payload_hash": canonical_hash("sentiment", market, stamp, composite),
    }


def normalize_ssrn_paper(entry: Dict[str, Any]) -> Dict[str, Any]:
    """An SSRN paper into an evidence payload (RMI-02, row 750).

    Channel shape (as a channel parses SSRN's abstract page): `id` (the
    abstract_id, stable), `title`, `abstract`, `authors`, `keywords`, `posted`,
    `url`. The abstract is the paper's claim, so it lands in `hypothesis`
    exactly like an arXiv summary. Keywords are mapped to markets/regimes ONLY
    on the same explicit vocabulary the arXiv normaliser uses; an unknown
    keyword is carried in the note, never fabricated into a market.
    """
    title = str(entry.get("title") or "").strip()
    ssrn_id = str(entry.get("id") or "").strip()
    if not title and not ssrn_id:
        raise ValueError("an SSRN paper needs a title or an SSRN id")
    abstract = str(entry.get("abstract") or entry.get("summary") or "").strip()
    authors = str(entry.get("authors") or "").strip()
    keywords = [k.strip() for k in (entry.get("keywords") or [])
                if str(k).strip()]
    posted = str(entry.get("posted") or entry.get("date") or "").strip()
    url = str(entry.get("url") or "").strip()
    markets = [k.upper() for k in keywords
               if k.upper() in KNOWN_MARKET_SYMBOLS]
    regimes = [k for k in keywords
               if k.lower() in ("high_volatility", "low_volatility",
                                "trending", "ranging")]
    parts = []
    if authors:
        parts.append(f"authors: {authors}")
    if posted:
        parts.append(f"posted: {posted}")
    if keywords:
        parts.append(f"keywords: {', '.join(keywords)}")
    return {
        "source_kind": "ssrn",
        "external_id": ssrn_id,
        "source_uri": url,
        "topic": keywords[0] if keywords else "ssrn",
        "headline": title,
        "relevance": None,
        "confidence": None,
        "source_quality": None,
        "markets": markets,
        "timeframes": [],
        "regimes": regimes,
        "hypothesis": abstract,
        "note": "; ".join(parts) if parts else "no provenance reported",
        "payload_hash": canonical_hash("ssrn", ssrn_id, title, abstract),
    }


def normalize_news_article(article: Dict[str, Any]) -> Dict[str, Any]:
    """A news article into an evidence payload (RMI-02, row 750).

    Channel shape: `title`, `url` (or `id`), `source`, `published`, `summary`,
    `markets`. A story is NOT a hypothesis: `hypothesis` stays empty unless the
    channel reports the article's own `summary` (the claim as the publisher
    wrote it), a body is never promoted into one. Markets come ONLY from the
    explicit symbol list -- scanning prose for tickers would invent tagging the
    publisher never made -- and provenance that was not reported is carried as
    "no provenance reported".
    """
    title = str(article.get("title") or "").strip()
    url = str(article.get("url") or "").strip()
    if not title and not url:
        raise ValueError("a news article needs a title or a url")
    news_id = str(article.get("id") or "").strip()
    source = str(article.get("source") or "").strip()
    published = str(article.get("published")
                    or article.get("datetime") or "").strip()
    summary = str(article.get("summary") or "").strip()
    markets = list(dict.fromkeys(
        str(m).strip().upper() for m in (article.get("markets") or [])
        if str(m).strip().upper() in KNOWN_MARKET_SYMBOLS))
    parts = []
    if source:
        parts.append(f"source: {source}")
    if published:
        parts.append(f"published: {published}")
    if url:
        parts.append(f"url: {url}")
    return {
        "source_kind": "news",
        "external_id": news_id or url,
        "source_uri": url,
        "topic": str(article.get("topic") or "").strip() or "news",
        "headline": title,
        "relevance": None,
        "confidence": None,
        "source_quality": None,
        "markets": markets,
        "timeframes": [],
        "regimes": [],
        "hypothesis": summary,
        "note": "; ".join(parts) if parts else "no provenance reported",
        "payload_hash": canonical_hash("news", news_id or url, title,
                                       source, published),
    }


def normalize(kind: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch a raw item by source kind. Unknown kinds raise (fail-closed)."""
    fn = {
        "arxiv": normalize_arxiv_rss,
        "github": normalize_github_event,
        "macro": normalize_macro_event,
        "ssrn": normalize_ssrn_paper,
        "news": normalize_news_article,
        "sentiment": normalize_sentiment_snapshot,
    }.get(str(kind or "").strip())
    if fn is None:
        raise ValueError(
            f"no intake normalizer for source_kind {kind!r}; a source enters "
            f"the plane only through a normalizer, never as raw bytes")
    return fn(raw)
