"""📊 NIFTY's own CVD / Cum Buy / Cum Sell graph — the same time-series
treatment `render_atm_cvd_graphs` gives the ATM±1 legs, applied to NIFTY's
own 1m candles via the SAME `indicators.order_flow.cumulative` estimator,
not a second one.

`vob_minimal` boots Streamlit on import, so these are source-level checks —
same convention as `test_dhan_rate_limits.py` / `test_live_confluence_wiring.py`.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text()


@pytest.fixture(scope="module")
def tree(source: str) -> ast.Module:
    return ast.parse(source)


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found")


def test_it_uses_the_same_cumulative_estimator_the_leg_graph_uses(tree: ast.Module):
    fn = _func(tree, "render_nifty_cvd_graph")
    src = ast.unparse(fn)
    assert "_of.cumulative" in src
    assert "_of.is_missing" in src


def test_it_computes_all_three_series(tree: ast.Module):
    fn = _func(tree, "render_nifty_cvd_graph")
    src = ast.unparse(fn)
    for kind in ("'delta'", "'buy'", "'sell'"):
        assert kind in src, f"{kind} not requested from _of.cumulative"


def test_a_missing_datetime_column_or_empty_frame_returns_quietly(tree: ast.Module):
    fn = _func(tree, "render_nifty_cvd_graph")
    src = ast.unparse(fn)
    assert "'datetime' not in df.columns" in src
    assert "getattr(df, 'empty'" in src


def test_it_is_wired_after_the_leg_graph(source: str):
    """⚠️ A renderer nothing calls never runs — same class of bug this
    session keeps finding. The substring appears twice — once in the `def`
    (which sits earlier in the file, beside `render_atm_cvd_graphs`'s own
    `def`) and once at the actual call site; `rindex` finds the latter."""
    first_idx = source.index("render_nifty_cvd_graph(df)")
    call_idx = source.rindex("render_nifty_cvd_graph(df)")
    assert call_idx != first_idx, "no separate call site found — only the def"
    leg_idx = source.index("render_atm_cvd_graphs(underlying)")
    assert leg_idx < call_idx


def test_it_does_not_duplicate_the_dhan_history_picker(tree: ast.Module):
    """The leg graph's date-picker exists because Dhan's option-intraday
    retention is short-lived; NIFTY's own `df` already reflects whatever the
    sidebar's own timeframe control chose, so a second picker here would be
    a duplicate control, not a missing feature."""
    fn = _func(tree, "render_nifty_cvd_graph")
    src = ast.unparse(fn)
    assert "selectbox" not in src
    assert "get_leg_flow_days" not in src


def test_it_never_raises_out_of_the_render_loop(tree: ast.Module):
    fn = _func(tree, "render_nifty_cvd_graph")
    assert any(isinstance(n, ast.Try) for n in ast.walk(fn))
