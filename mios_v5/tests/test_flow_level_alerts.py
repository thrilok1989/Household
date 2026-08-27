"""📨 Flow-at-level alerts: PUT heavier at resistance · CALL heavier at support,
to the alternate bot. Pure-logic tests — the decision, the band, and the
rising-edge latch that keeps a standing condition from flooding.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5 import flow_level_alerts as F

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── activity = buy + sell, honestly ───────────────────────────────────

def test_activity_is_buy_plus_sell():
    assert F.activity(100, 40) == 140.0
    # one side present, the other missing → still a number
    assert F.activity(100, None) == 100.0
    assert F.activity(None, 40) == 40.0


def test_a_side_with_no_flow_is_none_not_zero():
    """⚠️ Zero would make the OTHER side spuriously 'heavier'. Missing is missing."""
    assert F.activity(None, None) is None
    assert F.activity("x", None) is None


# ── the band is a fraction of spot, not points ────────────────────────

def test_at_level_uses_a_percentage_band():
    """⚠️ 0.25% of spot, so it means the same on NIFTY 24,000 and on 77,700."""
    assert F.at_level(24000, 24050) is True          # 50 pts = 0.21%
    assert F.at_level(24000, 24100) is False         # 100 pts = 0.42%
    assert F.at_level(77700, 77850) is True          # 150 pts = 0.19%
    assert F.at_level(77700, 78100) is False         # 400 pts = 0.51%


def test_at_level_is_false_on_junk():
    for spot, lvl in ((None, 100), (100, None), (0, 100), ("x", 1)):
        assert F.at_level(spot, lvl) is False


# ── the decision ──────────────────────────────────────────────────────

def test_put_heavier_at_resistance_fires_that_event_only():
    ev = F.assess(call_flow=100, put_flow=180, spot=24000,
                  support=23500, resistance=24040)
    assert ev["put_at_resistance"]["active"] is True
    assert ev["call_at_support"]["active"] is False


def test_call_heavier_at_support_fires_that_event_only():
    ev = F.assess(call_flow=200, put_flow=90, spot=24000,
                  support=24030, resistance=24600)
    assert ev["call_at_support"]["active"] is True
    assert ev["put_at_resistance"]["active"] is False


def test_the_wrong_side_heavy_at_a_level_does_not_fire():
    """CALL heavier but spot at RESISTANCE (not support) → neither event. The side
    and the level have to match."""
    ev = F.assess(call_flow=200, put_flow=90, spot=24000,
                  support=23500, resistance=24030)
    assert not any(v["active"] for v in ev.values())


def test_on_the_level_but_flow_not_heavier_does_not_fire():
    ev = F.assess(call_flow=150, put_flow=150, spot=24000,     # equal → no winner
                  support=23500, resistance=24030)
    assert ev["put_at_resistance"]["active"] is False
    # strictly heavier: a tie is not an event
    assert ev["put_at_resistance"]["heavier_ok"] is False


def test_heavier_but_not_on_the_level_does_not_fire():
    ev = F.assess(call_flow=100, put_flow=300, spot=24000,
                  support=23500, resistance=24500)          # spot far from res
    assert ev["put_at_resistance"]["active"] is False
    assert ev["put_at_resistance"]["heavier_ok"] is True
    assert ev["put_at_resistance"]["on_level"] is False


def test_a_missing_level_is_not_a_touch():
    ev = F.assess(call_flow=100, put_flow=300, spot=24000,
                  support=None, resistance=None)
    assert not any(v["active"] for v in ev.values())


# ── the rising-edge latch: this is what stops the flood ───────────────

def test_the_latch_fires_once_then_holds_until_the_condition_clears():
    """⚠️ THE anti-flood property. A standing condition must send ONCE, not every
    cycle — the exact failure the pivot alerts had."""
    st = None
    fired = []
    # condition true for five straight cycles
    for i in range(5):
        f, st = F.latch(True, st, now=1000 + i, cooldown_s=0)
        fired.append(f)
    assert fired == [True, False, False, False, False]


def test_the_latch_rearms_only_after_the_condition_goes_false():
    st = None
    f1, st = F.latch(True, st, now=1000, cooldown_s=0)
    assert f1 is True
    f2, st = F.latch(False, st, now=1001, cooldown_s=0)   # cleared → re-arm
    assert f2 is False
    f3, st = F.latch(True, st, now=1002, cooldown_s=0)    # fresh crossing
    assert f3 is True


def test_the_cooldown_suppresses_a_re_fire_even_after_rearm():
    """A level the price grinds on can flip true/false every cycle; the cooldown
    keeps that from chattering out a message each crossing."""
    st = None
    f, st = F.latch(True, st, now=1000, cooldown_s=300)
    assert f is True
    f, st = F.latch(False, st, now=1010, cooldown_s=300)
    f, st = F.latch(True, st, now=1020, cooldown_s=300)    # within cooldown
    assert f is False
    f, st = F.latch(False, st, now=1330, cooldown_s=300)
    f, st = F.latch(True, st, now=1340, cooldown_s=300)    # cooldown elapsed
    assert f is True


# ── the message ───────────────────────────────────────────────────────

def test_the_message_names_the_side_the_level_and_carries_a_ball():
    ev = F.assess(call_flow=100, put_flow=200, spot=24000,
                  support=23500, resistance=24030)
    msg = F.message("put_at_resistance", ev["put_at_resistance"],
                    call_label="ATM CE 24000", put_label="ATM PE 24000")
    assert "resistance" in msg and "ATM PE 24000" in msg
    assert "🔴" in msg and "🧱" in msg
    assert "2.00×" in msg          # 200 vs 100

    ev2 = F.assess(call_flow=250, put_flow=100, spot=24000,
                   support=24020, resistance=24600)
    msg2 = F.message("call_at_support", ev2["call_at_support"],
                     call_label="ATM CE 24000", put_label="ATM PE 24000")
    assert "support" in msg2 and "ATM CE 24000" in msg2
    assert "🟢" in msg2 and "🛡" in msg2


# ── purity and wiring ─────────────────────────────────────────────────

def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "flow_level_alerts.py").read_text()
    names = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas", "requests"}


def test_junk_never_raises():
    for a in (None, "x", [], {}):
        F.assess(a, a, a, a, a)
        F.activity(a, a)
        F.at_level(a, a)
        F.latch(bool(a), a if isinstance(a, dict) else None, now=0.0)
        F.message("put_at_resistance", a if isinstance(a, dict) else {})


def test_it_goes_to_the_alternate_bot_reads_the_graph_and_latches():
    """⚠️ The three things that make this the RIGHT alert: the alternate bot (not
    the main stream), the graph's own numbers (`_atm_flow_last`, not a second
    estimate), and the per-event latch (not a per-cycle resend)."""
    src = (_ROOT / "vob_minimal.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_notify_flow_at_level")
    calls = {getattr(c.func, "attr", "") or getattr(c.func, "id", "")
             for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "send_telegram_alert_bot" in calls, "must use the alternate bot"
    assert "send_telegram_message_sync" not in calls, "not the main stream"
    consts = {n.value for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_atm_flow_last" in consts and "_flow_level_state" in consts
    assert "latch" in calls and "assess" in calls


def test_the_graph_stashes_the_flow_and_the_dispatch_calls_the_alert():
    src = (_ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    graph = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "render_atm_cvd_graphs")
    gconsts = {n.value for n in ast.walk(graph)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_atm_flow_last" in gconsts, "the graph must publish what the alert reads"
    # the dispatch actually calls it
    called = {c.func.id for c in ast.walk(tree)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_notify_flow_at_level" in called
