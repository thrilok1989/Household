"""MIOS V6 — the expiry charm-pin strip (Trade Card + Guardian panel)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def charm_pin_html(read: Optional[Dict[str, Any]]) -> str:
    """One violet strip. Empty string unless the pin is actually exerting force
    — a permanently-present "no pin" row would train the eye to ignore it."""
    r = read or {}
    if not r.get("active"):
        return ""
    lbl = f" · {r['pin_label']}" if r.get("pin_label") else ""
    return (
        f"<div style='margin:6px 0;padding:8px 12px;background:#241a2e;"
        f"border-left:3px solid #a78bfa;border-radius:6px;font-size:13.5px;"
        f"color:#c9b6ec;text-align:left;'>"
        f"🧲 <b style='color:#d9c9f5;'>Expiry charm-pin</b> — dealer hedging "
        f"drags price toward the magnet "
        f"<b style='color:#e6dbff;'>₹{r['pin']:,.0f}</b> ({r['drift']}{lbl})"
        + (f" · net charm {r['net_charm']:+.1f}L/day"
           if r.get("net_charm") is not None else "")
        + f". Breakouts likely to <b>fade</b>; small dips are noise near the "
          f"pin."
        f"<span style='color:#8a7bb0;'> Context only — does NOT change the "
        f"Guardian verdict.</span></div>")
