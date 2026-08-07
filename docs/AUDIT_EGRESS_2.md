# Audit — where the Supabase egress actually goes (round 2)

**Observed:** ~1.20 GB in the billing period, ≈0.3 GB/day. The free tier is 5 GB.

**Headline:** the read path is not the problem any more. **The writes are.**
PostgREST echoes every written row back by default, Supabase bills that echo as
egress, and **29 of 30 write methods discarded the response they were paying
for**. `save_option_chain` writes the whole chain every cycle and received a
copy of it back, all session, every session.

---

## 1 · What was already fixed, and is still fixed

The read-cache work holds up. Checking it rather than assuming:

| Check | Result |
|---|---|
| Read methods on `SupabaseDB` | 63 |
| Covered by `read_cache` | **62** |
| Uncached | 1 — `count_rows_older_than`, a retention helper that runs off the render path |
| `SupabaseDB` construction sites | 1, and it **is** wrapped (`vob_minimal.py:13988`) |

So no app read escapes the cache. That is not where 0.3 GB/day is coming from.

---

## 2 · ⭐ The writes were echoing everything

PostgREST returns the inserted/updated rows unless told otherwise. Only **two**
places in the repo said otherwise — `purge_window`'s delete and
`futures_oi_store`'s upsert, both added deliberately in earlier work.

Everything else paid for a copy of what it had just uploaded:

| Path | Frequency | What came back |
|---|---|---|
| `save_option_chain` | every cycle (~20 s) | the whole option chain |
| `save_atm_strike_data` | every cycle | ATM ladder rows |
| `save_orderbook` · `save_bid_ask_history` | every cycle | per-strike depth rows |
| `save_pcr_history` · `save_gex_history` · `save_max_pain_history` | every cycle | per-strike rows |
| `save_candles` | every bar | candle rows |
| `save_nifty_spot` | every cycle | one row |
| …19 tables in total through `_safe_upsert`, plus 10 direct inserts | | |

Nineteen of those route through one helper, so one line fixed them all:

```python
self.client.table(table_name).upsert(
    records, on_conflict=conflict_cols,
    returning=self._WRITE_RETURNING).execute()
```

The ten direct `insert_*` methods were changed the same way. **One method was
deliberately left alone** — `upsert_auto_trade` reads `.data` for the generated
id, so it genuinely needs the row back.

### Why this is the likely bulk of the bill

A single option-chain write is ~50–100 strike rows of ~20 columns. Echoed back
that is tens of kilobytes, every twenty seconds, for six and a half hours — and
the same shape repeats across `atm_strike_data`, `orderbook_data`,
`bid_ask_history`, `pcr_history`, `gex_history` and `max_pain_history`, which
are all written on the same cycle from the same chain.

Rough order of magnitude: 1,170 cycles/day × six chain-shaped tables × tens of
KB each lands in the low hundreds of MB per day — which is the size of the gap.

**This is an estimate from row shapes, not a measurement.** §6 says what to
measure to confirm it.

---

## 3 · A 15,000-row scan to produce thirty values

`get_leg_flow_days` selected `trading_day` from `leg_flow_snapshots` with
`.limit(15000)` and deduplicated in Python. The table is written many times a
minute and kept for sixty days, so the day list was rebuilt by downloading most
of the table and discarding all but one column.

PostgREST has no `DISTINCT`, so it now walks pages of 1,000 descending and stops
as soon as it has thirty distinct days — the common case exits on the first
page. Worst case is 6,000 rows; typical is 1,000, against 15,000 before.

---

## 4 · Structural findings, not yet changed

### 54 of 69 selects are `select('*')`

Every column, including wide JSON blobs, when panels read a handful of fields.
This costs on every cache **miss** — which is every app restart, when the STATIC
reads refetch in bulk (`get_engine_attribution` 8,000 rows,
`get_liquidity_telemetry` 5,000, `get_trade_events` 4,000, `get_session_log`
2,000 — ~30,800 rows).

Not changed here because narrowing a column list is a per-call-site decision:
each one needs its consumers checked, and getting it wrong renders a blank
field rather than a slow one. It is the next-largest win after the writes.

### 17 selects have no `.limit()`

Most are bounded by a `trading_day` filter and are fine. Two are worth a look:

- `get_leg_flow_snapshots` — unbounded `select('*')` for a whole day, on a
  **5-minute** TTL. A busy day's snapshots refetched 78 times a day.
- `get_my_analysis` — unbounded, but the table is tiny.

### The always-on processes

| Process | Verdict |
|---|---|
| `discord_bot.py` | ✅ **Efficient.** Polls every 15 s with a six-column select and `id > last_id`, so it returns nothing when idle. Not a contributor. |
| `ws_worker.py` | ⚠️ Upserts `dhan_ticks` every 1.5 s and **echoed every row**. Tick-driven, so it is quiet outside market hours. Volume scales with `WATCH_INSTRUMENTS`, which is set by environment — one instrument is negligible, twenty is not. Fixed the same way. |
| `seller_perspective.py` · `auto_option_trader.py` | Create their own clients but are not imported by the app and there is no `pages/` directory, so neither runs in the deployed process. `seller_perspective.py` contains **zero** `.select(` calls. |

---

## 5 · What was checked and found clean

Recorded so the next round does not re-audit it:

- every read is cache-wrapped (§1)
- the cache's TTL buckets are sensible: LIVE 20 s for position questions,
  INTRADAY 5 min for tables that grow during the session, STATIC otherwise
- empty results are not cached, so a slow first write does not blank a tab
  until restart
- write-invalidation is explicit per method rather than a blanket clear
- `discord_bot.py`'s poll is already minimal

---

## 6 · What still needs measuring, not guessing

The write-echo estimate is derived from row shapes. To confirm it and rank
what is left:

1. **Instrument the client** — record response bytes per method per cycle, the
   same shape as `tools/hotpath_profiler.py`. That turns "probably the chain
   writes" into a number.
2. **Read Supabase's own per-day egress breakdown by type** (Database vs
   Storage vs Auth). If a material share is Storage or Realtime, none of this
   audit touches it.
3. **Then** narrow the `select('*')` list, worst first.

Until (1) exists, the honest statement is: the writes were provably paying for
an echo nobody read, that echo was proportional to the largest and most frequent
writes in the system, and it is now off. Whether that closes the whole gap is
measurable, and has not been measured.
