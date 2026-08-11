"""🧭 Dashboard 1 — the NIFTY index cockpit, in five blocks.

Answers five questions about the **index** and nothing else. Option-leg
behaviour belongs on Dashboard 2; engine telemetry belongs behind the audit
expander.

    1. Where is NIFTY, against the levels that matter?   `price_map_html`
    2. Where are the OI walls?                           `oi_walls_html`
    3. Is price pinned to a magnet?                      `market_pin_html`
    4. Where are support and resistance?                 `sr_table_html`
    5. Who is winning the level price is at?             `battle_zone_html`

## Every function is pure

Data in, HTML string out. No `streamlit`, no `session_state`, no database, no
engine imports. That is principle 4 — *an engine that needs a value receives it
as a parameter* — and it is also what makes this file renderable outside the app:
each block can be screenshotted from synthetic data before anyone deploys it.
The collector that reads session state lives in `dashboard_v6.py`, where every
other tab's collector lives.

## It calculates nothing

⚠️ Worth being exact, because the temptation here is real. `compute_market_picture`
owns the wall strikes (`oi_ceiling`, `oi_floor`), the pin (`oi_pin`) and the
gate's verdict; `calculate_money_flow_profile` owns POC and the value area;
Stage 35 owns the battle zone; `sr_intel.rank_levels` owns the S/R ordering.
This file **formats** those and never re-derives one of them. A second
implementation of "which strike is the wall" that disagreed with the Market
Picture by one strike would be worse than no panel at all.

The one thing it does arithmetic on is **distance from spot**, which is
subtraction, and a total PCR from the per-strike OI the chain already published.

## Three-state discipline

A missing value renders `—`, never `0` and never a guess. Zero is a market fact
— perfectly balanced flow — and printing one that was never measured is
fabricating data the reader cannot distinguish from the real thing. Every
formatter here goes through `_n`/`_f`, which return `None` rather than a
plausible lie, and every block returns `""` when it has nothing at all to say
rather than drawing an empty frame.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .theme import (ALERT, BEAR, BULL, CARD_BG, CARD_BORDER, FAINT, INK,
                    LABEL, MICRO, MUTED, VIOLET, WARN)

#: Shared card chrome, so five blocks cannot drift into five looks.
_CARD = (f"background:{CARD_BG};border:1px solid {CARD_BORDER};"
         f"border-radius:10px;padding:10px 12px;margin-bottom:8px")

_H = (f"font-size:9px;letter-spacing:.12em;color:{MICRO};"
      f"text-transform:uppercase;margin-bottom:6px")


# ══════════════════════════════════════════════════════════════════════
#  numbers that refuse to invent themselves
# ══════════════════════════════════════════════════════════════════════

def _f(v: Any) -> Optional[float]:
    """A float, or `None`. Never `0.0` as a stand-in for "not reported"."""
    if v is None or isinstance(v, bool):
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return None if out != out else out          # NaN is not a reading


def _n(v: Any, dp: int = 0, dash: str = "—") -> str:
    """Format a level. `—` when it was never measured."""
    f = _f(v)
    return dash if f is None else f"{f:,.{dp}f}"


def _esc(v: Any) -> str:
    return (str("" if v is None else v).replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _pct(v: Any, dp: int = 0) -> str:
    f = _f(v)
    return "—" if f is None else f"{f:.{dp}f}%"


def _dist(level: Any, spot: Any) -> str:
    """Signed distance from spot, in points. The number a trader actually uses:
    "24,605" means nothing without "+22 away"."""
    a, b = _f(level), _f(spot)
    return "—" if a is None or b is None else f"{a - b:+,.0f}"


def _get(src: Any, *keys: str) -> Any:
    """First present key. ⚠️ `Mapping`, not `dict` — MIOS freezes values as
    `MappingProxyType`, which is not a dict subclass, and this repo has shipped
    that confusion four times."""
    if not isinstance(src, Mapping):
        return None
    for k in keys:
        if src.get(k) is not None:
            return src.get(k)
    return None


def _row(label: str, value: str, tone: str = INK, extra: str = "") -> str:
    return (f"<div style='display:flex;justify-content:space-between;"
            f"gap:10px;padding:2px 0;font-size:12px'>"
            f"<span style='color:{LABEL}'>{_esc(label)}</span>"
            f"<span style='color:{tone};font-weight:700'>{value}"
            + (f"<span style='color:{MICRO};font-weight:400;margin-left:6px'>"
               f"{_esc(extra)}</span>" if extra else "")
            + "</span></div>")


def _card(title: str, inner: str) -> str:
    return (f"<div style='{_CARD}'><div style='{_H}'>{_esc(title)}</div>"
            f"{inner}</div>")


# ══════════════════════════════════════════════════════════════════════
#  1 · where is NIFTY
# ══════════════════════════════════════════════════════════════════════

def price_map_html(spot: Any, profile: Any = None, vwap: Any = None,
                   day: Any = None, prev_day: Any = None) -> str:
    """📍 The index against the levels that matter, ordered high to low.

    Ordered by PRICE rather than by importance on purpose: this block is a map,
    and a map whose rows are sorted by significance cannot be read as one. Spot
    is marked in place so "where am I" is answered by position, not arithmetic.

    `profile` is `_money_flow_data` — POC and the value area, owned by
    `calculate_money_flow_profile`. `day` and `prev_day` carry `high`/`low`.
    """
    px = _f(spot)
    rows: List[tuple] = [
        ("Prev Day High", _get(prev_day, "prev_high", "high"), FAINT),
        ("Day High", _get(day, "high"), MUTED),
        ("VAH", _get(profile, "value_area_high", "vah"), VIOLET),
        ("POC", _get(profile, "poc_price", "poc"), WARN),
        ("VWAP", vwap, VIOLET),
        ("VAL", _get(profile, "value_area_low", "val"), VIOLET),
        ("Day Low", _get(day, "low"), MUTED),
        ("Prev Day Low", _get(prev_day, "prev_low", "low"), FAINT),
    ]
    priced = [(lbl, _f(v), tone) for lbl, v, tone in rows if _f(v) is not None]
    if px is None and not priced:
        return ""
    priced.sort(key=lambda r: -r[1])

    out: List[str] = []
    placed = px is None
    for lbl, val, tone in priced:
        if not placed and val < px:
            out.append(_spot_row(px))
            placed = True
        out.append(_row(lbl, f"{val:,.0f}", tone, _dist(val, px)))
    if not placed:
        out.append(_spot_row(px))
    # Levels that were not reported, named rather than silently missing: a map
    # with a hole in it should say which hole.
    absent = [lbl for lbl, v, _t in rows if _f(v) is None]
    if absent:
        out.append(f"<div style='font-size:9.5px;color:{MICRO};margin-top:5px'>"
                   f"⚪ not reported: {_esc(' · '.join(absent))}</div>")
    return _card("📍 Nifty price map", "".join(out))


def _spot_row(px: float) -> str:
    return (f"<div style='display:flex;justify-content:space-between;"
            f"gap:10px;padding:3px 6px;margin:3px -6px;border-radius:5px;"
            f"background:rgba(23,201,139,.12);border-left:3px solid {BULL};"
            f"font-size:13px'>"
            f"<span style='color:{BULL};font-weight:800'>● SPOT</span>"
            f"<span style='color:{INK};font-weight:800'>{px:,.2f}</span></div>")


# ══════════════════════════════════════════════════════════════════════
#  2 · the OI walls
# ══════════════════════════════════════════════════════════════════════

def oi_walls_html(spot: Any, ceiling: Any = None, floor: Any = None,
                  ladder: Optional[Sequence[Mapping[str, Any]]] = None,
                  pcr: Any = None, atm: Any = None) -> str:
    """🧱 The two walls, then the ATM ladder they sit in.

    `ceiling` and `floor` are `compute_market_picture`'s `oi_ceiling` /
    `oi_floor` — `(strike, oi_in_lakhs)`. **Read, never re-derived.** A second
    "which strike is the biggest wall" that disagreed by one strike would be
    worse than showing nothing.

    `ladder` is ATM±2 rows straight off the chain: `strike`, `ce_oi`, `pe_oi`,
    `ce_doi`, `pe_doi`. Presenting published rows is display; picking a maximum
    would not be.
    """
    ce_k, ce_oi = _pair(ceiling)
    pe_k, pe_oi = _pair(floor)
    if ce_k is None and pe_k is None and not ladder:
        return ""

    walls = (
        f"<div style='display:flex;gap:8px;flex-wrap:wrap'>"
        f"{_wall_box('CALL WALL', ce_k, ce_oi, spot, BEAR, 'resistance')}"
        f"{_wall_box('PUT WALL', pe_k, pe_oi, spot, BULL, 'support')}"
        f"</div>")

    head = ""
    bits = []
    if _f(atm) is not None:
        bits.append(f"ATM <b style='color:{INK}'>{_n(atm)}</b>")
    if _f(pcr) is not None:
        p = _f(pcr)
        tone = BULL if p > 1.2 else BEAR if p < 0.8 else WARN
        bits.append(f"PCR <b style='color:{tone}'>{p:.2f}</b>")
    if _f(ce_oi) is not None and _f(pe_oi) is not None:
        lead = "PUT" if _f(pe_oi) > _f(ce_oi) else "CALL"
        tone = BULL if lead == "PUT" else BEAR
        bits.append(f"Heavier side <b style='color:{tone}'>{lead}</b>")
    if bits:
        head = (f"<div style='font-size:11.5px;color:{MUTED};margin:6px 0 4px'>"
                + " · ".join(bits) + "</div>")

    return _card("🧱 OI walls", walls + head + _ladder_html(ladder, atm, spot))


def _pair(v: Any):
    """`(strike, oi)` from the market picture's 2-tuple, tolerantly."""
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return _f(v[0]), _f(v[1])
    if isinstance(v, Mapping):
        return _f(_get(v, "strike", "price")), _f(_get(v, "oi", "value"))
    return None, None


