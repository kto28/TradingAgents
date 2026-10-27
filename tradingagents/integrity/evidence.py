"""Evidence is issued by adapters and validators, never by model assertions."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class UTCRecord(BaseModel):
    @field_validator("observed_at", "available_at", "retrieved_at", "published_at", "as_of", check_fields=False)
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(UTC)


class Status(StrEnum):
    VERIFIED = "VERIFIED"
    CORROBORATED = "CORROBORATED"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class Source(UTCRecord):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    provider: str
    url: str
    document: str
    published_at: AwareDatetime
    retrieved_at: AwareDatetime
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    origin: str  # Independence group: syndication does not create a new source.
    kind: Literal["primary", "secondary", "social"]
    timestamp_precision: Literal["instant", "date_only"] = "instant"
    excerpt: str = ""

    @model_validator(mode="after")
    def valid_url(self):
        if urlsplit(self.url).scheme not in {"http", "https"}:
            raise ValueError("An original HTTP(S) source URL is required")
        return self


class Fact(UTCRecord):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    id: str
    ticker: str
    metric: str
    value: float | str | None
    unit: str
    currency: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    fiscal_period: str | None = None
    scope: str | None = None  # e.g. a transaction/bucket; distinct tranches are not contradictions
    observed_at: AwareDatetime
    available_at: AwareDatetime
    retrieved_at: AwareDatetime
    source_ids: list[str]
    status: Status = Status.UNVERIFIED
    method: str = "not_verified"
    nature: Literal["reported", "estimated", "calculated", "inferred"] = "reported"
    inputs: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class Claim(BaseModel):
    """Only exact restatements can be facts. Free text is never validated by citation alone."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str
    agent: str
    label: Literal["FACT", "ESTIMATE", "INFERENCE", "HYPOTHESIS", "UNKNOWN"]
    metric: str
    value: float | str | None = None
    unit: str
    currency: str | None = None
    fiscal_period: str | None = None
    evidence_ids: list[str]
    material: bool = True


class EvidenceStore(UTCRecord):
    model_config = ConfigDict(extra="forbid")
    as_of: AwareDatetime
    sources: dict[str, Source] = Field(default_factory=dict)
    facts: dict[str, Fact] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)
    references: list[dict] = Field(default_factory=list)

    def add(self, fact: Fact) -> Fact:
        """Recheck temporal and source constraints even for caller-supplied records."""
        issues = list(fact.issues)
        status = fact.status
        sources = [self.sources[s] for s in fact.source_ids if s in self.sources]
        if len(sources) != len(fact.source_ids) or not sources:
            issues.append("missing_source")
            if status != Status.UNAVAILABLE:
                status = Status.UNVERIFIED
        if fact.available_at > self.as_of or fact.observed_at > self.as_of or any(
            s.published_at > self.as_of for s in sources
        ):
            issues.append("lookahead")
            status = Status.UNAVAILABLE
        if status == Status.VERIFIED and (
            not all(s.kind == "primary" for s in sources)
            or fact.method not in {"sec_xbrl", "sec_xml", "primary_document_extract", "formula"}
        ):
            issues.append("no_primary_verification")
            status = Status.UNVERIFIED
        if status == Status.CORROBORATED and len({s.origin for s in sources}) < 2:
            issues.append("sources_not_independent")
            status = Status.UNVERIFIED
        if fact.nature in {"estimated", "inferred"} and status == Status.VERIFIED:
            status = Status.UNVERIFIED
            issues.append("estimate_is_not_reported_fact")
        if fact.nature == "calculated":
            parents = [self.facts[i] for i in fact.inputs if i in self.facts]
            if not parents or len(parents) != len(fact.inputs) or any(
                p.status not in {Status.VERIFIED, Status.CORROBORATED} for p in parents
            ):
                status = Status.UNVERIFIED
                issues.append("unverified_calculation_inputs")
        fact = fact.model_copy(update={"status": status, "issues": issues})
        # Retain both values on disagreement. Never select a convenient restatement.
        for key, other in list(self.facts.items()):
            identity = ("ticker", "metric", "unit", "currency", "period_start", "period_end", "fiscal_period", "scope")
            if (key != fact.id and all(getattr(other, x) == getattr(fact, x) for x in identity)
                    and other.observed_at == fact.observed_at and other.value != fact.value
                    and other.status in {Status.VERIFIED, Status.CONTRADICTED}
                    and fact.status == Status.VERIFIED):
                self.facts[key] = other.model_copy(update={
                    "status": Status.CONTRADICTED, "issues": [*other.issues, "source_conflict"],
                })
                fact = fact.model_copy(update={
                    "status": Status.CONTRADICTED, "issues": [*fact.issues, "source_conflict"],
                })
        self.facts[fact.id] = fact
        return fact

    def expire(self, thresholds: dict[str, timedelta]):
        for key, fact in list(self.facts.items()):
            ttl = thresholds.get(fact.metric)
            if ttl and self.as_of - fact.observed_at > ttl and fact.status not in {
                Status.UNAVAILABLE, Status.CONTRADICTED,
            }:
                self.facts[key] = fact.model_copy(update={"status": Status.STALE})

    def check_claim(self, claim: Claim) -> list[str]:
        facts = [self.facts[i] for i in claim.evidence_ids if i in self.facts]
        errors = []
        if not facts or len(facts) != len(claim.evidence_ids):
            errors.append("unknown_evidence_reference")
        if claim.label not in {"FACT", "ESTIMATE"}:
            errors.append("interpretation_not_established_fact")
        for fact in facts:
            if fact.status not in {Status.VERIFIED, Status.CORROBORATED}:
                errors.append(f"evidence_{fact.status}")
            if any(getattr(claim, x) != getattr(fact, x) for x in (
                "metric", "value", "unit", "currency", "fiscal_period",
            )):
                errors.append("claim_does_not_match_evidence")
            if claim.label == "FACT" and fact.nature in {"estimated", "inferred"}:
                errors.append("forecast_presented_as_fact")
        self.references.append({
            **claim.model_dump(mode="json"), "errors": sorted(set(errors)),
            "eligible_for_decision": not errors and claim.material,
            "influenced_decision": False,
        })
        return sorted(set(errors))

    def revalidate(self):
        """Reconstruct at an input boundary; JSON status labels are not sufficient."""
        pending = list(self.facts.values())
        self.facts = {}
        for fact in sorted(pending, key=lambda f: bool(f.inputs)):
            self.add(fact)
        return self


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> datetime:
    return datetime.now(UTC)
