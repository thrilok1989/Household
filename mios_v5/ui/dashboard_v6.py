"""MIOS V6 — Dashboard V6: the Market Intelligence Workstation.

Not a charting app. A **persistent header** plus six screens, each answering ONE
question:

    1 Decision      should I trade right now?          — the action panel
    2 Trading       where exactly?                     — the cockpit
    3 Intelligence  why does MIOS think that?          — the engine room
    4 History       what happened, and why?            — case studies
    5 Learning      is MIOS actually any good?         — analytics
    6 Replay        can I verify it, cycle by cycle?   — the recording

The split that makes it usable is **2 vs 3**: Dashboard 2 is where a trader
lives during the session and must carry only what you act on; Dashboard 3 is
diagnostics and can be as dense as it likes because you go there deliberately.
Mixing them produces a screen that is too noisy to trade from and too shallow to
debug with.

The header is sticky and identical on every tab. A trader reading a post-trade
review on Dashboard 4 is exactly the one most likely to have stopped watching
the tape — the header is what stops a flow shift happening off-screen.

Highlight CHANGES, not static values: a panel that repeats the same number every
cycle trains the eye to skip it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..final_read import build_final_read, section
from ..sr_intel import build_level_intel, rank_levels
from ..thesis import build_thesis, market_controller, recent_changes

_TABS = ["🎯 Decision", "📈 Trading", "🧭 Intelligence",
         "📒 History", "🎓 Learning", "⏪ Replay"]

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:10px 12px;margin-bottom:8px")


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _fmt(v) -> str:
    try:
        return f"₹{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def render_dashboard_v6(state=None, db=None) -> None:
    import streamlit as st

    if state is None or not getattr(state, "results", None):
        st.info("MIOS pipeline warming up — Dashboard V6 pending first pass.")
        return
    fr = build_final_read(state) or {}

    # ── the persistent header: identical on every tab, above the tab bar ──
    from .header_panel import header_html
    from ..header import alerts as header_alerts
    from ..header import build as header_tiles
    spot = None
    try:
        spot = (st.session_state.get("_cached_option_data") or {}).get("underlying")
    except Exception:
        spot = None
    st.markdown(header_html(header_tiles(fr, spot), header_alerts(fr)),
                unsafe_allow_html=True)

    tabs = st.tabs(_TABS)
    with tabs[0]:
        _decision_center(st, fr)
    with tabs[1]:
        _trading_screen(st, fr, state)
    with tabs[2]:
        _intelligence(st, fr, state)
    with tabs[3]:
        _history(st, db)
    with tabs[4]:
        _learning(st, db, fr)
    with tabs[5]:
        _replay(st, db)


# ── 1 · DECISION ────────────────────────────────────────────────────────
def _run_execution_chain(st) -> None:
    """Stages 72 → 73 → 72.9, run once per cycle from the assembled context.

    Each stage takes the previous one's output and adds one thing:

    * **72** reads the `TradingContext` and nothing else, and returns a frozen
      `EntryDecision` carrying its own id, version, created_at and hash.
    * **73** takes that decision and the same context and returns a lifecycle
      action — it never mints its own id, it carries 72's forward.
    * **72.9** takes both and prepares a dispatch.

    ⚠️ **It sends only when a human has switched sending on.** The transport
    is read from `session_state["_mios_transport"]`, which the app sets *only*
    while the "MIOS V6 Telegram signals" toggle is on. With the toggle off the
    key is absent, the dispatcher receives `None`, builds the payload, decides
    whether it *would* send, and reports `NOT_SENT` — exactly as before.

    Stage 72.9 is still `VALIDATED_SIMULATED` with `freeze_ready: False`: five
    hundred live dispatches have not happened. The toggle is the human decision
    that report asks for, not a replacement for it, and the panel says so.

    The transport is a **callable taken from the app**. This module still
    imports no network client — `import requests` inside `mios_v5` is a named
    forbidden failure mode, and reading a function somebody else built is how
    that rule and a live send coexist.

    A registry is still used, because the claim protocol is what makes the
    dispatch decision meaningful at all: without one, "would this be a
    duplicate?" has no answer. `MemoryRegistry` lasts a session, which is the
    right scope for a stage that sends nothing.

    Advisory throughout, and every stage already promises never to raise — the
    guard here is for the wiring, not for them.
    """
    ctx = st.session_state.get("_trading_context")
    if ctx is None:
        # ⚠️ This used to `return` silently, and it was one of FOUR ways the
        # execution chain could fail to run without saying so. The trader saw
        # an empty space, which reads exactly like "no trade" — the one
        # misreading that makes a working system look broken. Say it instead.
        st.session_state["_entry_decision"] = None
        _render_chain_panel(
            st, "Stage 71.95 did not publish a trading context this cycle, so "
                "Stage 72 had nothing to read. Common causes: the option chain "
                "has not arrived yet, or the strike picker found no ATM ladder.")
        return
    try:
        from ..dispatcher import MemoryRegistry
        from ..dispatcher import run as _dispatch
        from ..entry_engine import run as _entry
        from ..trade_lifecycle import run as _lifecycle

        decision = _entry(ctx)
        st.session_state["_entry_decision"] = decision

        lifecycle = _lifecycle(decision, ctx)
        st.session_state["_lifecycle_decision"] = lifecycle

        # One registry for the session, so a decision already "dispatched" this
        # session is recognised as a duplicate rather than re-prepared.
        registry = st.session_state.get("_dispatch_registry")
        if registry is None:
            registry = MemoryRegistry()
            st.session_state["_dispatch_registry"] = registry

        # Absent unless the human toggle is on → `None` → prepares only.
        transport = st.session_state.get("_mios_transport")
        st.session_state["_dispatch_decision"] = _dispatch(
            decision, ctx, lifecycle=lifecycle, registry=registry,
            transport=transport)
        # The last decision worth keeping on screen while the current read is
        # WAIT. Written only when there IS one, so a quiet cycle cannot erase
        # the morning's signal — a blank panel in a slow market is precisely
        # what makes a working system feel broken.
        from .execution_panel import remember_signal
        _last = remember_signal(decision)
        if _last:
            st.session_state["_last_valid_signal"] = _last
    except Exception as err:
        st.session_state["_entry_decision"] = None
        _render_chain_panel(st, f"The chain raised on this cycle: {err}")
        return

    _render_chain_panel(st)


def _render_chain_panel(st, not_run_reason: str = "") -> None:
    """Draw the execution panel from whatever session state holds.

    Split out so the three failure paths above render the SAME panel the happy
    path does, rather than a bare caption. A caption reading "Strike Validation
    unavailable" while the real casualty was Stage 72 is how this stayed
    invisible.
    """
    try:
        from .execution_panel import render_execution
        render_execution(st, st.session_state.get("_entry_decision"),
                         st.session_state.get("_lifecycle_decision"),
                         st.session_state.get("_dispatch_decision"),
                         last_signal=st.session_state.get("_last_valid_signal"),
                         not_run_reason=not_run_reason)
    except Exception as err:
        st.caption(f"Execution panel unavailable: {err}")


def _decision_center(st, fr: Dict[str, Any]) -> None:
    """Should I trade right now? — answerable in 3-5 seconds.

    Nothing else is allowed to compete here. The checklist, the risk breakdown
    and the V6 voter table all moved to Dashboard 3; this screen carries the
    verdict, the ticket, the two biases and the three questions, and stops.
    """
    from .decision_panel import render_decision_panel
    from .explain_panel import decision_explanation_html
    from ..checklist import build as _build_checklist
    from ..explain_decision import explain as _explain

    # ── 🗓 Stage 68 — what KIND of day this is. First, because every read
    # below has to be interpreted against it: the same rejection at support is
    # a buy on a trend day and a fade on a pin day.
    from .day_type_panel import day_type_card
    from .session_panel import session_card
    st.markdown(day_type_card(fr.get("day_classification")),
                unsafe_allow_html=True)
    # 🕘 Stage 69 — WHERE in the day. A 09:20 breakout is not a 13:00
    # breakout, and the day type alone does not say which one this is.
    st.markdown(session_card(fr.get("session_intel")), unsafe_allow_html=True)

    dec = fr.get("decision_v2") or {}
    render_decision_panel(dec)

    cl = _build_checklist(fr)
    st.markdown(decision_explanation_html(_explain(fr, cl)),
                unsafe_allow_html=True)

    _ticket(st, fr, dec)

    from .bias_compare import bias_compare_html
    from ..v6_bias import compare as _v6_compare
    st.markdown(bias_compare_html(_v6_compare(fr)), unsafe_allow_html=True)

    t = build_thesis(fr)
    c1, c2, c3 = st.columns(3)
    for col, title, items, colour in (
            (c1, "WHY", t["why"], "#7fe8b0"),
            (c2, "EXPECT", t["expect"], "#9fd3ff"),
            (c3, "INVALIDATION", t["invalidation"], "#ffcc66")):
        with col:
            col.markdown(
                f"<div style='{_CARD};min-height:132px'>"
                f"<div style='font-size:10.5px;letter-spacing:.12em;"
                f"color:#cfd9e6;text-transform:uppercase'>{title}</div>"
                + "".join(f"<div style='font-size:12.5px;margin-top:3px;"
                          f"color:{colour}'>• {i}</div>" for i in items)
                + "</div>", unsafe_allow_html=True)


def _ticket(st, fr: Dict[str, Any], dec: Dict[str, Any]) -> None:
    """Market quality · entry · stop · trail · R:R — the trade in six numbers."""
    from ..explain_decision import market_quality
    from ..risk_explain import analyse as _risk
    ra = _risk(fr)
    trail = dec.get("trail") or {}
    rr = (ra.get("rr") or {}) if ra.get("available") else {}
    mq = market_quality(fr)
    cells = [
        ("Market Quality",
         f"{mq['grade']}" + (f" {mq['score']}%" if mq.get("score") is not None
                             else ""), mq["colour"]),
        ("Entry", _fmt(dec.get("entry")), "#00ff88"),
        ("Stop", _fmt(dec.get("stop")), "#ff6666"),
        ("Trail", (_fmt(trail.get("stop")) if trail.get("stop")
                   else (trail.get("mode") or "—")), "#a78bfa"),
        ("Target", (ra.get("target") or {}).get("display", "—")
         if ra.get("available") else "—", "#7fe8b0"),
        ("R:R", rr.get("display", "—"),
         "#00ff88" if rr.get("acceptable") else "#ffd000"),
    ]
    st.markdown(
        "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px'>"
        + "".join(
            f"<div style='flex:1;min-width:104px;{_CARD};margin-bottom:0'>"
            f"<div style='font-size:9.5px;letter-spacing:.10em;color:#cfd9e6;"
            f"text-transform:uppercase'>{k}</div>"
            f"<div style='font-size:17px;font-weight:800;color:{c}'>{v}</div>"
            f"</div>" for k, v, c in cells)
        + "</div>", unsafe_allow_html=True)


# ── 2 · TRADING TERMINAL ────────────────────────────────────────────────
def _trading_screen(st, fr: Dict[str, Any], state) -> None:
    """The execution screen — index, ATM call and ATM put evolving together.

    Layout: NIFTY large on the left, the two option legs stacked on the right,
    a CALL-vs-PUT ribbon between them, and the trade banner underneath. This is
    for execution, not analysis: everything here is something you act on, and
    the diagnostics live on Dashboard 3.
    """
    from .day_type_panel import day_type_badge
    from .session_panel import session_strip
    from .terminal_panel import (compare_ribbon_html, intelligence_html,
                                 leg_card_html, market_ribbon_html,
                                 recommendation_html)
    from ..terminal import (compare_ribbon, dominance, market_ribbon,
                            option_intelligence, recommendation)

    call, put, call_tag, put_tag = _leg_reads(st, fr)
    cmp_ = compare_ribbon(call, put)
    dom = dominance(call, put)

    # ── the header stack, in the order a trader reads it ──
    # Command Center answers "what is the market doing", Stage 71 answers
    # "where is the opportunity". Both belong above the charts; everything
    # else moved below (see the note on the context strips further down).
    _command_center(st, fr)

    # ── Stage 71 — the opportunity read, directly above the charts ──
    # A trader opening this tab should read WHERE the opportunity is before
    # looking at price. Everything else that used to sit here (day type,
    # session, market ribbon) has moved BELOW the charts rather than being
    # deleted: four blocks before a 660px chart puts execution below the fold
    # on a laptop, and this screen exists to execute on.
    _opportunity(st, fr)

    # ── Stage 71.8 — is the strike the trader picked worth trading? ──
    # Directly under 71.7, because the two are one question asked twice: 71.7
    # names a side, 71.8 grades the strike on it. Reading the side without the
    # strike grade is how a correct direction gets traded through an illiquid
    # option.
    _strike_validation(st, fr)

    # ── the execution chain · Stages 72 → 73 → 72.9 ────────────────────
    # Called HERE, at the top level, not from inside `_strike_validation`.
    #
    # It used to live in that function's body, and that placement is what made
    # the whole chain invisible. `_strike_validation` returns early when the ATM
    # ladder has not been published, and it wraps ~145 lines in a single
    # `except` — so whenever either fired, Stage 72 never ran, `_entry_decision`
    # was never written, the panel rendered `""`, and the only thing on screen
    # was a caption about the strike picker. Three unrelated failures all
    # presenting as "no signal", none of them saying the execution chain had not
    # run.
    #
    # It reads `_trading_context` out of session state, which `_strike_validation`
    # publishes before it returns, so nothing about the data flow depends on the
    # nesting — only the failure behaviour did. Out here, a strike-picker
    # problem can no longer take the trade verdict down with it.
    _run_execution_chain(st)

    _terminal_chart(st, fr, call_tag, put_tag, dom)

    # ── the same liquidity bars, per leg, directly under the charts ────
    # The chart draws each leg's profile as a translucent band behind the
    # candles, which shows WHERE the volume sits but cannot be read off. These
    # are the identical bins as bars, so a level can be measured rather than
    # eyeballed through a candle.
    #
    # Called out here rather than inside `_terminal_chart` on purpose: that
    # function owns a Plotly figure and its own failure mode, and nesting this
    # inside it would put a second panel behind the chart's `try`. That is
    # exactly the nesting that made the execution chain invisible.
    try:
        from .liquidity_panel import render_leg_heatmaps
        render_leg_heatmaps(st, st.session_state.get("_leg_profiles"))
    except Exception as err:
        st.caption(f"Premium liquidity unavailable: {err}")

    # ── market facts + the V5 ‖ V6 divergence ──
    # The slim Trade Card: ONLY what this tab does not already own. Bias,
    # quality and timing belong to the Opportunity Matrix (per horizon, which
    # is more than one blended verdict), S/R to `_sr_intelligence` below, and
    # the Stage 52 ladder to the Cockpit. What is left is the measurements
    # every version reads, and the one comparison that matters exactly when
    # the two generations disagree.
    from .trade_card_panel import render_slim_trade_card
    render_slim_trade_card(st, fr, _spot_now(st, fr))

    # context strips, relocated from above the chart — same content, same
    # order, no longer competing with the execution surface for the fold
    st.markdown(day_type_badge(fr.get("day_classification")),
                unsafe_allow_html=True)
    st.markdown(session_strip(fr.get("session_intel")), unsafe_allow_html=True)
    st.markdown(market_ribbon_html(market_ribbon(fr)), unsafe_allow_html=True)

    # the leg reads sit under the charts they describe, in the same order
    lc, rc = st.columns([0.60, 0.40])
    with lc:
        _war_zone(st, fr)
        _price_map(st, fr)
    with rc:
        st.markdown(leg_card_html(call, "ATM CALL"), unsafe_allow_html=True)
        st.markdown(compare_ribbon_html(cmp_), unsafe_allow_html=True)
        st.markdown(leg_card_html(put, "ATM PUT"), unsafe_allow_html=True)

    # ── the execution layer: where in the trade life are we? ──
    # Stage 52 runs the whole ladder every cycle and was shown as one badge.
    # A badge says where you are; a checklist says how far along, what is
    # satisfied, and what is left. Placed under the charts because it is trade
    # MANAGEMENT — you reach it after deciding, not before.
    from .cockpit_panel import render_cockpit
    render_cockpit(st, fr)

    st.markdown(intelligence_html(option_intelligence(fr, call, put)),
                unsafe_allow_html=True)
    st.markdown(recommendation_html(recommendation(fr, call, put)),
                unsafe_allow_html=True)

    st.markdown("---")
    _sr_intelligence(st, fr, state)

    from .narrator_panel import narrator_html
    st.markdown(narrator_html(st.session_state.get("_mios_beats"),
                              title="🎙 Live narration"),
                unsafe_allow_html=True)


def _opportunity(st, fr: Dict[str, Any]) -> None:
    """Stage 71 · 71.5 — the Trade Opportunity Matrix.

    The whole pipeline in one call, and every input arrives as a parameter:

        final_read  ──┐
                      ├─► build_matrix ─► enrich ─► render
        native_reads ─┘

    `_all_bias_rows` is the app's own published signal table — the same rows
    the All-Bias dashboard renders. It is read HERE, in the panel, and passed
    down, because `opportunity.py` may not reach into session_state.

    The previous cycle is kept for Stage 71.5's rotation read. It is stored
    after enrichment so a rotation is always measured against a matrix that
    actually rendered, never against a half-built one.
    """
    try:
        from ..opportunity import build_matrix, native_reads_from_rows
        from ..opportunity import _producer_reads
        from ..opportunity_intel import enrich
        from .opportunity_panel import render_opportunity_panel

        native = native_reads_from_rows(st.session_state.get("_all_bias_rows"))
        matrix = build_matrix(fr, native)
        matrix = enrich(matrix, fr, _producer_reads(fr, native),
                        previous=st.session_state.get("_opportunity_prev"))

        # ⚡ Stage 71.7 — Premium Energy & Spike, folded into Stage 71 rather
        # than sitting in its own section. 71 ranks the horizons and names a
        # side; 71.7 says whether that premium is actually being traded. Split
        # apart, the ranking gets read without the confirmation.
        #
        # `leg_rows` and `leg_totals` are passed in: `premium_energy` may not
        # touch session_state, the same rule this module already follows for
        # `native_reads`. The glyph rows carry DIRECTION; `_atm_leg_ltf_delta`
        # carries the CBV/CSV/CVD volumes the spec makes mandatory, and the two
        # are different questions about the same legs. Stability is read off
        # `matrix` so it is not computed twice.
        premium = None
        try:
            from ..premium_energy import build as _pe_build
            _legs = (st.session_state.get("_leg_bias_cache") or (None, None))[0]
            # `sid_…` duplicates of every leg live in the same store so the
            # render loop can find an entry by either key; summing both would
            # count each leg's volume twice.
            _totals = [(tag, tot) for tag, tot
                       in (st.session_state.get("_atm_leg_ltf_delta") or {}).items()
                       if not str(tag).startswith("sid_")]
            premium = _pe_build(fr, leg_rows=_legs, matrix=matrix,
                                leg_totals=_totals,
                                previous=st.session_state.get("_premium_energy_prev"))
        except Exception as _pe_err:
            st.caption(f"Premium Energy unavailable: {_pe_err}")

        render_opportunity_panel(st, matrix, premium)
        # this cycle's matrix, for Stage 71.95. `_prev` is next cycle's
        # rotation baseline — the same object in two roles, named apart.
        st.session_state["_opportunity_matrix"] = matrix
        st.session_state["_opportunity_prev"] = matrix
        if premium is not None:
            # `_premium_energy` is THIS cycle's, which Stage 71.8 reads.
            # `_premium_energy_prev` is the rotation/shift baseline for the
            # NEXT cycle. One object, two roles, and naming them the same made
            # 71.8 look like it was validating against a stale read.
            st.session_state["_premium_energy"] = premium
            st.session_state["_premium_energy_prev"] = premium
    except Exception as err:
        # advisory panel — it may never take the execution screen down with it
        st.caption(f"Trade Opportunity Matrix unavailable: {err}")


def _leg_reads(st, fr: Dict[str, Any]):
    """Assemble both legs from the caches the app already fills.

    Nothing is computed here — Stage 50 supplies the LTP × OI state, the
    leg-bias table supplies the signal tally, the VOB store supplies the zones
    and the leg Entry Gate supplies premium levels when it has armed one.
    """
    from ..terminal import leg_read

    ltp = fr.get("ltp_behaviour") or {}
    rows, _ = (st.session_state.get("_leg_bias_cache") or ([], None))
    setups = st.session_state.get("_entry_armed_setups") or {}
    live = st.session_state.get("_entry_signal_open") or {}
    absorb = fr.get("absorption") or {}

    _, _, call_tag, put_tag = _atm_tags(st)

    def _row(tag):
        return next((r for r in (rows or []) if r.get("Leg") == tag), {})

    def _one(side, tag):
        return leg_read(
            side, tag=tag,
            ltp_side=ltp.get("calls" if side == "CE" else "puts"),
            bias_row=_row(tag),
            vob_zones=_leg_store(st, "_atm_leg_vob_volume", tag),
            setup=setups.get(tag), open_sig=live.get(tag),
            absorption=absorb,
            money_flow=_leg_money_flow(st, tag, _row(tag)))

    return _one("CE", call_tag), _one("PE", put_tag), call_tag, put_tag


def _strike_ladder(st, fr: Dict[str, Any]) -> Tuple[List[float], Optional[float]]:
    """The ATM±3 strikes the picker offers, and the ATM itself.

    Taken from `_cockpit_ctx`, which `_publish_atm_legs` fills with security ids
    for exactly this range. Using the ids rather than the raw chain means the
    picker can only offer strikes the app can actually fetch candles for — a
    dropdown entry with no leg behind it would validate against nothing.
    """
    ctx = st.session_state.get("_cockpit_ctx") or {}
    atm, gap = _num(ctx.get("atm"), None), _num(ctx.get("gap"), None)
    if atm is None:
        return [], None
    step = gap or 50.0
    return [atm + k * step for k in (-3, -2, -1, 0, 1, 2, 3)], atm


def _strike_selection(st, fr: Dict[str, Any]) -> Dict[str, Any]:
    """The trader's chosen CALL and PUT strike, defaulting to ATM.

    Held in `session_state` so it survives every rerun — a picker that reset to
    ATM on each 20-second refresh would be unusable. The ATM itself drifts
    through the day, so a stored strike that has fallen outside the ±3 window is
    dropped back to ATM rather than kept: validating a strike the app no longer
    fetches would report on stale candles.

    ⚪ Not persisted to Supabase. `sql/022_vob_app_state.sql` exists and its
    writer was removed in the V6 reduction, so a selection survives reruns but
    not a restart. Declared rather than half-built.
    """
    ladder, atm = _strike_ladder(st, fr)
    if not ladder:
        return {}
    store = st.session_state.setdefault("_selected_strikes", {})
    picked: Dict[str, Any] = {}
    cols = st.columns([1, 1, 3])
    for col, side in ((cols[0], "CALL"), (cols[1], "PUT")):
        cur = _num(store.get(side), None)
        if cur is None or not any(abs(cur - s) < 0.5 for s in ladder):
            cur = atm
        idx = min(range(len(ladder)), key=lambda i: abs(ladder[i] - cur))
        with col:
            choice = st.selectbox(
                f"{side} strike", ladder, index=idx,
                format_func=lambda v: (f"{v:.0f}" if abs(v - atm) < 0.5
                                       else f"{v:.0f}  ({v - atm:+.0f})"),
                key=f"_strike_pick_{side}")
        store[side] = float(choice)
        picked[side] = float(choice)
    return picked


def _leg_frame(st, tag):
    """The selected leg's own candles, or `None`.

    RVOL and Volume Climax are the only two Premium Structure reads that need a
    raw series — the audit found `avg_vol_1m` computed and discarded in two
    places, and nothing published it.
    """
    dfs = st.session_state.get("_atm_leg_dfs") or {}
    for key in _leg_key_variants(st, tag):
        frame = dfs.get(key)
        if frame is not None and not getattr(frame, "empty", True):
            return frame
    return None


def _leg_reads_for(st, selected: Dict[str, Any]) -> Dict[Any, Dict[str, Any]]:
    """Each selected strike's Premium Structure, keyed `(side, strike)`.

    This function is the *extraction* half of the contract: it pulls finished
    engine output out of session_state and hands it to
    `premium_structure.analyse`, which may touch neither. Stage 71.8 then reads
    the structure rather than deriving one — one owner for the premium's
    structure, which is why Premium Structure exists.

    A wing strike outside the ATM±1 fetch has no leg entry, so its structure
    reports `UNKNOWN` rather than borrowing the ATM's. Substituting a
    neighbour's levels would grade the wrong option with nothing on screen to
    say so.
    """
    from ..premium_structure import analyse as _ps_analyse

    out: Dict[Any, Dict[str, Any]] = {}
    for side, strike in (selected or {}).items():
        s = _num(strike, None)
        if s is None:
            continue
        code = "CE" if side == "CALL" else "PE"
        tag = f"{code} {s:.0f}"
        frame = _leg_frame(st, tag)
        ltp = None
        candles = None
        vpfr = mfp = ignition = None
        if frame is not None:
            try:
                ltp = float(frame["close"].iloc[-1])
                candles = frame.tail(60).to_dict("records")
            except Exception:
                candles = None
            # VPFR is published for ATM±1 only, so a wing strike needs it built
            # here — from the app's own `compute_vpfr`, the one POC owner the
            # audit chose. `premium_structure` receives the result and computes
            # no profile of its own.
            builders = st.session_state.get("_premium_builders") or {}
            for key, target in (("vpfr", "vpfr"), ("mfp", "mfp"),
                                ("ignition", "ignition")):
                fn = builders.get(key)
                if not fn:
                    continue
                try:
                    val = fn(frame)
                except Exception:
                    val = None
                if target == "vpfr":
                    vpfr = val
                elif target == "mfp":
                    mfp = val
                else:
                    ignition = val

        row = next((r for r in ((st.session_state.get("_leg_bias_cache")
                                 or ([], None))[0] or [])
                    if str(r.get("Leg", "")).endswith(f"{code} {s:.0f}")), {})
        absorb = {"🟢": "bull", "🔴": "bear"}.get(
            str(row.get("Absorb") or "").strip()[:1])

        out[(side, s)] = {
            "structure": _ps_analyse(
                sr=_leg_store(st, "_atm_leg_sr_behavior", tag) or {},
                vob=_leg_store(st, "_atm_leg_vob_volume", tag) or [],
                vidya=_leg_store(st, "_atm_leg_vidya", tag) or {},
                flow=_leg_store(st, "_atm_leg_ltf_delta", tag) or {},
                vpfr=vpfr, mfp=mfp, ignition=ignition,
                candles=candles, absorb=absorb, ltp=ltp),
        }
    return out


def _strike_validation(st, fr: Dict[str, Any]) -> None:
    """Stage 71.8 — the strike picker and its validation.

    Every input arrives as a parameter, the rule `opportunity.py` and
    `premium_energy.py` already follow: the panel extracts from session_state,
    the stage interprets. Stage 71.7's finished output is passed straight in so
    71.8 re-derives none of it.
    """
    try:
        from ..strike_validation import build as _sv_build
        from .strike_validation_panel import render_strike_validation

        selected = _strike_selection(st, fr)
        if not selected:
            st.caption("Strike picker unavailable — the ATM ladder has not "
                       "been published yet.")
            return

        summary = ((st.session_state.get("_cached_option_data") or {})
                   .get("df_summary"))
        rows = (summary.to_dict("records")
                if summary is not None and not getattr(summary, "empty", True)
                else [])

        # built once and consumed twice — by the validation below and by the
        # chart overlay. Analysing the same leg in two places would be the
        # duplication Premium Structure exists to end.
        leg_reads = _leg_reads_for(st, selected)

        data = _sv_build(
            fr,
            premium=st.session_state.get("_premium_energy"),
            chain_rows=rows,
            selected=selected,
            leg_reads=leg_reads,
            spot=_spot_now(st, fr))
        render_strike_validation(st, data)
        st.session_state["_strike_validation"] = data

        # Built once and consumed three times — by Stage 71.85 below, by the
        # context, and by the chart overlay.
        _structures = {s: v["structure"]
                       for (s, _k), v in (leg_reads or {}).items()
                       if isinstance(v, dict) and v.get("structure")}

        # ── Stage 71.85 — Premium LTP Behaviour ────────────────────────
        # Runs between 71.8 and the context, which is the only place it can:
        # it consumes the structures built immediately above and its output is
        # a context root. Each side is analysed alone — the call takes one
        # premium and never sees the other.
        try:
            from ..premium_behaviour import build as _pb_build
            _behaviour = _pb_build(
                structure=_structures,
                energy=st.session_state.get("_premium_energy"),
                fr=fr, validation=data)
        except Exception as _pb_err:
            _behaviour = None
            st.caption(f"Premium Behaviour unavailable: {_pb_err}")
        st.session_state["_premium_behaviour"] = _behaviour

        # ── Stage 71.95 — the Unified Trading Context ──────────────────
        # Assembled here because this is the last point in the cycle where all
        # six roots exist: `final_read` from the pass, the matrix and 71.7 from
        # `_opportunity`, 71.8 plus the structures from just above, and 71.85
        # from immediately here. Building it earlier would freeze a context
        # missing half its fields.
        #
        # Nothing renders it. It exists so Stage 72 reads one object instead of
        # thirty, and every value in it names the stage that produced it.
        try:
            from ..trading_context import build as _ctx_build
            st.session_state["_trading_context"] = _ctx_build(
                fr=fr, matrix=st.session_state.get("_opportunity_matrix"),
                premium=st.session_state.get("_premium_energy"),
                validation=data,
                structure=_structures,
                behaviour=_behaviour,
                cycle=st.session_state.get("_render_seq"))
        except Exception as _ctx_err:
            st.session_state["_trading_context"] = None
            st.caption(f"Trading Context unavailable: {_ctx_err}")
        # the chart overlay reads these; published here so the structure is
        # built once per cycle and consumed by the validation, Stage 71.85 and
        # the chart, rather than analysed three times
        st.session_state["_premium_structures"] = {
            k: v["structure"] for k, v in (leg_reads or {}).items()
            if isinstance(v, dict) and v.get("structure")}
        # Principle 12: `premium.behaviour` is an eleventh weight in Stage 72's
        # entry score, so it moves decisions — and a value that moves decisions
        # must be inspectable somewhere.
        from .premium_behaviour_panel import render_premium_behaviour
        render_premium_behaviour(st, _behaviour)

        # ── Stage 74 — Liquidity Intelligence ──────────────────────────
        # Principle 12 again, and pre-emptively: Stage 74 publishes eight facts
        # nothing else computes, and the moment a stage reads one the rule
        # binds. Rendering it before the stage injection is deliberate — a
        # number nobody has looked at should not become load-bearing in twenty
        # consumers.
        #
        # The context is what a consuming stage would read; the raw profile is
        # passed alongside because the heatmap needs per-bin rows, which the
        # context deliberately does not carry (thirty bins are a chart, not a
        # field).
        from .liquidity_panel import (render_calibration, render_collection,
                                      render_liquidity)
        render_liquidity(st, st.session_state.get("_liquidity_context"),
                         st.session_state.get("_money_flow_data"))

        # Whether telemetry is actually being written. Silent when healthy;
        # loud when the migration is missing, because that failure is otherwise
        # invisible for a week.
        render_collection(st, st.session_state.get("_liq_telemetry_status"))

        # ── Stage 74 calibration verdict ───────────────────────────────
        # A different question from the panel above: that one says what
        # liquidity is doing, this says whether those numbers can be trusted
        # yet. Read from a week of telemetry, and it must stay on screen until
        # the verdict is HEALTHY — injecting Stage 42 on an untested curve is
        # the expensive mistake this whole exercise exists to avoid.
        try:
            from ..liquidity_telemetry import summarise as _liq_summary
            _telemetry = (db.get_liquidity_telemetry(days=7)
                          if db is not None
                          and hasattr(db, "get_liquidity_telemetry") else None)
            if _telemetry:
                render_calibration(st, _liq_summary(_telemetry))
        except Exception:
            pass
    except Exception as err:
        # advisory panel — it may never take the execution screen down with it
        st.caption(f"Strike Validation unavailable: {err}")


def _command_center(st, fr: Dict[str, Any]) -> None:
    """The six header cards, assembled from engines that already ran.

    Each source is fetched independently and guarded: a thesis that fails must
    cost one card, not the whole header. A header that vanishes takes the
    decision off the screen with it.
    """
    from ..command_center import build
    from .command_center_panel import render_command_center

    def _try(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            return None

    quality = _try(lambda: __import__(
        "mios_v5.explain_decision", fromlist=["market_quality"]
    ).market_quality(fr))
    risk = _try(lambda: __import__(
        "mios_v5.risk_explain", fromlist=["analyse"]).analyse(fr))
    # `fr["families"]` is the family dict (final_read.py:195). `fr["evidence"]`
    # is a LIST of narrative lines — reading "families" off it raised
    # `'list' object has no attribute 'get'` and took the whole Trading tab
    # down, but only once evidence had content. Empty evidence hit the `or {}`
    # and passed, which is why this survived. `order_flow_families` below has
    # always read the right key.
    controller = _try(market_controller, fr.get("families"))
    thesis = _try(build_thesis, fr)

    try:
        cc = build(fr, spot=_spot_now(st, fr), quality=quality, risk=risk,
                   controller=controller, thesis=thesis)
        render_command_center(st, cc)
    except Exception as err:
        st.caption(f"Command Center unavailable: {err}")


def order_flow_families(st, fr: Optional[Dict[str, Any]] = None
                        ) -> List[Dict[str, Any]]:
    """The Order Flow Family for NIFTY, the ATM Call and the ATM Put.

    Every value is read from a cache V5 already filled. Nothing here computes
    money flow, delta, CVD, CSV, CBV, volume or VOB — those have exactly one
    implementation each, and it is not in V6.
    """
    from ..order_flow import family

    fr = fr or {}
    _, _, ce, pe = _atm_tags(st)

    mf = st.session_state.get("_money_flow_data") or {}
    vd = (st.session_state.get("_volume_delta_data") or {}).get("summary") or {}
    nifty = {
        "money_flow": mf.get("sentiment") or mf.get("top_sentiment"),
        "candle_delta": vd.get("bias") or vd.get("total_delta"),
        "cvd": vd.get("total_delta"),
        "cbv": vd.get("total_buy_volume"),
        "csv": (-_num(vd.get("total_sell_volume"), 0.0)
                if vd.get("total_sell_volume") is not None else None),
        "volume": vd.get("delta_ratio"),
        "vob": (fr.get("ltp_behaviour") or {}).get("vob"),
    }

    out = [{"instrument": "NIFTY", "family": family(nifty)}]
    for label, tag in (("ATM Call", ce), ("ATM Put", pe)):
        out.append({"instrument": label or "ATM leg", "tag": tag,
                    "family": family(_leg_flow_readings(st, tag))})
    return out


def _leg_flow_readings(st, tag) -> Dict[str, Any]:
    """One leg's seven order-flow members, from the leg caches as they stand."""
    if not tag:
        return {}
    row = next((r for r in ((st.session_state.get("_leg_bias_cache")
                             or ([], None))[0] or [])
                if r.get("Leg") == tag), {})
    dv = _leg_store(st, "_atm_leg_ltf_delta", tag) or {}
    zones = _leg_store(st, "_atm_leg_vob_volume", tag) or []

    buy = _num(dv.get("buy_total"), None)
    sell = _num(dv.get("sell_total"), None)
    building = sum(1 for z in zones
                   if str(z.get("status") or "").upper() == "BUILDING")
    fading = sum(1 for z in zones
                 if str(z.get("status") or "").upper() == "FADING")
    return {
        "money_flow": row.get("MFP"),
        "candle_delta": row.get("Div") or _num(dv.get("delta"), None),
        "cvd": row.get("CVD"),
        "cbv": buy,
        # CSV is sell pressure — negated so "more selling" reads bearish
        # rather than the family treating a big positive number as a bid
        "csv": (-sell if sell is not None else None),
        "volume": _num(dv.get("delta_pct"), None),
        "vob": (building - fading) if zones else None,
    }


