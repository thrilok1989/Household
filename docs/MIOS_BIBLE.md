# THE MIOS BIBLE

**A complete manual to this application — from the first line of the file to
the last engine in the pipeline.**

> Read this when you need to know *what a number on the screen is*, *which code
> produced it*, and *whether you are allowed to trust it*.

Scope: `vob_minimal.py` (the app, 35,843 lines), the `mios_v5/` package (V5 + V6), and the
supporting `indicators/`, `db/`, `sql/` layers.

---

## Table of contents

| Part | What it covers |
|---|---|
| [0](#part-0--how-to-read-this) | How to read this · the four generations |
| [1](#part-1--the-map) | Repo map · what every directory is for |
| [2](#part-2--the-file-vob_minimalpy) | `vob_minimal.py` from line 1 · boot sequence · regions |
| [3](#part-3--the-data-layer) | Dhan · Supabase · yfinance · the indicator owners |
| [4](#part-4--the-refresh-cycle) | What happens every 20 seconds, in order |
| [5](#part-5--generation-1-the-native-app) | Market Picture · Entry Gate · the pre-MIOS app |
| [6](#part-6--mios-v5-the-computation-layer) | The contract · the orchestrator · all 41 stages |
| [7](#part-7--mios-v6-the-intelligence-layer) | Waves 1–7 · stages 42–70 · the V6 bias · **Stage 71 matrix** |
| [8](#part-8--the-decision-engines) | Entry Gate ‖ v0 ‖ v2 · the Signal Lifecycle |
| [9](#part-9--the-dashboards) | Trade Card · D1–D6 · the Trading Terminal |
| [10](#part-10--alerts) | Telegram tiers · Discord · the allow-list |
| [11](#part-11--persistence) | Supabase tables · 30 migrations · state save/restore |
| [12](#part-12--the-laws) | The binding principles · what tests enforce |
| [13](#part-13--operating-the-app) | Running · view modes · troubleshooting |
| [14](#part-14--glossary) | Every acronym on the screen |
| [15](#part-15--known-issues) | What is currently broken |

---

# Part 0 — How to read this

## The single most important idea

This application is **four generations of software running at the same time**,
on the same data, in the same page. Nothing was deleted when the next
generation was built. That is deliberate — the project's governing rule is:

> **Every engine ships observational-only and logged. Nothing influences a
> decision until it has proven itself.** Promotion requires 2–4 weeks of live
> data. This rule outranks every other item on the roadmap.

So when you see two numbers disagree on screen, that is usually **the system
working as designed**, not a bug. The disagreement is the data that decides
which generation gets promoted.

## The four generations

| Gen | Name | Lives in | Status |
|---|---|---|---|
| **1** | The native app | `vob_minimal.py` | **LIVE** — drives real alerts |
| **2** | MIOS V5 | `mios_v5/` stages 0–41 | **LIVE** — supplies the headline bias |
| **3** | MIOS V6 | `mios_v5/` stages 37, 42–54, 68–69 | **OBSERVATIONAL** |
| **4** | Decision Engines | `decision.py` (v0), `stage52` (v2) | **OBSERVATIONAL** |

**Only Generation 1 can fire an alert or arm a trade.** Everything else
computes, displays, and logs.

## How to tell which generation a number came from

Three rules, in order:

1. **Is it on the Trade Card?** Look at the section heading — the card is split
   into `📊 MARKET FACTS`, `🧭 MIOS V5`, `🧬 MIOS V6`, `🎯 DECISIONS`.
2. **Does it have a stage number?** `≤ 41` → V5. `37, 42–54, 68–70` → V6.
   `55–67` → V6.5 explainability/learning (never a signal).
3. **Does it carry `advisory_only: True`?** Then it is observational, full stop.

---

# Part 1 — The map

```
Cash-Maerket/
├── vob_minimal.py          35,843 lines — THE APP. Streamlit entry point.
├── seller_perspective.py   394 KB — separate analysis surface
├── auto_option_trader.py   Standalone order-placement bot
├── discord_bot.py          Standalone !command bot (separate process)
├── ws_worker.py            WebSocket depth worker
│
├── mios_v5/                THE ENGINE PACKAGE (67 top-level modules)
│   ├── core/               contract.py · orchestrator.py — the framework
│   ├── horizon_owner.py    Stage 71 ownership registry (see §7.7)
│   ├── opportunity*.py     Stage 71 · 71.5 — the Trade Opportunity Matrix
│   ├── engines/            stage00…stage69 — 47 registered engines
│   ├── ui/                 40 panels incl. dashboard_v6.py, terminal_chart.py
│   ├── tests/              65 test files, 1,123 tests
│   └── *.md                SPEC_V5.0 · ROADMAP_V6 · DECISION_ENGINE · …
│
├── indicators/             THE OWNERS of raw market facts (see §3.4)
├── db/                     supabase_client.py (75 KB) + schema.sql
├── sql/                    30 numbered migrations
├── api/  analysis/  ui/  alerts/    small helper packages
└── docs/                   ARCHITECTURE_PRINCIPLES.md · audits · THIS FILE
```

## 1.1 · Which file actually runs

`vob_minimal.py`. Everything else is either imported by it, or a separate
process. Despite the name it is the **largest** file in the repo (1.87 MB).
The name is historical.

## 1.2 · `vob (5).py` — deleted, and where it went

Until recently the repo carried a second 27,347-line application file. It was
**not** a backup of `vob_minimal.py`: it shared only 61 top-level definitions,
had 113 the running app lacks (`MasterDataEngine`, `UltimateRSI`, its own
inline `SupabaseDB`, the `_bn_` / `_fae_` / `_fii_` / `_amie_` families), and
was missing 281 the running app has. Two divergent siblings, neither
superseding the other, and no way for a newcomer to tell which was real.

It has been **deleted**. Nothing imported it and no CI referenced it.

`vob_minimal.py` still carries four comments recording code ported *from* it
(around lines 3042, 4947, 6706, 30638). Those are accurate provenance — the
code did come from there — and the file itself is recoverable from git
history if a port ever needs re-checking:

```bash
git log --all --oneline -- "vob (5).py"      # find a commit that had it
git show <commit>:"vob (5).py" > /tmp/vob5.py
```

**There is now exactly one executable application in this repo.**

---

# Part 2 — The file: `vob_minimal.py`

## 2.1 · Boot sequence (what runs at import, before any UI)

Lines 1–208, in this exact order:

| Lines | What happens | Why it matters |
|---|---|---|
| 1–24 | Imports | `mios_v5` is imported here — a broken engine package breaks boot |
| 26–33 | `_mios_stamp()` | Renders IST correctly. Supabase returns UTC; appending " IST" to a UTC string made a 12:15 bar read "06:45:00 IST" |
| 35–47 | Optional imports | `yfinance`, `google.genai` behind `try` → `_HAS_YF`, `_HAS_GEMINI` |
| 49–55 | `st.set_page_config` | Must be the first Streamlit call |
| 57–63 | **Market-hours gate** | `st_autorefresh(20000ms)` fires **only** inside 08:30–15:45 IST, weekdays. Computed **at import time** |
| 65–125 | CSS | Anti-flicker rules + the `@media (max-width: 640px)` mobile block |
| 126–196 | Secrets | Dhan · Supabase · Telegram ×2 · Discord · Gemini · Anthropic · Groq |
| 198–208 | Constants | `NIFTY_UNDERLYING_SCRIP = 13` · `INSTRUMENT_CONFIGS` |

⚠️ **The refresh gate is evaluated once, at import.** A session left open
across 15:45 keeps refreshing until the page is reloaded.

## 2.2 · Region map

| Lines | Region |
|---|---|
| 211–673 | Alert plumbing — Telegram/Discord senders, allow-lists, execution-plan template |
| 675–886 | `DhanAPI` — the **only** HTTP client for broker data |
| 888–1180 | Dhan fetch helpers + `@st.cache_data` wrappers |
| 1181–2058 | Indicator classes — `PivotIndicator`, `VolumeOrderBlocks`, `TriplePOC`, `FutureSwing`, `ReversalDetector`, `compute_vpfr` |
| 2060–3174 | Options math — max pain, GEX, DEX, IV skew/rank, vanna/charm, Black-Scholes |
| 3176–4941 | Four named engines — `GeometricPatternDetector`, CIE, CMCE, IOFCE |
| 4942–6300 | Liquidity-grab / stop-hunt detection + ~15 throttled alert senders |
| 6310–7620 | Charting + `analyze_option_chain` |
| 8032–9700 | TA detectors + external-data panels (sector, commodity, global, news) |
| 9823–10945 | `generate_master_signal` + AI explanation |
| 11006–12660 | S/R proximity alerts + the S/R zone engine |
| 13188–16346 | `compute_composite_bias` → `compute_market_picture` → `render_market_picture` |
| 16347–17632 | Lite/mobile gating · decision performance · signal lifecycle |
| 17633–19536 | **Trade Card** · all-bias dashboard |
| 19537–23450 | AI advisor · leg-level engines (per-strike CE/PE) · entry decisions |
| 24851–26456 | `send_master_signal_telegram` (1,599 lines) |
| 27982–35817 | **`_render_main_analyzer`** — 7,833 lines, the whole page |
| 35818–35843 | `main()` |

## 2.3 · The four functions over 600 lines

| Lines | Function | Note |
|---|---|---|
| 7,833 | `_render_main_analyzer` | The entire page |
| 1,599 | `send_master_signal_telegram` | One Telegram message |
| 1,183 | `render_market_picture` | |
| 982 | `compute_composite_bias` | **Pure computation, no Streamlit** — the cleanest extraction candidate |

## 2.4 · `session_state` is the message bus

996 references, ~112 distinct private `_`-prefixed keys. Compute functions
stash; render functions read. The critical ones:

| Key | Written by | Read by |
|---|---|---|
| `_cached_option_data` | `analyze_option_chain` | everything downstream |
| `_last_df` | the candle fetch | MIOS, charts, all TA |
| `_market_picture` | `compute_market_picture` | Trade Card, Entry Gate, mobile view |
| `_reaction_sr` | `build_reaction_sr` | Trade Card, Cockpit, v0, D2 |
| `_mios_state` | `run_mios_pass` | every V5/V6 panel |
| `_leg_bias_cache` | `build_leg_bias_table` | D2 terminal, leg cards |
| `_money_flow_data` | `calculate_money_flow_profile` | VAL/POC/VAH everywhere |
| `_entry_gate_active` | the Entry Gate | Trade Card, Guardian |
| `_mios_decision` | `build_mios_decision_and_log` | Trade Card DECISIONS |

⚠️ **Ordering is load-bearing.** See §4.

---

# Part 3 — The data layer

## 3.1 · Dhan API v2 — `DhanAPI` (line 675)

The **only** class that talks to the broker.

| Method | Endpoint | Returns |
|---|---|---|
| `get_intraday_data` | `/charts/intraday` | OHLCV candles |
| `get_ltp_data` | `/marketfeed/ltp` | last price |
| `get_quote` | `/marketfeed/quote` | LTP + volume + OI + OHLC |
| `place_order` | `/orders` | order id |
| `get_positions` / `get_orders` | `/positions`, `/orders` | book |

**Rate-limit discipline** (`_handle_response`, line 687):

- **401** → sets `_dhan_token_expired`, shows the sidebar refresh prompt
- **429 (DH-904)** → sets `_dhan_429_until = now + 90s`. Every caller checks
  this and serves cached data instead. Notification throttled to once per 30s
- **0.3s minimum gap** between intraday calls so leg fetches don't burst
- `get_quote` falls back to `/marketfeed/ltp` on a 200-but-empty response,
  returning `{'_ltp_only': True}` so the caller knows OI/volume are missing

## 3.2 · Supabase — `db/supabase_client.py`

75 KB. Handles reads, writes, and an offline **pending queue** (`sync_pending()`
runs at the top of every cycle). See Part 11.

## 3.3 · yfinance

Global indices, commodities, sector proxies, HTF daily bars for Stage 45.
Entirely optional — guarded by `_HAS_YF`.

## 3.4 · The indicator owners ⚠️ BINDING

`docs/ARCHITECTURE_PRINCIPLES.md` names exactly one owner per market fact.
**No other module may recompute these.**

| Fact | Owner |
|---|---|
| Buy/sell split, CVD, CBV, CSV | `indicators/order_flow.py` |
| Money Flow Profile | `indicators/money_flow_profile.py::calculate_money_flow_profile` |
| Candle Delta Volume | `indicators/volume_delta.py::calculate_volume_delta` |
| VPFR | `vob_minimal.py::compute_vpfr` |
| VOB | `vob_minimal.py::analyze_vob_volume` |

`mios_v5/order_flow_snapshot.py::OWNERS` is the machine-readable version.

## 3.5 · The trust tiers ⚠️ BINDING

Every `EngineResult` carries a `Provenance.tier`:

| Tier | Meaning | Example |
|---|---|---|
| **1 — EXECUTED** | Traded prints. Cannot be faked | volume, CVD, delta |
| **2 — DERIVED** | Modeled but trustworthy | greeks, OI, profiles |
| **3 — RESTING** | Quotes / stated intent. **Spoofable** | bid/ask depth |

This is why Stage 15 (Microstructure) is **DISABLED**: iceberg and spoofing
detection need L2 depth that retail Dhan does not provide. The project's
position is that fabricating it would be worse than not having it.

## 3.6 · `MISSING` is not zero ⚠️ BINDING

```python
from indicators.order_flow import MISSING, is_missing
assert MISSING != 0      # the whole point
assert not MISSING       # falsy, so `if not x:` still guards
```

Zero is a **market fact** — perfectly balanced flow. Asserting one that was
never observed is fabricating data, and the consumer cannot tell the
difference.

---

# Part 4 — The refresh cycle

## 4.1 · What triggers it

`st_autorefresh(interval=20000)` — every 20 seconds, weekdays 08:30–15:45 IST
only. Streamlit re-runs the **entire script** top to bottom on each tick.

## 4.2 · The order, and why it is load-bearing

```
 1. restore_app_state()            ← pull composites from Supabase (once/session)
 2. maybe_play_combo_audio()
 3. top buttons · Lite/Full toggle
 4. RESERVE containers             ← _clean_card, _all_bias, _v6, _v5, …
 5. market-hours check
 6. session_state defaults
 7. SupabaseDB() + db.sync_pending()
 8. define _mios_pass()            ← DEFINED here, NOT called
 9. hydrate PCR/GEX history from Supabase
10. sidebar (timeframe, expiry, toggles)
11. DhanAPI(access_token, client_id)
12. fetch candles → publish _last_df
13. pivots · VOB · POC · swings · money flow
14. analyze_option_chain()  → publish _cached_option_data   ★
15. leg fetches (ATM±3 CE/PE) → _atm_leg_dfs, _atm_leg_vob_volume, …
16. compute_composite_bias · compute_market_picture → _market_picture
17. build_reaction_sr → _reaction_sr
18. ══ _mios_pass() ══             ← CALLED HERE   ★★
19. fill _v6_container, _v5_container (dashboards)
20. option-chain panels, charts, alerts
21. save_app_state() (throttled 300s)
```

## 4.3 · ★★ The bug this order exists to prevent

`_mios_pass()` used to be called at step 8, where it was defined. The comment
at `vob_minimal.py:28117` records what happened:

> MIOS fetches nothing of its own — it reads the caches this function fills.
> Running it at this point read every one of them from the **PREVIOUS** cycle,
> because `_cached_option_data` is not published until the chain block far
> below. That is why spot price and everything derived from it sat still while
> the foundation panels underneath were live.

The fix: define the closure early, **call it after step 17**, and render the
dashboards into containers reserved at step 4 so the page layout is unchanged.

**If you add an engine that needs a new cache, publish the cache before step
18 or your engine reads last cycle's data — silently.**

## 4.4 · What `_mios_pass()` does

```
build_htf_profiles()          Stage 45 HTF refresh (cached per bar close)
    ↓
_is_expiry_today flag         the chain is the only place that knows
    ↓
run_mios_pass(session_state, db)      ← the orchestrator, 47 engines
    ↓
log_event_impact(db, state)           Stage 33 → Supabase
    ↓
build_mios_decision_and_log(db, …)    Decision v0 → mios_decisions
    ↓
advance_explainability(state)         Stages 65/67 narration + WAIT log
    ↓
manage_signal_lifecycle(db, dec, spot)  A/A+ decisions → trade_signals
    ↓
MIOS_BRIEFINGS (OFF by default)       Evolution shifts → Discord
```

---

# Part 5 — Generation 1: the native app

This is the original application, written before MIOS existed. **It is still
the only thing that fires a live alert or arms a trade.**

## 5.1 · `compute_market_picture` (line 14399)

The native bias engine. Produces `regime` ∈ {UP, DOWN, SIDEWAYS} plus
`p_up` / `p_down` / `p_side` percentages.

**Confidence-weighted voting, not a head-count.** Each signal's magnitude
scales the points it contributes, via `_mp_conf(mag, full, floor=0.35)`:

| Weight | Signal |
|---|---|
| Full | CE↔PE alignment · leg FAST net · VWAP · ATM chain · ΔOI |
| Reduced | GEX · DEX · IV skew · global · news · commodity |

The docstring explains why: *"This stops a pile of marginal secondary signals
from outvoting the strong primary ones — which is what let the banner disagree
with the MIOS V5 conflict read."*

It also produces `entry_gate`, `liq_pools`, `oi_floor`, `oi_ceiling`, `vwap`.

## 5.2 · The Entry Gate (line 14874)

The live decision path. States:

| State | Meaning | Trade Card renders |
|---|---|---|
| `CALL` / `PUT` | Zone tested **and** reclaimed | 🟢/🔴 **ENTER** |
| `ARMED_CALL` / `ARMED_PUT` | At the zone, awaiting confirmation candle | 🟡 **GET READY** |
| `AT_ZONE_WAIT` / `CHOP_WAIT` / `NO_ROOM` / `REVERSED` | At a zone, not clean | 👀 **WATCHING** |
| `PINNED` | Magnet-locked at an OI pin | 🧲 **PINNED** |
| `WAIT` | Mid-range | ⏳ **WAIT** |

Supporting machinery: `_GatePinned`, `_snap_level_to_swing`,
`_detect_liquidity_pools`, `_candle_sweep_reclaim`, `_zone_confirmed`.

## 5.3 · The other native engines

| Function | What it does |
|---|---|
| `compute_composite_bias` (13188) | 982-line multi-factor bias — pure computation |
| `build_reaction_sr` (11945) | **The canonical S/R object** → `_reaction_sr` |
| `enrich_zone_intel` (12452) | Attaches the Zone Intelligence card (origin ★, lifecycle, health, odds) |
| `compute_full_market_read` (20130) | Per-leg normalised factor scoring |
| `generate_master_signal` (9823) | The legacy 651-line master signal |
| `analyze_strike_activity` (7669) | Capping / decapping / wall detection |
| `compute_leg_entry_decisions` (21389) | Per-strike CE/PE entry logic |
| CIE / CMCE / IOFCE (3779–4941) | Candlestick · Cross-market · Institutional order flow |

## 5.4 · The Guardian

When `_entry_gate_active` is set, `_guard_state` grades the open trade every
cycle:

| State | Trade Card |
|---|---|
| `EXIT` | ⚡ **EXIT FAST — reversal confirmed** |
| `WARNING` | ⚠️ **WATCH — sudden opposite flow** |
| `PATIENT` | 🧘 **HOLD PATIENT — normal noise, don't panic-exit** |
| — | ✅ **ON TRACK — let it work** |

The guard state is only honoured if `time.time() - _gs['ts'] <= 60` — a stale
guard reading is discarded rather than shown.

---

# Part 6 — MIOS V5: the computation layer

> **V5 computes. V6 interprets.** — the governing principle.

## 6.1 · The contract (`mios_v5/core/contract.py`)

Every engine returns the same `EngineResult`:

```python
EngineResult(
    engine, stage, status, bias, confidence,
    evidence, risks, opportunities,
    data,                    # engine-specific payload
    provenance,              # source + tier + freshness
    errors, runtime_ms,
)
```

### The enums

```python
Bias    STRONG_BULL · BULL · NEUTRAL · BEAR · STRONG_BEAR · SIDEWAYS · NONE
Status  OK · NEUTRAL · DEGRADED · ERROR · DISABLED
Severity INFO · WARNING · ERROR · CRITICAL
ErrorType MISSING_API · MISSING_DATA · FAILED_FORMULA · TIMEOUT ·
          INVALID_CALCULATION · DATA_LIMIT · STALE_DATA
Tier    1 EXECUTED · 2 DERIVED · 3 RESTING
```

`Bias.NEUTRAL` ≠ `Bias.NONE`. NEUTRAL means *balanced*; NONE means *this
engine does not produce a direction*.

### The five hard rules

1. **Never fabricate.** Cannot compute → `NEUTRAL` **with a reason**.
2. **Structured errors.** Every failure is a row in `engine_errors`.
3. **Data-limits are not alarms.** Structurally impossible → `DISABLED` +
   `DATA_LIMIT` at severity `INFO`. Never lights the monitor red.
4. **No BUY/SELL, ever.** Output is bias + confidence + evidence + risks +
   levels + invalidation. *The trader decides.*
5. **Degrade, don't vanish.** A crashing engine yields a structured `ERROR`
   result; the pipeline continues.

## 6.2 · The orchestrator

```
MarketState (shared blackboard)
      ↓
Orchestrator ── topological order ──► Engine 0 … Engine 69
      ↓                                 each → EngineResult into MarketState
RunReport ──► Stage 0 Health score
```

- **Kahn's algorithm** topo-sort, stable-sorted by `(stage, name)` so
  equal-rank engines always run in spec order
- **Cycles raise at registration time**, never silently reorder
- **Unknown deps are tolerated** — they resolve to NEUTRAL via `state.require()`
- `health_pct = (ok + 0.5×degraded) / runnable × 100` — **DISABLED engines are
  excluded from the denominator.** They are not failures

It is a **DAG, not a chain**. Stage 35 alone consumes stages 7–11, 25, 31–34.

## 6.3 · The 41 V5 stages

### Layer 1 — Foundation (0–10)

| # | Engine | Key outputs |
|---|---|---|
| 0 | System Health | health score, engine status, errors → Supabase |
| 1 | Data Collection | *folded into the host app's caches* |
| 2 | Market Structure | HH/HL/LH/LL, BOS, CHOCH, order/breaker blocks, FVG |
| 3 | Market Memory | prev day/week/month H/L/close/VWAP/POC/VAH/VAL |
| 4 | Market Context | gap type, expiry/event day, day classification |
| 5 | Market Regime | regime + strength (adapter over `_market_picture`) |
| 6 | Time Cycle | session phase (6 IST blocks) + `confidence_tempered` weight |
| 7–10 | Structure / Levels / Volume Profile / Liquidity | *folded into 2, 17 and native indicators* |

### Layer 2 — Institutional Intelligence (11–20)

| # | Engine | Key outputs |
|---|---|---|
| 11 | Dealer Position | GEX, DEX, Vanna, Charm, flip, pinning, dealer zones |
| 12 | Option Chain | PCR, build-up/unwind, CE/PE walls, ATM bias |
| 13 | Institutional Position | Long/Short Build-up, Unwinding, Covering |
| 14 | Order Flow | CVD/CBV/CSV, delta divergence, absorption |
| 15 | Microstructure | ⛔ **DISABLED** — needs L2 depth |
| 17 | Liquidity | pools + walls |
| 18 | Sector Rotation | leaders/laggards, rotation bias |
| 19 | Global | global sentiment + influence score |
| 20 | Commodity & Macro | risk-on/off, external risk score |

### Layer 3 — AI Fusion (21–30)

| # | Engine | Key outputs |
|---|---|---|
| 21 | News | keyword sentiment over NIFTY/SENSEX headlines |
| 22 | VIX | volatility environment |
| 23 | Flows | FII / DII cash |
| 24 | **Institutional Preparation** | *event-agnostic* coiling detection → the ⚠️ banner |
| 25 | Institutional Intent | smart-money direction |
| 26 | Pattern Alignment | candlestick + chart patterns |
| 27 | **Conflict Engine ⭐** | **`preferred_bias`** — the Trade Card headline |
| 28 | Event Detection | live shock reaction (surprise mirror of 24) |
| 29 | Evolution | what-changed timeline |
| 30 | Calendar | scheduled events (RBI/Fed/CPI/expiry) |

### Layer 4 — Decision Support (31–41)

| # | Engine | Key outputs |
|---|---|---|
| 31 | Probability | breakout/breakdown/bounce/reject % |
| 33 | Event Impact | did the event actually change structure? |
| 34 | Event Explanation | the "why" — **never** the signal |
| 35 | **Reaction Zone ⭐** | battle zone, expected winner, next target, stop |
| 36 | Market Story | plain-language narrative |
| 37 | Market Energy | *promoted to a first-class engine in V6 Wave 3* |
| 38 | Tomorrow Preparation | post-close plan |
| 39 | Pre-Market Update | pre-09:15 brief |
| 40 | Learning | bias-vs-actual, confidence calibration |
| 41 | Final Read | `build_final_read()` — the boundary object |

## 6.4 · Stage 27 — the Conflict Engine

**This produces the number in the Trade Card headline.** It arbitrates ~34
engines by priority × confidence:

```
Dealer > Intent > OrderFlow > Liquidity > Structure > Options > Global > Patterns
```

Output: `preferred_bias` + `confidence` + `conflict_severity`.
`confidence_tempered` applies Stage 6's session conviction weight.

## 6.5 · Stage 41 — `final_read` — the boundary object

`build_final_read(state)` collapses the pipeline into one dict. **This is the
only object V6 reads.** Its ~70 keys include:

```
preferred_bias · confidence · confidence_tempered · conflict_severity
reaction · acceptance · absorption · htf · validity · validity_both
transition · memory_read · market_state · energy_read · flow_shift · stability
families · families_read · decision_v2 · day_classification · session_intel
strong_support · strong_resistance · next_target · battle_zone · invalidation
preparation · event · event_impact · explanation · calendar · probabilities
sections · risks · opportunities · evidence · health_score
```

If you are adding a V6 feature and the data is not in `final_read`, **add it to
`final_read` first**. Reaching into `MarketState` from a V6 module violates
principle 4 (No hidden logic).

---

# Part 7 — MIOS V6: the intelligence layer

> **V6 must never become a second analytics engine.** It interprets, correlates
> and explains the canonical outputs V5 produces — it never recomputes them.

## 7.1 · Why V6 exists

From `mios_v5/v6_bias.py`:

> V5 arrives at a bias by arbitrating ~34 engines through the Conflict Engine.
> V6 was built because **that count is a lie**: CVD, Money Flow, Delta and VOB
> are the same evidence counted four times, so the V5 tally is loudest exactly
> where it is most correlated.

## 7.2 · The admission rule ⚠️ BINDING

Before any new engine is accepted:

> **Can this be merged into an existing evidence family?**
> **YES → merge it. NO → only then create an engine.**

And it must **increase accuracy · reduce false entries · improve
explainability**. If it does none of those, it does not go in.

🧊 **WAVE 3 IS FROZEN.** No new analytical engines. Any proposal must also
answer: *why can't this be a field on an existing engine?*

## 7.3 · The V6 engines

### Wave 1 — Signal Protection

| # | Engine | Deliverable |
|---|---|---|
| **44** | Sudden Flow Shift + Stability | Reads the **derivative** — CVD swing, OI velocity, gamma repricing, IV jump, volume explosion, price displacement. Owns `STABLE → UNSTABLE → SHOCK → RECOVERY`. **Non-directional** (`Bias.NONE`) — it vetoes, never leans |
| **53** | Evidence Correlation | Groups correlated evidence into **families**, collapses each to one weighted vote. **This lowers some confidences — that is the point** |

### Wave 2 — Entry Intelligence

| # | Engine | Deliverable |
|---|---|---|
| **42** | Acceptance / Rejection / Trap | True/failed breakout · bull/bear trap · liquidity sweep · acceptance · rejection. Merged because *a "failed breakout" **is** a bull trap* — two engines would disagree |
| **45** | Higher-Timeframe VPFR | 1H · 4H · Daily · Weekly · **Monthly · Yearly** VAH/VAL/POC/HVN/LVN + value migration |

### Wave 3 — Market State

| # | Engine | Deliverable |
|---|---|---|
| **37** | Market Energy | state · compression · expansion readiness · release probability |
| **43** | Institutional Absorption | buyer/seller absorption · exhaustion. **Renamed from "Hidden Liquidity"** — iceberg detection needs L2 we do not receive. *Absorption is measurable; icebergs would be fabricated* |
| **47** | Bias Transition | `Bear ↓ Weakening` / `Bull ↑ Strengthening` — extends Evolution from "it flipped" to "it's decaying" |
| **48** | Market State | Trend · Pullback · Rotation · Compression · Expansion · Range · Accumulation · Distribution · Mark Up · Mark Down |
| **50** | LTP Behaviour | "Call exhaustion", "Put building", "Selling pressure increasing" |
| **51** | Signal Validity Filter | Checks 1H/4H/Daily/Weekly agreement before any entry |
| **54** | Market Memory | How long the current state has existed. Feeds 47 and 53 |

### Wave 4 — Decision

| # | Engine | Status |
|---|---|---|
| **46** | Market Control | **not built** |
| **52** | Decision Engine v2 | `WAIT · WATCH · ENTRY READY · ENTER · SCALE IN · HOLD · TRAIL · PARTIAL EXIT · FULL EXIT · ABORT` + adaptive trail |

⚠️ **Gate:** v2 does not go live until Wave 6 shows the v0 gate stack beats the
Entry Gate. *Validate before you weight.*

### Stage 68 — Market Day Classification

📈 Trend · 🔄 Swing · ↔ Range · 🔪 Choppy · ⚡ High Volatility ·
🧲 Expiry Pin · 💥 News Event · 💤 Low Participation

**Confidence is cross-group agreement, not signal count.** Twelve signals from
one group is one opinion repeated twelve times.

**Two types are facts, not votes:** `NEWS_EVENT` (Stage 28 fired) and
`EXPIRY_PIN` (expiry + measurable charm pin) take precedence.

**Style is separate from classification** — `style_caveat` overrides the
guidance without touching the type.

### Stage 69 — Market Session Intelligence

Eight windows: Pre-Open · Opening Auction · Opening Drive · Morning Trend ·
Midday Balance · Afternoon Trend · Closing · Closed.

> ⛔ **`SESSION_AWARE = False`.** The modifiers are computed, published and
> logged every cycle — **and applied by nobody.** `modifier_for()` returns `{}`
> while the switch is off, so the gate cannot be bypassed by reading
> `applies_to`.

Two modifiers move in **opposite** directions by design: Stage 44's spike
sensitivity is ×0.6 in the Opening Drive (opening spikes are normal) and ×1.4
at Midday (a spike in a quiet tape is meaningful).

## 7.4 · The V6 bias (`mios_v5/v6_bias.py`)

### Four voters

| Weight | Voter | Stage |
|---|---|---|
| **3.0** | Evidence families (de-duplicated) | 53 |
| **2.5** | Reaction at level | 42 |
| **2.0** | HTF alignment | 45 |
| **1.5** | Institutional absorption | 43 |

Stage 42 is weighted second **on purpose**: everything else is inference about
what price *should* do; a rejection or confirmed breakdown **has already
occurred**. *Executed evidence outranks derived evidence.*

### Four modifiers — which never vote

| Stage | Effect |
|---|---|
| 47 transition | ×0.55 … ×1.10 (→ ×0.6 when it points **against** the read) |
| 54 memory | ×0.80 … ×1.05 on state maturity |
| 51 validity | **caps** confidence |
| 44 flow shift | **hard cap** — the tape changed |

Stage 47 is excluded from voting because *its bias is derived from Stage 53's
families* — letting it vote would count the family read twice and inflate
confidence precisely when families are already unanimous.

51 and 44 **cap rather than scale**, because *"a gate that merely discounted a
read would let a strong-enough score walk through a veto."*

### The arithmetic

```python
w      = WEIGHTS[key] × max(0.25, confidence/100)
ratio  = (bull_w − bear_w) / total_w
bias   = band(ratio)        # ±0.60 → STRONG, ±0.15 → directional
coverage = len(voters) / 4
conf   = |ratio| × 100 × (0.6 + 0.4 × coverage)     # ← three voters ≠ four
conf  ×= each modifier
conf   = min(conf, gates.cap)
conf   = clamp(0, 97)
if bias == NEUTRAL: conf = min(conf, 40)
```

### Divergence is the deliverable

`compare()` returns V5 and V6 side by side. `_divergence()` writes a specific
sentence per disagreement shape:

| Shape | Sentence |
|---|---|
| V5 directional, V6 flat | *"V6 sees no clean edge where V5 does — the V5 read is likely correlated evidence counted more than once."* |
| V6 directional, V5 flat | *"V6 finds a directional read V5 calls flat — usually the reaction at the level, which V5 does not weight."* |
| **Opposite** | *"treat this as a stand-aside, not as a choice between two opinions."* |

⚠️ The middle sentence names the reaction voter generically. On a card where
Stage 42 reads `Watching 0%`, reaction is **not** one of the voters (it returns
`None` with no winner) — so the explanation points at the wrong voter. Read the
voter list, not the sentence.

## 7.5 · V6.5 — Explainability (Stages 61–67)

**No new trading logic and no new engines.**

| # | Module | Deliverable |
|---|---|---|
| 61 | `explain_decision.py` | Why BUY/SELL/WAIT/EXIT. **No generic explanations** — every ✓/✗ is built *from* an engine read and carries that engine's name |
| 62 | *(same module)* | WAIT analysis. Same module because *"why did you act"* and *"why didn't you"* have the same answer shape; split, they would drift |
| 63 | `checklist.py` | Nine weighted conditions. **Three states:** ✅ met · ❌ not met · ⚪ **could not report**. Unknowns are excluded from readiness, not guessed |
| 64 | `risk_explain.py` | Entry/stop/target/trail reasoning, labelled **proven vs derived** |
| 65 | `narrator.py` | Written **on transitions only** — a narrator that prints every cycle gets ignored within a day |
| 66 | `trade_review.py` | Winners reviewed too: +50 of a +55 run and +50 of a +200 run are the same P&L and completely different work |
| 67 | `daily_summary.py` | **What MIOS refused is half the report** |

## 7.6 · Wave 6 — Learning (Stages 55–60)

| # | Module | Deliverable |
|---|---|---|
| 55 | `attribution.py` | **One row per engine per trade** — without it there is only a blended win rate that cannot say *which* engine to fix |
| 56 | `engine_accuracy.py` | **Abstention is not a vote.** Small samples labelled, not hidden (Wilson interval) |
| 57 | `calibration.py` | *"Claims 90%, delivers 52%."* Brier score |
| 58 | `threshold_opt.py` | Reports **the winners a filter would have cost** as prominently as the losers it avoids |
| 59 | `contribution.py` | **Shapley values, not correlation** — correlation rewards the redundant engine and punishes the pivotal one |
| 60 | `false_signal.py` | Names **the engine that called it right and was outvoted** |

> ⛔ **BINDING.** The Learning Engine may only **observe · measure · explain ·
> recommend · validate**. It never influences a live decision, never moves a
> threshold or weight, and never hides a poor result. Not in `ALL_ENGINES`,
> exposes no `apply`/`deploy`/`promote` — **asserted by tests**.

## 7.7 · Stage 71 · 71.5 — the Trade Opportunity Matrix

> **An orchestrator, not an engine.** It computes no market fact. 47 engines
> answer *what is happening*; the Decision Engine answers *act or wait*.
> Neither answers what a trader opens the screen with: **where is the best
> opportunity, and over what hold time?**

| File | Role |
|---|---|
| `horizon_owner.py` | The ownership registry — pure data |
| `opportunity.py` | Stage 71 — scores and ranks the five horizons |
| `opportunity_intel.py` | Stage 71.5 — what *kind* of trade each one is |
| `ui/opportunity_panel.py` | The Dashboard 2 panel |

Not in `ALL_ENGINES`, no mutators, `advisory_only` throughout — the Stage 70
standing.

### The five horizons

| Horizon | Hold | Owns |
|---|---|---|
| **Scalp** | 5–15 min | 22 producers — `fast` signals + S42/43/50 |
| **Midday** | 1–3 h | 9 — `lag` leaves + S48/69/37 + 1H |
| **Intraday** | today | 10 — S02/11/12/13/14/17/22/51/68 + 4H |
| **Positional** | days | 6 — S18/23/30 + cross-expiry + Daily/Weekly ⚠️ degraded |
| **Swing** | weeks | 5 — S03/19/20 + Monthly/Yearly — **bias + levels only** |

### The ownership registry ⚠️ BINDING

Stage 53 exists because CVD, Money Flow, Delta and VOB were the same evidence
counted four times. A multi-horizon matrix re-creates that failure one level
up — feed one CVD read into scalp *and* midday *and* intraday, and "three
horizons agree" is one signal repeated three times.

`horizon_owner.py` is the table that prevents it. **93 producers, each in
exactly one category:**

| Category | n | Votes? | Meaning |
|---|---|---|---|
| `OWNED` | 52 | ✅ once | a leaf directional read |
| `STABILITY` | 3 | ❌ | S44/47/54 — shape Stability + the veto |
| `AGGREGATE` | 15 | ❌ shown | composites; voting would re-count members |
| `EXCLUDED` | 8 | ❌ shown | `mis`-tier noise, or superseded by a stage |
| `NON_DIRECTIONAL` | 15 | ❌ hidden | infrastructure with no bias |

Producers are keyed by **immutable id**, never display name. Engines reuse
`Engine.name` — already the `MarketState.results` key, so it cannot drift from
the pipeline. Natives use `native_*` bridged to their `_BIAS_CATEGORY` label;
a rename breaks the build rather than silently orphaning an owner.

**Supersession** applies principle 1 across generations: where a native signal
and a stage measure the same fact, the stage wins and the native goes to
`EXCLUDED` — which is why `native_atm_pcr` does not vote beside
`stage12_options`.

`STABILITY` is not a new judgement. `v6_bias.py` reached it first: 44 and 54
return `Bias.NONE` by design, and 47's bias derives from Stage 53's families.
Stage 48 stays in `OWNED` because, unlike its neighbours, it has a direction.

### The score is a Wilson lower bound

```python
score = wilson(agreeing, directional).low × coverage    # .low is PERCENT
```

Pools are deliberately uneven, so raw agreement would rank on pool size:

```
same ~80% agreement, different pools
  n=22  18/22 = 81.8%  →  61.5        n= 6   5/6 = 83.3%  →  43.6
  n=10   8/10 = 80.0%  →  49.0        n= 5   4/5 = 80.0%  →  37.6
```

Note row 3 against row 1: **83.3% scores below 81.8%** once sample size
counts. Reuses Stage 56's helper and its rule that small samples are labelled,
not hidden.

⚠️ Quality and Risk multipliers were **deliberately dropped** from the score.
Neither has a universal producer — v0's quality is `None` unless ARMED or
CONFIRMED, and risk needs a stop that positional and swing lack. Defaulting a
missing term to 1.0 asserts a fact nobody measured (principle 9).

### Stage 44 vetoes per horizon, never globally

| Horizon | Effect |
|---|---|
| Scalp · Midday | **veto** — score → 0 |
| Intraday | discount ×0.80 |
| Positional · Swing | ignored |

A flow shift destroys a scalp and can *be* the swing thesis.

### Stage 71.5 — what kind of trade

Nine derived labels per row: **type · quality · lifetime · risk · maturity ·
rotation · timing · confidence breakdown · weakness.**

Governed by Stage 63's rule: **three states, not two** — a value, or `UNKNOWN`
with the reason. Never a default. `Risk: —  (dealer, session and acceptance
silent)` is honest; `Risk: LOW` computed from nothing is not, and it is more
dangerous because it looks like an answer.

- **Quality** reuses `decision.py::_grade` bands exactly (`A+ ≥4.5 · A ≥3.8 ·
  B ≥3.0 · C`) plus `AVOID`. No `B+` — a band v0 cannot express would diverge
  the vocabularies. Unknown components are **excluded**, never scored 0.
- **Lifetime** modulates the horizon's own `HOLD` band — `"5–15 min
  (shorter)"` with the reason. Never a free-floating number.
- **Timing is horizon-scoped.** Scalp/midday/intraday trigger on Stage 42's
  reaction; positional/swing trigger on Stage 45 HTF alignment. Without this,
  swing read `NOW` off a one-minute event.
- **Counter-trend marking.** The type is a market fact shared by every row, so
  a horizon leaning against it renders `Counter-trend (Breakdown)` rather than
  a contradiction.
- **Rotation** takes `previous` as a parameter and is `UNKNOWN` on cycle one.

### The panel

Header + one row per horizon always visible (~9 KB); reasoning, breakdown and
excluded list behind expanders (~33 KB). Sits at the top of the Trading tab —
the three context strips that used to precede the chart moved **below** it, so
execution stays above the fold.

## 7.8 · The Trading tab, end to end

```
Command Center            what is the market doing        (6 cards)
Trade Opportunity Matrix  where is the opportunity        (§7.7)
NIFTY ‖ ATM CALL ‖ ATM PUT   one figure, one time axis
  levels    16 overlays, incl. Gamma Flip · Dealer Wall · Charm Pin · Reaction
  legs      bar COLOUR = who was buying · violet CVD line = still accumulating?
Slim Trade Card           market facts + the V5 ‖ V6 divergence
day type · session · market ribbon
leg cards · CALL-vs-PUT ribbon
Trade Cockpit             where in the trade life are we  (Stage 52)
recommendation · S/R Intelligence · live narration
```

### Who owns what on this tab ⚠️

Two surfaces showing the same number is how a trader ends up with two answers
to one question and no way to tell which is authoritative. Dashboard 2's split:

| Surface | Owns |
|---|---|
| **Opportunity Matrix** | horizon ranking · side · quality · timing · risk · energy · rotation · stability |
| **`_sr_intelligence`** | every S/R level, as a ranked object |
| **Trade Cockpit** | where in the trade life we are (Stage 52) |
| **Slim Trade Card** | market facts (spot · VAL/POC/VAH · gap) · the V5 ‖ V6 divergence |

`ui/trade_card_panel.py` is deliberately **not** the full Trade Card. Bias,
quality and timing are absent because the Matrix owns them *per horizon*, which
is more than one blended verdict; S/R is absent because `_sr_intelligence`
renders it ranked further down; the Stage 52 row is absent because the Cockpit
owns it. Tests assert each of those absences.

It also **cannot** be the full card: `mios_v5` never imports `vob_minimal`, so
`render_clean_card` is out of reach from `mios_v5/ui/` by design. The bias
strip is `bias_compare_html` reused unchanged, so the two cards cannot drift
into disagreeing about what V6 said.

### Premium behaviour on the option panels

Stage 50 knew whether a leg was BUILDING / WRITING / SHORT COVERING / FADING
and the trader had to read a badge. The panels now answer it themselves, and
both renderings are drawings of `indicators/order_flow.py` — the single owner:

| | Answers |
|---|---|
| **bar colour** | who was buying *this minute* |
| **CVD line** | is the premium *still* being accumulated |

Bar height is still volume, so the overlay occupies the footprint it always
did. The CVD line is **scaled into the price extent** rather than given a
second axis — the layout is a rowspan grid with `matches="x"`, and a secondary
y would need adding per panel and keeping out of the shared zoom. Consequence:
**the shape is the signal and the number is meaningless**, so it is never
labelled with one.

⚠️ An unmeasured bar is **grey, not green**. A frame with no volume column
yields no flow at all rather than a balanced one.

### The Trade Cockpit — Stage 52 as a checklist

```
Getting in                    Managing it
 ✓ Waiting — no setup          ✓ Holding
 ✓ Setup identified            – Scaled in      (optional, unknowable)
 ✓ Level confirmed             ◆ Trail active
 ✓ Entry taken                 · Partial exit
                               · Exited  · Complete
```

A view over `decision_v2.STATES`. Two refusals matter:

* **A passed optional step is not ticked.** Stage 52 publishes only the
  *current* state, so at TRAIL there is no way to know whether the trade ever
  scaled in. `–` means *not on the path*; a `✓` would assert a scale-in nobody
  took.
* **ABORT is not a rung.** It arrives at any point, so "step 11 of 12" would
  read as a trade nearly done when the correct read is *stop now*. It replaces
  the ladder rather than advancing it.

A test asserts every `STATES` member is accounted for, so a new state cannot
vanish and look like a skipped rung.

⚠️ `native_reads_from_rows()` reads `_all_bias_rows`, **not** `_leg_bias_cache`
— the former carries all 38 signals with `_dir`. A label with no registered id
is skipped, not guessed.

---

# Part 8 — The decision engines

## 8.1 · Three verdicts on the same instant

| Engine | Generation | Drives alerts? | Trade Card |
|---|---|---|---|
| **Entry Gate** | 1 (native) | ✅ **YES** | ⏳ WAIT / ENTER / GET READY |
| **Decision v0** | 4 | ❌ logs only | 🎯 Decision: … · gates ✓… |
| **Decision v2** | 4 (Stage 52) | ❌ logs only | checklist strip (hidden while WAIT) |

They can disagree — most often about **where price is**, because the Entry Gate
sides spot against `_market_picture` and v0 sides it against `_reaction_sr`.
Since the Trade Card restructure they render adjacent in the DECISIONS column
so the disagreement is visible.

## 8.2 · Decision v0 — the gate stack

**A stack, not a vote.** The first six decide; the seventh grades.

| # | Gate | Question |
|---|---|---|
| 1 | **Location** | Is spot *at* a zone? (never mid-range) |
| 2 | **Direction** | Does the MIOS bias agree with the side? |
| 3 | **Zone Health** | Is the level *building*, not *fading*? |
| 4 | **Confirmation** | Candle/flow confirmation — don't chase the first touch |
| 5 | **Risk** | R:R ≥ 1.2, room to target, invalidation defined |
| 6 | **Event / Veto** | Shock · preparation · hard conflict → stand aside |
| 7 | **Quality** | ★1–5 per gate, averaged |

**Quality:** `A+ ≥ 4.5 · A ≥ 3.8 · B ≥ 3.0 · C < 3.0`.
The same direction can be an A+ or a C — *that's how experienced traders
actually think.*

**Veto conditions** (any sets `veto = True` → STAND ASIDE):
shock in progress · institutional preparation · signals conflict sharply.

### Log every rejection

A **rejection** = spot was at a zone (a trade was possible) but a gate blocked
it. Logged with the blocking gate. Without this you can never learn *"the Event
Veto prevented 73% of losing trades."*

## 8.3 · The Signal Lifecycle

```
WAIT_ENTRY ──confirmed──▶ ENTERED ──target──▶ TARGET_HIT   (win)
    │  │                    │      ──stop────▶ STOP_HIT     (loss)
    │  │                    └──eod while open▶ EXPIRED      (open)
    │  └──flip / zone lost──────────────────▶ CANCELLED
    └──45m timeout / eod────────────────────▶ EXPIRED (never_entered)
```

- Born as `SIG-YYYYMMDD-NNN` from an **A/A+ only** decision. B/C never alert
- **Only one signal alive at a time**
- The **live Entry Gate's CONFIRMED state is the entry trigger**, so the
  lifecycle cannot drift from what actually fired
- **Never-entered signals are stored** — they tell you whether the
  wait-patiently discipline is skipping losers (good) or missing winners (bad)

---

# Part 9 — The dashboards

## 9.1 · The Trade Card — four labelled parts

```
┌──────────────────── 📊 MARKET FACTS ─────────────────────┐
│  📍 spot · VAL/POC/VAH · gap · value alignment           │
└──────────────────────────────────────────────────────────┘
┌───────────────┬───────────────────┬──────────────────────┐
│ 🧭 MIOS V5    │ 🧬 MIOS V6        │ 🎯 DECISIONS         │
│ conflict-arb  │ observational     │ gate ‖ v0 ‖ v2       │
├───────────────┼───────────────────┼──────────────────────┤
│ headline bias │ V5‖V6 strip       │ Entry Gate box       │
│ Stage 24 prep │ 68 day type       │ v0 decision + gates  │
│ 28 event      │ 69 session        │ v2 line (WAIT→hidden)│
│ 30 calendar   │ zone intel ★      │ checklist ⚪❌✅      │
│ 33 impact     │ 42/43/47/48/50/51 │                      │
│ 34 explain    │ 54/37 · zone 🩺   │                      │
└───────────────┴───────────────────┴──────────────────────┘
```

Routing rule: **stage ≤ 41 → V5 · 37, 42–54, 68/69 → V6 · decision engines →
DECISIONS.**

Columns stack on phones via the existing `@media (max-width: 640px)` rule.

⚠️ The whole function is wrapped in `try: … except Exception: pass`. **If any
fragment raises, the entire card vanishes silently.**

## 9.2 · Dashboard V6 — six screens

`mios_v5/ui/dashboard_v6.py`, 1,326 lines:

| Tab | Question |
|---|---|
| 🎯 Decision | What should I do? |
| 📈 Trading | *Where is the opportunity (§7.7), then the Trading Terminal (§9.3)* |
| 🧭 Intelligence | What do the engines say? |
| 📜 History | What happened before? |
| 🎓 Learning | What is working? |
| ⏮ Replay | What did it look like at 11:04? |

## 9.3 · Dashboard 2 — the Trading Terminal

```
┌──────────────────────────┬──────────────────┐
│                          │    ATM CALL      │
│        NIFTY  (60%)      ├──────────────────┤
│                          │    ATM PUT       │
└──────────────────────────┴──────────────────┘
     Option intelligence · TRADE BANNER
```

**One figure, not three.** Streamlit columns give three independent Plotly
figures, and Plotly can only synchronise axes *within* a figure. A single
figure with `rowspan` + `matches="x"` gives the proportions **and** real
synchronised zoom/pan/crosshair.

`matches="x"` not `shared_xaxes=True` — the latter only links within a column,
and NIFTY is in a different column from the legs.

Other decisions, each preventing a named failure:

| Mechanism | Prevents |
|---|---|
| `today_slice()` | Previous-day bars squeezing today into a sliver |
| `master_timeline()` + `align()` | A leg's untraded minute sliding later candles left |
| `uirevision` keyed on zoom | Streamlit's rerun resetting the trader's zoom |
| `hoversubplots="axis"` in try/except | Old Plotly raising; degrades to per-panel hover |
| Manual per-panel y-range | Zoom moving time and nothing else |
| Buttons, not scroll-wheel | The wheel zooming when you scroll the page past it |

**The dashboard creates nothing.** Two places refuse to answer:

1. **Premium entry/stop** — the Decision Engine works in NIFTY points;
   conversion needs delta, which no engine produces. *"A delta-free conversion
   would put a confident ₹ figure on the screen that no engine stands behind."*
2. **Per-leg strength without a leg-bias row** — reported absent, not 50%

Tint requires a **≥10-point strength gap** — tinting on 51/49 reads as a signal
where there is none.

### The three-key-shape trap

The app writes per-leg caches under three different key shapes:

```
_atm_leg_dfs         → "ATM CE 24250"   (with the ATM offset prefix)
_atm_leg_vob_volume  → "CE 24250"       (leg_name, no prefix)
every store, also    → "sid_65806"
```

`_leg_store()` tries all three. Before that fix, VOB and Money Flow read "—"
on every cycle regardless of the market.

---

# Part 10 — Alerts

## 10.1 · Two gates before anything sends

```python
_msg_allowed(message)      # is this headline on the allow-list at all?
_msg_entry_tier(message)   # does it qualify for the MAIN Telegram bot?
```

## 10.2 · The Telegram tier

**Only six markers reach the main Telegram bot:**

```
FRESH ENTRY · ENTRY GATE · EXIT GATE ·
ZONE REVERSAL · REVERSAL WARNING · STAY PATIENT
```

Everything else is **Discord + Supabase only**.

## 10.3 · `RETIRE_ENTRY_ALERTS = True`

MIOS V5 is pure decision-support (locked decision #1). These classes are
suppressed **at the send layer**:

```
leg_entry · confirmed_entry · entry_result · all_aligned_entry ·
sr_confluence · fresh_entry · bias_enter ·
spot_sh_aligned · cie_aligned · sr_touch_aligned
```

The confirmed-entry **lifecycle still runs** — only the message is withheld —
so Stage 40 keeps its validation data.

## 10.4 · Channels

| Channel | Purpose |
|---|---|
| Main Telegram bot | The six entry-tier markers only |
| Alert Telegram bot | Separate high-conviction stream |
| Discord webhook | Everything on the allow-list |
| Discord bot (REST) | Direct channel post |
| `discord_bot.py` | Separate process, `!commands` |

⚠️ `MIOS_BRIEFINGS = False` — the Evolution-shift briefing channel is opt-in
and OFF by default.

## 10.5 · Throttling

`_throttled_telegram_send(msg, alert_class, key, cooldown_s=900)` — per-class,
per-key cooldowns, typically 600–1800s. Every send is logged via
`_log_sent_alert` for audit.

---

# Part 11 — Persistence

## 11.1 · Key tables

| Migration | Table | Holds |
|---|---|---|
| 005 | `alert_log` | every alert sent |
| 008 | `signal_outcomes` | Stage 40 validation |
| 009 | `engine_errors` | structured engine failures |
| 012/013 | `entry_gate_signals` / `_exits` | live gate history |
| 016/017 | `market_events` / `market_stories` | Stage 28/36 |
| 018 | `engine_state` | replay source |
| 022 | `vob_app_state` | **the mobile-view snapshot** |
| 023 | `opening_auction_log` | first-30-min behaviour |
| 024 | `event_impact_log` | Stage 33 peak per event/day |
| 025 | `mios_decisions` | **Decision v0 — every transition + rejection** |
| 026 | `trade_signals` | the Signal Lifecycle |
| 027 | `learning.sql` | **five append-only tables** (Stages 55–60) |
| 028/029/030 | `day_type_log` · `session_log` · `session_validation` | Stages 68/69/70 |

## 11.2 · Append-only ⚠️ BINDING

`sql/027_learning.sql` is **append-only**. Nothing is ever updated, so replay
and backtesting show **what was known at the time**.

## 11.3 · State save/restore

- `save_app_state()` — throttled to once per 300s, writes composites to
  `vob_app_state`
- `restore_app_state()` — once per session, so a page refresh doesn't lose
  history
- **The mobile view reads `vob_app_state` and nothing else**

---

# Part 12 — The laws

From `docs/ARCHITECTURE_PRINCIPLES.md` — *"Binding. These outrank convenience,
and they outrank 'helpful' refactors."*

| # | Principle |
|---|---|
| 1 | **Single source of truth** — every market fact has exactly one owner |
| 2 | **Never recalculate** — `calculate_cvd_v6()` etc. must never exist |
| 3 | **One calculation → many consumers** — publish once, read many |
| 4 | **No hidden logic** — engines receive inputs as **parameters**, never reach into `session_state` |
| 5 | **Engines never own indicators** — Indicator → Engine ✅, Engine → Indicator ❌ |
| 6 | **Preserve the observational rule** — no refactor changes Entry, Guardian, Decision, Alerts or Confidence |
| 7 | **Backward compatibility** — every dashboard, message, API and alert keeps working |
| 8 | **Publish everything once** — one `OrderFlowSnapshot` |
| 9 | **Fail fast** — an unmeasured fact is `MISSING`, never `0` |
| 10 | **Performance** — a refactor must *reduce* calculations. Measure before and after |
| 11 | **Deliver the audit** — every consolidation ships with a before/after count |
| 12 | **Every computed decision must be inspectable** — if an engine influences a score, recommendation, timing, risk, trail or execution state, the trader must see the engine, its inputs and its output. **Hidden influence is prohibited** |
| 13 | **Non-negotiable** — *"A year from now there must still be exactly one implementation of every piece of market logic."* |

## 12.1 · What the tests actually enforce

| Test | Fails the build on |
|---|---|
| `test_no_duplicate_order_flow_engine_exists` | any `def <indicator>_v6(` |
| `test_no_hand_written_buy_fraction_survives` | an inline buy-fraction formula in `vob_minimal.py` |
| `test_explainability_exposes_no_mutators` | `decide`/`apply`/`set_confidence`/`set_weight` on Stages 61–67 |
| `test_learning_modules_expose_no_mutators` | `apply`/`deploy`/`promote` on Stages 55–60 |
| `test_stage_70_exposes_no_mutators` | **AST walk** — any assignment to `SESSION_AWARE` from Stage 70 |
| `test_every_output_declares_itself_advisory` | a missing `advisory_only: True` |
| `test_every_producer_has_exactly_one_home` | a producer in two horizon categories |
| `test_every_engine_is_registered` | **a new engine with no declared horizon** |
| `test_every_native_label_still_exists` | a `_BIAS_CATEGORY` rename orphaning an owner |
| `test_no_aggregate_may_own_a_horizon` | a composite voting and re-counting its members |
| `test_swing_never_returns_a_side` | swing emitting a CALL/PUT |
| `test_no_panel_still_uses_a_retired_grey` | a panel below the contrast floor |

## 12.2 · Principle 12, and the bug that produced it

Stage 37 Market Energy was shaping the Opportunity Matrix's lifetime estimate
and feeding its risk drivers on **every cycle**, while the panel cell labelled
"Energy" showed the *rotation* read instead. A third thing — the bull/bear vote
bar — was also called Energy. The engine was acting on the screen and absent
from it.

Nothing was miscomputed. The trader simply could not see what was moving the
answer, which is the whole failure: **an engine you cannot see is an engine you
cannot distrust at the moment it is wrong.**

Two corollaries, because they are where this gets violated:

* **A modifier is an influence.** Multiplying a confidence by 0.8 is as much a
  decision as producing a bias, and the ×0.8 needs a visible owner.
* **Consumed-but-unpublished is the smell.** If a value is read inside a
  computation and appears in no panel, either surface it or stop reading it.

Applies to Stage 44's veto, 47/54's stability modifiers, Stage 69's session
modifiers, Stage 71's scoring, and everything after.

## 12.3 · The honest limit

> The guard tests catch the *named* failure modes. They cannot catch someone
> reimplementing CVD inline under a different variable name inside a render
> block. **That is exactly how the six copies arose in the first place.**
>
> The durable defence is principle 3: if a number is worth computing, publish
> it, and the next person will find it rather than rewrite it.

---

# Part 13 — Operating the app

## 13.1 · Running

```bash
pip install -r requirements.txt
streamlit run vob_minimal.py
```

Secrets go in `.streamlit/secrets.toml` (gitignored):

```toml
DHAN_CLIENT_ID = "..."
DHAN_ACCESS_TOKEN = "..."
TELEGRAM_BOT_TOKEN = "..."
TELEGRAM_CHAT_ID  = "..."
DISCORD_WEBHOOK_URL = "..."
[supabase]
url = "..."
anon_key = "..."
```

Run every migration in `sql/` against your Supabase project, in numeric order.

## 13.2 · The three view modes

| Mode | How | What runs |
|---|---|---|
| **Full** | default | everything |
| **Lite** | sidebar radio | curated 6-block stack. **Compute, alerts and DB writes are identical** — only display changes |
| **Mobile** | `?view=mobile` | reads `vob_app_state` from Supabase, `st.stop()`s. **No engine runs** |

Bookmark `…streamlit.app/?view=mobile` on a phone. It never touches the live
desktop engine.

## 13.3 · Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Spot frozen, panels live | An engine reading last cycle's cache | Publish the cache before step 18 (§4.3) |
| Trade Card blank | A fragment raised; `except: pass` swallowed it | Temporarily remove the wrapper at `vob_minimal.py:18294` |
| "⏸️ Dhan rate-limited (DH-904)" | 429 back-off active | Wait 90s; cached data is being served |
| "🔑 Dhan token expired" | 401 | Sidebar → Refresh Dhan Token |
| VOB / Money Flow show "—" | Leg key-shape mismatch | Check `_leg_key_variants` covers your store |
| S/R panel "still warming up" forever | It is an **error**, not a warm-up | Read `_sr_status` — it names build failure vs cold start |
| Alert not arriving on Telegram | Not in `_TELEGRAM_ENTRY_MARKERS` | By design — check Discord |
| Engine silently NEUTRAL | Missing upstream | Check Stage 0 health panel + `engine_errors` |

## 13.4 · Tests

```bash
python3 -m pytest mios_v5/tests/ -q
```

Expect **1,123 tests, all passing**. Part 15 records what is still open.

## 13.5 · Adding an engine — the checklist

1. Answer the **admission rule** (§7.2). Wave 3 is frozen
2. Subclass `Engine`, return `EngineResult`, declare `deps`
3. Take inputs as **parameters** (principle 4)
4. Register in `mios_v5/engines/__init__.py::ALL_ENGINES`
5. Expose it on `final_read` if any V6 module needs it
6. Ship it **observational** with `advisory_only: True`
7. Write the guard test that keeps it observational
8. Log it. Promotion needs 2–4 weeks of live data **and a human**

---

# Part 14 — Glossary

| Term | Meaning |
|---|---|
| **ATM** | At-the-money strike |
| **CE / PE** | Call / Put option |
| **CVD / CBV / CSV** | Cumulative Volume Delta / Buy Volume / Sell Volume |
| **DEX / GEX** | Delta / Gamma Exposure — dealer positioning |
| **DPOC** | Dynamic Point of Control |
| **FVG** | Fair Value Gap (ICT) |
| **HVN / LVN** | High / Low Volume Node |
| **HVP** | High Volume Pivot |
| **HTF** | Higher timeframe |
| **IOFCE / CIE / CMCE** | Institutional Order Flow / Candlestick Intelligence / Cross-Market Confirmation Engine |
| **MFP** | Money Flow Profile |
| **MFE / MAE** | Max Favourable / Adverse Excursion |
| **OI** | Open Interest |
| **PCR** | Put/Call Ratio |
| **POC / VAH / VAL** | Point of Control / Value Area High / Low |
| **R:R** | Reward-to-risk |
| **VOB** | Volume Order Block |
| **VPFR** | Volume Profile Fixed Range |
| **Charm pin** | Expiry-day dealer hedging dragging price to the magnet strike |
| **Capping** | Writers defending a strike against a move through it |
| **Tier 1/2/3** | Executed / Derived / Resting — the trust hierarchy (§3.5) |
| **Advisory-only** | Computed, displayed and logged — **consumed by nothing** |
| **Horizon** | Scalp · Midday · Intraday · Positional · Swing (§7.7) |
| **Owned producer** | A leaf read that votes in exactly one horizon |
| **Aggregate** | A composite of other producers — shown, never counted |
| **Wilson lower bound** | The conservative end of a proportion's interval; penalises small samples |
| **Counter-trend** | A horizon leaning against the market-level opportunity type |

---

# Part 15 — Known issues

*As of this document's commit. Verify with `pytest` before trusting.*

## 15.1 · The suite is green

**1,123 passing, 0 failing.**

Three tests failed for most of this project's recent history, and all three
traced to a single revert rather than three bugs. Commit `9a79542` gave
`indicators/order_flow.py` sole ownership of the CLV buy/sell split and
removed six inline copies; four `Add files via upload` commits landed on top,
and the last of them put the copies back and deleted 70 lines from
`dashboard_v6.py`.

Restored in `3dbf592` — `9a79542`'s patch still applied cleanly with `--3way`.
The guard tests did exactly the job they were written for, and they were right
for weeks before anyone acted on them. **A red suite that everyone has learned
to ignore is worse than no suite**; treat these three as the reason the rules
in Part 12 are enforced by tests rather than documented.

## 15.2 · Hardcoded Discord webhook

A live webhook URL is committed at `vob_minimal.py:178`, `:181` and `:195` as
the no-secrets fallback. Anyone with repo access can post to that channel.
**Rotate it and replace the fallback with `""`.**

## 15.3 · Smaller items

| Item | Location |
|---|---|
| Bare `except:` swallows `KeyboardInterrupt`/`SystemExit` | `vob_minimal.py:169` |
| Two different "held N min" (Stage 68 session vs Stage 54 state) read as one number contradicting itself | Trade Card |
| `🌙 Market Closed` can render beside a live behaviour label | `session_strip` |
| Trade Card `except: pass` hides all render errors | `vob_minimal.py:18294` |
| V6 divergence sentence can name the wrong voter | `v6_bias.py:324` |
| Stage 46 (Market Control) never built | Wave 4 |
| No T1/T2/T3 target ladder — Stage 35 produces one `next_target` | a ladder is new computation, not a rendering |
| Stage 71.5 type and maturity are **global**, not per-horizon | by design — a confirmed breakdown is a market fact |
| Stage 71 pools are uneven (scalp 22, swing 5) | intended; Wilson handles it, but thin horizons still swing |

---

## Appendix — the one-paragraph summary

A Streamlit app polls Dhan every 20 seconds for NIFTY candles, the option chain
and ATM±3 option legs, publishes them into `session_state`, and then runs
**47 engines** over that snapshot. The **native layer** (Generation 1) produces
the Market Picture and the Entry Gate, and is the only thing that fires an
alert. **MIOS V5** (stages 0–41) arbitrates ~34 engines through the Conflict
Engine into the headline bias. **MIOS V6** (stages 37, 42–54, 68–69) re-derives
that bias from four de-duplicated voters and displays it beside V5 — never
instead of it. Two **Decision Engines** (v0 and v2) grade the setup and log
every verdict including rejections. Everything past Generation 1 is
observational, carries `advisory_only: True`, and is barred by tests from ever
touching a live decision until weeks of logged evidence and *a human flipping a
constant* promote it.
