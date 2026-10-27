# Acceptance and regression matrix

Run `pytest -q tests/test_integrity.py tests/test_graph_end_to_end.py`.
All cases below are deterministic/offline. The report artifact is not the test
oracle: arithmetic, calendar rules and original SEC fixtures are the oracle.

| # | Required failure | Test | Expected result |
|---:|---|---|---|
| 1 | Market cap off by ten | `test_01_market_cap_factor_ten` | Recompute price × shares; reject mismatch |
| 2 | Revenue growth disagrees | `test_02_yoy_mismatch` | Recompute compatible YoY durations |
| 3 | Wrong fiscal quarter | `test_03_wrong_quarter` | Reject wrong date interval/label |
| 4 | Receivables counted in FCF | `test_04_receivables_not_fcf` | Reject invalid formula inputs |
| 5 | Unsupported growth forecast | `test_05_unsupported_growth_forecast` | Cannot become reported fact |
| 6 | Fabricated citation | `test_06_fabricated_research_citation` | Unknown evidence ID blocked |
| 7 | Trust transfers as purchases | `test_07_actual_huang_trust_transfers` | Actual G+footnotes → trust transfer |
| 8 | Form 144 as completed sale | `test_08_actual_form144_is_not_sale` | No completed transaction emitted |
| 9 | Weekend as regular session | `test_09_weekends_holidays_and_early_close` | Weekend/holiday/early-close calendar |
| 10 | Incomplete daily candle | `test_10_incomplete_candle_excluded` | Exclude it before calculations |
| 11 | Contradictory indicators | `test_11_conflicting_indicators` | Preserve values, no confirmed signal |
| 12 | Long stop above entry | `test_12_stop_above_long_entry` | Schema rejects plan |
| 13 | Negative reward/risk | `test_13_negative_reward_and_costs` | Reject direction/net reward |
| 14 | Unsourced material news | `test_14_news_without_source_and_overreach` | Missing source/semantic leap blocked |
| 15 | Missing sentiment as signal | `test_15_missing_sentiment_not_signal` | UNAVAILABLE, no directional signal |
| 16 | Reuse contradicted evidence | `test_16_contradiction_not_reused` | Claim and decision gate reject |
| 17 | Stale presented as current | `test_17_stale_not_current` | STALE cannot support current fact |
| 18 | Currency/unit/period mismatch | `test_18_incompatible_currency_units_periods` | Reject all three incompatibilities |
| 19 | Uncalibrated confidence | `test_19_uncalibrated_confidence` | Unsupported scores quarantined |
| 20 | Provider failure invents data | `test_20_provider_failure_no_fallback` | Empty facts and INSUFFICIENT_DATA |

Additional tests cover actual Kress and Stevens filings; exact source hashes;
original news passages; amended-form handling; future-announcement leakage;
conflicting primary records; positive exact-claim acceptance; ownership-bucket
semantics; reduction/exit vs short; out-of-sample chronology; and the entire
graph in invoke/stream and checkpoint configurations.

For a machine-readable result use:

```sh
pytest -q --junitxml=docs/integrity/test-results.xml
```

The final measured execution summary is recorded in `VALIDATION.md`. A passing
test proves that specific behavior on the stated input. It does not prove that
all financial statements, natural-language assertions, corporate actions or
web sources are covered.
