"""`db/read_cache.py` — the Streamlit cache in front of every Supabase read.

The property under test is a number: **how many times does a read actually
reach Supabase?** Everything else here supports that one question.

The stakes, measured before this layer existed: `st_autorefresh` reruns the
script every 20 seconds, Streamlit executes every `st.tabs()` and
`st.expander()` body on every rerun regardless of what is visible, and the six
V6 tabs between them asked for ~30,800 rows per cycle — `get_engine_attribution(8000)`,
`get_session_log(8000)`, `get_trade_events(4000)` and a dozen more. None of that
data changes within 20 seconds.

`db/` is not importable here — `db/__init__.py` imports `supabase`, which is not
installed — so the module is loaded from its path directly, the same approach
`test_dispatch_registry` already uses.
"""

import importlib.util
import pathlib

import pytest


def _load():
    root = pathlib.Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "_read_cache_under_test", root / "db" / "read_cache.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RC = _load()


class FakeDB:
    """Counts real round-trips. Every method records that it was actually
    called, which is the only thing these tests care about."""

    is_connected = True

    def __init__(self):
        self.hits = {}

    def _hit(self, name):
        self.hits[name] = self.hits.get(name, 0) + 1

    # ── STATIC: cached until the app resets ──
    def get_engine_attribution(self, limit=8000):
        self._hit("get_engine_attribution")
        return [{"engine": i} for i in range(min(limit, 10))]

    def get_trade_events(self, limit=4000):
        self._hit("get_trade_events")
        return [{"ts": 1}]

    def get_available_candle_series(self):
        self._hit("get_available_candle_series")
        return [("NIFTY50", "IDX_I", "3")]

    # ── INTRADAY ──
    def get_session_log(self, trading_day=None, limit=2000):
        self._hit("get_session_log")
        return [{"session": "morning"}]

    # ── LIVE ──
    def get_active_trade(self):
        self._hit("get_active_trade")
        return {"id": 1}

    # ── returns nothing ──
    def get_trade_results(self, limit=500):
        self._hit("get_trade_results")
        return []

    # ── writes ──
    def insert_engine_attribution(self, row):
        self._hit("insert_engine_attribution")
        return True

    def insert_session_log(self, row):
        self._hit("insert_session_log")
        return True

    # ── a read this layer has never heard of ──
    def get_something_new(self):
        self._hit("get_something_new")
        return [1, 2, 3]


@pytest.fixture(autouse=True)
def _clean():
    RC.invalidate()
    RC.reset_stats()
    yield
    RC.invalidate()


@pytest.fixture
def pair():
    raw = FakeDB()
    return raw, RC.wrap(raw)


# ══════════════════════════════════════════════════════════════════════
#  the number that matters
# ══════════════════════════════════════════════════════════════════════

def test_a_full_trading_day_of_reruns_costs_one_fetch(pair):
    """1,125 reruns is a 6.25-hour session at a 20-second refresh. Before this
    layer that was 1,125 fetches of eight thousand rows."""
    raw, db = pair
    for _ in range(1125):
        db.get_engine_attribution(limit=8000)
    assert raw.hits["get_engine_attribution"] == 1


@pytest.mark.parametrize("method,kwargs", [
    ("get_engine_attribution", {"limit": 8000}),
    ("get_trade_events", {"limit": 4000}),
    ("get_session_log", {"limit": 8000}),
    ("get_active_trade", {}),
])
def test_repeated_identical_reads_fetch_once(pair, method, kwargs):
    raw, db = pair
    for _ in range(50):
        getattr(db, method)(**kwargs)
    assert raw.hits[method] == 1


def test_different_arguments_are_different_cache_entries(pair):
    """`_history` asks for 2,000 engine rows and `_learning` for 8,000. They are
    different questions and must not share an answer."""
    raw, db = pair
    db.get_engine_attribution(limit=2000)
    db.get_engine_attribution(limit=8000)
    db.get_engine_attribution(limit=2000)
    assert raw.hits["get_engine_attribution"] == 2


def test_positional_and_keyword_forms_of_one_call_agree(pair):
    """Two call sites in the dashboards genuinely write the same call both
    ways. Without binding they would be two entries and two fetches."""
    raw, db = pair
    db.get_session_log(None, 4000)
    db.get_session_log(trading_day=None, limit=4000)
    assert raw.hits["get_session_log"] == 1


def test_an_omitted_default_matches_the_same_value_passed_explicitly(pair):
    raw, db = pair
    db.get_engine_attribution()
    db.get_engine_attribution(limit=8000)
    db.get_engine_attribution(8000)
    assert raw.hits["get_engine_attribution"] == 1


# ══════════════════════════════════════════════════════════════════════
#  the three lifetimes
# ══════════════════════════════════════════════════════════════════════

