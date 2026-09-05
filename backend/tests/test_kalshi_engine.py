from datetime import datetime, timedelta, timezone

import pytest

from kalshi_engine import (
    MAX_ECONOMIC_SIZE_SEARCH_STEPS,
    _completed_minute_history,
    _smaller_economic_order_size,
    _worst_fill_price,
    evaluate_btc15_contract,
    kalshi_fee,
    kalshi_order_cost,
    normalize_strategy_config,
    select_btc15_market,
)


def _candles(count=90, start=64_000.0, step=1.00012):
    price = start
    values = []
    for index in range(count):
        price *= step
        values.append([index, price, price, price, price, 10.0])
    return values, price


def _market(now, **overrides):
    """Active contract inside the v3 late-entry window with the favorite side
    (YES) priced like a real Kalshi book: favorites trade in the 70s-80s."""
    value = {
        "ticker": "KXBTC15M-TEST-00",
        "status": "active",
        "title": "BTC price up in next 15 mins?",
        "open_time": (now - timedelta(minutes=11)).isoformat(),
        "close_time": (now + timedelta(minutes=4)).isoformat(),
        "floor_strike": 64_000.0,
        "yes_bid_dollars": "0.7200",
        "yes_ask_dollars": "0.7400",
        "no_bid_dollars": "0.2600",
        "no_ask_dollars": "0.2800",
        "yes_bid_size_fp": "100.0",
        "yes_ask_size_fp": "100.0",
    }
    value.update(overrides)
    return value


def _early_market(now, **overrides):
    return _market(
        now,
        open_time=(now - timedelta(minutes=5)).isoformat(),
        close_time=(now + timedelta(minutes=10)).isoformat(),
        **overrides,
    )


def _sizing_candidate(now, *, strike, yes_ask):
    candles, spot = _candles()
    yes_bid = yes_ask - 0.02
    no_bid = 1.0 - yes_ask
    return evaluate_btc15_contract(
        _market(
            now,
            floor_strike=strike,
            yes_bid_dollars=f"{yes_bid:.4f}",
            yes_ask_dollars=f"{yes_ask:.4f}",
            no_bid_dollars=f"{no_bid:.4f}",
            no_ask_dollars=f"{1.0 - yes_bid:.4f}",
            yes_bid_size_fp="1000.0",
            yes_ask_size_fp="1000.0",
        ),
        spot_price=spot,
        candles=candles,
        now=now,
        config={
            "paperBankroll": 10_000,
            "riskPerTradePct": 1.0,
            "fractionalKelly": 0.50,
            "maxBookParticipation": 0.50,
            "maxSingleMarketExposurePct": 20.0,
        },
        account_context={
            "bankroll": 10_000,
            "cashAvailable": 10_000,
            "portfolioExposure": 0,
            "currentMarketExposure": 0,
        },
        orderbook={
            "yes": [[yes_bid, 1000]],
            "no": [[no_bid, 1000]],
        },
        reference_time=now,
        book_time=now,
    )


def test_selects_active_contract_before_upcoming_contract():
    now = datetime(2026, 7, 20, 18, 0, tzinfo=timezone.utc)
    active = _market(now)
    upcoming = _market(
        now,
        ticker="KXBTC15M-NEXT-15",
        status="initialized",
        open_time=(now + timedelta(minutes=11)).isoformat(),
        close_time=(now + timedelta(minutes=26)).isoformat(),
    )

    selected, state = select_btc15_market([upcoming, active], now)

    assert state == "active"
    assert selected["ticker"] == active["ticker"]


def test_fee_uses_current_probability_weighted_formula():
    assert kalshi_fee(0.50) == pytest.approx(0.0175)
    assert kalshi_fee(0.50, 10) == pytest.approx(0.175)
    assert kalshi_fee(0.10) == pytest.approx(0.0063)
    fractional = kalshi_order_cost(0.50, 0.30)
    assert fractional["tradeFee"] == pytest.approx(0.0053)
    assert fractional["cashDebit"] == pytest.approx(0.16)
    assert fractional["roundingFee"] == pytest.approx(0.0047)
    assert fractional["allInFee"] == pytest.approx(0.01)


def test_confirmed_favorite_can_pass_all_paper_gates():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_625.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
    )

    assert result["action"] == "BUY_YES"
    assert result["paperOnly"] is True
    assert result["sizing"]["contracts"] > 0
    assert result["edge"]["netEdge"] >= result["edge"]["minimumNetEdge"]
    assert result["edge"]["modelProbability"] >= result["config"]["minModelProbability"]
    assert result["blockingReasons"] == []


def _completed_candles(now, count=90):
    candles, spot = _candles(count=count)
    for index, row in enumerate(candles):
        row[0] = (now - timedelta(minutes=count - index)).timestamp()
    return candles, spot


@pytest.mark.parametrize("ticker", ["KXBTC15M-TEST-00", "KXBTCD-TEST-T64625"])
def test_completed_history_clean_inputs_preserve_probability_and_sizing(ticker):
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    indexed, spot = _candles()
    completed, _ = _completed_candles(now)

    def evaluate(history):
        return evaluate_btc15_contract(
            _early_market(now, ticker=ticker, floor_strike=64_625.0),
            spot_price=spot, candles=history, now=now,
            reference_time=now, book_time=now,
        )

    baseline = evaluate(indexed)
    canonical = evaluate(completed)
    assert canonical["action"] == baseline["action"]
    assert canonical["blockingReasons"] == baseline["blockingReasons"]
    assert canonical["edge"] == baseline["edge"]
    assert canonical["sizing"] == baseline["sizing"]
    assert {
        key: value for key, value in canonical["model"].items()
        if key != "historyQuality"
    } == {
        key: value for key, value in baseline["model"].items()
        if key != "historyQuality"
    }
    assert canonical["model"]["historyQuality"]["status"] == "ready"


@pytest.mark.parametrize("repeat", [2, 5])
def test_duplicate_candles_do_not_inflate_sample_or_change_forecast(repeat):
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    candles, spot = _completed_candles(now)

    def evaluate(history):
        return evaluate_btc15_contract(
            _early_market(now, floor_strike=64_625.0),
            spot_price=spot, candles=history, now=now,
            reference_time=now, book_time=now,
        )

    baseline = evaluate(candles)
    repeated = evaluate(list(reversed(candles * repeat)))
    assert repeated["model"]["sampleSize"] == 89
    assert repeated["model"]["historyQuality"]["duplicateRows"] == 90 * (repeat - 1)
    for field in ("minuteVolatility", "modelYesProbability", "fairYesProbability", "momentum3m", "momentum5m", "momentum15m", "uncertainty"):
        assert repeated["model"][field] == baseline["model"][field]
    assert repeated["action"] == baseline["action"]
    assert repeated["sizing"] == baseline["sizing"]