def _wall_box(title: str, strike: Any, oi: Any, spot: Any, tone: str,
              role: str) -> str:
    if _f(strike) is None:
        return (f"<div style='flex:1 1 46%;min-width:150px;padding:6px 8px;"
                f"border:1px solid {CARD_BORDER};border-radius:8px'>"
                f"<div style='font-size:9px;color:{MICRO};letter-spacing:.1em'>"
                f"{_esc(title)}</div>"
                f"<div style='font-size:12px;color:{FAINT}'>⚪ not reported"
                f"</div></div>")
    return (f"<div style='flex:1 1 46%;min-width:150px;padding:6px 8px;"
            f"border:1px solid {CARD_BORDER};border-left:3px solid {tone};"
            f"border-radius:8px'>"
            f"<div style='font-size:9px;color:{MICRO};letter-spacing:.1em'>"
            f"{_esc(title)} · {_esc(role)}</div>"
            f"<div style='font-size:17px;font-weight:800;color:{tone}'>"
            f"{_n(strike)}</div>"
            f"<div style='font-size:11px;color:{MUTED}'>"
            + (f"{_f(oi):.1f}L OI · " if _f(oi) is not None else "")
            + f"{_dist(strike, spot)} pts</div></div>")


def _ladder_html(ladder: Optional[Sequence[Mapping[str, Any]]], atm: Any,
                 spot: Any) -> str:
    """ATM±2, CE on the left and PE on the right of the strike.

    Strike in the MIDDLE deliberately — it is the axis both sides are measured
    against, and a chain read with the strike in the first column makes the
    reader scan back to it for every comparison.
    """
    rows = [r for r in (ladder or ()) if isinstance(r, Mapping)
            and _f(_get(r, "strike")) is not None]
    if not rows:
        return ""
    rows.sort(key=lambda r: -_f(_get(r, "strike")))
    atm_f = _f(atm)

    head = ("<tr>" + "".join(
        f"<th style='text-align:{a};font-size:8.5px;letter-spacing:.08em;"
        f"color:{MICRO};font-weight:600;padding:2px 5px'>{h}</th>"
        for h, a in (("CE ΔOI", "right"), ("CE OI", "right"),
                     ("STRIKE", "center"),
                     ("PE OI", "left"), ("PE ΔOI", "left"))) + "</tr>")

    body = []
    for r in rows:
        k = _f(_get(r, "strike"))
        is_atm = atm_f is not None and abs(k - atm_f) < 0.5
        bg = "background:rgba(255,208,0,.08)" if is_atm else ""
        body.append(
            f"<tr style='{bg}'>"
            + _cell(_doi(_get(r, "ce_doi")), "right")
            + _cell(_lakh(_get(r, "ce_oi")), "right", BEAR)
            + _cell(f"<b>{k:,.0f}</b>" + (" ◀" if is_atm else ""), "center",
                    WARN if is_atm else INK)
            + _cell(_lakh(_get(r, "pe_oi")), "left", BULL)
            + _cell(_doi(_get(r, "pe_doi")), "left")
            + "</tr>")
    return (f"<table style='width:100%;border-collapse:collapse;"
            f"margin-top:4px'>{head}{''.join(body)}</table>")


