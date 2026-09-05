import kalshi_api

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from kalshi_api import (
    KalshiApiError,
    _PaperRobotController,
    _account_equity_cents,
    _brti_proxy,
    _contract_quantity,
    _entry_confirmation,
    _fee_reconciliation,
    _live_order_payload,
    _live_position_direction,
    _normalise_live_fill,
    _normalise_live_order,
    _normalise_live_settlement,
    _open_live_fill_inventory,
    _reconcile_live_exit_fills,
    _scale_in_signal_improved,
    _estimate_reduce_only_sale,
    _exit_economic_state,
    _hourly_candidate_management_priority,
    _hourly_candidate_diagnostic,
    _hourly_live_strategy_config,
    _hourly_reference_policy,
    _intent_client_order_id,
    _kalshi_response_error_detail,
    _market_observation,
    _maker_shadow_diagnostic,
    _monotone_ladder_probabilities,
    _paper_account_context,
    _paper_order_payload,
    _pending_entry_confirmation_signature,
    _position_execution_context,
    _position_market_mark,
    _position_side_and_count,
    _portfolio_analytics_after_reset,
    _pnl_stability_metrics,
    _protective_exit_state,
    _protective_exit_confirmation,
    _protective_confirmation_data_quality,
    _voluntary_exit_route_economics,
    _recent_filled_entry_age,
    _recent_filled_exit_age,
    _real_preflight_account_health,
    _apply_real_preflight_health_gate,
    _venue_quote,
    _btc15_live_strategy_config,
    _btc15_shadow_challenger_config,
    _entry_shadow_diagnostic,
    _PublicDataClient,
    register_kalshi_api,
)


@pytest.mark.parametrize("timestamp,start,end", [
    ("2026-09-05T20:52:17", "2026-09-05T15:53:00Z", "2026-09-05T20:53:00Z"),
    ("2026-09-05T20:52:17+00:00", "2026-09-05T15:53:00Z", "2026-09-05T20:53:00Z"),
    ("2026-09-05T20:59:59.999999+00:00", "2026-09-05T16:00:00Z", "2026-09-05T21:00:00Z"),
    ("2026-09-05T23:59:59+00:00", "2026-09-05T19:00:00Z", "2026-09-06T00:00:00Z"),
    ("2026-09-05T23:59:59-04:00", "2026-09-05T23:00:00Z", "2026-09-06T04:00:00Z"),
])
def test_coinbase_candle_window_is_bounded_utc_and_minute_aligned(timestamp, start, end):
    params = kalshi_api._coinbase_btc_candle_params(datetime.fromisoformat(timestamp))
    assert params == {"granularity": 60, "start": start, "end": end}
    assert (datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() == 300 * 60


@pytest.mark.parametrize("use_naive", [False, True])
def test_snapshot_bounded_candle_window_preserves_shared_cache_ttl_across_minute_rollover(monkeypatch, use_naive):
    now = datetime(2026, 9, 5, 20, 59, 59, tzinfo=timezone.utc)
    http_calls, cache_calls = [], []

    def fake_get(url, params=None, **_kwargs):
        if url.endswith("/candles"):
            http_calls.append(dict(params or {}))
            return _Response([[int(now.timestamp()) - 119, 65000, 65001, 65000, 65000, 1]])
        if url.endswith("/orderbook"):
            return _Response({"orderbook_fp": {"yes_dollars": [["0.49", "100"]], "no_dollars": [["0.49", "100"]]}})
        raise AssertionError(url)

    client = _PublicDataClient(http_get=fake_get)
    monkeypatch.setattr(client, "_market_candidates", lambda *_args: ({"ticker": "KXBTC15M-WINDOW"}, "active"))
    cached_json = client._cached_json

    def capture_cache(key, url, **kwargs):
        if url.endswith("/candles"):
            cache_calls.append((key, kwargs))
        return cached_json(key, url, **kwargs)

    monkeypatch.setattr(client, "_cached_json", capture_cache)
    override = {"price": 65000, "isOfficialBrti": True, "timestamp": now.isoformat()}
    request_now = now.replace(tzinfo=None) if use_naive else now
    first = client.snapshot(now=request_now, reference_override=override)
    second = client.snapshot(now=request_now + timedelta(seconds=2), reference_override=override)
    assert len(cache_calls) == 2
    assert len(http_calls) == 1  # A new minute does not bypass the existing TTL.
    assert http_calls[0] == {"granularity": 60, "start": "2026-09-05T16:00:00Z", "end": "2026-09-05T21:00:00Z"}
    assert cache_calls[1][1]["params"]["end"] == "2026-09-05T21:01:00Z"
    for key, kwargs in cache_calls:
        assert key == "coinbase-btc-candles-1m"
        assert kwargs["ttl"] == 15.0
        assert kwargs["max_stale"] == 120.0
    assert first["reference"]["candles"] == second["reference"]["candles"]
    assert first["reference"]["candles"][0][0] == int(now.timestamp()) - 119


def test_dual_market_live_policies_are_separately_calibrated():
    base = {
        "maxPrice": 0.92,
        "minConservativeEdge": 0.0075,
        "marketBlendWeight": 0.45,
        "probabilityLogitScale": 1.70,
        "maxSecondsToClose": 1800,
        "hourlyCandidatePenaltyWeight": 0.10,
    }

    btc15 = _btc15_live_strategy_config(base)
    btc15_malformed_band = _btc15_live_strategy_config({
        **base,
        "minPrice": 0.90,
        "maxPrice": 0.55,
    })
    btc15_shadow = _btc15_shadow_challenger_config(btc15)
    hourly = _hourly_live_strategy_config(base)

    assert btc15["minPrice"] == pytest.approx(0.70)
    assert btc15["maxPrice"] == pytest.approx(0.80)
    assert btc15_malformed_band["minPrice"] == pytest.approx(0.70)
    assert btc15_malformed_band["maxPrice"] == pytest.approx(0.80)
    assert btc15["minNetEdge"] == pytest.approx(0.010)
    assert btc15["minConservativeEdge"] == pytest.approx(0.015)
    assert btc15["entryConfirmationSnapshots"] == 2
    assert btc15["btc15EntryConfirmationMaxGapSeconds"] == 25
    assert btc15_shadow["minPrice"] == pytest.approx(0.70)
    assert btc15_shadow["maxPrice"] == pytest.approx(0.80)
    assert btc15_shadow["minNetEdge"] == pytest.approx(0.005)
    assert btc15_shadow["minConservativeEdge"] == pytest.approx(0.010)
    assert btc15_shadow["btc15EntryConfirmationMaxGapSeconds"] == 45
    assert hourly["maxPrice"] == pytest.approx(0.78)
    assert hourly["maxSecondsToClose"] == 1200
    assert hourly["minNetEdge"] == pytest.approx(0.015)
    assert hourly["minConservativeEdge"] == pytest.approx(0.015)
    assert hourly["marketBlendWeight"] == pytest.approx(0.60)
    assert hourly["probabilityLogitScale"] == pytest.approx(1.50)
    assert hourly["hourlyCandidatePenaltyWeight"] == pytest.approx(0.15)


def test_entry_shadow_is_explicitly_non_routing_and_compact():
    config = _btc15_shadow_challenger_config(
        _btc15_live_strategy_config({})
    )
    diagnostic = _entry_shadow_diagnostic(
        {
            "action": "BUY_YES",
            "side": "YES",
            "signalQuality": 81,
            "market": {"secondsToClose": 600},
            "edge": {
                "price": 0.72,
                "netEdge": 0.02,
                "conservativeEdge": 0.013,
            },
            "sizing": {"plannedContractsFp": 0.30},
            "blockingReasons": [],
        },
        policy="btc15_high_band_frequency_shadow_v10",
        strategy_config=config,
    )

    assert diagnostic["opportunity"] is True
    assert diagnostic["qualifyingFrame"] is True
    assert diagnostic["routeAllowed"] is False
    assert diagnostic["confirmationPolicy"] == {
        "evaluatedOnline": False,
        "requiredSnapshots": 2,
        "maxGapSeconds": 45,
    }
    assert diagnostic["thresholds"]["minPrice"] == pytest.approx(0.70)
    assert diagnostic["thresholds"]["minNetEdge"] == pytest.approx(0.005)
    assert diagnostic["thresholds"][
        "btc15EntryConfirmationMaxGapSeconds"
    ] == 45


def test_portfolio_display_baseline_filters_only_the_visible_projection():
    lifetime = {
        "realizedTradeRecords": [
            {
                "key": "new",
                "ticker": "KXBTCD-NEW",
                "settledAt": "2026-07-25T12:01:00Z",
                "pnl": -1.25,
                "exitType": "sale",
                "environment": "paper",
            },
            {
                "key": "old",
                "ticker": "KXBTC15M-OLD",
                "settledAt": "2026-07-25T11:59:00Z",
                "pnl": 4.0,
                "exitType": "settlement",
                "environment": "paper",
            },
        ],
        "settlementRecords": [],
        "closedTradeRecords": [],
    }

    visible = _portfolio_analytics_after_reset(
        lifetime,
        {
            "resetAt": "2026-07-25T12:00:00Z",
            "baselineEquityCents": 1_000_000,
            "ledgerPreserved": True,
        },
    )

    assert [row["key"] for row in visible["realizedTradeRecords"]] == ["new"]
    assert visible["realizedSamples"] == 1
    assert visible["realizedTotalPnl"] == -1.25
    assert visible["equityCurve"][0]["displayBaseline"] is True
    assert visible["equityCurve"][0]["cumulativePnl"] == 0
    assert visible["equityCurve"][-1]["cumulativePnl"] == -1.25
    assert visible["marketPerformance"]["btc15m"]["samples"] == 0
    assert visible["marketPerformance"]["btchourly"]["samples"] == 1
    assert visible["lifetime"] == {"realizedSamples": 2, "realizedTotalPnl": 2.75}
    assert visible["displayBaseline"]["archivedRealizedEvents"] == 1


def test_brti_proxy_uses_crossed_safe_robust_constituent_midpoints():
    quotes = [
        _venue_quote("coinbase", {"bid": "9999", "ask": "10001", "price": "10000"}),
        _venue_quote("bitstamp", {"bid": "10000", "ask": "10002", "last": "10001"}),
        _venue_quote("gemini", {"bid": "10999", "ask": "11001", "last": "11000"}),
    ]

    result = _brti_proxy(quotes)

    assert result["price"] == 10000.5
    assert result["venueCount"] == 2
    assert result["rejectedVenues"] == ["gemini"]


def test_hourly_strike_ladder_fit_is_monotone_by_strike():
    markets = [
        {"ticker": "LOW", "floor_strike": 64_000},
        {"ticker": "MID", "floor_strike": 65_000},
        {"ticker": "HIGH", "floor_strike": 66_000},
    ]
    books = {
        "LOW": {"yes": [["0.39", "100"]], "no": [["0.59", "100"]]},
        "MID": {"yes": [["0.59", "100"]], "no": [["0.39", "100"]]},
        "HIGH": {"yes": [["0.29", "100"]], "no": [["0.69", "100"]]},
    }

    fitted = _monotone_ladder_probabilities(markets, books)
    probabilities = [fitted[ticker]["smoothedProbability"] for ticker in ("LOW", "MID", "HIGH")]

    assert probabilities[0] >= probabilities[1] >= probabilities[2]
    assert probabilities[0] == probabilities[1] == 0.5


def test_hourly_snapshot_fetches_strike_books_in_one_batch():
    now = datetime.now(timezone.utc)
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        params = dict(params or {})
        calls.append((url, params))
        if url.endswith("/markets") and params.get("series_ticker") == "KXBTC15M":
            return _Response({"markets": [{
                "ticker": "KXBTC15M-TEST",
                "status": "active",
                "open_time": (now - timedelta(minutes=3)).isoformat(),
                "close_time": (now + timedelta(minutes=12)).isoformat(),
                "floor_strike": 65_000,
            }]})
        if url.endswith("/events") and params.get("series_ticker") == "KXBTCD":
            return _Response({"events": [
                {
                    "event_ticker": "KXBTCD-EXPIRED",
                    "markets": [{
                        "ticker": "KXBTCD-EXPIRED-T63000",
                        "event_ticker": "KXBTCD-EXPIRED",
                        "status": "open",
                        "close_time": (now - timedelta(minutes=1)).isoformat(),
                        "floor_strike": 63_000,
                    }],
                },
                {
                    "event_ticker": "KXBTCD-E",
                    "markets": [
                        {
                            "ticker": "KXBTCD-E-T64000", "event_ticker": "KXBTCD-E",
                            "status": "active", "open_time": (now - timedelta(minutes=30)).isoformat(),
                            "close_time": (now + timedelta(minutes=30)).isoformat(),
                            "floor_strike": 64_000, "yes_bid_dollars": "0.70", "yes_ask_dollars": "0.72",
                        },
                        {
                            "ticker": "KXBTCD-E-T65000", "event_ticker": "KXBTCD-E",
                            "status": "active", "open_time": (now - timedelta(minutes=30)).isoformat(),
                            "close_time": (now + timedelta(minutes=30)).isoformat(),
                            "floor_strike": 65_000, "yes_bid_dollars": "0.49", "yes_ask_dollars": "0.51",
                        },
                    ],
                },
            ]})
        if url.endswith("/markets/orderbooks"):
            return _Response({"orderbooks": [
                {"ticker": ticker, "orderbook_fp": {
                    "yes_dollars": [["0.49", "100"]],
                    "no_dollars": [["0.49", "100"]],
                }} for ticker in params.get("tickers", [])
            ]})
        if url.endswith("/orderbook"):
            return _Response({"orderbook_fp": {
                "yes_dollars": [["0.49", "100"]],
                "no_dollars": [["0.49", "100"]],
            }})
        if url.endswith("/candles"):
            return _Response([[index, 65_000, 65_001, 65_000, 65_000, 10] for index in range(90)])
        raise AssertionError((url, params))

    snapshot = _PublicDataClient(http_get=fake_get).hourly_snapshot(
        now=now,
        reference_override={
            "price": 65_000,
            "rawPrice": 65_000,
            "timestamp": now.isoformat(),
            "model": "kalshi_cf_benchmarks_brti",
            "isOfficialBrti": True,
            "venueCount": 1,
        },
    )

    batch_calls = [call for call in calls if call[0].endswith("/markets/orderbooks")]
    hourly_event_calls = [
        call for call in calls
        if call[0].endswith("/events")
        and call[1].get("series_ticker") == "KXBTCD"
    ]
    assert len(batch_calls) == 1
    assert hourly_event_calls[0][1]["limit"] == 200
    assert hourly_event_calls[0][1]["with_nested_markets"] is True
    assert hourly_event_calls[0][1]["min_close_ts"] >= int(now.timestamp()) + 44
    assert set(batch_calls[0][1]["tickers"]) == {"KXBTCD-E-T64000", "KXBTCD-E-T65000"}
    assert len(snapshot["markets"]) == 2
    assert len(snapshot["ladderFit"]) == 2


def test_hourly_reference_uses_raw_price_except_true_top_of_hour_final_window():
    reference = {
        "price": 65_050,
        "rawPrice": 65_000,
        "settlementWindowAverage": 65_120,
        "settlementWindowSamples": 30,
        "isOfficialBrti": True,
    }
    top_close = {"close_time": "2026-07-27T13:00:00Z"}
    final = _hourly_reference_policy(
        reference,
        top_close,
        now=datetime(2026, 7, 27, 12, 59, 30, tzinfo=timezone.utc),
    )
    before_window = _hourly_reference_policy(
        reference,
        top_close,
        now=datetime(2026, 7, 27, 12, 58, 30, tzinfo=timezone.utc),
    )
    quarter_hour = _hourly_reference_policy(
        reference,
        {"close_time": "2026-07-27T13:15:00Z"},
        now=datetime(2026, 7, 27, 13, 14, 30, tzinfo=timezone.utc),
    )

    assert final["selectedSource"] == "settlement_window_average"
    assert final["selectedPrice"] == 65_120
    assert final["settlementAverageEligible"] is True
    assert before_window["selectedSource"] == "raw_price"
    assert before_window["selectedPrice"] == 65_000
    assert quarter_hour["selectedSource"] == "raw_price"
    assert quarter_hour["trueTopOfHourClose"] is False


def test_hourly_reference_never_falls_back_to_generic_price_when_raw_missing():
    policy = _hourly_reference_policy(
        {
            "price": 65_500,
            "isOfficialBrti": True,
            "settlementWindowSamples": 0,
        },
        {"close_time": "2026-07-27T13:00:00Z"},
        now=datetime(2026, 7, 27, 12, 58, 0, tzinfo=timezone.utc),
    )

    assert policy["selectedSource"] == "unavailable"
    assert policy["selectedPrice"] is None
    assert policy["fallbackPrice"] == 65_500
    assert policy["warning"] == "btc_reference_unavailable"


def test_hourly_snapshot_fails_closed_when_only_generic_price_exists():
    now = datetime(2026, 7, 27, 12, 20, tzinfo=timezone.utc)
    client = _PublicDataClient(http_get=lambda *_args, **_kwargs: None)
    client.snapshot = lambda **_kwargs: {
        "reference": {
            "price": 65_500,
            "timestamp": now.isoformat(),
            "isOfficialBrti": True,
        },
        "warnings": [],
        "sources": {},
    }
    client._cached_json = lambda _key, url, **_kwargs: {
        "events": [{
            "event_ticker": "KXBTCD-27JUL2613",
            "markets": [{
                "ticker": "KXBTCD-27JUL2613-T65000",
                "event_ticker": "KXBTCD-27JUL2613",
                "status": "active",
                "close_time": (now + timedelta(minutes=40)).isoformat(),
                "floor_strike": 65_000,
            }],
        }],
    } if url.endswith("/events") else {}

    with pytest.raises(KalshiApiError) as unavailable:
        client.hourly_snapshot(now=now)

    assert unavailable.value.code == "btc_reference_unavailable"


def test_hourly_snapshot_retains_required_held_strike_outside_nearest_32():
    now = datetime(2026, 7, 27, 12, 20, tzinfo=timezone.utc)
    event = "KXBTCD-27JUL2613"
    markets = [
        {
            "ticker": f"{event}-T{64_000 + index * 100}",
            "event_ticker": event,
            "status": "active",
            "close_time": (now + timedelta(minutes=40)).isoformat(),
            "floor_strike": 64_000 + index * 100,
            "yes_bid_dollars": "0.49",
            "yes_ask_dollars": "0.51",
        }
        for index in range(45)
    ]
    required = markets[-1]["ticker"]
    batch_tickers = []
    client = _PublicDataClient(http_get=lambda *_args, **_kwargs: None)
    client.snapshot = lambda **_kwargs: {
        "reference": {
            "price": 65_000,
            "rawPrice": 65_000,
            "timestamp": now.isoformat(),
            "candles": [],
            "isOfficialBrti": True,
        },
        "warnings": [],
        "sources": {},
    }

    def cached(_key, url, params=None, **_kwargs):
        if url.endswith("/events"):
            return {"events": [{"event_ticker": event, "markets": markets}]}
        if url.endswith("/markets/orderbooks"):
            batch_tickers.extend((params or {}).get("tickers") or [])
            return {"orderbooks": [{
                "ticker": ticker,
                "orderbook_fp": {
                    "yes_dollars": [["0.49", "100"]],
                    "no_dollars": [["0.49", "100"]],
                },
            } for ticker in (params or {}).get("tickers") or []]}
        raise AssertionError(url)

    client._cached_json = cached
    client._cache_status = lambda _key: {}
    snapshot = client.hourly_snapshot(
        now=now,
        required_tickers=[required],
    )

    assert required in batch_tickers
    assert required in {
        market["ticker"] for market in snapshot["markets"]
    }
    assert snapshot["includedRequiredTickers"] == [required]
    assert snapshot["missingRequiredTickers"] == []
    assert len(snapshot["markets"]) == 32


def test_hourly_snapshot_reports_expected_standby_when_no_event_is_in_window():
    now = datetime.now(timezone.utc)

    def fake_get(url, params=None, headers=None, timeout=None):
        params = dict(params or {})
        if url.endswith("/markets"):
            return _Response({"markets": [{
                "ticker": "KXBTC15M-TEST",
                "status": "active",
                "open_time": (now - timedelta(minutes=3)).isoformat(),
                "close_time": (now + timedelta(minutes=12)).isoformat(),
                "floor_strike": 65_000,
            }]})
        if url.endswith("/events"):
            return _Response({"events": [{
                "event_ticker": "KXBTCD-FUTURE",
                "markets": [{
                    "ticker": "KXBTCD-FUTURE-T65000",
                    "event_ticker": "KXBTCD-FUTURE",
                    "status": "open",
                    "close_time": (now + timedelta(hours=3)).isoformat(),
                    "floor_strike": 65_000,
                }],
            }]})
        if url.endswith("/orderbook"):
            return _Response({"orderbook_fp": {
                "yes_dollars": [["0.49", "100"]],
                "no_dollars": [["0.49", "100"]],
            }})
        if url.endswith("/candles"):
            return _Response([
                [index, 65_000, 65_001, 65_000, 65_000, 10]
                for index in range(90)
            ])
        raise AssertionError((url, params))

    with pytest.raises(KalshiApiError) as error:
        _PublicDataClient(http_get=fake_get).hourly_snapshot(
            now=now,
            reference_override={
                "price": 65_000,
                "timestamp": now.isoformat(),
                "model": "kalshi_cf_benchmarks_brti",
                "isOfficialBrti": True,
                "venueCount": 1,
            },
        )

    assert error.value.code == kalshi_api.KALSHI_NO_ACTIVE_HOURLY_MARKET


def test_hourly_market_gap_is_loop_standby_not_failure_or_alert():
    controller = object.__new__(_PaperRobotController)
    controller._runtime_lock = threading.RLock()
    controller._loop_last_error = "KalshiApiError"
    controller._loop_error_counts = {"user-1:btchourly": 2}
    controller._loop_alerted = {"user-1:btchourly"}
    controller._market_standby = {}
    logs = []
    controller.safe_print = logs.append

    controller._record_loop_failure(
        "user-1",
        "btchourly",
        "paper",
        KalshiApiError(
            "No hourly event in window",
            status=409,
            code=kalshi_api.KALSHI_NO_ACTIVE_HOURLY_MARKET,
        ),
    )

    assert controller._loop_error_counts == {}
    assert controller._loop_alerted == set()
    assert controller._loop_last_error == ""
    assert controller._market_standby["user-1:btchourly"]["family"] == "btchourly"
    assert "standby" in logs[0]


def test_hourly_held_market_settlement_gap_is_standby_not_failure_or_alert():
    controller = object.__new__(_PaperRobotController)
    controller._runtime_lock = threading.RLock()
    controller._loop_last_error = ""
    controller._loop_error_counts = {}
    controller._loop_alerted = set()
    controller._market_standby = {}
    controller.safe_print = lambda *_args, **_kwargs: None

    controller._record_loop_failure(
        "user-1",
        "btchourly",
        "real",
        KalshiApiError(
            "Held hourly market is closed pending settlement",
            status=409,
            code=kalshi_api.KALSHI_HOURLY_HELD_MARKET_UNAVAILABLE,
        ),
    )

    assert controller._loop_error_counts == {}
    assert controller._loop_last_error == ""
    assert controller._market_standby["user-1:btchourly"]["reason"] == (
        kalshi_api.KALSHI_HOURLY_HELD_MARKET_UNAVAILABLE
    )


def test_hourly_public_rate_limit_is_standby_not_failure_or_alert():
    notifications = []
    controller = object.__new__(_PaperRobotController)
    controller._runtime_lock = threading.RLock()
    controller._loop_last_error = ""
    controller._loop_error_counts = {}
    controller._loop_alerted = set()
    controller._market_standby = {}
    controller.safe_print = lambda *_args, **_kwargs: None
    controller._notify = lambda *args, **kwargs: notifications.append((args, kwargs))

    controller._record_loop_failure(
        "user-1",
        "btchourly",
        "real",
        KalshiApiError(
            "Kalshi public market data is temporarily rate limited",
            status=503,
            code=kalshi_api.KALSHI_PUBLIC_RATE_LIMITED,
        ),
    )

    assert controller._loop_error_counts == {}
    assert controller._loop_alerted == set()
    assert controller._market_standby["user-1:btchourly"]["reason"] == (
        kalshi_api.KALSHI_PUBLIC_RATE_LIMITED
    )
    assert notifications == []


def test_kalshi_nested_error_detail_preserves_exchange_reason():
    response = _StatusResponse(
        {
            "error": {
                "code": "invalid_order",
                "message": "market is not open for orders",
            },
        },
        400,
    )

    assert _kalshi_response_error_detail(response) == (
        "invalid_order: market is not open for orders"
    )


def test_real_read_only_preflight_blocks_stale_scheduler_account_snapshot():
    now = datetime(2026, 7, 27, 22, 5, tzinfo=timezone.utc)
    state = {
        "decisions": [{
            "generatedAt": "2026-07-27T22:02:00Z",
            "account": {
                "cashAvailable": 19.87,
                "portfolioExposure": 0.0,
            },
        }],
    }
    runtime = {
        "healthy": False,
        "threadAlive": True,
        "schedulerLeaseOwned": True,
        "lastError": (
            "KalshiApiError:kalshi_account_request_failed "
            "status=502 endpoint=/portfolio/orders"
        ),
    }
    health = _real_preflight_account_health(state, runtime, now=now)
    decision = {
        "action": "BUY_NO",
        "executionIntent": "OPEN_NO",
        "blockingReasons": [],
        "gates": [],
        "sizing": {
            "contracts": 1,
            "estimatedFee": 0.01,
            "maximumLoss": 0.90,
            "expectedValue": 0.04,
            "microSizingApplied": True,
        },
    }

    _apply_real_preflight_health_gate(decision, health)

    assert health["snapshotAgeSeconds"] == 180
    assert health["accountSnapshotFresh"] is False
    assert health["ready"] is False
    assert decision["action"] == "WAIT"
    assert decision["executionIntent"] is None
    assert decision["blockingReasons"] == [
        "account_snapshot_stale",
        "robot_scheduler_unhealthy",
    ]
    assert decision["sizing"]["contracts"] == 0
    assert decision["sizing"]["maximumLoss"] == 0
    assert {gate["key"] for gate in decision["gates"]} == {
        "account_snapshot_fresh",
        "robot_scheduler_healthy",
    }


def test_loop_failure_persists_and_alerts_with_kalshi_error_details():
    errors = []
    notifications = []
    controller = object.__new__(_PaperRobotController)
    controller._runtime_lock = threading.RLock()
    controller._loop_last_error = ""
    controller._loop_error_counts = {}
    controller._loop_alerted = set()
    controller._market_standby = {}
    controller.safe_print = lambda *_args, **_kwargs: None
    controller.state = type(
        "State",
        (),
        {"error": lambda _self, _user_id, message: errors.append(message)},
    )()
    controller._notify = (
        lambda user_id, event_type, payload:
        notifications.append((user_id, event_type, payload))
    )
    failure = KalshiApiError(
        "upstream timeout",
        status=502,
        code="kalshi_account_request_failed",
        endpoint="/portfolio/orders",
    )

    for _ in range(3):
        controller._record_loop_failure(
            "user-1",
            "btc15m",
            "real",
            failure,
        )

    assert "kalshi_account_request_failed" in errors[-1]
    assert "endpoint=/portfolio/orders" in errors[-1]
    assert "kalshi_account_request_failed" in controller._loop_last_error
    assert notifications[0][1] == "risk_alert"
    alert = notifications[0][2]
    assert alert["errorCode"] == "kalshi_account_request_failed"
    assert alert["httpStatus"] == 502
    assert alert["endpoint"] == "/portfolio/orders"
    assert "HTTP 502" in alert["reason"]
    assert "upstream timeout" in alert["reason"]


def test_venue_quote_rejects_empty_or_crossed_without_last():
    assert _venue_quote("coinbase", {"bid": "101", "ask": "100"}) is None


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _StatusResponse(_Response):
    def __init__(self, payload, status_code, *, headers=None):
        super().__init__(payload)
        self.status_code = status_code
        self.headers = dict(headers or {})

    def raise_for_status(self):
        if self.status_code < 400:
            return None
        error = RuntimeError(f"HTTP {self.status_code}")
        error.response = self
        raise error


def test_public_kalshi_429_fails_over_and_shares_host_backoff():
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        if url.startswith(kalshi_api.KALSHI_PUBLIC_BASE):
            return _StatusResponse({}, 429)
        return _StatusResponse({"markets": [{"ticker": "fallback"}]}, 200)

    client = _PublicDataClient(http_get=fake_get, safe_print=lambda *_args: None)
    first = client._cached_json(
        "first-market-list",
        f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
        ttl=0.0,
    )
    second = client._cached_json(
        "second-market-list",
        f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
        ttl=0.0,
    )

    assert first == second == {"markets": [{"ticker": "fallback"}]}
    assert calls == [
        f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
        f"{kalshi_api.KALSHI_PUBLIC_FALLBACK_BASE}/markets",
        f"{kalshi_api.KALSHI_PUBLIC_FALLBACK_BASE}/markets",
    ]
    runtime = client.runtime_snapshot()
    assert runtime["healthy"] is True
    assert runtime["status"] == "fallback"
    assert {
        row["host"] for row in runtime["activeBackoffs"]
    } == {"external-api.kalshi.com"}


def test_public_kalshi_retry_after_defers_all_callers_without_retry_storm():
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        return _StatusResponse({}, 429, headers={"Retry-After": "30"})

    client = _PublicDataClient(http_get=fake_get, safe_print=lambda *_args: None)
    with pytest.raises(KalshiApiError) as first:
        client._cached_json(
            "rate-limited-one",
            f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
            ttl=0.0,
        )
    with pytest.raises(KalshiApiError) as second:
        client._cached_json(
            "rate-limited-two",
            f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
            ttl=0.0,
        )

    assert first.value.code == second.value.code == "kalshi_public_rate_limited"
    assert len(calls) == 2
    runtime = client.runtime_snapshot()
    assert runtime["healthy"] is False
    assert runtime["status"] == "degraded"
    assert len(runtime["activeBackoffs"]) == 2
    assert min(row["retryInSeconds"] for row in runtime["activeBackoffs"]) > 25


@pytest.mark.parametrize("failure_kind", ["http_404", "invalid_json"])
def test_public_kalshi_any_complete_failure_makes_runtime_unhealthy(failure_kind):
    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        if failure_kind == "http_404":
            return _StatusResponse({}, 404)
        response = _StatusResponse({}, 200)
        response.json = lambda: (_ for _ in ()).throw(ValueError("invalid JSON"))
        return response

    client = _PublicDataClient(http_get=fake_get, safe_print=lambda *_args: None)

    with pytest.raises(KalshiApiError) as error:
        client._cached_json(
            "complete-public-failure",
            f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
            ttl=0.0,
        )

    assert error.value.code == "kalshi_public_data_unavailable"
    assert len(calls) == 2
    runtime = client.runtime_snapshot()
    assert runtime["healthy"] is False
    assert runtime["status"] == "degraded"
    assert runtime["lastError"] == "kalshi_public_data_unavailable"
    assert len(runtime["activeBackoffs"]) == (
        0 if failure_kind == "http_404" else 2
    )


def test_public_kalshi_cross_key_cold_start_shares_host_gate():
    entered = threading.Event()
    release = threading.Event()
    calls = []
    calls_lock = threading.Lock()

    def fake_get(url, **_kwargs):
        with calls_lock:
            calls.append(url)
            first_call = len(calls) == 1
        if first_call:
            entered.set()
            assert release.wait(2.0)
        return _StatusResponse({}, 429, headers={"Retry-After": "30"})

    client = _PublicDataClient(http_get=fake_get, safe_print=lambda *_args: None)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                client._cached_json,
                f"cross-key-{index}",
                f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
                ttl=0.0,
            )
            for index in range(2)
        ]
        assert entered.wait(1.0)
        release.set()
        for future in futures:
            with pytest.raises(KalshiApiError):
                future.result(timeout=3.0)

    assert len(calls) == 2
    assert {
        client._host_name(url) for url in calls
    } == {
        "external-api.kalshi.com",
        "api.elections.kalshi.com",
    }


