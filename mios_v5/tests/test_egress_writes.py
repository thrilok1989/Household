"""Egress: a write must not pay to receive a copy of itself.

PostgREST echoes every written row back unless told otherwise, and Supabase
bills that echo. `docs/AUDIT_EGRESS_2.md` found 29 of 30 write methods
discarding a response they were paying for — including the whole option chain,
every cycle, all session.

These are structural tests against the parse tree. There is no Supabase here to
measure bytes against, but "did the author remember `returning='minimal'`" is
exactly the kind of thing a test can hold.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "db" / "supabase_client.py"

#: The one write that genuinely needs its row back: it reads `.data` for the
#: id the database generated. Listed by name so adding a second exception is a
#: deliberate edit rather than a silent drift.
_MAY_ECHO = {"upsert_auto_trade"}


def _write_methods():
    src = SRC.read_text()
    lines = src.splitlines()
    cls = next(n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.ClassDef) and n.name == "SupabaseDB")
    for fn in cls.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        body = "\n".join(lines[fn.lineno - 1:(fn.end_lineno or fn.lineno)])
        if ".insert(" in body or ".upsert(" in body:
            yield fn.name, body


def test_every_write_that_discards_its_response_asks_for_minimal():
    """⭐ The fix, held in place."""
    echoing = [name for name, body in _write_methods()
               if "returning" not in body and name not in _MAY_ECHO]
    assert not echoing, (
        "these writes still pay for an echo nobody reads: " + ", ".join(echoing))


def test_the_central_upsert_helper_is_minimal():
    """Nineteen write paths route through `_safe_upsert`, including
    `save_option_chain`. It is the single highest-value line in the file."""
    body = dict(_write_methods())["_safe_upsert"]
    assert "returning=" in body


def test_the_one_exception_is_the_one_that_reads_the_row():
    """A write may echo only when something actually consumes the echo."""
    bodies = dict(_write_methods())
    for name in _MAY_ECHO:
        assert name in bodies, f"{name} no longer exists — drop the exemption"
        assert ".data" in bodies[name], (
            f"{name} no longer reads its response, so it should be minimal too")


def test_the_day_list_does_not_scan_the_table():
    """`get_leg_flow_days` pulled 15,000 rows to derive at most thirty values
    from a table written many times a minute and kept for sixty days."""
    src = SRC.read_text()
    lines = src.splitlines()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "get_leg_flow_days")
    body = "\n".join(lines[fn.lineno - 1:(fn.end_lineno or fn.lineno)])
    assert "15000" not in body
    # it must stop early rather than page forever
    assert "break" in body or "while" in body
