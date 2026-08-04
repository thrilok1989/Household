"""The execution chain — Stages 72 → 73 → 72.9, on one card.

Pure presentation. Every value was decided by the three stages; this file
decides only where it sits and what colour it is.

## Why the three belong on one card

They are one thought split across three owners. Stage 72 says *should I enter*,
Stage 73 says *what do I do about the position*, Stage 72.9 says *does anyone
get told*. Rendered apart, a trader has to hold three panels in their head to
answer one question; rendered together, the disagreements are visible — and the
disagreements are the interesting part. Stage 72 saying `ENTER` while Stage 73
says `ABORT` is exactly the moment worth seeing.

## ⚠️ Nothing here has been sent

The dispatcher runs with **no transport**, so it prepares a payload, decides
whether it *would* send, and reports `NOT_SENT`. Stage 72.9 is
`VALIDATED_SIMULATED`; `STAGE72_9_VALIDATION_REPORT.md` records
`freeze_ready: False`. The panel says so on every render rather than in a
footnote, because a dispatch state that reads like a delivery is the one
misreading that would cost money.

## Every decision carries its identity

`id`, `version` and the first bytes of `hash` are shown. Not decoration: Stage
73 references Stage 72's id rather than minting its own, and seeing the same id
across all three rows is how a reader confirms the chain is describing one
decision rather than three independent ones.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .theme import (ALERT, BEAR, BULL, BULL_SOFT, FAINT, INK, MICRO, MUTED,
                    WARN)

UNKNOWN = "UNKNOWN"

#: Stage 52's vocabulary, coloured by what it means for a trader.
_STATE_COL = {
    "ENTER": BULL, "ENTRY_READY": BULL_SOFT, "ADD": BULL_SOFT,
    "HOLD": MUTED, "WAIT": MUTED, "TRAIL": WARN,
    "SCALE_OUT": WARN, "EXIT": ALERT, "ABORT": ALERT, "COMPLETE": MICRO,
    "WAIT_ENTRY": MUTED, "ENTERED": BULL_SOFT,
}

#: Dispatch states. `DELIVERED` is deliberately NOT green — nothing in this
#: build delivers, so a green delivery badge would be a lie waiting to happen.
_DISPATCH_COL = {
    "SENT": BULL_SOFT, "DELIVERED": BULL_SOFT, "READY": WARN,
    "NOT_SENT": MICRO, "BLOCKED": ALERT, "DUPLICATE": MICRO,
    "RATE_LIMIT": WARN, "RETRY": WARN, "DELIVERY_FAILED": ALERT,
}

_QUALITY_COL = {"A+": BULL, "A": BULL_SOFT, "B": WARN, "C": ALERT}


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _txt(v) -> str:
    s = "" if v is None else str(v).strip()
    return s if s and s != UNKNOWN else "—"


def _px(v) -> str:
    n = _num(v)
    return "—" if n is None else f"{n:,.1f}"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """A field from a frozen decision or from a stored dict.

    Both shapes render identically, so a replayed decision looks like a live
    one — which is the point of the identity fields below.
    """
    if obj is None:
        return default
    got = getattr(obj, name, None)
    if got is None and isinstance(obj, dict):
        got = obj.get(name)
    return default if got is None else got


def _cell(label: str, value: str, tone: str = MUTED) -> str:
    return (f"<div style='min-width:0'>"
            f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase'>{label}</div>"
            f"<div style='font-size:11px;font-weight:700;color:{tone}'>"
            f"{value}</div></div>")


def _identity(obj: Any) -> str:
    """id · version · hash prefix. Seeing the same id on Stage 73's row as on
    Stage 72's is how a reader confirms the chain describes one decision."""
    ident = str(_get(obj, "id", "") or "")
    version = str(_get(obj, "version", "") or "")
    digest = str(_get(obj, "hash", "") or "")
    bits = []
    if ident:
        bits.append(ident[:8])
    if version:
        bits.append(f"v{version}")
    if digest:
        bits.append(digest[:8])
    return " · ".join(bits) or "—"


def _row(stage: str, name: str, headline: str, colour: str,
         cells: str, ident: str, note: str = "") -> str:
    return (
        f"<div style='background:#0b0f16;border:1px solid #1e2836;"
        f"border-radius:8px;padding:8px 9px;margin-top:6px'>"
        f"<div style='display:flex;gap:8px;align-items:baseline;flex-wrap:wrap'>"
        f"<span style='color:{MICRO};font-size:9px;letter-spacing:.08em'>"
        f"{stage}</span>"
        f"<span style='color:{MUTED};font-size:10.5px'>{name}</span>"
        f"<span style='color:{colour};font-weight:800;font-size:13px'>"
        f"{headline}</span>"
        f"<span style='color:{MICRO};font-size:9px;margin-left:auto;"
        f"white-space:nowrap;font-family:monospace'>{ident}</span></div>"
        + (f"<div style='display:flex;flex-wrap:wrap;gap:10px;margin-top:5px;"
           f"padding-top:4px;border-top:1px solid #1a2330'>{cells}</div>"
           if cells else "")
        + (f"<div style='font-size:10px;color:{MICRO};margin-top:3px'>{note}"
           f"</div>" if note else "")
        + "</div>")


