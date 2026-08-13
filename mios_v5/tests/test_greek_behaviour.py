"""🧲 The Greek Behaviour Interpretation Layer.

It must read as an *interpretation* of Greek data the app already computes — not
another engine. So the tests are mostly about what it must NOT do: compute a
Greek, invent a level, emit a trade, or touch the Guardian verdict. The rest pin
the behavioural mapping (positive gamma → CHOP, negative → EXPANSION, charm →
time pressure, vanna → IV/direction only) and the safety rules (missing →
"Not reported", stale flagged).
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import greek_behaviour as GB
from mios_v5.ui import greek_behaviour_panel as GP

_ROOT = pathlib.Path(__file__).resolve().parents[2]
NR = GB.NOT_REPORTED


# ── it is an interpreter, not an engine ────────────────────────────────

def test_it_computes_no_greek_and_owns_no_market_fact():
    """No pricing/Greek math, no producer calls, no data libraries — every number
    arrives as a parameter (rules 1-5)."""
    tree = ast.parse((_ROOT / "mios_v5" / "greek_behaviour.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imported.add((n.module or "").split(".")[0])
    assert not (imported & {"pandas", "numpy", "scipy", "math", "requests",
                            "streamlit", "vob_minimal"})
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    # it must not re-run any existing Greek/dealer producer
    for producer in ("calculate_dealer_gex", "calculate_dealer_dex",
                     "calculate_vanna_charm_exposure", "calculate_greeks",
                     "calculate_vanna_charm", "norm"):
        assert producer not in called, f"{producer} — this must not compute Greeks"
    # nor define its own calculator
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    assert not any(d.startswith("calculate_") or d.endswith("_greeks")
                   for d in defined)


def test_it_never_emits_a_trade_or_touches_the_verdict():
    """No BUY/SELL anywhere, and context_only is always True (rules 6-8)."""
    read = GB.interpret(spot=24460, pull_level=24400, pull_source="max pain",
                        net_charm=-36.2, net_vanna=-120.0, total_gex=180.0,
                        is_expiry=False)
    assert read["context_only"] is True
    blob = repr(read).lower()
    for banned in ("buy", "sell", "verdict", "entry", "exit"):
        assert banned not in blob, f"'{banned}' must not appear in a context read"


# ── gamma: chop vs expansion ───────────────────────────────────────────

def test_positive_gamma_is_chop_pin():
    r = GB.gamma_regime(180.0)
    assert r["regime"] == "CHOP / PIN"
    assert "mean reversion" in r["text"]
    assert GB.gamma_regime(250.0)["strength"] == "strong"


def test_negative_gamma_is_expansion():
    r = GB.gamma_regime(-180.0)
    assert r["regime"] == "EXPANSION"
    assert "reinforce" in r["text"]
    assert GB.gamma_regime(-250.0)["strength"] == "strong"


def test_near_flat_gamma_is_balanced_not_a_forced_call():
    assert GB.gamma_regime(3.0)["regime"] == "BALANCED"


def test_missing_gamma_is_not_reported_never_zero():
    r = GB.gamma_regime(None)
    assert r["regime"] == NR and r["text"] == NR


# ── charm drives time pressure ─────────────────────────────────────────

def test_charm_drives_time_pressure_direction_and_elevation():
    down = GB.time_pressure(-36.2)
    assert down["direction"] == "downward"
    up = GB.time_pressure(40.0)
    assert up["direction"] == "upward"
    # near expiry + large charm → ELEVATED
    hot = GB.time_pressure(-390.9, is_expiry=True)
    assert hot["strength"] == "ELEVATED"
    assert "expiry" in hot["text"]
    # tiny charm is not a material drift
    assert GB.time_pressure(2.0)["strength"] == "low"


def test_missing_charm_time_pressure_is_not_reported():
    assert GB.time_pressure(None)["strength"] == NR


# ── vanna is IV/direction only, never a trade ──────────────────────────

def test_vanna_reads_iv_direction_interaction_only():
    hi = GB.vol_pressure(250.0)
    assert hi["strength"] == "HIGH" and hi["direction"] == "upside"
    lo = GB.vol_pressure(-250.0)
    assert lo["direction"] == "downside"
    assert "IV" in hi["text"] and "reinforce" in hi["text"]
    # weak vanna → LOW, explicitly "unlikely to materially alter"
    weak = GB.vol_pressure(10.0)
    assert weak["strength"] == "LOW" and "unlikely" in weak["text"]
    # never a trade
    assert "buy" not in hi["text"].lower() and "sell" not in hi["text"].lower()


def test_vanna_does_not_set_the_gamma_regime():
    """Vanna belongs to the volatility read; it must not leak into chop/expansion,
    which is gamma's alone."""
    only_vanna = GB.interpret(net_vanna=300.0)
    assert only_vanna["gamma"]["regime"] == NR
    assert only_vanna["vol"]["strength"] == "HIGH"


# ── expansion risk from gamma; positive gamma absorbs ──────────────────

def test_positive_gamma_makes_expansion_risk_low():
    assert GB.expansion_risk(180.0)["level"] == "LOW"
    assert "absorbing" in GB.expansion_risk(180.0)["text"]


def test_negative_gamma_raises_expansion_risk():
    assert GB.expansion_risk(-250.0)["level"] == "HIGH"


