"""Fail-closed deterministic gates. Fluent prose is not machine-verified evidence."""

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from .collect import collect
from .evidence import Claim, EvidenceStore, Status, utc_now
from .risk import TradePlan, evaluate_plan

INSTRUCTION = """
EVIDENCE CONTRACT (takes precedence over rhetorical role instructions):
Evaluate evidence quality, not persuasion. Never invent citations, statistics,
confidence scores, forecasts, insider motives or access to research documents.
Repetition is not independent corroboration. Receivables are not free cash flow.
PEG < 1 alone does not establish undervaluation. MACD/volume do not establish
institutional trading. Missing sentiment feeds mean UNKNOWN, never bullish/bearish.
Keep FACT, ESTIMATE, INFERENCE, HYPOTHESIS, UNKNOWN distinct.
Only the evidence ledger below can support FACT. Return a JSON object with
"claims": [{"label":"FACT", "metric":"revenue", "value":123, "unit":"USD",
"currency":"USD", "fiscal_period":"exact ledger period", "evidence_ids":["exact id"]}].
Use the exact ledger metric/value/unit/currency/fiscal_period. Do not add a claim
when evidence is unavailable. An empty claims array is allowed.
Free text and interpretations are quarantined and never become verified facts.
Models cannot assign evidence status. Forecasts are not reported fundamentals.
No numerical confidence or win rate without out-of-sample calibration.
"""


def compact_ledger(store: EvidenceStore) -> list[dict]:
    # Latest available period per metric/duration; retain conflicts in full evidence.json.
    chosen = {}
    for f in sorted(store.facts.values(), key=lambda x: (x.observed_at, x.available_at), reverse=True):
        duration = (f.period_end - f.period_start).days if f.period_end and f.period_start else 0
        key = f.metric, "quarter" if 70 <= duration <= 105 else "annual" if 350 <= duration <= 380 else duration
        if f.metric == "announcement_quote":
            key = f.metric, f.id
        if key not in chosen and not f.metric.startswith("insider_"):
            # Keep validation/citation fields in the prompt, full provenance on disk.
            # Repeating retrieval clocks, formula input chains and issue arrays
            # for every role inflated a local prompt without improving verification.
            chosen[key] = f.model_dump(mode="json", include={
                "id", "metric", "value", "unit", "currency", "fiscal_period",
                "observed_at", "status", "nature", "source_ids",
            })
    return list(chosen.values())[:65]


def collect_node(config: dict) -> Callable:
    def node(state):
        if state.get("asset_type", "stock") != "stock":
            data = {"evidence": EvidenceStore(as_of=utc_now(), gaps=[
                "Integrity adapter currently supports US equities only",
            ]).model_dump(mode="json"), "market_validation": {}, "insider_filings": []}
        else:
            data = collect(state["company_of_interest"], state["trade_date"], config)
        store = EvidenceStore.model_validate(data["evidence"])
        plan = None
        if config.get("research_plan_path"):
            try:
                plan = json.loads(Path(config["research_plan_path"]).expanduser().read_text())
            except (OSError, ValueError):
                store.gaps.append("Operator research plan could not be read or parsed")
        data["evidence"] = store.model_dump(mode="json")
        return {**data, "verification_mode": config["verification_mode"],
                "validated_trade_plan": plan,
                "instrument_context": state.get("instrument_context", "") + "\n" + INSTRUCTION
                + "\nEVIDENCE LEDGER:\n" + json.dumps(compact_ledger(store), ensure_ascii=False),
                "claim_audit": [], "quarantined_outputs": []}
    return node


def parse_claims(text: str, agent: str) -> list[Claim]:
    stripped = text.strip()
    # Existing researchers prepend a role label.
    stripped = re.sub(r"^(Bull|Bear) Analyst:\s*", "", stripped)
    match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.S)
    obj = json.loads(match.group(1) if match else stripped)
    return [Claim.model_validate({**c, "id": f"{agent}:{i}", "agent": agent})
            for i, c in enumerate(obj["claims"])]


def gate_text(text: str, agent: str, store: EvidenceStore) -> tuple[str, list[dict]]:
    errors = []
    try:
        claims = parse_claims(text, agent)
    except (ValueError, TypeError, KeyError, ValidationError):
        claims = []
        errors.append({"agent": agent, "error": "unstructured_unverified_output", "material": True})
    accepted = []
    for claim in claims:
        problems = store.check_claim(claim)
        if problems:
            errors.append({"agent": agent, "claim": claim.model_dump(mode="json"), "errors": problems,
                           "material": claim.material})
        else:
            accepted.append(f"FACT {claim.metric}={claim.value} {claim.unit}; "
                            f"period={claim.fiscal_period}; evidence={','.join(claim.evidence_ids)}")
    return "\n".join(accepted) or "UNKNOWN — no independently validated claims from this agent.", errors


def analyst_gate(state):
    store = EvidenceStore.model_validate(state["evidence"])
    updates, audit, quarantined = {}, [], []
    for key in ("market_report", "fundamentals_report", "news_report", "sentiment_report"):
        text = state.get(key, "")
        if not text:
            continue
        safe, errors = gate_text(text, key, store)
        audit.extend(errors)
        quarantined.append({"agent": key, "raw": text})
        updates[key] = safe if state["verification_mode"] == "strict" else text
    return {**updates, "claim_audit": audit, "quarantined_outputs": quarantined,
            "evidence": store.model_dump(mode="json")}


