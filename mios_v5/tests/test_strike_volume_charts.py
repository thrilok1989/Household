"""📈 Per-strike Cum Buy / Cum Sell / CVD for ATM±2, Call against Put.

Traded volume, from the snapshot the store already takes — `df_summary` carries
`totalTradedVolume_CE/PE` beside the LTPs, so the split costs no fetch. The
volume that traded between two snapshots is the difference in the exchange's
day-cumulative figure, and `flow_source.classify` assigns it a side from the LTP
move over that same interval.

⚠️ Two properties do most of the work here, and both are about honesty rather
than arithmetic:

  1. **Alignment.** Intervals with no volume are skipped, so the output is
     shorter than the input and a positional slice would time-shift every point
     after a gap.
  2. **Labelling.** This is neither tick data nor 1-minute CLV. The panel has to
     say which it is, because the desk's standing rule is that an estimate and a
     measurement are never shown as the same thing.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5 import flow_source as FS
from mios_v5 import strike_history as SH
from mios_v5.ui import strike_oi_series as SC

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DASH = _ROOT / "mios_v5" / "ui" / "dashboard_v6.py"
NOW = 1_775_000_000.0
pd = pytest.importorskip("pandas")


def _chain(spot=24610.0, ce_vol=10_000.0, pe_vol=10_000.0,
           ce_ltp=120.0, pe_ltp=95.0, volume=True):
    rows = []
    for k in range(24450, 24801, 50):
        r = {"Strike": float(k), "openInterest_CE": 8e6, "openInterest_PE": 7e6,
             "changeinOpenInterest_CE": 2e5, "changeinOpenInterest_PE": 3e5,
             "lastPrice_CE": ce_ltp, "lastPrice_PE": pe_ltp,
             "bidQty_CE": 400.0, "askQty_CE": 1500.0,
             "bidQty_PE": 900.0, "askQty_PE": 300.0}
        if volume:
            r.update({"totalTradedVolume_CE": ce_vol,
                      "totalTradedVolume_PE": pe_vol})
        rows.append(r)
    return pd.DataFrame(rows), spot


def _store(steps):
    """`steps` is a list of (ce_vol, ce_ltp, pe_vol, pe_ltp) per snapshot."""
    s = {"snaps": []}
    for i, (cv, cl, pv, pl) in enumerate(steps):
        df, spot = _chain(ce_vol=cv, ce_ltp=cl, pe_vol=pv, pe_ltp=pl)
        SH.record(s, df, spot, now=NOW + i * SH.MIN_GAP_S)
    return s


#: CE volume climbs on a rising LTP (buying), PE volume climbs on a falling LTP
#: (selling) — so the three measures separate cleanly.
#:
#: ⚠️ The PE LTP falls on EVERY step on purpose. A first draft let it tick back
#: up on the last one, which handed that interval's 3,000 to the buy side and
#: left the put's CVD at exactly 0.0 — a fixture that balanced by accident and
#: would have passed a broken decomposition just as happily.
#: CE:  +2,000 buy · +3,000 buy · −1,000 sell  → CVD +4,000
#: PE:  −1,000     · −2,000     · −3,000       → CVD −6,000
_RISING_CALL = [(10_000, 100.0, 10_000, 90.0),
                (12_000, 105.0, 11_000, 88.0),
                (15_000, 110.0, 13_000, 85.0),
                (16_000, 108.0, 16_000, 84.0)]


# ── the rule, in one place ──────────────────────────────────────────────

def test_the_rule_is_up_buy_down_sell_unchanged_neither():
    assert FS.classify(100.0, 101.0) == FS.BUY
    assert FS.classify(101.0, 100.0) == FS.SELL
    assert FS.classify(100.0, 100.0) is None


def test_an_unreadable_pair_attributes_to_neither_side():
    for a, b in ((None, 100.0), (100.0, None), ("x", 100.0), (100.0, "x")):
        assert FS.classify(a, b) is None


def test_the_intrabar_decomposition_uses_the_same_rule():
    """⚠️ One owner. A `>=` in one copy and a `>` in another is exactly how two
    panels come to disagree about who was buying."""
    src = (_ROOT / "mios_v5" / "flow_source.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "from_intrabar")
    body = ast.unparse(fn)
    assert "classify(" in body
    assert "c > o" not in body and "c < o" not in body


def test_the_series_builder_uses_it_too():
    src = (_ROOT / "mios_v5" / "flow_source.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "cumulative_flow")
    assert "classify(" in ast.unparse(fn)


def test_the_panel_module_does_not_decide_who_was_buying():
    """`flow_series` assembles inputs and calls the owner — it must not grow a
    second opinion."""
    src = (_ROOT / "mios_v5" / "ui" / "strike_oi_series.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "flow_series")
    body = ast.unparse(fn)
    assert "cumulative_flow(" in body
    for banned in ("classify(", "> o", "buy +=", "sell +="):
        assert banned not in body, body


# ── the decomposition ───────────────────────────────────────────────────

def test_volume_on_a_rising_price_is_buying():
    got = FS.cumulative_flow([100.0, 101.0], [10_000.0, 12_000.0])
    assert got["buy"] == [2000.0] and got["sell"] == [0.0]
    assert got["cvd"] == [2000.0]


def test_volume_on_a_falling_price_is_selling():
    got = FS.cumulative_flow([101.0, 100.0], [10_000.0, 12_000.0])
    assert got["sell"] == [2000.0] and got["buy"] == [0.0]
    assert got["cvd"] == [-2000.0]


def test_volume_on_an_unchanged_price_goes_to_neither_side():
    """⚠️ Not half and half. Volume that traded without moving the price says
    nothing about which side was the aggressor, and splitting it would
    manufacture a balance nobody measured."""
    got = FS.cumulative_flow([100.0, 100.0], [10_000.0, 12_000.0])
    assert got["buy"] == [0.0] and got["sell"] == [0.0]
    assert got["cvd"] == [0.0]
    assert got["i"] == [1], "the interval still happened and is still a point"


def test_the_totals_run():
    got = FS.cumulative_flow([100.0, 101.0, 102.0, 101.0],
                             [0.0, 100.0, 300.0, 900.0])
    assert got["buy"] == [100.0, 300.0, 300.0]
    assert got["sell"] == [0.0, 0.0, 600.0]
    assert got["cvd"] == [100.0, 300.0, -300.0]


def test_cvd_is_always_buy_minus_sell():
    got = FS.cumulative_flow(*zip(*[(100.0, 0.0), (102.0, 500.0),
                                    (99.0, 900.0), (103.0, 1500.0)]))
    for b, s, d in zip(got["buy"], got["sell"], got["cvd"]):
        assert d == b - s


def test_the_input_is_day_cumulative_volume_not_per_interval():
    """⚠️ The chain reports a running day total. 10,000 → 12,000 is 2,000
    traded, not 12,000."""
    got = FS.cumulative_flow([100.0, 101.0], [10_000.0, 12_000.0])
    assert got["buy"] == [2000.0]


def test_a_falling_volume_reading_is_dropped_not_counted_as_selling():
    """⚠️ Day-cumulative volume cannot fall. A drop means a reset, a rollover or
    a bad read — counting it as selling would print a phantom sell spike exactly
    when the data is least trustworthy."""
    got = FS.cumulative_flow([100.0, 99.0, 101.0], [10_000.0, 500.0, 900.0])
    assert got["sell"] == [] or 9500.0 not in got["sell"]
    assert got["i"] == [2], "only the one real interval"


def test_an_interval_with_no_volume_is_not_a_point():
    got = FS.cumulative_flow([100.0, 101.0, 102.0], [500.0, 500.0, 700.0])
    assert got["i"] == [2]
    assert got["buy"] == [200.0]


def test_one_reading_is_no_interval_at_all():
    """⚠️ A zero point would draw the session as starting flat when it simply
    had not started."""
    got = FS.cumulative_flow([100.0], [10_000.0])
    assert got == {"buy": [], "sell": [], "cvd": [], "i": []}
    assert FS.cumulative_flow([], []) == {"buy": [], "sell": [], "cvd": [],
                                          "i": []}


def test_junk_does_not_raise():
    for p, v in ((None, None), ("x", "y"), ([100.0], None)):
        assert FS.cumulative_flow(p, v)["i"] == []


def test_mismatched_lengths_use_the_shorter():
    got = FS.cumulative_flow([100.0, 101.0, 102.0], [0.0, 100.0])
    assert got["i"] == [1]


# ── alignment: the index, not a slice ───────────────────────────────────

def test_every_point_reports_the_index_of_its_later_end():
    got = FS.cumulative_flow([100.0, 101.0, 102.0], [0.0, 100.0, 300.0])
    assert got["i"] == [1, 2]


def test_a_skipped_interval_does_not_shift_the_points_that_follow():
    """⚠️ THE TRAP. With no volume in the middle interval the output is shorter
    than `n − 1`, so `ts[1:]` would stamp the last point one snapshot early —
    silently, and further out the more gaps there are."""
    got = FS.cumulative_flow([100.0, 101.0, 102.0, 103.0],
                             [0.0, 0.0, 0.0, 500.0])
    assert got["i"] == [3], "the only interval that carried volume"


def test_the_chart_stamps_from_the_index_rather_than_slicing():
    s = _store([(10_000, 100.0, 10_000, 90.0),   # no CE volume change
                (10_000, 101.0, 10_000, 90.0),
                (12_000, 102.0, 10_000, 90.0)])
    got = SC.flow_series(s, 24600, ("ce_vol", "ce_ltp"), "buy")
    assert got["t"] == [NOW + 2 * SH.MIN_GAP_S], got
    assert got["v"] == [2000.0]


def test_the_two_legs_are_paired_on_the_snapshot_not_by_position():
    """Same rule `net_series` follows: `SH.series` drops readings the chain did
    not carry, so pairing by position would attribute one minute's volume to
    another minute's price move."""
    s = {"snaps": []}
    df_a, spot = _chain(ce_vol=10_000.0, ce_ltp=100.0)
    df_gap, _ = _chain(ce_vol=11_000.0, ce_ltp=None)      # LTP missing
    df_c, _ = _chain(ce_vol=13_000.0, ce_ltp=105.0)
    SH.record(s, df_a, spot, now=NOW)
    SH.record(s, df_gap, spot, now=NOW + SH.MIN_GAP_S)
    SH.record(s, df_c, spot, now=NOW + 2 * SH.MIN_GAP_S)
    got = SC.flow_series(s, 24600, ("ce_vol", "ce_ltp"), "buy")
    # the gap snapshot has no LTP, so the one usable interval is 10k → 13k
    assert got["v"] == [3000.0]
    assert got["t"] == [NOW + 2 * SH.MIN_GAP_S]


