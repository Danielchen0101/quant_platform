# Kalshi BTC trading quality review — 2026-09-05

## Objective and evidence boundary

Optimize realizable, after-cost returns rather than headline win rate or raw
order frequency. This release fixes demonstrated data and execution defects;
it does not establish future profitability or promote a looser signal policy.
The BTC15 70–80c champion, hourly 48–78c policy, uncertainty reserves, fee
floors, fractional Kelly, exposure caps, and ownership checks remain intact.

The account's infrastructure and Predictions collateral blockers were resolved
separately. A scoped read after restoration still showed the last recorded bot
BUY on August 25. Observations after funding are new research evidence, not new
completed trades. Do not train on those frames as if their eventual outcomes or
execution were already known.

The stricter quantity-reconciled audit found 128 bot-entry tickers: 127 complete
and one incomplete. Complete BTC15 history had 107 tickers, 70 positive and 37
negative results (65.42% profitable), net -$0.6371 and profit factor 0.9408.
The 20 complete hourly tickers had 12 positive and 8 negative results, net
+$0.6352 and profit factor 1.2867. The partial BTC15 position had sold 0.99 of
1.00 recorded contracts; its +$0.0627 partial P/L is not a completed win.
195 unowned outcome tickers are excluded from these statistics.

These are small, mixed-policy historical samples, not a return forecast.
Reported trading P/L excludes hosting, data/AI subscriptions and taxes; trading
break-even alone does not cover the website's running costs.
Same-ticker manual activity and truncated history can still make attribution
imperfect even when quantities match. The audit reports those limitations and
separates incomplete/ambiguous cases. Account-wide settlements must not silently
be presented as the robot's performance. Both the pre-restoration and refreshed
September 5 exports gave the same complete-market baseline.

## Correctness changes

### One causal minute history

Volatility and momentum now consume the same completed, chronologically ordered
minute sequence. Equivalent duplicate rows no longer increase sample count or
flatten short-term momentum. Conflicting duplicates, invalid OHLC, future
records and incomplete buckets cannot enter the historical estimates. Missing
minutes are not filled with invented prices: only the newest contiguous run is
used, and insufficient/stale history is identified explicitly.

Coinbase's candle timestamp is the bucket start and its feed can omit intervals
with no trades. Therefore, a candle starting in the current minute is not yet a
complete one-minute observation. Its same-venue price movement may still
provide shock evidence; it is not a completed volatility sample. BRTI remains
the settlement reference, not a substitute for Coinbase's candle clock.
[Coinbase candle specification](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles).

The public source request now specifies a UTC minute-aligned 300-minute
start/end window, ending at the next minute boundary, while retaining the
existing 15-second local cache. A live read-only check found the unbounded
default endpoint returning completed data more than 120 seconds old, whereas
the explicit window returned 299 completed bars and one current partial bar,
with the latest completed close about 12 seconds old. This is a source-window
correction, not a higher polling rate or a relaxation of freshness validation.
The exact returned sample count can differ from the old unbounded response;
sampling uncertainty and the full-input return outlier cap may therefore
change. This is not included in the identical-input equivalence claim, and no
old observations are fabricated to force the previous forecast.

The compact `historyQuality` diagnostic records clock verification, duplicate,
gap and excluded-row counts, completed sample size and age. No raw candle or
order-book history is added to routine durable heartbeat writes. Relative-index
legacy research fixtures cannot establish a verified real-market clock.

### Actual sale-side costs and route-sized exits

Live exit estimates and paper execution share the same Decimal seller-side
cash calculation. Reusing a buyer's rounded debit as a sale fee previously
double-counted rounding for some fractional sales. For example, 0.33 contracts
sold at $0.80 credit $0.26 under the shared calculation, not the old $0.25
estimate. Fees remain market-policy aware; no assumed fee discount is added.
[Kalshi fee and cash rounding](https://docs.kalshi.com/getting_started/fee_rounding).

Voluntary take-profit decisions are rechecked after the scale-out quantity and
IOC limit are known. A profitable full-position estimate is not sufficient:
selling half can cross a cent-rounding boundary and erase the intended net
profit. Reprice that slice against the actual bid depth so it does not inherit
an unnecessarily poor price from deeper bids needed only for the full position.
If removing crossing tolerance preserves the existing profit and
hold-value requirements at the observed bid, tighten the limit; otherwise wait.
Do not increase the sale quantity or invent a better bid to pass the test.

The final real-order preflight repeats this check with the actual route size
and limit. Exact planned multi-level proceeds must also satisfy the existing
requirements: separate fee rounding across ladder fills can make a single-fill
limit-price estimate optimistic for a tiny slice. Missing or mismatched planned
quantity evidence cannot be repaired by prorating fees. Protective and
emergency reduce-only exits are not constrained by
voluntary profit-taking requirements or entry collateral gates. An IOC may fill
partially or not at all: the estimate is conditional on filling the requested
slice and is not a guarantee of realized profit. Authenticated fills and actual
fees remain authoritative.

### Restart-safe protective confirmation

Repeated timestamps cannot count as separate ordinary-loss confirmations.
Compact per-ticker, per-side cursors survive worker restarts, expire across
excessive gaps, and reset on an intervening ineligible frame or routed sale.
Different held hourly strikes do not overwrite one another. Emergency exits
retain their immediate bypass. Browser-only refreshes cannot advance cursors.

At most 16 small protective cursors are retained per mode. Only meaningful
progress changes are durably saved; routine WAIT rows are not restored to the
large Supabase artifact, avoiding the previous high-frequency bandwidth cost.

## Validation and promotion discipline

- Regression fixtures cover clean-history equivalence, duplicate invariance,
  future/partial data exclusion, gaps, malformed data, clock validity, seller
  rounding, actual scale-out economics and restart/duplicate confirmation.
  A paired mechanical comparison preserved all existing outputs across 864
  clean-input scenarios, including 146 BUY decisions; repeating/reversing
  those inputs also preserved results. Another 72 reference-basis/history-age
  scenarios produced no new false jump blocks. These are correctness checks,
  not a profit backtest.
- The offline audit consumes private JSON/JSON.gz exports only, with no broker
  credentials or network access. It aggregates complete market results before
  wins/losses, preserves zero-P/L outcomes, and distinguishes bot-entry ticker
  ownership from proof of exact account-wide fill allocation.
  Reproduce locally with `python scripts/kalshi_backtest/kalshi_owned_performance.py
  /path/to/private-state.json.gz`; never commit the private export. Explicit
  chronological boundaries can be supplied with `--train-end` and
  `--validation-end`, but dates selected after seeing results are not an
  untouched holdout.
- The old `kalshi_engine_replay.py`, `kalshi_strategy_sim.py` and related OHLC
  scripts are synthetic research, not current production replay. They use
  fabricated quotes/depth and approximate settlement references; the old
  replay also imports a temporary engine path and omits final confirmation and
  routing. Their win rates cannot justify a live policy promotion.
- A future challenger needs fresh chronological market/event holdouts, exact
  order costs, official settlement outcomes, realistic latency/partial fills,
  adverse execution scenarios, and complete-event profit factor/drawdown.
  Sampled WAIT rows do not supply all those inputs. Preserve the previously
  documented minimum new-sample and out-of-sample criteria before changing the
  champion's signal thresholds.

No new instance, subscription, wallet transfer, automatic balance allocation,
manual test order, or change to real-mode arming is part of this release.
