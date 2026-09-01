"""🎯 The trade-watch banner: formats a WAIT/EXIT decision already made
elsewhere — it must never compute one itself."""

from __future__ import annotations

import ast
import pathlib

from mios_v5.ui import trade_watch_panel as P

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_no_signal_draws_nothing():
    assert P.banner_html("CALL", 24000, 24010, {"signal": "NONE"}) == ""
    assert P.banner_html("CALL", 24000, 24010, {}) == ""
    assert P.banner_html(None, 24000, 24010, {"signal": "WAIT"}) == ""


def test_wait_reads_calm_and_exit_reads_urgent():
    wait = P.banner_html("CALL", 24000, 24010, {"signal": "WAIT"})
    assert "WAIT" in wait and "EXIT" not in wait
    exitb = P.banner_html("CALL", 24000, 23900, {"signal": "EXIT"})
    assert "EXIT FAST" in exitb


def test_the_gain_is_shown_in_the_traders_own_terms():
    put = P.banner_html("PUT", 24000, 23950, {"signal": "WAIT"})
    assert "+50.0 pts" in put
    call = P.banner_html("CALL", 24000, 23950, {"signal": "WAIT"})
    assert "-50.0 pts" in call


def test_missing_prices_show_a_dash_not_zero():
    html = P.banner_html("CALL", None, None, {"signal": "WAIT"})
    assert "₹" not in html
    assert html.count("—") >= 2


def test_source_is_tagged():
    dhan = P.banner_html("CALL", 24000, 24010, {"signal": "WAIT"}, source="dhan")
    assert "Dhan" in dhan
    manual = P.banner_html("CALL", 24000, 24010, {"signal": "WAIT"}, source="manual")
    assert "manual" in manual


def test_the_html_escapes_a_hostile_side_via_esc():
    # side is constrained to CALL/PUT before anything is escaped, but the tag
    # text still goes through _esc — this just pins that no raw markup can ride
    # along with a future free-text field added to the banner.
    html = P.banner_html("CALL", 24000, 24010, {"signal": "WAIT"})
    assert "<script>" not in html


def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "ui" / "trade_watch_panel.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas", "trade_watch"}
    assert "session_state" not in src


def test_nothing_is_computed_here():
    """The signal (WAIT/EXIT) must arrive pre-decided; this module must not
    touch net votes, protect levels, or thresholds."""
    src = (_ROOT / "mios_v5" / "ui" / "trade_watch_panel.py").read_text()
    tree = ast.parse(src)
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    assert not {"assess", "protect_level", "find_open_nifty_option"} & called


# ══ the two conditions, visible ═════════════════════════════════════════
#
# The verdict used to arrive with no working shown: SIDE / ENTRY / NOW / GAIN
# and a green headline, whether both EXIT conditions had been measured or
# neither had. "Checked and fine" looked exactly like "checked nothing".

def _info(**over):
    d = {"signal": "WAIT", "engine_against": False, "zone_against": False,
         "net": -1.2, "protect": 24180.0, "breach_at": 24150.0, "checked": 2}
    d.update(over)
    return d


def test_both_conditions_are_shown_with_their_numbers():
    h = P.banner_html("PUT", 24112.1, 24110.3, _info(), source="dhan")
    assert "engine" in h and "-1.2" in h
    assert "level" in h and "24,180" in h


def test_a_condition_on_your_side_reads_with_you():
    h = P.banner_html("PUT", 24000, 24010, _info(), source="dhan")
    assert h.count("✓ with you") == 2
    # ⚠️ NOT `"against you" not in h` — the WAIT sub-headline itself ends
    # "…hasn't turned all the way against you yet". The chips are what is
    # under test, so the assertion counts their marks.
    assert "✗" not in h


def test_a_condition_that_turned_reads_against_you():
    h = P.banner_html("PUT", 24000, 24600,
                      _info(signal="EXIT", engine_against=True,
                            zone_against=True))
    assert h.count("✗ against you") == 2
    assert "✓" not in h


def test_an_unevaluated_condition_says_so_rather_than_ticking():
    """⚠️ THE FIX. A missing input must never render as a passing check."""
    h = P.banner_html("PUT", 24000, 24010,
                      _info(zone_against=None, protect=None, breach_at=None,
                            checked=1))
    assert "— not evaluated" in h
    assert h.count("✓ with you") == 1, "the unmeasured leg was ticked"


def test_the_conditions_show_on_every_live_signal():
    for sig in ("WAIT", "EXIT", "UNKNOWN"):
        h = P.banner_html("PUT", 24000, 24010, _info(signal=sig))
        assert "engine" in h and "level" in h, sig


# ══ UNKNOWN gets its own banner, and it is not green ════════════════════

def _unknown():
    return {"signal": "UNKNOWN", "engine_against": None, "zone_against": None,
            "net": None, "protect": None, "breach_at": None, "checked": 0}


def test_unknown_never_says_still_yours_to_win():
    h = P.banner_html("PUT", 24112.1, 24110.3, _unknown(), source="dhan")
    assert "Still yours to win" not in h
    assert "NOT EVALUATED" in h
    assert "NOT an all-clear" in h


def test_unknown_is_not_toned_green():
    """⚠️ Colour is read before words. An unjudged trade sharing the WAIT green
    would be the same lie in a different medium."""
    from mios_v5.ui.theme import BULL
    h = P.banner_html("PUT", 24000, 24010, _unknown())
    wait = P.banner_html("PUT", 24000, 24010, _info())
    assert P.WARN in h
    assert BULL in wait and h.count(BULL) < wait.count(BULL)


def test_unknown_still_shows_the_position():
    """It is a live trade — hiding it would be worse than judging it."""
    h = P.banner_html("PUT", 24112.1, 24110.3, _unknown(), source="dhan")
    assert "PUT" in h and "24,112.1" in h and "24,110.3" in h


def test_no_trade_still_draws_nothing():
    assert P.banner_html("PUT", 24000, 24010, {"signal": "NONE"}) == ""
    assert P.banner_html("PUT", 24000, 24010, {}) == ""


# ══ the Dhan anchor is not an entry price ═══════════════════════════════
#
# `_track_my_trade` sets `entry_spot` from the LIVE NIFTY INDEX at the moment
# the app first saw the position — the positions endpoint is polled, and
# nothing reads the fill. Labelling that "ENTRY / GAIN +1.8 pts" reads as
# profit on the trade. It is not: it is index travel since detection.

def test_a_dhan_trade_does_not_call_it_entry_or_gain():
    h = P.banner_html("PUT", 24112.1, 24110.3, _info(), source="dhan")
    assert "SPOT WHEN SEEN" in h
    assert ">ENTRY<" not in h and ">GAIN<" not in h


def test_a_manual_trade_may_call_it_entry():
    """The button DOES capture the spot at the click, so the word is fair."""
    h = P.banner_html("PUT", 24112.1, 24110.3, _info(), source="manual")
    assert "ENTRY" in h
    assert ">GAIN<" not in h, "still index points, not P&L"


def test_the_number_itself_is_unchanged():
    """Only the label was wrong — the arithmetic was always right."""
    h = P.banner_html("PUT", 24112.1, 24110.3, _info(), source="dhan")
    assert "+1.8 pts" in h
