"""🔭 Live Market Confluence: an assembler over eleven already-published reads.

High volume alone is never a vote — only WHERE it trades (a VOB zone / HVP
line) or WHICH WAY a leg's own premium is moving votes, both routed through
`bias_ball`'s existing leg-inversion rule so a PUT and a CALL never get the
same sign for the same underlying fact. Ties (including 0 vs 0) → MIXED, and
a pinned strike overrides the vote entirely rather than casting one.
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import live_confluence as LC

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── spot_location ──────────────────────────────────────────────────────

def test_support_is_bullish_resistance_is_bearish():
    assert LC.spot_location("SUPPORT", 24000)["bias"] == LC.BULL
    assert LC.spot_location("RESISTANCE", 24100)["bias"] == LC.BEAR


def test_no_zone_is_neutral():
    assert LC.spot_location(None)["bias"] == LC.NEUTRAL
    assert LC.spot_location("")["bias"] == LC.NEUTRAL


# ── price_action: CALL's cumulative volume vs PUT's, not either alone ──

def test_heavier_call_participation_is_bullish():
    r = LC.price_action(call_total=8000, put_total=2000)
    assert r["bias"] == LC.BULL and "CALL" in r["label"]


def test_heavier_put_participation_is_bearish():
    r = LC.price_action(call_total=2000, put_total=8000)
    assert r["bias"] == LC.BEAR and "PUT" in r["label"]


def test_roughly_even_participation_under_the_margin_is_neutral():
    r = LC.price_action(call_total=5200, put_total=4800)
    assert r["bias"] == LC.NEUTRAL


def test_both_totals_missing_is_neutral_not_zero():
    r = LC.price_action(None, None)
    assert r["bias"] == LC.NEUTRAL and "unavailable" in r["label"]


def test_one_side_missing_is_treated_as_zero_on_that_side():
    """No PUT activity at all with real CALL activity is still a real
    (bullish) comparison, not a refusal to answer."""
    r = LC.price_action(call_total=5000, put_total=None)
    assert r["bias"] == LC.BULL


def test_zero_participation_on_both_sides_is_neutral():
    r = LC.price_action(call_total=0, put_total=0)
    assert r["bias"] == LC.NEUTRAL and "No participation" in r["label"]


# ── leg_location: VOB beats HVP, and PUT inverts ───────────────────────

def test_call_at_vob_support_is_bullish():
    assert LC.leg_location("CALL", vob_role="support")["bias"] == LC.BULL


def test_put_at_vob_support_is_bearish():
    """The exact inversion the desk corrected earlier this session: a PUT's
    OWN support is bearish for NIFTY, not bullish."""
    assert LC.leg_location("PUT", vob_role="support")["bias"] == LC.BEAR


def test_call_at_vob_resistance_is_bearish():
    assert LC.leg_location("CALL", vob_role="resistance")["bias"] == LC.BEAR


def test_put_at_vob_resistance_is_bullish():
    assert LC.leg_location("PUT", vob_role="resistance")["bias"] == LC.BULL


def test_vob_role_is_checked_before_hvp():
    r = LC.leg_location("CALL", vob_role="support", hvp_side="HIGH")
    assert "VOB" in r["label"]


def test_hvp_high_and_low_route_through_the_same_leg_inversion():
    assert LC.leg_location("CALL", hvp_side="HIGH")["bias"] == LC.BEAR
    assert LC.leg_location("PUT", hvp_side="HIGH")["bias"] == LC.BULL
    assert LC.leg_location("CALL", hvp_side="LOW")["bias"] == LC.BULL
    assert LC.leg_location("PUT", hvp_side="LOW")["bias"] == LC.BEAR


def test_no_contact_is_neutral():
    r = LC.leg_location("CALL")
    assert r["bias"] == LC.NEUTRAL and "no zone/pivot" in r["label"]


# ── leg_energy: rising/falling premium, PUT inverts ────────────────────

def test_call_building_or_squeeze_is_bullish():
    assert LC.leg_energy("CALL", "building")["bias"] == LC.BULL
    assert LC.leg_energy("CALL", "squeeze")["bias"] == LC.BULL


def test_put_building_or_squeeze_is_bearish():
    """PUT premium rising is bearish for NIFTY."""
    assert LC.leg_energy("PUT", "building")["bias"] == LC.BEAR
    assert LC.leg_energy("PUT", "squeeze")["bias"] == LC.BEAR


def test_call_distribution_or_unwinding_is_bearish():
    assert LC.leg_energy("CALL", "distribution")["bias"] == LC.BEAR
    assert LC.leg_energy("CALL", "unwinding")["bias"] == LC.BEAR


def test_put_distribution_or_unwinding_is_bullish():
    assert LC.leg_energy("PUT", "distribution")["bias"] == LC.BULL
    assert LC.leg_energy("PUT", "unwinding")["bias"] == LC.BULL


def test_flat_or_missing_energy_is_neutral():
    assert LC.leg_energy("CALL", "flat")["bias"] == LC.NEUTRAL
    assert LC.leg_energy("CALL", None)["bias"] == LC.NEUTRAL


def test_the_energy_label_shows_loaded_or_fading():
    assert "LOADED" in LC.leg_energy("PUT", "building")["label"]
    assert "FADING" in LC.leg_energy("PUT", "unwinding")["label"]


# ── regime_vote ─────────────────────────────────────────────────────────

def test_regime_up_is_bullish_down_is_bearish_sideways_is_neutral():
    assert LC.regime_vote("UP")["bias"] == LC.BULL
    assert LC.regime_vote("DOWN")["bias"] == LC.BEAR
    assert LC.regime_vote("SIDEWAYS")["bias"] == LC.NEUTRAL


# ── war_zone_vote: Stage 42's expected winner, NIFTY panel, read straight ──

def test_buyers_winning_is_bullish_sellers_is_bearish():
    assert LC.war_zone_vote("Buyers")["bias"] == LC.BULL
    assert LC.war_zone_vote("Sellers")["bias"] == LC.BEAR


def test_contested_or_no_fight_is_neutral():
    assert LC.war_zone_vote("Contested")["bias"] == LC.NEUTRAL
    assert LC.war_zone_vote(None)["bias"] == LC.NEUTRAL
    assert "No fight" in LC.war_zone_vote(None)["label"]


# ── assess(): the ten-vote majority, ties → MIXED ──────────────────────

def _bull_facts():
    """Every vote pointing bullish."""
    return dict(
        zone="SUPPORT", level=24000, call_total=8000, put_total=2000,
        call_vob_role="support", put_vob_role="resistance",
        call_energy_state="building", put_energy_state="unwinding",
        global_score=3, sector_bull=8, sector_bear=1, news_score=3,
        regime="UP", war_zone_winner="Buyers",
    )


def test_unanimous_bullish_facts_verdict_bullish():
    out = LC.assess(**_bull_facts())
    assert out["verdict"] == "BULLISH"
    assert out["bull_count"] == 11 and out["bear_count"] == 0


def test_unanimous_bearish_is_the_mirror():
    facts = _bull_facts()
    flipped = dict(
        zone="RESISTANCE", level=24100, call_total=2000, put_total=8000,
        call_vob_role="resistance", put_vob_role="support",
        call_energy_state="unwinding", put_energy_state="building",
        global_score=-3, sector_bull=1, sector_bear=8, news_score=-3,
        regime="DOWN", war_zone_winner="Sellers",
    )
    out = LC.assess(**flipped)
    assert out["verdict"] == "BEARISH"
    assert out["bear_count"] == 11 and out["bull_count"] == 0


def test_no_facts_at_all_is_mixed_not_bullish():
    out = LC.assess()
    assert out["verdict"] == "MIXED"
    assert out["bull_count"] == 0 and out["bear_count"] == 0


def test_an_exact_tie_is_mixed():
    """Spot bullish (support), regime bearish (down) — everything else
    unreadable → 1 vs 1 → MIXED, not forced either way."""
    out = LC.assess(zone="SUPPORT", level=24000, regime="DOWN")
    assert out["bull_count"] == 1 and out["bear_count"] == 1
    assert out["verdict"] == "MIXED"


def test_a_narrow_majority_still_wins():
    out = LC.assess(zone="SUPPORT", level=24000, regime="UP",
                    call_energy_state="unwinding")   # bull, bull, bear
    assert out["bull_count"] == 2 and out["bear_count"] == 1
    assert out["verdict"] == "BULLISH"


# ── pinned overrides the vote entirely ─────────────────────────────────

def test_pinned_short_circuits_before_any_vote():
    out = LC.assess(pinned=True, pin_level=24000, **_bull_facts())
    assert out["verdict"] == "PINNED"
    assert out["votes"] == []
    assert out["pin_level"] == 24000.0


def test_pinned_is_not_counted_as_neutral_among_ten_votes():
    """A pin is not "one more neutral input" — the whole vote is skipped."""
    out = LC.assess(pinned=True)
    assert out["bull_count"] == 0 and out["bear_count"] == 0
    assert "votes" in out and len(out["votes"]) == 0


# ── participation magnitude is carried but never voted ─────────────────

def test_spiking_flags_pass_through_without_affecting_the_vote():
    a = LC.assess(put_spiking=True)
    b = LC.assess(put_spiking=False)
    assert a["put_spiking"] is True and b["put_spiking"] is False
    assert a["verdict"] == b["verdict"] == "MIXED"


# ── purity ──────────────────────────────────────────────────────────────

def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "live_confluence.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas", "requests"}
    assert "session_state" not in src


def test_nothing_here_recomputes_a_published_engine():
    """⚠️ The whole premise: every fact arrives pre-resolved. This module must
    not touch a raw OHLCV series, an option chain, or a yfinance fetch."""
    src = (_ROOT / "mios_v5" / "live_confluence.py").read_text()
    tree = ast.parse(src)
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    assert not {"analyze_vob_volume", "detect_hvp", "calculate_vidya",
               "compute_global_nifty_bias", "compute_sector_rotation",
               "compute_news_bias", "activity_spike"} & called