def test_the_buckets_are_what_the_module_says_they_are():
    assert RC._bucket("get_engine_attribution") == RC.STATIC
    assert RC._bucket("get_session_log") == RC.INTRADAY
    assert RC._bucket("get_active_trade") == RC.LIVE
    assert RC._bucket("anything_unlisted") == RC.STATIC


def test_a_live_read_is_never_frozen_until_restart():
    """*Is there an open position right now?* — a frozen answer to that is worse
    than a slow one, so it expires within one refresh cycle."""
    assert RC.LIVE_TTL <= 20
    for name in RC._LIVE_READS:
        assert RC._bucket(name) == RC.LIVE


def test_intraday_reads_expire_while_the_session_is_still_running():
    """A session log frozen at 09:20 would render an empty afternoon all day."""
    assert 0 < RC.INTRADAY_TTL <= 600


def test_the_heavy_analytics_are_the_ones_held_until_reset():
    """Where the volume actually was — all STATIC, all fetched once."""
    for name in ("get_engine_attribution", "get_trade_events",
                 "get_trade_results", "get_trade_attribution",
                 "get_available_candle_series"):
        assert RC._bucket(name) == RC.STATIC


# ══════════════════════════════════════════════════════════════════════
#  what must NOT be cached
# ══════════════════════════════════════════════════════════════════════

def test_an_empty_result_is_held_briefly_rather_than_never_cached(pair):
    """⭐ Never caching an empty made the cache useless.

    A live session measured **741 reads, 734 of which reached Supabase** — a
    0.9% hit rate. Most of MIOS's analytics tables are empty for most of a
    session, and every one of those reads was cached, immediately discarded,
    and asked again twenty seconds later. The rule meant the emptier the
    database, the harder it was queried.

    An empty is now trusted for `EMPTY_TTL`, so repeated asks inside the window
    cost one round-trip rather than one each.
    """
    raw, db = pair
    for _ in range(3):
        assert db.get_trade_results() == []
    assert raw.hits["get_trade_results"] == 1, "one fetch, not three"


def test_an_empty_is_asked_again_once_the_window_passes(pair, monkeypatch):
    """It is trusted briefly, not indefinitely — a table that fills at 09:20
    must not still read blank at 15:00."""
    raw, db = pair
    assert db.get_trade_results() == []
    assert raw.hits["get_trade_results"] == 1

    clock = [RC._time.time() + RC.EMPTY_TTL + 1]
    monkeypatch.setattr(RC._time, "time", lambda: clock[0])
    db.get_trade_results()                      # expires the held empty
    raw.get_trade_results = lambda limit=500: [{"pnl": 12}]
    assert db.get_trade_results() == [{"pnl": 12}]


def test_a_write_picks_up_the_new_rows_without_waiting(pair):
    """The window is a bound, not the mechanism. Anything this app writes
    invalidates its own read, so rows it produced appear on the next call —
    which is the case that matters, since the app is the only writer for the
    tables in `_INVALIDATES`."""
    raw, db = pair
    assert db.get_trade_results() == []
    raw.get_trade_results = lambda limit=500: [{"pnl": 12}]
    RC.invalidate("get_trade_results")
    assert db.get_trade_results() == [{"pnl": 12}]


def test_empties_are_counted_so_a_low_hit_rate_can_be_diagnosed(pair):
    """A high `empty` beside a low saving means the tables are unpopulated, not
    that the cache keys are wrong. Without the count those look identical, and
    they have completely different fixes."""
    _raw, db = pair
    RC.reset_stats()
    db.get_trade_results()
    assert RC.stats()["empty"] >= 1


def test_a_failing_read_is_not_cached(pair):
    """A transient failure must retry, not become the cached answer."""
    raw, db = pair
    calls = {"n": 0}

    def flaky(limit=8000):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection reset")
        return [{"engine": "ok"}]

    raw.get_engine_attribution = flaky
    with pytest.raises(RuntimeError):
        db.get_engine_attribution(limit=8000)
    assert db.get_engine_attribution(limit=8000) == [{"engine": "ok"}]


def test_a_read_this_layer_has_never_seen_passes_straight_through(pair):
    """Not caching an unknown read is the safe direction — a new method is not
    silently frozen until someone classifies it."""
    raw, db = pair
    for _ in range(3):
        db.get_something_new()
    assert raw.hits["get_something_new"] == 3


# ══════════════════════════════════════════════════════════════════════
#  writes
# ══════════════════════════════════════════════════════════════════════

def test_a_write_passes_through_untouched(pair):
    raw, db = pair
    assert db.insert_engine_attribution({"x": 1}) is True
    assert raw.hits["insert_engine_attribution"] == 1