def test_future_and_unfinished_candles_cannot_change_completed_bar_features():
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    candles, spot = _completed_candles(now)
    unfinished = [now.timestamp(), spot * 1.10, spot * 1.10, spot * 1.10, spot * 1.10, 10]
    future = [now.timestamp() + 3600, spot * 0.90, spot * 0.90, spot * 0.90, spot * 0.90, 10]
    clean, quality = _completed_minute_history(candles + [unfinished, future], now)
    expected, _ = _completed_minute_history(candles, now)

    assert clean == expected
    assert quality["incompleteRows"] == 1
    assert quality["futureRows"] == 1
    assert quality["completedRows"] == 90
    assert quality["latestCompletedAgeSeconds"] == 0
    assert quality["status"] == "ready"
    # A bucket is not complete before its exact closing boundary.
    before_boundary, _ = _completed_minute_history(candles, now - timedelta(microseconds=2))
    assert len(before_boundary) == 89


def test_current_same_venue_candle_jump_remains_guarded_when_partial_bar_is_excluded():
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    candles, spot = _completed_candles(now)
    moved_spot = spot * 1.01
    partial = [now.timestamp(), moved_spot, moved_spot, moved_spot, moved_spot, 10]
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_625.0),
        spot_price=moved_spot, candles=candles + [partial], now=now,
        reference_time=now, book_time=now,
    )

    assert result["action"] == "WAIT"
    assert "volatility_regime" in result["blockingReasons"]
    assert result["model"]["historyQuality"]["incompleteRows"] == 1
    assert result["model"]["liveCandleJumpSigma"] > result["config"]["maxJumpSigma"]
    assert result["model"]["jumpSigma"] >= result["model"]["liveCandleJumpSigma"]


def test_nonadjacent_partial_bucket_is_not_used_as_one_minute_jump_evidence():
    close_at = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    now = close_at + timedelta(seconds=30)
    candles, spot = _completed_candles(close_at)
    moved_spot = spot * 1.01
    partial = [close_at.timestamp() + 1, moved_spot, moved_spot, moved_spot, moved_spot, 10]
    _, quality = _completed_minute_history(candles + [partial], now)

    # Relative tolerance on a Unix timestamp would silently accept this
    # one-second discontinuity as an adjacent minute bucket.
    assert quality["incompleteRows"] == 1
    assert quality["currentBucketReturn"] is None


@pytest.mark.parametrize("basis_bps", [1, 3, 10, 30])
@pytest.mark.parametrize("age_seconds", [0, 30, 75, 120])
def test_reference_basis_and_elapsed_time_do_not_create_same_venue_jump(basis_bps, age_seconds):
    close_at = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    now = close_at + timedelta(seconds=age_seconds)
    candles, spot = _completed_candles(close_at)
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_625.0),
        spot_price=spot * (1 + basis_bps / 10_000), candles=candles, now=now,
        reference_time=now, book_time=now,
        reference_metadata={"isOfficialBrti": True},
    )
    assert "volatility_regime" not in result["blockingReasons"]
    assert result["model"]["liveCandleJumpSigma"] is None
    assert result["model"]["jumpSigma"] < 1
    assert result["model"]["historyQuality"]["latestCompletedAgeSeconds"] == age_seconds


def test_relative_history_is_explicitly_research_only_and_not_clock_verified():
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    candles, _ = _candles()
    clean, quality = _completed_minute_history(candles, now)

    assert len(clean) == 90
    assert quality["timestampMode"] == "relative_minute_index"
    assert quality["clockVerified"] is False
    assert quality["fresh"] is False
    assert quality["status"] == "relative_index_research_only"


@pytest.mark.parametrize("conflicting_duplicate", [False, True])
def test_recent_candle_gap_does_not_fabricate_a_one_minute_sample(conflicting_duplicate):
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    candles, spot = _completed_candles(now)
    if conflicting_duplicate:
        row = candles[-10]
        modified = row[4] * 1.0001
        candles.append([row[0], modified, modified, modified, modified, row[5]])
    else:
        candles.pop(-10)
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_625.0),
        spot_price=spot, candles=candles, now=now,
        reference_time=now, book_time=now,
    )

    assert result["action"] == "WAIT"
    assert "history_sample" in result["blockingReasons"]
    assert result["model"]["sampleSize"] == 8
    quality = result["model"]["historyQuality"]
    assert quality["completedRows"] == 9
    assert quality["gapCount"] == 1
    assert quality["status"] == "insufficient_contiguous_history"
    assert quality["conflictingTimestamps"] == int(conflicting_duplicate)


def test_old_gap_keeps_enough_recent_contiguous_evidence_without_backfill():
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    candles, _ = _completed_candles(now)
    candles.pop(5)
    clean, quality = _completed_minute_history(candles, now)

    assert len(clean) == 84
    assert quality["rowsBeforeLastGap"] == 5
    assert quality["status"] == "ready"
    assert all(right["time"] - left["time"] == 60 for left, right in zip(clean, clean[1:]))


def test_old_history_cannot_be_made_fresh_by_a_live_reference_timestamp():
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    candles, spot = _completed_candles(now - timedelta(minutes=3))
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_625.0),
        spot_price=spot, candles=candles, now=now,
        reference_time=now, book_time=now,
    )

    assert result["action"] == "WAIT"
    assert "history_sample" in result["blockingReasons"]
    assert result["model"]["historyQuality"]["status"] == "stale_completed_history"
    assert result["model"]["historyQuality"]["latestCompletedAgeSeconds"] == 180


def test_candle_timestamp_formats_and_iterators_use_the_same_normalized_history():
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    candles, spot = _completed_candles(now)
    milliseconds = [[row[0] * 1000, *row[1:]] for row in candles]
    iso_rows = [{
        "t": datetime.fromtimestamp(row[0], timezone.utc).isoformat(),
        "l": row[1], "h": row[2], "o": row[3], "c": row[4], "v": row[5],
    } for row in candles]
    expected, _ = _completed_minute_history(candles, now)
    assert _completed_minute_history(milliseconds, now)[0] == expected
    assert _completed_minute_history(iso_rows, now)[0] == expected

    def evaluate(history):
        return evaluate_btc15_contract(
            _early_market(now, floor_strike=64_625.0),
            spot_price=spot, candles=history, now=now,
            reference_time=now, book_time=now,
        )

    assert evaluate(iter(candles)) == evaluate(candles)


