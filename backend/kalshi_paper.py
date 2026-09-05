"""AlphaLab-owned Kalshi paper-trading ledger.

The ledger consumes Kalshi's production public quotes but never submits an
order to Kalshi. Money is stored in integer cents and contract quantities in
hundredths, matching Kalshi V2 fixed-point counts and account-level rounding.
"""

from __future__ import annotations

import copy
import json
import math
import os
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


PAPER_ACCOUNT_VERSION = 4
DEFAULT_STARTING_BALANCE_CENTS = 1_000_000  # $10,000.00
MAX_LEDGER_ROWS = 500
CONTRACT_QUANTUM = Decimal("0.01")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _ceil(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_CEILING)


def _quantity_units(value: Any) -> int:
    """Return non-negative hundredth-contract units without rounding up risk."""
    try:
        parsed = Decimal(str(value))
    except Exception:
        return 0
    if not parsed.is_finite() or parsed <= 0:
        return 0
    return int((parsed / CONTRACT_QUANTUM).to_integral_value(rounding=ROUND_FLOOR))


def _quantity_from_units(units: int) -> float:
    return float(Decimal(max(0, int(units))) * CONTRACT_QUANTUM)


def _market_fee_multiplier(market: Optional[Mapping[str, Any]]) -> float:
    """Read an explicit market multiplier, otherwise use Kalshi's general 1x fee."""
    source = dict(market or {})
    for key in (
        "fee_multiplier",
        "fee_multiplier_fp",
        "taker_fee_multiplier",
        "event_taker_fee_multiplier",
    ):
        if source.get(key) is not None:
            return max(0.0, _number(source.get(key), 1.0))
    return 1.0


def taker_fill_amounts(
    price: float,
    contracts: float,
    *,
    fee_multiplier: float = 1.0,
) -> Dict[str, float]:
    """Return Kalshi-compatible taker cost and fee amounts in dollars.

    Kalshi's general event fee is 7% * C * P * (1-P), rounded up to
    $0.0001.  The total account debit is then rounded up to a whole cent;
    that final alignment is reported as part of the effective fill fee.
    """
    count_units = _quantity_units(contracts)
    count = Decimal(count_units) * CONTRACT_QUANTUM
    p = Decimal(str(price))
    if count_units <= 0 or p <= 0 or p >= 1:
        raise ValueError("price must be between 0 and 1 and contracts must be positive")
    cost = p * count
    multiplier = Decimal(str(max(0.0, _number(fee_multiplier, 1.0))))
    trade_fee = _ceil(
        multiplier * Decimal("0.07") * count * p * (Decimal(1) - p),
        Decimal("0.0001"),
    )
    debit = _ceil(cost + trade_fee, Decimal("0.01"))
    rounding_fee = debit - cost - trade_fee
    return {
        "positionCost": float(cost),
        "tradeFee": float(trade_fee),
        "roundingFee": float(rounding_fee),
        "fee": float(debit - cost),
        "debit": float(debit),
    }


def _normalize_book_levels(raw: Any) -> List[Tuple[float, float]]:
    levels: List[Tuple[float, float]] = []
    for level in raw or []:
        if not isinstance(level, Sequence) or isinstance(level, (str, bytes)) or len(level) < 2:
            continue
        price = _number(level[0])
        size_units = _quantity_units(level[1])
        if 0.0 < price < 1.0 and size_units > 0:
            levels.append((price, _quantity_from_units(size_units)))
    return sorted(levels, key=lambda item: item[0])


def executable_ask_levels(side: str, orderbook: Optional[Mapping[str, Any]]) -> List[Tuple[float, float]]:
    """Return Paper-executable user-side ask levels from Kalshi's YES book.

    Kalshi's public book exposes YES and NO bid ladders. Buying YES consumes the
    implied YES asks from NO bids at ``1 - no_bid``; buying NO consumes the
    implied NO asks from YES bids at ``1 - yes_bid``.
    """
    book = dict(orderbook or {})
    if str(side).upper() == "YES":
        return _normalize_book_levels((1.0 - price, size) for price, size in _normalize_book_levels(book.get("no")))
    if str(side).upper() == "NO":
        return _normalize_book_levels((1.0 - price, size) for price, size in _normalize_book_levels(book.get("yes")))
    return []


def executable_bid_levels(side: str, orderbook: Optional[Mapping[str, Any]]) -> List[Tuple[float, float]]:
    """Return executable bids for selling an existing Paper position."""
    book = dict(orderbook or {})
    key = "yes" if str(side).upper() == "YES" else "no" if str(side).upper() == "NO" else None
    if key is None:
        return []
    return sorted(_normalize_book_levels(book.get(key)), key=lambda item: item[0], reverse=True)


