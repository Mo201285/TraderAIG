"""Pure intake normalisers for the Evidence Plane (row 746, P1 slice;
SSRN/News join with row 750, RMI-02).

n8n (or any channel) delivers external reality; it never writes the database.
These tests pin what `providers.sources` does with a raw item before it reaches
`POST /evidence/intake`:

- normalisers are pure: dict in, dict out, no network, no platform, no DB;
- missing fields stay missing: an unreported macro actual is `None`, a missing
  sentiment composite is NOT fabricated -- fusing raw parts is a research
  decision, and inventing a composite is fabrication;
- each normaliser emits a canonical `payload_hash` so re-delivery of the same
  item de-duplicates (same digest -> stored once);
- unknown source kinds raise: a source enters the plane only through a
  normaliser, never as raw bytes;
- SSRN/news honesty: an abstract is the paper's claim, a news story is NOT a
  hypothesis (only the publisher's own summary becomes one), markets come only
  from explicit tags the vocabulary knows, and unreported provenance is
  carried as "no provenance reported".
"""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from providers.sources import (  # noqa: E402
    normalize,
    normalize_arxiv_rss,
    normalize_github_event,
    normalize_macro_event,
    normalize_news_article,
    normalize_sentiment_snapshot,
    normalize_ssrn_paper,
)

ARXIV_ENTRY = {
    "id": "http://arxiv.org/abs/2401.00001v1",
    "title": "Volatility under funding stress",
    "summary": "We model vol under funding stress with a new estimator.",
    "published": "2026-10-07T00:00:00Z",
    "categories": ["q-fin.ST", "BTC"],
}


def test_arxiv_normalize_maps_fields():
    out = normalize_arxiv_rss(ARXIV_ENTRY)
    assert out["source_kind"] == "arxiv"
    assert out["external_id"] == "2401.00001v1"
    assert out["source_uri"] == ARXIV_ENTRY["id"]
    assert out["headline"] == "Volatility under funding stress"
    assert out["topic"] == "q-fin.ST"
    assert out["markets"] == ["BTC"]  # only the explicit market category
    assert out["hypothesis"] == ARXIV_ENTRY["summary"]
    assert out["relevance"] is None
    assert out["payload_hash"]  # deterministic digest


def test_arxiv_without_identity_refused():
    with pytest.raises(ValueError):
        normalize_arxiv_rss({"title": ""})


def test_github_normalize_release():
    out = normalize_github_event({
        "action": "published",
        "repository": {"full_name": "acme/signal", "default_branch": "main",
                       "html_url": "https://github.com/acme/signal",
                       "topics": ["btc", "research"]},
        "release": {"name": "v2.0.0",
                    "html_url": "https://github.com/acme/signal/releases/v2.0.0"},
    })
    assert out["source_kind"] == "github"
    assert out["external_id"] == "acme/signal:published:v2.0.0"
    assert out["headline"] == "published v2.0.0 in acme/signal"
    assert out["markets"] == ["BTC"]  # topic mapped, others in note
    assert "topics: btc, research" in out["note"]


def test_github_without_repo_refused():
    with pytest.raises(ValueError):
        normalize_github_event({"action": "created"})


def test_macro_pending_stays_none_not_zero():
    out = normalize_macro_event({
        "code": "CPI", "region": "US", "currency": "USD",
        "period": "2026-09", "datetime": "2026-10-10T12:30:00Z",
        "forecast": 2.2, "previous": 2.1,
    })
    assert out["source_kind"] == "macro"
    assert "actual=None" in out["note"]  # not reported is not zero
    assert "pending" in out["headline"]
    assert out["markets"] == ["XAUUSD"]
    assert out["regimes"] == ["high_volatility"]


def test_macro_actual_kept_numeric():
    out = normalize_macro_event({
        "code": "NFP", "region": "US", "currency": "USD",
        "period": "2026-09", "actual": 224, "datetime": "",
    })
    assert "actual=224" in out["note"]
    assert out["headline"].startswith("NFP US 2026-09 actual=224")


def test_macro_without_code_refused():
    with pytest.raises(ValueError):
        normalize_macro_event({"region": "US"})


def test_sentiment_missing_composite_not_fabricated():
    out = normalize_sentiment_snapshot({
        "market": "BTC", "datetime": "2026-10-07T08:00:00Z",
        "news": 0.3, "social": -0.1, "open_interest": 0.05,
    })
    assert out["source_kind"] == "sentiment"
    assert "components only" in out["headline"]  # no fused fake composite
    assert "news=0.3" in out["note"]
    assert "funding" not in out["note"]  # unreported component not claimed


def test_sentiment_composite_reported():
    out = normalize_sentiment_snapshot({
        "market": "ETH", "datetime": "2026-10-07T08:00:00Z",
        "composite": 0.72, "confidence": 0.9,
    })
    assert out["headline"] == "ETH sentiment composite=0.72"
    assert out["note"] == "no numeric components reported"


