#!/usr/bin/env python3
"""Offline, descriptive audit of bot-entry-ticker-scoped Kalshi outcomes.

Usage (no backend imports, credentials, API calls, or writes):
    python scripts/kalshi_backtest/kalshi_owned_performance.py state.json.gz
    python scripts/kalshi_backtest/kalshi_owned_performance.py ledger.json \
        --entries bot_filled_trades.json --train-end 2026-08-01 \
        --validation-end 2026-08-15 --include-markets

Input is an exported mode bucket/full state, or a normalized ledger object with
filledTrades and settlementRecords/closedTradeRecords/realizedTradeRecords.
A bare realized-record list requires --entries containing bot filledTrades.
Amounts must already be dollars, quantities actual filled contracts (fractional
quantities supported), and timestamps ISO-8601 with offsets. Never pass a raw
account fill history as --entries: presence in that history does not prove bot
ownership. Canonical exits/settlements take precedence over their realized mirror.

Matching a bot entry ticker is NOT exact lot ownership: manual trades in the same
ticker can contaminate aggregate settlement cost/P&L even when quantities match.
This tool does not reconstruct missing history, simulate fills, or predict profit.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import json
from pathlib import Path
import sys
from typing import Any


ZERO = Decimal(0)
TOLERANCE = Decimal("0.00000001")
MAX_INPUT_BYTES = 64 * 1024 * 1024
LIMITATIONS = [
    "Scope is bot BUY-filled tickers, not verified lot-level bot attribution. "
    "Manual trades in the same ticker can contaminate amounts even when quantities reconcile.",
    "Quantity-complete means recorded exit/settlement contracts reconcile by side to recorded "
    "bot entries; it is not proof that the exported history is complete or unmixed.",
    "Stored pnl is treated as after-fee dollars and fees are not subtracted twice. "
    "Fallback derivation requires revenue, cost and fees. Reported fees/cost basis are not independently verified.",
    "Net P/L is after recorded exchange/trading fees only. It excludes hosting, market-data "
    "and AI subscription costs and taxes; it is not net business profit.",
    "Only quantity-complete, valid markets contribute wins, losses and profit factor. "
    "Partial realizations are not classified as completed winning/losing trades.",
    "Drawdown is the cumulative completed-market net-P&L curve starting at zero, ordered by "
    "completion time; it excludes open-position mark-to-market and intramarket drawdown.",
    "Chronological splits are descriptive, including user-supplied dates unless frozen before "
    "model selection. Correlated markets, repeated tuning and small samples can invalidate apparent improvements.",
    "Recorded entry strategyVersion labels are not complete frozen policy/configuration fingerprints; "
    "the current strategy label is never backfilled onto old trades.",
    "Old synthetic-quote replay baselines do not reproduce live depth, IOC execution, "
    "confirmation timing, fractional fee rounding or exact settlement reference. Compact "
    "decision exports cannot recompute candle features without contemporaneous raw data.",
    "Historical returns do not establish future profitability; this audit does not promise profit.",
]


def _number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _first(row: dict, *keys: str) -> Any:
    # An explicit zero or malformed fixed-point value must not fall through.
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    return None


def _time(value: Any, *, boundary: bool = False) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        if boundary and len(value) == 10:
            value += "T00:00:00+00:00"
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _money(value: Decimal) -> float:
    return round(float(value), 10)


def _side(row: dict) -> str:
    value = str(row.get("side") or "").upper()
    if value not in {"YES", "NO"}:
        value = str(row.get("action") or "").upper()
        value = value.removeprefix("BUY_").removeprefix("SELL_")
    return value if value in {"YES", "NO"} else "UNKNOWN"


def load_json(path: str | Path) -> Any:
    """Bound decompressed input; never load dotenv or make network requests."""
    path = Path(path)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("input exceeds 64 MiB decompressed limit")
    return json.loads(data)


def _bucket(payload: Any, environment: str) -> tuple[dict, str | None]:
    if not isinstance(payload, dict):
        raise ValueError("state/ledger must be an object, or use --entries with a realized-record list")
    if isinstance(payload.get("state"), dict):
        payload = payload["state"]
    if isinstance(payload.get("modeState"), dict):
        selected = payload["modeState"].get(environment)
        if not isinstance(selected, dict):
            raise ValueError("requested environment is absent from modeState")
        return selected, environment
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    inherited = payload.get("environment") or config.get("executionMode") or payload.get("activeEnvironment")
    return payload, str(inherited).lower() if inherited else None


def _pnl(row: dict) -> Decimal | None:
    if row.get("pnl") is not None:
        return _number(row["pnl"])
    revenue, cost, fees = (_number(row.get(key)) for key in ("revenue", "cost", "fees"))
    if any(value is None for value in (revenue, cost, fees)):
        return None
    return revenue - cost - fees


def _records(bucket: dict) -> tuple[list[tuple[str, dict]], str]:
    strategy = bucket.get("strategy") if isinstance(bucket.get("strategy"), dict) else bucket
    if "settlementRecords" in strategy or "closedTradeRecords" in strategy:
        result = []
        for kind, key in (("settlement", "settlementRecords"), ("sale", "closedTradeRecords")):
            rows = strategy.get(key, [])
            if not isinstance(rows, list):
                raise ValueError(f"{key} must be a list")
            result.extend((kind, row) for row in rows)
        return result, "canonical_settlements_and_closes"
    rows = strategy.get("realizedTradeRecords", [])
    if not isinstance(rows, list):
        raise ValueError("realizedTradeRecords must be a list")
    return [("sale" if isinstance(row, dict) and str(row.get("exitType") or "").lower() == "sale"
             else "settlement", row) for row in rows], "realized_mirror_only"


def _stats(markets: list[dict]) -> dict:
    ordered = sorted(markets, key=lambda row: (row["completed"], row["ticker"]))
    pnls = [row["pnl"] for row in ordered]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    equity = peak = drawdown = ZERO
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    gross_profit, gross_loss = sum(wins, ZERO), -sum(losses, ZERO)
    return {
        "markets": len(markets), "wins": len(wins), "losses": len(losses),
        "flat": len(pnls) - len(wins) - len(losses),
        "winRate": len(wins) / len(pnls) if pnls else None,
        "netPnl": _money(sum(pnls, ZERO)),
        "grossProfit": _money(gross_profit), "grossLoss": _money(gross_loss),
        "profitFactor": _money(gross_profit / gross_loss) if gross_loss else None,
        "profitFactorNote": None if gross_loss else "undefined_without_losing_markets",
        "maxCompletedMarketDrawdown": _money(drawdown),
        "firstEntryAt": _iso(min((row["entered"] for row in markets), default=None)),
        "lastCompletedAt": _iso(max((row["completed"] for row in markets), default=None)),
    }


def _event_key(ticker: str) -> str:
    # Hourly threshold strikes share an event. Do not guess grouping for other markets.
    if ticker.startswith("KXBTCD-") and "-T" in ticker:
        return ticker.rsplit("-T", 1)[0]
    return ticker


def _splits(markets: list[dict], train_end: str | None, validation_end: str | None) -> dict:
    supplied = train_end is not None or validation_end is not None
    if supplied:
        first, second = _time(train_end, boundary=True), _time(validation_end, boundary=True)
        if first is None or second is None or first >= second:
            raise ValueError("supply both increasing --train-end and --validation-end ISO dates/timestamps")
    else:
        ordered = sorted(markets, key=lambda row: (row["entered"], row["ticker"]))
        if len(ordered) < 5:
            return {"mode": "insufficient_markets_for_descriptive_split", "minimumMarkets": 5}
        first = ordered[int(len(ordered) * 0.6)]["entered"]
        second = ordered[int(len(ordered) * 0.8)]["entered"]
    groups = {"train": [], "validation": [], "holdout": []}
    purged = []
    assignments = []
    for row in markets:
        if row["entered"] < first:
            label = "train" if row["completed"] < first else "purged"
        elif row["entered"] < second:
            label = "validation" if row["completed"] < second else "purged"
        else:
            label = "holdout"
        assignments.append((row, label))
    event_splits: dict[str, set[str]] = defaultdict(set)
    for row, label in assignments:
        event_splits[_event_key(row["ticker"])].add(label)
    for row, label in assignments:
        if label == "purged" or len(event_splits[_event_key(row["ticker"])]) > 1:
            purged.append(row)
        else:
            groups[label].append(row)
    return {
        "mode": "user_supplied_chronological_dates" if supplied else "descriptive_60_20_20_entry_time",
        "untouchedHoldoutProven": False,
        "trainEndExclusive": _iso(first), "validationEndExclusive": _iso(second),
        "boundaryOrSharedEventPurgedMarkets": len(purged),
        "groups": {label: _stats(rows) for label, rows in groups.items()},
    }


def audit(payload: Any, *, environment: str = "real", entries: Any = None,
          train_end: str | None = None, validation_end: str | None = None,
          include_markets: bool = False) -> dict:
    if environment not in {"real", "paper"}:
        raise ValueError("environment must be real or paper")
    if isinstance(payload, list) and entries is not None:
        payload = {"realizedTradeRecords": payload}
    bucket, inherited = _bucket(payload, environment)
    entry_inherited = inherited
    entry_rows = bucket.get("filledTrades", [])
    if entries is not None:
        if isinstance(entries, list):
            entry_rows, entry_inherited = entries, None
        else:
            entry_bucket, entry_inherited = _bucket(entries, environment)
            entry_rows = entry_bucket.get("filledTrades", [])
    if not isinstance(entry_rows, list):
        raise ValueError("filledTrades must be a list")
    counts: Counter = Counter()
    markets: dict[str, dict] = {}
    seen_entries = {}

    def in_scope(row: Any, default: str | None) -> bool:
        if not isinstance(row, dict):
            counts["malformedRows"] += 1
            return False
        row_env = str(row.get("environment") or default or "").lower()
        if row_env != environment:
            counts["otherEnvironmentRows" if row_env else "missingEnvironmentRows"] += 1
            return False
        return True

    for row in entry_rows:
        if not in_scope(row, entry_inherited):
            continue
        action = str(row.get("action") or "").upper()
        if row.get("orderFilled") is not True or not (action == "BUY" or action.startswith("BUY_")):
            counts["nonBotBuyFilledRows"] += 1
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            counts["missingTickerRows"] += 1
            continue
        market = markets.setdefault(ticker, {
            "ticker": ticker, "entryQty": defaultdict(lambda: ZERO),
            "exitQty": defaultdict(lambda: ZERO), "entryTimes": [], "exitTimes": [],
            "policies": set(), "issues": set(), "pnl": ZERO, "outcomes": 0,
        })
        quantity = _number(_first(row, "fill_count_fp", "fillCount", "fill_count"))
        side, entered = _side(row), _time(row.get("generatedAt"))
        policy = str(row.get("strategyVersion") or "unknown")
        market["policies"].add(policy)
        signature = (ticker, side, quantity, entered, policy)
        identity = row.get("orderId") or row.get("clientOrderId")
        key = ("id", str(identity)) if identity else ("no_id", signature)
        if key in seen_entries:
            old_signature, old_ticker = seen_entries[key]
            counts["duplicateEntryRows"] += 1
            if old_signature != signature or not identity:
                market["issues"].add("conflicting_or_unidentified_duplicate_entry")
                markets[old_ticker]["issues"].add("conflicting_or_unidentified_duplicate_entry")
            continue
        seen_entries[key] = (signature, ticker)
        if quantity is None or quantity <= 0 or side == "UNKNOWN":
            market["issues"].add("invalid_entry_quantity_or_side")
        else:
            market["entryQty"][side] += quantity
        if entered is None:
            market["issues"].add("missing_or_invalid_entry_time")
        else:
            market["entryTimes"].append(entered)

    outcomes, source = _records(bucket)
    seen_outcomes = {}
    unowned_tickers = set()
    for kind, row in outcomes:
        if not in_scope(row, inherited):
            continue
        ticker = str(row.get("ticker") or "").strip()
        market = markets.get(ticker)
        if market is None:
            counts["unownedOutcomeRows"] += 1
            if ticker:
                unowned_tickers.add(ticker)
            continue
        side = _side(row)
        quantity = _number(_first(row, "contracts", "count"))
        pnl = _pnl(row)
        ended = _time(_first(row, "closedAt", "settledAt"))
        signature = (ticker, side, quantity, pnl, ended)
        identity = (row.get("orderId") if kind == "sale" else row.get("key"))
        key = (kind, "id", str(identity)) if identity else (kind, ticker, side, ended)
        if key in seen_outcomes:
            old_signature, old_ticker = seen_outcomes[key]
            counts["duplicateOutcomeRows"] += 1
            if old_signature != signature:
                market["issues"].add("conflicting_duplicate_outcome")
                markets[old_ticker]["issues"].add("conflicting_duplicate_outcome")
            continue
        seen_outcomes[key] = (signature, ticker)
        market["outcomes"] += 1
        if quantity is None or quantity <= 0 or side == "UNKNOWN":
            market["issues"].add("invalid_outcome_quantity_or_side")
        else:
            market["exitQty"][side] += quantity
        if pnl is None:
            market["issues"].add("missing_or_invalid_net_pnl")
        else:
            market["pnl"] += pnl
        if ended is None:
            market["issues"].add("missing_or_invalid_outcome_time")
        else:
            market["exitTimes"].append(ended)

    complete, incomplete, ambiguous = [], [], []
    for market in markets.values():
        entry_qty, exit_qty = market["entryQty"], market["exitQty"]
        sides = set(entry_qty) | set(exit_qty)
        if any(exit_qty[side] > entry_qty[side] + TOLERANCE for side in sides):
            market["issues"].add("outcomes_exceed_bot_entry_quantity_possible_manual_mix_or_missing_history")
        if market["exitTimes"] and market["entryTimes"]:
            if min(market["exitTimes"]) < min(market["entryTimes"]) or max(market["exitTimes"]) < max(market["entryTimes"]):
                market["issues"].add("outcome_precedes_recorded_entry_history")
        market["entered"] = min(market["entryTimes"], default=None)
        market["completed"] = max(market["exitTimes"], default=None)
        if market["issues"]:
            market["status"] = "ambiguous"
            ambiguous.append(market)
        elif market["outcomes"] and all(abs(exit_qty[side] - entry_qty[side]) <= TOLERANCE for side in sides):
            market["status"] = "quantity_complete_ticker_scoped"
            complete.append(market)
        else:
            market["status"] = "incomplete"
            incomplete.append(market)
    by_family, by_policy = defaultdict(list), defaultdict(list)
    for market in complete:
        ticker = market["ticker"]
        family = "btc15" if ticker.startswith("KXBTC15M-") else "btc_hourly" if ticker.startswith("KXBTCD-") else "other"
        by_family[family].append(market)
        policy = " + ".join(sorted(market["policies"]))
        by_policy[policy].append(market)
    report = {
        "schemaVersion": 1, "environment": environment,
        "ownershipScope": "bot_buy_filled_tickers_not_verified_lots", "outcomeSource": source,
        "currency": "USD", "ownedEntryTickers": len(markets),
        "complete": _stats(complete),
        "incomplete": {"markets": len(incomplete), "recordedPartialNetPnl": _money(sum((row["pnl"] for row in incomplete), ZERO))},
        "ambiguous": {"markets": len(ambiguous), "reasons": dict(Counter(issue for row in ambiguous for issue in row["issues"]))},
        "unownedOutcomeTickers": len(unowned_tickers), "dataQualityCounts": dict(counts),
        "byMarketFamily": {key: _stats(rows) for key, rows in sorted(by_family.items())},
        "byRecordedEntryPolicy": {key: _stats(rows) for key, rows in sorted(by_policy.items())},
        "chronologicalSplit": _splits(complete, train_end, validation_end),
        "limitations": list(LIMITATIONS),
    }
    if include_markets:
        report["markets"] = [{
            "ticker": row["ticker"], "status": row["status"], "issues": sorted(row["issues"]),
            "enteredAt": _iso(row["entered"]), "lastRealizationAt": _iso(row["completed"]),
            "recordedEntryPolicies": sorted(row["policies"]),
            "botEntryContractsBySide": {key: _money(value) for key, value in row["entryQty"].items()},
            "recordedRealizedContractsBySide": {key: _money(value) for key, value in row["exitQty"].items()},
            "knownRecordedNetPnl": _money(row["pnl"]), "outcomeRows": row["outcomes"],
        } for row in sorted(markets.values(), key=lambda item: item["ticker"])]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="local JSON or JSON.gz state/normalized ledger")
    parser.add_argument("--entries", help="optional separate bot filledTrades export; not raw account fills")
    parser.add_argument("--environment", choices=("real", "paper"), default="real")
    parser.add_argument("--train-end", help="exclusive training boundary, ISO UTC date or offset timestamp")
    parser.add_argument("--validation-end", help="exclusive validation boundary, ISO UTC date or offset timestamp")
    parser.add_argument("--include-markets", action="store_true", help="include private per-ticker performance in output")
    args = parser.parse_args(argv)
    try:
        report = audit(load_json(args.input), environment=args.environment,
                       entries=load_json(args.entries) if args.entries else None,
                       train_end=args.train_end, validation_end=args.validation_end,
                       include_markets=args.include_markets)
        print(json.dumps(report, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, OverflowError) as error:
        print(f"audit error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
