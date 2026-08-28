"""📦 `build_leg_bias_table` reads what `_publish_atm_legs` already computed.

Measured duplication (docs/AUDIT_FETCH_DUPLICATION.md §4): `_publish_atm_legs`
stores `_atm_leg_vob_volume`, `_atm_leg_sr_behavior` and `_atm_leg_vidya` per
ATM±1 leg at step 9 of the render; `build_leg_bias_table` then ran at step 10
and recomputed all three from the same frames, never looking at the store —
~250 ms per render, ~45 s/hour at a 20s cycle, with
`VolumeOrderBlocks.detect_blocks` running four times per leg.

Reading the store is only safe because of two facts, and both are tested here
rather than assumed:

1. **Same frame.** The store is keyed by the SAME `name` as `_atm_leg_dfs`, so
   the stored value was computed from the very frame the table reads.
2. **Deterministic functions.** Same frame in, same result out — so a stored
   result and a freshly computed one cannot differ.

Lose either and the table would silently show a different leg's numbers, which
is far worse than the 250 ms.
"""

from __future__ import annotations

import ast
import pathlib

import numpy as np
import pandas as pd
import pytest

from indicators import order_flow as _of

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"


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


@pytest.fixture(scope="module")
def engines(source: str, tree: ast.Module) -> dict:
    """The three leg engines, extracted and executed without booting the app."""
    want = {"VolumeOrderBlocks", "analyze_vob_volume", "_clv_delta_cols",
            "calculate_vidya", "classify_leg_sr_behavior", "ReversalDetector"}
    ns: dict = {"pd": pd, "np": np, "_of": _of}
    segs = [ast.get_source_segment(source, n) for n in tree.body
            if getattr(n, "name", None) in want]
    exec("\n\n".join(segs), ns)   # noqa: S102 — our own source
    return ns


def _frame(seed: int = 7, n: int = 375) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    return pd.DataFrame({"open": close - 0.2, "high": close + 0.4,
                         "low": close - 0.4, "close": close,
                         "volume": rng.integers(500, 5000, n)})


# ── fact 2: the functions are deterministic ────────────────────────────

def test_analyze_vob_volume_is_deterministic(engines):
    df = _frame(); ltp = float(df["close"].iloc[-1])
    assert engines["analyze_vob_volume"](df, ltp) == \
        engines["analyze_vob_volume"](df, ltp)


def test_calculate_vidya_is_deterministic(engines):
    df = _frame()
    assert engines["calculate_vidya"](df) == engines["calculate_vidya"](df)


def test_classify_leg_sr_behavior_is_deterministic(engines):
    df = _frame(); ltp = float(df["close"].iloc[-1])
    assert engines["classify_leg_sr_behavior"](df, ltp) == \
        engines["classify_leg_sr_behavior"](df, ltp)


def test_a_different_frame_gives_a_different_answer(engines):
    """Determinism must not be the trivial kind — if the function ignored its
    input, reading a stale store would also 'pass' the tests above."""
    a = engines["calculate_vidya"](_frame(seed=1))
    b = engines["calculate_vidya"](_frame(seed=2))
    assert a != b


# ── fact 1: one key, shared by the frames and the stores ───────────────

def test_the_stores_are_keyed_the_same_as_the_frames(source: str):
    """`_atm_leg_dfs[name]` and `_atm_leg_*[name]` — the SAME `name`, so
    `build_leg_bias_table`'s loop variable indexes both."""
    seg = source[source.index('name = f"{tag} {side} {strike:.0f}"'):][:1200]
    assert "st.session_state['_atm_leg_dfs'][name]" in seg
    assert "st.session_state[store][name] = val" in seg


def test_the_table_iterates_the_frame_store(source: str):
    seg = source[source.index("def build_leg_bias_table"):][:1500]
    assert "leg_dfs = st.session_state.get('_atm_leg_dfs')" in seg


# ── the helper ──────────────────────────────────────────────────────────

def test_the_helper_prefers_the_store(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_leg_cached"))
    hit = src.index("hit")
    call = src.index("fn(*args)")
    assert hit < call, "it recomputes before consulting the store"


def test_the_helper_falls_back_on_a_miss(tree: ast.Module):
    """First render of a session, or a leg `_publish_atm_legs` could not do."""
    src = ast.unparse(_fn(tree, "_leg_cached"))
    assert "fn(*args)" in src


def test_the_helper_never_raises(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_leg_cached"))
    assert src.count("except Exception") >= 2


# ── the three call sites actually use it ───────────────────────────────

def test_all_three_engines_go_through_the_store(tree: ast.Module):
    fn = _fn(tree, "build_leg_bias_table")
    src = ast.unparse(fn)
    for store in ("'_atm_leg_vob_volume'", "'_atm_leg_sr_behavior'",
                  "'_atm_leg_vidya'"):
        assert store in src, f"{store} is not read by the table"


def test_no_engine_is_called_bare_any_more(tree: ast.Module):
    """⚠️ The regression: a direct call bypasses the store and pays the full
    cost again."""
    fn = _fn(tree, "build_leg_bias_table")
    bare = {c.func.id for c in ast.walk(fn)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    for engine in ("analyze_vob_volume", "classify_leg_sr_behavior"):
        assert engine not in bare, f"{engine} is still called directly"


def test_the_vidya_read_survives_a_missing_result(tree: ast.Module):
    """`_leg_cached` may return None; `.get('trend')` on None would raise and
    blank the whole leg row."""
    src = ast.unparse(_fn(tree, "build_leg_bias_table"))
    assert "or {}).get('trend')" in src


def test_the_publisher_still_runs_before_the_table(source: str):
    """Reading the store is only correct if it has been filled this cycle."""
    pub = source.rindex("_publish_atm_legs(api, underlying, option_data")
    tbl = source.rindex("render_all_bias_dashboard(underlying, df, option_data")
    assert pub < tbl
