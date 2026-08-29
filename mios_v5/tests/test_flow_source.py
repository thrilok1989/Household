"""🟢/🟡 The flow-source hierarchy: tick → intrabar → CLV, always labelled.

The rule this module exists to enforce: **a real per-trade measurement and a
candle-shape inference must never be presented as the same thing.** Every
reading carries its source, and only tick/intrabar are `confident`.
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import flow_source as F

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _tick(buy=8000.0, sell=2000.0, age=2.0, **over):
    r = {"buy_vol": buy, "sell_vol": sell, "age_s": age, "cum_delta": buy - sell}
    r.update(over)
    return r


def _bars(*specs):
    """(open, close, volume) triples → sub-bar dicts."""
    return [{"open": o, "close": c, "volume": v} for o, c, v in specs]


# ── the hierarchy ───────────────────────────────────────────────────────

def test_tick_wins_when_available():
    r = F.resolve(tick_row=_tick(), sub_bars=_bars((1, 2, 500)),
                  clv_buy=10.0, clv_sell=90.0)
    assert r["source"] == F.TICK
    assert r["confident"] is True


def test_intrabar_is_used_when_there_is_no_tick():
    r = F.resolve(tick_row=None, sub_bars=_bars((1, 2, 500), (2, 1, 100)),
                  clv_buy=10.0, clv_sell=90.0)
    assert r["source"] == F.INTRABAR
    assert r["confident"] is True


def test_clv_is_the_last_resort():
    r = F.resolve(clv_buy=70.0, clv_sell=30.0)
    assert r["source"] == F.CLV
    assert r["confident"] is False, "CLV must never be presented as confident"


def test_nothing_usable_is_reported_as_nothing_not_as_balanced():
    """⚠️ 0/0 is not 50/50. A leg with no data must say so."""
    r = F.resolve()
    assert r["source"] == F.NONE
    assert r["buy_pct"] is None and r["sell_pct"] is None
    assert r["confident"] is False


# ── tick reading ────────────────────────────────────────────────────────

def test_a_stale_tick_row_falls_through():
    """The worker flushes every ~1.5s; a minute old means it stopped."""
    r = F.resolve(tick_row=_tick(age=600.0), clv_buy=70.0, clv_sell=30.0)
    assert r["source"] == F.CLV


def test_age_can_be_derived_from_a_timestamp():
    fresh = F.from_tick(_tick(age=None, updated_ts=1000.0), now=1005.0)
    stale = F.from_tick(_tick(age=None, updated_ts=1000.0), now=1900.0)
    assert fresh is not None and stale is None


def test_a_leg_the_worker_does_not_watch_falls_through():
    """No classified volume yet → not a zeroed tick reading."""
    assert F.from_tick(_tick(buy=0.0, sell=0.0)) is None


def test_it_reads_the_split_not_cum_delta_and_volume():
    """⚠️ `volume` counts unchanged-price ticks classified as NEITHER side, so
    buy+sell cannot be recovered from (cum_delta, volume) — see sql/038."""
    assert F.from_tick({"cum_delta": 6000.0, "volume": 10000.0}) is None


def test_junk_rows_do_not_raise():
    assert F.from_tick(None) is None
    assert F.from_tick("x") is None
    assert F.from_tick({}) is None


# ── intrabar decomposition (LuxAlgo's LTF method) ──────────────────────

def test_each_sub_bar_contributes_its_whole_volume_by_close_vs_open():
    r = F.from_intrabar(_bars((10, 11, 700), (11, 10, 300)))
    assert r["buy"] == 700.0 and r["sell"] == 300.0
    assert r["buy_pct"] == 70.0


def test_an_unchanged_sub_bar_counts_to_neither_side():
    """Exactly as the reference indicator does — `close == open` is neutral."""
    r = F.from_intrabar(_bars((10, 11, 700), (10, 10, 5000)))
    assert r["buy"] == 700.0 and r["sell"] == 0.0
    assert r["sub_bars"] == 2, "the neutral bar is still counted as present"


def test_no_sub_bars_falls_through():
    assert F.from_intrabar(None) is None
    assert F.from_intrabar([]) is None


def test_sub_bars_with_no_volume_fall_through():
    assert F.from_intrabar(_bars((10, 11, 0))) is None


def test_malformed_sub_bars_are_skipped_not_raised_on():
    r = F.from_intrabar([None, "x", {"open": 1}, *_bars((10, 11, 700))])
    assert r["buy"] == 700.0


# ── the reading itself ─────────────────────────────────────────────────

def test_percentages_and_delta_agree():
    r = F.from_clv(75.0, 25.0)
    assert r["buy_pct"] == 75.0 and r["sell_pct"] == 25.0
    assert r["delta"] == 50.0


def test_aggression_reads_the_strength_not_just_the_side():
    assert F.from_clv(90, 10)["aggression"] == "Strong Buying"
    assert F.from_clv(65, 35)["aggression"] == "Buying"
    assert F.from_clv(50, 50)["aggression"] == "Balanced"
    assert F.from_clv(35, 65)["aggression"] == "Selling"
    assert F.from_clv(10, 90)["aggression"] == "Strong Selling"


def test_the_dominance_thresholds_match_the_pivot_splits():
    """One number must not mean two different things on two panels."""
    assert F.BUY_DOMINANT == 60.0 and F.SELL_DOMINANT == 40.0


# ── labelling: the whole point ─────────────────────────────────────────

def test_every_source_has_a_badge_and_a_human_label():
    for src in (F.TICK, F.INTRABAR, F.CLV, F.NONE):
        badge, label = F.LABELS[src]
        assert badge and label


def test_tick_and_clv_are_never_badged_the_same():
    assert F.LABELS[F.TICK] != F.LABELS[F.CLV]
    assert "🟢" in F.LABELS[F.TICK][0]
    assert "🟡" in F.LABELS[F.CLV][0]


def test_only_real_measurements_are_confident():
    assert F.TICK in F.CONFIDENT and F.INTRABAR in F.CONFIDENT
    assert F.CLV not in F.CONFIDENT and F.NONE not in F.CONFIDENT


def test_the_line_always_names_its_source():
    """⚠️ Not decoration — it is the difference between a measurement and a
    guess, and the reader is entitled to know which they are looking at."""
    for r in (F.resolve(tick_row=_tick()),
              F.resolve(sub_bars=_bars((1, 2, 500))),
              F.resolve(clv_buy=70, clv_sell=30),
              F.resolve()):
        assert "Source:" in F.line(r)


def test_the_line_shows_the_tick_badge_for_tick_flow():
    s = F.line(F.resolve(tick_row=_tick()))
    assert "TICK FLOW" in s and "Live Tick Data" in s
    assert "Buy 80%" in s and "CVD +6,000" in s


def test_the_line_shows_the_estimate_badge_for_clv():
    s = F.line(F.resolve(clv_buy=62, clv_sell=38))
    assert "ESTIMATED FLOW" in s and "Candle CLV Estimate" in s


def test_an_empty_reading_says_not_available_not_fifty_fifty():
    s = F.line(F.resolve())
    assert "Not available" in s
    assert "50%" not in s


# ── purity, and no fourth opinion about who was buying ─────────────────

def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "flow_source.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas", "requests", "supabase"}
    assert "session_state" not in src


def test_it_does_not_compute_clv_itself():
    """`indicators.order_flow` owns CLV; `ws_worker` owns the tick rule. This
    picks between them and must not become a fourth opinion."""
    src = (_ROOT / "mios_v5" / "flow_source.py").read_text()
    tree = ast.parse(src)
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    assert not {"split", "buy_fraction", "cumulative"} & called
    # and it never reaches for a bar's high/low — the CLV inputs arrive
    # already computed, they are not re-derived here
    names = {n.value for n in ast.walk(tree)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "high" not in names and "low" not in names
