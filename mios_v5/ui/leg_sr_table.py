"""The option legs' S/R read, as a table BELOW the charts.

`classify_leg_sr_behavior` classifies each leg's own VOB structure against its
own LTP every cycle — BREAKING / REJECTING / ACCEPTING / BUILDING — and the
chart marks the level it is about. This is the same read in numbers: which
level, how far the leg is from it, and which way the verdict points for that
leg's own premium.

Pure: reads the analysis and returns rows / HTML. No `st`, no I/O — the same
shape `price_action_table` uses for the geometric patterns beneath the same
charts.

Direction is from the LEG'S OWN perspective, which is the axis the panel above
shows. A call breaking its own resistance is bullish for that call; what that
implies for the index is a separate read and is deliberately not restated here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: state → (what it means for this leg's premium, emoji). The vocabulary is
#: `classify_leg_sr_behavior`'s, unchanged — one word means one thing on the
#: chart above and in this table.
_MEANING = {
    "BREAKING": ("Broke through — level gave way", "🟢"),
    "BUILDING": ("Building at the level", "🔵"),
    "ACCEPTING": ("Accepted above/below — holding", "🟢"),
    "REJECTING": ("Rejected — level held", "🔴"),
    "NONE": ("No level in range", "⚪"),
}

#: No parallel colour map. A state's colour is the chart's colour, taken from
#: the chart — keeping a second copy here is how ACCEPTING ended up mint on the
#: panel and plain green in the table, which made it indistinguishable from
#: BREAKING at a glance. `SR_STATE_TONE` is a plain dict and `terminal_chart`
#: imports nothing heavy at module level, so this costs nothing.
_NO_STATE_COLOUR = "#8c9bad"


def state_colour(state: Any) -> str:
    """The colour this state is drawn in on the chart above."""
    try:
        from .terminal_chart import SR_STATE_TONE
        return SR_STATE_TONE[str(state).upper()][1]
    except Exception:
        return _NO_STATE_COLOUR


CHARTS = ("CALL", "PUT")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def row_for(chart: str, sr: Optional[Mapping[str, Any]],
            ltp: Any = None, label: Any = None) -> Dict[str, Any]:
    """One leg's row: `{chart, label, state, meaning, emoji, side, level, ltp,
    distance}`.

    Always returns a row, even with nothing measured — a leg with no structure
    in range is a fact worth showing. Leaving it out would make an empty table
    look like a broken one.
    """
    state = str((sr or {}).get("state") or "NONE").strip().upper()
    if state not in _MEANING:
        state = "NONE"
    meaning, emoji = _MEANING[state]
    level = _f((sr or {}).get("level"))
    price = _f(ltp)
    distance = (price - level) if (level is not None and price is not None) else None
    return {
        "chart": chart,
        "label": str(label or chart),
        "state": state,
        "meaning": meaning,
        "emoji": emoji,
        "side": str((sr or {}).get("side") or "").lower() or None,
        "level": level,
        "ltp": price,
        "distance": distance,
    }


def rows(call_sr=None, put_sr=None, call_ltp=None, put_ltp=None,
         call_label=None, put_label=None) -> List[Dict[str, Any]]:
    """Both legs' rows, call first — the order the panels are stacked in."""
    return [
        row_for("CALL", call_sr, call_ltp, call_label),
        row_for("PUT", put_sr, put_ltp, put_label),
    ]


def _cell(text: str, colour: Optional[str] = None, align: str = "left",
          bold: bool = False, border: str = "#223") -> str:
    style = f"padding:5px 8px;border:1px solid {border};text-align:{align};"
    if colour:
        style += f"color:{colour};"
    if bold:
        style += "font-weight:700;"
    return f"<td style='{style}'>{text}</td>"


#: Table chrome per theme. The chart above follows the viewer's theme, so a
#: dark-only table underneath it would be the same mismatch in miniature —
#: a black block sitting under a white chart.
_CHROME = {
    "dark": {"head_bg": "#0e1420", "head_fg": "#ffffff", "row_bg": "#141c28",
             "row_fg": "#e8eef5", "border": "#223", "title": "#dbe4ee",
             "muted": "#8c9bad"},
    "light": {"head_bg": "#eef2f7", "head_fg": "#1c2530", "row_bg": "#ffffff",
              "row_fg": "#1c2530", "border": "#d8dee7", "title": "#2b3644",
              "muted": "#5a6b7d"},
}


def chrome(theme: Any = None) -> Dict[str, str]:
    """Table chrome for `theme`; anything unrecognised falls back to dark,
    which is what the app shipped with."""
    return _CHROME["light"] if str(theme or "dark").strip().lower() == "light" \
        else _CHROME["dark"]


def table_html(leg_rows: Sequence[Mapping[str, Any]], theme: Any = None) -> str:
    """The rows as a compact table. `""` when there is nothing to show."""
    leg_rows = list(leg_rows or [])
    if not leg_rows:
        return ""
    _t = chrome(theme)
    head = (
        f"<div style='margin:6px 0 4px;font-weight:800;color:{_t['title']};"
        f"font-size:13px;'>🧱 Option legs · S/R behaviour "
        f"<span style='font-weight:400;color:{_t['muted']};'>(each leg's own "
        f"levels, in premium)</span></div>"
        "<div style='overflow-x:auto'><table style='width:100%;"
        "border-collapse:collapse;font-size:12px;'>"
        f"<tr style='background:{_t['head_bg']};color:{_t['head_fg']};'>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:left;'>Leg</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:left;'>State</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:left;'>What it means</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:left;'>Side</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:right;'>Level</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:right;'>LTP</th>"
        f"<th style='padding:5px 8px;border:1px solid {_t['border']};text-align:right;'>Distance</th></tr>")
    body = ""
    for r in leg_rows:
        col = state_colour(r.get("state"))
        level, ltp, dist = r.get("level"), r.get("ltp"), r.get("distance")
        body += (
            f"<tr style='background:{_t['row_bg']};color:{_t['row_fg']};'>"
            + _cell(str(r.get("label") or r.get("chart")), border=_t["border"])
            + _cell(f"{r.get('emoji')} {r.get('state')}", col, bold=True,
                    border=_t["border"])
            + _cell(str(r.get("meaning") or "—"), border=_t["border"])
            + _cell(str(r.get("side") or "—"), border=_t["border"])
            + _cell("—" if level is None else f"₹{level:,.2f}", align="right",
                    border=_t["border"])
            + _cell("—" if ltp is None else f"₹{ltp:,.2f}", align="right",
                    border=_t["border"])
            # Signed on purpose: +2.10 reads as "above the level" at a glance,
            # which is the half of the answer the state word does not carry.
            + _cell("—" if dist is None else f"{dist:+,.2f}", col, align="right",
                    border=_t["border"])
            + "</tr>")
    return head + body + "</table></div>"


def build_table(call_sr=None, put_sr=None, call_ltp=None, put_ltp=None,
                call_label=None, put_label=None, theme: Any = None) -> str:
    """Convenience: rows → HTML in one call. Computes nothing beyond formatting."""
    return table_html(rows(call_sr, put_sr, call_ltp, put_ltp,
                           call_label, put_label), theme=theme)
