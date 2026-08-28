"""📨 OI-wall level touches go to the ALTERNATE Telegram bot.

The owner asked for the two OI-wall touches — "CE OI wall (resistance)" and
"PE OI wall (support)" — on the second bot, away from the main stream. The
war zone and the (currently paused) ranked S/R touches stay on the main bot.

The subtlety is the dedupe. `level_touch.dedupe` drops a later hit whose price
rounds to an earlier one; a single pooled pass would therefore let a war-zone
hit on the MAIN bot swallow an OI-wall hit at the same price, and the OI wall
would never reach the alert bot at all — the one outcome this routing must not
produce. So each destination is deduped within itself.

`vob_minimal` boots Streamlit on import, so these are source-level checks —
same convention as `test_dhan_rate_limits.py`.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(_SRC.read_text())


def _fn(tree: ast.Module, name: str) -> ast.FunctionDef:
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found")


def _src(tree: ast.Module) -> str:
    return ast.unparse(_fn(tree, "_notify_level_touches"))


def test_both_senders_are_used(tree: ast.Module):
    src = _src(tree)
    assert "send_telegram_alert_bot" in src, "the alert bot is never used"
    assert "send_telegram_message_sync" in src, "the main bot was dropped"


def test_both_oi_walls_are_routed_to_the_alert_bot(tree: ast.Module):
    """Each OI-wall target must carry the 'alert' destination."""
    src = _src(tree)
    for wall in ("CE OI wall (resistance)", "PE OI wall (support)"):
        i = src.index(wall)
        # the destination travels in the same tuple, within a short span
        assert "'alert'" in src[i:i + 260], f"{wall} is not routed to the alert bot"


def test_the_war_zone_stays_on_the_main_bot(tree: ast.Module):
    src = _src(tree)
    # the KEY, not the prose — "war zone" also appears in the docstring
    i = src.index("'war_zone'")
    assert "'main'" in src[i:i + 320], "the war zone was moved off the main bot"


def test_the_ranked_sr_touches_stay_on_the_main_bot(tree: ast.Module):
    src = _src(tree)
    for label in ("'resistance'", "'support'"):
        i = src.rindex(label)
        assert "'main'" in src[i:i + 200], f"{label} was moved off the main bot"


def test_dedupe_runs_per_destination_not_once_across_both(tree: ast.Module):
    """⚠️ The trap: one pooled `dedupe` would let a main-bot hit at the same
    price swallow the OI-wall hit, so it would never reach the alert bot."""
    src = _src(tree)
    assert "hits = {'main': [], 'alert': []}" in src, \
        "hits are still pooled into one list"
    assert "dedupe(hits[_dest])" in src, "dedupe is not per-destination"


def test_every_target_declares_a_destination(tree: ast.Module):
    """The unpack is 7-wide, so a target added without a destination is a
    TypeError at import-review time rather than a silently mis-routed alert."""
    src = _src(tree)
    assert "for key, label, icon, price, extra, bias, dest in targets" in src


def test_the_alert_bot_is_not_called_with_force(tree: ast.Module):
    """`send_telegram_alert_bot(message)` takes no `force` kwarg — passing one
    would raise inside the per-send try and silently drop every OI-wall alert."""
    src = _src(tree)
    assert "send_telegram_alert_bot(m, force" not in src
    assert "send_telegram_alert_bot(_msg, force" not in src
