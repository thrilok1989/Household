"""🔭 Live Market Confluence — the card, drawn above the Trade Card.

Formats the verdict `mios_v5.live_confluence.assess` already reached.
Nothing here counts a vote, resolves a bias, or decides BULLISH vs BEARISH
vs MIXED — this module only lays the result out.

Three-state discipline, same as every other card in this app: BULLISH and
BEARISH get their own colour and lead with the evidence that produced them;
MIXED gets a third colour and shows BOTH sides rather than forcing one.
PINNED is a fourth, distinct look — a magnet strike is not "no evidence for
either side", it is "not a question this vote can answer" — matching
`entry_gate`'s own PINNED state.

Pure: the assess() result (plus a few display-only extras — spot/LTP prices,
leg labels) in, HTML out.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .. import bias_ball as _BB
from .nifty_cockpit import _card, _esc
from .theme import BEAR, BULL, CARD_BG, MICRO, MUTED, WARN

#: `theme.BULL`/`theme.BEAR` above are COLOURS ("#00ff88"/"#ff4444"), used for
#: styling only. A vote's own `bias` field is `bias_ball.BULL`/`.BEAR` — the
#: STRINGS "bull"/"bear" `mios_v5.live_confluence` writes — and must be
#: compared against THESE, never the colour constants of the same name.
_VOTE_BULL, _VOTE_BEAR = _BB.BULL, _BB.BEAR

_PIN = "#c026d3"

_TONE = {"BULLISH": (BULL, "🟢"), "BEARISH": (BEAR, "🔴"),
        "MIXED": (WARN, "🟡"), "PINNED": (_PIN, "🧲")}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _px(v: Any) -> str:
    f = _f(v)
    return "—" if f is None else f"₹{f:,.1f}"


def _participation_bar(diff: Any) -> str:
    """A two-colour bar from `price_action`'s own CALL-vs-PUT diff ratio
    (−1..1) — a display mapping of an already-computed number, not a new
    one. Left = CALL's share, right = PUT's. `""` when unreadable."""
    d = _f(diff)
    if d is None:
        return ""
    call_pct = max(0.0, min(100.0, 50.0 + d * 50.0))
    return (f"<div style='display:flex;width:100%;height:8px;border-radius:3px;"
            f"overflow:hidden;margin-top:3px'>"
            f"<span style='flex:0 0 {call_pct:.0f}%;background:{BULL}'></span>"
            f"<span style='flex:0 0 {100 - call_pct:.0f}%;background:{BEAR}'></span>"
            f"</div>")


def _leg_box(leg_label: str, ltp: Any, spiking: bool,
            location_vote: Mapping[str, Any], energy_vote: Mapping[str, Any],
            border: str) -> str:
    vol_word = "HIGH" if spiking else "normal"
    vol_col = WARN if spiking else MUTED
    loc = str((location_vote or {}).get("label") or "—")
    # Trim the leg-name prefix the vote label carries (e.g. "Call LTP at VOB
    # Support" → "at VOB Support") — this box already says which leg it is.
    for prefix in ("Call ", "Put "):
        if loc.startswith(prefix):
            loc = loc[len(prefix):]
            break
    energy = str((energy_vote or {}).get("label") or "—")
    for prefix in ("Call ", "Put "):
        if energy.startswith(prefix):
            energy = energy[len(prefix):]
            break
    return (
        f"<div style='flex:1;min-width:150px;border:1px solid {border};"
        f"border-radius:8px;padding:8px 10px'>"
        f"<div style='font-size:10px;letter-spacing:.08em;color:{MICRO};"
        f"text-transform:uppercase;margin-bottom:4px'>{_esc(leg_label)}</div>"
        f"<div style='font-size:11px;color:{MUTED}'>Volume "
        f"<b style='color:{vol_col}'>{vol_word}</b></div>"
        f"<div style='font-size:11px;color:{MUTED}'>LTP "
        f"<b style='color:{MUTED}'>{_px(ltp)}</b> · {_esc(loc)}</div>"
        f"<div style='font-size:11px;color:{MUTED}'>Energy "
        f"<b>{_esc(energy)}</b></div>"
        f"</div>")


def _context_chip(vote: Mapping[str, Any]) -> str:
    bias = (vote or {}).get("bias")
    dot = "🟢" if bias == _VOTE_BULL else "🔴" if bias == _VOTE_BEAR else "⚪"
    label = str((vote or {}).get("label") or "")
    name = label.split(":")[0] if ":" in label else label
    return f"<span style='font-size:11px;color:{MUTED};margin-right:10px'>{dot} {_esc(name)}</span>"


def card_html(model: Optional[Dict[str, Any]], spot: Any = None,
             call_ltp: Any = None, put_ltp: Any = None,
             call_label: str = "CALL", put_label: str = "PUT") -> str:
    """The full card. `""` when there is no model to show."""
    if not model:
        return ""
    verdict = str(model.get("verdict") or "MIXED")
    tone, glyph = _TONE.get(verdict, _TONE["MIXED"])
    votes = {v.get("key"): v for v in (model.get("votes") or []) if isinstance(v, Mapping)}

    if model.get("pinned"):
        lv = _f(model.get("pin_level"))
        lv_s = f" ₹{lv:,.0f}" if lv is not None else ""
        body = (
            f"<div style='text-align:center;padding:10px 4px'>"
            f"<div style='font-size:22px;font-weight:900;color:{tone}'>"
            f"{glyph} PINNED{lv_s}</div>"
            f"<div style='font-size:12px;color:{MUTED};margin-top:4px'>"
            f"Price is magnet-locked to one strike — no directional edge. "
            f"Not evidence for either side.</div></div>")
        return _card("🔭 Live Market Confluence", body)

    spot_v = votes.get("spot_location", {})
    flow_v = votes.get("price_action", {})
    ctx_keys = ("war_zone", "global", "sector", "news", "regime")

    header = (
        f"<div style='display:flex;justify-content:space-between;"
        f"align-items:baseline;flex-wrap:wrap;gap:8px'>"
        f"<div><span style='font-size:9px;color:{MICRO};letter-spacing:.08em;"
        f"text-transform:uppercase'>Spot</span><br>"
        f"<span style='font-size:16px;font-weight:800'>{_px(spot)}</span>"
        f" <span style='font-size:12px;color:{tone};font-weight:700'>"
        f"{_esc(spot_v.get('label'))}</span></div></div>")

    flow = (
        f"<div style='margin-top:8px'>"
        f"<span style='font-size:9px;color:{MICRO};letter-spacing:.08em;"
        f"text-transform:uppercase'>Price Action — CALL vs PUT participation</span>"
        f"<div style='font-size:12px;color:{MUTED}'>{_esc(flow_v.get('label'))}</div>"
        f"{_participation_bar(flow_v.get('value'))}</div>")

    legs = (
        f"<div style='display:flex;gap:10px;margin-top:10px;flex-wrap:wrap'>"
        + _leg_box(call_label, call_ltp, model.get("call_spiking"),
                  votes.get("call_location", {}), votes.get("call_energy", {}), BULL)
        + _leg_box(put_label, put_ltp, model.get("put_spiking"),
                  votes.get("put_location", {}), votes.get("put_energy", {}), BEAR)
        + "</div>")

    context = ("<div style='margin-top:10px'>"
              + "".join(_context_chip(votes.get(k, {})) for k in ctx_keys
                        if votes.get(k))
              + "</div>")

    bullish = [v["label"] for v in votes.values() if v.get("bias") == _VOTE_BULL]
    bearish = [v["label"] for v in votes.values() if v.get("bias") == _VOTE_BEAR]
    total = (model.get("bull_count", 0) + model.get("bear_count", 0)
            + model.get("neutral_count", 0))
    if verdict == "MIXED":
        summary = (
            f"<div style='font-size:11px;color:{BULL};margin-top:2px'>"
            f"Bullish: {', '.join(bullish) if bullish else '—'}</div>"
            f"<div style='font-size:11px;color:{BEAR};margin-top:2px'>"
            f"Bearish: {', '.join(bearish) if bearish else '—'}</div>"
            f"<div style='font-size:11px;color:{MUTED};margin-top:4px'>"
            f"No dominant alignment — watch for the first confirmed reaction."
            f"</div>")
    else:
        aligned = bullish if verdict == "BULLISH" else bearish
        summary = (
            f"<div style='font-size:11px;color:{MUTED};margin-top:2px'>"
            f"{', '.join(aligned) if aligned else '—'}</div>")

    footer = (
        f"<div style='margin-top:10px;padding-top:8px;"
        f"border-top:1px solid #1e2836'>"
        f"<span style='font-size:15px;font-weight:900;color:{tone}'>"
        f"{glyph} {verdict} CONFLUENCE</span>"
        f"<span style='font-size:11px;color:{MICRO}'> · {model.get('bull_count', 0)}"
        f" bull / {model.get('bear_count', 0)} bear of {total} read</span>"
        f"{summary}"
        f"<div style='font-size:10px;color:{MICRO};margin-top:6px'>"
        f"Confidence: Observational — this card does not generate a trade "
        f"signal.</div></div>")

    return _card("🔭 Live Market Confluence",
                 header + flow + legs + context + footer)
