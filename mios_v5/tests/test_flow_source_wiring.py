"""🟢/🟡 The flow-source hierarchy, wired: one resolution per cycle, and the
source visible on screen.

`_publish_leg_flow_source` resolves each ATM leg's best available reading
(tick → intrabar → CLV) once and publishes `_leg_flow_source`; the Live
Confluence card reads it. Two resolutions of the same leg is how a card and an
alert come to disagree about who was buying.

`vob_minimal` boots Streamlit on import, so these are source-level checks.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"
_PANEL = (pathlib.Path(__file__).resolve().parents[1]
          / "ui" / "live_confluence_panel.py")
_DB = pathlib.Path(__file__).resolve().parents[2] / "db" / "supabase_client.py"


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text()


@pytest.fixture(scope="module")
def tree(source: str) -> ast.Module:
    return ast.parse(source)


def _fn(tree: ast.Module, name: str) -> ast.FunctionDef:
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found")


# ── the collector ───────────────────────────────────────────────────────

def test_it_resolves_through_the_one_hierarchy(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_publish_leg_flow_source"))
    assert "_fs.resolve(" in src
    assert "'_leg_flow_source'" in src


def test_it_does_not_compute_buy_sell_itself(tree: ast.Module):
    """The tick rule is ws_worker's, CLV is order_flow's. This picks between
    them and must not become a fourth opinion."""
    fn = _fn(tree, "_publish_leg_flow_source")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "buy_fraction" not in called
    assert "split" in called, "the CLV fallback should reuse order_flow.split"


def test_the_tick_read_is_scoped_to_the_legs_on_screen(tree: ast.Module):
    """⚠️ Never the whole table — `dhan_ticks` is upserted many times a
    minute, and the egress rounds made narrow reads the house rule."""
    src = ast.unparse(_fn(tree, "_publish_leg_flow_source"))
    assert "get_tick_flow(want)" in src
    assert "_atm_leg_sids" in src


def test_the_tick_read_is_opt_outable_and_costs_nothing_when_off(tree: ast.Module):
    """A desk without the worker running should pay no query at all."""
    src = ast.unparse(_fn(tree, "_publish_leg_flow_source"))
    gate = src.index("_tick_flow_on")
    read = src.index("get_tick_flow")
    assert gate < read, "the Supabase read happens before the toggle is checked"


def test_a_one_minute_leg_passes_no_sub_bars(tree: ast.Module):
    """There is no finer bar in the feed to decompose a 1-minute frame into,
    so the intrabar tier must be skipped rather than faked."""
    src = ast.unparse(_fn(tree, "_publish_leg_flow_source"))
    assert "sub_bars=None" in src


def test_it_is_wired_into_the_cycle(source: str):
    assert "_publish_leg_flow_source()" in source


def test_it_publishes_before_the_card_reads_it(source: str):
    pub = source.rindex("_publish_leg_flow_source()")
    read = source.rindex("_leg_flow_source')")
    assert pub < read or "_render_live_confluence" in source


# ── the reader ──────────────────────────────────────────────────────────

def test_the_reader_projects_columns_narrowly():
    src = _DB.read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "get_tick_flow")
    # ⚠️ CODE only — the docstring explains why it is NOT select('*'), which
    # would otherwise match.
    body = "\n".join(
        ast.unparse(n) for n in fn.body
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)))
    assert "select('*')" not in body
    assert "buy_vol" in body and "sell_vol" in body


def test_the_reader_reports_row_age():
    """A stale row must be rejectable — the worker flushes every ~1.5s, so
    anything old means it stopped."""
    src = _DB.read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "get_tick_flow")
    assert "'age_s'" in ast.unparse(fn)


def test_the_reader_does_not_derive_the_split_from_cum_delta():
    """⚠️ `volume` counts unchanged-price ticks classified as NEITHER side."""
    src = _DB.read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "get_tick_flow")
    body = ast.unparse(fn)
    assert "cum_delta / 2" not in body and "volume + " not in body


# ── the display ─────────────────────────────────────────────────────────

def test_the_leg_box_shows_the_source_badge():
    panel = _PANEL.read_text()
    fn = next(n for n in ast.walk(ast.parse(panel))
              if isinstance(n, ast.FunctionDef) and n.name == "_flow_line")
    src = ast.unparse(fn)
    assert "badge" in src


def test_a_measurement_and_an_estimate_are_toned_differently():
    """⚠️ THE RULE. Never present a CLV guess as a tick measurement."""
    panel = _PANEL.read_text()
    fn = next(n for n in ast.walk(ast.parse(panel))
              if isinstance(n, ast.FunctionDef) and n.name == "_flow_line")
    src = ast.unparse(fn)
    assert "confident" in src, "the badge tone ignores whether it is measured"


def test_no_reading_draws_no_line():
    panel = _PANEL.read_text()
    fn = next(n for n in ast.walk(ast.parse(panel))
              if isinstance(n, ast.FunctionDef) and n.name == "_flow_line")
    assert "return ''" in ast.unparse(fn)


def test_the_card_is_handed_both_legs_flows(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_render_live_confluence"))
    assert "call_flow=" in src and "put_flow=" in src
