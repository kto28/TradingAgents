"""Exercise the real Ollama multi-agent graph with frozen evidence and no live data tools."""

import json
import resource
import time
from pathlib import Path

from cli.stats_handler import StatsCallbackHandler
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

ROOT = Path(__file__).resolve().parent


def main():
    output = ROOT / "nvda_model_run"
    output.mkdir(exist_ok=True)
    config = DEFAULT_CONFIG.copy()
    config.update(
        verification_mode="strict", evidence_snapshot=str(ROOT / "nvda_snapshot.json"),
        results_dir=str(output), data_cache_dir=str(output / "cache"),
        memory_log_path=str(output / "memory.md"), checkpoint_enabled=False,
        max_tokens=2048,
    )
    if config["llm_provider"] != "ollama":
        raise ValueError("This benchmark is local Ollama only")
    class ProgressStats(StatsCallbackHandler):
        def on_llm_end(self, response, **kwargs):
            super().on_llm_end(response, **kwargs)
            print(json.dumps(self.get_stats()), flush=True)

    stats = ProgressStats()
    started = time.perf_counter()
    graph = TradingAgentsGraph(config=config, callbacks=[stats])
    state, rating = graph.propagate("NVDA", "2026-10-27")
    graph.save_reports(state, "NVDA", save_path=output)
    metrics = {
        "models": [config["quick_think_llm"], config["deep_think_llm"]],
        "debate_rounds": config["max_debate_rounds"], "risk_rounds": config["max_risk_discuss_rounds"],
        "max_output_tokens_per_call": config["max_tokens"], "outcome": rating,
        "duration_seconds": time.perf_counter() - started,
        "python_maxrss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "quarantined_outputs": len(state["quarantined_outputs"]),
        "blocked_claims": len(state["claim_audit"]),
        "validated_references": len([r for r in state["evidence"]["references"] if not r["errors"]]),
        "token_accounting": {k: v for k, v in vars(stats).items() if isinstance(v, int | float)},
        "limitations": "Frozen ledger replaces analyst tools, other agents unchanged. Python memory excludes Ollama. This is not an exact replay of the original report.",
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2), flush=True)


if __name__ == "__main__":
    main()