def _spot_now(st, fr: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """The freshest spot available, live LTP first.

    Ordered the same way the runner orders it, so a level is sided against the
    same price the rest of the screen is quoting.
    """
    for src in (st.session_state.get("_nifty_spot_live"),
                (st.session_state.get("_cached_option_data") or {}).get("underlying"),
                (fr or {}).get("spot")):
        v = _num(src, None)
        if v is not None and v > 0:
            return v
    return None


def _leg_key_variants(st, tag) -> List[str]:
    """Every key the same leg is stored under.

    The app writes its per-leg caches under three different names and this cost
    the terminal its VOB read entirely:

      * `_atm_leg_dfs`         → "ATM CE 24250"   (with the ATM offset tag)
      * `_atm_leg_vob_volume`  → "CE 24250"       (`leg_name`, no tag)
      * every store, also      → "sid_65806"

    `atm_legs()` hands back the first form, so `vob.get(tag)` looked up a key
    that store never contains. It matched nothing on every cycle, which is why
    VOB and Money Flow read "—" no matter what the market did.
    """
    if not tag:
        return []
    out = [str(tag)]
    parts = str(tag).split()
    if len(parts) >= 3:
        out.append(" ".join(parts[1:]))          # drop the "ATM±n" prefix
    try:
        entry = (st.session_state.get("_atm_leg_sids") or {}).get(tag)
        sid = entry[0] if isinstance(entry, (list, tuple)) else entry
        if sid:
            out.append(f"sid_{sid}")
    except Exception:
        pass
    return out


def _leg_store(st, name: str, tag) -> Any:
    """A per-leg cache entry, found under whichever key it was written with."""
    store = st.session_state.get(name) or {}
    for key in _leg_key_variants(st, tag):
        val = store.get(key)
        if val:
            return val
    return None


def _leg_levels(st, tag) -> Dict[str, Any]:
    """One leg's own levels, in premium — never spot-derived.

    A stop computed in NIFTY points drawn on a premium series marks a price
    that series can never trade. Everything here comes from the leg's own
    engines: its VWAP, its S/R behaviour level, and the premium the leg Entry
    Gate actually armed, if it armed one.
    """
    if not tag:
        return {}
    out: Dict[str, Any] = {}

    sr = _leg_store(st, "_atm_leg_sr_behavior", tag) or {}
    lvl = _num(sr.get("level"), None)
    if lvl is not None and lvl > 0:
        # the leg's own S/R behaviour level, labelled by which side it is
        out["support" if str(sr.get("side") or "").lower() == "support"
            else "resistance"] = lvl

    # VWAP off the leg frame itself — the same column the leg panel prints
    try:
        frame = (st.session_state.get("_atm_leg_dfs") or {}).get(tag)
        if frame is not None and "vwap" in getattr(frame, "columns", []):
            v = _num(frame["vwap"].iloc[-1], None)
            if v is not None and v > 0:
                out["vwap"] = v
    except Exception:
        pass

    setup = ((st.session_state.get("_entry_armed_setups") or {}).get(tag)
             or (st.session_state.get("_entry_signal_open") or {}).get(tag)
             or {})
    for src, key in ((setup.get("entry"), "entry"), (setup.get("sl"), "stop"),
                     (setup.get("trail"), "trail"),
                     (setup.get("target"), "target")):
        v = _num(src, None)
        if v is not None and v > 0:
            out[key] = v

    # ── Premium Structure overlays, on the chart that already exists ──
    # POC / HVN / LVN and the structure's own support and resistance, drawn on
    # the leg panel by the renderer that already draws the leg's levels. No
    # second chart, and nothing computed here — the values come from
    # `premium_structure.analyse`, which the strike validation pass already ran.
    #
    # Structure levels do not overwrite the S/R behaviour level above: where
    # both exist the behaviour level is the one price is reacting to *now*, and
    # the structure's is where the zone sits.
    for (_side, _strike), read in (st.session_state.get("_premium_structures")
                                   or {}).items():
        if not str(tag).endswith(f"{'CE' if _side == 'CALL' else 'PE'} "
                                 f"{_strike:.0f}"):
            continue
        for key, val in (("poc", (read.get("profile") or {}).get("vp_poc")),
                         ("support", read.get("support")),
                         ("resistance", read.get("resistance"))):
            v = _num(val, None)
            if v is not None and v > 0:
                out.setdefault(key, v)
        # one node each — the strongest HVN and the emptiest LVN. Drawing four
        # of each turns the panel into a ladder and hides the price.
        for key in ("hvn", "lvn"):
            nodes = read.get(key) or []
            v = _num((nodes[0] or {}).get("price"), None) if nodes else None
            if v is not None and v > 0:
                out[key] = v
        break
    return out


def _leg_money_flow(st, tag, row: Dict[str, Any]) -> Dict[str, Any]:
    """The leg's money flow, read from what the app already computed.

    `_atm_leg_ltf_delta` is the intrabar buyer/seller split behind the panel's
    own Buy Vol / Sell Vol / Δ Vol tiles — the same cumulative buy and sell
    volume, not a second opinion on it. The MFP column from the leg-bias table
    supplies the direction the profile is leaning.
    """
    dv = _leg_store(st, "_atm_leg_ltf_delta", tag) or {}
    # `None`, not `_num`'s 0.0 default: an absent store must stay absent. A
    # fabricated "Even +0.0%" reads as a measured balance rather than a gap.
    buy = _num(dv.get("buy_total"), None)
    sell = _num(dv.get("sell_total"), None)
    pct = _num(dv.get("delta_pct"), None)
    if buy is None or sell is None:
        return {}

    if pct is None:
        total = buy + sell
        pct = ((buy - sell) / total * 100.0) if total else 0.0
    state = ("entering" if pct >= 5 else "leaving" if pct <= -5 else "flat")
    lean = {"🟢": "bull", "🔴": "bear"}.get(str(row.get("MFP") or "")[:1])
    return {
        "label": (f"{'Buyers' if pct > 0 else 'Sellers' if pct < 0 else 'Even'} "
                  f"{pct:+.1f}%"),
        "state": state,
        "buy_volume": buy, "sell_volume": sell, "delta_pct": round(pct, 1),
        "profile_lean": lean,
    }


def _atm_tags(st):
    from .terminal_chart import atm_legs
    return atm_legs(st.session_state.get("_atm_leg_dfs"))


_ZOOM_KEY = "_terminal_zoom"


def _zoom_controls(st) -> Optional[int]:
    """Expand / contract buttons, returning the minutes of session to show.

    Buttons rather than the scroll wheel: the wheel zoomed the chart whenever
    anyone scrolled the page past it, which is not a thing you can ask for on
    purpose. These are, and the current level is on screen so you always know
    what you are looking at.
    """
    from .terminal_chart import zoom_label, zoom_step

    cur = st.session_state.get(_ZOOM_KEY, None)
    c1, c2, c3, c4 = st.columns([1, 1, 1, 6])
    if c1.button("➖", key="_zoom_out", help="Contract — show more of the day",
                 use_container_width=True):
        cur = zoom_step(cur, -1)
        st.session_state[_ZOOM_KEY] = cur
    if c2.button("➕", key="_zoom_in", help="Expand — zoom in on the last bars",
                 use_container_width=True):
        cur = zoom_step(cur, +1)
        st.session_state[_ZOOM_KEY] = cur
    if c3.button("⟲", key="_zoom_reset", help="Back to the full session",
                 use_container_width=True):
        cur = None
        st.session_state[_ZOOM_KEY] = None
    c4.markdown(
        f"<div style='padding-top:7px;font-size:12px;color:#cfd9e6'>"
        f"🔍 {zoom_label(cur)} — the window is anchored at the newest bar, so "
        f"zooming in keeps live price on screen.</div>",
        unsafe_allow_html=True)
    return cur


def _panel_profile(st, tag, df=None, ready: Optional[Dict[str, Any]] = None):
    """One panel's liquidity & sentiment profile, plus Stage 71.86's shape.

    Each panel gets its **own** profile. The index profile is never projected
    onto a premium panel — audit 71.8 settled that a premium profile is
    computed natively per leg, and an index POC drawn on a premium series marks
    a price that series can never trade.

    `ready` is the profile the app already built (NIFTY's lives in
    `_money_flow_data`). When there is none, one is built here **through the
    existing owner** — `calculate_money_flow_profile`, never a second
    implementation — because the app is what owns the candle series, exactly as
    Stage 45 already works.

    ⚠️ Cached on the bar count. The terminal reruns every ~20 seconds and a
    profile only changes when a bar closes; recomputing 25 bins per leg per
    rerun is the shape of the problem that made egress 0.59 GB/day.
    """
    if not tag:
        return None
    if ready:
        profile = dict(ready)
    else:
        if df is None or getattr(df, "empty", True) or len(df) < 5:
            return None
        cache = st.session_state.setdefault("_panel_profiles", {})
        hit = cache.get(tag)
        if hit and hit.get("_bars") == len(df):
            return hit
        # The app registers `_premium_builders["mfp"]` for exactly this — the
        # money-flow profile of a leg frame. Calling the indicator directly
        # instead would build a SECOND premium profile with different
        # parameters (`source="Volume"` against the builder's "Money Flow"),
        # so the same leg would carry two profiles that disagree. One fact,
        # one owner: use the registered builder and only fall back when the
        # app has not published one.
        builder = (st.session_state.get("_premium_builders") or {}).get("mfp")
        try:
            if builder is not None:
                profile = builder(df) or {}
            else:
                from indicators.money_flow_profile import \
                    calculate_money_flow_profile
                profile = calculate_money_flow_profile(
                    df, num_rows=25, source="Money Flow") or {}
        except Exception:
            return None
        if not profile:
            return None
        profile = dict(profile)
        profile["_bars"] = len(df)

    try:
        from ..profile_shape import run as _shape
        profile["shape"] = _shape(profile.get("rows") or (),
                                  poc=profile.get("poc_price"),
                                  vah=profile.get("value_area_high"),
                                  val=profile.get("value_area_low"),
                                  source=str(tag))
    except Exception:
        pass

    if not ready:
        st.session_state.setdefault("_panel_profiles", {})[tag] = profile
    return profile


def _terminal_chart(st, fr: Dict[str, Any], call_tag, put_tag, dom) -> None:
    """NIFTY ‖ ATM Call ‖ ATM Put — one figure, so zoom, pan and crosshair
    stay locked together across all three."""
    from .terminal_chart import atm_legs, terminal_chart

    from ..runner import nifty_frame
    nifty, nifty_src = nifty_frame(st.session_state)
    call_df, put_df, ce, pe = atm_legs(st.session_state.get("_atm_leg_dfs"))
    if nifty is None and call_df is None and put_df is None:
        st.caption("Candle data warming up — the terminal draws once the "
                   "1-minute series and the ATM legs have loaded.")
        return

    dec = fr.get("decision_v2") or {}
    mf = st.session_state.get("_money_flow_data") or {}
    mp = st.session_state.get("_market_picture") or {}
    bz = fr.get("battle_zone") or {}
    pools = (mp.get("liq_pools") or {})
    liq = None
    for side in ("above", "below"):
        lst = pools.get(side) or []
        if lst:
            liq = _num((lst[0] or {}).get("price") if isinstance(lst[0], dict)
                       else lst[0]) or None
            break

    levels = {
        "entry": dec.get("entry"), "stop": dec.get("stop"),
        "trail": (dec.get("trail") or {}).get("stop"),
        "target": fr.get("next_target"),
        "support": fr.get("strong_support"),
        "resistance": fr.get("strong_resistance"),
        "war_zone": bz.get("price"), "liquidity": liq,
        "vwap": mp.get("vwap"), "poc": mf.get("poc_price"),
        "vah": mf.get("value_area_high"), "val": mf.get("value_area_low"),
    }
    # ── dealer hedging + the reaction price ──
    # Stage 11 computes gamma flip and the magnet wall every cycle, and Stage
    # 42 knows the price its verdict happened at. All three now arrive on
    # `final_read`, so the chart takes them as inputs rather than reaching for
    # them (principle 4) and the trader can see the levels that are moving the
    # decision (principle 12).
    levels.update(fr.get("dealer_levels") or {})
    levels["reaction"] = fr.get("reaction_level")
    # the expiry-day magnet, from the one shared rule the Trade Card uses
    try:
        from ..charm_pin import from_market_picture as _cpin
        _pin = _cpin(bool(fr.get("is_expiry")), _spot_now(st, fr), mp,
                     (st.session_state.get("_cached_option_data")
                      or {}).get("max_pain_strike"))
        levels["charm_pin"] = (_pin or {}).get("pin")
    except Exception:
        pass
    htf = (fr.get("htf") or {}).get("levels") or {}

    window = _zoom_controls(st)

    # Built once, used twice — by the chart's band overlay and by the liquidity
    # bars rendered underneath it. Building them here rather than again in the
    # panel is the same rule Stage 71.8 settled for the leg reads: one profile
    # per leg, one owner, two readers.
    _nifty_prof = _panel_profile(st, "NIFTY", nifty, mf)
    _call_prof = _panel_profile(st, ce, call_df)
    _put_prof = _panel_profile(st, pe, put_df)
    # Published for the bars below. Same cycle, so no lag — the panel reads what
    # this chart just drew, not last pass's copy.
    st.session_state["_leg_profiles"] = {
        "NIFTY": _nifty_prof, "CALL": _call_prof, "PUT": _put_prof,
        "call_label": ce, "put_label": pe}

    try:
        fig, notes = terminal_chart(
            nifty, call_df, put_df, levels, htf_levels=htf,
            call_label=ce or "ATM Call", put_label=pe or "ATM Put",
            tint=dom.get("tint"), dominance=dom.get("side", "neutral"),
            signal=dec, window_minutes=window,
            call_levels=_leg_levels(st, ce), put_levels=_leg_levels(st, pe),
            call_zones=_leg_store(st, "_atm_leg_vob_volume", ce),
            put_zones=_leg_store(st, "_atm_leg_vob_volume", pe),
            nifty_profile=_nifty_prof,
            call_profile=_call_prof,
            put_profile=_put_prof)
        # scrollZoom off: the wheel zoomed the chart out from under anyone
        # scrolling the page past it. Zoom is on the buttons, where it is
        # deliberate and the current level is visible.
        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False, "scrollZoom": False})
        if notes:
            # name the series AND why — "No candle series yet for: NIFTY" on a
            # screen where the two option legs drew fine tells you nothing
            # about where to look
            why = []
            if "NIFTY" in notes:
                why.append(nifty_src)
            if ce and ce in notes or pe and pe in notes:
                why.append("ATM leg frames come from `_atm_leg_dfs`, filled "
                           "by the ATM±3 leg fetch")
            st.caption("No candle series yet for: " + ", ".join(notes)
                       + (" — " + "; ".join(x for x in why if x) if why else ""))
        st.caption(
            "🖱 **Hover any candle — all three charts stay synchronised.** "
            "10:48 on NIFTY reads 10:48 on both legs, so a reversal and the "
            "premium response to it are visible in the same glance. The ➕/➖ "
            "buttons and dragging to pan move all three together.  \n"
            "🟢🔴 **Option bar colour is who was buying that minute**; bar "
            "height is still volume. The violet line is CVD — rising means "
            "buyers are still adding, falling means they have stopped. Its "
            "shape is the signal; it is scaled into the panel, so its height "
            "carries no price meaning.")
    except Exception as err:
        st.caption(f"Terminal chart unavailable: {err}")


