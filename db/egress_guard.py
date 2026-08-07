"""A spending limit on Supabase reads, enforced by the app itself.

`read_cache` removed the waste — the five-minute refetch treadmill and the
full-table scans. This is the different thing that was asked for next:
**control.** A budget the app enforces at the read boundary, so a bad day
cannot become a bad bill while nobody is watching.

Measurement alone could not do that. `tools/egress_meter.py` reports what a
cycle cost *after* it was spent, and only when someone remembered to set
`MIOS_EGRESS=1`. This runs always, in the running app, and can refuse.

## The rule it must never break

> **The budget may suppress analytics. It may not suppress the reads MIOS
> state, the decision stages, or Telegram alerts depend on.**

The same rule `docs/AUDIT_FOCUS_MODE.md` opens with, for the same reason: this
repo has three times shipped something that quietly took the alert chain down.
`PROTECTED` is that rule in machine-readable form, and `allow()` checks it
*before* it looks at the budget, the mode, or anything else. A trader who set
the budget to zero still gets their signals; they lose the learning tabs.

## Three modes, and the app moves between them on its own

* **`NORMAL`** — everything reads.
* **`FRUGAL`** — the heavy history and learning analytics stop. These are the
  reads `AUDIT_FOCUS_MODE.md` found reachable only from draw-only panels:
  `get_engine_attribution` at 8,000 rows, `get_session_log` at 8,000,
  `get_trade_events` at 4,000. Nothing on the decision path is in this set.
* **`CACHE_ONLY`** — nothing but `PROTECTED` reaches Supabase at all. Already
  cached rows still serve, so most of the screen keeps working.

`AUTO_FRUGAL_AT` and `AUTO_STOP_AT` are the fractions of the budget at which
the app degrades itself. A trader who never touches the sidebar still gets the
protection; one who wants a specific mode pins it.

## ⚠️ A blocked read is never silent

The failure this design could introduce is worse than the bill: a panel that
renders empty because its query was refused, looking exactly like a panel whose
table is genuinely empty. So every refusal is recorded with its method and its
reason, and the sidebar names them. `blocked_line()` exists to make "you are
not seeing this because you asked me not to fetch it" a sentence on screen.

## What the numbers are, and are not

Bytes here are the **parsed payload size**, the same measure
`tools/egress_meter.py` uses, and the same caveat applies: it excludes HTTP
headers and ignores gzip, so real egress on a repetitive JSON body is smaller.
It is a **budget in consistent units**, not a reading off the invoice. Setting
it to 50 MB does not promise 50 MB on the bill; it promises the app will have
stopped fetching by the time it has parsed 50 MB.
"""

from __future__ import annotations

import time as _time
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

NORMAL, FRUGAL, CACHE_ONLY = "NORMAL", "FRUGAL", "CACHE_ONLY"

#: Ordered loosest → tightest, which is what lets `_tighten` compare them.
MODES: Tuple[str, ...] = (NORMAL, FRUGAL, CACHE_ONLY)

#: Default session budget, in megabytes of parsed payload.
#:
#: 50 MB is the owner's stated target for a whole trading day. As a *session*
#: budget it is deliberately generous — the point is to catch a runaway, not to
#: nag — and the sidebar can lower it.
DEFAULT_BUDGET_MB = 50.0

#: Fractions of the budget at which the app tightens itself, without being told.
AUTO_FRUGAL_AT = 0.70
AUTO_STOP_AT = 1.00

_STATE_KEY = "_egress_guard"

#: ⚠️ Reads the budget may never refuse. The rule at the top of this file.
#:
#: The five LIVE reads answer *is there a position, what is the spot, what is
#: the config* — a stage that cannot see those does not degrade, it decides
#: wrongly. `get_candles` and `get_day_open_spot` feed the chart and the gap
#: read that the header and Stage 42 consume.
#:
#: Deliberately short. Every name here is a read that can never be throttled,
#: so adding one is a decision to spend, and it should look like one.
PROTECTED: Tuple[str, ...] = (
    "get_active_trade_signal", "get_active_trade", "get_latest_spot",
    "get_trade_config", "count_trade_signals_today",
    "get_candles", "get_day_open_spot",
)

