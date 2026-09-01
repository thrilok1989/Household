"""📊 Per-strike Call vs Put series — one figure per ATM±2 strike.

Five strikes × four measures — OI, ΔOI, and the cumulative top-of-book bid and
ask quantity — each figure showing CE against PE over the session, plus the
verdict the reference layout puts under each OI chart: which side is heavier
(support vs resistance) and, from OI direction against LTP direction, whether
that is building or covering.

⚠️ **The two `cum_*` measures carry no verdict, deliberately.** OI is a
committed position; a resting quote is an offer that can be withdrawn the
instant price reaches it. `vob_minimal` §5d already files the order book as
Tier-3 display-only and refuses it a vote in the regime, and a chart that
printed "STRONG SUPPORT" off cumulative bid quantity would contradict the
engine on the same screen. They show where the depth is; they do not say what
it means. See `running_total`.

⚠️ **Every conclusion here is arithmetic on the stored series** — no engine is
consulted and none is second-guessed. The OI/LTP quadrant rule is the standard
one, stated once in `POSITION_READ` rather than as four scattered branches:

    OI ↑ + price ↑   long building
    OI ↑ + price ↓   short building (writing)
    OI ↓ + price ↑   short covering
    OI ↓ + price ↓   long unwinding

⚠️ The "OI ↑/↓" here is the **recent trend** — the change over the last
`TREND_LOOKBACK` snapshots — NOT the drift since snapshotting began, and NOT the
day-cumulative ΔOI. Both of those net positive through a normal session (OI
accumulates), so they can only ever surface the two BUILDING rows; only the
recent direction turns negative when writers are covering *now*, which is what
lets the covering/unwinding rows appear — see `side_read`.

For a CE leg, writing is resistance; for a PE leg, writing is support. The flip is
applied in one place, `side_read`, for the same reason.

Figures in, figures out — `plotly.graph_objects` only. Streamlit renders them.

⚠️ Named `*_series`, not `*_charts`: `test_no_second_chart_was_created` globs
`ui/*chart*.py` to keep `terminal_chart.py` the ONLY price chart in the app, and
that guard is worth more than the filename. These are OI time series, not a second
price chart, and renaming kept the guard exactly as strict.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .. import strike_history as SH

#: The OI charts' pairing, and it is LEVEL semantics rather than side
#: semantics: call OI caps price, so it is drawn red for resistance, and put OI
#: supports it, so it is drawn green. The verdict printed under each OI chart
#: says exactly that ("STRONG RESISTANCE", "STRONG SUPPORT"), and the line
#: colours match the words underneath them.
CE_COLOUR, PE_COLOUR = "#ff4444", "#00cc66"

#: The depth charts' pairing, and it is SIDE semantics: green is the call side,
#: red is the put side. The desk asked for this, and the reason it is coherent
#: is that these charts carry NO level verdict to agree with — there is nothing
#: under them saying "resistance" for the red line to mean.
#:
#: ⚠️ It does mean the CALL line is red on the OI row and green on the depth row
#: directly beneath. Each chart stays internally consistent because the coloured
#: CE/PE figures in its own title are drawn from the same pair as its lines, and
#: every chart names its measure in the heading above it.
CALL_COLOUR, PUT_COLOUR = "#00cc66", "#ff4444"

#: measure → (call line colour, put line colour). Keyed for EVERY measure with
#: no default, so a measure added without a decision about its colours fails
#: `test_every_measure_names_its_colours` rather than silently inheriting a
#: pairing that means something else.
MEASURE_COLOURS: Dict[str, Tuple[str, str]] = {
    "oi":      (CE_COLOUR, PE_COLOUR),
    "chg":     (CE_COLOUR, PE_COLOUR),
    "cum_bid": (CALL_COLOUR, PUT_COLOUR),
    "cum_ask": (CALL_COLOUR, PUT_COLOUR),
    "cum_imb": (CALL_COLOUR, PUT_COLOUR),
    # Traded volume is side semantics too — green is the call side.
    "cum_buy": (CALL_COLOUR, PUT_COLOUR),
    "cum_sell": (CALL_COLOUR, PUT_COLOUR),
    "cvd": (CALL_COLOUR, PUT_COLOUR),
}

#: OI direction × price direction → what the position is doing. One map, so the
#: four cases cannot drift apart across CE and PE.
POSITION_READ = {
    (1, 1): "LONG BUILDING", (1, -1): "SHORT BUILDING",
    (-1, 1): "SHORT COVERING", (-1, -1): "LONG UNWINDING",
}

#: Which side's writing creates which level. CE writing caps price (resistance);
#: PE writing supports it.
WRITING_MEANS = {"ce": "resistance", "pe": "support"}


def _sign(x: Any, eps: float = 0.0) -> int:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0
    return 1 if v > eps else (-1 if v < -eps else 0)


#: What each chart draws. One table so a measure cannot be half-added: a field
#: spelling with no `strike_history.FIELDS` entry, a chart drawn in a unit its
#: axis does not name, or a measure with no colour pairing is a test failure
#: rather than a blank panel.
#:
#: `ce` / `pe` are TUPLES of fields. What is done with them depends on `flow`:
#:
#:   flow=None    netted first-minus-the-rest. One field is that field; two are
#:                a difference. That is what lets the imbalance measure exist
#:                without a second figure builder — a subtraction is not a new
#:                kind of chart.
#:   flow=buy/    the pair is (CUMULATIVE VOLUME field, PRICE field) and the
#:      sell/cvd  series is `flow_source.cumulative_flow`'s running buy, sell or
#:                CVD. The classification rule is NOT restated here — it lives
#:                in `flow_source.classify`, the same one `ws_worker` applies to
#:                ticks.
#:
#: ⚠️ The netting is aligned per snapshot, not by position — see `net_series`.
#:
#: `signed` means the value can be negative, so the axis gets a zero line and
#: the title figures get a `+`. `cumulative` means the y value is a running
#: total rather than the reading itself.
#:
#: OI reads naturally in lakhs and everything else in thousands — the units the
#: reference charts used, applied HERE rather than in the store, which keeps
#: absolutes.
MEASURES: Dict[str, Dict[str, Any]] = {
    "oi": {"ce": ("ce_oi",), "pe": ("pe_oi",), "flow": None,
           "div": 100_000.0, "unit": "OI (L)",
           "cumulative": False, "signed": False},
    "chg": {"ce": ("ce_chg",), "pe": ("pe_chg",), "flow": None,
            "div": 1_000.0, "unit": "ΔOI (K)",
            "cumulative": False, "signed": True},
    "cum_bid": {"ce": ("ce_bid",), "pe": ("pe_bid",), "flow": None,
                "div": 1_000.0, "unit": "Cum Bid Qty (K)",
                "cumulative": True, "signed": False},
    "cum_ask": {"ce": ("ce_ask",), "pe": ("pe_ask",), "flow": None,
                "div": 1_000.0, "unit": "Cum Ask Qty (K)",
                "cumulative": True, "signed": False},
    # Each side's own bid MINUS its own ask, accumulated. Above zero that side
    # has shown more resting demand than supply over the session; below zero,
    # more supply. CALL and PUT are read against each other, not against a
    # combined book — a call's imbalance and a put's are two separate questions.
    "cum_imb": {"ce": ("ce_bid", "ce_ask"), "pe": ("pe_bid", "pe_ask"),
                "flow": None,
                "div": 1_000.0, "unit": "Cum Bid − Ask (K)",
                "cumulative": True, "signed": True},
    # ── traded volume, decomposed ──────────────────────────────────────
    # ⚠️ `cumulative` is FALSE for these three: `cumulative_flow` already
    # returns a running total, and putting `running_total` over it again would
    # draw the integral of a cumulative series and label it volume.
    "cum_buy": {"ce": ("ce_vol", "ce_ltp"), "pe": ("pe_vol", "pe_ltp"),
                "flow": "buy",
                "div": 1_000.0, "unit": "Cum Buy Vol (K)",
                "cumulative": False, "signed": False},
    "cum_sell": {"ce": ("ce_vol", "ce_ltp"), "pe": ("pe_vol", "pe_ltp"),
                 "flow": "sell",
                 "div": 1_000.0, "unit": "Cum Sell Vol (K)",
                 "cumulative": False, "signed": False},
    "cvd": {"ce": ("ce_vol", "ce_ltp"), "pe": ("pe_vol", "pe_ltp"),
            "flow": "cvd",
            "div": 1_000.0, "unit": "CVD (K)",
            "cumulative": False, "signed": True},
}

#: Measures built by decomposing traded volume rather than plotting a stored
#: field. Named so a panel can caption them with where the split came from.
FLOW_MEASURES = tuple(m for m, s in MEASURES.items() if s["flow"])

#: ⚠️ THE LABEL for the volume rows, and it is not optional. The desk's
#: standing rule is that an estimate and a measurement are never presented as
#: the same thing. This split is neither tick data nor 1-minute CLV: it is
#: everything that traded between two chain snapshots, assigned to one side by
#: whichever way the LTP ended over that interval. Real volume, honestly
#: attributed, at roughly twenty-second granularity — and the panel says so.
FLOW_NOTE = ("buy/sell split by LTP direction between chain snapshots (~20s "
             "each) — real traded volume, but not tick data and not 1-min CLV")

#: Measures whose y value is a running total rather than the reading itself.
CUMULATIVE = tuple(m for m, s in MEASURES.items() if s["cumulative"])

#: What above and below the zero line mean, for the panel to print. The chart
#: cannot carry this in an axis label and a reader should not have to infer it.
#:
#: ⚠️ It stops at what was SHOWN. A book leaning to the bid is not a forecast —
#: the quantity can be pulled, and `vob_minimal` §5d gives the book no vote for
#: exactly that reason.
IMBALANCE_NOTE = ("above zero = that side's book has shown more bid than ask "
                  "depth over the session; below zero = more ask than bid")


def net_series(store: Any, strike: Any,
               fields: Sequence[str]) -> Dict[str, List[Any]]:
    """One field's series, or `fields[0] − fields[1] − …` netted per snapshot.

    ⚠️ **Aligned on the snapshot timestamp, never by position.** `SH.series`
    drops readings the chain did not carry rather than zero-filling them, so a
    snapshot with a bid but no ask shortens one list and not the other, and
    `zip`ping the two would subtract an ask from a *different minute's* bid —
    silently, and increasingly wrongly the more gaps there are. A timestamp that
    is missing any leg produces no point at all, which is the same rule
    `SH.series` already applies to a missing reading.
    """
    fs = tuple(fields or ())
    if not fs:
        return {"t": [], "v": []}
    base = SH.series(store, strike, fs[0])
    if len(fs) == 1:
        return base
    others = []
    for f in fs[1:]:
        s = SH.series(store, strike, f)
        others.append(dict(zip(s["t"], s["v"])))
    ts: List[Any] = []
    vs: List[Any] = []
    for t, v in zip(base["t"], base["v"]):
        if any(t not in o for o in others):
            continue
        ts.append(t)
        vs.append(v - sum(o[t] for o in others))
    return {"t": ts, "v": vs}


def flow_series(store: Any, strike: Any, fields: Sequence[str],
                component: str) -> Dict[str, List[Any]]:
    """Running buy / sell / CVD for one strike, from stored volume and LTP.

    `fields` is `(cumulative-volume field, price field)`. The decomposition is
    `flow_source.cumulative_flow`'s — nothing about who was buying is decided
    here, which is the point: `flow_source.classify` owns that rule and
    `ws_worker` applies the same one to ticks.

    ⚠️ The two legs are aligned ON THE SNAPSHOT, like `net_series`, and for the
    same reason: `SH.series` drops readings the chain did not carry, so pairing
    them by position would attribute one minute's volume to another minute's
    price move.

    ⚠️ The points are stamped with the LATER timestamp of each interval. A
    reading covering 10:00→10:00:20 belongs at 10:00:20, when the volume had
    actually traded — stamping it at the start would draw every point twenty
    seconds before it could have been known.
    """
    from .. import flow_source as FS

    if len(fields or ()) != 2:
        return {"t": [], "v": []}
    vol_f, price_f = fields[0], fields[1]
    v_s, p_s = SH.series(store, strike, vol_f), SH.series(store, strike, price_f)
    prices = dict(zip(p_s["t"], p_s["v"]))
    ts: List[Any] = []
    vols: List[Any] = []
    pxs: List[Any] = []
    for t, v in zip(v_s["t"], v_s["v"]):
        if t not in prices:
            continue
        ts.append(t)
        vols.append(v)
        pxs.append(prices[t])
    got = FS.cumulative_flow(pxs, vols)
    series = got.get(component) or []
    # ⚠️ Stamped from the returned INDEX, never by slicing. Intervals with no
    # volume are skipped, so `ts[1:]` would put every point after a skip at the
    # wrong time — silently, and further out the more gaps there are.
    return {"t": [ts[i] for i in got.get("i") or ()], "v": list(series)}


def running_total(vals: Sequence[Any]) -> List[float]:
    """Running sum of a series, one output per numeric input.

    ⚠️ **What a cumulative resting-quote total is, and is not.** `bidQty` is a
    LEVEL — how many contracts are sitting on the bid at the moment of the
    snapshot — not a flow like traded volume. Adding those snapshots up counts
    the same untouched order once every cycle it stays there, so the curve is
    not "contracts bought". It is a **time-weighted total of shown depth**: its
    slope is the average resting size, and CE against PE says which side has
    displayed more willingness to transact over the session. That is a real
    comparison, and it is the one the chart is labelled with.

    ⚠️ It is also the softest evidence on the screen. Resting quotes can be
    pulled the instant they are approached, which is why the app already files
    the order book as Tier-3, display-only, and refuses it a vote in the regime
    (`vob_minimal.py` §5d). Nothing here votes either.

    Non-numeric entries are skipped rather than treated as zero — a gap in the
    feed is not a moment when the book was empty.
    """
    out: List[float] = []
    total = 0.0
    for v in vals or ():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if v != v:  # NaN
            continue
        total += float(v)
        out.append(total)
    return out


#: how many snapshots back "recent" spans for the building-vs-covering read. At
#: the ~18s snapshot cadence this is roughly the last 5 minutes — long enough not
#: to flip on one noisy print, short enough to show the CURRENT phase.
TREND_LOOKBACK = 15


def _window(vals: Sequence[Any],
            lookback: int) -> Tuple[Optional[float], Optional[float]]:
    """`(earlier, latest)` over the last `lookback` snapshots — or the whole
    series when it is shorter. `(None, None)` with fewer than two points."""
    nums = [v for v in vals if isinstance(v, (int, float))]
    if len(nums) < 2:
        return None, None
    earlier = nums[max(0, len(nums) - 1 - int(lookback))]
    return earlier, nums[-1]


def side_read(oi: Sequence[Any], ltp: Sequence[Any], side: str,
              lookback: int = TREND_LOOKBACK) -> Dict[str, Any]:
    """`{state, oi_pct, ltp_pct, means}` for one side of one strike.

    `means` is what the state implies for price — resistance or support — and is
    only set for the two WRITING/COVERING cases, because a long build in an option
    is not a statement about the index level.

    ⚠️ **Direction is the RECENT trend, over the last `lookback` snapshots — not
    the drift since collection began, and not the day-cumulative ΔOI.** Both of
    those net *positive* through a normal session (OI accumulates), so the panel
    could only ever say BUILDING — which is exactly the bug reported: every strike
    stuck on LONG/SHORT BUILDING, never covering. What separates writers *adding*
    from writers *covering* is which way OI is moving **now**, so a strike whose
    OI has turned down in the last few minutes reads as covering even while the
    day is still net-long OI. On a series of two points the window is those two,
    so the quadrant rule is unchanged for callers that pass a before/after pair.
    """
    o_a, o_b = _window(oi, lookback)
    l_a, l_b = _window(ltp, lookback)
    if o_a is None or l_a is None:
        return {"state": None, "oi_pct": None, "ltp_pct": None, "means": None}
    d_oi, d_ltp = _sign(o_b - o_a), _sign(l_b - l_a)
    state = POSITION_READ.get((d_oi, d_ltp))
    means = None
    if state == "SHORT BUILDING":
        means = f"{WRITING_MEANS.get(side, '')} building"
    elif state == "SHORT COVERING":
        means = f"{WRITING_MEANS.get(side, '')} weakening"
    return {"state": state,
            "oi_pct": (o_b - o_a) / o_a * 100 if o_a else None,
            "ltp_pct": (l_b - l_a) / l_a * 100 if l_a else None,
            "means": means}


def strike_read(store: Any, strike: Any) -> Dict[str, Any]:
    """Both sides of one strike, plus which is heavier right now."""
    out: Dict[str, Any] = {}
    for side, oi_f, ltp_f in (("ce", "ce_oi", "ce_ltp"),
                              ("pe", "pe_oi", "pe_ltp")):
        oi = SH.series(store, strike, oi_f)["v"]
        ltp = SH.series(store, strike, ltp_f)["v"]
        # the RECENT trend of OI drives building-vs-covering; see `side_read`.
        out[side] = side_read(oi, ltp, side)
        out[f"{side}_oi"] = oi[-1] if oi else None
    ce, pe = out.get("ce_oi"), out.get("pe_oi")
    if isinstance(ce, (int, float)) and isinstance(pe, (int, float)) and ce > 0 and pe > 0:
        ratio = pe / ce
        out["heavier"] = "PE" if pe > ce else ("CE" if ce > pe else None)
        out["ratio"] = ratio if pe > ce else (ce / pe if ce > pe else 1.0)
        # ⚠️ The same two thresholds the reference layout used, stated once.
        out["strength"] = ("STRONG" if out["ratio"] >= 2.0 else
                           "MODERATE" if out["ratio"] >= 1.3 else "WEAK")
        # ⚠️ Only when one side really IS heavier. `"support" if heavier == "PE"
        # else "resistance"` sent the None case — CE and PE exactly equal — down the
        # else branch, and the render showed "WEAK RESISTANCE · 1.0×" on a strike
        # with 9.0L against 9.0L. Equal OI is neither; a balanced strike says so.
        if out["heavier"]:
            out["level"] = "support" if out["heavier"] == "PE" else "resistance"
        else:
            out["level"], out["strength"] = None, None
            out["balanced"] = True
        # ⚠️ A level is made by WRITERS. The ratio only says which side is heavier,
        # and the render showed "STRONG RESISTANCE · 6.0×" sitting directly above
        # "CE: LONG BUILDING" — 6× the call OI, but accumulated by BUYERS, which is
        # the opposite of a ceiling. The ratio is not silently rewritten; the
        # contradiction is stated, so the two lines stop disagreeing.
        heavy = (out.get((out["heavier"] or "").lower()) or {}).get("state")
        out["level_state"] = heavy
        if heavy in ("LONG BUILDING", "LONG UNWINDING"):
            out["level_note"] = (
                f"weight only — the heavy {out['heavier']} side is buyers, "
                f"not writers")
    return out


def figures(store: Any, measure: str = "oi"):
    """`[(strike, label, figure)]` — one CE-vs-PE chart per strike.

    `measure` is any key of `MEASURES`. Returns `[]` when there is nothing to
    plot, so a caller draws no empty axes.

    Three families, and they are not the same kind of number:

      · `oi` / `chg`                  what the exchange reports, plotted
      · `cum_bid` / `cum_ask` /       the running total of RESTING quantity —
        `cum_imb`                     see `running_total` for what that total
                                      does and does not mean
      · `cum_buy` / `cum_sell` /      TRADED volume, decomposed by LTP
        `cvd`                         direction — see `FLOW_NOTE`, which the
                                      panel is expected to print
    """
    try:
        import plotly.graph_objects as go
    except Exception:
        return []
    spec = MEASURES.get(measure)
    if spec is None:
        return []
    div, unit = spec["div"], spec["unit"]
    cumulate, signed = spec["cumulative"], spec["signed"]
    # ⚠️ Per measure, not module-wide. The OI charts pair red with the CALL side
    # because red means RESISTANCE there and a verdict underneath says so; the
    # depth charts have no such verdict and pair green with the CALL side.
    # Everything below — lines, markers and the coloured figures in the title —
    # reads from this one pair, so a chart cannot end up with a green line and a
    # red number for the same side.
    c_colour, p_colour = MEASURE_COLOURS[measure]
    window = SH.strikes(store)
    if not window:
        return []
    lab = SH.labels(window)

    out = []
    for k in window:
        if spec["flow"]:
            ce = flow_series(store, k, spec["ce"], spec["flow"])
            pe = flow_series(store, k, spec["pe"], spec["flow"])
        else:
            ce = net_series(store, k, spec["ce"])
            pe = net_series(store, k, spec["pe"])
        if cumulate:
            # ⚠️ Cumulated over the series that EXISTS, so a snapshot the feed
            # skipped does not add a zero. `series()` already drops missing
            # readings rather than zero-filling them, for the same reason.
            ce = {"t": ce["t"], "v": running_total(ce["v"])}
            pe = {"t": pe["t"], "v": running_total(pe["v"])}
        if not ce["v"] and not pe["v"]:
            continue
        # ⚠️ A single stored point needs a marker you can SEE and no time axis. At
        # size 3 the first snapshot rendered as a speck, under four x-ticks all
        # reading the same minute — which looked like an empty chart with clutter
        # rather than one honest observation.
        lone = max(len(ce["v"]), len(pe["v"])) < 2
        fig = go.Figure()
        for s, name, colour in ((ce, "Call", c_colour), (pe, "Put", p_colour)):
            if s["v"]:
                fig.add_trace(go.Scatter(
                    x=[_ts(t) for t in s["t"]],
                    y=[v / div for v in s["v"]],
                    mode="markers" if lone else "lines+markers", name=name,
                    line=dict(color=colour, width=2),
                    marker=dict(size=11 if lone else 3, color=colour)))
        # A measure that can go negative needs the axis to say where zero is —
        # on the imbalance charts the crossing IS the reading.
        if signed:
            fig.add_hline(y=0, line_dash="dash", line_color="white",
                          line_width=0.5)
        last_ce = (ce["v"][-1] / div) if ce["v"] else 0.0
        last_pe = (pe["v"][-1] / div) if pe["v"] else 0.0
        suffix = "L" if div >= 100_000.0 else "K"
        sign = "+" if (signed and last_ce >= 0) else ""
        sign_pe = "+" if (signed and last_pe >= 0) else ""
        # ⚠️ The latest values are COLOURED IN THE TITLE and the legend is off.
        # With a legend at y=1.02 and a three-line title, the two drew on top of
        # each other and the render showed "ATM ₹24600 CE: 4…" clipped behind the
        # key — five times over. Colouring the numbers makes the key redundant
        # instead of just moving the collision somewhere else.
        fig.update_layout(
            title=dict(
                text=(f"<b>{lab.get(k, '')}</b> · ₹{k}<br>"
                      f"<span style='color:{c_colour}'>CE "
                      f"{sign}{last_ce:.1f}{suffix}</span>"
                      f"<span style='color:#7c8798'>  ·  </span>"
                      f"<span style='color:{p_colour}'>PE "
                      f"{sign_pe}{last_pe:.1f}{suffix}</span>"),
                font=dict(size=12), x=0.5, xanchor="center"),
            template="plotly_dark", height=280, showlegend=False,
            margin=dict(l=10, r=10, t=54, b=30),
            xaxis=dict(tickformat="%H:%M", title="",
                       showticklabels=not lone),
            yaxis=dict(title=unit),
            plot_bgcolor="#1e1e1e", paper_bgcolor="#1e1e1e")
        out.append((k, lab.get(k, ""), fig))
    return out


def _ts(t: Any):
    """Epoch seconds → an IST datetime, so the axis reads in market time."""
    try:
        from datetime import datetime

        import pytz
        return datetime.fromtimestamp(float(t), pytz.timezone("Asia/Kolkata"))
    except Exception:
        return t


def caption(store: Any) -> str:
    """How much history there is — never a bare chart with no provenance.

    ⚠️ Three states, because the render showed the middle one wrong twice. First it
    read "1 snapshot(s) · ATM±2 · OI in lakhs, ΔOI in thousands" — repeating the
    ATM±2 the heading already carried and quoting units for charts that were not
    drawn. Then it said a series needs two points and nothing was plotted, which
    was true of the code and wrong as a design: one snapshot IS the current level at
    each strike. Now it says what one snapshot can and cannot tell you.
    """
    r = SH.read(store)
    n = r["n"]
    if not n:
        return "no snapshots yet — the series builds as the chain refreshes"
    if n < 2:
        return ("first snapshot — current levels only, the build direction needs "
                "a second · OI in lakhs, ΔOI in thousands")
    span = (f" over {r['span_s'] / 60:.0f} min" if r.get("span_s") else "")
    return f"{n} snapshots{span} · OI in lakhs, ΔOI in thousands"


def depth_caption(store: Any) -> str:
    """Provenance for the cumulative bid/ask panel — including the caveat.

    ⚠️ The caveat is IN THE CAPTION, not in a docstring nobody reading the
    dashboard will open. A rising cumulative bid curve looks exactly like
    accumulated buying and is not: it is the same resting quantity counted once
    per snapshot it stays on the book, and it can be pulled the moment price
    arrives. The app already files the order book as Tier-3 display-only and
    gives it no vote; a chart of it has to say the same thing.
    """
    r = SH.read(store)
    n = r["n"]
    if not n:
        return ("no snapshots yet — the depth series builds as the chain "
                "refreshes")
    base = ("top-of-book bid/ask quantity, summed across the session · "
            "⚠️ shown depth, not traded volume — resting quotes can be pulled")
    if n < 2:
        return f"first snapshot — one point per strike so far · {base}"
    span = (f" over {r['span_s'] / 60:.0f} min" if r.get("span_s") else "")
    return f"{n} snapshots{span} · {base}"
