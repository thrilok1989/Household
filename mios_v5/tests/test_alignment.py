"""🧭 The Market Alignment Checklist — one table, assembled from what other
engines already published.

The property this file defends above all others: **it computes no market fact.**
Every value is read; the only two things decided here are what spot is doing at
a level (`interaction`) and which way that points (`level_alignment`, through
`bias_ball`). A second opinion about any market fact would make this the very
thing the desk asked it not to be — another engine.
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import alignment as A
from mios_v5 import bias_ball as BB
from mios_v5.ui import alignment_panel as P

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── interaction: what spot is doing at a level ─────────────────────────

def test_above_a_support_is_holding():
    r = A.interaction(24400, 24350, "support")
    assert r["key"] == "holding"
    assert "₹24,350" in r["text"]


def test_below_a_resistance_is_rejecting():
    assert A.interaction(24300, 24400, "resistance")["key"] == "rejecting"


def test_below_a_support_is_breaking():
    assert A.interaction(24300, 24350, "support")["key"] == "breaking"


def test_within_the_band_is_testing_whatever_the_role():
    for role in ("support", "resistance"):
        assert A.interaction(24352, 24350, role)["key"] == "testing"


def test_a_cross_since_the_last_bar_is_reclaimed():
    """⚠️ What `prev` is for. A level crossed since the last bar is a different
    event from one that has been below spot all session."""
    r = A.interaction(24420, 24400, "resistance", prev=24380)
    assert r["key"] == "reclaimed"


def test_a_cross_the_other_way_is_breaking():
    r = A.interaction(24380, 24400, "support", prev=24420)
    assert r["key"] == "breaking"


def test_a_distant_level_is_far_not_holding():
    """⚠️ FAR is a real answer. A level eight bands away is not "holding" in any
    useful sense, and a green tick there would credit a level nobody is trading
    near."""
    assert A.interaction(25200, 24350, "support")["key"] == "far"


def test_the_band_scales_with_atm_range():
    near = A.interaction(24390, 24350, "support", atm_range=400.0)
    assert near["key"] == "testing", "a wider instrument needs a wider band"
    assert A.interaction(24390, 24350, "support", atm_range=100.0)["key"] == "holding"


def test_a_missing_level_is_not_available_not_a_guess():
    for spot, lvl in ((24400, None), (None, 24350), (None, None)):
        r = A.interaction(spot, lvl, "support")
        assert r["key"] == "na" and r["text"] == "—"


def test_junk_does_not_raise():
    assert A.interaction("x", "y", "support")["key"] == "na"
    assert A.interaction(24400, float("nan"), "support")["key"] == "na"


def test_every_interaction_has_an_icon_and_words():
    for key, (icon, words) in A.INTERACTIONS.items():
        assert icon and words, key


# ── alignment: through bias_ball, never re-derived ─────────────────────

def test_a_support_holding_is_bullish_and_breaking_is_bearish():
    assert A.level_alignment("NIFTY", "support", "holding") == A.BULL
    assert A.level_alignment("NIFTY", "support", "breaking") == A.BEAR


def test_a_resistance_rejecting_is_bearish_and_reclaimed_is_bullish():
    assert A.level_alignment("NIFTY", "resistance", "rejecting") == A.BEAR
    assert A.level_alignment("NIFTY", "resistance", "reclaimed") == A.BULL


def test_testing_and_far_are_neutral_because_nobody_can_tell_yet():
    for key in ("testing", "far", "na"):
        assert A.level_alignment("NIFTY", "support", key) == A.NEUTRAL


def test_the_put_leg_inversion_is_bias_balls_and_is_not_restated():
    """⚠️ A PUT's own support holding is NIFTY-BEARISH. The rule lives in
    `bias_ball.leg_level_bias`; this must inherit it, not re-derive it."""
    assert A.level_alignment("PUT", "support", "holding") == BB.leg_level_bias("PUT", "support")
    assert A.level_alignment("PUT", "support", "holding") == A.BEAR
    assert A.level_alignment("CALL", "support", "holding") == A.BULL


def test_the_failure_case_flips_the_leg_answer_too():
    assert A.level_alignment("PUT", "support", "breaking") == A.BULL


def test_an_unknown_role_is_neutral_rather_than_a_guess():
    assert A.level_alignment("NIFTY", "chop", "holding") == A.NEUTRAL


# ── rows ────────────────────────────────────────────────────────────────

def test_a_level_row_never_contradicts_itself():
    """⚠️ The words and the ball come from ONE interaction, so a row cannot read
    "Breaking below" beside a green tick."""
    r = A.level_row("NIFTY STRUCTURE", "NIFTY Support", 24350, 24300, "support")
    assert "Breaking below" in r["position"]
    assert r["align"] == A.BEAR and r["ball"] == "🔴"


def test_a_row_with_no_level_reads_not_available():
    r = A.level_row("NIFTY STRUCTURE", "PUT Wall OI", None, 24400, "support")
    assert r["align"] == A.NA and r["ball"] == "❓"
    assert r["value"] == "—"


def test_several_levels_are_shown_side_by_side():
    r = A.levels_row("NIFTY STRUCTURE", "NIFTY HVP LOW",
                     [24300, 24250, 24350], 24400, "support")
    assert "₹24,250" in r["value"] and "₹24,350" in r["value"]


def test_the_nearest_level_drives_the_verdict():
    """It is the one price is actually trading against."""
    r = A.levels_row("NIFTY STRUCTURE", "NIFTY HVP LOW",
                     [23000, 24390], 24400, "support")
    assert "₹24,390" in r["position"], r
    assert r["align"] == A.NEUTRAL          # within the testing band


def test_a_long_level_list_is_truncated_but_counted():
    r = A.levels_row("G", "HVP", [1, 2, 3, 4, 5, 6], 3.0, "support")
    assert "+2" in r["value"]


def test_no_levels_is_not_available():
    r = A.levels_row("G", "HVP", [], 24400, "support")
    assert r["align"] == A.NA


def test_a_score_below_the_threshold_is_neutral_not_slightly_bull():
    """⚠️ A checklist that counted +0.2 as an aligned vote would manufacture
    agreement out of noise."""
    assert A.score_row("G", "News", "Mild", 0.2, 1.0)["align"] == A.NEUTRAL
    assert A.score_row("G", "News", "Bullish", 1.4, 1.0)["align"] == A.BULL
    assert A.score_row("G", "News", "Bearish", -1.4, 1.0)["align"] == A.BEAR


def test_a_missing_score_is_not_available():
    assert A.score_row("G", "News", None, None)["align"] == A.NA


def test_a_label_with_no_value_is_not_available_rather_than_neutral():
    """⚠️ `bias_ball.direction_bias` returns NEUTRAL for both "unrecognised" and
    "genuinely neutral". Only this layer knows whether a value arrived at all."""
    assert A.label_bias(None) is None and A.label_bias("") is None
    assert A.label_bias("Bullish") == A.BULL
    assert A.label_bias("Bearish") == A.BEAR
    assert A.label_bias("wobble") == A.NEUTRAL


# ── the summary ─────────────────────────────────────────────────────────

def _rows(*specs):
    return [A.row("G", f"c{i}", "v", None, a, "", f) for i, (a, f) in enumerate(specs)]


def test_the_majority_wins():
    s = A.summarise(_rows((A.BEAR, "STRUCTURE"), (A.BEAR, "OPTIONS"),
                          (A.BULL, "DEALERS")))
    assert s["net"] == A.BEAR
    assert s["counts"][A.BEAR] == 2 and s["counts"][A.BULL] == 1


def test_a_tie_is_neutral_including_nothing_at_all():
    assert A.summarise(_rows((A.BULL, "X"), (A.BEAR, "Y")))["net"] == A.NEUTRAL
    assert A.summarise([])["net"] == A.NEUTRAL


def test_unreadable_checks_are_counted_apart_and_not_as_neutral():
    """⚠️ "I looked and it is balanced" and "I could not look" are different
    facts, and only one of them belongs in the denominator."""
    s = A.summarise(_rows((A.BULL, "X"), (A.NA, "Y"), (A.NEUTRAL, "Z")))
    assert s["counts"][A.NA] == 1
    assert s["active"] == 2, "an unreadable check inflated the coverage claim"
    assert s["total"] == 3


def test_each_family_gets_its_own_verdict():
    s = A.summarise(_rows((A.BEAR, "STRUCTURE"), (A.BEAR, "STRUCTURE"),
                          (A.BULL, "DEALERS")))
    assert s["families"]["STRUCTURE"] == A.BEAR
    assert s["families"]["DEALERS"] == A.BULL


def test_the_conflicting_family_is_named_not_just_counted():
    """⚠️ A verdict that hides the family pulling the other way is the
    overconfident read this table exists to replace."""
    s = A.summarise(_rows((A.BEAR, "STRUCTURE"), (A.BEAR, "OPTIONS"),
                          (A.BULL, "DEALERS")))
    assert s["conflicts"] == ["DEALERS"]


def test_no_conflict_is_reported_when_everything_agrees():
    s = A.summarise(_rows((A.BEAR, "STRUCTURE"), (A.BEAR, "OPTIONS")))
    assert s["conflicts"] == []


def test_a_neutral_net_names_no_conflict():
    s = A.summarise(_rows((A.BULL, "X"), (A.BEAR, "Y")))
    assert s["conflicts"] == []


def test_the_why_line_lists_only_the_agreeing_checks():
    rows = [A.row("G", "Resistance", "₹24,400", "🔴 Rejecting ₹24,400", A.BEAR),
            A.row("G", "Magnet", "₹24,500", "🧲 Pull ↑", A.BULL)]
    w = A.why(rows, A.BEAR)
    assert len(w) == 1 and "Resistance" in w[0]


def test_the_why_line_is_empty_when_there_is_no_verdict():
    assert A.why([A.row("G", "x", 1, None, A.BULL)], A.NEUTRAL) == []


# ── the panel ───────────────────────────────────────────────────────────

def _sample():
    return [
        A.level_row(A.GROUPS[0], "NIFTY Resistance", 24400, 24300, "resistance"),
        A.level_row(A.GROUPS[0], "NIFTY Support", 24350, 24300, "support"),
        A.row(A.GROUPS[0], "Charm Pin / Magnet", "₹24,400", "🧲 Pulled ↑",
              A.BULL, "dealer magnet", "DEALERS"),
        A.row(A.GROUPS[1], "Premium Energy", "CE 42 / PE 78", "⚡ PUT loaded",
              A.BEAR, "PE dominant", "OPTIONS"),
        A.row(A.GROUPS[2], "War Zone", "support ₹24,350", "🟣 Inside",
              A.BEAR, "sellers", "STRUCTURE"),
        A.row(A.GROUPS[0], "PUT Wall OI", None, None, None,
              "no wall published", "OPTIONS"),
    ]


def test_the_card_carries_every_group_it_has_rows_for():
    h = P.checklist_html(_sample(), 24300)
    for g in A.GROUPS:
        assert g in h, g


def test_the_card_shows_the_five_columns():
    h = P.checklist_html(_sample(), 24300)
    for col in ("CHECK", "VALUE / LEVEL", "SPOT BEHAVIOUR", "ALIGNMENT",
                "REMARKS"):
        assert col in h, col


def test_the_summary_reports_the_net_and_the_coverage():
    h = P.checklist_html(_sample(), 24300)
    assert "NET ALIGNMENT" in h
    assert "readable checks" in h


def test_the_conflict_is_printed_on_the_card():
    h = P.checklist_html(_sample(), 24300)
    assert "CONFLICT" in h and "DEALERS" in h


def test_an_unreadable_row_still_appears_marked():
    """⚠️ Never dropped. A checklist that quietly omits what it could not read
    overstates its own coverage."""
    h = P.checklist_html(_sample(), 24300)
    assert "PUT Wall OI" in h and "❓" in h


def test_no_rows_draws_no_card():
    assert P.checklist_html([], 24300) == ""
    assert P.checklist_html(None) == ""


def test_a_row_in_an_unknown_group_is_shown_not_swallowed():
    h = P.checklist_html([A.row("MYSTERY", "x", "1", None, A.BULL)], 24300)
    assert "OTHER" in h and "x" in h


def test_junk_rows_do_not_raise():
    assert isinstance(P.checklist_html([None, "x", 7]), str)


def test_a_bad_spot_does_not_break_the_header():
    assert "ALIGNMENT CHECKLIST" in P.checklist_html(_sample(), "nonsense")


# ── purity, and no second opinion ──────────────────────────────────────

def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "alignment.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas", "requests",
                        "numpy", "db"}


def test_it_computes_no_market_fact():
    """⚠️ THE RULE. It reads values other engines produced and decides only what
    spot is doing at a level. Calling an engine here would make it the duplicate
    the desk explicitly asked it not to be."""
    src = (_ROOT / "mios_v5" / "alignment.py").read_text()
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(ast.parse(src)) if isinstance(c, ast.Call)}
    for engine in ("compute_market_picture", "build_final_read", "split",
                   "calculate_money_flow_profile", "high_volume_pivots",
                   "analyze_vob_volume", "compute_vpfr", "assess",
                   "calculate_volume_delta", "detect_ignition"):
        assert engine not in called, f"alignment.py calls {engine}"


def test_the_bias_mapping_goes_through_bias_ball():
    src = (_ROOT / "mios_v5" / "alignment.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "level_alignment")
    assert "leg_level_bias" in ast.unparse(fn)


# ── the collector: reads only, and reads the REAL keys ─────────────────

_APP = _ROOT / "vob_minimal.py"


def _app_fn(name):
    for n in ast.walk(ast.parse(_APP.read_text())):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name}() not found in vob_minimal.py")


def test_the_collector_computes_nothing():
    """⚠️ THE RULE, at the wiring layer. It reads published state and hands it
    to `alignment`. An engine call here would be the duplicate work the desk
    asked to avoid — the same guard `_charts_screen` already carries."""
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(_app_fn("_alignment_rows"))
              if isinstance(c, ast.Call)}
    for engine in ("compute_market_picture", "analyze_vob_volume",
                   "calculate_money_flow_profile", "high_volume_pivots",
                   "compute_vpfr", "detect_ignition", "classify_leg_sr_behavior",
                   "calculate_volume_delta", "_hv_points", "compute_dynamic_poc"):
        assert engine not in called, f"_alignment_rows calls {engine}"


def test_it_reads_the_stores_the_app_already_publishes():
    src = ast.unparse(_app_fn("_alignment_rows"))
    for key in ("'_market_picture'", "'_leg_profiles'", "'_atm_leg_dfs'",
                "'_atm_leg_sr_behavior'", "'_premium_energy'"):
        assert key in src, key


def test_it_uses_build_final_read_rather_than_re_deriving_support():
    """`strong_support` / `battle_zone` have one owner. Reading them is fine;
    recomputing them would be a second answer to the same question."""
    src = ast.unparse(_app_fn("_alignment_rows"))
    assert "build_final_read" in src


def test_every_bias_comes_from_alignment_or_bias_ball():
    """⚠️ No inline bull/bear literals deciding a row's colour — that is how a
    second mapping gets born beside `bias_ball`'s."""
    fn = _app_fn("_alignment_rows")
    src = ast.unparse(fn)
    # the only bare BULL/BEAR references may be `_al.BULL` / `_al.BEAR`
    assert "'bull'" not in src and "'bear'" not in src, src[:400]


