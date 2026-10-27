"""Conservative source attribution without LLM verification or invented fallback data."""

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from .evidence import Source

SOURCE_PRIORITY = (
    "official_company", "sec_regulatory", "earnings_release", "primary_industry",
    "independent_reporting", "analyst_commentary", "social",
)


def prioritize_documents(documents: list[dict]) -> list[dict]:
    """Rank explicit source classes; syndication retains its original origin."""
    return sorted(documents, key=lambda d: SOURCE_PRIORITY.index(d["source_class"])
                  if d.get("source_class") in SOURCE_PRIORITY else len(SOURCE_PRIORITY))


def visible_text(raw: str) -> str:
    class Reader(HTMLParser):
        def __init__(self):
            super().__init__()
            self.hidden = 0
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag in {"script", "style"}:
                self.hidden += 1

        def handle_endtag(self, tag):
            if tag in {"script", "style"}:
                self.hidden = max(0, self.hidden - 1)

        def handle_data(self, data):
            if not self.hidden:
                self.parts.append(data)

    reader = Reader()
    reader.feed(raw)
    return " ".join(" ".join(reader.parts).split())


def primary_publisher(url: str) -> bool:
    # Deliberately narrow adapter allowlist; a model cannot declare a host primary.
    host = urlsplit(url).hostname or ""
    return host in {"www.sec.gov", "www.anthropic.com", "investor.nvidia.com", "newsroom.amd.com"}


class NewsClaim(BaseModel):
    source_id: str
    quote: str
    assertion: str
    kind: str  # partnership / exclusive_supplier / market_share / ...


def validate_news(claim: NewsClaim, sources: dict[str, Source]) -> dict:
    source = sources.get(claim.source_id)
    if not source or not claim.quote.strip() or claim.quote not in source.excerpt:
        return {"status": "UNVERIFIED", "reason": "source_or_exact_passage_missing"}
    # Exact retrieved attribution is verifiable; arbitrary paraphrases/implications are not.
    if claim.assertion != claim.quote:
        return {"status": "UNVERIFIED", "reason": "interpretation_requires_separate_evidence"}
    if claim.kind == "exclusive_supplier" and not re.search(r"\bexclusive\b", claim.quote, re.I):
        return {"status": "UNVERIFIED", "reason": "partnership_does_not_establish_exclusivity"}
    if claim.kind == "market_share" and not re.search(r"\d+(?:\.\d+)?%", claim.quote):
        return {"status": "UNVERIFIED", "reason": "market_share_statistic_missing"}
    return {"status": "ATTRIBUTED_QUOTE", "reason": "quote_exists; factual truth not independently established"}


class SentimentSample(BaseModel):
    provider: str
    available: bool
    sample_size: int = Field(ge=0)
    positive: int = Field(default=0, ge=0)
    negative: int = Field(default=0, ge=0)
    source_ids: list[str] = Field(default_factory=list)

    def summary(self):
        if not self.available or self.sample_size == 0 or not self.source_ids:
            return {"status": "UNAVAILABLE", "signal": None, "sample_size": self.sample_size}
        if self.positive + self.negative > self.sample_size:
            raise ValueError("sentiment counts exceed sample size")
        return {"status": "UNVERIFIED", "signal": None, "sample_size": self.sample_size,
                "sample_balance": (self.positive - self.negative) / self.sample_size,
                "limitation": "Convenience sample; not representative market sentiment"}
