"""📊 Rolling-window high-volume pivot totals, CALL vs PUT.

Counts pivot BARS once each (not `volume_points`' rolling-window `volume`
field, which overlaps between nearby pivots and would double-count), reports a
magnitude and never a direction, and distinguishes "nothing spiked" from "both
spiked evenly" — those are different facts.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta

from mios_v5 import hv_window as W

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_T0 = datetime(2026, 8, 28, 11, 0, 0)
_NOW = _T0.timestamp()


def _p(secs_ago=60, bar_vol=10000.0, buy=None, sell=None, **over):
    """A pivot as `_annotate_hv_pivots` emits it. `buy`/`sell` default to an
    even split of `bar_vol` so tests that don't care can ignore them."""
    if buy is None and sell is None:
        buy = sell = (bar_vol or 0.0) / 2.0
    d = {"at": (_T0 - timedelta(seconds=secs_ago)).isoformat(),
         "bar_vol": bar_vol, "bar_buy": buy, "bar_sell": sell,
         "side": "HIGH", "price": 100.0}
    d.update(over)
    return d


# ── the window ─────────────────────────────────────────────────────────

def test_only_pivots_inside_the_window_count():
    inside, outside = _p(secs_ago=120), _p(secs_ago=1200)
    got = W.in_window([inside, outside], now=_NOW)
    assert got == [inside]


def test_a_pivot_without_a_timestamp_is_dropped_not_assumed_recent():
    """⚠️ `at` exists precisely so a pivot's place in time is not guessed."""
    assert W.in_window([_p(at=None)], now=_NOW) == []
    assert W.in_window([{"bar_vol": 5000.0}], now=_NOW) == []


def test_a_future_timestamp_is_not_counted():
    assert W.in_window([_p(secs_ago=-30)], now=_NOW) == []


def test_epoch_and_datetime_timestamps_are_accepted_too():
    assert len(W.in_window([_p(at=_NOW - 60)], now=_NOW)) == 1
    assert len(W.in_window([_p(at=_T0 - timedelta(seconds=60))], now=_NOW)) == 1


# ── totals ──────────────────────────────────────────────────────────────

def test_the_heavier_side_is_reported():
    t = W.totals([_p(bar_vol=90000.0)], [_p(bar_vol=10000.0)], now=_NOW)
    assert t["heavier"] == "CALL"
    assert t["call_vol"] == 90000.0 and t["put_vol"] == 10000.0
    assert t["call_n"] == 1 and t["put_n"] == 1


def test_the_put_side_mirrors():
    t = W.totals([_p(bar_vol=10000.0)], [_p(bar_vol=90000.0)], now=_NOW)
    assert t["heavier"] == "PUT"


def test_near_even_is_comparable_not_a_winner():
    t = W.totals([_p(bar_vol=51000.0)], [_p(bar_vol=49000.0)], now=_NOW)
    assert t["heavier"] == "comparable"


def test_nothing_spiking_is_none_not_a_tie():
    """⚠️ The normal quiet state. Reporting 0 vs 0 as 'comparable' would claim
    both sides spiked evenly, which is not what happened."""
    t = W.totals([], [], now=_NOW)
    assert t["heavier"] is None
    assert t["call_n"] == 0 and t["put_n"] == 0


def test_pivots_outside_the_window_do_not_reach_the_total():
    t = W.totals([_p(secs_ago=1200, bar_vol=999999.0)], [], now=_NOW)
    assert t["heavier"] is None and t["call_vol"] == 0.0


def test_several_pivots_on_one_side_sum():
    t = W.totals([_p(bar_vol=1000.0), _p(secs_ago=200, bar_vol=2000.0)], [],
                 now=_NOW)
    assert t["call_vol"] == 3000.0 and t["call_n"] == 2


def test_the_rolling_window_volume_field_is_not_what_is_summed():
    """⚠️ THE DOUBLE-COUNT TRAP. `volume_points` attaches `volume` — the rolling
    sum over the pivot's own 11-bar formation window. Two nearby pivots share
    most of that window, so summing it grows with clustering rather than with
    what traded. Only `bar_vol` counts."""
    t = W.totals([_p(bar_vol=1000.0, volume=50000.0)], [], now=_NOW)
    assert t["call_vol"] == 1000.0, "the window rolling sum leaked into the total"