def test_a_write_invalidates_the_read_it_made_stale(pair):
    raw, db = pair
    db.get_engine_attribution(limit=8000)
    db.get_engine_attribution(limit=8000)
    assert raw.hits["get_engine_attribution"] == 1
    db.insert_engine_attribution({"x": 1})
    db.get_engine_attribution(limit=8000)
    assert raw.hits["get_engine_attribution"] == 2


def test_every_invalidation_target_is_a_read_this_layer_caches():
    """A write that clears a name nothing caches is a no-op somebody will one
    day mistake for working."""
    for write, reads in RC._INVALIDATES.items():
        for name in reads:
            assert name in RC._READS, f"{write} clears uncached {name}"


def test_no_read_is_classified_twice():
    assert len(RC._READS) == len(set(RC._READS))
    assert not set(RC._LIVE_READS) & set(RC._INTRADAY_READS)


# ══════════════════════════════════════════════════════════════════════
#  it is a drop-in — no call site changes
# ══════════════════════════════════════════════════════════════════════

def test_hasattr_still_answers_correctly(pair):
    """`dashboard_v6` guards on `hasattr(db, "get_trade_results")`. The wrapper
    must not turn those checks into a lie in either direction."""
    _, db = pair
    assert hasattr(db, "get_engine_attribution")
    assert hasattr(db, "insert_engine_attribution")
    assert not hasattr(db, "get_a_method_that_does_not_exist")


def test_plain_attributes_delegate(pair):
    _, db = pair
    assert db.is_connected is True


def test_dunder_lookups_do_not_recurse(pair):
    """`copy`, `pickle` and Streamlit's hasher probe for `__getstate__` and
    friends. Delegating those recurses until the stack ends."""
    _, db = pair
    for name in ("__deepcopy__", "__copy__", "__getnewargs__",
                 "__reduce_ex_custom__"):
        with pytest.raises(AttributeError):
            getattr(db, name)


def test_the_wrapped_client_stays_reachable(pair):
    raw, db = pair
    assert db.raw is raw


def test_wrapping_is_idempotent_and_none_safe():
    raw = FakeDB()
    once = RC.wrap(raw)
    assert RC.wrap(once) is once
    assert RC.wrap(None) is None


def test_the_app_wraps_the_client_exactly_once_where_it_is_built():
    """The regression this repo has been bitten by twice: a layer that exists
    but nothing calls. If the wrap is removed, every read goes direct again and
    nothing else would notice."""
    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "vob_minimal.py").read_text()
    assert "from db.read_cache import wrap as _cache_reads" in src
    assert "_cache_reads(SupabaseDB(" in src


# ══════════════════════════════════════════════════════════════════════
#  the manual reset, and the counters
# ══════════════════════════════════════════════════════════════════════

def test_invalidate_forces_a_refetch(pair):
    """The sidebar button — an app reset without restarting the app."""
    raw, db = pair
    db.get_engine_attribution(limit=8000)
    RC.invalidate()
    db.get_engine_attribution(limit=8000)
    assert raw.hits["get_engine_attribution"] == 2


def test_invalidating_one_bucket_leaves_the_others_alone(pair):
    raw, db = pair
    db.get_engine_attribution(limit=8000)
    db.get_session_log(limit=4000)
    RC.invalidate("get_session_log")
    db.get_engine_attribution(limit=8000)
    db.get_session_log(limit=4000)
    assert raw.hits["get_engine_attribution"] == 1
    assert raw.hits["get_session_log"] == 2


def test_the_counters_report_round_trips_not_calls(pair):
    """The saving has to be visible, not asserted."""
    _, db = pair
    for _ in range(20):
        db.get_engine_attribution(limit=8000)
    s = RC.stats()
    assert s["calls"] == 20
    assert s["fetches"] == 1
    assert s["rows"] > 0


# ══════════════════════════════════════════════════════════════════════
#  key building
# ══════════════════════════════════════════════════════════════════════

def test_the_key_survives_an_unhashable_argument():
    """A caller passing a dict or a DataFrame must not raise on the way in."""
    a = RC._signature(({"a": 1},), {"b": [1, 2]})
    b = RC._signature(({"a": 1},), {"b": [1, 2]})
    assert hash(a) == hash(b)
    assert a != RC._signature(({"a": 2},), {"b": [1, 2]})


@pytest.mark.parametrize("value,empty", [
    (None, True), ([], True), ({}, True), ("", True),
    ([{"a": 1}], False), ({"a": 1}, False), (0, False), (7, False),
])
def test_emptiness_is_judged_the_way_every_reader_returns_it(value, empty):
    """`0` from `count_rows` is a real answer, not an absence."""
    assert RC._empty(value) is empty
