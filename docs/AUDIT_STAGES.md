# Stage audit — are all 47 stages working, reporting, and consumed correctly?

Prompted by: *"in many places the app says some stages are not reporting."*

Method: run the **real** orchestrator against a session-state fixture built from
shapes verified against `vob_minimal.py`, then read every engine's status. Then
run the **real** cockpit collectors and see which display blocks stay silent.
Then derive producer/consumer graphs from the AST for both `session_state` and
`raw`.

---

## 1 · The engines themselves are healthy

All 47 engine classes are defined **and** registered — `ALL_ENGINES` matches the
class list exactly, nothing orphaned either way.

With correctly-shaped inputs:

| status | count | stages |
|---|---|---|
| **OK** | 40 | 00 02 04 05 06 11 12 13 14 17 18 19 20 21 22 23 24 25 27 28 29 30 31 33 34 35 36 37 38 39 44 45 47 48 51 52 53 54 68 69 |
| **NEUTRAL** | 6 | 03 memory · 26 patterns · 40 learning · 42 acceptance · 43 absorption · 50 ltp_behaviour |
| **DISABLED** | 1 | 15 microstructure |
| **ERROR** | 0 | — |

The 6 NEUTRALs are honest warm-up states, not faults: `03` needs a previous
session, `50` needs enough LTP history to read intent, `43` depends on `50`,
`40` needs a DB handle, `26` found no pattern, `42` needs canonical S/R. `15` is
DISABLED by design — Level-2 depth does not exist at retail.

### ⚠️ A methodology warning worth recording

My **first** run showed 5 stages in ERROR (`04`, `17`, `35`, `36`, `45`). Four of
those were **my fixture's shapes, not the app's**:

| I assumed | the app really publishes |
|---|---|
| `oi_pin` = `{"strike":…}` | **tuple** `(strike, note)` — `vob_minimal.py:7387` |
| `sup` / `res` = list of zones | **dict** for the single chosen zone — `:7336`, `:7345` |
| `_full_market_read` = `{"bias":…}` | 20+ keys incl. `call_mode`, `breakout` — `:10602` |
| `_leg_bias_cache` = `{}` | **tuple** `(rows, overall)` — `:9088` |

An audit fixture that does not match production shapes manufactures bugs. Every
finding below was re-verified against the real producer before being called a
bug.

---

## 2 · Fixed: the cockpits ran before their producer

**This is the answer to "some stages are not reporting".** The captions say
*stages*, but they list **display blocks that returned empty HTML**.

`st.tabs()` returns containers fillable in any order — the strip's layout comes
from `_TABS` and is unaffected by fill order. But the bodies have a real
dependency:

```
_charts_screen    writes  _leg_profiles
_trading_screen   reads   _leg_profiles
                  writes  _sr_levels · _premium_energy
                          _premium_structures · _entry_decision
_nifty_cockpit    reads   _sr_levels · _entry_decision
_options_cockpit  reads   _premium_energy · _premium_structures
```

The three new cockpits were moved to the **front** of the strip. Their producer
was not. Filled in tab order, four keys were read before they were written:

| key | read by (tab) | written by (tab) |
|---|---|---|
| `_sr_levels` | `_nifty_cockpit` (1) | `_trading_screen` (4) |
| `_entry_decision` | `_nifty_cockpit` (1) | `_trading_screen` (4) |
| `_premium_energy` | `_options_cockpit` (2) | `_trading_screen` (4) |
| `_premium_structures` | `_options_cockpit` (2) | `_trading_screen` (4) |

Consequences:

* **first render of a session** — the keys did not exist, the blocks drew
  nothing, and the tab printed `⚪ Not reporting yet: sr table` /
  `premium energy · premium structure · option flow`;
* **every render after** — they silently showed the **previous cycle's** data,
  one 20-second cycle behind the panels beside them. That is the worse failure,
  because it looks like it is working.

**Fix:** fill order is now `charts → trading → cockpits → …`. Nothing is
recomputed, no engine is touched, and `_TABS` is unchanged, so the strip looks
exactly as before.

### Verified end to end, not just by the graph

Running the real collectors against a fixture built from verified production
shapes:

```
BEFORE (cockpits filled first — the old order)
  NIFTY  : ⚪ Not reporting yet: sr table
  OPTIONS: ⚪ Not reporting yet: premium energy · premium structure · option flow

AFTER (charts → trading → cockpits)
  NIFTY  : ✅ all blocks rendered
  OPTIONS: ✅ all blocks rendered
           _sr_levels · _premium_energy · _premium_structures
           · _entry_decision · _leg_profiles   all published
```

Two blocks needed fixture corrections before this was trustworthy, and both are
worth recording because they are the same class of mismatch as the bug itself:

* `_reaction_sr` zones carry **`price`**, not `level` — `card_from_zone` returns
  `None` without it (`sr_intel.py:328`), so `sr_table` stayed empty;
* the strike picker reads `_cockpit_ctx` (`{sids, seg, api, atm, gap}`,
  `vob_minimal.py:13960`), without which `_strike_validation` never publishes
  `_premium_structures`.

### ⚠️ The bug was documented as expected behaviour

Three comments described this lag as normal, and one was also factually wrong:

