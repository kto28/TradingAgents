# Architecture and NVDA integrity audit

## Inspected baseline

- Upstream checkout: `c454491`, TradingAgents 0.7.1.
- Existing local additions: `run_notify.py`, `AGENTS.md`, private ignored `.env`.
  These were preserved in a separate baseline commit before feature changes.
- Python 3.13 environment managed by uv. Initial inspected packages included
  Pydantic 2.14.1, pandas 3.1.0, LangGraph 1.2.18 and yfinance 1.7.0.
- Hardware: Apple M4 Max, 137,438,953,472 bytes RAM (128 GiB).
- Ollama reported installed tags `qwen3.8:27b` (digest prefix `22130167c4c2`),
  `qwen3:30b` (`ad815644918f`) and `qwen3:8b` (`500a1f067a9f`).
  No model or debate-round change was made.
- Existing package was initially installed non-editably. Development now uses
  `uv pip install -e '.[dev]'`, so CLI and local module imports use the same code.

## Existing execution path

| Responsibility | Existing modules | Audit finding |
|---|---|---|
| Configuration | `default_config.py`, `dataflows/config.py`, `.env` | Run-scoped config supports env overrides; retain it |
| Tools/provider routing | `agents/tools.py`, `dataflows/router.py` | Dates are injected, but formatted strings lose machine-readable provenance |
| Prices/indicators | `vendors/yahoo/ohlcv.py`, `snapshot.py`, `market.py` | Existing deterministic stockstats snapshot is useful; naming it “verified” does not independently verify vendor prices |
| Statements | `vendors/sec_edgar.py`, `vendors/yahoo/fundamentals.py` | SEC adapter filters by filing date, but rendering drops accession and per-cell source identifiers |
| News/social | Yahoo news, StockTwits, Reddit, FRED, Polymarket vendors | Tool gaps already surfaced; downstream prose can still infer unsupported sentiment/statistics |
| Analyst execution | `graph/setup.py`, `graph/analyst_execution.py` | Four private tool subgraphs run in parallel |
| Shared state | `agents/state.py` | Primarily free-form reports/history; no central evidence ledger |
| Debate/risk | `agents/researchers/*`, `agents/risk_mgmt/*` | Prompts reward advocacy; new “facts” can appear without retrieving evidence |
| Managers/trader | `agents/schemas.py`, `agents/structured.py` | Structured response fallback permits unvalidated prose; schema shape is not factual verification |
| Final decision | `agents/rating.py`, portfolio manager | Parses rating, but does not independently validate thesis or numeric plan |
| Memory | `memory/*` | Repetition/previous output can transmit unverified reasoning |
| Reports | `reporting.py`, `report_html.py` | Concatenates narrative; reader cannot trace each number to original evidence |
| Local workflow | `run_notify.py` → `TradingAgentsGraph.propagate()` | Telegram summary/report plus 600-second stage notifications |
| CLI | `cli/run.py` → `stream_run()` | Uses a separate streaming path; gates therefore belong in the graph, not only a Python runner |
| Evaluation | `backtest.py` | Decision scoring exists; not an execution simulator or calibrated trade win-rate system |

Initial targeted upstream baseline: **161 passed** across SEC, fundamentals
units, snapshots, ratings, structured agents and reporting. These tests checked
existing code contracts, not the factual correctness of the generated report.

## Independently established findings

The supplied report is retained as an explicitly untrusted artifact in the
example's `quarantined_outputs.json`; its SHA-256 is in `comparison.json`.
Selected findings are reproducible with `examples/integrity/review_nvda.py`.

1. **Revenue is not wholly fabricated.** SEC companyfacts links the
   $96,221,000,000 quarterly revenue to accession `0001045810-26-000075`,
   period 2026-04-27 through 2026-07-26. The filing labels FY2027 Q2.
   The report's “2026 Q3” attribution is wrong.
2. **Growth is inconsistent.** The same filing's comparative revenue is
   $46,743,000,000 for 2025-04-28 through 2025-07-27.
   `(96.221 / 46.743 - 1) × 100 = 105.8511%`, not 47%.
3. **Margin mixes definitions/periods.** Quarterly gross profit $72.142B divided
   by quarterly revenue $96.221B gives 74.9753%, not the 63.66% attached to the
   current financial discussion. No assumption is made that a vendor's
   different TTM margin necessarily has the same period.
4. **Unit conversion is materially wrong for assets.** SEC reports
   $320.272B, or 3,202.72 億 USD; the report says 320.27 億.
   The market-cap passage also suggests a magnitude issue, but the original
   raw Yahoo response was not retained, so its exact original market-cap
   reconciliation is not claimed. A separate factor-ten test proves the check.
5. **Cash-flow attribution is unsafe.** The comparable six-month SEC figures
   are $74.421B operating cash flow and $4.434B productive-asset purchases:
   subtraction gives $69.987B for that stated definition and period.
   This is not silently equated to a PP&E-only, quarterly or TTM FCF measure.
   “45% of FCF is receivables” is a financial-definition error.
6. **Huang:** original Form 4 `0001197649-26-000005` has March 18 tax withholding
   (F, 437,908 shares) and G transactions whose footnotes explain trust
   transfers/annuity termination. They are not new incentive grants or market
   purchases. Acquired/disposed codes refer to particular ownership buckets.
