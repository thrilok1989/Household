"""⚙️ The Adaptive Greeks display — eight lines, four surfaces, one wording.

Two properties matter here beyond "does it draw":

1. **The Guardian line is READ, never produced.** The engine emits no side, so a
   panel that minted its own BUY would undo the whole layer.
2. **All four surfaces say the same thing about one cycle.** The card, the header
   chip, the Market Picture line and the Trade Card line all read one published
   object, so they cannot describe a cycle differently.
"""

import ast
import pathlib

from mios_v5 import adaptive_greeks as AG
from mios_v5.ui import greeks_panel as GP

ROOT = pathlib.Path(__file__).resolve().parents[2]

_OUT = AG.read(
    flow={"regime": "UP", "order_flow": "Bull", "cvd": 1.0},
    doi={"label": "Bullish (PE writers building support)"},
    gex={"total": 153.0, "signal": "Pin", "flip": 24573.0, "magnet": 24650.0},
    dex={"bias": "BULL", "label": "Call-delta heavy"},
    vc={"net_vanna": 12.0, "net_charm": -8.0},
    skew={"ratio": 1.18, "bias": "BEAR", "label": "Put fear"},
    iv_series=[11.8, 12.0, 12.6], spot=24583.8, magnet=24650.0,
    market_picture={"regime": "UP"})


# ── the eight lines ───────────────────────────────────────────────────

def test_the_card_shows_the_eight_readings_the_spec_asks_for():
    html = GP.greeks_card_html(_OUT, "BUY", 72)
    for label in ("Dealer position", "Gamma", "Hedging pressure",
                  "Pin / magnet", "Volatility", "Breakout risk", "Fade risk",
                  "GUARDIAN"):
        assert label in html, label


def test_it_shows_no_raw_greek_numbers():
    """The point of the layer: eight readings, not twenty greeks."""
    html = GP.greeks_card_html(_OUT, "BUY", 72)
    for word in ("Delta", "Vega", "Theta", "net_vanna", "net_charm"):
        assert word not in html, word


def test_risk_words_come_from_two_stated_thresholds():
    assert GP._band(75) == "HIGH"
    assert GP._band(50) == "MEDIUM"
    assert GP._band(20) == "LOW"
    assert GP._band(None) == "—"


def test_nothing_reported_draws_nothing():
    assert GP.greeks_card_html(None) == ""
    assert GP.greeks_card_html({}) == ""
    assert GP.micro(None) == "" and GP.micro({}) == ""
    assert GP.one_line(None) == "" and GP.one_line({}) == ""


def test_nothing_here_raises_on_junk():
    for junk in (None, {}, [], "x", 7, {"dealer": "no", "modifiers": []}):
        GP.greeks_card_html(junk, "BUY", 70)
        GP.micro(junk)
        GP.one_line(junk)


# ── the Guardian line is read, not produced ───────────────────────────

def test_the_guardian_verdict_is_whatever_it_was_handed():
    """⚠️ The engine emits no side. A panel that produced one would undo the
    layer, so the verdict is echoed verbatim — including a HOLD."""
    for word in ("BUY", "SELL", "HOLD", "BLOCKED", "WAIT", "PINNED"):
        assert word in GP.greeks_card_html(_OUT, word, 60)


def test_no_guardian_verdict_means_no_guardian_row():
    """The greeks context is useful on its own. Inventing a verdict to fill the
    row is the one thing this module must not do."""
    html = GP.greeks_card_html(_OUT, None, None)
    assert "GUARDIAN" not in html
    assert "Dealer position" in html


def test_the_panel_never_writes_a_verdict_of_its_own():
    """⚠️ Behaviour, not a source grep — the third time this session I confused
    MATCHING a word with EMITTING one.

    `greeks_card_html` tests `if "BUY" in word` to pick a colour for the verdict
    it was HANDED. Banning the literal would have forced the colour logic to get
    worse. The property that actually matters: hand it nothing, and no verdict
    word reaches the page.
    """
    for handed in (None, "", "   "):
        html = GP.greeks_card_html(_OUT, handed, 70)
        up = html.upper()
        for banned in ("BUY", "SELL", "HOLD", "BLOCKED", "GUARDIAN"):
            assert banned not in up, (banned, handed)
    # and the chip and one-line forms never carry a verdict at all
    for text in (GP.micro(_OUT), GP.one_line(_OUT)):
        up = text.upper()
        for banned in ("BUY", "SELL", "HOLD", "BLOCKED"):
            assert banned not in up, banned


