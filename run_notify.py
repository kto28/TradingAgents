"""Run one TradingAgents analysis and report the result to Telegram.

Usage: python run_notify.py TICKER [YYYY-MM-DD]
Needs TRADINGAGENT_TG_BOT_TOKEN and TRADINGAGENT_TG_CHAT_ID in the environment.
"""
import os
import sys
import threading
import time
import traceback
from datetime import date

import opencc
import requests

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

API = f"https://api.telegram.org/bot{os.environ['TRADINGAGENT_TG_BOT_TOKEN']}"
CHAT_ID = os.environ["TRADINGAGENT_TG_CHAT_ID"]
HANT = opencc.OpenCC("s2hk")


def send_text(text):
    for i in range(0, len(text), 4000):
        requests.post(f"{API}/sendMessage", data={"chat_id": CHAT_ID, "text": text[i:i + 4000]}, timeout=30).raise_for_status()


def send_file(path, caption=""):
    with open(path, "rb") as f:
        requests.post(f"{API}/sendDocument", data={"chat_id": CHAT_ID, "caption": caption},
                      files={"document": f}, timeout=60).raise_for_status()


NAMES_ZH = {
    "Market Analyst": "技術分析師", "Social Analyst": "情緒分析師", "Sentiment Analyst": "情緒分析師",
    "News Analyst": "新聞分析師", "Fundamentals Analyst": "基本面分析師",
    "Bull Researcher": "看好研究員", "Bear Researcher": "看淡研究員", "Research Manager": "研究經理",
    "Trader": "交易員", "Aggressive Analyst": "進取風險分析師", "Conservative Analyst": "保守風險分析師",
    "Neutral Analyst": "中立風險分析師", "Portfolio Manager": "投資組合經理",
}


class ProgressGraph:
    """Wraps the compiled graph so invoke() streams node updates and records progress."""

    def __init__(self, graph, analysts, config):
        self.graph = graph
        self.analysts = analysts
        self.sequence = (["Bull Researcher", "Bear Researcher"] * config["max_debate_rounds"]
                         + ["Research Manager", "Trader"]
                         + ["Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"] * config["max_risk_discuss_rounds"]
                         + ["Portfolio Manager"])
        self.done = []

    @property
    def total(self):
        return len(self.analysts) + len(self.sequence)

    def status(self):
        done_analysts = [a for a in self.analysts if a in self.done]
        seq_done = len([n for n in self.done if n not in self.analysts and n != "Memory Log"])
        if len(done_analysts) < len(self.analysts):
            running = [a for a in self.analysts if a not in self.done]
        else:
            running = self.sequence[seq_done:seq_done + 1]
        return len(done_analysts) + seq_done, [NAMES_ZH.get(n, n) for n in running]

    def invoke(self, graph_input, **args):
        args["stream_mode"] = ["updates", "values"]
        final_state = None
        for mode, chunk in self.graph.stream(graph_input, **args):
            if mode == "values":
                final_state = chunk
            else:
                self.done.extend(chunk.keys())
        return final_state


def report_progress(progress, ticker, trade_date, started, stop):
    while not stop.wait(PROGRESS_INTERVAL):
        done, running = progress.status()
        try:
            send_text(f"進度 {ticker} {trade_date}：{done * 100 // progress.total}%（{done}/{progress.total} 階段）\n"
                      f"已運行 {(time.time() - started) / 60:.0f} 分鐘\n"
                      f"進行中：{'、'.join(running) or '收尾中'}")
        except requests.RequestException as e:
            print(f"progress notify failed: {e}", file=sys.stderr)


PROGRESS_INTERVAL = int(os.environ.get("PROGRESS_INTERVAL", 600))


def main():
    ticker = sys.argv[1].upper()
    trade_date = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()
    config = DEFAULT_CONFIG.copy()
    started = time.time()
    stop = threading.Event()
    try:
        ta = TradingAgentsGraph(debug=False, config=config)
        progress = ProgressGraph(ta.graph, [], config)
        analysts = [n for n in ta.graph.get_graph().nodes if n.endswith("Analyst") and n not in progress.sequence]
        progress = ProgressGraph(ta.graph, analysts, config)
        ta.graph = progress
        threading.Thread(target=report_progress, args=(progress, ticker, trade_date, started, stop), daemon=True).start()
        state, rating = ta.propagate(ticker, trade_date)
        report = ta.save_reports(state, ticker)
    except Exception:
        send_text(f"TradingAgents {ticker} {trade_date} 運行失敗\n\n{traceback.format_exc()[-3500:]}")
        raise
    finally:
        stop.set()
    minutes = (time.time() - started) / 60
    send_result(report, ticker, trade_date, rating, state.get("final_trade_decision", ""),
                f"模型：{config['deep_think_llm']} / {config['quick_think_llm']}（{config['llm_provider']}）\n"
                f"耗時：{minutes:.1f} 分鐘\n")
    print(f"{ticker} {trade_date}: {rating} ({minutes:.1f} min) -> {report}")


def to_hant(text):
    """Local models often answer in Simplified Chinese; convert to Traditional (Hong Kong forms)."""
    return HANT.convert(text)


def send_result(report, ticker, trade_date, rating, decision, extra=""):
    """Convert the saved report files to Traditional Chinese in place, then send the summary and files."""
    for p in report.parent.rglob("*"):
        if p.suffix in (".md", ".html"):
            p.write_text(to_hant(p.read_text(encoding="utf-8")), encoding="utf-8")
    send_text(f"TradingAgents 完成：{ticker} {trade_date}\n評級：{rating}\n{extra}\n{to_hant(decision)}")
    for p in (report, report.with_suffix(".html")):
        if p.exists():
            send_file(p, f"{ticker} {trade_date} 完整報告")


if __name__ == "__main__":
    main()