def test_the_leg_rows_are_measured_against_the_leg_and_not_spot():
    """⚠️ A spot number on a premium axis is meaningless — the rule
    `_panel_profile` already follows for the money-flow profile."""
    src = ast.unparse(_app_fn("_alignment_rows"))
    assert "_ltp" in src, "the leg rows must use the leg's own LTP"


def test_the_card_is_rendered_above_the_live_confluence_card():
    src = _APP.read_text()
    assert src.index("_render_alignment_checklist(underlying)") < src.index(
        "_render_live_confluence(underlying)")


def test_the_renderer_never_leaves_a_silent_gap():
    """Three-state discipline: a card that cannot draw says why, in its own
    slot, rather than leaving a space that reads as a missing feature."""
    src = ast.unparse(_app_fn("_render_alignment_checklist"))
    assert "caption" in src
    assert "unavailable" in src or "could not" in src


# ── reference rows: context, not checks ────────────────────────────────

def test_a_reference_row_votes_for_nothing():
    """⚠️ Spot is CONTEXT. Counting it as "not available" would inflate the
    unreadable tally with a row that was never a question — and the desk's own
    table shows a dash in its alignment column for exactly this row."""
    rows = [A.row("G", "Spot Price", "₹24,300", "AT", None, "live",
                  "STRUCTURE", reference=True),
            A.row("G", "News", "Bearish", None, A.BEAR, "", "GLOBAL")]
    s = A.summarise(rows)
    assert s["counts"][A.NA] == 0, "the spot row was counted as unreadable"
    assert s["total"] == 1 and s["active"] == 1