7. **Kress:** original Form 4 `0001588670-26-000010` reports March 20 sales
   totaling 62,650 shares under a disclosed 10b5-1 plan. The final direct
   bucket is 881,387 shares; separate trust/LLC buckets remain. A timing
   narrative about unplanned bearish intent is not established.
8. **Stevens:** original Form 4 `0001199039-26-000012` covers August 31 through
   September 2, filed September 2. Sales total 1,848,501 shares. Remaining
   sale-trust shares are 3,358,770, with 11,544,612 directly held and 15,017,750
   in another trust. “Sold everything” is contradicted. Transaction sale
   prices are not cost basis.
9. **Form 144:** `0001628280-26-060177` is a proposed disposal notice; its
   5,000,000 proposed shares cannot be treated as completed sales or added
   again to Form 4 transactions.
10. **Session errors:** 2026-10-25 was Sunday. Interpreting the original
    2026-10-27 23:17:23 report timestamp in the machine's Hong Kong timezone
    gives 11:17:23 New York: the October 27 daily candle was incomplete.
    The rebuilt daily calculations end October 26. The old artifact omitted
    its timezone, so this interpretation is explicitly disclosed.
11. **Unretrieved citations:** the JPMorgan October 10 report, a specific
    Register forecast, and “financial note page 17” were not backed by
    preserved retrieved documents. They are UNVERIFIED; the audit does not
    claim to prove those publications never existed.
12. **News implication drift:** Anthropic's original April 6 announcement
    establishes an agreement with Google/Broadcom for expected TPU capacity;
    AMD's February 24 SEC-filed announcement establishes a multi-generation
    Meta partnership for up to 6 GW. These passages do not establish an
    acquisition, exclusive supply, or a 30% market share. Later developments
    would require their own dated sources. The exact original passages are
    captured, hashed and included as attributed quotations.
13. **Unsupported confidence and interpretation:** a 4.2/5 score has no
    calibration; PEG 0.26 does not imply 74% undervaluation; negative MACD
    does not identify institutional sellers. These are blocked as assertions.

Original source URLs and hashes are in `tests/fixtures/integrity/manifest.json`
and `news_manifest.json`. Fixtures are downloaded source bytes, not LLM-written
filings. The amendment unit test explicitly labels its synthetic mutation of
an actual Form 4; it is not represented as another original filing.

## Root causes and changes

Data is now collected before analysts into `EvidenceStore` with timestamp,
unit, currency, period, source, nature, method and status. Exact structured
claims pass a **Fact Gate** before research begins. Downstream nodes also
quarantine newly introduced unvalidated text. Raw outputs and claim references
remain available for audit, but strict-mode prompts do not receive them.
The final **Decision Gate** independently checks required evidence and any
operator-supplied numeric research scenario.

The strict path excludes legacy memory because old reasoning is not verified
evidence. Structured model fields were extended compatibly; their default
empty evidence list preserves old schema clients. HOLD is not used as a
substitute for insufficient evidence: `INSUFFICIENT_DATA` is distinct from
`WATCHLIST`, and both are recognized as non-actionable by legacy review checks.

Reports are built deterministically in Traditional Chinese, with exact original
quotations and evidence IDs preserved. This is more restrictive than simply
adding a warning to a persuasive recommendation.

## Evaluation limits

The original stochastic run cannot be exactly replayed. Three different
comparisons are kept distinct:

- The supplied original report versus deterministic revalidation of captured
  historical evidence.
- Six short real-Ollama probes on identical SEC evidence.
- A real multi-agent strict replay on a frozen ledger, with live data tools
  disabled and a documented per-call output cap.

The small model benchmark found `qwen3.8:27b` correct on the seven checked
answer fields but invalid on the requested evidence IDs. `qwen3:30b` copied
gross profit into the gross-margin field. `qwen3:8b` returned 0.75, outside the
declared numerical tolerance, while citing valid evidence IDs. Results were
stable across two seeds in this tiny sample. All six passed the output-key
schema and rejected the invalid long plan. This is not a general model ranking
or a measured semantic hallucination rate.

The resulting revised recommendation is **INSUFFICIENT_DATA**, because the
current price is not independently verified and the old thesis contains
unvalidated material claims. It is neither a forced reversal nor an
endorsement of the old Underweight recommendation.

## Ollama token-limit compatibility discovered during validation

The first full local experiment was stopped after approximately 17 minutes:
the SDK serialized its requested 2,048-token limit as `max_completion_tokens`.
A direct test against the installed **Ollama 0.32.13** requested one output
token. `max_completion_tokens: 1` produced **651 tokens**; the same short prompt
with `max_tokens: 1` produced **1 token**, with finish reason `length`.
The observations are recorded in `examples/integrity/ollama_limit_probe.json`.

An Ollama-specific client subclass now remaps that field on the wire, including
per-invocation overrides. Other provider payloads are unchanged. The direct
endpoint probe established the accepted field; tests now check serialized
client payloads, not merely the configured attribute. The corrected full-run
requests reported 2,048 output tokens each. A separate one-token client probe
timed out while that full run occupied the server and is not counted as a pass.
The aborted full experiment is not counted as a completed validation run.
