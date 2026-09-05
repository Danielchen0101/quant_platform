"""Deterministic research engine for Kalshi's 15-minute BTC contracts.

The engine is intentionally pure: it accepts a market snapshot and reference
prices, then returns an auditable, execution-neutral decision. It never signs
or submits an order; the controller separately applies the selected Paper or
Real environment and its authorization and risk checks.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


BTC_15M_SERIES = "KXBTC15M"
# Fractional cash rounding can make a slightly smaller order more economical.
# This is a bounded fallback, never a reason to expand an account's risk cap.
MAX_ECONOMIC_SIZE_SEARCH_STEPS = 1_000
MAX_COMPLETED_HISTORY_AGE_SECONDS = 120.0

DEFAULT_STRATEGY_CONFIG: Dict[str, Any] = {
    "executionMode": "paper",
    "paperBankroll": 1000.0,
    "riskPerTradePct": 0.50,
    # These are policy floors, not an asserted win rate. They must be
    # recalibrated against genuinely out-of-sample contract outcomes.
    "minNetEdge": 0.010,
    "minConservativeEdge": 0.0075,
    "maxSpread": 0.06,
    "maxRelativeSpread": 0.20,
    "minDepthContracts": 5.0,
    "maxBookParticipation": 0.20,
    # Entries live in the final minutes, where distance to the strike carries
    # more information and exposure duration remains short.
    "minSecondsToClose": 60,
    "maxSecondsToClose": 840,
    # Buy the model-confirmed favorite side only. Longshot buying is excluded
    # because its payoff profile is inconsistent with this carry strategy.
    "minPrice": 0.47,
    "maxPrice": 0.92,
    "minModelProbability": 0.64,
    # Logged out-of-sample contract outcomes show that Kalshi's executable
    # probability is a stronger prior than the old spot-only model early in a
    # contract.  Keep enough model weight to identify dislocations, but do not
    # let a noisy reference proxy overwhelm the traded market.
    "marketBlendWeight": 0.45,
    "maxModelMarketGap": 0.30,
    # The engine steepens the standardized distance score as expiry approaches.
    # 1.70 maps the standardised distance to a normal digital-option CDF.
    # The setting remains tunable as a transparent calibration multiplier.
    "probabilityLogitScale": 1.70,
    # Momentum enters as a bounded score shift, not a drift projection.
    "momentumProjectionScale": 0.07,
    "basisReserveBps": 3.0,
    "maxVolatilityRatio": 3.0,
    "maxJumpSigma": 5.0,
    "fractionalKelly": 0.15,
    # The hard loss budget is scaled down when a signal only just clears its
    # probability/edge floors or when a high-priced favorite offers little
    # payout relative to the capital at risk. Each multiplier is returned in
    # the decision payload so the sizing haircut is fully auditable.
    "minimumRiskBudgetScale": 0.35,
    "fullRiskModelProbability": 0.75,
    "fullRiskConservativeEdge": 0.030,
    "highPriceRiskStart": 0.75,
    "highPriceRiskFloor": 0.50,
    # A high-priced favorite can preserve a high headline win rate while one
    # loss consumes several ordinary wins.  Charge that asymmetric payoff an
    # explicit conservative-edge premium instead of banning the price tail.
    "recoveryMultipleTarget": 2.0,
    "recoveryPremiumPerUnit": 0.003,
    "maxRecoveryEdgePremium": 0.020,
    # Live results are materially stronger in the first part of the 15-minute
    # entry window than in its final minutes.  The raw uncertainty and edge
    # floors therefore become progressively more conservative as expiry nears.
    # These premiums apply only to KXBTC15M, never to the hourly strike ladder.
    "btc15MiddleStageSeconds": 420,
    "btc15LateStageSeconds": 180,
    "btc15MiddleEdgePremium": 0.0025,
    "btc15LateEdgePremium": 0.0050,
    "btc15MiddleUncertaintyPremium": 0.0050,
    "btc15LateUncertaintyPremium": 0.0100,
    "maxPortfolioExposurePct": 10.0,
    "maxSingleMarketExposurePct": 2.0,
    # Percentage-only sizing can round every valid setup to zero on a small
    # account.  A one-contract micro position is allowed only after every
    # signal/data/liquidity gate clears, and only when both an absolute loss
    # cap and an equity-relative cap can absorb the full contract cost.
    "microPositionMaxLossDollars": 1.0,
    "microPositionMaxLossPct": 5.0,
    "microPositionMinNetEdge": 0.020,
    "microPositionMinConservativeEdge": 0.010,
    # Kalshi V2 count_fp supports 0.01 contracts.  Risk-equal fractional
    # sizing is the default, while the legacy integer/micro path remains
    # available behind an explicit compatibility switch.
    "fractionalContractSizingEnabled": True,
    "contractStep": 0.01,
    "minimumEconomicContracts": 0.10,
    # A small account may use a still-bounded 2% target only for signals that
    # clear the existing stronger micro-edge floors.  The target is multiplied
    # by the same signal-quality and high-price tail-risk scale as ordinary
    # sizing; Kelly, cash, book and exposure limits remain authoritative.
    "smallAccountRiskTargetPct": 2.00,
    # Per-order cash debit is rounded up to the next cent.  Tiny orders whose
    # all-in fee consumes too much of the possible binary payout fail closed.
    "maxAllInFeeToPotentialProfitPct": 20.0,
    "takerFeeRate": 0.07,
    "entryConfirmationSnapshots": 2,
    # The hourly robot runs every 15 seconds.  Leave enough room for the
    # market/reference/account request latency so two genuinely consecutive
    # scheduler decisions can confirm instead of resetting at ~16 seconds.
    "entryConfirmationMaxGapSeconds": 25,
    # BTC15 production cycles include reference, order-book, and account reads.
    # Their observed cadence is slower and more variable than the five-second
    # scheduler target, so use a family-specific window while still requiring
    # two consecutive qualifying decisions.
    "btc15EntryConfirmationMaxGapSeconds": 25,
    "protectiveExitConfirmations": 3,
    "protectiveExitConfirmationMaxGapSeconds": 20,
    # Loss exits require three confirmations.  Give BTC15 enough wall-clock
    # room to complete that streak without weakening the probability or
    # executable-loss thresholds that authorize the exit.
    "btc15ProtectiveExitConfirmationMaxGapSeconds": 30,
    "hourlyCandidatePenaltyWeight": 0.10,
    "executionPriceTolerance": 0.01,
    "exitProbabilityThreshold": 0.35,
    # Exit orders are governed by executable value, not by the model
    # probability alone. These controls add hysteresis around entries so a
    # noisy five-second update cannot immediately reverse a fresh position.
    "minimumHoldSeconds": 60,
    "reversalCooldownSeconds": 90,
    "minimumAddIntervalSeconds": 90,
    "addMinModelProbability": 0.64,
    "addMinConservativeEdge": 0.0075,
    "addMinProbabilityImprovement": 0.01,
    "addMinEdgeImprovement": 0.001,
    "addSizeFraction": 0.25,
    "exitValueBuffer": 0.010,
    # Entries happen only inside the contract's bounded final window, so the
    # default is to HOLD TO SETTLEMENT. Crystallizing losses mid-window was a major
    # driver of the old strategy's poor realized win rate: exits must either
    # clear the fee-adjusted profit floor or meet both a deep probability
    # deterioration gate and a large mark-to-market loss gate.
    "minimumExitProfit": 0.015,
    "takeProfitScaleOutPct": 0.50,
    "stopLossPct": 0.45,
    "emergencyStopLossPct": 0.25,
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _number(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_strategy_config(raw: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Validate user-adjustable research limits against conservative bounds."""
    value = dict(DEFAULT_STRATEGY_CONFIG)
    raw = dict(raw or {})
    bounds: Dict[str, Tuple[float, float]] = {
        "paperBankroll": (100.0, 1_000_000.0),
        "riskPerTradePct": (0.10, 2.0),
        "minNetEdge": (0.005, 0.15),
        "minConservativeEdge": (0.0, 0.08),
        "maxSpread": (0.01, 0.20),
        "maxRelativeSpread": (0.05, 0.50),
        "minDepthContracts": (1.0, 10_000.0),
        "maxBookParticipation": (0.05, 0.50),
        "minSecondsToClose": (45.0, 360.0),
        # The 15-minute robot defaults to 840 seconds.  The wider upper
        # validation bound is used only by the separate hourly-strike robot.
        "maxSecondsToClose": (180.0, 2400.0),
        # Research policies may deliberately study a favorite-only band above
        # 60c.  The default remains 47c and live controllers still impose
        # their own narrower, outcome-validated envelopes.
        "minPrice": (0.30, 0.90),
        "maxPrice": (0.55, 0.99),
        "minModelProbability": (0.50, 0.90),
        "marketBlendWeight": (0.0, 0.75),
        "maxModelMarketGap": (0.10, 0.40),
        "probabilityLogitScale": (1.40, 2.60),
        "momentumProjectionScale": (0.0, 0.30),
        "basisReserveBps": (0.0, 15.0),
        "maxVolatilityRatio": (1.5, 5.0),
        "maxJumpSigma": (2.5, 8.0),
        "fractionalKelly": (0.05, 0.50),
        "minimumRiskBudgetScale": (0.10, 1.0),
        "fullRiskModelProbability": (0.65, 0.95),
        "fullRiskConservativeEdge": (0.01, 0.15),
        "highPriceRiskStart": (0.60, 0.90),
        "highPriceRiskFloor": (0.25, 1.0),
        "recoveryMultipleTarget": (1.0, 6.0),
        "recoveryPremiumPerUnit": (0.0, 0.03),
        "maxRecoveryEdgePremium": (0.0, 0.05),
        "btc15MiddleStageSeconds": (180.0, 900.0),
        "btc15LateStageSeconds": (60.0, 360.0),
        "btc15MiddleEdgePremium": (0.0, 0.03),
        "btc15LateEdgePremium": (0.0, 0.05),
        "btc15MiddleUncertaintyPremium": (0.0, 0.05),
        "btc15LateUncertaintyPremium": (0.0, 0.08),
        "maxPortfolioExposurePct": (2.0, 50.0),
        "maxSingleMarketExposurePct": (1.0, 20.0),
        "microPositionMaxLossDollars": (0.25, 5.0),
        "microPositionMaxLossPct": (1.0, 10.0),
        "microPositionMinNetEdge": (0.01, 0.10),
        "microPositionMinConservativeEdge": (0.005, 0.08),
        "contractStep": (0.01, 1.0),
        "minimumEconomicContracts": (0.01, 5.0),
        "smallAccountRiskTargetPct": (0.50, 2.0),
        "maxAllInFeeToPotentialProfitPct": (5.0, 50.0),
        "takerFeeRate": (0.0, 0.20),
        "entryConfirmationSnapshots": (1.0, 5.0),
        "entryConfirmationMaxGapSeconds": (5.0, 60.0),
        "btc15EntryConfirmationMaxGapSeconds": (10.0, 60.0),
        "protectiveExitConfirmations": (2.0, 6.0),
        "protectiveExitConfirmationMaxGapSeconds": (10.0, 60.0),
        "btc15ProtectiveExitConfirmationMaxGapSeconds": (15.0, 90.0),
        "hourlyCandidatePenaltyWeight": (0.0, 0.50),
        "executionPriceTolerance": (0.0, 0.03),
        "exitProbabilityThreshold": (0.10, 0.49),
        "minimumHoldSeconds": (0.0, 300.0),
        "reversalCooldownSeconds": (15.0, 600.0),
        "minimumAddIntervalSeconds": (10.0, 180.0),
        "addMinModelProbability": (0.55, 0.95),
        "addMinConservativeEdge": (0.0, 0.08),
        "addMinProbabilityImprovement": (0.0, 0.10),
        "addMinEdgeImprovement": (0.0, 0.03),
        "addSizeFraction": (0.10, 1.0),
        "exitValueBuffer": (0.0025, 0.05),
        "minimumExitProfit": (0.0, 0.10),
        "takeProfitScaleOutPct": (0.10, 1.0),
        "stopLossPct": (0.15, 0.80),
        "emergencyStopLossPct": (0.10, 0.60),
    }
    for key, (low, high) in bounds.items():
        if key not in raw:
            continue
        parsed = _number(raw.get(key))
        if parsed is None:
            continue
        value[key] = _clamp(parsed, low, high)

    requested_mode = str(raw.get("executionMode") or raw.get("mode") or value.get("executionMode") or "paper").strip().lower()
    value["executionMode"] = "real" if requested_mode in {"real", "live", "production"} else "paper"
    requested_fractional = raw.get(
        "fractionalContractSizingEnabled",
        value["fractionalContractSizingEnabled"],
    )
    if isinstance(requested_fractional, str):
        normalized_fractional = requested_fractional.strip().lower()
        if normalized_fractional in {"1", "true", "yes", "on"}:
            value["fractionalContractSizingEnabled"] = True
        elif normalized_fractional in {"0", "false", "no", "off"}:
            value["fractionalContractSizingEnabled"] = False
    else:
        value["fractionalContractSizingEnabled"] = bool(requested_fractional)
    value["minSecondsToClose"] = int(value["minSecondsToClose"])
    value["btc15MiddleStageSeconds"] = int(value["btc15MiddleStageSeconds"])
    value["btc15LateStageSeconds"] = int(value["btc15LateStageSeconds"])
    value["minimumHoldSeconds"] = int(value["minimumHoldSeconds"])
    value["entryConfirmationSnapshots"] = int(round(value["entryConfirmationSnapshots"]))
    value["protectiveExitConfirmations"] = int(round(value["protectiveExitConfirmations"]))
    value["reversalCooldownSeconds"] = int(value["reversalCooldownSeconds"])
    value["minimumAddIntervalSeconds"] = int(value["minimumAddIntervalSeconds"])
    value["maxSingleMarketExposurePct"] = min(
        value["maxSingleMarketExposurePct"],
        value["maxPortfolioExposurePct"],
    )
    value["microPositionMinNetEdge"] = max(
        value["microPositionMinNetEdge"],
        value["minNetEdge"],
    )
    value["microPositionMinConservativeEdge"] = max(
        value["microPositionMinConservativeEdge"],
        value["minConservativeEdge"],
    )
    value["emergencyStopLossPct"] = min(
        value["emergencyStopLossPct"],
        value["stopLossPct"],
    )
    value["maxSecondsToClose"] = max(
        int(value["maxSecondsToClose"]), value["minSecondsToClose"] + 30
    )
    if value["minPrice"] >= value["maxPrice"]:
        value["minPrice"], value["maxPrice"] = 0.50, 0.93
    value["fullRiskModelProbability"] = max(
        value["fullRiskModelProbability"],
        min(0.95, value["minModelProbability"] + 0.01),
    )
    value["fullRiskConservativeEdge"] = max(
        value["fullRiskConservativeEdge"],
        min(0.15, value["minConservativeEdge"] + 0.005),
    )
    value["highPriceRiskStart"] = min(
        value["highPriceRiskStart"],
        value["maxPrice"],
    )
    value["btc15LateStageSeconds"] = min(
        value["btc15LateStageSeconds"],
        value["btc15MiddleStageSeconds"],
    )
    value["btc15MiddleStageSeconds"] = max(
        value["btc15MiddleStageSeconds"],
        value["btc15LateStageSeconds"] + 30,
    )
    value["btc15LateEdgePremium"] = max(
        value["btc15LateEdgePremium"],
        value["btc15MiddleEdgePremium"],
    )
    value["btc15LateUncertaintyPremium"] = max(
        value["btc15LateUncertaintyPremium"],
        value["btc15MiddleUncertaintyPremium"],
    )
    value["minimumEconomicContracts"] = max(
        value["minimumEconomicContracts"],
        value["contractStep"],
    )
    return value


