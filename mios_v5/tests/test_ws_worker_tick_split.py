"""📡 `ws_worker` keeps the buy/sell split at source, and follows the ATM legs.

## Why the split cannot be derived downstream

The worker classifies every tick by the tick rule — LTP up → buy, LTP down →
sell, unchanged → neither — and used to store only the signed result,
`cum_delta` = buy − sell, alongside `volume` (the exchange's total traded
volume). Buy% and Sell% are not recoverable from that pair:

    buy − sell = cum_delta      known
    buy + sell = ?              NOT volume — volume >= buy + sell

Two unknowns, one equation. Assuming `buy + sell ≈ volume` is wrong exactly
where it matters most: an illiquid option leg prints many unchanged-price
ticks, so the neutral share is largest on the very instruments whose flow is
hardest to read. So both sides are accumulated explicitly.

`ws_worker` imports `websockets` and exits without Dhan credentials, so these
are source-level checks — the same convention as `test_dhan_rate_limits.py`.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "ws_worker.py"
_SCHEMA = pathlib.Path(__file__).resolve().parents[2] / "db" / "schema.sql"


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text()


@pytest.fixture(scope="module")
def tree(source: str) -> ast.Module:
    return ast.parse(source)


def _fn(tree: ast.Module, name: str) -> ast.FunctionDef:
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found")


# ── the split, accumulated not derived ─────────────────────────────────

def test_both_sides_are_accumulated_separately(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_apply_tick"))
    assert "s['buy_vol'] += ltq" in src
    assert "s['sell_vol'] += ltq" in src


def test_an_unchanged_price_counts_to_neither_side(tree: ast.Module):
    """The tick rule's third case. It must not be silently folded into one
    side — that is the whole reason volume cannot stand in for buy+sell."""
    src = ast.unparse(_fn(tree, "_apply_tick"))
    ups = src.count("+= ltq")
    downs = src.count("-= ltq")
    # exactly: cum_delta += , buy_vol += , cum_delta -= , sell_vol +=
    assert ups == 3 and downs == 1, f"unexpected tick accounting: {src}"


def test_the_split_reaches_the_database(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_flush_state_to_db"))
    assert "'buy_vol': float(s['buy_vol'])" in src
    assert "'sell_vol': float(s['sell_vol'])" in src


def test_the_state_starts_both_sides_at_zero(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_ensure_state"))
    assert "'buy_vol': 0.0" in src and "'sell_vol': 0.0" in src


def test_the_schema_has_the_two_columns():
    s = _SCHEMA.read_text()
    block = s[s.index("CREATE TABLE IF NOT EXISTS dhan_ticks"):][:900]
    assert "buy_vol" in block and "sell_vol" in block


def test_a_migration_exists_for_existing_deployments():
    sql = pathlib.Path(__file__).resolve().parents[2] / "sql"
    hits = [p for p in sql.glob("*.sql") if "buy_vol" in p.read_text()]
    assert hits, "no migration adds buy_vol to dhan_ticks"
    assert any("ADD COLUMN IF NOT EXISTS" in p.read_text() for p in hits)


# ── following the ATM legs ─────────────────────────────────────────────

def test_the_watch_set_is_bounded_by_wings(tree: ast.Module):
    """⚠️ The legs under analysis, never the whole chain — both the WebSocket
    load and the Supabase write volume have to stay flat."""
    src = ast.unparse(_fn(tree, "_resolve_atm_legs"))
    assert "ATM_WINGS" in src
    assert "strikes[max(0, i - ATM_WINGS):i + ATM_WINGS + 1]" in src


def test_it_subscribes_both_sides_of_each_strike(tree: ast.Module):
    src = ast.unparse(_fn(tree, "_resolve_atm_legs"))
    assert "('ce', 'pe')" in src


def test_a_failed_resolve_keeps_the_existing_subscription(tree: ast.Module):
    """A transient chain error must not drop the tick feed."""
    src = ast.unparse(_fn(tree, "_resolve_atm_legs"))
    assert "return []" in src
    refresh = ast.unparse(_fn(tree, "_refresh_atm"))
    assert "if not legs or set(legs) == set(_atm_current)" in refresh


def test_it_waits_out_dhans_option_chain_window(tree: ast.Module):
    """One request per 3 seconds — the same limit the app's own chain fetch
    respects."""
    src = ast.unparse(_fn(tree, "_resolve_atm_legs"))
    assert "sleep(3.1)" in src


def test_the_blocking_resolve_runs_off_the_event_loop(tree: ast.Module):
    """⚠️ It does blocking HTTP and a 3s wait. Inline, that would stall the
    WebSocket read and drop ticks — the one thing a tick worker must not do."""
    src = ast.unparse(_fn(tree, "_refresh_atm"))
    assert "asyncio.to_thread(_resolve_atm_legs)" in src


def test_an_atm_roll_unsubscribes_what_it_replaces(tree: ast.Module):
    """Otherwise the subscription set grows all session and the write volume
    with it."""
    src = ast.unparse(_fn(tree, "_refresh_atm"))
    assert "REQ_UNSUBSCRIBE" in src


def test_statically_pinned_instruments_survive_a_roll(tree: ast.Module):
    """An operator's explicit WATCH_INSTRUMENTS must not be dropped when the
    ATM legs change."""
    src = ast.unparse(_fn(tree, "_refresh_atm"))
    assert "_STATIC_WATCH" in src


def test_atm_following_is_opt_in(source: str):
    """Default behaviour is unchanged — no WATCH_ATM, no chain calls."""
    tree = ast.parse(source)
    src = ast.unparse(_fn(tree, "_refresh_atm"))
    assert "if not WATCH_ATM:" in src and "return" in src


def test_it_is_called_from_the_read_loop(source: str):
    assert "await _refresh_atm(ws)" in source


# ── the resolver actually RUN, not just grepped ────────────────────────

def _run_resolver(source: str, spot: float, wings: int, monkeypatch):
    """Execute `_resolve_atm_legs` against a synthetic chain, with its two
    HTTP calls stubbed. Returns (strikes_picked, legs)."""
    import json as _json
    import urllib.request

    ns = {"json": _json, "ACCESS_TOKEN": "x", "CLIENT_ID": "y",
          "WATCH_ATM": "NIFTY", "ATM_UNDERLYING": {"NIFTY": (13, "IDX_I")},
          "ATM_WINGS": wings,
          "time": type("T", (), {"sleep": staticmethod(lambda s: None)})()}
    for n in ast.parse(source).body:
        if getattr(n, "name", None) == "_resolve_atm_legs":
            exec(ast.get_source_segment(source, n), ns)   # noqa: S102

    oc, sid, rev = {}, 1000, {}
    for k in range(23800, 24301, 50):
        oc[f"{float(k):.6f}"] = {"ce": {"security_id": sid},
                                 "pe": {"security_id": sid + 1}}
        rev[sid], rev[sid + 1] = float(k), float(k)
        sid += 2
    payloads = [{"data": ["2026-09-03"]},
                {"data": {"last_price": spot, "oc": oc}}]

    class _R:
        def __init__(self, p): self.p = p
        def read(self): return _json.dumps(self.p).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _R(payloads.pop(0)))
    legs = ns["_resolve_atm_legs"]()
    return sorted({rev[s] for _sg, s in legs}), legs


def test_it_picks_the_nearest_strike_and_the_wings(source: str, monkeypatch):
    """Spot 24,037 → ATM 24,050 (nearest, not the one below), wings=1 → three
    strikes, both sides of each."""
    strikes, legs = _run_resolver(source, 24037.0, 1, monkeypatch)
    assert strikes == [24000.0, 24050.0, 24100.0]
    assert len(legs) == 6
    assert {sg for sg, _ in legs} == {"NSE_FNO"}


def test_wings_two_widens_to_five_strikes(source: str, monkeypatch):
    strikes, legs = _run_resolver(source, 24037.0, 2, monkeypatch)
    assert strikes == [23950.0, 24000.0, 24050.0, 24100.0, 24150.0]
    assert len(legs) == 10
