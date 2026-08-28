# Fetch-duplication audit — is anything fetched twice?

**Question asked:** does the app fetch the same data twice or three times,
anywhere, A to Z?

**Method:** not by reading. Every outbound HTTP call in one full render was
**measured** — `requests.post`/`get`/`Session.*` patched before `vob_minimal`
imports, each call recorded as `(method, url, sha1(url+payload))`, with mocked
responses shaped realistically enough (a 41-strike option chain, 220 1-minute
candles) that the whole downstream path actually ran. A duplicate is then not
an opinion: it is the same signature appearing more than once.

Recomputation (same answer computed twice from data already in hand) was
measured separately, by timing the real functions on a 375-bar session frame.

---

## Result

| | before | after |
|---|---|---|
| HTTP calls in one render | **9** | **5** |
| duplicated requests | **4** (all Google News) | **0** |

One real duplicate existed. It is fixed in this change. Three duplicated
*computations* were also found and measured; they are documented below and
**not** fixed here, deliberately (§4).

---

## 1 · The one duplicated fetch: Google News, 4× per render

```
4x  GET https://news.google.com/rss/search?q=nifty+OR+sensex+OR+...
```

`compute_news_bias(cadence_s=300)` has four callers — the News panel,
`compute_market_picture`, the bias dashboard, and the Live Confluence card
(added recently, which made a latent 3-caller bug a 4-caller one).

The gate was stamped **only on success**:

```python
if cached and (now_t - _last) < cadence_s:
    return cached
...
heads = fetch_news_headlines()        # ← the HTTP call
except Exception:      return cached  # ← returns WITHOUT stamping
if not heads:          return cached  # ← returns WITHOUT stamping
...
st.session_state['_news_last_fetch'] = now_t   # ← only reached on success
```

Two consequences, and the second is the bad one:

* **Cold start** — `cached` is `None`, so the `cached and …` guard fails for
  all four callers and all four fetch before the first result lands.
* **Feed unhealthy** — both failure exits skip the stamp, so the cadence gate
  never arms. Every caller refetches on every render: **4 requests per ~20s
  cycle ≈ 720/hour, aimed at an endpoint that is already failing.** A retry
  storm precisely when the remote is least able to serve it.

### The fix, and why it is the app's own existing rule

`_panel_self_fetch` — the app's other self-loading fetcher — already does this
correctly: it stamps `_ts_key` **before** calling `fetch_fn()`, so a failure
still arms the cadence. `compute_news_bias` was the one place that deviated.

The fix stamps the **attempt**, not the success, and drops the `cached and …`
guard so a cold start no longer lets all four through at once. The last good
value is still served on failure — the same "a failed fetch must not blank a
good answer" rule `get_dhan_option_chain`'s cache documents.

Pinned by `mios_v5/tests/test_news_fetch_cadence.py` (5 tests), including a
count of the call sites so a fifth caller is visible in review.

---

## 2 · Everything else that fetches — all clean

Each of these was confirmed single-fetch by the probe, by its cache, or both.

| Source | Call sites | What protects it | Verdict |
|---|---|---|---|
| `optionchain` | 2 | `_option_chain_cache`, 10s TTL + 3s inter-request gap | ✅ 1 call |
| `optionchain/expirylist` | 5 | `get_dhan_expiry_list_cached` + stale-fallback | ✅ 0–1 |
| `charts/intraday` | 7 | `_intraday_memo`, keyed on all 5 params, scoped to `_render_seq` | ✅ no dup |
| `marketfeed/ltp` | 4 | render-scoped cache + 4s floor + 1.05s quote gate | ✅ 1 call |
| `positions` (new) | 1 | `_dhan_positions_cache`, 15s TTL | ✅ 1 call |
| yfinance (sector ×11, global, VIX, commodities) | 4 | all funnel through `_fetch_yf_intraday`, `@st.cache_data(ttl=60)` | ✅ shared cache |
| FII/DII cash + derivatives | 2 | `@st.cache_data(ttl=1800)` | ✅ |
| security-id lookups | 2 | `@st.cache_data(ttl=21600)` | ✅ |
| Supabase reads | 6 distinct | `db/read_cache.py` — every read through `st.cache_data`, `LIVE_TTL=20` | ✅ (rounds 2–4) |