def execution_html(decision: Any = None, lifecycle: Any = None,
                   dispatch: Any = None) -> str:
    """The whole card, or `""` when Stage 72 has not decided anything."""
    if decision is None:
        return ""

    state = str(_get(decision, "state", UNKNOWN))
    meta = _get(decision, "metadata", {}) or {}
    score = _num(_get(decision, "score"))
    quality = str(_get(decision, "quality", UNKNOWN))

    entry_cells = "".join([
        _cell("Score", "—" if score is None else f"{score:.0f}/100",
              BULL if (score or 0) >= 75 else WARN if (score or 0) >= 60
              else MUTED),
        _cell("Quality", _txt(quality), _QUALITY_COL.get(quality, MUTED)),
        _cell("Side", _txt(_get(decision, "side"))),
        _cell("Strike", _px(_get(decision, "strike"))),
        _cell("Zone", _txt(_get(decision, "entry_zone"))),
        _cell("Entry", _px(_get(decision, "entry"))),
        _cell("Stop", _px(_get(decision, "stop")), ALERT),
        _cell("R:R", _txt(_get(decision, "risk_reward"))),
        _cell("Readiness", _txt(_get(decision, "readiness"))),
    ])
    reason = str(_get(meta, "state_reason", "") or "")

    rows = _row("STAGE 72", "Entry Engine", state,
                _STATE_COL.get(state, FAINT), entry_cells,
                _identity(decision), reason)

    if lifecycle is not None:
        action = str(_get(lifecycle, "action", UNKNOWN))
        lc_cells = "".join([
            _cell("State", _txt(_get(lifecycle, "state"))),
            _cell("Health", _txt(_get(lifecycle, "health"))),
            _cell("Intent", _txt(_get(lifecycle, "intent"))),
            # Always UNKNOWN by design — no producer publishes the position, and
            # Stage 73 refuses to infer one.
            _cell("Position", _txt(_get(lifecycle, "position_known")), MICRO),
            _cell("Trail", _txt(_get(lifecycle, "trail"))),
            _cell("Exit reason", _txt(_get(lifecycle, "exit_reason"))),
        ])
        same = (str(_get(lifecycle, "decision_id", "")) ==
                str(_get(decision, "id", "")))
        rows += _row(
            "STAGE 73", "Trade Lifecycle", action,
            _STATE_COL.get(action, FAINT), lc_cells, _identity(lifecycle),
            "" if same else "⚠ this lifecycle does not reference the entry "
                            "decision above")

    if dispatch is not None:
        d_state = str(_get(dispatch, "dispatch_state", UNKNOWN))
        tele = str(_get(dispatch, "telegram_state", UNKNOWN))
        # `should_send` is the verdict, `telegram_state` is what happened.
        # Showing both is the point of running the chain unwired: the gap
        # between "would have sent" and "sent" is exactly what is being
        # withheld until Stage 72.9 is validated.
        record = _get(dispatch, "record")
        d_cells = "".join([
            _cell("Would send", _txt(_get(dispatch, "should_send"))),
            _cell("Telegram", _txt(tele), _DISPATCH_COL.get(tele, MICRO)),
            _cell("Duplicate", _txt(_get(dispatch, "duplicate"))),
            _cell("Message id",
                  _txt(_get(record, "telegram_message_id")) if record else "—"),
        ])
        rows += _row("STAGE 72.9", "Dispatcher", d_state,
                     _DISPATCH_COL.get(d_state, FAINT), d_cells,
                     _identity(dispatch),
                     str(_get(dispatch, "dispatch_reason", "") or ""))

    return (
        f"<div style='background:#0d1117;border:1px solid #1e2836;"
        f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"
        f"<div style='font-size:11px;letter-spacing:.10em;color:{INK};"
        f"text-transform:uppercase'>⚙️ Execution chain "
        f"<span style='color:{MICRO};letter-spacing:0'>· Stages 72 → 73 → "
        f"72.9 · advisory</span></div>"
        # Stated on every render, not in a footnote: a dispatch state that
        # reads like a delivery is the one misreading that would cost money.
        f"<div style='font-size:10px;color:{WARN};margin-top:3px'>"
        f"⚠️ <b>Nothing is sent.</b> The dispatcher runs with no transport — it "
        f"prepares the payload and reports what it <i>would</i> do. Stage 72.9 "
        f"is VALIDATED_SIMULATED and its validation report records "
        f"<code>freeze_ready: False</code>.</div>"
        + rows + "</div>")


def render_execution(st, decision: Any = None, lifecycle: Any = None,
                     dispatch: Any = None) -> None:
    """Draw it, or say nothing. Advisory — it may never take the tab down."""
    try:
        html = execution_html(decision, lifecycle, dispatch)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Execution chain unavailable: {err}")
