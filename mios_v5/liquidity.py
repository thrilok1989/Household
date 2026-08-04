"""Liquidity Intelligence — the eight things nothing else owns.

`docs/AUDIT_LIQUIDITY_INTELLIGENCE.md` checked all thirteen requested outputs
against the codebase before this file existed. **Roughly seventy per cent
already existed**, across four owners that did not know about each other — and
there were already **five** point-of-control implementations, with the Stage
71.8 audit having chosen one and written *"a fifth is forbidden"*.

So this is not a profile builder. It computes the parts that were genuinely
absent and reads everything else:

1. **Liquidity Shift** — this cycle's profile against the last
2. **Liquidity Imbalance** — the aggregate of per-row deltas
3. **Net Sentiment / Dominance** — the aggregate of per-row sentiment
4. **Sentiment Shift** — cross-cycle
5. **POC Migration · Trend · Velocity · Stability** — over one existing series
6. **Money Flow Divergence** — price direction against flow direction
7. **Level clustering** — Major/Minor/Dynamic S/R from nine level sources
8. the `LiquidityContext` (in `liquidity_context.py`)

## What it must never do

No profile is built here. No POC is computed here. No HVN/LVN classifier is
written here. A test asserts this module imports no profile builder and defines
no function whose name claims one of those facts — the same guard
`premium_structure` carries, for the same reason.

## Cross-cycle state is passed in, never stored

`Shift` needs the previous cycle to compare against. This module holds no state:
the caller passes `previous`, exactly as Stage 71.7's `build(previous=…)` does.
A module that remembers is a module two callers can disagree with.

## Everything is a classifier over published numbers

`calculate_money_flow_profile` already returns, per row: `bin_low`, `bin_high`,
`total_volume`, `bull_volume`, `bear_volume`, `delta`, `ratio`, `node_type`,
`sentiment`, `sentiment_strength`. Summing those is arithmetic, not measurement
— the same justification the 71.8 audit accepted for HVN/LVN.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ADVISORY_ONLY = True

UNKNOWN = "UNKNOWN"

VERSION = "74.0.0"

# ══════════════════════════════════════════════════════════════════════
#  vocabulary
# ══════════════════════════════════════════════════════════════════════

#: Where liquidity moved between cycles. Six states, and `Holding` is one of
#: them for the same reason Stage 71.7 added it: a profile that has not moved is
#: a fact, not an absence.
SHIFT_UP = "Shifting Up"
SHIFT_DOWN = "Shifting Down"
SHIFT_EXPANDING = "Expanding"
SHIFT_COMPRESSING = "Compressing"
SHIFT_HOLDING = "Holding"

SHIFT_STATES: Tuple[str, ...] = (
    SHIFT_UP, SHIFT_DOWN, SHIFT_EXPANDING, SHIFT_COMPRESSING, SHIFT_HOLDING,
)

#: What the point of control is doing.
POC_RISING, POC_FALLING, POC_STABLE = "Rising", "Falling", "Stable"
POC_TRENDS: Tuple[str, ...] = (POC_RISING, POC_FALLING, POC_STABLE)

#: Who holds the book, in aggregate.
BULLS, BEARS, BALANCED = "Buyers", "Sellers", "Balanced"
DOMINANCE: Tuple[str, ...] = (BULLS, BEARS, BALANCED)

#: Price and flow agreeing, or not.
DIV_NONE = "Aligned"
DIV_BULL = "Bullish Divergence"
DIV_BEAR = "Bearish Divergence"
DIVERGENCE_STATES: Tuple[str, ...] = (DIV_NONE, DIV_BULL, DIV_BEAR)

#: How a clustered level is ranked.
MAJOR, MINOR, DYNAMIC = "Major", "Minor", "Dynamic"

#: The eight facts with no other owner.
COMPUTED_HERE: Tuple[str, ...] = (
    "liquidity_shift", "liquidity_imbalance", "net_sentiment",
    "sentiment_shift", "poc_migration", "money_flow_divergence",
    "levels", "context",
)

#: Every consumed fact and the one thing that owns it. Read before changing:
#: a name appearing here that this module starts *computing* is a regression,
#: and a test asserts no producer is defined for any of them.
CONSUMED: Dict[str, str] = {
    "profile_rows": "calculate_money_flow_profile (indicators/money_flow_profile)",
    "poc_price": "calculate_money_flow_profile",
    "value_area": "compute_vpfr — the ONE POC owner (audit 71.8)",
    "dynamic_poc_series": "compute_dynamic_poc",
    "node_type": "calculate_money_flow_profile — HVN/LVN already classified",
    "row_sentiment": "calculate_money_flow_profile — per-row bull/bear split",
    "vob_zones": "analyze_vob_volume",
    "liquidity_pools": "_detect_liquidity_pools — equal highs/lows, PDH/PDL",
    "dealer_levels": "Stage 11 — Dealer Positioning",
    "gamma_flip": "Stage 11 — Dealer Positioning",
    "acceptance": "Stage 42 — Acceptance / Rejection / Trap",
    "premium_structure": "Stage 71.8 — Premium Structure",
    "premium_behaviour": "Stage 71.85 — Premium LTP Behaviour",
    "energy_acceleration": "Stage 71.7 — Premium Energy",
    "exhaustion": "Stage 50 — LTP Behaviour · Stage 71.8 volume_climax",
}

# ══════════════════════════════════════════════════════════════════════
#  thresholds — the few numbers this module chooses
# ══════════════════════════════════════════════════════════════════════

#: A POC that moved less than this fraction of the profile's range has not
#: really moved. Bin noise, not migration.
_POC_MOVE_PCT = 0.15

#: Aggregate delta beyond this share of total volume is a real imbalance.
#: Below it, buyers and sellers are matched and calling a winner is noise.
_IMBALANCE_PCT = 8.0

#: A value-area width change beyond this fraction is expansion or compression.
_WIDTH_MOVE_PCT = 12.0

#: Levels within this percentage of each other are one level, not two.
_CLUSTER_PCT = 0.12

#: A cluster carrying at least this many independent sources is Major. Two
#: sources agreeing is a coincidence; three is a level.
_MAJOR_SOURCES = 3


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _d(v) -> Dict[str, Any]:
    """A dict, whatever arrived. Every entry point promises never to raise, and
    a degraded cycle can leave a cache holding a string."""
    return dict(v) if isinstance(v, Mapping) else {}


def _rows(profile: Any) -> List[Dict[str, Any]]:
    rows = _d(profile).get("rows")
    return [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, (list, tuple)) else []


def _seq(v) -> List[Any]:
    return list(v) if isinstance(v, (list, tuple)) else []


# ══════════════════════════════════════════════════════════════════════
#  1 · 2 · 3 — the aggregates the profile never summed
# ══════════════════════════════════════════════════════════════════════

def imbalance(profile: Any) -> Dict[str, Any]:
    """Who holds the book, across the whole profile.

    `calculate_money_flow_profile` publishes `delta` per row and nothing ever
    adds them up. The sum, against total volume, is the one number that says
    whether buyers or sellers own this range — and the per-row view cannot,
    because a profile can be bullish at every high-volume node and bearish
    everywhere else.
    """
    rows = _rows(profile)
    if not rows:
        return {"imbalance": UNKNOWN, "dominance": UNKNOWN, "pct": None,
                "bull": None, "bear": None, "reporting": 0,
                "why": "no profile rows"}

    bull = sum(_f(r.get("bull_volume")) or 0.0 for r in rows)
    bear = sum(_f(r.get("bear_volume")) or 0.0 for r in rows)
    total = bull + bear
    if total <= 0:
        return {"imbalance": UNKNOWN, "dominance": UNKNOWN, "pct": None,
                "bull": bull, "bear": bear, "reporting": len(rows),
                "why": "the profile carries no volume"}

    delta = bull - bear
    pct = delta / total * 100.0
    if abs(pct) < _IMBALANCE_PCT:
        who = BALANCED
    else:
        who = BULLS if pct > 0 else BEARS
    return {
        "imbalance": round(delta, 2), "dominance": who, "pct": round(pct, 2),
        "bull": round(bull, 2), "bear": round(bear, 2),
        "reporting": len(rows),
        "why": (f"{abs(pct):.1f}% net toward {who.lower()}" if who != BALANCED
                else f"net {abs(pct):.1f}% — inside the {_IMBALANCE_PCT:.0f}% "
                     f"band where neither side owns the range"),
        "source": CONSUMED["row_sentiment"],
    }


def net_sentiment(profile: Any) -> Dict[str, Any]:
    """Bull/bear dominance **weighted by where the volume is**.

    A plain row count treats a node holding 1% of the day's volume the same as
    the point of control. Weighting by each row's `ratio` — its share of the
    busiest bin — makes the levels people actually traded carry the verdict.
    """
    rows = _rows(profile)
    if not rows:
        return {"net_sentiment": UNKNOWN, "dominance": UNKNOWN, "score": None,
                "bull_nodes": 0, "bear_nodes": 0, "why": "no profile rows"}

    bull_w = bear_w = 0.0
    bull_n = bear_n = 0
    for r in rows:
        weight = _f(r.get("ratio")) or 0.0
        word = str(r.get("sentiment") or "")
        if word == "Bullish":
            bull_w += weight
            bull_n += 1
        elif word == "Bearish":
            bear_w += weight
            bear_n += 1
    total = bull_w + bear_w
    if total <= 0:
        return {"net_sentiment": UNKNOWN, "dominance": UNKNOWN, "score": None,
                "bull_nodes": bull_n, "bear_nodes": bear_n,
                "why": "no row reported a side"}

    score = (bull_w - bear_w) / total * 100.0
    who = (BALANCED if abs(score) < _IMBALANCE_PCT
           else BULLS if score > 0 else BEARS)
    return {
        "net_sentiment": round(score, 2), "dominance": who,
        "score": round(score, 2),
        "bull_nodes": bull_n, "bear_nodes": bear_n,
        "bull_weight": round(bull_w, 3), "bear_weight": round(bear_w, 3),
        "why": f"{bull_n} bullish and {bear_n} bearish nodes, "
               f"volume-weighted to {score:+.0f}",
        "source": CONSUMED["row_sentiment"],
    }


# ══════════════════════════════════════════════════════════════════════
#  4 · 5 — cross-cycle, and the POC series
# ══════════════════════════════════════════════════════════════════════

def poc_migration(series: Optional[Sequence[Any]] = None,
                  profile: Any = None) -> Dict[str, Any]:
    """Current · previous · migration · trend · velocity · stability.

    All six from `compute_dynamic_poc`'s existing series. It is the only POC in
    this codebase that migrates — the other four are one number per call — which
    is why the spec's "Dynamic Point of Control" is a read of it and not a new
    engine.

    **Stability is the interesting one**: how often the POC changed bin over the
    series. A point of control that moves every bar is not a level anyone is
    defending, however precisely it is reported.
    """
    values = [_f(v) for v in _seq(series)]
    values = [v for v in values if v is not None]
    if not values:
        poc = _f(_d(profile).get("poc_price"))
        if poc is None:
            return {"poc": UNKNOWN, "previous": UNKNOWN, "migration": None,
                    "trend": UNKNOWN, "velocity": None, "stability": None,
                    "why": "no dynamic POC series and no profile POC",
                    "source": CONSUMED["dynamic_poc_series"]}
        return {"poc": poc, "previous": UNKNOWN, "migration": None,
                "trend": UNKNOWN, "velocity": None, "stability": None,
                "why": "a POC with no history cannot show migration",
                "source": CONSUMED["poc_price"]}

    current = values[-1]
    previous = values[-2] if len(values) >= 2 else None

    # The reference is the TRADED RANGE, not the POC series' own span.
    # Normalising a move by how far the POC itself has travelled is
    # self-defeating: a point of control that sat still all session and then
    # ticked one paise has a span of one paise, so that tick reads as a 100%
    # move and gets called a trend. Against the range price actually covered,
    # it reads as what it is.
    prof = _d(profile)
    hi, lo = _f(prof.get("price_high")), _f(prof.get("price_low"))
    span = ((hi - lo) if hi is not None and lo is not None and hi > lo
            else (max(values) - min(values)))

    migration = None if previous is None else current - previous
    # Velocity over the whole series, not the last bar — one bar's step is bin
    # width, which says more about the histogram than about the market.
    velocity = ((values[-1] - values[0]) / max(1, len(values) - 1)
                if len(values) >= 2 else None)

    moves = sum(1 for a, b in zip(values, values[1:]) if a != b)
    stability = (round(100.0 * (1.0 - moves / max(1, len(values) - 1)))
                 if len(values) >= 2 else None)

    if migration is None or span <= 0:
        trend = POC_STABLE
    elif abs(migration) < span * _POC_MOVE_PCT:
        trend = POC_STABLE
    else:
        trend = POC_RISING if migration > 0 else POC_FALLING

    return {
        "poc": round(current, 2),
        "previous": (round(previous, 2) if previous is not None else UNKNOWN),
        "migration": (round(migration, 2) if migration is not None else None),
        "trend": trend,
        "velocity": (round(velocity, 3) if velocity is not None else None),
        "stability": stability,
        "bars": len(values),
        "why": (f"POC {trend.lower()}"
                + (f" {migration:+.1f} over the last bar" if migration else "")
                + (f", stable {stability}% of bars" if stability is not None else "")),
        "source": CONSUMED["dynamic_poc_series"],
    }


def liquidity_shift(profile: Any, previous: Any = None) -> Dict[str, Any]:
    """Where liquidity moved since the last cycle.

    The one thing in the whole specification that nothing in this repo could
    answer: every profile is computed fresh and compared to nothing.

    Two axes, and they are different questions. **Location** — did the point of
    control move up or down? **Width** — did the value area widen or narrow?
    A profile can shift up while compressing, and a reader who only sees one
    number cannot tell that from a drift.
    """
    now, before = _d(profile), _d(previous)
    if not now:
        return {"shift": UNKNOWN, "poc_move": None, "width_change": None,
                "why": "no profile this cycle"}
    if not before:
        return {"shift": UNKNOWN, "poc_move": None, "width_change": None,
                "why": "no previous profile — the first cycle has nothing to "
                       "compare against",
                "source": CONSUMED["profile_rows"]}

    poc_now, poc_was = _f(now.get("poc_price")), _f(before.get("poc_price"))
    hi, lo = _f(now.get("price_high")), _f(now.get("price_low"))
    span = (hi - lo) if (hi is not None and lo is not None) else None

    va_now = _va_width(now)
    va_was = _va_width(before)

    poc_move = (poc_now - poc_was
                if poc_now is not None and poc_was is not None else None)
    width_change = (
        (va_now - va_was) / va_was * 100.0
        if va_now is not None and va_was is not None and va_was > 0 else None)

    moved = (poc_move is not None and span and span > 0
             and abs(poc_move) >= span * _POC_MOVE_PCT)
    widened = width_change is not None and width_change >= _WIDTH_MOVE_PCT
    narrowed = width_change is not None and width_change <= -_WIDTH_MOVE_PCT

    if moved:
        state = SHIFT_UP if poc_move > 0 else SHIFT_DOWN
        why = f"the point of control moved {poc_move:+.1f}"
    elif widened:
        state = SHIFT_EXPANDING
        why = f"the value area widened {width_change:+.0f}%"
    elif narrowed:
        state = SHIFT_COMPRESSING
        why = f"the value area narrowed {width_change:+.0f}%"
    else:
        state = SHIFT_HOLDING
        why = "liquidity is sitting where it was"

    return {
        "shift": state,
        "poc_move": (round(poc_move, 2) if poc_move is not None else None),
        "width_change": (round(width_change, 1)
                         if width_change is not None else None),
        "width_now": va_now, "width_before": va_was,
        "why": why,
        "source": CONSUMED["profile_rows"],
    }


def _nodes(profile: Any) -> Dict[str, Any]:
    """The rows `calculate_money_flow_profile` already classified, split by
    node type. Read, never re-classified — `node_type` is its column."""
    rows = _rows(profile)
    if not rows:
        return {"high": UNKNOWN, "low": UNKNOWN,
                "source": CONSUMED["node_type"],
                "why": "no profile rows this cycle"}
    return {
        "high": tuple(r for r in rows if str(r.get("node_type")) == "High"),
        "low": tuple(r for r in rows if str(r.get("node_type")) == "Low"),
        "source": CONSUMED["node_type"],
    }


def _va_width(profile: Mapping[str, Any]) -> Optional[float]:
    hi = _f(profile.get("value_area_high"))
    lo = _f(profile.get("value_area_low"))
    return (hi - lo) if hi is not None and lo is not None and hi >= lo else None


def sentiment_shift(profile: Any, previous: Any = None) -> Dict[str, Any]:
    """Did the book change hands since the last cycle?

    Not the same question as `liquidity_shift`. Liquidity can sit exactly where
    it was while the side holding it flips, and that is the reading worth
    catching — a level being defended by the other side is the moment before it
    breaks.
    """
    now = net_sentiment(profile)
    was = net_sentiment(previous)
    a, b = now.get("score"), was.get("score")
    if a is None or b is None:
        return {"sentiment_shift": UNKNOWN, "delta": None,
                "from": was.get("dominance", UNKNOWN),
                "to": now.get("dominance", UNKNOWN),
                "why": "one of the two cycles did not report a sentiment"}

    delta = a - b
    flipped = (now.get("dominance") != was.get("dominance")
               and BALANCED not in (now.get("dominance"), was.get("dominance")))
    return {
        "sentiment_shift": ("FLIP" if flipped
                            else "STRENGTHENING" if abs(a) > abs(b)
                            else "FADING" if abs(a) < abs(b) else "STEADY"),
        "delta": round(delta, 2),
        "from": was.get("dominance"), "to": now.get("dominance"),
        "flipped": flipped,
        "why": (f"the book flipped from {was.get('dominance')} to "
                f"{now.get('dominance')}" if flipped
                else f"sentiment moved {delta:+.0f}"),
        "source": CONSUMED["row_sentiment"],
    }


# ══════════════════════════════════════════════════════════════════════
#  6 — divergence
# ══════════════════════════════════════════════════════════════════════

def divergence(profile: Any, price_change: Any = None,
               previous: Any = None) -> Dict[str, Any]:
    """Price going one way and money flow the other.

    The audit found this genuinely missing: Stage 71.7 measures acceleration and
    Stage 50 measures exhaustion, but nothing compares the **direction of price**
    to the **direction of flow**.

    A rally on a bearish book is the classic unsupported move — and it is the
    single most useful thing this whole engine can say, because every other
    signal in the stack reads the rally as strength.
    """
    move = _f(price_change)
    sent = net_sentiment(profile)
    score = sent.get("score")

    if move is None or score is None:
        return {"divergence": UNKNOWN, "why": "need both a price move and a "
                                              "sentiment to compare",
                "price_move": move, "flow": score}

    # Neither side committed — an aligned reading here would be manufactured.
    if abs(score) < _IMBALANCE_PCT:
        return {"divergence": DIV_NONE, "price_move": move, "flow": score,
                "why": "the book is balanced — nothing to diverge from",
                "source": CONSUMED["row_sentiment"]}

    if move > 0 and score < 0:
        state, why = DIV_BEAR, "price is rising on a bearish book"
    elif move < 0 and score > 0:
        state, why = DIV_BULL, "price is falling on a bullish book"
    else:
        state, why = DIV_NONE, "price and money flow agree"

    return {"divergence": state, "price_move": round(move, 2),
            "flow": round(score, 2), "why": why,
            "source": CONSUMED["row_sentiment"]}


# ══════════════════════════════════════════════════════════════════════
#  7 — level clustering
# ══════════════════════════════════════════════════════════════════════

def _collect(profile: Any, vpfr: Any, vob: Any, pools: Any,
             dealer: Any, poc_read: Any) -> List[Dict[str, Any]]:
    """Every level any owner published, each carrying where it came from.

    Nine sources, and the audit confirmed all nine already exist. Nothing here
    measures a level; it gathers what was measured elsewhere.
    """
    out: List[Dict[str, Any]] = []

    def add(price, kind, owner):
        p = _f(price)
        if p is not None and p > 0:
            out.append({"price": p, "kind": kind, "owner": owner})

    prof = _d(profile)
    add(prof.get("poc_price"), "POC", CONSUMED["poc_price"])
    add(prof.get("value_area_high"), "VAH", CONSUMED["profile_rows"])
    add(prof.get("value_area_low"), "VAL", CONSUMED["profile_rows"])

    vp = _d(vpfr)
    add(vp.get("poc"), "POC", CONSUMED["value_area"])
    add(vp.get("vah"), "VAH", CONSUMED["value_area"])
    add(vp.get("val"), "VAL", CONSUMED["value_area"])

    add(_d(poc_read).get("poc"), "Dynamic POC", CONSUMED["dynamic_poc_series"])

    for row in _rows(profile):
        if str(row.get("node_type")) == "High":
            mid = _f(row.get("bin_low")), _f(row.get("bin_high"))
            if all(m is not None for m in mid):
                add((mid[0] + mid[1]) / 2, "HVN", CONSUMED["node_type"])

    for zone in _seq(vob):
        z = _d(zone)
        add(z.get("mid") or z.get("level"), "VOB", CONSUMED["vob_zones"])

    pl = _d(pools)
    for side in ("above", "below"):
        for pool in _seq(pl.get(side)):
            p = _d(pool)
            add(p.get("price"), str(p.get("kind") or "Pool"),
                CONSUMED["liquidity_pools"])

    dl = _d(dealer)
    add(dl.get("gamma_flip"), "Gamma Flip", CONSUMED["gamma_flip"])
    for name in ("call_wall", "put_wall", "max_pain", "support", "resistance"):
        add(dl.get(name), name.replace("_", " ").title(),
            CONSUMED["dealer_levels"])

    return out


def cluster_levels(profile: Any = None, vpfr: Any = None, vob: Any = None,
                   pools: Any = None, dealer: Any = None,
                   poc_read: Any = None, spot: Any = None,
                   tolerance_pct: Optional[float] = None) -> Dict[str, Any]:
    """Nine level sources, collapsed into levels a trader reads once.

    The audit called this the highest-value item in the specification, and the
    reason is arithmetic: nine sources publishing levels near each other are
    **one level with nine witnesses**, but rendered separately they are nine
    numbers nobody can hold in their head.

    A cluster carrying `_MAJOR_SOURCES` or more **distinct owners** is `Major`.
    Distinct owners, not distinct levels — three HVN bins from one profile is
    one witness saying the same thing three times, and counting that as
    confirmation is how a profile talks itself into a level.

    Support is below spot, resistance above. A level exactly at spot is neither
    and is reported as such rather than assigned to a side by rounding.

    `tolerance_pct` defaults to `_CLUSTER_PCT`, which is tuned for an index —
    0.12% of NIFTY is about thirty points. A premium trading at ₹100 needs a
    wider band to mean the same thing, so the caller passes one rather than this
    module guessing which instrument it was handed.
    """
    px = _f(spot)
    tol = _f(tolerance_pct)
    tol = _CLUSTER_PCT if tol is None or tol <= 0 else tol
    raw = _collect(profile, vpfr, vob, pools, dealer, poc_read)
    if not raw:
        # UNKNOWN, not an empty list. "Nothing reported a level" and "we
        # clustered and found none" are different facts, and an empty support
        # list reads as the second one — a panel would render "no support" over
        # a cycle where nothing was measured at all.
        return {"support": UNKNOWN, "resistance": UNKNOWN, "at_spot": UNKNOWN,
                "major_support": UNKNOWN, "major_resistance": UNKNOWN,
                "clusters": UNKNOWN, "sources": 0,
                "why": "no level source reported"}

    raw.sort(key=lambda r: r["price"])
    clusters: List[List[Dict[str, Any]]] = []
    for level in raw:
        if clusters:
            last = clusters[-1]
            anchor = last[0]["price"]
            if anchor > 0 and abs(level["price"] - anchor) / anchor * 100.0 <= tol:
                last.append(level)
                continue
        clusters.append([level])

    support, resistance, at_spot = [], [], []
    for group in clusters:
        prices = [g["price"] for g in group]
        owners = {g["owner"] for g in group}
        kinds = sorted({g["kind"] for g in group})
        mid = sum(prices) / len(prices)
        rank = (MAJOR if len(owners) >= _MAJOR_SOURCES
                else DYNAMIC if any("Dynamic" in k for k in kinds)
                else MINOR)
        entry = {
            "price": round(mid, 2), "rank": rank,
            "kinds": tuple(kinds), "witnesses": len(owners),
            "owners": tuple(sorted(owners)),
            "low": round(min(prices), 2), "high": round(max(prices), 2),
        }
        if px is None or abs(mid - px) < 1e-9:
            at_spot.append(entry)
        elif mid < px:
            support.append(entry)
        else:
            resistance.append(entry)

    # Nearest first — the level that matters is the one price reaches next.
    support.sort(key=lambda e: -e["price"])
    resistance.sort(key=lambda e: e["price"])

    return {
        "support": tuple(support), "resistance": tuple(resistance),
        "at_spot": tuple(at_spot),
        "major_support": tuple(e for e in support if e["rank"] == MAJOR),
        "major_resistance": tuple(e for e in resistance if e["rank"] == MAJOR),
        "clusters": len(clusters), "sources": len(raw),
        "why": f"{len(raw)} levels from {len({r['owner'] for r in raw})} owners "
               f"collapsed into {len(clusters)}",
    }


# ══════════════════════════════════════════════════════════════════════
#  the stage
# ══════════════════════════════════════════════════════════════════════

def analyse(profile: Any = None, vpfr: Any = None,
            dynamic_poc: Optional[Sequence[Any]] = None,
            vob: Any = None, pools: Any = None, dealer: Any = None,
            spot: Any = None, price_change: Any = None,
            previous: Any = None,
            tolerance_pct: Optional[float] = None) -> Dict[str, Any]:
    """One chart's liquidity intelligence. Always a dict, never raises.

    Every argument is a **finished output** — see `CONSUMED`. `previous` is the
    last cycle's `profile`, passed in rather than remembered, because a module
    that holds state is one two callers can disagree with.
    """
    prof = _d(profile)
    poc = poc_migration(dynamic_poc, prof)
    imb = imbalance(prof)
    sent = net_sentiment(prof)

    return {
        "advisory_only": ADVISORY_ONLY,
        "version": VERSION,
        "ready": bool(_rows(prof)),
        # ── computed here, and only these ──
        "liquidity_shift": liquidity_shift(prof, previous),
        "liquidity_imbalance": imb,
        "net_sentiment": sent,
        "sentiment_shift": sentiment_shift(prof, previous),
        "poc_migration": poc,
        "money_flow_divergence": divergence(prof, price_change),
        "levels": cluster_levels(prof, vpfr, vob, pools, dealer, poc, spot,
                                 tolerance_pct),
        # ── the headline reads, transported ──
        "poc": poc.get("poc"),
        "dominance": imb.get("dominance"),
        "value_area": {"high": _f(prof.get("value_area_high")),
                       "low": _f(prof.get("value_area_low")),
                       "source": CONSUMED["profile_rows"]},
        # UNKNOWN when no profile reported, for the same reason the level lists
        # are: an empty node list says "we classified and found none", which is
        # a different fact from "nothing was profiled this cycle".
        "nodes": _nodes(prof),
        # ── provenance ──
        "consumed": dict(CONSUMED),
        "computed_here": list(COMPUTED_HERE),
    }
