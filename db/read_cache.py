"""A Streamlit-cache layer in front of every Supabase read.

**Fetch once, then serve from `st.cache_data` until the app resets.** The rule
this implements, in the owner's words: *use Supabase only if the data is not
available in the Streamlit cache, or when the app gets reset.*

## Why it exists

`st_autorefresh(interval=20000)` reruns the whole script every 20 seconds, and
Streamlit executes **every** `st.tabs()` and `st.expander()` body on every
rerun — being hidden or collapsed does not stop the code. So all six V6 tabs
ran their queries every cycle: `get_engine_attribution(8000)`,
`get_session_log(8000)`, `get_trade_events(4000)` and a dozen more, about
**30,800 rows per cycle**, every 20 seconds, whether or not anyone was looking
at the tab that asked for them.

None of that data changes within 20 seconds. `engine_attribution` is written
once per graded trade; `session_log` once per session. Re-reading it 180 times
an hour bought nothing and cost the egress bill.

## How it works

`CachedDB` wraps `SupabaseDB` and proxies attribute access:

* a **read** goes through `st.cache_data`, keyed by method name and arguments
* a **write** passes straight through, untouched, and clears the reads it
  invalidates
* anything else — attributes, `is_connected`, unknown methods — is delegated

So no call site changes. Wrap the object once where it is built and every
consumer, panel and dashboard is cached at the same moment.

## Three lifetimes, because "until reset" is wrong for some of it

The default is `STATIC` — cached until the app restarts, exactly as asked. Two
carve-outs, and both are about not lying to a trader:

* **`LIVE`** (one refresh cycle) — *is there an open position right now?* A
  frozen answer to that question is worse than a slow one. The TTL still caps
  it at one fetch per cycle, so it is never worse than the old behaviour.
* **`INTRADAY`** (five minutes) — tables that grow *during* the session. A
  session log frozen at 09:20 would render an empty afternoon all day.

Everything else — the learning and history analytics, which is where the volume
actually was — is `STATIC`.

## Empty results are held briefly, not discarded

An empty read means "not populated yet", not "no such data" — so it is not
trusted until restart. It was originally not cached **at all**, and that made
the cache useless: a live session measured **741 reads, 734 of which reached
Supabase**, a 0.9% hit rate. Most of MIOS's analytics tables are empty for most
of a session, and every one of those reads was cached, immediately discarded,
and asked again twenty seconds later. The rule meant the emptier the database,
the harder it was queried.

An empty is now held for `EMPTY_TTL`, then dropped so the table is asked again.
Anything this app writes still invalidates its own read, so rows it produced
appear on the next call rather than waiting out the window — the window bounds
the case where something else filled the table.

A failed read is not cached either: the exception propagates out of the cached
function, so Streamlit stores nothing and the next cycle retries.
"""

from __future__ import annotations

import inspect as _inspect
import time as _time
from typing import Any, Callable, Dict, Tuple

import streamlit as st

#: One refresh cycle. `st_autorefresh` is 20s, so this caps a LIVE read at one
#: fetch per rerun without ever showing a stale position.
LIVE_TTL = 20

#: Five minutes. Long enough to remove ~93% of the fetches, short enough that
#: a table growing during the session still appears while the session is on.
INTRADAY_TTL = 300

STATIC, INTRADAY, LIVE = "static", "intraday", "live"

#: How long an EMPTY result is trusted before the table is asked again.
#:
#: ⚠️ This exists because "never cache an empty result" made the cache useless.
#: A live session measured **741 reads, 734 of which reached Supabase** — a 0.9%
#: hit rate. Most of MIOS's analytics tables are empty for most of a session
#: (nothing has been graded, no story validated, no bias resolved yet), and
#: every one of those reads was cached, immediately discarded, and asked again
#: on the next rerun. The rule meant the emptier the database, the harder it
#: was queried.
#:
#: The fear behind the old rule was real — an empty cached until restart would
#: leave a panel blank all day after its first rows landed. Five minutes is not
#: the rest of the session, and it is the same window `INTRADAY_TTL` already
#: accepts for tables that grow during one.
EMPTY_TTL = 300

#: `(method, signature)` → when it last came back empty.
_EMPTY_KEY = "_db_cache_empty_since"

