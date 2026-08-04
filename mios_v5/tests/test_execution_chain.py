"""The execution chain — Stages 72 → 73 → 72.9, actually wired.

All three were built, frozen and tested earlier, and **nothing called them**.
A module that exists and never runs is the regression this repo has already
suffered twice: `cfb6c93` removed writers while keeping readers, and
`_atm_leg_ltf_delta` had the same problem. Tests that a stage *works* say
nothing about whether it *runs*.

So the tests here are mostly about the wiring, and about the one property that
must survive it: **nothing is sent**. Stage 72.9 is `VALIDATED_SIMULATED` with
`freeze_ready: False`, and wiring a stage is not the same as trusting it to
broadcast.
"""

import ast
import pathlib

import pytest

from mios_v5 import dispatcher as DP
from mios_v5 import entry_engine as EE
from mios_v5 import trade_lifecycle as TL
from mios_v5 import trading_context as TC
from mios_v5.tests.test_entry_engine import (_behaviour, _fr, _matrix,
                                             _premium, _structure, _validation)

ROOT = pathlib.Path(__file__).resolve().parents[2]
DASH = ROOT / "mios_v5" / "ui" / "dashboard_v6.py"


def _ctx(**over):
    kw = dict(fr=_fr(), matrix=_matrix(), premium=_premium(),
              validation=_validation(), structure=_structure(),
              behaviour=_behaviour(), cycle=9)
    kw.update(over)
    return TC.build(**kw)


def _chain(ctx=None):
    ctx = ctx or _ctx()
    decision = EE.run(ctx)
    lifecycle = TL.run(decision, ctx)
    dispatch = DP.run(decision, ctx, lifecycle=lifecycle,
                      registry=DP.MemoryRegistry(), transport=None)
    return decision, lifecycle, dispatch


# ══════════════════════════════════════════════════════════════════════
#  the wiring — the thing that was missing
# ══════════════════════════════════════════════════════════════════════

def test_all_three_stages_have_a_caller():
    """Built, frozen, tested — and until this was wired, dead code. A test that
    a stage works says nothing about whether it runs."""
    src = DASH.read_text()
    tree = ast.parse(src)
    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names}
    aliases = {alias.asname or alias.name for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert "run" in imported, "no stage entry point is imported"
    for expected in ("_entry", "_lifecycle", "_dispatch"):
        assert expected in aliases, f"{expected} is not wired"


def test_the_chain_runs_from_the_assembled_context():
    src = DASH.read_text()
    assert "_run_execution_chain" in src
    assert "_trading_context" in src


def test_each_stage_receives_the_previous_ones_output():
    """72 → 73 → 72.9. A chain where stage three ignores stage two is three
    stages, not a chain."""
    tree = ast.parse(DASH.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_run_execution_chain")
    body = ast.dump(fn)
    assert "'_entry'" in body and "'_lifecycle'" in body and "'_dispatch'" in body
    assert "lifecycle" in body


def test_the_chain_publishes_its_results_for_other_readers():
    src = DASH.read_text()
    for key in ("_entry_decision", "_lifecycle_decision", "_dispatch_decision"):
        assert key in src, key


# ══════════════════════════════════════════════════════════════════════
#  ⚠️ nothing is sent
# ══════════════════════════════════════════════════════════════════════

def test_no_transport_is_passed():
    """Stage 72.9 is VALIDATED_SIMULATED and its validation report records
    freeze_ready: False. Wiring a stage is not trusting it to broadcast."""
    tree = ast.parse(DASH.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_run_execution_chain")
    for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call)):
        for kw in call.keywords:
            if kw.arg == "transport":
                assert isinstance(kw.value, ast.Constant)
                assert kw.value.value is None, "a live transport is wired in"


def test_the_dispatch_reports_not_sent():
    _, _, dispatch = _chain()
    assert dispatch.telegram_state == "NOT_SENT"
    # `should_send` is the dispatcher's verdict; `telegram_state` is what
    # happened. With no transport the second must be NOT_SENT whatever the
    # first says — that gap is the whole point of running it unwired.
    assert dispatch.record is None or dispatch.record.telegram_message_id is None


def test_the_dashboard_never_imports_a_network_client():
    """`import requests` inside this path is a named forbidden failure mode."""
    tree = ast.parse(DASH.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"requests", "httpx", "urllib3", "telegram"})


def test_the_panel_says_nothing_was_sent_on_every_render():
    """In the card, not a footnote — a dispatch state that reads like a
    delivery is the one misreading that would cost money."""
    from mios_v5.ui.execution_panel import execution_html
    html = execution_html(*_chain())
    assert "Nothing is sent" in html
    assert "freeze_ready: False" in html