def test_invalid_and_mixed_timestamp_rows_do_not_enter_model_history():
    now = datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc)
    candles, spot = _completed_candles(now)
    malformed = [None, ["bad-time", spot, spot, spot, spot], [True, spot, spot, spot, spot],
                 [now.timestamp() - 30, 0, spot, spot, spot],
                 [now.timestamp() - 30, spot, spot, spot, spot * 2],
                 [now.timestamp() - 30, spot, float("nan"), spot, spot],
                 {"time": now.timestamp() - 30, "low": 0, "high": spot, "open": spot, "close": spot}]
    relative = [0, spot, spot, spot, spot]
    clean, quality = _completed_minute_history(candles + malformed + [relative], now)
    expected, _ = _completed_minute_history(candles, now)

    assert clean == expected
    assert quality["invalidRows"] == len(malformed)
    assert quality["mixedTimestampRows"] == 1


@pytest.mark.parametrize(
    ("reference_time", "book_time", "missing_detail"),
    [
        (None, "fresh", "spot timestamp missing"),
        ("fresh", None, "book timestamp missing"),
    ],
)
def test_missing_evidence_timestamp_fails_closed(
    reference_time,
    book_time,
    missing_detail,
):
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    result = evaluate_btc15_contract(
        _market(now, floor_strike=64_650.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now if reference_time == "fresh" else None,
        book_time=now if book_time == "fresh" else None,
    )

    freshness_gate = next(
        gate for gate in result["gates"] if gate["key"] == "data_freshness"
    )
    assert result["action"] == "WAIT"
    assert "data_freshness" in result["blockingReasons"]
    assert missing_detail in freshness_gate["detail"]


def test_stale_evidence_timestamp_fails_closed():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    result = evaluate_btc15_contract(
        _market(now, floor_strike=64_650.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now - timedelta(seconds=10.1),
        book_time=now - timedelta(seconds=8.1),
    )

    assert result["action"] == "WAIT"
    assert "data_freshness" in result["blockingReasons"]
    assert result["model"]["referenceAgeSeconds"] == pytest.approx(10.1)
    assert result["market"]["bookAgeSeconds"] == pytest.approx(8.1)


def test_mirrored_favorite_can_buy_no():
    now = datetime.now(timezone.utc)
    candles, _ = _candles(start=66_000.0, step=0.99988)
    spot = candles[-1][4]

    result = evaluate_btc15_contract(
        _early_market(
            now,
            floor_strike=65_400.0,
            yes_bid_dollars="0.2000",
            yes_ask_dollars="0.2200",
            no_bid_dollars="0.7800",
            no_ask_dollars="0.8000",
        ),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
    )

    assert result["action"] == "BUY_NO"
    assert result["side"] == "NO"
    assert result["sizing"]["contracts"] > 0
    assert result["blockingReasons"] == []


def test_engine_buys_the_favorite_side_not_the_longshot():
    """The engine must select the model favorite, not nominal longshot edge."""
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    result = evaluate_btc15_contract(
        _market(now, floor_strike=64_660.0),
        spot_price=spot,
        candles=candles,
        now=now,
    )

    assert result["side"] == "YES"
    assert result["edge"]["price"] >= result["config"]["minPrice"]
    assert result["model"]["selectedModelProbability"] >= 0.5
    gate_keys = [gate["key"] for gate in result["gates"]]
    assert "model_probability" in gate_keys


def test_coin_flip_contract_is_blocked_by_model_probability_gate():
    now = datetime.now(timezone.utc)
    candles, spot = _candles(step=1.0)  # flat tape: spot == strike, p ~= 0.5

    result = evaluate_btc15_contract(
        _market(
            now,
            floor_strike=round(spot, 2),
            yes_bid_dollars="0.4900",
            yes_ask_dollars="0.5100",
            no_bid_dollars="0.4900",
            no_ask_dollars="0.5100",
        ),
        spot_price=spot,
        candles=candles,
        now=now,
    )

    assert result["action"] == "WAIT"
    assert "model_probability" in result["blockingReasons"]


def test_position_size_is_not_capped_by_legacy_max_contracts():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    result = evaluate_btc15_contract(
        _early_market(
            now,
            floor_strike=64_600.0,
            yes_ask_size_fp="1000.0",
            no_ask_size_fp="1000.0",
        ),
        spot_price=spot,
        candles=candles,
        now=now,
        config={
            "paperBankroll": 100_000,
            "riskPerTradePct": 2.0,
            "fractionalKelly": 0.50,
            "maxBookParticipation": 0.50,
            "minDepthContracts": 5,
            "maxContracts": 20,
        },
        account_context={
            "bankroll": 100_000,
            "cashAvailable": 100_000,
            "portfolioExposure": 0,
            "dailyPnl": 0,
        },
        orderbook={
            "yes": [[0.72, 1000]],
            "no": [[0.26, 1000]],
        },
        reference_time=now,
        book_time=now,
    )

    assert result["action"] == "BUY_YES"
    assert result["sizing"]["contracts"] > 20


def test_small_real_account_uses_risk_equal_fractional_contracts():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_600.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        config={"executionMode": "real"},
        account_context={
            "bankroll": 19.87,
            "cashAvailable": 19.87,
            "portfolioExposure": 0,
            "currentMarketExposure": 0,
        },
    )

    assert result["action"] == "BUY_YES"
    assert result["blockingReasons"] == []
    assert 0.10 <= result["sizing"]["contracts"] < 1
    assert result["sizing"]["contractsFp"] == result["sizing"]["contracts"]
    assert result["sizing"]["fractionalSizingApplied"] is True
    assert result["sizing"]["smallAccountSizingApplied"] is True
    assert result["sizing"]["microSizingApplied"] is False
    assert result["sizing"]["standardRiskBudget"] < result["sizing"]["maximumLoss"]
    assert result["sizing"]["smallAccountUnscaledRiskTarget"] == pytest.approx(
        19.87 * 0.02
    )
    assert result["sizing"]["smallAccountRiskBudget"] <= (
        result["sizing"]["smallAccountUnscaledRiskTarget"]
        * result["sizing"]["appliedRiskScale"]
        + 1e-9
    )
    assert result["sizing"]["maximumLoss"] <= 19.87 * 0.02 + 1e-9
    assert result["sizing"]["maximumLoss"] <= result["sizing"]["riskBudget"] + 1e-9
    assert result["sizing"]["expectedValue"] > 0
    assert result["edge"]["netEdge"] >= result["config"]["microPositionMinNetEdge"]
    assert (
        result["edge"]["conservativeEdge"]
        >= result["config"]["microPositionMinConservativeEdge"]
    )


def test_small_account_override_still_respects_two_percent_relative_loss_cap():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_600.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        config={"executionMode": "real"},
        account_context={
            "bankroll": 5.0,
            "cashAvailable": 5.0,
            "portfolioExposure": 0,
            "currentMarketExposure": 0,
        },
    )

    assert result["action"] == "BUY_YES"
    assert "position_size" not in result["blockingReasons"]
    assert 0.10 <= result["sizing"]["contracts"] < 1.0
    assert result["sizing"]["microSizingApplied"] is False
    assert result["sizing"]["smallAccountSizingApplied"] is True
    assert result["sizing"]["maximumLoss"] <= 5.0 * 0.02 + 1e-9
    assert result["sizing"]["microPositionLossCap"] == pytest.approx(0.25)


