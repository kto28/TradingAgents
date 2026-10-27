"""Unit/period-aware calculations. Inputs are base units, never formatted 'millions'."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from .evidence import EvidenceStore, Fact, Source, Status, digest, utc_now

TAGS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "eps": ("EarningsPerShareDiluted",),
    "shares_outstanding": ("CommonStockSharesOutstanding",),
    "weighted_diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "equity": ("StockholdersEquity",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "productive_asset_purchases": ("PaymentsToAcquireProductiveAssets",),
    "current_debt": ("LongTermDebtCurrent",),
    "noncurrent_debt": ("LongTermDebtNoncurrent",),
    "accounts_receivable": ("AccountsReceivableNetCurrent",),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
}


def sec_facts(payload: dict, raw: bytes, store: EvidenceStore, ticker: str, url: str, retrieved=None):
    """Preserve XBRL accession, units, durations and filing knowledge dates.

    SEC's fy/fp identify the *filing*, not necessarily each comparative fact's
    fiscal period. Retain those as document metadata; never relabel a prior
    quarter using the filing's fp. Filing-date-only knowledge uses end of day
    New York conservatively (no intraday lookahead).
    """
    from zoneinfo import ZoneInfo

    retrieved = retrieved or utc_now()
    namespaces = payload.get("facts", {})
    for metric, tags in TAGS.items():
        for tag in tags:
            obj = namespaces.get("us-gaap", {}).get(tag) or namespaces.get("dei", {}).get(tag, {})
            for unit, rows in obj.get("units", {}).items():
                eligible = [r for r in rows if r.get("form") in {"10-K", "10-Q", "10-K/A", "10-Q/A"}
                            and r.get("filed", "9999") <= store.as_of.date().isoformat()]
                # Latest reporting period per duration, plus prior-year comparators.
                for row in eligible:
                    if not row.get("accn") or not row.get("end"):
                        continue
                    end = date.fromisoformat(row["end"])
                    if (store.as_of.date() - end).days > 800:
                        continue
                    filed = datetime.fromisoformat(row["filed"] + "T23:59:59").replace(
                        tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
                    sid = row["accn"]
                    store.sources[sid] = Source(
                        id=sid, provider="SEC EDGAR", url=f"https://www.sec.gov/Archives/edgar/data/{int(payload['cik'])}/{sid.replace('-', '')}/{sid}-index.html",
                        document=f"{sid}; {row['form']}; filing fy={row.get('fy')} fp={row.get('fp')}; {url}",
                        published_at=filed, retrieved_at=retrieved, sha256=digest(raw),
                        origin="SEC:" + str(payload["cik"]), kind="primary",
                        timestamp_precision="date_only",
                        excerpt=f"companyfacts/{tag}/{unit}; accession {sid}",
                    )
                    start = date.fromisoformat(row["start"]) if row.get("start") else None
                    fid = f"{metric}:{unit}:{start}:{end}:{sid}:{tag}"
                    store.add(Fact(
                        id=fid, ticker=ticker, metric=metric, value=row["val"], unit=unit,
                        currency="USD" if unit.startswith("USD") else None,
                        period_start=start, period_end=end,
                        fiscal_period=f"{start or 'instant'} / {end}",
                        observed_at=datetime.combine(end, datetime.min.time(), UTC),
                        available_at=filed, retrieved_at=retrieved, source_ids=[sid],
                        status=Status.VERIFIED, method="sec_xbrl",
                    ))


def calculate(store: EvidenceStore, metric: str, inputs: list[str]) -> Fact:
    fs = [store.facts[i] for i in inputs]
    if len(fs) != 2:
        raise ValueError("Two explicit input records required")
    a, b = fs
    if a.ticker != b.ticker or a.currency != b.currency and metric not in {"market_cap", "calculated_eps", "peg"}:
        raise ValueError("incompatible ticker/currency")
    same_period = (a.period_start, a.period_end) == (b.period_start, b.period_end)
    if metric not in {"yoy_growth", "market_cap", "pe", "forward_pe", "peg"} and not same_period:
        raise ValueError("incompatible reporting periods")
    formulas = {
        "gross_margin": ("gross_profit", "revenue"),
        "operating_margin": ("operating_income", "revenue"),
        "free_cash_flow": ("operating_cash_flow", "capital_expenditure"),
        "free_cash_flow_after_productive_assets": ("operating_cash_flow", "productive_asset_purchases"),
        "total_debt": ("current_debt", "noncurrent_debt"),
        "debt_ratio": ("total_debt", "assets"),
        "debt_equity": ("total_debt", "equity"),
        "liabilities_to_assets": ("liabilities", "assets"),
        "current_ratio": ("current_assets", "current_liabilities"),
        "market_cap": ("price", "shares_outstanding"),
        "pe": ("price", "eps_ttm"),
        "forward_pe": ("price", "eps_forward"),
        "peg": ("forward_pe", "growth_estimate_percent"),
        "calculated_eps": ("net_income", "weighted_diluted_shares"),
    }
    if metric == "yoy_growth":
        if a.metric != b.metric or not a.period_start or not b.period_start:
            raise ValueError("YoY requires matching duration metrics")
        if not 350 <= (a.period_end - b.period_end).days <= 380 or abs(
            (a.period_end - a.period_start).days - (b.period_end - b.period_start).days
        ) > 7:
            raise ValueError("YoY requires comparable fiscal durations a year apart")
    elif formulas.get(metric) != (a.metric, b.metric):
        raise ValueError("wrong formula inputs; receivables are not free cash flow")
    if metric in {"market_cap", "pe", "forward_pe", "peg"} and a.observed_at != b.observed_at:
        raise ValueError("valuation inputs need an explicit common valuation timestamp")
    x, y = float(a.value), float(b.value)
    if metric not in {"market_cap", "free_cash_flow", "free_cash_flow_after_productive_assets", "total_debt"} and y <= 0:
        raise ValueError("ratio undefined for non-positive denominator")
    if metric == "market_cap":
        if a.unit != "USD/share" or a.currency != "USD" or b.unit != "shares":
            raise ValueError("market cap needs price per share and share count in base units")
        value, unit = x * y, "USD"
    elif metric in {"free_cash_flow", "free_cash_flow_after_productive_assets", "total_debt"}:
        if a.unit != b.unit or y < 0:
            raise ValueError("capex must be a positive cash outflow in matching units")
        value, unit = (x + y if metric == "total_debt" else x - y), a.unit
    elif metric == "calculated_eps":
        if a.unit != "USD" or a.currency != "USD" or b.unit != "shares":
            raise ValueError("EPS needs net income and weighted diluted shares")
        value, unit = x / y, "USD/share"
    else:
        if metric in {"pe", "forward_pe"} and (
            a.unit not in {"USD/share", "USD/shares"}
            or b.unit not in {"USD/share", "USD/shares"} or a.currency != "USD"
        ):
            raise ValueError("P/E requires same-currency per-share price and EPS")
        if metric == "peg" and (a.unit != "ratio" or b.unit != "%"):
            raise ValueError("PEG requires a P/E ratio and growth in percentage points")
        if metric not in {"pe", "forward_pe", "peg"} and a.unit != b.unit:
            raise ValueError("incompatible units")
        value = (x / y - 1) * 100 if metric == "yoy_growth" else x / y
        unit = "%" if metric == "yoy_growth" else "ratio"
    return store.add(Fact(
        id=f"{metric}:" + digest("|".join(inputs).encode())[:16], ticker=a.ticker,
        metric=metric, value=value, unit=unit, currency="USD" if unit.startswith("USD") else None,
        period_start=a.period_start, period_end=a.period_end, fiscal_period=a.fiscal_period,
        observed_at=max(f.observed_at for f in fs), available_at=max(f.available_at for f in fs),
        retrieved_at=utc_now(), source_ids=sorted({s for f in fs for s in f.source_ids}),
        inputs=inputs, nature="calculated", status=Status.VERIFIED, method="formula",
        issues=["PEG alone is not an undervaluation test"] if metric == "peg" else [],
    ))


def reconcile(value: float, expected: float, relative_tolerance: float = .01) -> bool:
    return abs(value - expected) <= max(abs(expected) * relative_tolerance, 1e-9)


def validate_fiscal_period(fact: Fact, start: date, end: date) -> bool:
    return fact.period_start == start and fact.period_end == end


def freshness(store: EvidenceStore):
    store.expire({metric: timedelta(days=180) for metric in TAGS})


def derive_financials(store: EvidenceStore):
    """Compute only explicitly compatible facts; missing inputs remain missing."""
    for metric, left, right in (
        ("gross_margin", "gross_profit", "revenue"),
        ("operating_margin", "operating_income", "revenue"),
        ("free_cash_flow", "operating_cash_flow", "capital_expenditure"),
        ("free_cash_flow_after_productive_assets", "operating_cash_flow", "productive_asset_purchases"),
        ("total_debt", "current_debt", "noncurrent_debt"),
        ("debt_ratio", "total_debt", "assets"),
        ("debt_equity", "total_debt", "equity"),
        ("liabilities_to_assets", "liabilities", "assets"),
        ("current_ratio", "current_assets", "current_liabilities"),
        ("calculated_eps", "net_income", "weighted_diluted_shares"),
    ):
        lhs = sorted((f for f in store.facts.values() if f.metric == left and f.status == Status.VERIFIED),
                     key=lambda f: (f.observed_at, f.available_at), reverse=True)
        rhs = [f for f in store.facts.values() if f.metric == right and f.status == Status.VERIFIED]
        if not lhs:
            continue
        a = lhs[0]
        b = next((b for b in rhs if (a.period_start, a.period_end) == (b.period_start, b.period_end)), None)
        if b:
            calculate(store, metric, [a.id, b.id])