#: The heavy history and learning reads FRUGAL drops first.
#:
#: Taken from `docs/AUDIT_FOCUS_MODE.md`, which found these reachable **only**
#: from draw-only panels — nothing on the decision path reads them. They are
#: also the largest queries in the app, which is why they are the first to go
#: rather than merely eligible.
ANALYTICS: Tuple[str, ...] = (
    "get_engine_attribution", "get_trade_attribution", "get_trade_events",
    "get_trade_results", "get_learning_snapshots", "get_layer_outcomes",
    "get_resolved_entry_gate_signals", "get_bias_predictions",
    "get_signal_outcomes", "get_story_validations", "get_story_stats",
    "get_event_impact_log", "get_opening_auction_log", "get_session_log",
    "get_session_recommendations", "get_session_validation",
    "get_liquidity_telemetry", "get_market_analytics", "get_trade_history",
    "get_option_chain_history", "get_atm_iv_history", "get_leg_flow_days",
    "get_candle_trading_days", "get_available_candle_series",
    "count_rows", "fetch_all_rows",
)


def _blank() -> Dict[str, Any]:
    return {"mode": NORMAL, "pinned": None, "budget_mb": DEFAULT_BUDGET_MB,
            "bytes": 0, "reads": 0, "blocked": {}, "by_method": {},
            "started": _time.time()}


def _state() -> Dict[str, Any]:
    """The guard's session-scoped ledger.

    Falls back to a module-level dict when there is no Streamlit session — a
    test, or an import from a worker. The guard must answer either way; a
    budget that raises outside Streamlit would make `read_cache` untestable.
    """
    try:
        got = st.session_state.get(_STATE_KEY)
        if not isinstance(got, dict):
            got = _blank()
            st.session_state[_STATE_KEY] = got
        return got
    except Exception:
        global _FALLBACK
        if _FALLBACK is None:
            _FALLBACK = _blank()
        return _FALLBACK


_FALLBACK: Optional[Dict[str, Any]] = None


# ══════════════════════════════════════════════════════════════════════
#  the controls
# ══════════════════════════════════════════════════════════════════════

def set_budget_mb(mb: Any) -> float:
    """Set the session budget. `0` means *no reads beyond `PROTECTED`*."""
    s = _state()
    try:
        s["budget_mb"] = max(0.0, float(mb))
    except (TypeError, ValueError):
        pass
    return s["budget_mb"]


def pin_mode(mode: Optional[str]) -> Optional[str]:
    """Hold a mode regardless of spend, or `None` to let the budget decide.

    A pin can only be *tighter* than the budget would choose on its own —
    pinning `NORMAL` past the stop threshold would be a control that quietly
    disables itself, which is worse than no control.
    """
    s = _state()
    s["pinned"] = mode if mode in MODES else None
    return s["pinned"]


def reset() -> None:
    """Start the session's accounting again. The sidebar's counter reset."""
    s = _state()
    keep_budget, keep_pin = s.get("budget_mb"), s.get("pinned")
    s.clear()
    s.update(_blank())
    s["budget_mb"], s["pinned"] = keep_budget, keep_pin


# ══════════════════════════════════════════════════════════════════════
#  the decision
# ══════════════════════════════════════════════════════════════════════

def _earned_mode(s: Dict[str, Any]) -> str:
    """What the spend alone says the mode should be."""
    budget = float(s.get("budget_mb") or 0.0)
    if budget <= 0:
        return CACHE_ONLY
    used = float(s.get("bytes", 0)) / (1024 * 1024)
    frac = used / budget
    if frac >= AUTO_STOP_AT:
        return CACHE_ONLY
    if frac >= AUTO_FRUGAL_AT:
        return FRUGAL
    return NORMAL


def mode() -> str:
    """The mode in force: the tighter of what was pinned and what was spent."""
    s = _state()
    earned = _earned_mode(s)
    pinned = s.get("pinned")
    if pinned not in MODES:
        return earned
    return max((earned, pinned), key=MODES.index)


def allow(method: str) -> Tuple[bool, str]:
    """May this read reach Supabase, and why not.

    ⚠️ `PROTECTED` is checked **first**, before the mode and before the budget.
    That ordering is the rule at the top of this file: a trader who sets the
    budget to zero loses the learning tabs, never their signals.
    """
    if method in PROTECTED:
        return True, "decision-critical — never throttled"
    m = mode()
    if m == CACHE_ONLY:
        return False, "cache-only — the session budget is spent"
    if m == FRUGAL and method in ANALYTICS:
        return False, f"frugal — history and learning paused past "\
                      f"{AUTO_FRUGAL_AT:.0%} of the budget"
    return True, ""