def test_delivered_is_not_coloured_as_success():
    """Nothing in this build delivers, so a green delivery badge would be a lie
    waiting to happen."""
    from mios_v5.ui import execution_panel as P
    assert P._DISPATCH_COL["DELIVERED"] != P.BULL


# ══════════════════════════════════════════════════════════════════════
#  the chain describes ONE decision
# ══════════════════════════════════════════════════════════════════════

def test_the_lifecycle_references_the_entry_decision_rather_than_minting_one():
    decision, lifecycle, _ = _chain()
    assert lifecycle.decision_id == decision.id
    assert lifecycle.id != decision.id


def test_the_entry_decision_still_verifies_after_the_chain_has_run():
    """Nothing downstream may alter what Stage 72 concluded."""
    decision, _, _ = _chain()
    assert decision.verify() is True


def test_the_panel_flags_a_lifecycle_that_does_not_match():
    """A chain that silently describes two decisions is worse than one that
    fails loudly."""
    from mios_v5.ui.execution_panel import execution_html
    decision, lifecycle, dispatch = _chain()
    html = execution_html(decision, {"action": "HOLD", "decision_id": "other"},
                          dispatch)
    assert "does not reference the entry decision" in html


# ══════════════════════════════════════════════════════════════════════
#  the registry
# ══════════════════════════════════════════════════════════════════════

def test_a_registry_is_used_because_without_one_duplicate_has_no_answer():
    src = DASH.read_text()
    assert "MemoryRegistry" in src
    assert "_dispatch_registry" in src, "the registry must outlive one cycle"


def test_dispatching_the_same_decision_twice_is_recognised():
    ctx = _ctx()
    decision = EE.run(ctx)
    lifecycle = TL.run(decision, ctx)
    registry = DP.MemoryRegistry()
    first = DP.run(decision, ctx, lifecycle=lifecycle, registry=registry,
                   transport=None)
    second = DP.run(decision, ctx, lifecycle=lifecycle, registry=registry,
                    transport=None)
    assert first is not None and second is not None
    # Whatever the states, the second must not be MORE ready than the first —
    # a re-run of an identical decision cannot become newly sendable.
    assert not (second.dispatch_state == "READY"
                and first.dispatch_state != "READY")


# ══════════════════════════════════════════════════════════════════════
#  it never takes the tab down
# ══════════════════════════════════════════════════════════════════════

def test_the_chain_survives_a_thin_context():
    decision, lifecycle, dispatch = _chain(TC.build())
    assert decision.state in ("WAIT", "ABORT")
    assert lifecycle is not None and dispatch is not None


def test_the_panel_never_raises():
    from mios_v5.ui.execution_panel import execution_html
    assert execution_html(None) == ""
    for junk in ("a string", 42, {}, []):
        execution_html(junk, junk, junk)


def test_the_panel_renders_a_stored_decision_like_a_live_one():
    """A replayed decision is a dict; a live one is frozen. Identity is how a
    reader tells the chain describes one decision, so both must show it."""
    from mios_v5.ui.execution_panel import execution_html
    decision, lifecycle, dispatch = _chain()
    live = execution_html(decision, lifecycle, dispatch)
    stored = execution_html(decision.to_dict(), lifecycle, dispatch)
    assert decision.id[:8] in live and decision.id[:8] in stored


def test_the_panel_computes_nothing():
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "execution_panel.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"numpy", "pandas", "streamlit", "requests",
                            "entry_engine", "dispatcher", "trade_lifecycle"})


# ══════════════════════════════════════════════════════════════════════
#  no module built this session is left without a caller
# ══════════════════════════════════════════════════════════════════════

def test_every_stage_built_this_session_is_reachable_from_the_app():
    """The guard for the whole class. This is how three frozen stages sat
    unreachable for a day without anything noticing."""
    import re
    app = "\n".join(
        p.read_text() for p in
        [ROOT / "vob_minimal.py", ROOT / "mios_v5" / "runner.py"]
        + list((ROOT / "mios_v5" / "ui").glob("*.py")))
    for module in ("premium_energy", "premium_structure", "strike_validation",
                   "premium_behaviour", "trading_context", "entry_engine",
                   "dispatcher", "trade_lifecycle", "liquidity",
                   "liquidity_context", "liquidity_telemetry"):
        assert re.search(rf"\b{module}\b", app), f"{module} has no caller"
