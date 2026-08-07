"""`db/egress_guard.py` — a spending limit the app enforces on itself.

Two properties, and the second matters more than the first.

**It must refuse.** A budget that never says no is a meter with extra steps.

**It must never refuse the wrong thing.** The rule, from the guard's own
docstring and from `docs/AUDIT_FOCUS_MODE.md` before it:

    The budget may suppress analytics. It may not suppress the reads MIOS
    state, the decision stages, or Telegram alerts depend on.

A trader who sets the budget to zero loses the learning tabs. They must not
lose their signals. Most of what is below is that assertion from several
angles, because it is the one this repo has broken before.
"""

import importlib.util
import pathlib

import pytest


def _load(name, rel):
    root = pathlib.Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(name, root / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: `db/__init__.py` imports `supabase`, which is not installed here, so both
#: modules are loaded from their paths — the approach `test_read_cache` and
#: `test_dispatch_registry` already use.
EG = _load("_egress_guard_under_test", "db/egress_guard.py")
RC = _load("_read_cache_for_guard", "db/read_cache.py")

MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _clean():
    EG.reset()
    EG.set_budget_mb(EG.DEFAULT_BUDGET_MB)
    EG.pin_mode(None)
    RC.invalidate()
    RC.reset_stats()
    yield
    EG.reset()
    EG.pin_mode(None)
    RC.invalidate()


def _spend_fraction(f):
    """Burn `f` of the budget."""
    EG.spend("get_engine_attribution", int(EG.state()["budget_mb"] * MB * f))


# ══════════════════════════════════════════════════════════════════════
#  ⭐ the rule: what may never be refused
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method", EG.PROTECTED)
def test_a_decision_critical_read_is_never_refused(method):
    """At zero budget, pinned shut, with the meter blown — it still passes."""
    EG.set_budget_mb(0)
    EG.pin_mode(EG.CACHE_ONLY)
    _spend_fraction(5.0)
    ok, _ = EG.allow(method)
    assert ok, f"{method} was throttled — that is a silent alert outage"


def test_the_protected_check_happens_before_the_budget_is_consulted():
    """Ordering, not coincidence. If the mode were read first, a later edit
    that reordered the branches would take the alert chain down."""
    import inspect
    src = inspect.getsource(EG.allow)
    assert src.index("PROTECTED") < src.index("mode()")


def test_nothing_on_the_decision_path_is_in_the_analytics_set():
    """FRUGAL drops `ANALYTICS` wholesale, so an overlap would mean the first
    tightening step silently cost a signal."""
    assert not (set(EG.PROTECTED) & set(EG.ANALYTICS))


def test_the_protected_set_is_short_enough_to_read():
    """Every name here can never be throttled, so adding one is a decision to
    spend. It should stay small enough that adding one is noticed."""
    assert len(EG.PROTECTED) <= 12


def test_the_live_reads_are_all_protected():
    """`read_cache` already calls these decision-critical. The two files must
    not disagree about which reads those are."""
    assert set(RC._LIVE_READS) <= set(EG.PROTECTED)


# ══════════════════════════════════════════════════════════════════════
#  it does refuse
# ══════════════════════════════════════════════════════════════════════

def test_everything_reads_while_there_is_budget_left():
    assert EG.mode() == EG.NORMAL
    assert EG.allow("get_engine_attribution")[0]


def test_history_pauses_once_the_budget_is_mostly_gone():
    _spend_fraction(EG.AUTO_FRUGAL_AT + 0.01)
    assert EG.mode() == EG.FRUGAL
    assert not EG.allow("get_engine_attribution")[0]


def test_a_read_outside_the_analytics_set_survives_frugal():
    """FRUGAL is targeted, not a blanket stop — it drops the heaviest queries,
    which is what makes it worth having a step before CACHE_ONLY at all."""
    _spend_fraction(EG.AUTO_FRUGAL_AT + 0.01)
    assert EG.allow("get_market_stories")[0]


def test_everything_but_the_protected_stops_at_the_budget():
    _spend_fraction(1.0)
    assert EG.mode() == EG.CACHE_ONLY
    assert not EG.allow("get_market_stories")[0]
    assert EG.allow("get_latest_spot")[0]


def test_a_zero_budget_means_protected_reads_only():
    EG.set_budget_mb(0)
    assert EG.mode() == EG.CACHE_ONLY
    assert not EG.allow("get_session_log")[0]
    assert EG.allow("get_active_trade")[0]


def test_a_refusal_says_why():
    _spend_fraction(1.0)
    ok, why = EG.allow("get_session_log")
    assert not ok and why


# ══════════════════════════════════════════════════════════════════════
#  the pin
# ══════════════════════════════════════════════════════════════════════

def test_a_pin_can_tighten_beyond_what_the_spend_would_choose():
    EG.pin_mode(EG.CACHE_ONLY)
    assert EG.mode() == EG.CACHE_ONLY
    assert not EG.allow("get_market_stories")[0]


def test_a_pin_cannot_loosen_past_the_budget():
    """⭐ A control that quietly disables itself is worse than no control.

    Pinning NORMAL with the budget spent would let the cap be switched off by
    the same widget that exists to enforce it.
    """
    _spend_fraction(1.0)
    EG.pin_mode(EG.NORMAL)
    assert EG.mode() == EG.CACHE_ONLY


def test_clearing_the_pin_returns_to_what_the_spend_earned():
    EG.pin_mode(EG.CACHE_ONLY)
    EG.pin_mode(None)
    assert EG.mode() == EG.NORMAL


def test_an_unknown_pin_is_ignored_rather_than_obeyed():
    EG.pin_mode("OFF-ISH")
    assert EG.state()["pinned"] is None
    assert EG.mode() == EG.NORMAL


# ══════════════════════════════════════════════════════════════════════
#  ⚠️ a blocked read is never silent
# ══════════════════════════════════════════════════════════════════════

def test_a_refusal_is_recorded_by_name():
    """A blank panel from a refused query looks identical to a blank panel from
    an empty table. Acting on the wrong one of those is how a trader ends up
    mistrusting a working screen."""
    EG.note_blocked("get_session_log", "cache-only")
    EG.note_blocked("get_session_log", "cache-only")
    assert EG.state()["blocked"]["get_session_log"]["count"] == 2


def test_the_blocked_line_names_the_panels_and_the_reason():
    EG.note_blocked("get_engine_attribution", "frugal — history paused")
    line = EG.blocked_line()
    assert "get_engine_attribution" in line
    assert "frugal" in line
    assert "not because the table is empty" in line


def test_the_blocked_line_is_silent_when_nothing_was_refused():
    assert EG.blocked_line() == ""


# ══════════════════════════════════════════════════════════════════════
#  the meter
# ══════════════════════════════════════════════════════════════════════

def test_a_dataframe_is_measured_without_being_serialised():
    """`to_json` on eight thousand rows every cycle would cost more than the
    read it is measuring."""
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"a": range(500), "b": ["x" * 20] * 500})
    assert EG.measure(df) > 0