def test_a_reference_row_still_appears_on_the_card():
    h = P.checklist_html([A.row(A.GROUPS[0], "Spot Price", "₹24,300", "AT",
                                None, "live", "STRUCTURE", reference=True)])
    assert "Spot Price" in h and "24,300" in h
    assert "not available" not in h, "context was labelled as a failed read"


def test_a_reference_row_carries_no_ball():
    r = A.row("G", "Spot Price", "₹24,300", "AT", None, "", "STRUCTURE",
              reference=True)
    assert r["ball"] == "" and r["align"] is None


def test_ordinary_rows_are_unaffected():
    r = A.row("G", "News", "Bearish", None, A.BEAR, "", "GLOBAL")
    assert r["reference"] is False and r["ball"] == "🔴"


def test_the_collector_marks_spot_as_reference():
    src = ast.unparse(_app_fn("_alignment_rows"))
    assert "reference=True" in src


# ── the magnet row: the shapes the app really publishes ────────────────
#
# ⚠️ A first version called `.get('strike')` on `oi_pin`, which is a TUPLE
# `(strike, note)` (vob_minimal.py:8339) — so it never matched and the row read
# "no pin available" while the pin was sitting right there. Guessing a shape is
# the `fii_net` bug: a lookup that always misses on data that was always there.