def guarded_node(node, agent: str):
    """Sanitize newly produced reasoning before the next sequential agent reads it."""
    def guarded(state):
        output = node(state)
        store = EvidenceStore.model_validate(state["evidence"])
        audit = list(state.get("claim_audit", []))
        quarantined = list(state.get("quarantined_outputs", []))
        # Route labels/counts remain untouched; histories never reintroduce raw text.
        skip = {"latest_speaker", "count", "final_rating"}
        def walk(obj, key=""):
            if isinstance(obj, dict):
                return {k: walk(v, k) for k, v in obj.items()}
            if not isinstance(obj, str) or key in skip or not obj:
                return obj
            # Unchanged historical content was already checked.
            if obj == state.get(key) or any(
                isinstance(v, dict) and obj == v.get(key) for v in state.values()
            ):
                return obj
            safe, errors = gate_text(obj, agent, store)
            audit.extend(errors)
            quarantined.append({"agent": agent, "field": key, "raw": obj})
            if state["verification_mode"] != "strict":
                return obj
            if key == "current_response":
                safe = ("Bull" if agent == "Bull Researcher" else "Bear") + " Analyst: " + safe
            return safe
        output = walk(output)
        return {**output, "claim_audit": audit, "quarantined_outputs": quarantined,
                "evidence": store.model_dump(mode="json")}
    return guarded


def validate_decision(store: EvidenceStore, requested: str, plan: dict | None,
                      blocked_claims: list[dict], required=("price", "revenue", "net_income", "operating_cash_flow")) -> dict:
    from .market import session_state

    reasons = []
    for metric in required:
        facts = [f for f in store.facts.values() if f.metric == metric]
        latest_time = max((f.observed_at for f in facts), default=None)
        latest = [f for f in facts if f.observed_at == latest_time]
        if not latest or any(f.status not in {Status.VERIFIED, Status.CORROBORATED} for f in latest):
            reasons.append("missing_or_unverified:" + metric)
        elif metric == "price":
            completed_close = datetime.fromisoformat(session_state(store.as_of)["last_completed_close"])
            if latest_time < completed_close:
                reasons.append("stale_price_before_last_completed_session")
        elif store.as_of - latest_time > timedelta(days=180):
            reasons.append("stale_fundamental:" + metric)
    if any(c.get("material", True) for c in blocked_claims):
        reasons.append("material_claims_failed_gate")
    risk = None
    if reasons:
        outcome = "INSUFFICIENT_DATA"
    elif requested.upper() in {"HOLD", "WATCHLIST"}:
        outcome = requested.upper()
    elif requested.upper() not in {"BUY", "SELL"}:
        outcome, reasons = "WATCHLIST", ["unsupported_or_ambiguous_direction"]
    else:
        try:
            typed = TradePlan.model_validate(plan)
            risk = evaluate_plan(typed)
            if not typed.evidence_ids or any(
                i not in store.facts or store.facts[i].status not in {Status.VERIFIED, Status.CORROBORATED}
                for i in typed.evidence_ids
            ):
                raise ValueError("trade_plan_evidence_missing")
            anchors = {store.facts[i].metric: store.facts[i] for i in typed.evidence_ids}
            if "price" not in anchors or abs(typed.entry / float(anchors["price"].value) - 1) > .1:
                raise ValueError("entry_not_within_10_percent_of_verified_reference")
            if (typed.action in {"NEW_LONG", "NEW_SHORT"}
                    and ("atr_14" not in anchors or typed.atr != anchors["atr_14"].value)):
                raise ValueError("volatility_not_grounded_in_evidence")
            if typed.action not in ({"NEW_LONG"} if requested.upper() == "BUY" else {"NEW_SHORT", "REDUCE", "EXIT"}):
                raise ValueError("direction_action_mismatch")
            if not risk["valid"]:
                raise ValueError(";".join(risk["issues"]))
            outcome = requested.upper()
        except (ValueError, TypeError, ValidationError) as exc:
            outcome, reasons = "WATCHLIST", ["invalid_or_missing_trade_plan:" + str(exc)]
    return {"outcome": outcome, "signal_actionable": outcome in {"BUY", "SELL"} and not reasons,
            "execution_enabled": False, "reasons": reasons, "risk": risk,
            "historical_win_rate": "NOT ESTABLISHED"}


def final_gate(state):
    store = EvidenceStore.model_validate(state["evidence"]).revalidate()
    decision = validate_decision(store, state.get("final_rating", ""), state.get("validated_trade_plan"),
                                 state.get("claim_audit", []))
    plan_ids = set(state["validated_trade_plan"]["evidence_ids"]) if decision["signal_actionable"] else set()
    for reference in store.references:
        blocked = bool(reference["errors"] and reference["material"])
        used = (decision["signal_actionable"] and reference["eligible_for_decision"]
                and bool(plan_ids.intersection(reference["evidence_ids"])))
        reference["influenced_decision"] = blocked or used
        reference["decision_effect"] = "blocked_material_claim" if blocked else (
            "validated_plan_input" if used else "not_established"
        )
    from .report import decision_text
    return {"decision_validation": decision, "final_rating": decision["outcome"],
            "final_trade_decision": decision_text(decision),
            "evidence": store.model_dump(mode="json")}
