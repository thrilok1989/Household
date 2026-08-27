"""🎯 The trade-watch banner — WAIT (hold) or EXIT (bail), big and unmissable,
for a trade you have already declared or that Dhan shows filled.

Deliberately not a quiet card like the rest of the cockpit: the whole point is
that this is the ONE panel meant to override a trader's own panic in the
moment. WAIT reads calm and green; EXIT reads loud, red, and short — every
word in it should be readable at a glance, not parsed.

⚠️ Formats a decision, makes none. `mios_v5.trade_watch.assess` decided
WAIT/EXIT already; this only lays out `entry_spot`/`spot`/`side`/the signal
dict it was handed.

Pure: data in, HTML out. No streamlit, no session, no trade_watch import
(the caller runs `assess` and hands this the result).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .nifty_cockpit import _esc
from .theme import BEAR, BULL, CARD_BG, MICRO, MUTED

_BASE = (
    "border-radius:10px;padding:14px 18px;margin:6px 0 10px 0;"
    "border:2px solid {border};background:{bg};"
)


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def banner_html(side: Any, entry_spot: Any, spot: Any,
                info: Mapping[str, Any], source: str = "manual") -> str:
    """The banner for the currently-open trade. `""` when there is nothing
    open (`info["signal"]` is `"NONE"` or missing) — no empty shell shown
    when no trade is being watched.
    """
    signal = str((info or {}).get("signal") or "NONE")
    if signal not in ("WAIT", "EXIT") or side not in ("CALL", "PUT"):
        return ""
    e, sp = _f(entry_spot), _f(spot)
    gain = None
    if e is not None and sp is not None:
        gain = (sp - e) if side == "CALL" else (e - sp)
    e_s = "—" if e is None else f"₹{e:,.1f}"
    sp_s = "—" if sp is None else f"₹{sp:,.1f}"
    if gain is None:
        g_s, g_tone = "—", MUTED
    else:
        g_s, g_tone = f"{gain:+.1f} pts", (BULL if gain >= 0 else BEAR)
    tag = " · from Dhan" if source == "dhan" else " · manual"

    if signal == "EXIT":
        headline, sub, tone = (
            "🚨 EXIT FAST", "Direction has changed — both the engine's vote "
            "and your protecting level are against you now.", BEAR)
    else:
        headline, sub, tone = (
            "⏳ WAIT — hold your position",
            "Still yours to win. The market hasn't turned all the way "
            "against you yet.", BULL)

    return (
        f"<div style='{_BASE.format(border=tone, bg=CARD_BG)}'>"
        f"<div style='font-size:20px;font-weight:800;color:{tone}'>"
        f"{headline}</div>"
        f"<div style='font-size:12px;color:{MUTED};margin-top:2px'>{sub}</div>"
        f"<div style='display:flex;gap:18px;margin-top:8px;flex-wrap:wrap'>"
        f"<div><div style='font-size:9px;color:{MICRO}'>SIDE</div>"
        f"<div style='font-size:13px;font-weight:700'>"
        f"{_esc(side)}{_esc(tag)}</div></div>"
        f"<div><div style='font-size:9px;color:{MICRO}'>ENTRY</div>"
        f"<div style='font-size:13px'>{e_s}</div></div>"
        f"<div><div style='font-size:9px;color:{MICRO}'>NOW</div>"
        f"<div style='font-size:13px'>{sp_s}</div></div>"
        f"<div><div style='font-size:9px;color:{MICRO}'>GAIN</div>"
        f"<div style='font-size:13px;font-weight:700;color:{g_tone}'>"
        f"{g_s}</div></div>"
        f"</div></div>"
    )
