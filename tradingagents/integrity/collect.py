"""Trusted adapters for a run-scoped, immutable-as-of evidence snapshot."""

import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.vendors import sec_edgar
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv

from .evidence import EvidenceStore, Fact, Source, Status, digest, utc_now
from .financials import derive_financials, freshness, sec_facts
from .insiders import parse_ownership
from .market import analysis_cutoff, compare_indicator, indicators
from .news import primary_publisher, visible_text


def read_snapshot(path):
    path = Path(path).expanduser()
    snapshot = json.loads(path.read_text())
    for entry in snapshot["files"]:
        if "content" not in entry:
            entry["content"] = (path.parent / entry["path"]).read_bytes().decode("utf-8")
    return snapshot


def from_snapshot(ticker: str, as_of: datetime, snapshot: dict, user_timezone="Asia/Hong_Kong") -> dict:
    """Snapshot contains fetched bytes encoded as text plus source metadata, not LLM facts."""
    store = EvidenceStore(as_of=as_of)
    market, insiders = {}, []
    for entry in snapshot.get("files", []):
        raw = entry["content"].encode()
        retrieved = entry.get("retrieved_at", snapshot["retrieved_at"])
        if digest(raw) != entry["sha256"]:
            store.gaps.append("snapshot_hash_mismatch:" + entry["name"])
            continue
        try:
            if entry["name"].endswith("companyfacts.json"):
                payload = json.loads(raw)
                sec_facts(payload, raw, store, ticker, entry["url"], retrieved)
            elif entry["name"].endswith(".xml"):
                filed = datetime.fromisoformat(entry["filed"]).date()
                if filed > as_of.date():
                    continue
                # Date-only availability is conservatively next UTC day plus 5h.
                from zoneinfo import ZoneInfo
                available = datetime.combine(filed, datetime.max.time(), ZoneInfo("America/New_York"))
                if available > as_of:
                    continue
                filing = parse_ownership(raw, filed, entry["url"], snapshot.get("currency"))
                insiders.append(filing.model_dump(mode="json"))
                sid = entry["name"]
                store.sources[sid] = Source(
                    id=sid, provider="SEC EDGAR", url=entry["url"], document=sid,
                    published_at=available, retrieved_at=retrieved, sha256=digest(raw),
                    kind="primary", origin="SEC:" + filing.owner, excerpt="SEC ownership XML",
                    timestamp_precision="date_only",
                )
                for i, tx in enumerate(filing.transactions):
                    for metric, value, unit in (
                        ("insider_transaction_shares", tx.shares, "shares"),
                        ("insider_post_shares", tx.post_shares, "shares"),
                        ("insider_transaction_category", tx.category, "category"),
                    ):
                        store.add(Fact(
                            id=f"{sid}:{i}:{metric}", ticker=ticker, metric=metric, value=value,
                            scope=f"{sid}:{i}",
                            unit=unit, observed_at=datetime.combine(tx.transaction_date or filed, datetime.min.time(), UTC),
                            available_at=available, retrieved_at=retrieved,
                            source_ids=[sid], status=Status.VERIFIED, method="sec_xml",
                        ))
            elif entry["name"].endswith(".html"):
                published = datetime.fromisoformat(entry["published_at"])
                if published > as_of:
                    continue
                sid = entry["name"]
                text = visible_text(raw.decode())
                store.sources[sid] = Source(
                    id=sid, provider=entry["provider"], url=entry["url"], document=sid,
                    published_at=published, retrieved_at=retrieved,
                    sha256=digest(raw), kind="primary" if primary_publisher(entry["url"]) else "secondary",
                    origin=entry["provider"], excerpt=text,
                    timestamp_precision=entry.get("timestamp_precision", "date_only"),
                )
                for i, quote in enumerate(entry.get("quotes", [])):
                    exact = " ".join(quote.split())
                    store.add(Fact(
                        id=f"news:{sid}:{i}", ticker=ticker, metric="announcement_quote",
                        value=exact, unit="verbatim_source_statement", observed_at=published,
                        available_at=published, retrieved_at=retrieved, source_ids=[sid],
                        status=Status.VERIFIED if exact and exact in text else Status.UNVERIFIED,
                        method="primary_document_extract",
                        issues=["Verifies the announcement text only; not fulfillment, exclusivity, market share or future financial impact."],
                    ))
            elif entry["name"].endswith("ohlcv.csv"):
                frame = pd.read_csv(StringIO(raw.decode()))
                market = indicators(frame, as_of, user_timezone=user_timezone)
                sid = entry["name"]
                observed = datetime.fromisoformat(market["session"]["last_completed_close"])
                # Use the actual last bar, not the expected session, for stale series.
                import exchange_calendars as xcals
                observed = xcals.get_calendar("XNYS").session_close(pd.Timestamp(market["bar_date"])).to_pydatetime()
                store.sources[sid] = Source(
                    id=sid, provider="Yahoo Finance", url=entry["url"], document=sid,
                    published_at=observed, retrieved_at=retrieved, sha256=digest(raw),
                    kind="secondary", origin="Yahoo", excerpt=market["parameters"],
                )
                for metric, value in market["values"].items():
                    store.add(Fact(
                        id=f"market:{metric}", ticker=ticker, metric=metric, value=value,
                        unit="USD/share" if metric == "price" else "indicator",
                        currency="USD" if metric == "price" else None,
                        observed_at=observed, available_at=observed, retrieved_at=retrieved,
                        source_ids=[sid], status=Status.UNVERIFIED if market["fresh"] else Status.STALE,
                        method="local_ohlcv_formula", nature="reported" if metric == "price" else "calculated",
                        inputs=[] if metric == "price" else ["market:price"],
                        issues=["single_vendor_not_independently_verified"],
                    ))
        except (ValueError, KeyError, TypeError) as exc:
            store.gaps.append(f"{entry['name']}:{type(exc).__name__}")
    # External values never replace local values; disagreement blocks the signal.
    for external in snapshot.get("external_indicators", []):
        metric = external["metric"]
        fid = f"market:{metric}"
        if fid not in store.facts:
            continue
        comparison = compare_indicator(float(store.facts[fid].value), float(external["value"]),
                                       external.get("relative_tolerance", .01))
        market.setdefault("external_comparisons", []).append({**comparison, **external})
        if comparison["conflict"]:
            old = store.facts[fid]
            store.facts[fid] = old.model_copy(update={
                "status": Status.CONTRADICTED, "issues": [*old.issues, "external_indicator_disagreement"],
            })
            market["breakout"] = False
    freshness(store)
    derive_financials(store)
    store.gaps.extend(snapshot.get("gaps", []))
    for gap in ("News economic implications beyond exact retrieved passages are not verified",
                "Social feeds: sample sizes/availability not established",
                "Historical win rate: NOT ESTABLISHED"):
        if gap not in store.gaps:
            store.gaps.append(gap)
    return {"evidence": store.model_dump(mode="json"), "market_validation": market, "insider_filings": insiders}