def _war_zone(st, fr: Dict[str, Any]) -> None:
    bz = fr.get("battle_zone")
    if not bz:
        return
    probs = fr.get("probabilities") or {}
    st.markdown(
        f"<div style='{_CARD};border-left:3px solid #ffcc33'>"
        f"<span style='font-size:15px;font-weight:800;color:#ffcc33'>"
        f"⚔️ War zone — {bz.get('type')} {_fmt(bz.get('price'))}</span>"
        f"<span style='font-size:13px;color:#edf3f9'> → expected winner "
        f"<b>{fr.get('expected_winner', '—')}</b></span>"
        + ("".join(f"<span style='font-size:12px;color:#cfd9e6;margin-left:10px'>"
                   f"{k} {_num(v):.0f}%</span>" for k, v in probs.items())
           if probs else "")
        + "</div>", unsafe_allow_html=True)


def _price_map(st, fr: Dict[str, Any]) -> None:
    """Every level the chart drew, as numbers — including the HTF POCs the
    confluence score is computed against."""
    dec = fr.get("decision_v2") or {}
    trail = dec.get("trail") or {}
    mf = st.session_state.get("_money_flow_data") or {}
    rows: List[Any] = []
    for lbl, price, colr in (
            ("Entry (proven)", dec.get("entry"), "#00ff88"),
            ("Stop", dec.get("stop"), "#ff4444"),
            ("Trail", trail.get("stop"), "#a78bfa"),
            ("Target", fr.get("next_target"), "#7fe8b0"),
            ("Support", fr.get("strong_support"), "#17c98b"),
            ("Resistance", fr.get("strong_resistance"), "#ff8c8c"),
            ("VAH", mf.get("value_area_high"), "#7dffb0"),
            ("POC", mf.get("poc_price"), "#ffe066"),
            ("VAL", mf.get("value_area_low"), "#ff8c8c")):
        if price:
            rows.append((lbl, price, colr))
    for lbl, price in sorted((fr.get("htf") or {}).get("levels", {}).items(),
                             key=lambda kv: -_num(kv[1]))[:10]:
        rows.append((lbl, price, "#cfd9e6"))

    st.markdown("**📍 Price map**")
    if not rows:
        st.caption("Levels warming up.")
        return
    st.markdown("".join(
        f"<div style='display:flex;justify-content:space-between;"
        f"font-size:12.5px;padding:2px 0;border-bottom:1px solid #161b22'>"
        f"<span style='color:{c}'>{l}</span>"
        f"<span style='color:#ffffff;font-weight:700'>{_num(p):,.0f}</span>"
        f"</div>" for l, p, c in rows), unsafe_allow_html=True)


