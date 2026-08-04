"""Stage 74 — Liquidity Intelligence.

`docs/AUDIT_LIQUIDITY_INTELLIGENCE.md` checked all thirteen requested outputs
against the codebase first and found **roughly seventy per cent already
existed** — including *five* separate point-of-control implementations, with the
Stage 71.8 audit having already chosen one and written "a fifth is forbidden".

So the tests that matter most here are the ones proving this module **did not
build a sixth**. The eight things it does compute get tested for behaviour; the
much longer list of things it must only ever read gets tested structurally,
against the parse tree.
"""

import ast
import pathlib

import pytest

from mios_v5 import liquidity as LQ
from mios_v5 import liquidity_context as LC

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _rows(pairs, node="High"):
    """`pairs` is [(bull, bear), …] oldest bin first."""
    out = []
    for i, (bull, bear) in enumerate(pairs):
        total = bull + bear
        out.append({
            "bin_low": 95.0 + i * 3, "bin_high": 98.0 + i * 3,
            "total_volume": total, "bull_volume": bull, "bear_volume": bear,
            "delta": bull - bear, "ratio": max(0.1, 1.0 - i * 0.25),
            "node_type": node if i == 0 else "Average",
            "sentiment": ("Bullish" if bull > bear
                          else "Bearish" if bear > bull else "Neutral"),
        })
    return out


def _profile(pairs=((800, 200), (600, 100), (100, 500)), poc=100.0,
             vah=105.0, val=95.0):
    return {"rows": _rows(pairs), "poc_price": poc,
            "value_area_high": vah, "value_area_low": val,
            "price_high": 110.0, "price_low": 90.0}


# ══════════════════════════════════════════════════════════════════════
#  the guards — what it must NOT have built
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_no_profile_builder_and_no_producer():
    """The whole point of the audit. `premium_structure` carries this same
    guard, for the same reason."""
    tree = ast.parse((ROOT / "mios_v5" / "liquidity.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    banned = {"numpy", "pandas", "indicators", "streamlit", "requests",
              "vob_minimal", "vob_indicators", "db", "premium_structure",
              "money_flow_profile", "triple_poc", "market_depth_advanced"}
    assert not (imported & banned), imported & banned


@pytest.mark.parametrize("owned", [
    "poc", "value_area", "profile", "money_flow_profile", "volume_profile",
    "sentiment_profile", "liquidity_profile", "hvn", "lvn", "vpfr",
])
def test_it_defines_no_producer_for_a_fact_that_already_has_an_owner(owned):
    """There were already FIVE POC implementations. A function named for one of
    these would be the sixth, however carefully it was written."""
    tree = ast.parse((ROOT / "mios_v5" / "liquidity.py").read_text())
    defined = {n.name.lstrip("_").lower() for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)}
    assert owned not in defined, f"{owned} has a producer here"


def test_the_five_existing_poc_implementations_are_still_the_only_ones():
    """If this fails, someone added a POC. The audit named all five and chose
    `compute_vpfr`; the count is the guard."""
    import re
    found = []
    for path in (ROOT / "vob_minimal.py", ROOT / "vob_indicators.py",
                 ROOT / "indicators" / "triple_poc.py",
                 ROOT / "indicators" / "money_flow_profile.py",
                 ROOT / "market_depth_advanced.py",
                 ROOT / "mios_v5" / "liquidity.py"):
        if not path.exists():
            continue
        text = path.read_text()
        found += [f"{path.name}:{m}" for m in
                  re.findall(r"def (compute_vpfr|compute_dynamic_poc|"
                             r"calculate_poc|analyze_volume_profile)", text)]
    assert not any("liquidity.py" in f for f in found), found


def test_it_claims_only_the_eight_things_the_audit_justified():
    assert LQ.COMPUTED_HERE == (
        "liquidity_shift", "liquidity_imbalance", "net_sentiment",
        "sentiment_shift", "poc_migration", "money_flow_divergence",
        "levels", "context")


