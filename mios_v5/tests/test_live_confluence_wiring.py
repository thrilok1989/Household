"""🔭 The Live Confluence card's wiring in vob_minimal.py — an assembler
that must read every fact from a store some other function already filled,
never recompute one itself, and must be drawn ABOVE the Trade Card, not
instead of it or nowhere at all.

`vob_minimal` boots Streamlit on import, so these are source-level checks —
same convention as `test_dhan_rate_limits.py` / `test_trade_watch_wiring.py`.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text()


@pytest.fixture(scope="module")
def tree(source: str) -> ast.Module:
    return ast.parse(source)


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found")


def test_it_is_wired_above_the_trade_card(source: str):
    call_idx = source.index("_render_live_confluence(underlying)")
    card_idx = source.index("render_clean_card(underlying, option_data)")
    assert call_idx < card_idx, "Live Confluence must be drawn ABOVE the Trade Card"


def test_it_is_inside_the_same_ready_gate_as_the_trade_card(source: str):
    """Both must share `_mp_ready and underlying` — a card with a different
    precondition than its neighbour can appear/disappear independently in a
    way that looks like a bug."""
    seg = source[source.index("with _card_container:"):
                source.index("render_clean_card(underlying, option_data)")]
    assert "_render_live_confluence(underlying)" in seg


def test_it_reads_the_verdict_it_does_not_compute_one(tree: ast.Module):
    fn = _func(tree, "_render_live_confluence")
    called = {c.func.attr for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "assess" in called


def test_it_reads_the_same_vob_store_the_zone_table_reads(tree: ast.Module):
    """One owner, `analyze_vob_volume` — this must not call it again."""
    fn = _func(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "_atm_leg_vob_volume" in src
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "analyze_vob_volume" not in called


def test_vob_containment_is_a_real_range_check_not_nearest(tree: ast.Module):
    """"At" a VOB zone means the LTP is INSIDE lower..upper — the nearest-zone
    shortcut `compute_ce_pe_alignment` uses for a different purpose would
    call a leg "at" a zone it is nowhere near."""
    fn = _func(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "lower" in src and "upper" in src


def test_participation_uses_the_same_spike_detector_flow_alerts_uses(tree: ast.Module):
    fn = _func(tree, "_render_live_confluence")
    called = {c.func.attr for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "activity_spike" in called


def test_hvp_uses_the_same_band_the_touch_alert_uses(tree: ast.Module):
    fn = _func(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "LEG_HVP_BAND" in src


def test_it_does_not_fetch_global_or_sector_data_itself(tree: ast.Module):
    """Global bias and sector rotation are read from already-cached results —
    this must call the cheap already-cached accessor, never a fresh
    yfinance-backed fetch of its own."""
    fn = _func(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "_sector_rotation" in src   # reads the cache, not compute_sector_rotation
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "compute_sector_rotation" not in called


def test_sector_rotation_is_read_as_a_dict_with_an_all_key(tree: ast.Module):
    """⚠️ Regression: `_sector_rotation` is `{leading, lagging, all,
    rotation_bias}`, not a bare list. Iterating it directly (`or []`) raised
    on every cycle, swallowed by the except below, so the sector chip always
    fell back to "unavailable" — a white ball, never a real read."""
    fn = _func(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "_sector_rotation') or {}).get('all')" in src


def test_no_market_picture_returns_quietly(tree: ast.Module):
    fn = _func(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "if not mp or not spot_price" in src


def test_pinned_is_read_from_entry_gate_not_reinvented(tree: ast.Module):
    fn = _func(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "'PINNED'" in src


def test_price_action_compares_call_and_put_totals_not_nifty_cvd(tree: ast.Module):
    """The corrected framing: CALL's own cumulative buy+sell vs PUT's, from
    the SAME `_atm_flow_hist` the participation-spike check reads — not
    NIFTY's own tape CVD (`_volume_delta_data`)."""
    fn = _func(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "call_total" in src and "put_total" in src
    assert "_volume_delta_data" not in src


def test_war_zone_is_stage_42s_expected_winner(tree: ast.Module):
    """Reads the SAME `final_read.expected_winner` the war-zone panel already
    draws — must not resolve a winner from raw OI/flow itself."""
    fn = _func(tree, "_render_live_confluence")
    src = ast.unparse(fn)
    assert "expected_winner" in src
    assert "war_zone_winner" in src
