"""📤 The app → `vob_app_state` → Discord bot bridge, end to end.

The bug this file exists to keep fixed: `_PERSIST_KEYS` declared nineteen keys
that "persist to Supabase", `sql/022_vob_app_state.sql` created the table, and
`discord_bot.load_payload()` read the newest row — but **no code anywhere wrote
one**. Every `!picture` answered "not available yet — is the app running?"
while the app was running. A declared connection with no writer in the middle.

So the central test here is not a unit test. It runs the real producer's keys
through the real `snapshot`, through the real `SupabaseDB.save_app_state`, into
a stand-in Supabase, and then out through the **real `discord_bot` functions**,
and asserts a value the app published comes back in the text a user sees.

`discord_bot.py` calls `client.run(TOKEN)` at import and needs `discord`
installed, so its functions are compiled out of the file by AST rather than
imported. That is the actual shipped code, not a copy of it.
"""

from __future__ import annotations

import ast
import json
import math
import pathlib
import types

import pytest

from mios_v5 import app_state as A

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_APP = _ROOT / "vob_minimal.py"
_BOT = _ROOT / "discord_bot.py"
_DB = _ROOT / "db" / "supabase_client.py"


# ── a stand-in Supabase: upsert one row, select it back ─────────────────

class _Res:
    def __init__(self, data):
        self.data = data


class _Table:
    """Enough of postgrest-py for one upsert and one ordered read.

    ⚠️ The upsert `json.dumps`es what it is handed. A payload Postgres would
    reject (NaN, a DataFrame) must fail here, in a test, rather than silently
    at 09:20 with the bot going quiet.
    """

    def __init__(self, store, name):
        self._store, self._name = store, name
        self._op = self._rows = None

    def upsert(self, record, on_conflict=None, returning=None):
        json.dumps(record["payload"])          # JSONB acceptance, for real
        rows = self._store.setdefault(self._name, [])
        rows[:] = [r for r in rows if r.get("id") != record.get("id")]
        rows.append(dict(record))
        self._op = "write"
        return self

    def select(self, cols):
        self._rows = list(self._store.get(self._name, []))
        self._op = "read"
        return self

    def order(self, col, desc=False):
        self._rows.sort(key=lambda r: r.get(col) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _Res(None if self._op == "write" else self._rows)


class _Client:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Table(self.store, name)


def _db_stub(client):
    """The real `save_app_state` bound to a stand-in — no network, no
    constructor, but the shipped method body."""
    from db.supabase_client import SupabaseDB
    stub = types.SimpleNamespace(
        client=client, is_connected=False,
        _WRITE_RETURNING=SupabaseDB._WRITE_RETURNING,
        APP_STATE_ID=SupabaseDB.APP_STATE_ID)
    stub.save_app_state = types.MethodType(SupabaseDB.save_app_state, stub)
    return stub


def _bot(client):
    """`discord_bot`'s real `load_payload` / `fmt_*`, compiled out of the file.

    Importing it is impossible — the module ends in `client.run(TOKEN)` and
    imports `discord` — so the four functions are lifted by AST and given the
    stand-in as their `sb`."""
    tree = ast.parse(_BOT.read_text())
    want = {"load_payload", "fmt_picture", "fmt_bias", "fmt_news"}
    picked = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in want]
    assert {n.name for n in picked} == want, "discord_bot lost a command handler"
    ns = {"sb": client}
    exec(compile(ast.Module(body=picked, type_ignores=[]), "<bot>", "exec"), ns)
    return types.SimpleNamespace(**{n: ns[n] for n in want})


@pytest.fixture
def bridge():
    """producer → save_app_state → vob_app_state → discord_bot."""
    client = _Client()
    return client, _db_stub(client), _bot(client)


# ══ THE END-TO-END TEST ═════════════════════════════════════════════════

def test_a_value_the_app_publishes_reaches_a_discord_command(bridge):
    """⭐ The whole point. A Market Picture written to session state must come
    back out of `!picture` — through the snapshot, the row and the bot."""
    client, db, bot = bridge
    session = {
        "_market_picture": {
            "regime": "UP", "p_up": 62, "p_down": 21, "p_side": 17,
            "sup": {"price": 24100.0, "src_count": 4},
            "res": {"price": 24380.0, "src_count": 3},
            "playbook": "Buy dips to 24,100",
        },
        "_leg_bias_summary": {
            "label": "Bullish", "bull": 9, "bear": 5, "net": 4, "spot": 24233.4,
            "as_of": "13:45",
            "speed": {"fast": {"label": "Bull", "net": 3},
                      "lag": {"label": "Bull", "net": 1},
                      "mis": {"label": "Neutral", "net": 0}},
        },
        "_news_bias": {
            "label": "Bullish", "net": 2, "n": 7, "as_of": "13:44",
            "rows": [{"em": "🟢", "age_min": 12, "title": "RBI holds rates"}],
        },
        "_not_a_persist_key": "should not travel",
    }

    payload = A.snapshot(session, _persist_keys())
    assert db.save_app_state(payload) is True

    assert client.store["vob_app_state"], "nothing was written to the table"

    got = bot.load_payload()
    assert got, "the bot read an empty payload — the bridge is broken again"

    picture = bot.fmt_picture(got.get("_market_picture"))
    assert "is the app running?" not in picture
    assert "MARKET PICTURE: UP" in picture
    assert "Buy dips to 24,100" in picture
    assert "24100" in picture

    assert "Bullish" in bot.fmt_bias(got.get("_leg_bias_summary"))
    assert "24233" in bot.fmt_bias(got.get("_leg_bias_summary"))
    assert "RBI holds rates" in bot.fmt_news(got.get("_news_bias"))

    assert "_not_a_persist_key" not in got


