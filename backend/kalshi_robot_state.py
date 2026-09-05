"""Persistent non-financial state for the AlphaLab Kalshi robot."""

from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

try:
    from kalshi_engine import DEFAULT_STRATEGY_CONFIG, normalize_strategy_config
except ImportError:  # pragma: no cover - package-style test imports
    from .kalshi_engine import DEFAULT_STRATEGY_CONFIG, normalize_strategy_config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _entry_confirmation_family(ticker: Any) -> Optional[str]:
    normalized = str(ticker or "").upper()
    if normalized.startswith("KXBTC15M"):
        return "btc15m"
    if normalized.startswith("KXBTCD"):
        return "btchourly"
    return None


# Decision rows are a short-lived operator view, not the durable trade ledger.
# Filled trades and market observations are persisted separately, so retaining a
# few minutes here is enough while keeping each heartbeat write small on Nano
# Postgres compute.  The state mirrors the active bucket at the top level, which
# means every extra decision would otherwise be serialized twice.
MAX_DECISION_RECORDS = 50
MAX_SETTLEMENT_RECORDS = 1000
MAX_TRADED_TICKERS = 2000
PAPER_STATE_VERSION = 15
KALSHI_MODES = ("paper", "real")

# These fields mirror the active mode bucket for older API consumers.  Keeping
# both copies in memory is useful, but sending both copies to Supabase on every
# durable mutation doubles the largest parts of the request body.  The mirror
# is rebuilt by ``_sync_mode_mirror`` immediately after a durable load.
_TOP_LEVEL_MODE_MIRRORS = (
    "config",
    "strategy",
    "tradedTickers",
    "filledTrades",
    "processedSettlements",
    "decisions",
    "decisionLimit",
)

# Removed strategy experiments are not execution inputs.  Old durable rows can
# still contain them, so strip them from the next outbound write instead of
# paying Render egress to preserve unused history indefinitely.
_LEGACY_NON_TRADING_FIELDS = (
    "learningObservations",
    "learningExamples",
    "strategyLibrary",
)

# Evaluation decisions are a live operator view and already have a dedicated,
# bounded observation table.  They are intentionally kept in memory for entry
# and exit confirmation, while fills and settlement provenance remain durable
# in their own fields.  Persisting these feature-heavy rows made one robot
# artifact exceed a megabyte in production.
_EPHEMERAL_MODE_FIELDS = (
    "decisionLimit",
    "lastRunAt",
    "lastError",
    "runs",
)

_EPHEMERAL_TOP_LEVEL_FIELDS = (
    "lastRunAt",
    "lastError",
    "runs",
)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed and abs(parsed) != float("inf") else default


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    """Return the first explicit field, preserving numeric/string zero."""
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _has_present(row: Mapping[str, Any], *keys: str) -> bool:
    return any(row.get(key) not in (None, "") for key in keys)


def _utc_time_sort_key(value: Any) -> tuple[int, float]:
    """Chronologically sort mixed ISO-Z/offset timestamps in UTC."""
    raw = str(value or "").strip()
    if not raw:
        return (0, 0.0)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return (0, 0.0)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    try:
        timestamp = parsed.astimezone(timezone.utc).timestamp()
    except (OverflowError, OSError, ValueError):
        return (0, 0.0)
    return (1, timestamp)


def _update_protective_exit_progress(
    bucket: Dict[str, Any],
    row: Mapping[str, Any],
    decision: Mapping[str, Any],
    order: Optional[Mapping[str, Any]],
) -> bool:
    """Keep a small, mode-local stop confirmation cursor across restarts.

    Only authoritative execution cycles call ``record``. Browser refreshes
    cannot build a streak, and full decision rows need not be persisted for
    this safety mechanism to survive a worker handoff.
    """
    ticker = str(row.get("ticker") or "")
    if not _entry_confirmation_family(ticker):
        return False
    strategy = bucket["strategy"]
    cursors = dict(strategy.get("protectiveExitConfirmations") or {})
    previous = dict(cursors.get(ticker) or {})
    timestamp = _utc_time_sort_key(row.get("generatedAt"))[1]
    previous_timestamp = _utc_time_sort_key(previous.get("generatedAt"))[1]
    if previous and timestamp < previous_timestamp:
        return False
    confirmation = dict(decision.get("protectiveConfirmation") or {})
    side = str((row.get("account") or {}).get("heldSide") or "").upper()
    eligible = bool(
        timestamp > 0
        and side in {"YES", "NO"}
        and confirmation.get("required")
        and not confirmation.get("emergencyBypass")
        and confirmation.get("dataQualityEligible") is True
        and _number(confirmation.get("streak")) >= 1
        and not (order and str(row.get("action") or "").startswith("SELL_"))
    )
    if not eligible:
        if previous:
            cursors.pop(ticker, None)
            strategy["protectiveExitConfirmations"] = cursors
            return True
        return False
    # Repeated data, even if a caller supplied an inflated streak, must never
    # become multiple independent confirmations. A changed side breaks it.
    if previous and timestamp == previous_timestamp:
        if previous.get("side") == side:
            return False
        cursors.pop(ticker, None)
        strategy["protectiveExitConfirmations"] = cursors
        return True
    required = max(2, min(6, int(_number(confirmation.get("requiredSnapshots"), 3))))
    max_gap = max(10.0, min(90.0, _number(confirmation.get("maxGapSeconds"), 30.0)))
    continuous = bool(
        previous.get("side") == side
        and previous.get("dataQualityEligible") is True
        and 0 < timestamp - previous_timestamp <= max_gap
    )
    streak = min(
        required,
        max(1, int(_number(confirmation.get("streak"), 1))),
        max(1, int(_number(previous.get("streak"), 1))) + 1 if continuous else 1,
    )
    progress = {
        "ticker": ticker,
        "side": side,
        "generatedAt": row["generatedAt"],
        "streak": streak,
        "requiredSnapshots": required,
        "confirmed": streak >= required,
        "dataQualityEligible": True,
        "maxGapSeconds": max_gap,
    }
    changed = bool(
        not continuous
        or previous.get("streak") != streak
        or previous.get("requiredSnapshots") != required
        or previous.get("maxGapSeconds") != max_gap
    )
    cursors[ticker] = progress
    # An hourly ladder can have more than one held strike. Do not overwrite
    # one position's evidence with another's, or accumulate expired markets.
    cursors = {
        key: value for key, value in sorted(
            cursors.items(),
            key=lambda item: _utc_time_sort_key(item[1].get("generatedAt")),
        )[-16:]
        if timestamp - _utc_time_sort_key(value.get("generatedAt"))[1] <= 90
    }
    strategy["protectiveExitConfirmations"] = cursors
    return changed


def _money(row: Mapping[str, Any], dollar_keys, cent_keys=()) -> float:
    for key in dollar_keys:
        value = row.get(key)
        if value not in (None, ""):
            return _number(value)
    for key in cent_keys:
        value = row.get(key)
        if value not in (None, ""):
            return _number(value) / 100.0
    return 0.0


def _settlement_result(settlement: Mapping[str, Any]) -> str:
    result = str(settlement.get("market_result") or settlement.get("result") or "").upper()
    if result in {"YES", "NO"}:
        return result
    value = settlement.get("value")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(numeric):
        return ""
    threshold = 0.5 if 0.0 <= numeric <= 1.0 else 50.0
    return "YES" if numeric >= threshold else "NO"


def _execution_environment(value: Any) -> str:
    mode = str(value or "paper").strip().lower()
    return "real" if mode in {"real", "live", "production"} else "paper"