def _candle_points(candles: Iterable[Any]) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = []
    for index, candle in enumerate(candles or []):
        timestamp: Optional[float] = None
        close: Optional[float] = None
        if isinstance(candle, Mapping):
            timestamp = _number(candle.get("time") or candle.get("t") or candle.get("timestamp"))
            close = _number(candle.get("close") or candle.get("c"))
        elif isinstance(candle, Sequence) and not isinstance(candle, (str, bytes)):
            # Coinbase Exchange candles are [time, low, high, open, close, volume].
            if len(candle) >= 5:
                timestamp = _number(candle[0])
                close = _number(candle[4])
        if timestamp is None:
            timestamp = float(index)
        if close is not None and close > 0:
            points.append((timestamp, close))
    points.sort(key=lambda item: item[0])
    return points


def minute_return_series(candles: Iterable[Any]) -> List[float]:
    points = _candle_points(candles)
    returns: List[float] = []
    for (_, previous), (_, current) in zip(points, points[1:]):
        if previous > 0 and current > 0:
            returns.append(math.log(current / previous))
    return returns


def realized_minute_volatility(returns: Sequence[float]) -> Optional[float]:
    """EWMA one-minute volatility with a light outlier cap."""
    clean = [float(value) for value in returns if math.isfinite(float(value))]
    if len(clean) < 12:
        return None

    absolute = sorted(abs(value) for value in clean)
    cap = max(absolute[min(len(absolute) - 1, int(len(absolute) * 0.95))], 0.0002)
    clipped = [_clamp(value, -cap, cap) for value in clean[-120:]]
    weighted_square = 0.0
    weight_total = 0.0
    decay = 0.94
    for age, value in enumerate(reversed(clipped)):
        weight = decay ** age
        weighted_square += weight * value * value
        weight_total += weight
    if weight_total <= 0:
        return None
    return _clamp(math.sqrt(weighted_square / weight_total), 0.00020, 0.01000)


def _candle_rows(candles: Iterable[Any]) -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    for candle in candles or []:
        values: Dict[str, Any] = {}
        if isinstance(candle, Mapping):
            for field, aliases in (
                ("time", ("time", "t", "timestamp")),
                ("low", ("low", "l")), ("high", ("high", "h")),
                ("open", ("open", "o")), ("close", ("close", "c")),
                ("volume", ("volume", "v")),
            ):
                values[field] = next((
                    candle.get(key) for key in aliases
                    if candle.get(key) not in (None, "")
                ), None)
        elif isinstance(candle, Sequence) and not isinstance(candle, (str, bytes)) and len(candle) >= 5:
            values = {
                "time": candle[0],
                "low": candle[1], "high": candle[2],
                "open": candle[3], "close": candle[4],
                "volume": candle[5] if len(candle) > 5 else 0.0,
            }
        invalid_price = False
        for field in ("low", "high", "open", "close"):
            raw_price = values.get(field)
            parsed_price = _number(raw_price) if not isinstance(raw_price, bool) else None
            if raw_price not in (None, "") and parsed_price is None:
                invalid_price = True
            values[field] = parsed_price
        if invalid_price:
            continue
        close = values.get("close")
        if close is None or close <= 0:
            continue
        raw_time = values.get("time")
        timestamp = _number(raw_time) if not isinstance(raw_time, bool) else None
        if timestamp is None and isinstance(raw_time, str):
            parsed_time = _parse_time(raw_time)
            timestamp = parsed_time.timestamp() if parsed_time else None
        if timestamp is None or timestamp < 0:
            continue
        # Common adapters use Unix milliseconds; the Coinbase array uses
        # seconds. Normalize both before deduplication and as-of filtering.
        if timestamp >= 100_000_000_000:
            timestamp /= 1000.0
        low = values.get("low") if values.get("low") is not None else close
        high = values.get("high") if values.get("high") is not None else close
        opened = values.get("open") if values.get("open") is not None else close
        if min(low, high, opened) <= 0 or not low <= min(opened, close) <= max(opened, close) <= high:
            continue
        rows.append({
            "time": timestamp,
            "low": low,
            "high": high,
            "open": opened,
            "close": close,
            "volume": _number(values.get("volume"), 0.0) or 0.0,
        })
    rows.sort(key=lambda row: row["time"])
    return rows


