"""MIOS V6 — the dashboard palette.

A trading screen is read in a lit room, at a glance, under time pressure. The
original palette leaned on GitHub-dark greys (`#8fa1b3`, `#5d6b7d`) for labels,
engine attributions and every explanatory line — which is most of the words on
the screen. On a `#0d1117` card those sit around 4:1 contrast, fine for prose
and wrong for a panel a trader has to scan in two seconds.

Every muted tone was lifted one band. Nothing structural changed: the accent
colours (bull green, bear red, warning amber) are untouched, so the *meaning*
of a colour is exactly what it was — only the greys got brighter.

    INK        #ffffff   headline values, the number you came for
    BRIGHT     #edf3f9   primary text
    BODY       #dfe7f0   explanatory sentences
    MUTED      #cfd9e6   labels, secondary detail
    LABEL      #c4d0de   inline sub-labels
    MICRO      #b3c2d4   uppercase micro-labels
    ATTRIB     #9fb0c4   engine attributions ("Stage 42 Acceptance")
    FAINT      #93a5ba   the dimmest thing allowed on screen

Semantic accents, unchanged:

    BULL       #00ff88   BULL_SOFT  #17c98b
    BEAR       #ff4444   BEAR_SOFT  #ff6666
    WARN       #ffd000   ALERT      #ff9500   DANGER  #ff2d55
    INFO       #4da6ff   VIOLET     #a78bfa   MINT    #7fe8b0

Surfaces:

    CARD_BG    #0d1117   CARD_BORDER #1e2836
    PANEL_BG   #0f1622   GRID        #161b22

Panels still write hex inline — retrofitting every f-string to constants would
be a large diff for no behavioural gain. This module is the reference: new
panels should use these names, and anything dimmer than `FAINT` does not belong
on a screen someone trades from.
"""

from __future__ import annotations

INK = "#ffffff"
BRIGHT = "#edf3f9"
BODY = "#dfe7f0"
MUTED = "#cfd9e6"
LABEL = "#c4d0de"
MICRO = "#b3c2d4"
ATTRIB = "#9fb0c4"
FAINT = "#93a5ba"

BULL, BULL_SOFT = "#00ff88", "#17c98b"
BEAR, BEAR_SOFT = "#ff4444", "#ff6666"
WARN, ALERT, DANGER = "#ffd000", "#ff9500", "#ff2d55"
INFO, VIOLET, MINT = "#4da6ff", "#a78bfa", "#7fe8b0"

CARD_BG, CARD_BORDER = "#0d1117", "#1e2836"
PANEL_BG, GRID = "#0f1622", "#161b22"

#: the greys this replaced, so a stray one is recognisable in review
RETIRED = ("#4d5b6d", "#5d6b7d", "#66788c", "#7f8ea3", "#8fa1b3", "#aeb9c7")


# ══════════════════════════════════════════════════════════════════════
#  the shared maps — one meaning, one colour
# ══════════════════════════════════════════════════════════════════════
#
# Seven panels defined their own bias map and three defined their own grade
# map. Bull and bear agreed everywhere; **neutral did not** — it was `MUTED`
# grey in `absorption_panel` and `terminal_panel`, and `WARN` amber in the
# other five. Two panels called the same reading "nothing is happening" and
# five called it "be careful", on the same screen.
#
# `NEUTRAL` resolves to `MUTED`, not `WARN`. Five of the seven maps used amber
# and only two used grey, so this is the minority reading — chosen deliberately
# rather than by count.
#
# A neutral bias is an **absence of direction**, and this codebase is
# consistent that an absence must not look like a verdict: Stage 71.85 maps
# `Neutral` to `None` so it leaves Stage 72's denominator instead of scoring
# 50, and Stage 71.86 reports `UNKNOWN` confidence rather than a low number
# when no shape wins. `WARN` amber is the colour of *caution* — it is what
# `B`-grade quality and a `TRAIL` state wear. Painting "we have no read" in the
# same colour tells a trader something is wrong when nothing is.
#
# Cost: `family_panel`, `htf_panel`, `transition_panel`, `ltp_panel` and
# `state_panel` show a grey neutral where they showed amber.

#: bias → colour. Keys are matched case-insensitively by `bias_tone()`, because
#: half the panels wrote `BULL` and half wrote `bull`, which is how one map
#: became seven.
BIAS_TONE = {"BULL": BULL, "BEAR": BEAR, "NEUTRAL": MUTED}

#: ⚪ rather than 🟡 for the same reason the colour changed — a yellow dot is a
#: state, a white one is the absence of one.
BIAS_EMOJI = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "⚪"}

#: trade quality → colour. `dashboard.py` used `#f0b429`/`#f0455a` for B and C
#: where the other two panels used `WARN`/`ALERT`; the semantic constants win,
#: so a B on one screen is a B on every screen.
GRADE_TONE = {"A+": BULL, "A": BULL_SOFT, "B": WARN, "C": ALERT}


def bias_tone(value, default=INK) -> str:
    """A bias's colour whatever case it arrived in."""
    return BIAS_TONE.get(str(value or "").strip().upper(), default)


def bias_emoji(value, default="⚪") -> str:
    return BIAS_EMOJI.get(str(value or "").strip().upper(), default)


def grade_tone(value, default=MUTED) -> str:
    return GRADE_TONE.get(str(value or "").strip().upper(), default)
