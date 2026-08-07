"""The app's own header, footer and browser-tab title.

Pure presentation. Spot, the biases and the market clock all arrive as
parameters — this file decides where they sit and what colour they are, and
computes nothing.

## This is not the V6 header

`header_panel.py` draws the tile strip *inside* the MIOS V6 dashboard: eight
engine readings for one screen. This draws the strip *above the whole app*, and
it carries exactly three things — where price is, what the two engines think,
and whether the market is open. A trader on the commodity tab or the news tab
can still see those; that is the entire reason it exists.

Deliberately narrow. If it grew a fourth and fifth reading it would become a
second V6 header rendered twice on the V6 tab, which is the duplication the
repo has been removing all week.

## Colour in a browser tab is one emoji

A tab renders plain text. There is no styling, no markup and no colour — so the
bias travels as 🟢 / 🔴 / ⚪, which is the only coloured glyph a tab can show.
The header carries the real colour, because it can.

## Why the title needs JavaScript

`st.set_page_config(page_title=…)` must be the first Streamlit call of the
script and may only run **once**, so it can never carry a live price: at the
moment it runs, the cycle has not fetched anything. The tab title is therefore
set by assigning `parent.document.title` from a zero-height component, which is
the only way to change it after the page exists.

## Nothing is invented

A spot that has not arrived leaves the price out of the title rather than
printing a zero, and a bias nobody reported is `⚪` — the neutral glyph, not a
guess at a direction.
"""

from __future__ import annotations

import html as _html
from typing import Any, Optional

from .theme import (BEAR, BULL, FAINT, GRID, INK, MICRO, MUTED, PANEL_BG,
                    bias_emoji, bias_tone)

UNKNOWN = "UNKNOWN"

#: The app's name, in one place. The `st.title` it replaces hard-coded it.
APP_NAME = "Nifty Trading & Options Analyzer"

