"""🧭 The Market Alignment Checklist, as one table.

Four sections, one row per check: what the level or value is, what SPOT is doing
at it, which way that points, and a remark. Then a summary that counts the
agreement, names the families, and says out loud where they conflict.

⚠️ Formats a decision, makes none. `mios_v5.alignment` assembled the rows from
values other engines published; this lays them out.

Pure: rows in, HTML out. No streamlit, no session, no app import.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from .. import alignment as A
from .nifty_cockpit import _esc
from .theme import BEAR, BULL, CARD_BG, MICRO, MUTED

WARN = "#ffb000"
_TONE = {A.BULL: BULL, A.BEAR: BEAR, A.NEUTRAL: WARN, A.NA: MUTED}
_WORD = {A.BULL: "Bull", A.BEAR: "Bear", A.NEUTRAL: "Neutral",
         A.NA: "not available"}

_CARD = ("border-radius:10px;padding:12px 14px;margin:6px 0 10px 0;"
         f"border:1px solid #1e2836;background:{CARD_BG}")


def _hdr(text: str) -> str:
    return (f"<tr><td colspan='5' style='padding:10px 6px 4px;font-size:10px;"
            f"letter-spacing:.14em;color:{MICRO};text-transform:uppercase;"
            f"border-bottom:1px solid #1e2836'>{_esc(text)}</td></tr>")


def _row(r: Mapping[str, Any]) -> str:
    # ⚠️ A reference row (the spot price) shows a plain dash. It votes for
    # nothing, so giving it a ball would read as a verdict it never cast.
    if r.get("reference"):
        align, tone, word, ball = None, MUTED, "—", ""
    else:
        align = r.get("align") or A.NA
        tone = _TONE.get(align, MUTED)
        word, ball = _WORD.get(align, ""), r.get("ball", "❓")
    return (
        "<tr>"
        f"<td style='padding:4px 6px;font-size:12px;color:#cfd9e6'>"
        f"{_esc(r.get('check'))}</td>"
        f"<td style='padding:4px 6px;font-size:12px;font-weight:600;"
        f"color:#e6edf3'>{_esc(r.get('value'))}</td>"
        f"<td style='padding:4px 6px;font-size:12px'>"
        f"{_esc(r.get('position'))}</td>"
        f"<td style='padding:4px 6px;font-size:12px;font-weight:700;"
        f"color:{tone};white-space:nowrap'>{ball} {_esc(word)}</td>"
        f"<td style='padding:4px 6px;font-size:11px;color:{MUTED}'>"
        f"{_esc(r.get('remark'))}</td>"
        "</tr>"
    )


def _summary(rows: Sequence[Mapping[str, Any]],
             s: Mapping[str, Any]) -> str:
    c = s.get("counts") or {}
    net = s.get("net") or A.NEUTRAL
    tone = _TONE.get(net, WARN)
    fam = s.get("families") or {}
    # Families in the module's declared order, so the summary does not reshuffle
    # itself as dict insertion order changes between cycles.
    fam_html = "".join(
        f"<span style='font-size:12px;margin-right:14px'>"
        f"<span style='color:{MICRO}'>{_esc(f)}</span> "
        f"<b style='color:{_TONE.get(fam[f], MUTED)}'>"
        f"{A._bb.ball(fam[f])} {_esc(_WORD.get(fam[f], ''))}</b></span>"
        for f in A.FAMILIES if f in fam)

    reasons = A.why(rows, net)
    why_html = ""
    if reasons:
        why_html = (f"<div style='font-size:11px;color:{MUTED};margin-top:6px'>"
                    f"<b style='color:{MICRO}'>WHY:</b> "
                    + _esc(" · ".join(reasons)) + "</div>")
    # ⚠️ The conflict is printed, not buried. A verdict that hides the family
    # pulling the other way is the overconfident read this table replaces.
    conf = s.get("conflicts") or []
    conf_html = ""
    if conf:
        conf_html = (
            f"<div style='font-size:11px;color:{WARN};margin-top:4px'>"
            f"⚠️ <b>CONFLICT:</b> {_esc(', '.join(conf))} "
            f"{'is' if len(conf) == 1 else 'are'} pulling the other way — "
            f"treat continuation as unconfirmed.</div>")

    active, agree = s.get("active", 0), s.get("agree", 0)
    na = c.get(A.NA, 0)
    na_html = ("" if not na else
               f"<span style='color:{MUTED}'>· ❓ {na} not available</span>")
    return (
        f"<div style='margin-top:10px;padding-top:8px;"
        f"border-top:1px solid #1e2836'>"
        f"<div style='font-size:15px;font-weight:800;color:{tone}'>"
        f"⚖️ NET ALIGNMENT: {A._bb.ball(net)} "
        f"{_esc(_WORD.get(net, '').upper())}</div>"
        f"<div style='font-size:12px;color:{MUTED};margin:3px 0 6px'>"
        f"🟢 {c.get(A.BULL, 0)} bull · 🔴 {c.get(A.BEAR, 0)} bear · "
        f"🟡 {c.get(A.NEUTRAL, 0)} neutral {na_html} — "
        f"agreement {agree} / {active} readable checks</div>"
        f"<div>{fam_html}</div>{why_html}{conf_html}</div>"
    )


def checklist_html(rows: Optional[Sequence[Mapping[str, Any]]],
                   spot: Any = None) -> str:
    """The whole card. `""` when there are no rows at all, so an empty card is
    never drawn — but a row that could not be READ still appears, marked ❓."""
    rows = [r for r in (rows or ()) if isinstance(r, Mapping)]
    if not rows:
        return ""
    s = A.summarise(rows)
    sp = ""
    try:
        if spot is not None:
            sp = (f"<span style='font-size:13px;color:{MUTED};"
                  f"margin-left:8px'>spot ₹{float(spot):,.1f}</span>")
    except (TypeError, ValueError):
        sp = ""

    body = []
    for g in A.GROUPS:
        in_group = [r for r in rows if r.get("group") == g]
        if not in_group:
            continue
        body.append(_hdr(g))
        body.extend(_row(r) for r in in_group)
    # Any row whose group is not one of the four still appears, rather than
    # being silently dropped by the layout.
    stray = [r for r in rows if r.get("group") not in A.GROUPS]
    if stray:
        body.append(_hdr("OTHER"))
        body.extend(_row(r) for r in stray)

    return (
        f"<div style='{_CARD}'>"
        f"<div style='font-size:14px;font-weight:800;color:#e6edf3'>"
        f"🧭 MIOS MARKET ALIGNMENT CHECKLIST{sp}</div>"
        f"<div style='overflow-x:auto'>"
        f"<table style='width:100%;border-collapse:collapse;margin-top:6px'>"
        f"<tr><th style='text-align:left;font-size:9px;color:{MICRO};"
        f"padding:0 6px'>CHECK</th>"
        f"<th style='text-align:left;font-size:9px;color:{MICRO};"
        f"padding:0 6px'>VALUE / LEVEL</th>"
        f"<th style='text-align:left;font-size:9px;color:{MICRO};"
        f"padding:0 6px'>SPOT BEHAVIOUR</th>"
        f"<th style='text-align:left;font-size:9px;color:{MICRO};"
        f"padding:0 6px'>ALIGNMENT</th>"
        f"<th style='text-align:left;font-size:9px;color:{MICRO};"
        f"padding:0 6px'>REMARKS</th></tr>"
        + "".join(body) +
        f"</table></div>{_summary(rows, s)}</div>"
    )