def _cell(inner: str, align: str, tone: str = MUTED) -> str:
    return (f"<td style='text-align:{align};font-size:11.5px;color:{tone};"
            f"padding:2px 5px;white-space:nowrap'>{inner}</td>")


def _lakh(v: Any) -> str:
    f = _f(v)
    return "—" if f is None else f"{f / 1e5:.1f}L" if abs(f) > 1e4 else f"{f:,.0f}"


def _doi(v: Any) -> str:
    """ΔOI with its sign kept. A wall that is BUILDING and one that is being
    unwound are opposite facts and an unsigned number hides which."""
    f = _f(v)
    if f is None:
        return "—"
    tone = BULL if f > 0 else BEAR if f < 0 else MICRO
    txt = f"{f / 1e5:+.1f}L" if abs(f) > 1e4 else f"{f:+,.0f}"
    return f"<span style='color:{tone}'>{txt}</span>"


# ══════════════════════════════════════════════════════════════════════
#  3 · the pin
# ══════════════════════════════════════════════════════════════════════

def market_pin_html(spot: Any, oi_pin: Any = None, gate: Any = None,
                    poc: Any = None, gamma_flip: Any = None) -> str:
    """📌 Pin / magnet — price, distance, side, and whether the veto is live.

    Two different facts, kept apart on purpose:

    * `oi_pin` is the **detection** — the coincident CE+PE wall, and its note.
    * `gate['state'] == 'PINNED'` is the **decision** — price is close enough
      that the entry gate has vetoed every directional read.

    A pin can be detected while price has walked away from it, and a panel that
    collapsed the two would tell a trader "PINNED" when nothing is vetoed. So
    `Status` reports the detection's geometry and `Regime` reports the gate.
    """
    pin_k, _ = _pair(oi_pin)
    note = ""
    if isinstance(oi_pin, (list, tuple)) and len(oi_pin) >= 2:
        note = str(oi_pin[1] or "")
    pinned = (isinstance(gate, Mapping)
              and str(gate.get("state") or "").strip().upper() == "PINNED")
    if pin_k is None and not pinned:
        # ⚠️ "NOT PINNED" is a READING, and it needs evidence. With no pin, no
        # gate and no spot, nothing was measured — and printing NOT PINNED there
        # asserts the directional logic is live when the truth is that nobody
        # looked. Only claim it once the gate has reported or spot is known.
        if _f(spot) is None and not isinstance(gate, Mapping):
            return ""
        return _card("📌 Market pin", _row("Regime", "NOT PINNED", MUTED))

    px, gap = _f(spot), None
    if pin_k is not None and px is not None:
        gap = abs(pin_k - px)
    side = ("—" if gap is None else
            "AT PIN" if gap <= 10 else
            "ABOVE PIN" if px > pin_k else "BELOW PIN")
    tone = WARN if pinned else MUTED

    inner = [
        f"<div style='font-size:22px;font-weight:800;color:{tone};"
        f"line-height:1.1'>{_n(pin_k)}</div>",
        _row("Distance", f"{_dist(pin_k, spot)} pts"),
        _row("Position", side, WARN if side == "AT PIN" else MUTED),
        _row("Regime", "PINNED — no directional edge" if pinned
             else "NOT PINNED", WARN if pinned else MUTED),
        _row("POC", _n(poc), VIOLET),
        _row("Gamma flip", _n(gamma_flip), VIOLET),
    ]
    if note:
        inner.append(f"<div style='font-size:10.5px;color:{MICRO};"
                     f"margin-top:5px'>{_esc(note)}</div>")
    return _card("📌 Market pin", "".join(inner))