def _completed_minute_history(
    candles: Iterable[Any],
    now: datetime,
) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    """Build one causal, non-duplicated minute sequence for every estimator.

    Coinbase timestamps denote bucket *starts*, not closes. Including the
    current bucket gives a partial minute the weight of a complete return;
    counting duplicate/gapped buckets also invalidates the 3m/5m/15m horizons.
    Retain only the newest contiguous completed run without filling missing
    prices or choosing between conflicting records for the same timestamp.
    Small sequential indices remain compatible with offline research fixtures;
    real epoch-timestamped feeds additionally require recent completed data.
    """
    raw = list(candles or [])
    rows = _candle_rows(raw)
    by_time: Dict[float, Dict[str, float]] = {}
    conflicting = set()
    duplicate_count = 0
    for row in rows:
        stamp = row["time"]
        prior = by_time.get(stamp)
        if prior is not None:
            duplicate_count += 1
            if any(prior[key] != row[key] for key in ("open", "high", "low", "close")):
                conflicting.add(stamp)
        else:
            by_time[stamp] = row
    ordered = [by_time[stamp] for stamp in sorted(by_time) if stamp not in conflicting]
    epoch_mode = any(row["time"] >= 1_000_000_000 for row in rows)
    now_epoch = now.timestamp()
    incomplete_count = 0
    future_count = 0
    mixed_timestamp_count = 0
    completed = []
    incomplete = []
    for row in ordered:
        stamp = row["time"]
        if epoch_mode and stamp < 1_000_000_000:
            mixed_timestamp_count += 1
        elif epoch_mode and stamp > now_epoch:
            future_count += 1
        elif epoch_mode and stamp + 60.0 > now_epoch + 1e-6:
            incomplete_count += 1
            incomplete.append(row)
        else:
            completed.append(row)

    # A missing minute cannot be re-labelled as a one-minute return, and
    # stale windows before a gap must not enter short-horizon momentum.
    expected_step = 60.0 if epoch_mode else 1.0
    start = 0
    gap_count = 0
    for index in range(1, len(completed)):
        if not math.isclose(completed[index]["time"] - completed[index - 1]["time"], expected_step, rel_tol=0.0, abs_tol=1e-6):
            gap_count += 1
            start = index
    clean = completed[start:]
    latest_close = clean[-1]["time"] + 60.0 if clean and epoch_mode else None
    age = max(0.0, now_epoch - latest_close) if latest_close is not None else None
    fresh = bool(clean) and epoch_mode and age <= MAX_COMPLETED_HISTORY_AGE_SECONDS
    current_bucket = next((
        row for row in incomplete
        if latest_close is not None and math.isclose(row["time"], latest_close, rel_tol=0.0, abs_tol=1e-6)
    ), None)
    current_bucket_return = (
        math.log(current_bucket["close"] / clean[-1]["close"])
        if current_bucket is not None else None
    )
    quality = {
        "policy": "completed_contiguous_minutes_v1",
        "timestampMode": "unix_seconds" if epoch_mode else "relative_minute_index",
        "clockVerified": epoch_mode,
        "inputRows": len(raw),
        "invalidRows": len(raw) - len(rows),
        "duplicateRows": duplicate_count,
        "conflictingTimestamps": len(conflicting),
        "futureRows": future_count,
        "incompleteRows": incomplete_count,
        "mixedTimestampRows": mixed_timestamp_count,
        "gapCount": gap_count,
        "rowsBeforeLastGap": start,
        "completedRows": len(clean),
        "requiredCompletedRows": 31,
        "status": (
            "insufficient_contiguous_history" if len(clean) < 31
            else "relative_index_research_only" if not epoch_mode
            else "stale_completed_history" if not fresh else "ready"
        ),
        "latestCompletedAt": _iso(datetime.fromtimestamp(latest_close, timezone.utc)) if latest_close is not None else None,
        "latestCompletedAgeSeconds": age,
        "maximumAgeSeconds": MAX_COMPLETED_HISTORY_AGE_SECONDS,
        "fresh": fresh,
        # Same-venue partial data is shock evidence only. It never enters the
        # calibrated volatility, momentum, or sample-size feature sequence.
        "currentBucketReturn": current_bucket_return,
    }
    return clean, quality


def _garman_klass_minute_volatility(candles: Iterable[Any]) -> Optional[float]:
    rows = _candle_rows(candles)[-120:]
    if len(rows) < 12:
        return None
    variances: List[float] = []
    for row in rows:
        log_range = math.log(row["high"] / row["low"])
        log_close_open = math.log(row["close"] / row["open"])
        variance = 0.5 * log_range * log_range - (2.0 * math.log(2.0) - 1.0) * log_close_open * log_close_open
        variances.append(max(0.0, variance))
    return _clamp(math.sqrt(sum(variances) / len(variances)), 0.00020, 0.01000)


def _root_mean_square(values: Sequence[float]) -> Optional[float]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    return math.sqrt(sum(value * value for value in clean) / len(clean))


def _book_levels(raw: Any) -> List[Tuple[float, float]]:
    levels: List[Tuple[float, float]] = []
    for level in raw or []:
        if not isinstance(level, Sequence) or isinstance(level, (str, bytes)) or len(level) < 2:
            continue
        price = _number(level[0])
        size = _number(level[1])
        if price is None or size is None or not 0.0 < price < 1.0 or size <= 0:
            continue
        levels.append((price, size))
    return sorted(levels, key=lambda level: level[0])


def _worst_fill_price(
    levels: Sequence[Tuple[float, float]],
    contracts: float,
) -> Optional[float]:
    """Return the highest price needed to fill ``contracts`` from asks.

    ``eligible_levels`` can contain substantially more depth than an order is
    allowed to consume.  Using the last eligible level as the IOC limit makes
    a small order look more expensive to the final account preflight than it
    was to sizing.  Walk only the depth the planned quantity actually needs so
    sizing, reported economics, and the routed limit share one price basis.
    """
    remaining = max(0.0, float(contracts))
    if remaining <= 1e-12:
        return None
    worst_price: Optional[float] = None
    for price, size in sorted(levels, key=lambda level: level[0]):
        available = max(0.0, float(size))
        if available <= 0.0:
            continue
        worst_price = float(price)
        remaining -= min(remaining, available)
        if remaining <= 1e-9:
            return worst_price
    return None


def _age_seconds(value: Any, now: datetime) -> Optional[float]:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def kalshi_fee(price: float, contracts: float = 1.0, rate: float = 0.07) -> float:
    """Conservative current general taker fee, rounded to the next centicent."""
    price = _clamp(float(price), 0.0, 1.0)
    contracts = max(0.0, float(contracts))
    raw = rate * contracts * price * (1.0 - price)
    return math.ceil((raw - 1e-12) * 10_000.0) / 10_000.0


def kalshi_order_cost(
    price: float,
    contracts: float = 1.0,
    rate: float = 0.07,
) -> Dict[str, float]:
    """Return a conservative, cash-debit-aware Kalshi buy cost.

    Kalshi computes the probability-weighted trade fee to four decimals, then
    a buy order's aggregate cash debit is rounded up to the next cent.  The
    latter is economically material for fractional orders, so sizing and EV
    must use the actual debit rather than ``contracts * fee_per_contract``.
    """
    normalized_price = _clamp(float(price), 0.0, 1.0)
    normalized_contracts = max(0.0, float(contracts))
    position_cost = normalized_price * normalized_contracts
    trade_fee = kalshi_fee(normalized_price, normalized_contracts, rate)
    pre_round_debit = position_cost + trade_fee
    cash_debit = (
        math.ceil((pre_round_debit - 1e-12) * 100.0) / 100.0
        if pre_round_debit > 0.0
        else 0.0
    )
    rounding_fee = max(0.0, cash_debit - pre_round_debit)
    all_in_fee = max(0.0, cash_debit - position_cost)
    return {
        "contracts": normalized_contracts,
        "price": normalized_price,
        "positionCost": round(position_cost, 10),
        "tradeFee": round(trade_fee, 10),
        "preRoundDebit": round(pre_round_debit, 10),
        "roundingFee": round(rounding_fee, 10),
        "allInFee": round(all_in_fee, 10),
        "cashDebit": round(cash_debit, 10),
    }


def _floor_contracts(value: float, step: float) -> float:
    """Floor a non-negative contract count to a fixed-point increment."""
    normalized_step = max(0.01, float(step))
    units = math.floor((max(0.0, float(value)) + 1e-12) / normalized_step)
    return round(units * normalized_step, 8)


def _ceil_contracts(value: float, step: float) -> float:
    """Ceil a non-negative contract count to a fixed-point increment."""
    normalized_step = max(0.01, float(step))
    units = math.ceil((max(0.0, float(value)) - 1e-12) / normalized_step)
    return round(units * normalized_step, 8)


def _smaller_economic_order_size(
    levels: Sequence[Tuple[float, float]],
    contracts: float,
    *,
    step: float,
    minimum_contracts: float,
    conservative_probability: float,
    dollar_cap: float,
    fee_rate: float,
    max_fee_to_profit_pct: float,
) -> Tuple[float, int]:
    """Keep the largest cap-fitting size unless a smaller size clears economics.

    Cash debit is rounded to cents, so fee burden and EV are not monotone in
    fractional quantity. A rejected maximum therefore does not imply that all
    smaller quantities are invalid. Search downward using the same marginal
    book price and exact cost as execution. Never cross the minimum quantity,
    expand the budget, or relax the existing positive-EV / fee-burden gates.
    Exhausting the bounded search returns the original rejected size so the
    caller still reports its normal order-economics blocker and diagnostics.
    """
    original = max(0.0, float(contracts))
    candidate = original
    tested = 0
    for _ in range(MAX_ECONOMIC_SIZE_SEARCH_STEPS):
        if candidate < minimum_contracts - 1e-12 or candidate <= 0.0:
            break
        tested += 1
        price = _worst_fill_price(levels, candidate)
        if price is not None:
            cost = kalshi_order_cost(price, candidate, fee_rate)
            gross_profit = candidate * (1.0 - price)
            expected_value = (
                conservative_probability * candidate - cost["cashDebit"]
            )
            if (
                gross_profit > 0.0
                and expected_value > 0.0
                and cost["allInFee"] / gross_profit * 100.0
                <= max_fee_to_profit_pct
                and cost["cashDebit"] <= dollar_cap + 1e-12
            ):
                return candidate, tested
        candidate = _floor_contracts(candidate - step, step)
    return original, tested


def _recovery_profile(
    price: float,
    settings: Mapping[str, Any],
    contracts: float = 1.0,
) -> Dict[str, float]:
    """Describe fee-adjusted binary payoff asymmetry for an order size."""
    cost = kalshi_order_cost(
        price,
        contracts,
        float(settings["takerFeeRate"]),
    )
    payout = max(0.0, float(contracts))
    maximum_loss = cost["cashDebit"]
    win_profit = max(0.0, payout - maximum_loss)
    # Keep the payload valid strict JSON even when cent rounding consumes the
    # entire possible payout.
    recovery_multiple = min(
        1_000_000.0,
        maximum_loss / max(win_profit, 1e-9),
    )
    target = float(settings["recoveryMultipleTarget"])
    premium = min(
        float(settings["maxRecoveryEdgePremium"]),
        max(0.0, recovery_multiple - target)
        * float(settings["recoveryPremiumPerUnit"]),
    )
    return {
        **cost,
        "maximumLoss": maximum_loss,
        "winProfitAfterFees": round(win_profit, 10),
        "recoveryMultiple": recovery_multiple,
        "breakEvenProbability": (
            maximum_loss / payout if payout > 0.0 else 1.0
        ),
        "recoveryEdgePremium": premium,
    }


