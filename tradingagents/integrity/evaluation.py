"""Offline evaluation foundation; explicit fills/rules, no implied executable orders."""

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class HistoricalObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    signal_at: AwareDatetime
    latest_evidence_available_at: AwareDatetime
    entered_at: AwareDatetime
    exited_at: AwareDatetime
    entry_rule: str = Field(min_length=1)
    exit_rule: str = Field(min_length=1)
    execution_assumption: str = Field(min_length=1)
    entry: float = Field(gt=0)
    exit: float = Field(gt=0)
    quantity: float = Field(gt=0)
    direction: int = Field(default=1)
    costs: float = Field(ge=0)
    slippage: float = Field(ge=0)
    benchmark_return: float

    @model_validator(mode="after")
    def chronology(self):
        if not self.latest_evidence_available_at <= self.signal_at < self.entered_at < self.exited_at:
            raise ValueError("look-ahead or invalid signal/fill chronology")
        if self.direction not in {-1, 1}:
            raise ValueError("direction must be +1 or -1")
        return self

    @property
    def net_pnl(self):
        return self.direction * (self.exit - self.entry) * self.quantity - self.costs - self.slippage


def score_observations(records: list[HistoricalObservation], initial_equity: float,
                       training_until: datetime) -> dict:
    if initial_equity <= 0 or training_until.tzinfo is None:
        raise ValueError("positive equity and timezone-aware training cutoff required")
    if any(r.signal_at <= training_until for r in records):
        raise ValueError("out-of-sample observations must follow the frozen training cutoff")
    ordered = sorted(records, key=lambda r: r.entered_at)
    if any(a.exited_at >= b.entered_at for a, b in zip(ordered, ordered[1:], strict=False)):
        raise ValueError("this simple scorer requires non-overlapping observations")
    pnl = [r.net_pnl for r in ordered]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    equity, peak, max_drawdown = initial_equity, initial_equity, 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return {
        "sample_size": len(pnl), "historical_win_rate": len(wins) / len(pnl) if pnl else "NOT ESTABLISHED",
        "average_gain": sum(wins) / len(wins) if wins else None,
        "average_loss": sum(losses) / len(losses) if losses else None,
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "maximum_closed_trade_drawdown": max_drawdown, "net_pnl": sum(pnl),
        "mean_trade_alpha": sum(r.net_pnl / (r.entry * r.quantity) - r.benchmark_return for r in ordered) / len(pnl) if pnl else None,
        "out_of_sample": True, "training_until": training_until.isoformat(),
        "limitations": "Non-overlapping explicit fills; closed-trade drawdown excludes intratrade risk. No calibrated confidence follows from a small sample.",
    }
