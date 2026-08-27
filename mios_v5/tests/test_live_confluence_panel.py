"""🔭 The Live Confluence card: formats a verdict already reached by
`mios_v5.live_confluence.assess` — it must never compute one itself."""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import live_confluence as LC
from mios_v5.ui import live_confluence_panel as P

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _bull_model():
    return LC.assess(zone="SUPPORT", level=24000, call_total=8000, put_total=2000,
                     call_vob_role="support", put_vob_role="resistance",
                     call_energy_state="building", put_energy_state="unwinding",
                     global_score=3, sector_bull=8, sector_bear=1, news_score=3,
                     regime="UP", war_zone_winner="Buyers",
                     call_spiking=True, put_spiking=False)


def test_no_model_draws_nothing():
    assert P.card_html(None) == ""
    assert P.card_html({}) == ""


def test_bullish_and_bearish_get_their_own_tone():
    bull = P.card_html(_bull_model(), spot=24000)
    assert "BULLISH CONFLUENCE" in bull
    bear_model = LC.assess(zone="RESISTANCE", level=24100, call_total=2000, put_total=8000,
                           call_vob_role="resistance", put_vob_role="support",
                           regime="DOWN")
    bear = P.card_html(bear_model, spot=24100)
    assert "BEARISH CONFLUENCE" in bear


def test_mixed_shows_both_sides_not_one():
    mixed = LC.assess(zone="SUPPORT", level=24000, regime="DOWN")
    html = P.card_html(mixed, spot=24000)
    assert "MIXED CONFLUENCE" in html
    assert "Bullish:" in html and "Bearish:" in html


def test_pinned_shows_no_directional_edge_not_a_vote_tally():
    pinned = LC.assess(pinned=True, pin_level=24000)
    html = P.card_html(pinned, spot=24000)
    assert "PINNED" in html
    assert "no directional edge" in html
    assert "bull /" not in html   # no vote-count line for a pin


def test_call_and_put_boxes_show_volume_ltp_and_energy():
    html = P.card_html(_bull_model(), spot=24000, call_ltp=138, put_ltp=112,
                       call_label="ATM CE 24600", put_label="ATM PE 24600")
    assert "ATM CE 24600" in html and "ATM PE 24600" in html
    assert "₹138.0" in html and "₹112.0" in html
    assert "HIGH" in html   # call_spiking=True in _bull_model


def test_context_chips_are_drawn_for_global_sector_news_regime():
    html = P.card_html(_bull_model(), spot=24000)
    assert "Global" in html and "Sector" in html and "News" in html
    assert "Regime" in html


def test_the_war_zone_chip_is_drawn():
    html = P.card_html(_bull_model(), spot=24000)
    assert "War Zone" in html


# ── regression: theme.BULL/BEAR (hex colours) must never be compared
# against a vote's `bias` field (the strings "bull"/"bear" bias_ball
# writes) — a same-name shadow silently made every chip render neutral
# and every evidence list render empty, even for a unanimous verdict.

def test_bullish_evidence_is_actually_listed_not_empty():
    html = P.card_html(_bull_model(), spot=24000)
    assert "At Support" in html   # one of the 11 bullish vote labels
    assert "Bullish: —" not in html


def test_bearish_evidence_is_actually_listed_not_empty():
    bear_model = LC.assess(zone="RESISTANCE", level=24100, call_total=2000, put_total=8000,
                           call_vob_role="resistance", put_vob_role="support",
                           regime="DOWN")
    html = P.card_html(bear_model, spot=24100)
    assert "At Resistance" in html


def test_context_chips_show_a_coloured_dot_not_always_neutral():
    html = P.card_html(_bull_model(), spot=24000)
    assert "🟢 Global" in html
    assert "🟢 War Zone" in html
    assert "🟢 Sector" in html
    assert "🟢 Market Regime" in html


def test_the_disclaimer_is_always_present():
    html = P.card_html(_bull_model(), spot=24000)
    assert "does not generate a trade signal" in html


def test_missing_prices_show_a_dash():
    html = P.card_html(_bull_model())
    assert "—" in html


def test_the_html_escapes_a_hostile_label():
    html = P.card_html(_bull_model(), call_label="<script>x</script>")
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "ui" / "live_confluence_panel.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas", "live_confluence"}
    assert "session_state" not in src


def test_nothing_is_computed_here():
    src = (_ROOT / "mios_v5" / "ui" / "live_confluence_panel.py").read_text()
    tree = ast.parse(src)
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    assert not {"assess", "leg_location", "leg_energy", "spot_location"} & called