def test_a_field_pair_of_the_wrong_shape_yields_nothing():
    assert SC.flow_series(_store(_RISING_CALL), 24600, ("ce_vol",), "buy") == {
        "t": [], "v": []}


# ── the store keeps the volume ──────────────────────────────────────────

def test_volume_is_stored_per_strike():
    s = _store(_RISING_CALL)
    assert SH.series(s, 24600, "ce_vol")["v"] == [10_000, 12_000, 15_000, 16_000]
    assert SH.series(s, 24600, "pe_vol")["v"]


def test_the_volume_column_the_store_reads_really_exists_in_the_app():
    """⚠️ Derived from the app, not guessed — a renamed chain column would draw
    fifteen empty charts and say nothing."""
    app = (_ROOT / "vob_minimal.py").read_text()
    for field in ("ce_vol", "pe_vol"):
        cands = SH.FIELDS[field]
        assert any(f"'{c}'" in app or f'"{c}"' in app for c in cands), field


def test_it_is_read_off_the_frame_the_store_already_gets():
    """⚠️ No new fetch. `record()` is handed `df_summary` once per cycle and the
    volume column is already on it — this must not add a call of its own."""
    src = (_ROOT / "mios_v5" / "strike_history.py").read_text()
    for banned in ("requests", "fetch_", "get_option_chain", "DhanAPI"):
        assert banned not in src


