"""Research plan arithmetic only. No orders or brokerage connectivity."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TradePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: Literal["NEW_LONG", "NEW_SHORT", "REDUCE", "EXIT", "TRAIL", "HOLD"]
    entry: float = Field(gt=0)
    stop: float | None = Field(default=None, gt=0)
    target: float | None = Field(default=None, gt=0)
    equity: float = Field(gt=0)
    existing_quantity: float = Field(default=0, ge=0)
    quantity: float = Field(default=0, ge=0)
    risk_fraction: float = Field(default=.01, gt=0, le=.02)
    max_position_fraction: float = Field(default=.1, gt=0, le=1)
    fee_bps: float = Field(default=5, ge=0)
    slippage_bps: float = Field(default=10, ge=0)
    atr: float | None = Field(default=None, gt=0)
    minimum_stop_atr: float = Field(default=1, gt=0)
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def direction(self):
        if self.action in {"NEW_LONG", "NEW_SHORT"}:
            if self.stop is None or self.target is None:
                raise ValueError("directional positions require entry, stop and target")
            if self.action == "NEW_LONG" and not self.stop < self.entry < self.target:
                raise ValueError("long requires stop < entry < target")
            if self.action == "NEW_SHORT" and not self.target < self.entry < self.stop:
                raise ValueError("short requires target < entry < stop")
        if self.action in {"REDUCE", "EXIT", "TRAIL"} and self.existing_quantity <= 0:
            raise ValueError("existing position required; a reduction is not a new short")
        if self.action in {"REDUCE", "EXIT"} and not 0 < self.quantity <= self.existing_quantity:
            raise ValueError("cannot sell more than existing position")
        if self.action == "EXIT" and self.quantity != self.existing_quantity:
            raise ValueError("exit must close existing position")
        if self.action == "TRAIL" and (self.stop is None or self.stop >= self.entry):
            raise ValueError("trailing long stop must be below current reference price")
        return self


def evaluate_plan(plan: TradePlan) -> dict:
    result = {
        "valid": True, "issues": [], "historical_win_rate": "NOT ESTABLISHED",
        "warning": "Stops do not guarantee maximum realized loss: gaps, slippage and execution uncertainty remain. New shorts have borrow and unlimited-loss risk.",
        "fee_bps": plan.fee_bps, "slippage_bps": plan.slippage_bps,
    }
    if plan.action not in {"NEW_LONG", "NEW_SHORT"}:
        return {**result, "reward_risk": None, "sizing_limit": plan.existing_quantity}
    risk, reward = abs(plan.entry - plan.stop), abs(plan.target - plan.entry)
    costs = 2 * plan.entry * (plan.fee_bps + plan.slippage_bps) / 10000
    net_reward, net_risk = reward - costs, risk + costs
    limit = min(plan.equity * plan.risk_fraction / net_risk,
                plan.equity * plan.max_position_fraction / plan.entry)
    issues = []
    if net_reward <= 0:
        issues.append("non_positive_net_reward")
    if plan.atr is None:
        issues.append("volatility_not_established")
    elif risk < plan.minimum_stop_atr * plan.atr:
        issues.append("stop_inside_minimum_atr_distance")
    if plan.quantity <= 0 or plan.quantity > limit:
        issues.append("position_size_exceeds_limit_or_missing")
    return {
        **result, "valid": not issues, "issues": issues, "planned_risk": risk,
        "expected_reward": reward, "round_trip_cost_per_share": costs,
        "reward_risk": reward / risk, "net_reward_risk": net_reward / net_risk,
        "break_even_win_rate_before_costs": risk / (risk + reward),
        "break_even_win_rate_after_costs": net_risk / (risk + reward),
        "sizing_limit": limit,
    }
