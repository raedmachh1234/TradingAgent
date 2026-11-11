"""Internal book: P&L with costs, flips, day roll, drawdown; the allocator."""
from __future__ import annotations

from datetime import timedelta

import pytest

from quantbot.core.types import Fill, Instrument, Intent, Side
from quantbot.portfolio.ledger import Allocator, Ledger

from conftest import T0

INST = {"X": Instrument("X", multiplier=2.0)}


def fill(side, qty, price, commission=1.0, day=0, sid="s1", kind="order", intent=Intent.ENTRY, pid="P1"):
    return Fill("c", "X", side, qty, price, T0 + timedelta(days=day), commission, sid, intent, pid, kind)


def test_round_trip_pnl_includes_both_commissions_and_the_multiplier():
    led = Ledger(10000, INST)
    led.on_fill(fill(Side.BUY, 10, 100))
    led.on_fill(fill(Side.SELL, 10, 105, intent=Intent.EXIT))
    [t] = led.trades
    assert t.pnl == pytest.approx(10 * 5 * 2.0 - 1.0 - 1.0)
    assert led.cash == pytest.approx(10000 + t.pnl) and led.positions[("s1", "X")].qty == 0


def test_partial_close_charges_a_share_of_the_opening_commission():
    led = Ledger(10000, INST)
    led.on_fill(fill(Side.BUY, 10, 100, commission=2.0))
    led.on_fill(fill(Side.SELL, 4, 101, commission=0.5, intent=Intent.EXIT))
    assert led.trades[0].pnl == pytest.approx(4 * 1 * 2.0 - 0.5 - 0.8)
    assert led.positions[("s1", "X")].qty == 6 and led.positions[("s1", "X")].fees == pytest.approx(1.2)


def test_flip_opens_the_remainder_at_the_fill_price():
    led = Ledger(10000, INST)
    led.on_fill(fill(Side.BUY, 10, 100, commission=0))
    led.on_fill(fill(Side.SELL, 15, 90, commission=0, pid="P2"))
    pos = led.positions[("s1", "X")]
    assert pos.qty == -5 and pos.avg_price == 90 and pos.tag == "P2"
    assert led.trades[0].pnl == pytest.approx(-10 * 10 * 2.0)


def test_day_roll_and_drawdown():
    led = Ledger(10000, INST)
    led.roll_day(T0)
    led.on_fill(fill(Side.BUY, 10, 100, commission=0))
    led.mark("X", 110); led.close_step()
    assert led.equity == pytest.approx(10200) and led.high_water == pytest.approx(10200)
    led.roll_day(T0 + timedelta(days=1))
    assert led.day_start_equity == pytest.approx(10200)
    led.mark("X", 95); led.close_step()
    assert led.day_pnl == pytest.approx(-300) and led.drawdown_pct == pytest.approx(300 / 10200 * 100)


def test_positions_are_kept_per_sub_bot_and_netted_per_instrument():
    led = Ledger(10000, INST)
    led.on_fill(fill(Side.BUY, 10, 100, sid="a"))
    led.on_fill(fill(Side.BUY, 5, 100, sid="b"))
    assert led.strategy_position("a", "X") == 10 and led.strategy_position("b", "X") == 5
    assert led.net_positions() == {"X": 15} and led.open_positions() == 2 and led.open_positions("a") == 1


def test_allocator_splits_by_weight():
    a = Allocator(10000, {"a": 1, "b": 3})
    assert a.capital_for("a") == 2500 and a.capital_for("b") == 7500 and a.capital_for("unknown") == 0
    with pytest.raises(ValueError):
        Allocator(10000, {})