#: Shown in the footer so a screenshot says which build produced it.
CHROME_VERSION = "chrome.1"


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _txt(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.upper() in ("", UNKNOWN, "NONE") else s


def _esc(v) -> str:
    return _html.escape(_txt(v))


# ══════════════════════════════════════════════════════════════════════
#  the browser tab
# ══════════════════════════════════════════════════════════════════════

def tab_title(spot: Any = None, bias: Any = None,
              name: str = APP_NAME) -> str:
    """`🟢 24,650.30 · NIFTY` — price first, because that is what a glance at a
    background tab is for.

    The app name comes last and is dropped entirely once there is a price: a
    tab is ~20 characters wide, and a name that pushes the number out of view
    defeats the point of putting it there.
    """
    px = _num(spot)
    emoji = bias_emoji(bias)
    if px is None:
        return f"{emoji} {name}" if _txt(bias) else name
    return f"{emoji} {px:,.2f} · NIFTY"


def tab_title_script(title: str) -> str:
    """The zero-height component that applies it.

    `parent.document` because a Streamlit component renders inside an iframe;
    setting `document.title` here would rename the iframe nobody can see.
    Wrapped in a try so a browser that refuses the cross-frame write leaves the
    page working rather than throwing on every rerun.
    """
    safe = title.replace("\\", "\\\\").replace('"', '\\"')
    return (f'<script>try{{parent.document.title="{safe}";}}'
            f'catch(e){{}}</script>')


def render_tab_title(st, spot: Any = None, bias: Any = None,
                     name: str = APP_NAME) -> None:
    """Set the tab title for this cycle. Never raises.

    ⚠️ `st.components.v1.html` is deprecated with a stated removal date of
    2026-06-01, already past; Streamlit 1.60.0 still ships it but prints a
    deprecation line on every rerun.

    The replacement is **`st.html(..., unsafe_allow_javascript=True)`**, not
    `st.iframe` — Streamlit's own warning points at `st.iframe`, but that takes
    a `src` URL and cannot render markup at all, so following the warning
    literally silently does nothing. `st.html` is preferred here and the
    deprecated component is the fallback, for a Streamlit old enough to lack
    the flag.
    """
    markup = tab_title_script(tab_title(spot, bias, name))
    render = getattr(st, "html", None)
    if callable(render):
        try:
            render(markup, unsafe_allow_javascript=True)
            return
        except Exception:
            pass
    try:
        from streamlit.components.v1 import html as _component
        _component(markup, height=0)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  the header
# ══════════════════════════════════════════════════════════════════════

def _bias_chip(label: str, value: Any) -> str:
    v = _txt(value)
    tone = bias_tone(v, FAINT)
    shown = v or "—"
    return (f"<span style='display:inline-flex;align-items:center;gap:4px;"
            f"background:{PANEL_BG};border:1px solid {GRID};border-radius:6px;"
            f"padding:2px 7px;white-space:nowrap'>"
            f"<span style='font-size:8.5px;letter-spacing:.09em;color:{MICRO};"
            f"text-transform:uppercase'>{_esc(label)}</span>"
            f"<span style='font-size:11.5px;font-weight:800;color:{tone}'>"
            f"{bias_emoji(v)} {_esc(shown)}</span></span>")


def header_html(spot: Any = None, prev_close: Any = None,
                v5: Any = None, v6: Any = None,
                market: str = "", updated: str = "",
                name: str = APP_NAME) -> str:
    """The strip above every tab.

    `prev_close` is what the change is measured against. Absent, no change is
    shown — a move of unknown size is not a flat one, and `+0.00` would say the
    market had not moved.
    """
    px = _num(spot)
    prev = _num(prev_close)

    if px is None:
        price = (f"<span style='font-size:20px;font-weight:800;color:{FAINT}'>"
                 f"—</span>")
    else:
        change = None if prev is None or prev == 0 else px - prev
        tone = INK if change is None else BULL if change >= 0 else BEAR
        price = (f"<span style='font-size:20px;font-weight:800;color:{tone};"
                 f"line-height:1'>{px:,.2f}</span>")
        if change is not None:
            price += (f"<span style='font-size:11px;font-weight:700;"
                      f"color:{tone};margin-left:5px'>"
                      f"{change:+,.2f} ({change / prev * 100:+.2f}%)</span>")

    right = "".join(x for x in (
        _bias_chip("V5", v5) if _txt(v5) else "",
        _bias_chip("V6", v6) if _txt(v6) else "") if x)

    meta = " · ".join(x for x in (_esc(market), _esc(updated)) if x)

    return (
        f"<div style='background:{PANEL_BG};border:1px solid {GRID};"
        f"border-radius:10px;padding:8px 12px;margin-bottom:10px;"
        f"display:flex;align-items:center;gap:12px;flex-wrap:wrap'>"
        f"<div style='min-width:0'>"
        f"<div style='font-size:9px;letter-spacing:.12em;color:{MICRO};"
        f"text-transform:uppercase;white-space:nowrap'>📈 {_esc(name)}</div>"
        f"<div style='margin-top:1px;white-space:nowrap'>{price}</div></div>"
        f"<div style='display:flex;gap:6px;flex-wrap:wrap;margin-left:auto'>"
        f"{right}</div>"
        + (f"<div style='font-size:9.5px;color:{MICRO};white-space:nowrap'>"
           f"{meta}</div>" if meta else "")
        + "</div>")


def render_header(st, slot: Any = None, spot: Any = None,
                  prev_close: Any = None, v5: Any = None, v6: Any = None,
                  market: str = "", updated: str = "",
                  name: str = APP_NAME) -> None:
    """Draw the header into `slot`, or inline when there is none.

    A slot exists because the header sits at the TOP of the page and its values
    arrive at the BOTTOM of the cycle. Writing it directly at the top would show
    the previous cycle's price under a live timestamp, which is worse than a
    blank strip for the second it takes to fill.
    """
    try:
        target = slot if slot is not None else st
        target.markdown(
            header_html(spot, prev_close, v5, v6, market, updated, name),
            unsafe_allow_html=True)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  the footer
# ══════════════════════════════════════════════════════════════════════

def footer_html(updated: str = "", market: str = "",
                version: str = "", notes: Any = None) -> str:
    """The closing strip. Small, quiet, and it says the one thing that matters
    legally and practically: **nothing here is advice, and nothing auto-trades
    from this screen.**"""
    bits = [x for x in (_esc(version), _esc(market), _esc(updated)) if x]
    for n in (notes or []):
        t = _esc(n)
        if t:
            bits.append(t)
    line = " · ".join(bits)
    return (
        f"<div style='margin-top:14px;padding:8px 12px;border-top:1px solid "
        f"{GRID};display:flex;gap:10px;flex-wrap:wrap;align-items:baseline'>"
        f"<span style='font-size:9.5px;color:{MUTED}'>"
        f"⚠️ Advisory only — every reading on this screen is an observation, "
        f"not a recommendation, and no order is placed from here.</span>"
        + (f"<span style='font-size:9px;color:{MICRO};margin-left:auto;"
           f"white-space:nowrap'>{line}</span>" if line else "")
        + "</div>")


def render_footer(st, updated: str = "", market: str = "",
                  version: str = "", notes: Any = None) -> None:
    """Draw it. Never raises — a footer may not take the app down."""
    try:
        st.markdown(footer_html(updated, market, version, notes),
                    unsafe_allow_html=True)
    except Exception:
        pass