def test_the_oi_pin_is_read_as_a_tuple_not_a_dict():
    src = ast.unparse(_app_fn("_alignment_rows"))
    assert "isinstance(_pin, (tuple, list))" in src
    assert "_pin.get('strike')" not in src


def test_the_gex_magnet_is_preferred_over_the_oi_pin():
    """`gex_magnet` is the strike dealer hedging actually defends; `oi_pin` is
    the balanced-wall pin. Both are real, and the GEX one is the truer answer."""
    src = ast.unparse(_app_fn("_alignment_rows"))
    assert "'magnet'" in src
    assert src.index("_gmag = ") < src.index("_mag = _gmag if")


def test_the_repeller_is_drawn_too():
    """It was computed and dropped for the same reason the magnet was —
    nothing downstream ever read it."""
    src = ast.unparse(_app_fn("_alignment_rows"))
    assert "'repeller'" in src


def test_a_disagreeing_pin_and_magnet_are_both_shown():
    """Two published answers that differ is information, not a reason to hide
    one of them."""
    src = ast.unparse(_app_fn("_alignment_rows"))
    assert "OI Pin (balanced walls)" in src


def test_the_magnet_pulls_the_way_it_points():
    """Above spot pulls up (bull), below pulls down (bear) — the row's words
    and its ball must agree."""
    # exercised through the pure row builder the collector uses
    up = A.row("G", "Charm Pin / Magnet", "₹24,400", "🧲 Pulled ↑ ₹24,400",
               A.BULL, "dealer gamma magnet", "DEALERS")
    dn = A.row("G", "Charm Pin / Magnet", "₹24,200", "🧲 Pulled ↓ ₹24,200",
               A.BEAR, "dealer gamma magnet", "DEALERS")
    assert "↑" in up["position"] and up["ball"] == "🟢"
    assert "↓" in dn["position"] and dn["ball"] == "🔴"