#: method → the distinct cache keys it has asked for this session.
#:
#: ⚠️ The measurement that separates the two reasons a hit rate can be low, and
#: they have opposite fixes.
#:
#: A live session measured 253 calls against 229 fetches — at most **1.10 calls
#: per distinct key**. A cache cannot serve a repeat that never comes, so that
#: is not a broken cache: it is reads that are each asked once. The fix for
#: that is upstream (fewer distinct questions), not here.
#:
#: The other cause looks identical in the totals — keys that DO repeat but never
#: match, because an argument moves every call. Only a per-method distinct count
#: tells them apart: `calls ≈ distinct` is churn, `calls >> distinct` is a cache
#: that should be hitting and is not.
_KEYS_KEY = "_db_cache_keys"

#: Distinct keys remembered per method. A read parameterised by strike or by
#: day can legitimately have many, and this is a diagnostic, not a ledger — the
#: ratio is what matters and it survives a cap.
_KEYS_CAP = 400

#: Decision-critical "right now" reads. Never frozen.
_LIVE_READS: Tuple[str, ...] = (
    "get_active_trade_signal",
    "get_active_trade",
    "get_latest_spot",
    "get_trade_config",
    "count_trade_signals_today",
)

#: Tables that grow during the trading session.
_INTRADAY_READS: Tuple[str, ...] = (
    "get_trade_signals", "get_mios_decisions", "get_engine_state",
    "get_session_log", "get_session_recommendations", "get_session_validation",
    "get_day_type_log", "get_alerts_history", "get_alert_side_counts",
    "get_leg_flow_snapshots", "get_leg_entry_signals", "get_engine_errors",
    "get_my_analysis", "get_market_events", "get_market_stories",
    "get_entry_gate_signals", "get_open_bias_predictions",
    "get_oc_signals", "get_master_signals", "get_detected_patterns",
    "get_spot_history", "get_day_open_spot", "get_candles",
    "get_option_chain", "get_atm_strike_data", "get_orderbook",
    "get_pcr_history", "get_gex_history", "get_bid_ask_history",
    "get_volume_delta_history", "get_max_pain_history",
)

#: Every read on `SupabaseDB`. Anything here that is not LIVE or INTRADAY is
#: STATIC — fetched once, then served from cache until the app resets.
#:
#: A method absent from this tuple is **not cached at all** and goes straight
#: through, which is the safe direction for a read this file has never seen.
_READS: Tuple[str, ...] = _LIVE_READS + _INTRADAY_READS + (
    # ── the learning / history analytics: where the 30,800 rows lived ──
    "get_engine_attribution", "get_trade_attribution", "get_trade_events",
    "get_trade_results", "get_learning_snapshots",
    "get_resolved_entry_gate_signals", "get_layer_outcomes",
    "get_bias_predictions", "get_signal_outcomes",
    "get_story_validations", "get_story_stats",
    "get_event_impact_log", "get_opening_auction_log",
    # ── candle history: append-only, and the source of a full-table scan ──
    "get_available_candle_series", "get_candle_trading_days",
    "get_candles_for_day", "get_backfill_progress",
    # ── the rest ──
    # Stage 74 calibration evidence — a week of samples, read to render a
    # distribution. It grows by one row a minute, so INTRADAY would refetch
    # thousands of rows to gain sixty; STATIC plus the write-invalidation below
    # is the right trade.
    "get_liquidity_telemetry",
    "get_option_chain_history", "get_atm_iv_history", "get_market_analytics",
    "get_user_preferences", "get_leg_flow_days", "get_trade_history",
    "count_rows", "fetch_all_rows",
)