def test_planned_fractional_order_uses_only_the_book_depth_it_needs():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    # Synthetic small-account fixture; it is not derived from an account.
    bankroll = 20.00

    result = evaluate_btc15_contract(
        _early_market(
            now,
            floor_strike=64_500.0,
            yes_bid_dollars="0.6800",
            yes_ask_dollars="0.7000",
            no_bid_dollars="0.3000",
            no_ask_dollars="0.3200",
        ),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        config={
            "executionMode": "real",
            "maxBookParticipation": 0.10,
        },
        account_context={
            "bankroll": bankroll,
            "cashAvailable": bankroll,
            "portfolioExposure": 0,
            "currentMarketExposure": 0,
        },
        orderbook={
            "yes": [[0.68, 10.0]],
            # YES asks are 0.70 for 0.60 contracts, then 0.79.  The full
            # positive-edge depth is 5.10, but a 10% participation order needs
            # only the first 0.51 contracts.
            "no": [[0.21, 4.50], [0.30, 0.60]],
        },
    )

    market_cap = bankroll * 0.02
    planned_cost = kalshi_order_cost(0.70, 0.51)
    far_depth_cost = kalshi_order_cost(0.79, 0.51)

    assert result["action"] == "BUY_YES"
    assert result["blockingReasons"] == []
    assert result["market"]["edgeEligibleDepth"] == pytest.approx(5.10)
    assert result["sizing"]["plannedContractsFp"] == pytest.approx(0.51)
    assert result["edge"]["price"] == pytest.approx(0.70)
    assert result["edge"]["executionLimitPrice"] == pytest.approx(0.70)
    assert far_depth_cost["cashDebit"] > market_cap
    assert result["sizing"]["maximumLoss"] == pytest.approx(
        planned_cost["cashDebit"]
    )
    assert result["sizing"]["maximumLoss"] <= result["sizing"]["riskBudget"]
    assert result["sizing"]["maximumLoss"] <= bankroll
    assert result["sizing"]["maximumLoss"] <= bankroll * 0.10
    assert result["sizing"]["maximumLoss"] <= market_cap


def test_fractional_sizing_steps_down_at_the_actual_worst_fill_price():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    # Synthetic small-account fixture; it is not derived from an account.
    bankroll = 20.00

    result = evaluate_btc15_contract(
        _early_market(
            now,
            floor_strike=64_500.0,
            yes_bid_dollars="0.6800",
            yes_ask_dollars="0.7000",
            no_bid_dollars="0.3000",
            no_ask_dollars="0.3200",
        ),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        config={
            "executionMode": "real",
            "maxBookParticipation": 0.10,
        },
        account_context={
            "bankroll": bankroll,
            "cashAvailable": bankroll,
            "portfolioExposure": 0,
            "currentMarketExposure": 0,
        },
        orderbook={
            "yes": [[0.68, 10.0]],
            # Here 0.51 contracts must cross the second level, so its 0.79
            # marginal price must drive the exact cent-rounded cap check.
            "no": [[0.21, 4.80], [0.30, 0.30]],
        },
    )

    assert result["action"] == "BUY_YES"
    assert result["sizing"]["plannedContractsFp"] < 0.51
    assert result["sizing"]["plannedContractsFp"] == pytest.approx(0.49)
    assert result["edge"]["executionLimitPrice"] == pytest.approx(0.79)
    exact_cost = kalshi_order_cost(
        result["edge"]["executionLimitPrice"],
        result["sizing"]["plannedContractsFp"],
    )
    assert result["sizing"]["maximumLoss"] == pytest.approx(
        exact_cost["cashDebit"]
    )
    assert exact_cost["cashDebit"] <= bankroll * 0.02
    # The next 0.01 contract step would breach the same synthetic cap.
    assert kalshi_order_cost(0.79, 0.50)["cashDebit"] > bankroll * 0.02


@pytest.mark.parametrize(
    ("account_context", "expected_blocker"),
    [
        ({}, "account_ready"),
        ({"bankroll": 0.0, "cashAvailable": 100.0}, "account_ready"),
        ({"bankroll": 100.0, "cashAvailable": 0.0}, "position_size"),
    ],
)
def test_real_account_missing_or_zero_funds_fail_closed(
    account_context,
    expected_blocker,
):
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_600.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        config={"executionMode": "real"},
        account_context=account_context,
    )

    assert result["action"] == "WAIT"
    assert expected_blocker in result["blockingReasons"]
    assert result["sizing"]["contractsFp"] == 0
    assert result["sizing"]["plannedContractsFp"] == 0


def test_paper_without_account_context_keeps_configured_bankroll_fallback():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_600.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
    )

    assert result["action"] == "BUY_YES"
    assert result["sizing"]["paperBankroll"] == pytest.approx(1000.0)


