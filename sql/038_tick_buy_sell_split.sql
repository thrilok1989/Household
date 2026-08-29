-- 038 · dhan_ticks: keep the buy/sell split at source
--
-- `ws_worker.py` classifies every tick by the tick rule (LTP up → buy, LTP
-- down → sell, unchanged → neither) and stored only the SIGNED result,
-- `cum_delta` = buy − sell, alongside `volume` (the exchange's total traded
-- volume).
--
-- Buy% and Sell% cannot be recovered from that pair. `volume` includes the
-- unchanged-price ticks that were classified as neither side, so:
--
--     buy − sell = cum_delta        (known)
--     buy + sell = ?                (NOT volume — volume ≥ buy + sell)
--
-- Two unknowns, one equation. Assuming `buy + sell ≈ volume` would be wrong
-- exactly where it matters most: an illiquid option leg prints many ticks at
-- an unchanged price, so the neutral share is largest on precisely the
-- instruments whose flow reading is hardest to get right.
--
-- So the worker now accumulates both sides explicitly and writes them here.
-- Existing rows default to 0 and are simply not yet usable as a split; the
-- reader treats a row whose buy_vol + sell_vol is 0 as "no tick split
-- available" and falls back, rather than reporting 0/0 as 50/50.

ALTER TABLE dhan_ticks
    ADD COLUMN IF NOT EXISTS buy_vol  DOUBLE PRECISION DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sell_vol DOUBLE PRECISION DEFAULT 0;
