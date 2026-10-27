"""Traditional Chinese evidence report; unvalidated model prose stays in a separate audit file."""

import html
import json
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

from markdown_it import MarkdownIt
from opencc import OpenCC

from .evidence import EvidenceStore, Status
from .gates import compact_ledger

LABELS = {
    "INSUFFICIENT_DATA": "資料不足", "WATCHLIST": "觀察名單", "BUY": "買入研究信號",
    "SELL": "賣出研究信號", "HOLD": "持有研究信號",
}
METRICS = {
    "revenue": "營業收入", "gross_profit": "毛利", "gross_margin": "毛利率（比例）",
    "operating_income": "營業利潤", "operating_margin": "營業利潤率（比例）",
    "net_income": "淨利潤", "eps": "攤薄每股盈利", "calculated_eps": "重新計算每股盈利",
    "assets": "總資產", "liabilities": "總負債", "equity": "股東權益",
    "operating_cash_flow": "營業現金流", "capital_expenditure": "物業廠房設備資本開支",
    "productive_asset_purchases": "生產性資產購置支出",
    "free_cash_flow_after_productive_assets": "營業現金流減生產性資產購置（計算值）",
    "free_cash_flow": "自由現金流（計算值）",
    "shares_outstanding": "已發行股數", "weighted_diluted_shares": "加權攤薄股數",
    "current_assets": "流動資產", "current_liabilities": "流動負債", "current_ratio": "流動比率",
    "accounts_receivable": "應收帳款", "total_debt": "有息債務合計",
    "current_debt": "流動有息債務", "noncurrent_debt": "非流動有息債務",
    "debt_ratio": "有息債務／資產", "debt_equity": "有息債務／權益",
    "liabilities_to_assets": "總負債／資產",
}


def decision_text(decision):
    return (f"**最終研究建議：{decision['outcome']}（{LABELS.get(decision['outcome'], '')}）**\n\n"
            f"信號可採用：{'是（僅供研究）' if decision['signal_actionable'] else '否'}；自動交易：停用。\n\n"
            + "；".join(decision["reasons"]) + "\n\n歷史勝率：NOT ESTABLISHED。")


def _cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("<", "&lt;").replace(">", "&gt;")