def test_the_bot_still_says_not_available_when_the_app_never_published(bridge):
    """The honest empty case — no row means no answer, not a fabricated one."""
    _, _, bot = bridge
    assert bot.load_payload() == {}
    assert "is the app running?" in bot.fmt_picture({})


def test_a_second_cycle_overwrites_rather_than_appends(bridge):
    """One row per client id — `sql/022` keys on `id`, and the bot reads
    `limit(1)`. Appending would leave `!picture` reading a stale row."""
    client, db, bot = bridge
    db.save_app_state(A.snapshot({"_market_picture": {"regime": "UP"}},
                                 ("_market_picture",)))
    db.save_app_state(A.snapshot({"_market_picture": {"regime": "DOWN"}},
                                 ("_market_picture",)))
    assert len(client.store["vob_app_state"]) == 1
    assert bot.load_payload()["_market_picture"]["regime"] == "DOWN"


def test_a_numpy_flavoured_session_still_reaches_the_bot(bridge):
    """Real session values are rarely plain floats — the spot price arrives as
    `np.float64` more often than not, and JSONB rejects it."""
    np = pytest.importorskip("numpy")
    _, db, bot = bridge
    payload = A.snapshot(
        {"_leg_bias_summary": {"label": "Bullish", "spot": np.float64(24233.4),
                               "net": np.int64(4)}},
        ("_leg_bias_summary",))
    assert db.save_app_state(payload) is True
    assert "24233" in bot.fmt_bias(bot.load_payload()["_leg_bias_summary"])


# ── the payload: JSON-safety ────────────────────────────────────────────

def test_a_nan_does_not_poison_the_whole_write():
    """⚠️ `json.dumps` emits a bare `NaN`, which is not JSON and which Postgres
    rejects — one stray NaN would drop the entire payload, not just its key."""
    out = A.json_safe({"spot": float("nan"), "regime": "UP"})
    assert out["spot"] is None and out["regime"] == "UP"
    json.dumps(out)


def test_infinities_go_the_same_way():
    assert A.json_safe(math.inf) is None and A.json_safe(-math.inf) is None


def test_timestamps_become_readable_strings():
    import datetime as dt
    assert A.json_safe(dt.date(2026, 8, 31)) == "2026-08-31"
    assert A.json_safe(dt.datetime(2026, 8, 31, 13, 45)).startswith("2026-08-31T13:45")


def test_something_unrepresentable_becomes_none_not_its_repr():
    """⚠️ `str(value)` would send `"<DataFrame object at 0x7f…>"` all the way to
    a Discord message, where it would read as data."""
    class Weird:
        pass
    assert A.json_safe(Weird()) is None


def test_nesting_survives_and_tuples_become_lists():
    out = A.json_safe({"speed": {"fast": ("Bull", 3)}})
    assert out == {"speed": {"fast": ["Bull", 3]}}
    json.dumps(out)


def test_a_cycle_terminates_instead_of_recursing_forever():
    d = {}
    d["self"] = d
    json.dumps(A.json_safe(d))  # would not return at all without the depth cap


# ── the payload: what it does and does not carry ────────────────────────

def test_a_key_with_no_producer_is_omitted_not_written_as_null():
    """⚠️ Fifteen of the nineteen `_PERSIST_KEYS` have no producer today. A
    payload listing them all as null claims a producer for each."""
    out = A.snapshot({"_market_picture": {"regime": "UP"}},
                     ("_market_picture", "_discord_outbox", "_spike_score"))
    assert set(out) == {"_market_picture"}


def test_a_key_that_raises_on_lookup_is_skipped_not_fatal():
    class Hostile(dict):
        def __getitem__(self, k):
            raise RuntimeError("session went away")
    h = Hostile({"_market_picture": 1, "_news_bias": 2})
    assert A.snapshot(h, ("_market_picture", "_news_bias")) == {}


def test_no_state_yields_no_payload():
    assert A.snapshot(None, ("_market_picture",)) == {}
    assert A.snapshot({}, ("_market_picture",)) == {}


# ── the schedule ────────────────────────────────────────────────────────

def test_the_first_cycle_publishes():
    assert A.due(None, now=1000.0) is True


def test_a_recent_push_does_not_publish_again():
    assert A.due(1000.0, now=1010.0) is False
    assert A.due(1000.0, now=1060.0) is True


