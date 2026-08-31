"""📤 What the running app publishes for processes that cannot see its session.

`discord_bot.py` runs standalone — a different process, possibly a different
machine. It cannot read `st.session_state`, so the only thing it can look at is
the row the app leaves in Supabase `vob_app_state`. Its `load_payload()` reads
the newest row and answers `!picture` / `!bias` / `!news` from three keys inside
that payload:

    payload['_market_picture']     → !picture
    payload['_leg_bias_summary']   → !bias
    payload['_news_bias']          → !news

⚠️ The connection this module completes had been declared but never wired. The
app defined `_PERSIST_KEYS`, the table existed (`sql/022_vob_app_state.sql`),
the bot read from it — and **nothing ever wrote a row**, so every `!picture`
answered "not available yet — is the app running?" while the app was running
perfectly. The producer wrote to session state, the consumer read from a table,
and no step joined them.

This module is the join's pure half: take a mapping of session values, make
them something JSONB will accept, and say when the next publish is due. The
writing is `SupabaseDB.save_app_state`; the scheduling is `vob_minimal`'s
`_publish_app_state`.

## Absent is not null

A key the app never set is **left out** of the payload rather than written as
`null`. The bot's fallbacks key off falsiness, so the two read the same to it —
but a payload that lists nineteen keys of which fifteen are null claims a
producer exists for each, and the next person to read the row would believe it.

Pure: values in, a dict out. No Streamlit, no Supabase, no clock of its own.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, Iterable, Mapping, Optional

#: How often the app pushes a snapshot. The bot polls every 15s and the answers
#: are minute-scale reads (a regime, a bias verdict, headlines), so a push per
#: cycle — every 20s, all session — would be paying egress for the same JSON
#: three times over. One a minute keeps `!picture` current to within the age of
#: the underlying computation.
PUBLISH_INTERVAL_S = 60.0

#: Guards a pathological structure (or a cycle) from being walked forever.
#: Nothing in `_PERSIST_KEYS` nests anywhere near this deep.
MAX_DEPTH = 8


def json_safe(value: Any, _depth: int = 0) -> Any:
    """A session value → something `json.dumps` and JSONB will both accept.

    `None` for anything that cannot be represented, rather than `str(value)`:
    a repr like `"<DataFrame object at 0x...>"` would travel all the way to a
    Discord message and read as data.

    ⚠️ NaN and ±inf become `None`. Python's `json` emits them as bare `NaN` /
    `Infinity`, which is not JSON, and Postgres rejects them — one stray NaN
    deep in a payload would fail the whole write.
    """
    if _depth > MAX_DEPTH:
        return None
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): json_safe(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v, _depth + 1) for v in value]
    # numpy scalars (`np.float64`, `np.int64`) and 0-d arrays
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return json_safe(item(), _depth + 1)
        except Exception:
            pass
    # numpy arrays and pandas Index
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return json_safe(tolist(), _depth + 1)
        except Exception:
            pass
    try:  # Decimal, and anything else that is exactly a number
        import decimal
        if isinstance(value, decimal.Decimal):
            return json_safe(float(value), _depth + 1)
    except Exception:
        pass
    return None


def snapshot(state: Optional[Mapping[str, Any]],
             keys: Iterable[str]) -> Dict[str, Any]:
    """The publishable payload: the keys `state` actually has, made JSON-safe.

    A key missing from `state` is omitted — see "Absent is not null" above. A
    key whose lookup raises is skipped too: publishing is a courtesy to another
    process and must never be able to break the cycle that runs it.
    """
    out: Dict[str, Any] = {}
    if state is None:
        return out
    for k in keys or ():
        try:
            if k not in state:
                continue
            value = state[k]
        except Exception:
            continue
        try:
            out[str(k)] = json_safe(value)
        except Exception:
            continue
    return out


def due(last_publish_ts: Any, now: float,
        interval_s: float = PUBLISH_INTERVAL_S) -> bool:
    """Is a push due? True when nothing has been pushed yet.

    Also true when the stamp is junk or in the future — a clock that jumped
    backwards should cost one extra write, not silence the bot for however long
    the jump was.
    """
    try:
        last = float(last_publish_ts)
    except (TypeError, ValueError):
        return True
    if last != last:  # NaN
        return True
    if last > now:
        return True
    return (now - last) >= float(interval_s)
