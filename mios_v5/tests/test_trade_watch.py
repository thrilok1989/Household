"""🎯 Trade watch: WAIT-or-EXIT for a trade already taken, judged on the
combination of the engine's own vote AND the level protecting the trade —
never either alone, and never a cross-leg or reversal-only read.
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import trade_watch as T

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── protect_level ──────────────────────────────────────────────────────

def test_call_is_protected_by_support():
    assert T.protect_level("CALL", support=24000, resistance=24200) == 24000.0


def test_put_is_protected_by_resistance():
    assert T.protect_level("PUT", support=24000, resistance=24200) == 24200.0


def test_an_unknown_side_has_no_protection():
    assert T.protect_level("FLAT", support=24000, resistance=24200) is None


# ── assess: NONE when there is nothing to watch ────────────────────────

def test_no_side_is_none_not_wait():
    r = T.assess(None, entry_spot=24000, spot=24000, net=0, protect=23950)
    assert r["signal"] == "NONE"


def test_no_entry_or_no_live_spot_is_none():
    assert T.assess("CALL", entry_spot=None, spot=24000, net=0, protect=23950)["signal"] == "NONE"
    assert T.assess("CALL", entry_spot=24000, spot=None, net=0, protect=23950)["signal"] == "NONE"


# ── assess: WAIT unless BOTH turn against the side ─────────────────────

def test_call_holds_while_the_engine_still_favours_it():
    """Support broken but the engine vote is still up → WAIT, not EXIT."""
    r = T.assess("CALL", entry_spot=24000, spot=23960, net=3, protect=23990)
    assert r["signal"] == "WAIT"
    assert r["zone_against"] is True
    assert r["engine_against"] is False


def test_call_holds_while_the_zone_still_protects_it():
    """Engine flipped against, but support has not actually broken → WAIT."""
    r = T.assess("CALL", entry_spot=24000, spot=23995, net=-3, protect=23990)
    assert r["signal"] == "WAIT"
    assert r["engine_against"] is True
    assert r["zone_against"] is False


def test_call_exits_only_once_both_turn_against_it():
    r = T.assess("CALL", entry_spot=24000, spot=23950, net=-3, protect=23990)
    assert r["engine_against"] is True and r["zone_against"] is True
    assert r["signal"] == "EXIT"


def test_put_uses_the_mirrored_thresholds():
    # engine against a PUT = net UP; zone against a PUT = spot ABOVE resistance
    holds_engine = T.assess("PUT", entry_spot=24000, spot=24010, net=3, protect=24010)
    assert holds_engine["signal"] == "WAIT"          # zone not broken yet
    both = T.assess("PUT", entry_spot=24000, spot=24045, net=3, protect=24010)
    assert both["signal"] == "EXIT"


def test_a_mere_wobble_at_threshold_does_not_exit():
    """Net sitting exactly at the noise line, zone untouched → still WAIT."""
    r = T.assess("CALL", entry_spot=24000, spot=23999, net=-1, protect=23950)
    assert r["signal"] == "WAIT"


def test_the_zone_offset_scales_with_atm_range():
    """A wider instrument (bigger atm_range) needs a proportionally bigger
    breach before the zone counts as broken. protect=100; a 50pt breach clears
    the narrow 30pt offset (atm_range=100) but not the wide 120pt one
    (atm_range=400)."""
    narrow = T.assess("CALL", entry_spot=100, spot=50, net=-3, protect=100, atm_range=100.0)
    wide = T.assess("CALL", entry_spot=100, spot=50, net=-3, protect=100, atm_range=400.0)
    assert narrow["zone_against"] is True
    assert wide["zone_against"] is False


def test_no_protect_level_reads_as_NOT_EVALUATED_not_as_intact():
    """No S/R was resolvable at entry (e.g. a mid-range FOMO trade).

    ⚠️ `None`, not `False`. `False` means "checked, and the level is holding";
    a level that was never captured was not checked at all, and collapsing the
    two is what let an unevaluated trade render as a healthy one. The verdict is
    still WAIT — the engine leg WAS evaluated, so something was measured — but
    the zone leg reports honestly that nobody looked.
    """
    r = T.assess("CALL", entry_spot=24000, spot=23900, net=-5, protect=None)
    assert r["zone_against"] is None
    assert r["engine_against"] is True
    assert r["signal"] == "WAIT", "one leg was measured, so this is a real WAIT"
    assert r["checked"] == 1


# ── message ─────────────────────────────────────────────────────────────

def test_message_says_wait_or_exit_plainly():
    wait = T.message("CALL", {"signal": "WAIT"}, entry_spot=24000, spot=24010)
    assert "WAIT" in wait and "EXIT" not in wait
    exitm = T.message("CALL", {"signal": "EXIT"}, entry_spot=24000, spot=23900)
    assert "EXIT FAST" in exitm


def test_message_shows_the_gain_in_the_traders_own_terms():
    put_up = T.message("PUT", {"signal": "WAIT"}, entry_spot=24000, spot=23950)
    assert "+50.0 pts" in put_up   # PUT profits on a fall


def test_message_tags_a_dhan_detected_trade():
    msg = T.message("CALL", {"signal": "WAIT"}, entry_spot=24000, spot=24010, source="dhan")
    assert "Dhan" in msg
    manual = T.message("CALL", {"signal": "WAIT"}, entry_spot=24000, spot=24010, source="manual")
    assert "Dhan" not in manual


# ── find_open_nifty_option: Dhan's own /v2/positions shape ─────────────

def _pos(**over):
    row = {"tradingSymbol": "NIFTY 24000 CALL", "positionType": "LONG",
          "netQty": 50, "drvOptionType": "CALL", "securityId": "12345"}
    row.update(over)
    return row


def test_finds_an_open_long_call():
    r = T.find_open_nifty_option([_pos()])
    assert r == {"side": "CALL", "security_id": "12345",
                "trading_symbol": "NIFTY 24000 CALL", "qty": 50.0}


def test_finds_pe_spelled_option_type():
    r = T.find_open_nifty_option([_pos(drvOptionType="PE")])
    assert r["side"] == "PUT"


def test_a_flat_or_short_or_closed_position_is_skipped():
    assert T.find_open_nifty_option([_pos(netQty=0)]) is None
    assert T.find_open_nifty_option([_pos(positionType="SHORT")]) is None
    assert T.find_open_nifty_option([_pos(positionType="CLOSED", netQty=0)]) is None


def test_a_different_underlying_is_skipped():
    assert T.find_open_nifty_option([_pos(tradingSymbol="BANKNIFTY 51000 CALL")]) is None


def test_junk_rows_and_no_positions_do_not_raise():
    assert T.find_open_nifty_option(None) is None
    assert T.find_open_nifty_option([]) is None
    assert T.find_open_nifty_option([None, "x", 7, _pos()]) == {
        "side": "CALL", "security_id": "12345",
        "trading_symbol": "NIFTY 24000 CALL", "qty": 50.0}


def test_first_matching_position_wins():
    r = T.find_open_nifty_option([_pos(drvOptionType="CALL"), _pos(drvOptionType="PUT")])
    assert r["side"] == "CALL"


# ── purity ───────────────────────────────────────────────────────────

def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "trade_watch.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas", "requests"}
    assert "session_state" not in src


# ══ UNKNOWN: "could not check" is not "checked and fine" ════════════════
#
# THE BUG this section exists to keep fixed. Both EXIT conditions failed
# CLOSED — `n is not None and n <= -NET_THRESHOLD` is False when the engine
# vote is missing, and the zone test is False when no level was captured — so a
# trade with NOTHING measurable produced `exit_now = False` and the banner said
# "Still yours to win. The market hasn't turned all the way against you yet."
# A green reassurance from zero evidence, indistinguishable on screen from a
# genuine all-clear.

def test_neither_input_available_is_UNKNOWN_not_WAIT():
    r = T.assess("PUT", entry_spot=24112.1, spot=24110.3, net=None, protect=None)
    assert r["signal"] == "UNKNOWN"
    assert r["engine_against"] is None and r["zone_against"] is None
    assert r["checked"] == 0


def test_one_input_available_is_a_real_WAIT():
    """WAIT must mean something was actually measured."""
    eng_only = T.assess("PUT", 24000, 24010, net=0.5, protect=None)
    zone_only = T.assess("PUT", 24000, 24010, net=None, protect=24500)
    for r in (eng_only, zone_only):
        assert r["signal"] == "WAIT"
        assert r["checked"] == 1


def test_UNKNOWN_is_distinct_from_NONE():
    """NONE = no trade to watch. UNKNOWN = a trade IS open and unjudged. A
    caller that treats them alike would either hide a live position or draw a
    banner for one that does not exist."""
    no_trade = T.assess(None, None, None, net=1.0, protect=24500)
    unjudged = T.assess("PUT", 24000, 24010, net=None, protect=None)
    assert no_trade["signal"] == "NONE"
    assert unjudged["signal"] == "UNKNOWN"


def test_a_full_reversal_still_exits_when_both_were_measured():
    r = T.assess("PUT", 24000, 24600, net=3.0, protect=24500)
    assert r["signal"] == "EXIT"
    assert r["engine_against"] is True and r["zone_against"] is True


def test_exit_needs_both_TRUE_not_merely_not_false():
    """⚠️ `engine_against and zone_against` with None in one slot is falsy, so
    the old expression happened to behave — but `None and True` is None, not
    False, and a truthiness test here would have been one refactor from calling
    an unmeasured leg a passing one. The check is explicit."""
    r = T.assess("PUT", 24000, 24600, net=None, protect=24500)
    assert r["zone_against"] is True and r["engine_against"] is None
    assert r["signal"] == "WAIT", "an unmeasured engine must not complete an EXIT"


def test_the_numbers_behind_the_verdict_travel_with_it():
    """The panel shows the reader what the decision was made on — it must not
    have to re-derive them and risk showing a different number."""
    r = T.assess("PUT", 24000, 24010, net=1.5, protect=24500, atm_range=100.0)
    assert r["net"] == 1.5
    assert r["protect"] == 24500
    assert r["breach_at"] == 24530.0        # resistance + 30 for a PUT


def test_the_breach_line_scales_with_atm_range():
    wide = T.assess("PUT", 24000, 24010, net=0.0, protect=24500, atm_range=400.0)
    assert wide["breach_at"] == 24620.0     # 400/100 * 30 = 120


def test_no_breach_line_without_a_level():
    r = T.assess("PUT", 24000, 24010, net=0.0, protect=None)
    assert r["breach_at"] is None


def test_the_unknown_message_never_says_still_yours_to_win():
    """⚠️ THE WORDING RULE. Nothing was checked, so nothing may be reassured."""
    r = T.assess("PUT", 24112.1, 24110.3, net=None, protect=None)
    m = T.message("PUT", r, 24112.1, 24110.3, source="dhan")
    assert "NOT EVALUATED" in m
    assert "still yours to win" not in m.lower()
    assert "nothing has been checked" in m.lower()
