"""Alerts for structure forming on a chart — a new high-volume pivot, or a new
Volume Order Block.

Pure by design: signatures and wording only. `vob_minimal` owns the per-chart
memory (what has already been seen) and the send, the same split every other
alert in this file follows.

Both are "formed once, then it exists" events, so the alert must fire on the
FIRST appearance of a thing and never again for the same thing. Deciding what is
new is a question about history, which the app holds — so this module only turns
one pivot or one zone into a stable signature (for the app to diff against its
memory) and into a message. It never decides on its own that something is new,
and it seeds nothing.

The high-volume pivot fields come from `volume_points.high_volume_pivots`
(`side`/`price`/`confirmed_at`/`norm`); the VOB fields from
`vob_minimal.analyze_vob_volume` (`role`/`lower`/`upper`/`status`). Neither is
recomputed here — one owner each (ARCHITECTURE_PRINCIPLES §1).
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence, Set, Tuple

#: The charts a formation can appear on. VOB is drawn on the option legs only —
#: the NIFTY terminal panel carries the profile/POC, not order blocks — so the
#: app asks for VOB on CALL/PUT and for pivots on all three.
CHARTS = ("NIFTY", "CALL", "PUT")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def diff(signatures: Sequence[Any],
         known: Optional[Set[Any]]) -> Tuple[List[Any], Set[Any]]:
    """The seed-or-diff rule, made pure so it can be tested without the app.

    `known` is the set of signatures already seen for one (chart, kind), or
    `None` the very first time it is observed. Returns `(to_alert, updated)`:

    * First observation (`known is None`) → **seed**: `to_alert` is empty and
      `updated` is the current set. The structure that already existed when the
      app loaded is remembered, never announced — this is what stops the alert
      re-emitting the session's history on every refresh.
    * Afterwards → the signatures not in `known`, in input order, and `updated`
      is `known` plus everything seen now.

    Order is preserved and duplicates within one batch collapse, so a pivot that
    appears twice in one list is alerted once.
    """
    cur = list(dict.fromkeys(signatures))       # de-dup, keep order
    if known is None:
        return [], set(cur)
    to_alert = [s for s in cur if s not in known]
    return to_alert, known | set(cur)


# ── high-volume pivots ─────────────────────────────────────────────────

def hvp_signature(pivot: Mapping[str, Any],
                  decimals: int = 0) -> Optional[Tuple[Any, ...]]:
    """A stable id for one high-volume pivot: side, price, and the bar it was
    confirmed on. `None` when it cannot be identified — skip it rather than
    alert a blank. `confirmed_at` is included so two pivots at the same price on
    different bars are two events, not one.
    """
    side = str(pivot.get("side") or "").upper()
    price = _f(pivot.get("price"))
    if not side or price is None:
        return None
    # ⚠️ `at` (the pivot bar's TIMESTAMP) in preference to `confirmed_at` (its
    # POSITION in the frame). A position is not an identity in a rolling
    # window: every new 1-minute bar shifts every index by one, so the same
    # physical pivot produced a new signature each cycle and was announced
    # again and again — the alert flood the desk reported, where the same price
    # at the same volume ratio repeats. A timestamp does not move when the
    # window slides. `confirmed_at` remains the fallback for a caller that
    # cannot supply timestamps, which is still better than no identity at all.
    stamp = pivot.get("at")
    if stamp is None:
        stamp = pivot.get("confirmed_at")
    return (side, round(price, decimals), stamp)


def hvp_message(chart: str, label: Optional[str], pivot: Mapping[str, Any],
                decimals: int = 0) -> str:
    """One new pivot → the Telegram/alert text."""
    label = label or chart
    side = str(pivot.get("side") or "").upper()
    price = _f(pivot.get("price"))
    norm = _f(pivot.get("norm"))
    # a swing HIGH is overhead (resistance-side), a swing LOW underneath
    kind = "high" if side == "HIGH" else "low"
    icon = "🔺" if side == "HIGH" else "🔻"
    vol = f" on {norm:.1f}× volume" if norm is not None else ""
    price_s = "—" if price is None else f"₹{price:,.{decimals}f}"
    from . import bias_ball as _bb

    # ⚠️ MEASURED beats ASSUMED. `bias_ball.hvp_bias` reads the pivot's SHAPE —
    # a swing high is overhead, therefore resistance, therefore (leg-inverted) a
    # direction. That is a structural assumption, and the desk challenged it
    # correctly: a swing high can print on heavy BUYING and a swing low on heavy
    # SELLING. The shape of the bar says nothing about who was behind the volume.
    #
    # So when `_annotate_hv_pivots` has attributed the pivot's own formation
    # window (CLV-weighted, via `indicators.order_flow.split`), that measurement
    # decides the ball and is stated in the text. The structural read stays only
    # as the fallback for a pivot that could not be measured — better than
    # silence, but never preferred over the real split.
    buy_pct = _f(pivot.get("buy_pct"))
    dominant = str(pivot.get("dominant") or "").lower()
    if buy_pct is not None and dominant:
        sell_pct = 100.0 - buy_pct
        bias = (_bb.BULL if dominant == "buyers" else
                _bb.BEAR if dominant == "sellers" else _bb.NEUTRAL)
        if chart and str(chart).strip().upper() == "PUT" and bias != _bb.NEUTRAL:
            # a PUT's own buyers are NIFTY-bearish — the one inversion rule,
            # already owned by `bias_ball`; applied here to the MEASURED side
            bias = _bb.BEAR if bias == _bb.BULL else _bb.BULL
        flow = (f"{buy_pct:.0f}% buy / {sell_pct:.0f}% sell"
                if dominant == "balanced"
                else f"{'BUY' if dominant == 'buyers' else 'SELL'}-dominated "
                     f"({buy_pct:.0f}% buy / {sell_pct:.0f}% sell)")
        return _bb.prefix(
            bias,
            f"{icon} <b>New high-volume {kind} — {label}</b>\n"
            f"A high-volume swing {kind} formed at {price_s}{vol}.\n"
            f"Flow into it was {flow}.")

    return _bb.prefix(
        _bb.hvp_bias(chart, side),
        f"{icon} <b>New high-volume {kind} — {label}</b>\n"
        f"A high-volume swing {kind} formed at {price_s}{vol} — "
        f"a fresh level to watch (flow not measured).")


# ── volume order blocks ────────────────────────────────────────────────

def vob_signature(zone: Mapping[str, Any]) -> Optional[Tuple[Any, ...]]:
    """A stable id for one VOB: its role and its band. `None` when the band
    cannot be read. Status is deliberately NOT in the signature — a zone that
    goes INTACT → BUILDING is the same block, not a new one."""
    role = str(zone.get("role") or zone.get("zone_type") or "").lower()
    lo = _f(zone.get("lower"))
    hi = _f(zone.get("upper"))
    if not role or lo is None or hi is None:
        return None
    return (role, round(lo, 2), round(hi, 2))


def vob_message(chart: str, label: Optional[str], zone: Mapping[str, Any],
                decimals: int = 2) -> str:
    """One new VOB → the Telegram/alert text."""
    label = label or chart
    role = str(zone.get("role") or zone.get("zone_type") or "").lower()
    # bullish block = support, bearish = resistance
    if role in ("support", "bullish"):
        icon, word = "🛡", "support"
    elif role in ("resistance", "bearish"):
        icon, word = "🧱", "resistance"
    else:
        icon, word = "🧊", role or "zone"
    lo = _f(zone.get("lower"))
    hi = _f(zone.get("upper"))
    status = str(zone.get("status") or "").upper()
    band = ("—" if lo is None or hi is None
            else f"₹{lo:,.{decimals}f}–₹{hi:,.{decimals}f}")
    tail = f" ({status})" if status else ""
    from . import bias_ball as _bb
    return _bb.prefix(
        _bb.vob_bias(chart, role),
        f"{icon} <b>New VOB {word} — {label}</b>\n"
        f"A volume order block formed at {band}{tail}.")