def _aggregate_fill(
    levels: Sequence[Tuple[float, float]],
    requested: float,
    limit_price: float,
    cash_cents: int,
    *,
    fee_multiplier: float = 1.0,
) -> Dict[str, Any]:
    fills: List[Dict[str, Any]] = []
    requested_units = _quantity_units(requested)
    remaining_units = requested_units
    total_cost = Decimal("0")
    total_trade_fee = Decimal("0")
    total_debit_cents = 0
    rounding_accumulator = Decimal("0")
    multiplier = Decimal(str(max(0.0, _number(fee_multiplier, 1.0))))

    def level_amounts(level_price: float, count_units: int, accumulator: Decimal):
        p = Decimal(str(level_price))
        count_decimal = Decimal(max(0, count_units)) * CONTRACT_QUANTUM
        cost = p * count_decimal
        trade_fee = _ceil(
            multiplier * Decimal("0.07") * count_decimal * p * (Decimal(1) - p),
            Decimal("0.0001"),
        )
        gross_debit = cost + trade_fee
        rounded_debit = _ceil(gross_debit, Decimal("0.01"))
        rounding_fee = rounded_debit - gross_debit
        next_accumulator = accumulator + rounding_fee
        rebate_units = (next_accumulator / Decimal("0.01")).to_integral_value(
            rounding=ROUND_FLOOR
        )
        rebate = rebate_units * Decimal("0.01")
        next_accumulator -= rebate
        net_debit = rounded_debit - rebate
        return {
            "cost": cost,
            "tradeFee": trade_fee,
            "roundingFee": rounding_fee,
            "rebate": rebate,
            "netDebit": net_debit,
            "accumulator": next_accumulator,
        }

    for level_price, level_size in levels:
        if remaining_units <= 0 or level_price > limit_price + 1e-9:
            break
        count_units = min(remaining_units, _quantity_units(level_size))
        if count_units <= 0:
            continue
        amounts = level_amounts(level_price, count_units, rounding_accumulator)
        debit_cents = int(amounts["netDebit"] * 100)
        if total_debit_cents + debit_cents > cash_cents:
            # Debit is monotone in quantity. Find the largest affordable 0.01
            # contract slice without a potentially unbounded decrement loop.
            low, high = 0, count_units
            while low < high:
                middle = (low + high + 1) // 2
                candidate = level_amounts(level_price, middle, rounding_accumulator)
                candidate_cents = int(candidate["netDebit"] * 100)
                if total_debit_cents + candidate_cents <= cash_cents:
                    low = middle
                else:
                    high = middle - 1
            count_units = low
        if count_units <= 0:
            break
        amounts = level_amounts(level_price, count_units, rounding_accumulator)
        debit_cents = int(amounts["netDebit"] * 100)
        net_fee = amounts["tradeFee"] + amounts["roundingFee"] - amounts["rebate"]
        fills.append({
            "price_dollars": round(level_price, 4),
            "count_fp": _quantity_from_units(count_units),
            "position_cost_dollars": float(amounts["cost"]),
            "trade_fee_dollars": float(amounts["tradeFee"]),
            "rounding_fee_dollars": float(amounts["roundingFee"]),
            "rounding_rebate_dollars": float(amounts["rebate"]),
            "fee_cost_dollars": float(net_fee),
            "debit_dollars": float(amounts["netDebit"]),
        })
        total_cost += amounts["cost"]
        total_trade_fee += amounts["tradeFee"]
        total_debit_cents += debit_cents
        rounding_accumulator = amounts["accumulator"]
        remaining_units -= count_units
    fill_units = sum(_quantity_units(item["count_fp"]) for item in fills)
    fill_count = _quantity_from_units(fill_units)
    average_price = (
        float(total_cost / (Decimal(fill_units) * CONTRACT_QUANTUM))
        if fill_units
        else 0.0
    )
    return {
        "fills": fills,
        "fill_count": fill_count,
        "remaining_count": _quantity_from_units(max(0, requested_units - fill_units)),
        "average_price": average_price,
        "position_cost": float(total_cost),
        "trade_fee": float(total_trade_fee),
        "debit_cents": total_debit_cents,
        "fee_cost": (total_debit_cents / 100.0) - float(total_cost),
        "rounding_accumulator_dollars": float(rounding_accumulator),
    }