#: Which cached reads a write makes stale. A write that is not listed clears
#: nothing — it is better to leave a cache alone than to guess wrong and
#: re-fetch eight thousand rows because an unrelated row was inserted.
_INVALIDATES: Dict[str, Tuple[str, ...]] = {
    "insert_trade_signal": ("get_trade_signals", "count_trade_signals_today"),
    "update_trade_signal": ("get_trade_signals", "get_active_trade_signal"),
    "insert_engine_attribution": ("get_engine_attribution",),
    "insert_trade_attribution": ("get_trade_attribution",),
    "insert_trade_event": ("get_trade_events",),
    "insert_trade_result": ("get_trade_results",),
    "insert_learning_snapshot": ("get_learning_snapshots",),
    "insert_session_log": ("get_session_log",),
    "insert_session_recommendations": ("get_session_recommendations",),
    "insert_session_validation": ("get_session_validation",),
    "insert_day_type": ("get_day_type_log",),
    "insert_engine_state": ("get_engine_state",),
    "insert_market_event": ("get_market_events",),
    "insert_market_story": ("get_market_stories",),
    "insert_story_validation": ("get_story_validations",),
    "upsert_story_stats": ("get_story_stats",),
    "upsert_my_analysis": ("get_my_analysis",),
    "insert_engine_error": ("get_engine_errors",),
    "insert_entry_gate_signal": ("get_entry_gate_signals",),
    "update_entry_gate_signal": ("get_entry_gate_signals",
                                 "get_resolved_entry_gate_signals",
                                 "get_layer_outcomes"),
    "insert_bias_prediction": ("get_bias_predictions",
                               "get_open_bias_predictions"),
    "update_bias_prediction": ("get_bias_predictions",
                               "get_open_bias_predictions"),
    "insert_leg_flow_snapshot": ("get_leg_flow_snapshots", "get_leg_flow_days"),
    "insert_leg_entry_signal": ("get_leg_entry_signals",),
    "insert_signal_outcome": ("get_signal_outcomes",),
    "update_signal_outcome": ("get_signal_outcomes",),
    "insert_mios_decision": ("get_mios_decisions",),
    "upsert_backfill_progress": ("get_backfill_progress",),
    "save_trade_config": ("get_trade_config",),
    "insert_liquidity_telemetry": ("get_liquidity_telemetry",),
    "save_user_preferences": ("get_user_preferences",),
}

_STATS_KEY = "_db_cache_stats"


def _bucket(method: str) -> str:
    if method in _LIVE_READS:
        return LIVE
    if method in _INTRADAY_READS:
        return INTRADAY
    return STATIC


#: `inspect.signature` per method, computed once. Binding on every call would
#: be measurable at 180 reruns an hour; the signature never changes.
_SIGNATURES: Dict[str, Any] = {}


def _canonical(target: Callable, method: str, args: tuple,
               kwargs: dict) -> Tuple[Any, ...]:
    """One cache key for every spelling of the same call.

    `get_session_log(None, 4000)` and `get_session_log(trading_day=None,
    limit=4000)` are the same question, and two call sites in the dashboards
    genuinely do write it both ways. Without binding they would be two cache
    entries and two fetches of the same eight thousand rows.

    Defaults are applied too, so `get_engine_attribution()` and
    `get_engine_attribution(limit=8000)` collapse to one entry.

    A signature that will not bind — a caller passing the wrong arguments —
    falls back to the raw form. The call is about to raise anyway, and this
    layer is not the place to report it.
    """
    try:
        sig = _SIGNATURES.get(method)
        if sig is None:
            sig = _SIGNATURES[method] = _inspect.signature(target)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return _signature((), dict(bound.arguments))
    except (TypeError, ValueError):
        return _signature(args, kwargs)


def _signature(args: tuple, kwargs: dict) -> Tuple[Any, ...]:
    """A hashable cache key from the call's arguments.

    Unhashable arguments (a DataFrame, a dict) collapse to their `repr`. That
    keeps the key stable and hashable without pretending to understand a value
    this layer never inspects.
    """
    def one(v):
        try:
            hash(v)
            return v
        except TypeError:
            return repr(v)
    return (tuple(one(a) for a in args),
            tuple(sorted((k, one(v)) for k, v in kwargs.items())))


def _empty(result: Any) -> bool:
    """Did this read come back with nothing?

    Handles a DataFrame (`.empty`), a list, and `None` — the three shapes every
    read on `SupabaseDB` returns. A number (`count_rows`) is never empty; `0` is
    a real answer.
    """
    if result is None:
        return True
    is_empty = getattr(result, "empty", None)
    if is_empty is not None:
        return bool(is_empty)
    if isinstance(result, (list, tuple, dict, str)):
        return len(result) == 0
    return False


def _bump(kind: str) -> None:
    """Count a hit or a miss, when there is a session to count it in."""
    try:
        stats = st.session_state.setdefault(
            _STATS_KEY, {"calls": 0, "fetches": 0, "rows": 0, "empty": 0})
    except Exception:
        return
    stats[kind] = stats.get(kind, 0) + 1


