"""Capture a replay bundle of public SEC fixtures and cached Yahoo OHLCV."""

import json
from pathlib import Path

from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv
from tradingagents.integrity.evidence import digest, utc_now

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT.parents[1] / "tests/fixtures/integrity"


def main():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    snapshot = {
        "ticker": "NVDA", "currency": "USD", "as_of": "2026-10-27T15:17:23+00:00",
        "retrieved_at": manifest["retrieved_at"], "files": [],
        "gaps": [
            "Reconstructed snapshot: original run did not preserve raw provider responses.",
            "Yahoo OHLCV auto_adjust=True; fetched later; as-of filtering cannot undo future corporate-action adjustment revisions.",
            "Original 2026-10-27 23:17:23 report clock interpreted as Asia/Hong_Kong; intraday bar excluded.",
        ],
    }
    for item in manifest["files"]:
        name = item["file"]
        snapshot["files"].append({
            "name": name, "path": "../../tests/fixtures/integrity/" + name,
            "url": item["url"], "sha256": item["sha256"],
            "filed": "2026-09-02" if "1199039" in name or "1628280" in name else "2026-03-20",
        })
    news_path = FIXTURES / "news_manifest.json"
    if news_path.exists():
        news = json.loads(news_path.read_text())
        for item in news["files"]:
            snapshot["files"].append({
                **item, "path": "../../tests/fixtures/integrity/" + item["name"],
                "retrieved_at": news["retrieved_at"],
            })
    data = load_ohlcv("NVDA", "2026-10-27", fill_gaps=False)
    raw = data.to_csv(index=False)
    (ROOT / "nvda_ohlcv.csv").write_text(raw)
    snapshot["files"].append({
        "name": "nvda_ohlcv.csv", "path": "nvda_ohlcv.csv", "sha256": digest(raw.encode()),
        "url": "https://finance.yahoo.com/quote/NVDA/history/",
        "retrieved_at": utc_now().isoformat(),
    })
    (ROOT / "nvda_snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    print(ROOT / "nvda_snapshot.json")


if __name__ == "__main__":
    main()
