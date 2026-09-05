import json

from kalshi_paper import KalshiPaperAccountStore, aggregate_taker_sale, taker_fill_amounts


def test_fractional_sale_rounds_seller_credit_not_buyer_debit():
    sale = aggregate_taker_sale([(0.80, 0.33)], 0.33, 0.80)
    assert sale["trade_fee"] == 0.0037
    assert sale["gross_proceeds"] == 0.264
    assert sale["credit_cents"] == 26
    assert sale["fee_cost"] == 0.004


def test_sale_aggregates_order_rounding_and_respects_limit():
    sale = aggregate_taker_sale([(0.80, 0.33), (0.79, 0.33), (0.70, 1)], 1, 0.79)
    assert sale["fill_count"] == 0.66
    assert sale["remaining_count"] == 0.34
    assert sale["trade_fee"] == 0.0076
    assert sale["credit_cents"] == 51


def test_zero_fee_fractional_sale_still_rounds_credit_once():
    sale = aggregate_taker_sale([(0.80, 0.33)], 0.33, 0.80, fee_multiplier=0)
    assert sale["trade_fee"] == 0
    assert sale["credit_cents"] == 26
    assert sale["fee_cost"] == 0.004


def test_official_general_event_taker_fee_and_account_rounding():
    one = taker_fill_amounts(0.50, 1)
    hundred = taker_fill_amounts(0.50, 100)
    assert one["tradeFee"] == 0.0175
    assert one["debit"] == 0.52
    assert one["fee"] == 0.02
    assert hundred["tradeFee"] == 1.75
    assert hundred["debit"] == 51.75


def test_fractional_fill_uses_fixed_point_quantity_and_whole_cent_debit():
    amounts = taker_fill_amounts(0.50, 0.30)

    assert amounts["positionCost"] == 0.15
    assert amounts["tradeFee"] == 0.0053
    assert amounts["roundingFee"] == 0.0047
    assert amounts["fee"] == 0.01
    assert amounts["debit"] == 0.16


