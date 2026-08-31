"""📖 Per-strike cumulative BID / ASK quantity for ATM±2, Call against Put.

The same store and the same layout as the OI charts, one measure further: the
order book at the five strikes under analysis. `strike_history` already takes a
snapshot per cycle, so this adds no fetch — it adds four columns to the ones
already kept.

⚠️ The property most of this file defends is not arithmetic, it is **honesty
about what a cumulative resting quantity is**. `bidQty` is a level, not a flow;
summing it counts the same untouched order once per snapshot it survives. The
curve looks exactly like accumulated buying and is not, so the caveat has to be
on the screen and no verdict may be drawn from it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5 import strike_history as SH
from mios_v5.ui import strike_oi_series as SC

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DASH = _ROOT / "mios_v5" / "ui" / "dashboard_v6.py"
NOW = 1_775_000_000.0
pd = pytest.importorskip("pandas")


def _chain(spot=24610.0, ce_bid=400.0, pe_bid=900.0,
           ce_ask=1500.0, pe_ask=300.0, depth=True):
    """A chain frame under the column names `analyze_option_chain` really
    produces — `top_bid_quantity` → `bidQty_CE` (vob_minimal.py:4249)."""
    rows = []
    for k in range(24450, 24801, 50):
        r = {"Strike": float(k), "openInterest_CE": 8e6, "openInterest_PE": 7e6,
             "changeinOpenInterest_CE": 2e5, "changeinOpenInterest_PE": 3e5,
             "lastPrice_CE": 120.0, "lastPrice_PE": 95.0}
        if depth:
            r.update({"bidQty_CE": ce_bid, "askQty_CE": ce_ask,
                      "bidQty_PE": pe_bid, "askQty_PE": pe_ask})
        rows.append(r)
    return pd.DataFrame(rows), spot


def _store(n=3, **kw):
    s = {"snaps": []}
    df, spot = _chain(**kw)
    for i in range(n):
        SH.record(s, df, spot, now=NOW + i * SH.MIN_GAP_S)
    return s


# ── the store keeps the book ────────────────────────────────────────────

def test_the_four_depth_fields_are_stored_per_strike():
    s = _store()
    for f in ("ce_bid", "pe_bid", "ce_ask", "pe_ask"):
        assert SH.series(s, 24600, f)["v"], f


def test_the_depth_columns_the_store_reads_really_exist_in_the_app():
    """⚠️ Derived from the app, not guessed. A renamed chain column would draw
    five empty charts and say nothing — the `fii_net` failure again."""
    app = (_ROOT / "vob_minimal.py").read_text()
    for field in ("ce_bid", "pe_bid", "ce_ask", "pe_ask"):
        cands = SH.FIELDS[field]
        assert any(f"'{c}'" in app or f'"{c}"' in app for c in cands), field


def test_a_chain_without_top_of_book_still_stores_its_oi():
    """The depth columns are optional in the payload; losing them must not cost
    the OI series that arrived in the same snapshot."""
    s = _store(depth=False)
    assert SH.series(s, 24600, "ce_oi")["v"]
    assert SH.series(s, 24600, "ce_bid")["v"] == []


# ── the running total ───────────────────────────────────────────────────

def test_the_total_runs():
    assert SC.running_total([10, 20, 30]) == [10.0, 30.0, 60.0]


def test_it_emits_one_point_per_reading():
    assert len(SC.running_total([5] * 7)) == 7


def test_a_gap_in_the_feed_is_skipped_not_counted_as_an_empty_book():
    """⚠️ A missing snapshot is not a moment when nobody was bidding — treating
    it as zero would flatten the curve where the feed hiccuped."""
    assert SC.running_total([10, None, 20]) == [10.0, 30.0]
    assert SC.running_total([10, float("nan"), 20]) == [10.0, 30.0]


def test_booleans_are_not_quantities():
    assert SC.running_total([True, 10]) == [10.0]


def test_nothing_in_nothing_out():
    assert SC.running_total([]) == [] and SC.running_total(None) == []


def test_it_never_decreases_for_a_book_that_is_always_positive():
    """The shape claim the chart makes: a monotone curve whose SLOPE is the
    average resting size."""
    out = SC.running_total([3, 1, 9, 2])
    assert out == sorted(out)


# ── the figures ─────────────────────────────────────────────────────────

def test_one_figure_per_strike_for_each_depth_measure():
    s = _store()
    for measure in ("cum_bid", "cum_ask"):
        assert len(SC.figures(s, measure)) == 5, measure


def test_each_figure_draws_call_and_put():
    fig = SC.figures(_store(), "cum_bid")[0][2]
    names = {t.name for t in fig.data}
    assert names == {"Call", "Put"}


def test_call_is_green_and_put_is_red_on_the_depth_charts():
    """⚠️ The OPPOSITE pairing to the OI charts, and deliberately so. There red
    means RESISTANCE — call OI caps price — and a verdict printed underneath
    says exactly that, so the line colour matches the words. These charts carry
    no verdict for a colour to agree with, so the desk's side convention applies:
    green is the call side, red is the put side."""
    for measure in ("cum_bid", "cum_ask"):
        fig = SC.figures(_store(), measure)[0][2]
        by = {t.name: t.line.color for t in fig.data}
        assert by["Call"] == SC.CALL_COLOUR == "#00cc66", measure
        assert by["Put"] == SC.PUT_COLOUR == "#ff4444", measure


def test_the_oi_charts_keep_the_level_pairing():
    """The other half of the same decision — changing one row must not change
    the other."""
    for measure in ("oi", "chg"):
        fig = SC.figures(_store(), measure)[0][2]
        by = {t.name: t.line.color for t in fig.data}
        assert by["Call"] == SC.CE_COLOUR == "#ff4444", measure
        assert by["Put"] == SC.PE_COLOUR == "#00cc66", measure


def test_the_two_pairings_really_are_opposites():
    assert (SC.CALL_COLOUR, SC.PUT_COLOUR) == (SC.PE_COLOUR, SC.CE_COLOUR)


def test_a_charts_title_figures_match_its_own_lines():
    """⚠️ The legend is OFF — the coloured CE/PE numbers in the title are what
    identify the two lines. A title drawn from the module constants while the
    lines were drawn per-measure would label the green line with a red number,
    which is worse than either convention on its own."""
    for measure in ("oi", "chg", "cum_bid", "cum_ask"):
        fig = SC.figures(_store(), measure)[0][2]
        text = fig.layout.title.text
        by = {t.name: t.line.color for t in fig.data}
        assert f"color:{by['Call']}'>CE " in text, measure
        assert f"color:{by['Put']}'>PE " in text, measure


def test_the_plotted_value_is_the_running_total_not_the_reading():
    """⚠️ The whole point of the measure. Three snapshots of 900 must plot
    900 → 1800 → 2700, not a flat line at 900."""
    fig = SC.figures(_store(n=3, pe_bid=900.0), "cum_bid")[0][2]
    put = next(t for t in fig.data if t.name == "Put")
    assert [round(v, 3) for v in put.y] == [0.9, 1.8, 2.7]   # thousands


def test_the_axis_names_the_unit_it_is_drawn_in():
    for measure, unit in (("cum_bid", "Cum Bid Qty (K)"),
                          ("cum_ask", "Cum Ask Qty (K)")):
        fig = SC.figures(_store(), measure)[0][2]
        assert fig.layout.yaxis.title.text == unit


def test_the_title_carries_the_latest_totals_in_side_colour():
    """The legend is off on these charts — the coloured numbers in the title
    are what identifies the two lines, exactly as on the OI charts."""
    fig = SC.figures(_store(), "cum_bid")[0][2]
    text = fig.layout.title.text
    assert SC.CALL_COLOUR in text and SC.PUT_COLOUR in text
    assert "CE " in text and "PE " in text


def test_one_snapshot_draws_a_visible_marker_and_no_time_axis():
    fig = SC.figures(_store(n=1), "cum_bid")[0][2]
    assert all(t.mode == "markers" for t in fig.data)
    assert fig.layout.xaxis.showticklabels is False


def test_a_chain_with_no_book_plots_nothing_rather_than_a_flat_zero():
    """⚠️ Zero resting quantity is a real reading. Drawing one where the column
    never arrived would claim an empty book that was never observed."""
    assert SC.figures(_store(depth=False), "cum_bid") == []
    assert SC.figures(_store(depth=False), "cum_ask") == []


def test_an_empty_store_draws_no_axes():
    assert SC.figures({"snaps": []}, "cum_bid") == []


@pytest.mark.parametrize("store", [None, "x", 7, [], ()])
def test_a_junk_store_never_raises(store):
    assert SC.figures(store, "cum_bid") == []


def test_an_unknown_measure_is_refused_not_guessed():
    assert SC.figures(_store(), "cum_depth") == []
    assert SC.figures(_store(), "") == []


# ── the measure table ───────────────────────────────────────────────────

def test_every_measure_names_fields_the_store_actually_keeps():
    """⚠️ A spelling here with no `strike_history.FIELDS` entry draws a blank
    panel with no error anywhere."""
    for measure, (ce_f, pe_f, *_rest) in SC.MEASURES.items():
        assert ce_f in SH.FIELDS, f"{measure}: {ce_f}"
        assert pe_f in SH.FIELDS, f"{measure}: {pe_f}"


def test_every_measure_names_its_unit_and_a_divisor_that_matches():
    for measure, (_c, _p, div, unit, _cum) in SC.MEASURES.items():
        assert div > 0
        assert ("(L)" in unit) == (div >= 100_000.0), measure


def test_every_measure_names_its_colours():
    """⚠️ No default. A measure added without a decision about its pairing would
    otherwise inherit one that means something else."""
    assert set(SC.MEASURE_COLOURS) == set(SC.MEASURES)
    for measure, pair in SC.MEASURE_COLOURS.items():
        assert len(pair) == 2 and pair[0] != pair[1], measure


def test_only_the_bid_and_ask_measures_cumulate():
    """⚠️ OI is already a cumulative quantity as the exchange reports it —
    running-totalling it again would draw a parabola and call it open
    interest."""
    assert set(SC.CUMULATIVE) == {"cum_bid", "cum_ask"}


def test_the_oi_charts_are_unchanged_by_the_new_measures():
    s = _store()
    fig = SC.figures(s, "oi")[0][2]
    assert fig.layout.yaxis.title.text == "OI (L)"
    call = next(t for t in fig.data if t.name == "Call")
    assert [round(v, 1) for v in call.y] == [80.0, 80.0, 80.0]


# ── the caption: where the caveat lives ─────────────────────────────────

def test_the_caption_says_shown_depth_not_traded_volume():
    """⚠️ THE RULE for this panel. A rising cumulative bid curve looks exactly
    like accumulated buying. It is not, and the screen has to say so."""
    cap = SC.depth_caption(_store())
    assert "not traded volume" in cap
    assert "pulled" in cap, "the caption does not say quotes can be withdrawn"


def test_the_caption_reports_how_much_history_there_is():
    assert "3 snapshots" in SC.depth_caption(_store(n=3))


def test_an_empty_store_says_so_rather_than_quoting_units_for_nothing():
    cap = SC.depth_caption({"snaps": []})
    assert "no snapshots yet" in cap
    assert "not traded volume" not in cap


def test_the_first_snapshot_is_described_honestly():
    assert "first snapshot" in SC.depth_caption(_store(n=1))


@pytest.mark.parametrize("store", [None, "x", 7, []])
def test_the_caption_never_raises(store):
    assert isinstance(SC.depth_caption(store), str)


# ── the panel ───────────────────────────────────────────────────────────

def _dash_fn(name):
    for n in ast.walk(ast.parse(_DASH.read_text())):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found in dashboard_v6.py")


def test_the_panel_is_drawn_under_the_oi_charts():
    body = ast.unparse(_dash_fn("_charts_screen"))
    assert body.index("_strike_oi_charts") < body.index("_strike_depth_charts")


def test_it_reads_the_published_store_and_does_not_import_the_app():
    """`mios_v5` may not import `vob_minimal` — `test_no_mios_module_imports_the_app`
    holds that, and `_strike_hist` is the same mutable dict `strike_store()`
    publishes, so there is nothing to fetch."""
    fn = _dash_fn("_strike_depth_charts")
    assert "'_strike_hist'" in ast.unparse(fn)
    # ⚠️ IMPORTS only — the docstring names `vob_minimal` to explain whose rule
    # the no-verdict decision follows, and a substring check would match it.
    for n in ast.walk(fn):
        if isinstance(n, ast.ImportFrom):
            assert "vob_minimal" not in (n.module or "")
        elif isinstance(n, ast.Import):
            assert not any("vob_minimal" in a.name for a in n.names)


def test_it_costs_no_query_of_its_own():
    """The OI panel already snapshots the book in the same cycle. A second
    fetch here would be the duplication the fetch audit went looking for."""
    fn = _dash_fn("_strike_depth_charts")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not called & {"record", "get_orderbook", "get_bid_ask_history",
                         "fetch_option_chain", "get_option_chain"}


def test_the_basis_line_is_drawn_before_anything_can_return():
    """⚠️ The bug the OI panel already had: with the caption inside the drawing
    loop, a `figures()` that returned nothing took the whole panel with it and
    the screen read as "never built"."""
    fn = _dash_fn("_strike_depth_charts")
    src = ast.unparse(fn)
    assert src.index("depth_caption") < src.index("for measure")


def test_nothing_plottable_says_so_instead_of_leaving_a_gap():
    src = ast.unparse(_dash_fn("_strike_depth_charts"))
    assert "no bid/ask columns" in src


def test_the_panel_draws_no_verdict():
    """⚠️ Deliberate. `vob_minimal` §5d files the order book as Tier-3
    display-only and gives it NO vote in the regime; a "STRONG SUPPORT" line
    under a cumulative-bid chart would contradict the engine on one screen."""
    fn = _dash_fn("_strike_depth_charts")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_strike_verdict" not in called
    assert "strike_read" not in called


def test_both_measures_are_drawn():
    src = ast.unparse(_dash_fn("_strike_depth_charts"))
    assert "cum_bid" in src and "cum_ask" in src


def test_the_chart_keys_cannot_collide_with_the_oi_charts():
    """Streamlit raises `DuplicateWidgetID` on a repeated key, and the OI panel
    already uses `soi_{measure}_{strike}` for the same five strikes."""
    src = ast.unparse(_dash_fn("_strike_depth_charts"))
    assert "sdep_" in src and "soi_" not in src