def test_public_cache_is_bounded_and_old_stale_diagnostics_expire():
    client = _PublicDataClient(
        http_get=lambda _url, **_kwargs: _StatusResponse({"ok": True}, 200),
        safe_print=lambda *_args: None,
    )
    client._max_cache_entries = 8

    for index in range(12):
        client._cached_json(
            f"bounded-{index}",
            f"https://example.com/{index}",
            ttl=0.0,
        )

    assert len(client._cache) == 8
    assert "bounded-0" not in client._cache
    with client._cache_lock:
        key = "bounded-11"
        client._cache_meta[key].update({
            "servedStale": True,
            "servedStaleAtMonotonic": time.monotonic() - 61.0,
        })
    assert client.runtime_snapshot()["staleCacheEntries"] == 0


def test_public_cache_coalesces_concurrent_cold_refreshes():
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def fake_get(_url, **_kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(2.0)
        return _StatusResponse({"markets": [{"ticker": "single-flight"}]}, 200)

    client = _PublicDataClient(http_get=fake_get, safe_print=lambda *_args: None)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                client._cached_json,
                "shared-cold-key",
                f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
                ttl=30.0,
            )
            for _index in range(2)
        ]
        assert entered.wait(1.0)
        release.set()
        results = [future.result(timeout=2.0) for future in futures]

    assert calls == 1
    assert results[0] == results[1]


def test_public_cache_rejects_market_data_beyond_stale_safety_bound():
    fail = False

    def fake_get(_url, **_kwargs):
        if fail:
            return _StatusResponse({}, 429)
        return _StatusResponse({"markets": [{"ticker": "fresh"}]}, 200)

    client = _PublicDataClient(http_get=fake_get, safe_print=lambda *_args: None)
    key = "bounded-stale-market"
    client._cached_json(
        key,
        f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
        ttl=30.0,
        max_stale=8.0,
    )
    with client._cache_lock:
        fetched, payload = client._cache[key]
        client._cache[key] = (time.monotonic() - 9.0, payload)
    fail = True

    with pytest.raises(KalshiApiError) as error:
        client._cached_json(
            key,
            f"{kalshi_api.KALSHI_PUBLIC_BASE}/markets",
            ttl=1.0,
            max_stale=8.0,
        )

    assert error.value.code == "kalshi_public_rate_limited"
    assert client.runtime_snapshot()["healthy"] is False


def _fake_get(url, params=None, headers=None, timeout=None):
    now = datetime.now(timezone.utc)
    if url.endswith("/markets"):
        return _Response({"markets": [{
            "ticker": "KXBTC15M-TEST-00",
            "status": "active",
            "title": "BTC price up in next 15 mins?",
            "open_time": (now - timedelta(minutes=4)).isoformat(),
            "close_time": (now + timedelta(minutes=11)).isoformat(),
            "floor_strike": 64_000.0,
            "yes_bid_dollars": "0.4900",
            "yes_ask_dollars": "0.5000",
            "no_bid_dollars": "0.5000",
            "no_ask_dollars": "0.5100",
            "yes_bid_size_fp": "100.0",
            "yes_ask_size_fp": "100.0",
            "volume_fp": "1000.0",
            "open_interest_fp": "500.0",
        }]})
    if url.endswith("/orderbook"):
        return _Response({"orderbook_fp": {"yes_dollars": [["0.49", "100"]], "no_dollars": [["0.50", "100"]]}})
    if url.endswith("/ticker"):
        return _Response({"price": "64600", "bid": "64599", "ask": "64601", "time": now.isoformat()})
    if url.endswith("/candles"):
        return _Response([[index, 64_000, 64_000, 64_000, 64_000 + index, 10] for index in range(90)])
    raise AssertionError(url)


def test_live_fill_uses_current_fixed_point_dollar_fields():
    fill = _normalise_live_fill({
        "fill_id": "fill-1",
        "ticker": "KXBTC15M-TEST-00",
        "side": "yes",
        "count_fp": "12.50",
        "yes_price_dollars": "0.4300",
        "fee_cost": "0.5600",
    })

    assert fill["outcome_side"] == "YES"
    assert fill["count_fp"] == 12.5
    assert fill["price_dollars"] == 0.43
    assert fill["fee_cost_dollars"] == 0.56


def test_account_equity_adds_cash_and_position_value_in_both_modes():
    balance = {"balance": 80_000, "portfolio_value": 100_000}

    assert _account_equity_cents(balance, "real") == 180_000
    assert _account_equity_cents(balance, "paper") == 180_000
    assert _account_equity_cents({"balance": 80_000}, "real") == 80_000


def test_hourly_account_context_aggregates_positions_and_open_orders_by_event():
    event = "KXBTCD-27JUL2613"
    selected = f"{event}-T65000"
    sibling = f"{event}-T65100"
    portfolio = {
        "balance": {"balance": 100_000},
        "positions": [
            {
                "ticker": selected,
                "event_ticker": event,
                "position_fp": 2,
                "market_exposure_dollars": 6.0,
            },
            {
                "ticker": sibling,
                "event_ticker": event,
                "position_fp": 3,
                "market_exposure_dollars": 8.0,
            },
            {
                "ticker": "KXBTCD-27JUL2614-T65000",
                "event_ticker": "KXBTCD-27JUL2614",
                "position_fp": 1,
                "market_exposure_dollars": 4.0,
            },
        ],
        "orders": [
            {
                "ticker": sibling,
                "event_ticker": event,
                "status": "resting",
                "remaining_count_fp": 2,
                "limit_price_dollars": 0.50,
            },
            {
                "ticker": selected,
                "event_ticker": event,
                "status": "filled",
                "count_fp": 10,
                "limit_price_dollars": 0.50,
            },
            {
                "ticker": "KXBTCD-27JUL2614-T65100",
                "event_ticker": "KXBTCD-27JUL2614",
                "status": "pending",
                "remaining_count_fp": 2,
                "limit_price_dollars": 0.50,
            },
        ],
        "fills": [],
    }

    context = _paper_account_context(
        portfolio,
        {"strategy": {}, "tradedTickers": []},
        selected,
        1_000,
        event_ticker=event,
    )

    assert context["currentTickerExposure"] == 6.0
    assert context["currentEventPositionExposure"] == 14.0
    assert context["currentEventOpenOrderExposure"] == 1.0
    assert context["currentMarketExposure"] == 15.0
    assert context["portfolioExposure"] == 20.0
    assert context["hasPosition"] is True
    assert context["hasEventPosition"] is True
    assert context["hasOpenOrder"] is True
    assert context["openOrderTickers"] == [sibling]


def test_live_position_direction_never_labels_flat_exposure_as_yes():
    assert _live_position_direction(0, 0, 0) == (None, 0.0)
    assert _live_position_direction(0, 7, 7) == (None, 0.0)
    assert _live_position_direction(3, 0, 0) == ("YES", 3.0)
    assert _live_position_direction(-4, 0, 0) == ("NO", 4.0)
    assert _live_position_direction(0, 2, 5) == ("NO", 3.0)


def test_real_tick_with_zero_cash_fails_closed_without_routing(monkeypatch):
    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "enabled": True,
                "config": {"executionMode": environment or "real"},
                "strategy": {},
                "tradedTickers": [],
            }

        def record(self, _user_id, decision, order):
            return {"decision": decision, "order": order}

    class Client:
        def snapshot(self, *, base_url):
            return {
                "market": {"ticker": "KXBTC15M-TEST-00"},
                "reference": {"price": 65_000, "candles": [], "timestamp": "2026-07-22T12:00:00Z"},
                "orderbook": {},
                "orderbookAsOf": "2026-07-22T12:00:00Z",
            }

    decision = {
        "action": "BUY_YES",
        "side": "YES",
        "model": {"fairYesProbability": 0.65},
        "edge": {"price": 0.50},
        "sizing": {"contracts": 5, "notional": 2.5},
        "gates": [],
        "blockingReasons": [],
        "config": {"executionMode": "real"},
    }
    evaluation_calls = []

    def evaluate_with_shadow_failure(*_args, **_kwargs):
        evaluation_calls.append(1)
        if len(evaluation_calls) == 2:
            raise RuntimeError("shadow-only failure")
        return copy.deepcopy(decision)

    monkeypatch.setattr(
        kalshi_api,
        "evaluate_btc15_contract",
        evaluate_with_shadow_failure,
    )
    controller = _PaperRobotController(Client(), State(), paper_accounts=None)
    monkeypatch.setattr(
        controller,
        "portfolio",
        lambda _user_id, *, mode: {
            "balance": {"balance": 0, "portfolio_value": 0},
            "positions": [],
            "orders": [],
            "fills": [],
        },
    )

    result = controller.tick("user-1", submit_order=True, mode="real")

    assert result["orderSubmitted"] is False
    assert result["decision"]["action"] == "WAIT"
    assert result["decision"]["executionIntent"] == "WAIT_REAL_NO_CASH"
    assert "real_cash_unavailable" in result["decision"]["blockingReasons"]
    assert result["decision"]["sizing"]["contracts"] == 0
    assert len(evaluation_calls) == 2
    assert result["decision"]["entryShadow"]["champion"][
        "routeAllowed"
    ] is True
    challenger = result["decision"]["entryShadow"]["frequencyChallenger"]
    assert challenger["routeAllowed"] is False
    assert challenger["evaluationError"] == "RuntimeError"
    assert challenger["blockingReasons"] == ["shadow_evaluation_error"]


def test_hourly_tick_manages_held_strike_and_suppresses_higher_edge_sibling(
    monkeypatch,
):
    event = "KXBTCD-27JUL2613"
    held = f"{event}-T65000"
    sibling = f"{event}-T65100"
    captured = {}

    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "enabled": True,
                "activeEnvironment": "paper",
                "config": {"executionMode": environment or "paper"},
                    "strategy": {},
                    "tradedTickers": [],
                    "filledTrades": [],
                }

    class Client:
        def hourly_snapshot(self, **kwargs):
            captured.update(kwargs)
            markets = [
                {
                    "ticker": held,
                    "event_ticker": event,
                    "status": "active",
                    "close_time": "2026-07-27T13:00:00Z",
                    "floor_strike": 65_000,
                },
                {
                    "ticker": sibling,
                    "event_ticker": event,
                    "status": "active",
                    "close_time": "2026-07-27T13:00:00Z",
                    "floor_strike": 65_100,
                },
            ]
            return {
                "eventTicker": event,
                "markets": markets,
                "orderbooks": {
                    ticker: {
                        "yes": [["0.40", "100"]],
                        "no": [["0.58", "100"]],
                    }
                    for ticker in (held, sibling)
                },
                "ladderFit": {},
                "reference": {
                    "price": 65_050,
                    "rawPrice": 65_000,
                    "candles": [],
                    "timestamp": "2026-07-27T12:30:00Z",
                    "isOfficialBrti": True,
                },
                "referencePolicy": {
                    "policy": "kxbtcd_raw_reference_v1",
                    "selectedSource": "raw_price",
                    "selectedPrice": 65_000,
                },
                "orderbookAsOf": "2026-07-27T12:30:00Z",
                "warnings": [],
            }

    def evaluate(market, *_args, **_kwargs):
        is_held = market["ticker"] == held
        return {
            "generatedAt": "2026-07-27T12:30:00Z",
            "action": "WAIT" if is_held else "BUY_YES",
            "side": "YES",
            "model": {"fairYesProbability": 0.75},
            "market": {
                "ticker": market["ticker"],
                "yesAskDepth": 100,
                "secondsToClose": 1800,
            },
            "edge": {
                "price": 0.42,
                "conservativeEdge": 0.01 if is_held else 0.20,
                "netEdge": 0.02 if is_held else 0.25,
            },
            "sizing": {"contracts": 0 if is_held else 5},
            "gates": [],
            "blockingReasons": ["position_size"] if is_held else [],
            "config": {"executionMode": "paper"},
        }

    monkeypatch.setattr(kalshi_api, "evaluate_btc15_contract", evaluate)
    controller = _PaperRobotController(
        Client(),
        State(),
        None,
        portfolio_display_loader=lambda _user_id: {
            "modes": {
                "paper": {
                    "resetAt": "2026-07-27T12:00:00Z",
                    "environment": "paper",
                    "ledgerPreserved": True,
                    "alphaLabOnly": False,
                },
            },
        },
    )
    monkeypatch.setattr(
        controller,
        "portfolio",
        lambda *_args, **_kwargs: {
            "environment": "paper",
            "balance": {"balance": 100_000, "portfolio_value": 84},
            "positions": [{
                "ticker": held,
                "event_ticker": event,
                "position_fp": 2,
                "yes_count_fp": 2,
                "yes_average_price_dollars": 0.42,
                "market_exposure_dollars": 0.84,
                "last_trade_at": "2026-07-27T12:20:00Z",
            }],
            "orders": [],
            "fills": [],
            "settlements": [],
            "analytics": {
                "realizedTradeRecords": [{
                    "ticker": "KXBTCD-OLD-T64000",
                    "settledAt": "2026-07-27T11:00:00Z",
                    "pnl": 1.0,
                }],
            },
        },
    )

    result = controller.tick(
        "user-1",
        submit_order=False,
        mode="paper",
        family="btchourly",
    )

    assert captured["required_tickers"] == [held]
    assert result["snapshot"]["market"]["ticker"] == held
    assert result["decision"]["managementPriority"]["active"] is True
    assert result["decision"]["managementPriority"][
        "suppressedNewStrikeTickers"
    ] == [sibling]
    assert result["orderSubmitted"] is False
    assert result["portfolio"]["analytics"]["displayBaseline"]["active"] is True
    assert result["portfolio"]["analytics"]["realizedSamples"] == 0


@pytest.mark.parametrize(
    "warning",
    [
        "kalshi_market_stale",
        "kalshi_orderbook_stale",
        "hourly_markets_stale",
        "hourly_orderbooks_unavailable",
        "brti_proxy_stale",
        "btc_history_stale",
        "kalshi_account_history_incomplete",
        "kalshi_account_orders_incomplete",
        "kalshi_account_positions_incomplete",
    ],
)
def test_tick_never_routes_when_execution_input_is_not_fresh(monkeypatch, warning):
    account_warning = warning.startswith("kalshi_account_")
    execution_mode = "real" if account_warning else "paper"

    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "enabled": True,
                "activeEnvironment": execution_mode,
                "config": {"executionMode": environment or execution_mode},
                "strategy": {},
                "tradedTickers": [],
            }

        def record(self, _user_id, decision, order):
            return {"decision": decision, "order": order}

    class Client:
        def snapshot(self, *, base_url):
            return {
                "market": {"ticker": "KXBTC15M-TEST-00"},
                "reference": {
                    "price": 65_000,
                    "candles": [],
                    "timestamp": "2026-07-26T12:00:00Z",
                },
                "orderbook": {
                    "yes": [["0.49", "100"]],
                    "no": [["0.49", "100"]],
                },
                "orderbookAsOf": "2026-07-26T12:00:00Z",
                "warnings": [] if account_warning else [warning],
            }

    decision = {
        "action": "BUY_YES",
        "side": "YES",
        "model": {"fairYesProbability": 0.75},
        "market": {"yesAskDepth": 100},
        "edge": {"price": 0.50, "conservativeEdge": 0.05},
        "sizing": {"contracts": 5, "notional": 2.5},
        "gates": [],
        "blockingReasons": [],
        "config": {"executionMode": execution_mode},
    }
    monkeypatch.setattr(
        kalshi_api,
        "evaluate_btc15_contract",
        lambda *args, **kwargs: decision,
    )
    controller = _PaperRobotController(Client(), State(), paper_accounts=None)
    monkeypatch.setattr(
        controller,
        "portfolio",
        lambda _user_id, *, mode, mutate=False: {
            "balance": {"balance": 100_000, "portfolio_value": 0},
            "positions": [],
            "orders": [],
            "fills": [],
            "settlements": [],
            "warnings": [warning] if account_warning else [],
            "completeness": {"complete": not account_warning},
        },
    )

    result = controller.tick("user-1", submit_order=True, mode=execution_mode)

    assert result["orderSubmitted"] is False
    assert result["decision"]["action"] == "WAIT"
    assert result["decision"]["executionIntent"] == "WAIT_DATA_QUALITY"
    assert result["decision"]["dataQuality"]["executionBlocked"] is True
    assert result["decision"]["dataQuality"]["executionBlockingWarnings"] == [warning]
    assert "market_data_not_fresh" in result["decision"]["blockingReasons"]


def test_same_side_signal_becomes_add_on_without_a_trade_count_gate(monkeypatch):
    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "enabled": True,
                "config": {
                    "executionMode": environment or "paper",
                    "minimumAddIntervalSeconds": 30,
                    "addMinModelProbability": 0.67,
                    "addMinConservativeEdge": 0.01,
                },
                "strategy": {},
                "tradedTickers": ["KXBTC15M-TEST-00"],
                "filledTrades": [{
                    "ticker": "KXBTC15M-TEST-00",
                    "side": "YES",
                    "action": "BUY_YES",
                    "orderFilled": True,
                    "orderId": "prior-entry",
                    "fairProbability": 0.72,
                    "conservativeEdge": 0.02,
                }],
            }

        def record(self, _user_id, decision, order):
            return {"decisions": [decision]}

    class Client:
        def snapshot(self, *, base_url):
            return {
                "market": {"ticker": "KXBTC15M-TEST-00"},
                "reference": {"price": 65_000, "candles": [], "timestamp": "2026-07-25T12:00:00Z"},
                "orderbook": {"yes": [["0.60", "100"]], "no": [["0.38", "100"]]},
                "orderbookAsOf": "2026-07-25T12:00:00Z",
            }

    decision = {
        "generatedAt": "2026-07-25T12:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "model": {"fairYesProbability": 0.74},
        "edge": {
            "price": 0.62,
            "modelProbability": 0.74,
            "conservativeEdge": 0.03,
        },
        "sizing": {"contracts": 3},
        "gates": [],
        "blockingReasons": [],
        "config": {"executionMode": "paper"},
    }
    monkeypatch.setattr(
        kalshi_api,
        "evaluate_btc15_contract",
        lambda *args, **kwargs: decision,
    )
    controller = _PaperRobotController(Client(), State(), paper_accounts=None)
    monkeypatch.setattr(
        controller,
        "portfolio",
        lambda _user_id, *, mode: {
            "balance": {"balance": 99_000, "portfolio_value": 300},
            "positions": [{
                "ticker": "KXBTC15M-TEST-00",
                "yes_count_fp": 5,
                "no_count_fp": 0,
                "yes_average_price_dollars": 0.55,
                "market_exposure_dollars": 2.75,
                "last_trade_at": "2020-01-01T00:00:00Z",
            }],
            "orders": [],
            "fills": [],
            "settlements": [],
        },
    )

    result = controller.tick("user-1", submit_order=False, mode="paper")

    assert result["decision"]["action"] == "BUY_YES"
    assert result["decision"]["executionIntent"] == "ADD_YES"
    assert result["decision"]["positionManagement"]["existingContracts"] == 5
    assert "market_flat" not in result["decision"]["blockingReasons"]


def test_scale_in_requires_probability_and_edge_to_improve_together():
    previous = {"probability": 0.70, "conservativeEdge": 0.02}

    assert _scale_in_signal_improved(None, 0.80, 0.08, 0.01, 0.001) is False
    assert _scale_in_signal_improved(previous, 0.72, 0.022, 0.01, 0.001) is True
    assert _scale_in_signal_improved(previous, 0.72, 0.0205, 0.01, 0.001) is False
    assert _scale_in_signal_improved(previous, 0.705, 0.022, 0.01, 0.001) is False


def test_real_tick_never_manages_manual_contracts_in_selected_ticker(monkeypatch):
    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "enabled": True,
                "activeEnvironment": "real",
                "config": {"executionMode": "real"},
                "strategy": {},
                "tradedTickers": [],
                "filledTrades": [],
            }

        def record(self, _user_id, decision, order):
            return {"decision": decision, "order": order}

    class Client:
        def snapshot(self, *, base_url):
            return {
                "market": {"ticker": "KXBTC15M-MANUAL"},
                "reference": {
                    "price": 65_000,
                    "candles": [],
                    "timestamp": "2026-07-27T12:00:00Z",
                },
                "orderbook": {
                    "yes": [["0.49", "100"]],
                    "no": [["0.49", "100"]],
                },
                "orderbookAsOf": "2026-07-27T12:00:00Z",
                "warnings": [],
            }

    monkeypatch.setattr(
        kalshi_api,
        "evaluate_btc15_contract",
        lambda *_args, **_kwargs: {
            "action": "BUY_YES",
            "side": "YES",
            "model": {"fairYesProbability": 0.75},
            "market": {"yesAskDepth": 100},
            "edge": {"price": 0.50, "conservativeEdge": 0.05},
            "sizing": {"contracts": 5, "notional": 2.5},
            "gates": [],
            "blockingReasons": [],
            "config": {"executionMode": "real"},
        },
    )
    controller = _PaperRobotController(Client(), State(), None)
    monkeypatch.setattr(
        controller,
        "portfolio",
        lambda *_args, **_kwargs: {
            "environment": "real",
            "balance": {"balance": 100_000, "portfolio_value": 100},
            "positions": [{
                "ticker": "KXBTC15M-MANUAL",
                "position_fp": 2,
                "net_count_fp": 2,
                "net_side": "YES",
                "alphaLabManaged": False,
                "alphaLabManagedCount": 0,
                "alphaLabUnmanagedCount": 2,
            }],
            "orders": [],
            "fills": [],
            "settlements": [],
            "warnings": [],
            "completeness": {"complete": True},
        },
    )

    result = controller.tick("user-1", submit_order=True, mode="real")

    assert result["orderSubmitted"] is False
    assert result["decision"]["action"] == "WAIT"
    assert result["decision"]["executionIntent"] == "WAIT_UNMANAGED_POSITION_CONFLICT"
    assert "unmanaged_position_conflict" in result["decision"]["blockingReasons"]
    assert result["decision"]["account"]["unmanagedPositionCount"] == 2


def test_live_exit_fill_reconciliation_uses_fifo_cost_and_both_fees():
    rows = _reconcile_live_exit_fills([
        {
            "fill_id": "buy-1", "ticker": "KXBTC15M-TEST-00",
            "outcome_side": "NO", "action": "buy", "count_fp": 4,
            "average_price_dollars": 0.30, "fee_cost_dollars": 0.04,
            "created_time": "2026-07-22T12:00:00Z",
        },
        {
            "fill_id": "buy-2", "ticker": "KXBTC15M-TEST-00",
            "outcome_side": "NO", "action": "buy", "count_fp": 6,
            "average_price_dollars": 0.40, "fee_cost_dollars": 0.06,
            "created_time": "2026-07-22T12:01:00Z",
        },
        {
            "fill_id": "sell-1", "ticker": "KXBTC15M-TEST-00",
            "outcome_side": "NO", "action": "sell", "count_fp": 5,
            "average_price_dollars": 0.55, "fee_cost_dollars": 0.05,
            "created_time": "2026-07-22T12:02:00Z",
        },
    ])

    sale = rows[-1]
    assert sale["reduce_only"] is True
    assert sale["position_cost_dollars"] == 1.6
    assert sale["entry_fee_allocated_dollars"] == 0.05
    assert sale["gross_proceeds_dollars"] == 2.75
    assert sale["realized_pnl_dollars"] == 1.05


def test_live_exit_fill_reconciliation_skips_unknown_cost_basis():
    rows = _reconcile_live_exit_fills([{
        "fill_id": "sell-only", "ticker": "KXBTC15M-TEST-00",
        "outcome_side": "YES", "action": "sell", "count_fp": 3,
        "average_price_dollars": 0.60, "fee_cost_dollars": 0.03,
        "created_time": "2026-07-22T12:02:00Z",
    }])

    assert "realized_pnl_dollars" not in rows[0]


def test_trade_intent_id_is_stable_for_retries_and_rotates_by_window():
    first = _intent_client_order_id("u", "real", "T", "BUY_YES", "YES", 0, now_epoch=100)
    retry = _intent_client_order_id("u", "real", "T", "BUY_YES", "YES", 0, now_epoch=109)
    later = _intent_client_order_id("u", "real", "T", "BUY_YES", "YES", 0, now_epoch=110)
    changed_position = _intent_client_order_id("u", "real", "T", "BUY_YES", "YES", 2, now_epoch=100)

    assert retry == first
    assert later != first
    assert changed_position != first


