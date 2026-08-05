"""The futures bridge — Stage 71.90 across `TradingContext`, and on screen.

Futures were fetched every cycle and read by a display panel and nothing else.
This is the root that lets a stage see them, so the tests are mostly about two
things: that the root is *additive* (no existing consumer changes), and that
the values arrive with `UNKNOWN` rather than a number whenever the producer
could not report.
"""

import ast
import pathlib

import pytest

from mios_v5 import futures_oi as F
from mios_v5 import trading_context as TC

ROOT = pathlib.Path(__file__).resolve().parents[2]
DASH = ROOT / "mios_v5" / "ui" / "dashboard_v6.py"


def _quote(price=24600.0, oi=1_100_000.0):
    return {"symbol": "NIFTY-Aug2026-FUT", "expiry": "2026-08-27",
            "price": price, "volume": 500000.0, "oi": oi, "basis": 12.0,
            "stance": "Premium"}


def _base():
    return {"trading_day": "2026-08-05", "symbol": "NIFTY-Aug2026-FUT",
            "open_oi": 1_000_000.0, "open_price": 24500.0, "open_basis": 10.0}


def _reading(**kw):
    return F.read(_quote(**kw), _base()).to_dict()


# ══════════════════════════════════════════════════════════════════════
#  the root exists and carries the facts
# ══════════════════════════════════════════════════════════════════════

def test_futures_is_a_root_and_a_group():
    assert "futures" in TC.ROOTS
    assert "futures" in TC.SPEC
    ctx = TC.build(futures=_reading())
    assert "futures" in ctx.GROUPS


def test_every_field_arrives_with_its_owner():
    ctx = TC.build(futures=_reading())
    for name, field in ctx.futures.items():
        assert field.owner and field.owner != TC.UNKNOWN, name
        assert field.source.startswith("futures."), name


def test_the_state_and_the_measurements_cross():
    ctx = TC.build(futures=_reading())
    assert ctx.value("futures.oi_state") == F.LONG_BUILDUP
    assert ctx.value("futures.oi_direction") == F.UP
    assert ctx.value("futures.price_direction") == F.UP
    assert ctx.known("futures.day_oi_pct")
    assert ctx.known("futures.basis")


def test_no_two_fields_read_the_same_path():
    """One fact, one owner — the rule the whole bridge exists for."""
    paths = [path for _o, _s, _r, path in TC.SPEC["futures"].values()]
    assert len(paths) == len(set(paths))


def test_the_field_names_do_not_collide_with_another_group():
    """`futures.price` and `market.*` must stay distinct facts; a duplicate
    dotted path across groups would give one fact two names."""
    seen = {}
    for group, fields in TC.SPEC.items():
        for name, (_o, _s, root, path) in fields.items():
            key = (root, path)
            assert key not in seen, f"{group}.{name} duplicates {seen[key]}"
            seen[key] = f"{group}.{name}"


# ══════════════════════════════════════════════════════════════════════
#  ⛔ additive — nothing that worked before changes
# ══════════════════════════════════════════════════════════════════════

def test_a_context_built_without_futures_still_builds():
    ctx = TC.build()
    assert ctx.futures is not None
    assert not ctx.known("futures.oi_state")
    assert ctx.value("futures.oi_state") == TC.UNKNOWN


def test_the_missing_root_is_named_rather_than_silent():
    ctx = TC.build()
    assert "futures" in dict(ctx.meta)["roots_missing"]
    assert "futures" in dict(TC.build(futures=_reading()).meta)["roots_supplied"]


def test_the_version_moved_because_the_shape_did():
    assert TC.VERSION == "71.95.3"


def test_stage_72_is_unaffected():
    """Adding a root is not a scoring change. Stage 72 stays at 72.1 and its
    weights are untouched — a new weight would be an amendment with its own
    version bump, and there is no evidence yet to justify one."""
    from mios_v5 import entry_engine as EE
    assert EE.VERSION == "72.1"
    assert not any(k.startswith("futures.") for k in EE.WEIGHTS)


# ══════════════════════════════════════════════════════════════════════
#  UNKNOWN, never a number
# ══════════════════════════════════════════════════════════════════════

def test_a_reading_with_no_anchor_crosses_as_unknown():
    """Not as Flat. A context claiming futures were flat when the anchor was
    missing is worse than one that says it could not tell."""
    ctx = TC.build(futures=F.read(_quote(), None).to_dict())
    assert ctx.value("futures.oi_state") == TC.UNKNOWN
    assert ctx.value("futures.day_oi_pct") == TC.UNKNOWN


def test_junk_does_not_raise():
    for junk in (None, {}, {"futures_oi_state": None}, "a string", 42, []):
        ctx = TC.build(futures=junk)
        assert ctx.futures is not None


def test_the_context_stays_immutable():
    ctx = TC.build(futures=_reading())
    with pytest.raises(Exception):
        ctx.futures["oi_state"] = "x"


# ══════════════════════════════════════════════════════════════════════
#  it runs, and it is visible
# ══════════════════════════════════════════════════════════════════════

def test_the_app_passes_futures_into_the_context():
    """The producer already existed and no stage could see it. A root nothing
    populates would leave it exactly as invisible."""
    tree = ast.parse(DASH.read_text())
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_ctx_build")
    assert "futures" in {kw.arg for kw in call.keywords}


def test_the_reading_is_converted_through_to_dict():
    """`to_dict()` is what storage and replay already use, so a replayed
    context reads identically to a live one."""
    tree = ast.parse(DASH.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_futures_reading")
    attrs = {getattr(c.func, "attr", "") for c in ast.walk(fn)
             if isinstance(c, ast.Call)}
    assert "to_dict" in attrs


def test_the_panel_is_rendered():
    """Principle 12: the trader must be able to inspect a value before
    anything weighs it."""
    src = DASH.read_text()
    assert "render_futures" in src
    assert "futures_panel" in src


def test_the_panel_computes_nothing():
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "futures_panel.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"numpy", "pandas", "streamlit", "requests",
                            "futures_oi", "db"})


def test_the_panel_never_shows_zero_for_an_absent_reading():
    """A futures panel showing 0.00% when the quote carried no OI field is the
    one misreading that matters — zero is a plausible answer here."""
    from mios_v5.ui.futures_panel import futures_html
    html = futures_html(F.read(_quote(), None).to_dict())
    assert "0.00%" not in html
    assert "—" in html


def test_short_covering_is_not_coloured_like_a_build_up():
    """A rally on falling open interest is positions closing, not conviction
    arriving; the same green would flatter the weaker of the two."""
    from mios_v5.ui import futures_panel as P
    assert P.STATE_TONE["Short Covering"] != P.STATE_TONE["Long Build-up"]


def test_the_panel_renders_a_stored_reading_like_a_live_one():
    from mios_v5.ui.futures_panel import futures_html
    live = F.read(_quote(), _base())
    assert futures_html(live) == futures_html(live.to_dict())


def test_the_panel_never_raises():
    from mios_v5.ui.futures_panel import futures_html
    assert futures_html(None) == ""
    for junk in ("a string", 42, {}, []):
        futures_html(junk)