def _btc15_time_stage(
    ticker: Any,
    seconds_to_close: float,
    settings: Mapping[str, Any],
) -> Tuple[str, float, float]:
    """Return the BTC15-only stage and its additive safety premiums."""
    if not str(ticker or "").upper().startswith(f"{BTC_15M_SERIES}-"):
        return "not_applicable", 0.0, 0.0
    if seconds_to_close <= float(settings["btc15LateStageSeconds"]):
        return (
            "late",
            float(settings["btc15LateEdgePremium"]),
            float(settings["btc15LateUncertaintyPremium"]),
        )
    if seconds_to_close <= float(settings["btc15MiddleStageSeconds"]):
        return (
            "middle",
            float(settings["btc15MiddleEdgePremium"]),
            float(settings["btc15MiddleUncertaintyPremium"]),
        )
    return "early", 0.0, 0.0


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _time_scaled_probability_scale(base_scale: float, seconds_to_close: float) -> float:
    """Steepen the distance calibration modestly as settlement approaches."""
    ramp = _clamp((300.0 - float(seconds_to_close)) / 180.0, 0.0, 1.0)
    return float(base_scale) * (1.0 + 0.12 * ramp)


def _gate(
    key: str,
    passed: bool,
    label: str,
    label_zh: str,
    detail: str,
    severity: str = "hard",
    category: str = "signal",
) -> Dict[str, Any]:
    return {
        "key": key,
        "status": "pass" if passed else ("observe" if severity == "adaptive" else "block"),
        "blocking": bool(not passed and severity != "adaptive"),
        "severity": severity,
        "label": label,
        "labelZh": label_zh,
        "detail": detail,
        "category": category,
    }


def select_btc15_market(
    markets: Iterable[Mapping[str, Any]],
    now: Optional[datetime] = None,
    *,
    min_active_seconds_to_close: float = 0.0,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Select the active KXBTC15M contract, or the nearest upcoming one."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidates = [
        dict(market) for market in markets or []
        if str(market.get("ticker") or "").upper().startswith(f"{BTC_15M_SERIES}-")
    ]
    active: List[Tuple[datetime, Dict[str, Any]]] = []
    upcoming: List[Tuple[datetime, Dict[str, Any]]] = []
    recent: List[Tuple[datetime, Dict[str, Any]]] = []
    for market in candidates:
        opened = _parse_time(market.get("open_time"))
        closes = _parse_time(market.get("close_time"))
        status = str(market.get("status") or "").lower()
        if opened and closes and opened <= now < closes and status in {"active", "open"}:
            if (closes - now).total_seconds() >= min_active_seconds_to_close:
                active.append((closes, market))
            else:
                recent.append((closes, market))
        elif opened and opened > now and status in {"initialized", "active", "open"}:
            upcoming.append((opened, market))
        elif closes and closes <= now:
            recent.append((closes, market))
    if active:
        return min(active, key=lambda item: item[0])[1], "active"
    if upcoming:
        return min(upcoming, key=lambda item: item[0])[1], "upcoming"
    if recent:
        return max(recent, key=lambda item: item[0])[1], "recent"
    return None, "unavailable"