def test_market_observation_uses_a_stable_15_second_bucket():
    decision = {
        "generatedAt": "2026-07-25T12:00:14Z",
        "action": "BUY_YES",
        "side": "YES",
        "executionIntent": "ADD_YES",
        "signalQuality": 78,
        "blockingReasons": [],
        "market": {
            "ticker": "KXBTC15M-TEST",
            "secondsToClose": 140,
            "spread": 0.02,
        },
        "model": {
            "modelYesProbability": 0.72,
            "fairYesProbability": 0.69,
        },
        "edge": {
            "price": 0.62,
            "netEdge": 0.04,
            "conservativeEdge": 0.02,
        },
        "entryShadow": {
            "frequencyChallenger": {
                "routeAllowed": False,
                "qualifyingFrame": True,
            },
        },
    }

    first = _market_observation(
        "paper",
        decision,
        source="scheduler",
        submit_order=True,
    )
    second = _market_observation(
        "paper",
        {**decision, "generatedAt": "2026-07-25T12:00:01Z"},
        source="scheduler",
        submit_order=True,
    )

    assert first["observation_key"] == second["observation_key"]
    assert first["execution_intent"] == "ADD_YES"
    assert first["environment"] == "paper"
    assert first["features"]["observation"] == {
        "source": "scheduler",
        "submitOrder": True,
        "samplingPolicy": "routine_15s",
        "bucketSeconds": 15,
        "hasOrderResult": False,
    }
    assert first["features"]["entryShadow"]["frequencyChallenger"] == {
        "routeAllowed": False,
        "qualifyingFrame": True,
    }


def test_market_observation_separates_scheduler_and_browser_in_same_bucket():
    decision = {
        "generatedAt": "2026-08-30T12:00:14Z",
        "action": "WAIT",
        "market": {"ticker": "KXBTC15M-SOURCE", "secondsToClose": 600},
    }

    scheduler = _market_observation(
        "real",
        decision,
        source="scheduler",
        submit_order=True,
    )
    browser = _market_observation(
        "real",
        decision,
        source="browser_read_only",
        submit_order=False,
    )

    assert scheduler["observation_key"] != browser["observation_key"]
    assert ":scheduler:routine:" in scheduler["observation_key"]
    assert ":browser_read_only:routine:" in browser["observation_key"]
    assert scheduler["features"]["observation"]["submitOrder"] is True
    assert browser["features"]["observation"]["submitOrder"] is False


def test_market_observation_order_event_cannot_be_erased_by_read_only_wait():
    decision = {
        "generatedAt": "2026-08-30T12:00:04Z",
        "action": "BUY_NO",
        "side": "NO",
        "market": {"ticker": "KXBTC15M-ORDER", "secondsToClose": 500},
    }
    order = {
        "order_id": "order-123",
        "client_order_id": "client-123",
        "status": "executed",
        "action": "buy",
        "outcome_side": "no",
        "count_fp": 0.30,
        "fill_count_fp": 0.30,
    }

    submitted = _market_observation(
        "real",
        decision,
        order,
        source="scheduler",
        submit_order=True,
    )
    read_only = _market_observation(
        "real",
        {**decision, "action": "WAIT"},
        source="browser_read_only",
        submit_order=False,
    )

    assert submitted["order_result"]["order_id"] == "order-123"
    assert submitted["observation_key"] != read_only["observation_key"]
    assert ":order:" in submitted["observation_key"]
    assert submitted["features"]["observation"] == {
        "source": "scheduler",
        "submitOrder": True,
        "samplingPolicy": "order_event_unique",
        "bucketSeconds": 0,
        "hasOrderResult": True,
    }
    assert read_only["order_result"] is None


def test_market_observation_retains_confirmation_transitions_at_five_seconds():
    decision = {
        "generatedAt": "2026-08-30T12:00:01Z",
        "action": "WAIT",
        "side": "YES",
        "market": {"ticker": "KXBTC15M-CONFIRM", "secondsToClose": 400},
        "entryConfirmation": {
            "required": True,
            "streak": 1,
            "confirmed": False,
        },
        "entryShadow": {"champion": {"qualifyingFrame": True}},
    }
    first = _market_observation(
        "real", decision, source="scheduler", submit_order=True,
    )
    confirmed = _market_observation(
        "real",
        {
            **decision,
            "generatedAt": "2026-08-30T12:00:04Z",
            "entryConfirmation": {
                "required": True,
                "streak": 2,
                "confirmed": True,
            },
        },
        source="scheduler",
        submit_order=True,
    )

    assert first["observation_key"] != confirmed["observation_key"]
    assert ":confirmation:s1-c0:" in first["observation_key"]
    assert ":confirmation:s2-c1:" in confirmed["observation_key"]
    assert first["features"]["observation"]["bucketSeconds"] == 5
    assert confirmed["features"]["observation"]["samplingPolicy"] == (
        "entry_confirmation_5s"
    )


def test_market_observation_champion_frame_uses_five_second_bucket():
    decision = {
        "generatedAt": "2026-08-30T12:00:04Z",
        "action": "WAIT",
        "market": {"ticker": "KXBTC15M-CHAMP", "secondsToClose": 300},
        "entryShadow": {"champion": {"qualifyingFrame": True}},
    }
    first = _market_observation(
        "real", decision, source="scheduler", submit_order=True,
    )
    second = _market_observation(
        "real",
        {**decision, "generatedAt": "2026-08-30T12:00:06Z"},
        source="scheduler",
        submit_order=True,
    )

    assert first["observation_key"] != second["observation_key"]
    assert ":champion:" in first["observation_key"]
    assert first["features"]["observation"]["samplingPolicy"] == (
        "champion_qualifying_5s"
    )


def test_live_settlement_keeps_dollars_and_converts_cent_revenue():
    settlement = _normalise_live_settlement({
        "ticker": "KXBTC15M-TEST-00",
        "market_result": "yes",
        "yes_count_fp": "12.50",
        "yes_total_cost_dollars": "12.3400",
        "revenue": 1500,
        "fee_cost": "0.6600",
    })

    assert settlement["market_result"] == "YES"
    assert settlement["yes_count_fp"] == 12.5
    assert settlement["yes_total_cost_dollars"] == 12.34
    assert settlement["revenue_dollars"] == 15.0
    assert settlement["fee_cost_dollars"] == 0.66


def _app(tmp_path, *, auth=True):
    app = Flask(__name__)
    register_kalshi_api(
        app,
        require_auth=(lambda: {"id": "user-1"}) if auth else (lambda: None),
        http_get=_fake_get,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )
    return app


def test_registered_scheduler_controls_are_idempotent_and_restartable(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv("ALPHALAB_DISABLE_KALSHI_SCHEDULER", raising=False)
    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        http_get=_fake_get,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
        start_background=False,
    )

    assert controls["runtime"]()["required"] is False
    assert controls["runtime"]()["threadAlive"] is False
    assert controls["reference_stream"].enabled is False

    try:
        started = controls["start"]()
        first_thread = controls["paper_robot"]._thread
        assert started["required"] is True
        assert started["threadAlive"] is True
        assert started["healthy"] is True
        assert controls["reference_stream"].enabled is True

        repeated = controls["start"]()
        assert repeated["required"] is True
        assert controls["paper_robot"]._thread is first_thread

        stopped = controls["stop"]()
        assert stopped["required"] is False
        assert stopped["threadAlive"] is False
        assert controls["reference_stream"].enabled is False
        assert controls["stop"]()["threadAlive"] is False

        restarted = controls["start"]()
        assert restarted["required"] is True
        assert restarted["threadAlive"] is True
        assert controls["reference_stream"].enabled is True
        assert controls["paper_robot"]._thread is not first_thread
    finally:
        controls["stop"]()


@pytest.mark.parametrize(
    ("lease_owned", "enabled_user_count"),
    [(False, None), (True, 0)],
)
def test_public_data_failure_is_diagnostic_only_for_standby_scheduler(
    lease_owned,
    enabled_user_count,
):
    class Client:
        @staticmethod
        def runtime_snapshot():
            return {
                "healthy": False,
                "status": "degraded",
                "lastError": "kalshi_public_rate_limited",
            }

    class Thread:
        @staticmethod
        def is_alive():
            return True

    controller = _PaperRobotController(Client(), state=None, paper_accounts=None)
    controller._background_requested = True
    controller._thread = Thread()
    controller._scheduler_lease_owned = lease_owned
    controller._enabled_user_count = enabled_user_count

    runtime = controller.runtime_snapshot()

    assert runtime["required"] is True
    assert runtime["healthy"] is True
    assert runtime["publicDataRequired"] is False
    assert runtime["publicData"]["healthy"] is False


def test_start_background_uses_the_same_registered_scheduler_lifecycle(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv("ALPHALAB_DISABLE_KALSHI_SCHEDULER", raising=False)
    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        http_get=_fake_get,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
        start_background=True,
    )

    try:
        snapshot = controls["runtime"]()
        assert snapshot["required"] is True
        assert snapshot["threadAlive"] is True
        assert snapshot["healthy"] is True
        assert controls["reference_stream"].enabled is True
    finally:
        controls["stop"]()


def test_snapshot_uses_production_public_data_and_is_paper_only(tmp_path):
    payload = _app(tmp_path).test_client().get("/api/kalshi/btc-15m/snapshot").get_json()
    assert payload["success"] is True
    assert payload["decision"]["paperOnly"] is True
    assert payload["decision"]["executionEnvironment"] == "alphalab_paper"
    assert payload["decision"]["methodology"]["orderPolicy"].startswith("AlphaLab Paper")


def test_paper_account_is_available_without_personal_credentials(tmp_path):
    client = _app(tmp_path).test_client()
    response = client.get("/api/kalshi/paper/portfolio")
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["portfolio"]["environment"] == "paper"
    assert payload["portfolio"]["accountProvider"] == "AlphaLab"
    assert payload["portfolio"]["balance"]["balance"] == 1_000_000
    assert payload["portfolio"]["fills"] == []


def test_display_reset_preserves_the_complete_paper_ledger(tmp_path):
    display_store = {}

    def load_display(user_id):
        return copy.deepcopy(display_store.get(user_id))

    def save_display(user_id, payload):
        display_store[user_id] = copy.deepcopy(dict(payload))
        return copy.deepcopy(display_store[user_id])

    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        http_get=_fake_get,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
        portfolio_display_loader=load_display,
        portfolio_display_saver=save_display,
    )
    controls["paper_accounts"].submit_taker(
        "user-1",
        ticker="KXBTC15M-TEST-00",
        side="YES",
        price=0.55,
        contracts=3,
        available_depth=0,
        client_order_id="preserved-order",
    )
    before = controls["paper_accounts"].portfolio("user-1")

    response = app.test_client().post(
        "/api/kalshi/portfolio/display-reset",
        json={"mode": "paper"},
    )
    payload = response.get_json()
    after = controls["paper_accounts"].portfolio("user-1")

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["portfolio"]["analytics"]["displayBaseline"]["active"] is True
    assert payload["portfolio"]["analytics"]["displayBaseline"]["ledgerPreserved"] is True
    assert len(before["orders"]) == len(after["orders"]) == 1
    assert before["orders"][0]["client_order_id"] == after["orders"][0]["client_order_id"]
    assert before["balance"] == after["balance"]
    assert display_store["user-1"]["modes"]["paper"]["baselineEquityCents"] == 1_000_000
    assert display_store["user-1"]["modes"]["paper"]["alphaLabOnly"] is False


def test_real_display_reset_persists_alphalab_only_contract(monkeypatch):
    display_store = {}
    controller = _PaperRobotController(
        None,
        type("State", (), {"get": lambda *_args, **_kwargs: {"modeState": {}}})(),
        None,
        portfolio_display_loader=lambda user_id: copy.deepcopy(
            display_store.get(user_id)
        ),
        portfolio_display_saver=lambda user_id, payload: display_store.update({
            user_id: copy.deepcopy(payload),
        }),
    )
    monkeypatch.setattr(
        controller,
        "portfolio",
        lambda *_args, **_kwargs: {
            "balance": {"balance": 80_000, "portfolio_value": 20_000},
            "orders": [],
            "fills": [],
            "settlements": [],
            "analytics": {},
        },
    )

    result = controller.reset_portfolio_display("user-1", mode="real")
    baseline = display_store["user-1"]["modes"]["real"]

    assert baseline["alphaLabOnly"] is True
    assert baseline["baselineEquityCents"] == 100_000
    assert result["analytics"]["displayBaseline"]["alphaLabOnly"] is True


def test_real_display_baseline_exposes_only_post_baseline_alphalab_activity():
    baseline = {
        "resetAt": "2026-07-26T12:00:00Z",
        "baselineEquityCents": 100_000,
        "baselineCashCents": 100_000,
        "environment": "real",
        "ledgerPreserved": True,
        "alphaLabOnly": True,
    }

    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "modeState": {"real": {"displayBaseline": baseline}},
                "strategy": {},
            }

    controller = _PaperRobotController(None, State(), None)
    result = controller._apply_portfolio_display(
        "user-1",
        {
            "orders": [
                {
                    "order_id": "old-managed",
                    "created_time": "2026-07-26T11:59:00Z",
                    "alphaLabManaged": True,
                },
                {
                    "order_id": "new-manual",
                    "created_time": "2026-07-26T12:01:00Z",
                    "alphaLabManaged": False,
                },
                {
                    "order_id": "new-managed",
                    "created_time": "2026-07-26T12:02:00Z",
                    "alphaLabManaged": True,
                },
            ],
            "fills": [],
            "settlements": [],
            "analytics": {},
        },
        "real",
    )

    assert [row["order_id"] for row in result["orders"]] == ["new-managed"]
    assert result["analytics"]["displayBaseline"]["active"] is True
    assert result["analytics"]["displayBaseline"]["resetAt"] == baseline["resetAt"]
    assert result["accountActivity"]["lifetimeCounts"]["orders"] == 3
    assert result["accountActivity"]["visibleCounts"]["orders"] == 1


@pytest.mark.parametrize(
    "invalid_baseline",
    [
        {},
        {"environment": "real", "alphaLabOnly": True},
        {"resetAt": "2026-07-26T12:00:00Z", "alphaLabOnly": True},
        {"resetAt": "2026-07-26T12:00:00Z", "environment": "real"},
    ],
)
def test_real_display_artifact_repairs_invalid_baseline_fail_closed(
    invalid_baseline,
):
    display_store = {
        "user-1": {"modes": {"real": copy.deepcopy(invalid_baseline)}},
    }

    class State:
        def get(self, _user_id, *, environment=None):
            return {"modeState": {"real": {"displayBaseline": {}}}}

        def ensure_real_display_baseline(self, _user_id):
            return {
                "resetAt": "2026-07-27T12:00:00Z",
                "environment": "real",
                "ledgerPreserved": True,
                "alphaLabOnly": True,
                "reason": "test_repair",
            }

    controller = _PaperRobotController(
        None,
        State(),
        None,
        portfolio_display_loader=lambda user_id: copy.deepcopy(
            display_store.get(user_id)
        ),
        portfolio_display_saver=lambda user_id, payload: display_store.update({
            user_id: copy.deepcopy(payload),
        }),
    )
    result = controller._apply_portfolio_display(
        "user-1",
        {
            "balance": {"balance": 100_000, "portfolio_value": 0},
                "orders": [{
                    "order_id": "pre-repair",
                    "created_time": "2020-01-01T00:00:00Z",
                    "alphaLabManaged": True,
                }],
            "fills": [],
            "settlements": [],
            "analytics": {},
        },
        "real",
    )

    repaired = display_store["user-1"]["modes"]["real"]
    assert repaired["baselineEquityCents"] == 100_000
    assert repaired["baselineCashCents"] == 100_000
    assert repaired["environment"] == "real"
    assert repaired["alphaLabOnly"] is True
    assert result["orders"] == []
    assert result["analytics"]["displayBaseline"]["active"] is True


def test_real_state_fallback_baseline_materializes_current_cash_and_equity():
    materialized = []

    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "modeState": {
                    "real": {
                        "displayBaseline": {
                            "resetAt": "2026-07-26T12:00:00Z",
                            "environment": "real",
                            "ledgerPreserved": True,
                            "alphaLabOnly": True,
                        },
                    },
                },
            }

        def ensure_real_display_baseline(self, _user_id):
            return self.get(_user_id)["modeState"]["real"][
                "displayBaseline"
            ]

        def materialize_real_display_baseline(self, _user_id, baseline):
            materialized.append(copy.deepcopy(baseline))
            return dict(baseline)

    controller = _PaperRobotController(None, State(), None)
    result = controller._apply_portfolio_display(
        "user-1",
        {
            "balance": {
                "balance": 125_000,
                "portfolio_value": 25_000,
            },
            "orders": [],
            "fills": [],
            "settlements": [],
            "analytics": {},
        },
        "real",
    )

    assert len(materialized) == 1
    assert materialized[0]["resetAt"] == "2026-07-26T12:00:00Z"
    assert materialized[0]["baselineEquityCents"] == 150_000
    assert materialized[0]["baselineCashCents"] == 125_000
    assert result["analytics"]["displayBaseline"][
        "baselineEquityCents"
    ] == 150_000
    assert result["analytics"]["displayBaseline"][
        "baselineCashCents"
    ] == 125_000


def test_live_portfolio_marks_missing_position_value_as_unknown(monkeypatch):
    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "strategy": {},
                "filledTrades": [],
                "decisions": [],
                "modeState": {"real": {"displayBaseline": {}}},
            }

    def signed_request(_config, _environment, _method, endpoint, **_kwargs):
        if endpoint == "/portfolio/balance":
            return {"balance": 80_000, "portfolio_value": 20_000}
        if endpoint == "/portfolio/positions":
            return {"market_positions": [{
                "ticker": "KXBTC15M-TEST-00",
                "position_fp": 3,
                "market_exposure_dollars": "1.20",
            }]}
        if endpoint == "/portfolio/orders":
            return {"orders": []}
        if endpoint == "/portfolio/fills":
            return {"fills": []}
        if endpoint == "/portfolio/settlements":
            return {"settlements": []}
        raise AssertionError(endpoint)

    controller = _PaperRobotController(
        None,
        State(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        signed_request=signed_request,
    )
    monkeypatch.setattr(
        controller,
        "_historical_account_rows",
        lambda *_args: {"orders": [], "fills": [], "complete": True, "warnings": []},
    )

    portfolio = controller._live_portfolio("user-1", mutate=False)

    assert _account_equity_cents(portfolio["balance"], "real") == 100_000
    assert portfolio["positions"][0]["market_value_dollars"] is None
    assert portfolio["positions"][0]["unrealized_pnl_dollars"] is None
    assert portfolio["positions"][0]["markAvailable"] is False
    assert portfolio["positions"][0]["alphaLabManaged"] is False
    assert portfolio["positions"][0]["alphaLabManagedCount"] == 0
    assert portfolio["positions"][0]["alphaLabUnmanagedCount"] == 3
    assert portfolio["completeness"]["complete"] is True
    assert portfolio["warnings"] == ["kalshi_unmanaged_positions_present"]


def test_position_market_mark_uses_outcome_midpoint_and_last_trade_fallback():
    market = {
        "yes_bid_dollars": "0.6200",
        "yes_ask_dollars": "0.6600",
        "no_bid_dollars": "0.3400",
        "no_ask_dollars": "0.3800",
        "updated_time": "2026-07-27T23:00:00Z",
    }

    yes = _position_market_mark(market, "YES")
    no = _position_market_mark(market, "NO")
    last_no = _position_market_mark(
        {"last_price_dollars": "0.7100"},
        "NO",
    )

    assert yes == {
        "mark": 0.64,
        "bid": 0.62,
        "ask": 0.66,
        "source": "midpoint",
        "asOf": "2026-07-27T23:00:00Z",
    }
    assert no["mark"] == pytest.approx(0.36)
    assert no["source"] == "midpoint"
    assert last_no["mark"] == pytest.approx(0.29)
    assert last_no["source"] == "last_trade"


def test_live_portfolio_enriches_position_value_from_current_market_quote(
    monkeypatch,
):
    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "strategy": {},
                "filledTrades": [],
                "decisions": [],
                "modeState": {"real": {"displayBaseline": {}}},
            }

    class Client:
        def market(self, ticker):
            assert ticker == "KXBTC15M-MARK-00"
            return {
                "ticker": ticker,
                "yes_bid_dollars": "0.6200",
                "yes_ask_dollars": "0.6600",
                "no_bid_dollars": "0.3400",
                "no_ask_dollars": "0.3800",
                "updated_time": "2026-07-27T23:00:00Z",
            }

    def signed_request(_config, _environment, _method, endpoint, **_kwargs):
        if endpoint == "/portfolio/balance":
            return {"balance": 1_807, "portfolio_value": 192}
        if endpoint == "/portfolio/positions":
            return {"market_positions": [{
                "ticker": "KXBTC15M-MARK-00",
                "position_fp": 3,
                "market_exposure_dollars": "1.20",
                "fees_paid_dollars": "0.03",
            }]}
        if endpoint == "/portfolio/orders":
            return {"orders": []}
        if endpoint == "/portfolio/fills":
            return {"fills": []}
        if endpoint == "/portfolio/settlements":
            return {"settlements": []}
        raise AssertionError(endpoint)

    controller = _PaperRobotController(
        Client(),
        State(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        signed_request=signed_request,
    )
    monkeypatch.setattr(
        controller,
        "_historical_account_rows",
        lambda *_args: {
            "orders": [],
            "fills": [],
            "complete": True,
            "warnings": [],
        },
    )

    portfolio = controller._live_portfolio("user-1", mutate=False)
    position = portfolio["positions"][0]

    assert position["yes_mark_dollars"] == pytest.approx(0.64)
    assert position["no_mark_dollars"] == pytest.approx(0.36)
    assert position["market_value_dollars"] == pytest.approx(1.92)
    assert position["unrealized_pnl_dollars"] == pytest.approx(0.69)
    assert position["markAvailable"] is True
    assert position["markSource"] == "midpoint"
    assert position["markBidDollars"] == pytest.approx(0.62)
    assert position["markAskDollars"] == pytest.approx(0.66)
    assert position["markAsOf"] == "2026-07-27T23:00:00Z"


def test_live_portfolio_paginates_orders_before_marking_account_complete(
    monkeypatch,
):
    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "strategy": {},
                "filledTrades": [],
                "decisions": [],
                "modeState": {"real": {"displayBaseline": {}}},
            }

    order_calls = []

    def signed_request(_config, _environment, _method, endpoint, **kwargs):
        params = dict(kwargs.get("params") or {})
        if endpoint == "/portfolio/balance":
            return {"balance": 80_000, "portfolio_value": 0}
        if endpoint == "/portfolio/positions":
            return {"market_positions": []}
        if endpoint == "/portfolio/orders":
            order_calls.append(params)
            if not params.get("cursor"):
                return {
                    "orders": [{
                        "order_id": "order-1",
                        "ticker": "KXBTC15M-TEST-00",
                    }],
                    "cursor": "page-2",
                }
            assert params["cursor"] == "page-2"
            return {
                "orders": [{
                    "order_id": "order-2",
                    "ticker": "KXBTC15M-TEST-15",
                }],
            }
        if endpoint == "/portfolio/fills":
            return {"fills": []}
        if endpoint == "/portfolio/settlements":
            return {"settlements": []}
        raise AssertionError(endpoint)

    controller = _PaperRobotController(
        None,
        State(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        signed_request=signed_request,
    )
    monkeypatch.setattr(
        controller,
        "_historical_account_rows",
        lambda *_args: {
            "orders": [],
            "fills": [],
            "complete": True,
            "warnings": [],
        },
    )

    portfolio = controller._live_portfolio("user-1", mutate=False)

    assert [row["order_id"] for row in portfolio["orders"]] == [
        "order-1",
        "order-2",
    ]
    assert order_calls == [
        {"limit": 1000, "subaccount": 0},
        {"limit": 1000, "subaccount": 0, "cursor": "page-2"},
    ]
    assert portfolio["completeness"]["orders"] is True
    assert "kalshi_account_orders_incomplete" not in portfolio["warnings"]


def test_live_portfolio_separates_managed_and_manual_contract_counts(monkeypatch):
    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "strategy": {},
                "filledTrades": [{
                    "ticker": "KXBTC15M-TEST-00",
                    "side": "YES",
                    "action": "BUY_YES",
                    "orderId": "managed-order",
                    "clientOrderId": "managed-client",
                    "orderFilled": True,
                    "fillCount": 2,
                }],
                "decisions": [],
                "modeState": {"real": {"displayBaseline": {}}},
            }

    def signed_request(_config, _environment, _method, endpoint, **_kwargs):
        if endpoint == "/portfolio/balance":
            return {"balance": 80_000, "portfolio_value": 20_000}
        if endpoint == "/portfolio/positions":
            return {"market_positions": [{
                "ticker": "KXBTC15M-TEST-00",
                "position_fp": 5,
                "market_exposure_dollars": "2.00",
            }]}
        if endpoint == "/portfolio/orders":
            return {"orders": [{
                "order_id": "managed-order",
                "client_order_id": "managed-client",
                "ticker": "KXBTC15M-TEST-00",
                "outcome_side": "YES",
                "reduce_only": False,
                "count_fp": 2,
                "fill_count_fp": 2,
            }]}
        if endpoint == "/portfolio/fills":
            return {"fills": [{
                "fill_id": "managed-fill",
                "order_id": "managed-order",
                "ticker": "KXBTC15M-TEST-00",
                "outcome_side": "YES",
                "count_fp": 2,
                "yes_price_dollars": "0.40",
                "no_price_dollars": "0.60",
            }]}
        if endpoint == "/portfolio/settlements":
            return {"settlements": []}
        raise AssertionError(endpoint)

    controller = _PaperRobotController(
        None,
        State(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        signed_request=signed_request,
    )
    monkeypatch.setattr(
        controller,
        "_historical_account_rows",
        lambda *_args: {"orders": [], "fills": [], "complete": True, "warnings": []},
    )

    portfolio = controller._live_portfolio("user-1", mutate=False)
    position = portfolio["positions"][0]

    assert position["alphaLabManaged"] is True
    assert position["alphaLabManagedSide"] == "YES"
    assert position["alphaLabManagedCount"] == 2
    assert position["alphaLabUnmanagedCount"] == 3
    assert position["yes_average_price_dollars"] == 0.40
    assert "kalshi_unmanaged_positions_present" in portfolio["warnings"]
    assert _position_execution_context(
        portfolio, "KXBTC15M-TEST-00"
    )["count"] == 2


def test_manual_fill_roundtrip_to_zero_does_not_poison_managed_inventory(
    monkeypatch,
):
    ticker = "KXBTC15M-ROUNDTRIP"

    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "strategy": {},
                "filledTrades": [{
                    "ticker": ticker,
                    "side": "YES",
                    "action": "BUY_YES",
                    "orderId": "managed-order",
                    "clientOrderId": "managed-client",
                    "orderFilled": True,
                    "fillCount": 2,
                }],
                "decisions": [],
                "modeState": {"real": {"displayBaseline": {}}},
            }

    def signed_request(_config, _environment, _method, endpoint, **_kwargs):
        if endpoint == "/portfolio/balance":
            return {"balance": 80_000, "portfolio_value": 20_000}
        if endpoint == "/portfolio/positions":
            return {"market_positions": [{
                "ticker": ticker,
                "position_fp": 2,
                "yes_count_fp": 2,
                "market_exposure_dollars": "0.80",
            }]}
        if endpoint == "/portfolio/orders":
            return {"orders": [{
                "order_id": "managed-order",
                "client_order_id": "managed-client",
                "ticker": ticker,
                "outcome_side": "YES",
                "reduce_only": False,
                "count_fp": 2,
                "fill_count_fp": 2,
            }]}
        if endpoint == "/portfolio/fills":
            return {"fills": [
                {
                    "fill_id": "managed-fill",
                    "order_id": "managed-order",
                    "ticker": ticker,
                    "action": "BUY",
                    "outcome_side": "YES",
                    "count_fp": 2,
                    "yes_price_dollars": "0.40",
                },
                {
                    "fill_id": "manual-buy",
                    "order_id": "manual-buy-order",
                    "ticker": ticker,
                    "action": "BUY",
                    "outcome_side": "YES",
                    "count_fp": 5,
                    "yes_price_dollars": "0.45",
                },
                {
                    "fill_id": "manual-sell",
                    "order_id": "manual-sell-order",
                    "ticker": ticker,
                    "action": "SELL",
                    # Kalshi V2 outcome_side is the resulting exposure;
                    # SELL YES is therefore canonical NO.
                    "outcome_side": "NO",
                    "count_fp": 5,
                    "yes_price_dollars": "0.50",
                },
            ]}
        if endpoint == "/portfolio/settlements":
            return {"settlements": [{
                "ticker": ticker,
                "market_result": "YES",
                "settled_time": "2026-07-27T02:00:00Z",
            }]}
        raise AssertionError(endpoint)

    controller = _PaperRobotController(
        None,
        State(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        signed_request=signed_request,
    )
    monkeypatch.setattr(
        controller,
        "_historical_account_rows",
        lambda *_args: {
            "orders": [],
            "fills": [],
            "complete": True,
            "warnings": [],
        },
    )

    portfolio = controller._live_portfolio("user-1", mutate=False)
    position = portfolio["positions"][0]

    assert position["alphaLabManaged"] is True
    assert position["alphaLabManagedCount"] == 2
    assert position["alphaLabUnmanagedCount"] == 0
    assert position["alphaLabOwnershipConflict"] is False
    assert portfolio["settlements"][0]["alphaLabManaged"] is True
    assert "kalshi_unmanaged_positions_present" not in portfolio["warnings"]


def test_config_exposes_builtin_paper_and_production_only_environment(tmp_path):
    app = Flask(__name__)
    register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        http_get=_fake_get,
        get_user_config=lambda *_: {},
        save_user_config=lambda *_: (True, None),
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )
    payload = app.test_client().get("/api/kalshi/config").get_json()
    assert payload["activeEnvironment"] == "paper"
    assert payload["paper"]["builtIn"] is True
    assert payload["paper"]["startingBalance"] == 10_000.0
    assert payload["paper"]["startingBalanceCents"] == 1_000_000
    assert set(payload["environments"]) == {"production"}


