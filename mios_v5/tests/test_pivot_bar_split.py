"""📍 The pivot alert's headline split is the pivot BAR's own, not the
11-bar formation window's average.

## Why the window figure had to go

`buy_pct` used to be the volume-weighted mean CLV across all eleven bars of
the formation window (`left=right=5`). Averaging eleven bars regresses hard to
50%. Measured over 400 simulated pivots:

    11-bar window average   std  9.0   inside the 40-60 band  73% of the time
    pivot bar alone         std 26.1   inside the 40-60 band  26% of the time

So the window figure could only reach a verdict — "buyers" (>60) or "sellers"
(<40) — on 27% of pivots. The desk kept seeing "51% buy / 49% sell": the
number was arithmetically correct and practically mute. The bar alone reaches
a verdict 74% of the time.

It also removes a real inconsistency: `hv_window`'s 10-minute totals already
summed `bar_buy`/`bar_sell`, so the two surfaces described the same pivot with
different numbers.

The window figure survives as `win_buy_pct`/`win_sell_pct` — the flow AROUND
the formation is context worth having, just not the headline.
"""

from __future__ import annotations

import ast
import pathlib

import numpy as np
import pandas as pd
import pytest

from indicators import order_flow as _of

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text()


@pytest.fixture(scope="module")
def annotate(source: str):
    ns = {"pd": pd, "np": np, "_of": _of}
    tree = ast.parse(source)
    for n in tree.body:
        if getattr(n, "name", None) == "_annotate_hv_pivots":
            exec(ast.get_source_segment(source, n), ns)   # noqa: S102
    return ns["_annotate_hv_pivots"]


def _frame(pivot_at=40, n=60, bar_close_frac=0.995, bar_vol=20000.0):
    """A flat frame with ONE decisive bar at `pivot_at`: it spans 90..100.5 and
    closes `bar_close_frac` of the way up that range."""
    idx = pd.date_range("2026-08-28 09:15", periods=n, freq="1min")
    close = np.full(n, 100.0)
    high, low = close + 1.0, close - 1.0
    vol = np.full(n, 1000.0)
    lo_, hi_ = 90.0, 100.5
    low[pivot_at], high[pivot_at] = lo_, hi_
    close[pivot_at] = lo_ + (hi_ - lo_) * bar_close_frac
    vol[pivot_at] = bar_vol
    return pd.DataFrame({"datetime": idx, "open": close - 0.1, "high": high,
                         "low": low, "close": close, "volume": vol})


def _annotated(annotate, **kw):
    df = _frame(**kw)
    p = [{"index": 40, "confirmed_at": 45, "price": 90.0, "side": "LOW",
          "norm": 5.1}]
    annotate(p, df, left=5, right=5)
    return p[0]


# ── the headline is the bar ────────────────────────────────────────────

def test_the_headline_split_is_the_bars_own(annotate):
    """The bar closes 99.5% up its range → the headline must say ~99.5% buy,
    not the window's much softer average."""
    r = _annotated(annotate)
    assert r["buy_pct"] > 95.0
    assert r["dominant"] == "buyers"


def test_the_window_average_is_softer_and_is_not_the_headline(annotate):
    """⚠️ The whole point: on the same pivot the window figure is materially
    less decisive. If the headline ever equals it again, the regression is back."""
    r = _annotated(annotate)
    assert r["win_buy_pct"] < r["buy_pct"], \
        "the headline is no more decisive than the window average"


def test_the_window_figure_is_kept_as_context(annotate):
    r = _annotated(annotate)
    assert r["win_buy_pct"] is not None
    assert round(r["win_buy_pct"] + r["win_sell_pct"], 1) == 100.0


def test_a_bar_closing_at_its_low_reads_sell_led(annotate):
    r = _annotated(annotate, bar_close_frac=0.01)
    assert r["buy_pct"] < 5.0 and r["dominant"] == "sellers"


def test_a_bar_closing_mid_range_is_balanced(annotate):
    r = _annotated(annotate, bar_close_frac=0.5)
    assert 40.0 <= r["buy_pct"] <= 60.0
    assert r["dominant"] == "balanced"


def test_the_split_and_its_complement_agree(annotate):
    r = _annotated(annotate)
    assert round(r["buy_pct"] + r["sell_pct"], 1) == 100.0


# ── hv_window (#147) must keep working ─────────────────────────────────

def test_the_bar_fields_hv_window_depends_on_are_intact(annotate):
    """`hv_window` sums `bar_vol`/`bar_buy`/`bar_sell`; this change must not
    disturb them."""
    r = _annotated(annotate)
    assert r["bar_vol"] == 20000.0
    assert r["bar_buy"] > r["bar_sell"]
    assert round(r["bar_buy"] + r["bar_sell"], 0) == 20000.0


def test_the_headline_is_consistent_with_hv_windows_own_arithmetic(annotate):
    """⚠️ The inconsistency this closes: both surfaces must derive the same
    split for the same pivot."""
    r = _annotated(annotate)
    from_bar = r["bar_buy"] / (r["bar_buy"] + r["bar_sell"]) * 100.0
    assert abs(from_bar - r["buy_pct"]) < 0.15


# ── the regression that motivated it, measured ─────────────────────────

def test_the_window_average_really_does_regress_to_fifty():
    """Not an assertion of belief — the property that justified the change.
    An 11-bar volume-weighted CLV average is far more often stuck in the
    'balanced' band than a single bar is."""
    rng = np.random.default_rng(11)
    win, bar = [], []
    for _ in range(200):
        n = 120
        close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
        hi = close + np.abs(rng.standard_normal(n)) * 0.6
        lo = close - np.abs(rng.standard_normal(n)) * 0.6
        df = pd.DataFrame({"open": close, "high": hi, "low": lo, "close": close,
                           "volume": rng.integers(500, 5000, n).astype(float)})
        b, s = _of.split(df)
        i = int(rng.integers(10, n - 10))
        l, r_ = max(0, i - 5), min(n, i + 6)
        win.append(b.iloc[l:r_].sum() / (b.iloc[l:r_].sum() + s.iloc[l:r_].sum()) * 100)
        bar.append(b.iloc[i] / (b.iloc[i] + s.iloc[i]) * 100)
    band = lambda a: ((np.array(a) >= 40) & (np.array(a) <= 60)).mean()
    assert band(win) > 0.6, "the window average is not as mute as measured"
    assert band(bar) < band(win) - 0.3, "the bar is not materially more decisive"


# ── source-level guards ────────────────────────────────────────────────

def test_the_headline_is_derived_from_the_bar_fields(source: str):
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "_annotate_hv_pivots")
    src = ast.unparse(fn)
    bar_read = src.index("p.get('bar_buy')")
    headline = src.index("p['buy_pct']")
    assert bar_read < headline, "buy_pct is not derived from the bar's split"


def test_the_window_sum_no_longer_feeds_the_headline(source: str):
    """⚠️ THE REGRESSION. `buy_pct` must not come from the sliced window sum."""
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "_annotate_hv_pivots")
    src = ast.unparse(fn)
    win = src.index("iloc[lo:hi].sum()")
    headline = src.index("p['buy_pct']")
    assert headline < win, "the headline is still computed after the window sum"