def _sr_intelligence(st, fr: Dict[str, Any], state) -> None:
    """Each S/R level as an intelligent object, ranked."""
    from .sr_panel import render_sr_panel

    try:
        rsr = st.session_state.get("_reaction_sr") or {}
    except Exception:
        rsr = {}
    dec = fr.get("decision_v2") or {}
    ab = fr.get("absorption") or {}
    tr = fr.get("transition") or {}
    react_all = {}
    try:
        _ac = state.get("stage42_acceptance")
        if _ac is not None and _ac.ok and _ac.data:
            react_all = {"SUPPORT": _ac.data.get("support") or {},
                         "RESISTANCE": _ac.data.get("resistance") or {}}
    except Exception:
        react_all = {}

    # the next target the Reaction-Zone engine already computed
    tgt, tgt_lbl = fr.get("next_target"), None
    if tgt:
        for lbl, price in ((fr.get("htf") or {}).get("levels") or {}).items():
            try:
                if abs(float(price) - float(tgt)) <= max(8.0, float(tgt) * 0.0004):
                    tgt_lbl = lbl
                    break
            except (TypeError, ValueError):
                continue

    # ── the three states this panel can be in, told apart. They used to look
    # identical on screen ("still warming up"), so a real failure was
    # indistinguishable from a cold start and stayed there indefinitely.
    from ..sr_intel import card_from_zone
    levels, unenriched = [], 0
    for key, side in (("support", "SUPPORT"), ("resistance", "RESISTANCE")):
        z = rsr.get(key) or {}
        card = z.get("intel")
        if not card:
            # enrichment missing or failed — a level with a price and a
            # strength is still worth seeing
            card = card_from_zone(z, side)
            if card:
                unenriched += 1
        if not card:
            continue
        mem = {}
        try:
            mem = (st.session_state.get("_zone_memory") or {})
            mem = next((v for k, v in mem.items() if k.startswith(key)), {})
        except Exception:
            mem = {}
        levels.append(build_level_intel(
            card, reaction=react_all.get(side), absorption=ab, transition=tr,
            decision=dec, next_target=tgt, target_label=tgt_lbl,
            age_min=(float(mem.get("age", 0)) if mem.get("age") else None),
            # so a level the market has crossed is re-sided rather than kept
            # under the name it was given when it formed
            spot=_spot_now(st, fr)))

    if not levels:
        st.markdown(_sr_status(st, rsr), unsafe_allow_html=True)
        return

    _ranked = rank_levels(levels)
    # Published so the Telegram signal reads the SAME assembled levels the
    # panel draws — a second assembly here would be a second owner, and the
    # message and the screen could then disagree about the same level.
    st.session_state["_sr_levels"] = _ranked
    render_sr_panel(_ranked)
    if unenriched:
        st.caption(f"⚠️ {unenriched} level(s) shown WITHOUT Zone Intelligence — "
                   f"price and strength only. `enrich_zone_intel` did not "
                   f"attach a card; the origin ★, lifecycle, health and "
                   f"probabilities are missing, not zero."
                   + (f" Last error: {st.session_state.get('_reaction_sr_error')}"
                      if st.session_state.get("_reaction_sr_error") else ""))


