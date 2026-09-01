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
                decimals: int = 0, level_line: bool = True,
                flow_line: bool = True) -> str:
    """One new pivot → the Telegram/alert text.

    The body is two independent sentences and either can be switched off:

      `level_line`  "A high-volume swing high formed at ₹144.30 on 6.9×
                    volume — a fresh level to watch." The original wording,
                    and what the alert is announcing.
      `flow_line`   "Flow looks BUY-led — est. 83% buy / 17% sell (CLV from
                    1m bars, not tick data)." What the volume that built it
                    looked like.

    ⚠️ Turning `flow_line` off hides the SENTENCE, not the measurement: the
    bias ball still follows the measured split rather than reverting to the
    structural guess. A swing high on heavy buying is bullish whether or not
    the reader wants the percentages printed, and flipping the ball with the
    text would make the toggle change the alert's meaning instead of its
    verbosity.

    With both off the headline still goes out — it names the event and the leg,
    which is a legitimate minimal alert. Silencing the alert itself is
    `_formation_alerts_on`'s job, not this function's.
    """
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

    # ⚠️ ESTIMATED beats ASSUMED — but it is an ESTIMATE, and the text must say so.
    #
    # `bias_ball.hvp_bias` reads the pivot's SHAPE — a swing high is overhead,
    # therefore resistance, therefore (leg-inverted) a direction. That is a
    # structural assumption, and the desk challenged it correctly: a swing high
    # can print on heavy BUYING and a swing low on heavy SELLING.
    #
    # The replacement is `indicators.order_flow.split`, which is CLV:
    # `buy_fraction = (close − low) / (high − low)`. That is an INFERENCE FROM
    # WHERE THE BAR CLOSED IN ITS RANGE, not a count of buy versus sell trades.
    # Exact classification needs tick data with bid/ask so each trade can be
    # tagged as hitting the ask or the bid; Dhan's intraday endpoint returns
    # 1-minute OHLCV, so it is not available. CLV is a good proxy and a poor
    # certainty: a bar distributed into all the way up — real selling into
    # strength — still closes near its high and CLV calls it buying.
    #
    # So the wording hedges deliberately ("looks", "est.") and names the basis.
    # Every other surface in this app already labels the same number "CLV-
    # weighted estimate from 1m OHLCV (not tick data)"; an alert that dropped
    # the qualifier and printed a bare "83% buy" would be claiming a precision
    # the method does not have.
    buy_pct = _f(pivot.get("buy_pct"))
    dominant = str(pivot.get("dominant") or "").lower()
    if buy_pct is not None and dominant:
        sell_pct = 100.0 - buy_pct
        bias = (_bb.BULL if dominant == "buyers" else
                _bb.BEAR if dominant == "sellers" else _bb.NEUTRAL)
        if chart and str(chart).strip().upper() == "PUT" and bias != _bb.NEUTRAL:
            # a PUT's own buyers are NIFTY-bearish — the one inversion rule,
            # already owned by `bias_ball`; applied to the ESTIMATED side
            bias = _bb.BEAR if bias == _bb.BULL else _bb.BULL
        lean = ("mixed" if dominant == "balanced"
                else "BUY-led" if dominant == "buyers" else "SELL-led")
        # ⚠️ BOTH lines, at the desk's request. The flow estimate was added as a
        # REPLACEMENT for the "a fresh level to watch" tail, which quietly
        # dropped the only sentence that said what the alert is FOR. The two do
        # different jobs and neither substitutes for the other: the first names
        # the level, the second describes the volume that built it. So the
        # original wording stays, the estimate follows on its own line, and
        # each can be switched off without taking the other with it.
        body = [f"{icon} <b>New high-volume {kind} — {label}</b>"]
        if level_line:
            body.append(f"A high-volume swing {kind} formed at {price_s}{vol} — "
                        f"a fresh level to watch.")
        if flow_line:
            body.append(f"Flow looks {lean} — est. {buy_pct:.0f}% buy / "
                        f"{sell_pct:.0f}% sell (CLV from 1m bars, not tick data).")
        # ⚠️ `bias` — the MEASURED side — regardless of `flow_line`. Hiding the
        # sentence must not change which way the ball points; see the docstring.
        return _bb.prefix(bias, "\n".join(body))

    # No measurable split on this bar. The flow toggle has nothing to hide, so
    # only `level_line` applies — and the "(flow not estimated)" qualifier rides
    # with the level sentence, because that is the sentence it qualifies.
    plain = [f"{icon} <b>New high-volume {kind} — {label}</b>"]
    if level_line:
        plain.append(f"A high-volume swing {kind} formed at {price_s}{vol} — "
                     f"a fresh level to watch (flow not estimated).")
    return _bb.prefix(_bb.hvp_bias(chart, side), "\n".join(plain))


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