def _empty_expired(method: str, signature: Tuple[Any, ...]) -> bool:
    """Has this empty been trusted long enough? Stamps it on first sight.

    Returns True only once the window has passed, which is the moment the
    caller should drop the cached entry so the table is asked again.
    """
    try:
        seen = st.session_state.setdefault(_EMPTY_KEY, {})
    except Exception:
        return True          # no session to remember in — behave as before
    key = (method, signature)
    now = _time.time()
    first = seen.get(key)
    if first is None:
        seen[key] = now
        return False
    if now - first >= EMPTY_TTL:
        seen.pop(key, None)
        return True
    return False


def _forget_empty(method: str, signature: Tuple[Any, ...]) -> None:
    """A read that came back with rows is no longer an empty one."""
    try:
        st.session_state.get(_EMPTY_KEY, {}).pop((method, signature), None)
    except Exception:
        pass


def _note_key(method: str, signature: Tuple[Any, ...]) -> None:
    """Remember that this method was asked this exact question."""
    try:
        seen = st.session_state.setdefault(_KEYS_KEY, {})
    except Exception:
        return
    keys = seen.setdefault(method, set())
    if len(keys) < _KEYS_CAP:
        keys.add(signature)


def key_churn() -> Dict[str, Dict[str, int]]:
    """Per method: how many times it was asked, and how many DISTINCT questions.

    `calls ≈ distinct` means the method asks a different question every time, so
    nothing it does can be cached — look at the caller. `calls >> distinct` with
    a low hit rate means the cache is failing to match keys it should.
    """
    try:
        seen = dict(st.session_state.get(_KEYS_KEY) or {})
    except Exception:
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for method, keys in seen.items():
        out[method] = {"distinct": len(keys)}
    return out


def churn_line(limit: int = 4) -> str:
    """The methods asking the most DISTINCT questions, worst first.

    Empty when nothing has been read. This is the line that says whether a low
    hit rate is the cache's fault or the caller's: a method with 40 distinct
    keys is asking 40 different questions, and no cache can collapse those.
    """
    churn = key_churn()
    if not churn:
        return ""
    top = sorted(churn.items(), key=lambda kv: -kv[1]["distinct"])[:limit]
    if not top or top[0][1]["distinct"] <= 1:
        return ""
    return " · ".join(f"{m} {v['distinct']}" for m, v in top)


def _rows(result: Any) -> int:
    try:
        return int(len(result))
    except Exception:
        return 0


def _invoke(_db: Any, method: str, signature: Tuple[Any, ...],
            args: tuple, kwargs: dict) -> Any:
    """The real call. Only reached on a cache miss — which is what makes the
    counter below an accurate count of Supabase round-trips."""
    _bump("fetches")
    result = getattr(_db, method)(*args, **kwargs)
    try:
        stats = st.session_state.get(_STATS_KEY)
        if stats is not None:
            stats["rows"] = stats.get("rows", 0) + _rows(result)
    except Exception:
        pass
    return result


# Three functions rather than one, because `ttl` is fixed at decoration time.
# `_db`, `args` and `kwargs` are underscore-prefixed so Streamlit excludes them
# from the hash — `signature` is the key, and it is already hashable.

@st.cache_data(ttl=None, show_spinner=False)
def _fetch_static(_db, method, signature, _args, _kwargs):
    return _invoke(_db, method, signature, _args, _kwargs)


@st.cache_data(ttl=INTRADAY_TTL, show_spinner=False)
def _fetch_intraday(_db, method, signature, _args, _kwargs):
    return _invoke(_db, method, signature, _args, _kwargs)


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def _fetch_live(_db, method, signature, _args, _kwargs):
    return _invoke(_db, method, signature, _args, _kwargs)


_FETCHERS = {STATIC: _fetch_static, INTRADAY: _fetch_intraday, LIVE: _fetch_live}


def invalidate(*methods: str) -> None:
    """Drop cached reads. No arguments clears every bucket.

    Called after a write, and by the sidebar's Refresh button — the manual
    equivalent of an app reset, for when a trader wants the analytics re-read
    without restarting.
    """
    if not methods:
        for fetch in _FETCHERS.values():
            try:
                fetch.clear()
            except Exception:
                pass
        return
    # Streamlit clears per-entry by argument, and this layer does not track
    # which argument combinations are live — so a targeted invalidation clears
    # the whole bucket that method belongs to. Coarse, and correct.
    for method in methods:
        try:
            _FETCHERS[_bucket(method)].clear()
        except Exception:
            pass


