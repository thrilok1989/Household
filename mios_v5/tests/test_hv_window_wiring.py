"""📊 The 10-minute spike-volume window: one answer, two surfaces.

`_hv_window_totals` publishes `_hv_window` once per cycle; the Live Confluence
card and the flip alert both READ it. Neither totals its own — two totals of
the same window is how a card and an alert come to disagree about which side
is heavier.

`vob_minimal` boots Streamlit on import, so these are source-level checks.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"
_PANEL = (pathlib.Path(__file__).resolve().parents[1]
          / "ui" / "live_confluence_panel.py")


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text()


@pytest.fixture(scope="module")
def tree(source: str) -> ast.Module:
    return ast.parse(source)


def _fn(tree: ast.Module, name: str) -> ast.FunctionDef:
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found")


# ── the producer ────────────────────────────────────────────────────────

def test_the_totals_are_published_once(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_hv_window_totals"))
    assert "'_hv_window'" in src
    assert "hv_window" in src


def test_the_producer_reads_published_pivots_and_recomputes_none(tree: ast.Module):
    """`_leg_profiles[side].hv_points` is the one owner — no second pivot
    detection, no frame re-read."""
    fn = _fn(tree, "_hv_window_totals")
    src = ast.unparse(fn)
    assert "_leg_profiles" in src and "hv_points" in src
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "high_volume_pivots" not in called
    assert "_hv_points" not in called


def test_the_producer_runs_before_the_flip_alert(source: str):
    """The alert reads what the producer published; ordering is the contract."""
    prod = source.rindex("_hv_window_totals()")
    alert = source.rindex("_notify_hv_window_flip()")
    assert prod < alert


# ── the alert ───────────────────────────────────────────────────────────

def test_the_flip_alert_goes_to_the_alternate_bot(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_notify_hv_window_flip"))
    assert "send_telegram_alert_bot" in src
    assert "send_telegram_message_sync" not in src


def test_the_flip_alert_is_latched_not_re_emitted(tree: ast.Module):
    """⚠️ The flood rule. A standing lead must not re-announce every cycle."""
    src = ast.unparse(_fn(tree, "_notify_hv_window_flip"))
    assert "latch" in src
    assert "'_hv_window_state'" in src


def test_the_flip_alert_reads_the_published_totals(tree: ast.Module):
    fn = _fn(tree, "_notify_hv_window_flip")
    src = ast.unparse(fn)
    assert "'_hv_window'" in src
    called = {c.func.attr for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "totals" not in called, "the alert totals its own window"


def test_the_flip_alert_has_an_opt_out(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_notify_hv_window_flip"))
    assert "_hv_window_alerts_on" in src


# ── the card ────────────────────────────────────────────────────────────

def test_the_card_is_handed_the_same_published_totals(tree: ast.Module):
    fn = _fn(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "'_hv_window'" in src
    assert "hv_window_line" in src
    called = {c.func.attr for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "totals" not in called, "the card totals its own window"


def test_the_card_row_is_shown_not_voted():
    """High volume alone is not directional — the row must not become a vote."""
    panel = _PANEL.read_text()
    fn = next(n for n in ast.walk(ast.parse(panel))
              if isinstance(n, ast.FunctionDef) and n.name == "_hv_window_row")
    # ⚠️ CODE only — the docstring says "never voted", which would match.
    body = [n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str))]
    src = "\n".join(ast.unparse(n) for n in body)
    for word in ("bias", "BULL", "BEAR", "vote"):
        assert word not in src, f"{word!r} in the spike-volume row's code"


def test_an_empty_window_draws_no_row():
    panel = _PANEL.read_text()
    fn = next(n for n in ast.walk(ast.parse(panel))
              if isinstance(n, ast.FunctionDef) and n.name == "_hv_window_row")
    src = ast.unparse(fn)
    assert "return ''" in src


# ── the pivot fields the window depends on ─────────────────────────────

def test_the_annotator_attaches_the_bar_volume_and_its_split(tree: ast.Module):
    """`bar_vol` / `bar_buy` / `bar_sell` — the pivot BAR's own figures, which
    is what makes a window total addable without double-counting."""
    src = ast.unparse(_fn(tree, "_annotate_hv_pivots"))
    for field in ("'bar_vol'", "'bar_buy'", "'bar_sell'"):
        assert field in src, f"{field} never set"