def test_every_consumed_fact_names_exactly_one_owner():
    for name, owner in LQ.CONSUMED.items():
        assert owner and isinstance(owner, str), name
    assert not set(LQ.CONSUMED) & set(LQ.COMPUTED_HERE)


def test_the_audit_exists_and_records_the_five_pocs():
    doc = (ROOT / "docs" / "AUDIT_LIQUIDITY_INTELLIGENCE.md").read_text()
    assert "FIVE point-of-control implementations" in doc
    for marker in ("EXISTS", "WIRING", "COMPUTED", "MISSING"):
        assert marker in doc


def test_it_holds_no_state_between_cycles():
    """`previous` is passed in, never remembered. A module that remembers is one
    two callers can disagree with."""
    tree = ast.parse((ROOT / "mios_v5" / "liquidity.py").read_text())
    module_assigns = [n for n in tree.body if isinstance(n, ast.Assign)]
    for node in module_assigns:
        for target in node.targets:
            if isinstance(target, ast.Name) and not target.id.isupper():
                assert target.id.startswith("_"), target.id


def test_it_never_raises_whatever_arrives():
    for junk in (None, "", 0, [], {}, "a string", {"rows": "not a list"},
                 {"rows": [1, 2, 3]}):
        out = LQ.analyse(profile=junk, previous=junk, vpfr=junk, dealer=junk)
        assert isinstance(out, dict)
        assert out["advisory_only"] is True


# ══════════════════════════════════════════════════════════════════════
#  1 · 2 — imbalance and net sentiment
# ══════════════════════════════════════════════════════════════════════

def test_the_aggregate_delta_is_summed_because_nothing_else_sums_it():
    out = LQ.imbalance(_profile(((800, 200), (600, 100), (100, 500))))
    assert out["bull"] == 1500 and out["bear"] == 800
    assert out["dominance"] == LQ.BULLS


def test_a_matched_book_is_balanced_not_a_winner():
    """Below the band, calling a side is noise."""
    out = LQ.imbalance(_profile(((500, 500), (500, 500))))
    assert out["dominance"] == LQ.BALANCED
    assert "neither side" in out["why"]


def test_an_empty_profile_reports_unknown_not_zero():
    out = LQ.imbalance({"rows": []})
    assert out["imbalance"] == LQ.UNKNOWN and out["dominance"] == LQ.UNKNOWN


def test_a_profile_with_no_volume_is_unknown():
    out = LQ.imbalance({"rows": _rows(((0, 0), (0, 0)))})
    assert out["dominance"] == LQ.UNKNOWN


def test_sentiment_is_weighted_by_where_the_volume_is():
    """A node holding 1% of the day must not outvote the point of control."""
    heavy_bull = {"rows": [
        {"ratio": 1.0, "sentiment": "Bullish"},
        {"ratio": 0.05, "sentiment": "Bearish"},
        {"ratio": 0.05, "sentiment": "Bearish"},
    ]}
    out = LQ.net_sentiment(heavy_bull)
    assert out["dominance"] == LQ.BULLS
    assert out["bull_nodes"] == 1 and out["bear_nodes"] == 2


def test_sentiment_reports_unknown_when_no_row_picked_a_side():
    out = LQ.net_sentiment({"rows": [{"ratio": 1.0, "sentiment": "Neutral"}]})
    assert out["net_sentiment"] == LQ.UNKNOWN


# ══════════════════════════════════════════════════════════════════════
#  5 — POC migration over the existing series
# ══════════════════════════════════════════════════════════════════════

def test_all_six_poc_facts_come_from_one_existing_series():
    out = LQ.poc_migration([98, 99, 99, 100, 100, 101])
    assert out["poc"] == 101.0
    assert out["previous"] == 100.0
    assert out["migration"] == 1.0
    assert out["trend"] in LQ.POC_TRENDS
    assert out["velocity"] is not None
    assert out["stability"] is not None