def render(state, ticker, settings=None):
    store = EvidenceStore.model_validate(state["evidence"])
    decision = state["decision_validation"]
    market = state.get("market_validation", {})
    session = market.get("session", {})
    counts = Counter(f.status for f in store.facts.values())
    latest = compact_ledger(store)
    good = {f.metric for f in store.facts.values() if f.status in {Status.VERIFIED, Status.CORROBORATED}}
    required = {"price", "revenue", "net_income", "operating_cash_flow"}
    prices = [f for f in store.facts.values() if f.metric == "price" and f.status == Status.VERIFIED]
    text = [
        f"# {ticker} 可核查投資研究報告",
        f"- 分析截止（UTC）：{store.as_of.isoformat()}",
        f"- 市場時間：{session.get('market_local', '未建立')}；香港時間：{session.get('user_local', '未建立')}",
        f"- 最新已核實價格時間：{max((f.observed_at.isoformat() for f in prices), default='未建立（單一報價供應商不足以獨立核實）')}",
        f"- 最後完整交易時段：{session.get('last_completed_session', '未建立')}；當前時段：{session.get('phase', '未知')}",
        f"- 資料新鮮度：{'最新完整日線' if market.get('fresh') else '未建立或過期'}",
        f"- 關鍵資料完整度：{len(required & good)}/{len(required)} 類具可信記錄（不代表全部斷言準確）",
        f"- 核實狀態：{dict(counts)}",
        f"- 最終研究建議：{decision['outcome']}；信號可採用：{decision['signal_actionable']}；自動交易：停用",
        "\n## 1. 執行摘要\n", decision_text(decision),
        "\n## 2. 資料品質及核實狀態\n",
        "VERIFIED＝原始證據核對；CORROBORATED＝獨立來源互證；UNVERIFIED＝未能核實；"
        "CONTRADICTED＝證據矛盾；STALE＝過期；UNAVAILABLE＝無法取得。\n"
        "FACT／ESTIMATE／INFERENCE／HYPOTHESIS／UNKNOWN 不可互相替代。SEC 記錄只證明申報了該數字，不保證經濟結果。",
        f"已攔截／隔離項目：{len(state.get('claim_audit', []))}。重複引用不增加可信度。",
        "\n## 3. 市場快照\n",
        f"完整日線日期：{market.get('bar_date', '未取得')}；輸入 SHA-256：{market.get('input_sha256', '未建立')}",
        "Yahoo 報價及衍生指標屬單一供應商資料，不能標為獨立驗證的市場事實。",
        "\n## 4. 技術分析\n",
        f"計算參數：{market.get('parameters', '資料不足，未計算')}",
        "| 指標 | 本地計算值 | 狀態 |\n|---|---:|---|",
    ]
    for key, value in market.get("values", {}).items():
        text.append(f"| {_cell(key)} | {value:.6g} | UNVERIFIED（輸入未獨立互證） |")
    if market.get("external_comparisons"):
        text.append("\n外部指標比對（保留雙方數值；不一致者不作確認信號）：\n"
                    + _cell(json.dumps(market["external_comparisons"], ensure_ascii=False)))
    text += [
        "\n不完整日線不參與確認突破。負 MACD 不證明機構沽售；高成交量不證明派貨；均線不保證支持。",
        "\n## 5. 基本面分析\n",
        "以下數字保留基本單位、期間及證據 ID。期間以實際開始／結束日為準；SEC fy/fp 是申報標籤，不能直接當成比較數字的財季。",
        "| 指標 | 數值 | 單位／貨幣 | 期間 | 狀態 | 證據 ID |\n|---|---:|---|---|---|---|",
    ]
    for f in latest:
        if f["metric"] not in market.get("values", {}) and f["metric"] != "announcement_quote":
            text.append("| " + " | ".join(_cell(x) for x in (
                METRICS.get(f["metric"], f["metric"]), f["value"], f"{f['unit']} / {f['currency'] or '—'}",
                f["fiscal_period"], f["status"], f["id"],
            )) + " |")
    text += [
        "\n自由現金流＝同期間營業現金流−資本開支。應收帳款不是自由現金流組成項；PEG 小於 1 不代表低估。",
        "\n## 6. 新聞及催化劑\n",
        "只核實原始公告確曾如此表述，不把預期當成已實現結果。合作消息不能推導獨家供貨或市場份額。",
        "\n## 7. 內部人交易\n",
        "交易日期與申報日期分開；Form 144 是擬出售通知，不是成交證據。沒有完整持倉核對，不判斷清倉。",
    ]
    news = [f for f in store.facts.values() if f.metric == "announcement_quote"]
    news_section = next(i for i, line in enumerate(text) if line.startswith("\n## 7."))
    passages = [f"原文（{f.status}，公告日期 {f.observed_at.astimezone(ZoneInfo('America/New_York')).date()}，證據 {f.id}）：\n\n> {_cell(f.value)}"
                for f in news]
    text[news_section:news_section] = passages or ["UNKNOWN：未有核實的原始新聞段落。"]
    for filing in state.get("insider_filings", []):
        text.append(f"\n### {_cell(filing['owner'])} — {_cell(filing['form'])}，申報 {filing['filed']}\n")
        text.append(f"原始文件：{filing['source_url']}")
        text.append("| 交易日期 | 代碼／分類 | 股數 | 單價 | 交易後該項持股 | 直接／間接 | 10b5-1 |\n|---|---|---:|---:|---:|---|---|")
        for tx in filing["transactions"]:
            text.append("| " + " | ".join(_cell(x) for x in (
                tx["transaction_date"], f"{tx['code']} / {tx['category']}", tx["shares"],
                f"{tx['price']} {tx.get('price_currency') or '幣種未確認'}",
                tx["post_shares"], tx["ownership"], tx["planned_10b5_1"],
            )) + " |")
        text.append("其他披露持倉：" + _cell(filing["holdings"]))
        if filing.get("proposed_disposals"):
            text.append("擬出售（不是已成交）：" + _cell(filing["proposed_disposals"]))
        text.append("限制：" + "；".join(filing["limitations"]))
    text += [
        "\n## 8. 多空論點\n",
        "模型的原文與未驗證推論保留在 quarantined_outputs.json，不能作已核實證據。可接受的精確斷言及引用傳遞記錄見 evidence.json。",
        "\n## 9. 風險回報分析\n",
        json.dumps(decision.get("risk"), ensure_ascii=False) if decision.get("risk") else "未有通過驗證的交易計劃，不能計算可信的風險回報。",
        "歷史勝率：NOT ESTABLISHED。沒有經校準的信心分數。止蝕不保證最大實際損失；跳空、滑價及成交不確定性仍存在。",
        "\n## 10. 投資組合經理決策\n", decision_text(decision),
        "\n## 11. 進出場條件\n",
        "須先補足關鍵證據、核實最新完整交易時段，再提交明確的進場／止蝕／目標、方向、持倉及成本假設。減持既有倉位不等於新開淡倉。",
        "\n## 12. 證據及來源\n",
        "完整來源、原文雜湊、申報 accession、取回時間、數值、公式輸入與代理引用鏈均保存在 evidence.json。",
        "日期精度的來源以保守日終作知悉時間，不代表已知實際發布時分秒。",
        "| 來源 ID | 原始來源 | 公布／保守知悉時間（UTC） | 取回時間 | SHA-256 |\n|---|---|---|---|",
    ]
    for s in store.sources.values():
        text.append("| " + " | ".join(_cell(x) for x in (
            s.id, s.url, f"{s.published_at.isoformat()} ({getattr(s, 'timestamp_precision', 'unknown')})", s.retrieved_at.isoformat(), s.sha256,
        )) + " |")
    text += ["\n## 13. 已知限制\n"]
    text += ["- " + _cell(g) for g in store.gaps]
    text += [
        "- 驗證是保守的欄位及來源檢查，不能理解或證明任意自然語言斷言；無法解析的文字會被隔離。",
        "- 本地計算可重現不等於輸入價格正確；模型測試通過不代表百分百事實準確。",
        "- 本報告僅供研究，不接駁券商、不提交委託。",
    ]
    blocks = []
    previous_table = False
    for item in text:
        table = item.startswith("|")
        if not table or not previous_table:
            blocks.append("")
        blocks.append(item)
        previous_table = table
    return OpenCC("s2hk").convert("\n".join(blocks)) + "\n"


def write(state, ticker, destination, settings=None):
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=True)
    text = render(state, ticker, settings)
    (folder / "complete_report.md").write_text(text, encoding="utf-8")
    for name, data in (("evidence", state["evidence"]), ("claim_audit", state.get("claim_audit", [])),
                       ("quarantined_outputs", state.get("quarantined_outputs", [])),
                       ("market_validation", state.get("market_validation", {})),
                       ("decision_validation", state["decision_validation"])):
        (folder / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(text)
    (folder / "complete_report.html").write_text(
        '<!doctype html><html lang="zh-Hant"><meta charset="utf-8">'
        f"<title>{html.escape(ticker)} 研究報告</title>"
        "<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:40px auto;padding:20px}"
        "table{border-collapse:collapse;display:block;overflow:auto}td,th{border:1px solid #ccc;padding:6px}"
        "a{overflow-wrap:anywhere}</style>" + body + "</html>", encoding="utf-8",
    )
    return folder / "complete_report.md"
