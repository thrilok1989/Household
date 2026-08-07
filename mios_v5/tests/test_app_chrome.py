"""The app's header, footer and browser-tab title.

Chrome is the one part of a screen a trader reads without meaning to, so the
tests here are mostly about what it must NEVER say: a price it does not have, a
direction nobody reported, or a change of `+0.00` when the previous close is
unknown.
"""

import ast
import pathlib

from mios_v5.ui import app_chrome as C
from mios_v5.ui import theme as T

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "mios_v5" / "ui" / "app_chrome.py"


# ══════════════════════════════════════════════════════════════════════
#  the browser tab
# ══════════════════════════════════════════════════════════════════════

def test_the_tab_leads_with_the_price():
    """A background tab is ~20 characters wide. The number is the reason to
    look at it, so the app name is dropped once there is one."""
    title = C.tab_title(24650.3, "BULLISH")
    assert title.startswith("🟢")
    assert "24,650.30" in title
    assert C.APP_NAME not in title


def test_the_bias_reaches_the_tab_as_a_coloured_glyph():
    """A tab renders plain text — no markup, no styling, no colour. An emoji is
    the only coloured thing it can show."""
    assert C.tab_title(24650.3, "STRONG BULLISH").startswith("🟢")
    assert C.tab_title(24650.3, "BEARISH").startswith("🔴")
    assert C.tab_title(24650.3, "NEUTRAL").startswith("🟡")
    assert C.tab_title(24650.3, None).startswith("⚪")


def test_a_missing_spot_leaves_the_price_out_rather_than_printing_zero():
    assert "0.00" not in C.tab_title(None, "BULLISH")
    assert C.APP_NAME in C.tab_title(None, "BULLISH")
    assert C.tab_title(None, None) == C.APP_NAME


def test_the_title_script_targets_the_parent_document():
    """A Streamlit component renders inside an iframe; `document.title` there
    renames a frame nobody can see."""
    js = C.tab_title_script("x")
    assert "parent.document.title" in js
    assert "try" in js and "catch" in js


def test_a_quote_in_the_title_cannot_break_out_of_the_script():
    js = C.tab_title_script('a " b \\ c')
    assert '\\"' in js and "\\\\" in js


# ══════════════════════════════════════════════════════════════════════
#  the header
# ══════════════════════════════════════════════════════════════════════

def test_the_header_carries_price_change_and_both_biases():
    html = C.header_html(24650.3, 24580.0, "BULLISH", "NEUTRAL",
                         "🟢 Market open", "15:22:04 IST")
    assert "24,650.30" in html
    assert "+70.30" in html and "+0.29%" in html
    assert "V5" in html and "V6" in html
    assert "Market open" in html and "15:22:04 IST" in html


def test_the_price_is_coloured_by_the_move_and_the_bias_by_its_own_read():
    """They are different facts. A bullish read on a down day is exactly the
    disagreement worth seeing, so one colour may not stand in for the other."""
    up = C.header_html(24650.0, 24580.0, "BEARISH")
    assert T.BULL in up, "an up move is green even under a bearish read"
    assert T.BEAR in up, "…and the bearish chip is still red"
    down = C.header_html(24500.0, 24580.0)
    assert T.BEAR in down and T.BULL not in down


def test_no_previous_close_means_no_change_rather_than_a_flat_one():
    """`+0.00` says the market has not moved. Unknown is not flat."""
    html = C.header_html(24650.3, None)
    assert "24,650.30" in html
    assert "+0.00" not in html and "0.00%" not in html


def test_a_missing_spot_draws_a_dash_not_a_zero():
    html = C.header_html(None, 24580.0)
    assert "—" in html and "0.00" not in html


def test_a_bias_nobody_reported_draws_no_chip():
    """An absent engine is not a neutral one."""
    html = C.header_html(24650.3, 24580.0, v5="BULLISH", v6=None)
    assert "V5" in html and "V6" not in html
    assert "V5" not in C.header_html(24650.3, 24580.0)


def test_the_header_escapes_what_it_is_given():
    html = C.header_html(24650.3, 24580.0, market="<script>x</script>")
    assert "<script>" not in html and "&lt;script&gt;" in html