def test_legacy_integer_compatibility_path_keeps_bounded_micro_contract():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_600.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        config={
            "executionMode": "real",
            "fractionalContractSizingEnabled": False,
        },
        account_context={
            "bankroll": 50.0,
            "cashAvailable": 50.0,
            "portfolioExposure": 0,
            "currentMarketExposure": 0,
        },
    )

    assert result["action"] == "BUY_YES"
    assert result["sizing"]["contracts"] == 1
    assert result["sizing"]["contractStep"] == 1
    assert result["sizing"]["microSizingApplied"] is True
    assert result["sizing"]["fractionalSizingApplied"] is False


def test_rounding_economics_blocks_fractional_order_with_negative_ev():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_625.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        config={
            "executionMode": "real",
            # A smaller quantity would have positive EV, but is below this
            # configured floor and must never be used to force an entry.
            "minimumEconomicContracts": 0.18,
        },
        account_context={
            "bankroll": 19.87,
            "cashAvailable": 19.87,
            "portfolioExposure": 0,
            "currentMarketExposure": 0,
        },
    )

    assert result["action"] == "WAIT"
    assert result["blockingReasons"] == ["order_economics"]
    assert result["sizing"]["plannedContractsFp"] >= 0.10
    assert result["sizing"]["contractsFp"] == 0
    assert result["sizing"]["expectedValue"] <= 0


def test_fractional_sizing_recovers_smaller_positive_ev_order_without_more_risk():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_625.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        config={"executionMode": "real"},
        account_context={
            "bankroll": 19.87,
            "cashAvailable": 19.87,
            "portfolioExposure": 0,
            "currentMarketExposure": 0,
        },
    )

    sizing = result["sizing"]
    assert result["action"] == "BUY_YES"
    assert result["blockingReasons"] == []
    assert sizing["preEconomicContractsFp"] == pytest.approx(0.18)
    assert sizing["contractsFp"] == pytest.approx(0.17)
    assert sizing["economicSizeAdjustmentApplied"] is True
    assert sizing["economicSizeCandidatesTested"] == 2
    old_cost = kalshi_order_cost(0.74, 0.18)["cashDebit"]
    conservative_probability = result["edge"]["conservativeProbability"]
    assert conservative_probability * 0.18 - old_cost < 0
    assert sizing["maximumLoss"] < old_cost
    assert sizing["maximumLoss"] <= sizing["riskBudget"]
    assert sizing["expectedValue"] > 0
    assert sizing["feeToPotentialProfitPct"] <= 20.0


def test_fractional_economics_search_preserves_signal_blocks():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_625.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        config={"executionMode": "real", "minConservativeEdge": 0.08},
        account_context={"bankroll": 19.87, "cashAvailable": 19.87},
    )

    assert result["action"] == "WAIT"
    assert "conservative_edge" in result["blockingReasons"]
    assert result["sizing"]["economicSizeCandidatesTested"] == 0
    assert result["sizing"]["economicSizeAdjustmentApplied"] is False


def test_economic_quantity_search_grid_uses_largest_valid_smaller_size():
    # Includes hourly and BTC15 prices, varying cent-rounding phases, and a
    # second book level. This tests mechanics, not historical profitability.
    for price in (0.48, 0.60, 0.70, 0.74, 0.78, 0.80):
        levels = [(price, 0.15), (price + 0.01, 100.0)]
        for count_hundredths in range(10, 51, 2):
            original = count_hundredths / 100.0
            for probability in (price + 0.025, price + 0.04, 0.95):
                dollar_cap = kalshi_order_cost(
                    _worst_fill_price(levels, original), original
                )["cashDebit"]

                def valid(count):
                    limit = _worst_fill_price(levels, count)
                    cost = kalshi_order_cost(limit, count)
                    return (
                        probability * count - cost["cashDebit"] > 0.0
                        and cost["allInFee"] / (count * (1.0 - limit))
                        * 100.0 <= 20.0
                        and cost["cashDebit"] <= dollar_cap + 1e-12
                    )

                expected = next(
                    (
                        count / 100.0
                        for count in range(count_hundredths, 9, -1)
                        if valid(count / 100.0)
                    ),
                    original,
                )
                selected, tested = _smaller_economic_order_size(
                    levels,
                    original,
                    step=0.01,
                    minimum_contracts=0.10,
                    conservative_probability=probability,
                    dollar_cap=dollar_cap,
                    fee_rate=0.07,
                    max_fee_to_profit_pct=20.0,
                )
                assert selected == pytest.approx(expected)
                assert 0.10 <= selected <= original
                assert 1 <= tested <= count_hundredths - 9
                if selected < original:
                    assert valid(selected)
                    assert selected * 100 == pytest.approx(round(selected * 100))
                if valid(original):
                    assert tested == 1


def test_economic_quantity_search_is_bounded_and_preserves_noncent_steps():
    selected, tested = _smaller_economic_order_size(
        [(0.74, 1_000_000)],
        100_000.0,
        step=0.01,
        minimum_contracts=0.10,
        conservative_probability=0.01,
        dollar_cap=100_000.0,
        fee_rate=0.07,
        max_fee_to_profit_pct=20.0,
    )
    assert selected == 100_000.0
    assert tested == MAX_ECONOMIC_SIZE_SEARCH_STEPS
    selected, tested = _smaller_economic_order_size(
        [(0.50, 100)],
        0.15,
        step=0.05,
        minimum_contracts=0.10,
        conservative_probability=0.95,
        dollar_cap=0.07,
        fee_rate=0.07,
        max_fee_to_profit_pct=20.0,
    )
    assert selected == pytest.approx(0.10)
    assert tested == 2


def test_btc15_time_stage_premiums_only_tighten_later_windows():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    def decision(ticker, seconds):
        return evaluate_btc15_contract(
            _market(
                now,
                ticker=ticker,
                floor_strike=64_600.0,
                open_time=(now - timedelta(minutes=15)).isoformat(),
                close_time=(now + timedelta(seconds=seconds)).isoformat(),
            ),
            spot_price=spot,
            candles=candles,
            now=now,
            reference_time=now,
            book_time=now,
        )

    early = decision("KXBTC15M-EARLY", 600)
    middle = decision("KXBTC15M-MIDDLE", 300)
    late = decision("KXBTC15M-LATE", 120)
    hourly = decision("KXBTCD-HOURLY-T65000", 300)

    assert early["model"]["timeStage"] == "early"
    assert middle["model"]["timeStage"] == "middle"
    assert late["model"]["timeStage"] == "late"
    assert hourly["model"]["timeStage"] == "not_applicable"
    assert early["edge"]["timeStageEdgePremium"] == 0
    assert (
        early["edge"]["effectiveMinimumConservativeEdge"]
        < middle["edge"]["effectiveMinimumConservativeEdge"]
        < late["edge"]["effectiveMinimumConservativeEdge"]
    )
    assert hourly["edge"]["timeStageEdgePremium"] == 0