@pytest.mark.parametrize("value,positive", [
    ([{"a": 1}, {"a": 2}], True), ({"a": 1}, True), ("text", True),
    (None, False), ([], False),
])
def test_every_shape_a_read_returns_can_be_measured(value, positive):
    got = EG.measure(value)
    assert got >= 0
    assert (got > 2) is positive


def test_spending_is_attributed_so_the_biggest_read_is_findable():
    EG.spend("get_session_log", 900)
    EG.spend("get_session_log", 100)
    EG.spend("get_market_stories", 50)
    top = EG.top_methods()
    assert top[0]["method"] == "get_session_log"
    assert top[0]["bytes"] == 1000 and top[0]["reads"] == 2


def test_resetting_keeps_the_settings_and_clears_the_ledger():
    """The button is "reset the meter", not "reset my configuration"."""
    EG.set_budget_mb(123)
    EG.pin_mode(EG.FRUGAL)
    EG.spend("get_session_log", 5000)
    EG.note_blocked("get_trade_events", "frugal")
    EG.reset()
    s = EG.state()
    assert s["budget_mb"] == 123 and s["pinned"] == EG.FRUGAL
    assert s["used_mb"] == 0 and s["reads"] == 0 and not s["blocked"]


# ══════════════════════════════════════════════════════════════════════
#  wired into the read path
# ══════════════════════════════════════════════════════════════════════

