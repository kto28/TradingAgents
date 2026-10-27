"""Reproducible daily indicators; incomplete candles never enter confirmed signals."""

from datetime import UTC, datetime, time, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from .evidence import digest


def session_state(as_of: datetime, calendar: str = "XNYS", user_timezone: str = "Asia/Hong_Kong") -> dict:
    if as_of.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    cal = xcals.get_calendar(calendar)
    local = as_of.astimezone(ZoneInfo(str(cal.tz)))
    day = pd.Timestamp(local.date())
    valid = cal.is_session(day)
    phase = "WEEKEND" if local.weekday() > 4 else "HOLIDAY"
    if valid:
        opened, closed = cal.session_open(day), cal.session_close(day)
        instant = pd.Timestamp(as_of)
        phase = "REGULAR" if opened <= instant < closed else (
            "PREMARKET" if time(4) <= local.time() < opened.tz_convert(cal.tz).time()
            else "AFTER_HOURS" if closed <= instant and local.time() < time(20) else "CLOSED"
        )
    previous = cal.date_to_session(day, direction="previous")
    if cal.session_close(previous) > pd.Timestamp(as_of):
        previous = cal.previous_session(previous)
    return {
        "phase": phase, "as_of_utc": as_of.astimezone(UTC).isoformat(),
        "market_local": local.isoformat(), "user_local": as_of.astimezone(ZoneInfo(user_timezone)).isoformat(),
        "last_completed_session": str(previous.date()),
        "last_completed_close": cal.session_close(previous).isoformat(),
        "calendar": calendar,
    }


def complete_bars(frame: pd.DataFrame, as_of: datetime, calendar="XNYS") -> pd.DataFrame:
    cal = xcals.get_calendar(calendar)
    df = frame.rename(columns=str.lower).copy()
    if "date" not in df:
        df = df.reset_index().rename(columns={df.index.name or "index": "date"})
    required = ["date", "open", "high", "low", "close", "volume"]
    if any(c not in df for c in required):
        raise ValueError("missing OHLCV column")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    if df["date"].duplicated().any():
        raise ValueError("duplicate daily bars")
    df = df.sort_values("date")
    numeric = df[required[1:]].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(numeric.to_numpy()).all() or (numeric["volume"] < 0).any():
        raise ValueError("non-finite or negative volume")
    if (numeric[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("non-positive price")
    if (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any() or (
        numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)
    ).any():
        raise ValueError("inconsistent high/low")
    keep = [cal.is_session(pd.Timestamp(d)) and cal.session_close(pd.Timestamp(d)) <= pd.Timestamp(as_of)
            for d in df["date"]]
    completed = df.loc[keep, required].reset_index(drop=True)
    if not completed.empty:
        expected = cal.sessions_in_range(str(completed.date.iloc[0]), str(completed.date.iloc[-1]))
        if len(expected) != len(completed):
            raise ValueError("missing completed market sessions; do not silently bridge price gaps")
    return completed


def _wilder(series, period=14):
    result = pd.Series(np.nan, index=series.index)
    clean = series.dropna()
    if len(clean) >= period:
        start = clean.index[period - 1]
        result.loc[start] = clean.iloc[:period].mean()
        for idx in clean.index[period:]:
            result.loc[idx] = (result.loc[idx - 1] * (period - 1) + series.loc[idx]) / period
    return result


def indicators(frame: pd.DataFrame, as_of: datetime, calendar="XNYS", user_timezone="Asia/Hong_Kong") -> dict:
    df = complete_bars(frame, as_of, calendar)
    if len(df) < 200:
        raise ValueError("At least 200 completed daily bars required; no invented warm-up")
    close = df.close.astype(float)
    out = {f"sma_{n}": close.rolling(n).mean().iloc[-1] for n in (10, 20, 50, 100, 200)}
    out.update({f"ema_{n}": close.ewm(span=n, adjust=False, min_periods=n).mean().iloc[-1]
                for n in (10, 20, 50)})
    change = close.diff()
    gain, loss = _wilder(change.clip(lower=0)), _wilder(-change.clip(upper=0))
    rsi = 100 - 100 / (1 + gain / loss)
    rsi[(gain == 0) & (loss == 0)] = 50
    fast, slow = (close.ewm(span=n, adjust=False, min_periods=n).mean() for n in (12, 26))
    macd = fast - slow
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    true_range = pd.concat([df.high - df.low, (df.high - close.shift()).abs(),
                            (df.low - close.shift()).abs()], axis=1).max(axis=1)
    middle = close.rolling(20).mean()
    deviation = close.rolling(20).std(ddof=0)
    volume_ma = df.volume.rolling(20).mean()
    out.update({
        "rsi_14": rsi.iloc[-1], "macd_12_26": macd.iloc[-1],
        "macd_signal_9": signal.iloc[-1], "macd_histogram": (macd - signal).iloc[-1],
        "atr_14": _wilder(true_range).iloc[-1], "bollinger_middle": middle.iloc[-1],
        "bollinger_upper": (middle + 2 * deviation).iloc[-1],
        "bollinger_lower": (middle - 2 * deviation).iloc[-1],
        "volume_sma_20": volume_ma.iloc[-1], "price": close.iloc[-1],
    })
    session = session_state(as_of, calendar, user_timezone)
    fresh = str(df.date.iloc[-1]) == session["last_completed_session"]
    return {
        "values": {k: float(v) for k, v in out.items()},
        "breakout": bool(fresh and close.iloc[-1] > df.high.shift().rolling(20).max().iloc[-1]
                         and df.volume.iloc[-1] > 1.5 * volume_ma.shift().iloc[-1]),
        "fresh": fresh, "bar_date": str(df.date.iloc[-1]), "session": session,
        "input_sha256": digest(df.to_csv(index=False, float_format="%.12g").encode()),
        "rows": len(df), "parameters": "SMA 10/20/50/100/200; EMA 10/20/50 adjust=False; Wilder RSI/ATR 14; MACD 12/26/9; BB 20/2 ddof=0; volume SMA20; breakout prior20 high and volume>1.5x prior20 mean",
        "limitations": "Single vendor OHLCV; verify split/dividend adjustments. Signals do not establish institutional activity or guaranteed support.",
    }


def compare_indicator(local: float, external: float, tolerance: float = .01) -> dict:
    if not all(isfinite(x) for x in (local, external, tolerance)) or tolerance < 0:
        raise ValueError("indicator comparison needs finite values and non-negative tolerance")
    conflict = abs(local - external) > max(abs(local) * tolerance, 1e-8)
    return {"local": local, "external": external, "conflict": conflict,
            "confirmed": not conflict, "possible_causes": ["adjustment", "sampling", "warm_up", "formula"] if conflict else []}


def analysis_cutoff(trade_date: str, now: datetime) -> datetime:
    """A historical day means its NY end; today's cutoff is the actual current instant."""
    day_end = datetime.fromisoformat(trade_date).replace(tzinfo=ZoneInfo("America/New_York"))
    day_end += timedelta(days=1)
    return min(now.astimezone(UTC), day_end.astimezone(UTC) - timedelta(microseconds=1))
