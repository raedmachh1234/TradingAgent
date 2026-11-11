"""Paper broker: fills no earlier than the next bar, costs, brackets, idempotency, partial fills, failures."""
from __future__ import annotations

from datetime import timedelta

import pytest

from quantbot.brokers.base import BrokerError
from quantbot.brokers.paper import PaperBroker
from quantbot.core.types import Bar, Instrument, Intent, Order, OrderType, Side

from conftest import T0

INST = {"X": Instrument("X", multiplier=1.0, qty_step=1.0, min_qty=1.0)}


def broker(**kw):
    base = dict(spread_bps=2.0, slippage_bps=1.0, commission_bps=1.0)
    base.update(kw)
    return PaperBroker(INST, **base)


def bar(o, h, l, c, day=1, volume=1e6):
    return Bar("X", T0 + timedelta(days=day), o, h, l, c, volume)


def order(coid="o1", side=Side.BUY, qty=10, intent=Intent.ENTRY, otype=OrderType.MARKET, limit=None, stop=None, target=None, sid="s1"):
    return Order(coid, "X", side, qty, otype, sid, intent, "P-" + coid, limit, stop, target)


def test_market_order_fills_at_next_open_with_costs_against_it():
    b = broker()
    assert b.submit(order()).accepted
    assert b.positions() == {}  # nothing fills at submission
    [f] = b.on_bar(bar(100, 101, 99, 100.5))
    assert f.price == pytest.approx(100 * (1 + 2e-4)) and f.expected_price == 100
    assert f.commission == pytest.approx(10 * f.price * 1e-4)
    assert b.positions() == {"X": 10}
    sell = b.submit(order("o2", Side.SELL, intent=Intent.EXIT))
    assert sell.accepted
    [g] = b.on_bar(bar(102, 103, 101, 102, day=2))
    assert g.price == pytest.approx(102 * (1 - 2e-4)) and b.positions() == {}


def test_limit_order_fills_only_when_traded_through():
    b = broker()
    b.submit(order(otype=OrderType.LIMIT, limit=99.0))
    assert b.on_bar(bar(100, 101, 99.5, 100)) == []
    [f] = b.on_bar(bar(99.8, 100, 98.5, 99, day=2))
    assert f.price == 99.0  # at the limit, no slippage
    b.submit(order("o2", otype=OrderType.LIMIT, limit=99.0))
    [g] = b.on_bar(bar(97.0, 98, 96, 97.5, day=3))
    assert g.price == 97.0  # opened below the limit: filled at the better open


def test_bracket_stop_target_and_stop_first_rule():
    b = broker()
    b.submit(order(stop=98.0, target=104.0))
    b.on_bar(bar(100, 101, 99, 100))
    [t] = b.on_bar(bar(101, 104.5, 100.5, 104, day=2))
    assert t.kind == "target" and t.price == 104.0 and b.positions() == {}
    b.submit(order("o2", stop=98.0, target=104.0))
    b.on_bar(bar(100, 101, 99, 100, day=3))
    [s] = b.on_bar(bar(100, 105, 97, 101, day=4))  # touched both: the stop is assumed first
    assert s.kind == "stop" and s.price == pytest.approx(98.0 * (1 - 2e-4))


def test_gap_through_the_stop_fills_at_the_open():
    b = broker()
    b.submit(order(stop=98.0))
    b.on_bar(bar(100, 101, 99, 100))
    [s] = b.on_bar(bar(95, 96, 94, 95.5, day=2))
    assert s.kind == "stop" and s.price == pytest.approx(95 * (1 - 2e-4))


def test_short_entry_bracket():
    b = broker()
    b.submit(order(side=Side.SELL, stop=102.0, target=96.0))
    b.on_bar(bar(100, 101, 99, 100))
    assert b.positions() == {"X": -10}
    [s] = b.on_bar(bar(101, 103, 100.5, 102.5, day=2))
    assert s.kind == "stop" and s.side is Side.BUY and b.positions() == {}


def test_submission_is_idempotent_on_client_order_id():
    b = broker()
    first = b.submit(order())
    again = b.submit(order())
    assert first.accepted and again.duplicate and len(b.accepted) == 1 and len(b.open_orders()) == 1


def test_partial_fills_under_a_participation_cap():
    b = broker(max_participation=5e-6)  # 5 units of a 1e6 volume bar
    b.submit(order(qty=12))
    f1 = b.on_bar(bar(100, 101, 99, 100))
    f2 = b.on_bar(bar(100, 101, 99, 100, day=2))
    f3 = b.on_bar(bar(100, 101, 99, 100, day=3))
    assert [f.quantity for f in f1 + f2 + f3] == [5, 5, 2] and b.positions() == {"X": 12}


def test_cancel_and_injected_failures():
    b = broker()
    b.submit(order())
    assert b.cancel("o1") and not b.cancel("o1") and b.on_bar(bar(100, 101, 99, 100)) == []
    b.inject_failures(1)
    with pytest.raises(BrokerError):
        b.submit(order("o2"))
    assert b.submit(order("o3")).accepted


def test_resting_exit_is_cancelled_when_the_protective_stop_closes_the_position():
    b = broker()
    b.submit(order(stop=98.0))
    b.on_bar(bar(100, 101, 99, 100))
    b.submit(order("x1", Side.SELL, intent=Intent.EXIT, otype=OrderType.LIMIT, limit=105.0))
    b.on_bar(bar(99, 99.5, 97, 98, day=2))
    assert b.positions() == {} and b.drain_cancelled() == ["x1"] and b.open_orders() == []


def test_unknown_instrument_is_rejected():
    b = broker()
    ack = b.submit(Order("z", "NOPE", Side.BUY, 1, OrderType.MARKET, "s1", Intent.ENTRY, "P-z"))
    assert not ack.accepted and "unknown instrument" in ack.message
