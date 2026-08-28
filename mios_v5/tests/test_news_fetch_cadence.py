"""📰 `compute_news_bias` must arm its cadence gate on the ATTEMPT, not on
success.

It has four callers — the News panel, `compute_market_picture`, the bias
dashboard, and the Live Confluence card. The gate used to be stamped only on
the fully-successful path, so both failure exits returned without setting it
and every caller refetched on every render. A measured probe of one render
(all HTTP mocked, feed returning nothing) recorded FOUR identical Google-News
GETs — the only duplicated request in the entire render. At a ~20s cycle that
is ~720 requests/hour aimed at a feed that is already failing.

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


def _news(tree: ast.Module) -> str:
    return ast.unparse(_func(tree, "compute_news_bias"))


def test_the_gate_is_stamped_before_the_fetch_is_attempted(source: str, tree: ast.Module):
    """⚠️ The regression: stamping only after success let a failing feed be
    re-hit by all four callers on every render."""
    src = _news(tree)
    stamp = src.index("_news_last_fetch'] = now_t")
    fetch = src.index("fetch_news_headlines()")
    assert stamp < fetch, "the cadence gate is still armed only after fetching"


def test_a_failing_feed_cannot_be_refetched_within_the_cadence(tree: ast.Module):
    """Both failure exits return the last good value; neither may run before
    the gate has been stamped."""
    src = _news(tree)          # ⚠️ unparsed — comments are gone, anchor on code
    stamp = src.index("_news_last_fetch'] = now_t")
    # the `except` exit and the `if not heads` exit, by their code anchors
    for marker in ("except Exception as _e:", "if not heads:"):
        assert src.index(marker) > stamp, f"failure path {marker!r} bypasses the gate"
    # ⚠️ NOT every `return cached` — the FIRST one is the cache-hit fast path
    # and correctly precedes the stamp. It is the LAST one (the `if not heads`
    # exit) that must sit after it.
    assert src.rindex("return cached") > stamp


def test_the_cache_hit_does_not_require_a_populated_cache(tree: ast.Module):
    """`if cached and (now-last) < cadence` let all four callers through on a
    cold start, because `cached` is None until the first success lands."""
    src = _news(tree)
    assert "if cached and (now_t - _last) < cadence_s" not in src
    assert "if now_t - _last < cadence_s" in src


def test_it_still_serves_the_last_good_value_on_failure(tree: ast.Module):
    """Arming the gate must not turn a transient feed failure into a blank
    read — the same rule `get_dhan_option_chain`'s cache documents."""
    src = _news(tree)
    assert src.count("return cached") >= 2


def test_the_four_callers_are_still_only_four(source: str):
    """A fifth caller is fine, but it should be a deliberate choice — this
    pins the count so adding one is visible in review."""
    n = source.count("compute_news_bias()")
    assert n == 4, f"expected 4 call sites, found {n}"
