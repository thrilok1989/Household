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


def test_no_protect_level_never_reads_as_broken():
    """No S/R was resolvable at entry (e.g. a mid-range FOMO trade) — the zone
    leg of the combination can never fire, so only the engine vote matters,
    and even a hard engine flip alone must still be WAIT (combination rule)."""
    r = T.assess("CALL", entry_spot=24000, spot=23900, net=-5, protect=None)
    assert r["zone_against"] is False
    assert r["signal"] == "WAIT"


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