def aggregate_taker_sale(
    levels: Sequence[Tuple[float, float]],
    requested: float,
    limit_price: float,
    *,
    fee_multiplier: float = 1.0,
) -> Dict[str, Any]:
    """Price a reduce-only sale with seller-side, order-level fee rounding.

    The signed seller balance change is revenue minus trade fees, rounded
    down to a whole cent. Reusing a buyer's rounded debit as the seller fee
    would charge an extra cent for some fractional quantities. Accumulating
    before the final floor also incorporates same-order rounding rebates.
    This pure helper is shared by paper execution and live exit estimates.
    """
    fills: List[Dict[str, Any]] = []
    requested_units = _quantity_units(requested)
    remaining_units = requested_units
    gross = Decimal("0")
    trade_fee = Decimal("0")
    for level_price, level_size in levels:
        if remaining_units <= 0 or level_price + 1e-9 < limit_price:
            break
        count_units = min(remaining_units, _quantity_units(level_size))
        if count_units <= 0:
            continue
        p = Decimal(str(level_price))
        count_decimal = Decimal(count_units) * CONTRACT_QUANTUM
        level_gross = p * count_decimal
        level_fee = _ceil(
            Decimal(str(max(0.0, _number(fee_multiplier, 1.0))))
            * Decimal("0.07") * count_decimal * p * (Decimal(1) - p),
            Decimal("0.0001"),
        )
        fills.append({
            "price_dollars": round(level_price, 4),
            "count_fp": _quantity_from_units(count_units),
            "gross_proceeds_dollars": float(level_gross),
            "trade_fee_dollars": float(level_fee),
        })
        gross += level_gross
        trade_fee += level_fee
        remaining_units -= count_units
    fill_units = sum(_quantity_units(item["count_fp"]) for item in fills)
    fill_count = _quantity_from_units(fill_units)
    net_credit = max(Decimal("0"), gross - trade_fee).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
    effective_fee = gross - net_credit
    return {
        "fills": fills,
        "fill_count": fill_count,
        "remaining_count": _quantity_from_units(max(0, requested_units - fill_units)),
        "average_price": (
            float(gross / (Decimal(fill_units) * CONTRACT_QUANTUM))
            if fill_units
            else 0.0
        ),
        "gross_proceeds": float(gross),
        "trade_fee": float(trade_fee),
        "fee_cost": float(effective_fee),
        "credit_cents": int(net_credit * 100),
    }