def test_a_chain_without_volume_still_stores_its_oi():
    s = {"snaps": []}
    df, spot = _chain(volume=False)
    SH.record(s, df, spot, now=NOW)
    assert SH.series(s, 24600, "ce_oi")["v"]
    assert SH.series(s, 24600, "ce_vol")["v"] == []


# ── the figures ─────────────────────────────────────────────────────────

def test_one_figure_per_strike_for_each_volume_measure():
    s = _store(_RISING_CALL)
    for measure in ("cum_buy", "cum_sell", "cvd"):
        assert len(SC.figures(s, measure)) == 5, measure


def test_each_figure_draws_call_and_put():
    fig = SC.figures(_store(_RISING_CALL), "cvd")[0][2]
    assert {t.name for t in fig.data} == {"Call", "Put"}


def test_the_volume_charts_use_the_call_green_put_red_pairing():
    for measure in ("cum_buy", "cum_sell", "cvd"):
        fig = SC.figures(_store(_RISING_CALL), measure)[0][2]
        by = {t.name: t.line.color for t in fig.data}
        assert by["Call"] == SC.CALL_COLOUR, measure
        assert by["Put"] == SC.PUT_COLOUR, measure


def test_a_call_bought_into_and_a_put_sold_into_separate_cleanly():
    """The end-to-end read: CE volume arriving on a rising LTP is buying, PE
    volume arriving on a falling LTP is selling."""
    figs = SC.figures(_store(_RISING_CALL), "cvd")
    fig = figs[0][2]
    call = next(t for t in fig.data if t.name == "Call")
    put = next(t for t in fig.data if t.name == "Put")
    assert call.y[-1] == 4.0, "CE +2,000 +3,000 −1,000 = +4,000 (thousands)"
    assert put.y[-1] == -6.0, "PE −1,000 −2,000 −3,000 = −6,000 (thousands)"