def test_a_pivot_with_no_readable_bar_volume_is_skipped():
    t = W.totals([_p(bar_vol=None), _p(bar_vol=500.0)], [], now=_NOW)
    assert t["call_vol"] == 500.0 and t["call_n"] == 1


def test_junk_rows_do_not_raise():
    assert W.totals([None, "x", 7], None, now=_NOW)["heavier"] is None


# ── buy vs sell, per side, inside the window ───────────────────────────

def test_each_side_reports_its_own_buy_and_sell():
    t = W.totals([_p(bar_vol=10000.0, buy=8000.0, sell=2000.0)],
                 [_p(bar_vol=10000.0, buy=3000.0, sell=7000.0)], now=_NOW)
    assert t["call_buy"] == 8000.0 and t["call_sell"] == 2000.0
    assert t["put_buy"] == 3000.0 and t["put_sell"] == 7000.0
    assert t["call_buy_pct"] == 80.0
    assert t["put_buy_pct"] == 30.0


def test_the_buy_sell_split_sums_across_several_pivots():
    t = W.totals([_p(bar_vol=1000.0, buy=900.0, sell=100.0),
                  _p(secs_ago=200, bar_vol=1000.0, buy=100.0, sell=900.0)],
                 [], now=_NOW)
    assert t["call_buy"] == 1000.0 and t["call_sell"] == 1000.0
    assert t["call_buy_pct"] == 50.0


def test_the_bar_split_is_used_not_the_window_percentage():
    """⚠️ `buy_pct` on a pivot describes its ELEVEN-bar formation window.
    Multiplying one bar's volume by it would report a split never measured on
    that bar — only `bar_buy`/`bar_sell` count."""
    t = W.totals([_p(bar_vol=1000.0, buy=200.0, sell=800.0, buy_pct=95.0)],
                 [], now=_NOW)
    assert t["call_buy"] == 200.0
    assert t["call_buy_pct"] == 20.0, "the window percentage leaked into the split"


def test_an_unmeasured_split_is_none_not_fifty_fifty():
    t = W.totals([_p(bar_vol=1000.0, buy=None, sell=None, bar_buy=None,
                     bar_sell=None)], [], now=_NOW)
    assert t["call_buy_pct"] is None
    assert t["call_vol"] == 1000.0, "the volume total should still stand"


def test_a_side_with_no_pivots_has_no_split():
    t = W.totals([_p(bar_vol=1000.0)], [], now=_NOW)
    assert t["put_buy_pct"] is None


def test_the_message_reports_both_sides_buy_sell_as_an_estimate():
    t = W.totals([_p(bar_vol=900000.0, buy=700000.0, sell=200000.0)],
                 [_p(bar_vol=100000.0, buy=20000.0, sell=80000.0)], now=_NOW)
    m = W.message(t)
    assert "• CALL — 78% buy / 22% sell" in m
    assert "• PUT — 20% buy / 80% sell" in m
    assert "CLV from 1m bars, not tick data" in m


def test_a_side_whose_flow_was_never_measured_says_so_on_its_own_line():
    """⚠️ Not omitted, and not shown as 50/50 — the reader must be able to see
    which of the two lines is missing."""
    # `_p` fills an even split unless told otherwise; a real unmeasured bar has
    # neither field, so they are dropped outright.
    t = W.totals([_p(bar_vol=900000.0, bar_buy=None, bar_sell=None)],
                 [_p(bar_vol=100000.0, buy=20000.0, sell=80000.0)], now=_NOW)
    m = W.message(t)
    assert "• CALL — not measured" in m
    assert "• PUT — 20% buy" in m


def test_the_summary_shows_each_sides_split():
    t = W.totals([_p(bar_vol=900000.0, buy=700000.0, sell=200000.0)],
                 [_p(bar_vol=100000.0, buy=20000.0, sell=80000.0)], now=_NOW)
    s = W.summary(t)
    assert "78/22 buy/sell" in s and "20/80 buy/sell" in s


# ── the latch: only on a change of lead ────────────────────────────────

