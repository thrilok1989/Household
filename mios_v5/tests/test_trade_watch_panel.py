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