def _sr_status(st, rsr: Dict[str, Any]) -> str:
    """Why there are no levels — never just "warming up".

    The canonical object is written near the END of the analyser pass, after
    this dashboard renders, so the FIRST pass legitimately has nothing. Every
    pass after that, silence means something failed.
    """
    err = st.session_state.get("_reaction_sr_error")
    ts = st.session_state.get("_reaction_sr_ts")
    age = None
    if ts:
        try:
            import time as _t
            age = int(_t.time() - float(ts))
        except Exception:
            age = None

    if err:
        body = (f"<b style='color:#ff9d9d'>Reaction-Zone build failed.</b><br>"
                f"<code style='color:#ffd9a0'>{err}</code><br>"
                f"<span style='color:#cfd9e6'>This is an error, not a warm-up "
                f"— it will not clear on its own.</span>")
    elif rsr:
        body = ("<b style='color:#ffcc33'>The canonical S/R object exists but "
                "carries no priced level.</b><br>"
                "<span style='color:#cfd9e6'>`build_reaction_sr` found no "
                "support or resistance in the confluence clusters — usually "
                "spot sitting outside every scored zone.</span>")
    elif age is not None:
        body = (f"<b style='color:#ffcc33'>No S/R written for {age}s.</b><br>"
                f"<span style='color:#cfd9e6'>The last successful build was "
                f"{age}s ago; the analyser pass may be exiting before it "
                f"reaches the zone step.</span>")
    else:
        body = ("<b style='color:#cfd9e6'>Waiting for the first "
                "Reaction-Zone build.</b><br>"
                "<span style='color:#b3c2d4'>It is written near the end of the "
                "analyser pass, so the first render always precedes it. If "
                "this persists past one refresh, the zone step is not "
                "running.</span>")
    return (f"<div style='{_CARD};border-left:3px solid #ff9500'>"
            f"<div style='font-size:12.5px;color:#edf3f9;line-height:1.6'>"
            f"{body}</div></div>")