# ── pull is a pull, and never invented ─────────────────────────────────

def test_pull_is_a_pull_not_support_or_resistance():
    p = GB.pull(24460, 24400, "max pain", net_charm=-120.0)
    assert p["direction"] == "downward" and "pull" in p["text"]
    assert "support" not in p["text"] and "resistance" not in p["text"]
    assert p["strength"] == "strong"          # |charm| ≥ 100


def test_pull_never_invents_a_level():
    """No level handed in → Not reported, never a fabricated strike (rule 11)."""
    p = GB.pull(24460, None, "max pain", net_charm=-120.0)
    assert p["level"] == NR and p["text"] == NR


# ── higher-order Greeks stay contextual and honest ─────────────────────

def test_missing_greeks_are_not_reported_never_zero():
    r = GB.interpret(total_gex=100.0)          # no contextual greeks handed in
    for g in GB.CONTEXTUAL_GREEKS:
        assert r["greeks"][g] == NR, g
    # zero is a real reading and is kept, not turned into "Not reported"
    assert GB.interpret(vega=0.0)["greeks"]["vega"] == 0.0


def test_contextual_greeks_never_create_direction_or_a_regime():
    """Speed/Color/Zomma/Veta/Vomma/Vega are context — handing them in must not
    change the gamma regime or invent a direction."""
    base = GB.interpret(total_gex=180.0)
    withx = GB.interpret(total_gex=180.0, vomma=999, zomma=999, veta=999,
                         color=999, speed=999, vega=999)
    assert base["gamma"] == withx["gamma"]
    assert base["synthesis"] == withx["synthesis"]


# ── staleness ──────────────────────────────────────────────────────────

def test_stale_data_is_flagged():
    fresh = GB.interpret(total_gex=100.0, as_of=1000.0, now=1000.0 + 10)
    stale = GB.interpret(total_gex=100.0, as_of=1000.0,
                         now=1000.0 + GB.STALE_AFTER_S + 1)
    assert fresh["stale"] is False and stale["stale"] is True
    # no timestamps → cannot tell → not falsely marked stale
    assert GB.interpret(total_gex=100.0)["stale"] is False


# ── synthesis ──────────────────────────────────────────────────────────

def test_synthesis_reads_downward_drift_plus_chop():
    r = GB.interpret(spot=24460, pull_level=24400, net_charm=-36.2,
                     total_gex=180.0)
    assert r["synthesis"] == "DOWNWARD DRIFT + CHOP"


# ── the existing Dealer Magnet stays compatible ────────────────────────

def test_the_dealer_magnet_producer_is_untouched():
    """This layer reuses the magnet; it must not have edited the producer. On
    expiry day dealer_magnet still returns charm_pin's read unchanged."""
    from mios_v5 import charm_pin, dealer_magnet
    cp = charm_pin.read(True, 24460, 24400, -36.2, "max pain")
    dm = dealer_magnet.read(True, 24460, 24400, -36.2, "max pain")
    # dealer_magnet adds labels but keeps every charm_pin fact identical
    for k in ("pin", "distance", "drift", "net_charm", "sentence", "active"):
        assert dm[k] == cp[k], k


# ── the panel ──────────────────────────────────────────────────────────

def test_the_panel_renders_context_only_and_missing_greeks():
    read = GB.interpret(spot=24460, pull_level=24400, pull_source="max pain",
                        net_charm=-36.2, net_vanna=-120.0, total_gex=180.0)
    html = GP.behaviour_html(read)
    assert "Greek behaviour" in html
    assert "Context only" in html and "Guardian" in html
    assert "CHOP / PIN" in html and "DOWNWARD DRIFT + CHOP" in html
    # the unavailable higher-order Greeks are named as Not reported
    assert "Not reported" in html and "Vomma" in html
    # never a trade
    assert "buy" not in html.lower() and "sell" not in html.lower()


def test_the_panel_flags_stale_and_is_empty_when_nothing_to_say():
    stale = GB.interpret(total_gex=100.0, pull_level=24400, spot=24460,
                         net_charm=-30.0, net_vanna=-120.0,
                         as_of=1000.0, now=1000.0 + GB.STALE_AFTER_S + 1)
    assert "STALE" in GP.behaviour_html(stale)
    # an all-absent read draws nothing rather than a permanent empty strip
    assert GP.behaviour_html(GB.interpret()) == ""
    assert GP.behaviour_html(None) == ""


def test_the_panel_adds_no_number_of_its_own():
    """Pure presentation: the panel imports no producer and no data library."""
    tree = ast.parse((_ROOT / "mios_v5" / "ui" / "greek_behaviour_panel.py")
                     .read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[-1])
    assert not ({"pandas", "numpy"} & imported)


# ── the app wiring ─────────────────────────────────────────────────────

def test_the_app_feeds_the_layer_existing_producers_only():
    """vob_minimal builds the strip from `_gex_data`, the market picture's
    `vc_exp` and the ranked magnet — it does not recompute a Greek for it."""
    src = (_ROOT / "vob_minimal.py").read_text()
    assert "greek_behaviour import interpret" in src
    assert "behaviour_html" in src
    # the inputs come from already-published data
    assert "_gex_data" in src and "vc_exp" in src