"""Offline verification/report generation. Does not call a model or execute a trade."""

import argparse
import json
import resource
import time
from datetime import datetime
from pathlib import Path

from .collect import from_snapshot, read_snapshot
from .evidence import EvidenceStore, digest
from .gates import gate_text, validate_decision
from .report import write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--baseline-report", help="Optional original report to quarantine and compare")
    args = parser.parse_args()
    started = time.perf_counter()
    snapshot = read_snapshot(args.snapshot)
    state = from_snapshot(snapshot["ticker"], datetime.fromisoformat(snapshot["as_of"]), snapshot)
    store = EvidenceStore.model_validate(state["evidence"])
    state["quarantined_outputs"], state["claim_audit"] = [], []
    baseline = None
    if args.baseline_report:
        raw = Path(args.baseline_report).read_bytes()
        text = raw.decode()
        _, errors = gate_text(text, "legacy_report", store)
        state["claim_audit"] = errors
        state["quarantined_outputs"] = [{"agent": "legacy_report", "raw": text}]
        baseline = {"sha256": digest(raw), "bytes": len(raw), "original_recommendation": "Underweight",
                    "reported_runtime_minutes": 31.5, "exact_replay_available": False,
                    "original_tokens_and_peak_memory": None,
                    "limitation": "Original raw tool responses, prompt transcripts and sampling state not captured."}
    state["evidence"] = store.model_dump(mode="json")
    state["decision_validation"] = validate_decision(store, "WATCHLIST", None, state["claim_audit"])
    path = write(state, snapshot["ticker"], args.out)
    comparison = {
        "baseline": baseline,
        "upgraded": {"decision": state["decision_validation"], "facts": len(store.facts),
                     "sources": len(store.sources), "raw_llm_calls": 0, "llm_tokens": 0,
                     "runtime_seconds": time.perf_counter() - started,
                     "python_maxrss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
        "comparison_type": "deterministic revalidation of a reconstructed historical snapshot, not a repeat of the stochastic multi-agent run",
        "agent_agreement": "Not measured; repetition is not independent evidence",
    }
    (Path(args.out) / "comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
    print(path)
    print(state["decision_validation"]["outcome"])


if __name__ == "__main__":
    main()
