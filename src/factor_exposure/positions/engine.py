from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from factor_exposure.positions.schemas import PositionEvent, PositionSnapshotRow, canonical_event_type


@dataclass
class _TickerState:
    quantity: float = 0.0
    avg_cost: float = 0.0
    realized_pnl: float = 0.0
    dividends_pnl: float = 0.0
    last_event_time: Optional[datetime] = None
    change_reasons: set[str] = field(default_factory=set)

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.dividends_pnl


def _same_sign(a: float, b: float) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)


def _validate_event(event: PositionEvent) -> None:
    if not event.portfolio_id.strip():
        raise ValueError("portfolio_id cannot be empty")
    if not event.ticker.strip():
        raise ValueError("ticker cannot be empty")

    event_type = canonical_event_type(event.event_type)
    if event_type == "TRADE":
        if event.side not in {"BUY", "SELL"}:
            raise ValueError("TRADE event requires side=BUY or SELL")
        if event.quantity <= 0:
            raise ValueError("TRADE event requires quantity > 0")
        if event.price is None or event.price <= 0:
            raise ValueError("TRADE event requires price > 0")
    elif event_type == "MANUAL_ADJUSTMENT":
        if event.quantity == 0:
            raise ValueError("MANUAL_ADJUSTMENT event requires non-zero quantity")
    elif event_type == "SPLIT":
        if event.split_ratio is None or event.split_ratio <= 0:
            raise ValueError("SPLIT event requires split_ratio > 0")
    elif event_type == "DIVIDEND":
        if event.cash_amount_per_share is None:
            raise ValueError("DIVIDEND event requires cash_amount_per_share")


def _apply_trade(state: _TickerState, signed_qty: float, trade_price: float, fees: float) -> None:
    if state.quantity == 0 or _same_sign(state.quantity, signed_qty):
        prior_abs = abs(state.quantity)
        add_abs = abs(signed_qty)
        new_abs = prior_abs + add_abs
        if new_abs > 0:
            state.avg_cost = (state.avg_cost * prior_abs + trade_price * add_abs) / new_abs
        state.quantity += signed_qty
        state.realized_pnl -= fees
        return

    close_qty = min(abs(state.quantity), abs(signed_qty))
    direction = 1.0 if state.quantity > 0 else -1.0
    state.realized_pnl += close_qty * (trade_price - state.avg_cost) * direction
    state.realized_pnl -= fees

    remaining = state.quantity + signed_qty
    if remaining == 0:
        state.quantity = 0.0
        state.avg_cost = 0.0
        return

    if _same_sign(state.quantity, remaining):
        state.quantity = remaining
        return

    state.quantity = remaining
    state.avg_cost = trade_price


def _apply_event(state: _TickerState, event: PositionEvent) -> None:
    _validate_event(event)
    state.last_event_time = event.event_time
    event_type = canonical_event_type(event.event_type)

    if event_type == "TRADE":
        state.change_reasons.add("trade")
        signed_qty = event.quantity if event.side == "BUY" else -event.quantity
        _apply_trade(
            state=state,
            signed_qty=signed_qty,
            trade_price=float(event.price),
            fees=float(event.fees),
        )
        return

    if event_type == "MANUAL_ADJUSTMENT":
        state.change_reasons.add("manual_adjustment")
        effective_price = state.avg_cost if event.price is None else float(event.price)
        _apply_trade(
            state=state,
            signed_qty=float(event.quantity),
            trade_price=effective_price,
            fees=float(event.fees),
        )
        return

    if event_type == "SPLIT":
        state.change_reasons.add("split")
        ratio = float(event.split_ratio)
        state.quantity *= ratio
        if ratio != 0:
            state.avg_cost /= ratio
        return

    if event_type == "DIVIDEND":
        state.change_reasons.add("dividend")
        cps = float(event.cash_amount_per_share)
        state.dividends_pnl += state.quantity * cps
        return


def build_snapshot(
    events: List[PositionEvent],
    as_of: Optional[datetime] = None,
    include_closed: bool = False,
) -> Dict[str, PositionSnapshotRow]:
    relevant = [e for e in events if as_of is None or e.event_time <= as_of]
    relevant.sort(key=lambda e: (e.event_time, e.event_id))

    states: Dict[str, _TickerState] = {}
    for event in relevant:
        ticker = event.ticker.upper().strip()
        state = states.setdefault(ticker, _TickerState())
        _apply_event(state, event)

    out: Dict[str, PositionSnapshotRow] = {}
    for ticker, state in states.items():
        if not include_closed and abs(state.quantity) < 1e-12:
            continue
        if state.last_event_time is None:
            continue
        out[ticker] = PositionSnapshotRow(
            ticker=ticker,
            quantity=float(state.quantity),
            avg_cost=float(state.avg_cost),
            realized_pnl=float(state.realized_pnl),
            dividends_pnl=float(state.dividends_pnl),
            total_pnl=float(state.total_pnl),
            last_event_time=state.last_event_time,
            change_reasons=sorted(state.change_reasons),
        )
    return out