def test_recovery_multiple_adds_soft_edge_premium_without_hard_block():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    low = evaluate_btc15_contract(
        _early_market(
            now,
            floor_strike=64_400.0,
            yes_bid_dollars="0.58",
            yes_ask_dollars="0.60",
            no_bid_dollars="0.40",
            no_ask_dollars="0.42",
        ),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
    )
    high = evaluate_btc15_contract(
        _early_market(
            now,
            floor_strike=64_400.0,
            yes_bid_dollars="0.83",
            yes_ask_dollars="0.85",
            no_bid_dollars="0.15",
            no_ask_dollars="0.17",
        ),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
    )

    assert high["edge"]["recoveryMultiple"] > low["edge"]["recoveryMultiple"]
    assert high["edge"]["recoveryEdgePremium"] > low["edge"]["recoveryEdgePremium"]
    assert "recovery_asymmetry" not in high["blockingReasons"]


def test_weak_signal_receives_less_than_full_hard_risk_budget():
    now = datetime.now(timezone.utc)
    strong = _sizing_candidate(now, strike=64_625.0, yes_ask=0.74)
    weak = _sizing_candidate(now, strike=64_640.0, yes_ask=0.74)

    assert strong["action"] == "BUY_YES"
    assert weak["action"] == "BUY_YES"
    assert strong["sizing"]["qualityRiskScale"] == pytest.approx(1.0)
    assert 0 < weak["sizing"]["qualityRiskScale"] < 1.0
    assert weak["sizing"]["priceRiskScale"] == pytest.approx(1.0)
    assert (
        weak["sizing"]["riskBudget"]
        < strong["sizing"]["riskBudget"]
    )
    assert weak["sizing"]["contracts"] < strong["sizing"]["contracts"]
    assert {
        "scaledHardRiskBudget",
        "kellyRiskBudget",
        "probabilityStrength",
        "edgeStrength",
        "qualityRiskScale",
        "priceRiskScale",
        "appliedRiskScale",
    }.issubset(weak["sizing"])
    assert weak["sizing"]["riskBudget"] <= min(
        weak["sizing"]["scaledHardRiskBudget"],
        weak["sizing"]["kellyRiskBudget"],
    )
    assert (
        weak["sizing"]["scaledHardRiskBudget"]
        < weak["sizing"]["hardRiskBudget"]
    )
    assert weak["sizing"]["appliedRiskScale"] == pytest.approx(
        weak["sizing"]["qualityRiskScale"]
        * weak["sizing"]["priceRiskScale"]
    )


def test_high_price_favorite_receives_tail_loss_haircut():
    now = datetime.now(timezone.utc)
    lower_price = _sizing_candidate(now, strike=64_400.0, yes_ask=0.74)
    high_price = _sizing_candidate(now, strike=64_400.0, yes_ask=0.85)

    assert lower_price["action"] == "BUY_YES"
    assert high_price["action"] == "BUY_YES"
    assert lower_price["sizing"]["qualityRiskScale"] == pytest.approx(1.0)
    assert high_price["sizing"]["qualityRiskScale"] == pytest.approx(1.0)
    assert lower_price["sizing"]["priceRiskScale"] == pytest.approx(1.0)
    assert (
        high_price["config"]["highPriceRiskFloor"]
        <= high_price["sizing"]["priceRiskScale"]
        < 1.0
    )
    assert (
        high_price["sizing"]["scaledHardRiskBudget"]
        < lower_price["sizing"]["scaledHardRiskBudget"]
    )
    assert high_price["sizing"]["contracts"] < lower_price["sizing"]["contracts"]


def test_small_account_override_inherits_quality_and_tail_risk_haircuts():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    def decision(yes_ask):
        yes_bid = yes_ask - 0.02
        no_bid = 1.0 - yes_ask
        return evaluate_btc15_contract(
            _early_market(
                now,
                floor_strike=64_400.0,
                yes_bid_dollars=f"{yes_bid:.4f}",
                yes_ask_dollars=f"{yes_ask:.4f}",
                no_bid_dollars=f"{no_bid:.4f}",
                no_ask_dollars=f"{1.0 - yes_bid:.4f}",
            ),
            spot_price=spot,
            candles=candles,
            now=now,
            config={"executionMode": "real"},
            account_context={
                "bankroll": 22.50,
                "cashAvailable": 22.50,
                "portfolioExposure": 0.0,
                "currentMarketExposure": 0.0,
            },
            orderbook={
                "yes": [[yes_bid, 1_000]],
                "no": [[no_bid, 1_000]],
            },
            reference_time=now,
            book_time=now,
        )

    mid_price = decision(0.74)
    high_price = decision(0.85)

    assert mid_price["action"] == "BUY_YES"
    assert high_price["action"] == "BUY_YES"
    assert mid_price["sizing"]["smallAccountSizingApplied"] is True
    assert high_price["sizing"]["smallAccountSizingApplied"] is True
    assert high_price["sizing"]["priceRiskScale"] < 1.0
    assert high_price["sizing"]["smallAccountRiskBudget"] < (
        high_price["sizing"]["smallAccountUnscaledRiskTarget"]
    )
    assert high_price["sizing"]["maximumLoss"] < mid_price["sizing"]["maximumLoss"]


def test_full_bid_book_derives_executable_asks_and_depth():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    market = _market(
        now,
        floor_strike=64_660.0,
        yes_bid_dollars=None,
        yes_ask_dollars=None,
        no_bid_dollars=None,
        no_ask_dollars=None,
    )

    result = evaluate_btc15_contract(
        market,
        spot_price=spot,
        candles=candles,
        now=now,
        orderbook={
            "yes": [["0.4400", "25.00"], ["0.4800", "40.00"]],
            "no": [["0.4500", "30.00"], ["0.4900", "60.00"]],
        },
        reference_time=now,
        book_time=now,
    )

    assert result["market"]["yesBid"] == pytest.approx(0.48)
    assert result["market"]["yesAsk"] == pytest.approx(0.51)
    assert result["market"]["noBid"] == pytest.approx(0.49)
    assert result["market"]["noAsk"] == pytest.approx(0.52)
    assert result["market"]["yesAskDepth"] == pytest.approx(60.0)
    assert result["market"]["noAskDepth"] == pytest.approx(40.0)
    assert result["model"]["marketYesProbability"] is not None