def evaluate_btc15_contract(
    market: Mapping[str, Any],
    *,
    spot_price: Optional[float],
    candles: Iterable[Any],
    now: Optional[datetime] = None,
    config: Optional[Mapping[str, Any]] = None,
    orderbook: Optional[Mapping[str, Any]] = None,
    reference_time: Any = None,
    reference_metadata: Optional[Mapping[str, Any]] = None,
    book_time: Any = None,
    account_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a fail-closed decision using model, book, and account evidence."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    settings = normalize_strategy_config(config)
    market = dict(market or {})
    account = dict(account_context or {})
    reference = dict(reference_metadata or {})
    opened = _parse_time(market.get("open_time"))
    closes = _parse_time(market.get("close_time"))
    seconds_to_close = (closes - now).total_seconds() if closes else -1.0
    time_stage, time_stage_edge_premium, time_stage_uncertainty_premium = (
        _btc15_time_stage(market.get("ticker"), seconds_to_close, settings)
    )
    status = str(market.get("status") or "").lower()
    is_active = bool(opened and closes and opened <= now < closes and status in {"active", "open"})

    strike = _number(market.get("floor_strike"))
    spot = _number(spot_price)
    book = dict(orderbook or market.get("_orderbook") or {})
    yes_levels = _book_levels(book.get("yes"))
    no_levels = _book_levels(book.get("no"))
    best_yes_bid = yes_levels[-1] if yes_levels else None
    best_no_bid = no_levels[-1] if no_levels else None

    yes_bid = best_yes_bid[0] if best_yes_bid else _number(market.get("yes_bid_dollars"))
    no_bid = best_no_bid[0] if best_no_bid else _number(market.get("no_bid_dollars"))
    yes_ask = 1.0 - best_no_bid[0] if best_no_bid else _number(market.get("yes_ask_dollars"))
    no_ask = 1.0 - best_yes_bid[0] if best_yes_bid else _number(market.get("no_ask_dollars"))
    if no_bid is None and yes_ask is not None:
        no_bid = 1.0 - yes_ask
    if no_ask is None and yes_bid is not None:
        no_ask = 1.0 - yes_bid

    quotes_valid = all(
        value is not None and 0.0 < value < 1.0
        for value in (yes_bid, yes_ask, no_bid, no_ask)
    ) and bool(yes_ask >= yes_bid and no_ask >= no_bid)
    yes_spread = (yes_ask - yes_bid) if quotes_valid else None
    no_spread = (no_ask - no_bid) if quotes_valid else None
    spread = max(yes_spread or 0.0, no_spread or 0.0) if quotes_valid else None

    yes_bid_depth = best_yes_bid[1] if best_yes_bid else (_number(market.get("yes_bid_size_fp"), 0.0) or 0.0)
    no_bid_depth = best_no_bid[1] if best_no_bid else (_number(market.get("no_bid_size_fp"), 0.0) or 0.0)
    yes_ask_depth = no_bid_depth or (_number(market.get("yes_ask_size_fp"), 0.0) or 0.0)
    no_ask_depth = yes_bid_depth or (_number(market.get("no_ask_size_fp"), 0.0) or 0.0)
    top_depth_total = yes_bid_depth + yes_ask_depth
    book_imbalance = yes_bid_depth / top_depth_total if top_depth_total > 0 else None
    microprice_yes = None
    if quotes_valid and top_depth_total > 0:
        microprice_yes = (
            yes_ask * yes_bid_depth + yes_bid * yes_ask_depth
        ) / top_depth_total
    indicative_market_yes = None
    if quotes_valid:
        indicative_market_yes = microprice_yes if microprice_yes is not None else (yes_bid + yes_ask) / 2.0
    else:
        indicative_points = []
        direct_last = _number(market.get("last_price_dollars"))
        direct_yes_bid = _number(market.get("yes_bid_dollars"))
        direct_yes_ask = _number(market.get("yes_ask_dollars"))
        direct_no_bid = _number(market.get("no_bid_dollars"))
        direct_no_ask = _number(market.get("no_ask_dollars"))
        if direct_last is not None and 0.0 < direct_last < 1.0:
            indicative_points.append(direct_last)
        if direct_yes_bid is not None and 0.0 < direct_yes_bid < 1.0:
            indicative_points.append(direct_yes_bid)
        if direct_yes_ask is not None and 0.0 < direct_yes_ask < 1.0:
            indicative_points.append(direct_yes_ask)
        if direct_no_bid is not None and 0.0 < direct_no_bid < 1.0:
            indicative_points.append(1.0 - direct_no_bid)
        if direct_no_ask is not None and 0.0 < direct_no_ask < 1.0:
            indicative_points.append(1.0 - direct_no_ask)
        if indicative_points:
            indicative_market_yes = _clamp(sum(indicative_points) / len(indicative_points), 0.001, 0.999)

    history, history_quality = _completed_minute_history(candles, now)
    returns = minute_return_series(history)
    close_sigma = realized_minute_volatility(returns)
    range_sigma = _garman_klass_minute_volatility(history)
    if close_sigma is not None and range_sigma is not None:
        sigma_minute = math.sqrt(0.70 * close_sigma * close_sigma + 0.30 * range_sigma * range_sigma)
    else:
        sigma_minute = close_sigma or range_sigma

    short_rms = _root_mean_square(returns[-10:])
    long_rms = _root_mean_square(returns[-60:])
    volatility_ratio = (
        short_rms / max(long_rms, 1e-9)
        if short_rms is not None and long_rms is not None
        else None
    )
    jump_sigma = (
        max((abs(value) for value in returns[-5:]), default=0.0) / max(sigma_minute or 0.0, 1e-9)
        if sigma_minute is not None
        else None
    )
    live_candle_return = history_quality.get("currentBucketReturn")
    live_candle_jump_sigma = (
        abs(live_candle_return) / max(sigma_minute, 1e-9)
        if live_candle_return is not None and sigma_minute is not None
        else None
    )
    # Removing an unfinished bar from volatility/momentum must not hide a
    # current shock. Compare the current Coinbase bucket only with the same
    # venue's immediately preceding completed close: a BRTI/Coinbase basis or
    # a multi-minute gap must not be misclassified as a one-minute jump.
    if live_candle_jump_sigma is not None:
        jump_sigma = max(jump_sigma or 0.0, live_candle_jump_sigma)
    model_yes: Optional[float] = None
    fair_yes: Optional[float] = None
    market_mid: Optional[float] = None
    model_raw: Optional[float] = None
    horizon_sigma: Optional[float] = None
    momentum_3m: Optional[float] = None
    momentum_5m: Optional[float] = None
    momentum_15m: Optional[float] = None
    uncertainty = 0.12
    market_weight = 0.0
    basis_reserve = None
    effective_horizon_minutes = None
    venue_count = int(_number(reference.get("venueCount"), 0.0) or 0)
    dispersion_bps = max(0.0, _number(reference.get("dispersionBps"), 0.0) or 0.0)

    raw_market_mid = indicative_market_yes
    ladder_probability = _number(reference.get("smoothedProbability"))
    ladder_raw_probability = _number(reference.get("rawProbability"))
    ladder_dislocation = _number(reference.get("dislocation"))
    if ladder_probability is not None and 0.0 < ladder_probability < 1.0:
        market_mid = (
            _clamp(indicative_market_yes * 0.60 + ladder_probability * 0.40, 0.001, 0.999)
            if indicative_market_yes is not None
            else ladder_probability
        )
    else:
        market_mid = indicative_market_yes
    if spot and strike and spot > 0 and strike > 0 and sigma_minute is not None and seconds_to_close > 0:
        # KXBTC15M resolves from the arithmetic mean of the final 60 one-second
        # BRTI samples. Under a Brownian approximation, variance of that future
        # average is equivalent to a point horizon ending 40 seconds before
        # close (T - 60 + 60/3), not the old T - 30 shortcut.
        minutes = max((seconds_to_close - 40.0) / 60.0, 1.0 / 3.0)
        effective_horizon_minutes = minutes
        # Public constituent quotes are a proxy for licensed BRTI. Charge the
        # observed cross-venue dispersion and missing-venue risk explicitly.
        official_brti = bool(reference.get("isOfficialBrti")) or str(
            reference.get("model") or ""
        ) == "kalshi_cf_benchmarks_brti"
        quality_reserve_bps = dispersion_bps * 0.50 + max(0, 3 - venue_count) * 2.0
        # The authenticated Kalshi stream is the actual settlement index.  It
        # needs only a small timing reserve; public constituent quotes retain
        # the full observed basis and missing-venue reserve.
        configured_basis = (
            min(float(settings["basisReserveBps"]), 0.50)
            if official_brti else float(settings["basisReserveBps"])
        )
        basis_reserve = max(
            configured_basis,
            quality_reserve_bps if not official_brti else 0.0,
        ) / 10_000.0
        horizon_sigma = math.sqrt(max(sigma_minute, 0.00035) ** 2 * minutes + basis_reserve ** 2)
        momentum_3m = math.exp(sum(returns[-3:])) - 1.0 if returns else 0.0
        momentum_5m = math.exp(sum(returns[-5:])) - 1.0 if returns else 0.0
        momentum_15m = math.exp(sum(returns[-15:])) - 1.0 if returns else 0.0
        # Momentum is a small, bounded probability-score shift (fit: ~0.07 per standardized
        # 5-minute move), not a projected drift. Projected drift plus the old
        # reliability shrink systematically under-confident forecasts, which
        # made the engine "find value" on the longshot side and buy ~20%
        # winners. See docs/kalshi_dual_market_strategy_v6.md.
        momentum_z = _clamp(
            sum(returns[-5:]) / max(sigma_minute * math.sqrt(5.0), 1e-9),
            -3.0,
            3.0,
        ) if len(returns) >= 5 else 0.0
        distance_z = math.log(spot / strike) / max(horizon_sigma, 1e-9)
        scale = _time_scaled_probability_scale(float(settings["probabilityLogitScale"]), seconds_to_close)
        # Per-regime MLE fits show marginal favorites decay in elevated
        # volatility (hit 67.6% -> 61.6% as the 10m/60m vol ratio moves from
        # calm to 1.5-2.5). Damp confidence up to 5% across that band so
        # borderline entries fall below the probability floor instead of
        # entering over-priced.
        if volatility_ratio is not None and volatility_ratio > 1.5:
            scale *= 1.0 - 0.05 * _clamp((volatility_ratio - 1.5) / 1.0, 0.0, 1.0)
        distribution_z = _clamp(
            distance_z * (scale / 1.70)
            + momentum_z * float(settings["momentumProjectionScale"]),
            -8.0,
            8.0,
        )
        model_raw = _normal_cdf(distribution_z)
        model_yes = _clamp(model_raw, 0.02, 0.98)
        original_model_yes = model_yes

        if market_mid is not None:
            book_health = _clamp(
                (1.0 - (spread or settings["maxSpread"]) / max(settings["maxSpread"], 0.01)) * 0.50
                + min(1.0, min(yes_ask_depth, no_ask_depth) / max(settings["minDepthContracts"], 1.0)) * 0.50,
                0.15,
                1.0,
            )
            market_weight = settings["marketBlendWeight"] * book_health
            fair_yes = _clamp(model_yes * (1.0 - market_weight) + market_mid * market_weight, 0.03, 0.97)

        disagreement = abs(model_yes - market_mid) if market_mid is not None else 0.30
        uncertainty = _clamp(
            0.015
            + 0.10 / math.sqrt(max(len(returns), 1))
            + (spread or settings["maxSpread"]) * 0.35
            + min(0.03, max(0.0, (volatility_ratio or 1.0) - 1.0) * 0.02)
            + min(0.05, disagreement * 0.15),
            # A wide or single-venue proxy must not create false precision.
            0.02,
            0.12,
        )
        uncertainty = _clamp(
            uncertainty + min(0.025, dispersion_bps / 10_000.0 * 2.0)
            # A one-venue public quote is fragile; the official BRTI stream is
            # itself a regulated multi-exchange composite and must not receive
            # that proxy-only penalty merely because it is one index feed.
            + (0.01 if venue_count == 1 and not official_brti else 0.0),
            0.02,
            0.14,
        )

    base_uncertainty = uncertainty
    uncertainty = _clamp(
        base_uncertainty + time_stage_uncertainty_premium,
        0.02,
        0.22,
    )

    side: Optional[str] = None
    selected_price: Optional[float] = None
    selected_depth = 0.0
    selected_near_depth = 0.0
    selected_fair: Optional[float] = None
    gross_edge: Optional[float] = None
    fee_per_contract: Optional[float] = None
    all_in_fee_per_contract: Optional[float] = None
    rounding_fee_per_contract: Optional[float] = None
    net_edge: Optional[float] = None
    conservative_probability: Optional[float] = None
    conservative_edge: Optional[float] = None
    selected_model_probability: Optional[float] = None
    selected_levels: List[Tuple[float, float]] = []
    eligible_levels: List[Tuple[float, float]] = []
    edge_eligible_depth = 0.0
    execution_limit_price: Optional[float] = None
    maximum_loss_per_contract: Optional[float] = None
    win_profit_per_contract: Optional[float] = None
    recovery_multiple: Optional[float] = None
    break_even_probability: Optional[float] = None
    recovery_edge_premium = 0.0
    if fair_yes is not None and quotes_valid:
        # Favorite-carry selection: trade only the side the blended forecast
        # says is MORE likely to settle in the money. The old max-edge rule
        # compared both sides and, because the forecast was under-confident,
        # almost always "found value" on the longshot — a structural ~20%
        # winner. The favorite side's win rate is the forecast itself.
        if fair_yes >= 0.5:
            side, selected_price, selected_fair = "YES", yes_ask, fair_yes
            gross_edge = fair_yes - yes_ask
            selected_depth = yes_ask_depth
            selected_near_depth = sum(
                size for price, size in no_levels
                if (1.0 - price) <= (yes_ask or 0.0) + 0.03
            ) or selected_depth
            selected_levels = sorted(
                ((1.0 - price, size) for price, size in no_levels),
                key=lambda level: level[0],
            )
        else:
            side, selected_price, selected_fair = "NO", no_ask, 1.0 - fair_yes
            gross_edge = (1.0 - fair_yes) - no_ask
            selected_depth = no_ask_depth
            selected_near_depth = sum(
                size for price, size in yes_levels
                if (1.0 - price) <= (no_ask or 0.0) + 0.03
            ) or selected_depth
            selected_levels = sorted(
                ((1.0 - price, size) for price, size in yes_levels),
                key=lambda level: level[0],
            )
        selected_model_probability = model_yes if side == "YES" else 1.0 - model_yes
        recovery = _recovery_profile(selected_price, settings)
        fee_per_contract = recovery["tradeFee"]
        all_in_fee_per_contract = recovery["allInFee"]
        rounding_fee_per_contract = recovery["roundingFee"]
        maximum_loss_per_contract = recovery["maximumLoss"]
        win_profit_per_contract = recovery["winProfitAfterFees"]
        recovery_multiple = recovery["recoveryMultiple"]
        break_even_probability = recovery["breakEvenProbability"]
        recovery_edge_premium = recovery["recoveryEdgePremium"]
        net_edge = gross_edge - all_in_fee_per_contract
        conservative_probability = max(0.0, selected_fair - uncertainty * 0.50)
        conservative_edge = (
            conservative_probability - selected_price - all_in_fee_per_contract
        )
        if not selected_levels and selected_price is not None and selected_depth > 0:
            selected_levels = [(selected_price, selected_depth)]

    # Indexed fixtures remain available to the pure research engine, but are
    # explicitly NOT clock-verified/fresh. The Real routing boundary must
    # reject this compatibility mode rather than treat indices as live times.
    sample_ok = (
        len(returns) >= 30 and sigma_minute is not None
        and (history_quality["fresh"] or not history_quality["clockVerified"])
    )
    timing_ok = (
        settings["minSecondsToClose"] <= seconds_to_close <= settings["maxSecondsToClose"]
    )
    spread_ok = spread is not None and spread <= settings["maxSpread"]
    relative_spread = spread / selected_price if spread is not None and selected_price else None
    relative_spread_ok = (
        relative_spread is not None
        and relative_spread <= settings["maxRelativeSpread"]
    )
    depth_ok = selected_depth >= settings["minDepthContracts"]
    official_reference = bool(reference.get("isOfficialBrti")) or str(
        reference.get("model") or ""
    ) == "kalshi_cf_benchmarks_brti"
    # Model-confirmed dislocations below 50c are allowed only when the model
    # is driven by the exact settlement index.  The public proxy keeps the old
    # 50c favorite-carry floor to avoid basis-driven longshot entries.
    effective_min_price = (
        settings["minPrice"] if official_reference else max(0.50, settings["minPrice"])
    )
    price_ok = (
        selected_price is not None
        and effective_min_price <= selected_price <= settings["maxPrice"]
    )
    edge_ok = net_edge is not None and net_edge >= settings["minNetEdge"]
    conservative_edge_ok = (
        conservative_edge is not None
        and conservative_edge >= settings["minConservativeEdge"]
    )
    strike_ok = bool(strike and strike > 0 and spot and spot > 0)
    model_probability_ok = (
        selected_model_probability is not None
        and selected_model_probability >= settings["minModelProbability"]
    )
    volatility_ok = bool(
        volatility_ratio is not None
        and jump_sigma is not None
        and volatility_ratio <= settings["maxVolatilityRatio"]
        and jump_sigma <= settings["maxJumpSigma"]
    )
    model_market_gap = abs(model_yes - market_mid) if model_yes is not None and market_mid is not None else None
    model_agreement_ok = (
        model_market_gap is not None
        and model_market_gap <= settings["maxModelMarketGap"]
    )
    momentum_votes = [
        1 if value and value > 0 else -1 if value and value < 0 else 0
        for value in (momentum_3m, momentum_5m, momentum_15m)
    ]
    selected_vote = 1 if side == "YES" else -1 if side == "NO" else 0
    trend_support = sum(1 for vote in momentum_votes if vote == selected_vote)
    trend_conflict = sum(1 for vote in momentum_votes if vote == -selected_vote)
    trend_ok = side is not None and (trend_support >= 1 or trend_conflict < 2)
    book_pressure_ok = bool(
        side == "YES" and book_imbalance is not None and book_imbalance >= 0.20
        or side == "NO" and book_imbalance is not None and book_imbalance <= 0.80
    )
    # Trend and top-of-book pressure are noisy over a five-second cycle. They
    # should make entry more expensive, not veto an otherwise liquid,
    # fee-adjusted opportunity. This avoids the old "every signal must agree"
    # deadlock while still charging a 0.25-0.50pp confirmation premium.
    confirmation_edge_premium = (0.0025 if not trend_ok else 0.0) + (
        0.0025 if not book_pressure_ok else 0.0
    )
    adaptive_edge_premium = confirmation_edge_premium
    effective_min_net_edge = (
        settings["minNetEdge"]
        + confirmation_edge_premium
        + time_stage_edge_premium
    )
    effective_min_conservative_edge = (
        settings["minConservativeEdge"]
        + confirmation_edge_premium
        + time_stage_edge_premium
        + recovery_edge_premium
    )
    if selected_fair is not None and conservative_probability is not None:
        for price, size in selected_levels:
            if not effective_min_price <= price <= settings["maxPrice"]:
                continue
            level_recovery = _recovery_profile(price, settings)
            level_fee = level_recovery["allInFee"]
            level_min_conservative_edge = (
                settings["minConservativeEdge"]
                + confirmation_edge_premium
                + time_stage_edge_premium
                + level_recovery["recoveryEdgePremium"]
            )
            if (
                selected_fair - price - level_fee >= effective_min_net_edge
                and conservative_probability - price - level_fee
                >= level_min_conservative_edge
            ):
                eligible_levels.append((price, size))
        edge_eligible_depth = sum(size for _, size in eligible_levels)
        # The actual execution limit is assigned after sizing.  The farthest
        # positive-edge level is not necessarily touched by the planned order.
        execution_limit_price = selected_price
    depth_ok = edge_eligible_depth >= settings["minDepthContracts"]
    edge_ok = net_edge is not None and net_edge >= effective_min_net_edge
    conservative_edge_ok = (
        conservative_edge is not None
        and conservative_edge >= effective_min_conservative_edge
    )
    reference_age = _age_seconds(reference_time, now)
    book_age = _age_seconds(book_time, now)
    reference_fresh = reference_age is not None and reference_age <= 10.0
    book_fresh = book_age is not None and book_age <= 8.0
    freshness_detail = " / ".join(
        (
            f"spot {reference_age:.1f}s"
            if reference_age is not None
            else "spot timestamp missing",
            f"book {book_age:.1f}s"
            if book_age is not None
            else "book timestamp missing",
        )
    )

    gates = [
        _gate(
            "time_stage_stability",
            time_stage_edge_premium <= 0.0 and time_stage_uncertainty_premium <= 0.0,
            "BTC15 time-stage stability",
            "BTC15 分阶段稳定性",
            (
                f"{time_stage} / edge +{time_stage_edge_premium * 100:.2f}pp / "
                f"uncertainty +{time_stage_uncertainty_premium * 100:.2f}pp"
            ),
            severity="adaptive",
            category="signal",
        ),
        _gate(
            "recovery_asymmetry",
            recovery_multiple is not None
            and recovery_multiple <= settings["recoveryMultipleTarget"],
            "Fee-adjusted recovery multiple",
            "手续费后回本倍数",
            (
                f"{recovery_multiple:.2f} wins / target {settings['recoveryMultipleTarget']:.2f} / "
                f"edge +{recovery_edge_premium * 100:.2f}pp"
                if recovery_multiple is not None
                else "payoff unavailable"
            ),
            severity="adaptive",
            category="signal",
        ),
        _gate("contract_active", is_active, "Active contract", "合约交易中", f"status={status or 'unknown'}", category="data"),
        _gate("entry_window", timing_ok, "Entry window", "进场时段", f"{max(0, int(seconds_to_close))}s / {settings['minSecondsToClose']}-{settings['maxSecondsToClose']}s", category="data"),
        _gate("reference_ready", strike_ok, "Reference price", "参考价格", "BRTI strike and BTC reference available" if strike_ok else "missing strike or reference", category="data"),
        _gate("data_freshness", reference_fresh and book_fresh, "Fresh evidence", "数据新鲜度", freshness_detail, category="data"),
        _gate("history_sample", sample_ok, "Volatility sample", "波动率样本", f"{len(returns)} consecutive completed one-minute returns / min 30 / {history_quality['status']}", category="data"),
        _gate("volatility_regime", volatility_ok, "Stable volatility regime", "波动状态", f"ratio {(volatility_ratio or 0.0):.2f} / jump {(jump_sigma or 0.0):.1f} sigma", category="signal"),
        _gate(
            "model_probability",
            model_probability_ok,
            "Favorite-side confidence",
            "优势侧胜率下限",
            (
                f"{(selected_model_probability or 0.0) * 100:.1f}% / min {settings['minModelProbability'] * 100:.0f}%"
                if selected_model_probability is not None
                else "model probability unavailable"
            ),
            category="signal",
        ),
        _gate("model_market_agreement", model_agreement_ok, "Model-market agreement", "模型市场一致性", f"gap {(model_market_gap or 0.0) * 100:.1f}pp / max {settings['maxModelMarketGap'] * 100:.1f}pp", category="signal"),
        _gate("trend_confirmation", trend_ok, "Multi-horizon confirmation", "多周期确认", f"{trend_support} support / {trend_conflict} oppose", severity="adaptive", category="signal"),
        _gate("two_sided_quote", quotes_valid, "Two-sided market", "双边报价", "YES and NO bid books derive executable asks" if quotes_valid else "quote unavailable", category="execution"),
        _gate("spread", spread_ok, "Spread limit", "点差限制", f"{spread * 100:.1f}c / max {settings['maxSpread'] * 100:.1f}c" if spread is not None else "no executable spread", category="execution"),
        _gate("relative_spread", relative_spread_ok, "Relative spread", "相对点差", f"{(relative_spread or 0.0) * 100:.1f}% / max {settings['maxRelativeSpread'] * 100:.1f}%" if relative_spread is not None else "relative spread unavailable", category="execution"),
        _gate("depth", depth_ok, "Edge-eligible depth", "可执行深度", f"{selected_depth:.0f} top / {edge_eligible_depth:.0f} positive marginal edge / min {settings['minDepthContracts']:.0f}", category="execution"),
        _gate("book_pressure", book_pressure_ok, "Adverse book pressure", "盘口逆向压力", f"YES imbalance {(book_imbalance or 0.0) * 100:.0f}%", severity="adaptive", category="execution"),
        _gate(
            "price_band",
            price_ok,
            "Price band",
            "价格区间",
            (
                f"{selected_price * 100:.1f}c / min {effective_min_price * 100:.0f}c "
                f"({'official BRTI' if official_reference else 'proxy reference'})"
                if selected_price is not None else "no executable price"
            ),
            category="execution",
        ),
        _gate("net_edge", edge_ok, "Fee-adjusted edge", "扣费后边际", f"{net_edge * 100:.1f}pp / adaptive min {effective_min_net_edge * 100:.2f}pp" if net_edge is not None else "edge unavailable", category="signal"),
        _gate("conservative_edge", conservative_edge_ok, "Uncertainty-adjusted edge", "不确定性后边际", f"{conservative_edge * 100:.1f}pp / adaptive min {effective_min_conservative_edge * 100:.2f}pp" if conservative_edge is not None else "edge unavailable", category="signal"),
    ]

    is_real_execution = settings.get("executionMode") == "real"
    account_bankroll = _number(account.get("bankroll"))
    if account_bankroll is None:
        bankroll = 0.0 if is_real_execution else settings["paperBankroll"]
    else:
        bankroll = max(0.0, account_bankroll)
    daily_pnl = _number(account.get("dailyRealizedPnl"))
    if daily_pnl is None:
        daily_pnl = _number(account.get("dailyPnl"), 0.0) or 0.0
    daily_realized_loss = max(0.0, -daily_pnl)

    if account or is_real_execution:
        exposure = max(0.0, _number(account.get("portfolioExposure"), 0.0) or 0.0)
        market_exposure = max(0.0, _number(account.get("currentMarketExposure"), 0.0) or 0.0)
        exposure_pct = exposure / max(bankroll, 1.0) * 100.0
        market_exposure_pct = market_exposure / max(bankroll, 1.0) * 100.0
        cash_evidence = _number(account.get("cashAvailable"))
        account_ready = bool(
            bankroll > 0
            and (not is_real_execution or cash_evidence is not None)
        )
        account_gates = [
            _gate(
                "account_ready",
                account_ready,
                "Kalshi Real account ready" if is_real_execution else "AlphaLab Paper account ready",
                "Kalshi 实盘账户可用" if is_real_execution else "AlphaLab 模拟账户可用",
                f"portfolio {bankroll:.2f}",
                category="account",
            ),
            _gate("open_order", not bool(account.get("hasOpenOrder")), "No open order", "无未完成订单", "no resting order for this contract" if not account.get("hasOpenOrder") else "open order already exists", category="account"),
            _gate("portfolio_exposure", exposure_pct < settings["maxPortfolioExposurePct"], "Portfolio exposure", "组合总敞口", f"{exposure_pct:.1f}% / max {settings['maxPortfolioExposurePct']:.1f}%", category="account"),
            _gate("market_exposure", market_exposure_pct < settings["maxSingleMarketExposurePct"], "Single-market exposure", "单市场敞口", f"{market_exposure_pct:.1f}% / max {settings['maxSingleMarketExposurePct']:.1f}%", category="account"),
        ]
        gates.extend(account_gates)

    blocking = [gate["key"] for gate in gates if gate.get("blocking")]

    hard_risk_budget = bankroll * settings["riskPerTradePct"] / 100.0
    probability_strength = 0.0
    if selected_model_probability is not None:
        probability_strength = _clamp(
            (
                selected_model_probability - settings["minModelProbability"]
            )
            / max(
                settings["fullRiskModelProbability"]
                - settings["minModelProbability"],
                0.01,
            ),
            0.0,
            1.0,
        )
    edge_strength = 0.0
    if conservative_edge is not None:
        edge_strength = _clamp(
            (
                conservative_edge - effective_min_conservative_edge
            )
            / max(
                settings["fullRiskConservativeEdge"]
                - effective_min_conservative_edge,
                0.005,
            ),
            0.0,
            1.0,
        )
    # Both components must be strong before the strategy receives its full
    # hard loss budget. A setup that only just clears either entry floor gets
    # the configured minimum scale instead of the old all-or-nothing sizing.
    quality_strength = math.sqrt(probability_strength * edge_strength)
    quality_risk_scale = (
        settings["minimumRiskBudgetScale"]
        + (1.0 - settings["minimumRiskBudgetScale"]) * quality_strength
    )
    price_risk_scale = 1.0
    if (
        selected_price is not None
        and selected_price > settings["highPriceRiskStart"]
    ):
        high_price_progress = _clamp(
            (
                selected_price - settings["highPriceRiskStart"]
            )
            / max(
                settings["maxPrice"] - settings["highPriceRiskStart"],
                0.01,
            ),
            0.0,
            1.0,
        )
        price_risk_scale = (
            1.0
            - high_price_progress
            * (1.0 - settings["highPriceRiskFloor"])
        )
    applied_risk_scale = quality_risk_scale * price_risk_scale
    scaled_hard_risk_budget = hard_risk_budget * applied_risk_scale
    full_kelly = 0.0
    if (
        conservative_probability is not None
        and maximum_loss_per_contract is not None
    ):
        unit_cost = maximum_loss_per_contract
        full_kelly = max(0.0, (conservative_probability - unit_cost) / max(1.0 - unit_cost, 0.01))
    kelly_budget = bankroll * full_kelly * settings["fractionalKelly"]
    max_loss_budget = min(scaled_hard_risk_budget, kelly_budget) if kelly_budget > 0 else 0.0
    contracts = 0.0
    estimated_fee = 0.0
    estimated_trade_fee = 0.0
    rounding_fee = 0.0
    max_loss = 0.0
    expected_value = 0.0
    expected_loss = 0.0
    expected_win_profit = 0.0
    planned_recovery_multiple: Optional[float] = None
    fee_to_potential_profit_pct: Optional[float] = None
    standard_risk_budget = max_loss_budget
    micro_sizing_applied = False
    fractional_sizing_enabled = bool(settings["fractionalContractSizingEnabled"])
    contract_step = float(settings["contractStep"]) if fractional_sizing_enabled else 1.0
    minimum_economic_contracts = (
        _ceil_contracts(settings["minimumEconomicContracts"], contract_step)
        if fractional_sizing_enabled
        else 1.0
    )
    fractional_sizing_applied = False
    economic_size_adjustment_applied = False
    economic_size_candidates_tested = 0
    pre_economic_contracts_fp = 0.0
    small_account_sizing_applied = False
    small_account_risk_budget = 0.0
    small_account_unscaled_risk_target = 0.0
    risk_budget_utilization = 0.0
    planned_contracts_fp = 0.0
    micro_position_loss_cap = min(
        settings["microPositionMaxLossDollars"],
        bankroll * settings["microPositionMaxLossPct"] / 100.0,
    )
    if (
        not blocking
        and selected_price is not None
        and maximum_loss_per_contract is not None
        and conservative_probability is not None
    ):
        unit_cost = maximum_loss_per_contract
        depth_cap = _floor_contracts(
            edge_eligible_depth * settings["maxBookParticipation"],
            contract_step,
        )
        account_cash = _number(account.get("cashAvailable"))
        cash_available = (
            bankroll if account_cash is None else max(0.0, account_cash)
        )
        cash_cap = _floor_contracts(
            cash_available / max(unit_cost, 0.01),
            contract_step,
        )
        portfolio_exposure = max(0.0, _number(account.get("portfolioExposure"), 0.0) or 0.0)
        market_exposure = max(0.0, _number(account.get("currentMarketExposure"), 0.0) or 0.0)
        portfolio_room = max(
            0.0,
            bankroll * settings["maxPortfolioExposurePct"] / 100.0 - portfolio_exposure,
        )
        market_room = max(
            0.0,
            bankroll * settings["maxSingleMarketExposurePct"] / 100.0 - market_exposure,
        )
        exposure_cap = _floor_contracts(
            min(portfolio_room, market_room) / max(unit_cost, 0.01),
            contract_step,
        )
        strong_small_account_edge = bool(
            net_edge is not None
            and net_edge >= settings["microPositionMinNetEdge"]
            and conservative_edge is not None
            and conservative_edge >= settings["microPositionMinConservativeEdge"]
        )
        small_account_eligible = bool(
            fractional_sizing_enabled
            and strong_small_account_edge
            and market_exposure <= 0.0
            and standard_risk_budget > 0.0
            and standard_risk_budget < unit_cost
        )
        if small_account_eligible:
            small_account_unscaled_risk_target = (
                bankroll * settings["smallAccountRiskTargetPct"] / 100.0
            )
            small_account_risk_budget = min(
                small_account_unscaled_risk_target * applied_risk_scale,
                kelly_budget,
                micro_position_loss_cap,
            )
            if small_account_risk_budget > max_loss_budget:
                max_loss_budget = small_account_risk_budget
                small_account_sizing_applied = True

        risk_cap = _floor_contracts(
            max_loss_budget / max(unit_cost, 0.01),
            contract_step,
        )
        contracts = _floor_contracts(min(
            depth_cap,
            cash_cap,
            exposure_cap,
            risk_cap,
        ), contract_step)
        # The one-contract estimate is not sufficient for fractional orders:
        # aggregate cash debit rounds up to a cent.  Re-check the exact order
        # cost and step down until every monetary cap is truly respected.
        exact_dollar_cap = min(
            cash_available,
            portfolio_room,
            market_room,
            max_loss_budget,
        )
        while contracts > 0.0:
            candidate_execution_price = _worst_fill_price(
                eligible_levels,
                contracts,
            )
            if candidate_execution_price is None:
                contracts = _floor_contracts(
                    contracts - contract_step,
                    contract_step,
                )
                continue
            candidate_cost = kalshi_order_cost(
                candidate_execution_price,
                contracts,
                settings["takerFeeRate"],
            )
            if candidate_cost["cashDebit"] <= exact_dollar_cap + 1e-12:
                break
            contracts = _floor_contracts(contracts - contract_step, contract_step)
        micro_position_eligible = bool(
            not fractional_sizing_enabled
            and contracts <= 0
            and depth_cap >= 1
            and cash_cap >= 1
            and portfolio_room >= unit_cost
            and market_exposure <= 0.0
            and unit_cost <= micro_position_loss_cap
            and max_loss_budget > 0.0
            and net_edge is not None
            and net_edge >= settings["microPositionMinNetEdge"]
            and conservative_edge is not None
            and conservative_edge >= settings["microPositionMinConservativeEdge"]
        )
        if micro_position_eligible:
            contracts = 1.0
            micro_sizing_applied = True
            max_loss_budget = unit_cost
            exact_dollar_cap = min(
                cash_available,
                portfolio_room,
                market_room,
                max_loss_budget,
            )
            gates.append(_gate(
                "micro_position_size",
                True,
                "Small-account executable size",
                "小账户可执行仓位",
                (
                    f"1 contract / loss {unit_cost:.2f} / cap "
                    f"{micro_position_loss_cap:.2f}"
                ),
                severity="review",
                category="account",
            ))
        if (
            fractional_sizing_enabled
            and contracts < minimum_economic_contracts
        ):
            contracts = 0.0
        pre_economic_contracts_fp = contracts
        if fractional_sizing_enabled and contracts > 0.0:
            contracts, economic_size_candidates_tested = (
                _smaller_economic_order_size(
                    eligible_levels,
                    contracts,
                    step=contract_step,
                    minimum_contracts=minimum_economic_contracts,
                    conservative_probability=conservative_probability,
                    dollar_cap=exact_dollar_cap,
                    fee_rate=settings["takerFeeRate"],
                    max_fee_to_profit_pct=settings[
                        "maxAllInFeeToPotentialProfitPct"
                    ],
                )
            )
            economic_size_adjustment_applied = (
                contracts < pre_economic_contracts_fp - 1e-12
            )
        execution_limit_price = (
            _worst_fill_price(eligible_levels, contracts)
            if contracts > 0.0
            else selected_price
        )
        if contracts > 0.0 and execution_limit_price is None:
            contracts = 0.0
            execution_limit_price = selected_price
        planned_contracts_fp = contracts
        if contracts <= 0:
            blocking.append("position_size")
            gates.append(_gate(
                "position_size",
                False,
                "Executable position size",
                "可执行仓位",
                (
                    "Kelly/risk/depth caps are below the minimum economic size; "
                    f"min {minimum_economic_contracts:.2f} / "
                    f"small-account loss cap {micro_position_loss_cap:.2f}"
                ),
                category="account",
            ))
        else:
            order_cost = kalshi_order_cost(
                execution_limit_price,
                contracts,
                settings["takerFeeRate"],
            )
            estimated_trade_fee = order_cost["tradeFee"]
            rounding_fee = order_cost["roundingFee"]
            estimated_fee = order_cost["allInFee"]
            max_loss = order_cost["cashDebit"]
            gross_potential_profit = contracts * (1.0 - execution_limit_price)
            fee_to_potential_profit_pct = (
                estimated_fee / gross_potential_profit * 100.0
                if gross_potential_profit > 1e-12
                else 100.0
            )
            expected_loss = (1.0 - conservative_probability) * max_loss
            expected_win_profit = conservative_probability * max(
                0.0,
                contracts - max_loss,
            )
            expected_value = expected_win_profit - expected_loss
            planned_recovery = _recovery_profile(
                execution_limit_price,
                settings,
                contracts,
            )
            planned_recovery_multiple = planned_recovery["recoveryMultiple"]
            risk_budget_utilization = (
                max_loss / max_loss_budget if max_loss_budget > 0.0 else 0.0
            )
            fractional_sizing_applied = bool(
                fractional_sizing_enabled
                and abs(contracts - round(contracts)) > 1e-9
            )
            order_economics_ok = bool(
                expected_value > 0.0
                and fee_to_potential_profit_pct
                <= settings["maxAllInFeeToPotentialProfitPct"]
                and max_loss <= exact_dollar_cap + 1e-12
            )
            gates.append(_gate(
                "order_economics",
                order_economics_ok,
                "Rounding-aware order economics",
                "计入取整后的订单经济性",
                (
                    f"EV {expected_value:.4f} / all-in fee {estimated_fee:.4f} / "
                    f"fee {fee_to_potential_profit_pct:.1f}% of possible profit"
                ),
                category="execution",
            ))
            if not order_economics_ok:
                blocking.append("order_economics")
                contracts = 0.0

    action = f"BUY_{side}" if side and not blocking and contracts > 0 else "WAIT"
    # Favorite confidence drives the headline score; net edge and execution
    # friction adjust it around that base.
    signal_quality = int(round(_clamp(
        28.0
        + max(0.0, (selected_model_probability or 0.5) - 0.5) * 90.0
        + (conservative_edge or -0.05) * 500.0
        + min(len(returns), 90) / 15.0
        - uncertainty * 80.0
        - (spread if spread is not None else settings["maxSpread"] * 2.0) * 100.0
        - len(blocking) * 2.5,
        0.0,
        100.0,
    )))
    if blocking:
        # A blocked setup can contain an interesting forecast, but it is not a
        # high-quality trade. Keep the headline score aligned with that fact.
        signal_quality = min(signal_quality, max(0, 55 - len(blocking) * 5))

    distance_bps = ((spot / strike) - 1.0) * 10_000.0 if spot and strike else None
    is_real_execution = settings.get("executionMode") == "real"
    return {
        "engine": "btc15_settlement_aligned_v11",
        "generatedAt": _iso(now),
        "paperOnly": not is_real_execution,
        "executionEnvironment": "kalshi_real" if is_real_execution else "alphalab_paper",
        "action": action,
        "side": side,
        "signalQuality": signal_quality,
        "blockingReasons": blocking,
        "market": {
            "ticker": market.get("ticker"),
            "seriesTicker": BTC_15M_SERIES,
            "status": status,
            "title": market.get("title"),
            "openTime": market.get("open_time"),
            "closeTime": market.get("close_time"),
            "occurrenceTime": market.get("occurrence_datetime"),
            "secondsToClose": max(-1, int(seconds_to_close)),
            "strike": strike,
            "yesBid": yes_bid,
            "yesAsk": yes_ask,
            "noBid": no_bid,
            "noAsk": no_ask,
            "lastPrice": _number(market.get("last_price_dollars")),
            "spread": spread,
            "yesAskDepth": yes_ask_depth,
            "noAskDepth": no_ask_depth,
            "bookImbalance": book_imbalance,
            "micropriceYes": microprice_yes,
            "selectedDepth": selected_depth,
            "edgeEligibleDepth": edge_eligible_depth,
            "bookAgeSeconds": book_age,
            "volume": _number(market.get("volume_fp"), 0.0),
            "openInterest": _number(market.get("open_interest_fp"), 0.0),
        },
        "model": {
            "spot": spot,
            "strike": strike,
            "distanceBps": distance_bps,
            "minuteVolatility": sigma_minute,
            "projected15mVolatility": sigma_minute * math.sqrt(15.0) if sigma_minute else None,
            "horizonVolatility": horizon_sigma,
            "settlementEffectiveHorizonMinutes": effective_horizon_minutes,
            "referenceModel": reference.get("model") or "unspecified_spot_proxy",
            "isOfficialBrti": official_reference,
            "referenceRawPrice": _number(reference.get("rawPrice")),
            "settlementWindowAverage": _number(reference.get("settlementWindowAverage")),
            "settlementWindowSamples": int(_number(reference.get("settlementWindowSamples"), 0.0) or 0),
            "settlementWindowProgress": _number(reference.get("settlementWindowProgress"), 0.0),
            "referenceVenueCount": venue_count,
            "referenceDispersionBps": dispersion_bps,
            "basisReserveBpsApplied": basis_reserve * 10_000.0 if basis_reserve is not None else None,
            "momentum3m": momentum_3m,
            "momentum5m": momentum_5m,
            "momentum15m": momentum_15m,
            "volatilityRatio": volatility_ratio,
            "jumpSigma": jump_sigma,
            "liveCandleJumpSigma": live_candle_jump_sigma,
            "marketYesProbability": market_mid,
            "rawMarketYesProbability": raw_market_mid,
            "ladderRawProbability": ladder_raw_probability,
            "ladderSmoothedProbability": ladder_probability,
            "ladderDislocation": ladder_dislocation,
            "rawModelYesProbability": model_raw,
            "originalModelYesProbability": original_model_yes if 'original_model_yes' in locals() else model_yes,
            "modelYesProbability": model_yes,
            "fairYesProbability": fair_yes,
            "selectedModelProbability": selected_model_probability,
            "marketWeight": market_weight,
            "baseUncertainty": base_uncertainty,
            "uncertainty": uncertainty,
            "timeStage": time_stage,
            "timeStageEdgePremium": time_stage_edge_premium,
            "timeStageUncertaintyPremium": time_stage_uncertainty_premium,
            "referenceAgeSeconds": reference_age,
            "sampleSize": len(returns),
            "historyQuality": history_quality,
        },
        "edge": {
            "side": side,
            "price": selected_price,
            "executionLimitPrice": execution_limit_price,
            "fairProbability": selected_fair,
            "modelProbability": selected_model_probability,
            "minimumModelProbability": settings["minModelProbability"],
            "effectiveMinimumPrice": effective_min_price,
            "grossEdge": gross_edge,
            "feePerContract": fee_per_contract,
            "tradeFeePerContract": fee_per_contract,
            "roundingFeePerContract": rounding_fee_per_contract,
            "allInFeePerContract": all_in_fee_per_contract,
            "netEdge": net_edge,
            "conservativeProbability": conservative_probability,
            "conservativeEdge": conservative_edge,
            "minimumNetEdge": settings["minNetEdge"],
            "minimumConservativeEdge": settings["minConservativeEdge"],
            "adaptiveEdgePremium": adaptive_edge_premium,
            "confirmationEdgePremium": confirmation_edge_premium,
            "timeStageEdgePremium": time_stage_edge_premium,
            "recoveryEdgePremium": recovery_edge_premium,
            "effectiveMinimumNetEdge": effective_min_net_edge,
            "effectiveMinimumConservativeEdge": effective_min_conservative_edge,
            "maximumLossPerContract": maximum_loss_per_contract,
            "winProfitPerContract": win_profit_per_contract,
            "recoveryMultiple": recovery_multiple,
            "recoveryMultipleTarget": settings["recoveryMultipleTarget"],
            "breakEvenProbability": break_even_probability,
        },
        "sizing": {
            "paperBankroll": bankroll,
            "riskPerTradePct": settings["riskPerTradePct"],
            "dailyPnl": daily_pnl,
            "dailyRealizedLoss": daily_realized_loss,
            "riskBudget": max_loss_budget,
            "standardRiskBudget": standard_risk_budget,
            "hardRiskBudget": hard_risk_budget,
            "scaledHardRiskBudget": scaled_hard_risk_budget,
            "kellyRiskBudget": kelly_budget,
            "probabilityStrength": probability_strength,
            "edgeStrength": edge_strength,
            "qualityRiskScale": quality_risk_scale,
            "priceRiskScale": price_risk_scale,
            "appliedRiskScale": applied_risk_scale,
            "fullKelly": full_kelly,
            "fractionalKelly": settings["fractionalKelly"],
            "bookParticipationPct": settings["maxBookParticipation"] * 100.0,
            "microSizingApplied": micro_sizing_applied,
            "microPositionLossCap": micro_position_loss_cap,
            "fractionalSizingEnabled": fractional_sizing_enabled,
            "fractionalSizingApplied": fractional_sizing_applied,
            "economicSizeAdjustmentApplied": economic_size_adjustment_applied,
            "economicSizeCandidatesTested": economic_size_candidates_tested,
            "preEconomicContractsFp": pre_economic_contracts_fp,
            "smallAccountSizingApplied": small_account_sizing_applied,
            "smallAccountRiskTargetPct": settings["smallAccountRiskTargetPct"],
            "smallAccountUnscaledRiskTarget": small_account_unscaled_risk_target,
            "smallAccountRiskBudget": small_account_risk_budget,
            "contractStep": contract_step,
            "minimumEconomicContracts": minimum_economic_contracts,
            "contracts": contracts,
            "contractsFp": contracts,
            "plannedContractsFp": planned_contracts_fp,
            "integerCompatibilityContracts": int(math.floor(contracts)),
            "estimatedTradeFee": estimated_trade_fee,
            "roundingFee": rounding_fee,
            "allInFee": estimated_fee,
            "estimatedFee": estimated_fee,
            "maximumLoss": max_loss,
            "expectedLoss": expected_loss,
            "expectedWinProfit": expected_win_profit,
            "expectedValue": expected_value,
            "plannedRecoveryMultiple": planned_recovery_multiple,
            "feeToPotentialProfitPct": fee_to_potential_profit_pct,
            "riskBudgetUtilization": risk_budget_utilization,
        },
        "gates": gates,
        "config": settings,
        "methodology": {
            "settlementReference": "CF Benchmarks real-time index, 60-second settlement average",
            "spotReference": (
                "Official CF Benchmarks BRTI with final-minute settlement-average progress"
                if official_reference
                else "BRTI constituent-exchange proxy; official BRTI is the target settlement reference"
            ),
            "feeModel": (
                "Kalshi general taker fee plus conservative aggregate cash-debit "
                "rounding to the next cent"
            ),
            "probabilityModel": (
                "favorite-carry: normal digital probability on distance-to-strike, "
                "bounded momentum shift, market microprice blend, and monotone ladder prior"
            ),
            "directionMode": "normal",
            "samplePolicy": "deterministic fee-adjusted entry; no AI or random exploration overrides",
            "dailyLossPolicy": (
                "Realized profit and loss is informational and never blocks "
                "new entries"
            ),
            "orderPolicy": (
                "Kalshi Real IOC limit order signed and submitted by the backend only after every deterministic gate passes"
                if is_real_execution
                else "AlphaLab Paper IOC simulation at production Kalshi executable quotes; no exchange order is submitted"
            ),
        },
    }


__all__ = [
    "BTC_15M_SERIES",
    "DEFAULT_STRATEGY_CONFIG",
    "evaluate_btc15_contract",
    "kalshi_fee",
    "kalshi_order_cost",
    "minute_return_series",
    "normalize_strategy_config",
    "realized_minute_volatility",
    "select_btc15_market",
]
