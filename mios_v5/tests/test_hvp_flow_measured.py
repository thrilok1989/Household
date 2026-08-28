"""📍 High-volume pivot alerts: a STABLE identity, and a MEASURED buy/sell
split instead of a structural assumption.

Two faults, both reported from the live Telegram stream:

1. **The flood.** `hvp_signature` identified a pivot by `confirmed_at` — its
   POSITION in the frame. A position is not an identity in a rolling window:
   every new 1-minute bar shifts every index by one, so the same physical pivot
   came back with a new signature each cycle and was announced again. The
   desk's log shows exactly that — the same price at the same volume ratio,
   repeated (₹131.80 on 2.1×, ₹145.00 on 3.9×, ₹62.00 on 4.8×).

2. **The assumed bias.** The ball came from `bias_ball.hvp_bias(chart, side)`,
   which reads the pivot's SHAPE — a swing high is overhead, therefore bearish
   for the leg. The desk challenged that correctly: a swing high can print on
   heavy BUYING and a swing low on heavy SELLING. The shape says nothing about
   who was behind the volume.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5 import bias_ball as BB
from mios_v5 import formation_alerts as FA

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"


def _pivot(**over):
    p = {"index": 40, "confirmed_at": 45, "price": 131.80, "side": "LOW",
         "norm": 2.1}
    p.update(over)
    return p


# ── 1 · identity: a timestamp, not a position ──────────────────────────

def test_the_timestamp_identifies_the_pivot_when_present():
    sig = FA.hvp_signature(_pivot(at="2026-08-28T10:14:00+05:30"), decimals=2)
    assert sig[2] == "2026-08-28T10:14:00+05:30"


def test_the_same_pivot_survives_the_window_sliding():
    """⚠️ THE FLOOD. One new bar shifts every index; the timestamp does not
    move, so the signature must not change."""
    at = "2026-08-28T10:14:00+05:30"
    before = FA.hvp_signature(_pivot(index=40, confirmed_at=45, at=at), decimals=2)
    after = FA.hvp_signature(_pivot(index=39, confirmed_at=44, at=at), decimals=2)
    assert before == after, "the same pivot re-alerts after the window slides"


def test_two_pivots_at_one_price_on_different_bars_stay_distinct():
    a = FA.hvp_signature(_pivot(at="2026-08-28T10:14:00+05:30"), decimals=2)
    b = FA.hvp_signature(_pivot(at="2026-08-28T11:02:00+05:30"), decimals=2)
    assert a != b


def test_confirmed_at_is_still_the_fallback_without_a_timestamp():
    """A caller that cannot supply timestamps keeps the old behaviour —
    imperfect identity beats no identity."""
    sig = FA.hvp_signature(_pivot(), decimals=2)
    assert sig[2] == 45


# ── 2 · the ball follows the MEASURED flow ─────────────────────────────

def test_a_swing_low_on_buying_reads_bullish_on_a_call():
    m = FA.hvp_message("CALL", "ATM CE 24100",
                       _pivot(side="LOW", buy_pct=78.0, sell_pct=22.0,
                              dominant="buyers"), decimals=2)
    assert m.startswith(BB.BALLS[BB.BULL])
    assert "BUY-led" in m and "78% buy" in m


def test_a_swing_low_on_SELLING_reads_bearish_even_though_it_is_a_low():
    """⚠️ The exact case the structural read gets wrong: a LOW would be called
    support (bullish on a CALL) by shape alone, but the volume was selling."""
    m = FA.hvp_message("CALL", "ATM CE 24100",
                       _pivot(side="LOW", buy_pct=19.0, sell_pct=81.0,
                              dominant="sellers"), decimals=2)
    assert m.startswith(BB.BALLS[BB.BEAR])
    assert "SELL-led" in m


def test_a_swing_high_on_buying_reads_bullish_even_though_it_is_a_high():
    m = FA.hvp_message("CALL", "ATM CE 24100",
                       _pivot(side="HIGH", buy_pct=74.0, sell_pct=26.0,
                              dominant="buyers"), decimals=2)
    assert m.startswith(BB.BALLS[BB.BULL])


def test_the_put_leg_still_inverts_on_the_measured_side():
    """A PUT's own buyers are NIFTY-bearish — the one inversion rule, applied
    to the measurement rather than to the shape."""
    call = FA.hvp_message("CALL", "ATM CE 24100",
                          _pivot(buy_pct=80.0, dominant="buyers"), decimals=2)
    put = FA.hvp_message("PUT", "ATM PE 24100",
                         _pivot(buy_pct=80.0, dominant="buyers"), decimals=2)
    assert call.startswith(BB.BALLS[BB.BULL])
    assert put.startswith(BB.BALLS[BB.BEAR])


def test_balanced_flow_is_reported_as_balanced_not_forced():
    m = FA.hvp_message("CALL", "ATM CE 24100",
                       _pivot(buy_pct=51.0, sell_pct=49.0, dominant="balanced"),
                       decimals=2)
    assert m.startswith(BB.BALLS[BB.NEUTRAL])
    assert "51% buy / 49% sell" in m
    assert "mixed" in m


# ── 2b · the split is an ESTIMATE and the text must not hide that ──────
#
# CLV is `(close - low) / (high - low)`: an inference from where the bar
# closed in its range, NOT a count of buy vs sell trades. Exact
# classification needs tick data with bid/ask, which Dhan's 1-minute OHLCV
# endpoint does not provide. Printing a bare "83% buy" claims a precision the
# method does not have.

def test_the_flow_line_is_marked_as_an_estimate():
    m = FA.hvp_message("CALL", "ATM CE 24100",
                       _pivot(buy_pct=83.0, dominant="buyers"), decimals=2)
    assert "est." in m, "the split is printed as if it were exact"
    assert "looks" in m, "the verb does not hedge"


def test_the_flow_line_names_its_basis():
    """A reader must be able to tell WHERE the number came from without
    reading the source."""
    m = FA.hvp_message("CALL", "ATM CE 24100",
                       _pivot(buy_pct=83.0, dominant="buyers"), decimals=2)
    assert "CLV" in m
    assert "not tick data" in m


def test_it_never_claims_the_flow_was_measured_exactly():
    for dom, bp in (("buyers", 83.0), ("sellers", 17.0), ("balanced", 50.0)):
        m = FA.hvp_message("CALL", "ATM CE 24100",
                           _pivot(buy_pct=bp, dominant=dom), decimals=2)
        low = m.lower()
        for overclaim in ("dominated", "exactly", "precisely"):
            assert overclaim not in low, f"{overclaim!r} overclaims in: {m}"


def test_an_unmeasured_pivot_falls_back_and_says_so():
    """Never silent — but it must not pretend the flow was measured."""
    m = FA.hvp_message("CALL", "ATM CE 24100", _pivot(), decimals=2)
    assert "flow not estimated" in m
    assert m.startswith(BB.BALLS[BB.hvp_bias("CALL", "LOW")])


# ── 3 · the annotator, and the strike-roll key ─────────────────────────

@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(_SRC.read_text())


def _func(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found")


def test_the_annotator_reuses_the_one_owner_of_buy_sell_attribution(tree):
    """⚠️ `indicators.order_flow.split` — the same CLV-weighted attribution
    `analyze_vob_volume` and the CVD graphs use. Not a second estimator."""
    src = ast.unparse(_func(tree, "_annotate_hv_pivots"))
    assert "_of.split" in src
    assert "_of.is_missing" in src


def test_the_annotator_attaches_a_timestamp_and_a_split(tree):
    src = ast.unparse(_func(tree, "_annotate_hv_pivots"))
    for field in ("'at'", "'buy_pct'", "'sell_pct'", "'dominant'"):
        assert field in src, f"{field} never set"


def test_the_annotator_is_wired_into_hv_points(tree):
    """A helper nothing calls never runs."""
    src = ast.unparse(_func(tree, "_hv_points"))
    assert "_annotate_hv_pivots" in src


def test_an_unmeasurable_pivot_is_skipped_not_raised_on(tree):
    src = ast.unparse(_func(tree, "_annotate_hv_pivots"))
    assert "continue" in src, "no defensive skip for a malformed pivot"


def test_the_dedup_key_includes_the_leg_label(tree):
    """⚠️ THE STRIKE-ROLL BURST. Keyed on 'CALL' alone, an ATM roll carried the
    OLD contract's seen-set onto the new one, so every pivot on the new strike
    was unseen and fired at once."""
    src = _SRC.read_text()
    assert 'key = f"{kind}:{chart}:{labels.get(chart) or chart}"' in src