class FakeDB:
    is_connected = True

    def __init__(self):
        self.hits = {}

    def _hit(self, n):
        self.hits[n] = self.hits.get(n, 0) + 1

    def get_engine_attribution(self, limit=8000):
        self._hit("get_engine_attribution")
        return [{"engine": i} for i in range(10)]

    def get_active_trade(self):
        self._hit("get_active_trade")
        return {"id": 1}


@pytest.fixture
def pair():
    raw = FakeDB()
    return raw, RC.wrap(raw)


def test_a_refused_read_never_reaches_supabase(pair):
    raw, db = pair
    EG.set_budget_mb(0)
    assert db.get_engine_attribution(limit=8000) is None
    assert "get_engine_attribution" not in raw.hits


def test_a_refused_read_returns_none_rather_than_raising(pair):
    """Every consumer in this app already handles `None` — the "did not report"
    path exists in all of them. An exception reaching a panel would take the
    screen down over a budget."""
    _, db = pair
    EG.set_budget_mb(0)
    assert db.get_engine_attribution() is None


def test_the_protected_read_still_goes_through_the_wrapper(pair):
    raw, db = pair
    EG.set_budget_mb(0)
    assert db.get_active_trade() == {"id": 1}
    assert raw.hits["get_active_trade"] == 1


def test_a_refusal_is_not_cached_so_raising_the_budget_works_at_once(pair):
    """⭐ Why the refusal is an exception and not an empty return.

    Streamlit stores nothing when a cached function raises. Returning an empty
    would have cached the refusal, and the panel would have stayed blank after
    the trader raised the budget — a control that appears not to work.
    """
    raw, db = pair
    EG.set_budget_mb(0)
    assert db.get_engine_attribution(limit=8000) is None
    EG.set_budget_mb(500)
    assert db.get_engine_attribution(limit=8000) == [{"engine": i}
                                                     for i in range(10)]
    assert raw.hits["get_engine_attribution"] == 1


def test_a_cache_hit_is_never_charged(pair):
    """The budget must only ever be asked about a read that was about to cost
    something — otherwise a well-cached session would throttle itself."""
    raw, db = pair
    for _ in range(50):
        db.get_engine_attribution(limit=8000)
    assert raw.hits["get_engine_attribution"] == 1
    assert EG.state()["reads"] == 1


def test_the_meter_charges_what_the_read_returned(pair):
    _, db = pair
    db.get_engine_attribution(limit=8000)
    assert EG.state()["reads"] == 1
    assert EG.top_methods()[0]["method"] == "get_engine_attribution"


def test_the_guard_missing_does_not_stop_the_app_reading(pair, monkeypatch):
    """A budget that could cause an outage by failing to import would be worse
    than the bill it caps."""
    raw, db = pair
    monkeypatch.setattr(RC, "_guard", lambda: None)
    assert db.get_engine_attribution(limit=8000)
    assert raw.hits["get_engine_attribution"] == 1


# ══════════════════════════════════════════════════════════════════════
#  what the sidebar renders
# ══════════════════════════════════════════════════════════════════════

def test_the_summary_names_the_mode_and_the_spend():
    EG.spend("get_session_log", 2 * MB)
    line = EG.summary_line()
    assert "NORMAL" in line and "2.0" in line and "50" in line


def test_the_summary_says_so_when_there_is_no_budget():
    EG.set_budget_mb(0)
    assert "protected reads only" in EG.summary_line()


def test_the_state_needs_no_arithmetic_from_the_panel():
    EG.spend("get_session_log", 5 * MB)
    s = EG.state()
    assert set(s) >= {"mode", "pinned", "budget_mb", "used_mb", "used_pct",
                      "reads", "blocked", "top", "minutes"}
    assert s["used_pct"] == pytest.approx(10.0, abs=0.2)


@pytest.mark.parametrize("n,text", [(512, "512 B"), (2048, "2.0 KB"),
                                    (5 * MB, "5.0 MB")])
def test_sizes_read_as_sizes(n, text):
    assert EG.human(n) == text
