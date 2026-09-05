import json
import copy
from datetime import datetime, timezone

from kalshi_robot_state import (
    KalshiRobotState,
    _order_fill_count,
    _settlement_result,
)


def test_realized_analytics_exposes_payoff_asymmetry_and_drawdown():
    pnls = [1.0, -0.5, 0.25, -0.75, 2.0]
    strategy = {
        "settlementRecords": [
            {
                "environment": "paper",
                "ticker": f"KXBTC15M-{index}",
                "settledAt": f"2026-07-2{index}T00:00:00Z",
                "pnl": pnl,
            }
            for index, pnl in enumerate(pnls, start=1)
        ],
        "closedTradeRecords": [],
    }

    KalshiRobotState._sync_realized_analytics(strategy, "paper")

    assert strategy["realizedAverageWin"] == 1.0833
    assert strategy["realizedAverageLoss"] == 0.625
    assert strategy["realizedProfitFactor"] == 2.6
    assert strategy["realizedRecoveryMultiple"] == 0.5769
    assert strategy["realizedMaxDrawdown"] == 1.0


def test_fixed_point_fill_count_is_authoritative_including_zero():
    assert _order_fill_count({
        "status": "filled",
        "fill_count_fp": "0.30",
        "fill_count": 1,
    }) == 0.30
    assert _order_fill_count({
        "status": "filled",
        "fill_count_fp": "0.00",
        "fill_count": 1,
        "count_fp": "0.30",
        "count": 1,
    }) == 0.0
    assert _order_fill_count({
        "status": "filled",
        "count_fp": "0.30",
        "count": 1,
    }) == 0.30
    assert _order_fill_count({
        "status": "filled",
        "fill_count_fp": "nan",
        "fill_count": 1,
    }) == 0.0
    assert _order_fill_count({
        "status": "filled",
        "count_fp": "Infinity",
        "count": 1,
    }) == 0.0


def test_non_finite_settlement_outcome_fails_closed():
    assert _settlement_result({"value": "nan"}) == ""
    assert _settlement_result({"value": "Infinity"}) == ""


def test_realized_records_sort_mixed_offsets_by_utc():
    strategy = {
        "settlementRecords": [
            {
                "environment": "paper",
                "ticker": "late",
                "settledAt": "2026-07-21T01:00:00Z",
                "pnl": -2.0,
            },
            {
                "environment": "paper",
                "ticker": "early",
                "settledAt": "2026-07-21T02:00:00+02:00",
                "pnl": 1.0,
            },
        ],
        "closedTradeRecords": [],
    }

    KalshiRobotState._sync_realized_analytics(strategy, "paper")

    assert [row["ticker"] for row in strategy["equityCurve"]] == [
        "early",
        "late",
    ]
    assert strategy["realizedMaxDrawdown"] == 2.0


def test_decision_log_survives_process_restart(tmp_path):
    path = tmp_path / "kalshi-robot.json"
    store = KalshiRobotState(str(path))
    store.record("user-1", {
        "generatedAt": "2026-07-21T00:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "signalQuality": 82,
        "blockingReasons": [],
        "market": {"ticker": "KXBTC15M-TEST"},
        "edge": {"fairProbability": 0.62, "price": 0.53, "netEdge": 0.07},
    }, {"order_id": "order-1", "status": "filled", "fill_count": 1})

    restored = KalshiRobotState(str(path)).get("user-1")

    assert restored["decisions"][0]["ticker"] == "KXBTC15M-TEST"
    assert restored["decisions"][0]["fairProbability"] == 0.62


def test_robot_state_restores_from_durable_user_store_without_local_file(tmp_path):
    durable = {}

    def load(user_id):
        return durable.get(user_id)

    def save(user_id, state):
        durable[user_id] = state

    store = KalshiRobotState(
        str(tmp_path / "ignored-local-state.json"),
        state_loader=load,
        state_saver=save,
        enabled_users_loader=lambda: ["user-1"] if durable.get("user-1", {}).get("enabled") else [],
    )
    store.configure("user-1", True, {"executionMode": "paper"})

    restored = KalshiRobotState(
        str(tmp_path / "ignored-local-state.json"),
        state_loader=load,
        state_saver=save,
        enabled_users_loader=lambda: ["user-1"] if durable.get("user-1", {}).get("enabled") else [],
    )

    assert restored.get("user-1")["enabled"] is True
    assert restored.enabled_users() == ["user-1"]


