"""Revalidate saved model output with current deterministic adapters, without another LLM call."""

import json
from datetime import datetime
from pathlib import Path

from tradingagents.integrity.collect import from_snapshot, read_snapshot
from tradingagents.integrity.evidence import EvidenceStore
from tradingagents.integrity.gates import gate_text, validate_decision
from tradingagents.integrity.report import write

root = Path(__file__).resolve().parent
output = root / "nvda_model_run"
snapshot = read_snapshot(root / "nvda_snapshot.json")
state = from_snapshot(snapshot["ticker"], datetime.fromisoformat(snapshot["as_of"]), snapshot)
store = EvidenceStore.model_validate(state["evidence"])
raw = json.loads((output / "quarantined_outputs.json").read_text())
audit = []
for item in raw:
    _, errors = gate_text(item["raw"], item["agent"], store)
    audit.extend(errors)
state.update(evidence=store.model_dump(mode="json"), quarantined_outputs=raw, claim_audit=audit)
state["decision_validation"] = validate_decision(store, "WATCHLIST", None, audit)
write(state, snapshot["ticker"], output)
print(state["decision_validation"]["outcome"])
