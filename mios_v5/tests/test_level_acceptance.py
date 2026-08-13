"""⚔️ Level Acceptance / Rejection observation strip.

The strip must be an *observation* of the reused Stage-42 engine, never a second
engine: it maps that engine's verdict to six words, runs it per level, and
clusters nearby levels — and it must never predict, never emit a trade, and never
call a failed break a rejection early. Most tests inject a fake reaction function
so the mapping/clustering are pinned deterministically; a few drive the REAL
`evaluate_reaction` to prove the wiring maps end to end.
"""

from __future__ import annotations

import pathlib

import mios_v5.level_acceptance as LA
from mios_v5.acceptance import evaluate_reaction

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── a controllable stand-in for the Stage-42 engine ────────────────────
def _fake(state, checks=None, confidence=0, reasons=()):
    def _fn(zone, spot, metrics, prev):
        return {"state": state, "side": zone.get("side"),
                "checks": dict(checks or {}), "confidence": confidence,
                "reasons": list(reasons), "memory": {"state": state}}
    return _fn


def _obs(level, spot, fn, prev=None):
    return LA.observe_one(level, spot, {}, prev, fn)


# ── the vocabulary mapping ─────────────────────────────────────────────

def test_touch_and_watching_are_testing_not_rejection():
    for s in ("TOUCH", "WATCHING"):
        assert LA.map_observed(s, "RESISTANCE")["observed"] == LA.TESTING


def test_break_is_break_attempt_with_a_direction():
    up = LA.map_observed("BREAK", "RESISTANCE")
    dn = LA.map_observed("BREAK", "SUPPORT")
    assert up["observed"] == LA.BREAK_ATTEMPT and up["direction"] == "ABOVE"
    assert dn["observed"] == LA.BREAK_ATTEMPT and dn["direction"] == "BELOW"


def test_confirmed_and_acceptance_map_to_accepted_side():
    assert LA.map_observed("CONFIRMED_BREAKOUT", "RESISTANCE")["observed"] == LA.ACCEPTED_ABOVE
    assert LA.map_observed("CONFIRMED_BREAKDOWN", "SUPPORT")["observed"] == LA.ACCEPTED_BELOW
    # generic ACCEPTANCE resolves by which side the level was
    assert LA.map_observed("ACCEPTANCE", "RESISTANCE")["observed"] == LA.ACCEPTED_ABOVE
    assert LA.map_observed("ACCEPTANCE", "SUPPORT")["observed"] == LA.ACCEPTED_BELOW


def test_failed_break_family_is_wait_never_rejected():
    for s in ("FAILED_BREAKOUT", "FAILED_BREAKDOWN", "ABSORPTION"):
        assert LA.map_observed(s, "RESISTANCE")["observed"] == LA.FAILED_BREAK_WAIT


def test_rejection_and_traps_and_sweeps_are_rejected():
    for s in ("REJECTION", "BULL_TRAP", "BEAR_TRAP", "SWEEP_BUY", "SWEEP_SELL"):
        assert LA.map_observed(s, "RESISTANCE")["observed"] == LA.REJECTED


def test_idle_and_unknown_are_omitted():
    assert LA.map_observed("IDLE", "SUPPORT")["observed"] is None
    assert LA.map_observed("", "SUPPORT")["observed"] is None
    assert LA.map_observed("SOMETHING_NEW", "SUPPORT")["observed"] is None


# ── side inference (one engine judges any level type) ──────────────────

def test_side_is_inferred_from_position_relative_to_spot():
    assert LA.infer_side(24450, 24400) == "RESISTANCE"   # overhead
    assert LA.infer_side(24350, 24400) == "SUPPORT"      # below
    assert LA.infer_side(None, 24400) is None


# ── acceptance path ────────────────────────────────────────────────────

def test_break_then_hold_reads_accepted_above():
    o = _obs({"label": "R1", "price": 24400}, 24415,
             _fake("CONFIRMED_BREAKOUT",
                   {"price_held": True, "cvd_continued": True,
                    "volume_expanded": True, "oi_unwound": None}))
    assert o["observed"] == LA.ACCEPTED_ABOVE
    assert o["checks"] == {"Hold": True, "CVD": True, "Volume": True}
    assert o["passed"] == 3 and o["known"] == 3        # unknown OI dropped


