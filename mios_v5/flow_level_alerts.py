"""📨 Flow-at-level alerts — a note to the ALTERNATE Telegram bot when one option
side is being traded harder than the other *while spot sits on the matching
level*.

Two events, and only two, both to the second (alert) bot:

    · PUT heavier than CALL, and spot AT RESISTANCE   → the resistance is being
      defended with puts
    · CALL heavier than PUT, and spot AT SUPPORT       → the support is being
      defended with calls

"Heavier" is the cross-leg comparison the owner described against the existing
`ATM±1 CALL vs PUT — CVD / Cum Buy / Cum Sell` graph: a side's activity is its
*cumulative buy + cumulative sell* (total participation, CLV-weighted from 1m
OHLCV — the graph's own numbers, not recomputed here).

⚠️ **This decides nothing about volume or S/R itself.** `vob_minimal` reads the
graph's latest cumulative buy/sell for each side and the ranked
support/resistance, and passes them in. This module only says whether the pair of
conditions is met right now and, separately, whether *that* is a fresh crossing
worth sending — the flood the desk saw from the pivot alerts came from re-emitting
a standing condition every cycle, so the latch here fires on the RISING EDGE only
and re-arms when the condition clears.

Pure: numbers in, a decision and a message out. No app import, no session, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

#: How close spot must be to a level to count as "at" it, as a FRACTION of spot.
#: 0.25% — the owner's figure. A fraction, not a point band, so it means the same
#: thing on NIFTY at 24,000 and on a 77,700 underlying.
BAND_PCT = 0.0025

#: Once fired, the same side/level event will not re-fire within this many seconds
#: even if the condition keeps flipping across the band edge. Belt-and-braces on
#: top of the rising-edge latch, because a level the price is grinding on can
#: chatter true/false every cycle.
COOLDOWN_S = 300.0

#: The two events this module knows about. `heavier` is the side whose flow must
#: exceed the other; `level` is the S/R the spot must be sitting on.
EVENTS = {
    "put_at_resistance": {"heavier": "put", "level": "resistance"},
    "call_at_support": {"heavier": "call", "level": "support"},
}


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def activity(buy: Any, sell: Any) -> Optional[float]:
    """One side's total participation: cumulative buy + cumulative sell.

    `None` when neither number is readable — a side with no flow figure cannot be
    compared, and treating it as 0 would make the OTHER side spuriously "heavier".
    """
    b, s = _f(buy), _f(sell)
    if b is None and s is None:
        return None
    return (b or 0.0) + (s or 0.0)


def at_level(spot: Any, level: Any, band_pct: float = BAND_PCT) -> bool:
    """Is spot within `band_pct` of the level? `False` on any unreadable input —
    a missing level is not a touch."""
    sp, lv = _f(spot), _f(level)
    if sp is None or lv is None or sp <= 0:
        return False
    return abs(sp - lv) <= band_pct * sp


def assess(call_flow: Any, put_flow: Any, spot: Any,
           support: Any = None, resistance: Any = None,
           band_pct: float = BAND_PCT) -> Dict[str, Dict[str, Any]]:
    """For each event, is it active THIS cycle, and the facts behind it.

    Returns `{event: {active, level, heavier_flow, other_flow, ...}}`. Active means
    both halves hold: the named side is strictly heavier AND spot is on the level.
    Strictly — equal flow names no winner, so it is not an event.
    """
    # `call_flow`/`put_flow` are already the per-side ACTIVITY totals — the caller
    # sums buy+sell via `activity()` and passes the totals in.
    cf = _f(call_flow)
    pf = _f(put_flow)
    sp = _f(spot)
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in EVENTS.items():
        level = resistance if spec["level"] == "resistance" else support
        lv = _f(level)
        on_level = at_level(sp, lv, band_pct)
        if spec["heavier"] == "put":
            heavier_ok = pf is not None and cf is not None and pf > cf
            heavy_flow, other_flow = pf, cf
        else:
            heavier_ok = cf is not None and pf is not None and cf > pf
            heavy_flow, other_flow = cf, pf
        out[name] = {
            "active": bool(on_level and heavier_ok),
            "on_level": on_level,
            "heavier_ok": bool(heavier_ok),
            "level": lv,
            "spot": sp,
            "heavier_flow": heavy_flow,
            "other_flow": other_flow,
        }
    return out


def latch(active: bool, prev: Optional[Mapping[str, Any]],
          now: float, cooldown_s: float = COOLDOWN_S
          ) -> Tuple[bool, Dict[str, Any]]:
    """Rising-edge latch with a cooldown. `(fire, new_state)`.

    Fires when `active` goes False→True, provided the cooldown since the last fire
    has elapsed. Re-arms whenever `active` is False. This is what stops the standing
    condition from re-alerting every cycle — the exact failure the pivot alerts had.
    """
    st = dict(prev or {})
    was = bool(st.get("active"))
    last = _f(st.get("last_fire")) or 0.0
    fire = False
    if active and not was and (now - last) >= cooldown_s:
        fire = True
        st["last_fire"] = now
    st["active"] = bool(active)
    return fire, st


def message(event: str, info: Mapping[str, Any],
            call_label: str = "ATM Call", put_label: str = "ATM Put") -> str:
    """The alert text for one fired event. HTML, for Telegram."""
    spec = EVENTS.get(event) or {}
    heavier = spec.get("heavier")
    level_kind = spec.get("level")
    sp = _f(info.get("spot"))
    lv = _f(info.get("level"))
    hv = _f(info.get("heavier_flow"))
    ov = _f(info.get("other_flow"))
    heavy_label = put_label if heavier == "put" else call_label
    icon = "🧱" if level_kind == "resistance" else "🛡"
    ball = "🔴" if heavier == "put" else "🟢"
    sp_s = "—" if sp is None else f"₹{sp:,.0f}"
    lv_s = "—" if lv is None else f"₹{lv:,.0f}"
    ratio = ""
    if hv is not None and ov not in (None, 0):
        ratio = f" ({hv / ov:.2f}× the other side)"
    return (
        f"{ball} {icon} <b>{heavy_label} flow heavier at {level_kind}</b>\n"
        f"Spot {sp_s} is at {level_kind} {lv_s}, and {heavy_label} buy+sell "
        f"activity is outweighing the other side{ratio}."
    )