def test_sentiment_without_market_refused():
    with pytest.raises(ValueError):
        normalize_sentiment_snapshot({"datetime": "2026-10-07T08:00:00Z"})


def test_dispatch_unknown_kind_refused():
    with pytest.raises(ValueError):
        normalize("youtube", {})
    with pytest.raises(ValueError):
        normalize("", {})


def test_dispatch_roundtrip_is_pure_and_deterministic():
    a = normalize("arxiv", ARXIV_ENTRY)
    b = normalize("arxiv", ARXIV_ENTRY)
    assert a == b  # pure: same input, same output (and same digest)


# ---------------------------------------------------------------------------
# SSRN papers and news articles (row 750, RMI-02)
# ---------------------------------------------------------------------------

SSRN_PAPER = {
    "id": "5432109",
    "title": "Funding stress and intraday volatility",
    "abstract": "We show that funding stress raises intraday volatility.",
    "authors": "A. Trader, B. Quant",
    "keywords": ["market microstructure", "BTC", "high_volatility",
                 "econometrics"],
    "posted": "2026-09-30",
    "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5432109",
}

NEWS_ARTICLE = {
    "id": "wire-20261007-a",
    "title": "Policymakers hold rates steady",
    "url": "https://example.com/story-a",
    "source": "ExampleWire",
    "published": "2026-10-07T06:00:00Z",
    "summary": "The benchmark rate was left unchanged.",
    "markets": ["XAUUSD", "xauusd", "PLATINUM"],
}


def test_ssrn_normalize_maps_fields():
    out = normalize_ssrn_paper(SSRN_PAPER)
    assert out["source_kind"] == "ssrn"
    assert out["external_id"] == "5432109"
    assert out["source_uri"] == SSRN_PAPER["url"]
    assert out["headline"] == SSRN_PAPER["title"]
    assert out["topic"] == "market microstructure"
    assert out["markets"] == ["BTC"]  # only the symbol vocabulary
    assert out["regimes"] == ["high_volatility"]
    assert out["hypothesis"] == SSRN_PAPER["abstract"]
    assert out["relevance"] is None  # the normaliser never rates it
    assert "authors: A. Trader, B. Quant" in out["note"]
    assert "posted: 2026-09-30" in out["note"]
    assert out["payload_hash"]  # deterministic digest


def test_ssrn_without_identity_refused():
    with pytest.raises(ValueError):
        normalize_ssrn_paper({"abstract": "a claim with no paper"})


def test_ssrn_keyword_that_is_not_a_symbol_stays_in_the_note():
    out = normalize_ssrn_paper(SSRN_PAPER)
    assert "econometrics" not in out["markets"]  # a topic, never a position
    assert "econometrics" in out["note"]  # but not thrown away either


def test_ssrn_without_reported_provenance_is_honest():
    out = normalize_ssrn_paper({"id": "1", "title": "bare record"})
    assert out["note"] == "no provenance reported"
    assert out["hypothesis"] == ""  # no abstract reported, none claimed


def test_news_normalize_maps_fields():
    out = normalize_news_article(NEWS_ARTICLE)
    assert out["source_kind"] == "news"
    assert out["external_id"] == "wire-20261007-a"
    assert out["source_uri"] == NEWS_ARTICLE["url"]
    assert out["headline"] == NEWS_ARTICLE["title"]
    assert out["topic"] == "news"  # no topic reported, none invented
    assert out["markets"] == ["XAUUSD"]  # deduped, PLATINUM not in vocabulary
    assert out["hypothesis"] == NEWS_ARTICLE["summary"]
    assert "source: ExampleWire" in out["note"]
    assert "published: 2026-10-07T06:00:00Z" in out["note"]
    assert out["relevance"] is None
    assert out["payload_hash"]


def test_news_without_title_or_url_refused():
    with pytest.raises(ValueError):
        normalize_news_article({"source": "ExampleWire"})


def test_news_body_is_never_promoted_into_a_hypothesis():
    out = normalize_news_article({
        "title": "Rates held",
        "url": "https://example.com/story-b",
        "body": "Policymakers met all day and then announced nothing.",
    })
    assert out["hypothesis"] == ""  # the body is not the publisher's claim
    assert "Policymakers met" not in str(out.values())


def test_news_unreported_provenance_is_honest():
    out = normalize_news_article({"title": "bare headline"})
    assert out["note"] == "no provenance reported"
    assert out["markets"] == []  # no explicit list, no scanned prose


def test_dispatch_handles_ssrn_and_news():
    assert normalize("ssrn", SSRN_PAPER)["source_kind"] == "ssrn"
    assert normalize("news", NEWS_ARTICLE)["source_kind"] == "news"
    assert normalize("ssrn", SSRN_PAPER) == normalize("ssrn", SSRN_PAPER)
    with pytest.raises(ValueError):
        normalize("news", {"source": "no identity"})  # fails closed
