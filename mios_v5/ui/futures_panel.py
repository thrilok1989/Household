"""The futures strip — price, basis, and the day's open interest.

Pure presentation. Stage 71.90 decided every value; this file decides where it
sits and what colour it is.

## Why it exists at all

Principle 12: *nothing may influence a trading decision unless the trader can
inspect that exact value somewhere in the UI.* Futures now cross the bridge
into `TradingContext`, so the moment any stage weighs them the trader must be
able to see what was weighed. Building the panel with the bridge — rather than
after something starts scoring it — is the cheap order to do it in.

## The day's OI, not the last twenty seconds'

The number shown is measured from the day's stored anchor. The app's own
`chg_oi` is the delta since the previous ~20-second refresh and resets to `0.0`
on a restart; showing that would put a figure on screen that reads as *open
interest did not move* whenever the app had been restarted.

## UNKNOWN is drawn as an em dash, never as zero

A futures panel showing `0.0%` when the quote carried no OI field is the one
misreading that matters here, because zero is a plausible answer to the
question being asked.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .theme import ALERT, BULL, BULL_SOFT, FAINT, INK, MICRO, MUTED, WARN

UNKNOWN = "UNKNOWN"

#: Stage 71.90's four states, coloured by what they mean for a holder.
#: `Short Covering` is amber rather than green on purpose — a rally on falling
#: open interest is positions closing, not conviction arriving, and colouring
#: it like a build-up would flatter the weaker of the two.
STATE_TONE = {
    "Long Build-up": BULL,
    "Short Covering": WARN,
    "Short Build-up": ALERT,
    "Long Unwinding": WARN,
    "Flat": MUTED,
    UNKNOWN: FAINT,
}

_DIR_TONE = {"Up": BULL_SOFT, "Down": ALERT, "Unchanged": MUTED}


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _txt(v) -> str:
    s = "" if v is None else str(v).strip()
    return s if s and s != UNKNOWN else "—"


def _get(obj: Any, name: str) -> Any:
    """A field from the frozen reading or from a stored dict — both render
    identically, so a replayed reading looks like a live one."""
    if obj is None:
        return None
    got = getattr(obj, name, None)
    if got is None and isinstance(obj, Mapping):
        got = obj.get(name)
    return got


def _cell(label: str, value: str, tone: str = MUTED) -> str:
    return (f"<div style='min-width:0'>"
            f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase'>{label}</div>"
            f"<div style='font-size:11.5px;font-weight:700;color:{tone}'>"
            f"{value}</div></div>")


def futures_html(reading: Any = None) -> str:
    """The strip, or `""` when Stage 71.90 has published nothing."""
    if reading is None:
        return ""

    state = str(_get(reading, "futures_oi_state") or UNKNOWN)
    oi_pct = _num(_get(reading, "day_oi_pct"))
    price_chg = _num(_get(reading, "day_price_change"))
    basis = _num(_get(reading, "basis"))
    why = str(_get(reading, "why") or "")

    cells = "".join([
        _cell("Contract", _txt(_get(reading, "symbol"))),
        _cell("Price", "—" if _num(_get(reading, "current_price")) is None
              else f"{_num(_get(reading, 'current_price')):,.1f}"),
        # Both directions are shown because the STATE is the pair of them, and
        # a reader who disagrees with the state needs to see which half.
        _cell("Price today", "—" if price_chg is None else f"{price_chg:+,.0f}",
              _DIR_TONE.get(str(_get(reading, "price_direction")), MUTED)),
        _cell("OI today", "—" if oi_pct is None else f"{oi_pct:+.2f}%",
              _DIR_TONE.get(str(_get(reading, "oi_direction")), MUTED)),
        _cell("Basis", "—" if basis is None else f"{basis:+.1f}",
              BULL_SOFT if (basis or 0) > 0 else ALERT if basis else MUTED),
        # Reported, never scored: the anchor is what makes the OI figure mean
        # "today", and a reader checking the number needs to see it.
        _cell("Day open OI", "—" if _num(_get(reading, "open_oi")) is None
              else f"{_num(_get(reading, 'open_oi')):,.0f}", MICRO),
    ])

    return (
        f"<div style='background:#0d1117;border:1px solid #1e2836;"
        f"border-radius:10px;padding:9px 12px;margin-bottom:8px'>"
        f"<div style='display:flex;gap:8px;align-items:baseline;flex-wrap:wrap'>"
        f"<span style='font-size:10.5px;letter-spacing:.10em;color:{INK};"
        f"text-transform:uppercase'>⚙️ Futures</span>"
        f"<span style='color:{STATE_TONE.get(state, FAINT)};font-weight:800;"
        f"font-size:13px'>{_txt(state)}</span>"
        f"<span style='color:{MICRO};font-size:9px;margin-left:auto'>"
        f"Stage 71.90 · day-anchored · advisory</span></div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:12px;margin-top:5px;"
        f"padding-top:4px;border-top:1px solid #1a2330'>{cells}</div>"
        + (f"<div style='font-size:10px;color:{MICRO};margin-top:3px'>{why}"
           f"</div>" if why else "")
        + "</div>")


def render_futures(st, reading: Any = None) -> None:
    """Draw it, or say nothing. Advisory — it may never take the screen down."""
    try:
        html = futures_html(reading)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Futures unavailable: {err}")