def test_a_poc_that_moves_every_bar_is_unstable():
    """A point of control nobody defends is not a level, however precisely it
    is reported."""
    jumpy = LQ.poc_migration([100, 105, 98, 107, 95, 110])
    calm = LQ.poc_migration([100, 100, 100, 100, 100, 101])
    assert jumpy["stability"] < calm["stability"]


def test_a_tiny_move_is_stable_not_a_trend():
    """Bin noise is not migration.

    The reference is the traded range, not the POC series' own span — a point of
    control that sat still all session and then ticked one paise has a span of
    one paise, so normalising by that would read the tick as a 100% move."""
    out = LQ.poc_migration([100.0, 100.0, 100.0, 100.05], _profile())
    assert out["trend"] == LQ.POC_STABLE


def test_the_traded_range_is_the_reference_not_the_series_span():
    series = [100.0, 100.0, 100.0, 100.05]
    wide = LQ.poc_migration(series, {"price_high": 110.0, "price_low": 90.0})
    narrow = LQ.poc_migration(series, {"price_high": 100.06, "price_low": 100.0})
    assert wide["trend"] == LQ.POC_STABLE
    assert narrow["trend"] == LQ.POC_RISING


def test_a_poc_with_no_history_says_so():
    out = LQ.poc_migration([], {"poc_price": 100.0})
    assert out["poc"] == 100.0
    assert out["previous"] == LQ.UNKNOWN
    assert "cannot show migration" in out["why"]


def test_no_poc_at_all_is_unknown():
    out = LQ.poc_migration(None, None)
    assert out["poc"] == LQ.UNKNOWN


# ══════════════════════════════════════════════════════════════════════
#  4 · 11 — the cross-cycle reads, the one thing genuinely missing
# ══════════════════════════════════════════════════════════════════════

def test_the_first_cycle_has_nothing_to_compare_against():
    out = LQ.liquidity_shift(_profile())
    assert out["shift"] == LQ.UNKNOWN
    assert "no previous profile" in out["why"]


def test_a_moved_point_of_control_is_a_shift():
    out = LQ.liquidity_shift(_profile(poc=105.0), _profile(poc=95.0))
    assert out["shift"] == LQ.SHIFT_UP
    out = LQ.liquidity_shift(_profile(poc=95.0), _profile(poc=105.0))
    assert out["shift"] == LQ.SHIFT_DOWN


def test_a_widening_value_area_is_expansion_not_a_move():
    """Location and width are different questions — a reader seeing one number
    cannot tell a shift from a spread."""
    out = LQ.liquidity_shift(_profile(vah=115.0, val=85.0),
                             _profile(vah=105.0, val=95.0))
    assert out["shift"] == LQ.SHIFT_EXPANDING


def test_a_narrowing_value_area_is_compression():
    out = LQ.liquidity_shift(_profile(vah=101.0, val=99.0),
                             _profile(vah=110.0, val=90.0))
    assert out["shift"] == LQ.SHIFT_COMPRESSING


def test_a_profile_that_has_not_moved_is_holding():
    out = LQ.liquidity_shift(_profile(), _profile())
    assert out["shift"] == LQ.SHIFT_HOLDING


def test_every_shift_state_is_one_of_the_five():
    for now, before in ((_profile(), None), (_profile(), _profile()),
                        (_profile(poc=120.0), _profile()),
                        (_profile(vah=200.0), _profile())):
        assert LQ.liquidity_shift(now, before)["shift"] in \
            LQ.SHIFT_STATES + (LQ.UNKNOWN,)


