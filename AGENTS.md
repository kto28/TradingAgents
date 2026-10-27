# Local setup notes

- Clone of TauricResearch/TradingAgents. venv: `.venv` (uv, Python 3.13). Install: `uv pip install .`
- LLM: local Ollama, set in `.env` (deep `qwen3.8:27b`, quick `qwen3:30b`, output Traditional Chinese).
- `run_notify.py TICKER [DATE]`: runs one analysis, sends the rating, the decision and the report files to
  Telegram bot @tradingagtsbot. Needs `TRADINGAGENT_TG_BOT_TOKEN` and `TRADINGAGENT_TG_CHAT_ID`
  from `~/.config/devin/secrets.env`:
  ```sh
  set -a; . ~/.config/devin/secrets.env; set +a
  nohup .venv/bin/python run_notify.py NVDA > logs/nvda.log 2>&1 &
  ```
- It also sends a progress update (% of stages done, agents running now) every `PROGRESS_INTERVAL`
  seconds (default 600). It counts stages, not time: the deep-model stages near the end take longer.
- Qwen tends to answer in Simplified Chinese even when asked for Traditional, so `run_notify.py` runs every saved
  `.md`/`.html` file and the Telegram text through OpenCC `s2hk` (`opencc==1.4.2`, installed in the venv).
- Reports are saved under `~/.tradingagents/logs/reports/` (results_dir is `~/.tradingagents/logs`). StockTwits returns 403 (harmless; sentiment still uses other sources).
