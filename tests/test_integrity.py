"""Acceptance cases map to docs/integrity/ACCEPTANCE.md; no network or LLM needed."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from tradingagents.integrity.collect import from_snapshot
from tradingagents.integrity.evidence import Claim, EvidenceStore, Fact, Source, Status, digest
from tradingagents.integrity.financials import calculate, reconcile, validate_fiscal_period
from tradingagents.integrity.gates import analyst_gate, gate_text, validate_decision
from tradingagents.integrity.insiders import parse_ownership
from tradingagents.integrity.market import (
    compare_indicator,
    complete_bars,
    indicators,
    session_state,
)
from tradingagents.integrity.news import NewsClaim, SentimentSample, validate_news
from tradingagents.integrity.risk import TradePlan, evaluate_plan

FIXTURES = Path(__file__).parent / "fixtures/integrity"
NOW = datetime(2026, 10, 27, 15, 17, 23, tzinfo=UTC)


@pytest.fixture
def store():
    source = Source(id="sec", provider="SEC", url="https://www.sec.gov/Archives/example.xml",
                    document="test fixture (synthetic, not NVDA)", published_at=NOW - timedelta(days=1),
                    retrieved_at=NOW, sha256="0" * 64, origin="SEC", kind="primary")
    return EvidenceStore(as_of=NOW, sources={"sec": source})


def fact(store, metric, value, **kw):
    data = {"id": metric, "ticker": "NVDA", "metric": metric, "value": value, "unit": "USD", "currency": "USD",
            "period_start": date(2026, 4, 27), "period_end": date(2026, 7, 26),
            "fiscal_period": "2026-04-27 / 2026-07-26", "observed_at": NOW - timedelta(days=1),
            "available_at": NOW - timedelta(days=1), "retrieved_at": NOW, "source_ids": ["sec"],
            "status": Status.VERIFIED, "method": "sec_xbrl"}
    return store.add(Fact(**{**data, **kw}))


def claim(f, **kwargs):
    return Claim(**{"id": "c", "agent": "test", "label": "FACT", "metric": f.metric, "value": f.value,
                   "unit": f.unit, "currency": f.currency, "fiscal_period": f.fiscal_period,
                   "evidence_ids": [f.id], **kwargs})


def test_01_market_cap_factor_ten(store):
    fact(store, "price", 216.92, unit="USD/share")
    fact(store, "shares_outstanding", 24_152_000_000, unit="shares", currency=None)
    actual = calculate(store, "market_cap", ["price", "shares_outstanding"])
    assert actual.value == 216.92 * 24_152_000_000
    assert not reconcile(actual.value / 10, actual.value)


def test_02_yoy_mismatch(store):
    a = fact(store, "revenue", 96.221, id="current")
    b = fact(store, "revenue", 46.743, id="prior", period_start=date(2025, 4, 28), period_end=date(2025, 7, 27))
    actual = calculate(store, "yoy_growth", [a.id, b.id])
    assert actual.value == pytest.approx((96.221 / 46.743 - 1) * 100)
    assert not reconcile(47, actual.value)


def test_03_wrong_quarter(store):
    f = fact(store, "revenue", 96)
    assert not validate_fiscal_period(f, date(2026, 7, 27), date(2026, 10, 25))
    assert store.check_claim(claim(f, fiscal_period="2026 Q3")) == ["claim_does_not_match_evidence"]


def test_04_receivables_not_fcf(store):
    fact(store, "operating_cash_flow", 100)
    fact(store, "accounts_receivable", 45)
    with pytest.raises(ValueError, match="wrong formula"):
        calculate(store, "free_cash_flow", ["operating_cash_flow", "accounts_receivable"])
    fact(store, "capital_expenditure", 10)
    assert calculate(store, "free_cash_flow", ["operating_cash_flow", "capital_expenditure"]).value == 90


def test_05_unsupported_growth_forecast(store):
    f = fact(store, "growth_estimate_percent", 35, nature="estimated")
    assert f.status == Status.UNVERIFIED
    assert store.check_claim(claim(f))


def test_06_fabricated_research_citation(store):
    c = Claim(id="fake", agent="Bear", label="FACT", metric="growth", value=35,
              unit="%", evidence_ids=["JPMorgan-2026-10-10"])
    assert "unknown_evidence_reference" in store.check_claim(c)
    safe, errors = gate_text("JPMorgan 2026-10-10 says growth fell to 35%.", "Bear", store)
    assert errors and "35" not in safe


def _filing(name, filed):
    return parse_ownership((FIXTURES / name).read_bytes(), filed,
                           f"https://www.sec.gov/Archives/{name}")


def test_07_actual_huang_trust_transfers():
    f = _filing("0001197649-26-000005.xml", date(2026, 3, 20))
    assert f.owner == "HUANG JEN HSUN"
    transfers = [t for t in f.transactions if t.code == "G"]
    assert transfers and all(t.category == "TRUST_TRANSFER" for t in transfers)
    assert not any(t.category in {"AWARD", "OPEN_MARKET_OR_PRIVATE_PURCHASE"} for t in transfers)
    assert f.transactions[0].category == "TAX_WITHHOLDING"
    assert f.transactions[0].shares == 437908


def test_08_actual_form144_is_not_sale():
    f = _filing("0001628280-26-060177.xml", date(2026, 9, 2))
    assert f.form == "144"
    assert not f.transactions and not f.liquidation_claim_supported()


def test_actual_kress_planned_sale():
    f = _filing("0001588670-26-000010.xml", date(2026, 3, 20))
    sales = [t for t in f.transactions if t.code == "S"]
    assert sum(t.shares for t in sales) == 62650
    assert all(t.planned_10b5_1 for t in sales)
    assert all(t.transaction_date == date(2026, 3, 20) for t in sales)
    assert [t for t in sales if t.ownership == "D"][-1].post_shares == 881387
    assert sales[-1].post_shares == 712934  # Separate LLC bucket, not total ownership.


def test_actual_stevens_not_liquidated():
    f = _filing("0001199039-26-000012.xml", date(2026, 9, 2))
    assert sum(t.shares for t in f.transactions) == 1848501
    assert f.transactions[0].transaction_date == date(2026, 8, 31)
    assert f.transactions[-1].post_shares == 3358770
    assert f.holdings[0]["shares"] == 11544612
    assert not f.liquidation_claim_supported()


def test_09_weekends_holidays_and_early_close():
    assert session_state(datetime(2026, 10, 25, 15, tzinfo=UTC))["phase"] == "WEEKEND"
    assert session_state(datetime(2026, 12, 25, 15, tzinfo=UTC))["phase"] == "HOLIDAY"
    assert session_state(datetime(2026, 11, 27, 19, tzinfo=UTC))["phase"] == "AFTER_HOURS"


def bars():
    sessions = xcals.get_calendar("XNYS").sessions_in_range("2025-10-01", "2026-10-27")
    close = 100 + np.arange(len(sessions)) * .1
    return pd.DataFrame({"Date": sessions, "Open": close, "High": close + 1, "Low": close - 1,
                         "Close": close, "Volume": np.full(len(sessions), 1000)})


def test_10_incomplete_candle_excluded():
    data = bars()
    data.loc[len(data) - 1, ["Open", "High", "Low", "Close", "Volume"]] = [1000, 1001, 999, 1000, 1000000]
    clean = complete_bars(data, NOW)
    assert str(clean.date.iloc[-1]) == "2026-10-26"
    result = indicators(data, NOW)
    assert not result["breakout"]
    assert result["values"]["sma_200"] == pytest.approx(clean.close.tail(200).mean())
    assert result["values"]["rsi_14"] == 100
    assert result["values"]["atr_14"] == pytest.approx(2)
    assert indicators(data, NOW)["input_sha256"] == result["input_sha256"]


def test_11_conflicting_indicators():
    result = compare_indicator(-2.66, 2.66)
    assert result["conflict"] and not result["confirmed"]
    assert result["external"] == 2.66 and result["local"] == -2.66


def plan(**kw):
    return TradePlan(**{"action": "NEW_LONG", "entry": 100, "stop": 90, "target": 120, "equity": 100000,
                       "quantity": 50, "atr": 5, **kw})


def test_12_stop_above_long_entry():
    with pytest.raises(ValidationError):
        plan(stop=105)


def test_13_negative_reward_and_costs():
    with pytest.raises(ValidationError):
        plan(target=95)
    result = evaluate_plan(plan(target=100.1))
    assert not result["valid"] and result["net_reward_risk"] < 0
    valid = evaluate_plan(plan())
    assert valid["reward_risk"] == 2
    assert valid["break_even_win_rate_before_costs"] == pytest.approx(1 / 3)


def test_14_news_without_source_and_overreach(store):
    c = NewsClaim(source_id="missing", quote="partnership", assertion="exclusive supplier", kind="exclusive_supplier")
    assert validate_news(c, store.sources)["status"] == "UNVERIFIED"
    source = store.sources["sec"].model_copy(update={"excerpt": "A announced a partnership with B."})
    c = NewsClaim(source_id="sec", quote=source.excerpt, assertion="B captured 30% market share.", kind="market_share")
    assert validate_news(c, {"sec": source})["status"] == "UNVERIFIED"


def test_original_news_passages_and_unfounded_market_share():
    from tradingagents.integrity.news import visible_text

    manifest = json.loads((FIXTURES / "news_manifest.json").read_text())
    assert len(manifest["files"]) == 2
    for entry in manifest["files"]:
        raw = (FIXTURES / entry["name"]).read_bytes()
        assert digest(raw) == entry["sha256"]
        body = visible_text(raw.decode())
        assert all(q in body for q in entry["quotes"])
    assert "30% market share" not in visible_text((FIXTURES / "amd_meta_announcement.html").read_text())


def test_15_missing_sentiment_not_signal():
    result = SentimentSample(provider="StockTwits", available=False, sample_size=0).summary()
    assert result["signal"] is None and result["status"] == "UNAVAILABLE"


def test_16_contradiction_not_reused(store):
    f = fact(store, "revenue", 100, status=Status.CONTRADICTED)
    assert "evidence_CONTRADICTED" in store.check_claim(claim(f))
    assert validate_decision(store, "BUY", None, [])["outcome"] == "INSUFFICIENT_DATA"


def test_17_stale_not_current(store):
    f = fact(store, "price", 100, observed_at=NOW - timedelta(days=10))
    store.expire({"price": timedelta(days=3)})
    assert store.facts[f.id].status == Status.STALE
    assert store.check_claim(claim(f))


@pytest.mark.parametrize("changes", [{"unit": "USD millions"}, {"currency": "HKD"}, {"period_end": date(2026, 10, 25)}])
def test_18_incompatible_currency_units_periods(store, changes):
    fact(store, "gross_profit", 75)
    fact(store, "revenue", 100, **changes)
    with pytest.raises(ValueError):
        calculate(store, "gross_margin", ["gross_profit", "revenue"])


def test_19_uncalibrated_confidence(store):
    safe, errors = gate_text("**Rating:** 4.2/5; win probability 85%", "manager", store)
    assert errors and "85" not in safe and "4.2" not in safe


def test_20_provider_failure_no_fallback():
    result = from_snapshot("NVDA", NOW, {"files": [], "gaps": ["SEC HTTP 403"], "retrieved_at": NOW.isoformat()})
    assert not result["evidence"]["facts"]
    store = EvidenceStore.model_validate(result["evidence"])
    assert validate_decision(store, "BUY", None, [])["outcome"] == "INSUFFICIENT_DATA"


def test_actual_fixture_hashes():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert len(manifest["files"]) >= 5
    for f in manifest["files"]:
        assert digest((FIXTURES / f["file"]).read_bytes()) == f["sha256"]


def test_future_announcement_not_known(store):
    f = fact(store, "revenue", 100, available_at=NOW + timedelta(seconds=1))
    assert f.status == Status.UNAVAILABLE


def test_conflicts_preserve_both(store):
    fact(store, "revenue", 100, id="original")
    fact(store, "revenue", 110, id="amended")
    assert len(store.facts) == 2
    assert all(f.status == Status.CONTRADICTED for f in store.facts.values())


def test_distinct_insider_tranches_are_not_conflicting_measurements(store):
    fact(store, "insider_transaction_shares", 100, id="tx1", scope="filing:transaction1")
    fact(store, "insider_transaction_shares", 200, id="tx2", scope="filing:transaction2")
    assert all(f.status == Status.VERIFIED for f in store.facts.values())


def test_exact_claim_accepted_but_wrong_number_blocked(store):
    f = fact(store, "revenue", 100)
    assert not store.check_claim(claim(f))
    assert store.check_claim(claim(f, value=1000))
    text = json.dumps({"claims": [claim(f).model_dump(mode="json")]})
    state = {"evidence": store.model_dump(mode="json"), "verification_mode": "strict", "fundamentals_report": text,
             "market_report": "institutions definitely selling", "news_report": "", "sentiment_report": ""}
    result = analyst_gate(state)
    assert "FACT revenue=100" in result["fundamentals_report"]
    assert "institutions" not in result["market_report"]
    assert result["quarantined_outputs"]


def test_valid_complete_evidence_can_support_research_plan(store):
    for metric in ("price", "revenue", "net_income", "operating_cash_flow"):
        fact(store, metric, 100, observed_at=NOW - timedelta(minutes=1))
    fact(store, "atr_14", 5, unit="indicator", currency=None)
    data = plan(evidence_ids=["price", "atr_14"]).model_dump()
    result = validate_decision(store, "BUY", data, [])
    assert result["outcome"] == "BUY" and result["signal_actionable"]
    assert not result["execution_enabled"]
    assert validate_decision(store, "HOLD", None, [])["outcome"] == "HOLD"
    assert validate_decision(store, "BUY", None, [])["outcome"] == "WATCHLIST"
    assert validate_decision(store, "BUY", {**data, "stop": 105}, [])["outcome"] == "WATCHLIST"
    assert validate_decision(store, "BUY", {**data, "atr": 1}, [])["outcome"] == "WATCHLIST"


def test_missing_sessions_not_silently_filled():
    with pytest.raises(ValueError, match="missing completed"):
        indicators(bars().drop(index=20), NOW)


def test_flat_indicator_analytic_oracle():
    data = bars()
    data[["Open", "High", "Low", "Close"]] = 100.
    result = indicators(data, NOW)["values"]
    assert result["rsi_14"] == 50
    assert result["macd_12_26"] == result["macd_signal_9"] == result["atr_14"] == 0
    assert result["bollinger_upper"] == result["bollinger_lower"] == result["ema_20"] == 100


def test_syndicated_sources_do_not_corroborate(store):
    store.sources["mirror"] = store.sources["sec"].model_copy(update={"id": "mirror"})
    f = fact(store, "revenue", 100, source_ids=["sec", "mirror"], status=Status.CORROBORATED)
    assert f.status == Status.UNVERIFIED


def test_future_quote_and_tampered_capture_are_not_verified():
    snapshot = {"retrieved_at": NOW.isoformat(), "files": [{
        "name": "fake.html", "content": "<p>Revenue 100</p>", "sha256": "0" * 64,
        "url": "https://www.sec.gov/fiction.html", "provider": "SEC",
        "published_at": (NOW + timedelta(days=1)).isoformat(), "quotes": ["Revenue 100"],
    }]}
    result = from_snapshot("NVDA", NOW, snapshot)
    assert not result["evidence"]["facts"]
    assert result["evidence"]["gaps"][0].startswith("snapshot_hash_mismatch")


def test_reduction_and_exit_not_short():
    with pytest.raises(ValidationError):
        plan(action="REDUCE", existing_quantity=0, quantity=5)
    assert evaluate_plan(plan(action="REDUCE", existing_quantity=100, quantity=35))["reward_risk"] is None
    with pytest.raises(ValidationError):
        plan(action="EXIT", existing_quantity=100, quantity=35)


def test_amendment_not_new_sale():
    raw = (FIXTURES / "0001199039-26-000012.xml").read_bytes().replace(b"<documentType>4</documentType>", b"<documentType>4/A</documentType>")
    filing = parse_ownership(raw, date(2026, 9, 3), "https://www.sec.gov/amendment.xml")
    assert filing.amendment  # Synthetic amendment mutation of an actual SEC sample.


def test_out_of_sample_score_rejects_lookahead():
    from tradingagents.integrity.evaluation import HistoricalObservation, score_observations

    data = {
        "signal_at": NOW, "latest_evidence_available_at": NOW - timedelta(days=1),
        "entered_at": NOW + timedelta(days=1), "exited_at": NOW + timedelta(days=2),
        "entry_rule": "next session open", "exit_rule": "one session later",
        "execution_assumption": "explicit fills with costs and slippage",
        "entry": 100, "exit": 110, "quantity": 10, "costs": 2, "slippage": 3, "benchmark_return": .01,
    }
    record = HistoricalObservation(**data)
    score = score_observations([record], 10000, NOW - timedelta(days=1))
    assert score["net_pnl"] == 95 and score["sample_size"] == 1
    assert score["historical_win_rate"] == 1
    with pytest.raises(ValidationError, match="look-ahead"):
        HistoricalObservation(**{**data, "latest_evidence_available_at": NOW + timedelta(seconds=1)})
    with pytest.raises(ValueError, match="out-of-sample"):
        score_observations([record], 10000, NOW)
    assert score_observations([], 10000, NOW)["historical_win_rate"] == "NOT ESTABLISHED"