def test_the_book_can_flip_while_liquidity_stays_put():
    """The reading worth catching: a level defended by the other side is the
    moment before it breaks."""
    bull = _profile(((900, 100), (800, 200)))
    bear = _profile(((100, 900), (200, 800)))
    assert LQ.liquidity_shift(bull, bear)["shift"] == LQ.SHIFT_HOLDING
    flip = LQ.sentiment_shift(bull, bear)
    assert flip["flipped"] is True and flip["sentiment_shift"] == "FLIP"


def test_sentiment_shift_needs_both_cycles():
    assert LQ.sentiment_shift(_profile(), None)["sentiment_shift"] == LQ.UNKNOWN


# ══════════════════════════════════════════════════════════════════════
#  6 — divergence
# ══════════════════════════════════════════════════════════════════════

def test_a_rally_on_a_bearish_book_is_a_bearish_divergence():
    """The single most useful thing this engine says: every other signal in the
    stack reads that rally as strength."""
    out = LQ.divergence(_profile(((100, 900), (200, 800))), price_change=1.5)
    assert out["divergence"] == LQ.DIV_BEAR


def test_a_selloff_on_a_bullish_book_is_a_bullish_divergence():
    out = LQ.divergence(_profile(((900, 100), (800, 200))), price_change=-1.5)
    assert out["divergence"] == LQ.DIV_BULL


def test_price_and_flow_agreeing_is_aligned():
    out = LQ.divergence(_profile(((900, 100), (800, 200))), price_change=1.5)
    assert out["divergence"] == LQ.DIV_NONE


def test_a_measured_but_balanced_book_cannot_diverge():
    """An aligned reading against a book nobody owns would be manufactured.

    Both sides reported here — the rows picked sides and netted out — which is
    a different fact from nobody reporting at all, tested below."""
    balanced = {"rows": [{"ratio": 1.0, "sentiment": "Bullish"},
                         {"ratio": 1.0, "sentiment": "Bearish"}]}
    out = LQ.divergence(balanced, price_change=2.0)
    assert out["divergence"] == LQ.DIV_NONE
    assert "nothing to diverge from" in out["why"]


def test_a_book_where_nobody_picked_a_side_is_unknown_not_aligned():
    """Neutral rows are an absence of a reading, not a balanced one."""
    out = LQ.divergence(_profile(((500, 500), (500, 500))), price_change=2.0)
    assert out["divergence"] == LQ.UNKNOWN


def test_divergence_needs_both_halves():
    assert LQ.divergence(_profile(), None)["divergence"] == LQ.UNKNOWN
    assert LQ.divergence(None, 1.0)["divergence"] == LQ.UNKNOWN


# ══════════════════════════════════════════════════════════════════════
#  7 — level clustering, the audit's highest-value item
# ══════════════════════════════════════════════════════════════════════

def test_levels_from_different_owners_near_each_other_become_one():
    out = LQ.cluster_levels(profile={"poc_price": 24000.0, "rows": []},
                            vpfr={"poc": 24005.0},
                            dealer={"gamma_flip": 24002.0},
                            spot=23900.0)
    assert out["clusters"] == 1
    assert out["resistance"][0]["witnesses"] == 3
    assert out["resistance"][0]["rank"] == LQ.MAJOR


def test_three_witnesses_from_one_owner_is_still_one_witness():
    """Three HVN bins from one profile is one source saying the same thing
    three times. Counting that as confirmation is how a profile talks itself
    into a level."""
    rows = [{"bin_low": 24000.0, "bin_high": 24010.0, "node_type": "High"},
            {"bin_low": 24005.0, "bin_high": 24015.0, "node_type": "High"},
            {"bin_low": 24010.0, "bin_high": 24020.0, "node_type": "High"}]
    out = LQ.cluster_levels(profile={"rows": rows}, spot=23000.0)
    assert all(e["rank"] != LQ.MAJOR for e in out["resistance"])


def test_support_is_below_spot_and_resistance_above():
    out = LQ.cluster_levels(profile={"poc_price": 24100.0, "rows": []},
                            vpfr={"val": 23900.0}, spot=24000.0)
    assert out["resistance"] and out["support"]
    assert all(e["price"] > 24000.0 for e in out["resistance"])
    assert all(e["price"] < 24000.0 for e in out["support"])


