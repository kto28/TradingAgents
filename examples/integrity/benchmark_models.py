"""Small local model contract benchmark on the same frozen SEC evidence; not investment performance."""

import argparse
import json
import time
from pathlib import Path

import requests

from tradingagents.integrity.evidence import EvidenceStore, Status

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["qwen3.8:27b", "qwen3:30b", "qwen3:8b"])
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    store = EvidenceStore.model_validate_json((ROOT / "nvda_revised/evidence.json").read_text())
    available = [f for f in store.facts.values() if f.status == Status.VERIFIED and f.metric == "revenue"]
    revenue = max(available, key=lambda f: (f.period_end, f.period_start, f.available_at))
    gross = next(f for f in store.facts.values() if f.metric == "gross_profit" and f.status == Status.VERIFIED
                 and f.period_start == revenue.period_start and f.period_end == revenue.period_end)
    expected = {
        "revenue": revenue.value, "gross_margin": float(gross.value) / float(revenue.value),
        "huang_trust_transfer_is_purchase": False, "stevens_liquidated": False,
        "invalid_long_plan_accepted": False, "confidence": None, "decision": "INSUFFICIENT_DATA",
    }
    prompt = (
        "Use only this frozen evidence. Return one JSON object, no additional claims. "
        "Required keys: revenue (base USD), gross_margin (fraction calculated from evidence), "
        "huang_trust_transfer_is_purchase (bool), stevens_liquidated (bool), "
        "invalid_long_plan_accepted (bool), confidence (null unless calibrated), decision, source_ids (array). "
        "No independently verified current price is available. Choose BUY/SELL/HOLD/WATCHLIST/INSUFFICIENT_DATA. "
        "A proposed NEW_LONG has entry=100 stop=105 target=120: is it valid? "
        "There is no historical calibration. SEC Huang Form 4 0001197649-26-000005 shows G transfers "
        "between trusts, not purchases. SEC Stevens Form 4 0001199039-26-000012 shows 3,358,770 "
        "shares remaining in the sale trust plus 11,544,612 directly held and 15,017,750 in another trust. "
        "Cite only the two numeric evidence IDs below. Evidence:\n"
        + json.dumps([revenue.model_dump(mode="json"), gross.model_dump(mode="json")])
    )
    results = []
    for model in args.models:
        for repeat in range(args.repeats):
            start = time.perf_counter()
            response = requests.post("http://localhost:11434/api/chat", json={
                "model": model, "stream": False, "think": False, "format": "json",
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0, "seed": 42 + repeat, "num_predict": 768, "num_ctx": 8192},
            }, timeout=300)
            response.raise_for_status()
            payload = response.json()
            raw = payload.get("message", {}).get("content", "")
            try:
                answer = json.loads(raw)
                schema = isinstance(answer, dict) and set(answer) == set(expected) | {"source_ids"}
            except ValueError:
                answer, schema = {}, False
            errors = {}
            for key, value in expected.items():
                actual = answer.get(key)
                if isinstance(value, float):
                    correct = type(actual) in {float, int} and abs(actual - value) <= max(abs(value) * 1e-5, 1e-6)
                else:
                    correct = key in answer and type(actual) is type(value) and actual == value
                errors[key] = not correct
            citations = answer.get("source_ids", [])
            valid_citations = isinstance(citations, list) and bool(citations) and all(
                i in {revenue.id, gross.id} for i in citations)
            ps = requests.get("http://localhost:11434/api/ps", timeout=10).json()
            result = {
                "model": model, "repeat": repeat, "schema_compliant": schema,
                "field_error_rate": sum(errors.values()) / len(errors), "field_errors": errors,
                "citation_valid": valid_citations, "financial_calculation_correct": not errors["gross_margin"],
                "trade_rule_violations": int(errors["invalid_long_plan_accepted"]),
                "unsupported_fields": sorted(set(answer) - set(expected) - {"source_ids"}),
                "unsupported_claim_rate": None,  # Free-prose semantic claims are not scored by this harness.
                "wall_seconds": time.perf_counter() - start,
                "input_tokens": payload.get("prompt_eval_count"), "output_tokens": payload.get("eval_count"),
                "ollama_eval_nanoseconds": payload.get("eval_duration"),
                "loaded_model_memory_bytes": [{k: m.get(k) for k in ("name", "size", "size_vram")} for m in ps.get("models", [])],
                "response": answer,
            }
            results.append(result)
            print(model, repeat, result["field_error_rate"], round(result["wall_seconds"], 1), flush=True)
            (ROOT / "model_benchmark.json").write_text(json.dumps({
                "limitations": "Two tiny contract probes per model; not an accuracy guarantee, full research benchmark or measured semantic hallucination rate. Memory is post-request residency, not peak consumption.",
                "prompt": prompt, "expected": expected, "results": results,
            }, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
