"""⚙️ The Adaptive Greeks read, in the eight lines the spec asks for.

Not twenty Greek numbers — eight readings a trader acts on:

    DEALER POSITION   🟢 supportive · 🔴 opposing · 🟡 neutral
    GAMMA             positive / negative · flip level
    HEDGING PRESSURE  ↑ upward · ↓ downward · ↔ neutral
    PIN / MAGNET      ₹level · distance
    VOLATILITY        expanding / contracting / neutral
    BREAKOUT RISK     LOW / MEDIUM / HIGH
    FADE RISK         LOW / MEDIUM / HIGH
    GUARDIAN          the verdict + confidence, READ from the decision

⚠️ The Guardian line is **read, never produced here**. `adaptive_greeks` emits no
side (`assert_no_recommendation` enforces it), so the verdict and its confidence
arrive as parameters from whatever already decided them. This panel shows the
greeks *next to* that verdict — that is the whole point of the layer, and a panel
that minted its own BUY would undo it.

Every conclusion carries its evidence (rule 15): the reason line under the
verdict is assembled from the layer's own `evidence` and `conflicts`, never
re-worded.

Pure module — data in, HTML out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .nifty_cockpit import _card, _esc, _f, _get, _n, _row
from .theme import BEAR, BULL, CARD_BORDER, INK, MICRO, MUTED, VIOLET, WARN

#: Posture → (emoji, tone). One map, so the chip and the card agree.
POSTURE = {
    "SUPPORTIVE": ("🟢", BULL),
    "OPPOSING": ("🔴", BEAR),
    "NEUTRAL": ("🟡", WARN),
    "UNKNOWN": ("⚪", MUTED),
}

RISK_TONE = {"LOW": BULL, "MEDIUM": WARN, "HIGH": BEAR}

PRESSURE_ARROW = {"UPWARD": "↑ upward", "DOWNWARD": "↓ downward",
                  "NEUTRAL": "↔ neutral"}


def _risk(word: Any) -> str:
    w = str(word or "").strip().upper()
    return w if w in RISK_TONE else "—"


def _band(pct: Any) -> str:
    """A probability as a risk word. Two thresholds, stated once."""
    v = _f(pct)
    if v is None:
        return "—"
    return "HIGH" if v >= 60 else "MEDIUM" if v >= 40 else "LOW"


def greeks_card_html(out: Any = None, guardian: Any = None,
                     confidence: Any = None) -> str:
    """The full eight-line read. `""` when the layer reported nothing.

    `guardian` and `confidence` are the existing verdict, passed in. Absent them
    the card still draws the greeks and simply omits the Guardian line — the
    context is useful on its own, and inventing a verdict to fill the row would
    be the one thing this module must not do.
    """
    o = out if isinstance(out, Mapping) else {}
    if not o:
        return ""
    dealer = _get(o, "dealer") or {}
    pressure = _get(o, "pressure") or {}
    vol = _get(o, "volatility") or {}
    mods = _get(o, "modifiers") or {}

    posture = str(_get(dealer, "posture") or "UNKNOWN").upper()
    emoji, tone = POSTURE.get(posture, POSTURE["UNKNOWN"])

    rows: List[str] = [
        _row("Dealer position", f"{emoji} {_esc(posture)}", tone),
        _row("Gamma",
             _esc(str(_get(dealer, "gamma") or "—").title()), MUTED,
             (f"flip {_n(_get(dealer, 'gamma_flip'))}"
              if _f(_get(dealer, "gamma_flip")) is not None else "")),
        _row("Hedging pressure",
             _esc(PRESSURE_ARROW.get(str(_get(pressure, "direction") or "")
                                     .upper(), "—")), MUTED),
    ]
    if _f(_get(pressure, "magnet")) is not None:
        d = _f(_get(pressure, "distance"))
        rows.append(_row("Pin / magnet", f"₹{_n(_get(pressure, 'magnet'))}",
                         WARN,
                         f"{d:+.0f} pts" if d is not None else ""))
    rows.append(_row("Volatility",
                     _esc(str(_get(vol, "state") or "—").title()), VIOLET,
                     str(_get(vol, "confirmation") or "").title()))

    brk = _band(_get(mods, "breakout_probability"))
    fade = _band(_get(mods, "fade_probability"))
    rows.append(_row("Breakout risk", brk, RISK_TONE.get(brk, MUTED),
                     f"{_n(_get(mods, 'breakout_probability'))}%"))
    rows.append(_row("Fade risk", fade, RISK_TONE.get(fade, MUTED),
                     f"{_n(_get(mods, 'fade_probability'))}%"))

    # ── the Guardian line, read ──────────────────────────────────────
    verdict = ""
    word = str(guardian or "").strip().upper()
    if word:
        conf = _f(confidence)
        gt = (BULL if "BUY" in word else BEAR if "SELL" in word
              else MUTED if "HOLD" in word or "WAIT" in word else WARN)
        verdict = (
            f"<div style='margin-top:7px;padding-top:6px;"
            f"border-top:1px solid {CARD_BORDER};display:flex;"
            f"justify-content:space-between;align-items:baseline'>"
            f"<span style='font-size:9px;letter-spacing:.12em;color:{MICRO}'>"
            f"GUARDIAN</span>"
            f"<span style='font-size:15px;font-weight:800;color:{gt}'>"
            f"{_esc(word)}"
            + (f"<span style='font-size:11px;color:{MICRO};font-weight:600;"
               f"margin-left:6px'>{conf:.0f}/100</span>"
               if conf is not None else "")
            + "</span></div>")

    # ── the reason, from the layer's own words ───────────────────────
    reason = _reason_line(o)
    note = (f"<div style='font-size:10.5px;color:{MUTED};margin-top:5px'>"
            f"{_esc(reason)}</div>" if reason else "")

    foot = (f"<div style='font-size:9px;color:{MICRO};margin-top:5px'>"
            f"Context and confirmation — greeks modify confidence, they do not "
            f"make the call. Regime: "
            f"{_esc(str(_get(o, 'regime') or '—'))}</div>")

    missing = [str(m).replace("_", " ") for m in (_get(o, "missing") or ())]
    if missing:
        note += (f"<div style='font-size:9.5px;color:{MICRO};margin-top:3px'>"
                 f"⚪ not reporting: {_esc(' · '.join(missing))}</div>")

    return _card("⚙️ Dealer & volatility context",
                 "".join(rows) + verdict + note + foot)


def _reason_line(out: Mapping[str, Any]) -> str:
    """One sentence, taken from the layer's own conflict verdicts.

    A conflict is the most actionable thing the layer produces, so it leads. With
    no conflict the confidence reasons stand in. Nothing is re-phrased — the words
    are `adaptive_greeks`'s, so this panel and any other surface say the same
    thing about the same cycle.
    """
    cfl = list(_get(out, "conflicts") or ())
    if cfl:
        first = cfl[0] if isinstance(cfl[0], Mapping) else {}
        verdict = str(_get(first, "verdict") or "").strip()
        why = str(_get(first, "why") or "").strip()
        return f"{verdict} — {why}" if verdict and why else (verdict or why)
    why = list(_get(_get(out, "modifiers") or {}, "confidence_why") or ())
    return "; ".join(str(w) for w in why[:2]).capitalize() if why else ""


# ══════════════════════════════════════════════════════════════════════
#  the short forms
# ══════════════════════════════════════════════════════════════════════

def micro(out: Any = None) -> str:
    """The header chip. `""` when there is nothing worth a chip.

    Two facts and a risk, because the strip is frozen on every screen and each
    row it grows costs that space all session: dealer posture, gamma sign, and
    the fade risk that follows from them.
    """
    o = out if isinstance(out, Mapping) else {}
    dealer = _get(o, "dealer") or {}
    mods = _get(o, "modifiers") or {}
    posture = str(_get(dealer, "posture") or "").upper()
    if not posture or posture == "UNKNOWN":
        return ""
    emoji = POSTURE.get(posture, POSTURE["UNKNOWN"])[0]
    bits = [f"{emoji} dealer {posture.lower()}"]
    gamma = str(_get(dealer, "gamma") or "").upper()
    if gamma in ("POSITIVE", "NEGATIVE"):
        bits.append(f"{'+' if gamma == 'POSITIVE' else '−'}γ")
    fade = _band(_get(mods, "fade_probability"))
    if fade != "—":
        bits.append(f"fade {fade.lower()}")
    return "⚙️ " + " · ".join(bits)


def one_line(out: Any = None) -> str:
    """The Trade Card / Market Picture line — plain text, one sentence.

    Short on purpose: those two surfaces already carry a verdict, and this adds
    the terrain it has to cross, not a second opinion about it.
    """
    o = out if isinstance(out, Mapping) else {}
    dealer = _get(o, "dealer") or {}
    pressure = _get(o, "pressure") or {}
    mods = _get(o, "modifiers") or {}
    posture = str(_get(dealer, "posture") or "").upper()
    if not posture or posture == "UNKNOWN":
        return ""
    parts = [f"Dealers {posture.lower()}"]
    gamma = str(_get(dealer, "gamma") or "").title()
    if gamma in ("Positive", "Negative"):
        parts.append(f"{gamma.lower()} gamma")
    mg = _f(_get(pressure, "magnet"))
    if mg is not None and _get(pressure, "near"):
        parts.append(f"magnet ₹{mg:,.0f}")
    fade = _band(_get(mods, "fade_probability"))
    if fade in ("MEDIUM", "HIGH"):
        parts.append(f"{fade.lower()} fade risk")
    return " · ".join(parts) + "."