# ══════════════════════════════════════════════════════════════════════
#  4 · support and resistance
# ══════════════════════════════════════════════════════════════════════

#: Two a side. The spec's number, and the reason is not screen space: a ranked
#: list of six levels is a list nobody finishes reading, and the fifth-best
#: support is not a level anyone trades.
MAX_PER_SIDE = 2


def sr_table_html(levels: Optional[Sequence[Mapping[str, Any]]],
                  spot: Any = None) -> str:
    """🛡 The two supports and two resistances worth watching.

    `levels` is `_sr_levels` — already ranked by `sr_intel.rank_levels`, which
    puts an active level first, then confidence, then confluence. **The order is
    taken, not recomputed**; this only truncates it per side.

    Break and rejection are shown together, always. They are complements, and
    printing one invites the reader to supply the other from a wrong prior.
    """
    rows = [l for l in (levels or ()) if isinstance(l, Mapping)]
    if not rows:
        return ""
    picked: List[Mapping[str, Any]] = []
    for want in ("RESISTANCE", "SUPPORT"):
        same = [l for l in rows
                if str(_get(l, "side") or "").strip().upper() == want]
        picked.extend(same[:MAX_PER_SIDE])
    if not picked:
        return ""

    head = ("<tr>" + "".join(
        f"<th style='text-align:{a};font-size:8.5px;letter-spacing:.08em;"
        f"color:{MICRO};font-weight:600;padding:3px 5px'>{h}</th>"
        for h, a in (("LEVEL", "left"), ("PRICE", "right"), ("AWAY", "right"),
                     ("BREAK", "right"), ("REJECT", "right"),
                     ("STATUS", "left"))) + "</tr>")

    body = []
    for l in picked:
        side = str(_get(l, "side") or "").strip().upper()
        tone = BEAR if side == "RESISTANCE" else BULL
        pr = _get(l, "probabilities") or {}
        brk, rej = _get(pr, "break"), _get(pr, "rejection", "bounce")
        status = ("AT PRICE" if _get(l, "active") else
                  str(_get(l, "status", "state") or "Holding"))
        body.append(
            "<tr>"
            + _cell(f"<b>{'🧱' if side == 'RESISTANCE' else '🛡'} "
                    f"{side.title()}</b>", "left", tone)
            + _cell(f"<b>{_n(_get(l, 'price', 'level'))}</b>", "right", INK)
            + _cell(_dist(_get(l, "price", "level"), spot), "right")
            + _cell(_pct(brk), "right", BEAR if _f(brk) and _f(brk) > 55 else MUTED)
            + _cell(_pct(rej), "right", BULL if _f(rej) and _f(rej) > 55 else MUTED)
            + _cell(_esc(status), "left",
                    WARN if _get(l, "active") else MUTED)
            + "</tr>")
    extra = ""
    hidden = len(rows) - len(picked)
    if hidden > 0:
        extra = (f"<div style='font-size:9.5px;color:{MICRO};margin-top:5px'>"
                 f"{hidden} lower-ranked level{'s' if hidden > 1 else ''} not "
                 f"shown — ranked by Stage 42, best first.</div>")
    # ⚠️ A plain `&`, not `&amp;`. `_card` escapes its title, so a pre-escaped
    # entity is escaped twice and renders as the literal text "&amp;" — which is
    # exactly what the first screenshot of this panel showed.
    return _card("🛡 Support & resistance",
                 f"<table style='width:100%;border-collapse:collapse'>"
                 f"{head}{''.join(body)}</table>{extra}")