def test_missing_book_never_becomes_zero_probability_or_a_trade():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    market = _market(
        now,
        yes_bid_dollars=None,
        yes_ask_dollars=None,
        no_bid_dollars=None,
        no_ask_dollars=None,
        yes_bid_size_fp=None,
        yes_ask_size_fp=None,
    )

    result = evaluate_btc15_contract(
        market,
        spot_price=spot,
        candles=candles,
        now=now,
        orderbook={"yes": [], "no": []},
        reference_time=now,
        book_time=now,
    )

    assert result["action"] == "WAIT"
    assert result["model"]["marketYesProbability"] is None
    assert result["model"]["fairYesProbability"] is None
    assert result["edge"]["price"] is None
    assert "two_sided_quote" in result["blockingReasons"]
    assert result["signalQuality"] < 50


def test_official_brti_avoids_single_venue_proxy_uncertainty_penalty():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    # Keep distance-to-strike at zero so proxy basis reserves cannot alter the
    # model/market disagreement term; this isolates the venue-count penalty.
    market = _market(now, floor_strike=spot)
    common = {
        "market": market,
        "spot_price": spot,
        "candles": candles,
        "now": now,
        "reference_time": now,
        "book_time": now,
    }

    official = evaluate_btc15_contract(
        **common,
        reference_metadata={
            "model": "kalshi_cf_benchmarks_brti",
            "isOfficialBrti": True,
            "venueCount": 1,
            "dispersionBps": 0,
        },
    )
    single_venue_proxy = evaluate_btc15_contract(
        **common,
        reference_metadata={
            "model": "brti_constituent_proxy",
            "isOfficialBrti": False,
            "venueCount": 1,
            "dispersionBps": 0,
        },
    )

    assert official["model"]["uncertainty"] == pytest.approx(
        single_venue_proxy["model"]["uncertainty"] - 0.01
    )


def test_daily_realized_loss_never_blocks_new_buy():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    common = {
        "market": _early_market(now, floor_strike=64_600.0),
        "spot_price": spot,
        "candles": candles,
        "now": now,
        "reference_time": now,
        "book_time": now,
    }
    account = {
        "bankroll": 1_000.0,
        "cashAvailable": 1_000.0,
        "portfolioExposure": 0.0,
        "currentMarketExposure": 0.0,
        "hasOpenOrder": False,
    }

    below_limit = evaluate_btc15_contract(
        **common,
        account_context={**account, "dailyPnl": -19.99},
    )
    at_limit = evaluate_btc15_contract(
        **common,
        account_context={**account, "dailyPnl": -20.00},
    )

    assert below_limit["action"] == "BUY_YES"
    assert "daily_loss_limit" not in below_limit["blockingReasons"]
    assert at_limit["action"] == "BUY_YES"
    assert "daily_loss_limit" not in at_limit["blockingReasons"]
    assert at_limit["sizing"]["contracts"] > 0
    assert at_limit["sizing"]["dailyPnl"] == pytest.approx(-20.0)
    assert at_limit["sizing"]["dailyRealizedLoss"] == pytest.approx(20.0)
    assert "dailyLossLimit" not in at_limit["sizing"]
    assert all(gate["key"] != "daily_loss_limit" for gate in at_limit["gates"])
    assert "never blocks new entries" in at_limit["methodology"]["dailyLossPolicy"]


def test_explicit_daily_realized_pnl_is_reported_without_blocking():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()

    result = evaluate_btc15_contract(
        _early_market(now, floor_strike=64_600.0),
        spot_price=spot,
        candles=candles,
        now=now,
        reference_time=now,
        book_time=now,
        account_context={
            "bankroll": 1_000.0,
            "cashAvailable": 1_000.0,
            "portfolioExposure": 0.0,
            "currentMarketExposure": 0.0,
            "dailyPnl": 50.0,
            "dailyRealizedPnl": -25.0,
        },
    )

    assert result["action"] == "BUY_YES"
    assert "daily_loss_limit" not in result["blockingReasons"]
    assert result["sizing"]["dailyPnl"] == pytest.approx(-25.0)


def test_paper_account_gates_prevent_duplicate_or_over_budget_entries():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    result = evaluate_btc15_contract(
        _market(now, floor_strike=64_660.0),
        spot_price=spot,
        candles=candles,
        now=now,
        account_context={
            "bankroll": 1_000.0,
            "cashAvailable": 500.0,
            "portfolioExposure": 300.0,
            "hasPosition": True,
            "hasOpenOrder": True,
            "alreadyTraded": True,
            "dailyTrades": 8,
            "dailyPnl": -25.0,
            "cooldownActive": True,
            "cooldownDetail": "three-loss cooldown",
        },
    )

    assert result["action"] == "WAIT"
    assert {"open_order", "portfolio_exposure"}.issubset(result["blockingReasons"])
    assert "market_flat" not in result["blockingReasons"]
    assert "loss_cooldown" not in result["blockingReasons"]
    assert result["sizing"]["contracts"] == 0

    real_result = evaluate_btc15_contract(
        _market(now, floor_strike=64_660.0),
        spot_price=spot,
        candles=candles,
        now=now,
        config={"executionMode": "real"},
        account_context={
            "bankroll": 1_000.0,
            "cashAvailable": 500.0,
            "portfolioExposure": 0.0,
            "cooldownActive": True,
            "cooldownDetail": "three-loss cooldown",
        },
    )

    assert "loss_cooldown" not in real_result["blockingReasons"]
    assert real_result["paperOnly"] is False
    assert real_result["executionEnvironment"] == "kalshi_real"
    assert "Real IOC limit order" in real_result["methodology"]["orderPolicy"]
    assert "no AI or random exploration" in real_result["methodology"]["samplePolicy"]
    account_gate = next(gate for gate in real_result["gates"] if gate["key"] == "account_ready")
    assert account_gate["label"] == "Kalshi Real account ready"


def test_missing_strike_and_late_entry_fail_closed():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    market = _market(
        now,
        floor_strike=None,
        close_time=(now + timedelta(seconds=40)).isoformat(),
    )

    result = evaluate_btc15_contract(market, spot_price=spot, candles=candles, now=now)

    assert result["action"] == "WAIT"
    assert "reference_ready" in result["blockingReasons"]
    assert "entry_window" in result["blockingReasons"]