def test_three_of_five_is_enough_and_unknown_metrics_are_dropped():
    o = _obs({"label": "R1", "price": 24400}, 24415,
             _fake("ACCEPTANCE",
                   {"price_held": True, "cvd_continued": True,
                    "volume_expanded": True, "mf_continued": False,
                    "oi_unwound": None, "dealers_flipped": None}))
    # 3 passed of 4 known; the two unmeasured checks neither count nor invent
    assert o["passed"] == 3 and o["known"] == 4
    assert "OI" not in o["checks"] and "Dealers" not in o["checks"]


# ── failed-break / rejection path ──────────────────────────────────────

def test_break_then_return_is_failed_break_wait_not_rejected():
    o = _obs({"label": "R1", "price": 24400}, 24398,
             _fake("FAILED_BREAKOUT", {"price_held": False}))
    assert o["observed"] == LA.FAILED_BREAK_WAIT      # the critical "wait"


def test_confirmed_reversal_is_rejected():
    o = _obs({"label": "R1", "price": 24400}, 24390,
             _fake("REJECTION",
                   {"price_held": False, "cvd_continued": True,
                    "volume_expanded": True}))
    assert o["observed"] == LA.REJECTED


# ── testing / tolerance edges ──────────────────────────────────────────

def test_price_at_and_around_level_reads_testing():
    for spot in (24400, 24398, 24402):
        o = _obs({"label": "Mag", "price": 24400}, spot, _fake("TOUCH"))
        assert o["observed"] == LA.TESTING


# ── reset semantics ────────────────────────────────────────────────────

def test_a_moved_level_resets_its_reaction_memory():
    # first the level is at 24400 with live memory
    o1 = _obs({"label": "Mag", "price": 24400}, 24400, _fake("WATCHING"))
    assert o1["memory"].get("_price") == 24400
    # the magnet jumps to 24450 (> RESET_EPS) → memory must NOT carry the old ref
    seen = {}

    def _capture(zone, spot, metrics, prev):
        seen["prev"] = prev
        return {"state": "TOUCH", "side": zone["side"], "checks": {},
                "confidence": 0, "reasons": [], "memory": {"state": "TOUCH"}}

    _obs({"label": "Mag", "price": 24450}, 24450, _capture, prev=o1["memory"])
    assert seen["prev"] is None                        # reset, not stale ref


def test_a_small_wobble_keeps_the_reaction_memory():
    o1 = _obs({"label": "Mag", "price": 24400}, 24400, _fake("BREAK"))
    seen = {}

    def _capture(zone, spot, metrics, prev):
        seen["prev"] = prev
        return {"state": "BREAK", "side": zone["side"], "checks": {},
                "confidence": 0, "reasons": [], "memory": {"state": "BREAK"}}

    _obs({"label": "Mag", "price": 24401}, 24405, _capture, prev=o1["memory"])
    assert seen["prev"] is not None                    # within RESET_EPS, kept


# ── clustering (battle zone) ───────────────────────────────────────────

def test_nearby_levels_collapse_into_one_battle_zone():
    obs = [
        {"label": "VAH", "price": 24398, "observed": LA.TESTING, "direction": None,
         "checks": {}, "passed": 0, "known": 0, "confidence": 0},
        {"label": "Resistance", "price": 24399, "observed": LA.BREAK_ATTEMPT,
         "direction": "ABOVE", "checks": {}, "passed": 0, "known": 0, "confidence": 0},
        {"label": "Dealer magnet", "price": 24400, "observed": LA.ACCEPTED_ABOVE,
         "direction": "ABOVE", "checks": {"Hold": True}, "passed": 1, "known": 1,
         "confidence": 60},
        {"label": "Support", "price": 24350, "observed": LA.TESTING, "direction": None,
         "checks": {}, "passed": 0, "known": 0, "confidence": 0},
    ]
    zones = LA.cluster(obs, tolerance=5.0)
    assert len(zones) == 2                              # the 24,400 cluster + support
    battle = next(z for z in zones if z["is_battle_zone"])
    lone = next(z for z in zones if not z["is_battle_zone"])
    assert battle["price"] == 24400                    # takes the magnet's price
    # the most-resolved member is the headline
    assert battle["observed"] == LA.ACCEPTED_ABOVE
    assert set(battle["labels"]) == {"VAH", "Resistance", "Dealer magnet"}
    assert lone["price"] == 24350


def test_each_level_keeps_its_own_state_when_far_apart():
    obs = [
        {"label": "Resistance", "price": 24450, "observed": LA.ACCEPTED_BELOW,
         "direction": "BELOW", "checks": {}, "passed": 0, "known": 0, "confidence": 0},
        {"label": "Magnet", "price": 24400, "observed": LA.TESTING, "direction": None,
         "checks": {}, "passed": 0, "known": 0, "confidence": 0},
        {"label": "Support", "price": 24350, "observed": LA.TESTING, "direction": None,
         "checks": {}, "passed": 0, "known": 0, "confidence": 0},
    ]
    zones = LA.cluster(obs, tolerance=5.0)
    assert len(zones) == 3                              # not collapsed
    assert {z["price"] for z in zones} == {24450, 24400, 24350}