The two `charts/intraday` calls in the measured render are **not** a duplicate:
one is the chart frame at the user's selected interval, the other the 5-minute
frame Stage 3/4 need. Different `interval` → different data. The memo already
collapses them into one call on the day they *do* coincide (5-min selected with
days ≥ 3), which is exactly why it exists.

---

## 3 · Disproved leads

Worth recording so nobody "fixes" these later.

* **`build_final_read` called 8× per render.** Looks alarming. It is pure
  dict-assembly over engine results already in memory — 37 dict lookups, no
  I/O, no pandas. Eight calls is microseconds. Leave it.
* **Two identical wing-fetch functions** (`_leg_candles` at two sites). Byte-
  identical logic, but they share one cache dict (`_cockpit_wing_cache`), one
  budget (`_leg_fetch_budget`) and the render memo. Duplicated *code*, not a
  duplicated *fetch*.
* **Two leg caches with different TTLs** — `_opt_intraday_cache` (60s, ATM±1)
  and `_cockpit_wing_cache` (90s, ATM±2). They look like they could double-
  fetch the same leg. They cannot: the wing fetchers check `_atm_leg_dfs`
  first and return early, so the two cover disjoint strike sets.
* **`analyze_vob_volume` recomputed in the alert path** (`_notify_*`). It reads
  the cache first and only recomputes `if not zones` — a deliberate, documented
  fallback so the alert never goes silent waiting on a slow panel. Correct.
* **`compute_sector_rotation` has no cadence gate of its own** and runs its
  11-symbol loop every render. Harmless: every symbol goes through
  `_fetch_yf_intraday`'s 60s cache, so it is 11 fetches per minute, not per
  render. A gate would be tidier, not cheaper.

---

## 4 · Duplicated *computation* — found, measured, not fixed here

Three engine results are computed twice per render on the same frames. No
network cost; pure CPU.

`_publish_atm_legs` (line ~16130) computes and stores, per ATM±1 leg:

```python
for store, fn in (('_atm_leg_vob_volume',   analyze_vob_volume),
                  ('_atm_leg_sr_behavior',  classify_leg_sr_behavior)):
    st.session_state[store][name] = fn(frame, ltp)
st.session_state['_atm_leg_vidya'][name] = calculate_vidya(frame)
```

`build_leg_bias_table` then runs **later in the same render** (17037 publishes,
17087 renders the bias dashboard → `build_leg_bias_table`) and recomputes all
three unconditionally, from `_atm_leg_dfs` — the same frames — without ever
reading the store:

| line | recomputes | measured cost | × 6 legs |
|---|---|---|---|
| 10853 | `analyze_vob_volume(df_l, ltp)` | 18.4 ms | 111 ms |
| 10936 | `calculate_vidya(df_l)` | 8.7 ms | 52 ms |
| 10894 | `classify_leg_sr_behavior(df_l, ltp)` | ~15 ms | ~90 ms |

**≈250 ms of duplicated CPU per render**, ~45 s/hour at a 20s cycle. Both
`analyze_vob_volume` and `classify_leg_sr_behavior` run
`VolumeOrderBlocks(sensitivity=5).detect_blocks()` over the frame — so block
detection alone happens **four times** per leg per render (twice in
`_publish_atm_legs`, twice again here).

*(Timings: real functions, extracted by AST and run on a 375-bar synthetic 1m
frame, 20–50 repetitions each.)*

### Why it is not fixed in this change

The fix is a read-with-fallback in `build_leg_bias_table` — take the stored
value, recompute only on a miss, exactly as the alert path already does. That
is the right change, but `build_leg_bias_table` produces 19 per-signal columns
consumed by Stage 14, three alert paths and a gate check, and shipping it in
the same commit as a small safe cadence fix is how a regression gets in
unnoticed.

It should be its own change, with the store-vs-recompute equivalence pinned by
a test first. **Recommended as the next step.**

---

## 5 · Reproducing this

The probe is not committed (it needs fake credentials to get past the
credential guard, and those belong nowhere near the repo). To rebuild it:
patch `requests.post`/`get`/`Session.*` before importing `vob_minimal`, record
`(method, url, sha1(url+payload))` per call, return canned chain/candle shapes,
then drive one render with Playwright and tally the signatures. Anything
appearing more than once is a duplicate fetch.