def test_missing_auth_returns_stable_401(tmp_path):
    response = _app(tmp_path, auth=False).test_client().get("/api/kalshi/status")
    assert response.status_code == 401
    assert response.get_json()["code"] == "authentication_required"


def test_status_has_no_removed_ai_learning_surface(tmp_path):
    payload = _app(tmp_path).test_client().get("/api/kalshi/status").get_json()

    assert "ai" not in payload


def test_analytics_exposes_per_family_opportunity_funnels(tmp_path):
    rows = [
        {
            "ticker": "KXBTC15M-TEST-00",
            "environment": "paper",
            "observed_at": "2026-07-25T12:00:00Z",
            "action": "WAIT",
            "side": "YES",
            "seconds_to_close": 300,
            "net_edge": 0.02,
            "conservative_edge": 0.01,
            "blocked_reasons": ["depth"],
            "features": {
                "model": {
                    "referenceModel": "kalshi_cf_benchmarks_brti",
                    "isOfficialBrti": True,
                },
                "dataQuality": {"snapshotLatencyMs": 210},
            },
        },
        {
            "ticker": "KXBTCD-26JUL2515-T64000",
            "environment": "paper",
            "observed_at": "2026-07-25T12:00:00Z",
            "action": "WAIT",
            "side": "YES",
            "seconds_to_close": 600,
            "net_edge": 0.03,
            "conservative_edge": 0.02,
            "blocked_reasons": ["daily_loss_limit"],
            "features": {
                "model": {"referenceModel": "kalshi_cf_benchmarks_brti"},
                "dataQuality": {"snapshotLatencyMs": 350},
            },
        },
        {
            "ticker": "KXBTCD-26JUL2515-T64500",
            "environment": "paper",
            "observed_at": "2026-07-25T12:00:00Z",
            "action": "WAIT",
            "side": "YES",
            "seconds_to_close": 600,
            "net_edge": 0.025,
            "conservative_edge": 0.015,
            "blocked_reasons": ["depth", "daily_loss_limit"],
            "features": {
                "model": {"referenceModel": "kalshi_cf_benchmarks_brti"},
                "dataQuality": {"snapshotLatencyMs": 375},
            },
        },
        {
            "ticker": "KXBTCD-26JUL2515-T65000",
            "environment": "paper",
            "observed_at": "2026-07-25T12:00:01Z",
            "action": "BUY_NO",
            "side": "NO",
            "seconds_to_close": 600,
            "net_edge": 0.03,
            "conservative_edge": 0.012,
            "blocked_reasons": [],
            "order_result": {"status": "filled"},
            "features": {
                "model": {"referenceModel": "kalshi_cf_benchmarks_brti"},
                "dataQuality": {"snapshotLatencyMs": 400},
            },
        },
    ]
    app = Flask(__name__)
    register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        http_get=_fake_get,
        observation_loader=lambda *_args, **_kwargs: rows,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )

    response = app.test_client().get("/api/kalshi/analytics?mode=paper&hours=24")
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["analytics"]["families"]["btc15m"]["officialBrtiSamples"] == 1
    assert payload["analytics"]["families"]["btc15m"]["blockers"] == [
        {"key": "depth", "count": 1}
    ]
    assert payload["analytics"]["families"]["btchourly"]["funnel"]["orders"] == 1
    assert payload["analytics"]["families"]["btchourly"]["blockers"] == [
        {"key": "depth", "count": 1}
    ]
    assert payload["analytics"]["families"]["btchourly"]["nearMisses"] == [{
        "at": "2026-07-25T12:00:00Z",
        "ticker": "KXBTCD-26JUL2515-T64500",
        "side": "YES",
        "price": None,
        "netEdge": 0.025,
        "conservativeEdge": 0.015,
        "secondsToClose": 600,
        "blockingReasons": ["depth"],
    }]


def test_paper_order_payload_uses_yes_book_shape():
    yes = _paper_order_payload({"action": "BUY_YES", "side": "YES", "edge": {"price": 0.42}, "sizing": {"contracts": 7}}, "T")
    no = _paper_order_payload({"action": "BUY_NO", "side": "NO", "edge": {"price": 0.31}, "sizing": {"contracts": 4}}, "T")
    sharded = _paper_order_payload(
        {"action": "BUY_YES", "side": "YES", "edge": {"price": 0.42}, "sizing": {"contracts": 1}},
        "T",
        exchange_index=2,
    )
    assert yes["side"] == "bid" and yes["price"] == "0.4200"
    assert no["side"] == "ask" and no["price"] == "0.6900"
    assert yes["time_in_force"] == "immediate_or_cancel"
    assert yes["exchange_index"] == no["exchange_index"] == -1
    assert sharded["exchange_index"] == 2


def test_close_order_payload_uses_reduce_only_yes_book_shape():
    sell_yes = _paper_order_payload(
        {"action": "SELL_YES", "side": "YES", "edge": {"price": 0.57}, "sizing": {"contracts": 7}},
        "T",
    )
    sell_no = _paper_order_payload(
        {"action": "SELL_NO", "side": "NO", "edge": {"price": 0.36}, "sizing": {"contracts": 4}},
        "T",
    )

    assert sell_yes["side"] == "ask" and sell_yes["price"] == "0.5700"
    assert sell_no["side"] == "bid" and sell_no["price"] == "0.6400"
    assert sell_yes["reduce_only"] is True
    assert sell_no["reduce_only"] is True


def test_live_no_order_is_normalised_to_the_user_outcome_price():
    decision = {"action": "SELL_NO", "side": "NO"}
    payload = _paper_order_payload(
        {**decision, "edge": {"price": 0.36}, "sizing": {"contracts": 4}},
        "T",
    )
    order = _normalise_live_order(
        {"order_id": "order-1", "average_price": "0.6500", "fill_count": "4"},
        payload,
        decision,
    )

    assert order["outcome_side"] == "NO"
    assert order["limit_price_dollars"] == 0.36
    assert order["average_price_dollars"] == 0.35
    assert order["action"] == "SELL"
    assert order["reduce_only"] is True


def test_live_v2_partial_fill_uses_average_price_fee_and_remaining_count():
    decision = {"action": "BUY_NO", "side": "NO"}
    payload = _paper_order_payload(
        {**decision, "edge": {"price": 0.31}, "sizing": {"contracts": 4}},
        "T",
    )
    order = _normalise_live_order(
        {
            "order_id": "order-v2",
            "fill_count": "2.00",
            "remaining_count": "2.00",
            "average_fill_price": "0.6800",
            "average_fee_paid": "0.0125",
        },
        payload,
        decision,
    )

    assert order["outcome_side"] == "NO"
    assert order["average_price_dollars"] == 0.32
    assert order["fee_cost_dollars"] == 0.025
    assert order["fill_count_fp"] == 2.0
    assert order["remaining_count_fp"] == 2.0
    assert order["status"] == "partially_filled"


def test_live_sell_fill_maps_canonical_direction_to_reduced_contract():
    fill = _normalise_live_fill({
        "fill_id": "fill-no-1",
        "ticker": "KXBTC15M-TEST-00",
        "outcome_side": "no",
        "book_side": "yes",
        "action": "sell",
        "count_fp": "3.00",
        "yes_price_dollars": "0.6400",
        "no_price_dollars": "0.3600",
        "fee_cost": "0.0200",
    })

    assert fill["canonical_outcome_side"] == "NO"
    assert fill["outcome_side"] == "YES"
    assert fill["action"] == "SELL"
    assert fill["price_dollars"] == 0.64
    assert fill["fee_cost_dollars"] == 0.02


@pytest.mark.parametrize(
    (
        "action",
        "canonical_side",
        "expected_contract_side",
        "expected_price",
    ),
    (
        ("buy", "YES", "YES", 0.64),
        ("buy", "NO", "NO", 0.36),
        ("sell", "NO", "YES", 0.64),
        ("sell", "YES", "NO", 0.36),
    ),
)
def test_live_fill_canonical_direction_and_price_cover_all_four_quadrants(
    action,
    canonical_side,
    expected_contract_side,
    expected_price,
):
    fill = _normalise_live_fill({
        "fill_id": f"{action}-{canonical_side}",
        "ticker": "KXBTC15M-TEST-00",
        "outcome_side": canonical_side,
        "action": action,
        "count_fp": "2.00",
        "yes_price_dollars": "0.6400",
        "no_price_dollars": "0.3600",
    })

    assert fill["canonical_outcome_side"] == canonical_side
    assert fill["outcome_side"] == expected_contract_side
    assert fill["action"] == action.upper()
    assert fill["price_dollars"] == expected_price


def test_live_order_recovers_all_economic_sides_from_yes_book_shape():
    cases = (
        ("bid", False, "YES", "BUY"),
        ("ask", False, "NO", "BUY"),
        ("ask", True, "YES", "SELL"),
        ("bid", True, "NO", "SELL"),
    )
    for book_side, reduce_only, expected_side, expected_action in cases:
        order = _normalise_live_order(
            {"order_id": f"{book_side}-{reduce_only}", "side": book_side},
            {"side": book_side, "reduce_only": reduce_only, "count": "1", "price": "0.5"},
            {},
        )
        assert order["outcome_side"] == expected_side
        assert order["action"] == expected_action


def test_live_fill_uses_matching_order_when_fill_omits_economic_side_and_action():
    order = _normalise_live_order(
        {"order_id": "order-no", "side": "ask"},
        {"side": "ask", "reduce_only": False, "count": "2", "price": "0.64"},
        {},
    )
    fill = _normalise_live_fill({
        "fill_id": "fill-no",
        "order_id": "order-no",
        "ticker": "KXBTC15M-TEST-00",
        "count_fp": "2",
        "yes_price_dollars": "0.6400",
        "no_price_dollars": "0.3600",
    }, order)

    assert fill["outcome_side"] == "NO"
    assert fill["action"] == "BUY"
    assert fill["price_dollars"] == 0.36


def test_live_fill_does_not_guess_side_when_both_prices_exist_without_order_context():
    fill = _normalise_live_fill({
        "fill_id": "ambiguous",
        "ticker": "KXBTC15M-TEST-00",
        "count_fp": "2",
        "yes_price_dollars": "0.6400",
        "no_price_dollars": "0.3600",
    })

    assert fill["outcome_side"] == ""
    assert fill["price_dollars"] is None


def test_live_no_fill_uses_outcome_specific_legacy_cent_price():
    fill = _normalise_live_fill({
        "fill_id": "fill-no-cent",
        "ticker": "KXBTC15M-TEST-00",
        "outcome_side": "no",
        "count": 2,
        "yes_price": 64,
        "no_price": 36,
    })

    assert fill["outcome_side"] == "NO"
    assert fill["price_dollars"] == 0.36


def test_live_order_payload_keeps_symmetric_yes_and_no_order_shapes():
    yes = _paper_order_payload({"action": "BUY_YES", "side": "YES", "edge": {"price": 0.42}, "sizing": {"contracts": 7}}, "T")
    no = _paper_order_payload({"action": "BUY_NO", "side": "NO", "edge": {"price": 0.31}, "sizing": {"contracts": 4}}, "T")

    yes_live = _live_order_payload(yes)
    no_live = _live_order_payload(no)

    assert yes_live["side"] == "bid" and yes_live["price"] == "0.4200"
    assert no_live["side"] == "ask" and no_live["price"] == "0.6900"
    assert yes_live["count"] == "7.00" and no_live["count"] == "4.00"
    assert yes_live["exchange_index"] == no_live["exchange_index"] == -1


class _EnabledRealState:
    def __init__(self, *, filled_trades=None, strategy=None):
        self.filled_trades = list(filled_trades or [])
        self.strategy = dict(strategy or {})

    def get(self, _user_id, *, environment=None):
        return {
            "enabled": True,
            "activeEnvironment": "real",
            "config": {
                "executionMode": environment or "real",
                "maxPortfolioExposurePct": 10,
                "maxSingleMarketExposurePct": 2,
            },
            "strategy": copy.deepcopy(self.strategy),
            "filledTrades": copy.deepcopy(self.filled_trades),
        }

    def refresh(self, _user_id, *, environment=None):
        return {
            **self.get(_user_id, environment=environment),
            "authoritativeRefresh": True,
            "durableStateLoaderAvailable": True,
        }


def _test_real_credentials(_user_id):
    return {
        "production_api_key_id": "key-id-12345678",
        "production_private_key": "private-key-present",
    }


def _real_preflight_response(
    endpoint,
    *,
    balance=100_000,
    portfolio_value=0,
    positions=None,
    orders=None,
):
    if endpoint.startswith("/markets/"):
        return {"market": {"ticker": endpoint.removeprefix("/markets/"), "exchange_index": 2}}
    if endpoint == "/portfolio/balance":
        return {
            "balance": balance,
            "portfolio_value": portfolio_value,
            "balance_breakdown": [{"exchange_index": 2, "balance": str(balance / 100.0)}],
        }
    if endpoint == "/portfolio/positions":
        return {"market_positions": list(positions or [])}
    if endpoint == "/portfolio/orders":
        return {"orders": list(orders or [])}
    raise AssertionError(endpoint)


class _FencedLeaseStore:
    def __init__(self, *, renews=True):
        self.renews = renews
        self.events = []

    def claim_worker_lease_fenced(self, lease_name, owner_id, **_kwargs):
        self.events.append(("claim", lease_name, owner_id, 73))
        return {"acquired": True, "fencingToken": 73}

    def renew_worker_lease(
        self, lease_name, owner_id, fencing_token, **_kwargs,
    ):
        self.events.append(("renew", lease_name, owner_id, fencing_token))
        return self.renews and fencing_token == 73

    def release_worker_lease(
        self, lease_name, owner_id, fencing_token=None,
    ):
        self.events.append(("release", lease_name, owner_id, fencing_token))
        return fencing_token == 73


class _MutualFencedLeaseStore:
    def __init__(self):
        self.condition = threading.Condition()
        self.owner = None
        self.token = 0
        self.events = []

    def claim_worker_lease_fenced(self, lease_name, owner_id, **_kwargs):
        with self.condition:
            if self.owner is not None:
                return {"acquired": False}
            self.token += 1
            self.owner = owner_id
            self.events.append(("claim", lease_name, owner_id, self.token))
            return {"acquired": True, "fencingToken": self.token}

    def renew_worker_lease(
        self,
        lease_name,
        owner_id,
        fencing_token,
        **_kwargs,
    ):
        with self.condition:
            valid = (
                self.owner == owner_id and self.token == fencing_token
            )
            self.events.append(
                ("renew", lease_name, owner_id, fencing_token)
            )
            return valid

    def release_worker_lease(
        self,
        lease_name,
        owner_id,
        fencing_token=None,
    ):
        with self.condition:
            valid = (
                self.owner == owner_id and self.token == fencing_token
            )
            self.events.append(
                ("release", lease_name, owner_id, fencing_token)
            )
            if valid:
                self.owner = None
                self.condition.notify_all()
            return valid


def _durable_state_callbacks():
    durable = {}
    versions = {}

    def load(user_id):
        return copy.deepcopy(durable.get(user_id))

    def save(user_id, state):
        durable[user_id] = copy.deepcopy(state)
        versions[user_id] = versions.get(user_id, 0) + 1
        return {"version": versions[user_id]}

    return durable, load, save


@pytest.mark.parametrize("mutation", ["delete", "rotate"])
def test_connection_test_fence_prevents_stale_credential_writeback(
    tmp_path,
    monkeypatch,
    mutation,
):
    _durable, load_state, save_state = _durable_state_callbacks()
    connection_lock = threading.RLock()
    connection = {
        "production_api_key_id": "old-key-id-123456",
        "production_private_key": "old-private-material",
        "production_test_status": "saved",
    }

    def get_connection(_user_id, _kind):
        with connection_lock:
            return copy.deepcopy(connection)

    def save_connection(_user_id, _kind, payload):
        with connection_lock:
            connection.clear()
            connection.update(copy.deepcopy(payload))
        return True, None

    class ObservableLeaseStore(_MutualFencedLeaseStore):
        def __init__(self):
            super().__init__()
            self.blocked_attempt = threading.Event()

        def claim_worker_lease_fenced(
            self,
            lease_name,
            owner_id,
            **kwargs,
        ):
            if self.owner is not None:
                self.blocked_attempt.set()
            return super().claim_worker_lease_fenced(
                lease_name,
                owner_id,
                **kwargs,
            )

    lease_store = ObservableLeaseStore()
    balance_read_started = threading.Event()
    allow_connection_test = threading.Event()

    def http_get(_url, **_kwargs):
        balance_read_started.set()
        assert allow_connection_test.wait(timeout=3.0)
        return _Response({
            "balance": 100_000,
            "portfolio_value": 0,
        })

    def http_request(_method, url, **_kwargs):
        if str(url).endswith("/portfolio/positions"):
            return _Response({"market_positions": []})
        if str(url).endswith("/portfolio/orders"):
            return _Response({"orders": []})
        raise AssertionError(url)

    # These tests exercise routing/credential serialization, not RSA crypto.
    monkeypatch.setattr(kalshi_api, "_signed_headers", lambda *_a, **_k: {})
    monkeypatch.setattr(
        kalshi_api,
        "_load_rsa_private_key",
        lambda _value: object(),
    )

    app = Flask(__name__)
    register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        http_get=http_get,
        http_request=http_request,
        get_user_config=get_connection,
        authoritative_config_loader=get_connection,
        save_user_config=save_connection,
        robot_state_loader=load_state,
        robot_state_saver=save_state,
        worker_lease_store=lease_store,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )
    test_responses = []
    mutation_responses = []

    def run_connection_test():
        with app.test_client() as client:
            test_responses.append(client.post(
                "/api/kalshi/config/test",
                json={"environment": "production"},
            ))

    def run_mutation():
        with app.test_client() as client:
            if mutation == "delete":
                response = client.delete(
                    "/api/kalshi/config",
                    json={"environment": "production"},
                )
            else:
                response = client.post(
                    "/api/kalshi/config",
                    json={
                        "environment": "production",
                        "apiKeyId": "new-key-id-123456",
                        "privateKey": "new-private-material",
                    },
                )
            mutation_responses.append(response)

    test_thread = threading.Thread(target=run_connection_test)
    test_thread.start()
    assert balance_read_started.wait(timeout=2.0)
    mutation_thread = threading.Thread(target=run_mutation)
    mutation_thread.start()
    mutation_waited_for_fence = lease_store.blocked_attempt.wait(
        timeout=2.0
    )
    allow_connection_test.set()
    test_thread.join(timeout=5.0)
    mutation_thread.join(timeout=5.0)

    assert mutation_waited_for_fence is True
    assert not test_thread.is_alive()
    assert not mutation_thread.is_alive()
    assert [response.status_code for response in test_responses] == [200]
    assert [response.status_code for response in mutation_responses] == [200]
    with connection_lock:
        final_connection = copy.deepcopy(connection)
    if mutation == "delete":
        assert "production_api_key_id" not in final_connection
        assert "production_private_key" not in final_connection
        assert "production_test_status" not in final_connection
    else:
        assert (
            final_connection["production_api_key_id"]
            == "new-key-id-123456"
        )
        assert (
            final_connection["production_private_key"]
            == "new-private-material"
        )
        assert final_connection["production_test_status"] == "saved"
    assert [event[0] for event in lease_store.events].count("renew") >= 1


def test_connection_test_bypasses_stale_cross_worker_credential_cache(
    tmp_path,
    monkeypatch,
):
    stale_cache = {
        "production_api_key_id": "old-key-id-123456",
        "production_private_key": "old-private-material",
        "production_test_status": "connected",
    }
    durable = {
        "production_api_key_id": "new-key-id-123456",
        "production_private_key": "new-private-material",
        "production_test_status": "saved",
        "unrelatedSetting": "preserve-me",
    }
    signed_credentials = []

    def authoritative_loader(_user_id, _kind):
        return copy.deepcopy(durable)

    def save_connection(_user_id, _kind, payload):
        durable.clear()
        durable.update(copy.deepcopy(payload))
        return True, None

    def capture_headers(key_id, private_key, *_args, **_kwargs):
        signed_credentials.append((key_id, private_key))
        return {}

    monkeypatch.setattr(kalshi_api, "_signed_headers", capture_headers)
    app = Flask(__name__)
    register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        http_get=lambda *_args, **_kwargs: _Response({
            "balance": 100_000,
            "portfolio_value": 0,
        }),
        http_request=lambda method, url, **_kwargs: _Response(
            {"market_positions": []}
            if str(url).endswith("/portfolio/positions")
            else {"orders": []}
        ),
        get_user_config=lambda *_args: copy.deepcopy(stale_cache),
        authoritative_config_loader=authoritative_loader,
        save_user_config=save_connection,
        worker_lease_store=_FencedLeaseStore(),
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )

    response = app.test_client().post(
        "/api/kalshi/config/test",
        json={"environment": "production"},
    )

    assert response.status_code == 200
    assert signed_credentials == [
        ("new-key-id-123456", "new-private-material"),
    ] * 3
    assert durable["production_api_key_id"] == "new-key-id-123456"
    assert durable["production_private_key"] == "new-private-material"
    assert durable["production_test_status"] == "connected"
    assert durable["unrelatedSetting"] == "preserve-me"


def test_signed_account_get_retries_once_but_never_retries_a_post(
    tmp_path,
    monkeypatch,
):
    durable = {
        "production_api_key_id": "key-id-12345678",
        "production_private_key": "private-material",
        "production_test_status": "saved",
    }
    calls = {}

    def http_request(method, url, **_kwargs):
        endpoint = str(url).split("/trade-api/v2", 1)[-1]
        key = (method, endpoint)
        calls[key] = calls.get(key, 0) + 1
        if method == "GET" and calls[key] == 1:
            return _StatusResponse(
                {"message": "temporary upstream error"},
                503,
            )
        if endpoint == "/portfolio/positions":
            return _StatusResponse({"market_positions": []}, 200)
        if endpoint == "/portfolio/orders":
            return _StatusResponse({"orders": []}, 200)
        return _StatusResponse({"message": "write unavailable"}, 503)

    monkeypatch.setattr(kalshi_api, "_signed_headers", lambda *_a, **_k: {})
    monkeypatch.setattr(kalshi_api.time, "sleep", lambda *_a, **_k: None)
    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        http_get=lambda *_a, **_k: _Response({
            "balance": 100_000,
            "portfolio_value": 0,
        }),
        http_request=http_request,
        get_user_config=lambda *_args: copy.deepcopy(durable),
        authoritative_config_loader=lambda *_args: copy.deepcopy(durable),
        save_user_config=lambda *_args: (True, None),
        worker_lease_store=_FencedLeaseStore(),
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )

    response = app.test_client().post(
        "/api/kalshi/config/test",
        json={"environment": "production"},
    )

    assert response.status_code == 200
    assert calls[("GET", "/portfolio/positions")] == 2
    assert calls[("GET", "/portfolio/orders")] == 2

    with pytest.raises(KalshiApiError):
        controls["paper_robot"].signed_request(
            durable,
            "production",
            "POST",
            "/portfolio/events/orders",
            json_body={"ticker": "KXBTC15M-TEST"},
        )
    assert calls[("POST", "/portfolio/events/orders")] == 1


@pytest.mark.parametrize(
    ("remote_code", "internal_code", "status_code"),
    [
        ("market_not_found", "kalshi_market_not_found", 404),
        ("market_inactive", "kalshi_market_inactive", 400),
        ("market_already_closed", "kalshi_market_already_closed", 400),
    ],
)
def test_signed_live_order_preserves_market_state_error_without_post_retry(
    tmp_path,
    monkeypatch,
    remote_code,
    internal_code,
    status_code,
):
    durable = {
        "production_api_key_id": "key-id-12345678",
        "production_private_key": "private-material",
        "production_test_status": "saved",
    }
    calls = []

    def http_request(method, url, **_kwargs):
        calls.append((method, url))
        return _StatusResponse(
            {
                "error": {
                    "code": remote_code,
                    "message": "market is not routable",
                },
            },
            status_code,
        )

    monkeypatch.setattr(kalshi_api, "_signed_headers", lambda *_a, **_k: {})
    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        http_get=lambda *_a, **_k: _Response({}),
        http_request=http_request,
        get_user_config=lambda *_args: copy.deepcopy(durable),
        authoritative_config_loader=lambda *_args: copy.deepcopy(durable),
        save_user_config=lambda *_args: (True, None),
        worker_lease_store=_FencedLeaseStore(),
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )

    with pytest.raises(KalshiApiError) as raised:
        controls["paper_robot"].signed_request(
            durable,
            "production",
            "POST",
            "/portfolio/events/orders",
            json_body={
                "ticker": "KXBTC15M-SHARD2",
                "exchange_index": -1,
            },
        )

    assert raised.value.code == internal_code
    assert raised.value.status == status_code
    assert raised.value.endpoint == "/portfolio/events/orders"
    assert remote_code in str(raised.value)
    assert len(calls) == 1


def test_production_config_bypass_reads_supabase_instead_of_ttl_cache(
    monkeypatch,
):
    import start_quant_backend as backend

    user_id = "kalshi-cache-bypass-user"
    cache_key = (user_id, "kalshi")
    stale = {
        "production_api_key_id": "old-key-id-123456",
        "production_private_key": "old-private-material",
    }
    fresh = {
        "production_api_key_id": "new-key-id-123456",
        "production_private_key": "new-private-material",
    }
    reads = []

    class Query:
        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def execute(self):
            reads.append(1)
            return type(
                "ConfigResponse",
                (),
                {"data": [{"config": copy.deepcopy(fresh)}]},
            )()

    class Supabase:
        def table(self, table_name):
            assert table_name == "user_api_configs"
            return Query()

    monkeypatch.setattr(backend, "supabase_admin", Supabase())
    monkeypatch.setitem(
        backend._config_cache,
        cache_key,
        (copy.deepcopy(stale), time.time()),
    )

    cached = backend.get_user_config(user_id, "kalshi")
    authoritative = backend.get_user_config(
        user_id,
        "kalshi",
        bypass_cache=True,
    )

    assert cached == stale
    assert reads == [1]
    assert authoritative == fresh
    assert backend.get_user_config(user_id, "kalshi") == fresh