def test_a_backwards_clock_costs_one_write_not_a_silent_bot():
    assert A.due(9_000.0, now=1000.0) is True


def test_junk_stamps_publish_rather_than_block():
    for bad in ("soon", object(), float("nan")):
        assert A.due(bad, now=1000.0) is True


# ── the writer's contract ───────────────────────────────────────────────

def _db_fn(name):
    for n in ast.walk(ast.parse(_DB.read_text())):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found in supabase_client.py")


def test_the_write_is_an_upsert_on_id_not_an_insert():
    """`sql/022` is one row per client id; inserting would grow a table
    `db/retention.py` protects from purging precisely because it does not."""
    src = ast.unparse(_db_fn("save_app_state"))
    assert "'vob_app_state'" in src
    assert ".upsert(" in src and ".insert(" not in src
    assert "on_conflict='id'" in src


def test_the_write_does_not_pay_for_the_echo():
    """The egress rule: PostgREST echoes the written row and Supabase bills it.
    Nothing here reads the response."""
    assert "_WRITE_RETURNING" in ast.unparse(_db_fn("save_app_state"))


def test_the_write_reports_whether_it_landed():
    """A swallowed exception that returns None reads as success at the call
    site — which is how this connection stayed dead for so long."""
    fn = _db_fn("save_app_state")
    returns = {ast.unparse(n.value) for n in ast.walk(fn)
               if isinstance(n, ast.Return) and n.value is not None}
    assert "True" in returns and "False" in returns


def test_an_empty_payload_is_not_written(bridge):
    """A cycle before the engines have produced anything must not overwrite a
    good row with nothing."""
    client, db, _ = bridge
    assert db.save_app_state({}) is False
    assert db.save_app_state(None) is False
    assert "vob_app_state" not in client.store


def test_a_refusing_supabase_is_reported_not_raised():
    class Boom:
        def table(self, _):
            raise RuntimeError("PGRST205")
    assert _db_stub(Boom()).save_app_state({"_market_picture": {}}) is False


# ── the wiring in the app ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_src() -> str:
    return _APP.read_text()


def _persist_keys():
    """The real `_PERSIST_KEYS` tuple, read out of the app without importing
    it — `vob_minimal` boots Streamlit at import."""
    for n in ast.walk(ast.parse(_APP.read_text())):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and getattr(n.targets[0], "id", "") == "_PERSIST_KEYS"):
            return ast.literal_eval(n.value)
    raise AssertionError("_PERSIST_KEYS not found")


def test_the_keys_the_bot_reads_are_actually_in_the_list():
    """The three the commands answer from. Drop one and `!bias` goes quiet with
    no error anywhere."""
    keys = _persist_keys()
    for k in ("_market_picture", "_leg_bias_summary", "_news_bias"):
        assert k in keys


def _call_sites(src: str, name: str):
    """⚠️ Offsets of CALLS, not the `def` line — which also contains
    `name()` and would otherwise let a deleted call keep passing."""
    import re
    return [m.start() for m in re.finditer(rf"(?<!def ){re.escape(name)}\(\)", src)]


def test_the_publisher_is_wired_into_the_cycle(app_src: str):
    assert _call_sites(app_src, "_publish_app_state"), \
        "defined but never called — exactly the shape of the bug being fixed"


def test_it_publishes_after_the_market_picture_is_written(app_src: str):
    """A snapshot taken before `compute_market_picture` runs carries the
    previous cycle's regime — right shape, stale content."""
    assert app_src.index("'_market_picture'] = mp") < max(
        _call_sites(app_src, "_publish_app_state"))


def _app_fn(name):
    for n in ast.walk(ast.parse(_APP.read_text())):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found")


def test_it_stamps_the_attempt_not_the_success():
    """⚠️ The `compute_news_bias` lesson: stamping only on success turned a
    cadence gate into no gate at all, and Google News was fetched four times a
    render. A Supabase refusing writes must not be retried every 20 seconds."""
    src = ast.unparse(_app_fn("_publish_app_state"))
    assert src.index("'_app_state_last_push'] = _now") < src.index("save_app_state")


def test_it_is_throttled_rather_than_written_every_cycle():
    src = ast.unparse(_app_fn("_publish_app_state"))
    assert "_as.due(" in src


def test_it_uses_the_declared_key_list_not_its_own():
    """Two lists of what persists is how one of them goes stale."""
    assert "_PERSIST_KEYS" in ast.unparse(_app_fn("_publish_app_state"))


def test_publishing_cannot_break_the_cycle_that_runs_it():
    fn = _app_fn("_publish_app_state")
    assert any(isinstance(n, ast.Try) for n in ast.walk(fn))


# ── purity ──────────────────────────────────────────────────────────────

def test_the_module_is_pure():
    tree = ast.parse((_ROOT / "mios_v5" / "app_state.py").read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "supabase", "pandas", "db"}
    # ⚠️ CODE only — the docstring names `st.session_state` to explain what the
    # bot cannot see, and would otherwise match.
    assert not any(isinstance(n, ast.Attribute) and n.attr == "session_state"
                   for n in ast.walk(tree))