# ── the whole strip ────────────────────────────────────────────────────

def test_observe_levels_is_context_only_and_omits_idle():
    levels = [
        {"label": "Dealer magnet", "price": 24400},
        {"label": "Resistance", "price": 24401},
        {"label": "Support", "price": 24350},
    ]
    store = {}
    # magnet contested → CONFIRMED; support far & idle
    def _fn(zone, spot, metrics, prev):
        s = "CONFIRMED_BREAKOUT" if abs(zone["price"] - 24400) <= 2 else "IDLE"
        return {"state": s, "side": zone["side"], "checks": {"price_held": True},
                "confidence": 55, "reasons": [], "memory": {"state": s}}
    out = LA.observe_levels(levels, 24412, {}, store, _fn, tolerance=5.0)
    assert out["context_only"] is True
    # one battle zone shown (magnet+resistance), the idle support omitted
    assert len(out["zones"]) == 1
    assert out["zones"][0]["observed"] == LA.ACCEPTED_ABOVE
    # memory persisted per label for the next rerun
    assert set(store) == {"Dealer magnet", "Resistance", "Support"}


def test_missing_spot_or_price_is_safe():
    o = _obs({"label": "X", "price": None}, 24400, _fake("TOUCH"))
    assert o["observed"] is None
    o2 = _obs({"label": "X", "price": 24400}, None, _fake("TOUCH"))
    assert o2["observed"] is None


# ── end-to-end against the REAL engine (proves the wiring) ─────────────

def test_real_engine_touch_reads_testing():
    # spot right at a resistance, no follow-through metrics → the real engine
    # returns a TOUCH/WATCHING which must surface as TESTING
    o = LA.observe_one({"label": "R1", "price": 24400}, 24401, {}, None,
                       evaluate_reaction)
    assert o["observed"] in (LA.TESTING, None)          # never a trade word
    assert o["raw_state"] in ("TOUCH", "WATCHING", "IDLE")


def test_real_engine_away_from_level_is_omitted():
    o = LA.observe_one({"label": "R1", "price": 24400}, 24250, {}, None,
                       evaluate_reaction)
    assert o["observed"] is None                        # not contested → omitted


# ── invariant: this strip cannot emit a trade ──────────────────────────

def test_no_observed_state_is_a_trade_word():
    words = {LA.TESTING, LA.BREAK_ATTEMPT, LA.ACCEPTED_ABOVE, LA.ACCEPTED_BELOW,
             LA.FAILED_BREAK_WAIT, LA.REJECTED}
    for w in words:
        low = w.lower()
        for banned in ("buy", "sell", "enter", "long", "short", "call", "put"):
            assert banned not in low


def test_observe_levels_always_flags_context_only():
    out = LA.observe_levels([{"label": "R", "price": 24400}], 24400, {}, {},
                            _fake("CONFIRMED_BREAKOUT", {"price_held": True}))
    assert out["context_only"] is True


# ── the app wiring (source-pinned; vob_minimal can't be imported here) ─

def test_the_app_reuses_the_engine_and_stays_context_only():
    src = (_ROOT / "vob_minimal.py").read_text()
    # reuses the Stage-42 engine + the new strip, does not recompute a reaction
    assert "from mios_v5.acceptance import evaluate_reaction" in src
    assert "observe_levels" in src and "acceptance_html" in src
    # per-level memory persisted in session state, keyed per level
    assert "_level_accept_mem" in src
    # reuses the SAME published follow-through metrics, not a re-gather
    assert "stage42_acceptance" in src
    assert "'metrics'" in src or '"metrics"' in src


def test_stage42_publishes_metrics_for_reuse():
    src = (_ROOT / "mios_v5" / "engines" / "stage42_acceptance.py").read_text()
    assert '"metrics": metrics' in src


def test_guardian_does_not_consume_the_new_strip():
    """Invariant: the observation strip must not feed the decision path. No
    Guardian/final-read/decision module may import level_acceptance."""
    for mod in ("final_read.py", "decision.py", "decision_v2.py",
                "premium_structure.py"):
        p = _ROOT / "mios_v5" / mod
        if p.exists():
            assert "level_acceptance" not in p.read_text(), mod