def test_credential_rotation_uses_authoritative_record_not_stale_cache(
    tmp_path,
    monkeypatch,
):
    _state, load_state, save_state = _durable_state_callbacks()
    stale_cache = {
        "production_api_key_id": "old-key-id-123456",
        "production_private_key": "old-private-material",
    }
    durable = {
        "production_api_key_id": "current-key-id-123456",
        "production_private_key": "current-private-material",
        "unrelatedSetting": "preserve-me",
    }

    def save_connection(_user_id, _kind, payload):
        durable.clear()
        durable.update(copy.deepcopy(payload))
        return True, None

    monkeypatch.setattr(
        kalshi_api,
        "_load_rsa_private_key",
        lambda _value: object(),
    )
    app = Flask(__name__)
    register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        get_user_config=lambda *_args: copy.deepcopy(stale_cache),
        authoritative_config_loader=lambda *_args: copy.deepcopy(
            durable
        ),
        save_user_config=save_connection,
        robot_state_loader=load_state,
        robot_state_saver=save_state,
        worker_lease_store=_FencedLeaseStore(),
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )

    response = app.test_client().post(
        "/api/kalshi/config",
        json={
            "environment": "production",
            "apiKeyId": "third-key-id-123456",
            "privateKey": "********",
        },
    )

    assert response.status_code == 200
    assert durable["production_api_key_id"] == "third-key-id-123456"
    assert (
        durable["production_private_key"]
        == "current-private-material"
    )
    assert durable["production_test_status"] == "saved"
    assert durable["unrelatedSetting"] == "preserve-me"


def test_deleted_durable_credentials_block_real_state_mutations_from_stale_worker(
    tmp_path,
):
    _durable, load_state, save_state = _durable_state_callbacks()
    stale_cache = {
        "production_api_key_id": "deleted-key-id-123456",
        "production_private_key": "deleted-private-material",
    }
    lease_store = _FencedLeaseStore()
    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        get_user_config=lambda *_args: copy.deepcopy(stale_cache),
        authoritative_config_loader=lambda *_args: {},
        save_user_config=lambda *_args: (True, None),
        robot_state_loader=load_state,
        robot_state_saver=save_state,
        worker_lease_store=lease_store,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )
    state = controls["robot_state"]
    state.configure(
        "user-1",
        False,
        {
            "executionMode": "paper",
            "riskPerTradePct": 0.40,
        },
    )
    before = state.refresh("user-1")
    client = app.test_client()

    enable = client.post(
        "/api/kalshi/paper/robot",
        json={
            "enabled": True,
            "config": {
                "executionMode": "real",
                "riskPerTradePct": 0.20,
            },
        },
    )
    save_config = client.post(
        "/api/kalshi/paper/robot/config",
        json={
            "config": {
                "executionMode": "real",
                "riskPerTradePct": 0.10,
            },
        },
    )
    after = state.refresh("user-1")

    assert [enable.status_code, save_config.status_code] == [409, 409]
    assert [
        enable.get_json()["code"],
        save_config.get_json()["code"],
    ] == [
        "kalshi_real_credentials_missing",
        "kalshi_real_credentials_missing",
    ]
    assert after["enabled"] is False
    assert after["activeEnvironment"] == "paper"
    assert after["config"] == before["config"]
    assert after["modeState"] == before["modeState"]
    assert [event[0] for event in lease_store.events].count("claim") == 2


def test_real_control_mutation_routes_share_the_routing_fence(tmp_path):
    _durable, load_state, save_state = _durable_state_callbacks()
    connection = {
        "production_api_key_id": "key-id-12345678",
        "production_private_key": "private-key-present",
    }

    def save_connection(_user_id, _kind, payload):
        connection.clear()
        connection.update(copy.deepcopy(payload))
        return True, None

    lease_store = _FencedLeaseStore()
    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        get_user_config=lambda *_args: copy.deepcopy(connection),
        authoritative_config_loader=lambda *_args: copy.deepcopy(
            connection
        ),
        save_user_config=save_connection,
        robot_state_loader=load_state,
        robot_state_saver=save_state,
        worker_lease_store=lease_store,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )
    state = controls["robot_state"]
    state.configure("user-1", False, {"executionMode": "real"})
    state.configure("user-1", True, {"executionMode": "real"})
    client = app.test_client()

    responses = [
        client.post(
            "/api/kalshi/paper/robot",
            json={
                "enabled": False,
                "config": {"executionMode": "real"},
            },
        ),
        client.post(
            "/api/kalshi/paper/robot/config",
            json={"config": {"executionMode": "real"}},
        ),
        client.post(
            "/api/kalshi/paper/robot/config",
            json={"config": {"executionMode": "paper"}},
        ),
        client.post(
            "/api/kalshi/paper/robot",
            json={
                "enabled": False,
                "config": {"executionMode": "real"},
            },
        ),
        client.post(
            "/api/kalshi/config",
            json={
                "environment": "production",
                "apiKeyId": "********",
                "privateKey": "********",
            },
        ),
        client.delete(
            "/api/kalshi/config",
            json={"environment": "production"},
        ),
    ]

    assert [response.status_code for response in responses] == [200] * 6
    assert [event[0] for event in lease_store.events].count("claim") == 6
    assert [event[0] for event in lease_store.events].count("release") == 6


def test_robot_control_mutation_records_page_and_session_audit(tmp_path):
    audits = []
    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
        audit_recorder=lambda *args, **kwargs: audits.append((args, kwargs)),
    )
    controls["robot_state"].configure(
        "user-1",
        True,
        {"executionMode": "paper"},
    )

    response = app.test_client().post(
        "/api/kalshi/paper/robot",
        json={
            "enabled": False,
            "mode": "paper",
            "config": {"executionMode": "paper"},
            "controlContext": {
                "source": "kalshi-workspace-toggle",
                "sessionId": "browser-session-1",
                "page": "/kalshi/markets/btc-15m",
            },
        },
    )

    assert response.status_code == 200
    assert len(audits) == 1
    args, kwargs = audits[0]
    assert args[0:2] == ("user-1", "kalshi_robot_control")
    assert kwargs["actor"] == "user"
    assert kwargs["source"] == "kalshi-control:kalshi-workspace-toggle"
    assert kwargs["payload"]["requestedEnabled"] is False
    assert kwargs["payload"]["previousEnabled"] is True
    assert kwargs["payload"]["actualEnabled"] is False
    assert kwargs["payload"]["changed"] is True
    assert kwargs["payload"]["mode"] == "paper"
    assert kwargs["payload"]["controlSource"] == "kalshi-workspace-toggle"
    assert kwargs["payload"]["clientSessionId"] == "browser-session-1"
    assert kwargs["payload"]["page"] == "/kalshi/markets/btc-15m"
    assert kwargs["payload"]["referrerPath"] == ""
    assert len(kwargs["payload"]["userAgentHash"]) == 16
    assert kwargs["payload"]["occurredAt"].endswith("Z")


def test_real_control_mutation_fails_closed_without_durable_fence(tmp_path):
    connection = {
        "production_api_key_id": "key-id-12345678",
        "production_private_key": "private-key-present",
    }
    app = Flask(__name__)
    register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        get_user_config=lambda *_args: copy.deepcopy(connection),
        authoritative_config_loader=lambda *_args: copy.deepcopy(
            connection
        ),
        save_user_config=lambda *_args: (True, None),
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )

    response = app.test_client().post(
        "/api/kalshi/config",
        json={
            "environment": "production",
            "apiKeyId": "********",
            "privateKey": "********",
        },
    )

    assert response.status_code == 503
    assert response.get_json()["code"] == "kalshi_routing_fence_unavailable"


def test_concurrent_real_stop_linearizes_with_post_and_blocks_later_posts(
    tmp_path,
):
    _durable, load_state, save_state = _durable_state_callbacks()
    connection = {
        "production_api_key_id": "key-id-12345678",
        "production_private_key": "private-key-present",
    }
    lease_store = _MutualFencedLeaseStore()
    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        get_user_config=lambda *_args: copy.deepcopy(connection),
        authoritative_config_loader=lambda *_args: copy.deepcopy(
            connection
        ),
        save_user_config=lambda *_args: (True, None),
        robot_state_loader=load_state,
        robot_state_saver=save_state,
        worker_lease_store=lease_store,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )
    state = controls["robot_state"]
    state.configure("user-1", False, {"executionMode": "real"})
    state.configure("user-1", True, {"executionMode": "real"})
    controller = controls["paper_robot"]
    account_read = threading.Event()
    allow_post = threading.Event()
    posts = []
    ordering = []

    def signed_request(_config, _environment, method, endpoint, **kwargs):
        if method == "POST":
            posts.append(time.monotonic())
            ordering.append("post")
            body = kwargs["json_body"]
            return {"order": {
                "order_id": "linearized-order",
                "client_order_id": body["client_order_id"],
                "ticker": body["ticker"],
                "side": body["side"],
                "count_fp": body["count"],
                "fill_count_fp": body["count"],
                "price": body["price"],
                "status": "filled",
            }}
        if endpoint == "/portfolio/orders":
            account_read.set()
            assert allow_post.wait(2.0)
        return _real_preflight_response(endpoint)

    controller.signed_request = signed_request
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-LINEARIZED",
    )
    worker_errors = []
    stop_result = []

    def submit_worker():
        try:
            controller._submit_live_order(
                "user-1",
                payload,
                {"side": "YES", "action": "BUY_YES"},
            )
        except Exception as exc:  # pragma: no cover - assertion below
            worker_errors.append(exc)

    def stop_worker():
        with app.test_client() as client:
            response = client.post(
                "/api/kalshi/paper/robot",
                json={
                    "enabled": False,
                    "config": {"executionMode": "real"},
                },
            )
            ordering.append("stop_return")
            stop_result.append((response, time.monotonic()))

    submit_thread = threading.Thread(target=submit_worker)
    stop_thread = threading.Thread(target=stop_worker)
    submit_thread.start()
    assert account_read.wait(2.0)
    stop_thread.start()
    time.sleep(0.05)
    assert stop_result == []
    allow_post.set()
    submit_thread.join(timeout=3.0)
    stop_thread.join(timeout=3.0)

    assert not submit_thread.is_alive()
    assert not stop_thread.is_alive()
    assert worker_errors == []
    assert len(posts) == 1
    assert stop_result[0][0].status_code == 200
    assert ordering == ["post", "stop_return"]
    assert state.refresh("user-1")["enabled"] is False

    with pytest.raises(KalshiApiError) as stopped:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )
    assert stopped.value.code == "kalshi_automation_stopped"
    assert len(posts) == 1


def test_concurrent_paper_and_real_config_mutations_are_linearized(
    tmp_path,
):
    _durable, load_state, save_state = _durable_state_callbacks()
    connection = {
        "production_api_key_id": "key-id-12345678",
        "production_private_key": "private-key-present",
    }
    lease_store = _MutualFencedLeaseStore()
    app = Flask(__name__)
    controls = register_kalshi_api(
        app,
        require_auth=lambda: {"id": "user-1"},
        get_user_config=lambda *_args: copy.deepcopy(connection),
        authoritative_config_loader=lambda *_args: copy.deepcopy(
            connection
        ),
        save_user_config=lambda *_args: (True, None),
        robot_state_loader=load_state,
        robot_state_saver=save_state,
        worker_lease_store=lease_store,
        robot_state_path=str(tmp_path / "state.json"),
        paper_account_path=str(tmp_path / "paper.json"),
    )
    state = controls["robot_state"]
    state.configure("user-1", False, {"executionMode": "paper"})
    original_configure = state.configure
    paper_inside_mutation = threading.Event()
    allow_paper_mutation = threading.Event()

    def blocking_configure(user_id, enabled, config):
        if (
            str((config or {}).get("executionMode") or "") == "paper"
            and not paper_inside_mutation.is_set()
        ):
            paper_inside_mutation.set()
            assert allow_paper_mutation.wait(2.0)
        return original_configure(user_id, enabled, config)

    state.configure = blocking_configure
    responses = []

    def save_mode(mode):
        with app.test_client() as client:
            response = client.post(
                "/api/kalshi/paper/robot/config",
                json={"config": {"executionMode": mode}},
            )
            responses.append((mode, response.status_code))

    paper_thread = threading.Thread(target=save_mode, args=("paper",))
    real_thread = threading.Thread(target=save_mode, args=("real",))
    paper_thread.start()
    assert paper_inside_mutation.wait(2.0)
    real_thread.start()
    time.sleep(0.05)
    assert responses == []
    allow_paper_mutation.set()
    paper_thread.join(timeout=3.0)
    real_thread.join(timeout=3.0)

    assert not paper_thread.is_alive()
    assert not real_thread.is_alive()
    assert responses == [("paper", 200), ("real", 200)]
    final_state = state.refresh("user-1")
    assert final_state["activeEnvironment"] == "real"
    assert final_state["enabled"] is False
    assert [event[0] for event in lease_store.events].count("claim") == 2