# ══════════════════════════════════════════════════════════════════════
#  5 · the battle
# ══════════════════════════════════════════════════════════════════════

def battle_zone_html(battle_zone: Any = None, winner: Any = None,
                     probabilities: Any = None, spot: Any = None) -> str:
    """⚔️ The level price is actually at, and who is winning it.

    Stage 35 owns all four values. This block exists because "resistance at
    24,605" and "the buyers are losing that level" are different readings, and
    the second is the one that decides whether a break is worth trusting.
    """
    zone = battle_zone if isinstance(battle_zone, Mapping) else {}
    price = _get(zone, "price", "level")
    kind = str(_get(zone, "type", "side", "kind") or "").strip().upper()
    pr = probabilities if isinstance(probabilities, Mapping) else {}
    brk, rej = _get(pr, "break", "breakout"), _get(pr, "rejection", "reject")
    win = str(winner or "").strip() or "—"
    if _f(price) is None and win == "—":
        return ""

    tone = (BULL if "BUY" in win.upper() else BEAR if "SELL" in win.upper()
            else WARN)
    inner = [
        f"<div style='font-size:20px;font-weight:800;color:{INK};"
        f"line-height:1.1'>{_n(price)}"
        + (f"<span style='font-size:11px;color:{MICRO};margin-left:6px'>"
           f"{_esc(kind.title())}</span>" if kind else "")
        + "</div>",
        _row("Away", f"{_dist(price, spot)} pts"),
        _row("Break", _pct(brk), BEAR if _f(brk) and _f(brk) > 55 else MUTED),
        _row("Reject", _pct(rej), BULL if _f(rej) and _f(rej) > 55 else MUTED),
        _row("Winner", _esc(win.upper()), tone),
    ]
    return _card("⚔️ Battle zone", "".join(inner))


