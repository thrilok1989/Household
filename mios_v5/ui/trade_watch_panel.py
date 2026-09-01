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


#: Amber — the "nobody looked" tone. Deliberately NOT green: an unevaluated
#: trade must not share a colour with one that was checked and found healthy.
WARN = "#ffb000"


def _condition(label: str, detail: str, against: Any) -> str:
    """One of the two EXIT conditions, as a chip: what it is, its number, and
    whether it was even evaluated.

    ⚠️ Three states, one per value of `against`:

        None   not evaluated — amber, and it says so in words
        False  checked, and it is on your side
        True   checked, and it has turned against you

    This chip is the whole point of the panel change. WAIT was being shown as a
    green all-clear whether both conditions had been measured or neither had,
    and nothing on screen distinguished the two. Now the reader can see which
    of the two actually held the verdict up.
    """
    if against is None:
        tone, mark, word = WARN, "—", "not evaluated"
    elif against:
        tone, mark, word = BEAR, "✗", "against you"
    else:
        tone, mark, word = BULL, "✓", "with you"
    return (
        f"<span style='font-size:11px;color:{MUTED}'>{_esc(label)} "
        f"<b style='color:{tone}'>{_esc(detail)}</b> "
        f"<span style='color:{tone}'>{mark} {_esc(word)}</span></span>"
    )


def _conditions_row(info: Mapping[str, Any]) -> str:
    """Both conditions, side by side, under the numbers."""
    net = _f(info.get("net"))
    pr = _f(info.get("protect"))
    eng = _condition("engine", "—" if net is None else f"{net:+.1f}",
                     info.get("engine_against"))
    lvl = _condition("level", "—" if pr is None else f"₹{pr:,.0f}",
                     info.get("zone_against"))
    return (f"<div style='display:flex;gap:16px;margin-top:8px;"
            f"flex-wrap:wrap'>{eng}{lvl}</div>")


def banner_html(side: Any, entry_spot: Any, spot: Any,
                info: Mapping[str, Any], source: str = "manual") -> str:
    """The banner for the currently-open trade. `""` when there is nothing
    open (`info["signal"]` is `"NONE"` or missing) — no empty shell shown
    when no trade is being watched.

    Three live states now, not two. `UNKNOWN` — a trade is open but neither
    EXIT condition could be evaluated — gets its own amber banner saying so,
    because the green WAIT card it used to render was an all-clear nobody had
    earned.
    """
    signal = str((info or {}).get("signal") or "NONE")
    if signal not in ("WAIT", "EXIT", "UNKNOWN") or side not in ("CALL", "PUT"):
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
    # ⚠️ NOT "ENTRY" and "GAIN" on the Dhan path. `entry_spot` there is the
    # NIFTY spot at the moment the app first SAW the position — the positions
    # endpoint is polled, and nothing reads the fill price — and it is an index
    # level, not the option premium. Labelling that "ENTRY / GAIN +1.8 pts"
    # reads as profit on the trade, which it is not: it is how far the index has
    # travelled since detection. The manual path DOES capture the spot at the
    # click, so "ENTRY" is fair there.
    if source == "dhan":
        entry_label, gain_label = "SPOT WHEN SEEN", "SPOT SINCE"
    else:
        entry_label, gain_label = "ENTRY", "SPOT SINCE ENTRY"

    if signal == "EXIT":
        headline, sub, tone = (
            "🚨 EXIT FAST", "Direction has changed — both the engine's vote "
            "and your protecting level are against you now.", BEAR)
    elif signal == "UNKNOWN":
        # ⚠️ Amber, and the words say NOT an all-clear. This state used to
        # render as the green WAIT card: neither condition was measurable, both
        # failed closed to False, and the banner told the trader the market
        # hadn't turned against them — on no evidence whatsoever.
        headline, sub, tone = (
            "⚪ NOT EVALUATED",
            "Neither the engine vote nor a protecting level is available. "
            "This is NOT an all-clear — nothing has been checked.", WARN)
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
        f"<div><div style='font-size:9px;color:{MICRO}'>{entry_label}</div>"
        f"<div style='font-size:13px'>{e_s}</div></div>"
        f"<div><div style='font-size:9px;color:{MICRO}'>NOW</div>"
        f"<div style='font-size:13px'>{sp_s}</div></div>"
        f"<div><div style='font-size:9px;color:{MICRO}'>{gain_label}</div>"
        f"<div style='font-size:13px;font-weight:700;color:{g_tone}'>"
        f"{g_s}</div></div>"
        f"</div>"
        # ⚠️ The two EXIT conditions, ALWAYS shown — on WAIT, on EXIT and on
        # UNKNOWN alike. A verdict whose basis is invisible is one the reader
        # has to take on trust, and the reason this panel needed changing is
        # that "checked and fine" looked identical to "checked nothing".
        + _conditions_row(info or {})
        + f"</div>"
    )
