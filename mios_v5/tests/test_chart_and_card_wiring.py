"""Two things reported from the running app: no Trade Card, and a 3-day chart.

Both were call-site defects in the reduced `_render_main_analyzer`, not in the
things being called.

* **The card was absent with no explanation.** `render_clean_card` opens with
  `if not mp or not spot_price: return` — correct for the card (it will not
  invent a read) and wrong for the page, because an empty slot looks exactly
  like a card that decided there was no trade. It was also nested inside
  `if underlying and option_data:`, so a failed chain fetch skipped the call
  entirely.
* **The chart drew 3 days.** `_nifty_df_live` ("chart path") and `_last_df`
  ("analysis path") are separate keys in `NIFTY_SOURCES` for exactly this
  reason, and both were being handed the same multi-day fetch.

`_today_session` is pure pandas, so it is exec'd out of the source and tested
for real rather than grepped for.
"""

import pathlib
import re

import pandas as pd
import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC = (_ROOT / "vob_minimal.py").read_text(encoding="utf-8")


def _load(func_name):
    """Exec one top-level function out of the app source.

    `vob_minimal.py` cannot be imported (it boots Streamlit and reads secrets),
    but a self-contained helper can be lifted and exercised properly. Source
    assertions cannot tell a working filter from a broken one.
    """
    import ast
    tree = ast.parse(_SRC)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == func_name)
    ns = {"pd": pd}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<app>", "exec"), ns)
    return ns[func_name]


_today_session = _load("_today_session")


def _session(day, bars=75):
    idx = pd.date_range(f"{day} 09:15", periods=bars, freq="5min",
                        tz="Asia/Kolkata")
    return pd.DataFrame({"datetime": idx, "open": 1.0, "high": 1.0,
                         "low": 1.0, "close": 1.0, "volume": 1})


# ── the chart frame ─────────────────────────────────────────────────────

def test_three_sessions_are_cut_down_to_one():
    multi = pd.concat([_session(d) for d in
                       ("2026-07-27", "2026-07-28", "2026-07-29")],
                      ignore_index=True)
    out = _today_session(multi)
    assert len(out) == 75
    assert out["datetime"].dt.date.nunique() == 1


def test_it_keeps_the_latest_session_not_the_first():
    multi = pd.concat([_session("2026-07-27"), _session("2026-07-29")],
                      ignore_index=True)
    out = _today_session(multi)
    assert str(out["datetime"].iloc[0].date()) == "2026-07-29"


def test_a_single_session_passes_through_untouched():
    one = _session("2026-07-29")
    assert len(_today_session(one)) == len(one)


def test_today_is_the_last_bars_date_not_the_wall_clock():
    """Before the open, and on a holiday, the newest bars belong to the previous
    session. Anchoring on `datetime.now()` would return an empty frame and blank
    the chart — indistinguishable from a data outage."""
    stale = _session("2020-01-02")          # long past, definitely not "today"
    out = _today_session(stale)
    assert len(out) == len(stale), "a past-dated frame must still draw"


def test_it_never_returns_an_empty_frame_from_a_non_empty_one():
    for day in ("2026-07-29", "2019-06-03"):
        assert len(_today_session(_session(day))) > 0


def test_it_degrades_to_the_input_rather_than_raising():
    """Too much history is a smaller problem than no chart."""
    assert _today_session(None) is None
    assert len(_today_session(pd.DataFrame())) == 0
    assert len(_today_session(pd.DataFrame({"a": [1, 2]}))) == 2


# ── the two frames stay separate ────────────────────────────────────────

def test_the_chart_frame_is_filtered_and_the_analysis_frame_is_not():
    """Truncating the FETCH would break Stage 3 market memory (previous-session
    H/L/C), `build_htf_profiles` (weekly/monthly need multiple days) and
    `compute_dual_profile`'s COMPOSITE profile (~5 sessions by definition).
    Only the chart frame may be cut."""
    assert "st.session_state['_nifty_df_live'] = _today_session(df)" in _SRC
    assert re.search(r"st\.session_state\['_last_df'\] = df\b", _SRC), \
        "the analysis frame must keep its full history"


def test_the_chart_path_key_is_the_one_the_terminal_reads_first():
    """`NIFTY_SOURCES` is ordered — filtering a key the chart never reaches
    would change nothing on screen."""
    runner = (_ROOT / "mios_v5" / "runner.py").read_text(encoding="utf-8")
    order = re.findall(r'\("(_[a-z0-9_]+)",', runner[runner.index("NIFTY_SOURCES"):])
    assert order[0] == "_nifty_df_live", f"chart path is no longer first: {order}"


def test_the_atm_legs_are_already_today_only():
    """`_leg_intraday` filters each leg to the last bar's date, so the option
    panels never showed the extra days and must not be double-filtered."""
    body = _SRC[_SRC.index("def _leg_intraday("):]
    body = body[:body.index("\ndef ")]
    assert "frame['datetime'].dt.date == today" in body


# ── the Trade Card call site ────────────────────────────────────────────

def _card_block():
    start = _SRC.index("# 🎯 The Trade Card")
    return _SRC[start:start + 2200]


def test_the_card_is_not_nested_behind_the_chain_fetch():
    """Nested inside `if underlying and option_data:`, a Dhan 502 skipped the
    call and the card was absent with nothing said about why."""
    block = _card_block()
    assert "with _card_container:" in block
    # the container must be entered unconditionally, before any data guard
    assert block.index("with _card_container:") < block.index("if _mp_ready")


def test_a_missing_market_picture_is_reported_not_left_blank():
    """`render_clean_card` returns silently without one. An empty slot is
    indistinguishable from a card that decided there was no trade."""
    block = _card_block()
    assert "_mp_ready" in block
    assert "Trade Card** standing by" in block


def test_the_reason_distinguishes_the_three_causes():
    """"no chain", "no spot" and "Market Picture not ready yet" need different
    reactions — reporting them identically is how a stale read gets acted on."""
    block = _card_block()
    for reason in ("no option chain", "no spot price",
                   "Market Picture has not produced a read yet"):
        assert reason in block, reason


def test_the_chain_failure_reason_names_the_dhan_error():
    assert "_dhan_last_error" in _card_block()


def test_the_card_still_renders_into_its_own_slot_at_the_top():
    """The card is claimed above V6 but filled after the bias dashboard, because
    it reads what that publishes. Both halves have to stay true."""
    claim = _SRC.index("_card_container = st.container()")
    v6 = _SRC.index("_v6_container = st.container()")
    fill = _SRC.index("# 🎯 The Trade Card")
    bias = _SRC.index("render_all_bias_dashboard(underlying, df, option_data)")
    assert claim < v6, "the card must be claimed above the V6 container"
    assert bias < fill, "the card must be filled after the bias dashboard runs"


def test_the_card_body_was_not_edited():
    """It was restored verbatim on request. The wiring around it is fair game;
    the card itself is not."""
    body = _SRC[_SRC.index("def render_clean_card("):]
    body = body[:body.index("\ndef ")]
    assert "if not mp or not spot_price:" in body, \
        "the card's own guard was changed — the fix belongs at the call site"


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"chart + card wiring tests passed ({len(fns)})")