def _valid_real_display_baseline(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    reset_at = str(value.get("resetAt") or "").strip()
    if not reset_at:
        return False
    try:
        parsed = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return bool(
        parsed is not None
        and str(value.get("environment") or "").strip().lower() == "real"
        and value.get("alphaLabOnly") is True
    )


def _new_real_display_baseline(reason: str) -> Dict[str, Any]:
    return {
        "resetAt": _now(),
        "environment": "real",
        "ledgerPreserved": True,
        "alphaLabOnly": True,
        "reason": str(reason or "real_display_baseline_repair"),
    }


def _safe_strategy_config(
    raw: Optional[Mapping[str, Any]],
    environment: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize user settings while enforcing durable execution safety floors."""
    requested = dict(raw or {})
    configured = normalize_strategy_config(requested)
    if environment is not None:
        configured["executionMode"] = _execution_environment(environment)
    configured["minModelProbability"] = max(
        0.64, _number(configured.get("minModelProbability"), 0.64)
    )
    configured["minNetEdge"] = max(
        0.01, _number(configured.get("minNetEdge"), 0.01)
    )
    configured["minConservativeEdge"] = max(
        0.0075, _number(configured.get("minConservativeEdge"), 0.0075)
    )
    configured["maxPrice"] = min(
        0.92, _number(configured.get("maxPrice"), 0.92)
    )
    configured.setdefault("minimumRiskBudgetScale", 0.35)
    configured.setdefault("fullRiskModelProbability", 0.75)
    configured.setdefault("fullRiskConservativeEdge", 0.03)
    configured.setdefault("highPriceRiskStart", 0.75)
    configured.setdefault("highPriceRiskFloor", 0.50)
    configured["fullRiskModelProbability"] = max(
        _number(configured.get("fullRiskModelProbability"), 0.75),
        _number(configured.get("minModelProbability"), 0.64) + 0.01,
    )
    configured["fullRiskConservativeEdge"] = max(
        _number(configured.get("fullRiskConservativeEdge"), 0.03),
        _number(configured.get("minConservativeEdge"), 0.0075) + 0.005,
    )
    configured["highPriceRiskStart"] = min(
        _number(configured.get("highPriceRiskStart"), 0.75),
        _number(configured.get("maxPrice"), 0.92),
    )
    configured["riskPerTradePct"] = min(
        0.50, _number(configured.get("riskPerTradePct"), 0.50)
    )
    # Hourly scans run on a 15-second cadence.  A 15-second confirmation gap
    # is therefore impossible once normal request latency is included; keep
    # the persisted/effective setting above that cadence without weakening
    # the requirement for two consecutive qualifying decisions.
    configured["entryConfirmationMaxGapSeconds"] = max(
        25.0,
        _number(configured.get("entryConfirmationMaxGapSeconds"), 25.0),
    )
    configured["fractionalKelly"] = min(
        0.15, _number(configured.get("fractionalKelly"), 0.15)
    )
    configured["maxPortfolioExposurePct"] = min(
        10.0, _number(configured.get("maxPortfolioExposurePct"), 10.0)
    )
    configured["maxSingleMarketExposurePct"] = min(
        2.0, _number(configured.get("maxSingleMarketExposurePct"), 2.0)
    )
    configured["microPositionMaxLossDollars"] = min(
        1.0, _number(configured.get("microPositionMaxLossDollars"), 1.0)
    )
    configured["microPositionMaxLossPct"] = min(
        5.0, _number(configured.get("microPositionMaxLossPct"), 5.0)
    )
    configured["microPositionMinNetEdge"] = max(
        0.02, _number(configured.get("microPositionMinNetEdge"), 0.02)
    )
    configured["microPositionMinConservativeEdge"] = max(
        0.01,
        _number(configured.get("microPositionMinConservativeEdge"), 0.01),
    )
    configured["minimumAddIntervalSeconds"] = max(
        90, int(_number(configured.get("minimumAddIntervalSeconds"), 90))
    )
    configured["minimumHoldSeconds"] = max(
        60, int(_number(configured.get("minimumHoldSeconds"), 60))
    )
    configured["reversalCooldownSeconds"] = max(
        90, int(_number(configured.get("reversalCooldownSeconds"), 90))
    )
    configured["addMinProbabilityImprovement"] = max(
        0.01,
        _number(configured.get("addMinProbabilityImprovement"), 0.01),
    )
    configured["addMinEdgeImprovement"] = max(
        0.001,
        _number(configured.get("addMinEdgeImprovement"), 0.001),
    )
    configured["addSizeFraction"] = min(
        0.25, _number(configured.get("addSizeFraction"), 0.25)
    )
    return configured


def _order_fill_count(order: Optional[Mapping[str, Any]]) -> float:
    if not order:
        return 0.0
    # Fixed-point fields are authoritative, including an explicit zero.  A
    # value such as fill_count_fp="0.00" must not fall through to a stale
    # positive legacy integer field.
    for key in ("fill_count_fp", "filled_count_fp"):
        raw = order.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(value):
            return 0.0
        return max(0.0, value)
    for key in ("fill_count", "filled_count"):
        raw = order.get(key)
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(value):
            return 0.0
        return max(0.0, value)
    status = str(order.get("status") or "").strip().lower()
    if status == "filled":
        for key in ("count_fp", "count"):
            raw = order.get(key)
            if raw in (None, ""):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                return 0.0
            if not math.isfinite(value):
                return 0.0
            return max(0.0, value)
        return 1.0
    return 0.0


class KalshiRobotState:
    @staticmethod
    def _apply_v8_strategy_defaults(state: Dict[str, Any]) -> None:
        """Adopt settlement-aligned v5 controls without deleting audit records."""
        fields = (
            "minNetEdge", "minConservativeEdge", "maxSpread", "maxRelativeSpread",
            "minDepthContracts", "minSecondsToClose", "maxSecondsToClose",
            "minPrice", "maxPrice", "basisReserveBps",
            "minModelProbability", "maxModelMarketGap", "maxVolatilityRatio",
            "maxJumpSigma", "minimumAddIntervalSeconds", "addMinModelProbability",
            "addMinConservativeEdge", "addMinProbabilityImprovement",
            "addMinEdgeImprovement", "addSizeFraction", "exitValueBuffer",
            "minimumExitProfit", "takeProfitScaleOutPct", "stopLossPct",
            "emergencyStopLossPct",
        )

        def update_config(raw: Optional[Mapping[str, Any]], environment: Optional[str] = None) -> Dict[str, Any]:
            configured = normalize_strategy_config(raw or {})
            for field in fields:
                default_value = DEFAULT_STRATEGY_CONFIG[field]
                if field in {
                    "minNetEdge",
                    "minConservativeEdge",
                    "minModelProbability",
                }:
                    configured[field] = max(
                        _number(configured.get(field), default_value),
                        _number(default_value),
                    )
                elif field == "maxPrice":
                    configured[field] = min(
                        _number(configured.get(field), default_value),
                        _number(default_value),
                    )
                else:
                    configured[field] = default_value
            if environment:
                configured["executionMode"] = _execution_environment(environment)
            return configured

        change = {
            "at": _now(),
            "version": 5,
            "summary": (
                "Settlement-aligned v5: BRTI constituent proxy, final-60-second average "
                "horizon, wider staged entry window, marginal liquidity economics, and "
                "bounded scale-ins with durable Kalshi API audit history."
            ),
        }

        def update_changes(strategy: Dict[str, Any]) -> None:
            changes = list(strategy.get("changes") or [])
            if not changes or "settlement-aligned v5" not in str(changes[0].get("summary") or "").lower():
                changes.insert(0, dict(change))
            strategy["changes"] = changes[:50]

        state["config"] = update_config(state.get("config") or {})
        mode_state = state.get("modeState")
        if isinstance(mode_state, dict):
            for environment, bucket in mode_state.items():
                if isinstance(bucket, dict):
                    bucket["config"] = update_config(bucket.get("config") or {}, environment)
                    if isinstance(bucket.get("strategy"), dict):
                        update_changes(bucket["strategy"])
        state["storageVersion"] = max(8, int(state.get("storageVersion") or 0))
        strategy = state.setdefault("strategy", {})
        update_changes(strategy)

    @staticmethod
    def _apply_v9_strategy_defaults(state: Dict[str, Any]) -> None:
        """Adopt official-BRTI v6 model calibration without deleting records."""
        model_fields = (
            "maxSecondsToClose",
            "minPrice",
            "marketBlendWeight",
            "probabilityLogitScale",
        )

        def update_bucket(bucket: Dict[str, Any], environment: Optional[str] = None) -> None:
            configured = normalize_strategy_config(bucket.get("config") or {})
            for field in model_fields:
                configured[field] = DEFAULT_STRATEGY_CONFIG[field]
            if environment:
                configured["executionMode"] = _execution_environment(environment)
            bucket["config"] = configured
            strategy = bucket.setdefault("strategy", {})
            strategy.update({
                "name": "BTC15 Settlement-Aligned v6",
                "version": 6,
                "philosophy": (
                    "Trade only a fresh, executable favorite with positive fee-adjusted and "
                    "uncertainty-adjusted edge. Use Kalshi's official BRTI and final-minute "
                    "settlement average when available, while preserving hold-to-settlement, "
                    "partial exits, and bounded scale-ins."
                ),
                "components": [
                    "official CF Benchmarks BRTI one-second reference stream",
                    "final-60-second settlement-average estimator",
                    "normal-CDF distance and realized-volatility probability model",
                    "Kalshi microprice plus monotone hourly strike-ladder prior",
                    "fee-adjusted and uncertainty-adjusted executable edge",
                    "bounded scale-ins, partial economic exits, and settlement carry",
                    "freshness, depth, spread, exposure, cooldown, and stop gates",
                ],
            })
            changes = list(strategy.get("changes") or [])
            if not changes or "official-brti v6" not in str(changes[0].get("summary") or "").lower():
                changes.insert(0, {
                    "at": _now(),
                    "version": 6,
                    "summary": (
                        "Official-BRTI v6: authenticated one-second settlement reference, "
                        "normal-CDF calibration, wider evidence-backed entry window, and "
                        "monotone hourly strike-ladder pricing."
                    ),
                })
            strategy["changes"] = changes[:50]

        update_bucket(state)
        mode_state = state.get("modeState")
        if isinstance(mode_state, dict):
            for environment, bucket in mode_state.items():
                if isinstance(bucket, dict):
                    update_bucket(bucket, environment)
        state["storageVersion"] = max(9, int(state.get("storageVersion") or 0))

    def _apply_v10_mode_safety(self, state: Dict[str, Any]) -> None:
        """Migrate live accounts to explicit arming and conservative sizing.

        This migration deliberately preserves every decision, fill, and
        settlement record.  It only adds missing configuration fields, raises
        safety floors when an older value is less conservative, and creates a
        durable Real display baseline so pre-AlphaLab account activity is not
        presented as robot history.
        """
        active_environment = _execution_environment(
            state.get("activeEnvironment")
            or (state.get("config") or {}).get("executionMode")
        )
        migrated_at = _now()
        for environment in KALSHI_MODES:
            bucket = self._mode_bucket(state, environment)
            bucket["config"] = _safe_strategy_config(
                bucket.get("config") or {},
                environment,
            )
            arming = dict(bucket.get("arming") or {})
            arming.setdefault("armed", False)
            arming.setdefault("awaitingExplicitEnable", environment == "real")
            arming.setdefault("updatedAt", migrated_at)
            bucket["arming"] = arming
            if (
                environment == "real"
                and not _valid_real_display_baseline(
                    bucket.get("displayBaseline")
                )
            ):
                bucket["displayBaseline"] = {
                    **_new_real_display_baseline(
                        "real_mode_safety_migration"
                    ),
                    "resetAt": migrated_at,
                }

        # A deployment must never silently carry a previously armed Real robot
        # across a mode-safety migration.  The user can explicitly arm it again
        # after reviewing the new baseline and risk settings.
        if active_environment == "real":
            state["enabled"] = False
            real_arming = state["modeState"]["real"]["arming"]
            real_arming.update({
                "armed": False,
                "awaitingExplicitEnable": True,
                "updatedAt": migrated_at,
                "reason": "mode_safety_migration",
            })
        self._sync_mode_mirror(state, active_environment, activate=True)
        state["storageVersion"] = max(10, int(state.get("storageVersion") or 0))

    @staticmethod
    def _apply_v11_micro_account_sizing(state: Dict[str, Any]) -> None:
        """Add bounded one-contract sizing without changing live arming state."""
        migrated_at = _now()

        def update_bucket(bucket: Dict[str, Any], environment: Optional[str] = None) -> None:
            bucket["config"] = _safe_strategy_config(
                bucket.get("config") or {},
                environment,
            )
            strategy = bucket.setdefault("strategy", {})
            strategy.update({
                "name": "BTC15 Settlement-Aligned v7",
                "version": 7,
            })
            components = list(strategy.get("components") or [])
            micro_component = (
                "bounded one-contract small-account sizing after all entry gates clear"
            )
            if micro_component not in components:
                components.append(micro_component)
            strategy["components"] = components
            changes = list(strategy.get("changes") or [])
            if not changes or "small-account sizing v7" not in str(
                changes[0].get("summary") or ""
            ).lower():
                changes.insert(0, {
                    "at": migrated_at,
                    "version": 7,
                    "summary": (
                        "Small-account sizing v7: permit one contract only when "
                        "freshness, liquidity, model, fee-adjusted edge, stronger "
                        "micro-edge floors, cash, and bounded absolute loss all pass."
                    ),
                })
            strategy["changes"] = changes[:50]

        active_environment = _execution_environment(
            state.get("activeEnvironment")
            or (state.get("config") or {}).get("executionMode")
        )
        update_bucket(state, active_environment)
        mode_state = state.get("modeState")
        if isinstance(mode_state, dict):
            for environment, bucket in mode_state.items():
                if isinstance(bucket, dict):
                    update_bucket(bucket, environment)
        state["storageVersion"] = max(11, int(state.get("storageVersion") or 0))

    @staticmethod
    def _apply_v12_quality_scaled_sizing(state: Dict[str, Any]) -> None:
        """Raise only quality-scaled small-account risk without rearming Real."""
        migrated_at = _now()

        def update_bucket(bucket: Dict[str, Any], environment: Optional[str] = None) -> None:
            raw_config = dict(bucket.get("config") or {})
            prior_target = _number(
                raw_config.get("smallAccountRiskTargetPct"),
                1.50,
            )
            # The v11 default was 1.5%. Preserve an explicitly lower or already
            # higher user setting; migrate only the old default used in Real.
            if abs(prior_target - 1.50) <= 1e-9:
                raw_config["smallAccountRiskTargetPct"] = (
                    DEFAULT_STRATEGY_CONFIG["smallAccountRiskTargetPct"]
                )
            bucket["config"] = _safe_strategy_config(raw_config, environment)
            strategy = bucket.setdefault("strategy", {})
            strategy.update({
                "name": "BTC15 Settlement-Aligned v8",
                "version": 8,
            })
            components = list(strategy.get("components") or [])
            quality_component = (
                "quality-scaled fractional sizing with high-price tail-risk haircuts"
            )
            if quality_component not in components:
                components.append(quality_component)
            strategy["components"] = components
            changes = list(strategy.get("changes") or [])
            if not changes or "quality-scaled sizing v8" not in str(
                changes[0].get("summary") or ""
            ).lower():
                changes.insert(0, {
                    "at": migrated_at,
                    "version": 8,
                    "summary": (
                        "Quality-scaled sizing v8: allow a bounded 2% small-account "
                        "target only after stronger edge gates clear, then haircut it "
                        "by signal quality and high-price tail risk before Kelly, cash, "
                        "liquidity, and exposure caps."
                    ),
                })
            strategy["changes"] = changes[:50]

        active_environment = _execution_environment(
            state.get("activeEnvironment")
            or (state.get("config") or {}).get("executionMode")
        )
        update_bucket(state, active_environment)
        mode_state = state.get("modeState")
        if isinstance(mode_state, dict):
            for environment, bucket in mode_state.items():
                if isinstance(bucket, dict):
                    update_bucket(bucket, environment)
        state["storageVersion"] = max(12, int(state.get("storageVersion") or 0))

    @staticmethod
    def _apply_v13_outcome_calibration(state: Dict[str, Any]) -> None:
        """Record dual-market v9 calibration without changing Real arming."""
        migrated_at = _now()

        def update_bucket(
            bucket: Dict[str, Any],
            environment: Optional[str] = None,
        ) -> None:
            bucket["config"] = _safe_strategy_config(
                bucket.get("config") or {},
                environment,
            )
            strategy = bucket.setdefault("strategy", {})
            strategy.update({
                "name": "BTC Dual-Market Outcome-Calibrated v9",
                "version": 9,
                "philosophy": (
                    "Use separate BTC15 and hourly entry envelopes, require "
                    "fee- and uncertainty-adjusted edge, and size only after "
                    "the selected market survives payoff-asymmetry controls."
                ),
            })
            changes = list(strategy.get("changes") or [])
            if not changes or "outcome-calibrated v9" not in str(
                changes[0].get("summary") or ""
            ).lower():
                changes.insert(0, {
                    "at": migrated_at,
                    "version": 9,
                    "summary": (
                        "Outcome-calibrated v9: cap BTC15 favorites at 80c "
                        "with a 1.5pp conservative-edge floor; recalibrate "
                        "KXBTCD with a stronger market prior, compressed "
                        "distance forecast, 20-minute window, 78c cap, and "
                        "larger multiple-candidate penalty."
                    ),
                })
            strategy["changes"] = changes[:50]

        active_environment = _execution_environment(
            state.get("activeEnvironment")
            or (state.get("config") or {}).get("executionMode")
        )
        update_bucket(state, active_environment)
        mode_state = state.get("modeState")
        if isinstance(mode_state, dict):
            for environment, bucket in mode_state.items():
                if isinstance(bucket, dict):
                    update_bucket(bucket, environment)
        state["storageVersion"] = max(
            13,
            int(state.get("storageVersion") or 0),
        )

    @staticmethod
    def _apply_v14_walk_forward_champion(state: Dict[str, Any]) -> None:
        """Record the v10 live champion without changing Real arming state."""
        migrated_at = _now()

        def update_bucket(
            bucket: Dict[str, Any],
            environment: Optional[str] = None,
        ) -> None:
            bucket["config"] = _safe_strategy_config(
                bucket.get("config") or {},
                environment,
            )
            strategy = bucket.setdefault("strategy", {})
            strategy.update({
                "name": "BTC Dual-Market Walk-Forward v10",
                "version": 10,
                "philosophy": (
                    "Route only the walk-forward BTC15 champion while "
                    "retaining the calibrated hourly policy; record relaxed "
                    "frequency challengers as non-routing shadow evidence."
                ),
            })
            components = list(strategy.get("components") or [])
            component = (
                "walk-forward BTC15 70-80c champion with non-routing "
                "frequency challengers"
            )
            if component not in components:
                components.append(component)
            strategy["components"] = components
            changes = list(strategy.get("changes") or [])
            if not changes or "walk-forward champion v10" not in str(
                changes[0].get("summary") or ""
            ).lower():
                changes.insert(0, {
                    "at": migrated_at,
                    "version": 10,
                    "summary": (
                        "Walk-forward champion v10: constrain live BTC15 "
                        "entries to 70-80c while preserving edge, fee, "
                        "liquidity, two-snapshot confirmation, and risk gates; "
                        "keep lower-edge and wider-confirmation candidates "
                        "shadow-only until fresh finalized samples qualify."
                    ),
                })
            strategy["changes"] = changes[:50]

        active_environment = _execution_environment(
            state.get("activeEnvironment")
            or (state.get("config") or {}).get("executionMode")
        )
        update_bucket(state, active_environment)
        mode_state = state.get("modeState")
        if isinstance(mode_state, dict):
            for environment, bucket in mode_state.items():
                if isinstance(bucket, dict):
                    update_bucket(bucket, environment)
        state["storageVersion"] = max(
            14,
            int(state.get("storageVersion") or 0),
        )

    @staticmethod
    def _apply_v15_execution_consistency(state: Dict[str, Any]) -> None:
        """Record the v11 execution upgrade without changing Real arming.

        Signal thresholds remain the validated v10 champion.  Version 11
        aligns fractional sizing with the actual planned IOC depth/cent-rounded
        debit and prioritizes one fresh follow-up for a pending confirmation.
        """
        migrated_at = _now()

        def update_bucket(
            bucket: Dict[str, Any],
            environment: Optional[str] = None,
        ) -> None:
            bucket["config"] = _safe_strategy_config(
                bucket.get("config") or {},
                environment,
            )
            strategy = bucket.setdefault("strategy", {})
            strategy.update({
                "name": "BTC Dual-Market Execution-Consistent v11",
                "version": 11,
                "philosophy": (
                    "Retain the walk-forward BTC15 champion and calibrated "
                    "hourly signals, while making confirmation cadence and "
                    "fractional IOC execution consistent with live risk caps."
                ),
            })
            components = list(strategy.get("components") or [])
            component = (
                "depth-aware fractional IOC sizing with prioritized fresh "
                "confirmation follow-ups"
            )
            if component not in components:
                components.append(component)
            strategy["components"] = components
            changes = list(strategy.get("changes") or [])
            if not changes or "execution-consistent v11" not in str(
                changes[0].get("summary") or ""
            ).lower():
                changes.insert(0, {
                    "at": migrated_at,
                    "version": 11,
                    "summary": (
                        "Execution-consistent v11: preserve validated signal "
                        "thresholds; size against the planned worst IOC depth "
                        "with exact fee/cent rounding, and prioritize one "
                        "fresh second confirmation frame without widening "
                        "the 25-second gate."
                    ),
                })
            strategy["changes"] = changes[:50]

        active_environment = _execution_environment(
            state.get("activeEnvironment")
            or (state.get("config") or {}).get("executionMode")
        )
        update_bucket(state, active_environment)
        mode_state = state.get("modeState")
        if isinstance(mode_state, dict):
            for environment, bucket in mode_state.items():
                if isinstance(bucket, dict):
                    update_bucket(bucket, environment)
        state["storageVersion"] = PAPER_STATE_VERSION

    def __init__(
        self,
        path: Optional[str] = None,
        *,
        state_loader=None,
        state_saver=None,
        enabled_users_loader=None,
        persist_migrations: bool = True,
    ):
        self.path = path
        self._state_loader = state_loader
        self._state_saver = state_saver
        self._enabled_users_loader = enabled_users_loader
        self._persist_migrations = bool(persist_migrations)
        self._lock = threading.RLock()
        self._users: Dict[str, Dict[str, Any]] = {}
        self._last_persisted_monotonic: Dict[str, float] = {}
        self._last_durable_payload: Dict[str, Dict[str, Any]] = {}
        if path and os.path.exists(path) and not callable(self._state_loader):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, Mapping):
                    self._users = {str(key): dict(value) for key, value in payload.items() if isinstance(value, Mapping)}
            except Exception:
                self._users = {}
        migrated = False
        for user_id, state in list(self._users.items()):
            version = int(state.get("storageVersion") or 0)
            if version < 6:
                enabled = bool(state.get("enabled"))
                configured = normalize_strategy_config(state.get("config") or {})
                # The v3 favorite-carry strategy replaces the v2 longshot-prone
                # edge hunter. Old records and old tuned thresholds are not
                # valid evidence for the new entry logic, so both reset to the
                # freshly calibrated defaults.
                for field in (
                    "minNetEdge", "minConservativeEdge", "minPrice", "maxPrice",
                    "minModelProbability", "minSecondsToClose", "maxSecondsToClose",
                    "probabilityLogitScale", "momentumProjectionScale",
                    "basisReserveBps", "marketBlendWeight", "maxVolatilityRatio",
                    "exitProbabilityThreshold", "stopLossPct", "emergencyStopLossPct",
                    "minimumExitProfit", "riskPerTradePct",
                    "executionPriceTolerance",
                ):
                    configured[field] = DEFAULT_STRATEGY_CONFIG[field]
                replacement = self._initial()
                replacement["enabled"] = enabled
                replacement["config"] = configured
                replacement["strategy"]["changes"] = [{
                    "at": _now(),
                    "version": 5,
                    "summary": (
                        "Adopted deterministic BTC15 v4: fee-adjusted entries, bounded scale-ins, "
                        "economic exits, and explicit hold-to-settlement decisions. Removed all "
                        "AI learning, random exploration, contrarian mode, and strategy presets."
                    ),
                }]
                self._users[user_id] = replacement
                migrated = True
            if int(self._users[user_id].get("storageVersion") or 0) < 8:
                self._apply_v8_strategy_defaults(self._users[user_id])
                migrated = True
            if int(self._users[user_id].get("storageVersion") or 0) < PAPER_STATE_VERSION:
                if int(self._users[user_id].get("storageVersion") or 0) < 9:
                    self._apply_v9_strategy_defaults(self._users[user_id])
                if int(self._users[user_id].get("storageVersion") or 0) < 10:
                    self._apply_v10_mode_safety(self._users[user_id])
                if int(self._users[user_id].get("storageVersion") or 0) < 11:
                    self._apply_v11_micro_account_sizing(self._users[user_id])
                if int(self._users[user_id].get("storageVersion") or 0) < 12:
                    self._apply_v12_quality_scaled_sizing(self._users[user_id])
                if int(self._users[user_id].get("storageVersion") or 0) < 13:
                    self._apply_v13_outcome_calibration(self._users[user_id])
                if int(self._users[user_id].get("storageVersion") or 0) < 14:
                    self._apply_v14_walk_forward_champion(self._users[user_id])
                if int(self._users[user_id].get("storageVersion") or 0) < 15:
                    self._apply_v15_execution_consistency(
                        self._users[user_id]
                    )
                migrated = True
        if migrated and self._persist_migrations:
            self._save_all()

    @staticmethod
    def _initial() -> Dict[str, Any]:
        return {
            "storageVersion": PAPER_STATE_VERSION,
            "enabled": False,
            "activeEnvironment": "paper",
            "intervalSeconds": 5,
            "lastRunAt": None,
            "lastError": None,
            "runs": 0,
            "modeState": {},
            "config": {},
            "tradedTickers": [],
            "filledTrades": [],
            "processedSettlements": [],
            "decisions": [],
            "decisionLimit": MAX_DECISION_RECORDS,
            "strategy": {
                "name": "BTC Dual-Market Execution-Consistent v11",
                "version": 11,
                "philosophy": (
                    "Retain the walk-forward BTC15 champion and calibrated "
                    "hourly signals, while making confirmation cadence and "
                    "fractional IOC execution consistent with live risk caps."
                ),
                "components": [
                    "official CF Benchmarks BRTI one-second reference stream",
                    "final-60-second settlement-average estimator",
                    "normal-CDF distance and realized-volatility probability model",
                    "Kalshi microprice plus monotone hourly strike-ladder prior",
                    "fee-adjusted and uncertainty-adjusted executable edge",
                    "bounded scale-ins, partial economic exits, and settlement carry",
                    "freshness, depth, spread, exposure, cooldown, and stop gates",
                    "walk-forward BTC15 70-80c champion with non-routing frequency challengers",
                    "depth-aware fractional IOC sizing with prioritized fresh confirmation follow-ups",
                ],
                "settledSamples": 0,
                "wins": 0,
                "losses": 0,
                "winRate": None,
                "brierScore": None,
                "totalPnl": 0.0,
                "averagePnl": 0.0,
                "bestTrade": None,
                "worstTrade": None,
                "settlementRecords": [],
                "closedTradeRecords": [],
                "closedTradeSamples": 0,
                "closedTradeWinRate": None,
                "closedTradeTotalPnl": 0.0,
                "realizedTradeRecords": [],
                "realizedSamples": 0,
                "realizedWins": 0,
                "realizedLosses": 0,
                "realizedWinRate": None,
                "realizedTotalPnl": 0.0,
                "realizedAveragePnl": 0.0,
                "realizedAverageWin": 0.0,
                "realizedAverageLoss": 0.0,
                "realizedProfitFactor": None,
                "realizedRecoveryMultiple": None,
                "realizedMaxDrawdown": 0.0,
                "equityCurve": [],
                "dailyPnlDate": None,
                "dailyPnl": 0.0,
                "lastEntryTicker": None,
                "lastEntryAt": None,
                "lastExitTicker": None,
                "lastExitAt": None,
                "changes": [{
                    "at": _now(),
                    "version": 11,
                    "summary": (
                        "Execution-consistent v11: preserve validated signal "
                        "thresholds, align fractional IOC sizing with exact "
                        "live costs, and prioritize fresh confirmation follow-ups."
                    ),
                }],
            },
        }

    @staticmethod
    def _mode_template(environment: str, source: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        environment = _execution_environment(environment)
        initial = KalshiRobotState._initial()
        source = dict(source or {})
        config = _safe_strategy_config(
            source.get("config") or {"executionMode": environment},
            environment,
        )
        strategy = copy.deepcopy(source.get("strategy") or initial["strategy"])
        strategy.pop("learning", None)
        return {
            "config": config,
            "strategy": strategy,
            "displayBaseline": copy.deepcopy(source.get("displayBaseline")),
            "arming": copy.deepcopy(source.get("arming") or {
                "armed": False,
                "awaitingExplicitEnable": environment == "real",
                "updatedAt": None,
            }),
            "tradedTickers": list(source.get("tradedTickers") or [])[-MAX_TRADED_TICKERS:],
            "filledTrades": [
                dict(row) for row in list(source.get("filledTrades") or [])
                if _execution_environment((row or {}).get("environment") or environment) == environment
            ][-MAX_SETTLEMENT_RECORDS:],
            "processedSettlements": [
                str(value) for value in list(source.get("processedSettlements") or [])
                if str(value).startswith(f"{environment}:")
            ][-1000:],
            "decisions": [
                dict(row) for row in list(source.get("decisions") or [])
                if _execution_environment((row or {}).get("environment") or environment) == environment
            ][:MAX_DECISION_RECORDS],
            "decisionLimit": MAX_DECISION_RECORDS,
        }

    def _mode_bucket(self, state: Dict[str, Any], environment: str) -> Dict[str, Any]:
        environment = _execution_environment(environment)
        mode_state = state.setdefault("modeState", {})
        if not isinstance(mode_state, dict):
            mode_state = {}
            state["modeState"] = mode_state
        if environment not in mode_state or not isinstance(mode_state.get(environment), Mapping):
            active = _execution_environment(state.get("activeEnvironment") or (state.get("config") or {}).get("executionMode"))
            source = state if environment == active else {"config": {"executionMode": environment}}
            mode_state[environment] = self._mode_template(environment, source)
        bucket = mode_state[environment]
        template = self._mode_template(environment)
        for field, value in template.items():
            bucket.setdefault(field, copy.deepcopy(value))
        bucket["config"] = _safe_strategy_config(
            {**bucket.get("config", {}), "executionMode": environment},
            environment,
        )
        bucket["strategy"].pop("learning", None)
        bucket["decisionLimit"] = MAX_DECISION_RECORDS
        bucket["decisions"] = list(bucket.get("decisions") or [])[:MAX_DECISION_RECORDS]
        return bucket

    def _sync_mode_mirror(
        self,
        state: Dict[str, Any],
        environment: str,
        *,
        activate: bool = False,
    ) -> Dict[str, Any]:
        """Refresh the legacy top-level view without changing modes implicitly.

        Mode buckets are updated by background ticks and settlement reconciliation.
        Those writes must not silently switch the user's active Paper/Real mode.
        Only explicit reads/configuration with ``activate=True`` may select a mode.
        """
        environment = _execution_environment(environment)
        bucket = self._mode_bucket(state, environment)
        active_environment = _execution_environment(
            state.get("activeEnvironment")
            or (state.get("config") or {}).get("executionMode")
        )
        if activate:
            state["activeEnvironment"] = environment
            active_environment = environment
        if environment != active_environment:
            return state
        for field in (
            "config", "strategy", "tradedTickers", "filledTrades", "processedSettlements",
            "decisions", "decisionLimit",
        ):
            state[field] = copy.deepcopy(bucket.get(field))
        return state

    def _state(self, user_id: str) -> Dict[str, Any]:
        key = str(user_id)
        migrated = False
        had_cached_state = key in self._users
        restored_existing_state = False
        if key not in self._users:
            restored = self._state_loader(key) if callable(self._state_loader) else None
            restored_existing_state = isinstance(restored, Mapping)
            durable_compaction_required = bool(
                restored_existing_state
                and self._requires_durable_compaction(restored)
            )
            if restored_existing_state and not durable_compaction_required:
                self._last_durable_payload[key] = (
                    self._durable_comparison_payload(restored)
                )
            self._users[key] = dict(restored) if isinstance(restored, Mapping) else self._initial()
            if int(self._users[key].get("storageVersion") or 0) < 8:
                self._apply_v8_strategy_defaults(self._users[key])
                migrated = True
            if int(self._users[key].get("storageVersion") or 0) < PAPER_STATE_VERSION:
                if int(self._users[key].get("storageVersion") or 0) < 9:
                    self._apply_v9_strategy_defaults(self._users[key])
                if int(self._users[key].get("storageVersion") or 0) < 10:
                    self._apply_v10_mode_safety(self._users[key])
                if int(self._users[key].get("storageVersion") or 0) < 11:
                    self._apply_v11_micro_account_sizing(self._users[key])
                if int(self._users[key].get("storageVersion") or 0) < 12:
                    self._apply_v12_quality_scaled_sizing(self._users[key])
                if int(self._users[key].get("storageVersion") or 0) < 13:
                    self._apply_v13_outcome_calibration(self._users[key])
                if int(self._users[key].get("storageVersion") or 0) < 14:
                    self._apply_v14_walk_forward_champion(self._users[key])
                if int(self._users[key].get("storageVersion") or 0) < 15:
                    self._apply_v15_execution_consistency(self._users[key])
                migrated = True
            migrated = bool(migrated or durable_compaction_required)
        else:
            initial = self._initial()
            for field, value in initial.items():
                self._users[key].setdefault(field, value)
            for field, value in initial["strategy"].items():
                self._users[key]["strategy"].setdefault(field, value)
            strategy = self._users[key]["strategy"]
            self._users[key]["config"] = _safe_strategy_config(
                self._users[key].get("config") or {},
                self._users[key].get("activeEnvironment"),
            )
            # The user-facing decision state is intentionally ephemeral: only
            # the current five-second evaluation is retained. Filled trades are
            # preserved separately so settlement attribution remains correct.
            legacy_decisions = list(self._users[key].get("decisions") or [])
            filled_trades = list(self._users[key].get("filledTrades") or [])
            known_order_ids = {str(row.get("orderId") or row.get("clientOrderId") or "") for row in filled_trades}
            for row in legacy_decisions:
                identity = str(row.get("orderId") or row.get("clientOrderId") or "")
                if row.get("orderFilled") and identity not in known_order_ids:
                    filled_trades.append(dict(row))
                    known_order_ids.add(identity)
            self._users[key]["filledTrades"] = filled_trades[-MAX_SETTLEMENT_RECORDS:]
            self._users[key].pop("learningObservations", None)
            self._users[key].pop("learningExamples", None)
            self._users[key].pop("strategyLibrary", None)
            self._users[key]["decisions"] = legacy_decisions[:MAX_DECISION_RECORDS]
            self._users[key]["decisionLimit"] = MAX_DECISION_RECORDS
            if int(strategy.get("version") or 1) < 2:
                strategy.update({
                    "name": initial["strategy"]["name"],
                    "version": 2,
                    "philosophy": initial["strategy"]["philosophy"],
                    "components": initial["strategy"]["components"],
                })
                changes = list(strategy.get("changes") or [])
                changes.insert(0, {
                    "at": _now(),
                    "version": 2,
                    "summary": "Migrated to conservative edge, full order-book, and account-level risk gates.",
                })
                strategy["changes"] = changes[:50]
        active_environment = _execution_environment(
            self._users[key].get("activeEnvironment")
            or (self._users[key].get("config") or {}).get("executionMode")
        )
        for environment in KALSHI_MODES:
            self._mode_bucket(self._users[key], environment)
        real_bucket = self._mode_bucket(self._users[key], "real")
        if not _valid_real_display_baseline(
            real_bucket.get("displayBaseline")
        ):
            real_bucket["displayBaseline"] = _new_real_display_baseline(
                "invalid_real_display_baseline_repair"
            )
            # A brand-new user will be persisted by its first mutation. Avoid
            # an extra compare-and-swap write during that mutation, while still
            # repairing any cached or durably restored invalid v10 state now.
            migrated = bool(
                migrated or had_cached_state or restored_existing_state
            )
        self._sync_mode_mirror(self._users[key], active_environment, activate=True)
        if migrated and self._persist_migrations:
            self._save_user(key)
        return self._users[key]

    def _persist_user(self, user_id: str) -> None:
        key = str(user_id)
        state = self._users.get(key)
        if not isinstance(state, dict) or not callable(self._state_saver):
            return
        durable_payload = self._durable_payload(state)
        comparison_payload = self._durable_comparison_payload(durable_payload)
        if self._last_durable_payload.get(key) == comparison_payload:
            return
        try:
            saved = self._state_saver(
                key,
                durable_payload,
            )
        except Exception:
            # A failed compare-and-swap means another runtime owns a newer
            # state. Invalidate only this user's cache so the next operation
            # reloads that canonical version without disturbing other users.
            self._users.pop(key, None)
            self._last_durable_payload.pop(key, None)
            raise
        if isinstance(saved, Mapping) and saved.get("version") is not None:
            state["_operationsVersion"] = int(saved.get("version") or 0)
        self._last_durable_payload[key] = comparison_payload
        self._last_persisted_monotonic[key] = time.monotonic()

    @staticmethod
    def _durable_payload(state: Mapping[str, Any]) -> Dict[str, Any]:
        """Return the canonical low-bandwidth representation for Supabase.

        Active-mode mirrors and retired learning fields are reconstructed or
        ignored on load, so serializing them is pure duplicate egress.  Keep
        execution configuration, arming, fills, settlement provenance, risk
        guards, and compare-and-swap metadata unchanged.
        """
        payload = copy.deepcopy(dict(state))
        for field in _TOP_LEVEL_MODE_MIRRORS:
            payload.pop(field, None)
        for field in _EPHEMERAL_TOP_LEVEL_FIELDS:
            payload.pop(field, None)
        for field in _LEGACY_NON_TRADING_FIELDS:
            payload.pop(field, None)
        mode_state = payload.get("modeState")
        if isinstance(mode_state, dict):
            for bucket in mode_state.values():
                if not isinstance(bucket, dict):
                    continue
                durable_order_decisions = [
                    dict(row)
                    for row in list(bucket.get("decisions") or [])
                    if isinstance(row, Mapping)
                    and (
                        row.get("orderSubmitted")
                        or row.get("orderId")
                        or row.get("clientOrderId")
                    )
                ][:MAX_DECISION_RECORDS]
                if durable_order_decisions:
                    bucket["decisions"] = durable_order_decisions
                else:
                    bucket.pop("decisions", None)
                for field in _LEGACY_NON_TRADING_FIELDS:
                    bucket.pop(field, None)
                for field in _EPHEMERAL_MODE_FIELDS:
                    bucket.pop(field, None)
                strategy = bucket.get("strategy")
                if isinstance(strategy, dict):
                    strategy.pop("learning", None)
        return payload

    @classmethod
    def _durable_comparison_payload(
        cls,
        state: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Return durable content without local compare-and-swap metadata."""
        payload = cls._durable_payload(state)
        payload.pop("_operationsVersion", None)
        return payload

    @staticmethod
    def _requires_durable_compaction(state: Mapping[str, Any]) -> bool:
        """Detect one legacy full-row layout without mutating loaded state."""
        if any(field in state for field in _TOP_LEVEL_MODE_MIRRORS):
            return True
        if any(field in state for field in _EPHEMERAL_TOP_LEVEL_FIELDS):
            return True
        if any(field in state for field in _LEGACY_NON_TRADING_FIELDS):
            return True
        mode_state = state.get("modeState")
        if not isinstance(mode_state, Mapping):
            return False
        for bucket in mode_state.values():
            if not isinstance(bucket, Mapping):
                continue
            if any(field in bucket for field in _LEGACY_NON_TRADING_FIELDS):
                return True
            if any(field in bucket for field in _EPHEMERAL_MODE_FIELDS):
                return True
            decisions = bucket.get("decisions")
            if decisions is not None and (
                not isinstance(decisions, list)
                or any(
                    not isinstance(row, Mapping)
                    or not (
                        row.get("orderSubmitted")
                        or row.get("orderId")
                        or row.get("clientOrderId")
                    )
                    for row in decisions
                )
            ):
                return True
            strategy = bucket.get("strategy")
            if isinstance(strategy, Mapping) and "learning" in strategy:
                return True
        return False

    def _save_local_snapshot(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self._users, handle, ensure_ascii=True, separators=(",", ":"))
        os.replace(temporary, self.path)

    def _save_user(self, user_id: str) -> None:
        """Persist one changed durable user and the complete local snapshot."""
        self._persist_user(str(user_id))
        self._save_local_snapshot()

    def _save_all(self) -> None:
        """Persist every cached user for explicit bulk migrations only."""
        if callable(self._state_saver):
            for user_id in list(self._users):
                self._persist_user(str(user_id))
        self._save_local_snapshot()

    def get(self, user_id: str, *, environment: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            state = self._state(user_id)
            snapshot = copy.deepcopy(state)
            if environment is None:
                return snapshot
            selected_environment = _execution_environment(environment)
            bucket = self._mode_bucket(snapshot, selected_environment)
            for field in (
                "config", "strategy", "tradedTickers", "filledTrades",
                "processedSettlements", "decisions", "decisionLimit",
            ):
                snapshot[field] = copy.deepcopy(bucket.get(field))
            snapshot["selectedEnvironment"] = selected_environment
            snapshot["schedulerEnabled"] = bool(state.get("enabled"))
            snapshot["enabled"] = bool(
                state.get("enabled")
                and _execution_environment(state.get("activeEnvironment"))
                == selected_environment
            )
            # activeEnvironment remains the persisted scheduler mode. Merely
            # requesting another bucket must never arm or activate it.
            return snapshot

    def refresh(self, user_id: str, *, environment: Optional[str] = None) -> Dict[str, Any]:
        """Reload authoritative durable state before an irreversible action."""
        with self._lock:
            key = str(user_id)
            authoritative = callable(self._state_loader)
            if authoritative:
                self._users.pop(key, None)
            state = self._state(key)
            snapshot = copy.deepcopy(state)
            if environment is None:
                snapshot["authoritativeRefresh"] = authoritative
                snapshot["durableStateLoaderAvailable"] = authoritative
                return snapshot
            selected_environment = _execution_environment(environment)
            bucket = self._mode_bucket(snapshot, selected_environment)
            for field in (
                "config", "strategy", "tradedTickers", "filledTrades",
                "processedSettlements", "decisions", "decisionLimit",
            ):
                snapshot[field] = copy.deepcopy(bucket.get(field))
            snapshot["selectedEnvironment"] = selected_environment
            snapshot["schedulerEnabled"] = bool(state.get("enabled"))
            snapshot["enabled"] = bool(
                state.get("enabled")
                and _execution_environment(state.get("activeEnvironment"))
                == selected_environment
            )
            snapshot["authoritativeRefresh"] = authoritative
            snapshot["durableStateLoaderAvailable"] = authoritative
            return snapshot

    @property
    def durable_state_loader_available(self) -> bool:
        return callable(self._state_loader)

    def ensure_real_display_baseline(self, user_id: str) -> Dict[str, Any]:
        """Persist a valid fail-closed baseline and return its copy."""
        with self._lock:
            state = self._state(user_id)
            bucket = self._mode_bucket(state, "real")
            baseline = bucket.get("displayBaseline")
            if not _valid_real_display_baseline(baseline):
                baseline = _new_real_display_baseline(
                    "invalid_real_display_baseline_repair"
                )
                bucket["displayBaseline"] = baseline
                self._save_user(user_id)
            return copy.deepcopy(dict(baseline))

    def materialize_real_display_baseline(
        self,
        user_id: str,
        baseline: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Persist the live-money display origin discovered by the API layer.

        State migrations cannot know a Kalshi account's current balance, so
        their structural Real baseline intentionally omits money. Once an
        authenticated portfolio read supplies it, atomically replace that
        placeholder with the exact reset timestamp, equity, and cash values.
        """
        equity_cents = _number(baseline.get("baselineEquityCents"), -1.0)
        cash_cents = _number(baseline.get("baselineCashCents"), -1.0)
        reset_at = str(baseline.get("resetAt") or "").strip()
        if equity_cents < 0.0 or cash_cents < 0.0 or not reset_at:
            raise ValueError("invalid_real_display_baseline_money")
        with self._lock:
            state = self._state(user_id)
            bucket = self._mode_bucket(state, "real")
            current = dict(bucket.get("displayBaseline") or {})
            if (
                current.get("baselineEquityCents") is None
                or current.get("baselineCashCents") is None
            ):
                current = {
                    **dict(baseline),
                    "resetAt": reset_at,
                    "baselineEquityCents": int(round(equity_cents)),
                    "baselineCashCents": int(round(cash_cents)),
                    "environment": "real",
                    "ledgerPreserved": True,
                    "alphaLabOnly": True,
                }
                bucket["displayBaseline"] = current
                self._sync_mode_mirror(
                    state,
                    _execution_environment(
                        state.get("activeEnvironment")
                        or (state.get("config") or {}).get("executionMode")
                    ),
                    activate=True,
                )
                self._save_user(user_id)
            return copy.deepcopy(current)

    def reset_trading_history(self, user_id: str) -> Dict[str, Any]:
        """Clear all fills, settlements, and decisions."""
        with self._lock:
            current = self._state(user_id)
            enabled = bool(current.get("enabled"))
            active_environment = _execution_environment(current.get("activeEnvironment") or (current.get("config") or {}).get("executionMode"))
            config = normalize_strategy_config(current.get("config") or {})
            replacement = self._initial()
            replacement["enabled"] = enabled
            replacement["activeEnvironment"] = active_environment
            replacement["modeState"][active_environment] = self._mode_template(active_environment, {"config": config})
            self._sync_mode_mirror(replacement, active_environment, activate=True)
            self._users[str(user_id)] = replacement
            self._save_user(user_id)
            return copy.deepcopy(replacement)

    def start_fresh_strategy(
        self,
        user_id: str,
        *,
        environment: str = "paper",
        starting_bankroll: float = 1000.0,
        name: str = "",
    ) -> Dict[str, Any]:
        """Start a clean Paper run while leaving Real mode untouched."""
        selected_environment = _execution_environment(environment)
        if selected_environment != "paper":
            raise ValueError("fresh_strategy_reset_is_paper_only")
        bankroll = max(100.0, float(starting_bankroll))

        with self._lock:
            state = self._state(user_id)
            current_bucket = self._mode_bucket(state, selected_environment)
            current_config = normalize_strategy_config(current_bucket.get("config") or {})
            current_config.update({
                "executionMode": selected_environment,
                "paperBankroll": bankroll,
            })

            fresh_bucket = self._mode_template(
                selected_environment,
                {"config": current_config},
            )
            fresh_bucket["strategy"]["changes"] = [{
                "at": _now(),
                "version": 4,
                "source": "fresh_strategy",
                "summary": (
                    f"Started {(name or 'BTC15 Settlement-Aligned v6')[:80]} "
                    f"with a ${bankroll:,.2f} Paper bankroll "
                    "and zero trading history."
                ),
            }]
            state.setdefault("modeState", {})[selected_environment] = fresh_bucket
            self._sync_mode_mirror(
                state,
                selected_environment,
                activate=state.get("activeEnvironment") == selected_environment,
            )
            self._save_user(user_id)
            return copy.deepcopy(state)

    def enabled_users(self):
        with self._lock:
            enabled = {key for key, value in self._users.items() if value.get("enabled")}
            if callable(self._enabled_users_loader):
                enabled.update(
                    str(user_id) for user_id in (self._enabled_users_loader() or [])
                    if str(user_id).strip()
                )
            return sorted(enabled)

    def configure(self, user_id: str, enabled: bool, config: Mapping[str, Any]) -> Dict[str, Any]:
        with self._lock:
            state = self._state(user_id)
            normalized = _safe_strategy_config(
                config,
                (config or {}).get("executionMode"),
            )
            environment = _execution_environment(normalized.get("executionMode"))
            previous_environment = _execution_environment(
                state.get("activeEnvironment")
                or (state.get("config") or {}).get("executionMode")
            )
            mode_changed = previous_environment != environment
            bucket = self._mode_bucket(state, environment)
            bucket["config"] = normalized
            state["lastError"] = None
            bucket["strategy"].pop("learning", None)
            changed_at = _now()
            if (
                environment == "real"
                and not _valid_real_display_baseline(
                    bucket.get("displayBaseline")
                )
            ):
                bucket["displayBaseline"] = {
                    **_new_real_display_baseline("first_real_activation"),
                    "resetAt": changed_at,
                }
            arming = dict(bucket.get("arming") or {})
            if mode_changed:
                # Switching funding sources is a separate action from arming.
                # Even if the same request contains enabled=true, require one
                # subsequent explicit enable request in the newly active mode.
                state["enabled"] = False
                arming.update({
                    "armed": False,
                    "awaitingExplicitEnable": True,
                    "requestedEnableOnSwitch": bool(enabled),
                    "updatedAt": changed_at,
                    "reason": f"mode_switch_from_{previous_environment}",
                })
            else:
                state["enabled"] = bool(enabled)
                arming.update({
                    "armed": bool(enabled),
                    "awaitingExplicitEnable": False,
                    "requestedEnableOnSwitch": False,
                    "updatedAt": changed_at,
                    "reason": "explicit_enable" if enabled else "explicit_disable",
                })
            bucket["arming"] = arming
            self._sync_mode_mirror(state, environment, activate=True)
            self._save_user(user_id)
            return copy.deepcopy(state)

    def record(self, user_id: str, decision: Mapping[str, Any], order: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            state = self._state(user_id)
            edge = dict(decision.get("edge") or {})
            market = dict(decision.get("market") or {})
            environment = _execution_environment(
                (order or {}).get("environment")
                or (decision.get("config") or {}).get("executionMode")
                or state.get("config", {}).get("executionMode")
            )
            bucket = self._mode_bucket(state, environment)
            row = {
                "generatedAt": decision.get("generatedAt") or _now(),
                "environment": environment,
                "ticker": market.get("ticker"),
                "action": decision.get("action"),
                "side": decision.get("side"),
                "signalQuality": decision.get("signalQuality"),
                "fairProbability": edge.get("fairProbability"),
                "price": edge.get("price"),
                "netEdge": edge.get("netEdge"),
                "conservativeEdge": edge.get("conservativeEdge"),
                "recoveryMultiple": edge.get("recoveryMultiple"),
                "recoveryEdgePremium": edge.get("recoveryEdgePremium"),
                "timeStage": (decision.get("model") or {}).get("timeStage"),
                "uncertainty": (decision.get("model") or {}).get("uncertainty"),
                "blockingReasons": list(decision.get("blockingReasons") or []),
                "sizing": {
                    key: (decision.get("sizing") or {}).get(key)
                    for key in (
                        "contracts",
                        "contractsFp",
                        "plannedContractsFp",
                        "contractStep",
                        "maximumLoss",
                        "expectedLoss",
                        "expectedValue",
                        "riskBudget",
                        "standardRiskBudget",
                        "microSizingApplied",
                        "microPositionLossCap",
                        "fractionalSizingApplied",
                        "smallAccountSizingApplied",
                        "allInFee",
                        "roundingFee",
                    )
                },
                "gateSummary": {
                    category: sum(
                        1 for gate in decision.get("gates") or []
                        if gate.get("category") == category and gate.get("status") == "block"
                    )
                    for category in ("data", "signal", "execution", "account")
                },
                "orderId": (order or {}).get("order_id"),
                "clientOrderId": (order or {}).get("client_order_id"),
                "orderStatus": (order or {}).get("status"),
                "fillCount": _order_fill_count(order) if order else None,
                "orderSubmitted": bool(order),
                "orderFilled": _order_fill_count(order) > 0,
                "executionIntent": decision.get("executionIntent"),
                "exitTrigger": (decision.get("exitAnalysis") or {}).get("trigger"),
                "account": dict(decision.get("account") or {}),
                "entryConfirmation": dict(
                    decision.get("entryConfirmation") or {}
                ),
                "protectiveConfirmation": dict(
                    decision.get("protectiveConfirmation") or {}
                ),
                "engine": decision.get("engine"),
                "features": {
                    "selectedSide": decision.get("side"),
                    "selectedPrice": edge.get("price"),
                    "netEdge": edge.get("netEdge"),
                    "conservativeEdge": edge.get("conservativeEdge"),
                    "signalQuality": decision.get("signalQuality"),
                    "uncertainty": (decision.get("model") or {}).get("uncertainty"),
                    "marketYesProbability": (decision.get("model") or {}).get("marketYesProbability"),
                    "rawModelYesProbability": (decision.get("model") or {}).get("rawModelYesProbability"),
                    "originalModelYesProbability": (decision.get("model") or {}).get("originalModelYesProbability"),
                    "modelYesProbability": (decision.get("model") or {}).get("modelYesProbability"),
                    "fairYesProbability": (decision.get("model") or {}).get("fairYesProbability"),
                    "momentum3m": (decision.get("model") or {}).get("momentum3m"),
                    "momentum5m": (decision.get("model") or {}).get("momentum5m"),
                    "momentum15m": (decision.get("model") or {}).get("momentum15m"),
                    "historyQuality": dict((decision.get("model") or {}).get("historyQuality") or {}),
                    "volatilityRatio": (decision.get("model") or {}).get("volatilityRatio"),
                    "jumpSigma": (decision.get("model") or {}).get("jumpSigma"),
                    "distanceBps": (decision.get("model") or {}).get("distanceBps"),
                    "settlementEffectiveHorizonMinutes": (decision.get("model") or {}).get("settlementEffectiveHorizonMinutes"),
                    "referenceModel": (decision.get("model") or {}).get("referenceModel"),
                    "referenceVenueCount": (decision.get("model") or {}).get("referenceVenueCount"),
                    "referenceDispersionBps": (decision.get("model") or {}).get("referenceDispersionBps"),
                    "basisReserveBpsApplied": (decision.get("model") or {}).get("basisReserveBpsApplied"),
                    "spread": market.get("spread"),
                    "edgeEligibleDepth": market.get("edgeEligibleDepth"),
                    "executionLimitPrice": edge.get("executionLimitPrice"),
                    "bookImbalance": market.get("bookImbalance"),
                    "secondsToClose": market.get("secondsToClose"),
                },
                "strategyVersion": bucket["strategy"]["version"],
            }
            ticker = str(market.get("ticker") or "")
            confirmation_family = _entry_confirmation_family(ticker)
            entry_confirmation = dict(
                decision.get("entryConfirmation") or {}
            )
            confirmation_progress_changed = False
            confirmation_reasons = {
                str(value) for value in (decision.get("blockingReasons") or [])
            }
            confirmation_eligible = bool(
                confirmation_family
                and entry_confirmation.get("required")
                and entry_confirmation.get("dataQualityEligible") is not False
                and str(decision.get("side") or "").upper() in {"YES", "NO"}
                and int(_number(entry_confirmation.get("streak"), 0.0)) >= 1
                and confirmation_reasons <= {"entry_confirmation"}
                and (
                    "entry_confirmation" in confirmation_reasons
                    or bool(entry_confirmation.get("confirmed"))
                )
            )
            if confirmation_eligible:
                strategy = bucket["strategy"]
                durable_progress = dict(
                    strategy.get("entryConfirmations") or {}
                )
                previous = dict(
                    durable_progress.get(confirmation_family) or {}
                )
                required_snapshots = max(
                    1,
                    min(
                        5,
                        int(
                            _number(
                                entry_confirmation.get(
                                    "requiredSnapshots"
                                ),
                                2.0,
                            )
                        ),
                    ),
                )
                max_gap_seconds = max(
                    1.0,
                    _number(
                        entry_confirmation.get("maxGapSeconds"),
                        25.0,
                    ),
                )
                progress = {
                    "ticker": ticker,
                    "side": str(decision.get("side") or "").upper(),
                    "generatedAt": row["generatedAt"],
                    "streak": min(
                        required_snapshots,
                        max(
                            1,
                            int(
                                _number(
                                    entry_confirmation.get("streak"),
                                    1.0,
                                )
                            ),
                        ),
                    ),
                    "requiredSnapshots": required_snapshots,
                    "confirmed": bool(
                        entry_confirmation.get("confirmed")
                    ),
                    "dataQualityEligible": True,
                    "maxGapSeconds": max_gap_seconds,
                }
                previous_time = _utc_time_sort_key(
                    previous.get("generatedAt")
                )[1]
                progress_time = _utc_time_sort_key(
                    progress.get("generatedAt")
                )[1]
                confirmation_progress_changed = bool(
                    not previous
                    or previous.get("ticker") != progress["ticker"]
                    or previous.get("side") != progress["side"]
                    or int(_number(previous.get("streak"), 0.0))
                    != progress["streak"]
                    or bool(previous.get("confirmed"))
                    != progress["confirmed"]
                    or int(
                        _number(previous.get("requiredSnapshots"), 0.0)
                    ) != progress["requiredSnapshots"]
                    or previous_time <= 0.0
                    or progress_time < previous_time
                    or progress_time - previous_time > max_gap_seconds
                )
                durable_progress[confirmation_family] = progress
                strategy["entryConfirmations"] = durable_progress

            elif confirmation_family:
                # Only execution cycles call record(); browser observations
                # cannot advance or clear this cursor. A newer disqualified
                # frame breaks the consecutive signal even across restarts.
                # Keeping the old cursor would let a later good frame bridge
                # an intervening stale quote, failed edge, or funding block.
                strategy = bucket["strategy"]
                durable_progress = dict(strategy.get("entryConfirmations") or {})
                previous = dict(durable_progress.get(confirmation_family) or {})
                previous_time = _utc_time_sort_key(previous.get("generatedAt"))[1]
                row_time = _utc_time_sort_key(row.get("generatedAt"))[1]
                if previous and row_time >= previous_time:
                    durable_progress.pop(confirmation_family, None)
                    strategy["entryConfirmations"] = durable_progress
                    confirmation_progress_changed = True

            if (
                order
                and confirmation_family
                and str(decision.get("action") or "").startswith("BUY_")
            ):
                strategy = bucket["strategy"]
                durable_progress = dict(
                    strategy.get("entryConfirmations") or {}
                )
                if confirmation_family in durable_progress:
                    durable_progress.pop(confirmation_family, None)
                    strategy["entryConfirmations"] = durable_progress
                    confirmation_progress_changed = True
            protective_progress_changed = _update_protective_exit_progress(
                bucket, row, decision, order,
            )
            bucket["decisions"].insert(0, row)
            bucket["decisions"] = bucket["decisions"][:MAX_DECISION_RECORDS]
            bucket["decisionLimit"] = MAX_DECISION_RECORDS
            if row["orderFilled"]:
                bucket["filledTrades"].append(dict(row))
                bucket["filledTrades"] = bucket["filledTrades"][-MAX_SETTLEMENT_RECORDS:]
                action = str(row.get("action") or "")
                if action.startswith("BUY_"):
                    bucket["strategy"]["lastEntryTicker"] = row.get("ticker")
                    bucket["strategy"]["lastEntryAt"] = row.get("generatedAt")
                elif action.startswith("SELL_"):
                    # Decision history intentionally keeps only the current
                    # cycle. Persist the latest filled exit separately so the
                    # reversal cooldown survives the next five-second tick,
                    # page changes, and process restarts.
                    bucket["strategy"]["lastExitTicker"] = row.get("ticker")
                    bucket["strategy"]["lastExitAt"] = row.get("generatedAt")
            if _order_fill_count(order) > 0 and ticker and ticker not in bucket["tradedTickers"]:
                bucket["tradedTickers"].append(ticker)
                # Decision history is intentionally ephemeral, but the traded-ticker
                # guard must retain enough history to prevent duplicate entries.
                bucket["tradedTickers"] = bucket["tradedTickers"][-MAX_TRADED_TICKERS:]
            state["lastRunAt"] = _now()
            state["lastError"] = None
            state["runs"] = int(state.get("runs") or 0) + 1
            bucket["lastRunAt"] = state["lastRunAt"]
            # A successful retry clears the mode-local diagnostic as well as
            # the legacy top-level mirror. Deployment handoff CAS conflicts
            # must not remain visible forever after normal cycles resume.
            bucket["lastError"] = None
            bucket["runs"] = int(bucket.get("runs") or 0) + 1
            self._sync_mode_mirror(state, environment)
            material_change = bool(
                order
                or row["orderFilled"]
                or confirmation_progress_changed
                or protective_progress_changed
            )
            # Routine WAIT/HOLD decisions are an in-memory operator view. A
            # full-state heartbeat previously uploaded hundreds of kilobytes
            # to Supabase every minute, even though scheduler liveness and the
            # lease are tracked separately. Persist immediately for an actual
            # order mutation or the tiny confirmation cursor required by the
            # authoritative Real preflight. Feature-heavy decision rows remain
            # excluded from the durable payload, so this restores executable
            # confirmation without restoring the former bandwidth problem.
            if (
                not callable(self._state_saver)
                or material_change
            ):
                self._save_user(user_id)
            return copy.deepcopy(state)

    def reconcile_live_fills(
        self,
        user_id: str,
        fills,
        *,
        environment: str = "real",
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Promote delayed authenticated fills into durable robot provenance."""
        environment = _execution_environment(environment)
        with self._lock:
            state = self._state(user_id)
            bucket = self._mode_bucket(state, environment)
            evidence_rows = (
                list(bucket.get("filledTrades") or [])
                + list(bucket.get("decisions") or [])
            )
            evidence_by_id = {}
            for evidence in evidence_rows:
                if not isinstance(evidence, Mapping):
                    continue
                for identifier in (
                    evidence.get("orderId"),
                    evidence.get("clientOrderId"),
                    evidence.get("order_id"),
                    evidence.get("client_order_id"),
                ):
                    if identifier:
                        evidence_by_id[str(identifier)] = dict(evidence)

            changed = False
            filled_trades = list(bucket.get("filledTrades") or [])
            known_ids = {
                str(row.get("orderId") or row.get("clientOrderId") or "")
                for row in filled_trades
            }
            for fill in fills or []:
                if not isinstance(fill, Mapping) or _order_fill_count(fill) <= 0:
                    continue
                order_id = str(
                    fill.get("order_id")
                    or fill.get("client_order_id")
                    or ""
                )
                evidence = evidence_by_id.get(order_id)
                if not evidence:
                    continue
                if order_id and order_id not in known_ids:
                    promoted = {
                        **evidence,
                        "orderId": fill.get("order_id") or evidence.get("orderId"),
                        "clientOrderId": (
                            fill.get("client_order_id")
                            or evidence.get("clientOrderId")
                        ),
                        "orderStatus": "filled",
                        "fillCount": _order_fill_count(fill),
                        "orderSubmitted": True,
                        "orderFilled": True,
                        "environment": environment,
                    }
                    filled_trades.append(promoted)
                    known_ids.add(order_id)
                    changed = True
            if changed:
                bucket["filledTrades"] = filled_trades[-MAX_SETTLEMENT_RECORDS:]
                self._sync_mode_mirror(state, environment)
                if persist:
                    self._save_user(user_id)
            return copy.deepcopy(state)

    def record_early_close(
        self,
        user_id: str,
        decision: Mapping[str, Any],
        order: Mapping[str, Any],
        *,
        environment: str = "paper",
    ) -> Dict[str, Any]:
        """Persist a realized reduce-only close without fabricating a settlement label.

        Early closes are kept separate from final settlement calibration
        because they do not reveal the eventual binary contract result.
        """
        if not order or _order_fill_count(order) <= 0:
            return self.get(user_id, environment=environment)
        action = str(order.get("action") or decision.get("action") or "").upper()
        if action != "SELL" and not action.startswith("SELL_") and not order.get("reduce_only"):
            return self.get(user_id, environment=environment)
        if order.get("realized_pnl_dollars") is None:
            # Live order acknowledgement is not realized-P/L evidence. It must
            # be reconciled from authenticated fills/settlement data later.
            return self.get(user_id, environment=environment)
        environment = _execution_environment(environment)
        with self._lock:
            state = self._state(user_id)
            bucket = self._mode_bucket(state, environment)
            strategy = bucket["strategy"]
            records = list(strategy.get("closedTradeRecords") or [])
            order_id = str(order.get("order_id") or order.get("client_order_id") or "")
            if order_id and any(str(row.get("orderId") or "") == order_id for row in records):
                return copy.deepcopy(state)
            pnl = _number(order.get("realized_pnl_dollars"), 0.0)
            count = _order_fill_count(order)
            row = {
                "orderId": order_id,
                "ticker": order.get("ticker") or (decision.get("market") or {}).get("ticker"),
                "environment": environment,
                "closedAt": order.get("created_time") or decision.get("generatedAt") or _now(),
                "side": order.get("outcome_side") or decision.get("side"),
                "count": count,
                "entryPrice": (decision.get("exitAnalysis") or {}).get("averageEntryPrice"),
                "exitPrice": order.get("average_price_dollars"),
                "entryFee": order.get("entry_fee_allocated_dollars"),
                "exitFee": order.get("fee_cost_dollars"),
                "pnl": round(pnl, 4),
                "executionIntent": decision.get("executionIntent"),
                "exitTrigger": (decision.get("exitAnalysis") or {}).get("trigger"),
                "exitValueEdge": (decision.get("exitAnalysis") or {}).get("exitValueEdge"),
                "netExitPnlPerContract": (decision.get("exitAnalysis") or {}).get("netExitPnlPerContract"),
                "exitLossFraction": (decision.get("exitAnalysis") or {}).get("exitLossFraction"),
                "settlementLabel": None,
            }
            records.append(row)
            records = records[-MAX_SETTLEMENT_RECORDS:]
            strategy["closedTradeRecords"] = records
            strategy["closedTradeSamples"] = len(records)
            strategy["closedTradeTotalPnl"] = round(sum(_number(item.get("pnl")) for item in records), 4)
            strategy["closedTradeWinRate"] = round(
                sum(1 for item in records if _number(item.get("pnl")) > 0) / len(records),
                4,
            ) if records else None
            self._sync_realized_analytics(strategy, environment)
            self._sync_mode_mirror(state, environment)
            self._save_user(user_id)
            return copy.deepcopy(state)

    @staticmethod
    def _sync_realized_analytics(strategy: Dict[str, Any], environment: str) -> None:
        """Combine settlement and early-exit P/L without mixing calibration labels."""
        environment = _execution_environment(environment)
        settlements = [
            dict(row) for row in strategy.get("settlementRecords") or []
            if _execution_environment(row.get("environment") or environment) == environment
        ]
        closed = [
            dict(row) for row in strategy.get("closedTradeRecords") or []
            if _execution_environment(row.get("environment") or environment) == environment
        ]
        realized = list(settlements)
        for row in closed:
            contracts = _number(row.get("count"))
            cost = _number(row.get("cost") or row.get("positionCost"))
            if cost <= 0:
                cost = _number(row.get("entryPrice")) * contracts
            revenue = _number(row.get("revenue") or row.get("grossProceeds"))
            if revenue <= 0:
                revenue = _number(row.get("exitPrice")) * contracts
            fees = _number(row.get("fees"))
            if fees <= 0:
                fees = _number(row.get("entryFee")) + _number(row.get("exitFee"))
            realized.append({
                "key": f"{environment}:sale:{row.get('orderId') or row.get('ticker')}:{row.get('closedAt')}",
                "environment": environment,
                "ticker": row.get("ticker"),
                "settledAt": row.get("closedAt"),
                "result": None,
                "side": row.get("side"),
                "contracts": round(contracts, 4),
                "revenue": round(revenue, 4),
                "cost": round(cost, 4),
                "fees": round(fees, 4),
                "pnl": round(_number(row.get("pnl")), 4),
                "entryPrice": row.get("entryPrice"),
                "exitPrice": row.get("exitPrice"),
                "exitType": "sale",
                "exitTrigger": row.get("exitTrigger"),
                "netExitPnlPerContract": row.get("netExitPnlPerContract"),
                "exitLossFraction": row.get("exitLossFraction"),
                "won": _number(row.get("pnl")) > 0,
                "matchedFill": True,
                "orderId": row.get("orderId"),
            })
        realized = sorted(
            realized,
            key=lambda row: (
                _utc_time_sort_key(row.get("settledAt")),
                str(row.get("key") or row.get("orderId") or ""),
                str(row.get("ticker") or ""),
            ),
        )[-MAX_SETTLEMENT_RECORDS:]
        cumulative = 0.0
        equity_peak = 0.0
        max_drawdown = 0.0
        curve = []
        for row in realized:
            cumulative = round(cumulative + _number(row.get("pnl")), 4)
            equity_peak = max(equity_peak, cumulative)
            max_drawdown = max(max_drawdown, equity_peak - cumulative)
            curve.append({
                "environment": environment,
                "at": row.get("settledAt"),
                "ticker": row.get("ticker"),
                "pnl": row.get("pnl"),
                "cumulativePnl": cumulative,
                "exitType": row.get("exitType"),
            })
        winning_pnls = [
            _number(row.get("pnl"))
            for row in realized
            if _number(row.get("pnl")) > 0
        ]
        losing_pnls = [
            _number(row.get("pnl"))
            for row in realized
            if _number(row.get("pnl")) < 0
        ]
        wins = len(winning_pnls)
        gross_profit = sum(winning_pnls)
        gross_loss = abs(sum(losing_pnls))
        average_win = gross_profit / len(winning_pnls) if winning_pnls else 0.0
        average_loss = gross_loss / len(losing_pnls) if losing_pnls else 0.0
        strategy["realizedTradeRecords"] = list(reversed(realized))
        strategy["realizedSamples"] = len(realized)
        strategy["realizedWins"] = wins
        strategy["realizedLosses"] = max(0, len(realized) - wins)
        strategy["realizedWinRate"] = round(wins / len(realized), 4) if realized else None
        strategy["realizedTotalPnl"] = round(cumulative, 4)
        strategy["realizedAveragePnl"] = round(cumulative / len(realized), 4) if realized else 0.0
        strategy["realizedAverageWin"] = round(average_win, 4)
        strategy["realizedAverageLoss"] = round(average_loss, 4)
        strategy["realizedProfitFactor"] = (
            round(gross_profit / gross_loss, 4) if gross_loss > 0.0 else None
        )
        strategy["realizedRecoveryMultiple"] = (
            round(average_loss / average_win, 4)
            if average_loss > 0.0 and average_win > 0.0
            else None
        )
        strategy["realizedMaxDrawdown"] = round(max_drawdown, 4)
        strategy["realizedBestTrade"] = max((_number(row.get("pnl")) for row in realized), default=None)
        strategy["realizedWorstTrade"] = min((_number(row.get("pnl")) for row in realized), default=None)
        strategy["equityCurve"] = curve
        strategy["wins"] = strategy["realizedWins"]
        strategy["losses"] = strategy["realizedLosses"]
        strategy["winRate"] = strategy["realizedWinRate"]
        strategy["totalPnl"] = strategy["realizedTotalPnl"]
        strategy["averagePnl"] = strategy["realizedAveragePnl"]
        strategy["bestTrade"] = strategy["realizedBestTrade"]
        strategy["worstTrade"] = strategy["realizedWorstTrade"]
        # The entry loss gate must include both final settlements and
        # authenticated reduce-only sales. Recompute from canonical realized
        # records every time instead of incrementing one code path, making the
        # value idempotent across retries, delayed fills, and reconciliation.
        today = datetime.now(timezone.utc).date().isoformat()
        daily_pnl = 0.0
        for row in realized:
            realized_at = row.get("settledAt") or row.get("closedAt")
            if not realized_at:
                continue
            try:
                parsed = datetime.fromisoformat(
                    str(realized_at).replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed.astimezone(timezone.utc).date().isoformat() == today:
                daily_pnl += _number(row.get("pnl"))
        strategy["dailyPnlDate"] = today
        strategy["dailyPnl"] = round(daily_pnl, 4)

    def error(self, user_id: str, message: str) -> None:
        with self._lock:
            state = self._state(user_id)
            normalized_message = str(message)[:300]
            state["lastRunAt"] = _now()
            state["lastError"] = normalized_message
            bucket = self._mode_bucket(state, state.get("activeEnvironment") or (state.get("config") or {}).get("executionMode"))
            bucket["lastRunAt"] = state["lastRunAt"]
            bucket["lastError"] = state["lastError"]
            # Scheduler readiness already reports the current operational
            # error. Persisting transient public-API failures rewrote the
            # entire trading ledger on every error/recovery edge, which is
            # especially expensive during Kalshi 503/rate-limit oscillation.
            # Local-only mode may still snapshot this operator view.
            if not callable(self._state_saver):
                self._save_user(user_id)

    def reconcile_settlements(
        self,
        user_id: str,
        settlements,
        fills=None,
        *,
        environment: str = "paper",
        persist: bool = True,
    ) -> Dict[str, Any]:
        """Build realized analytics from actually filled and settled contracts."""
        environment = _execution_environment(environment)
        with self._lock:
            state = self._state(user_id)
            bucket = self._mode_bucket(state, environment)
            strategy_before = copy.deepcopy(bucket.get("strategy") or {})
            processed_before = list(bucket.get("processedSettlements") or [])
            processed = {
                str(value) for value in (bucket.get("processedSettlements") or [])
                if str(value).startswith(f"{environment}:")
            }
            changed = False
            legacy_forecast_mode = fills is None
            fill_rows = [
                row for row in list(fills or [])
                if _execution_environment((row or {}).get("environment") or environment) == environment
            ]
            strategy = bucket["strategy"]
            canonical_close_order_ids = {
                str(row.get("order_id") or row.get("client_order_id") or row.get("fill_id") or "")
                for row in fill_rows
                if (
                    _order_fill_count(row) > 0
                    and row.get("realized_pnl_dollars") is not None
                    and (
                        row.get("reduce_only")
                        or str(row.get("action") or "").upper() == "SELL"
                        or str(row.get("action") or "").upper().startswith("SELL_")
                    )
                )
            }
            canonical_fill_tickers = {
                str(row.get("ticker") or row.get("market_ticker") or "")
                for row in fill_rows
                if str(row.get("ticker") or row.get("market_ticker") or "")
            }
            closed_by_order = {
                str(row.get("orderId")): dict(row)
                for row in strategy.get("closedTradeRecords") or []
                if row.get("orderId")
                and not (
                    environment == "paper"
                    and str(row.get("ticker") or "") in canonical_fill_tickers
                    and str(row.get("orderId") or "") not in canonical_close_order_ids
                )
            }
            for fill in fill_rows:
                action = str(fill.get("action") or "").upper()
                if (
                    _order_fill_count(fill) <= 0
                    or fill.get("realized_pnl_dollars") is None
                    or not (fill.get("reduce_only") or action == "SELL" or action.startswith("SELL_"))
                ):
                    continue
                order_id = str(fill.get("order_id") or fill.get("client_order_id") or fill.get("fill_id") or "")
                if not order_id:
                    continue
                count = _order_fill_count(fill)
                allocated_cost = _number(fill.get("position_cost_dollars"))
                gross_proceeds = _number(fill.get("gross_proceeds_dollars"))
                entry_fee = _number(fill.get("entry_fee_allocated_dollars"))
                exit_fee = _number(fill.get("fee_cost_dollars"))
                row = {
                    "orderId": order_id,
                    "ticker": fill.get("ticker") or fill.get("market_ticker"),
                    "environment": environment,
                    "closedAt": fill.get("created_time") or fill.get("ts") or _now(),
                    "side": fill.get("outcome_side"),
                    "count": count,
                    "cost": round(allocated_cost, 4),
                    "revenue": round(gross_proceeds, 4),
                    "fees": round(entry_fee + exit_fee, 4),
                    "entryPrice": round(allocated_cost / count, 6) if count > 0 else None,
                    "exitPrice": fill.get("average_price_dollars") or fill.get("price_dollars"),
                    "entryFee": round(entry_fee, 4),
                    "exitFee": round(exit_fee, 4),
                    "pnl": round(_number(fill.get("realized_pnl_dollars")), 4),
                    "executionIntent": "CLOSE_POSITION",
                    "settlementLabel": None,
                }
                if closed_by_order.get(order_id) != row:
                    closed_by_order[order_id] = row
                    changed = True
            if closed_by_order:
                closed_records = sorted(
                    closed_by_order.values(),
                    key=lambda row: (
                        _utc_time_sort_key(row.get("closedAt")),
                        str(row.get("orderId") or ""),
                        str(row.get("ticker") or ""),
                    ),
                )[-MAX_SETTLEMENT_RECORDS:]
                strategy["closedTradeRecords"] = closed_records
                strategy["closedTradeSamples"] = len(closed_records)
                strategy["closedTradeTotalPnl"] = round(
                    sum(_number(row.get("pnl")) for row in closed_records),
                    4,
                )
                closed_wins = sum(1 for row in closed_records if _number(row.get("pnl")) > 0)
                strategy["closedTradeWinRate"] = (
                    round(closed_wins / len(closed_records), 4) if closed_records else None
                )
            existing_records = {
                str(row.get("key")): dict(row)
                for row in bucket["strategy"].get("settlementRecords") or []
                if row.get("key") and _execution_environment(row.get("environment")) == environment
            }
            ordered_settlements = sorted(
                list(settlements or []),
                key=lambda row: _utc_time_sort_key(
                    row.get("settled_time") or row.get("created_time")
                ),
            )
            canonical_settlement_keys: Dict[str, set[str]] = {}
            for settlement in ordered_settlements:
                ticker = str(settlement.get("ticker") or settlement.get("market_ticker") or "")
                settled_at = str(settlement.get("settled_time") or settlement.get("created_time") or "")
                result = _settlement_result(settlement)
                if ticker and result in {"YES", "NO"}:
                    canonical_settlement_keys.setdefault(ticker, set()).add(
                        f"{environment}:{ticker}:{settled_at}:{result}"
                    )
            if environment == "paper" and canonical_settlement_keys:
                for key, record in list(existing_records.items()):
                    ticker = str(record.get("ticker") or "")
                    if (
                        ticker in canonical_settlement_keys
                        and key not in canonical_settlement_keys[ticker]
                    ):
                        existing_records.pop(key, None)
                        changed = True
            for settlement in ordered_settlements:
                ticker = str(settlement.get("ticker") or settlement.get("market_ticker") or "")
                settled_at = str(settlement.get("settled_time") or settlement.get("created_time") or "")
                result = _settlement_result(settlement)
                settlement_key = f"{environment}:{ticker}:{settled_at}:{result}"
                if not ticker or result not in {"YES", "NO"}:
                    continue
                matching_fills = [
                    row for row in fill_rows
                    if str(row.get("ticker") or row.get("market_ticker") or "") == ticker
                ]
                # A reduce-only SELL is a separate early-close outcome. It
                # cannot also be treated as entry cost for settlement P/L.
                matching_entry_fills = [
                    row for row in matching_fills
                    if str(row.get("action") or "").upper() != "SELL"
                    and not row.get("reduce_only")
                ]
                forecasts = [
                    row for row in list(bucket.get("filledTrades") or [])
                    if _execution_environment(row.get("environment")) == environment
                ]
                if legacy_forecast_mode:
                    forecasts.extend(
                        row for row in (bucket.get("decisions") or [])
                        if _execution_environment(row.get("environment")) == environment
                    )
                forecast = next((
                    row for row in reversed(forecasts)
                    if row.get("ticker") == ticker
                    and (bool(row.get("orderFilled")) or (legacy_forecast_mode and row.get("action") != "WAIT"))
                ), None)
                if not forecast and not matching_entry_fills:
                    processed.add(settlement_key)
                    changed = True
                    continue
                side = str((forecast or {}).get("side") or "").upper()
                if side not in {"YES", "NO"}:
                    fill_side = str((matching_entry_fills[0] if matching_entry_fills else {}).get("outcome_side") or "").upper()
                    side = fill_side if fill_side in {"YES", "NO"} else ""
                side_entry_fills = [
                    row for row in matching_entry_fills
                    if str(row.get("outcome_side") or "").upper() == side
                ]
                side_close_fills = [
                    row for row in matching_fills
                    if (
                        str(row.get("outcome_side") or "").upper() == side
                        and row.get("realized_pnl_dollars") is not None
                        and (
                            row.get("reduce_only")
                            or str(row.get("action") or "").upper() == "SELL"
                            or str(row.get("action") or "").upper().startswith("SELL_")
                        )
                    )
                ]
                entry_fill_count = sum(
                    _order_fill_count(row) for row in side_entry_fills
                )
                close_fill_count = sum(
                    _order_fill_count(row) for row in side_close_fills
                )
                # Kalshi settlement history can retain the original contract
                # count and cost after the position was sold before expiry,
                # while reporting zero settlement revenue.  A canonical SELL
                # fill with complete FIFO cost basis is authoritative evidence
                # that those contracts were already realized.  Do not append a
                # second settlement outcome, and remove a stale duplicate from
                # earlier reconciliation runs so portfolio totals self-heal.
                fully_closed_before_settlement = bool(
                    side in {"YES", "NO"}
                    and entry_fill_count > 0
                    and close_fill_count + 1e-9 >= entry_fill_count
                )
                if fully_closed_before_settlement:
                    if existing_records.pop(settlement_key, None) is not None:
                        changed = True
                    if settlement_key not in processed:
                        processed.add(settlement_key)
                        changed = True
                    continue
                yes_count_present = _has_present(
                    settlement,
                    "yes_count_fp",
                    "yes_count",
                )
                no_count_present = _has_present(
                    settlement,
                    "no_count_fp",
                    "no_count",
                )
                yes_count = _number(_first_present(
                    settlement,
                    "yes_count_fp",
                    "yes_count",
                ))
                no_count = _number(_first_present(
                    settlement,
                    "no_count_fp",
                    "no_count",
                ))
                if side not in {"YES", "NO"}:
                    side = "YES" if yes_count > 0 else "NO" if no_count > 0 else ""
                count = yes_count if side == "YES" else no_count if side == "NO" else 0.0
                selected_count_present = (
                    yes_count_present
                    if side == "YES"
                    else no_count_present
                    if side == "NO"
                    else yes_count_present or no_count_present
                )
                if not selected_count_present:
                    count = sum(
                        _number(_first_present(
                            row,
                            "count_fp",
                            "fill_count_fp",
                            "count",
                            "fill_count",
                        ))
                        for row in matching_entry_fills
                    )
                if count <= 0 and not selected_count_present:
                    count = _number((forecast or {}).get("fillCount"), 1.0 if legacy_forecast_mode else 0.0)
                if count <= 0:
                    if existing_records.pop(settlement_key, None) is not None:
                        changed = True
                    if settlement_key not in processed:
                        processed.add(settlement_key)
                        changed = True
                    continue
                has_financials = any(settlement.get(key) not in (None, "") for key in (
                    "revenue_dollars", "revenue", "yes_total_cost_dollars", "yes_total_cost",
                    "no_total_cost_dollars", "no_total_cost", "fee_cost_dollars", "fee_cost",
                ))
                revenue = _money(settlement, ("revenue_dollars",), ("revenue",))
                yes_cost = _money(settlement, ("yes_total_cost_dollars",), ("yes_total_cost",))
                no_cost = _money(settlement, ("no_total_cost_dollars",), ("no_total_cost",))
                fees = _money(settlement, ("fee_cost_dollars", "fee_cost"), ("fees",))
                if yes_cost + no_cost <= 0 and matching_entry_fills:
                    derived_cost = 0.0
                    derived_fees = 0.0
                    for fill in matching_entry_fills:
                        fill_count = _number(_first_present(
                            fill,
                            "count_fp",
                            "fill_count_fp",
                            "count",
                            "fill_count",
                        ))
                        price = _money(fill, ("yes_price_dollars", "no_price_dollars", "price_dollars"), ("yes_price", "no_price", "price"))
                        derived_cost += fill_count * price
                        derived_fees += _money(fill, ("fee_cost_dollars", "fee_cost", "taker_fees_dollars", "maker_fees_dollars"), ("fees",))
                    if side == "YES":
                        yes_cost = derived_cost
                    elif side == "NO":
                        no_cost = derived_cost
                    fees = max(fees, derived_fees)
                if not has_financials and forecast and count > 0:
                    forecast_price = _number(forecast.get("price"), 0.0)
                    if side == "YES":
                        yes_cost = forecast_price * count
                    elif side == "NO":
                        no_cost = forecast_price * count
                    revenue = count if side == result else 0.0
                pnl = round(revenue - yes_cost - no_cost - fees, 4)
                won = pnl > 0
                probability = _number((forecast or {}).get("fairProbability"), 0.5)
                side_cost = yes_cost if side == "YES" else no_cost if side == "NO" else 0.0
                side_count = yes_count if side == "YES" else no_count if side == "NO" else 0.0
                entry_price = round(side_cost / side_count, 6) if side_count > 0 else None
                exit_price = 1.0 if side and side == result else 0.0 if side else None
                record = {
                    "key": settlement_key,
                    "environment": environment,
                    "ticker": ticker,
                    "settledAt": settled_at,
                    "result": result,
                    "side": side or None,
                    "contracts": round(count, 4),
                    "revenue": round(revenue, 4),
                    "cost": round(yes_cost + no_cost, 4),
                    "fees": round(fees, 4),
                    "pnl": pnl,
                    "entryPrice": entry_price,
                    "exitPrice": exit_price,
                    "exitType": "settlement",
                    "won": won,
                    "fairProbability": round(probability, 6),
                    "matchedFill": bool(matching_entry_fills or forecast),
                }
                existing_records[settlement_key] = record
                if settlement_key in processed:
                    continue
                strategy = bucket["strategy"]
                count = int(strategy.get("settledSamples") or 0) + 1
                previous_brier = strategy.get("brierScore")
                score = (probability - (1.0 if won else 0.0)) ** 2
                strategy["settledSamples"] = count
                strategy["wins"] = int(strategy.get("wins") or 0) + (1 if won else 0)
                strategy["winRate"] = round(strategy["wins"] / count, 4)
                strategy["brierScore"] = round(score if previous_brier is None else (float(previous_brier) * (count - 1) + score) / count, 5)
                try:
                    settlement_time = datetime.fromisoformat(settled_at.replace("Z", "+00:00")) if settled_at else datetime.now(timezone.utc)
                except ValueError:
                    settlement_time = datetime.now(timezone.utc)
                if settlement_time.tzinfo is None:
                    settlement_time = settlement_time.replace(tzinfo=timezone.utc)
                settlement_day = settlement_time.astimezone(timezone.utc).date().isoformat()
                if strategy.get("dailyPnlDate") != settlement_day:
                    strategy["dailyPnlDate"] = settlement_day
                    strategy["dailyPnl"] = 0.0
                strategy["dailyPnl"] = round(float(strategy.get("dailyPnl") or 0.0) + pnl, 4)
                processed.add(settlement_key)
                changed = True

            records = sorted(
                existing_records.values(),
                key=lambda row: (
                    _utc_time_sort_key(row.get("settledAt")),
                    str(row.get("key") or ""),
                    str(row.get("ticker") or ""),
                ),
            )[-MAX_SETTLEMENT_RECORDS:]
            strategy = bucket["strategy"]
            strategy["settlementRecords"] = list(reversed(records))
            strategy["settledSamples"] = len(records)
            if records:
                brier = sum((_number(row.get("fairProbability"), 0.5) - (1.0 if row.get("result") == row.get("side") else 0.0)) ** 2 for row in records) / len(records)
                strategy["brierScore"] = round(brier, 5)
            self._sync_realized_analytics(strategy, environment)
            realized_records = list(reversed(strategy.get("realizedTradeRecords") or []))
            derived_changed = (
                strategy != strategy_before
                or list(bucket.get("processedSettlements") or []) != processed_before
            )
            if changed or derived_changed:
                preserved_processed = [
                    str(value) for value in (bucket.get("processedSettlements") or [])
                    if not str(value).startswith(f"{environment}:")
                ][-1000:]
                bucket["processedSettlements"] = (
                    preserved_processed + sorted(processed)
                )[-1000:]
                self._sync_mode_mirror(state, environment)
                if persist:
                    self._save_user(user_id)
            return copy.deepcopy(state)

__all__ = ["KalshiRobotState"]