def test_successful_cycle_clears_mode_local_transient_error(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    store.configure("user-1", True, {"executionMode": "paper"})
    store.error("user-1", "Artifact changed concurrently")

    state = store.record("user-1", {
        "generatedAt": "2026-07-21T00:00:00Z",
        "action": "WAIT",
        "side": "YES",
        "blockingReasons": ["net_edge"],
        "config": {"executionMode": "paper"},
        "market": {"ticker": "KXBTC15M-TEST"},
        "edge": {"fairProbability": 0.60, "price": 0.65, "netEdge": -0.05},
    })

    assert state["lastError"] is None
    assert state["modeState"]["paper"]["lastError"] is None




def test_getting_an_inactive_mode_is_a_pure_projection(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    store.configure("user-1", True, {"executionMode": "paper"})

    real_view = store.get("user-1", environment="real")
    active_after_read = store.get("user-1")

    assert real_view["selectedEnvironment"] == "real"
    assert real_view["config"]["executionMode"] == "real"
    assert real_view["activeEnvironment"] == "paper"
    assert real_view["schedulerEnabled"] is True
    assert real_view["enabled"] is False
    assert active_after_read["activeEnvironment"] == "paper"
    assert active_after_read["config"]["executionMode"] == "paper"
    assert active_after_read["enabled"] is True


def test_real_display_baseline_money_materialization_is_durable_and_one_time(
    tmp_path,
):
    path = tmp_path / "state.json"
    store = KalshiRobotState(str(path))
    baseline = store.materialize_real_display_baseline(
        "user-1",
        {
            "resetAt": "2026-07-27T01:02:03Z",
            "baselineEquityCents": 150_000,
            "baselineCashCents": 125_000,
            "environment": "real",
            "alphaLabOnly": True,
        },
    )
    unchanged = store.materialize_real_display_baseline(
        "user-1",
        {
            "resetAt": "2026-07-27T02:00:00Z",
            "baselineEquityCents": 999_999,
            "baselineCashCents": 999_999,
            "environment": "real",
            "alphaLabOnly": True,
        },
    )
    restored = KalshiRobotState(str(path)).get(
        "user-1",
        environment="real",
    )["modeState"]["real"]["displayBaseline"]

    assert baseline["baselineEquityCents"] == 150_000
    assert baseline["baselineCashCents"] == 125_000
    assert unchanged == baseline
    assert restored == baseline


def test_switching_from_paper_to_real_stops_and_requires_a_second_enable(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    store.configure("user-1", True, {"executionMode": "paper"})

    switched = store.configure("user-1", True, {"executionMode": "real"})

    assert switched["activeEnvironment"] == "real"
    assert switched["enabled"] is False
    assert switched["modeState"]["real"]["arming"]["armed"] is False
    assert switched["modeState"]["real"]["arming"]["awaitingExplicitEnable"] is True
    assert switched["modeState"]["real"]["displayBaseline"]["alphaLabOnly"] is True
    assert switched["modeState"]["real"]["displayBaseline"]["resetAt"]

    armed = store.configure("user-1", True, {"executionMode": "real"})
    assert armed["enabled"] is True
    assert armed["modeState"]["real"]["arming"]["armed"] is True
    assert armed["modeState"]["real"]["arming"]["awaitingExplicitEnable"] is False


def test_every_configure_enforces_safety_floors_and_preserves_stricter_values(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))

    floored = store.configure("user-1", False, {
        "executionMode": "paper",
        "minModelProbability": 0.55,
        "minNetEdge": 0.001,
        "minConservativeEdge": 0.001,
        "maxPrice": 0.99,
        "riskPerTradePct": 2.0,
        "fractionalKelly": 0.50,
        "maxPortfolioExposurePct": 50.0,
        "maxSingleMarketExposurePct": 20.0,
        "entryConfirmationMaxGapSeconds": 5,
        "minimumAddIntervalSeconds": 10,
        "minimumHoldSeconds": 1,
        "reversalCooldownSeconds": 1,
        "addMinProbabilityImprovement": 0.0,
        "addMinEdgeImprovement": 0.0,
        "addSizeFraction": 1.0,
    })
    assert floored["config"]["minModelProbability"] == 0.64
    assert floored["config"]["minNetEdge"] == 0.01
    assert floored["config"]["minConservativeEdge"] == 0.0075
    assert floored["config"]["maxPrice"] == 0.92
    assert floored["config"]["riskPerTradePct"] == 0.50
    assert floored["config"]["fractionalKelly"] == 0.15
    assert floored["config"]["maxPortfolioExposurePct"] == 10.0
    assert floored["config"]["maxSingleMarketExposurePct"] == 2.0
    assert floored["config"]["entryConfirmationMaxGapSeconds"] == 25.0
    assert floored["config"]["microPositionMaxLossDollars"] == 1.0
    assert floored["config"]["microPositionMaxLossPct"] == 5.0
    assert floored["config"]["microPositionMinNetEdge"] == 0.02
    assert floored["config"]["microPositionMinConservativeEdge"] == 0.01
    assert floored["config"]["minimumAddIntervalSeconds"] == 90
    assert floored["config"]["minimumHoldSeconds"] == 60
    assert floored["config"]["reversalCooldownSeconds"] == 90
    assert floored["config"]["addMinProbabilityImprovement"] == 0.01
    assert floored["config"]["addMinEdgeImprovement"] == 0.001
    assert floored["config"]["addSizeFraction"] == 0.25
    assert "maxDailyLossPct" not in floored["config"]

    stricter = store.configure("user-1", False, {
        **floored["config"],
        "minModelProbability": 0.72,
        "minNetEdge": 0.03,
        "minConservativeEdge": 0.02,
        "maxPrice": 0.84,
        "entryConfirmationMaxGapSeconds": 30,
    })
    assert stricter["config"]["minModelProbability"] == 0.72
    assert stricter["config"]["minNetEdge"] == 0.03
    assert stricter["config"]["minConservativeEdge"] == 0.02
    assert stricter["config"]["maxPrice"] == 0.84
    assert stricter["config"]["entryConfirmationMaxGapSeconds"] == 30
    assert (
        stricter["config"]["fullRiskModelProbability"]
        >= stricter["config"]["minModelProbability"] + 0.01
    )
    assert (
        stricter["config"]["fullRiskConservativeEdge"]
        >= stricter["config"]["minConservativeEdge"] + 0.005
    )


def test_v10_real_migration_preserves_ledger_and_disarms_live_mode(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"user-1": {
        "storageVersion": 9,
        "enabled": True,
        "activeEnvironment": "real",
        "config": {
            "executionMode": "real",
            "minModelProbability": 0.70,
            "minNetEdge": 0.02,
            "minConservativeEdge": 0.02,
            "maxPrice": 0.85,
            "minimumHoldSeconds": 1,
            "reversalCooldownSeconds": 1,
            "addMinProbabilityImprovement": 0.0,
            "addMinEdgeImprovement": 0.0,
        },
        "filledTrades": [{
            "ticker": "KXBTC15M-KEEP",
            "environment": "real",
            "orderId": "keep-order",
        }],
        "decisions": [],
        "strategy": {"settlementRecords": [{"key": "keep-settlement"}]},
    }}), encoding="utf-8")

    restored = KalshiRobotState(str(path)).get("user-1")
    real = restored["modeState"]["real"]

    assert restored["storageVersion"] == 15
    assert restored["enabled"] is False
    assert real["arming"]["awaitingExplicitEnable"] is True
    assert real["displayBaseline"]["alphaLabOnly"] is True
    assert real["config"]["minModelProbability"] == 0.70
    assert real["config"]["minNetEdge"] == 0.02
    assert real["config"]["minConservativeEdge"] == 0.02
    assert real["config"]["maxPrice"] == 0.85
    assert real["config"]["minimumHoldSeconds"] == 60
    assert real["config"]["reversalCooldownSeconds"] == 90
    assert real["config"]["addMinProbabilityImprovement"] == 0.01
    assert real["config"]["addMinEdgeImprovement"] == 0.001
    assert real["config"]["minimumRiskBudgetScale"] == 0.35
    assert real["filledTrades"][0]["orderId"] == "keep-order"
    assert real["strategy"]["settlementRecords"][0]["key"] == "keep-settlement"


def test_v11_micro_sizing_migration_preserves_live_arming(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"user-1": {
        "storageVersion": 10,
        "enabled": True,
        "activeEnvironment": "real",
        "config": {"executionMode": "real"},
        "modeState": {
            "real": {
                "config": {"executionMode": "real"},
                "arming": {
                    "armed": True,
                    "awaitingExplicitEnable": False,
                },
                "decisions": [],
                "filledTrades": [],
                "strategy": {"version": 6, "changes": []},
            },
        },
    }}), encoding="utf-8")

    restored = KalshiRobotState(str(path)).get("user-1")
    real = restored["modeState"]["real"]

    assert restored["storageVersion"] == 15
    assert restored["enabled"] is True
    assert real["arming"]["armed"] is True
    assert real["arming"]["awaitingExplicitEnable"] is False
    assert real["config"]["microPositionMaxLossDollars"] == 1.0
    assert real["config"]["microPositionMaxLossPct"] == 5.0
    assert real["config"]["smallAccountRiskTargetPct"] == 2.0
    assert real["strategy"]["version"] == 11


def test_v12_quality_scaled_sizing_preserves_live_arming_and_custom_lower_target(
    tmp_path,
):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"user-1": {
        "storageVersion": 11,
        "enabled": True,
        "activeEnvironment": "real",
        "config": {
            "executionMode": "real",
            "smallAccountRiskTargetPct": 1.0,
        },
        "modeState": {
            "real": {
                "config": {
                    "executionMode": "real",
                    "smallAccountRiskTargetPct": 1.0,
                },
                "arming": {
                    "armed": True,
                    "awaitingExplicitEnable": False,
                },
                "decisions": [],
                "filledTrades": [],
                "strategy": {"version": 7, "changes": []},
            },
        },
    }}), encoding="utf-8")

    restored = KalshiRobotState(str(path)).get("user-1")
    real = restored["modeState"]["real"]

    assert restored["storageVersion"] == 15
    assert restored["enabled"] is True
    assert real["arming"]["armed"] is True
    assert real["arming"]["awaitingExplicitEnable"] is False
    assert real["config"]["smallAccountRiskTargetPct"] == 1.0
    assert real["strategy"]["version"] == 11


def test_v15_execution_consistency_preserves_live_arming_and_ledger(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"user-1": {
        "storageVersion": 14,
        "enabled": True,
        "activeEnvironment": "real",
        "config": {
            "executionMode": "real",
            "minNetEdge": 0.02,
            "minConservativeEdge": 0.025,
        },
        "modeState": {
            "real": {
                "config": {
                    "executionMode": "real",
                    "minNetEdge": 0.02,
                    "minConservativeEdge": 0.025,
                },
                "arming": {
                    "armed": True,
                    "awaitingExplicitEnable": False,
                },
                "decisions": [],
                "filledTrades": [{"orderId": "keep-v11-fill"}],
                "strategy": {
                    "version": 10,
                    "changes": [],
                    "settlementRecords": [{"key": "keep-v11-settlement"}],
                },
            },
        },
    }}), encoding="utf-8")

    restored = KalshiRobotState(str(path)).get("user-1")
    real = restored["modeState"]["real"]

    assert restored["storageVersion"] == 15
    assert restored["enabled"] is True
    assert real["arming"]["armed"] is True
    assert real["arming"]["awaitingExplicitEnable"] is False
    assert real["strategy"]["version"] == 11
    assert real["config"]["minNetEdge"] == 0.02
    assert real["config"]["minConservativeEdge"] == 0.025
    assert real["filledTrades"][0]["orderId"] == "keep-v11-fill"
    assert (
        real["strategy"]["settlementRecords"][0]["key"]
        == "keep-v11-settlement"
    )
    assert "Execution-consistent v11" in real["strategy"]["changes"][0][
        "summary"
    ]


