"""Capture two original announcements relevant to the NVDA narrative, with exact passages."""

import json
from pathlib import Path

import requests

from tradingagents.integrity.evidence import digest, utc_now
from tradingagents.integrity.news import visible_text

ROOT = Path(__file__).resolve().parents[2] / "tests/fixtures/integrity"
DOCUMENTS = [
    {
        "name": "anthropic_google_broadcom.html", "provider": "Anthropic",
        "url": "https://www.anthropic.com/news/google-broadcom-partnership-compute",
        "published_at": "2026-04-06T23:59:59-04:00", "source_class": "official_company",
        "quotes": [
            "We have signed a new agreement with Google and Broadcom for multiple gigawatts of next-generation TPU capacity that we expect to come online starting in 2027.",
        ],
    },
    {
        "name": "amd_meta_announcement.html", "provider": "AMD SEC exhibit",
        "url": "https://www.sec.gov/Archives/edgar/data/2488/000000248826000045/pressreleasedatedfebruary2.htm",
        "published_at": "2026-02-24T23:59:59-05:00", "source_class": "sec_regulatory",
        "quotes": [
            "AMD and Meta agree to a definitive multi-year, multi-generation partnership to deploy up to 6 gigawatts of AMD Instinct™ GPUs",
        ],
    },
]


def main():
    files, failures = [], []
    for item in DOCUMENTS:
        try:
            response = requests.get(item["url"], headers={"User-Agent": "TradingAgents research research@tauric.ai"}, timeout=30)
            response.raise_for_status()
            raw = response.content
            text = visible_text(raw.decode())
            if not all(" ".join(q.split()) in text for q in item["quotes"]):
                raise ValueError("Expected passage not present; inspect original, never invent it")
            (ROOT / item["name"]).write_bytes(raw)
            files.append({**item, "sha256": digest(raw)})
            print(item["name"], len(raw))
        except (requests.RequestException, ValueError) as exc:
            failures.append({"name": item["name"], "error": type(exc).__name__})
            print(item["name"], type(exc).__name__)
    (ROOT / "news_manifest.json").write_text(json.dumps({
        "retrieved_at": utc_now().isoformat(), "files": files, "failures": failures,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
