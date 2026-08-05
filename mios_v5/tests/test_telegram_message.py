"""The entry and exit messages a trader actually receives.

One rule dominates: **an `UNKNOWN` may never render as a number.** Stage 72
publishes `target2` and `target3` as `UNKNOWN` by name, and the earlier
Stage 71.90 audit already caught a sample alert printing three targets when
Stage 35 publishes one. A template renders whatever it is given; this is the
test that it is never given a fabrication.
"""

import ast
import pathlib

import pytest

from mios_v5.ui import telegram_message as M

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "mios_v5" / "ui" / "telegram_message.py"


def _entry(**over):
    p = {"id": "abcdef12-3456", "version": "72.1", "state": "ENTER",
         "side": "CALL", "strike": 24500.0, "quality": "A+",
         "confidence": 82, "timing": "Optimal", "entry": 182.4,
         "stop": 178.5, "risk": "Low", "reward": "Good",
         "behaviour": "Support Building", "horizon": "Scalp",
         "targets": {"target1": 185.0, "target2": "UNKNOWN",
                     "target3": "UNKNOWN"},
         "reasons": ("Strike Validation VALID", "Energy 78"),
         "warnings": ("RBI event today",)}
    p.update(over)
    return p


def _lc(**over):
    d = {"action": "EXIT", "state": "EXIT", "health": "Poor",
         "exit_reason": "Stop Hit", "trail": "No Trail", "scale": "Neither",
         "position_known": "UNKNOWN", "decision_id": "abcdef12-3456"}
    d.update(over)
    return d


# ══════════════════════════════════════════════════════════════════════
#  ⛔ it cannot invent a level
# ══════════════════════════════════════════════════════════════════════

def test_only_the_targets_that_exist_are_printed():
    """Stage 35 publishes ONE target. A fixed three-line block would render
    three, in the one artefact a trader acts on."""
    out = M.entry_message(_entry())
    assert "T1" in out
    assert "T2" not in out and "T3" not in out


def test_no_unknown_ever_reaches_the_message():
    for payload in (_entry(), _entry(quality="UNKNOWN", entry="UNKNOWN",
                                     behaviour="UNKNOWN", reward="UNKNOWN"),
                    _entry(targets={"target1": "UNKNOWN"})):
        assert "UNKNOWN" not in M.entry_message(payload)
    assert "UNKNOWN" not in M.exit_message(_lc(), _entry())


def test_an_absent_field_drops_its_row_rather_than_printing_a_dash():
    """A dash still occupies a row and implies the field was expected."""
    out = M.entry_message(_entry(reward="UNKNOWN"))
    assert "Reward" not in out
    assert "Entry" in out


def test_a_missing_stop_does_not_become_zero():
    out = M.entry_message(_entry(stop=None))
    assert "Stop" not in out
    assert "₹0" not in out


# ══════════════════════════════════════════════════════════════════════
#  what gets sent, and what does not
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("state", ["ENTER", "ENTRY_READY", "ABORT"])
def test_the_sendable_entry_states_render(state):
    assert M.entry_message(_entry(state=state))


@pytest.mark.parametrize("state", ["WAIT", "HOLD", "COMPLETE", "UNKNOWN", ""])
def test_everything_else_renders_nothing(state):
    """`WAIT` is the engine working correctly. Saying so every cycle trains a
    reader to mute the channel — the one thing a signal channel cannot
    survive."""
    assert M.entry_message(_entry(state=state)) == ""


@pytest.mark.parametrize("action", ["EXIT", "SCALE_OUT", "ADD", "TRAIL",
                                    "ABORT"])
def test_the_lifecycle_actions_render(action):
    assert M.exit_message(_lc(action=action), _entry())


def test_a_hold_is_not_a_message():
    assert M.exit_message(_lc(action="HOLD"), _entry()) == ""


# ══════════════════════════════════════════════════════════════════════
#  entry and exit describe ONE decision
# ══════════════════════════════════════════════════════════════════════

def test_the_exit_carries_the_entry_id():
    """So a trader can join it to the signal they were sent earlier — the whole
    reason Stage 73 references rather than mints."""
    out = M.exit_message(_lc(), _entry())
    assert "abcdef12" in out


def test_the_entry_carries_its_own_identity():
    out = M.entry_message(_entry())
    assert "abcdef12" in out and "72.1" in out


def test_the_exit_falls_back_to_the_lifecycle_reference():
    out = M.exit_message(_lc(), None)
    assert "abcdef12" in out


# ══════════════════════════════════════════════════════════════════════
#  presentation only
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_nothing_that_could_send_or_compute():
    tree = ast.parse(SRC.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"requests", "httpx", "streamlit", "numpy",
                            "pandas", "entry_engine", "dispatcher"})


def test_it_never_raises_on_junk():
    for junk in (None, {}, "a string", 42, [], {"state": None}):
        M.entry_message(junk if isinstance(junk, dict) else {})
        M.exit_message(junk if isinstance(junk, dict) else {})


def test_a_position_is_not_implied():
    """`position_known` is UNKNOWN by name in Stage 73 — no producer reports a
    fill. It must never appear as though a position were confirmed."""
    assert "Position" not in M.exit_message(_lc(), _entry())


# ══════════════════════════════════════════════════════════════════════
#  the router lets these through
# ══════════════════════════════════════════════════════════════════════

def test_the_message_carries_a_telegram_entry_tier_marker():
    """`send_telegram_message_sync` routes anything without an entry-tier
    marker to Discord only. A signal that silently went to the wrong channel
    would look exactly like a signal that was never generated."""
    import re
    src = (ROOT / "vob_minimal.py").read_text()
    block = src.split("_TELEGRAM_ENTRY_MARKERS = (")[1].split(")")[0]
    # Quoted literals only — the block carries inline comments, and stripping
    # punctuation off the whole line dragged the comment along with it.
    markers = [m for m in re.findall(r"'([^']+)'", block) if "MIOS" in m]
    assert markers, "no MIOS markers registered with the router"
    assert any(m in M.entry_message(_entry()) for m in markers)
    assert any(m in M.exit_message(_lc(), _entry()) for m in markers)


def test_the_transport_reports_failure_rather_than_assuming_success():
    """The dispatcher reads the return value; a transport that returned
    nothing on a failed send would record a delivery that never happened."""
    src = (ROOT / "vob_minimal.py").read_text()
    fn = src[src.index("def mios_v6_transport"):src.index(
        "def send_telegram_message_sync")]
    assert 'return "failed"' in fn and 'return "ok"' in fn
    assert "except Exception" in fn