def note_blocked(method: str, why: str) -> None:
    """Record a refusal so the screen can explain the blank panel.

    ⚠️ The whole reason this exists. A panel that renders empty because its
    query was refused looks exactly like a panel whose table is empty, and this
    repo has shipped that confusion before. Every refusal is named.
    """
    s = _state()
    blocked = s.setdefault("blocked", {})
    row = blocked.setdefault(method, {"count": 0, "why": why})
    row["count"] += 1
    row["why"] = why


# ══════════════════════════════════════════════════════════════════════
#  the meter
# ══════════════════════════════════════════════════════════════════════

def measure(result: Any) -> int:
    """Parsed size of one read's payload, in bytes. Never raises.

    Three shapes reach this: a DataFrame, a list of row dicts, and a scalar.
    A DataFrame is asked for its own deep memory rather than serialised —
    `to_json` on eight thousand rows every cycle would cost more than the read
    it is measuring.
    """
    if result is None:
        return 0
    try:
        usage = getattr(result, "memory_usage", None)
        if usage is not None:
            return int(usage(deep=True).sum())
    except Exception:
        pass
    try:
        import json
        return len(json.dumps(result, default=str, separators=(",", ":")))
    except Exception:
        try:
            return len(str(result))
        except Exception:
            return 0


def spend(method: str, nbytes: int) -> None:
    """Book one fetch against the budget."""
    s = _state()
    try:
        n = max(0, int(nbytes))
    except (TypeError, ValueError):
        n = 0
    s["bytes"] = int(s.get("bytes", 0)) + n
    s["reads"] = int(s.get("reads", 0)) + 1
    by = s.setdefault("by_method", {})
    row = by.setdefault(method, {"bytes": 0, "reads": 0})
    row["bytes"] += n
    row["reads"] += 1


# ══════════════════════════════════════════════════════════════════════
#  what the sidebar reads
# ══════════════════════════════════════════════════════════════════════

def state() -> Dict[str, Any]:
    """Everything the panel needs, with nothing for it to compute."""
    s = _state()
    budget = float(s.get("budget_mb") or 0.0)
    used_mb = float(s.get("bytes", 0)) / (1024 * 1024)
    return {
        "mode": mode(), "pinned": s.get("pinned"),
        "earned": _earned_mode(s),
        "budget_mb": budget, "used_mb": round(used_mb, 3),
        "used_pct": round(100 * used_mb / budget, 1) if budget > 0 else 100.0,
        "reads": int(s.get("reads", 0)),
        "blocked": dict(s.get("blocked") or {}),
        "top": top_methods(),
        "minutes": round((_time.time() - float(s.get("started") or _time.time()))
                         / 60.0, 1),
    }


def top_methods(limit: int = 5) -> List[Dict[str, Any]]:
    """The reads that actually cost, biggest first — where to look next."""
    by = (_state().get("by_method") or {})
    rows = [{"method": m, "bytes": int(v.get("bytes", 0)),
             "reads": int(v.get("reads", 0))} for m, v in by.items()]
    rows.sort(key=lambda r: -r["bytes"])
    return rows[:limit]


def human(nbytes: float) -> str:
    n = float(nbytes)
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} MB"


def summary_line() -> str:
    """One sentence: what has been spent, and what mode that has bought."""
    s = state()
    tone = {NORMAL: "🟢", FRUGAL: "🟡", CACHE_ONLY: "🔴"}[s["mode"]]
    budget = ("no budget — protected reads only" if s["budget_mb"] <= 0
              else f"{s['used_mb']:.1f} / {s['budget_mb']:.0f} MB "
                   f"({s['used_pct']:.0f}%)")
    return (f"{tone} **{s['mode']}** · {budget} over {s['reads']:,} reads"
            + (f" · {s['minutes']:.0f} min" if s["minutes"] >= 1 else ""))


def blocked_line() -> str:
    """⚠️ Which panels are blank because the budget said no.

    Empty when nothing was refused. A blocked read that goes unnamed is
    indistinguishable from an empty table, and acting on the wrong one of those
    is how a trader ends up mistrusting a working screen.
    """
    blocked = state()["blocked"]
    if not blocked:
        return ""
    top = sorted(blocked.items(), key=lambda kv: -kv[1]["count"])[:4]
    names = " · ".join(f"{m} ×{v['count']}" for m, v in top)
    why = top[0][1].get("why") or "the budget"
    more = "" if len(blocked) <= 4 else f" (+{len(blocked) - 4} more)"
    return (f"⛔ **Not fetched — {why}.** These panels are blank because the "
            f"read was refused, not because the table is empty: {names}{more}")
