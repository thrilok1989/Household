"""🎯 Trade watch — WAIT or EXIT for a trade YOU already took, not a fresh signal.

You declare (button click) or the app detects (a filled Dhan position) that
you are in a CALL or PUT. From there the question is not "should I enter" —
it's "the market has moved against me, do I hold or bail":

    WAIT  — hold. The engine's vote OR the level that was protecting the trade
            at entry is STILL in your favour — a pullback, not a reversal.
    EXIT  — the engine's vote AND the protecting level have BOTH turned against
            you. Get out; the direction has genuinely changed.

⚠️ **Not reversal-alone.** A trade taken on impulse (FOMO), away from any zone
the engine itself would have entered at, still gets watched — this module does
not ask how you got in, only whether the market is still capable of going your
way. `entry_gate`'s own REVERSED state asks a narrower question (is the
engine's OWN zone-entry still valid); this asks a broader one (is a trade
already open, by any route, still viable).

⚠️ **The combination, not either alone.** Judging on the engine vote alone
would exit on a single wobble; on the zone alone would hold through an engine
flip that a level hasn't caught up to yet. Both must turn before this says
EXIT — the desk's own call, not a guess.

Pure: numbers in, a decision and a message out. No app import, no session, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

#: The engine vote must cross this far opposite the trade's side to count as
#: "against" — the same threshold `entry_gate`'s own REVERSED state uses, so a
#: manually- or Dhan-detected trade reads reversal on the same terms the
#: engine's own zone-entry does.
NET_THRESHOLD = 2.0

#: Points the level must be breached by, scaled by `atm_range`, to call it
#: broken rather than tested — the same scaling `entry_gate` uses for its own
#: invalidation line (±30 for NIFTY, atm_range=100).
ZONE_OFFSET_PTS = 30.0


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def protect_level(side: Any, support: Any, resistance: Any) -> Optional[float]:
    """The S/R level protecting this trade: support under a CALL, resistance
    over a PUT. Meant to be captured ONCE, at entry, and held fixed — the same
    "arm once, don't wobble on a noisy cycle" rule `_gate_armed` uses for its
    own invalidation line."""
    if side == "CALL":
        return _f(support)
    if side == "PUT":
        return _f(resistance)
    return None


def assess(side: Any, entry_spot: Any, spot: Any, net: Any,
          protect: Any, atm_range: Any = 100.0) -> Dict[str, Any]:
    """Four states, because "checked and fine" and "could not check" are not
    the same news.

      EXIT     both the engine vote and the protecting level have turned
      WAIT     at least one of them WAS evaluated, and it is not a full reversal
      UNKNOWN  a trade is open but NEITHER input could be read
      NONE     there is no readable trade at all — no side, no entry, no spot

    ⚠️ **UNKNOWN exists because WAIT used to swallow it.** Both conditions
    failed CLOSED — `n is not None and n <= -NET_THRESHOLD` is False when the
    engine vote is missing, and the zone test is False when no level was ever
    captured — so a trade with nothing measurable produced `exit_now = False`
    and the banner said "Still yours to win, the market hasn't turned all the
    way against you yet". A green reassurance from zero evidence, indistinguish-
    able on screen from a genuine all-clear. That is the failure this repo's
    three-state rule exists to prevent, and this is the same rule applied here.

    `engine_against` / `zone_against` are now **True / False / None**, where
    `None` means NOT EVALUATED — so the panel can print "not evaluated" against
    that condition instead of an unearned tick.

      engine_against : net has crossed `NET_THRESHOLD` points opposite this
                       side's direction (CALL wants net up, PUT wants net down)
      zone_against   : spot has closed beyond `protect` by the atm_range-scaled
                       offset — the level that was holding has broken, not just
                       been tested

    The reported `net`, `protect` and `breach_at` travel with the verdict so the
    banner can show the reader what the decision was actually made on.
    """
    e, sp, n = _f(entry_spot), _f(spot), _f(net)
    ar = _f(atm_range) or 100.0
    if side not in ("CALL", "PUT") or e is None or sp is None:
        return {"signal": "NONE", "engine_against": None, "zone_against": None,
                "net": n, "protect": _f(protect), "breach_at": None,
                "checked": 0}
    pr = _f(protect)
    offset = (ar / 100.0) * ZONE_OFFSET_PTS
    # ⚠️ `None` when the input is absent, NOT False. False means "checked, and
    # it is on your side"; None means nobody looked. Collapsing the two is
    # exactly what made an unevaluated trade read as a healthy one.
    if side == "CALL":
        engine_against = None if n is None else n <= -NET_THRESHOLD
        breach_at = None if pr is None else pr - offset
        zone_against = None if pr is None else sp <= breach_at
    else:
        engine_against = None if n is None else n >= NET_THRESHOLD
        breach_at = None if pr is None else pr + offset
        zone_against = None if pr is None else sp >= breach_at
    checked = sum(1 for v in (engine_against, zone_against) if v is not None)
    if checked == 0:
        signal = "UNKNOWN"
    elif engine_against is True and zone_against is True:
        signal = "EXIT"
    else:
        signal = "WAIT"
    return {
        "signal": signal,
        "engine_against": engine_against,
        "zone_against": zone_against,
        "net": n, "protect": pr, "breach_at": breach_at,
        "checked": checked,
    }


def message(side: Any, info: Dict[str, Any], entry_spot: Any, spot: Any,
           source: str = "manual") -> str:
    """The banner/Telegram text for the current signal. HTML-safe plain text —
    no markup beyond `<b>`, matching the other Telegram senders in this app."""
    e, sp = _f(entry_spot), _f(spot)
    gain = None
    if e is not None and sp is not None:
        gain = (sp - e) if side == "CALL" else (e - sp)
    e_s = "—" if e is None else f"₹{e:,.1f}"
    sp_s = "—" if sp is None else f"₹{sp:,.1f}"
    g_s = "" if gain is None else f" ({gain:+.1f} pts)"
    tag = " · from Dhan" if source == "dhan" else ""
    signal = info.get("signal")
    if signal == "EXIT":
        return (
            f"🚨 <b>EXIT FAST — direction changed against your {side}</b>\n"
            f"Entry {e_s} → now {sp_s}{g_s}{tag}. Engine vote AND the "
            f"protecting level are both against you now."
        )
    if signal == "UNKNOWN":
        # ⚠️ Never the green wording here. Nothing was measurable, and saying
        # "still yours to win" would be reassurance this has not earned.
        return (
            f"⚪ <b>NOT EVALUATED — your {side} is not being judged</b>\n"
            f"Entry {e_s} → now {sp_s}{g_s}{tag}. Neither the engine vote nor a "
            f"protecting level is available, so this is NOT an all-clear — "
            f"nothing has been checked."
        )
    return (
        f"⏳ <b>WAIT — hold your {side}</b>\n"
        f"Entry {e_s} → now {sp_s}{g_s}{tag}. Still yours to win — "
        f"the market hasn't turned all the way against you yet."
    )


def find_open_nifty_option(positions: Any, underlying_prefix: str = "NIFTY"
                            ) -> Optional[Dict[str, Any]]:
    """The first open (LONG, netQty>0) NIFTY option position in Dhan's own
    `/v2/positions` shape, or `None`. Reads exactly the fields Dhan documents
    for an option position — `tradingSymbol`, `positionType`, `netQty`,
    `drvOptionType`, `securityId` — and nothing else; a malformed or
    unexpected row is skipped, not raised on.
    """
    for p in (positions or ()):
        if not isinstance(p, dict):
            continue
        sym = str(p.get("tradingSymbol") or "")
        if not sym.startswith(underlying_prefix):
            continue
        if str(p.get("positionType") or "").upper() != "LONG":
            continue
        qty = _f(p.get("netQty"))
        if qty is None or qty <= 0:
            continue
        side_raw = str(p.get("drvOptionType") or "").upper()
        side = ("CALL" if side_raw in ("CALL", "CE")
               else "PUT" if side_raw in ("PUT", "PE") else None)
        if side is None:
            continue
        return {"side": side, "security_id": p.get("securityId"),
               "trading_symbol": sym, "qty": qty}
    return None