def test_real_order_never_posts_when_refresh_is_only_local_cache():
    posts = []

    class LocalOnlyState:
        def refresh(self, _user_id, *, environment=None):
            return {
                "enabled": True,
                "activeEnvironment": "real",
                "config": {"executionMode": "real"},
                "strategy": {},
                "authoritativeRefresh": False,
                "durableStateLoaderAvailable": False,
            }

    def signed_request(_config, _environment, method, _endpoint, **kwargs):
        if method == "POST":
            posts.append(kwargs.get("json_body"))
        return {"orders": []}

    controller = _PaperRobotController(
        None,
        LocalOnlyState(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-TEST",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )

    assert blocked.value.code == "kalshi_robot_state_not_authoritative"
    assert posts == []


def test_real_order_blocks_deleted_credentials_despite_stale_process_cache():
    transport_calls = []
    controller = _PaperRobotController(
        None,
        _EnabledRealState(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "deleted-key-id-123456",
            "production_private_key": "deleted-private-material",
        },
        authoritative_connection_loader=lambda _uid: {},
        signed_request=lambda *_args, **_kwargs: transport_calls.append(1),
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-DELETED-CREDENTIAL",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )

    assert blocked.value.code == "kalshi_real_credentials_missing"
    assert transport_calls == []


def test_real_order_submission_uses_current_event_order_endpoint_without_side_rewrite():
    calls = []

    def signed_request(config, environment, method, endpoint, **kwargs):
        calls.append((config, environment, method, endpoint, kwargs))
        if method == "GET":
            return _real_preflight_response(endpoint)
        body = kwargs["json_body"]
        return {"order": {
            "order_id": "order-yes-1",
            "ticker": body["ticker"],
            "client_order_id": body["client_order_id"],
            "side": body["side"],
            "count_fp": body["count"],
            "fill_count_fp": body["count"],
            "price": body["price"],
            "status": "filled",
        }}

    controller = _PaperRobotController(
        client=None,
        state=_EnabledRealState(),
        paper_accounts=None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {"action": "BUY_YES", "side": "YES", "edge": {"price": 0.42}, "sizing": {"contracts": 7}},
        "KXBTC15M-TEST",
        exchange_index=2,
    )
    order = controller._submit_live_order("user-1", payload, {"side": "YES", "config": {"executionMode": "real"}})

    assert [call[3] for call in calls[:3]] == [
        "/portfolio/balance",
        "/portfolio/positions",
        "/portfolio/orders",
    ]
    assert calls[3][1:4] == (
        "production",
        "POST",
        "/portfolio/events/orders",
    )
    assert calls[3][4]["json_body"]["side"] == "bid"
    assert calls[3][4]["json_body"]["price"] == "0.4200"
    assert order["environment"] == "real"
    assert order["outcome_side"] == "YES"


def test_real_preflight_honors_engine_authorized_small_account_contract():
    calls = []

    def signed_request(config, environment, method, endpoint, **kwargs):
        calls.append((config, environment, method, endpoint, kwargs))
        if method == "GET":
            return _real_preflight_response(
                endpoint,
                balance=1_987,
                portfolio_value=0,
            )
        body = kwargs["json_body"]
        return {"order": {
            "order_id": "order-micro-1",
            "ticker": body["ticker"],
            "client_order_id": body["client_order_id"],
            "side": body["side"],
            "count_fp": body["count"],
            "fill_count_fp": body["count"],
            "price": body["price"],
            "status": "filled",
        }}

    controller = _PaperRobotController(
        client=None,
        state=_EnabledRealState(),
        paper_accounts=None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    decision = {
        "side": "YES",
        "action": "BUY_YES",
        "edge": {
            "price": 0.89,
            "netEdge": 0.04,
            "conservativeEdge": 0.02,
        },
        "sizing": {
            "contracts": 1,
            "microSizingApplied": True,
        },
    }
    payload = _paper_order_payload(
        decision,
        "KXBTCD-27JUL2618-T65000",
    )

    order = controller._submit_live_order(
        "user-1",
        payload,
        decision,
    )

    assert order["order_id"] == "order-micro-1"
    assert order["fill_count_fp"] == 1
    assert calls[-1][2:4] == (
        "POST",
        "/portfolio/events/orders",
    )


@pytest.mark.parametrize(
    ("account_overrides", "expected_code"),
    [
        (
            {"balance": 20, "portfolio_value": 0},
            "kalshi_live_cash_changed",
        ),
        (
            {
                "positions": [{
                    "ticker": "KXBTC15M-FRESH-GUARD",
                    "position_fp": 1,
                    "yes_count_fp": 1,
                    "market_exposure_dollars": 0.42,
                }],
            },
            "kalshi_live_position_ownership_conflict",
        ),
        (
            {
                "orders": [{
                    "order_id": "manual-resting",
                    "client_order_id": "manual-client",
                    "ticker": "KXBTC15M-FRESH-GUARD",
                    "status": "resting",
                    "count_fp": 1,
                    "fill_count_fp": 0,
                    "price_dollars": 0.42,
                }],
            },
            "kalshi_live_open_order_conflict",
        ),
    ],
)
def test_real_prepost_guard_blocks_fresh_account_changes(
    account_overrides,
    expected_code,
):
    posts = []

    def signed_request(_config, _environment, method, endpoint, **_kwargs):
        if method == "POST":
            posts.append(1)
            return {"order": {}}
        return _real_preflight_response(
            endpoint,
            **account_overrides,
        )

    controller = _PaperRobotController(
        None,
        _EnabledRealState(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-FRESH-GUARD",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )

    assert blocked.value.code == expected_code
    assert posts == []


@pytest.mark.parametrize(
    "positions",
    [
        [{
            "ticker": "KXBTC15M-MANUAL-REDUCE",
            "position_fp": 1,
            "yes_count_fp": 1,
            "market_exposure_dollars": 0.42,
        }],
        [],
    ],
)
def test_real_preflight_blocks_manual_reduction_of_managed_inventory(
    positions,
):
    posts = []
    state = _EnabledRealState(filled_trades=[{
        "orderFilled": True,
        "orderId": "managed-two",
        "generatedAt": "2026-07-27T01:00:00Z",
        "ticker": "KXBTC15M-MANUAL-REDUCE",
        "action": "BUY_YES",
        "side": "YES",
        "fillCount": 2,
    }])

    def signed_request(_config, _environment, method, endpoint, **_kwargs):
        if method == "POST":
            posts.append(1)
            return {"order": {}}
        return _real_preflight_response(endpoint, positions=positions)

    controller = _PaperRobotController(
        None,
        state,
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-MANUAL-REDUCE",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )

    assert blocked.value.code == "kalshi_live_position_ownership_conflict"
    assert posts == []


def test_real_preflight_follows_order_cursor_before_routing():
    order_cursors = []
    posts = []

    def signed_request(_config, _environment, method, endpoint, **kwargs):
        if method == "POST":
            posts.append(1)
            return {"order": {}}
        if endpoint == "/portfolio/orders":
            cursor = (kwargs.get("params") or {}).get("cursor")
            order_cursors.append(cursor)
            if not cursor:
                return {"orders": [], "cursor": "page-2"}
            return {"orders": [{
                "order_id": "page-two-open",
                "client_order_id": "different-client",
                "ticker": "KXBTC15M-PAGED",
                "status": "resting",
                "count_fp": 1,
                "fill_count_fp": 0,
                "price_dollars": 0.42,
            }]}
        return _real_preflight_response(endpoint)

    controller = _PaperRobotController(
        None,
        _EnabledRealState(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-PAGED",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )

    assert blocked.value.code == "kalshi_live_open_order_conflict"
    assert order_cursors == [None, "page-2"]
    assert posts == []


def test_real_preflight_fails_closed_on_incomplete_position_page():
    posts = []

    def signed_request(_config, _environment, method, endpoint, **_kwargs):
        if method == "POST":
            posts.append(1)
            return {"order": {}}
        if endpoint == "/portfolio/positions":
            return {"market_positions": [], "complete": False}
        return _real_preflight_response(endpoint)

    controller = _PaperRobotController(
        None,
        _EnabledRealState(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-INCOMPLETE",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )

    assert blocked.value.code == "kalshi_live_preflight_incomplete"
    assert posts == []


def test_real_preflight_recomputes_official_fee_when_decision_omits_it():
    posts = []

    def signed_request(_config, _environment, method, endpoint, **_kwargs):
        if method == "POST":
            posts.append(1)
            return {"order": {}}
        return _real_preflight_response(
            endpoint,
            balance=42,
            portfolio_value=99_958,
        )

    controller = _PaperRobotController(
        None,
        _EnabledRealState(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-FEE-CASH",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )

    assert blocked.value.code == "kalshi_live_cash_changed"
    assert posts == []


@pytest.mark.parametrize(
    "ticker",
    [
        "KXBTC15M-29JUL261330-DAILY-LOSS",
        "KXBTCD-29JUL2614-T65000",
    ],
)
def test_real_preflight_allows_btc15m_and_hourly_buy_despite_durable_daily_loss(
    ticker,
):
    today = datetime.now(timezone.utc).date().isoformat()
    posts = []
    state = _EnabledRealState(strategy={
        "dailyPnlDate": today,
        "dailyPnl": -20.0,
    })

    def signed_request(_config, _environment, method, endpoint, **_kwargs):
        if method == "POST":
            posts.append(1)
            return {"order": {}}
        return _real_preflight_response(endpoint)

    controller = _PaperRobotController(
        None,
        state,
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        ticker,
    )

    controller._submit_live_order(
        "user-1",
        payload,
        {"side": "YES", "action": "BUY_YES"},
    )

    assert posts == [1]


def test_real_preflight_recomputes_account_wide_exposure_before_buy():
    posts = []

    def signed_request(_config, _environment, method, endpoint, **_kwargs):
        if method == "POST":
            posts.append(1)
            return {"order": {}}
        return _real_preflight_response(
            endpoint,
            positions=[{
                "ticker": "UNRELATED-MANUAL-MARKET",
                "position_fp": 100,
                "yes_count_fp": 100,
                "market_exposure_dollars": 99.80,
            }],
        )

    controller = _PaperRobotController(
        None,
        _EnabledRealState(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-EXPOSURE",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )

    assert blocked.value.code == "kalshi_live_exposure_changed"
    assert posts == []


@pytest.mark.parametrize(
    (
        "conflict_code",
        "status_code",
        "expected_intent",
        "expected_portfolio_reads",
        "conflict_section",
    ),
    [
        (
            "kalshi_live_exposure_changed",
            409,
            "WAIT_LIVE_ACCOUNT_REFRESH",
            2,
            "account",
        ),
        (
            "kalshi_market_not_found",
            404,
            "WAIT_LIVE_MARKET_REFRESH",
            1,
            "dataQuality",
        ),
        ("kalshi_account_request_failed", 503, "WAIT_LIVE_ROUTING_FAILURE", 1, "routingFailure"),
        ("ReadTimeout", None, "WAIT_LIVE_ROUTING_FAILURE", 1, "routingFailure"),
    ],
)
def test_real_tick_records_wait_after_final_routing_conflict(
    monkeypatch,
    conflict_code,
    status_code,
    expected_intent,
    expected_portfolio_reads,
    conflict_section,
):
    recorded = {}
    portfolio_reads = []
    submit_attempts = []
    observations = []
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "enabled": True,
                "activeEnvironment": "real",
                "config": {"executionMode": environment or "real"},
                "strategy": {},
                "tradedTickers": [],
                "filledTrades": [],
                "decisions": [{
                    "generatedAt": (
                        datetime.now(timezone.utc)
                        - timedelta(seconds=5)
                    ).isoformat(),
                    "ticker": "KXBTC15M-REFRESH",
                    "action": "WAIT",
                    "side": "YES",
                    "blockingReasons": ["entry_confirmation"],
                    "executionIntent": "WAIT_ENTRY_CONFIRMATION",
                }],
            }

        def record(self, _user_id, decision, order):
            recorded["decision"] = copy.deepcopy(decision)
            recorded["order"] = order
            return {"decision": decision, "order": order}

    class Client:
        def snapshot(self, **_kwargs):
            return {
                "market": {
                    "ticker": "KXBTC15M-REFRESH",
                    "exchange_index": 2,
                },
                "reference": {
                    "price": 65_000,
                    "candles": [],
                    "timestamp": now,
                },
                "orderbook": {},
                "orderbookAsOf": now,
            }

    decision = {
        "generatedAt": now,
        "action": "BUY_YES",
        "side": "YES",
        "model": {"fairYesProbability": 0.80},
        "edge": {
            "price": 0.50,
            "netEdge": 0.05,
            "conservativeEdge": 0.03,
        },
        "market": {
            "yesAskDepth": 20,
            "selectedDepth": 20,
        },
        "sizing": {"contracts": 1, "notional": 0.50},
        "gates": [],
        "blockingReasons": [],
        "config": {"executionMode": "real"},
    }
    monkeypatch.setattr(
        kalshi_api,
        "evaluate_btc15_contract",
        lambda *_args, **_kwargs: copy.deepcopy(decision),
    )
    controller = _PaperRobotController(
        Client(),
        State(),
        paper_accounts=None,
    )

    def portfolio(_user_id, *, mode, mutate=True):
        portfolio_reads.append((mode, mutate))
        return {
            "environment": "real",
            "balance": {
                "balance": 100_000,
                "portfolio_value": 0,
            },
            "positions": [],
            "orders": [],
            "fills": [],
            "warnings": [],
            "completeness": {},
        }

    monkeypatch.setattr(controller, "portfolio", portfolio)
    controller.observation_saver = lambda _user_id, observation: observations.append(observation)
    def fail_live_order(_user_id, payload, _decision):
        submit_attempts.append(payload)
        assert payload["exchange_index"] == 2
        if conflict_code == "ReadTimeout":
            raise kalshi_api.requests.exceptions.ReadTimeout("synthetic timeout")
        raise KalshiApiError(
            "Final Kalshi routing state changed.",
            status=status_code,
            code=conflict_code,
        )

    monkeypatch.setattr(controller, "_submit_live_order", fail_live_order)

    if conflict_section == "routingFailure":
        with pytest.raises(Exception) as failed:
            controller.tick("user-1", submit_order=True, mode="real")
        assert str(getattr(failed.value, "code", None) or type(failed.value).__name__) == conflict_code
        assert len(submit_attempts) == 1
        assert recorded["order"] is None
        assert recorded["decision"]["executionIntent"] == "WAIT_LIVE_ROUTING_FAILURE"
        assert len(observations) == 1
        assert observations[0]["features"]["routingFailure"]["code"] == conflict_code
        assert observations[0]["features"]["routingFailure"]["outcome"] == "unknown"
        assert observations[0]["features"]["observation"]["samplingPolicy"] == "routing_failure_unique"
        assert not observations[0].get("order_result")
        return

    result = controller.tick(
        "user-1",
        submit_order=True,
        mode="real",
    )

    assert result["orderSubmitted"] is False
    assert result["decision"]["action"] == "WAIT"
    assert result["decision"]["executionIntent"] == expected_intent
    assert conflict_code in result["decision"]["blockingReasons"]
    assert recorded["order"] is None
    assert recorded["decision"][conflict_section]["preflightConflict"] == (
        conflict_code
    )
    assert portfolio_reads == [("real", True)] * expected_portfolio_reads


def test_real_reduce_only_close_is_preserved_and_normalised_as_sell():
    calls = []

    def signed_request(config, environment, method, endpoint, **kwargs):
        if method == "GET":
            return _real_preflight_response(
                endpoint,
                positions=[{
                    "ticker": "KXBTC15M-TEST",
                    "position_fp": -4,
                    "no_count_fp": 4,
                    "market_exposure_dollars": 1.44,
                }],
            )
        calls.append(kwargs["json_body"])
        body = kwargs["json_body"]
        return {"order": {
            "order_id": "order-close-1",
            "ticker": body["ticker"],
            "client_order_id": body["client_order_id"],
            "side": body["side"],
            "count_fp": body["count"],
            "fill_count_fp": body["count"],
            "price": body["price"],
            "status": "filled",
        }}

    controller = _PaperRobotController(
        client=None,
        state=_EnabledRealState(
            filled_trades=[{
                "orderFilled": True,
                "orderId": "managed-entry",
                "generatedAt": "2026-07-27T01:00:00Z",
                "ticker": "KXBTC15M-TEST",
                "action": "BUY_NO",
                "side": "NO",
                "fillCount": 4,
            }],
            strategy={
                "dailyPnlDate": datetime.now(
                    timezone.utc
                ).date().isoformat(),
                "dailyPnl": -999.0,
            },
        ),
        paper_accounts=None,
            connection_loader=lambda _uid: {
                "production_api_key_id": "key-id-12345678",
                "production_private_key": "private-key-present",
            },
            authoritative_connection_loader=_test_real_credentials,
            signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {"action": "SELL_NO", "side": "NO", "edge": {"price": 0.36}, "sizing": {"contracts": 4}},
        "KXBTC15M-TEST",
    )
    order = controller._submit_live_order(
        "user-1",
        payload,
        {"side": "NO", "action": "SELL_NO", "config": {"executionMode": "real"}},
    )

    assert calls[0]["side"] == "bid"
    assert calls[0]["price"] == "0.6400"
    assert calls[0]["reduce_only"] is True
    assert order["action"] == "SELL"
    assert order["reduce_only"] is True


def test_real_order_post_is_blocked_when_fenced_lease_renewal_is_lost():
    posts = []

    def signed_request(_config, _environment, method, endpoint, **kwargs):
        if method == "GET":
            return _real_preflight_response(endpoint)
        posts.append(kwargs["json_body"])
        return {"order": {}}

    lease_store = _FencedLeaseStore(renews=False)
    controller = _PaperRobotController(
        client=None,
        state=_EnabledRealState(),
        paper_accounts=None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=lease_store,
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-TEST",
    )

    with pytest.raises(kalshi_api.KalshiApiError) as lost:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "config": {"executionMode": "real"}},
        )

    assert lost.value.code == "kalshi_routing_lease_lost"
    assert posts == []
    assert [event[0] for event in lease_store.events] == [
        "claim", "renew", "release",
    ]


def test_real_order_refreshes_durable_state_and_blocks_stale_worker_after_stop():
    transport_calls = []

    class StoppedDurableState:
        def get(self, _user_id, *, environment=None):
            raise AssertionError("submission must not trust cached get()")

        def refresh(self, _user_id, *, environment=None):
            return {
                "enabled": False,
                "activeEnvironment": "real",
                "config": {"executionMode": "real"},
                "authoritativeRefresh": True,
                "durableStateLoaderAvailable": True,
            }

    controller = _PaperRobotController(
        client=None,
        state=StoppedDurableState(),
        paper_accounts=None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        signed_request=lambda *_args, **_kwargs: transport_calls.append(1),
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-TEST",
    )

    with pytest.raises(KalshiApiError) as stopped:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "config": {"executionMode": "real"}},
        )

    assert stopped.value.code == "kalshi_automation_stopped"
    assert transport_calls == []


def test_real_order_allows_reentry_after_durable_stop_loss():
    transport_calls = []

    class StoppedTickerState:
        def refresh(self, _user_id, *, environment=None):
            return {
                "enabled": True,
                "activeEnvironment": "real",
                "config": {"executionMode": "real"},
                "authoritativeRefresh": True,
                "durableStateLoaderAvailable": True,
                "strategy": {
                    "stopLossReentryTickers": ["KXBTC15M-STOPPED"],
                },
            }

    def signed_request(
        _config,
        _environment,
        method,
        endpoint,
        **kwargs,
    ):
        transport_calls.append((method, endpoint))
        if method == "POST":
            body = kwargs["json_body"]
            return {"order": {
                "order_id": "reentry-after-stop",
                "client_order_id": body["client_order_id"],
                "ticker": body["ticker"],
                "side": body["side"],
                "count_fp": body["count"],
                "fill_count_fp": body["count"],
                "price": body["price"],
                "status": "filled",
            }}
        return _real_preflight_response(endpoint)

    controller = _PaperRobotController(
        None,
        StoppedTickerState(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-STOPPED",
    )

    controller._submit_live_order(
        "user-1",
        payload,
        {"side": "YES", "action": "BUY_YES"},
    )

    assert [endpoint for _method, endpoint in transport_calls] == [
        "/portfolio/balance",
        "/portfolio/positions",
        "/portfolio/orders",
        "/markets/KXBTC15M-STOPPED",
        "/portfolio/events/orders",
    ]


def test_real_order_requires_stronger_durable_same_ticker_reentry_signal():
    transport_calls = []
    recent_exit = (
        datetime.now(timezone.utc) - timedelta(seconds=120)
    ).isoformat()

    def signed_request(
        _config,
        _environment,
        method,
        endpoint,
        **_kwargs,
    ):
        transport_calls.append((method, endpoint))
        if method == "GET":
            return _real_preflight_response(endpoint)
        raise AssertionError("weak re-entry must not POST")

    controller = _PaperRobotController(
        None,
        _EnabledRealState(strategy={
            "lastExitTicker": "KXBTC15M-REENTRY",
            "lastExitAt": recent_exit,
            "settlementRecords": [],
        }),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-REENTRY",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order(
            "user-1",
            payload,
            {
                "action": "BUY_YES",
                "side": "YES",
                "edge": {
                    "fairProbability": 0.699,
                    "conservativeEdge": 0.02,
                },
            },
        )

    assert blocked.value.code == "kalshi_reentry_confirmation_required"
    assert transport_calls == [
        ("GET", "/portfolio/balance"),
        ("GET", "/portfolio/positions"),
        ("GET", "/portfolio/orders"),
    ]


def test_real_order_allows_confirmed_durable_same_ticker_reentry_signal():
    posts = []
    recent_exit = (
        datetime.now(timezone.utc) - timedelta(seconds=120)
    ).isoformat()

    def signed_request(
        _config,
        _environment,
        method,
        endpoint,
        **kwargs,
    ):
        if method == "GET":
            return _real_preflight_response(endpoint)
        posts.append(dict(kwargs["json_body"]))
        return {"order": {
            "order_id": "confirmed-reentry",
            **dict(kwargs["json_body"]),
            "status": "submitted",
        }}

    controller = _PaperRobotController(
        None,
        _EnabledRealState(strategy={
            "lastExitTicker": "KXBTC15M-REENTRY",
            "lastExitAt": recent_exit,
            "settlementRecords": [],
        }),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-REENTRY",
    )

    order = controller._submit_live_order(
        "user-1",
        payload,
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {
                "fairProbability": 0.71,
                "conservativeEdge": 0.013,
            },
        },
    )

    assert len(posts) == 1
    assert order["order_id"] == "confirmed-reentry"


def test_real_order_rechecks_mode_after_idempotency_read_before_post():
    posts = []

    class StopsDuringAccountRead:
        def __init__(self):
            self.refreshes = 0

        def refresh(self, _user_id, *, environment=None):
            self.refreshes += 1
            return {
                "enabled": self.refreshes == 1,
                "activeEnvironment": "real",
                "config": {"executionMode": "real"},
                "authoritativeRefresh": True,
                "durableStateLoaderAvailable": True,
                "strategy": {},
            }

    state = StopsDuringAccountRead()

    def signed_request(_config, _environment, method, endpoint, **kwargs):
        if method == "GET":
            return _real_preflight_response(endpoint)
        posts.append(kwargs["json_body"])
        return {"order": {}}

    controller = _PaperRobotController(
        None,
        state,
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed_request,
        worker_lease_store=_FencedLeaseStore(),
    )
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42},
            "sizing": {"contracts": 1},
        },
        "KXBTC15M-STOP-RACE",
    )

    with pytest.raises(KalshiApiError) as stopped:
        controller._submit_live_order(
            "user-1",
            payload,
            {"side": "YES", "action": "BUY_YES"},
        )

    assert state.refreshes == 2
    assert stopped.value.code == "kalshi_automation_stopped"
    assert posts == []


def test_complementary_fills_are_net_not_repeated_close_exposure():
    portfolio = {
        "positions": [{
            "ticker": "KXBTC15M-HEDGE",
            "yes_count_fp": 17,
            "no_count_fp": 17,
            "position_fp": 0,
        }]
    }
    assert _position_side_and_count(portfolio, "KXBTC15M-HEDGE") == (None, 0)


def test_complementary_fills_report_only_residual_direction():
    portfolio = {
        "positions": [{
            "ticker": "KXBTC15M-NET",
            "yes_count_fp": 10,
            "no_count_fp": 14,
            "position_fp": -4,
        }]
    }
    assert _position_side_and_count(portfolio, "KXBTC15M-NET") == ("NO", 4)


def test_reduce_only_sale_estimate_uses_depth_weighted_price_and_fees():
    estimate = _estimate_reduce_only_sale(
        "YES",
        6,
        {"yes": [[0.61, 2], [0.58, 4], [0.50, 10]], "no": []},
    )

    assert estimate["fillableCount"] == 6
    assert estimate["fullDepthAvailable"] is True
    assert estimate["averageBid"] == (0.61 * 2 + 0.58 * 4) / 6
    assert estimate["worstBid"] == 0.58
    assert estimate["estimatedExitFee"] > 0
    assert estimate["netProceeds"] < estimate["grossProceeds"]


@pytest.mark.parametrize("side", ["YES", "NO"])
def test_reduce_sale_estimate_matches_seller_credit_rounding(side):
    estimate = _estimate_reduce_only_sale(side, 0.33, {side.lower(): [[0.80, 0.33]]})
    assert estimate["netProceeds"] == 0.26
    assert estimate["estimatedExitFee"] == 0.004
    assert estimate["estimatedExitTradeFee"] == 0.0037


def _voluntary_sale_decision(side="YES", break_even=0.7425742574257426):
    return {
        "action": f"SELL_{side}", "side": side,
        "edge": {"price": 0.78, "conservativeEdge": 0.03, "minimumConservativeEdge": 0},
        "sizing": {"contracts": 1.01},
        "exitAnalysis": {
            "trigger": "fee_adjusted_take_profit",
            "breakEvenExitValuePerContract": break_even,
            "heldProbability": 0.73,
            "routeQuote": _estimate_reduce_only_sale(side, 0.50, {side.lower(): [[0.78, 0.50]]}),
        },
    }


@pytest.mark.parametrize("side", ["YES", "NO"])
def test_voluntary_sale_tightens_ioc_limit_before_scale_out_can_realize_loss(side):
    decision = _voluntary_sale_decision(side)
    payload = _paper_order_payload(decision, "KXBTC15M-EXIT", count_override=0.50, price_tolerance=0.01)
    assert payload["user_side_limit_price"] == "0.7700"
    unsafe = _voluntary_exit_route_economics(decision, payload, {}, allow_tightening=False)
    assert unsafe["allowed"] is False
    assert unsafe["netExitPnl"] == pytest.approx(-0.0012871287128712883)
    protected = _voluntary_exit_route_economics(decision, payload, {})
    assert protected["allowed"] is True
    assert protected["limitTightened"] is True
    assert protected["minimumExecutionPrice"] == 0.78
    assert protected["netExitPnlPerContract"] >= 0.015
    decision["exitAnalysis"]["routeEconomics"] = protected
    final = _paper_order_payload(decision, "KXBTC15M-EXIT", count_override=0.50, price_tolerance=0.01)
    assert final["count"] == "0.50"
    assert final["user_side_limit_price"] == "0.7800"
    assert _voluntary_exit_route_economics(decision, final, {}, allow_tightening=False)["allowed"] is True


@pytest.mark.parametrize("side", ["YES", "NO"])
def test_voluntary_exit_requires_observed_fragmented_slice_profit_not_single_fill_only(side):
    decision = _voluntary_sale_decision(side, break_even=0.65)
    decision["edge"]["price"] = 0.7155
    decision["exitAnalysis"]["heldProbability"] = 0.60
    quote = _estimate_reduce_only_sale(side, 0.10, {side.lower(): [[0.7156, 0.05], [0.7155, 0.05]]})
    decision["exitAnalysis"]["routeQuote"] = quote
    payload = _paper_order_payload(decision, "KXBTC15M-FRAGMENTED", count_override=0.10)
    guard = _voluntary_exit_route_economics(decision, payload, {})
    assert quote["netProceeds"] == 0.06
    assert guard["singleFillLimitNetProceeds"] == 0.07
    assert guard["routeQuoteMatchesPayload"] is True
    assert guard["observedSliceProfitable"] is False
    assert guard["netExitPnl"] == pytest.approx(-0.005)
    assert guard["allowed"] is False
    assert _voluntary_exit_route_economics(decision, payload, {}, allow_tightening=False)["allowed"] is False
    ticker = payload["ticker"]
    state = {"filledTrades": [{"orderFilled": True, "orderId": "fragmented-entry", "ticker": ticker,
                                "action": f"BUY_{side}", "side": side, "fillCount": 0.10}]}
    account = {"orders": [], "positions": [{"ticker": ticker, "position_fp": 0.10 if side == "YES" else -0.10,
                                            f"{side.lower()}_count_fp": 0.10, "market_exposure_dollars": 0.065}]}
    controller = _PaperRobotController(None, None, None)
    with pytest.raises(KalshiApiError) as failed:
        controller._validate_live_order_preflight(state, account, payload, _live_order_payload(payload), decision)
    assert failed.value.code == "kalshi_live_voluntary_exit_economics_changed"
    decision["exitAnalysis"]["trigger"] = "protective_stop_loss"
    assert _voluntary_exit_route_economics(decision, payload, {}) == {"applicable": False, "allowed": True}
    assert controller._validate_live_order_preflight(state, account, payload, _live_order_payload(payload), decision) is None


@pytest.mark.parametrize("change", [
    None, {"requestedCount": 1.0}, {"fillableCount": 0.49}, {"takerFeeRate": 0.14},
    {"grossProceeds": 0.80}, {"netProceeds": None}, {"worstBid": 0.77},
])
def test_voluntary_exit_rejects_missing_or_mismatched_ladder_quote(change):
    decision = _voluntary_sale_decision()
    payload = _paper_order_payload(decision, "KXBTC15M-EXIT", count_override=0.50)
    if change is None:
        decision["exitAnalysis"].pop("routeQuote")
    else:
        decision["exitAnalysis"]["routeQuote"].update(change)
    guard = _voluntary_exit_route_economics(decision, payload, {}, allow_tightening=False)
    assert guard["allowed"] is False
    assert guard["routeQuoteMatchesPayload"] is False


def test_final_exit_size_change_cannot_prorate_old_slice_economics():
    decision = _voluntary_sale_decision()
    payload = _paper_order_payload(decision, "KXBTC15M-EXIT", count_override=0.50)
    assert _voluntary_exit_route_economics(decision, payload, {}, allow_tightening=False)["allowed"] is True
    payload["count"] = "0.25"
    changed = _voluntary_exit_route_economics(decision, payload, {}, allow_tightening=False)
    assert changed["allowed"] is False
    assert changed["routeQuoteMatchesPayload"] is False


def test_voluntary_exit_does_not_increase_size_when_scale_out_is_uneconomic():
    decision = _voluntary_sale_decision(break_even=0.75)
    full = _estimate_reduce_only_sale("YES", 1.01, {"yes": [[0.78, 1.01]]})
    assert full["netProceeds"] / 1.01 - 0.75 > 0.01
    payload = _paper_order_payload(decision, "KXBTC15M-EXIT", count_override=0.50, price_tolerance=0.01)
    guard = _voluntary_exit_route_economics(decision, payload, {"minimumExitProfit": 0.01})
    # 0.38/0.5 - 0.75 = 0.01 is allowed; higher configured profit must wait.
    assert guard["allowed"] is True
    assert _voluntary_exit_route_economics(decision, payload, {"minimumExitProfit": 0.012})["allowed"] is False
    assert payload["count"] == "0.50"


@pytest.mark.parametrize("side", ["YES", "NO"])
def test_tick_prices_voluntary_scale_out_from_actual_shallow_slice(monkeypatch, side):
    ticker = "KXBTC15M-SHALLOW-EXIT"
    now = datetime.now(timezone.utc).isoformat()
    config = {"executionMode": "paper", "takeProfitScaleOutPct": 0.50}

    class State:
        def get(self, _user_id, *, environment=None):
            return {"enabled": True, "activeEnvironment": "paper", "config": config,
                    "strategy": {}, "tradedTickers": [], "filledTrades": []}

    class Client:
        def snapshot(self, **_kwargs):
            return {
                "market": {"ticker": ticker},
                "reference": {"price": 65_000, "candles": [], "timestamp": now},
                "orderbook": {side.lower(): [[0.85, 2], [0.65, 2]]},
                "orderbookAsOf": now, "warnings": [],
            }

    decision = {
        "generatedAt": now, "action": "WAIT", "side": side,
        "model": {"fairYesProbability": 0.70 if side == "YES" else 0.30},
        "market": {"ticker": ticker}, "edge": {"price": 0.85, "conservativeEdge": 0.03},
        "sizing": {"contracts": 0}, "gates": [], "blockingReasons": [], "config": config,
    }
    monkeypatch.setattr(kalshi_api, "evaluate_btc15_contract", lambda *_args, **_kwargs: copy.deepcopy(decision))
    controller = _PaperRobotController(Client(), State(), None)
    monkeypatch.setattr(controller, "portfolio", lambda *_args, **_kwargs: {
        "environment": "paper", "balance": {"balance": 100_000, "portfolio_value": 300},
        "positions": [{"ticker": ticker, f"{side.lower()}_count_fp": 4,
                       f"{side.lower()}_average_price_dollars": 0.68,
                       f"{side.lower()}_fee_cost_dollars": 0.04,
                       "last_trade_at": "2020-01-01T00:00:00Z"}],
        "orders": [], "fills": [], "settlements": [],
    })
    result = controller.tick("u", submit_order=False, mode="paper")
    actual = result["decision"]
    assert actual["action"] == f"SELL_{side}"
    assert actual["positionManagement"]["routedContracts"] == 2
    assert actual["exitAnalysis"]["worstBid"] == 0.65  # Original full-holding eligibility retained.
    assert actual["exitAnalysis"]["routeQuote"]["worstBid"] == 0.85
    assert actual["edge"]["price"] == 0.85
    assert actual["exitAnalysis"]["routeEconomics"]["allowed"] is True
    payload = _paper_order_payload(actual, ticker, count_override=2, price_tolerance=0.01)
    assert payload["count"] == "2.00"
    assert payload["user_side_reference_price"] == "0.8500"
    assert payload["user_side_limit_price"] == "0.8400"
    observation = _market_observation("paper", actual)
    assert observation["features"]["exitAnalysis"]["routeQuote"]["requestedCount"] == 2


@pytest.mark.parametrize("trigger", ["emergency_stop_loss", "protective_stop_loss"])
def test_urgent_exit_bypasses_voluntary_profit_gate(trigger):
    decision = _voluntary_sale_decision()
    decision["exitAnalysis"]["trigger"] = trigger
    payload = _paper_order_payload(decision, "KXBTC15M-EXIT", count_override=0.50, price_tolerance=0.01)
    assert _voluntary_exit_route_economics(decision, payload, {}) == {"applicable": False, "allowed": True}


def test_sale_fee_reconciliation_uses_route_price_and_seller_rounding():
    decision = _voluntary_sale_decision()
    decision["exitAnalysis"]["routeEconomics"] = {"allowed": True, "minimumExecutionPrice": 0.80}
    decision["sizing"]["allInFee"] = 99
    reconciliation = _fee_reconciliation(decision, {"count_fp": 0.33, "fill_count_fp": 0.33, "fee_cost_dollars": 0.004})
    assert reconciliation["expectedPrice"] == 0.80
    assert reconciliation["expectedFeeDollars"] == 0.004
    assert reconciliation["feeVarianceDollars"] == 0
    assert reconciliation["expectedCashDebitDollars"] is None
    assert reconciliation["expectedCashCreditDollars"] == 0.26


def test_real_preflight_catches_unprotected_voluntary_exit_but_preserves_stops():
    controller = _PaperRobotController(None, None, None)
    ticker = "KXBTC15M-EXIT"
    decision = _voluntary_sale_decision()
    decision["model"] = {"historyQuality": {"clockVerified": False}}
    state = {"filledTrades": [{"orderFilled": True, "orderId": "managed-entry", "ticker": ticker,
                                "action": "BUY_YES", "side": "YES", "fillCount": 1.01}]}
    account = {"orders": [], "positions": [{"ticker": ticker, "position_fp": 1.01,
                                            "yes_count_fp": 1.01, "market_exposure_dollars": 0.73}]}
    payload = _paper_order_payload(decision, ticker, count_override=0.50, price_tolerance=0.01)
    with pytest.raises(KalshiApiError) as failed:
        controller._validate_live_order_preflight(state, account, payload, _live_order_payload(payload), decision)
    assert failed.value.code == "kalshi_live_voluntary_exit_economics_changed"
    decision["exitAnalysis"]["trigger"] = "protective_stop_loss"
    assert controller._validate_live_order_preflight(state, account, payload, _live_order_payload(payload), decision) is None


def test_real_buy_rejects_explicit_unverified_candle_clock_and_observation_keeps_quality():
    decision = _shard_test_decision()
    quality = {"clockVerified": False, "reason": "relative_fixture_timestamps"}
    decision["model"] = {"historyQuality": quality}
    payload = _paper_order_payload(decision, decision["market"]["ticker"], exchange_index=2)
    with pytest.raises(KalshiApiError) as failed:
        _PaperRobotController(None, None, None)._validate_live_order_preflight(
            {}, {"orders": []}, payload, _live_order_payload(payload), decision,
        )
    assert failed.value.code == "kalshi_live_history_clock_unverified"
    assert _market_observation("real", decision)["features"]["model"]["historyQuality"] == quality


def test_two_hourly_holdings_prioritize_emergency_exit_over_add():
    add_ticker = "KXBTCD-27JUL2613-T64000"
    emergency_ticker = "KXBTCD-27JUL2613-T66000"
    portfolio = {
        "environment": "paper",
        "positions": [
            {
                "ticker": add_ticker,
                "position_fp": 5,
                "yes_count_fp": 5,
                "yes_average_price_dollars": 0.40,
                "last_trade_at": "2026-07-27T00:00:00Z",
            },
            {
                "ticker": emergency_ticker,
                "position_fp": 5,
                "yes_count_fp": 5,
                "yes_average_price_dollars": 0.80,
                "last_trade_at": "2026-07-27T00:00:00Z",
            },
        ],
    }
    config = {
        "minimumHoldSeconds": 45,
        "exitProbabilityThreshold": 0.46,
        "stopLossPct": 0.35,
        "emergencyStopLossPct": 0.20,
        "minimumExitProfit": 0.01,
        "exitValueBuffer": 0.01,
    }
    add = {
        "action": "BUY_YES",
        "side": "YES",
        "model": {"fairYesProbability": 0.80},
        "edge": {"conservativeEdge": 0.04, "netEdge": 0.05},
    }
    emergency = {
        "action": "BUY_YES",
        "side": "YES",
        "model": {"fairYesProbability": 0.10},
        "edge": {"conservativeEdge": 0.001, "netEdge": 0.002},
    }
    book = {
        "yes": [[0.50, 100]],
        "no": [[0.48, 100]],
    }
    add_rank = _hourly_candidate_management_priority(
        add,
        {"ticker": add_ticker},
        book,
        portfolio,
        {},
        config,
    )
    emergency_rank = _hourly_candidate_management_priority(
        emergency,
        {"ticker": emergency_ticker},
        book,
        portfolio,
        {},
        config,
    )

    selected = max(
        [
            (add_rank, add_ticker),
            (emergency_rank, emergency_ticker),
        ],
        key=lambda item: item[0],
    )
    assert add_rank[0] == 2
    assert emergency_rank[0] == 7
    assert selected[1] == emergency_ticker


def test_two_hourly_holdings_prioritize_unfillable_exit_attention_over_add():
    add_ticker = "KXBTCD-27JUL2613-T64000"
    distressed_ticker = "KXBTCD-27JUL2613-T66000"
    portfolio = {
        "environment": "paper",
        "positions": [
            {
                "ticker": add_ticker,
                "position_fp": 5,
                "yes_count_fp": 5,
                "yes_average_price_dollars": 0.40,
                "last_trade_at": "2026-07-27T00:00:00Z",
            },
            {
                "ticker": distressed_ticker,
                "position_fp": 5,
                "yes_count_fp": 5,
                "yes_average_price_dollars": 0.80,
                "last_trade_at": "2026-07-27T00:00:00Z",
            },
        ],
    }
    config = {
        "minimumHoldSeconds": 45,
        "exitProbabilityThreshold": 0.46,
        "stopLossPct": 0.35,
        "emergencyStopLossPct": 0.20,
        "minimumExitProfit": 0.01,
        "exitValueBuffer": 0.01,
    }
    add = {
        "action": "BUY_YES",
        "side": "YES",
        "model": {"fairYesProbability": 0.80},
        "edge": {"conservativeEdge": 0.04, "netEdge": 0.05},
    }
    distressed = {
        "action": "WAIT",
        "side": "NO",
        "model": {"fairYesProbability": 0.10},
        "edge": {"conservativeEdge": -0.01, "netEdge": 0.0},
    }
    quoted_book = {
        "yes": [[0.50, 100]],
        "no": [[0.48, 100]],
    }
    no_bid_book = {"yes": [], "no": [[0.89, 100]]}

    add_rank = _hourly_candidate_management_priority(
        add,
        {"ticker": add_ticker},
        quoted_book,
        portfolio,
        {},
        config,
    )
    distressed_rank = _hourly_candidate_management_priority(
        distressed,
        {"ticker": distressed_ticker},
        no_bid_book,
        portfolio,
        {},
        config,
    )

    assert add_rank[0] == 2
    assert distressed_rank[0] == 5
    assert distressed_rank > add_rank


def test_fillable_protective_exit_outranks_unfillable_emergency_exit():
    protective_ticker = "KXBTCD-27JUL2613-T64000"
    emergency_ticker = "KXBTCD-27JUL2613-T66000"
    portfolio = {
        "environment": "paper",
        "positions": [
            {
                "ticker": protective_ticker,
                "position_fp": 5,
                "yes_count_fp": 5,
                "yes_average_price_dollars": 0.80,
                "last_trade_at": "2026-07-27T00:00:00Z",
            },
            {
                "ticker": emergency_ticker,
                "position_fp": 5,
                "yes_count_fp": 5,
                "yes_average_price_dollars": 0.80,
                "last_trade_at": "2026-07-27T00:00:00Z",
            },
        ],
    }
    config = {
        "minimumHoldSeconds": 60,
        "exitProbabilityThreshold": 0.46,
        "stopLossPct": 0.35,
        "emergencyStopLossPct": 0.20,
        "minimumExitProfit": 0.01,
        "exitValueBuffer": 0.01,
    }
    protective = {
        "action": "WAIT",
        "side": "YES",
        "model": {"fairYesProbability": 0.35},
        "edge": {"conservativeEdge": -0.01, "netEdge": 0.0},
    }
    emergency = {
        "action": "WAIT",
        "side": "YES",
        "model": {"fairYesProbability": 0.10},
        "edge": {"conservativeEdge": -0.01, "netEdge": 0.0},
    }
    fillable_book = {
        "yes": [[0.50, 100]],
        "no": [[0.48, 100]],
    }
    no_yes_bid_book = {
        "yes": [],
        "no": [[0.89, 100]],
    }

    protective_rank = _hourly_candidate_management_priority(
        protective,
        {"ticker": protective_ticker},
        fillable_book,
        portfolio,
        {},
        config,
    )
    emergency_rank = _hourly_candidate_management_priority(
        emergency,
        {"ticker": emergency_ticker},
        no_yes_bid_book,
        portfolio,
        {},
        config,
    )

    selected = max(
        [
            (protective_rank, protective_ticker),
            (emergency_rank, emergency_ticker),
        ],
        key=lambda item: item[0],
    )
    assert protective_rank[0] == 6
    assert emergency_rank[0] == 5
    assert selected[1] == protective_ticker


def test_protective_exit_uses_configured_threshold_and_emergency_floor():
    normal = _protective_exit_state(0.40, {"exitProbabilityThreshold": 0.46})
    emergency = _protective_exit_state(0.25, {"exitProbabilityThreshold": 0.46})
    healthy = _protective_exit_state(0.60, {"exitProbabilityThreshold": 0.46})

    assert normal["protectiveExit"] is True
    assert normal["emergencyExit"] is False
    assert emergency["protectiveExit"] is True
    assert emergency["emergencyExit"] is True
    assert emergency["emergencyExitThreshold"] == 0.26
    assert healthy["protectiveExit"] is False


def test_probability_dip_alone_cannot_force_a_small_loss_exit():
    state = _exit_economic_state(
        average_entry_price=0.30,
        allocated_entry_fee=0.30,
        held_count=100,
        net_exit_value_per_contract=0.28,
        held_probability=0.40,
        strategy_config={
            "exitProbabilityThreshold": 0.46,
            "minimumExitProfit": 0.01,
            "stopLossPct": 0.35,
            "emergencyStopLossPct": 0.20,
        },
    )

    assert state["protectiveExit"] is True
    assert state["profitableExit"] is False
    assert state["protectiveLossExit"] is False
    assert state["lossExitAuthorized"] is False


def test_take_profit_is_measured_after_entry_and_exit_fees():
    state = _exit_economic_state(
        average_entry_price=0.30,
        allocated_entry_fee=1.0,
        held_count=100,
        net_exit_value_per_contract=0.325,
        held_probability=0.60,
        strategy_config={"minimumExitProfit": 0.01},
    )

    assert state["breakEvenExitValuePerContract"] == 0.31
    assert round(state["netExitPnlPerContract"], 6) == 0.015
    assert state["profitableExit"] is True
    assert state["lossExitAuthorized"] is False


def test_open_live_fill_inventory_rebuilds_fifo_cost_after_partial_sale():
    inventory = _open_live_fill_inventory([
        {
            "fill_id": "buy-1", "ticker": "KXBTC15M-FIFO", "outcome_side": "YES",
            "action": "BUY", "count_fp": 4, "average_price_dollars": 0.40,
            "fee_cost_dollars": 0.04, "created_time": "2026-07-25T00:00:00Z",
        },
        {
            "fill_id": "buy-2", "ticker": "KXBTC15M-FIFO", "outcome_side": "YES",
            "action": "BUY", "count_fp": 4, "average_price_dollars": 0.60,
            "fee_cost_dollars": 0.08, "created_time": "2026-07-25T00:01:00Z",
        },
        {
            "fill_id": "sell-1", "ticker": "KXBTC15M-FIFO", "outcome_side": "YES",
            "action": "SELL", "count_fp": 5, "average_price_dollars": 0.70,
            "fee_cost_dollars": 0.03, "created_time": "2026-07-25T00:02:00Z",
        },
    ])

    row = inventory[("KXBTC15M-FIFO", "YES")]
    assert row["count"] == 3
    assert round(row["principal"], 8) == 1.8
    assert round(row["averagePrice"], 8) == 0.6
    assert round(row["entryFee"], 8) == 0.06


def test_material_loss_requires_the_matching_probability_stop_gate():
    protective = _exit_economic_state(
        average_entry_price=0.40,
        allocated_entry_fee=1.0,
        held_count=100,
        net_exit_value_per_contract=0.25,
        held_probability=0.40,
        strategy_config={
            "exitProbabilityThreshold": 0.46,
            "stopLossPct": 0.35,
            "emergencyStopLossPct": 0.20,
        },
    )
    emergency = _exit_economic_state(
        average_entry_price=0.40,
        allocated_entry_fee=1.0,
        held_count=100,
        net_exit_value_per_contract=0.31,
        held_probability=0.20,
        strategy_config={
            "exitProbabilityThreshold": 0.46,
            "stopLossPct": 0.35,
            "emergencyStopLossPct": 0.20,
        },
    )

    assert protective["protectiveLossExit"] is True
    assert protective["emergencyLossExit"] is False
    assert emergency["protectiveLossExit"] is False
    assert emergency["emergencyLossExit"] is True


def test_persisted_entry_and_exit_times_survive_ephemeral_decision_history():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(seconds=12)).isoformat()
    state = {
        "strategy": {
            "lastEntryTicker": "KXBTC15M-TIMING",
            "lastEntryAt": recent,
            "lastExitTicker": "KXBTC15M-TIMING",
            "lastExitAt": recent,
        },
        "decisions": [{"ticker": "OTHER", "action": "WAIT"}],
    }

    assert 0 <= _recent_filled_entry_age(state, "KXBTC15M-TIMING") < 30
    assert 0 <= _recent_filled_exit_age(state, "KXBTC15M-TIMING") < 30


def test_position_execution_context_keeps_entry_cost_and_age_inputs():
    portfolio = {
        "positions": [{
            "ticker": "KXBTC15M-CONTEXT",
            "yes_count_fp": 8,
            "no_count_fp": 0,
            "yes_average_price_dollars": 0.41,
            "yes_fee_cost_dollars": 0.12,
            "last_trade_at": "2026-07-22T12:00:00Z",
        }],
    }

    context = _position_execution_context(portfolio, "KXBTC15M-CONTEXT")

    assert context["side"] == "YES"
    assert context["count"] == 8
    assert context["averageEntryPrice"] == 0.41
    assert context["allocatedEntryFee"] == 0.12


def test_evaluate_does_not_persist_a_trade(tmp_path):
    client = _app(tmp_path).test_client()
    payload = client.post("/api/kalshi/btc-15m/evaluate", json={"config": {}}).get_json()
    assert payload["success"] is True
    assert payload["robotState"]["decisions"] == []


def test_reset_clears_builtin_paper_ledger(tmp_path):
    client = _app(tmp_path).test_client()
    payload = client.delete("/api/kalshi/paper/portfolio").get_json()
    assert payload["success"] is True
    assert payload["portfolio"]["balance"]["balance"] == 1_000_000
    assert payload["state"]["strategy"]["settledSamples"] == 0


def test_fractional_contract_quantity_reaches_v2_order_payload_without_truncation():
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.42, "conservativeEdge": 0.03},
            "sizing": {
                "contracts": 0,
                "contractsFp": 0.37,
                "plannedContractsFp": 0.37,
            },
        },
        "KXBTC15M-FRACTIONAL",
    )

    assert _contract_quantity(0.379) == 0.37
    assert payload["count"] == "0.37"


def test_fractional_position_and_reduce_estimate_preserve_fixed_point_count():
    portfolio = {
        "environment": "paper",
        "positions": [{
            "ticker": "KXBTC15M-FP",
            "yes_count_fp": "0.37",
            "no_count_fp": "0.00",
        }],
    }

    assert _position_side_and_count(portfolio, "KXBTC15M-FP") == ("YES", 0.37)
    estimate = _estimate_reduce_only_sale(
        "YES",
        0.37,
        {"yes": [[0.60, 2.0]], "no": []},
    )
    assert estimate["requestedCount"] == 0.37
    assert estimate["fillableCount"] == 0.37


def test_hourly_candidate_score_penalizes_uncertain_ladder_winner():
    uncertain = _hourly_candidate_diagnostic(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {
                "netEdge": 0.04,
                "conservativeEdge": 0.03,
                "minimumConservativeEdge": 0.0075,
            },
            "model": {"uncertainty": 0.20},
        },
        {"ticker": "KXBTCD-E-T65000", "floor_strike": 65_000},
        32,
    )
    stable = _hourly_candidate_diagnostic(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {
                "netEdge": 0.025,
                "conservativeEdge": 0.018,
                "minimumConservativeEdge": 0.0075,
            },
            "model": {"uncertainty": 0.005},
        },
        {"ticker": "KXBTCD-E-T65100", "floor_strike": 65_100},
        32,
    )

    assert uncertain["multipleCandidatePenalty"] > stable["multipleCandidatePenalty"]
    assert uncertain["penaltyCleared"] is False
    assert stable["penaltyCleared"] is True
    assert stable["shrunkenScore"] > uncertain["shrunkenScore"]


def test_protective_exit_requires_durable_streak_but_emergency_is_immediate():
    now = datetime.now(timezone.utc)
    state = {
        "decisions": [
            {
                "generatedAt": (now - timedelta(seconds=5)).isoformat(),
                "ticker": "KXBTC15M-EXIT",
                "account": {"heldSide": "YES"},
                "blockingReasons": ["protective_exit_confirmation"],
            },
            {
                "generatedAt": (now - timedelta(seconds=10)).isoformat(),
                "ticker": "KXBTC15M-EXIT",
                "account": {"heldSide": "YES"},
                "blockingReasons": ["protective_exit_confirmation"],
            },
        ],
    }
    confirmed = _protective_exit_confirmation(
        state,
        "KXBTC15M-EXIT",
        "YES",
        {"protectiveLossExit": True, "emergencyLossExit": False},
        {},
        generated_at=now,
    )
    emergency = _protective_exit_confirmation(
        {},
        "KXBTC15M-EXIT",
        "YES",
        {"protectiveLossExit": True, "emergencyLossExit": True},
        {},
        generated_at=now,
    )

    assert confirmed["streak"] == 3
    assert confirmed["confirmed"] is True
    assert emergency["confirmed"] is True
    assert emergency["emergencyBypass"] is True


def _protective_cursor_fixture():
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    ticker = "KXBTC15M-CURSOR"
    cursor = {
        "ticker": ticker, "side": "YES", "generatedAt": (now - timedelta(seconds=5)).isoformat(),
        "streak": 2, "requiredSnapshots": 3, "confirmed": False,
        "dataQualityEligible": True, "maxGapSeconds": 30,
    }
    return now, ticker, cursor


def test_protective_confirmation_recovers_compact_cursor_without_full_history():
    now, ticker, cursor = _protective_cursor_fixture()
    result = _protective_exit_confirmation(
        {"strategy": {"protectiveExitConfirmations": {ticker: cursor}}},
        ticker, "YES", {"protectiveLossExit": True}, {}, generated_at=now,
    )
    assert result["streak"] == 3
    assert result["confirmed"] is True
    assert result["durableProgressUsed"] is True


def test_protective_confirmation_api_and_state_survive_restart_each_cycle(tmp_path):
    durable = {}

    def save(user_id, payload):
        durable[user_id] = copy.deepcopy(payload)
        return {"version": len(durable)}

    now, ticker, _cursor = _protective_cursor_fixture()
    for index in range(3):
        store = kalshi_api.KalshiRobotState(str(tmp_path / f"state-{index}.json"),
                                           state_loader=durable.get, state_saver=save)
        generated = now + timedelta(seconds=5 * index)
        confirmation = _protective_exit_confirmation(
            store.get("u", environment="real"), ticker, "YES",
            {"protectiveLossExit": True}, {}, generated_at=generated,
        )
        assert confirmation["streak"] == index + 1
        store.record("u", {
            "generatedAt": generated.isoformat(), "action": "WAIT", "side": "NO",
            "config": {"executionMode": "real"}, "market": {"ticker": ticker},
            "account": {"heldSide": "YES", "heldCount": 1},
            "blockingReasons": ["protective_exit_confirmation"],
            "protectiveConfirmation": confirmation,
        })
        assert "decisions" not in durable["u"]["modeState"]["real"]
    assert confirmation["confirmed"] is True


@pytest.mark.parametrize("change", [
    {"generatedAt": "2026-09-05T12:00:00+00:00"},
    {"generatedAt": "2026-09-05T12:00:01+00:00"},
    {"generatedAt": "2026-09-05T11:58:00+00:00"},
    {"side": "NO"}, {"dataQualityEligible": False}, {"streak": 0},
    {"required": False}, {"emergencyBypass": True},
])
def test_invalid_protective_cursor_never_resurrects_older_eligible_history(change):
    now, ticker, cursor = _protective_cursor_fixture()
    result = _protective_exit_confirmation(
        {"strategy": {"protectiveExitConfirmations": {ticker: {**cursor, **change}}},
         "decisions": [{"ticker": ticker, "generatedAt": cursor["generatedAt"],
                        "account": {"heldSide": "YES"}, "blockingReasons": ["protective_exit_confirmation"]}]},
        ticker, "YES", {"protectiveLossExit": True}, {}, generated_at=now,
    )
    assert result["streak"] == 1
    assert result["confirmed"] is False


@pytest.mark.parametrize("metadata", [
    {}, {"dataQualityEligible": False}, {"dataQualityEligible": True, "required": False},
    {"dataQualityEligible": True, "emergencyBypass": True}, {"dataQualityEligible": True, "streak": 0},
])
@pytest.mark.parametrize("use_cursor", [True, False])
def test_newer_ineligible_protective_frame_breaks_durable_and_legacy_streak(metadata, use_cursor):
    now, ticker, cursor = _protective_cursor_fixture()
    state = {
        "decisions": [{"ticker": ticker, "generatedAt": (now - timedelta(seconds=2)).isoformat(),
                       "account": {"heldSide": "YES"}, "blockingReasons": ["protective_exit_confirmation"],
                       "protectiveConfirmation": metadata}],
    }
    if use_cursor:
        state["strategy"] = {"protectiveExitConfirmations": {ticker: cursor}}
    result = _protective_exit_confirmation(state, ticker, "YES", {"protectiveLossExit": True}, {}, generated_at=now)
    assert result["streak"] == 1
    assert result["confirmed"] is False


def test_protective_confirmation_requires_unique_frames_not_replayed_timestamps():
    now, ticker, _cursor = _protective_cursor_fixture()
    repeated = {"ticker": ticker, "generatedAt": now.isoformat(), "account": {"heldSide": "YES"},
                "blockingReasons": ["protective_exit_confirmation"]}
    result = _protective_exit_confirmation({"decisions": [repeated, repeated]}, ticker, "YES",
                                           {"protectiveLossExit": True}, {}, generated_at=now)
    assert result["streak"] == 1
    emergency = _protective_exit_confirmation({"decisions": [repeated, repeated]}, ticker, "YES",
                                              {"emergencyLossExit": True}, {}, generated_at=now)
    assert emergency["confirmed"] is True
    assert emergency["emergencyBypass"] is True


@pytest.mark.parametrize("gate", ["reference_ready", "data_freshness", "history_sample"])
def test_model_data_gate_failure_cannot_advance_ordinary_protective_confirmation(gate):
    now, ticker, cursor = _protective_cursor_fixture()
    decision = {"gates": [{"key": gate, "status": "block"}], "dataQuality": {"warnings": []}}
    eligible = _protective_confirmation_data_quality(decision)
    assert eligible is False
    result = _protective_exit_confirmation(
        {"strategy": {"protectiveExitConfirmations": {ticker: cursor}}}, ticker, "YES",
        {"protectiveLossExit": True}, {}, generated_at=now, data_quality_ok=eligible,
    )
    assert result["streak"] == 0
    assert result["dataQualityEligible"] is False
    assert result["confirmed"] is False


def test_exit_confirmation_quality_ignores_entry_window_but_requires_verified_clock():
    decision = {"gates": [{"key": "entry_window", "status": "block"}]}
    assert _protective_confirmation_data_quality(decision) is True
    decision["model"] = {"historyQuality": {"clockVerified": False}}
    assert _protective_confirmation_data_quality(decision) is False
    immediate = _protective_exit_confirmation({}, "KXBTC15M-E", "YES", {"emergencyLossExit": True}, {}, data_quality_ok=False)
    assert immediate["confirmed"] is True
    assert immediate["emergencyBypass"] is True


def test_protective_exit_streak_rejects_persisted_stale_marker():
    now = datetime.now(timezone.utc)
    stale_row = {
        "generatedAt": (now - timedelta(seconds=5)).isoformat(),
        "ticker": "KXBTC15M-STALE-EXIT",
        "account": {"heldSide": "YES"},
        "blockingReasons": ["protective_exit_confirmation"],
        "protectiveConfirmation": {"dataQualityEligible": False},
    }
    eligible_row = {
        **stale_row,
        "protectiveConfirmation": {"dataQualityEligible": True},
    }
    economics = {
        "protectiveLossExit": True,
        "emergencyLossExit": False,
    }

    rejected = _protective_exit_confirmation(
        {"decisions": [stale_row]},
        "KXBTC15M-STALE-EXIT",
        "YES",
        economics,
        {},
        generated_at=now,
    )
    accepted = _protective_exit_confirmation(
        {"decisions": [eligible_row]},
        "KXBTC15M-STALE-EXIT",
        "YES",
        economics,
        {},
        generated_at=now,
    )

    assert rejected["streak"] == 1
    assert rejected["confirmed"] is False
    assert accepted["streak"] == 2


def test_btc15_protective_exit_uses_latency_calibrated_gap():
    now = datetime.now(timezone.utc)
    economics = {
        "protectiveLossExit": True,
        "emergencyLossExit": False,
    }

    def state(ticker):
        return {"decisions": [{
            "generatedAt": (now - timedelta(seconds=25)).isoformat(),
            "ticker": ticker,
            "account": {"heldSide": "YES"},
            "blockingReasons": ["protective_exit_confirmation"],
        }]}

    btc15 = _protective_exit_confirmation(
        state("KXBTC15M-LATENCY"),
        "KXBTC15M-LATENCY",
        "YES",
        economics,
        {"protectiveExitConfirmations": 2},
        generated_at=now,
    )
    hourly = _protective_exit_confirmation(
        state("KXBTCD-LATENCY-T65000"),
        "KXBTCD-LATENCY-T65000",
        "YES",
        economics,
        {"protectiveExitConfirmations": 2},
        generated_at=now,
    )

    assert btc15["maxGapSeconds"] == pytest.approx(30.0)
    assert btc15["confirmed"] is True
    assert hourly["maxGapSeconds"] == pytest.approx(20.0)
    assert hourly["confirmed"] is False


def test_entry_confirmation_resets_when_hourly_selected_strike_changes():
    now = datetime.now(timezone.utc)
    current = {
        "generatedAt": now.isoformat(),
        "action": "BUY_YES",
    }
    same = _entry_confirmation(
        {"decisions": [{
            "generatedAt": (now - timedelta(seconds=5)).isoformat(),
            "ticker": "KXBTCD-E-T65000",
            "side": "YES",
            "blockingReasons": ["entry_confirmation"],
        }]},
        "KXBTCD-E-T65000",
        "YES",
        current,
        {},
    )
    switched = _entry_confirmation(
        {"decisions": [{
            "generatedAt": (now - timedelta(seconds=5)).isoformat(),
            "ticker": "KXBTCD-E-T65100",
            "side": "YES",
            "blockingReasons": ["entry_confirmation"],
        }]},
        "KXBTCD-E-T65000",
        "YES",
        current,
        {},
    )

    assert same["confirmed"] is True
    assert same["streak"] == 2
    assert switched["confirmed"] is False
    assert switched["streak"] == 1


def test_entry_confirmation_uses_family_latency_calibrated_gap():
    now = datetime.now(timezone.utc)
    current = {
        "generatedAt": now.isoformat(),
        "action": "BUY_YES",
    }

    def state(ticker):
        return {"decisions": [{
            "generatedAt": (now - timedelta(seconds=20)).isoformat(),
            "ticker": ticker,
            "side": "YES",
            "blockingReasons": ["entry_confirmation"],
        }]}

    btc15 = _entry_confirmation(
        state("KXBTC15M-LATENCY"),
        "KXBTC15M-LATENCY",
        "YES",
        current,
        {},
    )
    hourly = _entry_confirmation(
        state("KXBTCD-LATENCY-T65000"),
        "KXBTCD-LATENCY-T65000",
        "YES",
        current,
        {"entryConfirmationMaxGapSeconds": 15},
    )

    assert btc15["maxGapSeconds"] == pytest.approx(25.0)
    assert btc15["confirmed"] is True
    assert hourly["maxGapSeconds"] == pytest.approx(25.0)
    assert hourly["confirmed"] is True


def test_entry_confirmation_uses_compact_durable_progress_after_refresh():
    now = datetime.now(timezone.utc)
    state = {
        "strategy": {
            "entryConfirmations": {
                "btc15m": {
                    "ticker": "KXBTC15M-DURABLE",
                    "side": "YES",
                    "generatedAt": (now - timedelta(seconds=5)).isoformat(),
                    "streak": 1,
                    "requiredSnapshots": 2,
                    "confirmed": False,
                    "dataQualityEligible": True,
                    "maxGapSeconds": 25.0,
                },
            },
        },
        # Authoritative state intentionally excludes feature-heavy WAIT rows.
        "decisions": [],
    }

    confirmation = _entry_confirmation(
        state,
        "KXBTC15M-DURABLE",
        "YES",
        {
            "generatedAt": now.isoformat(),
            "action": "BUY_YES",
        },
        {},
    )

    assert confirmation["confirmed"] is True
    assert confirmation["streak"] == 2
    assert confirmation["durableProgressUsed"] is True


def test_pending_entry_confirmation_signature_only_marks_first_fresh_frame():
    base = {
        "decision": {
            "generatedAt": "2026-08-30T12:00:00Z",
            "action": "WAIT",
            "side": "YES",
            "market": {"ticker": "KXBTCD-E-T65000"},
            "blockingReasons": ["entry_confirmation"],
            "entryConfirmation": {
                "required": True,
                "requiredSnapshots": 2,
                "streak": 1,
                "confirmed": False,
            },
        },
    }

    signature = _pending_entry_confirmation_signature(
        base,
        "btchourly",
    )
    confirmed = copy.deepcopy(base)
    confirmed["decision"]["entryConfirmation"].update({
        "streak": 2,
        "confirmed": True,
    })

    assert signature == "btchourly:KXBTCD-E-T65000:YES"
    assert (
        _pending_entry_confirmation_signature(confirmed, "btchourly")
        is None
    )
    assert _pending_entry_confirmation_signature(base, "btc15m") is None


def test_scheduler_prioritizes_one_fresh_hourly_confirmation_followup():
    class State:
        @staticmethod
        def enabled_users():
            return ["user-a"]

        @staticmethod
        def get(_user_id):
            return {"config": {"executionMode": "real"}}

    class TwoCycles:
        calls = 0

        def wait(self, _seconds):
            self.calls += 1
            return self.calls > 2

    controller = _PaperRobotController(
        object(),
        State(),
        object(),
        safe_print=lambda *_args, **_kwargs: None,
    )
    calls = []
    hourly_calls = 0

    def tick(_user_id, *, family, **_kwargs):
        nonlocal hourly_calls
        calls.append(family)
        if family != "btchourly":
            return {"decision": {}}
        hourly_calls += 1
        pending = hourly_calls == 1
        return {
            "decision": {
                "generatedAt": (
                    f"2026-08-30T12:00:0{hourly_calls}Z"
                ),
                "action": "WAIT" if pending else "BUY_YES",
                "side": "YES",
                "market": {"ticker": "KXBTCD-E-T65000"},
                "blockingReasons": (
                    ["entry_confirmation"] if pending else []
                ),
                "entryConfirmation": {
                    "required": True,
                    "requiredSnapshots": 2,
                    "streak": 1 if pending else 2,
                    "confirmed": not pending,
                },
            },
        }

    controller.tick = tick
    controller._record_loop_success = lambda *_args: None
    controller._record_loop_failure = lambda *_args: None
    controller._loop(stop_event=TwoCycles())

    assert calls == ["btc15m", "btchourly", "btchourly", "btc15m"]


def test_scheduler_defers_routine_hourly_scan_for_btc15_first_frame():
    class State:
        @staticmethod
        def enabled_users():
            return ["user-a"]

        @staticmethod
        def get(_user_id):
            return {"config": {"executionMode": "real"}}

    class OneCycle:
        calls = 0

        def wait(self, _seconds):
            self.calls += 1
            return self.calls > 1

    controller = _PaperRobotController(
        object(),
        State(),
        object(),
        safe_print=lambda *_args, **_kwargs: None,
    )
    calls = []

    def tick(_user_id, *, family, **_kwargs):
        calls.append(family)
        return {
            "decision": {
                "generatedAt": "2026-08-30T12:00:01Z",
                "action": "WAIT",
                "side": "NO",
                "market": {"ticker": "KXBTC15M-PENDING"},
                "blockingReasons": ["entry_confirmation"],
                "entryConfirmation": {
                    "required": True,
                    "requiredSnapshots": 2,
                    "streak": 1,
                    "confirmed": False,
                },
            },
        }

    controller.tick = tick
    controller._record_loop_success = lambda *_args: None
    controller._record_loop_failure = lambda *_args: None
    controller._loop(stop_event=OneCycle())

    assert calls == ["btc15m"]


def test_scheduler_never_starves_hourly_for_repeated_btc15_first_frame():
    class State:
        @staticmethod
        def enabled_users():
            return ["user-a"]

        @staticmethod
        def get(_user_id):
            return {"config": {"executionMode": "real"}}

    class TwoCycles:
        calls = 0

        def wait(self, _seconds):
            self.calls += 1
            return self.calls > 2

    controller = _PaperRobotController(
        object(),
        State(),
        object(),
        safe_print=lambda *_args, **_kwargs: None,
    )
    calls = []

    def tick(_user_id, *, family, **_kwargs):
        calls.append(family)
        return {
            "decision": {
                "generatedAt": "2026-08-30T12:00:01Z",
                "action": "WAIT",
                "side": "NO",
                "market": {"ticker": "KXBTC15M-PENDING"},
                "blockingReasons": ["entry_confirmation"],
                "entryConfirmation": {
                    "required": True,
                    "requiredSnapshots": 2,
                    "streak": 1,
                    "confirmed": False,
                },
            },
        }

    controller.tick = tick
    controller._record_loop_success = lambda *_args: None
    controller._record_loop_failure = lambda *_args: None
    controller._loop(stop_event=TwoCycles())

    assert calls == ["btc15m", "btc15m", "btchourly"]


def test_entry_confirmation_rejects_stale_or_changed_durable_progress():
    now = datetime.now(timezone.utc)

    def confirmation(progress):
        return _entry_confirmation(
            {
                "strategy": {
                    "entryConfirmations": {"btchourly": progress},
                },
                "decisions": [],
            },
            "KXBTCD-E-T65000",
            "YES",
            {
                "generatedAt": now.isoformat(),
                "action": "BUY_YES",
            },
            {},
        )

    stale = confirmation({
        "ticker": "KXBTCD-E-T65000",
        "side": "YES",
        "generatedAt": (now - timedelta(seconds=40)).isoformat(),
        "streak": 1,
        "dataQualityEligible": True,
    })
    changed = confirmation({
        "ticker": "KXBTCD-E-T65100",
        "side": "YES",
        "generatedAt": (now - timedelta(seconds=5)).isoformat(),
        "streak": 1,
        "dataQualityEligible": True,
    })

    assert stale["confirmed"] is False
    assert stale["streak"] == 1
    assert changed["confirmed"] is False
    assert changed["streak"] == 1


def test_series_fee_policy_reads_current_and_scheduled_fee_metadata():
    calls = []

    def fake_get(url, params=None, **_kwargs):
        calls.append((url, dict(params or {})))
        if url.endswith("/series/KXBTCD"):
            return _Response({"series": {
                "ticker": "KXBTCD",
                "fee_type": "quadratic_with_maker_fees",
                "fee_multiplier": 1,
            }})
        if url.endswith("/series/fee_changes"):
            return _Response({"series_fee_change_arr": [{
                "id": "future-1",
                "series_ticker": "KXBTCD",
                "fee_type": "quadratic",
                "fee_multiplier": 2,
                "scheduled_ts": "2026-08-02T00:00:00Z",
            }]})
        raise AssertionError(url)

    policy = _PublicDataClient(http_get=fake_get).series_fee_policy("KXBTCD")

    assert policy["available"] is True
    assert policy["takerFeeCoefficient"] == 0.07
    assert policy["makerFeeCoefficient"] == 0.0175
    assert policy["scheduledChanges"][0]["feeMultiplier"] == 2
    assert any(url.endswith("/series/fee_changes") for url, _params in calls)


def test_maker_shadow_is_fail_closed_without_fee_rate_and_never_routes():
    decision = {
        "side": "YES",
        "market": {"yesBid": 0.40},
        "model": {"fairYesProbability": 0.70, "uncertainty": 0.01},
    }
    unavailable = _maker_shadow_diagnostic(decision, {}, {})
    available = _maker_shadow_diagnostic(
        decision,
        {
            "available": True,
            "makerRateKnown": True,
            "makerFeeCoefficient": 0.0175,
            "feeType": "quadratic_with_maker_fees",
            "feeMultiplier": 1,
        },
        {"minConservativeEdge": 0.0075, "minModelProbability": 0.64},
    )

    assert unavailable["opportunity"] is False
    assert unavailable["reason"] == "maker_fee_rate_unavailable"
    assert available["opportunity"] is True
    assert available["routeAllowed"] is False


def test_observation_persists_candidate_ladder_hold_counterfactual_and_fee_delta():
    decision = {
        "generatedAt": "2026-08-01T00:00:00Z",
        "action": "SELL_YES",
        "side": "YES",
        "market": {"ticker": "KXBTCD-E-T65000", "secondsToClose": 600},
        "model": {"fairYesProbability": 0.60},
        "edge": {"price": 0.55, "feePerContract": 0.02},
        "sizing": {"plannedContractsFp": 0.50},
        "candidateDiagnostics": {
            "candidateCount": 16,
            "selectedRank": 2,
            "topCandidates": [{"ticker": "KXBTCD-E-T65000"}],
        },
        "exitAnalysis": {
            "heldProbability": 0.60,
            "netExitValuePerContract": 0.54,
            "expectedHoldValuePerContract": 0.60,
            "holdVsExitExpectedDeltaPerContract": 0.06,
            "counterfactualPolicy": "hold_to_settlement_vs_executable_exit_v1",
            "fillableCount": 0.50,
            "estimatedExitFee": 0.01,
        },
    }
    order = {
        "count_fp": 0.50,
        "fill_count_fp": 0.50,
        "average_price_dollars": 0.55,
        "fee_cost_dollars": 0.02,
    }

    observation = _market_observation("real", decision, order)

    assert observation["features"]["candidateLadder"]["selectedRank"] == 2
    assert observation["features"]["exitAnalysis"][
        "holdVsExitExpectedDeltaPerContract"
    ] == 0.06
    assert observation["features"]["feeReconciliation"][
        "actualFeeDollars"
    ] == 0.02


def test_stability_metrics_expose_payoff_recovery_and_drawdown():
    metrics = _pnl_stability_metrics([0.20, 0.30, -0.60, 0.25])

    assert metrics["averageWin"] == 0.25
    assert metrics["averageLoss"] == 0.60
    assert metrics["profitFactor"] == 1.25
    assert metrics["recoveryMultiple"] == 2.4
    assert metrics["maxDrawdown"] == 0.60


def test_fractional_hourly_holding_keeps_executable_exit_management_priority():
    ticker = "KXBTCD-E-T65000"
    rank = _hourly_candidate_management_priority(
        {
            "action": "WAIT",
            "side": "YES",
            "model": {"fairYesProbability": 0.10},
            "edge": {"conservativeEdge": -0.02, "netEdge": -0.01},
        },
        {"ticker": ticker},
        {"yes": [[0.50, 0.40]], "no": [[0.48, 1.0]]},
        {
            "environment": "paper",
            "positions": [{
                "ticker": ticker,
                "position_fp": 0.40,
                "yes_count_fp": 0.40,
                "yes_average_price_dollars": 0.80,
                "last_trade_at": "2026-07-27T00:00:00Z",
            }],
        },
        {},
        {
            "minimumHoldSeconds": 0,
            "exitProbabilityThreshold": 0.35,
            "stopLossPct": 0.35,
            "emergencyStopLossPct": 0.20,
            "takerFeeRate": 0.07,
        },
    )

    assert rank[0] == 7


def test_fixed_point_order_fields_outrank_conflicting_legacy_counts():
    order = _normalise_live_order(
        {
            "order_id": "fixed-order",
            "ticker": "KXBTC15M-FIXED",
            "count": 1,
            "count_fp": "1.55",
            "fill_count": 1,
            "fill_count_fp": "1.25",
            "status": "partially_filled",
        },
        {"count": "1.55", "side": "bid", "price": "0.5000"},
        {"side": "YES", "action": "BUY_YES"},
    )

    assert order["count_fp"] == 1.55
    assert order["fill_count_fp"] == 1.25


def test_live_portfolio_prefers_fractional_position_over_legacy_integer(
    monkeypatch,
):
    class State:
        def get(self, _user_id, *, environment=None):
            return {
                "strategy": {},
                "filledTrades": [],
                "decisions": [],
                "modeState": {"real": {"displayBaseline": {}}},
            }

    def signed_request(_config, _environment, _method, endpoint, **_kwargs):
        if endpoint == "/portfolio/balance":
            return {"balance": 1_000, "portfolio_value": 100}
        if endpoint == "/portfolio/positions":
            return {"market_positions": [{
                "ticker": "KXBTC15M-FIXED-POS",
                "position": 1,
                "position_fp": "1.55",
                "yes_count": 1,
                "yes_count_fp": "1.55",
                "market_exposure_dollars": "0.70",
            }]}
        if endpoint == "/portfolio/orders":
            return {"orders": []}
        if endpoint == "/portfolio/fills":
            return {"fills": []}
        if endpoint == "/portfolio/settlements":
            return {"settlements": []}
        raise AssertionError(endpoint)

    controller = _PaperRobotController(
        None,
        State(),
        None,
        connection_loader=lambda _uid: {
            "production_api_key_id": "key-id-12345678",
            "production_private_key": "private-key-present",
        },
        signed_request=signed_request,
    )
    monkeypatch.setattr(
        controller,
        "_historical_account_rows",
        lambda *_args: {
            "orders": [], "fills": [], "complete": True, "warnings": []
        },
    )

    portfolio = controller._live_portfolio("user-1", mutate=False)

    assert portfolio["positions"][0]["net_count_fp"] == 1.55
    assert portfolio["positions"][0]["alphaLabUnmanagedCount"] == 1.55


def test_real_preflight_uses_cent_rounded_fractional_cash_debit():
    controller = _PaperRobotController(None, None, None)
    payload = _paper_order_payload(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {"price": 0.50, "conservativeEdge": 0.03},
            "sizing": {"plannedContractsFp": 0.30},
        },
        "KXBTC15M-CASH-ROUNDING",
    )

    with pytest.raises(KalshiApiError) as blocked:
        controller._validate_live_order_preflight(
            {
                "config": {"executionMode": "real", "takerFeeRate": 0.07},
                "strategy": {},
                "filledTrades": [],
            },
            {
                "balance": {"balance": 15, "portfolio_value": 0},
                "positions": [],
                "orders": [],
            },
            payload,
            _live_order_payload(payload),
            {
                "action": "BUY_YES",
                "side": "YES",
                "edge": {"price": 0.50},
                "config": {"takerFeeRate": 0.07},
            },
        )

    assert blocked.value.code == "kalshi_live_cash_changed"