# ── no GENERAL CONTEXT: the table asks one question ────────────────────
#
# News, FII/DII, sector, global and regime were in the first version and the
# desk removed them. This table asks "where is SPOT and what is it doing at
# each level"; a daily-cadence sentiment score has no spot behaviour to answer
# with, so those rows sat with an empty middle column, mostly read ❓, and
# diluted the agreement count with checks that could not speak to the question.

def test_there_is_no_general_context_group():
    assert "GENERAL CONTEXT" not in A.GROUPS
    assert A.GROUPS == ("NIFTY STRUCTURE", "OPTION PREMIUM / LTP",
                        "FINAL INTERACTION")


def test_the_collector_builds_no_context_rows():
    src = ast.unparse(_app_fn("_alignment_rows"))
    for check in ("'News'", "'FII / DII'", "'Sector'", "'Global'", "'Regime'"):
        assert check not in src, f"{check} is still a checklist row"


def test_the_collector_no_longer_reads_the_context_stores():
    """⚠️ Not just hidden — the reads are gone, so the table costs nothing for
    data it does not show."""
    src = ast.unparse(_app_fn("_alignment_rows"))
    for key in ("'_fii_dii_cash'", "'news_bias'", "'sector_bias'",
                "'global_bias'"):
        assert key not in src, f"{key} is still read for a row that is gone"


def test_those_engines_are_untouched_elsewhere():
    """⚠️ Removed from THIS table, not from the app. The Market Picture still
    computes them and their own panels still draw them."""
    app = _APP.read_text()
    for key in ("'news_bias'", "'sector_bias'", "'global_bias'"):
        assert key in app, f"{key} was deleted from the app, not just the table"


def test_the_global_family_is_still_ordered_for_a_future_row():
    """A family with no rows is skipped in the summary anyway; keeping it in
    the tuple means a later GLOBAL row renders in its place, not appended."""
    assert "GLOBAL" in A.FAMILIES
    s = A.summarise(_rows((A.BEAR, "STRUCTURE")))
    assert "GLOBAL" not in s["families"]
