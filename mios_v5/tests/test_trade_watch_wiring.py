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