# ── 3 · INTELLIGENCE (the engine room) ──────────────────────────────────
#: group → the engine sections it owns. Grouping beats a flat list because a
#: trader debugging a bearish read wants "what do the institutions say",
#: not the twenty-third row of an alphabetical table.
_GROUPS = (
    ("🏗 Market Structure", ("regime", "patterns")),
    ("🏛 Institutions", ("dealer", "flows", "intent")),
    ("📊 Options", ("options", "vix")),
    ("⚡ Order Flow", ("orderflow", "liquidity")),
    ("✅ Validation", ("sector",)),
)

_BIAS_COLOUR = {"STRONG_BULL": "#00ff88", "BULL": "#17c98b",
                "NEUTRAL": "#cfd9e6", "BEAR": "#ff6666",
                "STRONG_BEAR": "#ff4444", "NONE": "#9fb0c4"}


def _intelligence(st, fr: Dict[str, Any], state) -> None:
    """Why does MIOS think that? — grouped, collapsible, deliberately dense."""
    from .explain_panel import checklist_html, risk_html
    from ..checklist import build as _build_checklist
    from ..risk_explain import analyse as _risk

    ctl = market_controller(fr.get("families"))
    st.markdown(f"**🎮 Market controller:** {ctl.get('label', '—')} "
                f"<span style='color:#cfd9e6;font-size:12px'>"
                f"{ctl.get('reason', '')}</span>", unsafe_allow_html=True)

    _evo = state.get("stage29_evolution")
    changes = recent_changes(
        fr, (_evo.data.get("changes") if _evo is not None and _evo.data else None))
    st.markdown("**🔄 Recent changes** "
                "<span style='color:#b3c2d4;font-size:11px'>(only what moved)"
                "</span>", unsafe_allow_html=True)
    if changes:
        st.markdown("".join(f"<div style='font-size:12.5px;color:#edf3f9'>"
                            f"• {c}</div>" for c in changes),
                    unsafe_allow_html=True)
    else:
        st.caption("Nothing has changed materially this cycle.")

    with st.expander("🕘 Session Intelligence — measures · modifiers",
                     expanded=True):
        from .session_panel import modifier_table, session_card
        si = fr.get("session_intel") or {}
        st.markdown(session_card(si), unsafe_allow_html=True)
        st.markdown(modifier_table(si), unsafe_allow_html=True)

    with st.expander("🗓 Day Classification — groups · evidence · transitions",
                     expanded=True):
        from .day_type_panel import day_type_detail, day_type_timeline
        from ..day_type import timeline as _dt_timeline
        dc = fr.get("day_classification") or {}
        st.markdown(day_type_detail(dc), unsafe_allow_html=True)
        st.markdown(day_type_timeline(_dt_timeline(dc.get("memory"))),
                    unsafe_allow_html=True)

    with st.expander("🏗 Market Structure — state · transition · memory",
                     expanded=True):
        from .memory_panel import memory_panel_html
        from .state_panel import state_line
        from .transition_panel import render_transition_panel
        ms = fr.get("market_state") or {}
        if ms:
            st.markdown(state_line(ms), unsafe_allow_html=True)
        render_transition_panel(fr.get("transition"))
        st.markdown(memory_panel_html(fr.get("memory")), unsafe_allow_html=True)
        _sections(st, ("regime", "patterns"), fr)

    with st.expander("🏛 Institutions — dealer · FII/DII · absorption · flow",
                     expanded=False):
        from .absorption_panel import absorption_panel_html
        st.markdown(absorption_panel_html(fr.get("absorption")),
                    unsafe_allow_html=True)
        _flow_shift(st, fr)
        _sections(st, ("dealer", "flows", "intent"), fr)

    with st.expander("📊 Options — OI · gamma · charm · vanna · PCR · VIX",
                     expanded=False):
        _sections(st, ("options", "vix"), fr)
        st.caption("Per-strike OI, gamma and vanna/charm exposure charts live "
                   "on the main app page — this is the engine's read of them.")

    with st.expander("⚡ Order Flow — CVD · money flow · delta · VOB · liquidity",
                     expanded=False):
        from .ltp_panel import ltp_panel_html
        st.markdown(ltp_panel_html(fr.get("ltp_behaviour")),
                    unsafe_allow_html=True)
        _sections(st, ("orderflow", "liquidity"), fr)

    with st.expander("✅ Validation — acceptance · validity · evidence · energy",
                     expanded=True):
        from .energy_panel import energy_panel_html
        from .family_panel import render_family_panel
        from .validity_panel import validity_panel_html
        from .zone_card import reaction_line
        st.markdown(reaction_line(fr.get("reaction")), unsafe_allow_html=True)
        st.markdown(validity_panel_html({**(fr.get("validity_both") or {}),
                                         "active": fr.get("validity")}),
                    unsafe_allow_html=True)
        st.markdown(energy_panel_html(fr.get("energy_read")),
                    unsafe_allow_html=True)
        # Stage 71.7 (Premium Energy) used to render here, below Market Energy.
        # It now lives inside the Stage 71 panel on the Trading tab, because the
        # horizon ranking and the premium confirmation have to be read together.
        # Rendering it in both places would give the workstation two copies of
        # the same numbers — the drift the Stage 71 stack exists to prevent.
        ev = state.get("stage53_evidence")
        if ev is not None and ev.ok:
            render_family_panel(ev.data)
        _sections(st, ("sector",), fr)

    with st.expander("🧬 Decision diagnostics — checklist · risk · V6 voters",
                     expanded=False):
        cl = _build_checklist(fr)
        st.markdown(checklist_html(cl), unsafe_allow_html=True)
        st.markdown(risk_html(_risk(fr)), unsafe_allow_html=True)
        from .bias_compare import v6_detail_html
        from ..v6_bias import compute as _v6
        st.markdown(v6_detail_html(_v6(fr)), unsafe_allow_html=True)


def _sections(st, keys, fr: Dict[str, Any]) -> None:
    """Raw engine sections — bias · confidence · status · headline."""
    rows = [(k, section(fr, k)) for k in keys]
    rows = [(k, s) for k, s in rows if s]
    if not rows:
        return
    st.markdown("".join(
        f"<div style='display:flex;gap:8px;align-items:baseline;"
        f"font-size:12px;padding:2px 0;border-bottom:1px solid #161b22'>"
        f"<span style='width:96px;color:#cfd9e6'>{k.title()}</span>"
        f"<span style='width:88px;font-weight:800;"
        f"color:{_BIAS_COLOUR.get(str(s.get('bias', '')).upper(), '#cfd9e6')}'>"
        f"{s.get('bias', '—')}</span>"
        f"<span style='width:44px;color:#edf3f9'>{_num(s.get('confidence')):.0f}%"
        f"</span>"
        f"<span style='width:66px;font-size:10px;color:#9fb0c4'>"
        f"{s.get('status', '')}</span>"
        f"<span style='flex:1;min-width:0;color:#cfd9e6;overflow:hidden;"
        f"text-overflow:ellipsis;white-space:nowrap'>{s.get('headline', '')}"
        f"</span></div>" for k, s in rows), unsafe_allow_html=True)


def _flow_shift(st, fr: Dict[str, Any]) -> None:
    fs = fr.get("flow_shift") or {}
    if not fs:
        return
    col = "#ff9500" if fs.get("freeze_entries") else "#cfd9e6"
    st.markdown(f"<div style='font-size:12.5px;color:{col}'>"
                f"🌊 <b>Flow</b> {fr.get('stability', '—')} · "
                f"score {_num(fs.get('score')):.0f}% · "
                f"{fs.get('reason', 'no shift detected')}</div>",
                unsafe_allow_html=True)