def test_fractional_paper_position_can_fill_close_and_settle(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    entry = store.submit_taker(
        "u",
        ticker="T",
        side="YES",
        price=0.50,
        contracts=0.90,
        orderbook={"no": [[0.50, 0.60], [0.49, 0.30]]},
        limit_price=0.51,
    )

    assert entry["fill_count_fp"] == 0.9
    assert entry["remaining_count_fp"] == 0.0
    assert store.portfolio("u")["positions"][0]["yes_count_fp"] == 0.9

    close = store.submit_close(
        "u",
        ticker="T",
        side="YES",
        price=0.60,
        contracts=0.35,
        orderbook={"yes": [[0.60, 0.35]]},
    )
    assert close["fill_count_fp"] == 0.35
    assert store.portfolio("u")["positions"][0]["yes_count_fp"] == 0.55

    cash_before_settlement = store.portfolio("u")["balance"]["balance"]
    settlement = store.settle("u", "T", "YES")
    assert settlement["yes_count_fp"] == 0.55
    assert settlement["revenue_dollars"] == 0.55
    assert settlement["settlement_fee_dollars"] == 0.0
    assert store.portfolio("u")["balance"]["balance"] == cash_before_settlement + 55


def test_explicit_market_fee_multiplier_is_applied_to_paper_fills(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    order = store.submit_taker(
        "u",
        ticker="T",
        side="YES",
        price=0.50,
        contracts=100,
        available_depth=100,
        market={"fee_multiplier": 2},
    )

    assert order["fee_multiplier"] == 2
    assert order["trade_fee_dollars"] == 3.5


def test_fill_updates_cash_position_and_ledger(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    order = store.submit_taker("u", ticker="T", side="YES", price=0.50, contracts=10, available_depth=7)
    portfolio = store.portfolio("u")
    assert order["status"] == "partially_filled"
    assert order["fill_count_fp"] == 7
    assert portfolio["balance"]["balance"] == 999_637
    assert portfolio["positions"][0]["yes_count_fp"] == 7
    assert portfolio["fills"][0]["fee_cost_dollars"] == 0.13


def test_paper_account_restores_from_durable_user_store_without_local_file(tmp_path):
    durable = {}

    store = KalshiPaperAccountStore(
        str(tmp_path / "ignored-local-paper.json"),
        account_loader=durable.get,
        account_saver=durable.__setitem__,
    )
    store.submit_taker("u", ticker="T", side="YES", price=0.50, contracts=2, available_depth=10)

    restored = KalshiPaperAccountStore(
        str(tmp_path / "ignored-local-paper.json"),
        account_loader=durable.get,
        account_saver=durable.__setitem__,
    ).portfolio("u")

    assert restored["positions"][0]["yes_count_fp"] == 2


def test_live_mark_refresh_does_not_write_the_durable_ledger(tmp_path):
    durable = {}
    saves = []

    def save(user_id, payload):
        durable[user_id] = payload
        saves.append((user_id, payload))

    store = KalshiPaperAccountStore(
        str(tmp_path / "paper.json"),
        account_loader=durable.get,
        account_saver=save,
    )
    store.submit_taker(
        "u", ticker="T", side="YES", price=0.50,
        contracts=2, available_depth=10,
    )
    writes_after_fill = len(saves)

    store.update_mark("u", "T", {
        "yes_bid_dollars": 0.61,
        "no_bid_dollars": 0.38,
    })
    portfolio = store.portfolio("u")

    assert len(saves) == writes_after_fill
    assert portfolio["positions"][0]["market_value_dollars"] == 1.22


def test_durable_version_is_advanced_and_stale_cache_is_invalidated(tmp_path):
    durable = {}
    calls = []

    def save(user_id, payload):
        calls.append(payload)
        if len(calls) == 1:
            durable[user_id] = payload
            return {"version": 12}
        raise RuntimeError("stale durable version")

    store = KalshiPaperAccountStore(
        str(tmp_path / "paper.json"),
        account_loader=durable.get,
        account_saver=save,
    )
    store.submit_taker(
        "u", ticker="T", side="YES", price=0.50,
        contracts=1, available_depth=2,
    )

    assert store._users["u"]["_operationsVersion"] == 12
    try:
        store.reset("u")
    except RuntimeError:
        pass
    else:
        raise AssertionError("stale write must fail")
    assert "u" not in store._users


def test_paper_account_mutations_persist_only_the_target_user(tmp_path):
    path = tmp_path / "paper.json"
    durable = {}
    versions = {}
    calls = []
    failing_users = set()

    def save(user_id, payload):
        calls.append(user_id)
        if user_id in failing_users:
            raise RuntimeError("stale durable version")
        versions[user_id] = versions.get(user_id, 0) + 1
        durable[user_id] = payload
        return {"version": versions[user_id]}

    store = KalshiPaperAccountStore(
        str(path),
        account_loader=durable.get,
        account_saver=save,
    )
    store.reset("user-a")
    store.reset("user-b")
    assert store._users["user-a"]["_operationsVersion"] == 1
    assert store._users["user-b"]["_operationsVersion"] == 1

    calls.clear()
    store.submit_taker(
        "user-a",
        ticker="KXBTC15M-TARGET",
        side="YES",
        price=0.50,
        contracts=2,
        available_depth=2,
    )
    assert calls == ["user-a"]
    assert store._users["user-a"]["_operationsVersion"] == 2
    assert store._users["user-b"]["_operationsVersion"] == 1

    calls.clear()
    store.settle("user-a", "KXBTC15M-TARGET", "YES")
    assert calls == ["user-a"]
    assert store._users["user-a"]["_operationsVersion"] == 3
    assert store._users["user-b"]["_operationsVersion"] == 1

    calls.clear()
    store.reset("user-a")
    assert calls == ["user-a"]
    assert store._users["user-a"]["_operationsVersion"] == 4
    assert store._users["user-b"]["_operationsVersion"] == 1

    local_snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert set(local_snapshot) == {"user-a", "user-b"}
    assert local_snapshot["user-b"]["_operationsVersion"] == 1

    calls.clear()
    failing_users.add("user-a")
    try:
        store.reset("user-a")
    except RuntimeError:
        pass
    else:
        raise AssertionError("stale target write must fail")
    assert calls == ["user-a"]
    assert "user-a" not in store._users
    assert store._users["user-b"]["_operationsVersion"] == 1


def test_repeated_client_order_id_is_idempotent(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    first = store.submit_taker(
        "u",
        ticker="T",
        side="YES",
        price=0.50,
        contracts=2,
        available_depth=10,
        client_order_id="stable-intent",
    )
    cash_after_first = store.portfolio("u")["balance"]["balance"]
    retry = store.submit_taker(
        "u",
        ticker="T",
        side="YES",
        price=0.50,
        contracts=2,
        available_depth=10,
        client_order_id="stable-intent",
    )
    portfolio = store.portfolio("u")

    assert retry["order_id"] == first["order_id"]
    assert portfolio["balance"]["balance"] == cash_after_first
    assert portfolio["positions"][0]["yes_count_fp"] == 2
    assert len(portfolio["orders"]) == 1
    assert len(portfolio["fills"]) == 1


def test_reset_accepts_a_fresh_custom_bankroll_and_clears_history(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    store.submit_taker("u", ticker="T", side="YES", price=0.50, contracts=2, available_depth=10)

    portfolio = store.reset("u", starting_balance_dollars=1000)

    assert portfolio["balance"]["balance"] == 100_000
    assert portfolio["orders"] == []
    assert portfolio["fills"] == []
    assert portfolio["positions"] == []


def test_ioc_uses_book_levels_average_price_and_slippage(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    order = store.submit_taker(
        "u",
        ticker="T",
        side="YES",
        price=0.50,
        limit_price=0.55,
        contracts=8,
        orderbook={"no": [[0.50, 3], [0.48, 4], [0.40, 100]]},
    )
    portfolio = store.portfolio("u")

    assert order["status"] == "partially_filled"
    assert order["fill_count_fp"] == 7
    assert order["remaining_count_fp"] == 1
    assert order["average_price_dollars"] > 0.50
    assert order["slippage_dollars"] > 0
    assert len(order["matched_levels"]) == 2
    assert portfolio["positions"][0]["yes_count_fp"] == 7


def test_multi_level_ioc_applies_kalshi_rounding_accumulator_rebates(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    order = store.submit_taker(
        "u",
        ticker="T",
        side="YES",
        price=0.055,
        limit_price=0.057,
        contracts=3,
        orderbook={"no": [[0.945, 1], [0.944, 1], [0.943, 1]]},
    )

    assert order["fill_count_fp"] == 3
    assert len(order["matched_levels"]) == 3
    assert sum(level["rounding_rebate_dollars"] for level in order["matched_levels"]) == 0.01
    assert order["fee_cost_dollars"] < sum(
        level["trade_fee_dollars"] + level["rounding_fee_dollars"]
        for level in order["matched_levels"]
    )


def test_settlement_has_no_fee_and_credits_winning_contracts(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    store.submit_taker("u", ticker="T", side="NO", price=0.25, contracts=4, available_depth=10)
    cash_after_fill = store.portfolio("u")["balance"]["balance"]
    settlement = store.settle("u", "T", "NO")
    portfolio = store.portfolio("u")
    assert settlement["revenue_dollars"] == 4.0
    assert settlement["settlement_fee_dollars"] == 0.0
    assert settlement["realized_pnl_dollars"] == 2.94
    assert portfolio["balance"]["balance"] == cash_after_fill + 400
    assert portfolio["balance"]["realized_pnl_dollars"] == 2.94
    assert portfolio["balance"]["equity"] == portfolio["balance"]["balance"]
    assert portfolio["positions"] == []


def test_read_only_settlement_updates_response_without_persisting(tmp_path):
    saves = []

    def save(_user_id, _payload):
        saves.append(1)

    store = KalshiPaperAccountStore(
        str(tmp_path / "paper.json"),
        account_saver=save,
    )
    store.submit_taker(
        "u", ticker="T", side="YES", price=0.50,
        contracts=1, available_depth=2,
    )
    writes_after_fill = len(saves)

    settlement = store.settle("u", "T", "YES", persist=False)

    assert settlement["revenue_dollars"] == 1.0
    assert len(saves) == writes_after_fill
    assert store.portfolio("u")["positions"] == []


def test_reduce_only_close_sells_held_side_and_realizes_profit(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    store.submit_taker(
        "u",
        ticker="T",
        side="YES",
        price=0.40,
        contracts=10,
        orderbook={"no": [[0.60, 10]]},
    )
    cash_after_entry = store.portfolio("u")["balance"]["balance"]

    close = store.submit_close(
        "u",
        ticker="T",
        side="YES",
        price=0.60,
        limit_price=0.59,
        contracts=4,
        orderbook={"yes": [[0.60, 4], [0.58, 20]]},
    )
    portfolio = store.portfolio("u")

    assert close["status"] == "filled"
    assert close["action"] == "SELL"
    assert close["reduce_only"] is True
    assert close["fill_count_fp"] == 4
    assert close["realized_pnl_dollars"] > 0
    assert portfolio["balance"]["balance"] > cash_after_entry
    assert portfolio["positions"][0]["yes_count_fp"] == 6
    assert portfolio["positions"][0]["no_count_fp"] == 0


def test_reduce_only_close_cannot_create_or_reverse_a_position(tmp_path):
    store = KalshiPaperAccountStore(str(tmp_path / "paper.json"))
    store.submit_taker("u", ticker="T", side="NO", price=0.30, contracts=3, available_depth=3)

    close = store.submit_close(
        "u",
        ticker="T",
        side="NO",
        price=0.50,
        contracts=9,
        orderbook={"no": [[0.50, 20]]},
    )
    cash_after_close = store.portfolio("u")["balance"]["balance"]
    repeated = store.submit_close(
        "u",
        ticker="T",
        side="NO",
        price=0.50,
        contracts=9,
        orderbook={"no": [[0.50, 20]]},
    )
    portfolio = store.portfolio("u")

    assert close["fill_count_fp"] == 3
    assert portfolio["positions"] == []
    assert repeated["status"] == "rejected"
    assert repeated["rejection_reason"] == "no_position_to_reduce"
    assert portfolio["balance"]["balance"] == cash_after_close


def test_pre_v2_account_data_is_removed_during_upgrade(tmp_path):
    path = tmp_path / "paper.json"
    path.write_text(json.dumps({"u": {
        "version": 1,
        "cashCents": 123,
        "positions": {"OLD": {"ticker": "OLD", "yesCount": 99}},
        "orders": [{"order_id": "old"}],
        "fills": [{"fill_id": "old"}],
        "settlements": [{"settlement_id": "old"}],
    }}), encoding="utf-8")

    portfolio = KalshiPaperAccountStore(str(path)).portfolio("u")

    assert portfolio["balance"]["balance"] == 1_000_000
    assert portfolio["positions"] == []
    assert portfolio["orders"] == []
    assert portfolio["fills"] == []
    assert portfolio["settlements"] == []


def test_v2_account_upgrade_preserves_ledger_and_repairs_settlement_pnl(tmp_path):
    path = tmp_path / "paper.json"
    path.write_text(json.dumps({"u": {
        "version": 2,
        "startingBalanceCents": 100_000,
        "cashCents": 100_450,
        "realizedPnlDollars": -0.5,
        "positions": {},
        "orders": [{"order_id": "kept-order"}],
        "fills": [{
            "fill_id": "closed-fill",
            "action": "SELL",
            "realized_pnl_dollars": -0.5,
        }],
        "settlements": [{
            "settlement_id": "kept-settlement",
            "ticker": "KXBTC15M-KEEP",
            "revenue_dollars": 5.0,
            "yes_total_cost_dollars": 4.0,
            "no_total_cost_dollars": 0.0,
            "fee_cost_dollars": 0.05,
            "settlement_fee_dollars": 0.0,
        }],
    }}), encoding="utf-8")

    store = KalshiPaperAccountStore(str(path))
    portfolio = store.portfolio("u")
    persisted = json.loads(path.read_text(encoding="utf-8"))["u"]

    assert persisted["version"] == 4
    assert persisted["orders"][0]["order_id"] == "kept-order"
    assert persisted["fills"][0]["fill_id"] == "closed-fill"
    assert persisted["settlements"][0]["settlement_id"] == "kept-settlement"
    assert persisted["realizedPnlDollars"] == 0.45
    assert portfolio["balance"]["realized_pnl_dollars"] == 0.45