def test_v10_repairs_partial_real_display_baselines_and_persists_them(
    tmp_path,
):
    invalid_values = [
        {},
        {"environment": "real", "alphaLabOnly": True},
        {"resetAt": "2026-07-27T12:00:00Z", "alphaLabOnly": True},
        {"resetAt": "2026-07-27T12:00:00Z", "environment": "real"},
    ]
    for index, invalid in enumerate(invalid_values):
        original = KalshiRobotState._initial()
        original["modeState"] = {
            "real": {"displayBaseline": copy.deepcopy(invalid)},
        }
        saved = []
        store = KalshiRobotState(
            str(tmp_path / f"repair-{index}.json"),
            state_loader=lambda _user_id, value=original: copy.deepcopy(value),
            state_saver=lambda _user_id, payload: saved.append(
                copy.deepcopy(payload)
            ),
        )

        repaired = store.get("user-1", environment="real")
        baseline = repaired["modeState"]["real"]["displayBaseline"]

        assert baseline["resetAt"]
        assert baseline["environment"] == "real"
        assert baseline["alphaLabOnly"] is True
        assert baseline["ledgerPreserved"] is True
        assert len(saved) == 1


def test_refresh_reports_whether_it_reloaded_a_durable_source(tmp_path):
    local = KalshiRobotState(str(tmp_path / "local.json"))
    local_refresh = local.refresh("user-1", environment="real")
    durable = KalshiRobotState(
        str(tmp_path / "durable.json"),
        state_loader=lambda _user_id: None,
    )
    durable_refresh = durable.refresh("user-1", environment="real")

    assert local.durable_state_loader_available is False
    assert local_refresh["authoritativeRefresh"] is False
    assert local_refresh["durableStateLoaderAvailable"] is False
    assert durable.durable_state_loader_available is True
    assert durable_refresh["authoritativeRefresh"] is True
    assert durable_refresh["durableStateLoaderAvailable"] is True