def stats() -> Dict[str, int]:
    """`calls` asked of this layer · `fetches` that reached Supabase · `rows`
    those fetches returned · `empty` reads that came back with nothing.

    `calls - fetches` is what the cache saved. `empty` is the diagnostic: a
    high count beside a low saving means the tables are unpopulated, not that
    the keys are wrong — which is exactly what a 0.9% hit rate turned out to
    be."""
    try:
        return dict(st.session_state.get(_STATS_KEY)
                    or {"calls": 0, "fetches": 0, "rows": 0, "empty": 0})
    except Exception:
        return {"calls": 0, "fetches": 0, "rows": 0, "empty": 0}


def reset_stats() -> None:
    try:
        st.session_state[_STATS_KEY] = {"calls": 0, "fetches": 0, "rows": 0,
                                        "empty": 0}
        st.session_state[_KEYS_KEY] = {}
    except Exception:
        pass


class CachedDB:
    """`SupabaseDB`, with every read served from `st.cache_data`.

    A drop-in wrapper: `hasattr`, attribute reads and unknown methods all
    delegate, so the forty-odd call sites across the dashboards need no change
    and none of them can tell the difference — except that they stop costing
    egress.
    """

    def __init__(self, db: Any) -> None:
        # `object.__setattr__` is not needed — `__getattr__` only fires when
        # normal lookup fails, and `_db` is a real instance attribute.
        self._db = db

    # ── the wrapper ──────────────────────────────────────────────────
    def __getattr__(self, name: str) -> Any:
        # Only called when `name` is not on CachedDB itself.
        #
        # Dunders are refused outright. `copy`, `pickle` and Streamlit's hasher
        # probe for `__getstate__`, `__deepcopy__` and friends; delegating those
        # to `self._db` before `__init__` has run — or on a half-restored
        # instance — recurses until the stack ends. A plain AttributeError is
        # what every one of those callers is written to handle.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        target = getattr(self.__dict__["_db"], name)

        if name in _READS and callable(target):
            return self._cached(name, target)
        if name in _INVALIDATES and callable(target):
            return self._writing(name, target)
        return target

    def _cached(self, method: str, target: Callable) -> Callable[..., Any]:
        def call(*args, **kwargs):
            _bump("calls")
            signature = _canonical(target, method, args, kwargs)
            _note_key(method, signature)
            fetch = _FETCHERS[_bucket(method)]
            result = fetch(self._db, method, signature, args, kwargs)
            if _empty(result):
                _bump("empty")
                # ⚠️ Not discarded outright — held for `EMPTY_TTL`.
                #
                # Discarding immediately is what produced a 0.9% hit rate on a
                # live session: MIOS's analytics tables are empty for most of a
                # session, so nearly every read was cached, dropped, and asked
                # again twenty seconds later. The emptier the database, the
                # harder it was queried.
                #
                # An empty is still not trusted for long — a table that fills
                # at 09:20 must not read blank at 15:00 — so the entry is kept
                # only until the window expires, then cleared so the next call
                # asks again.
                if _empty_expired(method, signature):
                    try:
                        fetch.clear(self._db, method, signature, args, kwargs)
                    except Exception:
                        pass
            else:
                _forget_empty(method, signature)
            return result
        call.__name__ = method
        return call

    def _writing(self, method: str, target: Callable) -> Callable[..., Any]:
        def call(*args, **kwargs):
            result = target(*args, **kwargs)
            invalidate(*_INVALIDATES[method])
            return result
        call.__name__ = method
        return call

    # ── introspection ────────────────────────────────────────────────
    @property
    def raw(self) -> Any:
        """The wrapped `SupabaseDB`, for a caller that must bypass the cache."""
        return self._db

    def cache_stats(self) -> Dict[str, int]:
        return stats()

    def __repr__(self) -> str:
        s = stats()
        return (f"CachedDB({self._db!r}, calls={s['calls']}, "
                f"fetches={s['fetches']})")


def wrap(db: Any) -> Any:
    """Wrap a `SupabaseDB` once, at the point it is built.

    Returns `db` unchanged when it is `None` or already wrapped, so calling
    this twice is safe and a missing database still reads as missing rather
    than as an object that fails on first use.
    """
    if db is None or isinstance(db, CachedDB):
        return db
    return CachedDB(db)
