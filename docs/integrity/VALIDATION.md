# Measured validation results

Final automated suite: **1,456 passed**, **100 subtests passed**, **1 skipped**,
**1 deselected**, in **10.42 seconds** on the local M4 Max environment.
The skip is the optional `langchain_aws`/Bedrock extra; the deselected test
requires an external integration. Existing warnings concern deliberately
unknown model aliases in provider tests.

`ruff check .` and `git diff --check` pass.

Machine-readable execution: [test-results.xml](test-results.xml).
Full command output: [pytest-results.txt](pytest-results.txt).

All **20 mandatory acceptance cases PASS** in this execution. The numbered
mapping is in [ACCEPTANCE.md](ACCEPTANCE.md); additional graph tests exercise
both invocation and streaming, with and without checkpointing. Positive
controls demonstrate that complete synthetic trusted evidence can produce
HOLD or a valid research BUY, while invalid plans become WATCHLIST and
missing material evidence becomes INSUFFICIENT_DATA. No test executes a trade.

## NVDA reconstruction

The frozen snapshot yields **380 evidence records from 15 source records**:
132 VERIFIED, 230 STALE and 18 UNVERIFIED. Historical comparative records
remain in the ledger; these counts are not a factual-accuracy percentage.
Distinct insider tranches have separate scopes and are not falsely classified
as contradictory measurements.

Of **13 selected material assertions** reviewed from the supplied report:

- 1 was verified as stated.
- 7 were contradicted by original evidence, calendar rules or financial definitions.
- 5 remained unverified.

This is a selected regression sample, not an exhaustive hallucination rate.
The script and exact evidence IDs are in
`examples/integrity/review_nvda.py` and `nvda_claim_review.json`.

The reconstructed report has all 13 requested sections, Traditional Chinese
prose, Markdown/HTML, dated original quotations, full evidence and audit
sidecars. Its outcome is **INSUFFICIENT_DATA**, not actionable. The independent
quote-source gap and unvalidated material legacy claims prevent a directional
recommendation.

The deterministic comparison used **zero model calls/tokens** and took
approximately **0.52 seconds** after data capture; Python max RSS was recorded
in `comparison.json` (macOS reports bytes). The old run's 31.5 minutes came
from its recorded execution log. These are different workloads; no speedup
claim is made for a full multi-agent analysis.

## Local model contract probes

Six real Ollama requests used the same frozen SEC values, two seeds per model.
Production models and debate counts were retained.

| Model | Checked-field error rate, each run | Exact requested citation IDs | Schema keys | Invalid long plan |
|---|---:|---|---|---|
| qwen3.8:27b | 0/7 | Failed both | Passed both | Rejected both |
| qwen3:30b | 1/7 | Failed both | Passed both | Rejected both |
| qwen3:8b | 1/7 | Passed both | Passed both | Rejected both |

The 30B response placed gross-profit dollars in a margin field. The 8B
response rounded the margin to 0.75, outside the stated tolerance; that is a
precision failure, not evidence of an invented source. Invalid citation IDs
mean failure of the exact-record contract, not proof that the underlying
publication does not exist.

Durations, input/output tokens, model residency and raw JSON responses are in
`examples/integrity/model_benchmark.json`. Post-request residency is not a
peak-memory measurement. Semantic unsupported-claim rate is explicitly **not
measured** by this small structured probe.

## Runtime-bound verification

On Ollama 0.32.13, requesting one token via `max_completion_tokens` returned
651 output tokens. The equivalent `max_tokens` request returned one token.
The Ollama-specific adapter now corrects the serialized field, with regression
tests covering explicit overrides and other-provider isolation.

The first full model experiment was stopped after approximately 17 minutes
because its configured bound had not actually applied. It is recorded as an
aborted experiment in `ollama_limit_probe.json`, not a successful run.

## Remaining limits

The live adapter does not independently corroborate Yahoo prices. Original
issuer documents are authoritative evidence of reported figures, not a proof
that management's accounting or forecasts are infallible. General semantic
fact checking, arbitrary paywalled citations, automatic insider amendment
reconciliation and non-US exchange calendars are not solved by these tests.
Full historical strategy calibration is still NOT ESTABLISHED.