# ══════════════════════════════════════════════════════════════════════
#  the block order
# ══════════════════════════════════════════════════════════════════════

#: Read top to bottom, this is the order the questions get asked in — where am
#: I, what is holding me, am I stuck to it, what are the levels, who is winning.
#: Kept as data so the collector cannot silently reorder them and so a test can
#: assert the sequence rather than trusting a comment.
BLOCK_ORDER = ("price_map", "oi_walls", "market_pin", "sr_table",
               "battle_zone")


def cockpit_blocks(data: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Every block, keyed by name. Blocks with nothing to say are absent.

    One entry point so the collector reads session state once and this file
    decides what is renderable — and so the whole dashboard can be built from a
    single dict in a test or a preview harness.
    """
    d = data if isinstance(data, Mapping) else {}
    spot = d.get("spot")
    out = {
        "price_map": price_map_html(spot, d.get("profile"), d.get("vwap"),
                                    d.get("day"), d.get("prev_day")),
        "oi_walls": oi_walls_html(spot, d.get("oi_ceiling"), d.get("oi_floor"),
                                  d.get("ladder"), d.get("pcr"), d.get("atm")),
        "market_pin": market_pin_html(spot, d.get("oi_pin"), d.get("gate"),
                                      _get(d.get("profile") or {}, "poc_price",
                                           "poc"),
                                      d.get("gamma_flip")),
        "sr_table": sr_table_html(d.get("sr_levels"), spot),
        "battle_zone": battle_zone_html(d.get("battle_zone"), d.get("winner"),
                                        d.get("probabilities"), spot),
    }
    return {k: v for k, v in out.items() if v}