def test_it_fires_when_the_lead_changes_hands():
    fire, st = W.latch("CALL", {"heavier": "PUT"}, now=_NOW)
    assert fire is True and st["heavier"] == "CALL"


def test_it_does_not_re_announce_a_standing_lead():
    """The alert-flood rule this repo keeps having to re-learn."""
    fire, _ = W.latch("CALL", {"heavier": "CALL", "last_fire": _NOW - 10}, now=_NOW)
    assert fire is False


def test_going_quiet_or_even_updates_without_firing():
    for state in (None, "comparable"):
        fire, st = W.latch(state, {"heavier": "CALL"}, now=_NOW)
        assert fire is False
        assert st["heavier"] == state


def test_the_cooldown_suppresses_a_rapid_flip_back():
    fire, _ = W.latch("PUT", {"heavier": "CALL", "last_fire": _NOW - 5}, now=_NOW)
    assert fire is False


def test_the_cooldown_expires():
    fire, _ = W.latch("PUT", {"heavier": "CALL", "last_fire": _NOW - 9999}, now=_NOW)
    assert fire is True


# ── wording ─────────────────────────────────────────────────────────────

def test_the_summary_is_empty_when_nothing_spiked():
    assert W.summary(W.totals([], [], now=_NOW)) == ""


def test_the_summary_carries_both_sides_and_the_lead():
    s = W.summary(W.totals([_p(bar_vol=900000.0)], [_p(bar_vol=100000.0)], now=_NOW))
    assert "CALL" in s and "PUT" in s and "heavier" in s
    assert "10m" in s


def test_the_message_states_it_is_a_magnitude_not_a_direction():
    """⚠️ The rule the desk endorsed: high volume alone says nothing about
    which way it is going."""
    m = W.message(W.totals([_p(bar_vol=900000.0)], [_p(bar_vol=100000.0)], now=_NOW))
    assert "not a direction" in m


def test_no_message_without_a_clear_lead():
    assert W.message(W.totals([], [], now=_NOW)) == ""
    assert W.message(W.totals([_p(bar_vol=51000.0)], [_p(bar_vol=49000.0)],
                              now=_NOW)) == ""


# ── the leader's share, which is not the margin ────────────────────────

def test_the_lead_share_is_the_leaders_fraction_not_the_margin():
    """⚠️ THE BUG. `share` is the signed margin between the sides; the message
    printed `abs(share)` under the label "% of the window's spike volume". With
    CALL 15.6L against PUT 39.6L that read "PUT is where the unusual volume is
    clustering (44%)" — a figure under half, contradicting its own headline.
    PUT's share is 72%."""
    t = W.totals([_p(bar_vol=1_560_000.0)], [_p(bar_vol=3_960_000.0)], now=_NOW)
    assert t["heavier"] == "PUT"
    assert round(t["share"], 3) == -0.435
    assert round(t["lead_share"], 3) == 0.717
    assert "PUT carries 72% of the window's spike volume." in W.message(t)


def test_the_share_printed_is_always_more_than_half():
    """The leader holds the larger half by definition — any figure below 50%
    under that label is the old bug back."""
    import re
    for c, p in ((9e5, 1e5), (1e5, 9e5), (6e5, 4e5), (4e5, 6e5)):
        m = W.message(W.totals([_p(bar_vol=c)], [_p(bar_vol=p)], now=_NOW))
        pct = int(re.search(r"carries (\d+)% of the window", m).group(1))
        assert pct >= 50, m


def test_no_lead_no_share():
    for t in (W.totals([], [], now=_NOW),
              W.totals([_p(bar_vol=51000.0)], [_p(bar_vol=49000.0)], now=_NOW)):
        assert t["lead_share"] is None


# ── what would resolve the ambiguity ───────────────────────────────────

def test_a_sold_put_lead_names_the_two_readings_and_what_separates_them():
    """The desk's own reading of the 39.6L alert, now carried by the alert:
    PUT selling with price holding is put writing; PUT selling with price
    breaking down is sellers winning."""
    t = W.totals([_p(bar_vol=1_560_000.0, buy=1_513_200.0, sell=46_800.0)],
                 [_p(bar_vol=3_960_000.0, buy=118_800.0, sell=3_841_200.0)],
                 now=_NOW)
    m = W.message(t)
    assert "put writing" in m and "support" in m
    assert "breaking below" in m


