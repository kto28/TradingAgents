# Evidence integrity upgrade

This is a conservative research control layer on TradingAgents 0.7.1. It keeps
LangGraph, the existing analyst/debate/manager roles, Ollama, Markdown/HTML
reports and checkpoint support. It never submits orders.

The local machine's `.env` enables **strict** mode. The library default remains
`off` so existing integrations can migrate explicitly; `off` is the legacy
opinion-generating workflow and does not provide the new guarantees.

## Installation and modes

```sh
uv pip install -e '.[dev]'
source .venv/bin/activate

# Normal interactive analysis, with independent final validation
TRADINGAGENTS_VERIFICATION_MODE=audit tradingagents

# Quarantine unsupported claims BEFORE debate and at each subsequent agent
TRADINGAGENTS_VERIFICATION_MODE=strict tradingagents

# Existing Telegram entry point (same local models and debate rounds)
set -a; . ~/.config/devin/secrets.env; set +a
python run_notify.py NVDA 2026-10-27
```

`audit` preserves agent narrative for diagnosis, records failed claims and
still applies the final decision gate. `strict` replaces unsupported narrative
with UNKNOWN before downstream agents see it. Original text goes to a
quarantine sidecar; it is not presented as verified research in the final report.
`off` is available only for backwards compatibility/comparison.

Configuration:

| Environment variable | Meaning |
|---|---|
| `TRADINGAGENTS_VERIFICATION_MODE` | `off`, `audit`, `strict` |
| `TRADINGAGENTS_EVIDENCE_SNAPSHOT` | Optional trusted frozen capture manifest |
| `TRADINGAGENTS_DISPLAY_TIMEZONE` | Default `Asia/Hong_Kong` |
| `TRADINGAGENTS_RESEARCH_PLAN` | Optional operator-authored `TradePlan` JSON; never extracted from prose |
| `SEC_EDGAR_USER_AGENT` | SEC contact identity; no paid API needed |

Neither model IDs nor debate rounds were changed. Verified installed IDs:
`qwen3.8:27b`, `qwen3:30b`, alternative `qwen3:8b`. The human-readable
`qwen3.8:27b` tag reports Ollama family `qwen35`; the tag alone does not prove
upstream model lineage.

Ollama 0.32.13 was independently observed to ignore the SDK's
`max_completion_tokens` field. The Ollama adapter now sends `max_tokens`.
You can set `TRADINGAGENTS_MAX_TOKENS=4096` to bound output; this optional cap
does not change the selected model. Very small limits may truncate the evidence
JSON, which the gate treats as unverified rather than guessing missing fields.

## Frozen, reproducible analysis

Run without network access or model calls:

```sh
python -m tradingagents.integrity \
  --snapshot examples/integrity/nvda_snapshot.json \
  --out results/nvda_verified
```

Revalidate an original report as an additional untrusted artifact:

```sh
python -m tradingagents.integrity \
  --snapshot examples/integrity/nvda_snapshot.json \
  --baseline-report /path/to/complete_report.md \
  --out results/nvda_comparison
python examples/integrity/review_nvda.py
```

`comparison.json` distinguishes the old report's recorded elapsed time from
the new deterministic validation runtime. It does **not** pretend these are
equivalent computational workloads. The original raw tool responses, prompts,
sampling state and token accounting were not preserved.

Run the actual multi-agent Ollama workflow on the same frozen ledger:

```sh
python examples/integrity/run_frozen.py
```

This retains the original local models and one round of each debate, uses a
2,048 output-token cap per call for the experiment, and replaces analyst tools
with ledger-only prompts. Live identity lookup, news/social tools and legacy
memory are disabled for this strict replay. Managers and debaters still run.
This is a controlled experiment, not an exact reproduction of the original run.

Refresh public fixtures only when intentionally changing the dataset:

```sh
python examples/integrity/fetch_nvda.py
python examples/integrity/fetch_news.py
python examples/integrity/capture_nvda.py
```

SEC responses are public originals with SHA-256 manifests, accession numbers,
URLs and retrieval times. The OHLCV capture uses Yahoo's `auto_adjust=True`;
later corporate-action revisions cannot be undone by filtering dates. Freeze
both data and adjustment policy for a real historical backtest.

