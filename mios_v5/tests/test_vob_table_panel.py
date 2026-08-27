"""📦 The VOB zone buy/sell tabulation, below the terminal chart.

`analyze_vob_volume` has computed `buy_vol` / `sell_vol` / `bull_pct` WITHIN each
zone's own price window every cycle, for zones already drawn as coloured
rectangles on the CALL/PUT chart panels. Only the status colour reached the
screen; the percentage that produced it never did. Same class of gap as the
ATM±1 leg tabulation and the FII/DII row: computed, published, drawn nowhere.
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5.ui import vob_table_panel as V

_ROOT = pathlib.Path(__file__).resolve().parents[2]


#: A zone in exactly the shape `analyze_vob_volume` emits — vob_minimal.py:7163.
def _zone(zone_type="bullish", lower=118.5, upper=124.0, status="BUILDING",
         dominant="buyers", bull_pct=70.0, buy_vol=42000.0, sell_vol=18000.0,
         **over):
    mid = (lower + upper) / 2 if lower is not None and upper is not None else None
    z = {
        "zone_type": zone_type, "role": ("support" if zone_type == "bullish"
                                         else "resistance"),
        "lower": lower, "upper": upper, "mid": mid,
        "status": status, "dominant": dominant,
        "buy_vol": buy_vol, "sell_vol": sell_vol,
        "total_vol": buy_vol + sell_vol, "bull_pct": bull_pct,
        "max_buy_price": None, "max_sell_price": None, "n_bars_in_zone": 12,
    }
    z.update(over)
    return z


# ══════════════════════════════════════════════════════════════════════
#  rows_for
# ══════════════════════════════════════════════════════════════════════

def test_call_zones_come_before_put_zones():
    rows = V.rows_for([_zone()], [_zone(zone_type="bearish", lower=95, upper=99)],
                      call_label="ATM CE 24600", put_label="ATM PE 24600")
    assert [r["leg"] for r in rows] == ["ATM CE 24600", "ATM PE 24600"]


def test_the_buy_sell_split_is_read_not_recomputed():
    """The number requested: the split WITHIN the zone's own window, exactly as
    `analyze_vob_volume` computed it — not the zone's share of total volume."""
    rows = V.rows_for([_zone(bull_pct=63.5)], None)
    assert rows[0]["buy_pct"] == 63.5
    assert rows[0]["sell_pct"] == 36.5


def test_a_missing_split_stays_missing_not_fifty_fifty():
    """A 50/50 bar would claim a balanced read that is not what 'not computed'
    means."""
    rows = V.rows_for([_zone(bull_pct=None)], None)
    assert rows[0]["buy_pct"] is None and rows[0]["sell_pct"] is None


def test_role_wins_over_zone_type_when_both_are_present():
    """`analyze_vob_volume` writes both `role` and `zone_type` and they always
    agree — `role` is read first because it is the one already in plain English."""
    rows = V.rows_for([_zone(zone_type="bullish", role="support")], None)
    assert rows[0]["word"] == "Support"


def test_bullish_is_support_and_bearish_is_resistance():
    rows = V.rows_for([_zone(zone_type="bullish")],
                      [_zone(zone_type="bearish")])
    assert rows[0]["word"] == "Support" and rows[0]["icon"] == "🛡"
    assert rows[1]["word"] == "Resistance" and rows[1]["icon"] == "🧱"


def test_an_unreadable_range_is_skipped():
    """`analyze_vob_volume` guarantees lower < upper; this only guards a
    malformed caller rather than drawing a zero-height zone."""
    rows = V.rows_for([_zone(lower=None), _zone(lower=100, upper=100),
                       _zone(lower=110, upper=90)], None)
    assert rows == []


def test_junk_zones_are_skipped_not_raised_on():
    rows = V.rows_for([None, "x", 7, _zone()], None)
    assert len(rows) == 1


def test_no_zones_is_an_empty_list_not_none():
    assert V.rows_for(None, None) == []
    assert V.rows_for([], []) == []


# ══════════════════════════════════════════════════════════════════════
#  table_html
# ══════════════════════════════════════════════════════════════════════

def test_empty_rows_draw_no_table_shell():
    assert V.table_html([]) == ""
    assert V.table_html(None) == ""
    assert V.table_html("not a list") == ""


def test_a_known_row_carries_leg_range_and_percentages():
    rows = V.rows_for([_zone(lower=118.5, upper=124.0, bull_pct=70.0)], None,
                      call_label="ATM CE 24600")
    html = V.table_html(rows)
    assert "ATM CE 24600" in html
    assert "118.5" in html and "124.0" in html
    assert "70% / 30%" in html


