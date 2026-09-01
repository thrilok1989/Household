"""🧭 The Market Alignment Checklist — one table, one question.

*Where is SPOT now, which levels and forces are active, and does each of them
agree with BULL or BEAR?*

## Not an engine, and the distinction is the whole design

Every value in this table is computed somewhere else and read here: the regime,
the news/global/sector scores and the OI walls from `compute_market_picture`;
support, resistance, the war zone and the LTP behaviour from `build_final_read`;
the pivots and POC from `_leg_profiles`; the per-leg S/R from
`_atm_leg_sr_behavior`. **This module calculates no market fact.** It answers
one presentational question the app has never answered in one place: *given a
level someone else found, what is spot doing at it, and which way does that
point?*

Two things it does own, and only these:

  1. `interaction` — spot against a level: holding, reclaimed, testing,
     rejecting, breaking, far. Arithmetic on two numbers and a tolerance.
  2. `level_alignment` — that interaction turned into a NIFTY bias, **through
     `bias_ball`**, which is the single owner of "which way does this fact point
     for NIFTY" including the PUT-inversion rule. Nothing here re-derives it.

## The one rule this module adds

`bias_ball.leg_level_bias` says what a level MEANS (NIFTY support → bull). It
does not say whether the level is currently doing its job. So:

    the level is DOING its job   → bias_ball's answer
    the level is FAILING         → the opposite
    nobody can tell yet          → neutral

Support holds → bull; support breaks → bear. Resistance rejects → bear;
resistance is reclaimed → bull. One rule, stated once, applied to every level
row — instead of four branches that drift apart.

## Three states, never two

A check with no data is `NA` — reported as "not available" and counted
separately. It is never folded into neutral, and never silently dropped: a
checklist that quietly omits what it could not read is a checklist that
overstates its own coverage.

Pure: values in, rows out. No streamlit, no app import, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from . import bias_ball as _bb

BULL, BEAR, NEUTRAL = _bb.BULL, _bb.BEAR, _bb.NEUTRAL

#: A check that could not be read. NOT neutral — "I looked and it is balanced"
#: and "I could not look" are different facts, and the summary counts them apart.
NA = "na"

#: The four sections of the table, in the order the desk asked for them.
GROUPS = ("GENERAL CONTEXT", "NIFTY STRUCTURE", "OPTION PREMIUM / LTP",
          "FINAL INTERACTION")

#: Which summary bucket each row rolls up into. The desk's own five.
FAMILIES = ("GLOBAL", "STRUCTURE", "DEALERS", "OPTIONS", "FLOW")

#: interaction key → (icon, words). One table so a verb cannot be spelled two
#: ways on two rows.
INTERACTIONS: Dict[str, Any] = {
    "holding":   ("🟢", "Holding above"),
    "reclaimed": ("🟢", "Reclaimed"),
    "testing":   ("🟡", "Testing"),
    "rejecting": ("🔴", "Rejecting"),
    "breaking":  ("🔴", "Breaking below"),
    "inside":    ("🟣", "Inside"),
    "magnet":    ("🧲", "Pulled toward"),
    "far":       ("⚪", "Far from"),
    "na":        ("❓", "not available"),
}

#: Interactions that mean the level is DOING its job, and those that mean it has
#: FAILED. Anything else (testing, far) is undecided and reads neutral.
_INTACT = {"support": "holding", "resistance": "rejecting"}
_FAILED = {"support": "breaking", "resistance": "reclaimed"}

#: How close spot must be to count as testing the level, and how far before the
#: level stops being relevant at all. Points at atm_range=100, scaled with it —
#: the same scaling `trade_watch` uses for its own invalidation line, so one
#: instrument's "near" is not another's.
NEAR_PTS = 15.0
FAR_MULT = 8.0


def _f(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def interaction(spot: Any, level: Any, role: str = "support",
                prev: Any = None, atm_range: Any = 100.0) -> Dict[str, Any]:
    """What spot is doing at one level: `{key, icon, words, text, distance}`.

    `prev` is the previous close, and it is what makes RECLAIMED and BREAKING
    distinguishable from merely being above or below — a level crossed since the
    last bar is a different event from one that has been below spot all session.
    Without it the row still works; it just never reports a cross.

    ⚠️ FAR is a real answer. A level eight tolerance-bands away is not
    "holding" in any useful sense, and colouring it green would put a tick
    against a level nobody is trading near.
    """
    sp, lv = _f(spot), _f(level)
    if sp is None or lv is None:
        return {"key": "na", "icon": INTERACTIONS["na"][0],
                "words": INTERACTIONS["na"][1], "text": "—", "distance": None}
    ar = _f(atm_range) or 100.0
    near = (ar / 100.0) * NEAR_PTS
    dist = sp - lv
    pv = _f(prev)
    role = (role or "support").lower()

    if pv is not None and pv <= lv < sp:
        key = "reclaimed"
    elif pv is not None and pv >= lv > sp:
        key = "breaking"
    elif abs(dist) <= near:
        key = "testing"
    elif abs(dist) > near * FAR_MULT:
        key = "far"
    elif dist > 0:
        # above the level: a support is holding, a resistance has been cleared
        key = "holding" if role == "support" else "reclaimed"
    else:
        # below it: a resistance is rejecting, a support has given way
        key = "rejecting" if role == "resistance" else "breaking"

    icon, words = INTERACTIONS[key]
    return {"key": key, "icon": icon, "words": words,
            "text": f"{icon} {words} ₹{lv:,.0f}", "distance": dist}


def level_alignment(chart: Optional[str], role: Optional[str],
                    inter_key: Optional[str]) -> str:
    """One level's interaction → a NIFTY bias, through `bias_ball`.

    ⚠️ `bias_ball.leg_level_bias` owns what the level MEANS — including that a
    PUT's own support is NIFTY-bearish. This only asks whether the level is
    doing its job, and flips that answer when it is not. Re-deriving the leg
    rule here would be a second opinion about the same fact.
    """
    r = (role or "").lower()
    base = _bb.leg_level_bias(chart, r)
    if base not in (BULL, BEAR):
        return NEUTRAL
    if inter_key == _INTACT.get(r):
        return base
    if inter_key == _FAILED.get(r):
        return BEAR if base == BULL else BULL
    return NEUTRAL


def label_bias(label: Any) -> Optional[str]:
    """A plain "Bullish"/"Bearish" label → NIFTY bias, via `bias_ball`.

    `None` when there is no label at all, so the row reads ❓ rather than being
    counted as a neutral vote nobody cast. `bias_ball.direction_bias` returns
    NEUTRAL for both "unrecognised" and "genuinely neutral"; only this layer
    knows the difference, because only this layer knows whether a value arrived.
    """
    if label in (None, ""):
        return None
    return _bb.direction_bias(label)


def row(group: str, check: str, value: Any = None, position: Any = None,
        align: Optional[str] = None, remark: str = "",
        family: Optional[str] = None,
        reference: bool = False) -> Dict[str, Any]:
    """One checklist line. `align=None` means the check could not be read.

    ⚠️ `reference=True` marks a row that is CONTEXT, not a check — the spot
    price itself is the obvious one. It shows in the table with a `—` in the
    alignment column and is excluded from every count, because it votes for
    nothing. Counting it as "not available" would inflate the unreadable tally
    with a row that was never a question.
    """
    ok = align in (BULL, BEAR, NEUTRAL)
    return {
        "group": group, "check": check,
        "value": "—" if value in (None, "") else str(value),
        "position": "—" if position in (None, "") else str(position),
        "align": (align if ok else NA) if not reference else None,
        "ball": ("" if reference else (_bb.ball(align) if ok else "❓")),
        "remark": remark or "",
        "family": family or "STRUCTURE",
        "reference": bool(reference),
    }


def level_row(group: str, check: str, level: Any, spot: Any, role: str,
              chart: str = "NIFTY", prev: Any = None, atm_range: Any = 100.0,
              remark: str = "", family: str = "STRUCTURE") -> Dict[str, Any]:
    """A level row, assembled from `interaction` + `level_alignment`.

    ⚠️ Both come from the same interaction, so the words and the ball can never
    disagree — the failure mode where a row reads "Breaking below" beside a
    green tick.
    """
    inter = interaction(spot, level, role, prev, atm_range)
    if inter["key"] == "na":
        return row(group, check, None, None, None,
                   remark or "no level published", family)
    align = level_alignment(chart, role, inter["key"])
    lv = _f(level)
    return row(group, check, f"₹{lv:,.0f}" if lv is not None else None,
               inter["text"], align, remark, family)


def levels_row(group: str, check: str, levels: Sequence[Any], spot: Any,
               role: str, chart: str = "NIFTY", prev: Any = None,
               atm_range: Any = 100.0, remark: str = "",
               family: str = "STRUCTURE") -> Dict[str, Any]:
    """Several levels of one kind on one line — the desk asked for HVP highs and
    lows shown side by side rather than one row each.

    The NEAREST level drives the interaction and the alignment: it is the one
    price is actually trading against. The others are listed for context, which
    is what "show multiple levels side by side" was asking for.
    """
    vals = [v for v in (_f(x) for x in (levels or ())) if v is not None]
    sp = _f(spot)
    if not vals or sp is None:
        return row(group, check, None, None, None,
                   remark or "none published", family)
    vals = sorted(set(vals))
    nearest = min(vals, key=lambda v: abs(v - sp))
    inter = interaction(sp, nearest, role, prev, atm_range)
    align = level_alignment(chart, role, inter["key"])
    shown = " · ".join(f"₹{v:,.0f}" for v in vals[:4])
    tail = "" if len(vals) <= 4 else f" +{len(vals) - 4}"
    note = remark or f"nearest ₹{nearest:,.0f}"
    return row(group, check, shown + tail, inter["text"], align, note, family)


def score_row(group: str, check: str, label: Any, score: Any,
              threshold: float = 1.0, remark: str = "",
              family: str = "GLOBAL") -> Dict[str, Any]:
    """A signed-score check (news, global, sector, ΔOI …).

    ⚠️ Below the threshold is NEUTRAL, not "slightly bull". Every score surface
    in this app uses a threshold for exactly that reason, and a checklist that
    counted a +0.2 as an aligned vote would manufacture agreement out of noise.
    """
    s = _f(score)
    if s is None:
        return row(group, check, label, None, None,
                   remark or "not reporting", family)
    align = BULL if s >= threshold else BEAR if s <= -threshold else NEUTRAL
    return row(group, check, label if label else f"{s:+.1f}", None, align,
               remark or f"score {s:+.1f}", family)


# ── the summary ─────────────────────────────────────────────────────────

def _verdict(bull: int, bear: int) -> str:
    if bull > bear:
        return BULL
    if bear > bull:
        return BEAR
    return NEUTRAL


def summarise(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Counts, a verdict per family, the net, and where they disagree.

    ⚠️ `active` counts only checks that could be READ — NA rows are reported
    separately and excluded from the denominator. "14 of 28" where three were
    never available is a different claim from "14 of 25", and the honest one is
    the second.

    ⚠️ Ties are NEUTRAL, including 0-0. The same rule `live_confluence` follows,
    so the two cards cannot disagree about what "even" means.
    """
    counts = {BULL: 0, BEAR: 0, NEUTRAL: 0, NA: 0}
    fams: Dict[str, Dict[str, int]] = {}
    for r in rows or ():
        if (r or {}).get("reference"):
            continue        # context, not a check — see `row`
        a = (r or {}).get("align")
        a = a if a in counts else NA
        counts[a] += 1
        fam = str((r or {}).get("family") or "STRUCTURE")
        d = fams.setdefault(fam, {BULL: 0, BEAR: 0, NEUTRAL: 0, NA: 0})
        d[a] += 1

    family_verdicts = {f: _verdict(d[BULL], d[BEAR]) for f, d in fams.items()}
    net = _verdict(counts[BULL], counts[BEAR])
    active = counts[BULL] + counts[BEAR] + counts[NEUTRAL]
    agree = counts[BULL] if net == BULL else counts[BEAR] if net == BEAR else 0

    # ⚠️ The conflict is NAMED, not just counted. A checklist that says
    # "BEARISH, 14 of 25" and hides that the dealer magnet is pulling the other
    # way is the overconfident read this table exists to replace.
    conflicts = []
    if net in (BULL, BEAR):
        against = BEAR if net == BULL else BULL
        for f, v in family_verdicts.items():
            if v == against:
                conflicts.append(f)
    return {
        "counts": counts, "families": family_verdicts, "net": net,
        "active": active, "agree": agree, "conflicts": conflicts,
        "total": sum(counts.values()),
    }


def why(rows: Sequence[Mapping[str, Any]], net: Optional[str],
        limit: int = 3) -> List[str]:
    """The checks that carried the verdict, in table order — the "WHY" line.

    Only rows that align WITH the net read, because a reason list that mixed in
    the opposing evidence would not be a reason for anything.
    """
    if net not in (BULL, BEAR):
        return []
    out = []
    for r in rows or ():
        if (r or {}).get("align") != net:
            continue
        pos = str(r.get("position") or "").strip()
        out.append(f"{r.get('check')}: {pos}" if pos and pos != "—"
                   else f"{r.get('check')}: {r.get('value')}")
        if len(out) >= limit:
            break
    return out