# ── 4 · HISTORY (case studies) ──────────────────────────────────────────
def _history(st, db) -> None:
    """What happened, and why? — every trade as a case study."""
    if db is None:
        st.caption("No database connection.")
        return
    try:
        df = db.get_trade_signals(limit=300)
    except Exception:
        df = None
    if df is None or getattr(df, "empty", True):
        st.caption("No signals recorded yet — run sql/026_trade_signals.sql and "
                   "let the Decision Engine generate A/A+ setups.")
        return

    cols = [c for c in ["signal_id", "trading_day", "side", "quality", "status",
                        "entry_price", "entered_price", "exit_price",
                        "pnl_points", "rr", "outcome", "confidence"]
            if c in df.columns]
    st.dataframe(df[cols] if cols else df, use_container_width=True,
                 hide_index=True)

    if not hasattr(db, "get_trade_results"):
        return
    try:
        res = db.get_trade_results(limit=40)
        att = db.get_trade_attribution(limit=40)
        eng = db.get_engine_attribution(limit=2000)
        evs = db.get_trade_events(limit=1000)
    except Exception:
        res = att = eng = evs = None

    from .review_panel import review_html, review_list_html
    from ..trade_review import review_many
    reviews = review_many(att, res, eng, evs, limit=20)
    if not reviews:
        st.caption("No graded trades to review yet — Stage 66 needs "
                   "`sql/027_learning.sql` and a closed trade.")
        return

    st.markdown("---")
    ids = [r["signal_id"] for r in reviews]
    picked = st.selectbox("Case study", ids, index=0, key="_v6_case_study")
    rev = next((r for r in reviews if r["signal_id"] == picked), reviews[0])
    trade = next((t for t in (att or [])
                  if str(t.get("signal_id")) == str(picked)), {})

    st.markdown(review_html(rev), unsafe_allow_html=True)
    _case_context(st, trade, rev)

    if st.button("⏪ Replay this trade", key="_v6_replay_btn"):
        st.session_state["_v6_replay_signal"] = picked
        st.session_state["_v6_replay_day"] = trade.get("trading_day")
        st.info(f"Loaded {picked} — open the ⏪ Replay tab to step through it.")

    st.markdown(review_list_html([r for r in reviews
                                  if r["signal_id"] != picked]),
                unsafe_allow_html=True)


def _case_context(st, trade: Dict[str, Any], rev: Dict[str, Any]) -> None:
    """Market state at entry vs at exit, the AI thesis, and the raw engine
    snapshot — the three things that turn a row into a case study."""
    if not trade:
        return
    at_entry = [("Market state", trade.get("market_state")),
                ("Bias", trade.get("market_bias")),
                ("Acceptance", trade.get("acceptance")),
                ("Absorption", trade.get("absorption")),
                ("Dealer", trade.get("dealer_state")),
                ("Flow", trade.get("flow_shift")),
                ("HTF", trade.get("htf_alignment")),
                ("Controller", trade.get("market_controller"))]
    st.markdown(
        f"<div style='{_CARD}'>"
        f"<div style='font-size:12px;font-weight:800;color:#ffffff;"
        f"margin-bottom:3px'>📌 Market state at ENTRY</div>"
        + "".join(
            f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
            f"<span style='width:104px;color:#cfd9e6'>{k}</span>"
            f"<span style='color:#edf3f9'>{v or '—'}</span></div>"
            for k, v in at_entry)
        + f"<div style='margin-top:6px;font-size:12px;font-weight:800;"
          f"color:#ffffff'>📌 At EXIT</div>"
          f"<div style='font-size:12px;color:#edf3f9'>"
          f"{rev.get('exit_reason', '—')} · quality "
          f"{rev.get('trade_quality', '—')} · {rev.get('evolution', '')}</div>"
        + (f"<div style='margin-top:6px;font-size:12px;color:#9fd3ff'>"
           f"🤖 {trade.get('ai_thesis')}</div>" if trade.get("ai_thesis") else "")
        + "</div>", unsafe_allow_html=True)

    with st.expander("🔬 Engine snapshot at signal time", expanded=False):
        st.json(trade.get("snapshot") or trade.get("decision_reason") or {})

    st.caption("Entry/exit **screenshots are not captured** — no screenshot "
               "infrastructure exists in this app, and a fabricated one would "
               "be worse than none. The engine snapshot plus the replay "
               "timeline are the audit trail instead.")


# ── 5 · LEARNING (analytics centre) ─────────────────────────────────────
def _learning(st, db, fr: Optional[Dict[str, Any]] = None) -> None:
    """Is MIOS actually any good? — four sections, in order of usefulness."""
    _daily_summary(st, db, fr or {})

    if db is None or not hasattr(db, "get_engine_attribution"):
        st.info("Learning tables not available on this DB client.", icon="ℹ️")
        return
    try:
        eng = db.get_engine_attribution(limit=8000)
        res = db.get_trade_results(limit=500)
        att = db.get_trade_attribution(limit=500)
        evs = db.get_trade_events(limit=4000)
    except Exception:
        eng = res = att = evs = None

    if not eng or not res:
        st.warning(
            "No per-engine attribution rows yet — the Learning Engine has "
            "nothing to measure.\n\n"
            "Run **`sql/027_learning.sql`** in Supabase, then let the app take "
            "graded trades. Every signal writes one `trade_attribution` row, "
            "one `engine_attribution` row per engine, an append-only "
            "`trade_events` trail, and one `trade_results` row at exit.\n\n"
            "I'd rather say this than show invented numbers.", icon="⚠️")
        return

    from .learning_panel import (accuracy_html, calibration_html,
                                 contribution_html, false_signal_html,
                                 governance_html, overall_html,
                                 thresholds_html)
    from ..learning_report import build as _build_learning

    win = st.selectbox("Window", ["last30", "last100", "last500", "lifetime"],
                       index=1, key="_v6_learn_window")
    p = _build_learning(eng, res, att, evs, window=win)

    s1, s2, s3, s4 = st.tabs(["📊 Performance", "🏆 Engine Accuracy",
                              "🎚 Optimisation", "🔍 Failure Analysis"])
    with s1:
        st.markdown(overall_html(p.get("overall")), unsafe_allow_html=True)
        _performance_by_day_type(st, db, res)
        _performance_by_session(st, db, res)
        _session_validation(st, db, res, att)
    with s2:
        st.markdown(accuracy_html(p.get("rankings"), win),
                    unsafe_allow_html=True)
        st.markdown(contribution_html(p.get("contribution"),
                                      p.get("contribution_lines")),
                    unsafe_allow_html=True)
    with s3:
        st.markdown(calibration_html(p.get("calibration_suggestions"),
                                     p.get("calibration"), win),
                    unsafe_allow_html=True)
        st.markdown(thresholds_html(p.get("thresholds")), unsafe_allow_html=True)
    with s4:
        st.markdown(false_signal_html(p.get("false_signals"),
                                      p.get("recent_losses")),
                    unsafe_allow_html=True)
        _wait_reasons(st)
    st.markdown(governance_html(), unsafe_allow_html=True)


def _wait_reasons(st) -> None:
    """What MIOS spent the session refusing — the other half of the record."""
    log = st.session_state.get("_mios_wait_log") or []
    if not log:
        st.caption("No WAIT cycles logged yet this session.")
        return
    counts: Dict[str, int] = {}
    for r in log:
        counts[str(r)] = counts.get(str(r), 0) + 1
    rows = sorted(counts.items(), key=lambda kv: -kv[1])
    n = len(log)
    st.markdown(
        f"<div style='{_CARD}'>"
        f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
        f"margin-bottom:4px'>⏳ Most common WAIT reasons "
        f"<span style='font-size:11px;color:#b3c2d4'>({n} cycles)</span></div>"
        + "".join(
            f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
            f"<span style='flex:1;color:#edf3f9'>{k}</span>"
            f"<span style='color:#ffcc66'>{v} ({100.0 * v / n:.0f}%)</span>"
            f"</div>" for k, v in rows[:8])
        + "</div>", unsafe_allow_html=True)


def _daily_summary(st, db, fr: Dict[str, Any]) -> None:
    """Stage 67 — today's report."""
    from .review_panel import daily_summary_html
    from ..daily_summary import summarise as _summarise

    day = None
    res = trades = eng = evs = None
    if db is not None and hasattr(db, "get_trade_results"):
        try:
            res = db.get_trade_results(limit=60)
            trades = db.get_trade_attribution(limit=60)
            eng = db.get_engine_attribution(limit=3000)
            evs = db.get_trade_events(limit=1500)
        except Exception:
            res = trades = eng = evs = None
    if trades:
        day = (trades[0] or {}).get("trading_day")
    if res and day:
        res = [r for r in res if r.get("trading_day") == day]
        trades = [t for t in (trades or []) if t.get("trading_day") == day]

    st.markdown(daily_summary_html(_summarise(
        results=res, trades=trades, engine_rows=eng, events=evs,
        wait_log=st.session_state.get("_mios_wait_log"),
        state_log=st.session_state.get("_mios_state_log"),
        final_read=fr,
        levels={"support": fr.get("strong_support"),
                "resistance": fr.get("strong_resistance")},
        trading_day=day)), unsafe_allow_html=True)
    st.markdown("---")


