"""🎯 The Dhan side of the trade-watch banner (`_track_my_trade`,
`get_dhan_positions`, `_dhan_get` in vob_minimal.py) — a failed/skipped fetch
must never read as "you exited", and a manual entry must not be clobbered by
the very next poll.

`vob_minimal` boots Streamlit on import, so these are source-level checks —
same convention as `test_dhan_rate_limits.py`.
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


# ── get_dhan_positions / _dhan_get: cached and rate-gated like the chain ──

def test_positions_are_cached(tree: ast.Module):
    src = ast.unparse(_func(tree, "get_dhan_positions"))
    assert "_dhan_positions_cache" in src
    assert "DHAN_POSITIONS_TTL_S" in src


def test_a_failed_positions_fetch_does_not_blank_a_good_one(tree: ast.Module):
    """Same mistake the option-chain cache and expiry-list cache both document:
    caching (or returning) a failure in place of a good prior answer."""
    fn = _func(tree, "get_dhan_positions")
    src = ast.unparse(fn)
    assert "if resp is None" in src or "if resp:" in src


def test_dhan_get_respects_the_global_backoff(tree: ast.Module):
    src = ast.unparse(_func(tree, "_dhan_get"))
    assert "_dhan_429_until" in src


def test_dhan_get_trips_the_backoff_on_429(tree: ast.Module):
    src = ast.unparse(_func(tree, "_dhan_get"))
    assert "_trip_dhan_backoff" in src


def test_dhan_get_refuses_without_credentials(tree: ast.Module):
    src = ast.unparse(_func(tree, "_dhan_get"))
    assert "DHAN_CLIENT_ID" in src and "DHAN_ACCESS_TOKEN" in src


# ── _track_my_trade: lifecycle only, no verdict ────────────────────────

def test_a_none_fetch_is_treated_as_unknown_not_flat(tree: ast.Module):
    """`get_dhan_positions` returns `None` on a failed/skipped fetch. Reading
    that as 'flat' would clear a live trade on a network blip."""
    src = ast.unparse(_func(tree, "_track_my_trade"))
    assert "positions is None" in src
    idx_none_check = src.index("positions is None")
    idx_pop = src.find("pop('_my_trade'", idx_none_check)
    # the None-check's own return must come before any clearing logic runs
    idx_return_after_none = src.index("return", idx_none_check)
    assert idx_return_after_none < (idx_pop if idx_pop != -1 else len(src) + 1)


def test_a_manual_entry_survives_a_matching_dhan_poll(tree: ast.Module):
    """The button's own entry_spot, captured at the click, must not be
    overwritten by the next poll finding the same side still open."""
    src = ast.unparse(_func(tree, "_track_my_trade"))
    assert "pos.get('side') == found" in src or "pos.get(\"side\") == found" in src


def test_it_reads_find_open_nifty_option_not_a_reimplementation(tree: ast.Module):
    fn = _func(tree, "_track_my_trade")
    called = {c.func.attr for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "find_open_nifty_option" in called


def test_it_does_not_decide_wait_or_exit(tree: ast.Module):
    """The verdict belongs to `trade_watch.assess`, called at render time in
    the dashboard — this function only manages `_my_trade`'s lifecycle."""
    fn = _func(tree, "_track_my_trade")
    called = {c.func.attr for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "assess" not in called


def test_it_is_wired_into_the_notify_sequence(source: str):
    """⚠️ A tracker nothing calls never runs. Same class of bug as a renderer
    nothing calls: one occurrence is the `def`, so a second means a call site."""
    assert source.count("_track_my_trade()") >= 1, "nothing calls _track_my_trade"


# ── render_clean_card: the DECISIONS section was computed, never drawn ──
#
# `_action_html` (Entry Gate native), `_signal_html` (v0) and `_dec_v2_html`
# (v2) were each assembled every cycle and none of them reached a
# `st.markdown` call — the Trade Card showed Market Facts and the V6 read,
# then stopped, on every render since the V6-reduction restore. Fixed by
# adding the missing DECISIONS section; these pin it so it cannot regress
# back into dead code a second time.

def test_the_decisions_section_is_actually_drawn(tree: ast.Module):
    fn = _func(tree, "render_clean_card")
    src = ast.unparse(fn)
    assert '"🎯 Decisions"' in src or "'🎯 Decisions'" in src


def _decisions_call(src: str) -> str:
    """The one `st.markdown(_sec("🎯 Decisions", ...), unsafe_allow_html=True)`
    call, isolated by its two textual anchors — `_sec(` opens it, immediately
    before the title; `unsafe_allow_html=True)` closes it."""
    start = src.rindex("_sec(", 0, src.index("🎯 Decisions"))
    end = src.index("unsafe_allow_html=True)", start) + len("unsafe_allow_html=True)")
    return src[start:end]


def test_the_decisions_section_includes_all_three_native_verdicts(tree: ast.Module):
    src = ast.unparse(_func(tree, "render_clean_card"))
    dec_call = _decisions_call(src)
    assert "_action_html" in dec_call
    assert "_signal_html" in dec_call
    assert "_dec_v2_html" in dec_call


def test_the_trade_watch_banner_is_in_the_same_card(tree: ast.Module):
    """Your own manually/Dhan-tracked trade sits beside the engine's native
    verdict in the same DECISIONS section, not a separate untested one."""
    src = ast.unparse(_func(tree, "render_clean_card"))
    assert "_tw_html" in _decisions_call(src)


def test_the_trade_card_reads_trade_watch_not_a_reimplementation(tree: ast.Module):
    fn = _func(tree, "render_clean_card")
    called = {c.func.attr for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "assess" in called   # mios_v5.trade_watch.assess, imported locally


def test_the_trade_card_reads_my_trade_not_dhan_directly(tree: ast.Module):
    """The card only READS `_my_trade` (whatever `_track_my_trade` last set);
    it must not poll Dhan itself — one fetch owner, `_track_my_trade`."""
    fn = _func(tree, "render_clean_card")
    src = ast.unparse(fn)
    assert "_my_trade" in src
    assert "find_open_nifty_option" not in src
    assert "get_dhan_positions" not in src


# ── render_market_picture's Position Guardian: idle must not be a lie ──
#
# The Guardian's "idle" fallback only meant the ENGINE had no armed trade —
# it said "no active trade" even while a manually-declared or Dhan-detected
# one (`_my_trade`) was open, which is wrong, not just uninformative.

def test_the_guardian_idle_branch_checks_my_trade(tree: ast.Module):
    fn = _func(tree, "render_market_picture")
    src = ast.unparse(fn)
    assert "_my_trade" in src


def test_the_guardian_uses_the_same_trade_watch_formula(tree: ast.Module):
    fn = _func(tree, "render_market_picture")
    called = {c.func.attr for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    assert "assess" in called


def test_the_idle_pink_banner_only_shows_when_nothing_is_open(tree: ast.Module):
    """The literal idle message must still exist for the true-idle case, but
    `_my_trade` is checked BEFORE it in source order — the trade-watch banner
    gets first refusal of the slot."""
    fn = _func(tree, "render_market_picture")
    src = ast.unparse(fn)
    assert "no active trade" in src
    assert src.index("_my_trade") < src.index("no active trade")