def test_cum_buy_and_cum_sell_never_decrease():
    for measure in ("cum_buy", "cum_sell"):
        fig = SC.figures(_store(_RISING_CALL), measure)[0][2]
        for tr in fig.data:
            assert list(tr.y) == sorted(tr.y), measure


def test_cvd_can_go_either_way_and_gets_a_zero_line():
    """⚠️ On a CVD chart the crossing is the reading."""
    fig = SC.figures(_store(_RISING_CALL), "cvd")[0][2]
    lines = [s for s in (fig.layout.shapes or []) if s.type == "line"]
    assert any(s.y0 == 0 and s.y1 == 0 for s in lines)


def test_the_quantity_charts_get_no_zero_line():
    for measure in ("cum_buy", "cum_sell"):
        fig = SC.figures(_store(_RISING_CALL), measure)[0][2]
        assert not (fig.layout.shapes or ()), measure


def test_the_axis_names_the_unit():
    for measure, unit in (("cum_buy", "Cum Buy Vol (K)"),
                          ("cum_sell", "Cum Sell Vol (K)"),
                          ("cvd", "CVD (K)")):
        fig = SC.figures(_store(_RISING_CALL), measure)[0][2]
        assert fig.layout.yaxis.title.text == unit


def test_the_cvd_title_carries_a_sign():
    fig = SC.figures(_store(_RISING_CALL), "cvd")[0][2]
    assert "CE +" in fig.layout.title.text


def test_one_snapshot_draws_nothing_because_there_is_no_interval():
    """⚠️ Unlike every other measure, one snapshot is genuinely not a reading
    here — a flow needs two points to exist at all."""
    s = _store([(10_000, 100.0, 10_000, 90.0)])
    for measure in ("cum_buy", "cum_sell", "cvd"):
        assert SC.figures(s, measure) == [], measure


def test_a_chain_with_no_volume_draws_nothing():
    s = {"snaps": []}
    df, spot = _chain(volume=False)
    for i in range(3):
        SH.record(s, df, spot, now=NOW + i * SH.MIN_GAP_S)
    assert SC.figures(s, "cvd") == []


def test_a_flat_session_draws_nothing_rather_than_a_zero_line():
    """No volume traded is not the same as balanced flow."""
    s = _store([(10_000, 100.0, 10_000, 90.0)] * 3)
    assert SC.figures(s, "cum_buy") == []


@pytest.mark.parametrize("store", [None, "x", 7, [], ()])
def test_a_junk_store_never_raises(store):
    for measure in ("cum_buy", "cum_sell", "cvd"):
        assert SC.figures(store, measure) == []


# ── the measure table ───────────────────────────────────────────────────

def test_the_flow_measures_are_the_three_volume_ones():
    assert set(SC.FLOW_MEASURES) == {"cum_buy", "cum_sell", "cvd"}


def test_a_flow_measure_names_a_volume_field_and_a_price_field():
    for measure in SC.FLOW_MEASURES:
        spec = SC.MEASURES[measure]
        for side in ("ce", "pe"):
            assert len(spec[side]) == 2, measure
            vol_f, price_f = spec[side]
            assert vol_f.endswith("_vol"), f"{measure}: {vol_f} is not volume"
            assert price_f.endswith("_ltp"), f"{measure}: {price_f} is not price"


