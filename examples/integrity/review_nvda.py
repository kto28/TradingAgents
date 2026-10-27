"""Reproduce specific NVDA corrections from the captured SEC evidence, not model guesses."""

import json
from datetime import datetime
from pathlib import Path

from tradingagents.integrity.collect import from_snapshot, read_snapshot
from tradingagents.integrity.evidence import EvidenceStore
from tradingagents.integrity.financials import calculate

ROOT = Path(__file__).resolve().parent


def main():
    snapshot = read_snapshot(ROOT / "nvda_snapshot.json")
    data = from_snapshot("NVDA", datetime.fromisoformat(snapshot["as_of"]), snapshot)
    store = EvidenceStore.model_validate(data["evidence"])

    def find(metric, start, end):
        matches = [f for f in store.facts.values() if f.metric == metric
                   and str(f.period_start) == start and str(f.period_end) == end]
        return max(matches, key=lambda f: f.available_at)

    revenue = find("revenue", "2026-04-27", "2026-07-26")
    prior = find("revenue", "2025-04-28", "2025-07-27")
    growth = calculate(store, "yoy_growth", [revenue.id, prior.id])
    # Older comparator can be STALE for current valuation yet valid as an explicitly historical input.
    gross = find("gross_profit", "2026-04-27", "2026-07-26")
    assets = find("assets", "None", "2026-07-26")
    cfo = find("operating_cash_flow", "2026-01-26", "2026-07-26")
    productive = find("productive_asset_purchases", "2026-01-26", "2026-07-26")
    observations = [
        {"claim": "Revenue 96.221B USD", "status": "VERIFIED", "value": revenue.value,
         "evidence_ids": [revenue.id]},
        {"claim": "Quarter described as calendar 2026 Q3", "status": "CONTRADICTED",
         "correction": "2026-04-27 through 2026-07-26; filing FY2027 Q2, accession 0001045810-26-000075",
         "evidence_ids": [revenue.id]},
        {"claim": "Revenue YoY +47%", "status": "CONTRADICTED", "calculated_percent": growth.value,
         "evidence_ids": [revenue.id, prior.id], "method": "(current/prior - 1)*100, matching fiscal durations"},
        {"claim": "Gross margin 63.66% attached to current quarterly results", "status": "CONTRADICTED",
         "calculated_percent": float(gross.value) / float(revenue.value) * 100,
         "evidence_ids": [gross.id, revenue.id]},
        {"claim": "Assets 320.27 億 USD", "status": "CONTRADICTED",
         "source_base_usd": assets.value, "correct_yi_usd": float(assets.value) / 100_000_000,
         "evidence_ids": [assets.id]},
        {"claim": "FCF 47.006B attributed to 2026-07-26 cash-flow period", "status": "UNVERIFIED",
         "consistent_ytd_cfo_less_productive_asset_purchases": float(cfo.value) - float(productive.value),
         "period": "2026-01-26 / 2026-07-26",
         "limitation": "Broader productive-asset-purchases definition disclosed; do not mix quarterly, YTD and TTM FCF.",
         "evidence_ids": [cfo.id, productive.id]},
        {"claim": "45% of FCF consists of receivables", "status": "CONTRADICTED",
         "correction": "Definition error: receivables are a balance-sheet asset, not a component of the FCF cash-flow formula."},
        {"claim": "JPMorgan 2026-10-10 cut 2027 growth from 47% to 35%", "status": "UNVERIFIED",
         "correction": "No retrieved original document. Cannot establish whether such a report exists; citation is blocked."},
        {"claim": "Huang March transfers are new awards/bullish purchases", "status": "CONTRADICTED",
         "source": "0001197649-26-000005.xml", "correction": "F tax withholding; G trust transfers documented in footnotes."},
        {"claim": "Kress March sale shows unplanned bearish timing", "status": "UNVERIFIED",
         "source": "0001588670-26-000010.xml", "correction": "62,650 shares sold under disclosed 10b5-1 plan; motive not established."},
        {"claim": "Stevens liquidated all holdings", "status": "CONTRADICTED",
         "source": "0001199039-26-000012.xml",
         "correction": "Remaining sale-trust shares 3,358,770; directly held 11,544,612; Envy Trust 15,017,750. Sale price is not cost basis."},
        {"claim": "2026-10-27 daily candle confirms signal", "status": "UNVERIFIED",
         "correction": "Report clock interpreted as 11:17:23 New York; session incomplete. Last completed session 2026-10-26."},
        {"claim": "4.2/5 confidence and PEG 0.26 implies 74% undervaluation", "status": "UNVERIFIED",
         "correction": "No calibration or valuation model establishes either conclusion."},
    ]
    (ROOT / "nvda_claim_review.json").write_text(json.dumps({
        "scope": "Selected material claims, not an exhaustive semantic audit",
        "observations": observations,
    }, ensure_ascii=False, indent=2) + "\n")
    for row in observations:
        print(row["status"], row["claim"])


if __name__ == "__main__":
    main()