## Tests and model comparison

```sh
pytest -q
pytest -q tests/test_integrity.py tests/test_graph_end_to_end.py
ruff check .
python examples/integrity/benchmark_models.py --repeats 2
```

The benchmark sends the same frozen SEC facts to the three installed local
models, records exact field errors, arithmetic, source-ID validity, schema
compliance, trade-rule violations, tokens, duration and model residency.
It does not estimate a semantic unsupported-claim rate or investment win rate.
Its small sample does not justify changing production models.

## Trust boundary and limitations

- A model cannot create a VERIFIED record. Only the trusted adapters issue
  records from captured documents; gates compare exact metric, value, unit,
  currency, period and evidence IDs. Valid citation syntax alone is insufficient.
- A file hash proves capture integrity, not authenticity. Snapshot manifests
  and source classification are trusted operator inputs, **not untrusted model
  output**. Do not accept arbitrary model-generated snapshots as source evidence.
- SEC companyfacts preserves original accession, dates, base units, tags and
  duration. Filing-date-only data is made available at New York end of day.
  fy/fp describe a filing; comparative values keep their actual date intervals.
  Conflicting original records are both retained and blocked.
- Financial formula inputs must have compatible units, currencies and periods.
  `free_cash_flow_after_productive_assets` deliberately names its broader
  productive-assets definition instead of silently substituting PP&E capex.
  `liabilities_to_assets` is distinct from interest-bearing `debt_ratio`.
- The current live verified collectors cover SEC US-GAAP and Yahoo OHLCV.
  Yahoo is secondary and is **not independently verified**. Accordingly strict
  runs with only that quote source generally return `INSUFFICIENT_DATA`.
  This is a real limitation, not a reason to elevate it to VERIFIED.
- Live insider XML is supplied through a capture manifest, not automatically
  crawled for all issuers. Form 4/4-A and 144 parsers retain transaction codes,
  dates, ownership buckets, derivative flags and footnotes. Amendments are
  marked for reconciliation and are not automatically summed. P/S codes include
  private transactions; they alone do not prove an open-market execution.
- News validation proves a retrieved passage exists, not its economic truth.
  Captures can include original HTML, publication time, exact quote selectors
  and publisher metadata. The NVDA example includes Anthropic's original
  announcement and AMD's SEC-filed press release. A narrow primary-publisher
  allowlist and deterministic passage matching prevent model-assigned status.
  Explicit source classes are prioritized before retrieval/selection.
  The live graph does not automatically verify arbitrary contracts, forecasts or
  market-share claims. They remain unverified and cannot support a strict call.
  Source class assignment is an operator/adapter responsibility; general web
  discovery and paywalled report verification are not implemented.
- Missing social feeds have no directional signal. Sample counts do not imply
  representative sampling. The report exposes these gaps.
- The exact-record claim contract intentionally quarantines free-form prose,
  even when some of it may be correct. The strict report is narrower than the
  legacy narrative. Successful extraction does not validate hidden implications.
- The calendar implementation targets US equities via XNYS (also the relevant
  daily schedule for these NVDA examples). Non-US exchange/session support is
  not implemented in this integrity adapter; do not reuse it silently for crypto
  or other exchanges.
- `validate_decision` supports BUY, SELL, HOLD, WATCHLIST and INSUFFICIENT_DATA.
  BUY/SELL need verified material inputs and an explicitly supplied `TradePlan`,
  including source-backed reference price/ATR, costs, sizing and direction.
  Supply the plan using `TRADINGAGENTS_RESEARCH_PLAN`. The graph does not turn
  arbitrary legacy trader prose into that plan. Missing structured plans return
  WATCHLIST once data is sufficient.
  Stop/target/equity assumptions must come from an explicit research scenario,
  not invented performance statistics.
- `HistoricalObservation` and `score_observations` provide an out-of-sample,
  no-lookahead foundation with explicit entry/exit rules, fills, fees, slippage,
  benchmark returns, sample sizes, profit factor and closed-trade drawdown.
  This is not a calibrated track record or a portfolio execution simulator.

See [AUDIT.md](AUDIT.md), [ACCEPTANCE.md](ACCEPTANCE.md) and the checked-in
`examples/integrity/` artifacts for measured findings.