# ══════════════════════════════════════════════════════════════════════
#  the footer
# ══════════════════════════════════════════════════════════════════════

def test_the_footer_says_nothing_here_is_advice():
    """The one thing it exists to say."""
    html = C.footer_html("15:22 IST", "🟢 Market open", C.CHROME_VERSION)
    assert "Advisory only" in html
    assert "no order is placed" in html
    assert C.CHROME_VERSION in html


def test_the_footer_renders_with_nothing_to_say():
    assert C.footer_html()


# ══════════════════════════════════════════════════════════════════════
#  it computes nothing, and it cannot take the app down
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_no_engine_no_io_and_no_streamlit():
    """Every value arrives as a parameter. `streamlit` is imported inside
    `render_tab_title` only, for the component call — never at module scope,
    so the panel stays testable without a session."""
    tree = ast.parse(SRC.read_text())
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            top.add((node.module or "").split(".")[0])
    assert not (top & {"streamlit", "requests", "pandas", "numpy", "db"})


def test_the_bias_colour_comes_from_the_shared_map():
    """Not a fourth private copy of bull-is-green."""
    tree = ast.parse(SRC.read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and "theme" in (n.module or ""):
            imported |= {a.name for a in n.names}
    assert {"bias_tone", "bias_emoji"} <= imported


def test_nothing_here_raises_on_junk():
    for junk in (None, "x", [], {}, float("nan"), object()):
        C.tab_title(junk, junk)
        C.header_html(junk, junk, junk, junk, "", "")
        C.footer_html(str(junk), str(junk), str(junk))


# ══════════════════════════════════════════════════════════════════════
#  wiring
# ══════════════════════════════════════════════════════════════════════

def test_the_chrome_is_filled_after_the_cycle_not_before():
    """The header sits at the TOP and its values arrive at the BOTTOM. Written
    at the top it would show the previous cycle's price under a live
    timestamp — worse than a blank strip for the second it takes to fill.

    AST, not a text scan: the source comment explains this rule and names both
    functions, so a substring search matches the prose rather than the code.
    """
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "main")
    order = [c.func.id for c in ast.walk(fn)
             if isinstance(c, ast.Call) and getattr(c.func, "id", "") in
             ("_render_main_analyzer", "_render_app_chrome")]
    assert order == ["_render_main_analyzer", "_render_app_chrome"]


def test_the_chrome_reads_producers_rather_than_computing_anything():
    """Spot and both biases come from `_mios_market_read`, the previous close
    from `_gap_today`, the clock from `_is_market_open`. None is derived here."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_render_app_chrome")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_mios_market_read" in called
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "_is_market_open" in names
    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_gap_today" in literals


def test_the_old_static_title_is_gone():
    """`st.title` printed a name and nothing else, every cycle, above a page
    whose whole point is the number."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "main")
    titles = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
              and getattr(c.func, "attr", "") == "title"]
    assert not titles


def test_the_tab_title_uses_the_api_that_can_actually_run_a_script():
    """⚠️ Streamlit's own deprecation warning is misleading.

    `st.components.v1.html` is deprecated with a removal date already past, and
    the warning says to use `st.iframe`. But `st.iframe` takes a `src` URL and
    cannot render markup at all — following the warning literally makes the tab
    title silently stop working. The real replacement is `st.html` with
    `unsafe_allow_javascript=True`, which is the only one of the three that
    both accepts markup and lets a script run.
    """
    import inspect
    import streamlit as st
    assert "src" in inspect.signature(st.iframe).parameters, (
        "st.iframe still takes a URL — it is not a markup renderer")
    assert "unsafe_allow_javascript" in inspect.signature(st.html).parameters

    src = SRC.read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "render_tab_title")
    body = "\n".join(src.splitlines()[fn.lineno - 1:(fn.end_lineno or fn.lineno)])
    assert "unsafe_allow_javascript" in body
    assert '"iframe"' not in body and "'iframe'" not in body