def test_the_nearest_level_comes_first():
    """The level that matters is the one price reaches next."""
    out = LQ.cluster_levels(
        profile={"poc_price": 24500.0, "rows": []},
        vpfr={"poc": 24100.0, "vah": 24900.0, "val": 23500.0},
        spot=24000.0)
    res = [e["price"] for e in out["resistance"]]
    sup = [e["price"] for e in out["support"]]
    assert res == sorted(res)
    assert sup == sorted(sup, reverse=True)


def test_a_level_at_spot_is_neither_support_nor_resistance():
    out = LQ.cluster_levels(profile={"poc_price": 24000.0, "rows": []},
                            spot=24000.0)
    assert out["at_spot"] and not out["support"] and not out["resistance"]


def test_the_tolerance_is_the_callers_because_a_premium_is_not_an_index():
    """0.12% of NIFTY is thirty points; of a ₹100 premium it is twelve paise."""
    tight = LQ.cluster_levels(profile={"poc_price": 100.0, "rows": []},
                              vpfr={"poc": 102.0}, spot=90.0)
    wide = LQ.cluster_levels(profile={"poc_price": 100.0, "rows": []},
                             vpfr={"poc": 102.0}, spot=90.0,
                             tolerance_pct=5.0)
    assert tight["clusters"] == 2 and wide["clusters"] == 1


def test_no_level_source_reporting_is_unknown_not_an_empty_list():
    """An empty support list reads as "we looked and found none". A panel would
    render "no support" over a cycle where nothing was measured at all."""
    out = LQ.cluster_levels()
    assert out["clusters"] == LQ.UNKNOWN
    assert out["support"] == LQ.UNKNOWN and out["resistance"] == LQ.UNKNOWN
    assert "no level source" in out["why"]


def test_every_clustered_level_names_the_owners_behind_it():
    out = LQ.cluster_levels(profile={"poc_price": 24000.0, "rows": []},
                            dealer={"gamma_flip": 24001.0}, spot=23000.0)
    entry = out["resistance"][0]
    assert entry["owners"] and all(isinstance(o, str) for o in entry["owners"])
    assert entry["kinds"]


# ══════════════════════════════════════════════════════════════════════
#  the whole stage
# ══════════════════════════════════════════════════════════════════════

def test_analyse_publishes_all_eight_and_names_its_sources():
    out = LQ.analyse(profile=_profile(), previous=_profile(poc=95.0),
                     dynamic_poc=[98, 99, 100], spot=100.0, price_change=0.5)
    for key in LQ.COMPUTED_HERE:
        if key != "context":
            assert key in out, key
    assert out["consumed"] == LQ.CONSUMED
    assert out["ready"] is True


def test_it_is_advisory_only():
    assert LQ.ADVISORY_ONLY is True
    assert LQ.analyse(profile=_profile())["advisory_only"] is True


def test_the_same_inputs_always_give_the_same_answer():
    """No clock, no counter, no state."""
    args = dict(profile=_profile(), previous=_profile(poc=95.0),
                dynamic_poc=[98, 99, 100], spot=100.0, price_change=0.5)
    first = LQ.analyse(**args)
    for _ in range(5):
        assert LQ.analyse(**args) == first


# ══════════════════════════════════════════════════════════════════════
#  the context — computed once, read by every stage
# ══════════════════════════════════════════════════════════════════════

def _ctx(**over):
    kw = dict(profile=_profile(), vpfr={"poc": 100.5, "vah": 105.0, "val": 95.0},
              dynamic_poc=[98, 99, 100, 101], vob=[{"mid": 100.3}],
              dealer={"gamma_flip": 100.1}, spot=100.0, price_change=1.2,
              previous=_profile(poc=97.0),
              premium={"CALL": {"vp_poc": 120.0, "support": 112.0,
                                "acceptance": True, "cvd": 4200}},
              chain={"oi_wall": 24500, "gamma_flip_level": 24010,
                     "support_strength": 72, "resistance_strength": 40},
              cycle=3)
    kw.update(over)
    return LC.build(**kw)