def test_a_sold_call_lead_reads_as_the_mirror():
    t = W.totals([_p(bar_vol=3_960_000.0, buy=118_800.0, sell=3_841_200.0)],
                 [_p(bar_vol=1_560_000.0, buy=1_513_200.0, sell=46_800.0)],
                 now=_NOW)
    m = W.message(t)
    assert "call writing" in m and "resistance" in m


def test_a_lead_with_mixed_flow_gets_no_interpretation_at_all():
    """⚠️ 50/50 does not distinguish writing from buying, so there is no fork
    to offer. Silence beats a sentence that fits either case."""
    t = W.totals([_p(bar_vol=300_000.0, buy=150_000.0, sell=150_000.0)],
                 [_p(bar_vol=900_000.0, buy=450_000.0, sell=450_000.0)],
                 now=_NOW)
    m = W.message(t)
    assert "put writing" not in m and "hedging" not in m
    assert "not a direction" in m, "the caveat still has to be there"


def test_the_interpretation_reads_the_LEADING_sides_flow():
    """⚠️ The other side's split is shown but must not drive the fork — the
    alert is about where the volume clustered."""
    # PUT leads and is BOUGHT; CALL happens to be sold.
    t = W.totals([_p(bar_vol=1_000_000.0, buy=50_000.0, sell=950_000.0)],
                 [_p(bar_vol=3_000_000.0, buy=2_850_000.0, sell=150_000.0)],
                 now=_NOW)
    m = W.message(t)
    assert "PUT is being BOUGHT" in m
    assert "put writing" not in m


def test_every_interpretation_refuses_to_name_a_market_direction():
    """⚠️ THE RULE for this module, held over the words themselves. Each entry
    names the OBSERVATION that would settle it — never the answer."""
    for key, text in W.INTERPRETATION.items():
        low = text.lower()
        assert "price" in low, f"{key} does not say what to watch"
        for banned in ("go long", "go short", "buy the", "sell the",
                       "bullish signal", "bearish signal", "expect "):
            assert banned not in low, f"{key} tells the reader what to do"


def test_the_table_covers_both_sides_and_both_leans():
    """Four cases, symmetric — four scattered branches drift apart."""
    assert set(W.INTERPRETATION) == {("PUT", "sold"), ("PUT", "bought"),
                                     ("CALL", "sold"), ("CALL", "bought")}


def test_the_lean_thresholds_are_the_ones_the_rest_of_the_app_uses():
    """One number must not mean two things on two panels."""
    from mios_v5 import flow_source as F
    assert (W.BUY_DOMINANT, W.SELL_DOMINANT) == (F.BUY_DOMINANT, F.SELL_DOMINANT)
    assert W._lean(60.0) == "bought" and W._lean(40.0) == "sold"
    assert W._lean(59.9) is None and W._lean(None) is None


# ── the small wording things ───────────────────────────────────────────

def test_one_pivot_is_not_written_as_one_pivots():
    """`pivot(s)` read as a template that had not been filled in."""
    m = W.message(W.totals([_p(bar_vol=9e5)], [_p(bar_vol=1e5)], now=_NOW))
    assert "1 pivot," in m and "pivot(s)" not in m


def test_several_pivots_are_plural():
    m = W.message(W.totals([_p(bar_vol=9e5), _p(bar_vol=9e5)],
                           [_p(bar_vol=1e5)], now=_NOW))
    assert "2 pivots" in m


def test_the_leading_side_is_named_first():
    """The headline says PUT; the numbers should not open with CALL."""
    m = W.message(W.totals([_p(bar_vol=1e5)], [_p(bar_vol=9e5)], now=_NOW))
    body = m.split("\n")[1]
    assert body.index("PUT") < body.index("CALL")


# ── purity, and no direction anywhere ──────────────────────────────────

def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "hv_window.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas", "requests"}
    assert "session_state" not in src


def test_it_never_returns_a_bias():
    """Magnitude only — direction belongs to the reads that measure it."""
    t = W.totals([_p(bar_vol=900000.0)], [_p(bar_vol=1000.0)], now=_NOW)
    assert "bias" not in t
    for v in t.values():
        assert v not in ("bull", "bear")