def test_filled_stop_loss_does_not_persist_same_ticker_reentry_block(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    state = store.record(
        "user-1",
        {
            "generatedAt": "2026-07-27T12:00:00Z",
            "action": "SELL_YES",
            "side": "YES",
            "config": {"executionMode": "paper"},
            "market": {"ticker": "KXBTC15M-STOP"},
            "edge": {"price": 0.30},
            "exitAnalysis": {"trigger": "protective_stop_loss"},
        },
        {
            "order_id": "stop-order",
            "status": "filled",
            "fill_count_fp": 2,
            "environment": "paper",
        },
    )

    assert "stopLossReentryTickers" not in state["modeState"]["paper"]["strategy"]


def test_delayed_live_fill_promotes_provenance_without_reentry_block(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    store.configure("user-1", False, {"executionMode": "real"})
    store.record(
        "user-1",
        {
            "generatedAt": "2026-07-27T12:00:00Z",
            "action": "SELL_YES",
            "side": "YES",
            "config": {"executionMode": "real"},
            "market": {"ticker": "KXBTC15M-DELAYED"},
            "edge": {"price": 0.30},
            "exitAnalysis": {"trigger": "emergency_stop_loss"},
        },
        {
            "order_id": "delayed-order",
            "client_order_id": "delayed-client",
            "status": "submitted",
            "fill_count_fp": 0,
            "environment": "real",
        },
    )

    reconciled = store.reconcile_live_fills("user-1", [{
        "fill_id": "delayed-fill",
        "order_id": "delayed-order",
        "ticker": "KXBTC15M-DELAYED",
        "action": "SELL",
        "fill_count_fp": 2,
    }])
    real = reconciled["modeState"]["real"]

    assert real["filledTrades"][-1]["orderFilled"] is True
    assert real["filledTrades"][-1]["orderId"] == "delayed-order"
    assert "stopLossReentryTickers" not in real["strategy"]


def test_pre_v6_trade_and_learning_data_is_removed_during_upgrade(tmp_path):
    path = tmp_path / "kalshi-robot.json"
    path.write_text(json.dumps({"user-1": {
        "storageVersion": 4,
        "enabled": True,
        "config": {"riskPerTradePct": 0.5, "minPrice": 0.12, "maxPrice": 0.88},
        "decisions": [{"ticker": "OLD"}],
        "filledTrades": [{"ticker": "OLD"}],
        "learningObservations": [{"ticker": "OLD"}],
        "learningExamples": [{"ticker": "OLD"}],
    }}), encoding="utf-8")

    restored = KalshiRobotState(str(path)).get("user-1")

    assert restored["storageVersion"] == 15
    assert restored["enabled"] is True
    assert restored["decisions"] == []
    assert restored["filledTrades"] == []
    assert "learningObservations" not in restored
    assert "learningExamples" not in restored
    assert "strategyLibrary" not in restored
    # Old longshot-era tuning is replaced by the deterministic v4 favorite band.
    assert restored["config"]["minPrice"] == 0.47
    assert restored["config"]["maxPrice"] == 0.92
    assert restored["config"]["minModelProbability"] == 0.64


def test_v6_state_adopts_calibrated_defaults_without_losing_records(tmp_path):
    path = tmp_path / "kalshi-robot.json"
    path.write_text(json.dumps({"user-1": {
        "storageVersion": 6,
        "enabled": True,
        "config": {
            "executionMode": "paper",
            "minNetEdge": 0.015,
            "minModelProbability": 0.60,
        },
        "decisions": [{"ticker": "KXBTC15M-KEEP", "environment": "paper"}],
        "filledTrades": [{"ticker": "KXBTC15M-KEEP", "environment": "paper"}],
    }}), encoding="utf-8")

    restored = KalshiRobotState(str(path)).get("user-1")

    assert restored["storageVersion"] == 15
    assert restored["config"]["minNetEdge"] == 0.015
    assert restored["config"]["minModelProbability"] == 0.64
    assert restored["config"]["marketBlendWeight"] == 0.45
    assert restored["config"]["probabilityLogitScale"] == 1.70
    assert restored["strategy"]["version"] == 11
    assert restored["decisions"][0]["ticker"] == "KXBTC15M-KEEP"
    assert restored["filledTrades"][0]["ticker"] == "KXBTC15M-KEEP"


def test_removed_learning_configuration_is_not_persisted(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    state = store.configure("user-1", True, {
        "executionMode": "paper",
        "learningMode": True,
        "learningAiMode": True,
        "learningExplorationRate": 0.9,
        "riskPerTradePct": 0.5,
    })

    assert state["config"]["riskPerTradePct"] == 0.5
    assert not any(key.startswith("learning") for key in state["config"])
    assert "learning" not in state["strategy"]


def test_settlement_calibration_is_idempotent(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    store.record("user-1", {
        "generatedAt": "2026-07-21T00:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "blockingReasons": [],
        "market": {"ticker": "KXBTC15M-TEST"},
        "edge": {"fairProbability": 0.70, "price": 0.55, "netEdge": 0.05},
    })
    settlement = {"ticker": "KXBTC15M-TEST", "settled_time": "2026-07-21T00:15:00Z", "market_result": "yes"}

    first = store.reconcile_settlements("user-1", [settlement])
    second = store.reconcile_settlements("user-1", [settlement])

    assert first["strategy"]["settledSamples"] == 1
    assert first["strategy"]["winRate"] == 1.0
    assert second["strategy"]["settledSamples"] == 1


def test_same_timestamp_settlement_analytics_do_not_flip_or_repersist(tmp_path):
    saves = []

    def save(_user_id, payload):
        saves.append(copy.deepcopy(payload))
        return {"version": len(saves)}

    store = KalshiRobotState(
        str(tmp_path / "state.json"),
        state_saver=save,
    )
    store.configure("user-1", True, {"executionMode": "real"})
    bucket = store._users["user-1"]["modeState"]["real"]
    bucket["strategy"]["settlementRecords"] = [
        {
            "key": "real:A:shared:YES",
            "environment": "real",
            "ticker": "A",
            "settledAt": "2026-08-01T00:00:00Z",
            "pnl": 1.0,
            "side": "YES",
            "result": "YES",
        },
        {
            "key": "real:B:shared:YES",
            "environment": "real",
            "ticker": "B",
            "settledAt": "2026-08-01T00:00:00Z",
            "pnl": 2.0,
            "side": "YES",
            "result": "YES",
        },
    ]
    bucket["processedSettlements"] = [
        "real:B:shared:YES",
        "real:A:shared:YES",
    ]

    first = store.reconcile_settlements(
        "user-1", [], fills=[], environment="real"
    )
    writes_after_first = len(saves)
    second = store.reconcile_settlements(
        "user-1", [], fills=[], environment="real"
    )
    third = store.reconcile_settlements(
        "user-1", [], fills=[], environment="real"
    )

    first_order = [
        row["ticker"] for row in first["strategy"]["realizedTradeRecords"]
    ]
    assert first_order == [
        row["ticker"] for row in second["strategy"]["realizedTradeRecords"]
    ]
    assert first_order == [
        row["ticker"] for row in third["strategy"]["realizedTradeRecords"]
    ]
    assert len(saves) == writes_after_first


def test_explicit_zero_fp_settlement_count_never_revives_legacy_position(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    ticker = "KXBTC15M-ZERO-FP"
    store.record("user-1", {
        "generatedAt": "2026-07-21T00:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "blockingReasons": [],
        "market": {"ticker": ticker},
        "edge": {"fairProbability": 0.70, "price": 0.55},
    }, {
        "order_id": "zero-fp-order",
        "status": "filled",
        "fill_count_fp": "1.00",
        "fill_count": 1,
    })
    settlement = {
        "ticker": ticker,
        "settled_time": "2026-07-21T00:15:00Z",
        "market_result": "yes",
        "yes_count_fp": "0.00",
        "yes_count": 5,
        "no_count_fp": "0.00",
        "no_count": 0,
        "revenue_dollars": 5,
        "yes_total_cost_dollars": 4,
        "fee_cost_dollars": 0.1,
    }

    state = store.reconcile_settlements("user-1", [settlement])

    assert state["strategy"]["settlementRecords"] == []
    assert state["strategy"]["realizedTradeRecords"] == []
    assert state["strategy"]["settledSamples"] == 0
    assert state["strategy"]["realizedTotalPnl"] == 0.0


def test_settlement_record_exposes_weighted_entry_and_resolution_exit_prices(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    ticker = "KXBTC15M-PRICES"
    store.record("user-1", {
        "generatedAt": "2026-07-21T00:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "blockingReasons": [],
        "market": {"ticker": ticker},
        "edge": {"fairProbability": 0.70, "price": 0.55},
    }, {"order_id": "price-order", "status": "filled", "fill_count": 10})
    settlement = {
        "ticker": ticker,
        "settled_time": "2026-07-21T00:15:00Z",
        "market_result": "yes",
        "yes_count_fp": 10,
        "no_count_fp": 0,
        "revenue_dollars": 10,
        "yes_total_cost_dollars": 5.5,
        "no_total_cost_dollars": 0,
        "fee_cost_dollars": 0.2,
    }
    fills = [{
        "ticker": ticker,
        "outcome_side": "YES",
        "count_fp": 10,
        "price_dollars": 0.55,
        "environment": "paper",
    }]

    state = store.reconcile_settlements("user-1", [settlement], fills)
    record = state["strategy"]["settlementRecords"][0]

    assert record["entryPrice"] == 0.55
    assert record["exitPrice"] == 1.0
    assert record["exitType"] == "settlement"












def test_only_filled_trades_enter_realized_win_rate(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    store.record("user-1", {
        "generatedAt": "2026-07-21T00:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "blockingReasons": [],
        "market": {"ticker": "KXBTC15M-NOFILL"},
        "edge": {"fairProbability": 0.70, "price": 0.55, "netEdge": 0.05},
    }, {"order_id": "order-no-fill", "status": "canceled", "fill_count": 0})

    state = store.reconcile_settlements("user-1", [{
        "ticker": "KXBTC15M-NOFILL",
        "settled_time": "2026-07-21T00:15:00Z",
        "market_result": "yes",
        "revenue_dollars": "1.00",
        "yes_total_cost_dollars": "0.55",
    }], [])

    assert state["strategy"]["settledSamples"] == 0
    assert state["strategy"]["settlementRecords"] == []


def test_decision_log_retains_compact_audit_history_and_filled_trade_evidence(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    for index in range(3):
        store.record("user-1", {
            "generatedAt": f"2026-07-21T00:0{index}:00Z",
            "action": "BUY_YES",
            "side": "YES",
            "blockingReasons": [],
            "market": {"ticker": f"KXBTC15M-{index}"},
            "edge": {"fairProbability": 0.70, "price": 0.55, "netEdge": 0.05},
        }, {"order_id": f"order-{index}", "status": "filled", "fill_count": 1})

    state = store.get("user-1")

    assert state["decisionLimit"] == 50
    assert len(state["decisions"]) == 3
    assert [row["ticker"] for row in state["decisions"]] == [
        "KXBTC15M-2", "KXBTC15M-1", "KXBTC15M-0",
    ]
    assert len(state["filledTrades"]) == 3
    assert state["tradedTickers"] == ["KXBTC15M-0", "KXBTC15M-1", "KXBTC15M-2"]


def test_filled_entry_and_exit_times_persist_with_decision_audit_history(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    store.record("user-1", {
        "generatedAt": "2026-07-21T00:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "market": {"ticker": "KXBTC15M-TIMING"},
        "edge": {"price": 0.45},
    }, {"status": "filled", "fill_count": 2})
    store.record("user-1", {
        "generatedAt": "2026-07-21T00:01:00Z",
        "action": "SELL_YES",
        "side": "YES",
        "market": {"ticker": "KXBTC15M-TIMING"},
        "edge": {"price": 0.55},
    }, {"status": "filled", "fill_count": 2})
    store.record("user-1", {
        "generatedAt": "2026-07-21T00:01:05Z",
        "action": "WAIT",
        "market": {"ticker": "KXBTC15M-TIMING"},
    })

    restored = KalshiRobotState(str(tmp_path / "state.json")).get("user-1")

    assert len(restored["decisions"]) == 3
    assert restored["strategy"]["lastEntryTicker"] == "KXBTC15M-TIMING"
    assert restored["strategy"]["lastEntryAt"] == "2026-07-21T00:00:00Z"
    assert restored["strategy"]["lastExitTicker"] == "KXBTC15M-TIMING"
    assert restored["strategy"]["lastExitAt"] == "2026-07-21T00:01:00Z"






















def test_early_close_pnl_is_tracked_without_becoming_calibration_label(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    decision = {
        "generatedAt": "2026-07-22T12:00:00Z",
        "action": "SELL_YES",
        "side": "YES",
        "executionIntent": "CLOSE_YES",
        "market": {"ticker": "KXBTC15M-CLOSE"},
        "exitAnalysis": {
            "averageEntryPrice": 0.40,
            "exitValueEdge": 0.03,
            "trigger": "fee_adjusted_take_profit",
            "netExitPnlPerContract": 0.136,
            "exitLossFraction": 0.0,
        },
    }
    order = {
        "order_id": "close-1",
        "ticker": "KXBTC15M-CLOSE",
        "environment": "paper",
        "action": "SELL",
        "reduce_only": True,
        "outcome_side": "YES",
        "status": "executed",
        "fill_count_fp": 5,
        "average_price_dollars": 0.55,
        "entry_fee_allocated_dollars": 0.03,
        "fee_cost_dollars": 0.04,
        "realized_pnl_dollars": 0.68,
    }

    state = store.record_early_close("user-1", decision, order, environment="paper")
    strategy = state["strategy"]

    assert strategy["closedTradeSamples"] == 1
    assert strategy["closedTradeTotalPnl"] == 0.68
    assert strategy["closedTradeRecords"][0]["settlementLabel"] is None
    assert strategy["settlementRecords"] == []
    assert "learning" not in strategy
    assert strategy["realizedSamples"] == 1
    assert strategy["realizedTotalPnl"] == 0.68
    assert strategy["realizedTradeRecords"][0]["exitType"] == "sale"
    assert strategy["realizedTradeRecords"][0]["result"] is None
    assert strategy["realizedTradeRecords"][0]["exitTrigger"] == "fee_adjusted_take_profit"
    assert strategy["realizedTradeRecords"][0]["netExitPnlPerContract"] == 0.136
    assert strategy["realizedTradeRecords"][0]["exitLossFraction"] == 0.0
    assert strategy["closedTradeRecords"][0]["exitTrigger"] == "fee_adjusted_take_profit"
    assert strategy["closedTradeRecords"][0]["netExitPnlPerContract"] == 0.136
    assert strategy["closedTradeRecords"][0]["exitLossFraction"] == 0.0


def test_daily_pnl_idempotently_combines_sale_and_settlement(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    decision = {
        "generatedAt": now,
        "action": "SELL_YES",
        "side": "YES",
        "executionIntent": "CLOSE_YES",
        "market": {"ticker": "KXBTC15M-DAILY-SALE"},
        "exitAnalysis": {
            "averageEntryPrice": 0.60,
            "trigger": "protective_stop_loss",
        },
    }
    close_order = {
        "order_id": "daily-close",
        "ticker": "KXBTC15M-DAILY-SALE",
        "environment": "paper",
        "action": "SELL",
        "reduce_only": True,
        "outcome_side": "YES",
        "status": "executed",
        "fill_count_fp": 5,
        "average_price_dollars": 0.40,
        "realized_pnl_dollars": -1.0,
        "created_time": now,
    }
    store.record_early_close(
        "user-1",
        decision,
        close_order,
        environment="paper",
    )
    store.record(
        "user-1",
        {
            "generatedAt": now,
            "action": "BUY_YES",
            "side": "YES",
            "config": {"executionMode": "paper"},
            "market": {"ticker": "KXBTC15M-DAILY-SETTLE"},
            "edge": {"fairProbability": 0.70, "price": 0.50},
        },
        {
            "order_id": "daily-entry",
            "status": "filled",
            "fill_count": 2,
            "environment": "paper",
        },
    )
    settlement = {
        "ticker": "KXBTC15M-DAILY-SETTLE",
        "market_result": "YES",
        "settled_time": now,
        "yes_count_fp": 2,
        "revenue_dollars": 2.0,
        "yes_total_cost_dollars": 1.0,
        "fee_cost_dollars": 0.0,
    }
    first = store.reconcile_settlements(
        "user-1",
        [settlement],
        environment="paper",
    )
    second = store.reconcile_settlements(
        "user-1",
        [settlement],
        environment="paper",
    )

    today = datetime.now(timezone.utc).date().isoformat()
    assert first["strategy"]["dailyPnlDate"] == today
    assert first["strategy"]["dailyPnl"] == 0.0
    assert second["strategy"]["dailyPnl"] == 0.0
    assert second["strategy"]["realizedSamples"] == 2


def test_reconcile_backfills_reduce_only_fills_into_realized_analytics(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    fill = {
        "fill_id": "fill-close-1",
        "order_id": "close-1",
        "ticker": "KXBTC15M-CLOSE",
        "environment": "paper",
        "action": "SELL",
        "reduce_only": True,
        "outcome_side": "NO",
        "fill_count_fp": 10,
        "average_price_dollars": 0.62,
        "position_cost_dollars": 4.0,
        "gross_proceeds_dollars": 6.2,
        "entry_fee_allocated_dollars": 0.1,
        "fee_cost_dollars": 0.2,
        "realized_pnl_dollars": 1.9,
        "created_time": "2026-07-22T12:15:00Z",
    }

    state = store.reconcile_settlements(
        "user-1",
        [],
        [fill],
        environment="paper",
    )
    strategy = state["strategy"]

    assert strategy["settledSamples"] == 0
    assert strategy["realizedSamples"] == 1
    assert strategy["realizedWins"] == 1
    assert strategy["totalPnl"] == 1.9
    assert strategy["equityCurve"][0]["cumulativePnl"] == 1.9
    record = strategy["realizedTradeRecords"][0]
    assert record["entryPrice"] == 0.4
    assert record["exitPrice"] == 0.62
    assert record["fees"] == 0.3


def test_settlement_after_full_early_close_is_removed_from_realized_analytics(
    tmp_path,
):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    ticker = "KXBTC15M-FULL-CLOSE"
    settlement = {
        "ticker": ticker,
        "market_result": "YES",
        "settled_time": "2026-07-28T13:00:05Z",
        # Kalshi history can retain the original acquired count and cost even
        # after a pre-expiry sale, but no settlement cash is credited.
        "yes_count_fp": 1,
        "revenue_dollars": 0.0,
        "yes_total_cost_dollars": 0.766,
        "fee_cost_dollars": 0.0133,
    }
    entry_fill = {
        "fill_id": "entry-fill",
        "order_id": "entry-order",
        "ticker": ticker,
        "environment": "real",
        "action": "BUY",
        "outcome_side": "YES",
        "fill_count_fp": 1,
        "average_price_dollars": 0.76,
        "fee_cost_dollars": 0.006,
        "created_time": "2026-07-28T12:47:03Z",
    }

    stale = store.reconcile_settlements(
        "user-1",
        [settlement],
        [entry_fill],
        environment="real",
    )
    stale_strategy = stale["modeState"]["real"]["strategy"]
    assert stale_strategy["realizedSamples"] == 1
    assert stale_strategy["realizedTotalPnl"] == -0.7793

    close_fill = {
        "fill_id": "close-fill",
        "order_id": "close-order",
        "ticker": ticker,
        "environment": "real",
        "action": "SELL",
        "reduce_only": True,
        "outcome_side": "YES",
        "fill_count_fp": 1,
        "average_price_dollars": 0.994,
        "position_cost_dollars": 0.76,
        "gross_proceeds_dollars": 0.994,
        "entry_fee_allocated_dollars": 0.006,
        "fee_cost_dollars": 0.0073,
        "realized_pnl_dollars": 0.2207,
        "created_time": "2026-07-28T12:57:02Z",
    }
    repaired = store.reconcile_settlements(
        "user-1",
        [settlement],
        [entry_fill, close_fill],
        environment="real",
    )
    strategy = repaired["modeState"]["real"]["strategy"]

    assert strategy["settlementRecords"] == []
    assert strategy["realizedSamples"] == 1
    assert strategy["realizedWins"] == 1
    assert strategy["realizedLosses"] == 0
    assert strategy["realizedTotalPnl"] == 0.2207
    assert strategy["realizedTradeRecords"][0]["exitType"] == "sale"
    assert strategy["realizedTradeRecords"][0]["orderId"] == "close-order"


def test_partial_early_close_keeps_remaining_settlement_outcome(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    ticker = "KXBTC15M-PARTIAL-CLOSE"
    fills = [
        {
            "fill_id": "entry-fill",
            "order_id": "entry-order",
            "ticker": ticker,
            "environment": "real",
            "action": "BUY",
            "outcome_side": "YES",
            "fill_count_fp": 2,
            "average_price_dollars": 0.60,
            "fee_cost_dollars": 0.02,
            "created_time": "2026-07-28T12:40:00Z",
        },
        {
            "fill_id": "partial-close-fill",
            "order_id": "partial-close-order",
            "ticker": ticker,
            "environment": "real",
            "action": "SELL",
            "reduce_only": True,
            "outcome_side": "YES",
            "fill_count_fp": 1,
            "average_price_dollars": 0.80,
            "position_cost_dollars": 0.60,
            "gross_proceeds_dollars": 0.80,
            "entry_fee_allocated_dollars": 0.01,
            "fee_cost_dollars": 0.01,
            "realized_pnl_dollars": 0.18,
            "created_time": "2026-07-28T12:50:00Z",
        },
    ]
    settlement = {
        "ticker": ticker,
        "market_result": "YES",
        "settled_time": "2026-07-28T13:00:05Z",
        "yes_count_fp": 1,
        "revenue_dollars": 1.0,
        "yes_total_cost_dollars": 0.60,
        "fee_cost_dollars": 0.01,
    }

    state = store.reconcile_settlements(
        "user-1",
        [settlement],
        fills,
        environment="real",
    )
    strategy = state["modeState"]["real"]["strategy"]

    assert len(strategy["settlementRecords"]) == 1
    assert strategy["realizedSamples"] == 2
    assert {row["exitType"] for row in strategy["realizedTradeRecords"]} == {
        "sale",
        "settlement",
    }
    assert strategy["realizedTotalPnl"] == 0.57


def test_repeated_settlement_reconciliation_does_not_rewrite_unchanged_state(tmp_path):
    durable = {}
    saves = []

    def save(user_id, payload):
        durable[user_id] = payload
        saves.append((user_id, payload))

    store = KalshiRobotState(
        str(tmp_path / "state.json"),
        state_loader=durable.get,
        state_saver=save,
    )
    store.record("u", {
        "generatedAt": "2026-07-25T12:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "market": {"ticker": "KXBTC15M-IDEMPOTENT"},
        "edge": {"fairProbability": 0.70, "price": 0.50},
    }, {
        "order_id": "entry-1",
        "status": "filled",
        "fill_count": 1,
        "environment": "paper",
    })
    settlement = {
        "ticker": "KXBTC15M-IDEMPOTENT",
        "settled_time": "2026-07-25T12:15:00Z",
        "market_result": "YES",
        "yes_count_fp": 1,
        "revenue_dollars": 1.0,
        "yes_total_cost_dollars": 0.5,
    }
    store.reconcile_settlements("u", [settlement], [], environment="paper")
    writes_after_first_reconciliation = len(saves)

    store.reconcile_settlements("u", [settlement], [], environment="paper")

    assert len(saves) == writes_after_first_reconciliation


def test_robot_state_tracks_durable_version_and_invalidates_after_conflict(tmp_path):
    calls = []

    def save(_user_id, payload):
        calls.append(payload)
        if len(calls) == 1:
            return {"version": 41}
        raise RuntimeError("stale durable version")

    store = KalshiRobotState(
        str(tmp_path / "state.json"),
        state_saver=save,
    )
    store.configure("u", True, {"executionMode": "paper"})

    assert store._users["u"]["_operationsVersion"] == 41
    try:
        store.configure("u", False, {"executionMode": "paper"})
    except RuntimeError:
        pass
    else:
        raise AssertionError("stale write must fail")
    assert "u" not in store._users


def test_robot_state_mutations_persist_only_the_target_user(tmp_path):
    path = tmp_path / "state.json"
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

    store = KalshiRobotState(
        str(path),
        state_loader=durable.get,
        state_saver=save,
    )
    store.configure("user-a", True, {"executionMode": "paper"})
    store.configure("user-b", True, {"executionMode": "paper"})
    assert store._users["user-a"]["_operationsVersion"] == 1
    assert store._users["user-b"]["_operationsVersion"] == 1

    calls.clear()
    store.configure("user-a", True, {
        "executionMode": "paper",
        "riskPerTradePct": 0.5,
    })
    assert calls == ["user-a"]
    assert store._users["user-a"]["_operationsVersion"] == 2
    assert store._users["user-b"]["_operationsVersion"] == 1

    calls.clear()
    store.record("user-a", {
        "generatedAt": "2026-07-26T12:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "blockingReasons": [],
        "config": {"executionMode": "paper"},
        "market": {"ticker": "KXBTC15M-TARGET"},
        "edge": {"fairProbability": 0.70, "price": 0.50, "netEdge": 0.10},
    }, {
        "order_id": "order-target-1",
        "status": "resting",
        "count": 1,
    })
    assert calls == ["user-a"]
    assert store._users["user-a"]["_operationsVersion"] == 3
    assert store._users["user-b"]["_operationsVersion"] == 1

    calls.clear()
    store.reconcile_settlements("user-a", [{
        "ticker": "KXBTC15M-TARGET",
        "settled_time": "2026-07-26T12:15:00Z",
        "market_result": "YES",
    }])
    assert calls == ["user-a"]
    assert store._users["user-a"]["_operationsVersion"] == 4
    assert store._users["user-b"]["_operationsVersion"] == 1

    local_snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert set(local_snapshot) == {"user-a", "user-b"}
    assert local_snapshot["user-b"]["_operationsVersion"] == 1

    calls.clear()
    failing_users.add("user-a")
    try:
        store.configure("user-a", False, {"executionMode": "paper"})
    except RuntimeError:
        pass
    else:
        raise AssertionError("stale target write must fail")
    assert calls == ["user-a"]
    assert "user-a" not in store._users
    assert store._users["user-b"]["_operationsVersion"] == 1


def test_routine_wait_decisions_never_upload_full_durable_heartbeats(tmp_path):
    calls = []

    def save(_user_id, payload):
        calls.append(payload)
        return {"version": len(calls)}

    store = KalshiRobotState(
        str(tmp_path / "state.json"),
        state_saver=save,
    )
    decision = {
        "generatedAt": "2026-07-26T12:00:00Z",
        "action": "WAIT",
        "side": "YES",
        "blockingReasons": ["net_edge"],
        "config": {"executionMode": "paper"},
        "market": {"ticker": "KXBTC15M-WAIT"},
        "edge": {"fairProbability": 0.55, "price": 0.56, "netEdge": -0.01},
    }

    store.record("user-a", decision)
    store.record("user-a", {**decision, "generatedAt": "2026-07-26T12:00:05Z"})
    assert calls == []

    store.record("user-a", {
        **decision,
        "generatedAt": "2026-07-26T12:00:10Z",
        "blockingReasons": ["liquidity"],
    })
    assert calls == []

    store.record("user-a", {
        **decision,
        "generatedAt": "2026-07-26T12:01:10Z",
        "blockingReasons": ["liquidity"],
    })
    assert calls == []

    store.record("user-a", {
        **decision,
        "generatedAt": "2026-07-26T12:01:15Z",
        "action": "BUY_YES",
        "blockingReasons": [],
    })
    assert calls == []

    store.record("user-a", {
        **decision,
        "generatedAt": "2026-07-26T12:01:20Z",
        "action": "BUY_YES",
        "blockingReasons": [],
    }, {
        "order_id": "order-1",
        "status": "resting",
        "count": 1,
    })
    assert len(calls) == 1


def test_entry_confirmation_persists_compact_cursor_and_clears_invalid_frame(tmp_path):
    durable = {}
    saves = []

    def save(user_id, payload):
        durable[user_id] = copy.deepcopy(payload)
        saves.append(copy.deepcopy(payload))
        return {"version": len(saves)}

    store = KalshiRobotState(
        str(tmp_path / "state.json"),
        state_loader=durable.get,
        state_saver=save,
    )
    candidate = {
        "generatedAt": "2026-08-03T12:00:00Z",
        "action": "WAIT",
        "intendedAction": "BUY_YES",
        "side": "YES",
        "blockingReasons": ["entry_confirmation"],
        "config": {"executionMode": "real"},
        "market": {"ticker": "KXBTC15M-DURABLE"},
        "edge": {
            "fairProbability": 0.72,
            "price": 0.55,
            "netEdge": 0.12,
            "conservativeEdge": 0.08,
        },
        "entryConfirmation": {
            "required": True,
            "requiredSnapshots": 2,
            "streak": 1,
            "confirmed": False,
            "maxGapSeconds": 25.0,
        },
    }

    store.record("user-a", candidate)

    assert len(saves) == 1
    persisted_bucket = saves[-1]["modeState"]["real"]
    assert "decisions" not in persisted_bucket
    assert persisted_bucket["strategy"]["entryConfirmations"]["btc15m"] == {
        "ticker": "KXBTC15M-DURABLE",
        "side": "YES",
        "generatedAt": "2026-08-03T12:00:00Z",
        "streak": 1,
        "requiredSnapshots": 2,
        "confirmed": False,
        "dataQualityEligible": True,
        "maxGapSeconds": 25.0,
    }

    store.record("user-a", {
        **candidate,
        "generatedAt": "2026-08-03T12:00:05Z",
        "blockingReasons": ["net_edge"],
        "entryConfirmation": {},
    })
    assert len(saves) == 2

    restored = KalshiRobotState(
        str(tmp_path / "restored.json"),
        state_loader=durable.get,
        state_saver=save,
    ).get("user-a", environment="real")
    assert "btc15m" not in restored["strategy"]["entryConfirmations"]

    store.record("user-a", {
        **candidate,
        "generatedAt": "2026-08-03T12:00:10Z",
    })
    # A delayed older record must not erase a newer valid family cursor.
    store.record("user-a", {
        **candidate,
        "generatedAt": "2026-08-03T12:00:06Z",
        "blockingReasons": ["data_freshness"],
        "entryConfirmation": {},
    })
    progress = store.get("user-a", environment="real")["strategy"]["entryConfirmations"]["btc15m"]
    assert progress["generatedAt"] == "2026-08-03T12:00:10Z"
    # Another strategy family must not erase BTC15's progress.
    store.record("user-a", {
        **candidate,
        "generatedAt": "2026-08-03T12:00:12Z",
        "market": {"ticker": "KXBTCD-OTHER"},
        "blockingReasons": ["net_edge"],
        "entryConfirmation": {},
    })
    assert "btc15m" in store.get("user-a", environment="real")["strategy"]["entryConfirmations"]
    # A confirmed strategy signal with an execution blocker is not a
    # consecutive executable frame; preserving it could bypass revalidation.
    store.record("user-a", {
        **candidate,
        "generatedAt": "2026-08-03T12:00:15Z",
        "blockingReasons": ["entry_confirmation", "kalshi_live_shard_insufficient_cash"],
        "entryConfirmation": {**candidate["entryConfirmation"], "confirmed": True, "streak": 2},
    })
    assert "btc15m" not in store.get("user-a", environment="real")["strategy"]["entryConfirmations"]


def _protective_decision(timestamp, streak=1, ticker="KXBTC15M-PROTECT", **overrides):
    return {
        "generatedAt": timestamp,
        "action": "WAIT",
        "side": "NO",
        "config": {"executionMode": "real"},
        "market": {"ticker": ticker},
        "account": {"heldSide": "YES", "heldCount": 1},
        "blockingReasons": ["protective_exit_confirmation"],
        "protectiveConfirmation": {
            "required": True,
            "requiredSnapshots": 3,
            "streak": streak,
            "confirmed": streak >= 3,
            "dataQualityEligible": True,
            "maxGapSeconds": 30,
        },
        **overrides,
    }


def test_protective_confirmation_is_compact_durable_and_unique(tmp_path):
    durable, saves = {}, []

    def save(user_id, payload):
        durable[user_id] = copy.deepcopy(payload)
        saves.append(copy.deepcopy(payload))
        return {"version": len(saves)}

    store = KalshiRobotState(str(tmp_path / "state.json"), state_loader=durable.get, state_saver=save)
    first = _protective_decision("2026-09-05T20:00:00Z")
    store.record("user-a", first)
    assert len(saves) == 1
    bucket = saves[-1]["modeState"]["real"]
    assert "decisions" not in bucket
    assert bucket["strategy"]["protectiveExitConfirmations"]["KXBTC15M-PROTECT"]["streak"] == 1

    # An identical frame claiming three confirmations cannot advance.
    store.record("user-a", _protective_decision("2026-09-05T20:00:00Z", 3))
    assert len(saves) == 1
    restored = KalshiRobotState(str(tmp_path / "restore.json"), state_loader=durable.get, state_saver=save)
    restored.record("user-a", _protective_decision("2026-09-05T20:00:05Z", 2))
    assert len(saves) == 2
    assert saves[-1]["modeState"]["real"]["strategy"]["protectiveExitConfirmations"]["KXBTC15M-PROTECT"]["streak"] == 2
    restored.record("user-a", _protective_decision("2026-09-05T20:00:10Z", 3))
    assert len(saves) == 3
    cursor = saves[-1]["modeState"]["real"]["strategy"]["protectiveExitConfirmations"]["KXBTC15M-PROTECT"]
    assert cursor["confirmed"] is True
    assert cursor["side"] == "YES"  # Held side, not the opposite new-entry signal.
    # Once capped, repeated qualifying cycles don't rewrite the full ledger.
    restored.record("user-a", _protective_decision("2026-09-05T20:00:15Z", 3))
    assert len(saves) == 3
    # Only compact metadata, not a raw candle/book payload, is required.
    assert len(json.dumps(cursor)) < 400


def test_protective_confirmation_clears_invalid_frames_and_sale_orders(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    ticker = "KXBTC15M-PROTECT"

    def progress():
        return store.get("user-a", environment="real")["strategy"].get("protectiveExitConfirmations", {})

    store.record("user-a", _protective_decision("2026-09-05T20:00:00Z"))
    # The other family/strike is independent; older invalid records cannot
    # erase the latest confirmed evidence for this position.
    store.record("user-a", _protective_decision("2026-09-05T20:00:02Z", ticker="KXBTCD-OTHER"))
    store.record("user-a", _protective_decision("2026-09-05T19:59:59Z", protectiveConfirmation={}))
    assert ticker in progress() and "KXBTCD-OTHER" in progress()
    store.record("user-a", _protective_decision("2026-09-05T20:00:05Z", protectiveConfirmation={}))
    assert ticker not in progress()
    assert "KXBTCD-OTHER" in progress()
    # Missing/invalid quality explicitly breaks continuity at the same time.
    candidate = _protective_decision("2026-09-05T20:00:10Z")
    store.record("user-a", candidate)
    store.record("user-a", {**candidate, "protectiveConfirmation": {**candidate["protectiveConfirmation"], "dataQualityEligible": False}})
    assert ticker not in progress()
    store.record("user-a", _protective_decision("2026-09-05T20:00:15Z"))
    store.record("user-a", _protective_decision("2026-09-05T20:00:20Z", 2, action="SELL_YES"), {"order_id": "close-1", "status": "canceled", "fill_count_fp": "0.00"})
    assert ticker not in progress()  # Reevaluate position after any routed sale.


def test_protective_confirmation_resets_stale_changed_side_and_is_bounded(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    store.record("user-a", _protective_decision("2026-09-05T20:00:00Z"))
    store.record("user-a", _protective_decision("2026-09-05T20:00:40Z", 3))
    cursor = store.get("user-a", environment="real")["strategy"]["protectiveExitConfirmations"]["KXBTC15M-PROTECT"]
    assert cursor["streak"] == 1 and not cursor["confirmed"]
    store.record("user-a", _protective_decision("2026-09-05T20:00:45Z", 3, account={"heldSide": "NO"}))
    cursor = store.get("user-a", environment="real")["strategy"]["protectiveExitConfirmations"]["KXBTC15M-PROTECT"]
    assert cursor["side"] == "NO" and cursor["streak"] == 1
    for index in range(20):
        store.record("user-a", _protective_decision("2026-09-05T20:00:50Z", ticker=f"KXBTCD-{index}"))
    assert len(store.get("user-a", environment="real")["strategy"]["protectiveExitConfirmations"]) == 16


def test_transient_errors_never_rewrite_full_durable_state(tmp_path):
    calls = []

    def save(_user_id, payload):
        calls.append(payload)
        return {"version": len(calls)}

    store = KalshiRobotState(
        str(tmp_path / "state.json"),
        state_saver=save,
    )

    store.error("user-a", "ReadTimeout")
    store.error("user-a", "ReadTimeout")
    store.error("user-a", "ReadTimeout")
    assert calls == []

    store.error("user-a", "OperationsStoreUnavailable")
    assert calls == []

    decision = {
        "action": "WAIT",
        "config": {"executionMode": "real"},
        "market": {"ticker": "KXBTC15M-RECOVERED"},
    }
    store.record("user-a", decision)
    assert calls == []


def test_durable_writer_skips_runtime_only_changes_at_the_final_boundary(tmp_path):
    saves = []

    def save(_user_id, payload):
        saves.append(copy.deepcopy(payload))
        return {"version": len(saves)}

    store = KalshiRobotState(
        str(tmp_path / "state.json"),
        state_saver=save,
    )
    store.configure("user-a", True, {"executionMode": "real"})
    assert len(saves) == 1

    state = store._users["user-a"]
    bucket = state["modeState"]["real"]
    state["runs"] = 99
    state["lastRunAt"] = "2026-08-02T12:00:00Z"
    state["lastError"] = "temporary"
    bucket["runs"] = 99
    bucket["lastRunAt"] = "2026-08-02T12:00:00Z"
    bucket["lastError"] = "temporary"
    store._save_user("user-a")
    assert len(saves) == 1

    bucket["arming"]["reason"] = "durable_change"
    store._save_user("user-a")
    assert len(saves) == 2
    assert "runs" not in saves[-1]
    assert "lastRunAt" not in saves[-1]
    assert "lastError" not in saves[-1]
    assert "runs" not in saves[-1]["modeState"]["real"]


def test_durable_payload_omits_rebuildable_mirrors_and_legacy_learning(tmp_path):
    durable = {}
    saves = []

    def save(user_id, payload):
        durable[user_id] = copy.deepcopy(payload)
        saves.append(copy.deepcopy(payload))
        return {"version": len(saves)}

    store = KalshiRobotState(
        str(tmp_path / "state.json"),
        state_loader=durable.get,
        state_saver=save,
    )
    store.configure("user-a", True, {"executionMode": "paper"})
    state = store._users["user-a"]
    state["learningObservations"] = [{"unused": "x" * 2000}]
    state["modeState"]["paper"]["learningExamples"] = [
        {"unused": "y" * 2000}
    ]
    state["modeState"]["paper"]["decisions"] = [
        {"action": "WAIT", "features": {"unused": "z" * 4000}}
    ]
    state["modeState"]["paper"]["filledTrades"] = [{
        "environment": "paper",
        "ticker": "KXBTC15M-FILLED",
        "orderId": "order-filled-1",
        "orderFilled": True,
        "action": "BUY_YES",
    }]
    full_size = len(json.dumps(state, separators=(",", ":")))

    store.configure("user-a", True, {
        "executionMode": "paper",
        "riskPerTradePct": 0.5,
    })
    persisted = saves[-1]
    persisted_size = len(json.dumps(persisted, separators=(",", ":")))

    for field in (
        "config", "strategy", "tradedTickers", "filledTrades",
        "processedSettlements", "decisions", "decisionLimit",
        "learningObservations", "learningExamples", "strategyLibrary",
    ):
        assert field not in persisted
    assert "learningExamples" not in persisted["modeState"]["paper"]
    assert "decisions" not in persisted["modeState"]["paper"]
    assert "decisionLimit" not in persisted["modeState"]["paper"]
    assert persisted["modeState"]["paper"]["filledTrades"][0]["orderId"] == "order-filled-1"
    assert persisted_size < full_size * 0.75

    restored = KalshiRobotState(
        str(tmp_path / "restored.json"),
        state_loader=durable.get,
        state_saver=save,
    ).get("user-a", environment="paper")
    assert restored["enabled"] is True
    assert restored["config"]["executionMode"] == "paper"
    assert restored["config"]["riskPerTradePct"] == 0.5
    assert restored["decisionLimit"] == 50
    assert restored["decisions"] == []
    assert restored["filledTrades"][0]["orderId"] == "order-filled-1"


def test_legacy_full_durable_state_is_compacted_once_on_restore(tmp_path):
    seed = KalshiRobotState(str(tmp_path / "seed.json")).get(
        "user-a", environment="paper"
    )
    seed["learningObservations"] = [{"unused": "x" * 1000}]
    durable = {"user-a": copy.deepcopy(seed)}
    saves = []

    def save(user_id, payload):
        durable[user_id] = copy.deepcopy(payload)
        saves.append(copy.deepcopy(payload))
        return {"version": len(saves)}

    store = KalshiRobotState(
        str(tmp_path / "restored.json"),
        state_loader=durable.get,
        state_saver=save,
    )
    restored = store.get("user-a", environment="paper")

    assert restored["config"]["executionMode"] == "paper"
    assert len(saves) == 1
    assert "config" not in saves[0]
    assert "learningObservations" not in saves[0]

    store.get("user-a", environment="paper")
    assert len(saves) == 1


def test_paper_reconciliation_removes_stale_conflict_artifacts_for_same_market(tmp_path):
    store = KalshiRobotState(str(tmp_path / "state.json"))
    state = store._state("u")
    strategy = state["modeState"]["paper"]["strategy"]
    strategy["closedTradeRecords"] = [{
        "orderId": "stale-close",
        "ticker": "KXBTC15M-CONFLICT",
        "environment": "paper",
        "closedAt": "2026-07-25T12:12:00Z",
        "side": "YES",
        "count": 1,
        "pnl": 0.20,
    }]
    strategy["settlementRecords"] = [{
        "key": "paper:KXBTC15M-CONFLICT:2026-07-25T12:15:00Z:YES",
        "ticker": "KXBTC15M-CONFLICT",
        "environment": "paper",
        "settledAt": "2026-07-25T12:15:00Z",
        "side": "YES",
        "result": "YES",
        "contracts": 1,
        "pnl": 0.40,
    }]
    canonical_fill = {
        "fill_id": "canonical-close-fill",
        "order_id": "canonical-close",
        "ticker": "KXBTC15M-CONFLICT",
        "environment": "paper",
        "action": "SELL",
        "reduce_only": True,
        "outcome_side": "YES",
        "fill_count_fp": 1,
        "average_price_dollars": 0.70,
        "position_cost_dollars": 0.50,
        "gross_proceeds_dollars": 0.70,
        "entry_fee_allocated_dollars": 0.01,
        "fee_cost_dollars": 0.01,
        "realized_pnl_dollars": 0.18,
        "created_time": "2026-07-25T12:13:00Z",
    }
    canonical_entry = {
        "fill_id": "canonical-entry-fill",
        "order_id": "canonical-entry",
        "ticker": "KXBTC15M-CONFLICT",
        "environment": "paper",
        "action": "BUY",
        "outcome_side": "YES",
        "fill_count_fp": 2,
        "price_dollars": 0.50,
        "position_cost_dollars": 1.0,
        "fee_cost_dollars": 0.02,
        "created_time": "2026-07-25T12:10:00Z",
    }
    canonical_settlement = {
        "ticker": "KXBTC15M-CONFLICT",
        "settled_time": "2026-07-25T12:15:05Z",
        "market_result": "YES",
        "yes_count_fp": 1,
        "revenue_dollars": 1.0,
        "yes_total_cost_dollars": 0.50,
        "fee_cost_dollars": 0.01,
    }

    reconciled = store.reconcile_settlements(
        "u", [canonical_settlement], [canonical_entry, canonical_fill], environment="paper",
    )
    strategy = reconciled["strategy"]

    assert [row["orderId"] for row in strategy["closedTradeRecords"]] == ["canonical-close"]
    assert [row["key"] for row in strategy["settlementRecords"]] == [
        "paper:KXBTC15M-CONFLICT:2026-07-25T12:15:05Z:YES"
    ]


def test_read_only_reconciliation_returns_analytics_without_durable_write(tmp_path):
    saves = []

    def save(_user_id, _payload):
        saves.append(1)

    store = KalshiRobotState(
        str(tmp_path / "state.json"),
        state_saver=save,
    )
    store.record("u", {
        "generatedAt": "2026-07-25T12:00:00Z",
        "action": "BUY_YES",
        "side": "YES",
        "market": {"ticker": "KXBTC15M-READONLY"},
        "edge": {"fairProbability": 0.70, "price": 0.50},
    }, {
        "order_id": "entry-readonly",
        "status": "filled",
        "fill_count": 1,
        "environment": "paper",
    })
    writes_after_entry = len(saves)

    state = store.reconcile_settlements("u", [{
        "ticker": "KXBTC15M-READONLY",
        "settled_time": "2026-07-25T12:15:00Z",
        "market_result": "YES",
        "yes_count_fp": 1,
        "revenue_dollars": 1.0,
        "yes_total_cost_dollars": 0.50,
    }], None, environment="paper", persist=False)

    assert state["strategy"]["settledSamples"] == 1
    assert len(saves) == writes_after_entry
