"""Kalshi market data and per-user API connection routes."""

from __future__ import annotations

import base64
import copy
import hashlib
import math
import os
import re
import statistics
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Tuple
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from flask import Blueprint, jsonify, request

try:
    from kalshi_engine import (
        BTC_15M_SERIES,
        evaluate_btc15_contract,
        kalshi_order_cost,
        normalize_strategy_config,
        select_btc15_market,
        _smaller_economic_order_size,
    )
except ImportError:  # pragma: no cover - package-style test imports
    from .kalshi_engine import (
        BTC_15M_SERIES,
        evaluate_btc15_contract,
        kalshi_order_cost,
        normalize_strategy_config,
        select_btc15_market,
        _smaller_economic_order_size,
    )
try:
    from kalshi_robot_state import KalshiRobotState
except ImportError:  # pragma: no cover - package-style test imports
    from .kalshi_robot_state import KalshiRobotState
try:
    from kalshi_paper import KalshiPaperAccountStore, aggregate_taker_sale, executable_bid_levels
except ImportError:  # pragma: no cover - package-style test imports
    from .kalshi_paper import KalshiPaperAccountStore, aggregate_taker_sale, executable_bid_levels
try:
    from kalshi_reference_stream import KalshiReferenceStream
except ImportError:  # pragma: no cover - package-style test imports
    from .kalshi_reference_stream import KalshiReferenceStream


KALSHI_PUBLIC_BASE = "https://external-api.kalshi.com/trade-api/v2"
KALSHI_PUBLIC_FALLBACK_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_PUBLIC_BASES = (KALSHI_PUBLIC_BASE, KALSHI_PUBLIC_FALLBACK_BASE)
KALSHI_NO_ACTIVE_HOURLY_MARKET = "kalshi_no_active_hourly_market"
KALSHI_HOURLY_HELD_MARKET_UNAVAILABLE = "kalshi_hourly_held_market_unavailable"
KALSHI_PUBLIC_RATE_LIMITED = "kalshi_public_rate_limited"
KALSHI_HOURLY_LOOP_INTERVAL_SECONDS = 15.0
KALSHI_HOURLY_RATE_LIMIT_BACKOFF_SECONDS = 60.0
KALSHI_HOURLY_STANDBY_CODES = frozenset({
    KALSHI_NO_ACTIVE_HOURLY_MARKET,
    KALSHI_HOURLY_HELD_MARKET_UNAVAILABLE,
    KALSHI_PUBLIC_RATE_LIMITED,
})
KALSHI_EXECUTION_BLOCKING_WARNINGS = frozenset({
    "kalshi_market_stale",
    "hourly_markets_stale",
    "kalshi_orderbook_stale",
    "kalshi_orderbook_unavailable",
    "hourly_orderbooks_stale",
    "hourly_orderbooks_unavailable",
    "brti_proxy_stale",
    "btc_reference_unavailable",
    "btc_history_stale",
    "kalshi_account_history_incomplete",
    "kalshi_account_orders_incomplete",
    "kalshi_account_positions_incomplete",
})
COINBASE_EXCHANGE_BASE = "https://api.exchange.coinbase.com"
BITSTAMP_BASE = "https://www.bitstamp.net/api/v2"
GEMINI_BASE = "https://api.gemini.com/v1"
KRAKEN_BASE = "https://api.kraken.com/0/public"
KALSHI_ENVIRONMENTS = {
    "production": KALSHI_PUBLIC_BASE,
}
KALSHI_ROUTING_LEASE_TTL_SECONDS = 30
KALSHI_ROUTING_LEASE_TIMEOUT_SECONDS = 5.0
KALSHI_REAL_ACCOUNT_SNAPSHOT_MAX_AGE_SECONDS = 30.0
KALSHI_LIVE_MARKET_STATE_CONFLICTS = frozenset({
    "kalshi_market_not_found",
    "kalshi_market_inactive",
    "kalshi_market_already_closed",
    "kalshi_live_history_clock_unverified",
})
KALSHI_LIVE_ROUTING_STATE_CONFLICTS = frozenset({
    "kalshi_live_cash_changed",
    "kalshi_live_shard_cash_insufficient",
    "kalshi_live_shard_cash_unavailable",
    "kalshi_live_exposure_changed",
    "kalshi_live_open_order_conflict",
    "kalshi_live_position_ownership_conflict",
    "kalshi_live_event_position_conflict",
    "kalshi_live_close_inventory_changed",
    "kalshi_live_voluntary_exit_economics_changed",
    "kalshi_reversal_cooldown_active",
    "kalshi_reentry_confirmation_required",
    "kalshi_entry_confirmation_required",
}) | KALSHI_LIVE_MARKET_STATE_CONFLICTS
RETIRED_KALSHI_BLOCKING_REASONS = frozenset({
    "daily_loss_limit",
})


def _is_btc15_ticker(value: Any) -> bool:
    """Return whether a ticker belongs to the legacy 15-minute robot."""
    return str(value or "").upper().startswith(str(BTC_15M_SERIES).upper())


BTC_HOURLY_SERIES = "KXBTCD"


def _kalshi_event_ticker(
    ticker: Any,
    row: Optional[Mapping[str, Any]] = None,
) -> str:
    """Return the common event scope used by KXBTCD strike contracts."""
    explicit = str(
        (row or {}).get("event_ticker")
        or (row or {}).get("eventTicker")
        or ""
    ).strip()
    if explicit:
        return explicit
    normalized = str(ticker or "").strip()
    if not normalized.upper().startswith(BTC_HOURLY_SERIES):
        return normalized
    # Hourly strikes are commonly suffixed with ``-T65000`` (and older
    # contracts may use ``-B65000``).  Everything before that suffix is the
    # event shared by every strike in the ladder.
    match = re.match(r"^(KXBTCD-.+?)-[TB]\d", normalized, flags=re.IGNORECASE)
    return match.group(1) if match else normalized


def _market_family(value: Any) -> Optional[str]:
    ticker = str(value or "").upper()
    if ticker.startswith(str(BTC_15M_SERIES).upper()):
        return "btc15m"
    if ticker.startswith(BTC_HOURLY_SERIES):
        return "btchourly"
    return None


def _is_supported_kalshi_ticker(value: Any) -> bool:
    return _market_family(value) is not None


def _tag_market_family(row: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(row or {})
    result["market_family"] = _market_family(
        result.get("ticker") or result.get("market_ticker")
    )
    return result


def _pnl_stability_metrics(values: Any) -> Dict[str, Any]:
    """Describe payoff asymmetry and peak-to-trough realized drawdown."""
    pnl_values = [_finite_number(value, 0.0) for value in (values or [])]
    positive = [value for value in pnl_values if value > 0.0]
    negative = [abs(value) for value in pnl_values if value < 0.0]
    average_win = sum(positive) / len(positive) if positive else 0.0
    average_loss = sum(negative) / len(negative) if negative else 0.0
    gross_profit = sum(positive)
    gross_loss = sum(negative)
    peak = 0.0
    cumulative = 0.0
    max_drawdown = 0.0
    for value in pnl_values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return {
        "averageWin": round(average_win, 4),
        "averageLoss": round(average_loss, 4),
        "profitFactor": (
            round(gross_profit / gross_loss, 4)
            if gross_loss > 1e-12
            else None
        ),
        "recoveryMultiple": (
            round(average_loss / average_win, 4)
            if average_win > 1e-12 and average_loss > 0.0
            else None
        ),
        "maxDrawdown": round(max_drawdown, 4),
    }


def _family_performance(strategy: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    records = [
        dict(row) for row in (strategy.get("realizedTradeRecords") or [])
        if isinstance(row, Mapping)
    ]
    output: Dict[str, Dict[str, Any]] = {}
    for family, label in (("btc15m", "BTC 15-minute"), ("btchourly", "BTC hourly strikes")):
        selected = [row for row in records if _market_family(row.get("ticker")) == family]
        pnl_values = [_finite_number(row.get("pnl"), 0.0) for row in selected]
        wins = sum(1 for value in pnl_values if value > 0)
        chronological_rows = sorted(
            selected,
            key=lambda row: _portfolio_record_timestamp(row) or 0.0,
        )
        stability = _pnl_stability_metrics([
            _finite_number(row.get("pnl"), 0.0)
            for row in chronological_rows
        ])
        cumulative = 0.0
        curve = []
        for row, pnl in reversed(list(zip(selected, pnl_values))):
            cumulative = round(cumulative + pnl, 4)
            curve.append({
                "at": row.get("settledAt") or row.get("closedAt"),
                "pnl": round(pnl, 4),
                "cumulativePnl": cumulative,
                "ticker": row.get("ticker"),
            })
        output[family] = {
            "family": family,
            "label": label,
            "samples": len(selected),
            "uniqueMarkets": len({
                str(row.get("ticker") or "") for row in selected if row.get("ticker")
            }),
            "settlementEvents": sum(
                str(row.get("exitType") or "").lower() == "settlement"
                for row in selected
            ),
            "saleEvents": sum(
                str(row.get("exitType") or "").lower() == "sale"
                for row in selected
            ),
            "wins": wins,
            "losses": max(0, len(selected) - wins),
            "winRate": round(wins / len(selected), 4) if selected else None,
            "realizedPnl": round(sum(pnl_values), 4),
            "averagePnl": round(sum(pnl_values) / len(selected), 4) if selected else 0.0,
            **stability,
            "records": [_tag_market_family(row) for row in selected],
            "equityCurve": curve,
        }
    return output


_PORTFOLIO_ANALYTICS_KEYS = (
    "settledSamples", "wins", "losses", "winRate", "totalPnl",
    "averagePnl", "averageWin", "averageLoss", "profitFactor",
    "recoveryMultiple", "maxDrawdown", "bestTrade", "worstTrade",
    "settlementRecords",
    "closedTradeRecords", "realizedTradeRecords", "realizedSamples",
    "realizedWins", "realizedLosses", "realizedWinRate",
    "realizedTotalPnl", "realizedAveragePnl", "realizedBestTrade",
    "realizedWorstTrade", "realizedAverageWin", "realizedAverageLoss",
    "realizedProfitFactor", "realizedRecoveryMultiple",
    "realizedMaxDrawdown", "equityCurve",
)


def _portfolio_analytics(strategy: Mapping[str, Any]) -> Dict[str, Any]:
    analytics = {key: strategy.get(key) for key in _PORTFOLIO_ANALYTICS_KEYS}
    analytics["marketPerformance"] = _family_performance(strategy)
    return analytics


def _portfolio_timestamp(value: Any) -> Optional[float]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _valid_real_display_baseline(value: Any) -> bool:
    """Validate the minimum fail-closed contract for a Real display reset."""
    if not isinstance(value, Mapping):
        return False
    equity_cents = _finite_number(value.get("baselineEquityCents"), None)
    cash_cents = _finite_number(value.get("baselineCashCents"), None)
    return bool(
        _portfolio_timestamp(value.get("resetAt")) is not None
        and str(value.get("environment") or "").strip().lower() == "real"
        and value.get("alphaLabOnly") is True
        and equity_cents is not None
        and cash_cents is not None
        and equity_cents >= 0.0
        and cash_cents >= 0.0
    )


def _portfolio_record_timestamp(row: Mapping[str, Any]) -> Optional[float]:
    return _portfolio_timestamp(
        row.get("settledAt")
        or row.get("closedAt")
        or row.get("settled_time")
        or row.get("created_time")
        or row.get("created_ts")
        or row.get("trade_time")
        or row.get("executed_time")
        or row.get("updated_time")
        or row.get("updated_ts")
    )


def _portfolio_rows_after(rows: Any, reset_timestamp: float) -> list:
    visible = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        row_timestamp = _portfolio_record_timestamp(row)
        if row_timestamp is not None and row_timestamp > reset_timestamp:
            visible.append(dict(row))
    return visible


def _is_alpha_lab_activity(row: Mapping[str, Any]) -> bool:
    return bool(
        row.get("alphaLabManaged")
        or row.get("alphalabManaged")
        or row.get("alphaLabOrder")
        or str(row.get("source") or "").lower() == "alphalab"
    )


def _visible_real_activity(rows: Any, baseline: Mapping[str, Any]) -> list:
    """Expose only post-baseline AlphaLab-owned account activity."""
    reset_timestamp = _portfolio_timestamp(baseline.get("resetAt"))
    if reset_timestamp is None:
        return []
    return [
        dict(row)
        for row in _portfolio_rows_after(rows, reset_timestamp)
        if _is_alpha_lab_activity(row)
    ]


def _portfolio_realized_summary(records: Any, *, baseline_at: Optional[str] = None) -> Dict[str, Any]:
    clean = [dict(row) for row in records or [] if isinstance(row, Mapping)]
    pnl_values = [_finite_number(row.get("pnl"), 0.0) for row in clean]
    wins = sum(value > 0 for value in pnl_values)
    total = round(sum(pnl_values), 4)
    chronological = sorted(
        clean,
        key=lambda row: _portfolio_record_timestamp(row) or 0.0,
    )
    stability = _pnl_stability_metrics([
        _finite_number(row.get("pnl"), 0.0) for row in chronological
    ])
    cumulative = 0.0
    curve = []
    if baseline_at:
        curve.append({
            "at": baseline_at,
            "ticker": "DISPLAY-BASELINE",
            "pnl": 0.0,
            "cumulativePnl": 0.0,
            "environment": None,
            "displayBaseline": True,
        })
    for row in chronological:
        pnl = _finite_number(row.get("pnl"), 0.0)
        cumulative = round(cumulative + pnl, 4)
        curve.append({
            "at": row.get("settledAt") or row.get("closedAt"),
            "ticker": row.get("ticker"),
            "pnl": round(pnl, 4),
            "cumulativePnl": cumulative,
            "exitType": row.get("exitType"),
            "environment": row.get("environment"),
        })
    return {
        "records": clean,
        "samples": len(clean),
        "wins": wins,
        "losses": max(0, len(clean) - wins),
        "winRate": round(wins / len(clean), 4) if clean else None,
        "totalPnl": total,
        "averagePnl": round(total / len(clean), 4) if clean else 0.0,
        **stability,
        "bestTrade": round(max(pnl_values), 4) if pnl_values else None,
        "worstTrade": round(min(pnl_values), 4) if pnl_values else None,
        "equityCurve": curve,
    }


def _portfolio_analytics_after_reset(
    lifetime_analytics: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return a non-destructive, post-baseline analytics projection.

    The source analytics remain the durable lifetime ledger.  Only the object
    returned to the Portfolio view is filtered so users can start a fresh
    visible measurement period without deleting orders, fills or settlements.
    """
    reset_at = str(baseline.get("resetAt") or "").strip()
    reset_timestamp = _portfolio_timestamp(reset_at)
    analytics = dict(lifetime_analytics or {})
    if reset_timestamp is None:
        analytics["displayBaseline"] = {"active": False}
        return analytics

    lifetime_records = [
        dict(row) for row in (lifetime_analytics.get("realizedTradeRecords") or [])
        if isinstance(row, Mapping)
    ]
    visible_records = _portfolio_rows_after(lifetime_records, reset_timestamp)
    realized = _portfolio_realized_summary(visible_records, baseline_at=reset_at)

    lifetime_settlements = lifetime_analytics.get("settlementRecords") or []
    visible_settlements = _portfolio_rows_after(lifetime_settlements, reset_timestamp)
    settled = _portfolio_realized_summary(visible_settlements)
    visible_closed = _portfolio_rows_after(
        lifetime_analytics.get("closedTradeRecords") or [],
        reset_timestamp,
    )

    analytics.update({
        "settledSamples": settled["samples"],
        "wins": settled["wins"],
        "losses": settled["losses"],
        "winRate": settled["winRate"],
        "totalPnl": settled["totalPnl"],
        "averagePnl": settled["averagePnl"],
        "averageWin": settled["averageWin"],
        "averageLoss": settled["averageLoss"],
        "profitFactor": settled["profitFactor"],
        "recoveryMultiple": settled["recoveryMultiple"],
        "maxDrawdown": settled["maxDrawdown"],
        "bestTrade": settled["bestTrade"],
        "worstTrade": settled["worstTrade"],
        "settlementRecords": visible_settlements,
        "closedTradeRecords": visible_closed,
        "realizedTradeRecords": visible_records,
        "realizedSamples": realized["samples"],
        "realizedWins": realized["wins"],
        "realizedLosses": realized["losses"],
        "realizedWinRate": realized["winRate"],
        "realizedTotalPnl": realized["totalPnl"],
        "realizedAveragePnl": realized["averagePnl"],
        "realizedAverageWin": realized["averageWin"],
        "realizedAverageLoss": realized["averageLoss"],
        "realizedProfitFactor": realized["profitFactor"],
        "realizedRecoveryMultiple": realized["recoveryMultiple"],
        "realizedMaxDrawdown": realized["maxDrawdown"],
        "realizedBestTrade": realized["bestTrade"],
        "realizedWorstTrade": realized["worstTrade"],
        "equityCurve": realized["equityCurve"],
        "marketPerformance": _family_performance({"realizedTradeRecords": visible_records}),
        "lifetime": {
            "realizedSamples": len(lifetime_records),
            "realizedTotalPnl": round(sum(
                _finite_number(row.get("pnl"), 0.0) for row in lifetime_records
            ), 4),
        },
        "displayBaseline": {
            **dict(baseline),
            "active": True,
            "archivedRealizedEvents": max(0, len(lifetime_records) - len(visible_records)),
        },
    })
    return analytics


def _observation_analytics(rows) -> Dict[str, Any]:
    """Build a compact, auditable opportunity funnel for both strategy families."""
    clean = []
    for raw_row in rows or []:
        if not isinstance(raw_row, Mapping):
            continue
        row = dict(raw_row)
        raw_blockers = [
            str(reason) for reason in (row.get("blocked_reasons") or [])
            if str(reason)
        ]
        active_blockers = [
            reason for reason in raw_blockers
            if reason not in RETIRED_KALSHI_BLOCKING_REASONS
        ]
        row["blocked_reasons"] = active_blockers
        row["_retired_blockers_only"] = bool(
            raw_blockers and not active_blockers
        )
        clean.append(row)
    result: Dict[str, Any] = {"generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "families": {}}
    for family, prefix, label in (
        ("btc15m", str(BTC_15M_SERIES), "BTC 15-minute"),
        ("btchourly", BTC_HOURLY_SERIES, "BTC hourly strikes"),
    ):
        selected = [row for row in clean if str(row.get("ticker") or "").upper().startswith(prefix)]
        blocker_counts = Counter(
            str(reason)
            for row in selected
            for reason in (row.get("blocked_reasons") or [])
        )
        sources = Counter(
            str(((row.get("features") or {}).get("model") or {}).get("referenceModel") or "unknown")
            for row in selected
        )
        latencies = [
            _finite_number(((row.get("features") or {}).get("dataQuality") or {}).get("snapshotLatencyMs"), -1.0)
            for row in selected
        ]
        latencies = [value for value in latencies if value >= 0]
        positive_net = sum(_finite_number(row.get("net_edge"), -99.0) > 0 for row in selected)
        positive_conservative = sum(
            _finite_number(row.get("conservative_edge"), -99.0) > 0 for row in selected
        )
        entry_ready = sum("entry_window" not in set(row.get("blocked_reasons") or []) for row in selected)
        data_ready = sum(
            not set(row.get("blocked_reasons") or []).intersection({
                "contract_active", "reference_ready", "data_freshness", "history_sample",
            })
            for row in selected
        )
        liquidity_ready = sum(
            not set(row.get("blocked_reasons") or []).intersection({
                "two_sided_quote", "spread", "relative_spread", "depth",
            })
            for row in selected
        )
        routed = sum(str(row.get("action") or "").startswith("BUY_") for row in selected)
        orders = sum(bool(row.get("order_result")) for row in selected)
        near_misses = [
            row for row in selected
            if str(row.get("action") or "") == "WAIT"
            and _finite_number(row.get("conservative_edge"), -99.0) > 0
            and not row.get("_retired_blockers_only")
        ]
        near_misses.sort(
            key=lambda row: _finite_number(row.get("conservative_edge"), -99.0),
            reverse=True,
        )
        timeline_rows = list(reversed(selected[:160]))
        result["families"][family] = {
            "family": family,
            "label": label,
            "observations": len(selected),
            "uniqueMarkets": len({str(row.get("ticker") or "") for row in selected}),
            "latestAt": selected[0].get("observed_at") if selected else None,
            "funnel": {
                "observations": len(selected),
                "dataReady": data_ready,
                "entryWindow": entry_ready,
                "liquidityReady": liquidity_ready,
                "positiveNetEdge": positive_net,
                "positiveConservativeEdge": positive_conservative,
                "routable": routed,
                "orders": orders,
            },
            "blockers": [
                {"key": key, "count": count}
                for key, count in blocker_counts.most_common(10)
            ],
            "referenceSources": [
                {"key": key, "count": count}
                for key, count in sources.most_common()
            ],
            "officialBrtiSamples": sum(
                bool(((row.get("features") or {}).get("model") or {}).get("isOfficialBrti"))
                for row in selected
            ),
            "averageSnapshotLatencyMs": (
                round(sum(latencies) / len(latencies), 1) if latencies else None
            ),
            "edgeTimeline": [
                {
                    "at": row.get("observed_at"),
                    "ticker": row.get("ticker"),
                    "action": row.get("action"),
                    "secondsToClose": row.get("seconds_to_close"),
                    "netEdge": row.get("net_edge"),
                    "conservativeEdge": row.get("conservative_edge"),
                    "signalQuality": row.get("signal_quality"),
                }
                for row in timeline_rows
            ],
            "nearMisses": [
                {
                    "at": row.get("observed_at"),
                    "ticker": row.get("ticker"),
                    "side": row.get("side"),
                    "price": row.get("executable_price"),
                    "netEdge": row.get("net_edge"),
                    "conservativeEdge": row.get("conservative_edge"),
                    "secondsToClose": row.get("seconds_to_close"),
                    "blockingReasons": list(row.get("blocked_reasons") or []),
                }
                for row in near_misses[:8]
            ],
        }
    return result


class KalshiApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int = 502,
        code: str = "kalshi_data_unavailable",
        endpoint: Optional[str] = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.endpoint = endpoint


def _kalshi_response_error_detail(response: Any) -> str:
    """Extract a concise, non-secret diagnostic from a Kalshi error response."""
    if response is None:
        return ""
    try:
        payload = response.json() if hasattr(response, "json") else response
    except Exception:
        payload = None

    def message(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, Mapping):
            code = str(value.get("code") or "").strip()
            detail = str(
                value.get("message")
                or value.get("details")
                or value.get("detail")
                or ""
            ).strip()
            if code and detail:
                return f"{code}: {detail}"
            return detail or code
        if isinstance(value, (list, tuple)):
            return "; ".join(filter(None, (message(item) for item in value)))
        return ""

    detail = ""
    if isinstance(payload, Mapping):
        detail = (
            message(payload.get("error"))
            or message(payload.get("errors"))
            or message(payload.get("message"))
            or message(payload.get("details"))
            or message(payload.get("detail"))
        )
    else:
        detail = message(payload)
    if not detail:
        try:
            detail = str(getattr(response, "text", "") or "").strip()
        except Exception:
            detail = ""
    return " ".join(detail.split())[:240]


def _kalshi_response_error_code(response: Any) -> str:
    """Extract Kalshi's stable nested error code for safe classification."""
    if response is None:
        return ""
    try:
        payload = response.json() if hasattr(response, "json") else response
    except Exception:
        return ""

    def code(value: Any) -> str:
        if isinstance(value, Mapping):
            direct = str(value.get("code") or "").strip()
            if direct:
                return direct
            for nested_key in ("error", "errors"):
                nested = code(value.get(nested_key))
                if nested:
                    return nested
        if isinstance(value, (list, tuple)):
            for item in value:
                nested = code(item)
                if nested:
                    return nested
        return ""

    return code(payload).lower()


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _venue_quote(venue: str, payload: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize a public BTC/USD quote used to approximate CF BRTI."""
    venue = str(venue).lower()
    row: Mapping[str, Any] = payload or {}
    timestamp = None
    if venue == "kraken":
        values = list((row.get("result") or {}).values())
        row = values[0] if values and isinstance(values[0], Mapping) else {}
        bid = _finite_number((row.get("b") or [None])[0], -1.0)
        ask = _finite_number((row.get("a") or [None])[0], -1.0)
        last = _finite_number((row.get("c") or [None])[0], -1.0)
    else:
        bid = _finite_number(row.get("bid"), -1.0)
        ask = _finite_number(row.get("ask"), -1.0)
        last = _finite_number(row.get("price", row.get("last")), -1.0)
        timestamp = row.get("time") or row.get("timestamp")
    if bid > 0 and ask > bid:
        price = (bid + ask) / 2.0
    elif last > 0:
        price = last
    else:
        return None
    return {
        "venue": venue,
        "price": price,
        "bid": bid if bid > 0 else None,
        "ask": ask if ask > 0 else None,
        "timestamp": timestamp,
    }


def _brti_proxy(quotes) -> Optional[Dict[str, Any]]:
    """Robust constituent-venue aggregate; deliberately not labelled official BRTI."""
    clean = [dict(row) for row in quotes or [] if row and _finite_number(row.get("price"), 0.0) > 0]
    if not clean:
        return None
    median = statistics.median(_finite_number(row["price"]) for row in clean)
    deviations = [abs(_finite_number(row["price"]) - median) for row in clean]
    mad = statistics.median(deviations) if deviations else 0.0
    tolerance = max(median * 0.0015, mad * 4.5)
    accepted = [row for row in clean if abs(_finite_number(row["price"]) - median) <= tolerance]
    if not accepted:
        accepted = clean
    proxy = statistics.median(_finite_number(row["price"]) for row in accepted)
    dispersion = (
        (max(_finite_number(row["price"]) for row in accepted)
         - min(_finite_number(row["price"]) for row in accepted))
        / proxy * 10_000.0
        if len(accepted) > 1 and proxy > 0 else 0.0
    )
    return {
        "price": proxy,
        "venueCount": len(accepted),
        "venues": [row["venue"] for row in accepted],
        "rejectedVenues": [row["venue"] for row in clean if row not in accepted],
        "dispersionBps": dispersion,
        "quotes": accepted,
    }


def _book_mid_probability(
    market: Mapping[str, Any],
    book: Optional[Mapping[str, Any]] = None,
) -> Optional[Tuple[float, float]]:
    """Return an executable YES midpoint and a bounded liquidity weight."""
    book = dict(book or {})
    yes_levels = [
        (_finite_number(row[0], -1.0), _finite_number(row[1], 0.0))
        for row in (book.get("yes") or []) if isinstance(row, (list, tuple)) and len(row) >= 2
    ]
    no_levels = [
        (_finite_number(row[0], -1.0), _finite_number(row[1], 0.0))
        for row in (book.get("no") or []) if isinstance(row, (list, tuple)) and len(row) >= 2
    ]
    yes_levels = [row for row in yes_levels if 0 < row[0] < 1 and row[1] > 0]
    no_levels = [row for row in no_levels if 0 < row[0] < 1 and row[1] > 0]
    yes_bid = max(yes_levels, default=(None, 0.0), key=lambda row: row[0])
    no_bid = max(no_levels, default=(None, 0.0), key=lambda row: row[0])
    direct_bid = _finite_number(market.get("yes_bid_dollars"), -1.0)
    direct_ask = _finite_number(market.get("yes_ask_dollars"), -1.0)
    bid = yes_bid[0] if yes_bid[0] is not None else direct_bid
    ask = 1.0 - no_bid[0] if no_bid[0] is not None else direct_ask
    if not (0.0 < bid < 1.0 and 0.0 < ask < 1.0 and ask >= bid):
        return None
    bid_size = yes_bid[1] or _finite_number(market.get("yes_bid_size_fp"), 0.0)
    ask_size = no_bid[1] or _finite_number(market.get("yes_ask_size_fp"), 0.0)
    weight = max(1.0, min(5000.0, math.sqrt(max(1.0, bid_size * ask_size))))
    return _clamp_probability((bid + ask) / 2.0), weight


def _clamp_probability(value: float) -> float:
    return max(0.001, min(0.999, float(value)))


def _monotone_ladder_probabilities(
    markets: list[Mapping[str, Any]],
    books: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Liquidity-weighted PAV fit for a decreasing strike probability curve."""
    points = []
    for market in markets:
        ticker = str(market.get("ticker") or "")
        strike = _finite_number(market.get("floor_strike"), -1.0)
        quote = _book_mid_probability(market, books.get(ticker) or {})
        if ticker and strike > 0 and quote:
            probability, weight = quote
            points.append((strike, ticker, probability, weight))
    points.sort(key=lambda row: row[0])
    blocks = []
    for index, (_strike, _ticker, probability, weight) in enumerate(points):
        blocks.append({
            "start": index,
            "end": index,
            "weight": weight,
            "weighted": probability * weight,
        })
        # For increasing strikes, P(YES) must not increase.
        while len(blocks) >= 2:
            left = blocks[-2]
            right = blocks[-1]
            left_mean = left["weighted"] / left["weight"]
            right_mean = right["weighted"] / right["weight"]
            if left_mean >= right_mean:
                break
            blocks[-2:] = [{
                "start": left["start"],
                "end": right["end"],
                "weight": left["weight"] + right["weight"],
                "weighted": left["weighted"] + right["weighted"],
            }]
    fitted = [0.5] * len(points)
    for block in blocks:
        mean = _clamp_probability(block["weighted"] / block["weight"])
        for index in range(block["start"], block["end"] + 1):
            fitted[index] = mean
    return {
        ticker: {
            "rawProbability": round(raw, 6),
            "smoothedProbability": round(fitted[index], 6),
            "dislocation": round(fitted[index] - raw, 6),
        }
        for index, (_strike, ticker, raw, _weight) in enumerate(points)
    }


def _account_equity_cents(balance: Mapping[str, Any], environment: str) -> float:
    """Return cash plus marked positions for both AlphaLab Paper and Kalshi."""
    cash_cents = _finite_number(balance.get("balance"))
    # Kalshi defines portfolio_value as the current value of positions held,
    # excluding available cash. AlphaLab Paper uses the same decomposition.
    return cash_cents + _finite_number(balance.get("portfolio_value"))


def _live_position_direction(
    position: Any,
    yes_count: Any,
    no_count: Any,
) -> Tuple[Optional[str], float]:
    """Normalize Kalshi's signed and outcome-specific position fields.

    A zero position is flat, not a YES position. Some account responses retain
    settled/closed rows with all counts at zero; those rows must not leak into
    the open-position UI or robot risk context.
    """
    signed_position = _finite_number(position, 0.0)
    outcome_delta = _finite_number(yes_count, 0.0) - _finite_number(no_count, 0.0)
    net = signed_position if abs(signed_position) > 1e-9 else outcome_delta
    if abs(net) <= 1e-9:
        return None, 0.0
    return ("YES" if net > 0 else "NO"), abs(net)


def _parse_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coinbase_btc_candle_params(now: datetime) -> Dict[str, Any]:
    """Request a deterministic, UTC-aligned window within Coinbase's 300-bar cap.

    Include the current partial minute for shock checks; the engine separately
    excludes it from completed-bar history. Explicit bounds avoid relying on
    a lagging upstream default window, without random cache-busting or a new
    per-minute local cache key. Freshness still comes from candle timestamps.
    """
    utc_now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    end = utc_now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    start = end - timedelta(minutes=300)
    return {
        "granularity": 60,
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
    }


def _hourly_reference_policy(
    reference: Mapping[str, Any],
    market: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
    seconds_to_close: Optional[float] = None,
) -> Dict[str, Any]:
    """Select KXBTCD's model reference without leaking 15-minute semantics.

    The authenticated reference stream's generic ``price`` may contain a
    15-minute contract's flat-forward settlement estimate.  Hourly strikes
    instead use the instantaneous official BRTI tick by default.  The observed
    settlement-window average is eligible only during the final 60 seconds of
    a contract whose close timestamp is an actual top-of-hour boundary.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    close_at = _parse_utc(market.get("close_time") or market.get("close_ts"))
    remaining = (
        float(seconds_to_close)
        if seconds_to_close is not None
        else (close_at - now).total_seconds() if close_at else None
    )
    true_top_of_hour = bool(
        close_at
        and close_at.minute == 0
        and close_at.second == 0
        and close_at.microsecond == 0
    )
    inside_final_window = bool(
        remaining is not None and 0.0 <= remaining <= 60.0
    )
    raw_price = _finite_number(reference.get("rawPrice"), None)
    fallback_price = _finite_number(reference.get("price"), None)
    settlement_average = _finite_number(
        reference.get("settlementWindowAverage"),
        None,
    )
    settlement_samples = max(
        0,
        int(_finite_number(reference.get("settlementWindowSamples"), 0.0)),
    )
    official = bool(reference.get("isOfficialBrti"))
    settlement_eligible = bool(
        official
        and true_top_of_hour
        and inside_final_window
        and settlement_average is not None
        and settlement_average > 0.0
        and settlement_samples > 0
    )
    if settlement_eligible:
        selected_price = settlement_average
        selected_source = "settlement_window_average"
        reason = "official_top_of_hour_final_settlement_window"
    elif raw_price is not None and raw_price > 0.0:
        selected_price = raw_price
        selected_source = "raw_price"
        reason = "kxbtcd_uses_instantaneous_reference_by_default"
    else:
        # ``reference.price`` is the generic BTC15 settlement estimator. It is
        # not an admissible KXBTCD strike reference and must never silently
        # substitute for the instantaneous official raw BRTI observation.
        selected_price = None
        selected_source = "unavailable"
        reason = "raw_price_unavailable"
    return {
        "policy": "kxbtcd_raw_reference_v1",
        "selectedSource": selected_source,
        "selectedPrice": selected_price,
        "rawPrice": raw_price,
        "fallbackPrice": fallback_price,
        "settlementWindowAverage": settlement_average,
        "settlementWindowSamples": settlement_samples,
        "officialBrti": official,
        "closeTime": (
            close_at.isoformat().replace("+00:00", "Z") if close_at else None
        ),
        "secondsToClose": remaining,
        "trueTopOfHourClose": true_top_of_hour,
        "insideFinalSettlementWindow": inside_final_window,
        "settlementAverageEligible": settlement_eligible,
        "warning": (
            None if selected_price is not None else "btc_reference_unavailable"
        ),
        "reason": reason,
    }


def _fee_reconciliation(
    decision: Mapping[str, Any],
    order: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compare the decision-time fee estimate with the returned order fee."""
    edge = dict(decision.get("edge") or {})
    sizing = dict(decision.get("sizing") or {})
    action = str(decision.get("action") or "").upper()
    requested = _contract_quantity(
        _first_present(order or {}, "count_fp", "count")
        if _first_present(order or {}, "count_fp", "count") is not None
        else _first_present(
            sizing,
            "plannedContractsFp",
            "contractsFp",
            "contracts",
        )
        if _first_present(
            sizing,
            "plannedContractsFp",
            "contractsFp",
            "contracts",
        ) is not None
        else (decision.get("exitAnalysis") or {}).get("fillableCount")
    )
    filled = _contract_quantity(
        _first_present(
            order or {},
            "fill_count_fp",
            "filled_count_fp",
            "fill_count",
            "filled_count",
        )
    )
    exit_analysis = dict(decision.get("exitAnalysis") or {})
    route_economics = dict(exit_analysis.get("routeEconomics") or {})
    price = _finite_number(
        route_economics.get("minimumExecutionPrice")
        if action.startswith("SELL_") and route_economics.get("allowed") is True
        else edge.get("price"),
        None,
    )
    count_for_estimate = filled if filled > 0 else requested
    fee_policy = dict(decision.get("feePolicy") or {})
    taker_fee_rate = _finite_number(
        (decision.get("config") or {}).get("takerFeeRate"),
        _finite_number(fee_policy.get("takerFeeCoefficient"), 0.07),
    )
    order_cost = (
        kalshi_order_cost(price, count_for_estimate, taker_fee_rate)
        if price is not None and 0.0 < price < 1.0 and count_for_estimate > 0
        else {}
    )
    formula_fee = _finite_number(order_cost.get("allInFee"), None)
    sale = None
    if action.startswith("SELL_") and price is not None and 0.0 < price < 1.0 and count_for_estimate > 0:
        sale = aggregate_taker_sale(
            [(price, count_for_estimate)], count_for_estimate, price,
            fee_multiplier=taker_fee_rate / 0.07,
        )
        formula_fee = sale["fee_cost"]
        order_cost = {
            "tradeFee": sale["trade_fee"],
            "roundingFee": sale["fee_cost"] - sale["trade_fee"],
            "cashCredit": sale["credit_cents"] / 100.0,
        }
    model_fee = (
        max(
            0.0,
            _finite_number(
                _first_present(sizing, "allInFee", "estimatedFee"),
                0.0,
            ),
        )
        if not action.startswith("SELL_") and requested > 0
        and (filled <= 0 or abs(filled - requested) <= 1e-9)
        else None
    )
    exit_fee = _finite_number(exit_analysis.get("estimatedExitFee"), None)
    exit_fillable = _finite_number(exit_analysis.get("fillableCount"), 0.0)
    prorated_exit_fee = (
        formula_fee
        if sale is not None
        else exit_fee * count_for_estimate / exit_fillable
        if action.startswith("SELL_")
        and exit_fee is not None
        and exit_fillable > 0
        and count_for_estimate > 0
        else None
    )
    estimates = [
        value
        for value in (formula_fee, model_fee, prorated_exit_fee)
        if value is not None and value >= 0.0
    ]
    expected = max(estimates) if estimates else None
    actual = (
        max(0.0, _finite_number((order or {}).get("fee_cost_dollars"), 0.0))
        if order
        else None
    )
    delta = actual - expected if actual is not None and expected is not None else None
    return {
        "action": action or "WAIT",
        "requestedCountFp": requested,
        "filledCountFp": filled,
        "expectedPrice": price,
        "takerFeeRate": taker_fee_rate,
        "actualAveragePrice": (
            (order or {}).get("average_price_dollars") if order else None
        ),
        "formulaFeeDollars": formula_fee,
        "tradeFeeDollars": order_cost.get("tradeFee"),
        "roundingFeeDollars": order_cost.get("roundingFee"),
        "expectedCashDebitDollars": order_cost.get("cashDebit"),
        "expectedCashCreditDollars": order_cost.get("cashCredit"),
        "modelFeeDollars": model_fee,
        "estimatedExitFeeDollars": prorated_exit_fee,
        "expectedFeeDollars": expected,
        "actualFeeDollars": actual,
        "feeVarianceDollars": delta,
        "feeVariancePct": (
            delta / expected
            if delta is not None and expected is not None and expected > 1e-12
            else None
        ),
    }


def _maker_shadow_diagnostic(
    decision: Mapping[str, Any],
    fee_policy: Mapping[str, Any],
    strategy_config: Mapping[str, Any],
    *,
    has_position: bool = False,
) -> Dict[str, Any]:
    """Evaluate a resting-price opportunity without ever creating an order."""
    policy = dict(fee_policy or {})
    if not policy.get("available") or not policy.get("makerRateKnown"):
        return {
            "enabled": False,
            "routeAllowed": False,
            "opportunity": False,
            "reason": "maker_fee_rate_unavailable",
            "feePolicy": policy,
        }
    side = str(decision.get("side") or "").upper()
    market = dict(decision.get("market") or {})
    model = dict(decision.get("model") or {})
    maker_price = _finite_number(
        market.get("yesBid") if side == "YES" else market.get("noBid"),
        None,
    )
    fair_yes = _finite_number(model.get("fairYesProbability"), None)
    fair = (
        fair_yes
        if side == "YES"
        else 1.0 - fair_yes
        if side == "NO" and fair_yes is not None
        else None
    )
    coefficient = _finite_number(policy.get("makerFeeCoefficient"), None)
    if (
        side not in {"YES", "NO"}
        or maker_price is None
        or fair is None
        or coefficient is None
        or not 0.0 < maker_price < 1.0
    ):
        return {
            "enabled": False,
            "routeAllowed": False,
            "opportunity": False,
            "reason": "maker_shadow_inputs_unavailable",
            "feePolicy": policy,
        }
    maker_fee = math.ceil(
        max(0.0, coefficient * maker_price * (1.0 - maker_price))
        * 10_000.0
        - 1e-9
    ) / 10_000.0
    uncertainty = max(0.0, _finite_number(model.get("uncertainty"), 0.0))
    net_edge = fair - maker_price - maker_fee
    conservative_edge = net_edge - uncertainty
    minimum = _finite_number(
        strategy_config.get("minConservativeEdge"),
        0.0075,
    )
    model_floor = _finite_number(
        strategy_config.get("minModelProbability"),
        0.64,
    )
    opportunity = bool(
        not has_position
        and fair >= model_floor
        and conservative_edge >= minimum
    )
    return {
        "enabled": True,
        "routeAllowed": False,
        "opportunity": opportunity,
        "reason": (
            "shadow_only_candidate"
            if opportunity
            else "shadow_edge_or_probability_below_floor"
        ),
        "side": side,
        "makerPrice": maker_price,
        "fairProbability": fair,
        "makerFeeCoefficient": coefficient,
        "estimatedMakerFeePerContract": maker_fee,
        "netEdge": net_edge,
        "conservativeEdge": conservative_edge,
        "minimumConservativeEdge": minimum,
        "minimumModelProbability": model_floor,
        "feeType": policy.get("feeType"),
        "feeMultiplier": policy.get("feeMultiplier"),
        "source": policy.get("source"),
    }


def _market_observation(
    environment: str,
    decision: Mapping[str, Any],
    order: Optional[Mapping[str, Any]] = None,
    *,
    source: Optional[str] = None,
    submit_order: bool = False,
) -> Optional[Dict[str, Any]]:
    """Build a compact research sample without erasing routing evidence.

    Routine WAIT decisions remain bounded to one sample per 15-second bucket.
    Routing and read-only callers use separate identities, while confirmation
    transitions and champion frames retain five-second resolution.  An order
    result receives an order-identity key so a later read-only refresh cannot
    replace the only persisted execution record from that cycle.
    """
    market = dict(decision.get("market") or {})
    ticker = str(market.get("ticker") or "").strip()
    if not ticker:
        return None
    observed = _parse_utc(decision.get("generatedAt")) or datetime.now(timezone.utc)
    normalized_source = re.sub(
        r"[^a-z0-9_-]+",
        "_",
        str(
            source
            or ("scheduler" if submit_order else "browser_read_only")
        ).strip().lower(),
    ).strip("_")[:40]
    if not normalized_source:
        normalized_source = (
            "scheduler" if submit_order else "browser_read_only"
        )
    confirmation = dict(decision.get("entryConfirmation") or {})
    champion = dict(
        (decision.get("entryShadow") or {}).get("champion") or {}
    )
    confirmation_transition = bool(
        confirmation
        and (
            confirmation.get("required") is True
            or confirmation.get("confirmed") is True
            or int(_finite_number(confirmation.get("streak"), 0.0)) > 0
        )
    )
    champion_qualifying = champion.get("qualifyingFrame") is True
    observation_policy = "routine_15s"
    bucket_seconds = 15
    bucket_epoch = int(observed.timestamp()) // bucket_seconds * bucket_seconds
    routing_failure = dict(decision.get("routingFailure") or {})
    if routing_failure and not order:
        identity = "|".join((
            str(routing_failure.get("clientOrderId") or ""),
            str(routing_failure.get("code") or ""),
            observed.isoformat(),
        ))
        token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        observation_key = f"{ticker}:{normalized_source}:routing_failure:{token}"
        observation_policy = "routing_failure_unique"
        bucket_seconds = 0
    elif order:
        order_identity = str(
            order.get("order_id")
            or order.get("client_order_id")
            or order.get("fill_id")
            or ""
        ).strip()
        if not order_identity:
            order_identity = "|".join((
                observed.isoformat(),
                str(decision.get("action") or ""),
                str(order.get("action") or ""),
                str(order.get("outcome_side") or ""),
                str(order.get("count_fp") or ""),
                str(order.get("fill_count_fp") or ""),
            ))
        event_token = hashlib.sha256(
            order_identity.encode("utf-8")
        ).hexdigest()[:20]
        observation_key = (
            f"{ticker}:{normalized_source}:order:{event_token}"
        )
        observation_policy = "order_event_unique"
        bucket_seconds = 0
    elif confirmation_transition:
        bucket_seconds = 5
        bucket_epoch = int(observed.timestamp()) // bucket_seconds * bucket_seconds
        transition = (
            f"s{int(_finite_number(confirmation.get('streak'), 0.0))}"
            f"-c{int(confirmation.get('confirmed') is True)}"
        )
        observation_key = (
            f"{ticker}:{normalized_source}:confirmation:"
            f"{transition}:{bucket_epoch}"
        )
        observation_policy = "entry_confirmation_5s"
    elif champion_qualifying:
        bucket_seconds = 5
        bucket_epoch = int(observed.timestamp()) // bucket_seconds * bucket_seconds
        observation_key = (
            f"{ticker}:{normalized_source}:champion:{bucket_epoch}"
        )
        observation_policy = "champion_qualifying_5s"
    else:
        observation_key = (
            f"{ticker}:{normalized_source}:routine:{bucket_epoch}"
        )
    model = dict(decision.get("model") or {})
    edge = dict(decision.get("edge") or {})
    account = dict(decision.get("account") or {})
    return {
        "environment": _execution_mode(environment),
        "ticker": ticker,
        "observation_key": observation_key,
        "observed_at": observed.isoformat().replace("+00:00", "Z"),
        "action": str(decision.get("action") or "WAIT"),
        "side": decision.get("side"),
        "execution_intent": decision.get("executionIntent"),
        "signal_quality": int(_finite_number(decision.get("signalQuality"), 0.0)),
        "seconds_to_close": int(_finite_number(market.get("secondsToClose"), -1.0)),
        "model_yes_probability": model.get("modelYesProbability"),
        "fair_yes_probability": model.get("fairYesProbability"),
        "executable_price": edge.get("price"),
        "net_edge": edge.get("netEdge"),
        "conservative_edge": edge.get("conservativeEdge"),
        "spread": market.get("spread"),
        "book_imbalance": market.get("bookImbalance"),
        "blocked_reasons": [
            str(reason)[:80] for reason in (decision.get("blockingReasons") or [])[:20]
        ],
        "features": {
            "observation": {
                "source": normalized_source,
                "submitOrder": bool(submit_order),
                "samplingPolicy": observation_policy,
                "bucketSeconds": bucket_seconds,
                "hasOrderResult": bool(order),
            },
            "market": {
                key: market.get(key)
                for key in (
                    "status", "yesBid", "yesAsk", "noBid", "noAsk",
                    "yesAskDepth", "noAskDepth", "selectedDepth",
                    "edgeEligibleDepth", "referenceAgeSeconds",
                    "exchangeIndex",
                )
            },
            "model": {
                key: model.get(key)
                for key in (
                    "spot", "strike", "distanceBps", "momentum3m",
                    "momentum15m", "volatilityRatio", "jumpSigma",
                    "marketYesProbability", "uncertainty", "sampleSize",
                    "settlementEffectiveHorizonMinutes", "referenceModel",
                    "referenceVenueCount", "referenceDispersionBps", "historyQuality",
                    "basisReserveBpsApplied", "isOfficialBrti",
                    "referenceRawPrice", "settlementWindowAverage",
                    "settlementWindowSamples", "settlementWindowProgress",
                    "rawMarketYesProbability", "ladderRawProbability",
                    "ladderSmoothedProbability", "ladderDislocation",
                )
            },
            "execution": {
                "topPrice": edge.get("price"),
                "marginalLimitPrice": edge.get("executionLimitPrice"),
                "feePerContract": edge.get("feePerContract"),
                "adaptiveEdgePremium": edge.get("adaptiveEdgePremium"),
                "plannedContractsFp": (
                    decision.get("sizing") or {}
                ).get("plannedContractsFp"),
                "contractsFp": (decision.get("sizing") or {}).get(
                    "contractsFp"
                ),
                "contractStep": (decision.get("sizing") or {}).get(
                    "contractStep"
                ),
                "fractionalSizingApplied": (
                    decision.get("sizing") or {}
                ).get("fractionalSizingApplied"),
            },
            "account": {
                key: account.get(key)
                for key in (
                    "heldSide", "heldCount", "cashAvailable",
                    "portfolioExposure", "currentMarketExposure",
                    "exchangeIndex", "aggregateCashAvailable",
                    "shardCashAvailable", "shardCashKnown", "fundingStatus",
                )
            },
            "positionManagement": dict(decision.get("positionManagement") or {}),
            "dataQuality": dict(decision.get("dataQuality") or {}),
            "exitAnalysis": {
                key: (decision.get("exitAnalysis") or {}).get(key)
                for key in (
                    "heldProbability", "netExitValuePerContract", "exitValueEdge",
                    "netExitPnlPerContract", "exitLossFraction", "trigger",
                    "breakEvenExitValuePerContract", "estimatedExitFee",
                    "expectedHoldValuePerContract", "expectedHoldPnlPerContract",
                    "holdVsExitExpectedDeltaPerContract", "counterfactualPolicy",
                    "protectiveConfirmation", "lossExitAuthorizedAfterConfirmation", "routeEconomics", "routeQuote",
                )
            },
            "candidateLadder": dict(decision.get("candidateDiagnostics") or {}),
            "entryConfirmation": dict(decision.get("entryConfirmation") or {}),
            "entryShadow": dict(decision.get("entryShadow") or {}),
            "feeReconciliation": _fee_reconciliation(decision, order),
            "feePolicy": dict(decision.get("feePolicy") or {}),
            "makerShadow": dict(decision.get("makerShadow") or {}),
            "shardFunding": dict(decision.get("shardFunding") or {}),
            "routingFailure": routing_failure,
        },
        "order_result": ({
            key: order.get(key)
            for key in (
                "order_id", "client_order_id", "status", "action",
                "outcome_side", "count_fp", "fill_count_fp",
                "average_price_dollars", "fee_cost_dollars",
                "trade_fee_dollars", "rounding_fee_dollars",
                "rounding_rebate_dollars", "realized_pnl_dollars",
            )
        } if order else None),
    }


def _open_order_remaining(row: Mapping[str, Any]) -> float:
    explicit = row.get("remaining_count_fp")
    if explicit in (None, ""):
        explicit = row.get("remaining_count")
    if explicit not in (None, ""):
        return max(0.0, _finite_number(explicit, 0.0))
    requested = _finite_number(
        _first_present(row, "count_fp", "count", "contracts"),
        0.0,
    )
    filled = _finite_number(
        _first_present(
            row,
            "fill_count_fp",
            "filled_count_fp",
            "fill_count",
            "filled_count",
        ),
        0.0,
    )
    return max(0.0, requested - filled)


def _open_order_exposure(row: Mapping[str, Any]) -> float:
    """Conservatively estimate the outstanding notional of one live order."""
    for key in (
        "remaining_exposure_dollars",
        "market_exposure_dollars",
        "notional_dollars",
    ):
        if row.get(key) not in (None, ""):
            return abs(_finite_number(row.get(key), 0.0))
    for key in ("remaining_exposure", "market_exposure", "notional"):
        if row.get(key) not in (None, ""):
            return abs(_finite_number(row.get(key), 0.0)) / 100.0
    remaining = _open_order_remaining(row)
    if remaining <= 0.0:
        return 0.0
    price = None
    for key in (
        "limit_price_dollars",
        "average_price_dollars",
        "price_dollars",
        "yes_price_dollars",
        "no_price_dollars",
        "price",
    ):
        if row.get(key) not in (None, ""):
            price = abs(_finite_number(row.get(key), 0.0))
            if key == "price" and price > 1.0:
                price /= 100.0
            break
    # Unknown-price open orders reserve the full $1 payout per contract. This
    # intentionally fails closed instead of understating event exposure.
    return remaining * (price if price is not None and price > 0.0 else 1.0)


def _exchange_shard_index(value: Any) -> Optional[int]:
    """Only an explicit nonnegative integer identifies a collateral shard."""
    if isinstance(value, bool):
        return None
    number = _finite_number(value, None)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _shard_cash_dollars(balance: Mapping[str, Any], exchange_index: Any) -> Optional[float]:
    """Kalshi breakdown.balance is DOLLARS, unlike top-level balance cents.

    Missing, duplicate, or malformed rows are unknown, never aggregate cash.
    Restricted API keys omit the breakdown; the final router reads a scoped
    balance for those keys instead.
    """
    index = _exchange_shard_index(exchange_index)
    rows = balance.get("balance_breakdown")
    if index is None or not isinstance(rows, list):
        return None
    matches = [
        row for row in rows
        if isinstance(row, Mapping)
        and _exchange_shard_index(row.get("exchange_index")) == index
    ]
    if len(matches) != 1:
        return None
    value = _finite_number(matches[0].get("balance"), None)
    return value if value is not None and value >= 0 else None


def _shard_funding_context(balance: Mapping[str, Any], exchange_index: Any) -> Dict[str, Any]:
    index = _exchange_shard_index(exchange_index)
    cash = _shard_cash_dollars(balance, index)
    aggregate = _finite_number(balance.get("balance_dollars"), None)
    if aggregate is None:
        aggregate = _finite_number(balance.get("balance"), 0.0) / 100.0
    return {
        "exchangeIndex": index,
        "aggregateCashAvailable": max(0.0, aggregate),
        "shardCashAvailable": cash,
        "shardCashKnown": cash is not None,
        "fundingStatus": (
            "funded" if cash is not None and cash > 0
            else "empty" if cash == 0
            else "unverified"
        ),
    }


def _paper_account_context(
    portfolio: Mapping[str, Any],
    state: Mapping[str, Any],
    ticker: str,
    bankroll: float,
    *,
    event_ticker: Optional[str] = None,
    exchange_index: Optional[Any] = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    positions = list(portfolio.get("positions") or [])
    orders = list(portfolio.get("orders") or [])
    fills = list(portfolio.get("fills") or [])
    target_event = str(event_ticker or _kalshi_event_ticker(ticker)).strip()
    is_hourly = _market_family(ticker) == "btchourly"

    def in_risk_scope(row: Mapping[str, Any]) -> bool:
        row_ticker = str(row.get("ticker") or row.get("market_ticker") or "")
        if not is_hourly:
            return row_ticker == ticker
        return _kalshi_event_ticker(row_ticker, row) == target_event

    exact_positions = [
        row for row in positions
        if str(row.get("ticker") or row.get("market_ticker") or "") == ticker
        and abs(_finite_number(_first_present(row, "position_fp", "position"))) > 1e-9
    ]
    event_positions = [
        row for row in positions
        if in_risk_scope(row)
        and abs(_finite_number(
            _first_present(
                row,
                "position_fp",
                "net_count_fp",
                "yes_count_fp",
                "no_count_fp",
                "position",
            )
        )) > 1e-9
    ]
    terminal_order_states = {
        "canceled", "cancelled", "closed", "executed", "filled", "expired",
        "rejected",
    }
    open_orders = [
        row for row in orders
        if str(row.get("status") or "").lower() not in terminal_order_states
        and _open_order_remaining(row) > 0.0
    ]
    event_orders = [row for row in open_orders if in_risk_scope(row)]
    position_exposure = sum(
        abs(_finite_number(
            row.get("market_exposure_dollars")
            or row.get("market_exposure")
        ))
        for row in positions
    )
    open_order_exposure = sum(_open_order_exposure(row) for row in open_orders)
    portfolio_exposure = sum(
        (position_exposure, open_order_exposure)
    )
    current_position_exposure = sum(
        abs(_finite_number(row.get("market_exposure_dollars") or row.get("market_exposure")))
        for row in event_positions
    )
    current_order_exposure = sum(
        _open_order_exposure(row) for row in event_orders
    )
    current_market_exposure = current_position_exposure + current_order_exposure
    daily_order_ids = {
        str(row.get("order_id") or row.get("fill_id") or "")
        for row in fills
        if (_parse_utc(row.get("created_time")) or datetime.min.replace(tzinfo=timezone.utc)).date() == now.date()
    }
    strategy = dict(state.get("strategy") or {})
    daily_pnl = (
        _finite_number(strategy.get("dailyPnl"))
        if strategy.get("dailyPnlDate") == now.date().isoformat()
        else 0.0
    )
    balance = dict(portfolio.get("balance") or {})
    cash_available = _finite_number(balance.get("balance")) / 100.0
    return {
        "bankroll": bankroll,
        "cashAvailable": max(0.0, cash_available),
        # Keep aggregate-capital strategy/shadow evaluation independent of
        # funding logistics. A separate real-entry gate caps shard-local cash
        # while retaining the intended action as opportunity evidence.
        **_shard_funding_context(balance, exchange_index),
        "portfolioExposure": portfolio_exposure,
        "currentMarketExposure": current_market_exposure,
        "currentTickerExposure": sum(
            abs(_finite_number(
                row.get("market_exposure_dollars")
                or row.get("market_exposure")
            ))
            for row in exact_positions
        ),
        "currentEventExposure": current_market_exposure,
        "currentEventPositionExposure": current_position_exposure,
        "currentEventOpenOrderExposure": current_order_exposure,
        "eventTicker": target_event if is_hourly else ticker,
        "hasPosition": bool(exact_positions),
        "hasEventPosition": bool(event_positions),
        "hasOpenOrder": bool(event_orders),
        "openOrderTickers": sorted({
            str(row.get("ticker") or row.get("market_ticker") or "")
            for row in event_orders
            if row.get("ticker") or row.get("market_ticker")
        }),
        "alreadyTraded": ticker in set(state.get("tradedTickers") or []),
        "dailyTrades": len(daily_order_ids - {""}),
        "dailyPnl": daily_pnl,
    }


def _contract_quantity(value: Any, default: float = 0.0) -> float:
    """Floor a contract quantity to Kalshi's 0.01 fixed-point quantum."""
    parsed = max(0.0, _finite_number(value, default))
    return math.floor(parsed * 100.0 + 1e-9) / 100.0


def _position_side_and_count(portfolio: Mapping[str, Any], ticker: str) -> Tuple[Optional[str], float]:
    for row in list(portfolio.get("positions") or []):
        if str(row.get("ticker") or row.get("market_ticker") or "") != ticker:
            continue
        if _execution_mode(portfolio.get("environment")) == "real":
            managed_side = str(
                row.get("alphaLabManagedSide")
                or row.get("net_side")
                or ""
            ).upper()
            managed_count = _finite_number(
                row.get("alphaLabManagedCount"),
                0.0,
            )
            if managed_side in {"YES", "NO"} and managed_count > 0:
                return managed_side, _contract_quantity(managed_count)
            return None, 0.0
        yes_count = _finite_number(
            _first_present(row, "yes_count_fp", "yes_count"), 0.0
        )
        no_count = _finite_number(
            _first_present(row, "no_count_fp", "no_count"), 0.0
        )
        # Older Paper ledgers may contain complementary YES/NO hedges from the
        # pre-sell close implementation. Treat only their residual as current
        # directional exposure; all new exits are reduce-only sales.
        net_count = yes_count - no_count
        if abs(net_count) > 1e-9:
            return ("YES" if net_count > 0 else "NO"), _contract_quantity(abs(net_count))
        if yes_count > 0 or no_count > 0:
            return None, 0.0
        position = _finite_number(
            _first_present(row, "position_fp", "position"), 0.0
        )
        if position > 0:
            return "YES", _contract_quantity(abs(position))
        if position < 0:
            return "NO", _contract_quantity(abs(position))
    return None, 0.0


def _managed_open_tickers(
    portfolio: Mapping[str, Any],
    family: str,
) -> list[str]:
    """Return only positions this robot is allowed to manage."""
    environment = _execution_mode(portfolio.get("environment"))
    selected = []
    seen = set()
    for row in list(portfolio.get("positions") or []):
        ticker = str(row.get("ticker") or row.get("market_ticker") or "")
        if not ticker or ticker in seen or _market_family(ticker) != family:
            continue
        if environment == "real":
            managed = _finite_number(row.get("alphaLabManagedCount"), 0.0) > 0.0
        else:
            _side, count = _position_side_and_count(portfolio, ticker)
            managed = count > 0
        if managed:
            selected.append(ticker)
            seen.add(ticker)
    return selected


def _position_execution_context(
    portfolio: Mapping[str, Any],
    ticker: str,
) -> Dict[str, Any]:
    """Return normalized entry economics for the currently held outcome."""
    side, count = _position_side_and_count(portfolio, ticker)
    result: Dict[str, Any] = {
        "side": side,
        "count": count,
        "accountPositionCount": 0,
        "unmanagedCount": 0,
        "averageEntryPrice": None,
        "allocatedEntryFee": 0.0,
        "lastTradeAt": None,
    }
    for row in list(portfolio.get("positions") or []):
        if str(row.get("ticker") or row.get("market_ticker") or "") != ticker:
            continue
        result["accountPositionCount"] = _contract_quantity(abs(_finite_number(
            row.get("net_count_fp")
            if row.get("net_count_fp") not in (None, "")
            else row.get("position_fp")
            if row.get("position_fp") not in (None, "")
            else row.get("position"),
            count,
        )))
        result["unmanagedCount"] = _contract_quantity(max(
            0.0,
            _finite_number(row.get("alphaLabUnmanagedCount"), 0.0),
        ))
        if not side or count <= 0:
            break
        prefix = side.lower()
        average = _finite_number(row.get(f"{prefix}_average_price_dollars"), -1.0)
        side_cost = _finite_number(row.get(f"{prefix}_cost"), -1.0)
        if average <= 0.0 and side_cost >= 0.0:
            average = side_cost / count
        fee = _finite_number(
            row.get(f"{prefix}_fee_cost_dollars")
            or row.get("feeCost")
            or row.get("fees_paid_dollars"),
            0.0,
        )
        result.update({
            "averageEntryPrice": average if 0.0 < average < 1.0 else None,
            "allocatedEntryFee": max(0.0, fee),
            "lastTradeAt": row.get("last_trade_at") or row.get("lastTradeAt") or row.get("updated_time"),
        })
        break
    return result


def _estimate_reduce_only_sale(
    side: str,
    requested: float,
    orderbook: Mapping[str, Any],
    *,
    taker_fee_rate: float = 0.07,
) -> Dict[str, Any]:
    """Estimate a full-depth reduce-only fill, including the official taker fee."""
    requested_count = _contract_quantity(requested)
    sale = aggregate_taker_sale(
        executable_bid_levels(side, orderbook),
        requested_count,
        0.0,
        fee_multiplier=max(0.0, _finite_number(taker_fee_rate, 0.07)) / 0.07,
    )
    fill_count = sale["fill_count"]
    fills = sale["fills"]
    return {
        "requestedCount": requested_count,
        "fillableCount": _contract_quantity(fill_count),
        "averageBid": sale["average_price"] if fill_count else None,
        "worstBid": fills[-1]["price_dollars"] if fills else None,
        "grossProceeds": sale["gross_proceeds"],
        "estimatedExitFee": sale["fee_cost"],
        "estimatedExitTradeFee": sale["trade_fee"],
        "takerFeeRate": max(
            0.0,
            _finite_number(taker_fee_rate, 0.07),
        ),
        "netProceeds": sale["credit_cents"] / 100.0,
        "fullDepthAvailable": fill_count + 1e-9 >= requested_count,
    }


def _protective_exit_state(
    held_probability: Optional[float],
    strategy_config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Classify deterministic exit risk without inventing an executable price.

    This is the probability half of the stop rule. A materially weaker
    probability (20 percentage points below it) is treated as an emergency.
    The caller must still combine it with fee-adjusted loss and executable
    liquidity gates.
    """
    threshold = _finite_number(strategy_config.get("exitProbabilityThreshold"), 0.46)
    emergency_threshold = max(0.05, threshold - 0.20)
    probability = _finite_number(held_probability, 1.0)
    return {
        "protectiveExitThreshold": threshold,
        "emergencyExitThreshold": emergency_threshold,
        "protectiveExit": probability <= threshold,
        "emergencyExit": probability <= emergency_threshold,
    }


def _exit_economic_state(
    *,
    average_entry_price: Optional[float],
    allocated_entry_fee: float,
    held_count: float,
    net_exit_value_per_contract: Optional[float],
    held_probability: Optional[float],
    strategy_config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Evaluate an exit against actual entry cost, both fees, and model risk.

    A probability threshold alone is too noisy for a contract evaluated every
    five seconds.  It previously allowed repeated loss-taking exits whose gross
    price movement was small relative to two taker fees.  Normal closes now
    require a real fee-adjusted profit.  Loss-taking closes require both model
    deterioration and a material mark-to-market loss; an emergency probability
    collapse uses a lower loss threshold but still needs an executable bid.
    """
    probability_state = _protective_exit_state(held_probability, strategy_config)
    count = _contract_quantity(held_count)
    entry_price = _finite_number(average_entry_price, -1.0)
    entry_fee_per_contract = (
        max(0.0, _finite_number(allocated_entry_fee, 0.0)) / count
        if count > 0
        else 0.0
    )
    break_even = (
        entry_price + entry_fee_per_contract
        if 0.0 < entry_price < 1.0
        else None
    )
    exit_value = (
        _finite_number(net_exit_value_per_contract)
        if net_exit_value_per_contract is not None
        else None
    )
    pnl_per_contract = (
        exit_value - break_even
        if exit_value is not None and break_even is not None
        else None
    )
    loss_fraction = (
        max(0.0, -pnl_per_contract / break_even)
        if pnl_per_contract is not None and break_even and break_even > 0
        else None
    )
    minimum_profit = _finite_number(strategy_config.get("minimumExitProfit"), 0.01)
    stop_loss = _finite_number(strategy_config.get("stopLossPct"), 0.35)
    emergency_stop = min(
        stop_loss,
        _finite_number(strategy_config.get("emergencyStopLossPct"), 0.20),
    )
    profitable_exit = bool(
        pnl_per_contract is not None
        and pnl_per_contract >= minimum_profit
    )
    emergency_loss_exit = bool(
        probability_state["emergencyExit"]
        and loss_fraction is not None
        and loss_fraction >= emergency_stop
    )
    protective_loss_exit = bool(
        probability_state["protectiveExit"]
        and loss_fraction is not None
        and loss_fraction >= stop_loss
    )
    return {
        **probability_state,
        "entryFeePerContract": entry_fee_per_contract,
        "breakEvenExitValuePerContract": break_even,
        "netExitPnlPerContract": pnl_per_contract,
        "exitLossFraction": loss_fraction,
        "minimumExitProfit": minimum_profit,
        "stopLossPct": stop_loss,
        "emergencyStopLossPct": emergency_stop,
        "profitableExit": profitable_exit,
        "protectiveLossExit": protective_loss_exit,
        "emergencyLossExit": emergency_loss_exit,
        "lossExitAuthorized": protective_loss_exit or emergency_loss_exit,
    }


def _voluntary_exit_route_economics(
    decision: Mapping[str, Any],
    payload: Mapping[str, Any],
    strategy_config: Mapping[str, Any],
    *,
    allow_tightening: bool = True,
) -> Dict[str, Any]:
    """Check both the observed sale slice and a single-fill limit scenario.

    A full-position VWAP profit does not establish profitability for a small
    scale-out after cent rounding or crossing tolerance. This guard is only
    for voluntary profit-taking; risk-reducing stops must remain executable.
    Per-fill trade-fee rounding means a single fill at the limit is not always
    a lower bound than a slightly better, fragmented fill. Both scenarios
    must clear the existing profit hurdle. Neither guarantees IOC execution
    or the eventual number of fills when the live orderbook changes.
    """
    exit_analysis = dict(decision.get("exitAnalysis") or {})
    applicable = bool(
        str(decision.get("action") or "").startswith("SELL_")
        and exit_analysis.get("trigger") == "fee_adjusted_take_profit"
    )
    if not applicable:
        return {"applicable": False, "allowed": True}
    config = normalize_strategy_config(strategy_config)
    count = _contract_quantity(payload.get("count"))
    limit = _finite_number(payload.get("user_side_limit_price"), None)
    reference = _finite_number(payload.get("user_side_reference_price"), limit)
    break_even = _finite_number(exit_analysis.get("breakEvenExitValuePerContract"), None)
    hold_value = _finite_number(exit_analysis.get("heldProbability"), None)
    required_value = (
        max(break_even + config["minimumExitProfit"], hold_value + config["exitValueBuffer"])
        if break_even is not None and hold_value is not None
        else None
    )
    result = {
        "applicable": True,
        "allowed": False,
        "requestedContracts": count,
        "proposedLimitPrice": limit,
        "minimumExecutionPrice": limit,
        "breakEvenExitValuePerContract": break_even,
        "requiredNetValuePerContract": required_value,
        "minimumExitProfit": config["minimumExitProfit"],
        "requiredExitValueEdge": config["exitValueBuffer"],
        "limitTightened": False,
        "assumption": "observed_full_slice_and_single_fill_limit_scenarios; live fragmentation or partial fills may differ",
    }
    if count <= 0 or limit is None or not 0.0 < limit < 1.0 or required_value is None:
        return result
    quote = dict(exit_analysis.get("routeQuote") or {})
    quote_net = _finite_number(quote.get("netProceeds"), None)
    quote_gross = _finite_number(quote.get("grossProceeds"), None)
    quote_fee = _finite_number(quote.get("estimatedExitFee"), None)
    quote_trade_fee = _finite_number(quote.get("estimatedExitTradeFee"), None)
    quote_price = _finite_number(quote.get("worstBid"), None)
    quote_rate = _finite_number(quote.get("takerFeeRate"), None)
    quote_matches = bool(
        abs(_finite_number(quote.get("requestedCount"), -1) - count) <= 1e-9
        and abs(_finite_number(quote.get("fillableCount"), -1) - count) <= 1e-9
        and quote_net is not None and quote_net >= 0
        and quote_gross is not None and quote_gross >= quote_net
        and quote_fee is not None and quote_fee >= 0
        and quote_trade_fee is not None and quote_trade_fee >= 0
        and abs(quote_gross - quote_fee - quote_net) <= 1e-8
        and quote_price is not None and 0 < quote_price < 1
        and limit <= quote_price + 1e-9
        and reference is not None and abs(reference - quote_price) <= 1e-8
        and quote_rate is not None and abs(quote_rate - config["takerFeeRate"]) <= 1e-9
    )
    quote_value = quote_net / count if quote_matches else None
    quote_clears = bool(quote_value is not None and quote_value + 1e-9 >= required_value)
    result.update({
        "routeQuoteMatchesPayload": quote_matches,
        "observedSliceNetProceeds": quote_net,
        "observedSliceNetValuePerContract": quote_value,
        "observedSliceProfitable": quote_clears,
    })
    # Final preflight checks this exact quantity again; never scale/prorate an
    # old ladder fee after a count or fee-policy change.
    if not quote_matches:
        return result
    prices = [limit]
    # Removing the crossing allowance preserves the observed executable bid;
    # never invent a higher bid or increase the configured scale-out quantity.
    if allow_tightening and reference is not None and limit < reference < 1.0:
        prices.append(reference)
    for price in prices:
        sale = aggregate_taker_sale(
            [(price, count)], count, price,
            fee_multiplier=config["takerFeeRate"] / 0.07,
        )
        limit_net = sale["credit_cents"] / 100.0
        net = min(limit_net, quote_net)
        net_per_contract = net / count
        result.update({
            "minimumExecutionPrice": price,
            "limitTightened": price > limit + 1e-9,
            "estimatedExitFee": max(sale["fee_cost"], quote_fee),
            "estimatedNetProceeds": net,
            "singleFillLimitNetProceeds": limit_net,
            "netExitValuePerContract": net_per_contract,
            "netExitPnlPerContract": net_per_contract - break_even,
            "netExitPnl": net - count * break_even,
            "exitValueEdge": net_per_contract - hold_value,
            "allowed": quote_clears and net_per_contract + 1e-9 >= required_value,
        })
        if result["allowed"]:
            break
    return result


def _protective_confirmation_data_quality(decision: Mapping[str, Any]) -> bool:
    """Ordinary stop confirmations require valid model evidence, not entry timing."""
    history_quality = (decision.get("model") or {}).get("historyQuality") or {}
    return bool(
        history_quality.get("clockVerified") is not False
        and not (
            set((decision.get("dataQuality") or {}).get("warnings") or [])
            & KALSHI_EXECUTION_BLOCKING_WARNINGS
        )
        and not any(
            gate.get("key") in {"reference_ready", "data_freshness", "history_sample"}
            and (gate.get("status") == "block" or gate.get("blocking") is True)
            for gate in decision.get("gates") or []
            if isinstance(gate, Mapping)
        )
    )


def _protective_exit_confirmation(
    robot_state: Mapping[str, Any],
    ticker: str,
    held_side: str,
    economics: Mapping[str, Any],
    strategy_config: Mapping[str, Any],
    *,
    generated_at: Any = None,
    data_quality_ok: bool = True,
) -> Dict[str, Any]:
    """Confirm an ordinary loss exit across durable scheduler decisions.

    The compact per-ticker state cursor survives worker restarts without
    persisting full decision history. A true emergency remains immediate and
    cannot be delayed by this hysteresis guard.
    """
    required = max(
        2,
        min(
            6,
            int(
                round(
                    _finite_number(
                        strategy_config.get("protectiveExitConfirmations"),
                        3.0,
                    )
                )
            ),
        ),
    )
    gap_setting = (
        "btc15ProtectiveExitConfirmationMaxGapSeconds"
        if _market_family(ticker) == "btc15m"
        else "protectiveExitConfirmationMaxGapSeconds"
    )
    gap_default = 30.0 if gap_setting.startswith("btc15") else 20.0
    gap_cap = 90.0 if gap_setting.startswith("btc15") else 60.0
    max_gap = max(
        10.0,
        min(
            gap_cap,
            _finite_number(
                strategy_config.get(gap_setting),
                gap_default,
            ),
        ),
    )
    emergency = bool(economics.get("emergencyLossExit"))
    ordinary = bool(economics.get("protectiveLossExit")) and not emergency
    if emergency:
        return {
            "required": False,
            "requiredSnapshots": required,
            "streak": required,
            "confirmed": True,
            "emergencyBypass": True,
            "dataQualityEligible": bool(data_quality_ok),
            "maxGapSeconds": max_gap,
        }
    if not ordinary or not data_quality_ok:
        return {
            "required": ordinary,
            "requiredSnapshots": required,
            "streak": 0,
            "confirmed": False,
            "emergencyBypass": False,
            "dataQualityEligible": bool(data_quality_ok),
            "maxGapSeconds": max_gap,
        }

    streak = 1
    previous_time = _parse_utc(generated_at) or datetime.now(timezone.utc)
    normalized_side = str(held_side or "").upper()
    ticker_history = [
        row for row in list(robot_state.get("decisions") or [])
        if isinstance(row, Mapping) and str(row.get("ticker") or "") == str(ticker or "")
    ]
    cursors = (robot_state.get("strategy") or {}).get("protectiveExitConfirmations")
    cursor = cursors.get(ticker) if isinstance(cursors, Mapping) else None

    def eligible_row(row: Mapping[str, Any]) -> bool:
        row_side = str(((row.get("account") or {}).get("heldSide") or "")).upper()
        metadata = next(
            (value for value in (
                row.get("protectiveConfirmation"),
                (row.get("exitAnalysis") or {}).get("protectiveConfirmation"),
                ((row.get("features") or {}).get("exitAnalysis") or {}).get("protectiveConfirmation"),
            ) if value is not None),
            None,
        )
        reasons = set(str(value) for value in (row.get("blockingReasons") or []))
        return bool(
            (not row_side or row_side == normalized_side)
            and (
                metadata is None
                or (
                    isinstance(metadata, Mapping)
                    and metadata.get("dataQualityEligible") is True
                    and metadata.get("required") is not False
                    and metadata.get("emergencyBypass") is not True
                    and _finite_number(metadata.get("streak"), 1) > 0
                )
            )
            and (
                {"protective_exit_confirmation", "protective_exit_confirmed"} & reasons
                or str(row.get("exitTrigger") or "") == "protective_stop_loss"
            )
        )

    if isinstance(cursor, Mapping):
        cursor_time = _parse_utc(cursor.get("generatedAt"))
        elapsed = (previous_time - cursor_time).total_seconds() if cursor_time is not None else None
        newer_invalid = any(
            row_time is not None and cursor_time is not None and row_time >= cursor_time
            and not eligible_row(row)
            for row in ticker_history
            for row_time in [_parse_utc(row.get("generatedAt"))]
        )
        if (
            str(cursor.get("ticker") or "") == str(ticker or "")
            and str(cursor.get("side") or "").upper() == normalized_side
            and cursor.get("dataQualityEligible") is True
            and cursor.get("required") is not False
            and cursor.get("emergencyBypass") is not True
            and _finite_number(cursor.get("streak"), 0) > 0
            and elapsed is not None and 1e-6 < elapsed <= max_gap
            and not newer_invalid
        ):
            streak = min(required, max(1, int(_finite_number(cursor.get("streak"), 1))) + 1)
            return {
                "required": True, "requiredSnapshots": required, "streak": streak,
                "confirmed": streak >= required, "emergencyBypass": False,
                "dataQualityEligible": True, "maxGapSeconds": max_gap,
                "durableProgressUsed": True,
            }
    # An explicit invalid cursor must reset, never resurrect older history.
    for row in ([] if isinstance(cursor, Mapping) else ticker_history):
        row_side = str(((row.get("account") or {}).get("heldSide") or "")).upper()
        if row_side and normalized_side and row_side != normalized_side:
            break
        row_time = _parse_utc(row.get("generatedAt"))
        if row_time is None:
            break
        gap = (previous_time - row_time).total_seconds()
        if gap <= 1e-6 or gap > max_gap:
            break
        # Explicitly ineligible persisted rows are never allowed to advance a
        # later fresh streak, even if an old worker accidentally wrote the
        # legacy marker. Missing metadata remains compatible with eligible
        # rows recorded before this field was introduced.
        if not eligible_row(row):
            break
        streak += 1
        previous_time = row_time
        if streak >= required:
            break
    return {
        "required": True,
        "requiredSnapshots": required,
        "streak": streak,
        "confirmed": streak >= required,
        "emergencyBypass": False,
        "dataQualityEligible": True,
        "maxGapSeconds": max_gap,
    }


def _entry_confirmation(
    robot_state: Mapping[str, Any],
    ticker: str,
    side: str,
    decision: Mapping[str, Any],
    strategy_config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Require a new-position BUY thesis to persist for consecutive cycles."""
    required = max(
        1,
        min(
            5,
            int(
                round(
                    _finite_number(
                        strategy_config.get("entryConfirmationSnapshots"),
                        2.0,
                    )
                )
            ),
        ),
    )
    gap_setting = (
        "btc15EntryConfirmationMaxGapSeconds"
        if _market_family(ticker) == "btc15m"
        else "entryConfirmationMaxGapSeconds"
    )
    is_btc15 = gap_setting.startswith("btc15")
    gap_default = 25.0
    # The hourly loop itself runs every 15 seconds.  Network and evaluation
    # latency make an exact 15-second maximum self-defeating, so enforce a
    # cadence-aware floor while preserving the two-snapshot confirmation gate.
    gap_floor = 5.0 if is_btc15 else 25.0
    max_gap = max(
        gap_floor,
        min(
            60.0,
            _finite_number(
                strategy_config.get(gap_setting),
                gap_default,
            ),
        ),
    )
    generated = _parse_utc(decision.get("generatedAt")) or datetime.now(timezone.utc)
    normalized_ticker = str(ticker or "")
    normalized_side = str(side or "").upper()
    action = str(decision.get("action") or "").upper()
    if (
        not normalized_ticker
        or normalized_side not in {"YES", "NO"}
        or not action.startswith("BUY_")
    ):
        return {
            "required": False,
            "requiredSnapshots": required,
            "streak": 0,
            "confirmed": False,
            "maxGapSeconds": max_gap,
        }
    if required <= 1:
        return {
            "required": False,
            "requiredSnapshots": required,
            "streak": 1,
            "confirmed": True,
            "maxGapSeconds": max_gap,
        }

    streak = 1
    family = _market_family(normalized_ticker)
    previous_time = generated
    durable_progress = (
        (robot_state.get("strategy") or {}).get("entryConfirmations")
        if isinstance(robot_state.get("strategy"), Mapping)
        else None
    )
    persisted = (
        durable_progress.get(family)
        if isinstance(durable_progress, Mapping) and family
        else None
    )
    family_history = [
        row for row in list(robot_state.get("decisions") or [])
        if _market_family(str(row.get("ticker") or "")) == family
    ]
    if isinstance(persisted, Mapping):
        persisted_time = _parse_utc(persisted.get("generatedAt"))
        elapsed = (
            (generated - persisted_time).total_seconds()
            if persisted_time is not None
            else None
        )
        newest = family_history[0] if family_history else {}
        newest_time = _parse_utc(newest.get("generatedAt"))
        newest_reasons = set(str(value) for value in newest.get("blockingReasons") or [])
        newer_invalid_frame = bool(
            persisted_time is not None
            and newest_time is not None
            and newest_time >= persisted_time
            and (
                str(newest.get("ticker") or "") != normalized_ticker
                or str(newest.get("side") or "").upper() != normalized_side
                or newest_reasons - {"entry_confirmation"}
                or (newest.get("entryConfirmation") or {}).get("dataQualityEligible") is False
            )
        )
        if (
            str(persisted.get("ticker") or "") == normalized_ticker
            and str(persisted.get("side") or "").upper()
            == normalized_side
            and persisted.get("dataQualityEligible") is True
            and elapsed is not None
            and elapsed > 1e-6
            and elapsed <= max_gap
            and not newer_invalid_frame
        ):
            prior_streak = max(
                1,
                min(
                    required,
                    int(
                        round(
                            _finite_number(
                                persisted.get("streak"),
                                1.0,
                            )
                        )
                    ),
                ),
            )
            streak = min(required, prior_streak + 1)
            return {
                "required": True,
                "requiredSnapshots": required,
                "streak": streak,
                "confirmed": streak >= required,
                "maxGapSeconds": max_gap,
                "ticker": normalized_ticker,
                "side": normalized_side,
                "durableProgressUsed": True,
            }
    # The most recent decision in this same strategy family must describe the
    # same ticker and side.  This deliberately resets an hourly confirmation
    # whenever the selected strike changes, even if an older strike reappears.
    # An explicit durable frame that cannot extend the streak must reset it;
    # do not resurrect a stale eligible row hidden behind that invalid frame.
    for row in ([] if isinstance(persisted, Mapping) else family_history):
        row_ticker = str(row.get("ticker") or "")
        if _market_family(row_ticker) != family:
            continue
        row_side = str(row.get("side") or "").upper()
        row_time = _parse_utc(row.get("generatedAt"))
        reasons = set(str(value) for value in (row.get("blockingReasons") or []))
        if (
            row_ticker != normalized_ticker
            or row_side != normalized_side
            or row_time is None
            or (previous_time - row_time).total_seconds() <= 1e-6
            or (previous_time - row_time).total_seconds() > max_gap
            or "entry_confirmation" not in reasons
            or reasons - {"entry_confirmation"}
            or (row.get("entryConfirmation") or {}).get("dataQualityEligible") is False
        ):
            break
        streak += 1
        previous_time = row_time
        if streak >= required:
            break
    return {
        "required": True,
        "requiredSnapshots": required,
        "streak": streak,
        "confirmed": streak >= required,
        "maxGapSeconds": max_gap,
        "ticker": normalized_ticker,
        "side": normalized_side,
    }


def _pending_entry_confirmation_signature(
    result: Mapping[str, Any],
    family: str,
) -> Optional[str]:
    """Return a stable signature for a fresh first confirmation frame.

    The public-market and account work performed by one scheduler cycle can
    take longer than the strategy's 25-second confirmation horizon.  The
    scheduler uses this compact signal to prioritize one fresh follow-up for
    the same family; it does not waive or extend the confirmation gate.
    """
    decision = dict((result or {}).get("decision") or {})
    confirmation = dict(decision.get("entryConfirmation") or {})
    market = dict(decision.get("market") or {})
    ticker = str(market.get("ticker") or "").strip()
    side = str(decision.get("side") or "").upper()
    normalized_family = (
        "btchourly" if str(family).lower() == "btchourly" else "btc15m"
    )
    if (
        _market_family(ticker) != normalized_family
        or side not in {"YES", "NO"}
        or confirmation.get("required") is not True
        or confirmation.get("confirmed") is True
        or int(_finite_number(confirmation.get("streak"), 0.0)) != 1
        or "entry_confirmation"
        not in {
            str(reason)
            for reason in (decision.get("blockingReasons") or [])
        }
    ):
        return None
    return f"{normalized_family}:{ticker}:{side}"


def _hourly_candidate_diagnostic(
    candidate: Mapping[str, Any],
    market: Mapping[str, Any],
    candidate_count: int,
    *,
    penalty_weight: float = 0.10,
) -> Dict[str, Any]:
    """Return a winner's-curse-adjusted score for one hourly strike."""
    edge = dict(candidate.get("edge") or {})
    model = dict(candidate.get("model") or {})
    raw_score = _finite_number(edge.get("conservativeEdge"), -99.0)
    uncertainty = max(0.0, _finite_number(model.get("uncertainty"), 0.0))
    trials = max(1, int(candidate_count or 1))
    trial_factor = math.sqrt(max(0.0, 2.0 * math.log(float(trials))))
    weight = max(0.0, min(0.50, _finite_number(penalty_weight, 0.10)))
    penalty = min(0.08, uncertainty * trial_factor * weight)
    shrunken = raw_score - penalty
    minimum = _finite_number(
        edge.get("effectiveMinimumConservativeEdge"),
        _finite_number(edge.get("minimumConservativeEdge"), 0.0075),
    )
    action = str(candidate.get("action") or "").upper()
    return {
        "ticker": str(market.get("ticker") or ""),
        "strike": market.get("floor_strike"),
        "action": action or "WAIT",
        "side": candidate.get("side"),
        "netEdge": edge.get("netEdge"),
        "conservativeEdge": edge.get("conservativeEdge"),
        "uncertainty": model.get("uncertainty"),
        "candidateCount": trials,
        "multipleCandidatePenalty": penalty,
        "shrunkenScore": shrunken,
        "minimumShrunkenScore": minimum,
        "penaltyCleared": bool(action.startswith("BUY_") and shrunken >= minimum),
        "blockingReasons": [
            str(reason)[:80]
            for reason in (candidate.get("blockingReasons") or [])[:6]
        ],
    }


def _btc15_live_strategy_config(
    strategy_config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Apply the walk-forward-selected BTC15 live champion envelope."""
    return normalize_strategy_config({
        **dict(strategy_config or {}),
        # Keep the tested band atomic.  Combining a user-supplied minimum
        # above the champion maximum would make generic normalization reset to
        # its broad fallback band and accidentally weaken the live policy.
        "minPrice": 0.70,
        "maxPrice": 0.80,
        "minNetEdge": max(
            0.010,
            _finite_number(strategy_config.get("minNetEdge"), 0.010),
        ),
        "minConservativeEdge": max(
            0.015,
            _finite_number(
                strategy_config.get("minConservativeEdge"),
                0.015,
            ),
        ),
        "entryConfirmationSnapshots": 2,
        "btc15EntryConfirmationMaxGapSeconds": 25,
    })


def _btc15_shadow_challenger_config(
    champion_config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the non-routing BTC15 frequency challenger.

    The lower edge floors and wider confirmation window did not pass every
    historical walk-forward segment, so this policy is observation-only.  It
    deliberately reuses the champion's price band and all data, liquidity,
    volatility, fee, account, Kelly, and exposure controls.
    """
    return normalize_strategy_config({
        **dict(champion_config or {}),
        "minNetEdge": 0.005,
        "minConservativeEdge": 0.010,
        "btc15EntryConfirmationMaxGapSeconds": 45,
    })


def _entry_shadow_diagnostic(
    decision: Mapping[str, Any],
    *,
    policy: str,
    strategy_config: Mapping[str, Any],
    route_allowed: bool = False,
    confirmation_evaluated_online: bool = False,
) -> Dict[str, Any]:
    """Compact an entry-policy decision with explicit routing authority."""
    action = str(decision.get("action") or "WAIT").upper()
    qualifying_frame = action.startswith("BUY_")
    market = dict(decision.get("market") or {})
    edge = dict(decision.get("edge") or {})
    sizing = dict(decision.get("sizing") or {})
    return {
        "policy": str(policy),
        "enabled": True,
        "routeAllowed": bool(route_allowed),
        # Confirmation is reconstructed from consecutive persisted frames.
        # Calling this a qualifying frame avoids implying that this isolated
        # pure-engine evaluation has already passed its multi-frame gate.
        "qualifyingFrame": qualifying_frame,
        "opportunity": qualifying_frame,
        "action": action,
        "side": decision.get("side"),
        "signalQuality": decision.get("signalQuality"),
        "secondsToClose": market.get("secondsToClose"),
        "price": edge.get("price"),
        "netEdge": edge.get("netEdge"),
        "conservativeEdge": edge.get("conservativeEdge"),
        "plannedContractsFp": sizing.get("plannedContractsFp"),
        "evaluationError": decision.get("shadowEvaluationError"),
        "blockingReasons": [
            str(reason)[:80]
            for reason in (decision.get("blockingReasons") or [])[:12]
        ],
        "confirmationPolicy": {
            "evaluatedOnline": bool(confirmation_evaluated_online),
            "requiredSnapshots": strategy_config.get(
                "entryConfirmationSnapshots"
            ),
            "maxGapSeconds": strategy_config.get(
                "btc15EntryConfirmationMaxGapSeconds"
            ),
        },
        "thresholds": {
            "minPrice": strategy_config.get("minPrice"),
            "maxPrice": strategy_config.get("maxPrice"),
            "minNetEdge": strategy_config.get("minNetEdge"),
            "minConservativeEdge": strategy_config.get(
                "minConservativeEdge"
            ),
            "entryConfirmationSnapshots": strategy_config.get(
                "entryConfirmationSnapshots"
            ),
            "btc15EntryConfirmationMaxGapSeconds": strategy_config.get(
                "btc15EntryConfirmationMaxGapSeconds"
            ),
            "hourlyCandidatePenaltyWeight": strategy_config.get(
                "hourlyCandidatePenaltyWeight"
            ),
        },
    }


def _hourly_live_strategy_config(
    strategy_config: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return the separately calibrated policy for the KXBTCD ladder."""
    return normalize_strategy_config({
        **dict(strategy_config or {}),
        "riskPerTradePct": min(
            _finite_number(strategy_config.get("riskPerTradePct"), 0.50),
            0.50,
        ),
        "minNetEdge": max(
            0.015,
            _finite_number(strategy_config.get("minNetEdge"), 0.015),
        ),
        "minConservativeEdge": max(
            0.015,
            _finite_number(
                strategy_config.get("minConservativeEdge"),
                0.015,
            ),
        ),
        "marketBlendWeight": max(
            0.60,
            min(
                _finite_number(
                    strategy_config.get("marketBlendWeight"),
                    0.60,
                ),
                0.75,
            ),
        ),
        "probabilityLogitScale": min(
            1.50,
            _finite_number(
                strategy_config.get("probabilityLogitScale"),
                1.50,
            ),
        ),
        "minSecondsToClose": 120,
        "maxSecondsToClose": 1200,
        "minPrice": 0.48,
        "maxPrice": min(
            0.78,
            _finite_number(strategy_config.get("maxPrice"), 0.78),
        ),
        "minModelProbability": max(
            0.64,
            _finite_number(
                strategy_config.get("minModelProbability"),
                0.64,
            ),
        ),
        "hourlyCandidatePenaltyWeight": max(
            0.15,
            _finite_number(
                strategy_config.get("hourlyCandidatePenaltyWeight"),
                0.15,
            ),
        ),
        "maxSingleMarketExposurePct": min(
            _finite_number(
                strategy_config.get("maxSingleMarketExposurePct"),
                2.0,
            ),
            2.0,
        ),
    })


def _hourly_candidate_management_priority(
    candidate: Mapping[str, Any],
    market: Mapping[str, Any],
    orderbook: Mapping[str, Any],
    portfolio: Mapping[str, Any],
    robot_state: Mapping[str, Any],
    strategy_config: Mapping[str, Any],
) -> Tuple[int, float, float]:
    """Rank an owned hourly strike by the action its position needs now.

    Multiple KXBTCD strikes can remain open after partial fills. Candidate
    entry edge alone must not let an add-on starve a sibling's stop or
    profitable reduction. Executability is considered before severity so an
    unfillable emergency cannot starve a fillable protective exit. The tuple
    orders: fillable emergency, fillable protective, unfillable emergency,
    unfillable protective, profitable reduce, add, then hold.
    """
    ticker = str(market.get("ticker") or "")
    position = _position_execution_context(portfolio, ticker)
    held_side = str(position.get("side") or "").upper()
    held_count = _contract_quantity(position.get("count"))
    if held_side not in {"YES", "NO"} or held_count <= 0:
        return (0, -1.0, -1.0)

    fair_yes = _finite_number(
        (candidate.get("model") or {}).get("fairYesProbability"),
        0.5,
    )
    held_probability = fair_yes if held_side == "YES" else 1.0 - fair_yes
    sale = _estimate_reduce_only_sale(
        held_side,
        held_count,
        orderbook,
        taker_fee_rate=_finite_number(
            strategy_config.get("takerFeeRate"), 0.07
        ),
    )
    fillable = _contract_quantity(sale.get("fillableCount"))
    net_exit = (
        _finite_number(sale.get("netProceeds"), 0.0) / fillable
        if fillable > 0
        else None
    )
    economics = _exit_economic_state(
        average_entry_price=position.get("averageEntryPrice"),
        allocated_entry_fee=_finite_number(
            position.get("allocatedEntryFee"),
            0.0,
        ),
        held_count=held_count,
        net_exit_value_per_contract=net_exit,
        held_probability=held_probability,
        strategy_config=strategy_config,
    )
    hold_age = _seconds_since(position.get("lastTradeAt"))
    if hold_age is None:
        hold_age = _recent_filled_entry_age(robot_state, ticker)
    minimum_hold = int(
        _finite_number(strategy_config.get("minimumHoldSeconds"), 45)
    )
    hold_elapsed = hold_age is None or hold_age >= minimum_hold
    exit_value_edge = (
        net_exit - held_probability if net_exit is not None else None
    )
    profitable_reduce = bool(
        fillable > 0
        and hold_elapsed
        and exit_value_edge is not None
        and exit_value_edge
        >= _finite_number(strategy_config.get("exitValueBuffer"), 0.01)
        and economics["profitableExit"]
    )
    loss_fraction = _finite_number(
        economics.get("exitLossFraction"),
        0.0,
    )
    # A probability stop that currently has no executable bid still outranks
    # every add. A fillable protective exit must nevertheless outrank an
    # unfillable emergency so executable risk reduction is never starved.
    if economics["emergencyExit"]:
        return (
            7 if fillable > 0 else 5,
            1.0 if economics["emergencyLossExit"] else 0.0,
            loss_fraction - held_probability,
        )
    if economics["protectiveExit"]:
        return (
            6 if fillable > 0 else 4,
            1.0 if economics["protectiveLossExit"] and hold_elapsed else 0.0,
            loss_fraction - held_probability,
        )
    if profitable_reduce:
        return (
            3,
            _finite_number(economics.get("netExitPnlPerContract"), 0.0),
            _finite_number(exit_value_edge, 0.0),
        )
    action = str(candidate.get("action") or "").upper()
    candidate_side = str(candidate.get("side") or "").upper()
    if action.startswith("BUY_") and candidate_side == held_side:
        return (
            2,
            _finite_number(
                (candidate.get("edge") or {}).get("conservativeEdge"),
                -1.0,
            ),
            _finite_number(
                (candidate.get("edge") or {}).get("netEdge"),
                -1.0,
            ),
        )
    return (1, -held_probability, 0.0)


def _seconds_since(value: Any) -> Optional[float]:
    parsed = _parse_utc(value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def _real_preflight_account_health(
    state: Mapping[str, Any],
    runtime: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Describe whether a browser preflight has a current scheduler-owned account view."""
    current = now or datetime.now(timezone.utc)
    latest_rows = list(state.get("decisions") or [])
    latest = dict(latest_rows[0] or {}) if latest_rows else {}
    latest_account = dict(latest.get("account") or {})
    snapshot_at = latest.get("generatedAt")
    parsed = _parse_utc(snapshot_at)
    age_seconds = (
        max(0.0, (current - parsed).total_seconds())
        if parsed is not None
        else None
    )
    account_present = bool(
        latest_account
        and latest_account.get("cashAvailable") is not None
        and latest_account.get("portfolioExposure") is not None
    )
    snapshot_fresh = bool(
        account_present
        and age_seconds is not None
        and age_seconds <= KALSHI_REAL_ACCOUNT_SNAPSHOT_MAX_AGE_SECONDS
    )
    scheduler_healthy = bool(runtime.get("healthy"))
    scheduler_running = bool(runtime.get("threadAlive"))
    scheduler_lease_owned = runtime.get("schedulerLeaseOwned") is True
    return {
        "snapshotAt": snapshot_at,
        "snapshotAgeSeconds": round(age_seconds, 3) if age_seconds is not None else None,
        "maximumAgeSeconds": KALSHI_REAL_ACCOUNT_SNAPSHOT_MAX_AGE_SECONDS,
        "accountSnapshotPresent": account_present,
        "accountSnapshotFresh": snapshot_fresh,
        "schedulerHealthy": scheduler_healthy,
        "schedulerRunning": scheduler_running,
        "schedulerLeaseOwned": scheduler_lease_owned,
        "schedulerLastError": str(runtime.get("lastError") or "")[:240],
        "ready": bool(
            snapshot_fresh
            and scheduler_healthy
            and scheduler_running
            and scheduler_lease_owned
        ),
    }


def _apply_real_preflight_health_gate(
    decision: Dict[str, Any],
    health: Mapping[str, Any],
) -> Dict[str, Any]:
    """Fail a read-only Real preflight closed when its account/runtime view is stale."""
    if health.get("ready"):
        return decision

    reasons = list(decision.get("blockingReasons") or [])
    gates = list(decision.get("gates") or [])
    if not health.get("accountSnapshotFresh"):
        reasons.append("account_snapshot_stale")
        age = health.get("snapshotAgeSeconds")
        detail = (
            f"latest scheduler account snapshot is {age:.1f}s old; "
            f"maximum {health.get('maximumAgeSeconds', 0):.0f}s"
            if isinstance(age, (int, float))
            else "no complete scheduler-owned account snapshot is available"
        )
        gates.append({
            "key": "account_snapshot_fresh",
            "status": "block",
            "blocking": True,
            "severity": "hard",
            "label": "Fresh Real account snapshot",
            "labelZh": "实盘账户快照新鲜度",
            "detail": detail,
            "category": "account",
        })
    if not (
        health.get("schedulerHealthy")
        and health.get("schedulerRunning")
        and health.get("schedulerLeaseOwned")
    ):
        reasons.append("robot_scheduler_unhealthy")
        scheduler_detail = str(
            health.get("schedulerLastError")
            or "the cloud scheduler is not healthy and lease-owned"
        )
        gates.append({
            "key": "robot_scheduler_healthy",
            "status": "block",
            "blocking": True,
            "severity": "hard",
            "label": "Live robot scheduler",
            "labelZh": "实盘机器人调度器",
            "detail": scheduler_detail,
            "category": "account",
        })

    decision["action"] = "WAIT"
    decision["executionIntent"] = None
    decision["blockingReasons"] = list(dict.fromkeys(reasons))
    decision["gates"] = gates
    decision["accountPreflight"] = dict(health)
    sizing = dict(decision.get("sizing") or {})
    sizing.update({
        "contracts": 0,
        "estimatedFee": 0.0,
        "maximumLoss": 0.0,
        "expectedValue": 0.0,
        "microSizingApplied": False,
    })
    decision["sizing"] = sizing
    return decision


def _recent_filled_exit_age(state: Mapping[str, Any], ticker: str) -> Optional[float]:
    strategy = dict(state.get("strategy") or {})
    if str(strategy.get("lastExitTicker") or "") == ticker:
        age = _seconds_since(strategy.get("lastExitAt"))
        if age is not None:
            return age
    for row in list(state.get("decisions") or []):
        if str(row.get("ticker") or "") != ticker:
            continue
        if not row.get("orderFilled") or not str(row.get("action") or "").startswith("SELL_"):
            continue
        return _seconds_since(row.get("generatedAt"))
    return None


def _same_ticker_reentry_confirmation(
    state: Mapping[str, Any],
    ticker: str,
    edge: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    recent_exit_age: Optional[float] = None,
) -> Dict[str, Any]:
    """Require a materially stronger signal after a filled same-ticker exit.

    The last filled exit is durable robot state, so this gate survives worker
    restarts and is shared by Paper evaluation and Real's final pre-POST
    refresh. A stop-loss ticker is handled by the stricter permanent block.
    """
    strategy = dict(state.get("strategy") or {})
    settled = any(
        str(
            row.get("ticker")
            or row.get("market_ticker")
            or ""
        ) == str(ticker or "")
        for row in strategy.get("settlementRecords") or []
        if isinstance(row, Mapping)
    )
    exit_age = (
        recent_exit_age
        if recent_exit_age is not None
        else _recent_filled_exit_age(state, ticker)
    )
    probability = _finite_number(
        edge.get("fairProbability"),
        _finite_number(edge.get("modelProbability"), 0.0),
    )
    conservative_edge = _finite_number(
        edge.get("conservativeEdge"),
        -1.0,
    )
    probability_threshold = max(
        _finite_number(config.get("minModelProbability"), 0.64) + 0.05,
        0.70,
    )
    edge_threshold = max(
        _finite_number(config.get("minConservativeEdge"), 0.0075) + 0.005,
        0.0125,
    )
    required = bool(str(ticker or "") and exit_age is not None and not settled)
    confirmed = bool(
        not required
        or (
            probability >= probability_threshold
            and conservative_edge >= edge_threshold
        )
    )
    return {
        "required": required,
        "confirmed": confirmed,
        "settled": settled,
        "recentExitAgeSeconds": exit_age,
        "modelProbability": probability,
        "requiredModelProbability": probability_threshold,
        "conservativeEdge": conservative_edge,
        "requiredConservativeEdge": edge_threshold,
    }


def _recent_filled_entry_age(state: Mapping[str, Any], ticker: str) -> Optional[float]:
    strategy = dict(state.get("strategy") or {})
    if str(strategy.get("lastEntryTicker") or "") == ticker:
        age = _seconds_since(strategy.get("lastEntryAt"))
        if age is not None:
            return age
    for row in list(state.get("decisions") or []):
        if str(row.get("ticker") or "") != ticker:
            continue
        if not row.get("orderFilled") or not str(row.get("action") or "").startswith("BUY_"):
            continue
        return _seconds_since(row.get("generatedAt"))
    return None


def _recent_filled_entry_signal(state: Mapping[str, Any], ticker: str, side: str) -> Optional[Dict[str, float]]:
    """Return the last filled same-side signal so scale-ins require improvement."""
    side = str(side or "").upper()
    rows = list(state.get("decisions") or []) + list(
        reversed(list(state.get("filledTrades") or []))
    )
    seen = set()
    for row in rows:
        identity = str(row.get("orderId") or row.get("clientOrderId") or "")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        if str(row.get("ticker") or "") != ticker or str(row.get("side") or "").upper() != side:
            continue
        if not row.get("orderFilled") or not str(row.get("action") or "").startswith("BUY_"):
            continue
        return {
            "probability": _finite_number(row.get("fairProbability"), 0.0),
            "conservativeEdge": _finite_number(row.get("conservativeEdge"), -1.0),
        }
    return None


def _scale_in_signal_improved(
    previous_signal: Optional[Mapping[str, Any]],
    probability: float,
    conservative_edge: float,
    probability_improvement: float,
    edge_improvement: float,
) -> bool:
    if not previous_signal:
        return False
    return bool(
        probability
        >= _finite_number(previous_signal.get("probability"), 0.0)
        + probability_improvement
        and conservative_edge
        >= _finite_number(previous_signal.get("conservativeEdge"), -1.0)
        + edge_improvement
    )


def _intent_client_order_id(
    user_id: str,
    environment: str,
    ticker: str,
    action: str,
    side: str,
    held_count: float,
    *,
    now_epoch: Optional[float] = None,
) -> str:
    """Create a short-lived idempotency key for one observable trade intent.

    A retry after an ambiguous network timeout reuses the same key, while a
    later quote cycle or a changed position receives a new key.
    """
    bucket = int(float(now_epoch if now_epoch is not None else time.time())) // 10
    identity = ":".join((
        str(user_id),
        str(environment),
        str(ticker),
        str(action),
        str(side),
        f"{_contract_quantity(held_count):.2f}",
        str(bucket),
    ))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"alphalab:kalshi:intent:{identity}"))


def _paper_order_payload(
    decision: Mapping[str, Any],
    ticker: str,
    *,
    count_override: Optional[float] = None,
    price_tolerance: float = 0.0,
    client_order_id: Optional[str] = None,
    exchange_index: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Translate a cleared engine decision into Kalshi's V2 YES-book shape."""
    action = str(decision.get("action") or "")
    side = str(decision.get("side") or "").upper()
    edge = dict(decision.get("edge") or {})
    sizing = dict(decision.get("sizing") or {})
    selected_price = _finite_number(edge.get("price"), -1.0)
    count_source = (
        count_override
        if count_override is not None
        else sizing.get("plannedContractsFp")
        if sizing.get("plannedContractsFp") not in (None, "")
        else sizing.get("contractsFp")
        if sizing.get("contractsFp") not in (None, "")
        else sizing.get("contracts")
    )
    count = _contract_quantity(count_source)
    is_buy = action in {"BUY_YES", "BUY_NO"}
    is_sell = action in {"SELL_YES", "SELL_NO"}
    if not (is_buy or is_sell) or side not in {"YES", "NO"} or count <= 0:
        return None

    # V2 quotes one YES book: bid buys YES, while ask sells YES and is
    # economically the same as buying NO at 1 - YES price.
    # A small, user-capped crossing allowance protects IOC orders from a quote
    # moving by one tick between evaluation and submission. It is also capped by
    # the remaining conservative edge so execution can never erase the thesis.
    edge_room = max(
        0.0,
        _finite_number(edge.get("conservativeEdge"))
        - _finite_number(edge.get("minimumConservativeEdge")),
    )
    crossing = min(max(0.0, float(price_tolerance or 0.0)), edge_room * 0.5)
    marginal_limit = _finite_number(edge.get("executionLimitPrice"), -1.0)
    if is_buy and selected_price <= marginal_limit < 1.0:
        # The engine has evaluated every included depth level after fees and
        # uncertainty, so this limit can safely consume positive-edge depth.
        execution_price = min(0.99, marginal_limit)
        crossing = max(0.0, execution_price - selected_price)
    else:
        execution_price = min(0.99, selected_price + crossing) if is_buy else max(0.01, selected_price - crossing)
    if is_sell and (decision.get("exitAnalysis") or {}).get("trigger") == "fee_adjusted_take_profit":
        route_economics = (decision.get("exitAnalysis") or {}).get("routeEconomics") or {}
        protected_price = _finite_number(route_economics.get("minimumExecutionPrice"), None)
        if route_economics.get("allowed") is True and protected_price is not None:
            execution_price = max(execution_price, protected_price)
            crossing = max(0.0, selected_price - execution_price)
    yes_book_price = execution_price if side == "YES" else 1.0 - execution_price
    if not str(ticker or "").strip() or not 0.0 < yes_book_price < 1.0:
        return None
    try:
        authoritative_exchange_index = int(exchange_index)
    except (TypeError, ValueError):
        authoritative_exchange_index = -1
    if authoritative_exchange_index < 0:
        authoritative_exchange_index = -1
    return {
        "ticker": str(ticker),
        "client_order_id": str(client_order_id or uuid.uuid4()),
        "side": ("bid" if side == "YES" else "ask") if is_buy else ("ask" if side == "YES" else "bid"),
        "count": f"{count:.2f}",
        "price": f"{yes_book_price:.4f}",
        "user_side_limit_price": f"{execution_price:.4f}",
        "user_side_reference_price": f"{selected_price:.4f}",
        "crossing_allowance": f"{crossing:.4f}",
        "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
        "cancel_order_on_pause": True,
        "reduce_only": bool(is_sell),
        "subaccount": 0,
        # Crypto markets created after Kalshi's August 2026 exchange-sharding
        # rollout no longer live on shard 0. Use the public market's
        # authoritative shard when present; ``-1`` is Kalshi's documented
        # ticker-based auto-route fallback for older/missing market metadata.
        "exchange_index": authoritative_exchange_index,
    }


def _apply_real_shard_funding_gate(
    decision: Dict[str, Any],
    context: Mapping[str, Any],
    *,
    price_tolerance: float = 0.0,
    count_override: Optional[float] = None,
) -> bool:
    """Separate executable collateral from the capital-qualified signal.

    This never moves money and never restricts reduce-only exits. Unknown
    collateral is resolved by an uncached scoped read in the final preflight;
    a known empty shard is visible even while the signal itself is WAIT.
    """
    action = str(decision.get("action") or "WAIT")
    funding = {
        key: context.get(key) for key in (
            "exchangeIndex", "aggregateCashAvailable", "shardCashAvailable",
            "shardCashKnown", "fundingStatus",
        )
    }
    funding.update({
        "strategyAction": action,
        "strategyQualified": action.startswith("BUY_"),
        "applicable": not action.startswith("SELL_"),
        "requiresUserFunding": context.get("fundingStatus") == "empty",
    })
    decision["shardFunding"] = funding
    if action.startswith("SELL_"):
        return False
    cash = _finite_number(context.get("shardCashAvailable"), None)
    if context.get("shardCashKnown") is not True or cash is None:
        return False
    payload = _paper_order_payload(
        decision,
        str((decision.get("market") or {}).get("ticker") or ""),
        price_tolerance=price_tolerance,
        count_override=count_override,
        exchange_index=context.get("exchangeIndex"),
    )
    insufficient = cash <= 0.0
    if action.startswith("BUY_") and payload:
        sizing = dict(decision.get("sizing") or {})
        settings = normalize_strategy_config(decision.get("config") or {})
        quantity = _contract_quantity(payload.get("count"))
        price = _finite_number(payload.get("user_side_limit_price"), 0.0)
        fee_rate = settings["takerFeeRate"]
        required = kalshi_order_cost(price, quantity, fee_rate)["cashDebit"]
        funding.update({
            "strategyPlannedContracts": quantity,
            "requiredCash": required,
            "fundingGap": round(max(0.0, required - cash), 4),
        })
        if required > cash + 1e-9:
            # Monotone exact-cost search preserves the engine's contract step,
            # worst-fill limit and all existing risk/depth caps while avoiding
            # needless rejections when only part of the capital is on-shard.
            step = max(0.01, _finite_number(sizing.get("contractStep"), 1.0))
            low, high = 0, int(math.floor(quantity / step + 1e-9))
            while low < high:
                middle = (low + high + 1) // 2
                debit = kalshi_order_cost(price, middle * step, fee_rate)["cashDebit"]
                if debit <= cash + 1e-9:
                    low = middle
                else:
                    high = middle - 1
            funded_quantity = _contract_quantity(low * step)
            insufficient = funded_quantity <= 0
            if not insufficient:
                minimum_quantity = max(step, _finite_number(sizing.get("minimumEconomicContracts"), settings["minimumEconomicContracts"]))
                conservative_probability = _finite_number((decision.get("edge") or {}).get("conservativeProbability"), None)
                max_fee_ratio = settings["maxAllInFeeToPotentialProfitPct"]
                if conservative_probability is not None:
                    funded_quantity, _tested = _smaller_economic_order_size(
                        [(price, quantity)], funded_quantity,
                        step=step, minimum_contracts=minimum_quantity,
                        conservative_probability=conservative_probability,
                        dollar_cap=cash, fee_rate=fee_rate,
                        max_fee_to_profit_pct=max_fee_ratio,
                    )
                economics = kalshi_order_cost(price, funded_quantity, fee_rate)
                expected_value = conservative_probability * funded_quantity - economics["cashDebit"] if conservative_probability is not None else None
                possible_profit = funded_quantity * (1.0 - price)
                fee_ratio = 100.0 * economics["allInFee"] / possible_profit if possible_profit > 0 else float("inf")
                # Downsizing must not bypass the engine's rounding-aware
                # economic floor. Missing probability evidence is not consent
                # to accept a newly resized real order.
                insufficient = funded_quantity < minimum_quantity - 1e-9 or expected_value is None or expected_value <= 0 or fee_ratio > max_fee_ratio
                funding["resizedExpectedValue"] = expected_value
                funding["resizedFeeToPotentialProfitPct"] = fee_ratio if math.isfinite(fee_ratio) else None
            if not insufficient:
                decision["sizing"] = {
                    **sizing,
                    "contracts": funded_quantity,
                    "contractsFp": funded_quantity,
                    "plannedContractsFp": funded_quantity,
                    "notional": round(price * funded_quantity, 4),
                    "maximumLoss": economics["cashDebit"],
                    "expectedValue": expected_value,
                    "estimatedTradeFee": economics["tradeFee"],
                    "roundingFee": economics["roundingFee"],
                    "allInFee": economics["allInFee"],
                    "estimatedFee": economics["allInFee"],
                    "feeToPotentialProfitPct": fee_ratio,
                    "shardCashSizingApplied": True,
                }
                funding["routedContracts"] = funded_quantity
                funding["fundedCashDebit"] = kalshi_order_cost(price, funded_quantity, fee_rate)["cashDebit"]
        else:
            funding["routedContracts"] = quantity
    if insufficient:
        reason = "kalshi_live_shard_cash_insufficient"
        decision["blockingReasons"] = list(dict.fromkeys(
            list(decision.get("blockingReasons") or []) + [reason]
        ))
        funding["requiresUserFunding"] = True
        funding["executionBlocked"] = True
        if action.startswith("BUY_"):
            decision["action"] = "WAIT"
            decision["executionIntent"] = "WAIT_LIVE_SHARD_FUNDING"
        decision["gates"] = list(decision.get("gates") or []) + [{
            "key": reason,
            "category": "account",
            "name": "Market exchange collateral",
            "nameZh": "合约分片可用资金",
            "label": "Market exchange collateral",
            "labelZh": "合约分片可用资金",
            "status": "block",
            "blocking": True,
            "value": cash,
            "threshold": funding.get("requiredCash") or "> 0",
            "detail": (
                f"Exchange shard {context.get('exchangeIndex')} has ${cash:.4f}; "
                f"account total is ${_finite_number(context.get('aggregateCashAvailable')):.4f}. "
                "Cash on other shards cannot fund this entry. No money was transferred."
            ),
        }]
    return insufficient


def _order_fill_count(order: Optional[Mapping[str, Any]]) -> float:
    if not order:
        return 0.0
    explicit_fill = _first_present(
        order,
        "fill_count_fp",
        "filled_count_fp",
        "fill_count",
        "filled_count",
    )
    if explicit_fill is not None:
        try:
            value = float(explicit_fill)
        except (TypeError, ValueError):
            value = 0.0
        return max(0.0, value)
    status = str(order.get("status") or "").strip().lower()
    if status == "filled":
        try:
            return float(
                _first_present(order, "count_fp", "count") or 1
            )
        except (TypeError, ValueError):
            return 1.0
    return 0.0


def _environment_name(value: Any) -> str:
    environment = str(value or "production").strip().lower()
    aliases = {"live": "production", "real": "production"}
    environment = aliases.get(environment, environment)
    if environment not in KALSHI_ENVIRONMENTS:
        raise KalshiApiError("Kalshi credential environment must be production", status=400, code="invalid_environment")
    return environment


def _execution_mode(value: Any) -> str:
    mode = str(value or "paper").strip().lower()
    return "real" if mode in {"real", "live", "production"} else "paper"


def _cents_amount(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    # Kalshi account endpoints conventionally return cents as integers. If the
    # API ever returns a decimal dollar value for a derived field, keep it sane.
    if abs(parsed) < 10_000 and isinstance(value, float):
        return int(round(parsed * 100))
    return int(round(parsed))


def _dollar_amount(dollar_value: Any = None, cents_value: Any = None, default: float = 0.0) -> float:
    """Read Kalshi fixed-point dollar fields before legacy integer-cent fields."""
    if dollar_value not in (None, ""):
        return _finite_number(dollar_value, default)
    if cents_value not in (None, ""):
        return _cents_amount(cents_value, int(round(default * 100))) / 100.0
    return default


def _optional_dollar_amount(
    dollar_value: Any = None,
    cents_value: Any = None,
) -> Optional[float]:
    """Return None when an account response does not provide a monetary mark."""
    if dollar_value not in (None, ""):
        return _finite_number(dollar_value, None)
    if cents_value not in (None, ""):
        return _cents_amount(cents_value) / 100.0
    return None


def _position_market_mark(
    market: Mapping[str, Any],
    side: str,
) -> Dict[str, Any]:
    """Return an auditable current mark for one binary outcome position."""
    normalized_side = str(side or "").upper()
    if normalized_side not in {"YES", "NO"}:
        return {
            "mark": None,
            "bid": None,
            "ask": None,
            "source": None,
            "asOf": None,
        }

    yes_bid = _optional_dollar_amount(
        market.get("yes_bid_dollars"),
        market.get("yes_bid"),
    )
    yes_ask = _optional_dollar_amount(
        market.get("yes_ask_dollars"),
        market.get("yes_ask"),
    )
    no_bid = _optional_dollar_amount(
        market.get("no_bid_dollars"),
        market.get("no_bid"),
    )
    no_ask = _optional_dollar_amount(
        market.get("no_ask_dollars"),
        market.get("no_ask"),
    )
    if yes_ask is None and no_bid is not None:
        yes_ask = 1.0 - no_bid
    if no_ask is None and yes_bid is not None:
        no_ask = 1.0 - yes_bid
    if yes_bid is None and no_ask is not None:
        yes_bid = 1.0 - no_ask
    if no_bid is None and yes_ask is not None:
        no_bid = 1.0 - yes_ask

    result = str(market.get("result") or "").upper()
    if result in {"YES", "NO"}:
        mark = 1.0 if normalized_side == result else 0.0
        source = "settlement"
        bid = mark
        ask = mark
    else:
        bid = yes_bid if normalized_side == "YES" else no_bid
        ask = yes_ask if normalized_side == "YES" else no_ask
        bid = bid if bid is not None and 0.0 <= bid <= 1.0 else None
        ask = ask if ask is not None and 0.0 <= ask <= 1.0 else None
        if bid is not None and ask is not None and ask >= bid:
            mark = (bid + ask) / 2.0
            source = "midpoint"
        elif bid is not None:
            mark = bid
            source = "best_bid"
        elif ask is not None:
            mark = ask
            source = "best_ask"
        else:
            last_yes = _optional_dollar_amount(
                market.get("last_price_dollars"),
                market.get("last_price"),
            )
            if last_yes is not None and 0.0 <= last_yes <= 1.0:
                mark = (
                    last_yes
                    if normalized_side == "YES"
                    else 1.0 - last_yes
                )
                source = "last_trade"
            else:
                mark = None
                source = None
    return {
        "mark": round(mark, 4) if mark is not None else None,
        "bid": round(bid, 4) if bid is not None else None,
        "ask": round(ask, 4) if ask is not None else None,
        "source": source,
        "asOf": (
            market.get("updated_time")
            or market.get("last_trade_time")
            or market.get("close_time")
        ),
    }


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _live_order_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    allowed = {
        "ticker",
        "client_order_id",
        "side",
        "count",
        "price",
        "time_in_force",
        "self_trade_prevention_type",
        "post_only",
        "cancel_order_on_pause",
        "reduce_only",
        "subaccount",
        "exchange_index",
    }
    return {key: value for key, value in dict(payload or {}).items() if key in allowed and value is not None}


def _opposite_outcome(side: Any) -> str:
    normalized = str(side or "").upper()
    if normalized == "YES":
        return "NO"
    if normalized == "NO":
        return "YES"
    return ""


def _live_order_action(order: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    explicit = str(
        order.get("action")
        or payload.get("action")
        or ""
    ).upper()
    if explicit in {"BUY", "SELL"}:
        return explicit
    for source in (order, payload):
        if "reduce_only" in source and source.get("reduce_only") is not None:
            return "SELL" if bool(source.get("reduce_only")) else "BUY"
    return ""


def _live_order_economic_side(order: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    """Recover the contract being increased/reduced from canonical V2 fields.

    Canonical ``outcome_side`` is directional exposure, not always the contract
    named in a legacy BUY/SELL pair: SELL YES has outcome_side=NO, while SELL
    NO has outcome_side=YES.  AlphaLab keeps ``outcome_side`` as the held/traded
    contract for its FIFO ledger and exposes the exchange value separately.
    """
    canonical = str(
        order.get("outcome_side")
        or payload.get("outcome_side")
        or ""
    ).upper()
    action = _live_order_action(order, payload)
    if canonical in {"YES", "NO"}:
        return _opposite_outcome(canonical) if action == "SELL" else canonical

    # Legacy responses used YES/NO in ``side`` to name the contract directly.
    legacy_side = str(order.get("side") or "").upper()
    if legacy_side in {"YES", "NO"}:
        return legacy_side

    book_side = str(
        order.get("book_side")
        or order.get("side")
        or payload.get("book_side")
        or payload.get("side")
        or ""
    ).lower()
    canonical = "YES" if book_side == "bid" else "NO" if book_side == "ask" else ""
    if canonical:
        return _opposite_outcome(canonical) if action == "SELL" else canonical
    return ""


def _normalise_live_order(raw: Mapping[str, Any], payload: Mapping[str, Any], decision: Mapping[str, Any]) -> Dict[str, Any]:
    order = dict(raw or {})
    side = str((decision.get("side") or "")).upper()
    if side not in {"YES", "NO"}:
        side = _live_order_economic_side(order, payload)
    action = _live_order_action(
        order,
        {**dict(payload or {}), "action": decision.get("action") or payload.get("action")},
    )
    reduce_only = action == "SELL"
    canonical_side = str(order.get("outcome_side") or payload.get("outcome_side") or "").upper()
    if canonical_side not in {"YES", "NO"}:
        canonical_side = (
            _opposite_outcome(side)
            if reduce_only and side in {"YES", "NO"}
            else side
        )
    requested = _finite_number(
        _first_present(order, "count_fp", "count")
        if _first_present(order, "count_fp", "count") is not None
        else payload.get("count"),
        0.0,
    )
    filled = _finite_number(
        _first_present(
            order,
            "fill_count_fp",
            "filled_count_fp",
            "fill_count",
            "filled_count",
        ),
        0.0,
    )
    explicit_remaining = order.get("remaining_count_fp")
    if explicit_remaining in (None, ""):
        explicit_remaining = order.get("remaining_count")
    remaining = (
        _finite_number(explicit_remaining, 0.0)
        if explicit_remaining not in (None, "")
        else max(0.0, requested - filled)
    )
    # Event-market V2 transports every order on one YES book.  Preserve the
    # economic price of the outcome the user is actually trading: a 64c YES
    # book price for a NO order is a 36c NO contract, not a 64c NO contract.
    user_side_limit = _finite_number(payload.get("user_side_limit_price"), None)
    if user_side_limit is None:
        user_side_limit = _dollar_amount(
            order.get("no_price_dollars") if side == "NO" else order.get("yes_price_dollars"),
            default=None,
        )
    yes_book_limit = _finite_number(
        order.get("price_dollars") or order.get("price") or payload.get("price"),
        None,
    )
    if user_side_limit is None and yes_book_limit is not None:
        user_side_limit = round(1.0 - yes_book_limit, 8) if side == "NO" else yes_book_limit
    yes_book_average = _finite_number(order.get("average_fill_price"), None)
    if yes_book_average is None:
        yes_book_average = _finite_number(
            order.get("average_price") or order.get("average_price_dollars"),
            None,
        )
    user_side_average = (
        (round(1.0 - yes_book_average, 8) if side == "NO" else yes_book_average)
    ) if yes_book_average is not None else None
    if user_side_average is None:
        user_side_average = _dollar_amount(
            order.get("no_price_dollars") if side == "NO" else order.get("yes_price_dollars"),
            default=None,
        )
    if user_side_average is None:
        user_side_average = user_side_limit

    fee_cost = _dollar_amount(
        order.get("fee_cost_dollars") or order.get("fee_dollars"),
        order.get("fee") or order.get("fees"),
    )
    if fee_cost <= 0 and order.get("average_fee_paid") not in (None, ""):
        fee_cost = round(_finite_number(order.get("average_fee_paid"), 0.0) * filled, 8)

    explicit_status = str(order.get("status") or "").lower()
    if explicit_status:
        status = explicit_status
    elif requested > 0 and filled >= requested:
        status = "filled"
    elif filled > 0:
        status = "partially_filled"
    else:
        status = "submitted"
    return {
        **order,
        "environment": "real",
        "ticker": order.get("ticker") or payload.get("ticker"),
        "order_id": order.get("order_id") or order.get("id") or payload.get("client_order_id"),
        "client_order_id": order.get("client_order_id") or payload.get("client_order_id"),
        "outcome_side": side,
        "canonical_outcome_side": canonical_side,
        "action": action,
        "reduce_only": reduce_only,
        "count_fp": requested,
        "fill_count_fp": filled,
        "remaining_count_fp": remaining,
        "limit_price_dollars": user_side_limit,
        "average_price_dollars": user_side_average,
        "fee_cost_dollars": fee_cost,
        "status": status,
        "time_in_force": order.get("time_in_force") or payload.get("time_in_force") or "immediate_or_cancel",
        "created_time": (
            order.get("created_time")
            or order.get("created_ts")
            or payload.get("created_time")
            or payload.get("created_ts")
        ),
    }


def _normalise_live_fill(
    raw: Mapping[str, Any],
    order_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    fill = dict(raw or {})
    context = dict(order_context or {})
    ticker = fill.get("ticker") or fill.get("market_ticker") or fill.get("market") or fill.get("contract_ticker")
    action = str(fill.get("action") or context.get("action") or "").upper()
    if action not in {"BUY", "SELL"}:
        action = _live_order_action(fill, context)
    context_side = str(context.get("outcome_side") or "").upper()
    canonical_side = str(fill.get("outcome_side") or "").upper()
    legacy_side = str(fill.get("side") or fill.get("result") or "").upper()
    if context_side in {"YES", "NO"}:
        side = context_side
    elif canonical_side in {"YES", "NO"}:
        side = _opposite_outcome(canonical_side) if action == "SELL" else canonical_side
    elif legacy_side in {"YES", "NO"}:
        side = legacy_side
    else:
        side = ""
    if side not in {"YES", "NO"}:
        has_yes = fill.get("yes_price") not in (None, "") or fill.get("yes_price_dollars") not in (None, "")
        has_no = fill.get("no_price") not in (None, "") or fill.get("no_price_dollars") not in (None, "")
        if has_yes and not has_no:
            side = "YES"
        elif has_no and not has_yes:
            side = "NO"
    count = _finite_number(
        _first_present(
            fill,
            "count_fp",
            "fill_count_fp",
            "count",
            "fill_count",
            "contracts",
        ),
        0.0,
    )
    price_dollars = None
    if side in {"YES", "NO"}:
        price_dollars = _dollar_amount(
            fill.get("no_price_dollars") if side == "NO" else fill.get("yes_price_dollars"),
            default=None,
        )
    if price_dollars is None and side in {"YES", "NO"}:
        yes_book_price = _finite_number(
            fill.get("price_dollars") or fill.get("average_price_dollars"),
            None,
        )
        if yes_book_price is not None:
            price_dollars = round(1.0 - yes_book_price, 8) if side == "NO" else yes_book_price
    if price_dollars is None and side in {"YES", "NO"}:
        outcome_cents = (
            fill.get("no_price") if side == "NO"
            else fill.get("yes_price") if side == "YES"
            else None
        )
        if outcome_cents not in (None, ""):
            price_dollars = _cents_amount(outcome_cents) / 100.0
        else:
            yes_book_raw = _finite_number(
                fill.get("price") or fill.get("average_price"),
                0.0,
            )
            yes_book_dollars = yes_book_raw / 100.0 if yes_book_raw > 1 else yes_book_raw
            price_dollars = (
                round(1.0 - yes_book_dollars, 8)
                if side == "NO" and yes_book_dollars > 0
                else yes_book_dollars
            )
    fee_dollars = _dollar_amount(
        fill.get("fee_cost_dollars")
        or fill.get("fee_cost")
        or fill.get("taker_fees_dollars")
        or fill.get("maker_fees_dollars"),
        fill.get("fee") or fill.get("fees") or fill.get("taker_fees") or fill.get("maker_fees"),
    )
    reduce_only = bool(
        fill.get("reduce_only")
        or context.get("reduce_only")
        or action == "SELL"
    )
    return {
        **fill,
        "environment": "real",
        "ticker": ticker,
        "fill_id": fill.get("fill_id") or fill.get("trade_id") or fill.get("id") or fill.get("order_id"),
        "order_id": fill.get("order_id"),
        "outcome_side": side,
        "canonical_outcome_side": canonical_side,
        "action": action,
        "reduce_only": reduce_only,
        "count_fp": count,
        "fill_count_fp": count,
        "price_dollars": price_dollars,
        "average_price_dollars": price_dollars,
        "fee_cost_dollars": fee_dollars,
        "created_time": fill.get("created_time") or fill.get("created_ts") or fill.get("trade_time") or fill.get("updated_time"),
    }


def _reconcile_live_exit_fills(fills) -> list:
    """Attach FIFO cost basis and realized P/L to authenticated SELL fills.

    Kalshi fill rows describe execution, not account-level realized P/L.  This
    helper reconstructs only fully supported round trips from the returned
    history.  A SELL whose complete cost basis is outside the fetched window is
    deliberately left unscored instead of inventing a profit or loss.
    """
    rows = [
        dict(row) for row in list(fills or [])
        if isinstance(row, Mapping)
        and _is_supported_kalshi_ticker(row.get("ticker") or row.get("market_ticker"))
    ]
    rows.sort(key=lambda row: (
        str(row.get("created_time") or ""),
        str(row.get("fill_id") or row.get("order_id") or ""),
    ))
    lots: Dict[Tuple[str, str], list] = {}
    reconciled = []
    for row in rows:
        action = str(row.get("action") or "").upper()
        side = str(row.get("outcome_side") or "").upper()
        ticker = str(row.get("ticker") or row.get("market_ticker") or "")
        count = _finite_number(
            _first_present(row, "count_fp", "fill_count_fp"), 0.0
        )
        price = _finite_number(row.get("average_price_dollars") or row.get("price_dollars"), 0.0)
        fee = max(0.0, _finite_number(row.get("fee_cost_dollars"), 0.0))
        if side not in {"YES", "NO"} or count <= 0 or price <= 0:
            reconciled.append(row)
            continue

        key = (ticker, side)
        queue = lots.setdefault(key, [])
        if action == "BUY":
            queue.append({
                "count": count,
                "price": price,
                "fee": fee,
            })
            reconciled.append(row)
            continue
        if action != "SELL":
            reconciled.append(row)
            continue

        remaining = count
        principal = 0.0
        entry_fee = 0.0
        while remaining > 1e-9 and queue:
            lot = queue[0]
            available = _finite_number(lot.get("count"), 0.0)
            matched = min(remaining, available)
            fraction = matched / available if available > 0 else 0.0
            principal += matched * _finite_number(lot.get("price"), 0.0)
            allocated_fee = _finite_number(lot.get("fee"), 0.0) * fraction
            entry_fee += allocated_fee
            lot["count"] = max(0.0, available - matched)
            lot["fee"] = max(0.0, _finite_number(lot.get("fee"), 0.0) - allocated_fee)
            remaining -= matched
            if lot["count"] <= 1e-9:
                queue.pop(0)

        # Consume any known inventory above, but publish a P/L record only when
        # the entire SELL has an authenticated cost basis in this fill window.
        if remaining > 1e-9:
            reconciled.append(row)
            continue
        gross_proceeds = count * price
        realized_pnl = gross_proceeds - fee - principal - entry_fee
        reconciled.append({
            **row,
            "reduce_only": True,
            "position_cost_dollars": round(principal, 8),
            "gross_proceeds_dollars": round(gross_proceeds, 8),
            "entry_fee_allocated_dollars": round(entry_fee, 8),
            "realized_pnl_dollars": round(realized_pnl, 8),
        })
    return reconciled


def _open_live_fill_inventory(fills) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Rebuild open FIFO lots from canonical Kalshi fills.

    The authenticated position endpoint is authoritative for quantity. Fill
    history supplies the missing entry economics used by exit decisions, so
    market exposure is never mistaken for cost basis.
    """
    queues: Dict[Tuple[str, str], list] = {}
    last_trade: Dict[Tuple[str, str], Any] = {}
    rows = sorted(
        [dict(row) for row in fills or [] if isinstance(row, Mapping)],
        key=lambda row: (
            str(row.get("created_time") or ""),
            str(row.get("fill_id") or row.get("order_id") or ""),
        ),
    )
    for row in rows:
        ticker = str(row.get("ticker") or row.get("market_ticker") or "")
        side = str(row.get("outcome_side") or "").upper()
        action = str(row.get("action") or "").upper()
        count = _finite_number(
            _first_present(row, "count_fp", "fill_count_fp"), 0.0
        )
        price = _finite_number(row.get("average_price_dollars") or row.get("price_dollars"), 0.0)
        if not _is_supported_kalshi_ticker(ticker) or side not in {"YES", "NO"} or count <= 0:
            continue
        key = (ticker, side)
        queue = queues.setdefault(key, [])
        last_trade[key] = row.get("created_time")
        if action == "BUY" and price > 0:
            queue.append({
                "count": count,
                "price": price,
                "fee": max(0.0, _finite_number(row.get("fee_cost_dollars"), 0.0)),
            })
        elif action == "SELL":
            remaining = count
            while remaining > 1e-9 and queue:
                lot = queue[0]
                available = _finite_number(lot.get("count"), 0.0)
                matched = min(remaining, available)
                fraction = matched / available if available > 0 else 0.0
                lot["count"] = max(0.0, available - matched)
                lot["fee"] = max(0.0, _finite_number(lot.get("fee"), 0.0) * (1.0 - fraction))
                remaining -= matched
                if lot["count"] <= 1e-9:
                    queue.pop(0)

    result: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, queue in queues.items():
        count = sum(_finite_number(lot.get("count"), 0.0) for lot in queue)
        if count <= 1e-9:
            continue
        principal = sum(
            _finite_number(lot.get("count"), 0.0) * _finite_number(lot.get("price"), 0.0)
            for lot in queue
        )
        result[key] = {
            "count": count,
            "principal": principal,
            "averagePrice": principal / count,
            "entryFee": sum(_finite_number(lot.get("fee"), 0.0) for lot in queue),
            "lastTradeAt": last_trade.get(key),
        }
    return result


def _durable_managed_inventory(
    state: Mapping[str, Any],
) -> Dict[Tuple[str, str], float]:
    """Rebuild AlphaLab-owned counts from authoritative durable fill evidence.

    ``filledTrades`` is the crash-safe provenance boundary used by the router.
    A position that exists at Kalshi but is not covered by these rows is
    deliberately treated as manual/unmanaged.
    """
    by_identity: Dict[str, Dict[str, Any]] = {}
    anonymous = []
    for raw in state.get("filledTrades") or []:
        if not isinstance(raw, Mapping) or not raw.get("orderFilled"):
            continue
        row = dict(raw)
        identity = str(
            row.get("orderId")
            or row.get("clientOrderId")
            or row.get("order_id")
            or row.get("client_order_id")
            or ""
        )
        if identity:
            # Delayed reconciliation may promote the same order with a more
            # complete fill count. Keep the latest durable representation.
            by_identity[identity] = row
        else:
            anonymous.append(row)
    rows = list(by_identity.values()) + anonymous
    rows.sort(key=lambda row: str(
        row.get("generatedAt")
        or row.get("created_time")
        or row.get("createdAt")
        or ""
    ))
    inventory: Dict[Tuple[str, str], float] = {}
    for row in rows:
        ticker = str(row.get("ticker") or row.get("market_ticker") or "")
        side = str(row.get("side") or row.get("outcome_side") or "").upper()
        action = str(row.get("action") or "").upper()
        count = _finite_number(
            _first_present(
                row,
                "fill_count_fp",
                "count_fp",
                "fillCount",
                "fill_count",
                "count",
            ),
            0.0,
        )
        if (
            not ticker
            or side not in {"YES", "NO"}
            or count <= 0.0
        ):
            continue
        key = (ticker, side)
        if action == "BUY" or action.startswith("BUY_"):
            inventory[key] = inventory.get(key, 0.0) + count
        elif action == "SELL" or action.startswith("SELL_"):
            inventory[key] = max(0.0, inventory.get(key, 0.0) - count)
    return {
        key: count
        for key, count in inventory.items()
        if count > 1e-9
    }


def _normalise_live_settlement(raw: Mapping[str, Any]) -> Dict[str, Any]:
    settlement = dict(raw or {})
    ticker = settlement.get("ticker") or settlement.get("market_ticker") or settlement.get("market") or settlement.get("contract_ticker")
    result = str(settlement.get("market_result") or settlement.get("result") or settlement.get("settlement_value") or "").upper()
    if result not in {"YES", "NO"}:
        value = _finite_number(settlement.get("yes_win") or settlement.get("value"), float("nan"))
        if math.isfinite(value):
            result = "YES" if value >= (0.5 if 0 <= value <= 1 else 50.0) else "NO"
    return {
        **settlement,
        "environment": "real",
        "ticker": ticker,
        "market_ticker": ticker,
        "market_result": result,
        "settled_time": (
            settlement.get("settled_time")
            or settlement.get("settlement_time")
            or settlement.get("determined_time")
            or settlement.get("created_time")
            or settlement.get("updated_time")
        ),
        "yes_count_fp": _finite_number(
            _first_present(
                settlement, "yes_count_fp", "yes_count", "yes_position"
            ),
            0.0,
        ),
        "no_count_fp": _finite_number(
            _first_present(
                settlement, "no_count_fp", "no_count", "no_position"
            ),
            0.0,
        ),
        "revenue_dollars": _dollar_amount(
            settlement.get("revenue_dollars"),
            settlement.get("revenue") or settlement.get("settlement_value") or settlement.get("proceeds"),
        ),
        "yes_total_cost_dollars": _dollar_amount(
            settlement.get("yes_total_cost_dollars"),
            settlement.get("yes_total_cost") or settlement.get("yes_cost"),
        ),
        "no_total_cost_dollars": _dollar_amount(
            settlement.get("no_total_cost_dollars"),
            settlement.get("no_total_cost") or settlement.get("no_cost"),
        ),
        "fee_cost_dollars": _dollar_amount(
            settlement.get("fee_cost_dollars") or settlement.get("fee_cost"),
            settlement.get("fees") or settlement.get("fee"),
        ),
    }


def _credential_fields(environment: str) -> Tuple[str, str]:
    prefix = _environment_name(environment)
    return f"{prefix}_api_key_id", f"{prefix}_private_key"


def _normalize_private_key(value: Any) -> str:
    raw = str(value or "").strip().replace("\\n", "\n")
    if not raw or len(raw) > 20_000:
        raise KalshiApiError("A valid Kalshi RSA private key is required", status=400, code="invalid_private_key")
    match = re.search(
        r"-----BEGIN (?:RSA )?PRIVATE KEY-----(.*?)-----END (?:RSA )?PRIVATE KEY-----",
        raw,
        flags=re.DOTALL,
    )
    if match:
        body = re.sub(r"\s+", "", match.group(1))
        label = "RSA PRIVATE KEY" if "BEGIN RSA PRIVATE KEY" in raw else "PRIVATE KEY"
        wrapped = "\n".join(body[index:index + 64] for index in range(0, len(body), 64))
        raw = f"-----BEGIN {label}-----\n{wrapped}\n-----END {label}-----"
    return raw


def _load_rsa_private_key(value: Any):
    try:
        key = serialization.load_pem_private_key(_normalize_private_key(value).encode("utf-8"), password=None)
    except Exception as exc:
        raise KalshiApiError(
            "The Kalshi private key is not a valid unencrypted RSA PEM key",
            status=400,
            code="invalid_private_key",
        ) from exc
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
        raise KalshiApiError(
            "Kalshi requires an RSA private key of at least 2048 bits",
            status=400,
            code="invalid_private_key",
        )
    return key


def _signed_headers(api_key_id: str, private_key: str, method: str, path: str, *, timestamp_ms: Optional[int] = None):
    key_id = str(api_key_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,200}", key_id):
        raise KalshiApiError("A valid Kalshi API Key ID is required", status=400, code="invalid_api_key_id")
    clean_path = str(path or "").split("?", 1)[0]
    timestamp = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
    message = f"{timestamp}{str(method).upper()}{clean_path}".encode("utf-8")
    signature = _load_rsa_private_key(private_key).sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256(),
    )
    return {
        "Accept": "application/json",
        "KALSHI-ACCESS-KEY": key_id,
        "KALSHI-ACCESS-TIMESTAMP": str(timestamp),
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("ascii"),
        "User-Agent": "AlphaLab-Kalshi/1.0",
    }


class _PublicDataClient:
    def __init__(self, *, http_get=None, safe_print=print):
        self.http_get = http_get or requests.get
        # Injected transports are deterministic tests/offline adapters. They
        # may not implement the optional series endpoints, so automatic fee
        # refresh is limited to the real public transport; callers can still
        # invoke ``series_fee_policy`` explicitly with an injected transport.
        self._automatic_fee_policy = http_get is None
        self.safe_print = safe_print
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_meta: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.RLock()
        self._inflight: Dict[str, threading.Event] = {}
        self._key_retry_until: Dict[str, float] = {}
        self._key_errors: Dict[str, KalshiApiError] = {}
        self._host_backoff: Dict[str, Dict[str, Any]] = {}
        self._host_request_locks = {
            self._host_name(base): threading.Lock()
            for base in KALSHI_PUBLIC_BASES
        }
        self._max_cache_entries = 512
        self._kalshi_last_attempt_at: Optional[str] = None
        self._kalshi_last_success_at: Optional[str] = None
        self._kalshi_last_success_host: Optional[str] = None
        self._kalshi_last_error: Optional[str] = None
        self._headers = {
            "Accept": "application/json",
            "User-Agent": "AlphaLab-Kalshi-Research/1.0",
        }

    @staticmethod
    def _host_name(url: str) -> str:
        return str(urlsplit(str(url or "")).hostname or "unknown").lower()

    @staticmethod
    def _request_status(response: Any, error: Exception) -> Optional[int]:
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(getattr(error, "response", None), "status_code", None)
        try:
            return int(status) if status is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _retry_after_seconds(response: Any) -> Optional[float]:
        headers = getattr(response, "headers", None) or {}
        raw = None
        try:
            raw = headers.get("Retry-After") or headers.get("retry-after")
        except AttributeError:
            return None
        if raw in (None, ""):
            return None
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(raw))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(
                    0.0,
                    (retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds(),
                )
            except (TypeError, ValueError, OverflowError):
                return None

    @staticmethod
    def _kalshi_url_candidates(url: str) -> list:
        raw = str(url or "")
        for base in KALSHI_PUBLIC_BASES:
            if raw == base or raw.startswith(base + "/"):
                suffix = raw[len(base):]
                return [raw] + [
                    candidate + suffix
                    for candidate in KALSHI_PUBLIC_BASES
                    if candidate != base
                ]
        return [raw]

    def _mark_host_failure(
        self,
        url: str,
        *,
        status: Optional[int],
        response: Any,
    ) -> float:
        """Apply process-wide-per-client cooldown for one public Kalshi host."""
        host = self._host_name(url)
        now = time.monotonic()
        with self._cache_lock:
            previous = dict(self._host_backoff.get(host) or {})
            failures = int(previous.get("failures") or 0) + 1
            if status == 429:
                exponential = min(120.0, float(2 ** min(failures, 6)))
                supplied = self._retry_after_seconds(response)
                delay = min(300.0, max(exponential, supplied or 0.0))
                reason = "http_429"
            else:
                delay = min(30.0, float(2 ** min(max(0, failures - 1), 5)))
                reason = f"http_{status}" if status is not None else "transport_error"
            until = max(float(previous.get("until") or 0.0), now + delay)
            self._host_backoff[host] = {
                "until": until,
                "failures": failures,
                "reason": reason,
            }
            self._kalshi_last_error = reason
        self.safe_print(
            f"[Kalshi] public host backoff host={host} "
            f"reason={reason} retryInSeconds={round(max(0.0, until - now), 1)}"
        )
        return until

    def _mark_host_success(self, url: str) -> None:
        host = self._host_name(url)
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._cache_lock:
            self._host_backoff.pop(host, None)
            self._kalshi_last_success_at = now_iso
            self._kalshi_last_success_host = host
            self._kalshi_last_error = None

    def _stale_locked(
        self,
        key: str,
        *,
        max_stale: float,
        now: float,
    ) -> Optional[Tuple[float, Any]]:
        cached = self._cache.get(key)
        if not cached:
            return None
        age = max(0.0, now - cached[0])
        return cached if age <= max(0.0, float(max_stale)) else None

    def _serve_stale_locked(
        self,
        key: str,
        cached: Tuple[float, Any],
        *,
        now: float,
        error_code: str,
    ) -> Any:
        age = max(0.0, now - cached[0])
        meta = self._cache_meta.setdefault(key, {})
        meta.update({
            "servedStale": True,
            "servedStaleAtMonotonic": now,
            "ageSeconds": round(age, 3),
            "lastError": error_code,
        })
        return cached[1]

    def _prune_cache_locked(self, *, now: Optional[float] = None) -> None:
        """Bound rotating market keys and discard expired retry diagnostics."""
        now = time.monotonic() if now is None else float(now)
        for key, retry_until in list(self._key_retry_until.items()):
            if float(retry_until or 0.0) <= now:
                self._key_retry_until.pop(key, None)
                self._key_errors.pop(key, None)
        for host, item in list(self._host_backoff.items()):
            if float((item or {}).get("until") or 0.0) <= now:
                self._host_backoff.pop(host, None)
        overflow = max(0, len(self._cache) - self._max_cache_entries)
        if overflow <= 0:
            return
        oldest = sorted(
            (
                (float(fetched_at), key)
                for key, (fetched_at, _payload) in self._cache.items()
                if key not in self._inflight
            ),
            key=lambda item: item[0],
        )
        for _fetched_at, key in oldest[:overflow]:
            self._cache.pop(key, None)
            self._cache_meta.pop(key, None)
            self._key_retry_until.pop(key, None)
            self._key_errors.pop(key, None)

    def _cached_json(
        self,
        key: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        ttl: float,
        timeout: float = 8.0,
        max_stale: float = 0.0,
    ) -> Any:
        wait_timeout = max(1.0, float(timeout) * 2.0 + 1.0)
        while True:
            now = time.monotonic()
            with self._cache_lock:
                cached = self._cache.get(key)
                if cached and now - cached[0] <= ttl:
                    meta = self._cache_meta.setdefault(key, {})
                    meta.update({
                        "servedStale": False,
                        "ageSeconds": round(max(0.0, now - cached[0]), 3),
                    })
                    return cached[1]

                retry_until = float(self._key_retry_until.get(key) or 0.0)
                if retry_until > now:
                    stale = self._stale_locked(key, max_stale=max_stale, now=now)
                    if stale:
                        return self._serve_stale_locked(
                            key,
                            stale,
                            now=now,
                            error_code=(self._key_errors.get(key) or KalshiApiError("retry deferred")).code,
                        )
                    previous_error = self._key_errors.get(key)
                    if previous_error is not None:
                        raise KalshiApiError(
                            str(previous_error),
                            status=previous_error.status,
                            code=previous_error.code,
                        )

                flight = self._inflight.get(key)
                if flight is None:
                    flight = threading.Event()
                    self._inflight[key] = flight
                    break

            if not flight.wait(wait_timeout):
                now = time.monotonic()
                with self._cache_lock:
                    stale = self._stale_locked(key, max_stale=max_stale, now=now)
                    if stale:
                        return self._serve_stale_locked(
                            key,
                            stale,
                            now=now,
                            error_code="kalshi_public_request_coalescing_timeout",
                        )
                raise KalshiApiError(
                    "Timed out waiting for the shared public-data refresh",
                    status=503,
                    code="kalshi_public_request_timeout",
                )

        try:
            candidates = self._kalshi_url_candidates(url)
            is_kalshi = any(
                str(url or "") == base or str(url or "").startswith(base + "/")
                for base in KALSHI_PUBLIC_BASES
            )
            if is_kalshi:
                with self._cache_lock:
                    self._kalshi_last_attempt_at = (
                        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    )

            errors = []
            skipped_until = []
            payload = None
            selected_url = None
            for candidate_url in candidates[:2]:
                host = self._host_name(candidate_url)
                with self._cache_lock:
                    backoff_until = float(
                        (self._host_backoff.get(host) or {}).get("until") or 0.0
                    )
                now = time.monotonic()
                if is_kalshi and backoff_until > now:
                    skipped_until.append(backoff_until)
                    continue

                response = None
                request_gate = (
                    self._host_request_locks.setdefault(host, threading.Lock())
                    if is_kalshi
                    else nullcontext()
                )
                with request_gate:
                    if is_kalshi:
                        with self._cache_lock:
                            backoff_until = float(
                                (self._host_backoff.get(host) or {}).get("until")
                                or 0.0
                            )
                        now = time.monotonic()
                        if backoff_until > now:
                            skipped_until.append(backoff_until)
                            continue
                    try:
                        response = self.http_get(
                            candidate_url,
                            params=dict(params or {}),
                            headers=self._headers,
                            timeout=timeout,
                        )
                        if hasattr(response, "raise_for_status"):
                            response.raise_for_status()
                        payload = response.json() if hasattr(response, "json") else response
                        selected_url = candidate_url
                        if is_kalshi:
                            self._mark_host_success(candidate_url)
                        break
                    except Exception as exc:
                        status = self._request_status(response, exc)
                        errors.append((exc, status))
                        if is_kalshi:
                            retryable_host_failure = bool(
                                status == 429
                                or status is None
                                or status >= 500
                                or 200 <= status < 300
                            )
                            if retryable_host_failure:
                                skipped_until.append(
                                    self._mark_host_failure(
                                        candidate_url,
                                        status=status,
                                        response=(
                                            response
                                            if response is not None
                                            else getattr(exc, "response", None)
                                        ),
                                    )
                                )
                            else:
                                with self._cache_lock:
                                    self._kalshi_last_error = f"http_{status}"
                            # Try the other supported official host, but only
                            # retryable failures open a shared host cooldown.
                            continue
                        break

            if selected_url is not None:
                fetched_monotonic = time.monotonic()
                fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                with self._cache_lock:
                    self._cache[key] = (fetched_monotonic, payload)
                    self._cache_meta[key] = {
                        "fetchedAt": fetched_at,
                        "servedStale": False,
                        "ageSeconds": 0.0,
                        "sourceHost": self._host_name(selected_url),
                    }
                    self._key_retry_until.pop(key, None)
                    self._key_errors.pop(key, None)
                    self._prune_cache_locked(now=fetched_monotonic)
                return payload

            rate_limited = bool(
                skipped_until
                and (
                    not errors
                    or any(status == 429 for _error, status in errors)
                )
            )
            public_error = KalshiApiError(
                (
                    "Kalshi public market data is temporarily rate limited"
                    if rate_limited
                    else "Kalshi public market data is temporarily unavailable"
                ),
                status=503,
                code=(
                    KALSHI_PUBLIC_RATE_LIMITED
                    if rate_limited
                    else "kalshi_public_data_unavailable"
                ),
            )
            if is_kalshi:
                # Any complete public-data failure must make readiness fail
                # closed, including non-retryable 4xx responses and malformed
                # JSON returned with HTTP 200. A later successful response from
                # either official host clears this state in _mark_host_success.
                with self._cache_lock:
                    self._kalshi_last_error = public_error.code
            now = time.monotonic()
            retry_at = (
                min(value for value in skipped_until if value > now)
                if any(value > now for value in skipped_until)
                else now + 1.0
            )
            with self._cache_lock:
                self._key_retry_until[key] = retry_at
                self._key_errors[key] = public_error
                stale = self._stale_locked(key, max_stale=max_stale, now=now)
                if stale:
                    result = self._serve_stale_locked(
                        key,
                        stale,
                        now=now,
                        error_code=public_error.code,
                    )
                else:
                    result = None
            key_type = str(key or "unknown").split(":", 1)[0][:48]
            self.safe_print(
                f"[Kalshi] public fetch degraded keyType={key_type} "
                f"reason={public_error.code} servedStale={bool(stale)}"
            )
            if stale:
                return result
            raise public_error from (errors[-1][0] if errors else None)
        finally:
            with self._cache_lock:
                completed = self._inflight.pop(key, None)
                if completed is not None:
                    completed.set()

    def _cache_status(self, key: str) -> Dict[str, Any]:
        with self._cache_lock:
            meta = dict(self._cache_meta.get(key) or {})
            cached = self._cache.get(key)
        if cached:
            meta["ageSeconds"] = round(max(0.0, time.monotonic() - cached[0]), 3)
        return meta

    def runtime_snapshot(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._cache_lock:
            self._prune_cache_locked(now=now)
            backoffs = [
                {
                    "host": host,
                    "reason": str(item.get("reason") or "unknown"),
                    "retryInSeconds": round(
                        max(0.0, float(item.get("until") or 0.0) - now),
                        3,
                    ),
                }
                for host, item in self._host_backoff.items()
                if float(item.get("until") or 0.0) > now
            ]
            attempted = self._kalshi_last_attempt_at is not None
            last_error = self._kalshi_last_error
            last_success_at = self._kalshi_last_success_at
            last_success_host = self._kalshi_last_success_host
            stale_entries = sum(
                bool(
                    meta.get("servedStale")
                    and now - float(meta.get("servedStaleAtMonotonic") or 0.0)
                    <= 60.0
                )
                for meta in self._cache_meta.values()
            )
            cache_entries = len(self._cache)
        healthy = bool(not attempted or not last_error)
        using_fallback = bool(
            healthy
            and last_success_host == self._host_name(KALSHI_PUBLIC_FALLBACK_BASE)
        )
        return {
            "healthy": healthy,
            "status": (
                "idle" if not attempted else
                "degraded" if not healthy else
                "fallback" if using_fallback else
                "healthy"
            ),
            "lastSuccessAt": last_success_at,
            "lastSuccessHost": last_success_host,
            "lastError": last_error,
            "activeBackoffs": backoffs,
            "cacheEntries": cache_entries,
            "staleCacheEntries": stale_entries,
        }

    @staticmethod
    def _top_book_from_market(market: Mapping[str, Any]) -> Dict[str, Any]:
        """Build a valid top-level fallback from Kalshi's market quote fields."""
        yes_bid = _finite_number(market.get("yes_bid_dollars"), -1.0)
        no_bid = _finite_number(market.get("no_bid_dollars"), -1.0)
        yes_size = _finite_number(market.get("yes_bid_size_fp"), 0.0)
        # A YES ask is the reciprocal NO bid.  Kalshi exposes the matching YES
        # ask size on the market object even when no_bid_size_fp is omitted.
        no_size = _finite_number(
            market.get("no_bid_size_fp", market.get("yes_ask_size_fp")),
            0.0,
        )
        return {
            "yes": [[yes_bid, yes_size]] if 0.0 < yes_bid < 1.0 and yes_size > 0 else [],
            "no": [[no_bid, no_size]] if 0.0 < no_bid < 1.0 and no_size > 0 else [],
        }

    def _market_candidates(self, now: datetime, base_url: str):
        environment_key = "production"
        live_key = f"kalshi-btc15-open:{environment_key}"
        live_payload = self._cached_json(
            live_key,
            f"{base_url}/markets",
            params={"series_ticker": BTC_15M_SERIES, "status": "open", "limit": 100},
            ttl=4.0,
            max_stale=20.0,
        )
        live_markets = list((live_payload or {}).get("markets") or [])
        market, selection = select_btc15_market(live_markets, now, min_active_seconds_to_close=45.0)
        if market and selection == "active":
            return market, selection

        schedule_key = f"kalshi-btc15-schedule:{environment_key}"
        schedule_payload = self._cached_json(
            schedule_key,
            f"{base_url}/markets",
            params={"series_ticker": BTC_15M_SERIES, "limit": 100},
            ttl=60.0,
            max_stale=300.0,
        )
        combined = live_markets + list((schedule_payload or {}).get("markets") or [])
        return select_btc15_market(combined, now, min_active_seconds_to_close=45.0)

    def market(self, ticker: str) -> Dict[str, Any]:
        payload = self._cached_json(
            f"kalshi-market:{ticker}",
            f"{KALSHI_PUBLIC_BASE}/markets/{str(ticker)}",
            ttl=2.0,
            max_stale=15.0,
        )
        return dict((payload or {}).get("market") or payload or {})

    def _optional_public_json(
        self,
        key: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        ttl: float,
        timeout: float = 5.0,
    ) -> Any:
        """Cache optional metadata without degrading execution-data health.

        Fee metadata can disable maker shadow when absent, but it must never
        open the shared market-data host backoff and thereby starve a required
        orderbook/reference request.  Taker execution keeps its conservative
        0.07 fallback while this optional fetch recovers.
        """
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] <= max(0.0, float(ttl)):
                return cached[1]
        errors = []
        for candidate_url in self._kalshi_url_candidates(url)[:2]:
            try:
                response = self.http_get(
                    candidate_url,
                    params=dict(params or {}),
                    headers=self._headers,
                    timeout=timeout,
                )
                if hasattr(response, "raise_for_status"):
                    response.raise_for_status()
                payload = (
                    response.json() if hasattr(response, "json") else response
                )
                fetched = time.monotonic()
                with self._cache_lock:
                    self._cache[key] = (fetched, payload)
                    self._cache_meta[key] = {
                        "fetchedAt": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "servedStale": False,
                        "ageSeconds": 0.0,
                        "sourceHost": self._host_name(candidate_url),
                        "optional": True,
                    }
                    self._prune_cache_locked(now=fetched)
                return payload
            except Exception as exc:
                errors.append(exc)
        raise KalshiApiError(
            "Optional Kalshi series fee metadata is unavailable",
            status=503,
            code="kalshi_fee_policy_unavailable",
        ) from (errors[-1] if errors else None)

    def series_fee_policy(
        self,
        series_ticker: str,
        *,
        base_url: str = KALSHI_PUBLIC_BASE,
    ) -> Dict[str, Any]:
        """Return current fee metadata plus scheduled changes for a series."""
        series = str(series_ticker or "").strip().upper()
        if not series:
            return {"available": False, "reason": "series_ticker_missing"}
        current_payload = self._optional_public_json(
            f"kalshi-series-fee:{base_url}:{series}",
            f"{base_url}/series/{series}",
            ttl=60.0,
        )
        current = dict((current_payload or {}).get("series") or {})
        try:
            changes_payload = self._optional_public_json(
                f"kalshi-series-fee-changes:{base_url}:{series}",
                f"{base_url}/series/fee_changes",
                params={
                    "series_ticker": series,
                    "show_historical": False,
                },
                ttl=30.0,
            )
            changes = [
                {
                    "id": row.get("id"),
                    "feeType": row.get("fee_type"),
                    "feeMultiplier": row.get("fee_multiplier"),
                    "scheduledAt": row.get("scheduled_ts"),
                }
                for row in (
                    (changes_payload or {}).get("series_fee_change_arr") or []
                )
                if str(row.get("series_ticker") or "").upper() in {"", series}
            ]
        except KalshiApiError:
            changes = []
        fee_type = str(current.get("fee_type") or "").strip().lower()
        fee_multiplier = _finite_number(current.get("fee_multiplier"), None)
        recognized = fee_type in {
            "quadratic",
            "quadratic_with_maker_fees",
        }
        available = bool(
            recognized
            and fee_multiplier is not None
            and fee_multiplier >= 0.0
        )
        maker_coefficient = (
            0.0175 * fee_multiplier
            if available and fee_type == "quadratic_with_maker_fees"
            else 0.0
            if available and fee_type == "quadratic"
            else None
        )
        return {
            "available": available,
            "seriesTicker": series,
            "feeType": fee_type or None,
            "feeMultiplier": fee_multiplier,
            "takerFeeCoefficient": (
                0.07 * fee_multiplier if available else None
            ),
            "makerFeeCoefficient": maker_coefficient,
            "makerRateKnown": maker_coefficient is not None,
            "scheduledChanges": changes[:10],
            "source": "kalshi_series_and_fee_changes_v2",
            "reason": None if available else "fee_policy_unavailable",
        }

    def snapshot(
        self,
        *,
        now: Optional[datetime] = None,
        base_url: str = KALSHI_PUBLIC_BASE,
        reference_override: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        started_at = time.perf_counter()
        now = now or datetime.now(timezone.utc)
        now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
        warnings = []
        market, selection = self._market_candidates(now, base_url)
        if not market:
            raise KalshiApiError("No KXBTC15M contract was returned by Kalshi")
        market = dict(market)
        try:
            if not self._automatic_fee_policy:
                raise KalshiApiError(
                    "Automatic fee policy refresh is disabled for this transport",
                    code="kalshi_fee_policy_unavailable",
                )
            fee_policy = self.series_fee_policy(
                BTC_15M_SERIES,
                base_url=base_url,
            )
        except KalshiApiError:
            fee_policy = {
                "available": False,
                "seriesTicker": BTC_15M_SERIES,
                "makerRateKnown": False,
                "reason": "fee_policy_unavailable",
            }
        if fee_policy.get("available"):
            market["fee_type"] = fee_policy.get("feeType")
            market["fee_multiplier"] = fee_policy.get("feeMultiplier")
        else:
            warnings.append("kalshi_fee_policy_unavailable")
        market_keys = ["kalshi-btc15-open:production"]
        if selection != "active":
            market_keys.append("kalshi-btc15-schedule:production")
        if any(self._cache_status(key).get("servedStale") for key in market_keys):
            warnings.append("kalshi_market_stale")

        orderbook = {"yes": [], "no": []}
        orderbook_as_of = None
        ticker = str(market.get("ticker") or "")
        if ticker and selection == "active":
            book_key = f"kalshi-orderbook:{base_url}:{ticker}"
            try:
                book_payload = self._cached_json(
                    book_key,
                    f"{base_url}/markets/{ticker}/orderbook",
                    params={"depth": 10},
                    ttl=1.25,
                    max_stale=8.0,
                )
                fixed = (book_payload or {}).get("orderbook_fp") or {}
                orderbook = {
                    "yes": fixed.get("yes_dollars") or [],
                    "no": fixed.get("no_dollars") or [],
                }
                book_status = self._cache_status(book_key)
                orderbook_as_of = book_status.get("fetchedAt")
                if book_status.get("servedStale"):
                    warnings.append("kalshi_orderbook_stale")
            except KalshiApiError:
                warnings.append("kalshi_orderbook_unavailable")
            if not orderbook["yes"] or not orderbook["no"]:
                fallback_book = self._top_book_from_market(market)
                if fallback_book["yes"] and fallback_book["no"]:
                    orderbook = fallback_book
                    orderbook_as_of = (
                        market.get("updated_time")
                        or now.isoformat().replace("+00:00", "Z")
                    )
                    warnings.append("kalshi_top_quote_fallback")

        ticker_payload: Mapping[str, Any] = {}
        venue_payloads: Dict[str, Mapping[str, Any]] = {}
        candles = []
        official_reference = (
            dict(reference_override or {})
            if _finite_number((reference_override or {}).get("price"), 0.0) > 0
            and bool((reference_override or {}).get("isOfficialBrti"))
            else {}
        )
        venue_requests = {
            "coinbase": ("coinbase-btc-ticker", f"{COINBASE_EXCHANGE_BASE}/products/BTC-USD/ticker"),
            "bitstamp": ("bitstamp-btc-ticker", f"{BITSTAMP_BASE}/ticker/btcusd/"),
            "gemini": ("gemini-btc-ticker", f"{GEMINI_BASE}/pubticker/btcusd"),
            "kraken": ("kraken-btc-ticker", f"{KRAKEN_BASE}/Ticker?pair=XBTUSD"),
        }
        proxy = None
        accepted_statuses = []
        if not official_reference:
            with ThreadPoolExecutor(max_workers=len(venue_requests)) as executor:
                futures = {
                    venue: executor.submit(
                        self._cached_json,
                        cache_key,
                        url,
                        ttl=1.0,
                        timeout=4.0,
                        max_stale=10.0,
                    )
                    for venue, (cache_key, url) in venue_requests.items()
                }
                for venue, future in futures.items():
                    try:
                        venue_payloads[venue] = future.result() or {}
                    except KalshiApiError:
                        warnings.append(f"{venue}_reference_unavailable")
            ticker_payload = venue_payloads.get("coinbase") or {}
            venue_quotes = [
                quote for quote in (
                    _venue_quote(venue, payload)
                    for venue, payload in venue_payloads.items()
                ) if quote
            ]
            proxy = _brti_proxy(venue_quotes)
            if not proxy:
                warnings.append("btc_reference_unavailable")
            elif int(proxy.get("venueCount") or 0) < 2:
                warnings.append("brti_proxy_single_venue")
            accepted_venues = set((proxy or {}).get("venues") or [])
            accepted_statuses = [
                self._cache_status(cache_key)
                for venue, (cache_key, _url) in venue_requests.items()
                if venue in accepted_venues
            ]
            if any(item.get("servedStale") for item in accepted_statuses):
                warnings.append("brti_proxy_stale")
        try:
            candles = self._cached_json(
                "coinbase-btc-candles-1m",
                f"{COINBASE_EXCHANGE_BASE}/products/BTC-USD/candles",
                params=_coinbase_btc_candle_params(now),
                # 15s keeps the momentum logit term at most one refresh behind
                # inside the 100-320s decision window while staying far under
                # Coinbase's public rate limits at a 5-second robot cadence.
                ttl=15.0,
                max_stale=120.0,
            ) or []
            if self._cache_status("coinbase-btc-candles-1m").get("servedStale"):
                warnings.append("btc_history_stale")
        except KalshiApiError:
            warnings.append("btc_history_unavailable")

        fetched_at = now.isoformat().replace("+00:00", "Z")
        reference_price = (
            official_reference.get("price")
            or (proxy or {}).get("price")
            or ticker_payload.get("price")
        )
        proxy_fetch_times = [
            str(item.get("fetchedAt")) for item in accepted_statuses if item.get("fetchedAt")
        ]
        fallback_timestamp = (
            min(proxy_fetch_times)
            if proxy and proxy_fetch_times
            else fetched_at if proxy else ticker_payload.get("time")
        )
        reference = {
            "symbol": "BTC-USD",
            "price": reference_price,
            "bid": ticker_payload.get("bid"),
            "ask": ticker_payload.get("ask"),
            "timestamp": official_reference.get("timestamp") or fallback_timestamp,
            "model": official_reference.get("model") or (
                "brti_constituent_proxy" if proxy else "coinbase_fallback"
            ),
            "isOfficialBrti": bool(official_reference),
            "venueCount": int(
                official_reference.get("venueCount")
                or (proxy or {}).get("venueCount")
                or 0
            ),
            "venues": list(
                official_reference.get("venues")
                or (proxy or {}).get("venues")
                or []
            ),
            "rejectedVenues": list(
                official_reference.get("rejectedVenues")
                or (proxy or {}).get("rejectedVenues")
                or []
            ),
            "dispersionBps": round(
                _finite_number(
                    official_reference.get("dispersionBps", (proxy or {}).get("dispersionBps"))
                ),
                4,
            ),
            "venueQuotes": list((proxy or {}).get("quotes") or []),
            "candles": candles,
            "candleCount": len(candles),
        }
        for key in (
            "rawPrice", "trailing60sAverage", "settlementWindowAverage",
            "settlementWindowSamples", "settlementWindowProgress", "receivedAt",
            "streamAgeSeconds", "streamStatus", "sourceSequence",
        ):
            if key in official_reference:
                reference[key] = official_reference.get(key)
        return {
            "asOf": fetched_at,
            "latencyMs": int(round((time.perf_counter() - started_at) * 1000)),
            "selection": selection,
            "seriesTicker": BTC_15M_SERIES,
            "market": market,
            "orderbook": orderbook,
            "orderbookAsOf": orderbook_as_of,
            "reference": reference,
            "feePolicy": fee_policy,
            "warnings": warnings,
            "sources": {
                "contract": f"Kalshi {BTC_15M_SERIES}",
                "orderbook": "Kalshi public market orderbook",
                "settlement": "CF Benchmarks BRTI",
                "spotReference": (
                    "Official CF Benchmarks BRTI via Kalshi WebSocket"
                    if official_reference
                    else "BRTI constituent-exchange proxy (Coinbase, Bitstamp, Gemini, Kraken)"
                ),
            },
        }

    def hourly_snapshot(
        self,
        *,
        now: Optional[datetime] = None,
        base_url: str = KALSHI_PUBLIC_BASE,
        reference_override: Optional[Mapping[str, Any]] = None,
        required_tickers: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Return the nearest active KXBTCD event and executable strike books.

        The hourly event is a ladder of binary strike contracts.  It is kept
        separate from the 15-minute contract selector, while sharing the same
        BRTI-proxy reference evidence and candle history.
        """
        started_at = time.perf_counter()
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        required = {
            str(value or "").strip()
            for value in (required_tickers or [])
            if _market_family(value) == "btchourly"
        }
        reference_snapshot = self.snapshot(
            now=now,
            base_url=base_url,
            reference_override=reference_override,
        )
        # KXBTCD currently exposes hundreds of strikes across only a handful
        # of events. Querying nested events prevents a 100-market page from
        # hiding the next event, while min_close_ts excludes already expired
        # ladders at the API boundary.
        hourly_events_key = f"kalshi-btchourly-events:{base_url}"
        payload = self._cached_json(
            hourly_events_key,
            f"{base_url}/events",
            params={
                "series_ticker": BTC_HOURLY_SERIES,
                "status": "open",
                "with_nested_markets": True,
                "min_close_ts": int(now.timestamp() + 45),
                "limit": 200,
            },
            ttl=10.0,
            max_stale=30.0,
        )
        markets = [
            dict(market)
            for event in ((payload or {}).get("events") or [])
            if isinstance(event, Mapping)
            for market in (event.get("markets") or [])
            if isinstance(market, Mapping)
        ]
        eligible = []
        for market in markets:
            close_at = _parse_utc(market.get("close_time") or market.get("close_ts"))
            seconds = (close_at - now).total_seconds() if close_at else -1
            if 45 <= seconds <= 3700 and str(market.get("status") or "").lower() in {"active", "open"}:
                ticker = str(market.get("ticker") or "")
                eligible.append((
                    seconds,
                    _kalshi_event_ticker(ticker, market),
                    market,
                ))
        if not eligible:
            raise KalshiApiError(
                "No KXBTCD hourly event is inside the trading window",
                status=409,
                code=KALSHI_NO_ACTIVE_HOURLY_MARKET,
            )
        required_eligible = [
            item
            for item in eligible
            if str((item[2] or {}).get("ticker") or "") in required
        ]
        # If AlphaLab already owns a strike, select its event before the
        # nearest fresh event. This makes the snapshot a position-management
        # input and prevents a higher-edge sibling/new event from replacing it.
        nearest_seconds, event_ticker, anchor_market = min(
            required_eligible or eligible,
            key=lambda item: item[0],
        )
        event_markets = [market for seconds, event, market in eligible if event == event_ticker]
        reference_policy = _hourly_reference_policy(
            reference_snapshot.get("reference") or {},
            anchor_market,
            now=now,
            seconds_to_close=nearest_seconds,
        )
        selected_reference = _finite_number(
            reference_policy.get("selectedPrice"),
            None,
        )
        if selected_reference is None or selected_reference <= 0.0:
            raise KalshiApiError(
                "KXBTCD requires a fresh raw BRTI reference; the generic "
                "BTC15 settlement estimate cannot be used for hourly strikes.",
                status=409,
                code="btc_reference_unavailable",
            )
        spot = selected_reference
        event_markets.sort(
            key=lambda market: abs(_finite_number(market.get("floor_strike"), spot) - spot)
        )
        # The batch endpoint makes a wider ladder cheap.  Keep all contracts
        # with a two-sided direct quote plus nearby strikes, then cap at 32 so
        # the probability fit remains focused on the liquid part of the event.
        quoted = [
            market for market in event_markets
            if 0.0 < _finite_number(market.get("yes_bid_dollars"), -1.0) < 1.0
            and 0.0 < _finite_number(market.get("yes_ask_dollars"), -1.0) < 1.0
        ]
        required_event_markets = [
            market for market in event_markets
            if str(market.get("ticker") or "") in required
        ]
        selected_by_ticker = {
            str(market.get("ticker") or ""): market
            for market in (required_event_markets + event_markets[:16] + quoted)
            if str(market.get("ticker") or "")
        }
        required_selected = [
            selected_by_ticker[str(market.get("ticker") or "")]
            for market in required_event_markets
            if str(market.get("ticker") or "") in selected_by_ticker
        ]
        required_selected_tickers = {
            str(market.get("ticker") or "") for market in required_selected
        }
        optional_selected = [
            market for ticker, market in selected_by_ticker.items()
            if ticker not in required_selected_tickers
        ]
        optional_selected.sort(
            key=lambda market: abs(_finite_number(market.get("floor_strike"), spot) - spot)
        )
        selected_markets = (
            required_selected
            + optional_selected[:max(0, 32 - len(required_selected))]
        )

        books: Dict[str, Dict[str, Any]] = {}
        warnings = list(reference_snapshot.get("warnings") or [])
        try:
            if not self._automatic_fee_policy:
                raise KalshiApiError(
                    "Automatic fee policy refresh is disabled for this transport",
                    code="kalshi_fee_policy_unavailable",
                )
            fee_policy = self.series_fee_policy(
                BTC_HOURLY_SERIES,
                base_url=base_url,
            )
        except KalshiApiError:
            fee_policy = {
                "available": False,
                "seriesTicker": BTC_HOURLY_SERIES,
                "makerRateKnown": False,
                "reason": "fee_policy_unavailable",
            }
        if fee_policy.get("available"):
            for market in selected_markets:
                market["fee_type"] = fee_policy.get("feeType")
                market["fee_multiplier"] = fee_policy.get("feeMultiplier")
        else:
            warnings.append("kalshi_fee_policy_unavailable")
        included_required = sorted(
            required.intersection({
                str(market.get("ticker") or "") for market in selected_markets
            })
        )
        missing_required = sorted(required - set(included_required))
        if missing_required:
            warnings.append("hourly_required_held_ticker_unavailable")
        if self._cache_status(hourly_events_key).get("servedStale"):
            warnings.append("hourly_markets_stale")
        tickers = [str(market.get("ticker") or "") for market in selected_markets]
        batch_key = f"kalshi-orderbooks:{base_url}:{event_ticker}:{','.join(tickers)}"
        try:
            batch = self._cached_json(
                batch_key,
                f"{base_url}/markets/orderbooks",
                params={"tickers": tickers},
                ttl=1.25,
                timeout=6.0,
                max_stale=8.0,
            )
            for row in (batch or {}).get("orderbooks") or []:
                ticker = str((row or {}).get("ticker") or "")
                fixed = (row or {}).get("orderbook_fp") or {}
                if ticker:
                    books[ticker] = {
                        "yes": fixed.get("yes_dollars") or [],
                        "no": fixed.get("no_dollars") or [],
                    }
            batch_status = self._cache_status(batch_key)
            if batch_status.get("servedStale"):
                warnings.append("hourly_orderbooks_stale")
        except KalshiApiError:
            warnings.append("hourly_orderbooks_unavailable")
        for market in selected_markets:
            ticker = str(market.get("ticker") or "")
            book = books.get(ticker) or {}
            if not book.get("yes") or not book.get("no"):
                fallback = self._top_book_from_market(market)
                if fallback["yes"] and fallback["no"]:
                    books[ticker] = fallback
                    warnings.append("hourly_top_quote_fallback")
        ladder_fit = _monotone_ladder_probabilities(selected_markets, books)
        as_of = now.isoformat().replace("+00:00", "Z")
        orderbook_as_of = self._cache_status(batch_key).get("fetchedAt") or as_of
        return {
            "asOf": as_of,
            "latencyMs": int(round((time.perf_counter() - started_at) * 1000)),
            "selection": "active",
            "seriesTicker": BTC_HOURLY_SERIES,
            "eventTicker": event_ticker,
            "secondsToClose": nearest_seconds,
            "requiredTickers": sorted(required),
            "includedRequiredTickers": included_required,
            "missingRequiredTickers": missing_required,
            "markets": selected_markets,
            "orderbooks": books,
            "orderbookAsOf": orderbook_as_of,
            "ladderFit": ladder_fit,
            "reference": dict(reference_snapshot.get("reference") or {}),
            "referencePolicy": reference_policy,
            "feePolicy": fee_policy,
            "warnings": sorted(set(warnings)),
            "sources": {
                **dict(reference_snapshot.get("sources") or {}),
                "contract": f"Kalshi {BTC_HOURLY_SERIES} hourly strike ladder",
            },
        }


class _PaperRobotController:
    def __init__(
        self,
        client,
        state,
        paper_accounts,
        *,
        connection_loader: Optional[Callable[[str], Mapping[str, Any]]] = None,
        authoritative_connection_loader: Optional[
            Callable[[str], Mapping[str, Any]]
        ] = None,
        signed_request: Optional[Callable[..., Dict[str, Any]]] = None,
        notifier: Optional[Callable[[str, str, Mapping[str, Any]], Any]] = None,
        observation_saver: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
        portfolio_display_loader: Optional[Callable[[str], Mapping[str, Any]]] = None,
        portfolio_display_saver: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
        scheduler_lease_acquirer: Optional[Callable[[], bool]] = None,
        worker_lease_store=None,
        reference_stream: Optional[KalshiReferenceStream] = None,
        safe_print=print,
        start_background=False,
    ):
        self.client = client
        self.state = state
        self.paper_accounts = paper_accounts
        self.connection_loader = connection_loader
        self.authoritative_connection_loader = (
            authoritative_connection_loader
        )
        self.signed_request = signed_request
        self.notifier = notifier
        self.observation_saver = observation_saver
        self.portfolio_display_loader = portfolio_display_loader
        self.portfolio_display_saver = portfolio_display_saver
        self.scheduler_lease_acquirer = scheduler_lease_acquirer
        self.worker_lease_store = worker_lease_store
        self.reference_stream = reference_stream
        self.safe_print = safe_print
        self._stop_event = threading.Event()
        self._tick_locks: Dict[str, threading.RLock] = {}
        self._tick_locks_guard = threading.RLock()
        self._historical_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._historical_cache_lock = threading.RLock()
        self._last_hourly_tick: Dict[str, float] = {}
        # A first qualifying hourly frame receives exactly one prioritized
        # follow-up on the next five-second scheduler cycle.  This keeps the
        # existing two-frame/25-second policy executable without turning a
        # wider, historically weaker confirmation window into live policy.
        self._hourly_confirmation_followups: Dict[str, str] = {}
        self._btc15_confirmation_deferrals: Dict[str, str] = {}
        self._loop_error_counts: Dict[str, int] = {}
        self._loop_alerted: set[str] = set()
        self._market_standby: Dict[str, Dict[str, str]] = {}
        self._portfolio_display_lock = threading.RLock()
        self._local_portfolio_display: Dict[str, Dict[str, Any]] = {}
        self._lifecycle_lock = threading.RLock()
        self._runtime_lock = threading.RLock()
        self._thread = None
        self._loop_started_at = datetime.now(timezone.utc).isoformat()
        self._loop_last_heartbeat_monotonic = time.monotonic()
        self._loop_last_heartbeat_at = self._loop_started_at
        self._loop_last_error = ""
        self._scheduler_lease_owned: Optional[bool] = None
        self._scheduler_lease_checked_at = ""
        self._enabled_user_count: Optional[int] = None
        self._routing_owner_prefix = "%s:%s" % (
            os.environ.get("RENDER_INSTANCE_ID")
            or os.environ.get("HOSTNAME")
            or "local",
            uuid.uuid4().hex,
        )
        scheduler_disabled = str(
            os.environ.get("ALPHALAB_DISABLE_KALSHI_SCHEDULER") or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        self._background_requested = False
        self._scheduler_disabled = scheduler_disabled
        self.persist_derived_state = not scheduler_disabled
        if start_background:
            self.start()

    def start(self) -> Dict[str, Any]:
        """Start the background scheduler once and make later restarts safe."""
        with self._lifecycle_lock:
            self._background_requested = True
            if self._scheduler_disabled:
                if self.reference_stream is not None:
                    self.reference_stream.set_enabled(False)
                self.safe_print(
                    "[KalshiRobot] background scheduler disabled by environment"
                )
                return self.runtime_snapshot()
            if self._thread and self._thread.is_alive():
                return self.runtime_snapshot()

            if self.reference_stream is not None:
                self.reference_stream.set_enabled(True)
            self._stop_event = threading.Event()
            stop_event = self._stop_event
            started_at = datetime.now(timezone.utc).isoformat()
            with self._runtime_lock:
                self._loop_started_at = started_at
                self._loop_last_heartbeat_monotonic = time.monotonic()
                self._loop_last_heartbeat_at = started_at
                self._loop_last_error = ""
                self._scheduler_lease_owned = None
                self._scheduler_lease_checked_at = ""
                self._enabled_user_count = None
            self._thread = threading.Thread(
                target=self._loop,
                args=(stop_event,),
                name="kalshi-robot",
                daemon=True,
            )
            self._thread.start()
            return self.runtime_snapshot()

    def stop(self) -> Dict[str, Any]:
        """Stop the active scheduler idempotently without poisoning a restart."""
        with self._lifecycle_lock:
            self._background_requested = False
            stop_event = self._stop_event
            thread = self._thread
            stop_event.set()
            if self.reference_stream is not None:
                self.reference_stream.set_enabled(False)
            if (
                thread
                and thread.is_alive()
                and thread is not threading.current_thread()
            ):
                thread.join(timeout=5.0)
            if thread is self._thread and (
                thread is None or not thread.is_alive()
            ):
                self._thread = None
            return self.runtime_snapshot()

    def _load_portfolio_display(self, user_id: str, *, strict: bool = False) -> Dict[str, Any]:
        if callable(self.portfolio_display_loader):
            try:
                payload = self.portfolio_display_loader(user_id)
                return dict(payload or {}) if isinstance(payload, Mapping) else {}
            except Exception as exc:
                if strict:
                    raise
                self.safe_print(
                    f"[KalshiPortfolio] display baseline read failed "
                    f"user={str(user_id)[:8]} error={type(exc).__name__}"
                )
                return {}
        return copy.deepcopy(self._local_portfolio_display.get(str(user_id)) or {})

    def _apply_portfolio_display(
        self,
        user_id: str,
        portfolio: Mapping[str, Any],
        environment: str,
        *,
        display_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = copy.deepcopy(dict(portfolio or {}))
        payload = dict(display_payload or self._load_portfolio_display(user_id) or {})
        modes = payload.get("modes") if isinstance(payload.get("modes"), Mapping) else {}
        baseline = modes.get(environment) if isinstance(modes, Mapping) else None
        if environment == "real" and not _valid_real_display_baseline(baseline):
            structural_reset_at = (
                str(baseline.get("resetAt"))
                if isinstance(baseline, Mapping)
                and _portfolio_timestamp(baseline.get("resetAt")) is not None
                and str(baseline.get("environment") or "").lower() == "real"
                and baseline.get("alphaLabOnly") is True
                else None
            )
            baseline = None
            try:
                state_snapshot = self.state.get(user_id, environment="real")
                mode_state = state_snapshot.get("modeState")
                real_bucket = (
                    mode_state.get("real")
                    if isinstance(mode_state, Mapping)
                    and isinstance(mode_state.get("real"), Mapping)
                    else {}
                )
                state_baseline = real_bucket.get("displayBaseline")
                if (
                    isinstance(state_baseline, Mapping)
                    and _portfolio_timestamp(
                        state_baseline.get("resetAt")
                    ) is not None
                    and str(
                        state_baseline.get("environment") or ""
                    ).lower() == "real"
                    and state_baseline.get("alphaLabOnly") is True
                ):
                    structural_reset_at = str(
                        state_baseline.get("resetAt")
                    )
                if _valid_real_display_baseline(state_baseline):
                    baseline = dict(state_baseline)
                elif callable(
                    getattr(self.state, "ensure_real_display_baseline", None)
                ):
                    repaired = self.state.ensure_real_display_baseline(user_id)
                    if (
                        isinstance(repaired, Mapping)
                        and _portfolio_timestamp(
                            repaired.get("resetAt")
                        ) is not None
                        and str(
                            repaired.get("environment") or ""
                        ).lower() == "real"
                        and repaired.get("alphaLabOnly") is True
                    ):
                        structural_reset_at = str(repaired.get("resetAt"))
                    if _valid_real_display_baseline(repaired):
                        baseline = dict(repaired)
            except Exception as exc:
                self.safe_print(
                    "[KalshiPortfolio] Real baseline state repair failed "
                    f"user={str(user_id)[:8]} error={type(exc).__name__}"
                )
            if not _valid_real_display_baseline(baseline):
                balance = dict(result.get("balance") or {})
                reset_at = (
                    structural_reset_at
                    or datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                baseline = {
                    "resetAt": reset_at,
                    "baselineEquityCents": int(round(
                        _account_equity_cents(balance, "real")
                    )),
                    "baselineCashCents": int(round(
                        _finite_number(balance.get("balance"), 0.0)
                    )),
                    "environment": "real",
                    "ledgerPreserved": True,
                    "alphaLabOnly": True,
                    "reason": "fail_closed_missing_baseline_repair",
                }
                materialize = getattr(
                    self.state,
                    "materialize_real_display_baseline",
                    None,
                )
                if callable(materialize):
                    try:
                        persisted_baseline = materialize(user_id, baseline)
                        if _valid_real_display_baseline(persisted_baseline):
                            baseline = dict(persisted_baseline)
                    except Exception as exc:
                        self.safe_print(
                            "[KalshiPortfolio] Real baseline state "
                            "materialization failed "
                            f"user={str(user_id)[:8]} "
                            f"error={type(exc).__name__}"
                        )
            # Repair the canonical display artifact as well as the state
            # fallback. Subsequent reads therefore cannot repeatedly accept
            # ``{}`` or a partially populated Real baseline.
            try:
                with self._portfolio_display_lock:
                    repaired_modes = (
                        dict(payload.get("modes") or {})
                        if isinstance(payload.get("modes"), Mapping)
                        else {}
                    )
                    repaired_modes["real"] = dict(baseline)
                    repaired_payload = {
                        **payload,
                        "schemaVersion": 1,
                        "modes": repaired_modes,
                        "updatedAt": baseline["resetAt"],
                    }
                    if callable(self.portfolio_display_saver):
                        self.portfolio_display_saver(
                            user_id,
                            repaired_payload,
                        )
                    else:
                        self._local_portfolio_display[str(user_id)] = (
                            copy.deepcopy(repaired_payload)
                        )
                    payload = repaired_payload
            except Exception as exc:
                # The in-memory baseline still keeps the response fail-closed;
                # report the durability issue without exposing old activity.
                self.safe_print(
                    "[KalshiPortfolio] Real baseline artifact repair failed "
                    f"user={str(user_id)[:8]} error={type(exc).__name__}"
                )
        analytics = dict(result.get("analytics") or {})
        if (
            isinstance(baseline, Mapping)
            and (
                environment != "real"
                or _valid_real_display_baseline(baseline)
            )
        ):
            analytics = _portfolio_analytics_after_reset(analytics, baseline)
        else:
            analytics["displayBaseline"] = {"active": False}
        if environment == "real":
            if _valid_real_display_baseline(baseline):
                lifetime_counts = {
                    collection: len(result.get(collection) or [])
                    for collection in ("orders", "fills", "settlements")
                }
                for collection in ("orders", "fills", "settlements"):
                    result[collection] = _visible_real_activity(
                        result.get(collection) or [],
                        baseline,
                    )
                result["accountActivity"] = {
                    "scope": "alphalab_post_baseline",
                    "lifetimeCounts": lifetime_counts,
                    "visibleCounts": {
                        collection: len(result.get(collection) or [])
                        for collection in ("orders", "fills", "settlements")
                    },
                }
            else:
                for collection in ("orders", "fills", "settlements"):
                    result[collection] = []
                warnings = list(result.get("warnings") or [])
                warnings.append("kalshi_real_display_baseline_missing")
                result["warnings"] = sorted(set(warnings))
        result["analytics"] = analytics
        return result

    def reset_portfolio_display(self, user_id: str, *, mode: str = "paper") -> Dict[str, Any]:
        """Start a new visible Portfolio period without mutating its ledger."""
        environment = _execution_mode(mode)
        portfolio = self.portfolio(user_id, mode=environment, include_display=False, mutate=False)
        balance = dict(portfolio.get("balance") or {})
        baseline = {
            "resetAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "baselineEquityCents": int(round(_account_equity_cents(balance, environment))),
            "baselineCashCents": int(round(_finite_number(balance.get("balance"), 0.0))),
            "environment": environment,
            "ledgerPreserved": True,
            "alphaLabOnly": environment == "real",
        }
        with self._portfolio_display_lock:
            payload = self._load_portfolio_display(user_id, strict=True)
            modes = dict(payload.get("modes") or {}) if isinstance(payload.get("modes"), Mapping) else {}
            modes[environment] = baseline
            updated = {
                **payload,
                "schemaVersion": 1,
                "modes": modes,
                "updatedAt": baseline["resetAt"],
            }
            if callable(self.portfolio_display_saver):
                self.portfolio_display_saver(user_id, updated)
            else:
                self._local_portfolio_display[str(user_id)] = copy.deepcopy(updated)
        return self._apply_portfolio_display(
            user_id,
            portfolio,
            environment,
            display_payload=updated,
        )

    def _real_config(
        self,
        user_id: str,
        *,
        authoritative: bool = False,
    ) -> Mapping[str, Any]:
        loader = (
            self.authoritative_connection_loader
            if authoritative
            else self.connection_loader
        )
        if not callable(loader):
            raise KalshiApiError(
                (
                    "Authoritative Kalshi credential storage is unavailable"
                    if authoritative
                    else "Kalshi credential storage is unavailable"
                ),
                status=503,
                code=(
                    "kalshi_authoritative_credentials_unavailable"
                    if authoritative
                    else "credential_store_unavailable"
                ),
            )
        config = dict(loader(user_id) or {})
        key_field, private_field = _credential_fields("production")
        if not str(config.get(key_field) or "").strip() or not str(config.get(private_field) or "").strip():
            raise KalshiApiError(
                "Kalshi Real mode requires a configured production API key in Settings.",
                status=409,
                code="kalshi_real_credentials_missing",
            )
        if not callable(self.signed_request):
            raise KalshiApiError("Kalshi signed order transport is unavailable", status=503, code="kalshi_signed_transport_unavailable")
        return config

    def _signed(self, config: Mapping[str, Any], method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        if not callable(self.signed_request):
            raise KalshiApiError("Kalshi signed order transport is unavailable", status=503, code="kalshi_signed_transport_unavailable")
        return self.signed_request(config, "production", method, endpoint, **kwargs)

    def _optional_signed(self, config: Mapping[str, Any], endpoint: str, *, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        try:
            payload = self._signed(config, "GET", endpoint, params=dict(params or {}))
            return payload if isinstance(payload, Mapping) else {}
        except Exception as exc:
            self.safe_print(f"[KalshiReal] optional signed fetch failed endpoint={endpoint} error={type(exc).__name__}")
            return {
                "_alphalabIncomplete": True,
                "_alphalabWarning": "kalshi_account_history_incomplete",
            }

    def _historical_account_rows(self, user_id: str, config: Mapping[str, Any]) -> Dict[str, Any]:
        """Load paginated exchange history with a bounded 15-minute cache."""
        key_field, _private_field = _credential_fields("production")
        credential_fingerprint = hashlib.sha256(
            str(config.get(key_field) or "").encode("utf-8")
        ).hexdigest()[:16]
        cache_key = f"{user_id}:{credential_fingerprint}:subaccount-0"
        now = time.monotonic()
        with self._historical_cache_lock:
            cached = self._historical_cache.get(cache_key)
            if cached and now - cached[0] < 900:
                return copy.deepcopy(cached[1])

        def collect(endpoint: str, collection: str) -> Dict[str, Any]:
            rows = []
            cursor = None
            complete = True
            warnings = []
            for _ in range(5):
                params: Dict[str, Any] = {"limit": 1000, "subaccount": 0}
                if cursor:
                    params["cursor"] = cursor
                payload = self._optional_signed(config, endpoint, params=params)
                if payload.get("_alphalabIncomplete"):
                    complete = False
                    warnings.append(
                        str(payload.get("_alphalabWarning") or "kalshi_account_history_incomplete")
                    )
                    break
                page = payload.get(collection) or []
                rows.extend(dict(row) for row in page if isinstance(row, Mapping))
                cursor = payload.get("cursor") or payload.get("next_cursor")
                if not cursor or not page:
                    break
            if cursor:
                complete = False
                warnings.append("kalshi_account_history_incomplete")
            return {
                "rows": rows,
                "complete": complete,
                "warnings": sorted(set(warnings)),
            }

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="kalshi-history") as pool:
            orders_future = pool.submit(collect, "/historical/orders", "orders")
            fills_future = pool.submit(collect, "/historical/fills", "fills")
            orders_result = orders_future.result()
            fills_result = fills_future.result()
            result = {
                "orders": orders_result["rows"],
                "fills": fills_result["rows"],
                "complete": bool(orders_result["complete"] and fills_result["complete"]),
                "warnings": sorted(set(
                    list(orders_result["warnings"]) + list(fills_result["warnings"])
                )),
            }
        with self._historical_cache_lock:
            self._historical_cache[cache_key] = (now, copy.deepcopy(result))
        return result

    def _live_account_collection(
        self,
        config: Mapping[str, Any],
        endpoint: str,
        collection_keys,
        *,
        optional: bool = False,
        max_pages: int = 10,
    ) -> Dict[str, Any]:
        """Read a complete cursor-paginated live account collection."""
        keys = tuple(str(key) for key in collection_keys if str(key))
        if not keys:
            raise ValueError("collection_keys are required")
        rows = []
        cursor = None
        seen_cursors = set()
        warnings = []
        complete = True
        page_count = 0
        last_payload: Dict[str, Any] = {}

        for _ in range(max(1, int(max_pages or 1))):
            params: Dict[str, Any] = {"limit": 1000, "subaccount": 0}
            if cursor:
                params["cursor"] = cursor
            payload = (
                self._optional_signed(config, endpoint, params=params)
                if optional
                else self._signed(config, "GET", endpoint, params=params)
            )
            last_payload = dict(payload or {})
            page_count += 1
            if last_payload.get("_alphalabIncomplete"):
                complete = False
                warnings.append(
                    str(
                        last_payload.get("_alphalabWarning")
                        or "kalshi_account_history_incomplete"
                    )
                )
                break

            page = []
            for key in keys:
                candidate = last_payload.get(key)
                if isinstance(candidate, list):
                    page = candidate
                    break
            rows.extend(dict(row) for row in page if isinstance(row, Mapping))

            next_cursor = (
                last_payload.get("cursor")
                or last_payload.get("next_cursor")
            )
            if not next_cursor:
                cursor = None
                break
            next_cursor = str(next_cursor)
            if next_cursor in seen_cursors:
                complete = False
                warnings.append("kalshi_account_pagination_stalled")
                cursor = next_cursor
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            if cursor:
                complete = False
                warnings.append("kalshi_account_pagination_limit")

        result = dict(last_payload)
        result[keys[0]] = rows
        result.pop("cursor", None)
        result.pop("next_cursor", None)
        result["_alphalabComplete"] = bool(complete and not cursor)
        result["_alphalabWarnings"] = sorted(set(warnings))
        result["_alphalabPageCount"] = page_count
        return result

    def _live_portfolio(self, user_id: str, *, mutate: bool = True) -> Dict[str, Any]:
        config = self._real_config(user_id)
        before_state = self.state.get(user_id, environment="real")
        managed_contexts: Dict[str, Dict[str, Any]] = {}
        managed_tickers = set()
        for evidence in (
            list(before_state.get("filledTrades") or [])
            + list(before_state.get("decisions") or [])
        ):
            if not isinstance(evidence, Mapping):
                continue
            action_value = str(evidence.get("action") or "").upper()
            action = (
                "SELL" if action_value.startswith("SELL")
                else "BUY" if action_value.startswith("BUY")
                else ""
            )
            context = {
                "side": str(evidence.get("side") or "").upper(),
                "action": action,
                "reduce_only": action == "SELL",
                "alphaLabManaged": True,
            }
            for identifier in (
                evidence.get("orderId"),
                evidence.get("clientOrderId"),
                evidence.get("order_id"),
                evidence.get("client_order_id"),
            ):
                if identifier:
                    managed_contexts[str(identifier)] = context
            ticker = str(evidence.get("ticker") or "")
            if ticker and (
                evidence.get("orderFilled")
                or evidence.get("fillCount")
                or evidence in list(before_state.get("filledTrades") or [])
            ):
                managed_tickers.add(ticker)
        # These endpoints are independent. Reading them concurrently cuts the
        # pre-decision account snapshot latency without increasing request count
        # or weakening any execution/risk gate.
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="kalshi-account") as pool:
            balance_future = pool.submit(
                self._signed, config, "GET", "/portfolio/balance", params={"subaccount": 0}
            )
            positions_future = pool.submit(
                self._live_account_collection,
                config,
                "/portfolio/positions",
                ("market_positions", "positions", "event_positions"),
            )
            orders_future = pool.submit(
                self._live_account_collection,
                config,
                "/portfolio/orders",
                ("orders",),
            )
            fills_future = pool.submit(
                self._live_account_collection,
                config,
                "/portfolio/fills",
                ("fills",),
                optional=True,
            )
            settlements_future = pool.submit(
                self._live_account_collection,
                config,
                "/portfolio/settlements",
                ("settlements", "settlement_history", "market_settlements"),
                optional=True,
            )
            balance_payload = balance_future.result()
            positions_payload = positions_future.result()
            orders_payload = orders_future.result()
            fills_payload = fills_future.result()
            settlements_payload = settlements_future.result()
        historical = self._historical_account_rows(user_id, config)
        warnings = list(historical.get("warnings") or [])
        completeness = {
            "balance": True,
            "positions": bool(positions_payload.get("_alphalabComplete")),
            "orders": bool(orders_payload.get("_alphalabComplete")),
            "fills": bool(fills_payload.get("_alphalabComplete")),
            "settlements": bool(settlements_payload.get("_alphalabComplete")),
            "history": bool(historical.get("complete", True)),
        }
        for payload in (
            positions_payload,
            orders_payload,
            fills_payload,
            settlements_payload,
        ):
            warnings.extend(payload.get("_alphalabWarnings") or [])
        if not completeness["positions"]:
            warnings.append("kalshi_account_positions_incomplete")
        if not completeness["orders"]:
            warnings.append("kalshi_account_orders_incomplete")
        if not completeness["fills"] or not completeness["settlements"] or not completeness["history"]:
            warnings.append("kalshi_account_history_incomplete")
        completeness["complete"] = all(completeness.values())

        raw_positions = list(
            positions_payload.get("market_positions")
            or positions_payload.get("positions")
            or positions_payload.get("event_positions")
            or []
        )
        position_markets: Dict[str, Dict[str, Any]] = {}
        position_tickers = sorted({
            str(
                row.get("ticker")
                or row.get("market_ticker")
                or row.get("market")
                or ""
            )
            for row in raw_positions
            if isinstance(row, Mapping)
            and _is_supported_kalshi_ticker(
                row.get("ticker")
                or row.get("market_ticker")
                or row.get("market")
            )
        })
        market_loader = getattr(self.client, "market", None)
        if position_tickers and callable(market_loader):
            with ThreadPoolExecutor(
                max_workers=min(8, len(position_tickers)),
                thread_name_prefix="kalshi-position-marks",
            ) as pool:
                market_futures = {
                    ticker: pool.submit(market_loader, ticker)
                    for ticker in position_tickers
                }
                for ticker, future in market_futures.items():
                    try:
                        market = future.result()
                        if isinstance(market, Mapping) and market:
                            position_markets[ticker] = dict(market)
                        else:
                            warnings.append("kalshi_position_mark_unavailable")
                    except Exception as exc:
                        warnings.append("kalshi_position_mark_unavailable")
                        self.safe_print(
                            "[KalshiPortfolio] position mark unavailable "
                            f"ticker={ticker} error={type(exc).__name__}"
                        )
        positions = []
        for row in raw_positions:
            if not isinstance(row, Mapping):
                continue
            ticker = str(row.get("ticker") or row.get("market_ticker") or row.get("market") or "")
            if not _is_supported_kalshi_ticker(ticker):
                continue
            yes_count = _finite_number(
                _first_present(
                    row, "yes_count_fp", "yes_count", "yes_position"
                ),
                0.0,
            )
            no_count = _finite_number(
                _first_present(
                    row, "no_count_fp", "no_count", "no_position"
                ),
                0.0,
            )
            position = _finite_number(
                _first_present(row, "position_fp", "position"),
                yes_count - no_count,
            )
            if yes_count == 0 and no_count == 0 and position:
                if position > 0:
                    yes_count = abs(position)
                else:
                    no_count = abs(position)
            net_side, net_count = _live_position_direction(position, yes_count, no_count)
            if not net_side or net_count <= 0:
                continue
            market_mark = _position_market_mark(
                position_markets.get(ticker) or {},
                net_side,
            )
            exposure_dollars = _dollar_amount(
                row.get("market_exposure_dollars") or row.get("cost_dollars"),
                row.get("market_exposure") or row.get("cost") or row.get("realized_cost"),
            )
            value_dollars = _optional_dollar_amount(
                _first_present(
                    row,
                    "market_value_dollars",
                    "value_dollars",
                    "settlement_value_dollars",
                ),
                _first_present(row, "market_value", "value", "settlement_value"),
            )
            if (
                value_dollars is None
                and market_mark.get("mark") is not None
            ):
                value_dollars = (
                    _finite_number(market_mark.get("mark"), 0.0)
                    * net_count
                )
            fee_dollars = _dollar_amount(
                row.get("fees_paid_dollars") or row.get("fee_cost_dollars"),
                row.get("fees_paid") or row.get("fee_cost") or row.get("fees"),
            )
            yes_market_mark = _position_market_mark(
                position_markets.get(ticker) or {},
                "YES",
            )
            no_market_mark = _position_market_mark(
                position_markets.get(ticker) or {},
                "NO",
            )
            positions.append({
                **dict(row),
                "environment": "real",
                "ticker": ticker,
                "position_fp": position,
                "yes_count_fp": yes_count,
                "no_count_fp": no_count,
                "net_count_fp": net_count,
                "net_side": net_side,
                "market_exposure_dollars": exposure_dollars,
                "market_value_dollars": value_dollars,
                "fee_cost_dollars": fee_dollars,
                "unrealized_pnl_dollars": (
                    value_dollars - exposure_dollars - fee_dollars
                    if value_dollars is not None
                    else None
                ),
                "yes_mark_dollars": _optional_dollar_amount(
                    _first_present(row, "yes_mark_dollars"),
                    _first_present(row, "yes_mark", "yes_price"),
                ) if _first_present(
                    row,
                    "yes_mark_dollars",
                    "yes_mark",
                    "yes_price",
                ) is not None else yes_market_mark.get("mark"),
                "no_mark_dollars": _optional_dollar_amount(
                    _first_present(row, "no_mark_dollars"),
                    _first_present(row, "no_mark", "no_price"),
                ) if _first_present(
                    row,
                    "no_mark_dollars",
                    "no_mark",
                    "no_price",
                ) is not None else no_market_mark.get("mark"),
                "markAvailable": value_dollars is not None,
                "markSource": market_mark.get("source"),
                "markBidDollars": market_mark.get("bid"),
                "markAskDollars": market_mark.get("ask"),
                "markAsOf": market_mark.get("asOf"),
                "last_trade_at": row.get("last_trade_at") or row.get("updated_time") or row.get("created_time"),
            })

        raw_orders = list(orders_payload.get("orders") or orders_payload.get("order_history") or [])
        raw_orders.extend(historical.get("orders") or [])
        orders = []
        orders_by_id = {}
        order_fill_fallback = []
        seen_order_ids = set()
        for row in raw_orders:
            if not isinstance(row, Mapping):
                continue
            evidence = None
            for identifier in (row.get("order_id"), row.get("id"), row.get("client_order_id")):
                if identifier and str(identifier) in managed_contexts:
                    evidence = managed_contexts[str(identifier)]
                    break
            normalized = _normalise_live_order(row, row, evidence or {})
            if not _is_supported_kalshi_ticker(normalized.get("ticker") or normalized.get("market_ticker")):
                continue
            managed = evidence is not None
            normalized.update({
                "alphaLabManaged": managed,
                "alphalabManaged": managed,
                "alphaLabOrder": managed,
                "source": "alphalab" if managed else "kalshi_account",
            })
            order_key = str(normalized.get("order_id") or normalized.get("client_order_id") or "")
            if order_key and order_key in seen_order_ids:
                continue
            if order_key:
                seen_order_ids.add(order_key)
            orders.append(normalized)
            for identifier in (normalized.get("order_id"), normalized.get("client_order_id")):
                if identifier:
                    orders_by_id[str(identifier)] = normalized
            if _order_fill_count(normalized) > 0:
                fill_id = str(normalized.get("order_id") or normalized.get("client_order_id") or "")
                order_fill_fallback.append({**normalized, "fill_id": fill_id})

        raw_fills = list(
            fills_payload.get("fills")
            or fills_payload.get("fill_history")
            or fills_payload.get("trades")
            or []
        )
        raw_fills.extend(historical.get("fills") or [])
        fills = []
        seen_fill_ids = set()
        for row in raw_fills:
            if not isinstance(row, Mapping):
                continue
            order_context = orders_by_id.get(str(row.get("order_id") or ""))
            normalized = _normalise_live_fill(row, order_context)
            if not _is_supported_kalshi_ticker(normalized.get("ticker") or normalized.get("market_ticker")):
                continue
            managed = bool((order_context or {}).get("alphaLabManaged"))
            if not managed:
                for identifier in (row.get("order_id"), row.get("client_order_id")):
                    if identifier and str(identifier) in managed_contexts:
                        managed = True
                        break
            normalized.update({
                "alphaLabManaged": managed,
                "alphalabManaged": managed,
                "alphaLabOrder": managed,
                "source": "alphalab" if managed else "kalshi_account",
            })
            fill_id = str(normalized.get("fill_id") or normalized.get("order_id") or uuid.uuid4())
            if fill_id in seen_fill_ids:
                continue
            seen_fill_ids.add(fill_id)
            fills.append(normalized)
        # Prefer canonical fill rows. Order summaries are only a degraded
        # fallback when the optional fills endpoint is unavailable/empty; using
        # both would count one execution twice under different identifiers.
        if not fills:
            fills = order_fill_fallback
        fills = _reconcile_live_exit_fills(fills)
        if mutate and callable(getattr(self.state, "reconcile_live_fills", None)):
            before_state = self.state.reconcile_live_fills(
                user_id,
                [row for row in fills if row.get("alphaLabManaged")],
                environment="real",
                persist=self.persist_derived_state,
            )
        managed_inventory = _open_live_fill_inventory(
            [row for row in fills if row.get("alphaLabManaged")]
        )
        # Historical manual activity is not an ownership conflict by itself.
        # Only manual lots that remain open after their own FIFO round trips
        # may contaminate a currently held ticker. Previously, one old manual
        # fill permanently marked the ticker unmanaged even after it was sold
        # back to zero.
        unmanaged_inventory = _open_live_fill_inventory(
            [row for row in fills if not row.get("alphaLabManaged")]
        )
        unmanaged_open_tickers = {
            str(ticker)
            for (ticker, _side), inventory in unmanaged_inventory.items()
            if _finite_number(inventory.get("count"), 0.0) > 1e-9
        }
        for position_row in positions:
            ticker = str(position_row.get("ticker") or "")
            side = str(position_row.get("net_side") or "").upper()
            account_count = max(
                0.0,
                _finite_number(position_row.get("net_count_fp"), 0.0),
            )
            inventory = managed_inventory.get((ticker, side))
            managed_count = min(
                account_count,
                max(0.0, _finite_number((inventory or {}).get("count"), 0.0)),
            )
            unmanaged_count = max(0.0, account_count - managed_count)
            opposite_inventory = managed_inventory.get(
                (ticker, _opposite_outcome(side))
            )
            ownership_conflict = bool(
                ticker in unmanaged_open_tickers
                or (
                    opposite_inventory
                    and _finite_number(opposite_inventory.get("count"), 0.0) > 0
                )
            )
            if ownership_conflict:
                managed_count = 0.0
                unmanaged_count = account_count
            managed = managed_count > 1e-9 and not ownership_conflict
            position_row.update({
                "alphaLabManaged": managed,
                "alphalabManaged": managed,
                "alphaLabManagedSide": side if managed else None,
                "alphaLabManagedCount": managed_count,
                "alphaLabUnmanagedCount": unmanaged_count,
                "alphaLabOwnershipConflict": ownership_conflict,
                "source": (
                    "alphalab"
                    if managed and unmanaged_count <= 1e-9
                    else "mixed"
                    if managed
                    else "kalshi_account"
                ),
            })
            if not managed or not inventory:
                continue
            inventory_count = max(
                _finite_number(inventory.get("count"), 0.0),
                1e-9,
            )
            managed_fraction = managed_count / inventory_count
            managed_principal = _finite_number(
                inventory.get("principal"), 0.0
            ) * managed_fraction
            managed_entry_fee = _finite_number(
                inventory.get("entryFee"), 0.0
            ) * managed_fraction
            prefix = side.lower()
            position_row[f"{prefix}_average_price_dollars"] = inventory["averagePrice"]
            position_row[f"{prefix}_cost"] = managed_principal
            position_row[f"{prefix}_fee_cost_dollars"] = managed_entry_fee
            position_row["position_cost_dollars"] = managed_principal
            position_row["fee_cost_dollars"] = managed_entry_fee
            position_row["last_trade_at"] = inventory.get("lastTradeAt") or position_row.get("last_trade_at")
            # Cost-based unrealized P/L is intentionally marked only when the
            # position endpoint supplies a usable current value.
            if (
                position_row.get("market_value_dollars") is not None
                and unmanaged_count <= 1e-9
            ):
                position_row["unrealized_pnl_dollars"] = (
                    _finite_number(position_row.get("market_value_dollars"))
                    - managed_principal
                    - managed_entry_fee
                )
            elif unmanaged_count > 1e-9:
                position_row["unrealized_pnl_dollars"] = None
        if any(
            _finite_number(row.get("alphaLabUnmanagedCount"), 0.0) > 0
            for row in positions
        ):
            warnings.append("kalshi_unmanaged_positions_present")

        raw_settlements = list(
            settlements_payload.get("settlements")
            or settlements_payload.get("settlement_history")
            or settlements_payload.get("market_settlements")
            or []
        )
        settlements = []
        for row in raw_settlements:
            if not isinstance(row, Mapping):
                continue
            normalized = _normalise_live_settlement(row)
            if _is_supported_kalshi_ticker(normalized.get("ticker") or normalized.get("market_ticker")):
                settlement_ticker = str(normalized.get("ticker") or "")
                managed = (
                    settlement_ticker in managed_tickers
                    and settlement_ticker not in unmanaged_open_tickers
                )
                normalized.update({
                    "alphaLabManaged": managed,
                    "alphalabManaged": managed,
                    "alphaLabOrder": managed,
                    "source": "alphalab" if managed else "kalshi_account",
                })
                settlements.append(normalized)

        before_records = {
            str(row.get("key") or "")
            for row in ((before_state.get("strategy") or {}).get("settlementRecords") or [])
            if row.get("key")
        }
        if mutate:
            managed_fills = [row for row in fills if row.get("alphaLabManaged")]
            managed_settlements = [
                row for row in settlements if row.get("alphaLabManaged")
            ]
            state = self.state.reconcile_settlements(
                user_id,
                managed_settlements,
                managed_fills,
                environment="real",
                persist=self.persist_derived_state,
            )
            if self.persist_derived_state:
                for record in ((state.get("strategy") or {}).get("settlementRecords") or []):
                    if str(record.get("key") or "") not in before_records:
                        self._notify_settlement(user_id, record)
        else:
            state = before_state
        analytics = _portfolio_analytics(state.get("strategy") or {})

        return {
            "environment": "real",
            "accountProvider": "Kalshi",
            "asOf": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "balance": {
                "balance": _cents_amount(balance_payload.get("balance")),
                "portfolio_value": _cents_amount(balance_payload.get("portfolio_value") or balance_payload.get("portfolioValue")),
                "balance_dollars": balance_payload.get("balance_dollars"),
                "balance_breakdown": [
                    {"exchange_index": index, "balance": str(cash)}
                    for index in sorted({
                        _exchange_shard_index(row.get("exchange_index"))
                        for row in balance_payload.get("balance_breakdown") or []
                        if isinstance(row, Mapping)
                        and _exchange_shard_index(row.get("exchange_index")) is not None
                    })
                    if (cash := _shard_cash_dollars(balance_payload, index)) is not None
                ],
            },
            "positions": [_tag_market_family(row) for row in positions],
            "orders": [_tag_market_family(row) for row in orders],
            "fills": [_tag_market_family(row) for row in fills],
            "settlements": [_tag_market_family(row) for row in settlements],
            "analytics": analytics,
            "warnings": sorted(set(warnings)),
            "completeness": completeness,
        }

    def portfolio(
        self,
        user_id: str,
        *,
        mode: str = "paper",
        include_display: bool = False,
        mutate: bool = True,
    ) -> Dict[str, Any]:
        environment = _execution_mode(mode)
        if environment == "real":
            result = self._live_portfolio(user_id, mutate=mutate)
            return self._apply_portfolio_display(user_id, result, environment) if include_display else result
        open_tickers = set(self.paper_accounts.open_tickers(user_id))
        refreshed_markets: Dict[str, Mapping[str, Any]] = {}
        if open_tickers and mutate:
            # A user can hold several rolling contracts at once. Sequential
            # market refreshes used to exceed the frontend's ten-second poll,
            # causing every completed response to be discarded as stale. Fetch
            # the independent marks concurrently, then update the ledger in a
            # deterministic single-threaded pass.
            with ThreadPoolExecutor(
                max_workers=min(8, len(open_tickers)),
                thread_name_prefix="kalshi-paper-marks",
            ) as pool:
                futures = {ticker: pool.submit(self.client.market, ticker) for ticker in open_tickers}
                for ticker, future in futures.items():
                    try:
                        refreshed_markets[ticker] = future.result()
                    except Exception as exc:
                        self.safe_print(
                            f"[KalshiPaper] market refresh failed ticker={ticker} "
                            f"error={type(exc).__name__}"
                        )
        for ticker in (sorted(open_tickers) if mutate else []):
            market = refreshed_markets.get(ticker)
            if not market:
                continue
            result_value = str(market.get("result") or market.get("market_result") or "").upper()
            if result_value in {"YES", "NO"}:
                settled_time = str(market.get("settlement_ts") or market.get("determined_time") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
                settlement = self.paper_accounts.settle(
                    user_id,
                    ticker,
                    result_value,
                    settled_time=settled_time,
                    persist=self.persist_derived_state,
                )
                if settlement:
                    if self.persist_derived_state:
                        self._notify_settlement(user_id, settlement)
            else:
                self.paper_accounts.update_mark(user_id, ticker, market)
        result = self.paper_accounts.portfolio(user_id)
        for collection in ("positions", "orders", "fills", "settlements"):
            result[collection] = [
                row for row in result.get(collection) or []
                if _is_supported_kalshi_ticker((row or {}).get("ticker") or (row or {}).get("market_ticker"))
            ]
        state = (
            self.state.reconcile_settlements(
                user_id,
                result["settlements"],
                result["fills"],
                environment=environment,
                persist=self.persist_derived_state,
            )
            if mutate
            else self.state.get(user_id, environment=environment)
        )
        result["analytics"] = _portfolio_analytics(state.get("strategy") or {})
        for collection in ("positions", "orders", "fills", "settlements"):
            result[collection] = [_tag_market_family(row) for row in result.get(collection) or []]
        return self._apply_portfolio_display(user_id, result, environment) if include_display else result

    @contextmanager
    def _live_routing_lease(self, user_id: str) -> Iterator[Dict[str, Any]]:
        claim = getattr(self.worker_lease_store, "claim_worker_lease_fenced", None)
        renew = getattr(self.worker_lease_store, "renew_worker_lease", None)
        release = getattr(self.worker_lease_store, "release_worker_lease", None)
        if not (callable(claim) and callable(renew) and callable(release)):
            raise KalshiApiError(
                "Fenced Kalshi order-routing coordination is unavailable",
                status=503,
                code="kalshi_routing_fence_unavailable",
            )
        uid_digest = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:32]
        lease_name = "kalshi-routing:%s" % uid_digest
        owner_id = "%s:routing:%s" % (
            self._routing_owner_prefix, uuid.uuid4().hex,
        )
        deadline = time.monotonic() + KALSHI_ROUTING_LEASE_TIMEOUT_SECONDS
        lease = None
        while True:
            try:
                result = claim(
                    lease_name,
                    owner_id,
                    ttl_seconds=KALSHI_ROUTING_LEASE_TTL_SECONDS,
                    metadata={
                        "component": "kalshi_order_routing",
                        "userScope": uid_digest,
                    },
                )
            except Exception as exc:
                raise KalshiApiError(
                    "Durable Kalshi order-routing coordination is unavailable",
                    status=503,
                    code="kalshi_routing_lease_unavailable",
                ) from exc
            if (
                isinstance(result, Mapping)
                and result.get("acquired")
                and result.get("fencingToken")
            ):
                lease = {
                    "lease_name": lease_name,
                    "owner_id": owner_id,
                    "fencing_token": int(result["fencingToken"]),
                    "user_scope": uid_digest,
                }
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise KalshiApiError(
                    "Kalshi order routing is busy; retry shortly",
                    status=423,
                    code="kalshi_routing_lease_timeout",
                )
            time.sleep(min(0.025, remaining))
        try:
            yield lease
        finally:
            try:
                release(
                    lease["lease_name"],
                    lease["owner_id"],
                    lease["fencing_token"],
                )
            except Exception as exc:
                self.safe_print(
                    "[KalshiReal] routing lease release failed error=%s"
                    % type(exc).__name__
                )

    def _renew_live_routing_lease(self, lease: Mapping[str, Any]) -> None:
        renew = getattr(self.worker_lease_store, "renew_worker_lease", None)
        if not callable(renew):
            raise KalshiApiError(
                "Fenced Kalshi order-routing coordination is unavailable",
                status=503,
                code="kalshi_routing_fence_unavailable",
            )
        try:
            renewed = bool(renew(
                lease.get("lease_name"),
                lease.get("owner_id"),
                lease.get("fencing_token"),
                ttl_seconds=KALSHI_ROUTING_LEASE_TTL_SECONDS,
                metadata={
                    "component": "kalshi_order_routing",
                    "userScope": lease.get("user_scope"),
                },
            ))
        except Exception as exc:
            raise KalshiApiError(
                "Durable Kalshi order-routing coordination is unavailable",
                status=503,
                code="kalshi_routing_lease_unavailable",
            ) from exc
        if not renewed:
            raise KalshiApiError(
                "This backend no longer owns the fenced Kalshi routing lease",
                status=423,
                code="kalshi_routing_lease_lost",
            )

    def _collect_live_preflight_rows(
        self,
        config: Mapping[str, Any],
        endpoint: str,
        collection_keys: Tuple[str, ...],
    ) -> list:
        """Read every page required by an irreversible Real account guard."""
        rows = []
        cursor = None
        seen_cursors = set()
        for _page_number in range(50):
            params: Dict[str, Any] = {"limit": 100, "subaccount": 0}
            if cursor:
                params["cursor"] = cursor
            payload = self._signed(
                config,
                "GET",
                endpoint,
                params=params,
            )
            if (
                not isinstance(payload, Mapping)
                or payload.get("_alphalabIncomplete")
                or payload.get("complete") is False
                or payload.get("incomplete") is True
            ):
                raise KalshiApiError(
                    "Kalshi returned an incomplete Real account preflight.",
                    status=503,
                    code="kalshi_live_preflight_incomplete",
                )
            collection = None
            for key in collection_keys:
                if key in payload:
                    collection = payload.get(key)
                    break
            if not isinstance(collection, list):
                raise KalshiApiError(
                    "Kalshi omitted required Real account preflight rows.",
                    status=503,
                    code="kalshi_live_preflight_incomplete",
                )
            rows.extend(
                dict(row) for row in collection if isinstance(row, Mapping)
            )
            next_cursor = str(
                payload.get("cursor")
                or payload.get("next_cursor")
                or ""
            ).strip()
            if not next_cursor:
                return rows
            if next_cursor in seen_cursors:
                raise KalshiApiError(
                    "Kalshi repeated an account cursor during Real preflight.",
                    status=503,
                    code="kalshi_live_preflight_incomplete",
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        raise KalshiApiError(
            "Kalshi account pagination exceeded the bounded Real preflight.",
            status=503,
            code="kalshi_live_preflight_incomplete",
        )

    def _fresh_live_account_preflight(
        self,
        config: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Fetch uncached cash, positions, and every current account order."""
        balance = self._signed(
            config,
            "GET",
            "/portfolio/balance",
            params={"subaccount": 0},
        )
        if (
            not isinstance(balance, Mapping)
            or balance.get("balance") in (None, "")
            or _first_present(balance, "portfolio_value", "portfolioValue")
            in (None, "")
        ):
            raise KalshiApiError(
                "Kalshi omitted balance fields required for Real routing.",
                status=503,
                code="kalshi_live_preflight_incomplete",
            )
        positions = self._collect_live_preflight_rows(
            config,
            "/portfolio/positions",
            ("market_positions", "positions", "event_positions"),
        )
        orders = self._collect_live_preflight_rows(
            config,
            "/portfolio/orders",
            ("orders", "order_history"),
        )
        return {
            "balance": dict(balance),
            "positions": positions,
            "orders": orders,
        }

    def _validate_live_order_preflight(
        self,
        latest_state: Mapping[str, Any],
        account: Mapping[str, Any],
        payload: Mapping[str, Any],
        live_payload: Mapping[str, Any],
        decision: Mapping[str, Any],
        *,
        verify_shard_cash: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Re-evaluate irreversible account gates from the final fresh reads."""
        ticker = str(live_payload.get("ticker") or "")
        client_order_id = str(live_payload.get("client_order_id") or "")
        action_value = str(decision.get("action") or "").upper()
        is_sell = bool(live_payload.get("reduce_only")) or action_value.startswith(
            "SELL"
        )
        is_buy = not is_sell and (
            action_value.startswith("BUY") or not action_value
        )
        side = str(decision.get("side") or "").upper()
        if side not in {"YES", "NO"}:
            side = _live_order_economic_side(
                {},
                {
                    **dict(payload or {}),
                    "reduce_only": is_sell,
                },
            )
        requested_count = _finite_number(live_payload.get("count"), 0.0)
        user_price = _finite_number(
            payload.get("user_side_limit_price"),
            None,
        )
        if user_price is None:
            yes_book_price = _finite_number(live_payload.get("price"), None)
            if yes_book_price is not None:
                user_price = (
                    1.0 - yes_book_price
                    if side == "NO"
                    else yes_book_price
                )
        if (
            not ticker
            or not client_order_id
            or side not in {"YES", "NO"}
            or requested_count <= 0.0
            or user_price is None
            or not 0.0 < user_price < 1.0
            or not (is_buy or is_sell)
        ):
            raise KalshiApiError(
                "Real Kalshi order payload is incomplete.",
                status=400,
                code="kalshi_live_order_incomplete",
            )

        terminal_states = {
            "canceled", "cancelled", "closed", "executed", "filled",
            "expired", "rejected",
        }
        all_orders = [
            dict(row)
            for row in account.get("orders") or []
            if isinstance(row, Mapping)
        ]
        existing = next(
            (
                row for row in all_orders
                if str(row.get("client_order_id") or "") == client_order_id
            ),
            None,
        )
        if existing is not None:
            return dict(existing)
        history_quality = (decision.get("model") or {}).get("historyQuality") or {}
        if is_buy and history_quality.get("clockVerified") is False:
            raise KalshiApiError(
                "Real entries require epoch-timestamped candle history with a verified clock.",
                status=409,
                code="kalshi_live_history_clock_unverified",
            )
        open_orders = [
            row for row in all_orders
            if str(row.get("status") or "").lower() not in terminal_states
            and _open_order_remaining(row) > 0.0
        ]

        normalized_positions = []
        for raw in account.get("positions") or []:
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            row_ticker = str(
                row.get("ticker")
                or row.get("market_ticker")
                or row.get("market")
                or ""
            )
            yes_count = _finite_number(
                _first_present(
                    row, "yes_count_fp", "yes_count", "yes_position"
                ),
                0.0,
            )
            no_count = _finite_number(
                _first_present(
                    row, "no_count_fp", "no_count", "no_position"
                ),
                0.0,
            )
            signed = _finite_number(
                row.get("position_fp")
                if row.get("position_fp") not in (None, "")
                else row.get("position"),
                yes_count - no_count,
            )
            position_side, position_count = _live_position_direction(
                signed,
                yes_count,
                no_count,
            )
            if not position_side or position_count <= 0.0:
                continue
            exposure = _optional_dollar_amount(
                _first_present(
                    row,
                    "market_exposure_dollars",
                    "cost_dollars",
                ),
                _first_present(
                    row,
                    "market_exposure",
                    "cost",
                    "realized_cost",
                ),
            )
            normalized_positions.append({
                **row,
                "ticker": row_ticker,
                "side": position_side,
                "count": position_count,
                # Missing account exposure must not understate risk.
                "exposure": (
                    abs(exposure)
                    if exposure is not None
                    else position_count
                ),
            })

        is_hourly = _market_family(ticker) == "btchourly"
        target_event = _kalshi_event_ticker(ticker)

        def in_target_scope(row: Mapping[str, Any]) -> bool:
            row_ticker = str(
                row.get("ticker")
                or row.get("market_ticker")
                or ""
            )
            if is_hourly:
                return _kalshi_event_ticker(row_ticker, row) == target_event
            return row_ticker == ticker

        event_open_orders = [
            row for row in open_orders if in_target_scope(row)
        ]
        if event_open_orders:
            raise KalshiApiError(
                "A Kalshi order is already open in this event.",
                status=409,
                code="kalshi_live_open_order_conflict",
            )

        managed_inventory = _durable_managed_inventory(latest_state)
        scoped_positions = [
            row for row in normalized_positions if in_target_scope(row)
        ]
        account_scope_counts: Dict[Tuple[str, str], float] = {}
        for row in scoped_positions:
            row_ticker = str(row.get("ticker") or "")
            row_side = str(row.get("side") or "").upper()
            key = (row_ticker, row_side)
            account_scope_counts[key] = (
                account_scope_counts.get(key, 0.0)
                + _finite_number(row.get("count"), 0.0)
            )
        managed_scope_counts = {
            (managed_ticker, managed_side): _finite_number(
                managed_count,
                0.0,
            )
            for (
                managed_ticker,
                managed_side,
            ), managed_count in managed_inventory.items()
            if in_target_scope({"ticker": managed_ticker})
            and _finite_number(managed_count, 0.0) > 1e-9
        }
        # Equality is intentionally bidirectional. A fresh manual add makes
        # account > durable; a manual reduction or close makes durable >
        # account (including a completely missing position row). Either means
        # AlphaLab can no longer prove ownership of the contracts it would add
        # to or sell.
        ownership_conflict = any(
            abs(
                account_scope_counts.get(key, 0.0)
                - managed_scope_counts.get(key, 0.0)
            ) > 1e-9
            for key in (
                set(account_scope_counts)
                | set(managed_scope_counts)
            )
        )
        if ownership_conflict:
            raise KalshiApiError(
                "Fresh Kalshi positions include manual or unmanaged contracts.",
                status=409,
                code="kalshi_live_position_ownership_conflict",
            )

        exact_positions = [
            row for row in normalized_positions
            if str(row.get("ticker") or "") == ticker
        ]
        exact_same_side = [
            row for row in exact_positions
            if str(row.get("side") or "").upper() == side
        ]
        exact_opposite = [
            row for row in exact_positions
            if str(row.get("side") or "").upper() != side
        ]

        if is_sell:
            account_count = sum(
                _finite_number(row.get("count"), 0.0)
                for row in exact_same_side
            )
            managed_count = _finite_number(
                managed_inventory.get((ticker, side)),
                0.0,
            )
            if (
                exact_opposite
                or account_count <= 0.0
                or managed_count + 1e-9 < account_count
                or requested_count > account_count + 1e-9
                or requested_count > managed_count + 1e-9
            ):
                raise KalshiApiError(
                    "The fresh AlphaLab-managed position no longer covers "
                    "this reduce-only order.",
                    status=409,
                    code="kalshi_live_close_inventory_changed",
                )
            # Reduce-only exits are never blocked by entry cash or exposure.
            final_exit = _voluntary_exit_route_economics(
                decision,
                {**dict(payload), "count": requested_count, "user_side_limit_price": user_price},
                decision.get("config") or {},
                allow_tightening=False,
            )
            if final_exit["applicable"] and not final_exit["allowed"]:
                raise KalshiApiError(
                    "The actual voluntary close size and limit no longer preserve fee-adjusted exit economics.",
                    status=409,
                    code="kalshi_live_voluntary_exit_economics_changed",
                )
            return None

        if exact_opposite:
            raise KalshiApiError(
                "The fresh Kalshi position conflicts with this entry side.",
                status=409,
                code="kalshi_live_position_ownership_conflict",
            )
        if is_hourly and any(
            str(row.get("ticker") or "") != ticker
            for row in scoped_positions
        ):
            raise KalshiApiError(
                "An owned KXBTCD strike must be managed before another strike "
                "in the event can be added.",
                status=409,
                code="kalshi_live_event_position_conflict",
            )

        config = normalize_strategy_config(
            latest_state.get("config") or {}
        )
        if not exact_same_side:
            if "entryConfirmation" in decision:
                entry_confirmation = _entry_confirmation(
                    latest_state,
                    ticker,
                    side,
                    decision,
                    config,
                )
                if (
                    entry_confirmation.get("required")
                    and not entry_confirmation.get("confirmed")
                ):
                    raise KalshiApiError(
                        "A new Real position requires consecutive confirmed "
                        "scheduler decisions.",
                        status=409,
                        code="kalshi_entry_confirmation_required",
                    )
            reentry_confirmation = _same_ticker_reentry_confirmation(
                latest_state,
                ticker,
                dict(decision.get("edge") or {}),
                config,
            )
            reversal_cooldown = max(
                90,
                int(
                    _finite_number(
                        config.get("reversalCooldownSeconds"),
                        90,
                    )
                ),
            )
            if (
                reentry_confirmation["required"]
                and _finite_number(
                    reentry_confirmation.get("recentExitAgeSeconds"),
                    0.0,
                ) < reversal_cooldown
            ):
                raise KalshiApiError(
                    "The durable same-ticker reversal cooldown is active.",
                    status=409,
                    code="kalshi_reversal_cooldown_active",
                )
            if (
                reentry_confirmation["required"]
                and not reentry_confirmation["confirmed"]
            ):
                raise KalshiApiError(
                    "Same-ticker re-entry requires a stronger confirmed "
                    "probability and conservative edge.",
                    status=409,
                    code="kalshi_reentry_confirmation_required",
                )
        balance = dict(account.get("balance") or {})
        cash_cents = _cents_amount(balance.get("balance"))
        portfolio_value_cents = _cents_amount(
            _first_present(balance, "portfolio_value", "portfolioValue")
        )
        equity_dollars = (cash_cents + portfolio_value_cents) / 100.0
        cash_dollars = cash_cents / 100.0
        if equity_dollars <= 0.0:
            raise KalshiApiError(
                "Fresh Kalshi account equity is unavailable.",
                status=409,
                code="kalshi_live_cash_changed",
            )
        taker_fee_rate = _finite_number(
            (decision.get("config") or {}).get("takerFeeRate"),
            _finite_number(config.get("takerFeeRate"), 0.07),
        )
        rounded_order_cost = kalshi_order_cost(
            user_price,
            requested_count,
            taker_fee_rate,
        )
        # The engine and final preflight must use exactly the same worst-fill
        # price, quantity, fee coefficient, and cent rounding.  Mixing the
        # top-quote per-contract fee into this marginal-limit calculation can
        # add a fractional cent and reject an otherwise exact-cap order.
        required_cash = _finite_number(
            rounded_order_cost.get("cashDebit"),
            0.0,
        )
        if required_cash > cash_dollars + 1e-9:
            raise KalshiApiError(
                "Kalshi cash changed after the strategy decision.",
                status=409,
                code="kalshi_live_cash_changed",
            )

        position_exposure = sum(
            _finite_number(row.get("exposure"), 0.0)
            for row in normalized_positions
        )
        order_exposure = sum(
            _open_order_exposure(row) for row in open_orders
        )
        portfolio_exposure = position_exposure + order_exposure
        scope_exposure = sum(
            _finite_number(row.get("exposure"), 0.0)
            for row in scoped_positions
        ) + sum(
            _open_order_exposure(row)
            for row in open_orders
            if in_target_scope(row)
        )
        ticker_exposure = sum(
            _finite_number(row.get("exposure"), 0.0)
            for row in exact_positions
        ) + sum(
            _open_order_exposure(row)
            for row in open_orders
            if str(
                row.get("ticker")
                or row.get("market_ticker")
                or ""
            ) == ticker
        )
        portfolio_limit = equity_dollars * min(
            10.0,
            max(
                0.1,
                _finite_number(
                    config.get("maxPortfolioExposurePct"),
                    10.0,
                ),
            ),
        ) / 100.0
        market_limit = equity_dollars * min(
            2.0,
            max(
                0.1,
                _finite_number(
                    config.get("maxSingleMarketExposurePct"),
                    2.0,
                ),
            ),
        ) / 100.0
        sizing = dict(decision.get("sizing") or {})
        edge = dict(decision.get("edge") or {})
        micro_position_loss_cap = min(
            _finite_number(
                config.get("microPositionMaxLossDollars"),
                1.0,
            ),
            equity_dollars
            * _finite_number(
                config.get("microPositionMaxLossPct"),
                5.0,
            )
            / 100.0,
        )
        micro_position_authorized = bool(
            sizing.get("microSizingApplied") is True
            and abs(requested_count - 1.0) <= 1e-9
            and ticker_exposure <= 1e-9
            and (not is_hourly or scope_exposure <= 1e-9)
            and required_cash <= micro_position_loss_cap + 1e-9
            and portfolio_exposure + required_cash
            <= portfolio_limit + 1e-9
            and _finite_number(edge.get("netEdge"), -1.0)
            >= _finite_number(
                config.get("microPositionMinNetEdge"),
                0.02,
            )
            and _finite_number(edge.get("conservativeEdge"), -1.0)
            >= _finite_number(
                config.get("microPositionMinConservativeEdge"),
                0.01,
            )
        )
        requested_risk = required_cash
        if portfolio_exposure + requested_risk > portfolio_limit + 1e-9:
            raise KalshiApiError(
                "Fresh Kalshi portfolio exposure exceeds the Real limit.",
                status=409,
                code="kalshi_live_exposure_changed",
            )
        if (
            ticker_exposure + requested_risk > market_limit + 1e-9
            and not micro_position_authorized
        ):
            raise KalshiApiError(
                "Fresh Kalshi ticker exposure exceeds the Real limit.",
                status=409,
                code="kalshi_live_exposure_changed",
            )
        if (
            is_hourly
            and scope_exposure + requested_risk > market_limit + 1e-9
            and not micro_position_authorized
        ):
            raise KalshiApiError(
                "Fresh KXBTCD event exposure exceeds the Real limit.",
                status=409,
                code="kalshi_live_exposure_changed",
            )
        if verify_shard_cash:
            shard_cash = _shard_cash_dollars(balance, live_payload.get("exchange_index"))
            if shard_cash is None:
                raise KalshiApiError(
                    "The target Kalshi exchange shard's available cash is unverified.",
                    status=409,
                    code="kalshi_live_shard_cash_unavailable",
                )
            if required_cash > shard_cash + 1e-9:
                raise KalshiApiError(
                    "Available cash on the target Kalshi exchange shard cannot fund this entry.",
                    status=409,
                    code="kalshi_live_shard_cash_insufficient",
                )
        return None

    def _complete_live_shard_preflight(
        self,
        config: Mapping[str, Any],
        account: Dict[str, Any],
        live_payload: Dict[str, Any],
    ) -> None:
        """Resolve entry collateral using authoritative metadata, never ticker prefixes."""
        if live_payload.get("reduce_only"):
            return
        index = _exchange_shard_index(live_payload.get("exchange_index"))
        if index is None:
            # This read is only needed for older market responses without a
            # shard. It does not retry or auto-submit an order.
            ticker = str(live_payload.get("ticker") or "")
            response = self._signed(config, "GET", f"/markets/{ticker}")
            market = response.get("market") if isinstance(response, Mapping) else None
            if not isinstance(market, Mapping) or str(market.get("ticker") or "") != ticker:
                index = None
            else:
                index = _exchange_shard_index(market.get("exchange_index"))
            if index is None:
                raise KalshiApiError(
                    "Kalshi did not identify the target market's exchange shard.",
                    status=409,
                    code="kalshi_live_shard_cash_unavailable",
                )
            live_payload["exchange_index"] = index
        balance = dict(account.get("balance") or {})
        if _shard_cash_dollars(balance, index) is not None:
            return
        scoped = self._signed(
            config,
            "GET",
            "/portfolio/balance",
            params={"subaccount": 0, "exchange_index": index},
        )
        cash = _finite_number(scoped.get("balance_dollars"), None) if isinstance(scoped, Mapping) else None
        if cash is None and isinstance(scoped, Mapping):
            cents = _finite_number(scoped.get("balance"), None)
            cash = cents / 100.0 if cents is not None else None
        if cash is None or cash < 0:
            raise KalshiApiError(
                "Kalshi omitted the target exchange shard's available balance.",
                status=409,
                code="kalshi_live_shard_cash_unavailable",
            )
        account["balance"] = {
            **balance,
            "balance_breakdown": [
                row for row in balance.get("balance_breakdown") or []
                if isinstance(row, Mapping)
                and _exchange_shard_index(row.get("exchange_index")) != index
            ] + [{"exchange_index": index, "balance": str(cash)}],
        }

    def _submit_live_order(self, user_id: str, payload: Mapping[str, Any], decision: Mapping[str, Any]) -> Dict[str, Any]:
        live_payload = _live_order_payload(payload)
        if not live_payload.get("ticker") or not live_payload.get("client_order_id"):
            raise KalshiApiError("Real Kalshi order payload is incomplete", status=400, code="kalshi_live_order_incomplete")
        with self._live_routing_lease(user_id) as lease:
            refresh_state = getattr(self.state, "refresh", None)
            if self.state is None or not callable(refresh_state):
                raise KalshiApiError(
                    "Authoritative durable Kalshi robot state refresh is unavailable",
                    status=503,
                    code="kalshi_robot_state_unavailable",
                )
            def validate_authoritative_state() -> Dict[str, Any]:
                latest = refresh_state(user_id, environment="real")
                if (
                    not isinstance(latest, Mapping)
                    or latest.get("authoritativeRefresh") is not True
                    or latest.get("durableStateLoaderAvailable") is not True
                ):
                    raise KalshiApiError(
                        "Real Kalshi orders require a durable robot-state refresh",
                        status=503,
                        code="kalshi_robot_state_not_authoritative",
                    )
                latest_config = dict((latest or {}).get("config") or {})
                if (
                    not bool((latest or {}).get("enabled"))
                    or _execution_mode((latest or {}).get("activeEnvironment")) != "real"
                    or _execution_mode(latest_config.get("executionMode")) != "real"
                ):
                    raise KalshiApiError(
                        "Real Kalshi automation was stopped before order submission",
                        status=409,
                        code="kalshi_automation_stopped",
                    )
                return dict(latest or {})

            latest = validate_authoritative_state()
            config = self._real_config(
                user_id,
                authoritative=True,
            )
            account = self._fresh_live_account_preflight(config)
            existing = self._validate_live_order_preflight(
                latest,
                account,
                payload,
                live_payload,
                decision,
                verify_shard_cash=False,
            )
            if existing is not None:
                normalized_existing = _normalise_live_order(
                    existing,
                    payload,
                    decision,
                )
                if not normalized_existing.get("created_time"):
                    normalized_existing["created_time"] = (
                        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    )
                return {
                    **normalized_existing,
                    "alphaLabManaged": True,
                    "alphalabManaged": True,
                    "alphaLabOrder": True,
                    "source": "alphalab",
                    "idempotent": True,
                }
            # The account read above can outlive both configuration and lease
            # generations. Reload durable mode/arming state once more, then
            # renew the exact fencing token immediately before the real POST.
            self._complete_live_shard_preflight(config, account, live_payload)
            if isinstance(decision, dict):
                # Restricted API keys and older market metadata can require a
                # final scoped read. Expose the verified execution funding,
                # without replacing the separately retained strategy thesis.
                funding_context = _shard_funding_context(
                    account.get("balance") or {}, live_payload.get("exchange_index"),
                )
                decision["market"] = {
                    **dict(decision.get("market") or {}),
                    "exchangeIndex": funding_context["exchangeIndex"],
                }
                decision["account"] = {
                    **dict(decision.get("account") or {}),
                    **funding_context,
                }
                decision["shardFunding"] = {
                    **dict(decision.get("shardFunding") or {}),
                    **funding_context,
                    "requiresUserFunding": funding_context["fundingStatus"] == "empty",
                    "verifiedAtPreflight": True,
                }
            latest = validate_authoritative_state()
            self._validate_live_order_preflight(
                latest,
                account,
                payload,
                live_payload,
                decision,
            )
            self._renew_live_routing_lease(lease)
            try:
                response = self._signed(
                    config,
                    "POST",
                    "/portfolio/events/orders",
                    json_body=live_payload,
                )
            except Exception as exc:
                # A timeout/5xx does not prove that the exchange rejected the
                # order. Persist uncertainty; never send a second POST here.
                status = getattr(exc, "status", None)
                setattr(exc, "kalshi_routing_failure", {
                    "code": str(getattr(exc, "code", None) or type(exc).__name__),
                    "httpStatus": status,
                    "endpoint": "/portfolio/events/orders",
                    "outcome": "rejected" if isinstance(status, int) and 400 <= status < 500 and status != 408 else "unknown",
                    "phase": "submission",
                    "intendedAction": str(decision.get("action") or ""),
                    "plannedCount": _contract_quantity(live_payload.get("count")),
                    "clientOrderId": str(live_payload.get("client_order_id") or ""),
                })
                raise
        raw_order = response.get("order") or response.get("order_response") or response
        if not isinstance(raw_order, Mapping):
            raw_order = {}
        # The local payload also contains the user-outcome price that is
        # intentionally stripped before the signed request.  Keep it only for
        # normalization so NO orders cannot be recorded at the complementary
        # YES-book price.
        order = _normalise_live_order(raw_order, payload, decision)
        if not order.get("created_time"):
            order["created_time"] = datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        order.update({
            "alphaLabManaged": True,
            "alphalabManaged": True,
            "alphaLabOrder": True,
            "source": "alphalab",
        })
        self._notify_order(user_id, order, decision)
        return order

    def _persist_routing_failure(
        self,
        user_id: str,
        decision: Mapping[str, Any],
        payload: Mapping[str, Any],
        error: Exception,
    ) -> None:
        """Retain failed-attempt evidence even though scheduler health raises."""
        failure = dict(getattr(error, "kalshi_routing_failure", None) or {
            "code": str(getattr(error, "code", None) or type(error).__name__),
            "httpStatus": getattr(error, "status", None),
            "endpoint": getattr(error, "endpoint", None),
            "outcome": "not_submitted" if getattr(error, "endpoint", None) and getattr(error, "endpoint", None) != "/portfolio/events/orders" else "unknown",
            "phase": "preflight" if getattr(error, "endpoint", None) and getattr(error, "endpoint", None) != "/portfolio/events/orders" else "routing",
            "intendedAction": str(decision.get("action") or ""),
            "plannedCount": _contract_quantity(payload.get("count")),
            "clientOrderId": str(payload.get("client_order_id") or ""),
        })
        failed_decision = {
            **dict(decision),
            "action": "WAIT",
            "executionIntent": "WAIT_LIVE_ROUTING_FAILURE",
            "routingFailure": failure,
            "blockingReasons": list(dict.fromkeys(list(decision.get("blockingReasons") or []) + [failure["code"]])),
        }
        try:
            self.state.record(user_id, failed_decision, None)
        except Exception as persist_error:
            self.safe_print(f"[KalshiReal] failed-attempt state write error={type(persist_error).__name__}")
        observation = _market_observation("real", failed_decision, source="scheduler", submit_order=True)
        if observation and callable(self.observation_saver):
            try:
                self.observation_saver(user_id, observation)
            except Exception as persist_error:
                self.safe_print(f"[KalshiReal] failed-attempt observation write error={type(persist_error).__name__}")

    def tick(
        self,
        user_id: str,
        *,
        submit_order: bool,
        mode: Optional[str] = None,
        family: str = "btc15m",
    ) -> Dict[str, Any]:
        """Serialize each account's evaluate-and-route cycle.

        The background scheduler and a manual refresh may arrive together. A
        per-user lock prevents both from observing the same position and
        submitting the same close before either portfolio refresh completes.
        """
        key = str(user_id)
        with self._tick_locks_guard:
            lock = self._tick_locks.setdefault(key, threading.RLock())
        with lock:
            return self._tick_locked(
                user_id,
                submit_order=submit_order,
                mode=mode,
                family=family,
            )

    def _tick_locked(
        self,
        user_id: str,
        *,
        submit_order: bool,
        mode: Optional[str] = None,
        family: str = "btc15m",
    ) -> Dict[str, Any]:
        seed_state = self.state.get(user_id)
        strategy_seed = dict(seed_state.get("config") or {})
        execution_mode = _execution_mode(mode or strategy_seed.get("executionMode") or "paper")
        robot_state = self.state.get(user_id, environment=execution_mode)
        strategy_seed = dict(robot_state.get("config") or {})
        try:
            portfolio = self.portfolio(
                user_id,
                mode=execution_mode,
                mutate=bool(submit_order),
            )
        except TypeError as exc:
            # Preserve compatibility with small injected portfolio adapters used
            # by integrations/tests that predate the explicit read-only flag.
            if "unexpected keyword argument 'mutate'" not in str(exc):
                raise
            portfolio = self.portfolio(user_id, mode=execution_mode)
        environment = "real" if execution_mode == "real" else "paper"
        balance = portfolio.get("balance") or {}
        cash_cents = _finite_number(balance.get("balance"), 0.0)
        # Kalshi and AlphaLab Paper both expose cash separately from marked
        # position value. Risk capital is their sum.
        bankroll_cents = _account_equity_cents(balance, execution_mode)
        try:
            bankroll = float(bankroll_cents) / 100.0
        except (TypeError, ValueError):
            bankroll = 0.0 if execution_mode == "real" else 1000.0
        if execution_mode != "real":
            bankroll = max(100.0, bankroll)
        raw_strategy_config = dict(robot_state.get("config") or {})
        strategy_config = dict(raw_strategy_config)
        strategy_config["executionMode"] = execution_mode
        strategy_config["paperBankroll"] = bankroll
        strategy_config = normalize_strategy_config(strategy_config)
        family = "btchourly" if str(family).lower() == "btchourly" else "btc15m"
        reference_override = None
        if self.reference_stream is not None:
            try:
                reference_override = self.reference_stream.snapshot(user_id)
            except Exception as exc:
                self.safe_print(
                    f"[KalshiBRTI] snapshot unavailable user={str(user_id)[:8]} "
                    f"error={type(exc).__name__}"
                )
        if family == "btchourly":
            required_held_tickers = _managed_open_tickers(
                portfolio,
                "btchourly",
            )
            hourly_snapshot_args: Dict[str, Any] = {"base_url": KALSHI_PUBLIC_BASE}
            if required_held_tickers:
                hourly_snapshot_args["required_tickers"] = required_held_tickers
            if reference_override is not None:
                hourly_snapshot_args["reference_override"] = reference_override
            ladder = self.client.hourly_snapshot(**hourly_snapshot_args)
            hourly_config = _hourly_live_strategy_config(strategy_config)
            hourly_fee_rate = _finite_number(
                (ladder.get("feePolicy") or {}).get("takerFeeCoefficient"),
                None,
            )
            if hourly_fee_rate is not None and hourly_fee_rate >= 0.0:
                hourly_config["takerFeeRate"] = hourly_fee_rate
            hourly_candidate_penalty_weight = max(
                0.0,
                min(
                    0.50,
                    _finite_number(
                        hourly_config.get("hourlyCandidatePenaltyWeight"),
                        0.10,
                    ),
                ),
            )
            reference_policy = dict(ladder.get("referencePolicy") or {})
            evaluation_spot = _finite_number(
                reference_policy.get("selectedPrice"),
                None,
            )
            if evaluation_spot is None or evaluation_spot <= 0.0:
                raise KalshiApiError(
                    "KXBTCD evaluation requires a fresh raw BRTI reference.",
                    status=409,
                    code="btc_reference_unavailable",
                )
            candidates = []
            for market in ladder.get("markets") or []:
                candidate_ticker = str((market or {}).get("ticker") or "")
                book = (ladder.get("orderbooks") or {}).get(candidate_ticker) or {}
                context = _paper_account_context(
                    portfolio,
                    robot_state,
                    candidate_ticker,
                    bankroll,
                    exchange_index=(market or {}).get("exchange_index"),
                    event_ticker=str(
                        (market or {}).get("event_ticker")
                        or ladder.get("eventTicker")
                        or ""
                    ),
                )
                if context.get("hasPosition"):
                    context["hasPosition"] = False
                    context["alreadyTraded"] = False
                candidate_reference = dict(ladder.get("reference") or {})
                candidate_reference.update({
                    "price": evaluation_spot,
                    "evaluationPrice": evaluation_spot,
                    "referencePolicy": reference_policy,
                })
                candidate_reference.update(
                    dict((ladder.get("ladderFit") or {}).get(candidate_ticker) or {})
                )
                candidate = evaluate_btc15_contract(
                    market,
                    spot_price=evaluation_spot,
                    candles=(ladder.get("reference") or {}).get("candles") or [],
                    config=hourly_config,
                    orderbook=book,
                    reference_time=(ladder.get("reference") or {}).get("timestamp"),
                    reference_metadata=candidate_reference,
                    book_time=ladder.get("orderbookAsOf"),
                    account_context=context,
                )
                candidates.append((candidate, market, book))
            if not candidates:
                raise KalshiApiError("The active KXBTCD event has no executable strike candidates")
            candidate_diagnostics = {
                str((item[1] or {}).get("ticker") or ""):
                _hourly_candidate_diagnostic(
                    item[0],
                    item[1],
                    len(candidates),
                    penalty_weight=hourly_candidate_penalty_weight,
                )
                for item in candidates
            }
            held_candidates = [
                item
                for item in candidates
                if str((item[1] or {}).get("ticker") or "")
                in set(required_held_tickers)
            ]
            if required_held_tickers and not held_candidates:
                raise KalshiApiError(
                    "A managed KXBTCD holding is unavailable in the executable ladder",
                    status=409,
                    code=KALSHI_HOURLY_HELD_MARKET_UNAVAILABLE,
                )
            held_management_ranks = {
                str((item[1] or {}).get("ticker") or ""):
                _hourly_candidate_management_priority(
                    item[0],
                    item[1],
                    item[2],
                    portfolio,
                    robot_state,
                    hourly_config,
                )
                for item in held_candidates
            }
            # Prefer a routable opportunity; otherwise expose the closest
            # uncertainty-adjusted candidate so the UI explains why it waited.
            # An owned strike always narrows this pool first: while it is being
            # managed, no higher-edge sibling strike may become a new entry.
            # Among multiple owned strikes, exit urgency outranks add edge.
            decision, selected_market, selected_book = max(
                held_candidates or candidates,
                key=lambda item: (
                    *(
                        held_management_ranks.get(
                            str((item[1] or {}).get("ticker") or ""),
                            (0, -1.0, -1.0),
                        )
                        if held_candidates
                        else ()
                    ),
                    1
                    if candidate_diagnostics.get(
                        str((item[1] or {}).get("ticker") or ""),
                        {},
                    ).get("penaltyCleared")
                    else 0,
                    _finite_number(
                        candidate_diagnostics.get(
                            str((item[1] or {}).get("ticker") or ""),
                            {},
                        ).get("shrunkenScore"),
                        -99.0,
                    ),
                    _finite_number((item[0].get("edge") or {}).get("netEdge"), -99.0),
                ),
            )
            suppressed_new_strikes = sorted({
                str((item[1] or {}).get("ticker") or "")
                for item in candidates
                if required_held_tickers
                and str((item[1] or {}).get("ticker") or "")
                not in set(required_held_tickers)
                and str(item[0].get("action") or "").startswith("BUY_")
            })
            decision = dict(decision)
            selected_ticker = str((selected_market or {}).get("ticker") or "")
            selected_diagnostic = dict(
                candidate_diagnostics.get(selected_ticker) or {}
            )
            ranked_diagnostics = sorted(
                candidate_diagnostics.values(),
                key=lambda row: (
                    1 if row.get("penaltyCleared") else 0,
                    _finite_number(row.get("shrunkenScore"), -99.0),
                    _finite_number(row.get("netEdge"), -99.0),
                ),
                reverse=True,
            )
            selected_rank = next(
                (
                    index
                    for index, row in enumerate(ranked_diagnostics, start=1)
                    if str(row.get("ticker") or "") == selected_ticker
                ),
                None,
            )
            compact_candidates = [dict(row) for row in ranked_diagnostics[:12]]
            if (
                selected_ticker
                and all(
                    str(row.get("ticker") or "") != selected_ticker
                    for row in compact_candidates
                )
            ):
                compact_candidates.append(selected_diagnostic)
            decision["candidateDiagnostics"] = {
                "candidateCount": len(candidates),
                "selectedTicker": selected_ticker,
                "selectedRank": selected_rank,
                "penaltyWeight": hourly_candidate_penalty_weight,
                "selected": selected_diagnostic,
                "topCandidates": compact_candidates,
            }
            if (
                str(decision.get("action") or "").startswith("BUY_")
                and not selected_diagnostic.get("penaltyCleared")
            ):
                decision["action"] = "WAIT"
                decision["executionIntent"] = "WAIT_HOURLY_CANDIDATE_SHRINKAGE"
                decision["blockingReasons"] = list(dict.fromkeys(
                    list(decision.get("blockingReasons") or [])
                    + ["hourly_multiple_candidate_uncertainty"]
                ))
                decision["sizing"] = {
                    **dict(decision.get("sizing") or {}),
                    "contracts": 0,
                    "contractsFp": 0.0,
                    "plannedContractsFp": 0.0,
                    "notional": 0.0,
                }
                decision["gates"] = list(decision.get("gates") or []) + [{
                    "category": "signal",
                    "name": "Hourly multiple-candidate uncertainty",
                    "status": "block",
                    "value": selected_diagnostic.get("shrunkenScore"),
                    "threshold": selected_diagnostic.get(
                        "minimumShrunkenScore"
                    ),
                    "detail": (
                        "The selected strike's conservative edge did not "
                        "survive the hourly ladder winner's-curse penalty."
                    ),
                }]
            decision["referencePolicy"] = reference_policy
            decision["managementPriority"] = {
                "active": bool(required_held_tickers),
                "requiredHeldTickers": list(required_held_tickers),
                "selectedTicker": (selected_market or {}).get("ticker"),
                "newStrikeOpeningSuppressed": bool(suppressed_new_strikes),
                "suppressedNewStrikeTickers": suppressed_new_strikes,
                "heldCandidateRanks": {
                    ticker: list(rank)
                    for ticker, rank in held_management_ranks.items()
                },
            }
            strategy_config = hourly_config
            snapshot = {
                **dict(ladder),
                "market": dict(selected_market),
                "orderbook": dict(selected_book),
                "candidateCount": len(candidates),
                "evaluationReferencePrice": evaluation_spot,
                "referencePolicy": reference_policy,
                "managementPriority": dict(decision["managementPriority"]),
                "candidateSummary": compact_candidates,
            }
        else:
            strategy_config = _btc15_live_strategy_config(strategy_config)
            shadow_strategy_config = _btc15_shadow_challenger_config(
                strategy_config
            )
            snapshot_args: Dict[str, Any] = {"base_url": KALSHI_PUBLIC_BASE}
            if reference_override is not None:
                snapshot_args["reference_override"] = reference_override
            snapshot = self.client.snapshot(**snapshot_args)
            snapshot_fee_rate = _finite_number(
                (snapshot.get("feePolicy") or {}).get(
                    "takerFeeCoefficient"
                ),
                None,
            )
            if snapshot_fee_rate is not None and snapshot_fee_rate >= 0.0:
                strategy_config["takerFeeRate"] = snapshot_fee_rate
                shadow_strategy_config["takerFeeRate"] = snapshot_fee_rate
            candidate_ticker = str((snapshot.get("market") or {}).get("ticker") or "")
            context = _paper_account_context(
                portfolio, robot_state, candidate_ticker, bankroll,
                exchange_index=(snapshot.get("market") or {}).get("exchange_index"),
            )
            if context.get("hasPosition"):
                context["hasPosition"] = False
                context["alreadyTraded"] = False
            decision = evaluate_btc15_contract(
                snapshot["market"],
                spot_price=snapshot["reference"].get("price"),
                candles=snapshot["reference"].get("candles") or [],
                config=strategy_config,
                orderbook=snapshot.get("orderbook") or {},
                reference_time=snapshot["reference"].get("timestamp"),
                reference_metadata=snapshot.get("reference") or {},
                book_time=snapshot.get("orderbookAsOf"),
                account_context=context,
            )
            # Evaluate the challenger over the exact same immutable snapshot.
            # No additional network request is made and this result is never
            # passed to the order router; it exists only for future finalized-
            # outcome evaluation without look-ahead selection bias.
            try:
                shadow_decision = evaluate_btc15_contract(
                    snapshot["market"],
                    spot_price=snapshot["reference"].get("price"),
                    candles=snapshot["reference"].get("candles") or [],
                    config=shadow_strategy_config,
                    orderbook=snapshot.get("orderbook") or {},
                    reference_time=snapshot["reference"].get("timestamp"),
                    reference_metadata=snapshot.get("reference") or {},
                    book_time=snapshot.get("orderbookAsOf"),
                    account_context=context,
                )
            except Exception as exc:
                # Observability must never become an availability dependency
                # for the validated live policy.  Record only the exception
                # type so logs and persisted diagnostics cannot leak payloads.
                self.safe_print(
                    "[KalshiEntryShadow] evaluation skipped "
                    f"error={type(exc).__name__}"
                )
                shadow_decision = {
                    "action": "WAIT",
                    "blockingReasons": ["shadow_evaluation_error"],
                    "shadowEvaluationError": type(exc).__name__,
                }
        decision = dict(decision)
        decision["marketFamily"] = family
        decision["engine"] = (
            "btchourly-strike-ladder-v4"
            if family == "btchourly"
            else "btc15_settlement_aligned_v11"
        )
        decision["outcomeCalibrationPolicy"] = "btc_walk_forward_live_v10"
        if family == "btc15m":
            decision["entryShadow"] = {
                "champion": _entry_shadow_diagnostic(
                    decision,
                    policy="btc15_high_band_champion_v10",
                    strategy_config=strategy_config,
                    route_allowed=True,
                    confirmation_evaluated_online=True,
                ),
                "frequencyChallenger": _entry_shadow_diagnostic(
                    shadow_decision,
                    policy="btc15_high_band_frequency_shadow_v10",
                    strategy_config=shadow_strategy_config,
                ),
                "promotionCriteria": {
                    "minimumFinalizedMarkets": 50,
                    "minimumRollingWindowProfitFactor": 1.10,
                    "requiredPositiveRollingWindows": 3,
                    "requirePositiveAggregateAfterFeePnl": True,
                    "requireDrawdownNoWorseThanChampion": True,
                    "routeAllowed": False,
                },
            }
        else:
            decision["entryShadow"] = {
                "champion": _entry_shadow_diagnostic(
                    decision,
                    policy="btchourly_outcome_calibrated_v9",
                    strategy_config=strategy_config,
                    route_allowed=True,
                    confirmation_evaluated_online=True,
                ),
                "frequencyChallenger": {
                    "policy": "btchourly_frequency_observation_v10",
                    "enabled": True,
                    "routeAllowed": False,
                    "opportunity": False,
                    "reason": (
                        "No relaxed hourly rule passed walk-forward validation; "
                        "candidateDiagnostics remains the shadow evidence stream."
                    ),
                },
            }
        account_warnings = (
            list(portfolio.get("warnings") or [])
            if execution_mode == "real"
            else []
        )
        decision["dataQuality"] = {
            "referenceModel": (snapshot.get("reference") or {}).get("model"),
            "officialBrti": bool((snapshot.get("reference") or {}).get("isOfficialBrti")),
            "referenceAgeSeconds": (decision.get("model") or {}).get("referenceAgeSeconds"),
            "bookAgeSeconds": (decision.get("market") or {}).get("bookAgeSeconds"),
            "snapshotLatencyMs": snapshot.get("latencyMs"),
            "settlementWindowSamples": (snapshot.get("reference") or {}).get("settlementWindowSamples"),
            "referencePolicy": dict(snapshot.get("referencePolicy") or {}),
            "warnings": sorted(set(
                list(snapshot.get("warnings") or []) + account_warnings
            )),
            "candidateCount": snapshot.get("candidateCount", 1),
            "accountCompleteness": dict(portfolio.get("completeness") or {}),
            "feePolicy": dict(snapshot.get("feePolicy") or {}),
        }
        decision["feePolicy"] = dict(snapshot.get("feePolicy") or {})
        ticker = str((snapshot.get("market") or {}).get("ticker") or "")
        decision["market"] = {
            **dict(decision.get("market") or {}),
            "ticker": ticker,
            "exchangeIndex": _exchange_shard_index((snapshot.get("market") or {}).get("exchange_index")),
        }
        account_context = _paper_account_context(
            portfolio,
            robot_state,
            ticker,
            bankroll,
            exchange_index=(snapshot.get("market") or {}).get("exchange_index"),
            event_ticker=(
                str(snapshot.get("eventTicker") or "")
                if family == "btchourly"
                else None
            ),
        )
        position_context = _position_execution_context(portfolio, ticker)
        held_side = position_context.get("side")
        held_count = _contract_quantity(position_context.get("count"))
        unmanaged_position_count = _contract_quantity(
            position_context.get("unmanagedCount")
        )
        decision["makerShadow"] = _maker_shadow_diagnostic(
            decision,
            snapshot.get("feePolicy") or {},
            strategy_config,
            has_position=bool(held_side and held_count > 0),
        )
        fair_yes = _finite_number((decision.get("model") or {}).get("fairYesProbability"), 0.5)
        held_probability = (
            fair_yes if held_side == "YES"
            else 1.0 - fair_yes if held_side == "NO"
            else None
        )
        sale_estimate = (
            _estimate_reduce_only_sale(
                held_side,
                held_count,
                snapshot.get("orderbook") or {},
                taker_fee_rate=_finite_number(
                    strategy_config.get("takerFeeRate"), 0.07
                ),
            )
            if held_side and held_count > 0
            else {}
        )
        fillable_exit_count = _contract_quantity(
            sale_estimate.get("fillableCount")
        )
        exit_net_per_contract = (
            _finite_number(sale_estimate.get("netProceeds")) / fillable_exit_count
            if fillable_exit_count > 0
            else None
        )
        hold_age_seconds = _seconds_since(position_context.get("lastTradeAt"))
        if hold_age_seconds is None and held_side:
            hold_age_seconds = _recent_filled_entry_age(robot_state, ticker)
        minimum_hold_seconds = max(
            60,
            int(
                _finite_number(
                    strategy_config.get("minimumHoldSeconds"),
                    60,
                )
            ),
        )
        exit_value_buffer = _finite_number(strategy_config.get("exitValueBuffer"), 0.01)
        exit_value_edge = (
            exit_net_per_contract - held_probability
            if exit_net_per_contract is not None and held_probability is not None
            else None
        )
        exit_economics = _exit_economic_state(
            average_entry_price=position_context.get("averageEntryPrice"),
            allocated_entry_fee=_finite_number(position_context.get("allocatedEntryFee"), 0.0),
            held_count=held_count,
            net_exit_value_per_contract=exit_net_per_contract,
            held_probability=held_probability,
            strategy_config=strategy_config,
        )
        exit_confirmation = _protective_exit_confirmation(
            robot_state,
            ticker,
            str(held_side or ""),
            exit_economics,
            strategy_config,
            generated_at=decision.get("generatedAt"),
            data_quality_ok=_protective_confirmation_data_quality(decision),
        )
        loss_exit_authorized = bool(
            exit_economics.get("emergencyLossExit")
            or (
                exit_economics.get("protectiveLossExit")
                and exit_confirmation.get("confirmed")
            )
        )
        economically_executable = bool(
            fillable_exit_count > 0
            and exit_value_edge is not None
            and exit_value_edge >= exit_value_buffer
            and exit_economics["profitableExit"]
        )
        exit_analysis = {
            **position_context,
            **sale_estimate,
            **exit_economics,
            "heldProbability": held_probability,
            "netExitValuePerContract": exit_net_per_contract,
            "exitValueEdge": exit_value_edge,
            "requiredExitValueEdge": exit_value_buffer,
            "holdAgeSeconds": hold_age_seconds,
            "minimumHoldSeconds": minimum_hold_seconds,
            "economicallyExecutable": economically_executable,
            "expectedHoldValuePerContract": held_probability,
            "expectedHoldPnlPerContract": (
                held_probability
                - _finite_number(
                    exit_economics.get("breakEvenExitValuePerContract"),
                    0.0,
                )
                if held_probability is not None
                and exit_economics.get("breakEvenExitValuePerContract")
                is not None
                else None
            ),
            "holdVsExitExpectedDeltaPerContract": (
                held_probability - exit_net_per_contract
                if held_probability is not None
                and exit_net_per_contract is not None
                else None
            ),
            "counterfactualPolicy": "hold_to_settlement_vs_executable_exit_v1",
            "protectiveConfirmation": exit_confirmation,
            "lossExitAuthorizedAfterConfirmation": loss_exit_authorized,
        }
        decision["exitAnalysis"] = exit_analysis
        decision["protectiveConfirmation"] = dict(exit_confirmation)
        if (
            exit_confirmation.get("required")
            and exit_confirmation.get("dataQualityEligible") is True
        ):
            confirmation_reason = (
                "protective_exit_confirmed"
                if exit_confirmation.get("confirmed")
                else "protective_exit_confirmation"
            )
            decision["blockingReasons"] = list(dict.fromkeys(
                list(decision.get("blockingReasons") or [])
                + [confirmation_reason]
            ))
        decision["account"] = {
            **{
                key: account_context.get(key) for key in (
                    "exchangeIndex", "aggregateCashAvailable",
                    "shardCashAvailable", "shardCashKnown", "fundingStatus",
                )
            },
            "heldSide": held_side,
            "heldCount": held_count,
            "unmanagedPositionCount": unmanaged_position_count,
            "accountPositionCount": position_context.get("accountPositionCount"),
            "cashAvailable": account_context.get("cashAvailable"),
            "portfolioExposure": account_context.get("portfolioExposure"),
            "currentMarketExposure": account_context.get("currentMarketExposure"),
            "currentTickerExposure": account_context.get("currentTickerExposure"),
            "currentEventExposure": account_context.get("currentEventExposure"),
            "currentEventPositionExposure": account_context.get(
                "currentEventPositionExposure"
            ),
            "currentEventOpenOrderExposure": account_context.get(
                "currentEventOpenOrderExposure"
            ),
            "eventTicker": account_context.get("eventTicker"),
            "hasEventPosition": account_context.get("hasEventPosition"),
            "hasOpenOrder": account_context.get("hasOpenOrder"),
            "openOrderTickers": account_context.get("openOrderTickers"),
        }

        if execution_mode == "real" and cash_cents <= 0 and not held_side:
            decision["action"] = "WAIT"
            decision["executionIntent"] = "WAIT_REAL_NO_CASH"
            decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["real_cash_unavailable"]
            decision["gates"] = list(decision.get("gates") or []) + [{
                "category": "account",
                "name": "Real cash available",
                "status": "block",
                "value": 0,
                "threshold": "> 0",
                "detail": "Real Kalshi account has no available cash; robot will not submit orders.",
            }]
            decision["sizing"] = {
                **dict(decision.get("sizing") or {}),
                "contracts": 0,
                "contractsFp": 0.0,
                "plannedContractsFp": 0.0,
                "notional": 0.0,
            }
        order = None
        decision_side = str(decision.get("side") or "").upper()
        can_route = False
        route_count_override: Optional[float] = None
        if (
            held_side
            and str(decision.get("action") or "").startswith("BUY_")
            and decision_side == held_side
            and (
                exit_economics["emergencyExit"]
                or exit_economics["protectiveExit"]
            )
        ):
            # Never add to a position already demanding exit attention. Even
            # when no bid makes the loss economically authorizable yet, keep
            # the cycle in position-management mode and wait for close depth.
            decision["action"] = "WAIT"
            decision["executionIntent"] = (
                f"WAIT_{held_side}_EXIT_ATTENTION"
            )
            decision["blockingReasons"] = list(dict.fromkeys(
                list(decision.get("blockingReasons") or [])
                + ["position_exit_attention"]
            ))
        if str(decision.get("action") or "").startswith("BUY_") and ticker:
            if held_side and held_side == decision_side:
                add_age_seconds = _seconds_since(position_context.get("lastTradeAt"))
                minimum_add_interval = max(
                    90,
                    int(
                        _finite_number(
                            strategy_config.get(
                                "minimumAddIntervalSeconds"
                            ),
                            90,
                        )
                    ),
                )
                add_probability = _finite_number(
                    (decision.get("edge") or {}).get("fairProbability"),
                    _finite_number((decision.get("edge") or {}).get("modelProbability"), 0.0),
                )
                add_edge = _finite_number((decision.get("edge") or {}).get("conservativeEdge"), -1.0)
                add_probability_floor = _finite_number(strategy_config.get("addMinModelProbability"), 0.67)
                add_edge_floor = _finite_number(strategy_config.get("addMinConservativeEdge"), 0.01)
                previous_signal = _recent_filled_entry_signal(robot_state, ticker, decision_side)
                probability_improvement = max(
                    0.01,
                    _finite_number(
                        strategy_config.get(
                            "addMinProbabilityImprovement"
                        ),
                        0.01,
                    ),
                )
                edge_improvement = max(
                    0.001,
                    _finite_number(
                        strategy_config.get("addMinEdgeImprovement"),
                        0.001,
                    ),
                )
                signal_improved = _scale_in_signal_improved(
                    previous_signal,
                    add_probability,
                    add_edge,
                    probability_improvement,
                    edge_improvement,
                )
                if account_context.get("hasOpenOrder"):
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["add_order_pending"]
                elif add_age_seconds is not None and add_age_seconds < minimum_add_interval:
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["add_interval"]
                elif add_probability < add_probability_floor or add_edge < add_edge_floor or not signal_improved:
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["add_signal_not_improved"]
                elif _contract_quantity(
                    (decision.get("sizing") or {}).get("plannedContractsFp")
                    or (decision.get("sizing") or {}).get("contractsFp")
                    or (decision.get("sizing") or {}).get("contracts")
                ) <= 0:
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["add_exposure_full"]
                else:
                    can_route = True
                    proposed_add = _contract_quantity(
                        (decision.get("sizing") or {}).get("plannedContractsFp")
                        or (decision.get("sizing") or {}).get("contractsFp")
                        or (decision.get("sizing") or {}).get("contracts")
                    )
                    add_fraction = max(
                        0.10,
                        min(1.0, _finite_number(strategy_config.get("addSizeFraction"), 0.50)),
                    )
                    route_count_override = max(
                        0.01,
                        _contract_quantity(proposed_add * add_fraction),
                    )
                    decision["executionIntent"] = f"ADD_{decision_side}"
                    decision["positionManagement"] = {
                        "mode": "add",
                        "existingContracts": held_count,
                        "proposedContracts": proposed_add,
                        "routedContracts": route_count_override,
                        "addSizeFraction": add_fraction,
                        "secondsSinceLastFill": add_age_seconds,
                        "minimumAddIntervalSeconds": minimum_add_interval,
                        "minimumAddModelProbability": add_probability_floor,
                        "minimumAddConservativeEdge": add_edge_floor,
                        "previousSignal": previous_signal,
                        "minimumProbabilityImprovement": probability_improvement,
                        "minimumEdgeImprovement": edge_improvement,
                    }
            elif held_side and held_side != decision_side:
                if account_context.get("hasOpenOrder"):
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["close_order_pending"]
                elif (
                    hold_age_seconds is not None
                    and hold_age_seconds < minimum_hold_seconds
                    and not exit_economics["emergencyLossExit"]
                ):
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["minimum_hold_period"]
                elif fillable_exit_count <= 0:
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["no_executable_close_depth"]
                elif not economically_executable and not loss_exit_authorized:
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["reversal_exit_value_insufficient"]
                elif exit_net_per_contract is not None and 0.0 < exit_net_per_contract < 1.0:
                    # A reversal is deliberately two-step. First reduce the
                    # existing outcome to zero; a later fresh cycle may open the
                    # opposite side. Full-depth VWAP, fees, and the model's
                    # expected hold value must justify the close first.
                    decision["action"] = f"SELL_{held_side}"
                    decision["side"] = held_side
                    decision["edge"] = {
                        **dict(decision.get("edge") or {}),
                        "side": held_side,
                        # Route at the worst depth level included by the
                        # estimator. A VWAP limit would exclude lower bids and
                        # can turn a planned full close into a partial fill.
                        "price": _finite_number(sale_estimate.get("worstBid"), exit_net_per_contract),
                    }
                    decision["blockingReasons"] = []
                    decision["executionIntent"] = f"CLOSE_{held_side}_FOR_REVERSE_TO_{decision_side}"
                    decision["exitAnalysis"]["trigger"] = (
                        "emergency_stop_loss"
                        if exit_economics["emergencyLossExit"]
                        else "protective_stop_loss"
                        if exit_economics["protectiveLossExit"] and not economically_executable
                        else "fee_adjusted_take_profit"
                    )
                    route_count_override = fillable_exit_count
                    can_route = True
                else:
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["no_executable_close_bid"]
            else:
                # There is deliberately no per-contract or per-day trade-count
                # ceiling.  Re-entry is governed by current position/open-order,
                # cash, Kelly sizing, exposure, and anti-churn timing gates.
                recent_exit_age = _recent_filled_exit_age(robot_state, ticker)
                reversal_cooldown = max(
                    90,
                    int(
                        _finite_number(
                            strategy_config.get("reversalCooldownSeconds"),
                            90,
                        )
                    ),
                )
                reentry_confirmation = _same_ticker_reentry_confirmation(
                    robot_state,
                    ticker,
                    dict(decision.get("edge") or {}),
                    strategy_config,
                    recent_exit_age=recent_exit_age,
                )
                if recent_exit_age is not None and recent_exit_age < reversal_cooldown:
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["reversal_cooldown"]
                    decision["exitAnalysis"]["recentExitAgeSeconds"] = recent_exit_age
                    decision["exitAnalysis"]["reversalCooldownSeconds"] = reversal_cooldown
                    decision["reentryConfirmation"] = reentry_confirmation
                elif (
                    reentry_confirmation["required"]
                    and not reentry_confirmation["confirmed"]
                ):
                    decision["action"] = "WAIT"
                    decision["blockingReasons"] = list(
                        decision.get("blockingReasons") or []
                    ) + ["reentry_confirmation"]
                    decision["executionIntent"] = (
                        "WAIT_REENTRY_CONFIRMATION"
                    )
                    decision["reentryConfirmation"] = (
                        reentry_confirmation
                    )
                    decision["gates"] = list(
                        decision.get("gates") or []
                    ) + [{
                        "category": "position",
                        "name": "Same-ticker re-entry confirmation",
                        "status": "block",
                        "value": {
                            "modelProbability": reentry_confirmation[
                                "modelProbability"
                            ],
                            "conservativeEdge": reentry_confirmation[
                                "conservativeEdge"
                            ],
                        },
                        "threshold": {
                            "modelProbability": reentry_confirmation[
                                "requiredModelProbability"
                            ],
                            "conservativeEdge": reentry_confirmation[
                                "requiredConservativeEdge"
                            ],
                        },
                        "detail": (
                            "A filled same-ticker exit requires a stronger "
                            "signal before settlement."
                        ),
                    }]
                else:
                    entry_inputs_fresh = not bool(
                        set(
                            (decision.get("dataQuality") or {}).get(
                                "warnings"
                            )
                            or []
                        )
                        & KALSHI_EXECUTION_BLOCKING_WARNINGS
                    )
                    entry_confirmation = (
                        _entry_confirmation(
                            robot_state,
                            ticker,
                            decision_side,
                            decision,
                            strategy_config,
                        )
                        if entry_inputs_fresh
                        else {
                            "required": True,
                            "requiredSnapshots": int(
                                _finite_number(
                                    strategy_config.get(
                                        "entryConfirmationSnapshots"
                                    ),
                                    2.0,
                                )
                            ),
                            "streak": 0,
                            "confirmed": False,
                            "dataQualityEligible": False,
                        }
                    )
                    decision["entryConfirmation"] = entry_confirmation
                    if not entry_inputs_fresh:
                        # Let the existing fail-closed data-quality gate own
                        # the public intent and blocker; a stale frame must not
                        # advance durable entry confirmation.
                        can_route = True
                        decision["executionIntent"] = f"OPEN_{decision_side}"
                    elif (
                        entry_confirmation.get("required")
                        and not entry_confirmation.get("confirmed")
                    ):
                        intended_action = str(decision.get("action") or "")
                        decision["action"] = "WAIT"
                        decision["intendedAction"] = intended_action
                        decision["executionIntent"] = (
                            "WAIT_ENTRY_CONFIRMATION"
                        )
                        decision["blockingReasons"] = list(dict.fromkeys(
                            list(decision.get("blockingReasons") or [])
                            + ["entry_confirmation"]
                        ))
                        decision["gates"] = list(
                            decision.get("gates") or []
                        ) + [{
                            "category": "signal",
                            "name": "Consecutive entry confirmation",
                            "status": "block",
                            "value": entry_confirmation.get("streak"),
                            "threshold": entry_confirmation.get(
                                "requiredSnapshots"
                            ),
                            "detail": (
                                "A first entry must remain on the same ticker "
                                "and side across consecutive scheduler cycles."
                            ),
                        }]
                    else:
                        can_route = True
                        decision["executionIntent"] = f"OPEN_{decision_side}"
                        decision["gates"] = list(
                            decision.get("gates") or []
                        ) + [{
                            "category": "signal",
                            "name": "Consecutive entry confirmation",
                            "status": "pass",
                            "value": entry_confirmation.get("streak"),
                            "threshold": entry_confirmation.get(
                                "requiredSnapshots"
                            ),
                            "detail": (
                                "The entry thesis persisted on the same "
                                "ticker and side."
                            ),
                        }]
                    if reentry_confirmation["required"]:
                        decision["reentryConfirmation"] = (
                            reentry_confirmation
                        )
                        decision["positionManagement"] = {
                            "mode": "confirmed_reentry",
                            "recentExitAgeSeconds": (
                                reentry_confirmation[
                                    "recentExitAgeSeconds"
                                ]
                            ),
                        }
                        decision["gates"] = list(
                            decision.get("gates") or []
                        ) + [{
                            "category": "position",
                            "name": (
                                "Same-ticker re-entry confirmation"
                            ),
                            "status": "pass",
                            "value": {
                                "modelProbability": (
                                    reentry_confirmation[
                                        "modelProbability"
                                    ]
                                ),
                                "conservativeEdge": (
                                    reentry_confirmation[
                                        "conservativeEdge"
                                    ]
                                ),
                            },
                            "threshold": {
                                "modelProbability": (
                                    reentry_confirmation[
                                        "requiredModelProbability"
                                    ]
                                ),
                                "conservativeEdge": (
                                    reentry_confirmation[
                                        "requiredConservativeEdge"
                                    ]
                                ),
                            },
                            "detail": (
                                "The post-exit re-entry signal cleared both "
                                "durable confirmation thresholds."
                            ),
                        }]
        elif held_side and ticker:
            if account_context.get("hasOpenOrder"):
                decision["action"] = "WAIT"
                decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["close_order_pending"]
            elif (
                fillable_exit_count <= 0
                and (
                    exit_economics["emergencyExit"]
                    or exit_economics["protectiveExit"]
                )
            ):
                decision["action"] = "WAIT"
                decision["executionIntent"] = (
                    f"WAIT_{held_side}_EXIT_DEPTH"
                )
                decision["blockingReasons"] = list(dict.fromkeys(
                    list(decision.get("blockingReasons") or [])
                    + ["no_executable_close_depth"]
                ))
            elif (
                hold_age_seconds is not None
                and hold_age_seconds < minimum_hold_seconds
                and not exit_economics["emergencyLossExit"]
            ):
                decision["blockingReasons"] = list(decision.get("blockingReasons") or []) + ["minimum_hold_period"]
            elif (
                fillable_exit_count > 0
                and exit_net_per_contract is not None
                and (
                    economically_executable
                    or loss_exit_authorized
                )
            ):
                # Close the held outcome with a reduce-only sale. Buying the
                # complementary outcome is a hedge, not a close. A normal exit
                # requires a real fee-adjusted profit. A loss exit requires both
                # material model deterioration and a configured realized-loss
                # gate; an emergency can only bypass the minimum hold period.
                decision["action"] = f"SELL_{held_side}"
                decision["side"] = held_side
                decision["edge"] = {
                    **dict(decision.get("edge") or {}),
                    "side": held_side,
                    "price": _finite_number(sale_estimate.get("worstBid"), exit_net_per_contract),
                    "conservativeEdge": max(0.0, exit_value_edge),
                    "minimumConservativeEdge": 0.0,
                }
                decision["blockingReasons"] = []
                decision["executionIntent"] = f"CLOSE_{held_side}"
                exit_trigger = (
                    "emergency_stop_loss"
                    if exit_economics["emergencyLossExit"]
                    else "protective_stop_loss"
                    if exit_economics["protectiveLossExit"] and not economically_executable
                    else "fee_adjusted_take_profit"
                )
                decision["exitAnalysis"]["trigger"] = exit_trigger
                if exit_trigger == "fee_adjusted_take_profit" and fillable_exit_count > 1:
                    scale_out = max(
                        0.10,
                        min(1.0, _finite_number(strategy_config.get("takeProfitScaleOutPct"), 0.50)),
                    )
                    route_count_override = max(
                        0.01,
                        _contract_quantity(fillable_exit_count * scale_out),
                    )
                    decision["executionIntent"] = f"REDUCE_{held_side}_TAKE_PROFIT"
                    decision["positionManagement"] = {
                        "mode": "reduce",
                        "existingContracts": held_count,
                        "routedContracts": route_count_override,
                        "takeProfitScaleOutPct": scale_out,
                        "remainingIfFilled": _contract_quantity(
                            max(0.0, held_count - route_count_override)
                        ),
                    }
                else:
                    route_count_override = fillable_exit_count
                can_route = True
            else:
                decision["executionIntent"] = f"HOLD_{held_side}_TO_SETTLEMENT"
                decision["exitAnalysis"]["trigger"] = "hold_to_settlement"
        if execution_mode == "real" and unmanaged_position_count > 0:
            intended_action = str(decision.get("action") or "")
            can_route = False
            decision["action"] = "WAIT"
            decision["executionIntent"] = "WAIT_UNMANAGED_POSITION_CONFLICT"
            decision["blockingReasons"] = list(dict.fromkeys(
                list(decision.get("blockingReasons") or [])
                + ["unmanaged_position_conflict"]
            ))
            decision["account"] = {
                **dict(decision.get("account") or {}),
                "executionBlocked": True,
                "intendedAction": intended_action,
            }
            decision["gates"] = list(decision.get("gates") or []) + [{
                "category": "account",
                "name": "AlphaLab-managed position ownership",
                "status": "block",
                "value": unmanaged_position_count,
                "threshold": "0 unmanaged contracts in selected ticker",
                "detail": (
                    "The Kalshi account contains contracts that AlphaLab did not "
                    "open. They count toward risk but are never added to or sold "
                    "by the robot."
                ),
            }]
        execution_warnings = sorted(
            set((decision.get("dataQuality") or {}).get("warnings") or [])
            & KALSHI_EXECUTION_BLOCKING_WARNINGS
        )
        if can_route and execution_warnings:
            intended_action = str(decision.get("action") or "")
            can_route = False
            decision["action"] = "WAIT"
            decision["executionIntent"] = (
                f"HOLD_{held_side}_DATA_QUALITY"
                if held_side
                else "WAIT_DATA_QUALITY"
            )
            decision["blockingReasons"] = list(dict.fromkeys(
                list(decision.get("blockingReasons") or [])
                + ["market_data_not_fresh"]
            ))
            decision["dataQuality"] = {
                **dict(decision.get("dataQuality") or {}),
                "executionBlocked": True,
                "executionBlockingWarnings": execution_warnings,
                "intendedAction": intended_action,
            }
            decision["gates"] = list(decision.get("gates") or []) + [{
                "category": "data",
                "name": "Fresh execution data",
                "status": "block",
                "value": ", ".join(execution_warnings),
                "threshold": "no stale or unavailable execution inputs",
                "detail": (
                    "Order routing is paused until Kalshi market, orderbook, "
                    "reference, and history inputs are fresh."
                ),
            }]
        if can_route and str(decision.get("action") or "").startswith("SELL_"):
            if (decision.get("exitAnalysis") or {}).get("trigger") == "fee_adjusted_take_profit":
                # A scale-out consumes only its own slice of the bid ladder.
                # Retaining the full holding's deepest bid would needlessly
                # reject profitable shallow reductions or permit excess slip.
                planned_sale = _estimate_reduce_only_sale(
                    str(decision.get("side") or ""),
                    route_count_override if route_count_override is not None else fillable_exit_count,
                    snapshot.get("orderbook") or {},
                    taker_fee_rate=_finite_number(strategy_config.get("takerFeeRate"), 0.07),
                )
                if planned_sale["fullDepthAvailable"] and planned_sale["worstBid"] is not None:
                    decision["edge"]["price"] = planned_sale["worstBid"]
                decision["exitAnalysis"]["routeQuote"] = {
                    key: planned_sale.get(key) for key in (
                        "requestedCount", "fillableCount", "averageBid", "worstBid", "grossProceeds",
                        "estimatedExitFee", "estimatedExitTradeFee", "netProceeds", "takerFeeRate",
                    )
                }
            proposed_exit_payload = _paper_order_payload(
                decision, ticker, count_override=route_count_override,
                price_tolerance=_finite_number(strategy_config.get("executionPriceTolerance"), 0.01),
            )
            route_economics = _voluntary_exit_route_economics(
                decision, proposed_exit_payload or {}, strategy_config,
            )
            if route_economics["applicable"]:
                decision["exitAnalysis"]["routeEconomics"] = route_economics
                if not route_economics["allowed"]:
                    can_route = False
                    decision["action"] = "WAIT"
                    decision["executionIntent"] = f"HOLD_{held_side}_EXIT_ECONOMICS"
                    decision["blockingReasons"] = list(dict.fromkeys(
                        list(decision.get("blockingReasons") or []) + ["voluntary_exit_routing_economics"]
                    ))
                    decision["gates"] = list(decision.get("gates") or []) + [{
                        "category": "execution",
                        "name": "Fee-adjusted voluntary exit",
                        "label": "Fee-adjusted voluntary exit",
                        "labelZh": "扣费后主动止盈",
                        "status": "block",
                        "value": route_economics.get("netExitValuePerContract"),
                        "threshold": route_economics.get("requiredNetValuePerContract"),
                        "detail": "The actual scale-out size and IOC limit do not preserve the configured net profit and hold-value advantage.",
                    }]
        if execution_mode == "real" and _apply_real_shard_funding_gate(
            decision,
            account_context,
            price_tolerance=_finite_number(strategy_config.get("executionPriceTolerance"), 0.01),
            count_override=route_count_override,
        ):
            can_route = False
        if (
            execution_mode == "real"
            and route_count_override is not None
            and str(decision.get("action") or "").startswith("BUY_")
            and (decision.get("shardFunding") or {}).get("routedContracts") is not None
        ):
            route_count_override = min(route_count_override, decision["shardFunding"]["routedContracts"])
        if (
            submit_order
            and bool(robot_state.get("enabled"))
            and can_route
        ):
            order_payload = _paper_order_payload(
                decision,
                ticker,
                count_override=route_count_override,
                price_tolerance=_finite_number(strategy_config.get("executionPriceTolerance"), 0.01),
                client_order_id=_intent_client_order_id(
                    user_id,
                    execution_mode,
                    ticker,
                    str(decision.get("action") or ""),
                    str(decision.get("side") or ""),
                    held_count,
                ),
                exchange_index=(
                    (snapshot.get("market") or {}).get("exchange_index")
                ),
            )
            if order_payload:
                side = str(decision.get("side") or "").upper()
                is_close_order = str(decision.get("action") or "").startswith("SELL_")
                selected_price = _finite_number((decision.get("edge") or {}).get("price"), 0.0)
                available_depth = _finite_number(
                    ((decision.get("market") or {}).get("yesAskDepth") if side == "YES" else (decision.get("market") or {}).get("noAskDepth")),
                    _finite_number((decision.get("market") or {}).get("selectedDepth"), float(order_payload.get("count") or 0)),
                )
                if execution_mode == "real":
                    try:
                        order = self._submit_live_order(
                            user_id,
                            order_payload,
                            decision,
                        )
                    except Exception as exc:
                        if not isinstance(exc, KalshiApiError) or exc.code not in KALSHI_LIVE_ROUTING_STATE_CONFLICTS:
                            self._persist_routing_failure(user_id, decision, order_payload, exc)
                            raise
                        if getattr(exc, "kalshi_routing_failure", None):
                            decision["routingFailure"] = dict(exc.kalshi_routing_failure)
                        market_state_conflict = (
                            exc.code in KALSHI_LIVE_MARKET_STATE_CONFLICTS
                        )
                        # Final account state or the matching-engine market
                        # route can legitimately differ from the evaluation
                        # snapshot. Persist a fail-closed WAIT so the next
                        # cycle recalculates from fresh inputs instead of
                        # poisoning scheduler health. Account conflicts also
                        # refresh the portfolio immediately; market conflicts
                        # avoid that unrelated extra account traffic.
                        if not market_state_conflict:
                            try:
                                portfolio = self.portfolio(
                                    user_id,
                                    mode=execution_mode,
                                    mutate=True,
                                )
                                refreshed_context = _paper_account_context(
                                    portfolio,
                                    robot_state,
                                    ticker,
                                    bankroll,
                                    exchange_index=(snapshot.get("market") or {}).get("exchange_index"),
                                    event_ticker=(
                                        str(snapshot.get("eventTicker") or "")
                                        if family == "btchourly"
                                        else None
                                    ),
                                )
                                decision["account"] = {
                                    **dict(decision.get("account") or {}),
                                    **{
                                        key: refreshed_context.get(key) for key in (
                                            "exchangeIndex", "aggregateCashAvailable",
                                            "shardCashAvailable", "shardCashKnown", "fundingStatus",
                                        )
                                    },
                                    "cashAvailable": refreshed_context.get(
                                        "cashAvailable"
                                    ),
                                    "portfolioExposure": refreshed_context.get(
                                        "portfolioExposure"
                                    ),
                                    "currentMarketExposure": refreshed_context.get(
                                        "currentMarketExposure"
                                    ),
                                    "currentTickerExposure": refreshed_context.get(
                                        "currentTickerExposure"
                                    ),
                                    "currentEventExposure": refreshed_context.get(
                                        "currentEventExposure"
                                    ),
                                    "hasOpenOrder": refreshed_context.get(
                                        "hasOpenOrder"
                                    ),
                                    "openOrderTickers": refreshed_context.get(
                                        "openOrderTickers"
                                    ),
                                }
                            except Exception as refresh_exc:
                                self.safe_print(
                                    "[KalshiReal] conflict portfolio refresh failed "
                                    f"user={user_id} "
                                    f"error={type(refresh_exc).__name__}"
                                )
                        intended_action = str(
                            decision.get("action") or ""
                        )
                        decision["action"] = "WAIT"
                        decision["executionIntent"] = (
                            "WAIT_LIVE_MARKET_REFRESH"
                            if market_state_conflict
                            else "WAIT_LIVE_SHARD_FUNDING"
                            if exc.code.startswith("kalshi_live_shard_cash_")
                            else "WAIT_LIVE_ACCOUNT_REFRESH"
                        )
                        decision["blockingReasons"] = list(dict.fromkeys(
                            list(decision.get("blockingReasons") or [])
                            + [exc.code]
                        ))
                        conflict_section = (
                            "dataQuality"
                            if market_state_conflict
                            else "account"
                        )
                        decision[conflict_section] = {
                            **dict(decision.get(conflict_section) or {}),
                            "executionBlocked": True,
                            "intendedAction": intended_action,
                            "preflightConflict": exc.code,
                        }
                        decision["gates"] = list(
                            decision.get("gates") or []
                        ) + [{
                            "category": (
                                "market"
                                if market_state_conflict
                                else "account"
                            ),
                            "name": (
                                "Final Real market routing"
                                if market_state_conflict
                                else "Final Real account reconciliation"
                            ),
                            "status": "block",
                            "value": exc.code,
                            "threshold": (
                                "selected ticker is routable on its active exchange"
                                if market_state_conflict
                                else "evaluation and final account state agree"
                            ),
                            "detail": str(exc),
                        }]
                elif is_close_order:
                    order = self.paper_accounts.submit_close(
                        user_id,
                        ticker=ticker,
                        side=side,
                        price=selected_price,
                        contracts=_contract_quantity(order_payload["count"]),
                        limit_price=_finite_number(order_payload.get("user_side_limit_price"), selected_price),
                        orderbook=snapshot.get("orderbook") or {},
                        client_order_id=str(order_payload["client_order_id"]),
                    )
                else:
                    order = self.paper_accounts.submit_taker(
                        user_id,
                        ticker=ticker,
                        side=side,
                        price=selected_price,
                        contracts=_contract_quantity(order_payload["count"]),
                        available_depth=available_depth,
                        limit_price=_finite_number(order_payload.get("user_side_limit_price"), selected_price),
                        orderbook=snapshot.get("orderbook") or {},
                        client_order_id=str(order_payload["client_order_id"]),
                        market=snapshot.get("market") or {},
                    )
                if order and execution_mode != "real":
                    self._notify_order(user_id, order, decision)
        # Only the lease-owning execution cycle mutates durable robot state.
        # Browser refreshes still persist their compact research observation
        # below, but must not race the online scheduler or overwrite its
        # enabled flag, decision history, and fill guards from another process.
        state = (
            self.state.record(user_id, decision, order)
            if submit_order
            else robot_state
        )
        observation = _market_observation(
            environment,
            decision,
            order,
            source=(
                "scheduler" if submit_order else "browser_read_only"
            ),
            submit_order=submit_order,
        )
        if observation and callable(self.observation_saver):
            try:
                self.observation_saver(user_id, observation)
            except Exception as exc:
                self.safe_print(
                    f"[KalshiRobot] observation persistence failed "
                    f"user={user_id} ticker={observation.get('ticker')} "
                    f"error={type(exc).__name__}"
                )
        if order and str(decision.get("action") or "").startswith("SELL_"):
            state = self.state.record_early_close(
                user_id,
                decision,
                order,
                environment=environment,
            )
        if order:
            # The initial portfolio was read before the IOC order. Refresh after
            # submission so the UI can immediately show filled positions, fills,
            # and any rejected/unfilled order status.
            try:
                portfolio = self.portfolio(user_id, mode=execution_mode, mutate=True)
            except Exception as exc:
                self.safe_print(f"[KalshiPaper] post-order portfolio refresh failed user={user_id} error={type(exc).__name__}")
        clean_snapshot = dict(snapshot)
        clean_snapshot["reference"] = dict(snapshot["reference"])
        clean_snapshot["reference"].pop("candles", None)
        response_portfolio = self._apply_portfolio_display(
            user_id,
            portfolio,
            execution_mode,
        )
        return {
            "portfolio": response_portfolio,
            "state": state,
            "snapshot": clean_snapshot,
            "decision": decision,
            "order": order,
            "orderSubmitted": bool(order),
            "orderFilled": _order_fill_count(order) > 0,
        }

    def _notify(self, user_id: str, event_type: str, payload: Mapping[str, Any]) -> None:
        if not callable(self.notifier):
            return
        try:
            self.notifier(user_id, event_type, dict(payload or {}))
        except Exception as exc:
            self.safe_print(f"[KalshiPaper] discord notify failed user={user_id} event={event_type} error={type(exc).__name__}")

    def _notify_order(self, user_id: str, order: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
        mode = _execution_mode(order.get("environment") or (decision.get("config") or {}).get("executionMode") or "paper")
        source = "Kalshi Real Robot" if mode == "real" else "Kalshi Paper Robot"
        status = str(order.get("status") or "").lower()
        filled = _contract_quantity(order.get("fill_count_fp"))
        requested = _contract_quantity(order.get("count_fp"))
        filled_label = f"{filled:.2f}".rstrip("0").rstrip(".")
        requested_label = f"{requested:.2f}".rstrip("0").rstrip(".")
        symbol = str(order.get("ticker") or "")
        side = str(order.get("outcome_side") or "").upper()
        avg_price = _finite_number(order.get("average_price_dollars"), None)
        limit_price = _finite_number(order.get("limit_price_dollars"), None)
        fee = _finite_number(order.get("fee_cost_dollars"), 0.0)
        action_name = "SELL" if bool(order.get("reduce_only")) or str(order.get("action") or "").upper() == "SELL" else "BUY"
        action_zh = "卖出减仓" if action_name == "SELL" else "买入"
        payload = {
            "source": source,
            "notificationScope": "kalshi",
            "assetClass": "kalshi",
            "event_id": order.get("order_id") or order.get("client_order_id"),
            "mode": mode,
            "symbol": symbol,
            "side": action_name,
            "action": f"{action_name} {side}".strip(),
            "qty": f"{filled_label} / {requested_label} contracts",
            "orderType": "IOC limit",
            "price": f"{avg_price * 100:.1f}c avg" if avg_price is not None else None,
            "limitPrice": f"{limit_price * 100:.1f}c limit" if limit_price is not None else None,
            "status": "filled" if status in {"filled", "partially_filled"} else status,
            "orderId": order.get("order_id"),
            "description": f"{source} {action_name.lower()} {status.replace('_', ' ')} {filled_label}/{requested_label} {side} on {symbol}.",
            "descriptionZh": f"Kalshi {'实盘' if mode == 'real' else '模拟盘'}{action_zh}{status.replace('_', ' ')}：{symbol} {side} 成交 {filled}/{requested} 张。",
            "reason": (
                f"Intent {decision.get('executionIntent') or decision.get('action')}; "
                f"fee ${fee:.4f}; slippage {(float(order.get('slippage_dollars') or 0.0) * 100):.1f}c."
            ),
            "reasonZh": (
                f"意图 {decision.get('executionIntent') or decision.get('action')}；"
                f"手续费 ${fee:.4f}；滑点 {(float(order.get('slippage_dollars') or 0.0) * 100):.1f}c。"
            ),
        }
        self._notify(user_id, "order", payload)

    def _notify_settlement(self, user_id: str, settlement: Mapping[str, Any]) -> None:
        ticker = str(settlement.get("ticker") or "")
        result = str(settlement.get("result") or settlement.get("market_result") or "").upper()
        environment = _execution_mode(settlement.get("environment") or "paper")
        revenue = _finite_number(
            settlement.get("revenue") if settlement.get("revenue") is not None else settlement.get("revenue_dollars"),
            0.0,
        )
        yes_cost = _finite_number(settlement.get("yes_total_cost_dollars"), 0.0)
        no_cost = _finite_number(settlement.get("no_total_cost_dollars"), 0.0)
        cost = _finite_number(settlement.get("cost"), yes_cost + no_cost)
        fees = _finite_number(
            settlement.get("fees"),
            _finite_number(settlement.get("fee_cost_dollars"), 0.0)
            + _finite_number(settlement.get("settlement_fee_dollars"), 0.0),
        )
        raw_pnl = settlement.get("pnl")
        if raw_pnl is None:
            raw_pnl = settlement.get("pnl_dollars")
        pnl = _finite_number(raw_pnl, revenue - cost - fees)
        side = str(settlement.get("side") or "").upper()
        yes_count = _finite_number(
            _first_present(settlement, "yes_count_fp", "yes_count"), 0.0
        )
        no_count = _finite_number(
            _first_present(settlement, "no_count_fp", "no_count"), 0.0
        )
        if side not in {"YES", "NO"}:
            side = "YES" if yes_count > 0 else "NO" if no_count > 0 else ""
        contracts = _finite_number(
            settlement.get("contracts"),
            yes_count if side == "YES" else no_count if side == "NO" else yes_count + no_count,
        )
        settled_at = (
            settlement.get("settledAt")
            or settlement.get("settled_time")
            or settlement.get("created_time")
        )
        source = "Kalshi Real Settlement" if environment == "real" else "Kalshi Paper Settlement"
        payload = {
            "source": source,
            "notificationScope": "kalshi",
            "assetClass": "kalshi",
            "event_id": settlement.get("key") or settlement.get("settlement_id") or f"{environment}:{ticker}:{settled_at}:{result}",
            "mode": environment,
            "symbol": ticker,
            "result": result,
            "outcome": side,
            "contracts": contracts,
            "revenue": revenue,
            "cost": cost,
            "fees": fees,
            "pnl": pnl,
            "settledAt": settled_at,
            "description": f"{source}: {ticker} resolved {result}; net P/L ${pnl:.4f}.",
            "descriptionZh": f"Kalshi {'实盘' if environment == 'real' else '模拟盘'}结算：{ticker} 结果 {result}，净盈亏 ${pnl:.4f}。",
        }
        self._notify(user_id, "settlement", payload)

    def _record_loop_success(self, user_id: str, family: str, mode: str) -> None:
        key = f"{user_id}:{family}"
        market_standby = getattr(self, "_market_standby", None)
        runtime_lock = getattr(self, "_runtime_lock", None)
        if runtime_lock is None:
            self._loop_last_error = ""
            if isinstance(market_standby, dict):
                market_standby.pop(key, None)
        else:
            with runtime_lock:
                self._loop_last_error = ""
                if isinstance(market_standby, dict):
                    market_standby.pop(key, None)
        previous = self._loop_error_counts.pop(key, 0)
        if key not in self._loop_alerted:
            return
        self._loop_alerted.discard(key)
        self._notify(
            user_id,
            "lifecycle",
            {
                "source": "Kalshi Robot",
                "notificationScope": "kalshi",
                "assetClass": "kalshi",
                "event_id": f"kalshi-recovered:{family}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
                "component": "BTC Hourly Robot" if family == "btchourly" else "BTC 15-Minute Robot",
                "state": "recovered",
                "mode": mode,
                "detail": f"Background cycles recovered after {previous} consecutive failures.",
                "detailZh": f"后台周期已恢复，此前连续失败 {previous} 次。",
            },
        )

    def _record_loop_standby(
        self,
        user_id: str,
        family: str,
        exc: KalshiApiError,
    ) -> None:
        """Record an expected market-window gap without raising an incident."""
        key = f"{user_id}:{family}"
        self._loop_error_counts.pop(key, None)
        self._loop_alerted.discard(key)
        standby = {
            "family": family,
            "reason": exc.code,
            "since": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        runtime_lock = getattr(self, "_runtime_lock", None)
        if runtime_lock is None:
            self._market_standby[key] = standby
            if not self._loop_error_counts:
                self._loop_last_error = ""
        else:
            with runtime_lock:
                self._market_standby[key] = standby
                if not self._loop_error_counts:
                    self._loop_last_error = ""
        self.safe_print(
            f"[KalshiRobot] {family} standby reason={exc.code}"
        )

    def _record_loop_failure(self, user_id: str, family: str, mode: str, exc: Exception) -> None:
        if (
            family == "btchourly"
            and isinstance(exc, KalshiApiError)
            and exc.code in KALSHI_HOURLY_STANDBY_CODES
        ):
            self._record_loop_standby(user_id, family, exc)
            return
        key = f"{user_id}:{family}"
        market_standby = getattr(self, "_market_standby", None)
        runtime_lock = getattr(self, "_runtime_lock", None)
        if runtime_lock is None:
            self._loop_last_error = type(exc).__name__
            if isinstance(market_standby, dict):
                market_standby.pop(key, None)
        else:
            with runtime_lock:
                self._loop_last_error = type(exc).__name__
                if isinstance(market_standby, dict):
                    market_standby.pop(key, None)
        count = int(self._loop_error_counts.get(key, 0)) + 1
        self._loop_error_counts[key] = count
        error_type = type(exc).__name__
        error_code = (
            str(exc.code)
            if isinstance(exc, KalshiApiError)
            else error_type
        )
        error_status = (
            int(exc.status)
            if isinstance(exc, KalshiApiError)
            else None
        )
        error_endpoint = (
            str(exc.endpoint or "")
            if isinstance(exc, KalshiApiError)
            else ""
        )
        error_message = str(exc).strip()[:180]
        error_summary = (
            f"{error_type}:{error_code}"
            f"{f' status={error_status}' if error_status is not None else ''}"
            f"{f' endpoint={error_endpoint}' if error_endpoint else ''}"
            f"{f' message={error_message}' if error_message else ''}"
        )
        is_version_conflict = error_type == "OperationsVersionConflict"
        if runtime_lock is None:
            self._loop_last_error = error_summary
        else:
            with runtime_lock:
                self._loop_last_error = error_summary
        self.safe_print(
            f"[KalshiRobot] {family} tick failed user={user_id} "
            f"error={error_summary} consecutive={count}"
        )
        if not is_version_conflict:
            try:
                self.state.error(
                    user_id,
                    f"{error_summary}: background cycle failed",
                )
            except Exception as state_exc:
                self.safe_print(
                    f"[KalshiRobot] state error record skipped user={user_id} "
                    f"error={type(state_exc).__name__}"
                )
        if count < 3 or key in self._loop_alerted:
            return

        self._loop_alerted.add(key)
        if is_version_conflict:
            reason = "State changed on another backend instance; AlphaLab reloaded it and will retry."
            reason_zh = "状态已被另一后端实例更新；AlphaLab 已重新读取，并将在下一周期重试。"
            severity = "medium"
        else:
            error_detail = error_code
            if error_status is not None:
                error_detail += f", HTTP {error_status}"
            if error_endpoint:
                error_detail += f", {error_endpoint}"
            if error_message:
                error_detail += f", {error_message}"
            reason = (
                f"{family} background cycle failed {count} consecutive times "
                f"({error_detail})."
            )
            reason_zh = (
                f"{'BTC 小时' if family == 'btchourly' else 'BTC 15 分钟'}"
                f"后台周期已连续失败 {count} 次（{error_detail}）。"
            )
            severity = "high"
        self._notify(
            user_id,
            "risk_alert",
            {
                "source": "Kalshi Robot",
                "notificationScope": "kalshi",
                "assetClass": "kalshi",
                "event_id": f"kalshi-loop:{family}:{error_code}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
                "fingerprint": f"kalshi:{family}:{error_code}",
                "symbol": BTC_HOURLY_SERIES if family == "btchourly" else BTC_15M_SERIES,
                "step": "Kalshi Hourly Robot" if family == "btchourly" else "Kalshi BTC15 Robot",
                "status": "attention",
                "severity": severity,
                "reason": reason,
                "reasonZh": reason_zh,
                "errorType": error_type,
                "errorCode": error_code,
                "httpStatus": error_status,
                "endpoint": error_endpoint or None,
                "errorMessage": error_message or None,
                "action": "The robot remains fail-closed and will keep retrying. Review backend health if it does not recover.",
                "actionZh": "机器人保持安全关闭并继续重试；若未自动恢复，请检查后端健康状态。",
                "mode": mode,
            },
        )

    def _loop(self, stop_event: Optional[threading.Event] = None):
        active_stop = stop_event or self._stop_event
        while not active_stop.wait(5.0):
            with self._runtime_lock:
                self._loop_last_heartbeat_monotonic = time.monotonic()
                self._loop_last_heartbeat_at = datetime.now(timezone.utc).isoformat()
            if callable(self.scheduler_lease_acquirer):
                try:
                    owns_lease = bool(self.scheduler_lease_acquirer())
                    with self._runtime_lock:
                        self._scheduler_lease_owned = owns_lease
                        self._scheduler_lease_checked_at = (
                            datetime.now(timezone.utc).isoformat()
                        )
                    if not owns_lease:
                        continue
                except Exception as exc:
                    with self._runtime_lock:
                        self._scheduler_lease_owned = False
                        self._scheduler_lease_checked_at = (
                            datetime.now(timezone.utc).isoformat()
                        )
                        self._loop_last_error = type(exc).__name__
                    self.safe_print(
                        f"[KalshiRobot] scheduler lease unavailable "
                        f"error={type(exc).__name__}"
                    )
                    continue
            try:
                enabled_users = self.state.enabled_users()
                with self._runtime_lock:
                    self._enabled_user_count = len(enabled_users)
                    if not self._loop_error_counts:
                        self._loop_last_error = ""
            except Exception as exc:
                with self._runtime_lock:
                    self._loop_last_error = type(exc).__name__
                self.safe_print(
                    f"[KalshiRobot] enabled-user discovery failed error={type(exc).__name__}"
                )
                continue
            for user_id in enabled_users:
                mode = "paper"
                try:
                    state = self.state.get(user_id)
                    mode = _execution_mode((state.get("config") or {}).get("executionMode"))
                    user_key = str(user_id)

                    def run_hourly_cycle():
                        next_hourly_tick_base = time.monotonic()
                        result = None
                        try:
                            result = self.tick(
                                user_id,
                                submit_order=True,
                                mode=mode,
                                family="btchourly",
                            )
                            self._record_loop_success(
                                user_id,
                                "btchourly",
                                mode,
                            )
                        except Exception as exc:
                            self._record_loop_failure(
                                user_id,
                                "btchourly",
                                mode,
                                exc,
                            )
                            if (
                                isinstance(exc, KalshiApiError)
                                and exc.code == KALSHI_PUBLIC_RATE_LIMITED
                            ):
                                next_hourly_tick_base += (
                                    KALSHI_HOURLY_RATE_LIMIT_BACKOFF_SECONDS
                                    - KALSHI_HOURLY_LOOP_INTERVAL_SECONDS
                                )
                        finally:
                            self._last_hourly_tick[user_key] = (
                                next_hourly_tick_base
                            )
                        return result

                    # An hourly first frame from the previous loop is evaluated
                    # before routine work so the second frame can be genuinely
                    # fresh and still land inside the unchanged 25-second gate.
                    hourly_ran = False
                    if self._hourly_confirmation_followups.pop(
                        user_key,
                        None,
                    ):
                        run_hourly_cycle()
                        hourly_ran = True

                    btc15_result = self.tick(
                        user_id,
                        submit_order=True,
                        mode=mode,
                        family="btc15m",
                    )
                    self._record_loop_success(user_id, "btc15m", mode)
                    btc15_signature = (
                        _pending_entry_confirmation_signature(
                            btc15_result,
                            "btc15m",
                        )
                    )
                    # Defer the slower hourly ladder exactly once for a new
                    # BTC15 ticker/side first frame. If that same signal still
                    # cannot confirm on the next cycle, hourly resumes instead
                    # of being starved indefinitely.
                    btc15_defer_hourly = bool(
                        btc15_signature
                        and self._btc15_confirmation_deferrals.get(user_key)
                        != btc15_signature
                    )
                    if btc15_signature:
                        self._btc15_confirmation_deferrals[user_key] = (
                            btc15_signature
                        )
                    else:
                        self._btc15_confirmation_deferrals.pop(
                            user_key,
                            None,
                        )
                    now_monotonic = time.monotonic()
                    if (
                        not hourly_ran
                        and not btc15_defer_hourly
                        and now_monotonic
                        - self._last_hourly_tick.get(user_key, 0.0)
                        >= KALSHI_HOURLY_LOOP_INTERVAL_SECONDS
                    ):
                        hourly_result = run_hourly_cycle()
                        hourly_signature = (
                            _pending_entry_confirmation_signature(
                                hourly_result or {},
                                "btchourly",
                            )
                        )
                        if hourly_signature:
                            self._hourly_confirmation_followups[
                                user_key
                            ] = hourly_signature
                except Exception as exc:
                    self._record_loop_failure(user_id, "btc15m", mode, exc)

    def runtime_snapshot(self) -> Dict[str, Any]:
        with self._lifecycle_lock:
            thread_alive = bool(self._thread and self._thread.is_alive())
            background_requested = self._background_requested
        with self._runtime_lock:
            heartbeat_mono = self._loop_last_heartbeat_monotonic
            heartbeat_at = self._loop_last_heartbeat_at
            last_error = self._loop_last_error
            lease_owned = self._scheduler_lease_owned
            lease_checked_at = self._scheduler_lease_checked_at
            enabled_user_count = self._enabled_user_count
            market_standby = list(self._market_standby.values())
        public_data = (
            self.client.runtime_snapshot()
            if callable(getattr(self.client, "runtime_snapshot", None))
            else {"healthy": True, "status": "unknown"}
        )
        heartbeat_age = max(0.0, time.monotonic() - heartbeat_mono)
        required = bool(background_requested and not self._scheduler_disabled)
        public_data_required = bool(
            required
            and lease_owned is not False
            and enabled_user_count != 0
        )
        healthy = bool(
            (not required)
            or (
                thread_alive
                and heartbeat_age <= 30
                and not last_error
                and (
                    not public_data_required
                    or public_data.get("healthy") is not False
                )
            )
        )
        return {
            "required": required,
            "healthy": healthy,
            "status": (
                "disabled" if self._scheduler_disabled else
                "standby" if healthy and lease_owned is False else
                "healthy" if healthy else
                "degraded"
            ),
            "threadAlive": thread_alive,
            "startedAt": self._loop_started_at,
            "lastHeartbeatAt": heartbeat_at,
            "heartbeatAgeSeconds": round(heartbeat_age, 3),
            "lastError": last_error or public_data.get("lastError"),
            "schedulerLeaseOwned": lease_owned,
            "schedulerLeaseCheckedAt": lease_checked_at,
            "enabledUserCount": enabled_user_count,
            "publicDataRequired": public_data_required,
            "publicData": public_data,
            "marketStandby": {
                "active": bool(market_standby),
                "families": dict(Counter(
                    row.get("family") or "unknown"
                    for row in market_standby
                )),
                "reasons": sorted({
                    row.get("reason") or "unknown"
                    for row in market_standby
                }),
                "latestAt": max(
                    (row.get("since") or "" for row in market_standby),
                    default=None,
                ),
            },
            "routingFencingSupported": bool(
                callable(getattr(self.worker_lease_store, "claim_worker_lease_fenced", None))
                and callable(getattr(self.worker_lease_store, "renew_worker_lease", None))
                and callable(getattr(self.worker_lease_store, "release_worker_lease", None))
            ),
        }



def register_kalshi_api(
    app,
    *,
    require_auth,
    safe_print=print,
    http_get=None,
    get_user_config=None,
    authoritative_config_loader=None,
    save_user_config=None,
    mask_key=None,
    robot_state_path=None,
    paper_account_path=None,
    start_background=False,
    http_request=None,
    notifier=None,
    robot_state_loader=None,
    robot_state_saver=None,
    enabled_users_loader=None,
    paper_account_loader=None,
    paper_account_saver=None,
    portfolio_display_loader=None,
    portfolio_display_saver=None,
    observation_saver=None,
    observation_loader=None,
    scheduler_lease_acquirer=None,
    worker_lease_store=None,
    audit_recorder=None,
):
    """Register Kalshi research and per-user connection APIs once per app."""
    existing = app.extensions.get("alphalab_kalshi_api")
    if existing:
        return existing

    client = _PublicDataClient(http_get=http_get, safe_print=safe_print)
    blueprint = Blueprint("kalshi_api", __name__)

    def authenticated_user():
        user = require_auth()
        if not isinstance(user, Mapping) or not str(user.get("id") or "").strip():
            raise KalshiApiError("Authentication required", status=401, code="authentication_required")
        return dict(user)

    def ok(payload: Mapping[str, Any], status: int = 200):
        return jsonify(dict(payload)), status

    def fail(exc: Exception):
        if isinstance(exc, KalshiApiError):
            return ok({"success": False, "code": exc.code, "message": str(exc)}, exc.status)
        safe_print(f"[KalshiAPI] unexpected error={type(exc).__name__}")
        return ok({
            "success": False,
            "code": "kalshi_internal_error",
            "message": "Kalshi research request failed safely.",
        }, 500)

    def configuration_available():
        return callable(get_user_config) and callable(save_user_config)

    def record_robot_control_audit(user_id, body, previous, state, mode):
        if not callable(audit_recorder):
            return
        context = body.get("controlContext") or {}
        if not isinstance(context, Mapping):
            context = {}
        source = str(context.get("source") or "api").strip()
        if source not in {"api", "kalshi-workspace-toggle", "shell-mode-switch"}:
            source = "api"
        session_id = str(context.get("sessionId") or "").strip()[:80]
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", session_id):
            session_id = ""
        page = str(context.get("page") or "").strip().split("?", 1)[0][:160]
        if not page.startswith("/"):
            page = ""
        referrer_path = ""
        try:
            referrer_path = urlsplit(str(request.referrer or "")).path[:160]
        except ValueError:
            referrer_path = ""
        user_agent_hash = hashlib.sha256(
            str(request.user_agent.string or "").encode("utf-8")
        ).hexdigest()[:16]
        requested_enabled = bool(body.get("enabled"))
        actual_enabled = bool(state.get("enabled"))
        occurred_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            audit_recorder(
                user_id,
                "kalshi_robot_control",
                f"kalshi-control:{user_id}:{time.time_ns()}",
                actor="user",
                source=f"kalshi-control:{source}",
                resource_type="kalshi_robot",
                resource_id=mode,
                payload={
                    "occurredAt": occurred_at,
                    "requestedEnabled": requested_enabled,
                    "previousEnabled": bool(previous.get("enabled")),
                    "actualEnabled": actual_enabled,
                    "changed": bool(previous.get("enabled")) != actual_enabled,
                    "mode": mode,
                    "controlSource": source,
                    "clientSessionId": session_id,
                    "page": page,
                    "referrerPath": referrer_path,
                    "userAgentHash": user_agent_hash,
                },
            )
        except Exception as exc:
            safe_print(
                f"[KalshiAPI] control audit skipped error={type(exc).__name__}"
            )

    connection_cache: Dict[str, Dict[str, Any]] = {}
    connection_cache_lock = threading.RLock()

    def remember_connection(user_id: str, config: Mapping[str, Any]):
        with connection_cache_lock:
            connection_cache[user_id] = dict(config or {})

    def load_connection(user_id: str) -> Dict[str, Any]:
        if not configuration_available():
            return {}
        config = dict(get_user_config(user_id, "kalshi") or {})
        if config:
            remember_connection(user_id, config)
            return config
        with connection_cache_lock:
            cached = connection_cache.get(user_id)
        if cached:
            safe_print(f"[Kalshi] using cached connection config for user={user_id[:8]}...")
            return dict(cached)
        return {}

    def load_authoritative_connection(user_id: str) -> Dict[str, Any]:
        """Read the durable credential record without the fallback cache."""
        if not callable(authoritative_config_loader):
            raise KalshiApiError(
                "Authoritative credential storage is unavailable",
                status=503,
                code="kalshi_authoritative_credentials_unavailable",
            )
        raw = authoritative_config_loader(user_id, "kalshi")
        return dict(raw or {}) if isinstance(raw, Mapping) else {}

    def request_mode(default: str = "paper") -> str:
        body = request.get_json(silent=True) if request.method in {"POST", "PUT", "PATCH", "DELETE"} else None
        if isinstance(body, Mapping):
            config = body.get("config")
            if body.get("mode") is not None:
                return _execution_mode(body.get("mode"))
            if isinstance(config, Mapping) and config.get("executionMode") is not None:
                return _execution_mode(config.get("executionMode"))
        return _execution_mode(request.args.get("mode") or default)

    def ensure_real_ready(user_id: str, mode: str) -> None:
        if _execution_mode(mode) != "real":
            return
        # Real arming/configuration must never trust this worker's TTL cache:
        # another worker may have deleted or rotated credentials before this
        # routing generation acquired the fence.
        config = load_authoritative_connection(user_id)
        if not environment_summary(config, "production")["configured"]:
            raise KalshiApiError(
                "Kalshi Real mode needs a production API key and private key in Settings before the robot can trade.",
                status=409,
                code="kalshi_real_credentials_missing",
            )

    def environment_summary(config: Mapping[str, Any], environment: str):
        key_field, private_field = _credential_fields(environment)
        key_id = str(config.get(key_field) or "")
        private_key = str(config.get(private_field) or "")
        masker = mask_key if callable(mask_key) else (lambda value: "********" if value else "")
        return {
            "configured": bool(key_id and private_key),
            "apiKeyIdMasked": masker(key_id),
            "privateKeySaved": bool(private_key),
            "baseUrl": KALSHI_ENVIRONMENTS[environment],
            "testStatus": config.get(f"{environment}_test_status", "not_tested"),
            "lastTestedAt": config.get(f"{environment}_last_tested_at"),
        }

    def signed_account_check(config: Mapping[str, Any], environment: str):
        key_field, private_field = _credential_fields(environment)
        key_id = str(config.get(key_field) or "").strip()
        private_key = str(config.get(private_field) or "").strip()
        if not key_id or not private_key:
            raise KalshiApiError(
                f"Kalshi {environment} credentials are not configured",
                status=400,
                code="credentials_not_configured",
            )
        path = "/trade-api/v2/portfolio/balance"
        try:
            response = (http_get or requests.get)(
                KALSHI_ENVIRONMENTS[environment] + "/portfolio/balance",
                headers=_signed_headers(key_id, private_key, "GET", path),
                timeout=10.0,
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            payload = response.json() if hasattr(response, "json") else response
        except KalshiApiError:
            raise
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in (401, 403):
                raise KalshiApiError(
                    "Kalshi rejected the API Key ID or signature",
                    status=400,
                    code="kalshi_auth_rejected",
                ) from exc
            raise KalshiApiError(
                "Kalshi connection test could not reach the account endpoint",
                status=502,
                code="kalshi_connection_failed",
            ) from exc
        return payload if isinstance(payload, Mapping) else {}

    def signed_api_request(
        config: Mapping[str, Any],
        environment: str,
        method: str,
        endpoint: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        environment = _environment_name(environment)
        key_field, private_field = _credential_fields(environment)
        key_id = str(config.get(key_field) or "").strip()
        private_key = str(config.get(private_field) or "").strip()
        if not key_id or not private_key:
            raise KalshiApiError(
                f"Kalshi {environment} credentials are not configured",
                status=409,
                code="credentials_not_configured",
            )
        endpoint = "/" + str(endpoint or "").lstrip("/")
        sign_path = "/trade-api/v2" + endpoint
        headers = _signed_headers(key_id, private_key, method, sign_path)
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        transport = http_request or requests.request
        request_method = str(method).upper()
        max_attempts = 2 if request_method == "GET" else 1
        for attempt in range(max_attempts):
            response = None
            try:
                response = transport(
                    request_method,
                    KALSHI_ENVIRONMENTS[environment] + endpoint,
                    params=dict(params or {}),
                    json=dict(json_body) if json_body is not None else None,
                    headers=headers,
                    timeout=12.0,
                )
                if hasattr(response, "raise_for_status"):
                    response.raise_for_status()
                payload = response.json() if hasattr(response, "json") else response
                return dict(payload or {}) if isinstance(payload, Mapping) else {}
            except Exception as exc:
                status_code = getattr(response, "status_code", None)
                retryable = bool(
                    request_method == "GET"
                    and attempt + 1 < max_attempts
                    and (
                        status_code is None
                        or status_code == 429
                        or int(status_code) >= 500
                    )
                )
                if retryable:
                    retry_after = 0.25 * (attempt + 1)
                    try:
                        retry_after = float(
                            (getattr(response, "headers", {}) or {}).get(
                                "Retry-After",
                                retry_after,
                            )
                        )
                    except (TypeError, ValueError):
                        retry_after = 0.25 * (attempt + 1)
                    retry_after = max(0.05, min(retry_after, 2.0))
                    safe_print(
                        f"[KalshiReal] retrying signed GET endpoint={endpoint} "
                        f"status={status_code or 'transport'} "
                        f"attempt={attempt + 1}/{max_attempts}"
                    )
                    time.sleep(retry_after)
                    continue
                if status_code in (401, 403):
                    raise KalshiApiError(
                        f"Kalshi {environment} rejected the API credentials",
                        status=401,
                        code="kalshi_auth_rejected",
                        endpoint=endpoint,
                    ) from exc
                if status_code == 429:
                    raise KalshiApiError(
                        f"Kalshi {environment} rate limit reached; the robot will retry",
                        status=429,
                        code="kalshi_rate_limited",
                        endpoint=endpoint,
                    ) from exc
                detail = _kalshi_response_error_detail(response)
                remote_code = _kalshi_response_error_code(response)
                live_market_code = {
                    "market_not_found": "kalshi_market_not_found",
                    "market_inactive": "kalshi_market_inactive",
                    "market_already_closed": "kalshi_market_already_closed",
                }.get(remote_code)
                if (
                    request_method == "POST"
                    and endpoint == "/portfolio/events/orders"
                    and live_market_code
                ):
                    raise KalshiApiError(
                        detail or remote_code,
                        status=int(status_code) if status_code else 409,
                        code=live_market_code,
                        endpoint=endpoint,
                    ) from exc
                raise KalshiApiError(
                    detail or f"Kalshi {environment} account request failed",
                    status=int(status_code) if status_code else 502,
                    code="kalshi_account_request_failed",
                    endpoint=endpoint,
                ) from exc
        raise KalshiApiError(
            f"Kalshi {environment} account request failed",
            status=502,
            code="kalshi_account_request_failed",
            endpoint=endpoint,
        )

    scheduler_disabled = str(
        os.environ.get("ALPHALAB_DISABLE_KALSHI_SCHEDULER") or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    reference_stream = KalshiReferenceStream(
        connection_loader=load_connection,
        header_factory=_signed_headers,
        safe_print=safe_print,
        enabled=False,
    )
    robot_state = KalshiRobotState(
        robot_state_path,
        state_loader=robot_state_loader,
        state_saver=robot_state_saver,
        enabled_users_loader=enabled_users_loader,
        persist_migrations=not scheduler_disabled,
    )
    paper_accounts = KalshiPaperAccountStore(
        paper_account_path,
        account_loader=paper_account_loader,
        account_saver=paper_account_saver,
    )
    paper_robot = _PaperRobotController(
        client,
        robot_state,
        paper_accounts,
        connection_loader=load_connection,
        authoritative_connection_loader=load_authoritative_connection,
        signed_request=signed_api_request,
        notifier=notifier,
        observation_saver=observation_saver,
        portfolio_display_loader=portfolio_display_loader,
        portfolio_display_saver=portfolio_display_saver,
        scheduler_lease_acquirer=scheduler_lease_acquirer,
        worker_lease_store=worker_lease_store,
        reference_stream=reference_stream,
        safe_print=safe_print,
        start_background=start_background,
    )

    def authoritative_robot_state(user_id: str) -> Dict[str, Any]:
        refresh = getattr(robot_state, "refresh", None)
        if not callable(refresh):
            raise KalshiApiError(
                "Authoritative durable Kalshi robot state is unavailable.",
                status=503,
                code="kalshi_robot_state_not_authoritative",
            )
        snapshot = refresh(user_id)
        if (
            not isinstance(snapshot, Mapping)
            or snapshot.get("authoritativeRefresh") is not True
            or snapshot.get("durableStateLoaderAvailable") is not True
        ):
            raise KalshiApiError(
                "Real Kalshi control changes require durable robot state.",
                status=503,
                code="kalshi_robot_state_not_authoritative",
            )
        return dict(snapshot)

    def robot_control_guard(
        user_id: str,
        target_mode: str,
        previous_mode: str,
    ):
        """Serialize every production robot mutation with order routing.

        When the durable fenced store exists, even an apparently Paper-only
        mutation takes the fence: another worker may switch to Real after our
        initial read. A single-process Paper development setup can continue
        without the durable store, while any mutation already involving Real
        still fails closed through ``_live_routing_lease``.
        """
        fenced = all(callable(getattr(worker_lease_store, name, None)) for name in (
            "claim_worker_lease_fenced",
            "renew_worker_lease",
            "release_worker_lease",
        ))
        if (
            fenced
            or _execution_mode(target_mode) == "real"
            or _execution_mode(previous_mode) == "real"
        ):
            return paper_robot._live_routing_lease(user_id)
        return nullcontext()

    @blueprint.route("/api/kalshi/config", methods=["GET", "POST", "DELETE"])
    def kalshi_config():
        try:
            user = authenticated_user()
            if not configuration_available():
                raise KalshiApiError("Credential storage is unavailable", status=503, code="credential_store_unavailable")
            config = load_connection(user["id"])
            if request.method == "GET":
                state_snapshot = robot_state.get(user["id"])
                active_environment = _execution_mode(
                    state_snapshot.get("activeEnvironment")
                    or (state_snapshot.get("config") or {}).get("executionMode")
                )
                return ok({
                    "success": True,
                    "activeEnvironment": active_environment,
                    "paper": {
                        "builtIn": True,
                        "configured": True,
                        "startingBalance": round(paper_accounts.starting_balance_cents / 100.0, 2),
                        "startingBalanceCents": paper_accounts.starting_balance_cents,
                        "marketDataBaseUrl": KALSHI_PUBLIC_BASE,
                    },
                    "environments": {
                        name: environment_summary(config, name) for name in KALSHI_ENVIRONMENTS
                    },
                })

            body = request.get_json(silent=True) or {}
            if not isinstance(body, Mapping):
                raise KalshiApiError("JSON body must be an object", status=400, code="invalid_request")
            environment = _environment_name(body.get("environment"))
            key_field, private_field = _credential_fields(environment)
            clearing_credentials = (
                request.method == "DELETE" or body.get("clear") is True
            )
            incoming_key_id = str(body.get("apiKeyId") or "").strip()
            incoming_private = str(body.get("privateKey") or "").strip()
            prepared_key_id = None
            prepared_private = None
            if not clearing_credentials:
                if incoming_key_id and "****" not in incoming_key_id:
                    if not re.fullmatch(
                        r"[A-Za-z0-9._-]{8,200}",
                        incoming_key_id,
                    ):
                        raise KalshiApiError(
                            "A valid Kalshi API Key ID is required",
                            status=400,
                            code="invalid_api_key_id",
                        )
                    prepared_key_id = incoming_key_id
                if incoming_private and "****" not in incoming_private:
                    # Validate and normalize the CPU-heavy RSA material before
                    # acquiring the routing fence. The lease below covers only
                    # the actual credential/state mutation.
                    _load_rsa_private_key(incoming_private)
                    prepared_private = _normalize_private_key(
                        incoming_private
                    )
            # Credential rotation/deletion is part of the same per-user
            # routing generation as order submission. Once this lease returns,
            # no worker holding an older credential/state view can still POST.
            with paper_robot._live_routing_lease(user["id"]):
                authoritative_robot_state(user["id"])
                config = load_authoritative_connection(user["id"])
                if clearing_credentials:
                    current_state = authoritative_robot_state(user["id"])
                    current_mode = _execution_mode(
                        current_state.get("activeEnvironment")
                        or (current_state.get("config") or {}).get(
                            "executionMode"
                        )
                    )
                    if current_mode == "real" and current_state.get("enabled"):
                        robot_state.configure(
                            user["id"],
                            False,
                            current_state.get("config")
                            or {"executionMode": "real"},
                        )
                    config.pop(key_field, None)
                    config.pop(private_field, None)
                    config.pop(f"{environment}_test_status", None)
                    config.pop(f"{environment}_last_tested_at", None)
                else:
                    if prepared_key_id is not None:
                        config[key_field] = prepared_key_id
                    if prepared_private is not None:
                        config[private_field] = prepared_private
                    if not config.get(key_field) or not config.get(
                        private_field
                    ):
                        raise KalshiApiError(
                            "Both the API Key ID and RSA private key are required",
                            status=400,
                            code="incomplete_credentials",
                        )
                    config[f"{environment}_test_status"] = "saved"
                config["active_environment"] = environment
                config["updated_at"] = (
                    datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                saved, error = save_user_config(
                    user["id"],
                    "kalshi",
                    config,
                )
                if not saved:
                    message = "Kalshi configuration could not be saved"
                    if error == "config_type_check":
                        message = (
                            "Database migration for Kalshi configuration "
                            "is required"
                        )
                    raise KalshiApiError(
                        message,
                        status=500,
                        code=error or "config_save_failed",
                    )
                remember_connection(user["id"], config)
            return ok({
                "success": True,
                "environment": environment,
                "configured": bool(config.get(key_field) and config.get(private_field)),
                "message": "Kalshi credentials removed" if clearing_credentials else "Kalshi credentials saved",
            })
        except Exception as exc:
            return fail(exc)

    @blueprint.post("/api/kalshi/config/test")
    def kalshi_config_test():
        try:
            user = authenticated_user()
            body = request.get_json(silent=True) or {}
            if not isinstance(body, Mapping):
                raise KalshiApiError("JSON body must be an object", status=400, code="invalid_request")
            environment = _environment_name(body.get("environment"))
            key_field, private_field = _credential_fields(environment)
            # Credential verification belongs to the same per-user routing
            # generation as credential mutation and Real order submission.
            # Holding the fence across every signed read and the status patch
            # prevents an old test snapshot from resurrecting deleted or
            # rotated credentials.
            with paper_robot._live_routing_lease(user["id"]) as routing_lease:
                config = load_authoritative_connection(user["id"])
                started_at = time.perf_counter()
                account = signed_account_check(config, environment)
                # A balance-only check can pass even when the portfolio
                # transport used by the robot is broken. Verify the two
                # additional signed reads needed immediately before routing.
                # This remains read-only: no order is created or cancelled.
                with ThreadPoolExecutor(
                    max_workers=2,
                    thread_name_prefix="kalshi-preflight",
                ) as pool:
                    positions_future = pool.submit(
                        signed_api_request,
                        config,
                        environment,
                        "GET",
                        "/portfolio/positions",
                        params={"limit": 1},
                    )
                    orders_future = pool.submit(
                        signed_api_request,
                        config,
                        environment,
                        "GET",
                        "/portfolio/orders",
                        params={"limit": 1},
                    )
                    positions_payload = positions_future.result()
                    orders_payload = orders_future.result()
                latency_ms = int(
                    round((time.perf_counter() - started_at) * 1000)
                )
                paper_robot._renew_live_routing_lease(routing_lease)
                latest_config = load_authoritative_connection(user["id"])
                tested_credentials = (
                    str(config.get(key_field) or ""),
                    str(config.get(private_field) or ""),
                )
                latest_credentials = (
                    str(latest_config.get(key_field) or ""),
                    str(latest_config.get(private_field) or ""),
                )
                if (
                    latest_credentials != tested_credentials
                    or not all(latest_credentials)
                ):
                    raise KalshiApiError(
                        "Kalshi credentials changed during the connection "
                        "test; run the test again.",
                        status=409,
                        code="kalshi_credentials_changed",
                    )
                # Patch only test metadata onto the newest durable record.
                # Never write back the credential snapshot used for signing.
                latest_config[f"{environment}_test_status"] = "connected"
                latest_config[f"{environment}_last_tested_at"] = (
                    datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                saved, error = save_user_config(
                    user["id"],
                    "kalshi",
                    latest_config,
                )
                if not saved:
                    raise KalshiApiError(
                        "Connection succeeded but its status could not be saved",
                        status=500,
                        code=error or "config_save_failed",
                    )
                config = latest_config
                remember_connection(user["id"], config)
            return ok({
                "success": True,
                "environment": environment,
                "message": "Kalshi account connection verified",
                "account": {
                    "balance": account.get("balance"),
                    "portfolioValue": account.get("portfolio_value"),
                },
                "preflight": {
                    "authenticatedReads": ["balance", "positions", "orders"],
                    "positionsVisible": len(positions_payload.get("market_positions") or positions_payload.get("positions") or []),
                    "ordersVisible": len(orders_payload.get("orders") or []),
                    "orderTransportPath": "/trade-api/v2/portfolio/events/orders",
                    "orderSigningReady": True,
                    "writeRequestSent": False,
                    "latencyMs": latency_ms,
                },
            })
        except Exception as exc:
            return fail(exc)

    @blueprint.get("/api/kalshi/btc-15m/snapshot")
    def btc15_snapshot():
        try:
            user = authenticated_user()
            snapshot = client.snapshot(
                base_url=KALSHI_PUBLIC_BASE,
                reference_override=reference_stream.snapshot(user["id"]),
            )
            decision = evaluate_btc15_contract(
                snapshot["market"],
                spot_price=snapshot["reference"].get("price"),
                candles=snapshot["reference"].get("candles") or [],
                orderbook=snapshot.get("orderbook") or {},
                reference_time=snapshot["reference"].get("timestamp"),
                reference_metadata=snapshot.get("reference") or {},
                book_time=snapshot.get("orderbookAsOf"),
            )
            snapshot["reference"].pop("candles", None)
            return ok({"success": True, "snapshot": snapshot, "decision": decision})
        except Exception as exc:
            return fail(exc)

    @blueprint.post("/api/kalshi/btc-15m/evaluate")
    def btc15_evaluate():
        try:
            user = authenticated_user()
            body = request.get_json(silent=True)
            if body is not None and not isinstance(body, Mapping):
                raise KalshiApiError("JSON body must be an object", status=400, code="invalid_request")
            requested_config = normalize_strategy_config((body or {}).get("config") or {})
            mode = _execution_mode(
                requested_config.get("executionMode")
                or (body or {}).get("mode")
                or "paper"
            )
            state = robot_state.get(user["id"], environment=mode)
            # Real-mode polling is a read-only preflight.  Use the durable
            # robot policy and its latest scheduler-owned account snapshot
            # instead of the browser's research bankroll.  This keeps the
            # screen honest without adding another burst of private Kalshi API
            # calls every five seconds.
            config = (
                normalize_strategy_config({
                    **dict(state.get("config") or {}),
                    "executionMode": mode,
                })
                if mode == "real"
                else requested_config
            )
            account_context: Dict[str, Any] = {}
            account_preflight: Dict[str, Any] = {}
            robot_runtime: Dict[str, Any] = {}
            if mode == "real":
                robot_runtime = paper_robot.runtime_snapshot()
                latest_rows = list(state.get("decisions") or [])
                latest_account = dict(
                    (latest_rows[0].get("account") if latest_rows else {}) or {}
                )
                account_preflight = _real_preflight_account_health(
                    state,
                    robot_runtime,
                )
                cash_available = _finite_number(
                    latest_account.get("cashAvailable"),
                    0.0,
                )
                portfolio_exposure = _finite_number(
                    latest_account.get("portfolioExposure"),
                    0.0,
                )
                account_context = {
                    **latest_account,
                    "bankroll": max(0.0, cash_available + portfolio_exposure),
                    "cashAvailable": cash_available,
                    "portfolioExposure": portfolio_exposure,
                    "currentMarketExposure": _finite_number(
                        latest_account.get("currentMarketExposure"),
                        0.0,
                    ),
                    "snapshotAt": account_preflight.get("snapshotAt"),
                    "snapshotAgeSeconds": account_preflight.get(
                        "snapshotAgeSeconds"
                    ),
                    "snapshotFresh": account_preflight.get(
                        "accountSnapshotFresh"
                    ),
                }
            snapshot = client.snapshot(
                base_url=KALSHI_PUBLIC_BASE,
                reference_override=reference_stream.snapshot(user["id"]),
            )
            decision = evaluate_btc15_contract(
                snapshot["market"],
                spot_price=snapshot["reference"].get("price"),
                candles=snapshot["reference"].get("candles") or [],
                config=config,
                orderbook=snapshot.get("orderbook") or {},
                reference_time=snapshot["reference"].get("timestamp"),
                reference_metadata=snapshot.get("reference") or {},
                book_time=snapshot.get("orderbookAsOf"),
                account_context=account_context,
            )
            decision["marketFamily"] = "btc15m"
            decision["decisionScope"] = (
                "real_read_only_preflight"
                if mode == "real"
                else "paper_research_preflight"
            )
            if mode == "real":
                decision["accountPreflight"] = account_preflight
                _apply_real_preflight_health_gate(
                    decision,
                    account_preflight,
                )
            if account_context:
                decision["account"] = account_context
            snapshot["reference"].pop("candles", None)
            return ok({
                "success": True,
                "snapshot": snapshot,
                "decision": decision,
                "robotState": state,
                "robotRuntime": robot_runtime if mode == "real" else None,
            })
        except Exception as exc:
            return fail(exc)

    @blueprint.get("/api/kalshi/btc-hourly/snapshot")
    def btc_hourly_snapshot():
        try:
            user = authenticated_user()
            snapshot = client.hourly_snapshot(
                base_url=KALSHI_PUBLIC_BASE,
                reference_override=reference_stream.snapshot(user["id"]),
            )
            snapshot["reference"].pop("candles", None)
            return ok({"success": True, "snapshot": snapshot})
        except Exception as exc:
            return fail(exc)

    @blueprint.post("/api/kalshi/btc-hourly/evaluate")
    def btc_hourly_evaluate():
        try:
            user = authenticated_user()
            state = robot_state.get(user["id"])
            mode = request_mode((state.get("config") or {}).get("executionMode") or "paper")
            result = paper_robot.tick(
                user["id"],
                submit_order=False,
                mode=mode,
                family="btchourly",
            )
            return ok({"success": True, **result, "robotState": result.get("state")})
        except Exception as exc:
            return fail(exc)

    @blueprint.get("/api/kalshi/paper/portfolio")
    def kalshi_paper_portfolio():
        try:
            user = authenticated_user()
            mode = request_mode()
            return ok({
                "success": True,
                "portfolio": paper_robot.portfolio(
                    user["id"], mode=mode, include_display=True, mutate=False
                ),
                "state": robot_state.get(user["id"], environment=mode),
            })
        except Exception as exc:
            return fail(exc)

    @blueprint.delete("/api/kalshi/paper/portfolio")
    def kalshi_paper_portfolio_reset():
        try:
            user = authenticated_user()
            mode = request_mode()
            if mode == "real":
                raise KalshiApiError("Real Kalshi accounts cannot be reset from AlphaLab.", status=400, code="kalshi_real_reset_not_allowed")
            body = request.get_json(silent=True) or {}
            starting_balance = body.get("startingBalance", 10_000)
            try:
                starting_balance = float(starting_balance)
            except (TypeError, ValueError):
                raise KalshiApiError(
                    "Starting balance must be a number.",
                    status=400,
                    code="kalshi_invalid_starting_balance",
                )
            if not 100 <= starting_balance <= 1_000_000:
                raise KalshiApiError(
                    "Starting balance must be between $100 and $1,000,000.",
                    status=400,
                    code="kalshi_invalid_starting_balance",
                )
            portfolio = paper_accounts.reset(
                user["id"],
                starting_balance_dollars=starting_balance,
            )
            state = robot_state.start_fresh_strategy(
                user["id"],
                environment="paper",
                starting_bankroll=starting_balance,
                name=str(body.get("strategyName") or ""),
            )
            return ok({"success": True, "portfolio": portfolio, "state": robot_state.get(user["id"], environment=mode)})
        except Exception as exc:
            return fail(exc)

    @blueprint.get("/api/kalshi/paper/robot")
    def kalshi_paper_robot_status():
        try:
            user = authenticated_user()
            raw_mode = request.args.get("mode")
            state = robot_state.get(user["id"], environment=raw_mode) if raw_mode else robot_state.get(user["id"])
            return ok({"success": True, "state": state})
        except Exception as exc:
            return fail(exc)

    @blueprint.post("/api/kalshi/paper/robot")
    def kalshi_paper_robot_configure():
        try:
            user = authenticated_user()
            body = request.get_json(silent=True) or {}
            if not isinstance(body, Mapping) or not isinstance(body.get("enabled"), bool):
                raise KalshiApiError("enabled must be true or false", status=400, code="invalid_request")
            config = normalize_strategy_config(body.get("config") or {})
            mode = _execution_mode(config.get("executionMode") or body.get("mode"))
            config["executionMode"] = mode
            refresh_state = getattr(robot_state, "refresh", None)
            previous = (
                refresh_state(user["id"])
                if callable(refresh_state)
                else robot_state.get(user["id"])
            )
            previous_mode = _execution_mode(
                previous.get("activeEnvironment")
                or (previous.get("config") or {}).get("executionMode")
            )
            routing_guard = robot_control_guard(
                user["id"],
                mode,
                previous_mode,
            )
            with routing_guard:
                # Reload after acquiring the fence so mode/arming mutation is
                # linearized with the final refresh and POST in every worker.
                previous = (
                    authoritative_robot_state(user["id"])
                    if callable(robot_state_loader)
                    else robot_state.get(user["id"])
                )
                current_previous_mode = _execution_mode(
                    previous.get("activeEnvironment")
                    or (previous.get("config") or {}).get("executionMode")
                )
                if (
                    mode == "real"
                    or previous_mode == "real"
                    or current_previous_mode == "real"
                ) and previous.get("authoritativeRefresh") is not True:
                    # A Real mutation in a local-only state store is unsafe
                    # even when a test double happens to provide a lease.
                    authoritative_robot_state(user["id"])
                if body["enabled"]:
                    ensure_real_ready(user["id"], mode)
                state = robot_state.configure(
                    user["id"],
                    body["enabled"],
                    config,
                )
            record_robot_control_audit(user["id"], body, previous, state, mode)
            actually_enabled = bool(state.get("enabled"))
            payload = {
                "success": True,
                "state": state,
                "requiresExplicitEnable": bool(body["enabled"]) and not actually_enabled,
            }
            if bool(previous.get("enabled")) != actually_enabled:
                paper_robot._notify(
                    user["id"],
                    "lifecycle",
                    {
                        "source": "Kalshi Robot",
                        "notificationScope": "kalshi",
                        "assetClass": "kalshi",
                        "event_id": f"kalshi-robot:{mode}:{'start' if actually_enabled else 'stop'}:{time.time_ns()}",
                        "component": "Kalshi BTC Robot",
                        "state": "started" if actually_enabled else "stopped",
                        "mode": mode,
                        "trigger": "user",
                        "description": (
                            f"Kalshi {mode} automation is armed."
                            if actually_enabled
                            else f"Kalshi {mode} automation is stopped."
                        ),
                        "descriptionZh": (
                            f"Kalshi {'实盘' if mode == 'real' else '模拟盘'}自动化已启动。"
                            if actually_enabled
                            else f"Kalshi {'实盘' if mode == 'real' else '模拟盘'}自动化已停止。"
                        ),
                    },
                )
            if actually_enabled:
                payload.update(paper_robot.tick(user["id"], submit_order=True, mode=mode))
            return ok(payload)
        except Exception as exc:
            return fail(exc)

    @blueprint.post("/api/kalshi/paper/robot/config")
    def kalshi_paper_robot_save_config():
        """Persist risk limits without starting, stopping, or trading the robot."""
        try:
            user = authenticated_user()
            body = request.get_json(silent=True) or {}
            config = normalize_strategy_config(body.get("config") or {})
            mode = _execution_mode(config.get("executionMode") or body.get("mode"))
            config["executionMode"] = mode
            refresh_state = getattr(robot_state, "refresh", None)
            previous = (
                refresh_state(user["id"])
                if callable(refresh_state)
                else robot_state.get(user["id"])
            )
            previous_mode = _execution_mode(
                previous.get("activeEnvironment")
                or (previous.get("config") or {}).get("executionMode")
            )
            routing_guard = robot_control_guard(
                user["id"],
                mode,
                previous_mode,
            )
            with routing_guard:
                current_state = (
                    authoritative_robot_state(user["id"])
                    if callable(robot_state_loader)
                    else robot_state.get(user["id"])
                )
                current_mode = _execution_mode(
                    current_state.get("activeEnvironment")
                    or (current_state.get("config") or {}).get(
                        "executionMode"
                    )
                )
                if mode == "real" or previous_mode == "real" or current_mode == "real":
                    authoritative_robot_state(user["id"])
                ensure_real_ready(user["id"], mode)
                current = robot_state.get(user["id"], environment=mode)
                state = robot_state.configure(
                    user["id"],
                    bool(current.get("enabled")),
                    config,
                )
            return ok({"success": True, "state": state})
        except Exception as exc:
            return fail(exc)

    @blueprint.post("/api/kalshi/paper/robot/tick")
    def kalshi_paper_robot_tick():
        try:
            user = authenticated_user()
            raw_mode = request.args.get("mode") or request.args.get("environment")
            active_state = robot_state.get(user["id"])
            active_mode = _execution_mode(
                active_state.get("activeEnvironment")
                or (active_state.get("config") or {}).get("executionMode")
            )
            mode = request_mode(active_mode)
            if raw_mode and mode != active_mode:
                raise KalshiApiError(
                    "Select and save the requested Kalshi mode before running a trading tick.",
                    status=409,
                    code="kalshi_mode_not_active",
                )
            state = (
                robot_state.get(user["id"], environment=mode)
                if mode != active_mode
                else active_state
            )
            ensure_real_ready(user["id"], mode)
            body = request.get_json(silent=True) or {}
            family = str(request.args.get("family") or body.get("family") or "btc15m").lower()
            if family not in {"btc15m", "btchourly"}:
                raise KalshiApiError("family must be btc15m or btchourly", status=400, code="invalid_request")
            return ok({
                "success": True,
                **paper_robot.tick(
                    user["id"],
                    submit_order=bool(state.get("enabled")),
                    mode=mode,
                    family=family,
                ),
            })
        except Exception as exc:
            return fail(exc)

    @blueprint.get("/api/kalshi/status")
    def kalshi_status():
        try:
            user = authenticated_user()
            config = load_connection(user["id"])
            active_summary = environment_summary(config, "production")
            state = robot_state.get(user["id"])
            active_mode = _execution_mode((state.get("config") or {}).get("executionMode") or "paper")
            return ok({
                "success": True,
                "publicData": "available",
                "seriesTicker": BTC_15M_SERIES,
                "strategyFamilies": ["btc15m", "btchourly"],
                "execution": "real_available" if active_summary["configured"] else "paper_only",
                "activeEnvironment": active_mode,
                "accountProvider": "Kalshi" if active_mode == "real" else "AlphaLab",
                "builtInPaperConfigured": True,
                "personalApiConfigured": active_summary["configured"],
                "liveTradingConfigured": active_summary["configured"],
                "connectionStatus": active_summary["testStatus"],
                "referenceFeed": reference_stream.status(user["id"]),
                "publicDataStatus": client.runtime_snapshot(),
            })
        except Exception as exc:
            return fail(exc)

    @blueprint.post("/api/kalshi/portfolio/display-reset")
    def kalshi_portfolio_display_reset():
        try:
            user = authenticated_user()
            mode = request_mode()
            portfolio = paper_robot.reset_portfolio_display(user["id"], mode=mode)
            return ok({
                "success": True,
                "portfolio": portfolio,
                "state": robot_state.get(user["id"], environment=mode),
                "message": "Portfolio display period reset; the complete account ledger was preserved.",
            })
        except Exception as exc:
            return fail(exc)

    @blueprint.get("/api/kalshi/analytics")
    def kalshi_analytics():
        try:
            user = authenticated_user()
            if not callable(observation_loader):
                raise KalshiApiError(
                    "Kalshi analytics storage is unavailable",
                    status=503,
                    code="kalshi_analytics_unavailable",
                )
            mode = request_mode("paper")
            try:
                hours = max(1, min(int(request.args.get("hours") or 24), 168))
            except (TypeError, ValueError):
                hours = 24
            since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
            rows = observation_loader(
                user["id"],
                environment=mode,
                since=since,
                limit=5000,
            )
            return ok({
                "success": True,
                "environment": mode,
                "windowHours": hours,
                "analytics": _observation_analytics(rows),
                "referenceFeed": reference_stream.status(user["id"]),
            })
        except Exception as exc:
            return fail(exc)


    app.register_blueprint(blueprint)
    controls = {
        "client": client,
        "robot_state": robot_state,
        "paper_accounts": paper_accounts,
        "paper_robot": paper_robot,
        "runtime": paper_robot.runtime_snapshot,
        "start": paper_robot.start,
        "stop": paper_robot.stop,
        "reference_stream": reference_stream,
    }
    app.extensions["alphalab_kalshi_api"] = controls
    return controls


__all__ = [
    "COINBASE_EXCHANGE_BASE",
    "KALSHI_ENVIRONMENTS",
    "KALSHI_PUBLIC_BASE",
    "KALSHI_PUBLIC_FALLBACK_BASE",
    "KalshiApiError",
    "_paper_order_payload",
    "_signed_headers",
    "register_kalshi_api",
]