# ── 6 · REPLAY ──────────────────────────────────────────────────────────
def _replay(st, db) -> None:
    """Can I verify it, cycle by cycle?

    Reconstruction, not re-simulation: this shows what MIOS believed at the
    time, from the `engine_state` rows the runner has been writing since
    Stage 18. The engines are not re-run — replaying a January session with
    today's code would hide every improvement and every regression alike.
    """
    from ..replay import (SPEEDS, compare_to_outcome, decision_timeline,
                          engine_timeline, flips, frame_at, narrate, seek,
                          summary)

    _reference(st)
    if db is None:
        st.caption("No database connection.")
        return

    try:
        rows = db.get_engine_state(limit=800) if hasattr(db, "get_engine_state") else None
        signals = db.get_trade_signals(limit=100)
        signals = (signals.to_dict("records")
                   if hasattr(signals, "to_dict") else list(signals or []))
    except Exception:
        rows, signals = None, []

    if not rows:
        st.info("No engine-state history yet. The runner persists one row per "
                "pipeline pass during live sessions — replay becomes available "
                "once a session has run.")
        return

    from ..replay import build_timeline
    frames = build_timeline(rows, signals)
    if not frames:
        st.info("Engine-state rows found but none could be parsed.")
        return

    meta = summary(frames)
    st.markdown(
        f"<div style='{_CARD}'>"
        f"<span style='font-size:13px;font-weight:800;color:#ffffff'>"
        f"⏪ {meta.get('day') or 'session'} · {meta['from']}–{meta['to']}</span>"
        f"<span style='font-size:12px;color:#cfd9e6'> · {meta['frames']} cycles"
        f" · {meta['decision_changes']} decision changes"
        f" · {meta['engine_flips']} engine flips</span>"
        + (f"<div style='font-size:11.5px;color:#ffcc33'>⚠️ "
           f"{meta['gaps']} gap(s) in the recording — not interpolated.</div>"
           if meta.get("gaps") else "")
        + (f"<div style='font-size:11.5px;color:#ffcc33'>⚠️ mixed engine "
           f"versions ({', '.join(meta['versions'])}) — rows from different "
           f"scoring logic must not be compared as if they were the same."
           f"</div>" if meta.get("mixed_versions") else "")
        + f"<div style='font-size:10.5px;color:#9fb0c4;margin-top:3px'>"
          f"{meta['note']}</div></div>", unsafe_allow_html=True)

    # ── transport controls ──
    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
    last = frames[-1]["index"]
    with c1:
        idx = st.slider("Cycle", 0, last, min(last, int(
            st.session_state.get("_v6_replay_idx", last))), key="_v6_replay_idx")
    with c2:
        jump = st.text_input("Jump to", value="", placeholder="10:42",
                             key="_v6_replay_jump")
    with c3:
        speed = st.selectbox("Speed", SPEEDS, index=1, key="_v6_replay_speed")
    with c4:
        step = st.button("▶ Step", key="_v6_replay_step")

    if jump:
        idx = seek(frames, jump.strip())
    if step:
        idx = min(last, idx + int(speed))

    f = frame_at(frames, idx)
    st.markdown(
        f"<div style='{_CARD};border-left:3px solid #a78bfa'>"
        f"<span style='font-size:19px;font-weight:900;color:#ffffff'>"
        f"{f.get('time')} · {_fmt(f.get('spot'))}</span>"
        f"<span style='font-size:13px;color:#c9b6ec'> · "
        f"{f.get('bias') or '—'} · {f.get('structure_decision') or '—'}"
        f" · agreement {_num(f.get('agreement_pct')):.0f}%</span>"
        + "".join(f"<div style='font-size:12.5px;color:#ffd000'>{m['label']}"
                  f"</div>" for m in (f.get("markers") or []))
        + "</div>", unsafe_allow_html=True)

    # ── engine state at this candle ──
    engines = f.get("engines") or {}
    if engines:
        st.markdown(
            f"<div style='{_CARD}'>"
            f"<div style='font-size:12px;font-weight:800;color:#ffffff;"
            f"margin-bottom:3px'>🔬 Engine state at {f.get('time')}</div>"
            + "".join(
                f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
                f"<span style='width:112px;color:#cfd9e6'>{k}</span>"
                f"<span style='width:92px;font-weight:800;color:"
                f"{_BIAS_COLOUR.get(str(v.get('bias', '')).upper(), '#cfd9e6')}'>"
                f"{v.get('bias') or '—'}</span>"
                f"<span style='color:#edf3f9'>{_num(v.get('confidence')):.0f}%"
                f"</span></div>" for k, v in engines.items())
            + "</div>", unsafe_allow_html=True)

    t1, t2, t3 = st.tabs(["🗓 Decision timeline", "🔬 Engine timeline",
                          "🎙 Narration"])
    with t1:
        dt = decision_timeline(frames)
        st.markdown("".join(
            f"<div style='display:flex;gap:8px;font-size:12.5px;padding:2px 0;"
            f"border-bottom:1px solid #161b22;"
            f"{'background:#151d2b' if d['index'] == idx else ''}'>"
            f"<span style='width:44px;color:#9fb0c4'>{d['time']}</span>"
            f"<span style='width:70px;color:#ffffff'>{_num(d['spot']):,.0f}</span>"
            f"<span style='color:#c9b6ec'>{d['from_bias'] or '—'} → "
            f"<b>{d['bias'] or '—'}</b></span>"
            f"<span style='margin-left:auto;color:#cfd9e6'>"
            f"{d['decision'] or ''}</span></div>" for d in dt),
            unsafe_allow_html=True)
    with t2:
        names = sorted({k for x in frames for k in (x.get("engines") or {})})
        if names:
            pick = st.selectbox("Engine", names, key="_v6_replay_engine")
            et = engine_timeline(frames, pick)
            st.markdown("".join(
                f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
                f"<span style='width:44px;color:#9fb0c4'>{e['time']}</span>"
                f"<span style='width:92px;font-weight:{800 if e['flipped'] else 600};"
                f"color:{_BIAS_COLOUR.get(str(e['bias']).upper(), '#cfd9e6')}'>"
                f"{e['bias'] or '—'}</span>"
                f"<span style='color:#edf3f9'>{_num(e['confidence']):.0f}%</span>"
                + ("<span style='color:#ffcc33'> ⟲ flip</span>"
                   if e["flipped"] else "")
                + "</div>" for e in et[-80:]), unsafe_allow_html=True)
        st.caption(f"{len(flips(frames))} engine flips in this session.")
    with t3:
        from .narrator_panel import narrator_html
        st.markdown(narrator_html(narrate(frames, upto=idx),
                                  title="🎙 Replay narration"),
                    unsafe_allow_html=True)

    # ── replay vs actual outcome ──
    closed = [s for s in signals if s.get("entered_at")]
    if closed:
        st.markdown("---")
        pre = st.session_state.get("_v6_replay_signal")
        ids = [s.get("signal_id") for s in closed]
        i0 = ids.index(pre) if pre in ids else 0
        sid = st.selectbox("Compare replay vs actual outcome", ids, index=i0,
                           key="_v6_replay_compare")
        sig = next((s for s in closed if s.get("signal_id") == sid), None)
        cmp = compare_to_outcome(frames, sig)
        if not cmp.get("available"):
            st.caption(cmp.get("reason", ""))
        else:
            pnl = cmp.get("pnl_points")
            col = "#00ff88" if (pnl or 0) > 0 else "#ff6666"
            st.markdown(
                f"<div style='{_CARD};border-left:3px solid {col}'>"
                f"<div style='font-size:13px;font-weight:800;color:{col}'>"
                f"{cmp['signal_id']} {cmp.get('side', '')} · "
                f"{cmp.get('outcome', '—')}"
                f"{(' %+.0f pts' % pnl) if pnl is not None else ''}</div>"
                f"<div style='font-size:12.5px;color:#edf3f9;margin-top:2px'>"
                f"Entry {cmp['entry_frame'].get('time')} · bias "
                f"{cmp.get('bias_at_entry') or '—'} · agreement "
                f"{_num(cmp.get('agreement_at_entry')):.0f}%<br>"
                f"Exit {cmp['exit_frame'].get('time')} · bias "
                f"{cmp.get('bias_at_exit') or '—'} · agreement "
                f"{_num(cmp.get('agreement_at_exit')):.0f}%<br>"
                f"{cmp['cycles_in_trade']} cycles in trade · "
                f"{len(cmp['flips_during'])} engine flips while open</div>"
                f"<div style='font-size:12.5px;color:#ffcc66;margin-top:3px'>"
                f"{cmp['verdict']}</div>"
                + (f"<div style='font-size:11.5px;color:#ff9500;margin-top:2px'>"
                   f"⚠️ engine_version changed between entry and exit — these "
                   f"rows were not produced by the same scoring logic.</div>"
                   if cmp.get("version_changed") else "")
                + "</div>", unsafe_allow_html=True)


def _reference(st) -> None:
    """What each checklist condition means and which engine owns it."""
    from .explain_panel import boundary_html
    from ..checklist import CONDITIONS, ORDER

    with st.expander("📚 Reference — what each condition means", expanded=False):
        st.markdown(
            f"<div style='{_CARD}'>"
            + "".join(
                f"<div style='display:flex;gap:8px;align-items:baseline;"
                f"margin-top:3px'>"
                f"<span style='width:172px;font-size:12px;font-weight:700;"
                f"color:#edf3f9'>{CONDITIONS[k][0]}</span>"
                f"<span style='width:44px;font-size:11px;color:#cfd9e6'>"
                f"w{CONDITIONS[k][1]}</span>"
                f"<span style='font-size:11.5px;color:#cfd9e6'>"
                f"{CONDITIONS[k][2]}</span></div>" for k in ORDER)
            + "<div style='margin-top:7px;font-size:11px;color:#9fb0c4'>"
              "✅ met · ❌ not met · ⚪ the engine could not report. Unknown "
              "conditions are excluded from readiness rather than guessed — "
              "guessing either way would be a lie in one direction."
              "</div></div>", unsafe_allow_html=True)
        st.markdown(boundary_html(), unsafe_allow_html=True)


def _performance_by_day_type(st, db, results) -> None:
    """Which market types actually produce results — Stage 68's payoff."""
    from .day_type_panel import day_type_timeline, performance_by_type
    from ..day_type import occurrence, performance_by_type as _perf

    if db is None or not hasattr(db, "get_day_type_log"):
        return
    try:
        log = db.get_day_type_log(limit=1000)
    except Exception:
        log = None
    if not log:
        st.caption("No day-type history yet — run `sql/028_day_type_log.sql` "
                   "and let a few sessions record.")
        return
    st.markdown(performance_by_type(_perf(log, results)), unsafe_allow_html=True)

    occ = occurrence(log)
    if occ:
        st.markdown(
            f"<div style='{_CARD}'>"
            f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
            f"margin-bottom:4px'>📊 How often each market type occurs</div>"
            + "".join(
                f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
                f"<span style='width:180px;color:#edf3f9'>{o['label']}</span>"
                f"<span style='width:56px;color:#cfd9e6'>{o['count']}×</span>"
                f"<span style='width:52px;color:#cfd9e6'>{o['pct']}%</span>"
                f"<span style='color:#9fb0c4'>"
                f"{('avg %.0f min' % o['avg_hold_min']) if o.get('avg_hold_min') else ''}"
                f"</span></div>" for o in occ)
            + "</div>", unsafe_allow_html=True)


def _performance_by_session(st, db, results) -> None:
    """Which sessions actually produce results — Stage 69's payoff."""
    from .session_panel import performance_by_session
    from ..session import performance_by_session as _perf

    if db is None or not hasattr(db, "get_session_log"):
        return
    try:
        log = db.get_session_log(limit=4000)
    except Exception:
        log = None
    if not log:
        st.caption("No session history yet — run `sql/029_session_log.sql` "
                   "and let a few sessions record.")
        return
    st.markdown(performance_by_session(_perf(log, results)),
                unsafe_allow_html=True)


def _session_validation(st, db, results, trades) -> None:
    """Stage 70 — is Stage 69 actually worth applying?

    The counterfactual is the point: Stage 69's modifiers have never been
    live, so this replays what they WOULD have done against the graded
    history. It changes nothing; it decides whether a human should.
    """
    from .session_validation_panel import render as _render_validation
    from ..session_validation import build as _build_validation

    if db is None or not hasattr(db, "get_session_log"):
        return
    try:
        log = db.get_session_log(limit=8000)
        recs = (db.get_session_recommendations(limit=500)
                if hasattr(db, "get_session_recommendations") else [])
    except Exception:
        log, recs = None, []
    if not log:
        st.caption("Stage 70 needs `sql/029_session_log.sql` and "
                   "`sql/030_session_validation.sql`, plus a few graded "
                   "sessions.")
        return
    with st.expander("🔬 Stage 70 — Session validation", expanded=False):
        _render_validation(st, _build_validation(log, results, trades, recs))