def test_the_engine_runs_once_inside_the_context():
    """The specification's runtime rule: compute once, every stage reads."""
    src = (ROOT / "mios_v5" / "liquidity_context.py").read_text()
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_analyse"]
    assert len(calls) == 1


def test_the_context_computes_nothing_of_its_own():
    """A context that computes is a context whose cost nobody can see."""
    tree = ast.parse((ROOT / "mios_v5" / "liquidity_context.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"numpy", "pandas", "indicators", "streamlit",
                            "requests", "vob_minimal", "db"})


def test_every_field_carries_its_owner_and_the_path_it_was_read_from():
    """Principle 12 — a value with no owner cannot be inspected."""
    ctx = _ctx()
    for row in ctx.owners():
        assert row["owner"].startswith("Stage ")
        assert row["source"].split(".")[0] in LC.ROOTS


def test_no_two_fields_read_the_same_path():
    """Stage 71.95's binding rule. Two names for one fact drift."""
    seen = {}
    for row in LC.spec_rows():
        assert row["source"] not in seen, (row["field"], seen[row["source"]])
        seen[row["source"]] = row["field"]


def test_the_premium_group_is_entirely_stage_71_8():
    """The audit's finding: the premium chart is already covered. A second
    premium profile would duplicate a frozen stage."""
    for row in LC.spec_rows():
        if row["field"].startswith("premium."):
            assert row["stage"] == "71.8", row


def test_an_absent_producer_is_unknown_never_zero():
    ctx = _ctx(premium=None, chain=None)
    assert "premium" in ctx.meta["roots_missing"]
    assert not ctx.known("premium.poc")
    assert ctx.value("premium.poc") == LC.UNKNOWN
    assert ctx.known("index.poc"), "the index still reports"


def test_a_context_built_from_nothing_still_answers():
    """Nothing reported, so nothing is claimed — including the level count,
    which must not read as a measured zero."""
    ctx = LC.build()
    assert ctx.coverage()["known"] == 0, ctx.owners()
    assert ctx.get("index.poc").value == LC.UNKNOWN
    assert ctx.get("levels.clusters").value == LC.UNKNOWN
    assert ctx.get("no.such.field").known is False


def test_it_is_immutable_all_the_way_down():
    import dataclasses
    ctx = _ctx()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.index = {}
    with pytest.raises(TypeError):
        ctx.index["poc"] = None


def test_the_three_charts_are_all_carried():
    ctx = _ctx()
    assert ctx.known("index.poc")
    assert ctx.known("premium.poc")
    assert ctx.known("chain.oi_wall")


def test_the_per_side_premium_paths_expand_to_both_sides():
    ctx = _ctx(premium={"CALL": {"vp_poc": 120.0}, "PUT": {"vp_poc": 80.0}})
    value = ctx.get("premium.poc").value
    assert value["CALL"] == 120.0 and value["PUT"] == 80.0


def test_a_premium_with_neither_side_reads_unknown_not_an_empty_dict():
    ctx = _ctx(premium={})
    assert not ctx.known("premium.poc")


def test_coverage_reports_how_thin_the_cycle_was():
    full, thin = _ctx(), _ctx(premium=None, chain=None)
    assert full.coverage()["pct"] > thin.coverage()["pct"]
    assert thin.missing()


# ══════════════════════════════════════════════════════════════════════
#  the app wiring — computed once, and reading only keys with writers
# ══════════════════════════════════════════════════════════════════════

