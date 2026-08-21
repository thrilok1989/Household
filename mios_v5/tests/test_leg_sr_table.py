"""The legs' S/R read as a table under the charts.

The chart marks the level and names the state; the table says how far the leg
actually is from it, which a line on a premium axis cannot show at a glance.

Same values either way — nothing is recomputed here, the reads come from the
store `_publish_atm_legs` already fills each cycle. The one job these tests do
is make sure the table cannot disagree with the chart above it.
"""

from __future__ import annotations

import re

import pytest

from mios_v5.ui.leg_sr_table import (
    CHARTS,
    build_table,
    row_for,
    rows,
    table_html,
)
from mios_v5.ui.terminal_chart import SR_STATE_TONE


def _text(html: str) -> str:
    """The table's visible text, tags stripped."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


BREAK = {"state": "BREAKING", "side": "resistance", "level": 124.5}
REJECT = {"state": "REJECTING", "side": "support", "level": 88.0}


# ── one row per leg, always ────────────────────────────────────────────

def test_both_legs_get_a_row():
    out = rows(call_sr=BREAK, put_sr=REJECT)
    assert [r["chart"] for r in out] == list(CHARTS)


def test_a_leg_with_no_read_still_gets_a_row():
    """An empty table would look broken. "No level in range" is a fact worth
    showing — it is the engine saying it has no verdict, not a failure."""
    out = rows()
    assert len(out) == 2
    assert all(r["state"] == "NONE" for r in out)
    assert all(r["level"] is None for r in out)


def test_an_unknown_state_degrades_to_none():
    r = row_for("CALL", {"state": "WOBBLING", "level": 10.0})
    assert r["state"] == "NONE"


# ── the numbers ────────────────────────────────────────────────────────

def test_distance_is_ltp_minus_level():
    r = row_for("CALL", BREAK, ltp=126.6)
    assert r["distance"] == pytest.approx(2.1)


def test_distance_is_negative_below_the_level():
    r = row_for("PUT", REJECT, ltp=86.35)
    assert r["distance"] == pytest.approx(-1.65)


def test_distance_is_none_without_both_numbers():
    assert row_for("CALL", BREAK, ltp=None)["distance"] is None
    assert row_for("CALL", {"state": "BREAKING"}, ltp=120.0)["distance"] is None


def test_a_non_numeric_ltp_does_not_raise():
    assert row_for("CALL", BREAK, ltp="n/a")["ltp"] is None


# ── the rendered table ─────────────────────────────────────────────────

def test_the_table_shows_state_level_ltp_and_distance():
    html = build_table(call_sr=BREAK, call_ltp=126.6, call_label="ATM CE 24500")
    text = _text(html)
    for want in ("ATM CE 24500", "BREAKING", "resistance",
                 "₹124.50", "₹126.60", "+2.10"):
        assert want in text, f"{want!r} missing from: {text}"


def test_distance_carries_its_sign():
    """+2.10 reads as "above the level" at a glance, which is the half of the
    answer the state word does not carry."""
    assert "+2.10" in _text(build_table(call_sr=BREAK, call_ltp=126.6))
    assert "-1.65" in _text(build_table(put_sr=REJECT, put_ltp=86.35))


def test_missing_numbers_render_as_a_dash_not_a_zero():
    text = _text(build_table(call_sr={"state": "NONE"}))
    assert "—" in text
    assert "₹0.00" not in text


def test_empty_rows_render_nothing():
    assert table_html([]) == ""
    assert table_html(None) == ""


def test_the_legs_are_labelled_by_their_strike():
    text = _text(build_table(call_sr=BREAK, put_sr=REJECT,
                             call_label="ATM CE 24500",
                             put_label="ATM PE 24500"))
    assert "ATM CE 24500" in text and "ATM PE 24500" in text


def test_call_and_put_reads_stay_on_their_own_rows():
    text = _text(build_table(call_sr=BREAK, put_sr=REJECT,
                             call_label="CE", put_label="PE"))
    ce, pe = text.index("CE "), text.index("PE ")
    assert text.index("BREAKING") < pe, "the call's state leaked into the put row"
    assert text.index("REJECTING") > ce


# ── the table and the chart agree ──────────────────────────────────────

@pytest.mark.parametrize("state", sorted(SR_STATE_TONE))
def test_every_charted_state_has_a_meaning_in_the_table(state):
    """The chart can draw a state the table has no wording for only if these
    two vocabularies drift apart. They must not."""
    r = row_for("CALL", {"state": state, "level": 10.0}, ltp=11.0)
    assert r["state"] == state
    assert r["meaning"] and r["meaning"] != "No level in range"


def test_the_table_colours_match_the_chart():
    """A state must not be one colour on the chart and another in the table.

    It was: ACCEPTING is mint (#7fe8b0) on the panel, and a parallel colour map
    here rendered it the same green as BREAKING — indistinguishable at a
    glance. The table now takes the colour from the chart, so they cannot
    drift; this asserts the wiring, not a copied value."""
    from mios_v5.ui.leg_sr_table import state_colour
    for state, (_label, colour) in SR_STATE_TONE.items():
        assert state_colour(state) == colour, state


def test_an_unknown_state_gets_a_neutral_colour():
    from mios_v5.ui.leg_sr_table import state_colour
    assert state_colour("NONE") == "#8c9bad"
    assert state_colour("nonsense") == "#8c9bad"


# ── the table follows the theme, like the charts above it ──────────────

def test_the_table_has_a_light_and_a_dark_chrome():
    from mios_v5.ui.leg_sr_table import chrome
    assert chrome("light") != chrome("dark")
    assert chrome("light")["row_bg"] == "#ffffff"


def test_unknown_theme_falls_back_to_dark():
    from mios_v5.ui.leg_sr_table import chrome
    assert chrome("nonsense") == chrome("dark")
    assert chrome(None) == chrome("dark")


def test_the_rendered_table_takes_the_theme():
    """A dark-only table under a light chart is the same mismatch the chart
    theming just fixed, in miniature.

    Asserts on the ROW BACKGROUND, which is what actually differs. Testing for
    "#ffffff" alone would pass on dark too — dark puts white *text* on its
    header, so the colour appears in both.
    """
    from mios_v5.ui.leg_sr_table import chrome
    light = build_table(call_sr=BREAK, call_ltp=126.6, theme="light")
    dark = build_table(call_sr=BREAK, call_ltp=126.6, theme="dark")
    assert f"background:{chrome('light')['row_bg']}" in light
    assert f"background:{chrome('dark')['row_bg']}" not in light
    assert f"background:{chrome('dark')['row_bg']}" in dark
    assert f"background:{chrome('light')['row_bg']}" not in dark


def test_both_themes_show_the_same_numbers():
    """Only the chrome changes — the read must be identical."""
    args = dict(call_sr=BREAK, put_sr=REJECT, call_ltp=126.6, put_ltp=86.35)
    assert _text(build_table(theme="light", **args)) == \
        _text(build_table(theme="dark", **args))


# ── "NONE" has to say WHICH kind of nothing ────────────────────────────

def test_a_missing_read_is_not_the_same_as_no_level():
    """Regression: both rendered as "No level in range", so a leg whose frame
    was too short to analyse looked identical to one trading in clear air.

    `_publish_atm_legs` only stores a truthy read, and
    `classify_leg_sr_behavior` returns None outright for a short frame — so a
    missing entry means the engine never got to look."""
    from mios_v5.ui.leg_sr_table import no_level_reason
    assert no_level_reason(None) == "unmeasured"
    assert no_level_reason({}) == "unmeasured"
    assert no_level_reason({"state": "NONE"}) == "no_blocks"


def test_blocks_present_but_no_level_says_wrong_side():
    """Support counts only at or below the LTP and resistance only at or
    above, so blocks can exist while none is on the side being tested."""
    from mios_v5.ui.leg_sr_table import no_level_reason
    assert no_level_reason({"state": "NONE"}, zones=[{"mid": 130.0}]) == "wrong_side"
    assert no_level_reason({"state": "NONE"}, zones=[]) == "no_blocks"


def test_a_real_state_reports_no_reason():
    from mios_v5.ui.leg_sr_table import no_level_reason
    assert no_level_reason(BREAK) == "none"


def test_the_reason_reaches_the_rendered_row():
    unmeasured = _text(build_table(call_sr=None, call_ltp=117.25))
    assert "Not measured" in unmeasured

    no_blocks = _text(build_table(call_sr={"state": "NONE"}, call_ltp=117.25))
    assert "28+" in no_blocks, no_blocks

    wrong_side = _text(build_table(call_sr={"state": "NONE"}, call_ltp=117.25,
                                   call_zones=[{"mid": 130.0}]))
    assert "wrong" in wrong_side.lower() or "tested side" in wrong_side


def test_the_bar_threshold_matches_the_detector():
    """`VolumeOrderBlocks(sensitivity)` needs `sensitivity + 13 + 10` bars.
    If that changes, this wording becomes a lie."""
    from mios_v5.ui.leg_sr_table import MIN_BARS_FOR_BLOCKS
    sensitivity = 5                      # what classify_leg_sr_behavior uses
    assert MIN_BARS_FOR_BLOCKS == sensitivity + 13 + 10


def test_a_verdict_still_reads_as_before():
    """The reason must not intrude on a leg that actually has a state.

    Scoped to the CALL row: passing only `call_sr` leaves the PUT genuinely
    unmeasured, so "Not measured" belongs in the table — just not in this row.
    """
    text = _text(build_table(call_sr=BREAK, call_ltp=126.6, call_label="CE",
                             put_label="PE"))
    call_row = text[text.index("CE "):text.index("PE ")]
    assert "Broke through" in call_row
    assert "Not measured" not in call_row and "28+" not in call_row