def collect(ticker: str, trade_date: str, config: dict) -> dict:
    now = utc_now()
    as_of = analysis_cutoff(trade_date, now)
    path = config.get("evidence_snapshot")
    if path:
        snapshot = read_snapshot(path)
        # A replay cannot move the snapshot's cutoff forward.
        as_of = min(as_of, datetime.fromisoformat(snapshot["as_of"]))
        if snapshot["ticker"] != ticker:
            raise ValueError("snapshot ticker mismatch")
        return from_snapshot(ticker, as_of, snapshot, config.get("display_timezone", "Asia/Hong_Kong"))
    snapshot = {"ticker": ticker, "as_of": as_of.isoformat(), "retrieved_at": now.isoformat(),
                "files": [], "gaps": []}
    supported_us_issuer = False
    try:
        cik = sec_edgar.cik_for(ticker)
        if not cik:
            raise ValueError("no SEC issuer mapping")
        supported_us_issuer = True
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        raw = json.dumps(sec_edgar._cached_json(url, f"CIK{cik}.json")).encode()
        snapshot["files"].append({"name": "companyfacts.json", "content": raw.decode(),
                                  "sha256": digest(raw), "url": url})
    except Exception as exc:
        snapshot["gaps"].append(f"SEC unavailable:{type(exc).__name__}")
    try:
        if not supported_us_issuer:
            snapshot["gaps"].append("US exchange calendar not established for this instrument")
            raise ValueError("unsupported exchange")
        frame = load_ohlcv(ticker, trade_date, fill_gaps=False)
        raw = frame.to_csv(index=False).encode()
        snapshot["files"].append({"name": "ohlcv.csv", "content": raw.decode(), "sha256": digest(raw),
                                  "url": f"https://finance.yahoo.com/quote/{ticker}/history/"})
    except Exception as exc:
        snapshot["gaps"].append(f"OHLCV unavailable:{type(exc).__name__}")
    snapshot["gaps"].append("Live insider XML not fetched automatically; supply a captured SEC snapshot")
    folder = Path(config["data_cache_dir"]) / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(snapshot, ensure_ascii=False)
    filename = digest(raw.encode()) + ".json"
    (folder / filename).write_text(raw, encoding="utf-8")
    return from_snapshot(ticker, as_of, snapshot, config.get("display_timezone", "Asia/Hong_Kong"))