def test_fractional_ioc_uses_planned_worst_price_and_passes_live_preflight():
    controller = _PaperRobotController(None, None, None)
    ticker = "KXBTC15M-PLANNED-DEPTH"
    decision = {
        "action": "BUY_YES",
        "side": "YES",
        "edge": {
            "price": 0.70,
            # The engine's execution limit is the marginal price for the
            # planned 0.51 contracts, not the farthest positive-edge level.
            "executionLimitPrice": 0.70,
            "feePerContract": 0.0147,
            "netEdge": 0.10,
            "conservativeEdge": 0.08,
        },
        "sizing": {"plannedContractsFp": 0.51},
        "config": {
            "executionMode": "real",
            "takerFeeRate": 0.07,
            "maxPortfolioExposurePct": 10.0,
            "maxSingleMarketExposurePct": 2.0,
        },
    }
    payload = _paper_order_payload(
        decision,
        ticker,
        price_tolerance=0.01,
        exchange_index=2,
    )
    latest_state = {
        "config": decision["config"],
        "strategy": {},
        "filledTrades": [],
    }
    account = {
        # Synthetic $20 balance; it is not derived from an account.
        "balance": _real_preflight_response("/portfolio/balance", balance=2_000),
        "positions": [],
        "orders": [],
    }

    assert payload["count"] == "0.51"
    assert payload["user_side_reference_price"] == "0.7000"
    assert payload["user_side_limit_price"] == "0.7000"
    assert controller._validate_live_order_preflight(
        latest_state,
        account,
        payload,
        _live_order_payload(payload),
        decision,
    ) is None

    # This is the old all-depth limit.  It proves the regression fixture is
    # meaningful: the same quantity would be rejected by the 2% market cap.
    old_wide_payload = {
        **payload,
        "price": "0.7900",
        "user_side_limit_price": "0.7900",
    }
    with pytest.raises(KalshiApiError) as blocked:
        controller._validate_live_order_preflight(
            latest_state,
            account,
            old_wide_payload,
            _live_order_payload(old_wide_payload),
            decision,
        )
    assert blocked.value.code == "kalshi_live_exposure_changed"


