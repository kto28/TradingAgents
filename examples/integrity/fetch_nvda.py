"""Refresh public SEC regression fixtures. No keys; never synthesizes missing filings."""

import json
import os
import time
from pathlib import Path

import requests

from tradingagents.integrity.evidence import digest, utc_now

ROOT = Path(__file__).resolve().parents[2] / "tests/fixtures/integrity"
HEADERS = {"User-Agent": os.environ.get("SEC_EDGAR_USER_AGENT", "TradingAgents research research@tauric.ai")}


def fetch(url):
    time.sleep(.2)
    r = requests.get(url, headers=HEADERS, timeout=40)
    r.raise_for_status()
    return r.content


def main():
    manifest = {"retrieved_at": utc_now().isoformat(), "files": [], "failures": []}
    sub = json.loads(fetch("https://data.sec.gov/submissions/CIK0001045810.json"))
    recent = sub["filings"]["recent"]
    requests_to_make = [("nvda_companyfacts.json", "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json")]
    for i, form in enumerate(recent["form"]):
        owner = recent["accessionNumber"][i].split("-")[0]
        filed = recent["filingDate"][i]
        if (form in {"4", "4/A"} and (
            owner in {"0001197649", "0001588670"} and "2026-03-18" <= filed <= "2026-03-25"
            or recent["accessionNumber"][i] == "0001199039-26-000012"
        )) or (form == "144" and filed == "2026-09-02"):
            accn = recent["accessionNumber"][i]
            doc = recent["primaryDocument"][i].split("/")[-1]
            requests_to_make.append((accn + ".xml", f"https://www.sec.gov/Archives/edgar/data/1045810/{accn.replace('-', '')}/{doc}"))
    for name, url in requests_to_make:
        try:
            raw = fetch(url)
            if name.endswith(".xml") and b"ownershipDocument" not in raw and b"edgarSubmission" not in raw:
                raise ValueError("Response is not SEC ownership XML")
            (ROOT / name).write_bytes(raw)
            manifest["files"].append({"file": name, "url": url, "sha256": digest(raw)})
            print(name, len(raw))
        except (requests.RequestException, ValueError) as exc:
            manifest["failures"].append({"url": url, "error": type(exc).__name__})
            print(name, type(exc).__name__)
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
