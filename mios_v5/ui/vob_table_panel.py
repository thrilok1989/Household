"""📦 The VOB (Volume Order Block) zone tabulation — buy% / sell% WITHIN each
zone's own price window, directly under the terminal chart.

## Why this exists

`analyze_vob_volume` already computes, per zone, the exact number that was asked
for: not the zone's share of total volume across all blocks (that lives on the
zone dict too, as `total_vol`, but it is not the ask), but the buy-vs-sell SPLIT
INSIDE that zone's own price window — `buy_vol`, `sell_vol`, `bull_pct`,
`dominant`. It has been computed every cycle and drawn only as a coloured
rectangle on the CALL/PUT chart panels (`_leg_overlay`, `ZONE_TONE`) — the status
colour survives, the percentage that produced it never reaches the screen.

⚠️ **Nothing is recomputed here.** Every value in a row is read off the zone dict
`analyze_vob_volume` already built; this module only lays them out.

Same status glyphs as `build_leg_bias_table._stat_em` (🚀 BUILD · 🌫️ FADE ·
⚠️ BREAK · • INTACT) and the same tone rule as `leg_table_panel._tone_of_cell`,
so a zone described in the leg tabulation and here reads identically both places.

Pure module — rows in, HTML out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .nifty_cockpit import _card, _esc
from .theme import BEAR, BULL, MICRO, MUTED, WARN

#: zone_type / role → (icon, word). `analyze_vob_volume` writes both `zone_type`
#: ("bullish"/"bearish") and `role` ("support"/"resistance"); either is accepted.
ZONE_LABEL = {
    "bullish": ("🛡", "Support"), "support": ("🛡", "Support"),
    "bearish": ("🧱", "Resistance"), "resistance": ("🧱", "Resistance"),
}

#: Same mapping `build_leg_bias_table._stat_em` uses, so a zone's status reads
#: identically in the leg tabulation's Sup/Res VOB columns and here.
STATUS_GLYPH = {
    "BUILDING": "🚀 BUILD", "FADING": "🌫️ FADE",
    "BREAKING": "⚠️ BREAK", "INTACT": "• INTACT",
}

#: `leg_table_panel._tone_of_cell`'s rule, restated: colour a status word from
#: the glyph the app already puts in front of it.
STATUS_TONE = {
    "BUILDING": BULL, "BREAKING": BEAR, "FADING": WARN, "INTACT": MUTED,
}

#: buyers → bullish for the OPTION (not necessarily for NIFTY — a PE leg's
#: buyers are NIFTY-bearish; this table stays in the leg's own terms, matching
#: `classify_leg_sr_behavior`'s "from the leg's own perspective" convention).
DOMINANT_TONE = {"buyers": BULL, "sellers": BEAR, "balanced": MUTED}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _vol(v: Any) -> str:
    """Compact volume: plain below 1L, `#.#L` at and above — the same break
    point `options_cockpit` uses for option-leg volume."""
    f = _f(v)
    if f is None:
        return "—"
    return f"{f / 1e5:.1f}L" if abs(f) >= 1e5 else f"{f:,.0f}"


def rows_for(call_zones: Optional[Sequence[Mapping[str, Any]]] = None,
            put_zones: Optional[Sequence[Mapping[str, Any]]] = None,
            call_label: str = "CALL", put_label: str = "PUT"
            ) -> List[Dict[str, Any]]:
    """One row per zone, CALL's zones first then PUT's — the same leg order the
    terminal chart draws left-to-right. Zones with no readable range are
    skipped; `analyze_vob_volume` already guarantees `lower < upper`, so this
    only guards a malformed caller.
    """
    out: List[Dict[str, Any]] = []
    for label, zones in ((call_label, call_zones), (put_label, put_zones)):
        for z in (zones or ()):
            if not isinstance(z, Mapping):
                continue
            lo, hi = _f(z.get("lower")), _f(z.get("upper"))
            if lo is None or hi is None or hi <= lo:
                continue
            kind = str(z.get("role") or z.get("zone_type") or "").lower()
            icon, word = ZONE_LABEL.get(kind, ("⬜", kind.title() or "—"))
            status = str(z.get("status") or "").upper()
            bull_pct = _f(z.get("bull_pct"))
            out.append({
                "leg": label,
                "kind": kind, "icon": icon, "word": word,
                "lower": lo, "upper": hi,
                "status": status,
                "buy_pct": bull_pct,
                "sell_pct": (100.0 - bull_pct) if bull_pct is not None else None,
                "dominant": str(z.get("dominant") or "").lower(),
                "buy_vol": _f(z.get("buy_vol")),
                "sell_vol": _f(z.get("sell_vol")),
                "total_vol": _f(z.get("total_vol")),
                "n_bars": z.get("n_bars_in_zone"),
            })
    return out


def _split_bar(buy_pct: Optional[float]) -> str:
    """A two-colour bar: BULL width = buy%, BEAR width = sell%. `""` when the
    split was never computed — a bar at 50/50 would claim a balanced read that
    is not what "no data" means."""
    if buy_pct is None:
        return ""
    b = max(0.0, min(100.0, buy_pct))
    return (f"<div style='display:flex;width:56px;height:7px;"
            f"border-radius:2px;overflow:hidden'>"
            f"<span style='flex:0 0 {b:.0f}%;background:{BULL}'></span>"
            f"<span style='flex:0 0 {100 - b:.0f}%;background:{BEAR}'></span>"
            f"</div>")


def table_html(rows: Optional[Sequence[Mapping[str, Any]]]) -> str:
    """The full table. `""` when there are no zones — no empty table shell."""
    if not rows or isinstance(rows, (str, bytes)):
        return ""
    body: List[str] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        # ⚠️ `rows_for` guarantees a readable range on every row it emits, but
        # this is a public function — a caller that skips `rows_for` (or a row
        # a future edit forgets to set `lower`/`upper` on) must get a dropped
        # row, not a `KeyError` that takes the whole table down.
        lo, hi = _f(r.get("lower")), _f(r.get("upper"))
        if lo is None or hi is None:
            continue
        status = str(r.get("status") or "")
        glyph = STATUS_GLYPH.get(status, "—")
        s_tone = STATUS_TONE.get(status, MUTED)
        dom = str(r.get("dominant") or "")
        d_tone = DOMINANT_TONE.get(dom, MUTED)
        buy_pct, sell_pct = r.get("buy_pct"), r.get("sell_pct")
        pct_txt = ("—" if buy_pct is None else
                   f"{buy_pct:.0f}% / {sell_pct:.0f}%")
        body.append(
            "<tr>"
            f"<td style='padding:4px 8px;color:{MUTED};font-size:11px'>"
            f"{_esc(r.get('leg'))}</td>"
            f"<td style='padding:4px 8px;font-size:11px'>"
            f"{r.get('icon', '')} {_esc(r.get('word'))}</td>"
            f"<td style='padding:4px 8px;font-size:11px;white-space:nowrap'>"
            f"₹{lo:,.1f}–₹{hi:,.1f}</td>"
            f"<td style='padding:4px 8px;font-size:11px;color:{s_tone};"
            f"font-weight:700'>{glyph}</td>"
            f"<td style='padding:4px 8px'>{_split_bar(buy_pct)}</td>"
            f"<td style='padding:4px 8px;font-size:11px;white-space:nowrap'>"
            f"{pct_txt}</td>"
            f"<td style='padding:4px 8px;font-size:11px;color:{d_tone};"
            f"text-transform:capitalize'>{_esc(dom) or '—'}</td>"
            f"<td style='padding:4px 8px;font-size:11px;color:{MUTED};"
            f"text-align:right'>{_vol(r.get('total_vol'))}</td>"
            "</tr>")
    if not body:
        return ""
    head = "".join(
        f"<th style='padding:4px 8px;text-align:left;color:{MICRO};"
        f"font-size:9px;letter-spacing:.05em'>{h}</th>"
        for h in ("LEG", "ZONE", "RANGE", "STATUS", "", "BUY / SELL",
                  "DOMINANT", "VOL"))
    table = (f"<table style='width:100%;border-collapse:collapse'>"
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
            f"</table>")
    return _card("📦 VOB zones — buy/sell split within each zone", table)