class KalshiPaperAccountStore:
    """Thread-safe, per-user AlphaLab paper account and execution ledger."""

    def __init__(
        self,
        path: Optional[str] = None,
        *,
        starting_balance_cents: int = DEFAULT_STARTING_BALANCE_CENTS,
        account_loader=None,
        account_saver=None,
    ):
        self.path = path
        self._account_loader = account_loader
        self._account_saver = account_saver
        self.starting_balance_cents = max(10_000, int(starting_balance_cents))
        self._lock = threading.RLock()
        self._users: Dict[str, Dict[str, Any]] = {}
        if path and os.path.exists(path) and not callable(self._account_loader):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, Mapping):
                    self._users = {
                        str(key): dict(value)
                        for key, value in payload.items()
                        if isinstance(value, Mapping)
                    }
            except Exception:
                self._users = {}
        migrated = False
        for user_id, account in list(self._users.items()):
            upgraded, changed = self._upgrade_account(account)
            self._users[user_id] = upgraded
            migrated = migrated or changed
        if migrated:
            self._save_all()

    def _initial(self, starting_balance_cents: Optional[int] = None) -> Dict[str, Any]:
        initial_balance = (
            self.starting_balance_cents
            if starting_balance_cents is None
            else max(10_000, int(starting_balance_cents))
        )
        return {
            "version": PAPER_ACCOUNT_VERSION,
            "createdAt": _now(),
            "updatedAt": _now(),
            "startingBalanceCents": initial_balance,
            "dataProvenance": "kalshi_production_public_v2",
            "feeSchedule": {
                "seriesTicker": "KXBTC15M",
                "feeType": "quadratic",
                "feeMultiplier": 1.0,
                "formula": "0.07 * contracts * price * (1 - price)",
            },
            "cashCents": initial_balance,
            "realizedPnlDollars": 0.0,
            "positions": {},
            "orders": [],
            "fills": [],
            "settlements": [],
        }

    @staticmethod
    def _ledger_realized_pnl(account: Mapping[str, Any]) -> float:
        """Rebuild closed-position P/L from the immutable Paper ledger.

        Version 2 updated this account total for reduce-only sales but omitted
        expiry settlements.  That made the cash/equity total correct while the
        headline realized P/L could remain negative after profitable
        settlements.  Rebuilding from fills and settlements repairs the
        reporting field without deleting or rewriting any trade records.
        """
        total = 0.0
        seen_fills = set()
        for row in account.get("fills") or []:
            if not isinstance(row, Mapping):
                continue
            if str(row.get("action") or "").upper() != "SELL":
                continue
            identity = str(
                row.get("fill_id")
                or row.get("order_id")
                or row.get("client_order_id")
                or ""
            )
            if identity and identity in seen_fills:
                continue
            if identity:
                seen_fills.add(identity)
            total += _number(row.get("realized_pnl_dollars"))

        seen_settlements = set()
        for row in account.get("settlements") or []:
            if not isinstance(row, Mapping):
                continue
            identity = str(
                row.get("settlement_id")
                or f"{row.get('ticker')}:{row.get('settled_time')}"
            )
            if identity and identity in seen_settlements:
                continue
            if identity:
                seen_settlements.add(identity)
            total += (
                _number(row.get("revenue_dollars"))
                - _number(row.get("yes_total_cost_dollars"))
                - _number(row.get("no_total_cost_dollars"))
                - _number(row.get("fee_cost_dollars"))
                - _number(row.get("settlement_fee_dollars"))
            )
        return round(total, 4)

    def _upgrade_account(self, raw: Mapping[str, Any]) -> Tuple[Dict[str, Any], bool]:
        """Upgrade a Paper account without discarding the v2 audit ledger."""
        account = dict(raw or {})
        version = int(account.get("version") or 0)
        if version < 2:
            # Version 1 used complementary buys as closes and cannot be
            # reconciled safely into the reduce-only FIFO ledger.
            return self._initial(), True
        changed = version < PAPER_ACCOUNT_VERSION
        rebuilt_pnl = self._ledger_realized_pnl(account)
        if round(_number(account.get("realizedPnlDollars")), 4) != rebuilt_pnl:
            account["realizedPnlDollars"] = rebuilt_pnl
            changed = True
        if version != PAPER_ACCOUNT_VERSION:
            account["version"] = PAPER_ACCOUNT_VERSION
            changed = True
        return account, changed

    def _account(self, user_id: str) -> Dict[str, Any]:
        key = str(user_id)
        account = self._users.get(key)
        if account is None and callable(self._account_loader):
            restored = self._account_loader(key)
            account = dict(restored) if isinstance(restored, Mapping) else None
            if account is not None:
                self._users[key] = account
        if not isinstance(account, dict):
            account = self._initial()
            self._users[key] = account
        else:
            account, _changed = self._upgrade_account(account)
            self._users[key] = account
        return account

    def _persist_user(self, user_id: str) -> None:
        key = str(user_id)
        account = self._users.get(key)
        if not isinstance(account, dict) or not callable(self._account_saver):
            return
        try:
            saved = self._account_saver(key, copy.deepcopy(account))
        except Exception:
            # The cached ledger no longer has write authority. Drop only this
            # user's cache so the next request reloads its canonical Supabase
            # copy without disturbing unrelated accounts.
            self._users.pop(key, None)
            raise
        if isinstance(saved, Mapping) and saved.get("version") is not None:
            account["_operationsVersion"] = int(saved.get("version") or 0)

    def _save_local_snapshot(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        temporary = f"{self.path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(self._users, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, self.path)

    def _save_user(self, user_id: str) -> None:
        """Persist one changed durable account and the complete local snapshot."""
        self._persist_user(str(user_id))
        self._save_local_snapshot()

    def _save_all(self) -> None:
        """Persist every cached account for explicit bulk migrations only."""
        if callable(self._account_saver):
            for user_id in list(self._users):
                self._persist_user(str(user_id))
        self._save_local_snapshot()

    def reset(
        self,
        user_id: str,
        *,
        starting_balance_dollars: Optional[float] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            starting_balance_cents = None
            if starting_balance_dollars is not None:
                starting_balance_cents = round(float(starting_balance_dollars) * 100)
            self._users[str(user_id)] = self._initial(starting_balance_cents)
            self._save_user(user_id)
            return self.portfolio(user_id)

    @staticmethod
    def _position_value(position: Mapping[str, Any]) -> float:
        yes = _number(position.get("yesCount"))
        no = _number(position.get("noCount"))
        yes_mark = _number(position.get("yesMark"), _number(position.get("yesAveragePrice")))
        no_mark = _number(position.get("noMark"), _number(position.get("noAveragePrice")))
        return max(0.0, yes * yes_mark + no * no_mark)

    def update_mark(self, user_id: str, ticker: str, market: Mapping[str, Any]) -> None:
        with self._lock:
            position = (self._account(user_id).get("positions") or {}).get(str(ticker))
            if not isinstance(position, dict):
                return
            yes_bid = _number(market.get("yes_bid_dollars"), _number(market.get("yes_bid")) / 100.0)
            no_bid = _number(market.get("no_bid_dollars"), _number(market.get("no_bid")) / 100.0)
            if 0 < yes_bid < 1:
                position["yesMark"] = yes_bid
            if 0 < no_bid < 1:
                position["noMark"] = no_bid
            position["lastMarkedAt"] = _now()
            self._account(user_id)["updatedAt"] = _now()
            # Marks are derived from the current public book and are refreshed
            # before every portfolio response. Persisting them used to turn a
            # read-only page poll into a durable ledger write. Two healthy app
            # instances (for example during a deploy) could then collide even
            # though neither cash, positions, orders, nor fills had changed.
            # Keep the fresh mark in this process for valuation, while only
            # durable financial events call ``_save``.

    def submit_taker(
        self,
        user_id: str,
        *,
        ticker: str,
        side: str,
        price: float,
        contracts: float,
        available_depth: Optional[float] = None,
        limit_price: Optional[float] = None,
        orderbook: Optional[Mapping[str, Any]] = None,
        client_order_id: Optional[str] = None,
        market: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Immediately simulate a Paper IOC against production Kalshi book levels."""
        side = str(side or "").upper()
        ticker = str(ticker or "").strip()
        requested = _quantity_from_units(_quantity_units(contracts))
        base_price = float(price)
        limit = float(limit_price if limit_price is not None else price)
        order_id = f"paper-order-{uuid.uuid4()}"
        client_id = str(client_order_id or uuid.uuid4())
        created = _now()
        if side not in {"YES", "NO"} or not ticker or requested <= 0 or not 0 < base_price < 1 or not 0 < limit < 1:
            raise ValueError("A valid ticker, YES/NO side, price, and contract count are required")

        with self._lock:
            account = self._account(user_id)
            existing = next(
                (
                    row for row in account.get("orders") or []
                    if client_id and str((row or {}).get("client_order_id") or "") == client_id
                ),
                None,
            )
            if existing:
                return copy.deepcopy(existing)
            fee_multiplier = _market_fee_multiplier(market)
            levels = executable_ask_levels(side, orderbook)
            if not levels:
                depth = requested
                if available_depth is not None and _number(available_depth) >= 0:
                    depth = min(
                        depth,
                        _quantity_from_units(_quantity_units(available_depth)),
                    )
                if depth > 0 and base_price <= limit + 1e-9:
                    levels = [(base_price, depth)]
            execution = _aggregate_fill(
                levels,
                requested,
                limit,
                int(account.get("cashCents") or 0),
                fee_multiplier=fee_multiplier,
            )
            fill_count = _quantity_from_units(
                _quantity_units(execution["fill_count"])
            )
            avg_price = float(execution["average_price"] or 0.0)
            remaining_count = _quantity_from_units(
                _quantity_units(execution["remaining_count"])
            )
            status = (
                "filled"
                if abs(fill_count - requested) < 0.005
                else "partially_filled"
                if fill_count > 0
                else "rejected"
            )
            top_depth = sum(size for price_level, size in levels if price_level <= limit + 1e-9)
            rejection_reason = None
            if fill_count <= 0:
                rejection_reason = "insufficient_liquidity_or_price" if top_depth <= 0 else "insufficient_paper_cash"

            order = {
                "order_id": order_id,
                "client_order_id": client_id,
                "ticker": ticker,
                "outcome_side": side,
                "side": "bid" if side == "YES" else "ask",
                "type": "limit",
                "time_in_force": "immediate_or_cancel",
                "count_fp": requested,
                "fill_count_fp": fill_count,
                "remaining_count_fp": remaining_count,
                "limit_price_dollars": round(limit, 4),
                "average_price_dollars": round(avg_price, 4) if fill_count else None,
                "slippage_dollars": round(max(0.0, avg_price - base_price), 4) if fill_count else None,
                "position_cost_dollars": round(float(execution["position_cost"]), 4),
                "trade_fee_dollars": round(float(execution["trade_fee"]), 4),
                "rounding_fee_dollars": round(float(execution["fee_cost"]) - float(execution["trade_fee"]), 4),
                "fee_cost_dollars": round(float(execution["fee_cost"]), 4),
                "yes_price_dollars": round(avg_price if side == "YES" and fill_count else base_price if side == "YES" else 1.0 - (avg_price or base_price), 4),
                "no_price_dollars": round(avg_price if side == "NO" and fill_count else base_price if side == "NO" else 1.0 - (avg_price or base_price), 4),
                "status": status,
                "rejection_reason": rejection_reason,
                "matched_levels": copy.deepcopy(execution["fills"]),
                "created_time": created,
                "environment": "paper",
                "data_provenance": "kalshi_production_public_v2",
                "fee_multiplier": fee_multiplier,
            }
            account["orders"].insert(0, order)
            account["orders"] = account["orders"][:MAX_LEDGER_ROWS]
            if fill_count <= 0:
                account["updatedAt"] = created
                self._save_user(user_id)
                return copy.deepcopy(order)

            debit_cents = int(execution["debit_cents"])
            account["cashCents"] = int(account.get("cashCents") or 0) - debit_cents
            fill = {
                "fill_id": f"paper-fill-{uuid.uuid4()}",
                "order_id": order_id,
                "client_order_id": client_id,
                "ticker": ticker,
                "outcome_side": side,
                "side": order["side"],
                "count_fp": fill_count,
                "yes_price_dollars": order["yes_price_dollars"],
                "no_price_dollars": order["no_price_dollars"],
                "price_dollars": round(avg_price, 4),
                "limit_price_dollars": round(limit, 4),
                "slippage_dollars": round(max(0.0, avg_price - base_price), 4),
                "position_cost_dollars": round(float(execution["position_cost"]), 4),
                "trade_fee_dollars": round(float(execution["trade_fee"]), 4),
                "rounding_fee_dollars": round(float(execution["fee_cost"]) - float(execution["trade_fee"]), 4),
                "fee_cost_dollars": round(float(execution["fee_cost"]), 4),
                "matched_levels": copy.deepcopy(execution["fills"]),
                "created_time": created,
                "environment": "paper",
                "data_provenance": "kalshi_production_public_v2",
                "fee_multiplier": fee_multiplier,
            }
            account["fills"].insert(0, fill)
            account["fills"] = account["fills"][:MAX_LEDGER_ROWS]

            position = account["positions"].setdefault(ticker, {
                "ticker": ticker,
                "yesCount": 0,
                "noCount": 0,
                "yesCost": 0.0,
                "noCost": 0.0,
                "yesEntryFee": 0.0,
                "noEntryFee": 0.0,
                "feeCost": 0.0,
                "yesMark": 0.0,
                "noMark": 0.0,
                "marketTitle": str((market or {}).get("title") or ""),
                "closeTime": (market or {}).get("close_time"),
                "feeMultiplier": fee_multiplier,
            })
            count_key = "yesCount" if side == "YES" else "noCount"
            cost_key = "yesCost" if side == "YES" else "noCost"
            fee_key = "yesEntryFee" if side == "YES" else "noEntryFee"
            position[count_key] = round(
                _number(position.get(count_key)) + fill_count,
                2,
            )
            position[cost_key] = round(_number(position.get(cost_key)) + float(execution["position_cost"]), 4)
            position[fee_key] = round(_number(position.get(fee_key)) + float(execution["fee_cost"]), 4)
            position["feeCost"] = round(_number(position.get("feeCost")) + float(execution["fee_cost"]), 4)
            position["yesMark"] = avg_price if side == "YES" else max(0.0, 1.0 - avg_price)
            position["noMark"] = avg_price if side == "NO" else max(0.0, 1.0 - avg_price)
            position["lastTradeAt"] = created
            account["updatedAt"] = created
            self._save_user(user_id)
            return copy.deepcopy(order)

    def submit_close(
        self,
        user_id: str,
        *,
        ticker: str,
        side: str,
        price: float,
        contracts: float,
        limit_price: Optional[float] = None,
        orderbook: Optional[Mapping[str, Any]] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Simulate a reduce-only IOC sale of an existing Paper position.

        Unlike the old complementary-buy shortcut, this releases sale proceeds,
        reduces the held side, and realizes P/L immediately.  The requested size
        is always capped to the current position.
        """
        side = str(side or "").upper()
        ticker = str(ticker or "").strip()
        requested = _quantity_from_units(_quantity_units(contracts))
        base_price = float(price)
        limit = float(limit_price if limit_price is not None else price)
        order_id = f"paper-order-{uuid.uuid4()}"
        client_id = str(client_order_id or uuid.uuid4())
        created = _now()
        if side not in {"YES", "NO"} or not ticker or requested <= 0 or not 0 < base_price < 1 or not 0 < limit < 1:
            raise ValueError("A valid ticker, held side, sale price, and contract count are required")

        with self._lock:
            account = self._account(user_id)
            existing = next(
                (
                    row for row in account.get("orders") or []
                    if client_id and str((row or {}).get("client_order_id") or "") == client_id
                ),
                None,
            )
            if existing:
                return copy.deepcopy(existing)
            position = (account.get("positions") or {}).get(ticker)
            count_key = "yesCount" if side == "YES" else "noCount"
            cost_key = "yesCost" if side == "YES" else "noCost"
            fee_key = "yesEntryFee" if side == "YES" else "noEntryFee"
            held_count = _quantity_from_units(
                _quantity_units((position or {}).get(count_key))
            )
            reduce_count = min(requested, held_count)
            fee_multiplier = _number((position or {}).get("feeMultiplier"), 1.0)
            levels = executable_bid_levels(side, orderbook)
            if not levels and reduce_count > 0 and base_price + 1e-9 >= limit:
                levels = [(base_price, reduce_count)]
            execution = aggregate_taker_sale(
                levels,
                reduce_count,
                limit,
                fee_multiplier=fee_multiplier,
            ) if reduce_count > 0 else {
                "fills": [], "fill_count": 0, "remaining_count": requested,
                "average_price": 0.0, "gross_proceeds": 0.0, "trade_fee": 0.0,
                "fee_cost": 0.0, "credit_cents": 0,
            }
            fill_count = _quantity_from_units(
                _quantity_units(execution["fill_count"])
            )
            remaining_count = _quantity_from_units(
                max(0, _quantity_units(requested) - _quantity_units(fill_count))
            )
            avg_price = float(execution["average_price"] or 0.0)
            status = (
                "filled"
                if abs(fill_count - requested) < 0.005
                else "partially_filled"
                if fill_count > 0
                else "rejected"
            )
            rejection_reason = None
            if held_count <= 0:
                rejection_reason = "no_position_to_reduce"
            elif fill_count <= 0:
                rejection_reason = "insufficient_liquidity_or_price"

            held_cost = _number((position or {}).get(cost_key))
            held_entry_fee = _number((position or {}).get(fee_key))
            if held_entry_fee <= 0 and position:
                total_cost = _number(position.get("yesCost")) + _number(position.get("noCost"))
                held_entry_fee = _number(position.get("feeCost")) * (held_cost / total_cost if total_cost > 0 else 0.0)
            allocated_cost = held_cost * (fill_count / held_count) if held_count > 0 else 0.0
            allocated_entry_fee = held_entry_fee * (fill_count / held_count) if held_count > 0 else 0.0
            exit_fee = float(execution["fee_cost"])
            realized_pnl = float(execution["gross_proceeds"]) - exit_fee - allocated_cost - allocated_entry_fee
            order = {
                "order_id": order_id,
                "client_order_id": client_id,
                "ticker": ticker,
                "outcome_side": side,
                "side": "ask" if side == "YES" else "bid",
                "action": "SELL",
                "reduce_only": True,
                "type": "limit",
                "time_in_force": "immediate_or_cancel",
                "count_fp": requested,
                "fill_count_fp": fill_count,
                "remaining_count_fp": remaining_count,
                "limit_price_dollars": round(limit, 4),
                "average_price_dollars": round(avg_price, 4) if fill_count else None,
                "slippage_dollars": round(max(0.0, base_price - avg_price), 4) if fill_count else None,
                "gross_proceeds_dollars": round(float(execution["gross_proceeds"]), 4),
                "position_cost_dollars": round(allocated_cost, 4),
                "entry_fee_allocated_dollars": round(allocated_entry_fee, 4),
                "trade_fee_dollars": round(float(execution["trade_fee"]), 4),
                "fee_cost_dollars": round(exit_fee, 4),
                "realized_pnl_dollars": round(realized_pnl, 4),
                "status": status,
                "rejection_reason": rejection_reason,
                "matched_levels": copy.deepcopy(execution["fills"]),
                "created_time": created,
                "environment": "paper",
                "data_provenance": "kalshi_production_public_v2",
                "fee_multiplier": fee_multiplier,
            }
            account["orders"].insert(0, order)
            account["orders"] = account["orders"][:MAX_LEDGER_ROWS]
            if fill_count <= 0 or not isinstance(position, dict):
                account["updatedAt"] = created
                self._save_user(user_id)
                return copy.deepcopy(order)

            account["cashCents"] = int(account.get("cashCents") or 0) + int(execution["credit_cents"])
            fill = {
                **copy.deepcopy(order),
                "fill_id": f"paper-fill-{uuid.uuid4()}",
                "count_fp": fill_count,
                "price_dollars": round(avg_price, 4),
            }
            account["fills"].insert(0, fill)
            account["fills"] = account["fills"][:MAX_LEDGER_ROWS]

            position[count_key] = round(max(0.0, held_count - fill_count), 2)
            position[cost_key] = round(max(0.0, held_cost - allocated_cost), 4)
            position[fee_key] = round(max(0.0, held_entry_fee - allocated_entry_fee), 4)
            position["feeCost"] = round(max(0.0, _number(position.get("feeCost")) - allocated_entry_fee), 4)
            position["realizedPnl"] = round(_number(position.get("realizedPnl")) + realized_pnl, 4)
            position["lastTradeAt"] = created
            account["realizedPnlDollars"] = round(_number(account.get("realizedPnlDollars")) + realized_pnl, 4)
            if (
                _number(position.get("yesCount")) < 0.005
                and _number(position.get("noCount")) < 0.005
            ):
                account["positions"].pop(ticker, None)
            account["updatedAt"] = created
            self._save_user(user_id)
            return copy.deepcopy(order)

    def settle(
        self,
        user_id: str,
        ticker: str,
        result: str,
        *,
        settled_time: Optional[str] = None,
        persist: bool = True,
    ) -> Optional[Dict[str, Any]]:
        result = str(result or "").upper()
        if result not in {"YES", "NO"}:
            return None
        with self._lock:
            account = self._account(user_id)
            position = (account.get("positions") or {}).pop(str(ticker), None)
            if not isinstance(position, Mapping):
                return None
            yes_count = _quantity_from_units(_quantity_units(position.get("yesCount")))
            no_count = _quantity_from_units(_quantity_units(position.get("noCount")))
            raw_revenue = Decimal(str(yes_count if result == "YES" else no_count))
            credited_revenue = raw_revenue.quantize(
                Decimal("0.01"),
                rounding=ROUND_FLOOR,
            )
            revenue = float(credited_revenue)
            yes_cost = _number(position.get("yesCost"))
            no_cost = _number(position.get("noCost"))
            entry_fees = _number(position.get("feeCost"))
            settlement_fee = float(raw_revenue - credited_revenue)
            realized_pnl = (
                revenue
                - yes_cost
                - no_cost
                - entry_fees
                - settlement_fee
            )
            account["cashCents"] = (
                int(account.get("cashCents") or 0)
                + int(credited_revenue * 100)
            )
            row = {
                "settlement_id": f"paper-settlement-{uuid.uuid4()}",
                "ticker": str(ticker),
                "market_result": result,
                "yes_count_fp": yes_count,
                "no_count_fp": no_count,
                "revenue_dollars": round(revenue, 4),
                "yes_total_cost_dollars": round(yes_cost, 4),
                "no_total_cost_dollars": round(no_cost, 4),
                "fee_cost_dollars": round(entry_fees, 4),
                "settlement_fee_dollars": settlement_fee,
                "realized_pnl_dollars": round(realized_pnl, 4),
                "settled_time": settled_time or _now(),
                "environment": "paper",
            }
            account["settlements"].insert(0, row)
            account["settlements"] = account["settlements"][:MAX_LEDGER_ROWS]
            account["realizedPnlDollars"] = round(
                _number(account.get("realizedPnlDollars")) + realized_pnl,
                4,
            )
            account["updatedAt"] = _now()
            if persist:
                self._save_user(user_id)
            return copy.deepcopy(row)

    def open_tickers(self, user_id: str):
        with self._lock:
            return list((self._account(user_id).get("positions") or {}).keys())

    def portfolio(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            account = self._account(user_id)
            positions = []
            portfolio_value = 0.0
            for position in (account.get("positions") or {}).values():
                yes_count = _quantity_from_units(
                    _quantity_units(position.get("yesCount"))
                )
                no_count = _quantity_from_units(
                    _quantity_units(position.get("noCount"))
                )
                value = self._position_value(position)
                portfolio_value += value
                yes_cost = _number(position.get("yesCost"))
                no_cost = _number(position.get("noCost"))
                exposure = yes_cost + no_cost
                fees = _number(position.get("feeCost"))
                positions.append({
                    "ticker": position.get("ticker"),
                    "market_title": position.get("marketTitle"),
                    "close_time": position.get("closeTime"),
                    "yes_count_fp": yes_count,
                    "no_count_fp": no_count,
                    "position_fp": yes_count - no_count,
                    "market_exposure_dollars": round(exposure, 4),
                    "market_value_dollars": round(value, 4),
                    "unrealized_pnl_dollars": round(value - exposure - fees, 4),
                    "net_side": "YES" if yes_count > no_count else "NO" if no_count > yes_count else "HEDGED",
                    "net_count_fp": abs(yes_count - no_count),
                    "locked_payout_dollars": round(min(yes_count, no_count), 4),
                    "yes_average_price_dollars": round(yes_cost / yes_count, 4) if yes_count else None,
                    "no_average_price_dollars": round(no_cost / no_count, 4) if no_count else None,
                    "yes_mark_dollars": round(_number(position.get("yesMark")), 4),
                    "no_mark_dollars": round(_number(position.get("noMark")), 4),
                    "fee_cost_dollars": round(fees, 4),
                    "last_trade_at": position.get("lastTradeAt"),
                })
            return {
                "environment": "paper",
                "accountProvider": "AlphaLab",
                "balance": {
                    "balance": int(account.get("cashCents") or 0),
                    "portfolio_value": int(round(portfolio_value * 100)),
                    "starting_balance": int(account.get("startingBalanceCents") or self.starting_balance_cents),
                    "equity": int(account.get("cashCents") or 0) + int(round(portfolio_value * 100)),
                    "realized_pnl_dollars": round(
                        _number(account.get("realizedPnlDollars")),
                        4,
                    ),
                },
                "positions": positions,
                "orders": copy.deepcopy(list(account.get("orders") or [])),
                "fills": copy.deepcopy(list(account.get("fills") or [])),
                "settlements": copy.deepcopy(list(account.get("settlements") or [])),
                "asOf": _now(),
            }


__all__ = [
    "aggregate_taker_sale",
    "DEFAULT_STARTING_BALANCE_CENTS",
    "KalshiPaperAccountStore",
    "taker_fill_amounts",
]