def test_a_missing_split_shows_a_dash_not_a_bar():
    rows = V.rows_for([_zone(bull_pct=None)], None)
    html = V.table_html(rows)
    assert "—" in html
    # no split-bar div was drawn for this row
    assert "flex:0 0" not in html


def test_status_glyphs_match_the_leg_tabulations_own_convention():
    """Same glyph set as `build_leg_bias_table._stat_em`, so one zone reads
    identically in both tables."""
    for status, glyph in (("BUILDING", "🚀 BUILD"), ("FADING", "🌫️ FADE"),
                          ("BREAKING", "⚠️ BREAK"), ("INTACT", "• INTACT")):
        rows = V.rows_for([_zone(status=status)], None)
        assert glyph in V.table_html(rows), status


def test_an_unknown_status_shows_a_dash():
    rows = V.rows_for([_zone(status="WEIRD")], None)
    html = V.table_html(rows)
    assert ">—<" in html


def test_status_tone_follows_leg_table_panels_tone_rule():
    from mios_v5.ui.theme import BEAR, BULL, MUTED, WARN
    assert V.STATUS_TONE["BUILDING"] == BULL
    assert V.STATUS_TONE["BREAKING"] == BEAR
    assert V.STATUS_TONE["FADING"] == WARN
    assert V.STATUS_TONE["INTACT"] == MUTED


def test_dominant_is_toned_buyers_bull_sellers_bear():
    from mios_v5.ui.theme import BEAR, BULL, MUTED
    assert V.DOMINANT_TONE["buyers"] == BULL
    assert V.DOMINANT_TONE["sellers"] == BEAR
    assert V.DOMINANT_TONE["balanced"] == MUTED


def test_the_html_escapes_a_hostile_label():
    rows = V.rows_for([_zone()], None, call_label="<script>x</script>")
    html = V.table_html(rows)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_volume_is_compact_l_above_a_lakh_plain_below():
    assert V._vol(60_000) == "60,000"
    assert V._vol(150_000) == "1.5L"
    assert V._vol(None) == "—"
    assert V._vol("junk") == "—"


def test_a_row_missing_required_fields_does_not_raise():
    """`rows_for` guarantees `lower`/`upper` on every row it emits, but
    `table_html` is a public function and must not trust that blindly."""
    assert V.table_html([{"leg": "X"}]) == ""
    assert V.table_html([None, 7, "x"]) == ""


# ══════════════════════════════════════════════════════════════════════
#  purity
# ══════════════════════════════════════════════════════════════════════

def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "ui" / "vob_table_panel.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas"}
    assert "session_state" not in src


def test_nothing_is_recomputed_here():
    """⚠️ The whole premise: `analyze_vob_volume` already produced every number
    in a row. This module must not touch price/volume series at all."""
    src = (_ROOT / "mios_v5" / "ui" / "vob_table_panel.py").read_text()
    tree = ast.parse(src)
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(tree) if isinstance(c, ast.Call)}
    assert not {"analyze_vob_volume", "detect_blocks", "VolumeOrderBlocks"} & called


# ══════════════════════════════════════════════════════════════════════
#  wiring — below the chart, reading the same store the chart draws from
# ══════════════════════════════════════════════════════════════════════

def _charts_fn():
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    return next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == "_charts_screen"), src


def test_the_table_is_drawn_by_the_charts_screen():
    """⚠️ A renderer nothing calls is the bug this session keeps finding."""
    fn, _src = _charts_fn()
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_vob_zone_table" in called


def test_it_is_drawn_below_the_chart():
    fn, src = _charts_fn()
    body = ast.get_source_segment(src, fn) or ""
    assert body.index("_terminal_chart") < body.index("_vob_zone_table")


def test_it_reads_the_same_store_the_chart_rectangles_draw_from():
    """⚠️ Two readers of ONE store, not two owners of the answer — the table and
    the chart's coloured rectangles must never be able to disagree about a zone."""
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_vob_zone_table")
    keys = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_atm_leg_vob_volume" in keys
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_leg_store" in called
    assert "analyze_vob_volume" not in called, "must not recompute the zones"


def test_no_zones_says_so_rather_than_drawing_nothing():
    fn, _src = _charts_fn()
    d6 = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn2 = next(n for n in ast.walk(ast.parse(d6))
              if isinstance(n, ast.FunctionDef) and n.name == "_vob_zone_table")
    body = ast.get_source_segment(d6, fn2) or ""
    assert "st.caption" in body
