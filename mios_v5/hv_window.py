"""📊 High-volume pivots in a rolling window — which side is spiking?

Totals the volume on the bars that qualified as high-volume pivots over the
last `WINDOW_S` (10 minutes by default), CALL side against PUT side, and says
which side the unusual volume clustered on.

## What it counts, and what it deliberately does not

**Pivot BARS, counted once each.** `volume_points.high_volume_pivots` attaches
a `volume` field, but that is the ROLLING SUM over the pivot's formation window
— eleven bars at the default `left=right=5`. Two pivots a few bars apart share
most of that window, so adding those figures double-counts the overlap and the
"total" grows with how clustered the pivots are rather than with how much
traded. `bar_vol` (the pivot bar's own volume, attached by
`vob_minimal._annotate_hv_pivots`) is counted instead: one bar, once.

**Only pivots, not all volume.** This is the desk's choice: the question is
*where did the UNUSUAL volume cluster*, not *which side is busier*. Most of the
time neither side has a pivot in the last ten minutes and the answer is
honestly "nothing spiking" — which is information, and is reported as such
rather than as a 50/50 split.

## It reports a magnitude, and magnitudes do not vote

Consistent with `live_confluence`'s own rule: **high volume on a side means
nothing directional on its own.** A PUT can spike because it is being bought as
a hedge or sold into strength. So this says WHERE the spike was and how big,
and leaves direction to the reads that measure it (each pivot's own CLV
buy/sell split, already in `formation_alerts`). Nothing here returns a bias.

Pure: pivots in, a dict out. No app import, no session, no I/O, no pandas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: The rolling window, in seconds. Ten minutes — the desk's figure.
WINDOW_S = 600.0

#: How far apart the two sides' totals must be, as a fraction of their sum,
#: before one is called heavier rather than "comparable". Same 10% margin
#: `live_confluence.price_action` uses for its own CALL-vs-PUT comparison, so
#: the two surfaces do not disagree about what "even" means.
MARGIN = 0.10

#: Once the lead changes hands, it will not be re-announced within this many
#: seconds — a window whose two sides are near the margin can otherwise flip
#: back and forth every cycle.
COOLDOWN_S = 300.0


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def _epoch(v: Any) -> Optional[float]:
    """A pivot's `at` (ISO string, datetime, or epoch) → epoch seconds.

    `_annotate_hv_pivots` writes an ISO string; a caller holding datetimes or
    raw epochs should not have to convert first.
    """
    if v is None:
        return None
    n = _f(v)
    if n is not None:
        return n
    if isinstance(v, datetime):
        try:
            return v.timestamp()
        except Exception:
            return None
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except Exception:
        return None


def in_window(pivots: Optional[Sequence[Mapping[str, Any]]], now: float,
              window_s: float = WINDOW_S) -> List[Mapping[str, Any]]:
    """The pivots whose bar falls inside the window, oldest first.

    A pivot without a readable `at` is dropped, not assumed recent — an
    undated pivot in a time-windowed total is a guess, and the whole point of
    `at` was to stop guessing about a pivot's identity in time.
    """
    out: List[Tuple[float, Mapping[str, Any]]] = []
    for p in (pivots or ()):
        if not isinstance(p, Mapping):
            continue
        t = _epoch(p.get("at"))
        if t is None:
            continue
        if 0 <= (now - t) <= window_s:
            out.append((t, p))
    out.sort(key=lambda r: r[0])
    return [p for _t, p in out]


def _side_total(pivots: Sequence[Mapping[str, Any]]
                ) -> Tuple[float, int, float, float]:
    """(summed bar volume, pivot count, summed buy, summed sell) for one side.

    Buy/sell come from each pivot BAR's own split (`bar_buy` / `bar_sell`,
    attached by `_annotate_hv_pivots` straight off the per-bar series) — NOT
    from the window-level `buy_pct`, which describes eleven bars and would
    report a split never measured on the bar being counted.

    ⚠️ Like every buy/sell figure in this app it is a CLV ESTIMATE from
    1-minute OHLCV — `(close − low) / (high − low)` — not a count of buy versus
    sell trades. Callers must say so.
    """
    total, n, b_tot, s_tot = 0.0, 0, 0.0, 0.0
    for p in pivots:
        v = _f(p.get("bar_vol"))
        if v is None:
            continue
        total += v
        n += 1
        b, s = _f(p.get("bar_buy")), _f(p.get("bar_sell"))
        if b is not None:
            b_tot += b
        if s is not None:
            s_tot += s
    return total, n, b_tot, s_tot


def totals(call_pivots: Optional[Sequence[Mapping[str, Any]]] = None,
           put_pivots: Optional[Sequence[Mapping[str, Any]]] = None,
           now: Optional[float] = None, window_s: float = WINDOW_S,
           margin: float = MARGIN) -> Dict[str, Any]:
    """Which side's high-volume pivots carried more volume in the window.

    `heavier` is `"CALL"`, `"PUT"`, `"comparable"` (both sides spiked, within
    `margin`), or `None` when neither side had a pivot at all — which is the
    normal quiet state and must not be reported as a tie.
    """
    t_now = _f(now)
    if t_now is None:
        t_now = datetime.now().timestamp()
    call_in = in_window(call_pivots, t_now, window_s)
    put_in = in_window(put_pivots, t_now, window_s)
    c_vol, c_n, c_buy, c_sell = _side_total(call_in)
    p_vol, p_n, p_buy, p_sell = _side_total(put_in)

    total = c_vol + p_vol
    if c_n == 0 and p_n == 0:
        heavier, share = None, None
    elif total <= 0:
        # pivots exist but carried no readable volume — say "comparable"
        # rather than inventing a winner from a count alone
        heavier, share = "comparable", None
    else:
        share = (c_vol - p_vol) / total
        heavier = ("CALL" if share >= margin else
                   "PUT" if share <= -margin else "comparable")
    def _pct(b, tot):
        return round(b / tot * 100.0, 1) if tot > 0 else None

    return {
        "call_vol": c_vol, "put_vol": p_vol,
        "call_n": c_n, "put_n": p_n,
        # per-side buy/sell inside the window — a CLV estimate, not a trade count
        "call_buy": c_buy, "call_sell": c_sell,
        "put_buy": p_buy, "put_sell": p_sell,
        "call_buy_pct": _pct(c_buy, c_buy + c_sell),
        "put_buy_pct": _pct(p_buy, p_buy + p_sell),
        "heavier": heavier,
        "share": share,
        "window_s": window_s,
    }


def latch(heavier: Optional[str], prev: Optional[Mapping[str, Any]],
          now: float, cooldown_s: float = COOLDOWN_S
          ) -> Tuple[bool, Dict[str, Any]]:
    """Fire only when the LEAD CHANGES HANDS. `(fire, new_state)`.

    Same rising-edge discipline as `flow_level_alerts.latch`, for the same
    reason: a standing condition re-announced every cycle is the alert flood
    this repo keeps having to undo. A move to `None` (nothing spiking) or to
    `"comparable"` updates the remembered side without firing — those are not a
    side taking the lead.
    """
    st = dict(prev or {})
    was = st.get("heavier")
    last = _f(st.get("last_fire")) or 0.0
    fire = False
    if (heavier in ("CALL", "PUT") and heavier != was
            and (now - last) >= cooldown_s):
        fire = True
        st["last_fire"] = now
    st["heavier"] = heavier
    return fire, st


def _vol(v: Any) -> str:
    f = _f(v)
    if f is None:
        return "—"
    return f"{f / 1e5:.1f}L" if abs(f) >= 1e5 else f"{f:,.0f}"


def _split_txt(buy_pct: Any) -> str:
    """"est. 63/37 buy/sell" for one side, or "" when unmeasured."""
    b = _f(buy_pct)
    return "" if b is None else f" · est. {b:.0f}/{100 - b:.0f} buy/sell"


def summary(t: Mapping[str, Any]) -> str:
    """One plain line for a panel. `""` when nothing spiked."""
    if not t or t.get("heavier") is None:
        return ""
    mins = int(_f(t.get("window_s")) or WINDOW_S) // 60
    c = (f"CALL {_vol(t.get('call_vol'))} ({t.get('call_n', 0)})"
         f"{_split_txt(t.get('call_buy_pct'))}")
    p = (f"PUT {_vol(t.get('put_vol'))} ({t.get('put_n', 0)})"
         f"{_split_txt(t.get('put_buy_pct'))}")
    lead = t.get("heavier")
    tail = "comparable" if lead == "comparable" else f"{lead} heavier"
    return f"{mins}m high-volume pivots · {c} vs {p} — {tail}"


def message(t: Mapping[str, Any]) -> str:
    """The alert text for a lead change. HTML, for Telegram."""
    lead = t.get("heavier")
    if lead not in ("CALL", "PUT"):
        return ""
    mins = int(_f(t.get("window_s")) or WINDOW_S) // 60
    ball = "🟢" if lead == "CALL" else "🔴"
    share = _f(t.get("share"))
    pct = (f" ({abs(share) * 100:.0f}% of the window's spike volume)"
           if share is not None else "")
    # ⚠️ The buy/sell figures are CLV estimates from 1-minute OHLCV, not a count
    # of buy versus sell trades — the text says so rather than printing bare
    # percentages that read as executions.
    cb, pb = _f(t.get("call_buy_pct")), _f(t.get("put_buy_pct"))
    if cb is None and pb is None:
        flow = ""
    else:
        cs = "—" if cb is None else f"{cb:.0f}% buy / {100 - cb:.0f}% sell"
        ps = "—" if pb is None else f"{pb:.0f}% buy / {100 - pb:.0f}% sell"
        flow = (f"\nFlow on those bars — CALL {cs}, PUT {ps} "
                f"(est., CLV from 1m bars, not tick data).")
    return (
        f"{ball} 📊 <b>{lead} side now carrying the high volume</b>\n"
        f"Over the last {mins} minutes: CALL {_vol(t.get('call_vol'))} across "
        f"{t.get('call_n', 0)} pivot(s), PUT {_vol(t.get('put_vol'))} across "
        f"{t.get('put_n', 0)}.{flow}\n"
        f"{lead} is where the unusual volume is clustering{pct} — a magnitude, "
        f"not a direction."
    )
