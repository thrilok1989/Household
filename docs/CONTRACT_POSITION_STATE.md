# Open contract: `open_position` and `zone_extremes`

**Status: unresolved on purpose. Do not wire by shape.**

`mios_v5/engines/stage52_decision.py` consumes two raw inputs that have **no
authoritative app-level producer**:

```python
extremes = raw.get("zone_extremes") or []     # line 74
position = raw.get("open_position") or {}     # line 118
d = decide(proof=proof, position=position, …) # line 119
```

Nothing anywhere in the app writes either key. So `decide()` runs every cycle
with `position={}` and `extremes=[]` — **Stage 52 always decides as though the
book is flat.**

## Why this is not a wiring bug to be patched

`_entry_signal_open` exists and is tempting. It is **per-leg entry state**, not
position-level state, and the two are not semantically equivalent:

| | holds |
|---|---|
| `_entry_signal_open` | per-leg entry signals, keyed by leg tag |
| `open_position` | the position-level state `decide()` reasons about |

Adapting the per-leg dict to whatever `decide()` happens to accept would be
**inventing semantics for a trading decision**. The pipeline would go green and
the strategy's behaviour would change based on a guess. That is strictly worse
than the current honest gap: right now Stage 52 is consistently wrong in one
known direction (always flat), which is auditable. A shape-matched adapter would
make it inconsistently wrong in an unknown direction.

Leaving a decision input unresolved is safer than silently changing what the
strategy does.

## What the next change should be

A **contract-definition task**, not an implementation guess:

1. Read `stage52_decision.decide()` and enumerate exactly which fields of
   `position` it reads, and what each one changes about the outcome.
2. Find what the position lifecycle already means elsewhere in MIOS —
   `trade_lifecycle.py`, `entry_engine.py`, the dispatcher — and whether one of
   those is already the de-facto owner.
3. Only then write the producer.

`open_position` will probably need something along these lines — **but do not add
these fields because they look reasonable.** Derive them from what `decide()`
actually uses:

```
open_position
├── is_open
├── side              # CALL / PUT / LONG / SHORT — per actual engine semantics
├── strike
├── entry_price
├── entry_time
├── quantity
└── source / signal_id   # only if stage52 needs provenance
```

### `zone_extremes` needs the same treatment, and first a definition

It could mean at least four materially different trading inputs:

* current market **liquidity** extremes;
* **S/R zone** extremes;
* **entry-zone** boundaries;
* extremes **captured at entry**.

Those are not interchangeable. Establish which one `decide()` is reasoning about
before producing anything.

## Guard

`mios_v5/tests/test_screen_order.py::test_every_raw_key_an_engine_reads_is_published_or_listed`
keeps both keys on an explicit `KNOWN_UNPUBLISHED` list with this reason
attached, and a companion test fails if either becomes published — so closing the
gap forces this document to be revisited rather than leaving a stale excuse
behind.