def test_user_config_is_bounded_to_research_limits():
    config = normalize_strategy_config({
        "paperBankroll": 5,
        "riskPerTradePct": 50,
        "minNetEdge": 0,
        "minModelProbability": 0.2,
        "minimumRiskBudgetScale": -1,
        "fullRiskModelProbability": 0,
        "fullRiskConservativeEdge": 0,
        "highPriceRiskStart": 1,
        "highPriceRiskFloor": 0,
        "minimumHoldSeconds": -1,
        "reversalCooldownSeconds": 5000,
        "exitValueBuffer": 1,
        "minimumExitProfit": 1,
        "stopLossPct": 0,
        "emergencyStopLossPct": 1,
        "entryConfirmationSnapshots": 99,
        "entryConfirmationMaxGapSeconds": 1,
        "btc15EntryConfirmationMaxGapSeconds": 999,
        "protectiveExitConfirmations": 0,
        "protectiveExitConfirmationMaxGapSeconds": 999,
        "btc15ProtectiveExitConfirmationMaxGapSeconds": 1,
        "hourlyCandidatePenaltyWeight": 5,
    })

    assert config["paperBankroll"] == 100.0
    assert config["riskPerTradePct"] == 2.0
    assert "maxContracts" not in config
    assert "maxDailyLossPct" not in config
    assert config["minNetEdge"] == 0.005
    assert config["minModelProbability"] == 0.50
    assert config["minimumRiskBudgetScale"] == 0.10
    assert config["fullRiskModelProbability"] == 0.65
    assert config["fullRiskConservativeEdge"] == pytest.approx(0.0125)
    assert config["highPriceRiskStart"] == 0.90
    assert config["highPriceRiskFloor"] == 0.25
    assert config["minimumHoldSeconds"] == 0
    assert config["reversalCooldownSeconds"] == 600
    assert config["exitValueBuffer"] == 0.05
    assert config["minimumExitProfit"] == 0.10
    assert config["stopLossPct"] == 0.15
    assert config["emergencyStopLossPct"] == 0.15
    assert config["entryConfirmationSnapshots"] == 5
    assert config["entryConfirmationMaxGapSeconds"] == 5
    assert config["btc15EntryConfirmationMaxGapSeconds"] == 60
    assert config["protectiveExitConfirmations"] == 2
    assert config["protectiveExitConfirmationMaxGapSeconds"] == 60
    assert config["btc15ProtectiveExitConfirmationMaxGapSeconds"] == 15
    assert config["hourlyCandidatePenaltyWeight"] == pytest.approx(0.50)


def test_default_quality_floors_and_risk_scale_invariants():
    defaults = normalize_strategy_config()
    malformed_fractional = normalize_strategy_config({
        "fractionalContractSizingEnabled": "malformed",
    })
    constrained = normalize_strategy_config({
        "minModelProbability": 0.90,
        "fullRiskModelProbability": 0.65,
        "minConservativeEdge": 0.08,
        "fullRiskConservativeEdge": 0.01,
        "maxPrice": 0.70,
        "highPriceRiskStart": 0.90,
    })

    assert defaults["minModelProbability"] == pytest.approx(0.64)
    assert defaults["minNetEdge"] == pytest.approx(0.010)
    assert defaults["minConservativeEdge"] == pytest.approx(0.0075)
    assert defaults["maxPrice"] == pytest.approx(0.92)
    assert normalize_strategy_config({"minPrice": 0.70})[
        "minPrice"
    ] == pytest.approx(0.70)
    assert defaults["riskPerTradePct"] == pytest.approx(0.50)
    assert defaults["fractionalKelly"] == pytest.approx(0.15)
    assert defaults["fractionalContractSizingEnabled"] is True
    assert defaults["contractStep"] == pytest.approx(0.01)
    assert defaults["minimumEconomicContracts"] == pytest.approx(0.10)
    assert defaults["smallAccountRiskTargetPct"] == pytest.approx(2.00)
    assert defaults["recoveryMultipleTarget"] == pytest.approx(2.0)
    assert defaults["entryConfirmationSnapshots"] == 2
    assert defaults["entryConfirmationMaxGapSeconds"] == 25
    assert defaults["btc15EntryConfirmationMaxGapSeconds"] == 25
    assert defaults["protectiveExitConfirmations"] == 3
    assert defaults["btc15ProtectiveExitConfirmationMaxGapSeconds"] == 30
    assert defaults["hourlyCandidatePenaltyWeight"] == pytest.approx(0.10)
    assert malformed_fractional["fractionalContractSizingEnabled"] is True
    assert defaults["maxPortfolioExposurePct"] == pytest.approx(10.0)
    assert defaults["maxSingleMarketExposurePct"] == pytest.approx(2.0)
    assert defaults["minimumAddIntervalSeconds"] == 90
    assert defaults["addSizeFraction"] == pytest.approx(0.25)
    assert "maxDailyLossPct" not in defaults
    assert "maxDailyLossPct" not in constrained
    assert constrained["fullRiskModelProbability"] == pytest.approx(0.91)
    assert constrained["fullRiskConservativeEdge"] == pytest.approx(0.085)
    assert constrained["highPriceRiskStart"] == pytest.approx(0.70)


def test_v4_config_ignores_removed_learning_and_bounds_add_on_controls():
    config = normalize_strategy_config({
        "learningMode": True,
        "learningAiMode": True,
        "learningExplorationRate": 0.9,
        "maxSingleMarketExposurePct": 100,
        "minimumAddIntervalSeconds": 1,
        "addMinModelProbability": 0.99,
    })

    assert not any(key.startswith("learning") for key in config)
    assert config["maxSingleMarketExposurePct"] == 10
    assert config["minimumAddIntervalSeconds"] == 10
    assert config["addMinModelProbability"] == 0.95






def test_relative_spread_blocks_wide_percentage_friction():
    now = datetime.now(timezone.utc)
    candles, spot = _candles()
    result = evaluate_btc15_contract(
        _market(
            now,
            floor_strike=64_660.0,
            yes_bid_dollars="0.4500",
            yes_ask_dollars="0.5500",
            no_bid_dollars="0.4500",
            no_ask_dollars="0.5500",
        ),
        spot_price=spot,
        candles=candles,
        now=now,
        config={"maxSpread": 0.12, "maxRelativeSpread": 0.15},
    )

    assert "relative_spread" in result["blockingReasons"]
