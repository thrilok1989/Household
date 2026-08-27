"""🔭 Live Market Confluence — an assembler, not another engine.

Eleven existing reads, laid side by side: where spot sits against its own
support/resistance, which option side has more going on right now, each
option leg's own participation and premium behaviour, Stage 42's war zone,
and the broader (global / sector / news / regime) context. Every number here
was already computed somewhere else in the app; this module counts which
way each one points and says whether they agree.

## The one rule that decided the shape of this module

**High volume on a side means nothing on its own.** A PUT can trade heavily
because it is being bought as a hedge (bearish) or sold into strength
(bullish) — volume alone cannot tell those apart. So a side's OWN spike vs
its OWN history (`leg_participation`'s magnitude) is shown but never voted.
What DOES vote is a comparison: `price_action` weighs CALL's total
cumulative buy+sell against PUT's — heavier CALL participation votes
bullish, heavier PUT votes bearish, by the desk's own stated convention —
and `leg_location` weighs WHERE a leg is trading (a VOB support/resistance
zone or an HVP high/low), through `bias_ball`'s existing leg-inversion rule.
The same split applies to premium energy: a side's own premium rising or
falling votes; the state label describing why (building/squeeze vs
distribution/unwinding) is shown, not separately voted.

## Majority, ties go to MIXED

`assess()` counts BULL votes against BEAR votes among whatever evidence is
readable this cycle (missing or NEUTRAL evidence casts no vote). More BULLs
→ BULLISH. More BEARs → BEARISH. Equal — including 0 vs 0 — → MIXED. A
confident wrong answer is worse than an honest "no dominant alignment", which
is the same three-state discipline every other panel in this app already
follows.

## Pinned overrides the vote entirely

A magnet strike is not evidence for either side — `entry_gate`'s own PINNED
state already says so ("no directional edge, WAIT"). When `pinned=True` this
returns a PINNED verdict before any vote is taken, rather than counting a
pin as one more neutral input among many.

Pure: facts in, a verdict + the evidence behind it out. No app import, no
session, no I/O, and nothing here recomputes a VOB zone, an HVP pivot, a
CVD, a premium-energy state or a bias score — every one of those has exactly
one producer elsewhere, and this module only reads its output through
`bias_ball`, the app's own single home for "which way does this option-leg
fact point for NIFTY".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import bias_ball as BB

BULL, BEAR, NEUTRAL = BB.BULL, BB.BEAR, BB.NEUTRAL

#: how far CALL's and PUT's cumulative buy+sell volume must diverge, as a
#: fraction of their combined total, to call one side heavier rather than
#: "balanced participation" — the desk's own margin for this comparison.
PRICE_ACTION_MARGIN = 0.10

#: |global nifty_score| below this is "neutral", matching compute_global_
#: nifty_bias's own neutral band (its label thresholds start at ±1).
GLOBAL_THRESHOLD = 1.0

#: net (bullish − bearish) headline count below this is "neutral".
NEWS_THRESHOLD = 1.0

#: sector rotation: (bullish − bearish) sector count below this is "neutral" —
#: a one-sector edge out of eleven is noise, not a rotation.
SECTOR_MARGIN = 2

#: a leg's own premium direction, from Stage 50's OI×LTP quadrant (see
#: mios_v5/ltp_behaviour.py): building/squeeze = premium rising,
#: distribution/unwinding = premium falling.
_ENERGY_RISING = ("building", "squeeze")
_ENERGY_FALLING = ("distribution", "unwinding")


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def spot_location(zone: Optional[str], level: Any = None) -> Dict[str, Any]:
    """Where spot sits against the canonical support/resistance zone
    `entry_gate` already resolved. Read straight — NIFTY panel, not a leg."""
    z = str(zone or "").upper()
    lv = _f(level)
    if z == "SUPPORT":
        label = f"At Support ₹{lv:,.0f}" if lv is not None else "At Support"
        bias = BULL
    elif z == "RESISTANCE":
        label = f"At Resistance ₹{lv:,.0f}" if lv is not None else "At Resistance"
        bias = BEAR
    else:
        label, bias = "Between levels", NEUTRAL
    return {"key": "spot_location", "label": label, "bias": bias}


def price_action(call_total: Any, put_total: Any,
                 margin: float = PRICE_ACTION_MARGIN) -> Dict[str, Any]:
    """Which side has MORE going on — CALL's own cumulative buy+sell volume
    against PUT's, both already published by the same `_atm_flow_hist`
    aggregate `flow_level_alerts` reads. This is a comparison of two
    magnitudes, not an inference from either one alone: heavier CALL
    participation votes bullish, heavier PUT votes bearish, by the desk's
    own convention — not a claim that a busy PUT is inherently bearish on
    its own (that claim was corrected earlier: volume alone means nothing).
    """
    c, p = _f(call_total), _f(put_total)
    if c is None and p is None:
        return {"key": "price_action", "label": "Participation unavailable",
               "bias": NEUTRAL, "value": None}
    c, p = (c or 0.0), (p or 0.0)
    total = c + p
    if total <= 0:
        return {"key": "price_action", "label": "No participation yet",
               "bias": NEUTRAL, "value": 0.0}
    diff = (c - p) / total
    if diff >= margin:
        return {"key": "price_action",
                "label": f"CALL cumulative volume > PUT ({diff * 100:+.0f}%)",
                "bias": BULL, "value": diff}
    if diff <= -margin:
        return {"key": "price_action",
                "label": f"PUT cumulative volume > CALL ({diff * 100:+.0f}%)",
                "bias": BEAR, "value": diff}
    return {"key": "price_action",
           "label": f"Balanced CALL/PUT participation ({diff * 100:+.0f}%)",
           "bias": NEUTRAL, "value": diff}


def leg_location(leg: str, vob_role: Optional[str] = None,
                 hvp_side: Optional[str] = None) -> Dict[str, Any]:
    """Where THIS leg's own LTP sits — a VOB zone if it's in one, else an HVP
    line if it's touching one, else nothing. VOB is checked first: a zone is
    a range the price is actually inside, a pivot line is a single point —
    the range is the stronger claim when both happen to be true at once.
    """
    word = leg.title()
    if vob_role:
        bias = BB.vob_bias(leg, vob_role)
        zone_word = ("Support" if str(vob_role).lower() in ("support", "bullish")
                    else "Resistance")
        return {"key": f"{leg.lower()}_location",
                "label": f"{word} LTP at VOB {zone_word}", "bias": bias}
    if hvp_side:
        bias = BB.hvp_bias(leg, hvp_side)
        pivot_word = "High" if str(hvp_side).upper() == "HIGH" else "Low"
        return {"key": f"{leg.lower()}_location",
                "label": f"{word} LTP at HVP {pivot_word}", "bias": bias}
    return {"key": f"{leg.lower()}_location",
           "label": f"{word} — no zone/pivot contact", "bias": NEUTRAL}


def leg_energy(leg: str, state: Optional[str]) -> Dict[str, Any]:
    """A leg's own premium direction from Stage 50's already-computed
    building/distribution/unwinding/squeeze state. Routed through
    `bias_ball.poc_bias`, which already encodes "a leg's premium rising is
    bullish for NIFTY on CALL, bearish on PUT" — the identical rule this
    needs, so it is reused rather than re-derived.
    """
    s = str(state or "").lower()
    word = leg.title()
    if s in _ENERGY_RISING:
        return {"key": f"{leg.lower()}_energy",
                "label": f"{word} Energy: LOADED ({s})",
                "bias": BB.poc_bias(leg, "UP")}
    if s in _ENERGY_FALLING:
        return {"key": f"{leg.lower()}_energy",
                "label": f"{word} Energy: FADING ({s})",
                "bias": BB.poc_bias(leg, "DOWN")}
    return {"key": f"{leg.lower()}_energy",
           "label": f"{word} Energy: Neutral", "bias": NEUTRAL}


def _score_vote(name: str, score: Optional[float], threshold: float,
                bull_word: str = "BULLISH", bear_word: str = "BEARISH"
                ) -> Dict[str, Any]:
    s = _f(score)
    if s is None:
        return {"key": name, "label": f"{name.title()}: unavailable", "bias": NEUTRAL}
    if s >= threshold:
        return {"key": name, "label": f"{name.title()}: {bull_word}", "bias": BULL}
    if s <= -threshold:
        return {"key": name, "label": f"{name.title()}: {bear_word}", "bias": BEAR}
    return {"key": name, "label": f"{name.title()}: Neutral", "bias": NEUTRAL}


def regime_vote(regime: Optional[str]) -> Dict[str, Any]:
    """The market regime (`_market_picture.regime`, already computed) —
    UP/DOWN/SIDEWAYS, read straight through `bias_ball.direction_bias`."""
    bias = BB.direction_bias(regime)
    word = {BULL: "UP", BEAR: "DOWN"}.get(bias, "SIDEWAYS")
    return {"key": "regime", "label": f"Market Regime: {word}", "bias": bias}


def war_zone_vote(winner: Optional[str]) -> Dict[str, Any]:
    """Stage 42's battle zone — who is expected to win the level spot is
    fighting at (`final_read.expected_winner`), through `bias_ball.winner_bias`
    (buyers → bullish, sellers → bearish, anything else neutral)."""
    bias = BB.winner_bias(winner)
    word = str(winner or "").strip() or "No fight"
    return {"key": "war_zone", "label": f"War Zone: {word}", "bias": bias}


def assess(
    pinned: bool = False, pin_level: Any = None,
    zone: Optional[str] = None, level: Any = None,
    call_total: Any = None, put_total: Any = None,
    call_spiking: bool = False, call_vob_role: Optional[str] = None,
    call_hvp_side: Optional[str] = None, call_energy_state: Optional[str] = None,
    put_spiking: bool = False, put_vob_role: Optional[str] = None,
    put_hvp_side: Optional[str] = None, put_energy_state: Optional[str] = None,
    global_score: Any = None, sector_bull: Any = None, sector_bear: Any = None,
    news_score: Any = None, regime: Optional[str] = None,
    war_zone_winner: Optional[str] = None,
) -> Dict[str, Any]:
    """The full card model: PINNED override, or an eleven-vote majority
    (ties → MIXED). Every argument is a fact some other engine already
    published — nothing here is computed from a raw series.
    """
    if pinned:
        lv = _f(pin_level)
        return {
            "pinned": True,
            "pin_level": lv,
            "verdict": "PINNED",
            "votes": [],
            "bull_count": 0, "bear_count": 0, "neutral_count": 0,
            "call_spiking": bool(call_spiking), "put_spiking": bool(put_spiking),
        }

    sec_score = None
    if sector_bull is not None or sector_bear is not None:
        sec_score = (_f(sector_bull) or 0.0) - (_f(sector_bear) or 0.0)

    votes: List[Dict[str, Any]] = [
        spot_location(zone, level),
        price_action(call_total, put_total),
        leg_location("CALL", call_vob_role, call_hvp_side),
        leg_location("PUT", put_vob_role, put_hvp_side),
        leg_energy("CALL", call_energy_state),
        leg_energy("PUT", put_energy_state),
        _score_vote("global", global_score, GLOBAL_THRESHOLD),
        _score_vote("sector", sec_score, SECTOR_MARGIN),
        _score_vote("news", news_score, NEWS_THRESHOLD),
        regime_vote(regime),
        war_zone_vote(war_zone_winner),
    ]
    bulls = [v for v in votes if v["bias"] == BULL]
    bears = [v for v in votes if v["bias"] == BEAR]
    if len(bulls) > len(bears):
        verdict = "BULLISH"
    elif len(bears) > len(bulls):
        verdict = "BEARISH"
    else:
        verdict = "MIXED"

    return {
        "pinned": False,
        "verdict": verdict,
        "votes": votes,
        "bull_count": len(bulls), "bear_count": len(bears),
        "neutral_count": len(votes) - len(bulls) - len(bears),
        "call_spiking": bool(call_spiking), "put_spiking": bool(put_spiking),
    }