| where | said | actually |
|---|---|---|
| `_nifty_cockpit` docstring | `_sr_levels` is published by `_sr_intelligence`, "which runs on the **Intelligence** tab" | `_sr_intelligence` is called by **`_trading_screen`** |
| same | "Reordering the tabs to fix that would move a CRITICAL producer" | no tab has to move — only the **fill** sequence |
| `_options_cockpit` docstring | "on the first rerun of a session the structure and flow blocks are empty and **fill on the next**" | that is the bug, recorded as accepted |
| `_TABS` comment | "Streamlit executes tab bodies **in order**" | it executes them when their container is **filled** |

All four corrected. A note that says "this is expected" beside code where it is
not is how the same bug comes back.

### One cycle remains, and it is genuine

There is a **cycle**: `_charts_screen` writes `_leg_profiles` (trading needs it
first) but also reads `_premium_structures` (trading writes it). Both cannot be
first. `_leg_profiles` wins because `_trading_screen`'s whole execution chain is
built on the leg reads, whereas `_premium_structures` reaches `_charts_screen`
only via `_leg_levels`, where it adds **optional** overlay lines (S/R, VWAP,
entry, stop) that are already `or {}`-guarded — one cycle of lag moves a marker
rather than blanking a panel.

Recorded as `KNOWN_CYCLE` in `mios_v5/tests/test_screen_order.py`, with a test
asserting the list neither grows silently nor goes stale.

---

## 3 · Fixed: one `None` took all of Stage 45 down

`htf_vpfr.migration_summary` (line 299):

```python
((reads or {}).get(t) or {}).get("migration", {}).get("direction")
```

`tf_read` stores `"migration": migration` verbatim and its parameter **defaults
to `None`** — so a timeframe whose migration was never computed holds the key
with a `None` value. `.get(k, default)` returns that `None`, never the default,
and the chained `.get("direction")` raised `AttributeError`, taking **the whole
of Stage 45 to ERROR** — which degrades Stage 51 (validity) and Stage 68 (day
type), both of which depend on it.

The same module gets it right 57 lines earlier: `mg = (migration or {}).get(…)`.

**Fix:** `(… .get("migration") or {})`.

I scanned the rest of `mios_v5` for the same pattern and found 5 more
(`sr_intel:134`, `checklist:132`, `stage40_learning:167-169`). All five are
**safe** — `_as_scored` and `_section` always return a dict, never `None` — so
they were left alone rather than patched for symmetry.

---

## 4 · Fixed: Stage 33's gap signal had never once fired

`stage33_event_impact` tests:

```python
(raw.get("gap_today") or {}).get("type") in ("GAP-UP", "GAP-DOWN")
```

Nothing ever put `gap_today` into `raw`. The data was there the whole time —
`capture_day_open_and_gap` publishes `_gap_today` as
`{'type', 'pct', 'open', 'prev_close'}`, the exact `type` key the engine checks,
and the app header already reads it for the previous close.

**Fix:** forwarded in the runner's `raw` literal. Also forwarded
`cached_raw_chain_latest`, Stage 4's expiry fallback.

This is the same failure as the `fii_net` bug: a key read by one layer, published
under a different name (or not at all) by another, with nothing erroring.

---

## 5 · Reported, NOT fixed

### `open_position` and `zone_extremes` — Stage 52 always decides as if flat

`stage52_decision` reads both; **no key anywhere in the app holds either value**.
So `decide(position={}, …)` runs every cycle as though there is no open trade.

Not patched deliberately. `_entry_signal_open` exists but is a per-leg dict, not
the `position` shape `decide()` expects, and guessing at that contract would
change a **trading decision** to satisfy an audit. This needs a decision about
what `position` should contain.

### Test-injection keys — not bugs

`calendar_today`, `now_ist_time`, `now_ist_dt` are read but never published **by
design**: each engine computes a real default from the IST clock and the raw key
exists so a test can move it. `stage30_calendar` says so in a comment.

### Published but never read — dead inputs

`composite_profile`, `value_alignment`, `value_migration` are forwarded into
`raw` every cycle and no engine reads them. Harmless, but they are assembly work
per cycle for nothing, and they imply a consumer that was never written.

`fii_deriv` is read only by the new UI panel, not by Stage 23 — which is why that
panel labels its verdict **"STAGE 23 FLOWS (cash)"**.

---

## 6 · Guards added

`mios_v5/tests/test_screen_order.py` — derives the graphs from the AST rather
than hardcoding an order, so moving a tab, adding a block, or moving a
`session_state` write is checked on its own terms:

| test | catches |
|---|---|
| `test_no_screen_reads_a_key_a_later_screen_writes` | a consumer filled before its producer |
| `test_the_known_cycle_is_still_the_only_one_and_is_still_real` | the allowlist growing **or** going stale |
| `test_the_tab_strip_order_is_unchanged_by_the_fill_order` | the layout drifting; a tab filled twice or not at all |
| `test_every_raw_key_an_engine_reads_is_published_or_listed` | an engine reading a raw key nothing publishes |
| `test_a_timeframe_with_no_migration_does_not_take_stage_45_down` | the `None`-vs-default crash |

Reverting the fill order reproduces all four faults by name. Suite: **3066
passed, 3 skipped.**