def test_fractional_ioc_exact_cap_uses_marginal_fee_not_top_quote_fee():
    controller = _PaperRobotController(None, None, None)
    ticker = "KXBTC15M-EXACT-CAP"
    decision = {
        "action": "BUY_YES",
        "side": "YES",
        "edge": {
            "price": 0.72,
            "executionLimitPrice": 0.75,
            # At the favorite-side top quote this per-contract fee is
            # slightly larger than the fee at the actual marginal limit.
            # Preflight must not mix the two price bases.
            "feePerContract": 0.0142,
            "minimumConservativeEdge": 0.01,
            "conservativeEdge": 0.08,
            "netEdge": 0.10,
        },
        "sizing": {
            "plannedContractsFp": 1.31,
            "riskBudget": 1.00,
            "maximumLoss": 1.00,
        },
        "config": {
            "executionMode": "real",
            "takerFeeRate": 0.07,
            "maxPortfolioExposurePct": 10.0,
            "maxSingleMarketExposurePct": 2.0,
        },
    }
    payload = _paper_order_payload(
        decision,
        ticker,
        price_tolerance=0.01,
        exchange_index=2,
    )
    latest_state = {
        "config": decision["config"],
        "strategy": {},
        "filledTrades": [],
    }
    account = {
        # Synthetic $50 balance: the 2% market cap is exactly $1.00.
        "balance": _real_preflight_response("/portfolio/balance", balance=5_000),
        "positions": [],
        "orders": [],
    }

    assert payload["count"] == "1.31"
    assert payload["user_side_reference_price"] == "0.7200"
    assert payload["user_side_limit_price"] == "0.7500"
    assert kalshi_api.kalshi_order_cost(0.75, 1.31, 0.07)[
        "cashDebit"
    ] == pytest.approx(1.00)
    assert 1.31 * 0.75 + 1.31 * 0.0142 > 1.00
    assert controller._validate_live_order_preflight(
        latest_state,
        account,
        payload,
        _live_order_payload(payload),
        decision,
    ) is None


def test_real_preflight_accepts_authoritative_durable_entry_confirmation():
    now = datetime.now(timezone.utc)
    ticker = "KXBTC15M-DURABLE-PREFLIGHT"
    controller = _PaperRobotController(None, None, None)
    decision = {
        "generatedAt": now.isoformat(),
        "action": "BUY_YES",
        "side": "YES",
        "edge": {
            "price": 0.50,
            "netEdge": 0.08,
            "conservativeEdge": 0.05,
            "feePerContract": 0.02,
        },
        "sizing": {"plannedContractsFp": 1.0},
        "entryConfirmation": {
            "required": True,
            "requiredSnapshots": 2,
            "streak": 2,
            "confirmed": True,
        },
        "config": {"executionMode": "real"},
    }
    payload = _paper_order_payload(decision, ticker, exchange_index=2)
    state = {
        "config": {"executionMode": "real"},
        "strategy": {
            "entryConfirmations": {
                "btc15m": {
                    "ticker": ticker,
                    "side": "YES",
                    "generatedAt": (
                        now - timedelta(seconds=5)
                    ).isoformat(),
                    "streak": 1,
                    "requiredSnapshots": 2,
                    "confirmed": False,
                    "dataQualityEligible": True,
                    "maxGapSeconds": 25.0,
                },
            },
        },
        "filledTrades": [],
        "decisions": [],
    }

    result = controller._validate_live_order_preflight(
        state,
        {
            "balance": _real_preflight_response("/portfolio/balance", balance=10_000),
            "positions": [],
            "orders": [],
        },
        payload,
        _live_order_payload(payload),
        decision,
    )

    assert result is None


def test_fee_reconciliation_includes_fractional_cent_rounding():
    reconciliation = _fee_reconciliation({
        "action": "BUY_YES",
        "side": "YES",
        "edge": {"price": 0.50},
        "sizing": {"plannedContractsFp": 0.30},
        "config": {"takerFeeRate": 0.07},
    })

    assert reconciliation["tradeFeeDollars"] == 0.0053
    assert reconciliation["roundingFeeDollars"] == pytest.approx(0.0047)
    assert reconciliation["expectedFeeDollars"] == 0.01
    assert reconciliation["expectedCashDebitDollars"] == 0.16


def test_reduce_exit_fee_estimate_uses_dynamic_taker_rate():
    normal = _estimate_reduce_only_sale(
        "YES", 1.0, {"yes": [[0.50, 1.0]], "no": []},
        taker_fee_rate=0.07,
    )
    doubled = _estimate_reduce_only_sale(
        "YES", 1.0, {"yes": [[0.50, 1.0]], "no": []},
        taker_fee_rate=0.14,
    )

    assert doubled["estimatedExitFee"] > normal["estimatedExitFee"]
    assert doubled["takerFeeRate"] == 0.14


def test_hourly_shrink_uses_effective_conservative_edge_floor():
    diagnostic = _hourly_candidate_diagnostic(
        {
            "action": "BUY_YES",
            "side": "YES",
            "edge": {
                "conservativeEdge": 0.020,
                "netEdge": 0.025,
                "minimumConservativeEdge": 0.0075,
                "effectiveMinimumConservativeEdge": 0.019,
            },
            "model": {"uncertainty": 0.01},
        },
        {"ticker": "KXBTCD-E-T65000", "floor_strike": 65_000},
        32,
    )

    assert diagnostic["minimumShrunkenScore"] == 0.019
    assert diagnostic["penaltyCleared"] is False


def _shard_test_decision(ticker="KXBTC15M-SHARD", action="BUY_YES"):
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "market": {"ticker": ticker, "exchangeIndex": 2},
        "action": action,
        "side": "YES",
        "edge": {"price": 0.50, "fairProbability": 0.80, "conservativeProbability": 0.75, "netEdge": 0.28, "conservativeEdge": 0.25},
        "sizing": {"plannedContractsFp": 1.0, "contractStep": 0.01},
        "config": {"executionMode": "real", "takerFeeRate": 0.07},
        "blockingReasons": [],
        "gates": [],
        "entryShadow": {"champion": {"qualifyingFrame": True}},
    }


@pytest.mark.parametrize("bad_index", [None, -1, "bad", 2.5, True, float("inf")])
def test_shard_index_never_guesses_from_invalid_metadata(bad_index):
    assert kalshi_api._exchange_shard_index(bad_index) is None


@pytest.mark.parametrize("rows", [None, [], [{"exchange_index": 2, "balance": "bad"}], [{"exchange_index": 2, "balance": "1.0"}] * 2])
def test_unknown_shard_balance_is_not_aggregate_cash(rows):
    assert kalshi_api._shard_cash_dollars({"balance": 100_000, "balance_breakdown": rows}, 2) is None


def test_shard_breakdown_preserves_dollars_and_zero_without_cent_conversion():
    balance = {"balance": 9_993, "balance_dollars": "99.9380", "balance_breakdown": [
        {"exchange_index": 0, "balance": "99.9380"},
        {"exchange_index": 2, "balance": "0.0000"},
    ]}
    context = _paper_account_context({"balance": balance}, {}, "KXBTC15M-SHARD", 99.938, exchange_index=2)
    assert context["aggregateCashAvailable"] == pytest.approx(99.938)
    assert context["shardCashAvailable"] == 0
    assert context["shardCashKnown"] is True
    assert context["fundingStatus"] == "empty"
    assert kalshi_api._shard_cash_dollars(balance, 0) == pytest.approx(99.938)


@pytest.mark.parametrize("ticker", ["KXBTC15M-SHARD", "KXBTCD-E-T65000"])
def test_empty_crypto_shard_explains_qualified_entry_without_hiding_strategy(ticker):
    decision = _shard_test_decision(ticker)
    context = kalshi_api._shard_funding_context({"balance": 10_000, "balance_breakdown": [
        {"exchange_index": 0, "balance": "100.0000"}, {"exchange_index": 2, "balance": "0.0000"},
    ]}, 2)
    assert kalshi_api._apply_real_shard_funding_gate(decision, context) is True
    assert decision["action"] == "WAIT"
    assert decision["executionIntent"] == "WAIT_LIVE_SHARD_FUNDING"
    assert decision["shardFunding"]["strategyAction"] == "BUY_YES"
    assert decision["shardFunding"]["strategyQualified"] is True
    assert decision["shardFunding"]["requiredCash"] == pytest.approx(0.52)
    assert decision["sizing"]["plannedContractsFp"] == 1.0
    observation = _market_observation("real", decision, submit_order=True)
    assert observation["features"]["market"]["exchangeIndex"] == 2
    assert observation["features"]["shardFunding"]["shardCashAvailable"] == 0
    assert observation["features"]["entryShadow"]["champion"]["qualifyingFrame"] is True


def test_empty_shard_never_blocks_reduce_only_exit():
    decision = _shard_test_decision(action="SELL_YES")
    assert kalshi_api._apply_real_shard_funding_gate(decision, {
        "exchangeIndex": 2, "shardCashAvailable": 0.0,
        "shardCashKnown": True, "fundingStatus": "empty",
    }) is False
    assert decision["action"] == "SELL_YES"
    assert decision["blockingReasons"] == []
    assert decision["shardFunding"]["applicable"] is False


def test_partial_shard_funding_caps_exact_rounded_debit_without_loosening_strategy():
    decision = _shard_test_decision()
    assert kalshi_api._apply_real_shard_funding_gate(decision, {
        "exchangeIndex": 2, "aggregateCashAvailable": 100.0,
        "shardCashAvailable": 0.15, "shardCashKnown": True, "fundingStatus": "funded",
    }) is False
    assert decision["action"] == "BUY_YES"
    assert decision["shardFunding"]["strategyPlannedContracts"] == 1.0
    assert decision["sizing"]["plannedContractsFp"] == pytest.approx(0.28)
    assert decision["shardFunding"]["fundedCashDebit"] == pytest.approx(0.15)
    assert decision["shardFunding"]["resizedExpectedValue"] > 0


def test_shard_downsizing_cannot_erase_fee_adjusted_expected_profit():
    decision = _shard_test_decision()
    decision["edge"]["fairProbability"] = 0.521
    decision["edge"]["conservativeProbability"] = 0.521
    assert kalshi_api._apply_real_shard_funding_gate(decision, {
        "exchangeIndex": 2, "aggregateCashAvailable": 100.0,
        "shardCashAvailable": 0.02, "shardCashKnown": True, "fundingStatus": "funded",
    }) is True
    assert decision["action"] == "WAIT"
    assert decision["shardFunding"]["resizedExpectedValue"] < 0


@pytest.mark.parametrize("shard_cash,expected_error", [("0.0000", "kalshi_live_shard_cash_insufficient"), (None, "kalshi_live_shard_cash_unavailable"), ("10.0000", None)])
def test_final_preflight_verifies_local_shard_cash(shard_cash, expected_error):
    controller = _PaperRobotController(None, None, None)
    decision = _shard_test_decision()
    payload = _paper_order_payload(decision, decision["market"]["ticker"], exchange_index=2)
    balance = {"balance": 10_000, "portfolio_value": 0, "balance_breakdown": [
        {"exchange_index": 0, "balance": "100.0000"},
    ]}
    if shard_cash is not None:
        balance["balance_breakdown"].append({"exchange_index": 2, "balance": shard_cash})
    args = ({"config": decision["config"], "strategy": {}, "filledTrades": []},
            {"balance": balance, "positions": [], "orders": []}, payload, _live_order_payload(payload), decision)
    if expected_error:
        with pytest.raises(KalshiApiError) as blocked:
            controller._validate_live_order_preflight(*args)
        assert blocked.value.code == expected_error
    else:
        assert controller._validate_live_order_preflight(*args) is None


def test_restricted_key_uses_one_explicit_shard_balance_read():
    calls = []
    def signed(_config, _environment, method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        return {"balance": 56, "balance_dollars": "0.5670", "portfolio_value": 0}
    controller = _PaperRobotController(None, None, None, signed_request=signed)
    account = {"balance": {"balance": 10_000, "portfolio_value": 0}}
    payload = {"ticker": "KXBTC15M-SHARD", "exchange_index": 2, "reduce_only": False}
    controller._complete_live_shard_preflight({}, account, payload)
    assert calls == [("GET", "/portfolio/balance", {"params": {"subaccount": 0, "exchange_index": 2}})]
    assert account["balance"]["balance"] == 10_000
    assert kalshi_api._shard_cash_dollars(account["balance"], 2) == pytest.approx(0.567)
    controller._complete_live_shard_preflight({}, account, payload)
    assert len(calls) == 1


def test_unknown_entry_shard_resolves_by_market_metadata_not_crypto_prefix():
    calls = []
    def signed(_config, _environment, method, endpoint, **kwargs):
        calls.append((method, endpoint))
        return {"market": {"ticker": "KXBTC15M-SHARD", "exchange_index": 3}}
    controller = _PaperRobotController(None, None, None, signed_request=signed)
    account = {"balance": {"balance": 1000, "balance_breakdown": [{"exchange_index": 3, "balance": "10.0000"}]}}
    payload = {"ticker": "KXBTC15M-SHARD", "exchange_index": -1}
    controller._complete_live_shard_preflight({}, account, payload)
    assert payload["exchange_index"] == 3
    assert calls == [("GET", "/markets/KXBTC15M-SHARD")]


def test_existing_order_idempotency_precedes_shard_funding_requirement():
    decision = _shard_test_decision()
    payload = _paper_order_payload(decision, decision["market"]["ticker"], exchange_index=-1)
    existing = {"client_order_id": payload["client_order_id"], "order_id": "already-submitted", "status": "filled"}
    controller = _PaperRobotController(None, None, None)
    assert controller._validate_live_order_preflight({}, {"orders": [existing]}, payload, _live_order_payload(payload), decision) == existing


@pytest.mark.parametrize("durable", [True, False])
def test_entry_confirmation_rejects_the_same_frame_replayed(durable):
    now = datetime.now(timezone.utc)
    ticker = "KXBTC15M-SAME-FRAME"
    frame = {"ticker": ticker, "side": "YES", "generatedAt": now.isoformat(),
             "streak": 1, "dataQualityEligible": True, "blockingReasons": ["entry_confirmation"]}
    state = {"strategy": {"entryConfirmations": {"btc15m": frame}} if durable else {}, "decisions": [frame]}
    result = _entry_confirmation(state, ticker, "YES", {"action": "BUY_YES", "generatedAt": now.isoformat()}, {})
    assert result["streak"] == 1
    assert result["confirmed"] is False


def test_durable_confirmation_cannot_skip_a_newer_invalid_frame():
    now = datetime.now(timezone.utc)
    ticker = "KXBTC15M-INVALID-FRAME"
    state = {
        "strategy": {"entryConfirmations": {"btc15m": {
            "ticker": ticker, "side": "YES", "generatedAt": (now - timedelta(seconds=10)).isoformat(),
            "streak": 1, "dataQualityEligible": True,
        }}},
        "decisions": [{"ticker": ticker, "side": "YES", "generatedAt": (now - timedelta(seconds=5)).isoformat(), "blockingReasons": ["net_edge"]}],
    }
    result = _entry_confirmation(state, ticker, "YES", {"action": "BUY_YES", "generatedAt": now.isoformat()}, {})
    assert result["streak"] == 1
    assert result["confirmed"] is False


@pytest.mark.parametrize("status,outcome", [(400, "rejected"), (503, "unknown"), (408, "unknown"), (None, "unknown")])
def test_live_submit_failure_keeps_uncertain_outcome_and_never_retries_post(status, outcome):
    posts = []
    def signed(_config, _environment, method, endpoint, **kwargs):
        if method == "GET":
            return _real_preflight_response(endpoint)
        posts.append(kwargs["json_body"])
        if status is None:
            raise kalshi_api.requests.exceptions.ReadTimeout("synthetic timeout")
        raise KalshiApiError("synthetic exchange error", status=status, code="kalshi_account_request_failed", endpoint=endpoint)
    controller = _PaperRobotController(
        None, _EnabledRealState(), None,
        connection_loader=_test_real_credentials,
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed, worker_lease_store=_FencedLeaseStore(),
    )
    decision = _shard_test_decision()
    payload = _paper_order_payload(decision, decision["market"]["ticker"], exchange_index=2)
    with pytest.raises(Exception) as failed:
        controller._submit_live_order("user-1", payload, decision)
    assert len(posts) == 1
    evidence = failed.value.kalshi_routing_failure
    assert evidence["phase"] == "submission"
    assert evidence["outcome"] == outcome
    assert evidence["httpStatus"] == status
    assert evidence["clientOrderId"] == payload["client_order_id"]
    assert evidence["plannedCount"] == 1.0


def test_live_submit_with_empty_shard_never_calls_post():
    posts = []
    def signed(_config, _environment, method, endpoint, **kwargs):
        if method == "POST":
            posts.append(kwargs)
            raise AssertionError("empty shard must never be routed")
        response = _real_preflight_response(endpoint)
        if endpoint == "/portfolio/balance":
            response["balance_breakdown"] = [
                {"exchange_index": 0, "balance": "1000.0000"},
                {"exchange_index": 2, "balance": "0.0000"},
            ]
        return response
    controller = _PaperRobotController(
        None, _EnabledRealState(), None,
        connection_loader=_test_real_credentials,
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed, worker_lease_store=_FencedLeaseStore(),
    )
    decision = _shard_test_decision()
    payload = _paper_order_payload(decision, decision["market"]["ticker"], exchange_index=2)
    with pytest.raises(KalshiApiError) as blocked:
        controller._submit_live_order("user-1", payload, decision)
    assert blocked.value.code == "kalshi_live_shard_cash_insufficient"
    assert posts == []


def test_shard_resizer_uses_engine_default_economic_floor_when_sizing_omits_it():
    decision = _shard_test_decision()
    decision["edge"].update({"price": 0.10, "conservativeProbability": 0.90})
    context = {"exchangeIndex": 2, "aggregateCashAvailable": 100.0,
               "shardCashAvailable": 0.01, "shardCashKnown": True, "fundingStatus": "funded"}
    assert kalshi_api._apply_real_shard_funding_gate(decision, context) is True
    assert decision["action"] == "WAIT"


def test_shard_resizer_uses_engine_twenty_percent_default_not_twenty_five():
    decision = _shard_test_decision()
    decision["edge"].update({"price": 0.70, "conservativeProbability": 0.90})
    context = {"exchangeIndex": 2, "aggregateCashAvailable": 100.0,
               "shardCashAvailable": 0.10, "shardCashKnown": True, "fundingStatus": "funded"}
    assert kalshi_api._apply_real_shard_funding_gate(decision, context) is False
    # 0.13 contracts fit cash but their fee burden is23.08%;0.12 clears20%.
    assert decision["sizing"]["plannedContractsFp"] == pytest.approx(0.12)
    assert decision["shardFunding"]["resizedFeeToPotentialProfitPct"] <= 20.0


def test_scoped_final_preflight_updates_funding_diagnostics_without_erasing_thesis():
    posts = []
    def signed(_config, _environment, method, endpoint, **kwargs):
        if method == "POST":
            posts.append(kwargs["json_body"])
            return {"order": {"order_id": "synthetic-scoped-order"}}
        if endpoint.startswith("/markets/"):
            return {"market": {"ticker": "KXBTC15M-SHARD", "exchange_index": 3}}
        if endpoint == "/portfolio/balance":
            if (kwargs.get("params") or {}).get("exchange_index") == 3:
                return {"balance": 500, "balance_dollars": "5.0000", "portfolio_value": 0}
            return {"balance": 10_000, "portfolio_value": 0}
        return _real_preflight_response(endpoint)
    controller = _PaperRobotController(
        None, _EnabledRealState(), None,
        connection_loader=_test_real_credentials,
        authoritative_connection_loader=_test_real_credentials,
        signed_request=signed, worker_lease_store=_FencedLeaseStore(),
    )
    decision = _shard_test_decision()
    decision["shardFunding"] = {"fundingStatus": "unverified", "strategyAction": "BUY_YES", "strategyPlannedContracts": 1.0}
    payload = _paper_order_payload(decision, "KXBTC15M-SHARD")
    controller._submit_live_order("user-1", payload, decision)
    assert len(posts) == 1
    assert posts[0]["exchange_index"] == 3
    assert decision["market"]["exchangeIndex"] == 3
    assert decision["account"]["shardCashAvailable"] == 5.0
    assert decision["shardFunding"]["verifiedAtPreflight"] is True
    assert decision["shardFunding"]["requiresUserFunding"] is False
    assert decision["shardFunding"]["strategyAction"] == "BUY_YES"
    assert decision["shardFunding"]["strategyPlannedContracts"] == 1.0