def test_a_flow_measure_is_not_also_running_totalled():
    """⚠️ `cumulative_flow` already returns a running total. Putting
    `running_total` over it again would draw the integral of a cumulative series
    and label it volume."""
    for measure in SC.FLOW_MEASURES:
        assert SC.MEASURES[measure]["cumulative"] is False, measure


def test_only_cvd_is_signed_among_the_volume_measures():
    assert SC.MEASURES["cvd"]["signed"] is True
    assert SC.MEASURES["cum_buy"]["signed"] is False
    assert SC.MEASURES["cum_sell"]["signed"] is False


def test_the_flow_component_names_match_what_the_builder_returns():
    """A typo here would silently draw an empty series."""
    got = FS.cumulative_flow([100.0, 101.0], [0.0, 100.0])
    for measure in SC.FLOW_MEASURES:
        assert SC.MEASURES[measure]["flow"] in got, measure


def test_every_measure_still_declares_the_whole_spec():
    for measure, spec in SC.MEASURES.items():
        assert set(spec) == {"ce", "pe", "flow", "div", "unit",
                             "cumulative", "signed"}, measure


def test_the_older_measures_are_unchanged():
    """Adding a family must not disturb the two that were there first."""
    s = _store(_RISING_CALL)
    assert SC.figures(s, "oi")[0][2].layout.yaxis.title.text == "OI (L)"
    assert len(SC.figures(s, "cum_bid")) == 5


# ── labelling: the whole point ──────────────────────────────────────────

def test_the_note_says_it_is_not_tick_data():
    """⚠️ THE RULE. Never present this beside a tick reading as if they were the
    same measurement."""
    note = SC.FLOW_NOTE
    assert "not tick data" in note
    assert "CLV" in note, "it is not the 1-minute CLV estimate either"


def test_the_note_says_where_the_split_came_from():
    assert "LTP direction" in SC.FLOW_NOTE
    assert "snapshot" in SC.FLOW_NOTE


def test_the_note_does_not_undersell_it_as_an_estimate():
    """The VOLUME is real — it is the exchange's own figure differenced. Only
    the side attribution is coarse, and the note distinguishes the two."""
    assert "real traded volume" in SC.FLOW_NOTE


# ── the panel ───────────────────────────────────────────────────────────

def _dash_fn(name):
    for n in ast.walk(ast.parse(_DASH.read_text())):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found in dashboard_v6.py")


def test_the_panel_is_drawn_under_the_depth_charts():
    body = ast.unparse(_dash_fn("_charts_screen"))
    assert body.index("_strike_depth_charts") < body.index("_strike_volume_charts")


def test_all_three_measures_are_drawn():
    src = ast.unparse(_dash_fn("_strike_volume_charts"))
    for measure in ("cum_buy", "cum_sell", "cvd"):
        assert measure in src


def test_the_panel_prints_the_note():
    """⚠️ Not optional — it is the difference between a measurement and a
    coarser attribution, and the reader is entitled to know which."""
    assert "FLOW_NOTE" in ast.unparse(_dash_fn("_strike_volume_charts"))


def test_the_note_comes_before_anything_can_return():
    src = ast.unparse(_dash_fn("_strike_volume_charts"))
    assert src.index("FLOW_NOTE") < src.index("for measure")


def test_it_costs_no_query_of_its_own():
    fn = _dash_fn("_strike_volume_charts")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not called & {"record", "get_option_chain", "fetch_option_chain",
                         "get_volume_delta_history", "get_candles"}


def test_the_panel_draws_no_verdict():
    """Volume is a magnitude — which way it points is a separate question these
    charts do not answer."""
    fn = _dash_fn("_strike_volume_charts")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_strike_verdict" not in called and "strike_read" not in called


def test_nothing_plottable_says_why():
    src = ast.unparse(_dash_fn("_strike_volume_charts"))
    assert "two snapshots" in src


def test_the_chart_keys_cannot_collide_with_the_other_two_panels():
    """Streamlit raises `DuplicateWidgetID`; the OI panel uses `soi_` and the
    depth panel `sdep_` for the same five strikes."""
    src = ast.unparse(_dash_fn("_strike_volume_charts"))
    assert "svol_" in src and "soi_" not in src and "sdep_" not in src