def test_the_card_says_it_is_context_not_a_call():
    html = GP.greeks_card_html(_OUT, "BUY", 72)
    assert "do not make the call" in html


# ── the reason carries the layer's own words ───────────────────────────

def test_the_reason_is_the_conflict_verdict_when_there_is_one():
    """A conflict is the most actionable thing the layer produces, so it leads —
    and it is quoted, never re-worded."""
    html = GP.greeks_card_html(_OUT, "BUY", 72)
    assert _OUT["conflicts"], "fixture stopped producing a conflict"
    assert _OUT["conflicts"][0]["verdict"] in html


def test_missing_layers_are_named():
    thin = AG.read(flow={"regime": "UP"}, spot=24583.8)
    html = GP.greeks_card_html(thin, None, None)
    assert "not reporting" in html


# ── one wording across four surfaces ──────────────────────────────────

def test_the_chip_is_short_and_carries_posture_gamma_and_fade():
    chip = GP.micro(_OUT)
    assert chip.startswith("⚙️")
    assert "dealer" in chip and "γ" in chip and "fade" in chip
    assert len(chip) < 60, "the strip is frozen on every screen"


def test_the_one_line_form_is_plain_text():
    line = GP.one_line(_OUT)
    assert line and "<" not in line and line.endswith(".")


def test_the_one_line_form_names_the_magnet_only_when_it_is_near():
    near = GP.one_line(_OUT)
    assert "magnet" in near
    far = AG.read(flow={"regime": "UP"}, gex={"total": 153.0},
                  spot=24583.8, magnet=30000.0)
    assert "magnet" not in GP.one_line(far)


def test_the_publisher_is_actually_called():
    """⚠️ The hole that let a broken PR ship claiming four surfaces.

    `_adaptive_greeks` was DEFINED and never CALLED: a patch script printed
    success without verifying its replacement matched, and the anchor had moved.
    Nothing published `_adaptive_greeks`, so the header chip, the Market Picture
    line and the Trade Card line all read an absent key and silently drew
    nothing — three surfaces failing in the one way that looks like "no signal".

    Existence tests are not wiring tests. This asserts the call, inside the
    function that owns it.
    """
    import ast
    src = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_nifty_cockpit")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_adaptive_greeks" in called, "the read is never built"
    assert "greeks_card_html" in called, "the card is never drawn"
    assert "_guardian_read" in called, "the Guardian line is never read"


def test_every_surface_reads_the_same_published_object():
    """⚠️ One calculation, published once, four consumers (principle 3). Building
    the read per surface would be four chances to disagree about one cycle."""
    v6 = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    app = (ROOT / "vob_minimal.py").read_text()
    assert '_adaptive_greeks"] = out' in v6, "V6 must publish the read"
    # header chip + Market Picture + Trade Card all READ it
    assert app.count("_adaptive_greeks") >= 3
    for surface in ("greeks_panel import micro", "greeks_panel import one_line"):
        assert surface in app, surface


def test_the_engine_is_built_once_per_cycle_not_per_surface():
    app = (ROOT / "vob_minimal.py").read_text()
    assert "adaptive_greeks import read" not in app, \
        "vob_minimal must READ the published object, not rebuild it"


def test_the_trade_card_keeps_its_own_guard():
    """The card was restored verbatim; the wiring around it is fair game, the
    card's guard is not."""
    app = (ROOT / "vob_minimal.py").read_text()
    body = app[app.index("def render_clean_card("):]
    body = body[:body.index("\ndef ")]
    assert "if not mp or not spot_price:" in body


def test_charm_pin_is_untouched_and_still_owns_the_pin():
    """The user asked for it to stay exactly as it was, and the layer consumes it
    rather than re-deriving the pin."""
    src = (ROOT / "mios_v5" / "charm_pin.py").read_text()
    assert "context_only" in src and "NEAR_POINTS" in src
    assert "adaptive_greeks" not in src, "charm_pin must not depend on the new layer"
