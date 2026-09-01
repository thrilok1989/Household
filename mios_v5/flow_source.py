"""🟢/🟡 Where a buy/sell reading came from — and never mixing two sources.

One question: *what is the best flow measurement available for this
instrument right now, and how good is it?* Three sources, in falling order of
truth:

    1. TICK      real per-trade aggression from `ws_worker`'s tick rule
                 (LTP up → buy, down → sell, unchanged → neither), streamed
                 sub-second and stored in Supabase `dhan_ticks`.
    2. INTRABAR  LuxAlgo's lower-timeframe method: decompose a higher-timeframe
                 bar into the 1-minute bars inside it and classify each whole
                 sub-bar by its own close-vs-open. Real decomposition, coarser
                 than ticks.
    3. CLV       a single bar's shape, `(close − low) / (high − low)`. An
                 inference, not a measurement. The fallback.

## The rule this module exists to enforce

**A tick reading and a CLV estimate must never be presented as the same
thing.** They differ in kind, not just in precision: one counts what traded on
which side, the other guesses from where a candle closed. So every result
carries its `source`, its `label`, and a `confident` flag, and the panels are
expected to show them — 🟢 TICK FLOW · Source: Live Tick Data versus 🟡
ESTIMATED FLOW · Source: Candle CLV Estimate.

## Not another engine

This picks a source and reports it. It does not compute buy/sell itself —
`ws_worker` owns the tick rule, `indicators.order_flow` owns CLV, and the
intrabar decomposition is a sum over sub-bars the caller already has. Adding a
fourth opinion about who was buying is exactly what this is meant to avoid.

Pure: numbers in, a dict out. No app import, no session, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

TICK = "tick"
INTRABAR = "intrabar"
CLV = "clv"
NONE = "none"

#: source → (badge, human label) for the panels. The badge is the honesty
#: signal: green only for a real per-trade measurement.
LABELS = {
    TICK: ("🟢 TICK FLOW", "Live Tick Data"),
    INTRABAR: ("🟢 INTRABAR FLOW", "1-min Sub-bar Decomposition"),
    CLV: ("🟡 ESTIMATED FLOW", "Candle CLV Estimate"),
    NONE: ("⚪ NO FLOW", "Not available"),
}

#: Only TICK and INTRABAR are actual measurements of what traded. CLV is an
#: inference from candle shape and is never presented as confident.
CONFIDENT = (TICK, INTRABAR)

#: A tick row older than this is stale — the worker flushes every ~1.5s, so
#: anything beyond a minute means it has stopped or lost the instrument.
TICK_MAX_AGE_S = 60.0

#: buy% above / below this reads as one-sided. Same 60/40 the pivot split uses,
#: so one number does not mean two different things on two panels.
BUY_DOMINANT = 60.0
SELL_DOMINANT = 40.0


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def _pack(source: str, buy: Optional[float], sell: Optional[float],
          extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    badge, label = LABELS.get(source, LABELS[NONE])
    b, s = _f(buy), _f(sell)
    total = (b or 0.0) + (s or 0.0)
    if b is None or s is None or total <= 0:
        pct = delta = None
        aggression = "unknown"
    else:
        pct = b / total * 100.0
        delta = b - s
        aggression = ("Strong Buying" if pct >= 75 else
                      "Buying" if pct > BUY_DOMINANT else
                      "Strong Selling" if pct <= 25 else
                      "Selling" if pct < SELL_DOMINANT else "Balanced")
    out = {
        "source": source, "badge": badge, "label": label,
        "confident": source in CONFIDENT,
        "buy": b, "sell": s,
        "buy_pct": None if pct is None else round(pct, 1),
        "sell_pct": None if pct is None else round(100.0 - pct, 1),
        "delta": delta,
        "aggression": aggression,
    }
    if extra:
        out.update(extra)
    return out


def from_tick(row: Optional[Mapping[str, Any]], now: Optional[float] = None,
              max_age_s: float = TICK_MAX_AGE_S) -> Optional[Dict[str, Any]]:
    """A `dhan_ticks` row → a tick-flow reading, or `None` when unusable.

    `None` — not a zeroed reading — when the row is missing, stale, or has no
    classified volume yet. A leg the worker is not subscribed to must fall
    through to the next source, not report 0/0 as if it were balanced.

    ⚠️ `buy_vol`/`sell_vol`, never `(cum_delta, volume)`. `volume` counts the
    unchanged-price ticks the tick rule classifies as neither side, so
    `buy + sell` cannot be recovered from that pair — see sql/038.
    """
    if not isinstance(row, Mapping):
        return None
    b, s = _f(row.get("buy_vol")), _f(row.get("sell_vol"))
    if b is None or s is None or (b + s) <= 0:
        return None
    age = _f(row.get("age_s"))
    if age is None:
        t = _f(row.get("updated_ts"))
        if t is not None and now is not None:
            age = now - t
    if age is not None and age > max_age_s:
        return None
    return _pack(TICK, b, s, {
        "age_s": age,
        "cum_delta": _f(row.get("cum_delta")),
    })


BUY, SELL = "buy", "sell"


def classify(before: Any, after: Any) -> Optional[str]:
    """THE RULE, in one place: price up → buy, down → sell, unchanged → neither.

    `"buy"`, `"sell"`, or `None` — and `None` for an unreadable pair, which is
    not the same as unchanged but is treated the same way, because both mean
    "this interval's volume cannot be attributed to a side".

    ⚠️ This is the tick rule `ws_worker._apply_tick` applies to individual
    ticks and the close-vs-open rule the reference indicator applies to
    sub-bars. They are the same rule at different granularities, so it is
    written once here and called from everywhere rather than being typed out
    again each time the granularity changes. An `>=` in one copy and a `>` in
    another is exactly how two panels come to disagree about who was buying.

    ⚠️ Unchanged counts to NEITHER side. It is not half a buy and half a sell:
    volume that traded without moving the price says nothing about which side
    was the aggressor, and splitting it would manufacture a balance nobody
    measured.
    """
    a, b = _f(before), _f(after)
    if a is None or b is None:
        return None
    if b > a:
        return BUY
    if b < a:
        return SELL
    return None


def from_intrabar(sub_bars: Optional[Sequence[Mapping[str, Any]]]
                  ) -> Optional[Dict[str, Any]]:
    """Lower-timeframe decomposition — LuxAlgo's LTF method.

    Each sub-bar's WHOLE volume is assigned by its own close-vs-open via
    `classify`. `None` when there is nothing to decompose, so the caller falls
    through to CLV.

    ⚠️ This is what makes a higher-timeframe reading real rather than inferred:
    ten 1-minute bars inside a 10-minute candle give ten independent votes,
    where CLV on the 10-minute candle gives one shape guess. It cannot help a
    1-minute bar — there is no finer bar available from the feed.
    """
    if not sub_bars:
        return None
    buy = sell = 0.0
    n = 0
    for b in sub_bars:
        if not isinstance(b, Mapping):
            continue
        o, c, v = _f(b.get("open")), _f(b.get("close")), _f(b.get("volume"))
        if o is None or c is None or v is None or v <= 0:
            continue
        n += 1
        side = classify(o, c)
        if side == BUY:
            buy += v
        elif side == SELL:
            sell += v
    if n == 0 or (buy + sell) <= 0:
        return None
    return _pack(INTRABAR, buy, sell, {"sub_bars": n})


def cumulative_flow(prices: Optional[Sequence[Any]],
                    cum_volumes: Optional[Sequence[Any]]
                    ) -> Dict[str, List[float]]:
    """A price series + a CUMULATIVE volume series → running buy / sell / CVD.

    The same decomposition `from_intrabar` performs, kept as a running series
    rather than collapsed to one total: for each consecutive pair, the volume
    that traded between them is `cum_volumes[i] − cum_volumes[i-1]`, and
    `classify` assigns that whole amount to a side from the price move over the
    same interval.

    Returns `{"buy": [...], "sell": [...], "cvd": [...], "i": [...]}`, one
    point per interval that carried volume. A single reading produces none:
    there is no interval before the first sample, and inventing a zero point
    would draw the session as starting flat when it simply had not started.

    ⚠️ `i` is the index IN THE INPUT of each point's later end, and callers must
    use it to stamp their x-axis. Intervals with no volume are skipped, so the
    output is shorter than `n − 1` and slicing the input positionally would put
    every point after a skip at the wrong time — silently, and further out the
    more gaps there are.

    ⚠️ `cum_volumes` is the exchange's running day total, not per-interval
    volume — that is what the option chain reports (`totalTradedVolume_CE`).
    Passing per-interval volume here would differences it a second time.

    ⚠️ A NEGATIVE difference is dropped, not counted as a sell. Day-cumulative
    volume cannot fall; a drop means the feed reset, rolled to a new contract,
    or returned a bad read, and treating it as selling would print a phantom
    sell spike exactly when the data is least trustworthy.

    ⚠️ **This is not tick data.** Each interval is one classification of
    everything that traded between two chain snapshots — roughly twenty seconds
    of trades attributed to whichever way the LTP happened to end. It is real
    volume, honestly attributed at that granularity, and the caller must label
    it as such rather than presenting it beside a tick reading.
    """
    ps = list(prices or ())
    vs = list(cum_volumes or ())
    n = min(len(ps), len(vs))
    buy = sell = 0.0
    out: Dict[str, List[Any]] = {"buy": [], "sell": [], "cvd": [], "i": []}
    for i in range(1, n):
        v0, v1 = _f(vs[i - 1]), _f(vs[i])
        if v0 is None or v1 is None:
            continue
        traded = v1 - v0
        if traded <= 0:
            # no trades, or a reset/rollover — see the warning above
            continue
        side = classify(ps[i - 1], ps[i])
        if side == BUY:
            buy += traded
        elif side == SELL:
            sell += traded
        # unchanged or unreadable → neither side, but the point is still
        # emitted so the three series stay aligned with each other
        out["buy"].append(buy)
        out["sell"].append(sell)
        out["cvd"].append(buy - sell)
        out["i"].append(i)
    return out


def from_clv(buy: Any, sell: Any) -> Optional[Dict[str, Any]]:
    """The CLV fallback, from already-computed per-bar buy/sell volume
    (`indicators.order_flow.split`). `None` when there is nothing to report."""
    b, s = _f(buy), _f(sell)
    if b is None or s is None or (b + s) <= 0:
        return None
    return _pack(CLV, b, s)


def resolve(tick_row: Optional[Mapping[str, Any]] = None,
            sub_bars: Optional[Sequence[Mapping[str, Any]]] = None,
            clv_buy: Any = None, clv_sell: Any = None,
            now: Optional[float] = None,
            max_age_s: float = TICK_MAX_AGE_S) -> Dict[str, Any]:
    """The best available reading, in the order tick → intrabar → CLV.

    Always returns a dict; `source` is `"none"` when nothing was usable, which
    a panel should render as "not available" rather than as balanced flow.
    """
    for got in (from_tick(tick_row, now=now, max_age_s=max_age_s),
                from_intrabar(sub_bars),
                from_clv(clv_buy, clv_sell)):
        if got is not None:
            return got
    return _pack(NONE, None, None)


def line(read: Optional[Mapping[str, Any]]) -> str:
    """One plain line for a panel or an alert, badge first, source named.

    The source is not optional decoration — it is the difference between a
    measurement and a guess, and the reader is entitled to know which they are
    looking at.
    """
    r = read or {}
    badge = str(r.get("badge") or LABELS[NONE][0])
    label = str(r.get("label") or LABELS[NONE][1])
    bp, sp = r.get("buy_pct"), r.get("sell_pct")
    if bp is None or sp is None:
        return f"{badge} · Source: {label}"
    d = _f(r.get("delta"))
    d_s = "" if d is None else f" · CVD {d:+,.0f}"
    return (f"{badge}  Buy {bp:.0f}% · Sell {sp:.0f}%{d_s} · "
            f"{r.get('aggression', 'Balanced')} · Source: {label}")