def test_the_app_builds_the_context_once_per_cycle():
    """The regression this repo has been bitten by twice: a layer that exists
    and nothing calls."""
    src = (ROOT / "vob_minimal.py").read_text()
    assert "from mios_v5.liquidity_context import build as _liq_build" in src
    assert src.count("_liq_build(") == 1, "the engine must run once per cycle"
    assert "st.session_state['_liquidity_context']" in src


def test_every_session_key_the_wiring_reads_has_a_writer():
    """Inventing `_dealer_levels` — a key nothing sets — would create the
    reader-without-a-writer regression on purpose."""
    import re
    src = (ROOT / "vob_minimal.py").read_text()
    block = src.split("Stage 74 — Liquidity Intelligence")[1] \
               .split("except Exception as _liq_err")[0]
    reads = set(re.findall(r"session_state\.get\('(_[a-z_]+)'\)", block))
    writers = set(re.findall(r"session_state\['(_[a-z_]+)'\] = ", src))
    writers |= set(re.findall(r'session_state\["(_[a-z_]+)"\] = ',
                              (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()))
    assert reads and not (reads - writers), reads - writers


def test_the_premium_structures_are_re_keyed_from_tuples():
    """`_premium_structures` is keyed by (side, strike). Passed as-is, every
    premium field would read UNKNOWN — present, wrong shape, no error."""
    src = (ROOT / "vob_minimal.py").read_text()
    block = src.split("Stage 74 — Liquidity Intelligence")[1] \
               .split("except Exception as _liq_err")[0]
    assert "isinstance(_k, tuple)" in block
    assert "('CALL', 'PUT')" in block


def test_the_premium_lag_is_recorded_rather_than_hidden():
    """A stale value a reader believes is live is worse than a missing one."""
    ctx = _ctx()
    assert "premium_lag" in ctx.meta
    src = (ROOT / "vob_minimal.py").read_text()
    assert "premium_lag=1 if _prem else 0" in src


def test_the_context_carries_the_engines_provenance():
    ctx = _ctx()
    engine = ctx.meta["engine"]
    assert engine["ready"] is True
    assert set(engine["consumed"]) == set(LQ.CONSUMED)


# ══════════════════════════════════════════════════════════════════════
#  the panel — Principle 12, and the heatmap
# ══════════════════════════════════════════════════════════════════════

def _heat_rows(n=6):
    out = []
    for i in range(n):
        bull, bear = (900 - i * 120), (200 + i * 120)
        out.append({"bin_low": 23900.0 + i * 20, "bin_high": 23920.0 + i * 20,
                    "total_volume": bull + bear, "bull_volume": bull,
                    "bear_volume": bear, "delta": bull - bear,
                    "ratio": max(0.08, 1.0 - abs(i - 3) * 0.22),
                    "node_type": "High" if i == 3 else "Average",
                    "sentiment": "Bullish" if bull > bear else "Bearish",
                    "sentiment_strength": abs(bull - bear) / (bull + bear) * 100})
    return out


def _panel_ctx():
    prof = {"rows": _heat_rows(), "poc_price": 23960.0,
            "value_area_high": 24000.0, "value_area_low": 23920.0,
            "price_high": 24020.0, "price_low": 23890.0}
    ctx = LC.build(profile=prof, vpfr={"poc": 23962.0, "vah": 24001.0},
                   dynamic_poc=[23930, 23940, 23950, 23950, 23960],
                   dealer={"gamma_flip": 23965.0, "support": 23900.0},
                   spot=23955.0, price_change=12.0,
                   previous={**prof, "poc_price": 23930.0}, cycle=7)
    return ctx, prof


def test_the_engine_has_somewhere_to_be_inspected():
    """Principle 12 — Stage 74 publishes eight facts nothing else computes."""
    from mios_v5.ui import liquidity_panel as P
    ctx, prof = _panel_ctx()
    html = P.liquidity_html(ctx, prof)
    assert "Stage 74" in html and len(html) > 500


def test_the_panel_shows_both_heatmaps_because_they_answer_different_questions():
    """"Where is the volume" and "who owns it" disagree at the interesting
    bins, so rendering one would force a choice between them."""
    from mios_v5.ui import liquidity_panel as P
    html = P.liquidity_html(*_panel_ctx())
    assert "how much traded here" in html
    assert "who traded here" in html


def test_the_heatmap_marks_the_point_of_control():
    """A heatmap without it is a gradient nobody can locate."""
    from mios_v5.ui import liquidity_panel as P
    assert "◄ POC" in P.heatmap_html(_heat_rows(), "liquidity", 23960.0)


def test_the_heatmap_reads_highest_price_first():
    """The way a profile is read on a chart, not the way the list is ordered."""
    from mios_v5.ui import liquidity_panel as P
    html = P.heatmap_html(_heat_rows(), "liquidity")
    assert html.index("24,020") < html.index("23,920")


def test_the_intensity_ramp_never_goes_grey():
    """Blue to yellow in plain RGB passes through grey at the quarter mark, and
    a desaturated bin reads as "no data" rather than "a little"."""
    import colorsys
    from mios_v5.ui import liquidity_panel as P
    for i in range(21):
        colour = P.ramp(i / 20)
        rgb = tuple(int(colour[j:j + 2], 16) / 255 for j in (1, 3, 5))
        _, _, sat = colorsys.rgb_to_hsv(*rgb)
        assert sat > 0.6, (i / 20, colour, sat)


def test_an_unmeasured_bin_is_not_the_cold_end_of_the_ramp():
    """A bin nobody measured and a bin that traded nothing are different."""
    from mios_v5.ui import liquidity_panel as P
    assert P.ramp(None) != P.ramp(0.0)


def test_the_ramp_is_monotonic_from_cold_to_hot():
    from mios_v5.ui import liquidity_panel as P
    assert P.ramp(0.0) == P._RAMP[0] and P.ramp(1.0) == P._RAMP[-1]
    assert P.ramp(-5) == P.ramp(0.0) and P.ramp(99) == P.ramp(1.0)


def test_a_cycle_with_no_level_source_says_so_rather_than_showing_none():
    """UNKNOWN levels must not render as "no support"."""
    from mios_v5.ui import liquidity_panel as P
    html = P._levels_html({"support": LQ.UNKNOWN, "resistance": LQ.UNKNOWN})
    assert "No level source reported" in html


def test_a_divergence_is_the_one_reading_that_gets_shouted():
    """It contradicts the rest of the stack, which is exactly why it is worth
    seeing."""
    from mios_v5.ui import liquidity_panel as P
    prof = {"rows": [{"ratio": 1.0, "sentiment": "Bearish",
                      "bull_volume": 100, "bear_volume": 900,
                      "bin_low": 1.0, "bin_high": 2.0}],
            "poc_price": 1.5, "price_high": 3.0, "price_low": 1.0}
    ctx = LC.build(profile=prof, price_change=5.0, spot=2.0,
                   previous=prof, dynamic_poc=[1.4, 1.5])
    assert ctx.value("index.divergence") == LQ.DIV_BEAR
    assert LQ.DIV_BEAR in P.liquidity_html(ctx, prof)


def test_the_panel_never_takes_the_tab_down():
    from mios_v5.ui import liquidity_panel as P
    for junk in (None, "a string", 42, {}, []):
        P.liquidity_html(junk)
        P.heatmap_html(junk)
    P.liquidity_html(LC.build(), None)


def test_the_panel_computes_nothing():
    """Presentation only — it may not import a producer."""
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "liquidity_panel.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"numpy", "pandas", "indicators", "streamlit",
                            "requests", "vob_minimal", "db"})


def test_the_panel_is_wired_into_the_dashboard():
    src = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    assert "from .liquidity_panel import render_liquidity" in src
    assert "_liquidity_context" in src