def test_the_chrome_failure_is_loud_rather_than_swallowed():
    """A swallowed failure here looks exactly like the feature was never built
    — which is what it looked like, and why this test exists.

    Scoped to the handlers that guard the CHROME. `main` also has a legitimate
    silent handler: a disabled hot-path profiler sets `_prof = None` and has
    nothing to announce, and asserting over every handler in the function
    flagged that as a bug.
    """
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())

    def _guards(fn_name, needle):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == fn_name)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Try):
                continue
            calls = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
                     for c in ast.walk(node) if isinstance(c, ast.Call)}
            if needle in calls:
                yield node

    # the call site: a chrome that raises must say so
    for node in _guards("main", "_render_app_chrome"):
        spoken = {getattr(c.func, "attr", "") for h in node.handlers
                  for c in ast.walk(h) if isinstance(c, ast.Call)}
        assert spoken & {"warning", "error", "caption"}, (
            "main swallows a chrome failure silently")

    # …and the import guard inside, which used to `return` with no message
    for node in _guards("_render_app_chrome", "render_header"):
        pass
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_render_app_chrome")
    silent = [h for t in ast.walk(fn) if isinstance(t, ast.Try)
              for h in t.handlers
              if not [c for c in ast.walk(h) if isinstance(c, ast.Call)]
              and any(isinstance(x, ast.Return) for x in ast.walk(h))]
    assert not silent, "_render_app_chrome returns silently on failure"


# ══════════════════════════════════════════════════════════════════════
#  frozen in place, Word-style
# ══════════════════════════════════════════════════════════════════════

def test_the_strips_carry_the_markers_the_css_needs():
    """The CSS selects the wrapper by what it contains. Without a class on the
    strip there is nothing to select on."""
    assert C.HEADER_CLASS in C.header_html(24650.3, 24580.0)
    assert C.FOOTER_CLASS in C.footer_html("15:22", "open", "v1")


def test_the_rule_targets_the_wrapper_not_the_strip():
    """⭐ The reason this is CSS and not an inline style.

    `position: sticky` moves an element within its containing block, and
    Streamlit sizes `.element-container` to exactly the height of what it
    holds. A sticky div inside a box its own height has nowhere to travel, so
    an inline rule is accepted and does nothing — the confusing kind of broken.
    """
    css = C.chrome_css()
    assert ":has(" in css, "the wrapper can only be selected by its contents"
    assert "position: sticky" in css
    # the strip's own style must NOT try to do it alone
    assert "position:sticky" not in C.header_html(24650.3, 24580.0)
    assert "position: sticky" not in C.header_html(24650.3, 24580.0)


def test_the_header_parks_below_streamlits_own_toolbar():
    """Sticking at 0 slides it underneath."""
    assert C.HEADER_TOP not in ("0", "0px", "0rem")
    assert f"top: {C.HEADER_TOP}" in C.chrome_css()


def test_the_footer_sticks_to_the_bottom():
    assert "bottom: 0" in C.chrome_css()


def test_both_strips_are_opaque():
    """A transparent bar lets the page scroll visibly through it."""
    css = C.chrome_css()
    assert "backdrop-filter" in css
    header = C.header_html(24650.3, 24580.0)
    assert "background:" in header, "the header paints its own ground"
    assert "background: #0e1117" in css, "and so does the footer"


def test_the_footer_returns_to_the_flow_on_a_phone():
    """Two frozen strips would eat most of a short viewport."""
    css = C.chrome_css()
    assert "max-width: 640px" in css
    phone = css.split("max-width: 640px")[1]
    assert "position: static" in phone
    assert C.FOOTER_CLASS in phone and C.HEADER_CLASS not in phone


def test_the_css_is_injected_before_the_strips_are_drawn():
    """A `<style>` block after the markup still applies, but a missing one
    silently un-freezes the page — so it is asserted to run, and first."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_render_app_chrome")
    order = [getattr(c.func, "id", "") for c in ast.walk(fn)
             if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") in
             ("render_chrome_css", "render_header", "render_footer")]
    assert "render_chrome_css" in order
    assert order.index("render_chrome_css") < order.index("render_header")


def test_the_css_never_raises():
    class Boom:
        def markdown(self, *a, **k): raise RuntimeError("no")
    C.render_chrome_css(Boom())
