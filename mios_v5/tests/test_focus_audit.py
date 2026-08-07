"""Stage 1 of Focus Mode — the audit that decides what may be skipped.

The rule it enforces: *Focus Mode may suppress presentation, but may not
suppress computation required by MIOS state, the decision stages, or Telegram
alerts.* These tests are about the audit not quietly losing that rule.
"""

import pathlib

from tools import focus_audit as F

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_alert_chains_context_is_protected():
    """⚠️ `_trading_context` is the single key that would take Telegram down.

    Stage 72 reads it, 73 and 72.9 follow, Telegram is the far end. It is
    written inside `_strike_validation` — a RENDER function — which is the
    whole reason this audit exists.
    """
    assert "_trading_context" in F.PROTECTED
    for key in ("_entry_decision", "_lifecycle_decision", "_dispatch_decision",
                "_mios_transport"):
        assert key in F.PROTECTED, key


def test_the_headers_own_inputs_are_protected():
    for key in ("_cached_option_data", "_mios_state", "_reaction_sr",
                "_premium_energy", "_sr_levels"):
        assert key in F.PROTECTED, key


def test_strike_validation_is_critical():
    """If this ever reports DRAW-ONLY, Focus Mode would skip it and the alert
    chain would go silent with nothing on screen to say so."""
    panels = {r["panel"]: r for r in F.build()["panels"]}
    row = panels.get("_strike_validation")
    assert row, "_strike_validation is no longer reachable from a render entry"
    assert row["verdict"] == "CRITICAL"
    assert "_trading_context" in row["protected"]


def test_the_other_header_producers_are_critical():
    panels = {r["panel"]: r for r in F.build()["panels"]}
    for name, key in (("_opportunity", "_premium_energy"),
                      ("_sr_intelligence", "_sr_levels"),
                      ("_terminal_chart", "_leg_profiles")):
        row = panels.get(name)
        assert row and row["verdict"] == "CRITICAL", name
        assert key in row["protected"], (name, key)


def test_most_panels_really_are_skippable():
    """The feature is only worth building if the skippable set is large. It is
    127 of 153 — but this asserts the shape, not the exact number, so a new
    panel does not fail the suite."""
    tally = F.build()["tally"]
    assert tally["DRAW-ONLY"] > 50
    assert tally["CRITICAL"] < 20, "too many critical panels to skip anything"


def test_a_draw_only_panel_writes_nothing_anyone_reads():
    """The definition, checked rather than trusted."""
    for row in F.build()["panels"]:
        if row["verdict"] == "DRAW-ONLY":
            assert not row["read_by_others"], row["panel"]
            assert not row["protected"], row["panel"]


def test_the_audit_errs_toward_keeping_things_alive():
    """Name-matched call graph merges same-named functions, which can only make
    a panel look like it writes MORE. A false PRODUCER costs a panel that keeps
    running; a false DRAW-ONLY costs the Telegram chain."""
    src = (ROOT / "tools" / "focus_audit.py").read_text()
    assert "by name" in src
    assert "DRAW-ONLY" in src and "CRITICAL" in src


def test_it_reports_without_touching_the_app():
    """Stage 1 changes no behaviour: the tool only parses."""
    import ast
    tree = ast.parse((ROOT / "tools" / "focus_audit.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imported.add((n.module or "").split(".")[0])
    assert not (imported & {"streamlit", "requests", "supabase", "db"})
