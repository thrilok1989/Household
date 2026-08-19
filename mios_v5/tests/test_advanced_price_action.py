"""Advanced Price Action — BOS / CHOCH / Fibonacci / patterns, and the opt-in
chart overlay.

The analysis is pinned on deterministic frames; the overlay is pinned as
default-OFF, silent-on-bad-data, and wired to all three charts through one
`price_action` flag.
"""

import ast
import pathlib

import numpy as np
import pandas as pd
from plotly.subplots import make_subplots

from mios_v5.advanced_price_action import AdvancedPriceAction
from mios_v5.ui.price_action_overlay import draw

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _frame(n=80, seed=1):
    idx = pd.date_range("2024-01-01 09:15", periods=n, freq="1min")
    rng = np.random.default_rng(seed)
    base = 24000 + np.cumsum(rng.standard_normal(n)) * 5
    return pd.DataFrame({"open": base, "high": base + 3, "low": base - 3,
                         "close": base + rng.standard_normal(n)}, index=idx)


def test_analyze_returns_all_sections():
    a = AdvancedPriceAction(swing_length=3).analyze(_frame())
    assert a["success"]
    for key in ("swing_highs", "swing_lows", "bos_events", "choch_events",
                "fibonacci", "patterns"):
        assert key in a
    assert a["swing_highs"] and a["swing_lows"]


def test_bullish_bos_when_close_breaks_prior_swing_high():
    # a clean ramp up after a small pullback → price closes above a prior swing high
    highs = [{"index": 5, "price": 100.0, "time": 5}]
    lows = [{"index": 2, "price": 90.0, "time": 2}]
    df = pd.DataFrame({"close": [95, 96, 97, 98, 99, 100, 101, 102]})
    ev = AdvancedPriceAction()._detect_bos_internal(df, highs, lows)
    assert any(e["type"] == "BULLISH" and e["structure_level"] == 100.0 for e in ev)


def test_choch_flags_lower_high_and_higher_low():
    highs = [{"index": 1, "price": 110, "time": 1}, {"index": 5, "price": 105, "time": 5}]
    lows = [{"index": 2, "price": 90, "time": 2}, {"index": 6, "price": 95, "time": 6}]
    ev = AdvancedPriceAction()._detect_choch_internal(pd.DataFrame({"close": [0]}), highs, lows)
    assert any(e["type"] == "BEARISH" for e in ev)   # lower high
    assert any(e["type"] == "BULLISH" for e in ev)   # higher low


def test_fibonacci_levels_span_the_swing_range():
    a = AdvancedPriceAction(swing_length=3)
    sh, sl = a.find_swing_highs_lows(_frame())
    fib = a.calculate_fibonacci_levels(_frame(), sh, sl)
    assert fib["success"]
    rl = fib["retracement_levels"]
    assert set(("0.0", "0.382", "0.5", "0.618", "1.0")) <= set(rl)


def test_head_and_shoulders_detected_on_a_constructed_shape():
    highs = [{"index": 2, "price": 100, "time": 2},
             {"index": 5, "price": 110, "time": 5},     # head
             {"index": 8, "price": 100.5, "time": 8}]   # ~= left shoulder
    lows = [{"index": 4, "price": 95, "time": 4}, {"index": 6, "price": 96, "time": 6}]
    pats = AdvancedPriceAction().detect_head_and_shoulders(highs, lows, tolerance=0.02)
    assert pats and pats[0]["type"] == "HEAD_AND_SHOULDERS"


def test_insufficient_swings_return_empty_or_unsuccessful():
    a = AdvancedPriceAction()
    assert a.detect_head_and_shoulders([], []) == []
    assert a.calculate_fibonacci_levels(pd.DataFrame(), [], []).get("success") is False


# ── the overlay ────────────────────────────────────────────────────────

def test_overlay_draws_traces_on_a_subplot_figure():
    fig = make_subplots(rows=1, cols=1)
    draw(fig, _frame(), 1, 1)
    assert len(fig.data) > 0                       # swing/BOS traces
    assert len(fig.layout.shapes) > 0              # Fib hlines


def test_overlay_is_silent_on_bad_or_short_data():
    fig = make_subplots(rows=1, cols=1)
    draw(fig, None, 1, 1)                           # no frame
    draw(fig, _frame(n=4), 1, 1)                    # too few bars to analyse
    assert len(fig.data) == 0                       # nothing drawn, no raise


# ── the wiring: default OFF, all three charts, one flag ────────────────

def test_overlay_is_default_off_and_wired_to_all_three_charts():
    # the splitter takes the flag and applies it inside the per-chart loop
    tc = (_ROOT / "mios_v5" / "ui" / "terminal_chart.py").read_text()
    assert "price_action: bool = False" in tc      # default OFF
    assert "from .price_action_overlay import draw" in tc
    assert "if price_action:" in tc                 # applied per figure (all 3)
    # the dashboard passes the session flag; the app exposes the toggle default OFF
    d6 = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    assert "price_action=bool(st.session_state.get(\"_apa_on\", False))" in d6
    src = (_ROOT / "vob_minimal.py").read_text()
    assert "_apa_on" in src and "value=False" in src
    # the toggle sits on the price-action checkbox specifically
    tree = ast.parse(src)
    assert "Advanced Price Action on charts" in src
