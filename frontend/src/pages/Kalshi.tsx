import React from 'react';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  DatabaseOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { useLanguage } from '../contexts/LanguageContext';
import kalshiAPI, {
  DEFAULT_KALSHI_BOT_CONFIG,
  KALSHI_CONFIG_CHANGED_EVENT,
  KALSHI_CONFIG_STORAGE_KEY,
  KalshiBotConfig,
  KalshiDecision,
  KalshiPaperPortfolio,
  KalshiPaperRobotState,
  KalshiEvaluationResponse,
  KalshiAnalyticsResponse,
  KalshiFamilyDiagnostics,
  KalshiGate,
  KalshiSnapshot,
} from '../services/kalshiApi';
import '../styles/Kalshi.css';

const MARKET_REFRESH_MS = 5_000;
const PORTFOLIO_REFRESH_MS = 10_000;
const RETIRED_KALSHI_BLOCKING_REASONS = new Set([
  'daily_loss_limit',
]);

export const activeKalshiBlockingReasons = (reasons: unknown): string[] => (
  Array.isArray(reasons)
    ? reasons
      .map((reason) => String(reason || ''))
      .filter((reason) => reason && !RETIRED_KALSHI_BLOCKING_REASONS.has(reason))
    : []
);

export type KalshiView =
  | 'desk'
  | 'rules'
  | 'bot'
  | 'decisions'
  | 'risk'
  | 'positions'
  | 'orders'
  | 'data'
  | 'connection';

export const resolveKalshiView = (pathname: string): KalshiView => {
  if (pathname.endsWith('/markets/rules')) return 'rules';
  if (pathname.endsWith('/bots/decisions')) return 'decisions';
  if (pathname.endsWith('/bots/risk')) return 'risk';
  if (pathname.includes('/bots/')) return 'bot';
  if (pathname.endsWith('/portfolio/orders')) return 'orders';
  if (pathname.includes('/portfolio/')) return 'positions';
  if (pathname.endsWith('/settings/connection')) return 'connection';
  if (pathname.includes('/settings/')) return 'data';
  return 'desk';
};

const number = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const metricNumber = (source: Record<string, any>, keys: string[]): number | null => {
  for (const key of keys) {
    const parsed = number(source?.[key]);
    if (parsed !== null) return parsed;
  }
  return null;
};

export interface KalshiStabilityMetrics {
  samples: number;
  wins: number;
  losses: number;
  totalPnl: number | null;
  averageWin: number | null;
  averageLoss: number | null;
  profitFactor: number | null;
  recoveryMultiple: number | null;
  maxDrawdown: number | null;
  worstTrade: number | null;
}

/**
 * Normalizes the evolving backend analytics contract and remains useful while
 * older deployments only expose realized records. Loss values are always
 * returned as positive magnitudes so the recovery multiple reads naturally.
 */
export const deriveKalshiStabilityMetrics = (
  rawSource: unknown,
  fallbackRecords: Array<Record<string, any>> = [],
): KalshiStabilityMetrics => {
  const source = rawSource && typeof rawSource === 'object'
    ? rawSource as Record<string, any>
    : {};
  const sourceRecords = Array.isArray(source.records)
    ? source.records
    : Array.isArray(source.realizedTradeRecords)
      ? source.realizedTradeRecords
      : Array.isArray(source.settlementRecords)
        ? source.settlementRecords
        : fallbackRecords;
  const records = sourceRecords
    .filter((record) => number(record?.pnl) !== null);
  const explicitSamples = metricNumber(source, ['samples', 'realizedSamples', 'settledSamples']);
  const recordsCoverSamples = explicitSamples === null
    || records.length >= Math.max(0, Math.trunc(explicitSamples));
  const completeRecords = recordsCoverSamples ? records : [];
  const pnlValues = completeRecords.map((record) => Number(record.pnl));
  const positive = pnlValues.filter((value) => value > 0);
  const negative = pnlValues.filter((value) => value < 0);
  const explicitWins = metricNumber(source, ['wins', 'realizedWins']);
  const explicitLosses = metricNumber(source, ['losses', 'realizedLosses']);
  const samples = Math.max(0, Math.trunc(explicitSamples ?? pnlValues.length));
  const wins = Math.max(0, Math.trunc(explicitWins ?? positive.length));
  const losses = Math.max(0, Math.trunc(explicitLosses ?? negative.length));
  const grossWin = positive.reduce((sum, value) => sum + value, 0);
  const grossLoss = negative.reduce((sum, value) => sum + Math.abs(value), 0);
  const explicitAverageWin = metricNumber(source, ['averageWin', 'realizedAverageWin']);
  const explicitAverageLoss = metricNumber(source, ['averageLoss', 'realizedAverageLoss']);
  const averageWin = explicitAverageWin !== null
    ? Math.abs(explicitAverageWin)
    : positive.length
      ? grossWin / positive.length
      : null;
  const averageLoss = explicitAverageLoss !== null
    ? Math.abs(explicitAverageLoss)
    : negative.length
      ? grossLoss / negative.length
      : null;
  const factorGrossWin = grossWin > 0 ? grossWin : (averageWin ?? 0) * wins;
  const factorGrossLoss = grossLoss > 0 ? grossLoss : (averageLoss ?? 0) * losses;
  const explicitProfitFactor = metricNumber(source, ['profitFactor', 'realizedProfitFactor']);
  const profitFactor = explicitProfitFactor !== null
    ? Math.max(0, explicitProfitFactor)
    : factorGrossLoss > 0
      ? factorGrossWin / factorGrossLoss
      : factorGrossWin > 0
        ? Infinity
        : null;
  const explicitRecovery = metricNumber(source, ['recoveryMultiple', 'realizedRecoveryMultiple']);
  const recoveryMultiple = explicitRecovery !== null
    ? Math.max(0, explicitRecovery)
    : averageWin !== null && averageWin > 0 && averageLoss !== null
      ? averageLoss / averageWin
      : null;
  const explicitTotal = metricNumber(source, ['totalPnl', 'realizedPnl', 'realizedTotalPnl']);
  const totalPnl = explicitTotal ?? (pnlValues.length
    ? pnlValues.reduce((sum, value) => sum + value, 0)
    : averageWin !== null || averageLoss !== null
      ? factorGrossWin - factorGrossLoss
      : null);
  const explicitWorst = metricNumber(source, ['worstTrade', 'realizedWorstTrade']);
  const worstTrade = explicitWorst ?? (pnlValues.length ? Math.min(...pnlValues) : null);
  const explicitDrawdown = metricNumber(source, ['maxDrawdown', 'realizedMaxDrawdown']);
  let derivedDrawdown: number | null = null;
  if (pnlValues.length) {
    const ordered = [...completeRecords].sort((left, right) => {
      const leftAt = Date.parse(String(left?.settledAt || left?.settled_at || left?.at || ''));
      const rightAt = Date.parse(String(right?.settledAt || right?.settled_at || right?.at || ''));
      if (!Number.isFinite(leftAt) || !Number.isFinite(rightAt)) return 0;
      return leftAt - rightAt;
    });
    let cumulative = 0;
    let peak = 0;
    let maxDrawdown = 0;
    ordered.forEach((record) => {
      cumulative += Number(record.pnl);
      peak = Math.max(peak, cumulative);
      maxDrawdown = Math.max(maxDrawdown, peak - cumulative);
    });
    derivedDrawdown = maxDrawdown;
  }

  return {
    samples,
    wins,
    losses,
    totalPnl,
    averageWin,
    averageLoss,
    profitFactor,
    recoveryMultiple,
    maxDrawdown: explicitDrawdown !== null ? Math.abs(explicitDrawdown) : derivedDrawdown,
    worstTrade,
  };
};

export interface KalshiPrimaryWaitReason {
  key: string;
  count?: number;
  source: 'backend' | 'current' | 'aggregate';
}

const SHARD_FUNDING_BLOCKERS = {
  kalshi_live_shard_cash_insufficient: [
    'Contract exchange funds are insufficient', '合约所属分片资金不足',
  ],
  kalshi_live_shard_cash_unavailable: [
    'Contract exchange balance is unverified', '合约所属分片余额尚未核实',
  ],
} as const;

export interface KalshiFundingReadiness {
  status: 'funded' | 'insufficient' | 'unverified' | 'exit';
  exchangeIndex: number | null;
  aggregateCash: number | null;
  shardCash: number | null;
  requiredCash: number | null;
  fundingGap: number | null;
  strategyQualified: boolean;
}

/** Aggregate account cash is not collateral available to this contract. */
export const deriveKalshiFundingReadiness = (
  decision: Partial<KalshiDecision> | null | undefined,
  isRealMode: boolean,
): KalshiFundingReadiness | null => {
  if (!isRealMode || !decision) return null;
  const source = { ...decision.account, ...decision.shardFunding };
  const blockers = activeKalshiBlockingReasons(decision.blockingReasons);
  const blocked = blockers.includes('kalshi_live_shard_cash_insufficient');
  const unavailable = blockers.includes('kalshi_live_shard_cash_unavailable');
  if (
    !decision.shardFunding
    && source.fundingStatus === undefined
    && source.shardCashKnown === undefined
    && !blocked
    && !unavailable
  ) return null;
  const cash = number(source.shardCashAvailable);
  const cashKnown = source.shardCashKnown === true && cash !== null && cash >= 0;
  const rawIndex = number(source.exchangeIndex);
  const exchangeIndex = rawIndex !== null && Number.isInteger(rawIndex) && rawIndex >= 0
    ? rawIndex : null;
  const exit = source.applicable === false || String(decision.action || '').startsWith('SELL_');
  const insufficient = blocked || source.executionBlocked === true
    || source.requiresUserFunding === true || source.fundingStatus === 'empty'
    || (cashKnown && cash === 0);
  return {
    status: exit ? 'exit' : unavailable ? 'unverified' : insufficient ? 'insufficient'
      : cashKnown ? 'funded' : 'unverified',
    exchangeIndex,
    aggregateCash: number(source.aggregateCashAvailable),
    // Never replace an unknown/zero shard balance with aggregate cash.
    shardCash: cashKnown ? cash : null,
    requiredCash: number(source.requiredCash),
    fundingGap: number(source.fundingGap),
    strategyQualified: source.strategyQualified === true,
  };
};

export const kalshiFundingSummary = (funding: KalshiFundingReadiness, chinese: boolean): string => {
  if (funding.status === 'exit') {
    return chinese
      ? '分片现金不足不会阻止减仓和平仓；退出仍须通过持仓、盘口与最终路由检查。'
      : 'Low exchange cash does not block reduce-only exits; inventory, liquidity, and final routing checks still apply.';
  }
  if (funding.status === 'insufficient') {
    return chinese
      ? '资金不足阻止新开仓和加仓，不阻止减仓和平仓。其他分片的现金不能直接用于该合约；AlphaLab 未自动转移任何资金。'
      : 'Insufficient funds block new entries and adds, not reduce-only exits. Cash on other exchanges cannot directly fund this contract; AlphaLab has not transferred any funds.';
  }
  if (funding.status === 'unverified') {
    return chinese
      ? '总账户现金不等于该合约的可用资金。后台须核实所属分片余额后才能开仓；未核实不代表余额为零。'
      : 'Aggregate cash is not this contract’s available collateral. The backend must verify its exchange balance before an entry; unverified does not mean zero.';
  }
  return chinese
    ? '合约所属分片有可用现金，但这不代表已经下单；仍须通过交易信号、仓位限制与最终账户检查。'
    : 'This contract’s exchange has cash available, but no order is implied; signal, sizing, and final account checks must still pass.';
};

const normalizedPrimaryBlocker = (value: unknown): { key: string; count?: number } | null => {
  if (typeof value === 'string') {
    const key = activeKalshiBlockingReasons([value])[0];
    return key ? { key } : null;
  }
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  const key = activeKalshiBlockingReasons([record.key ?? record.reason])[0];
  const count = number(record.count);
  return key ? { key, ...(count === null ? {} : { count }) } : null;
};

/** Picks one causal wait reason instead of presenting correlated gate failures. */
export const primaryKalshiNoTradeReason = (
  diagnostics: Partial<KalshiFamilyDiagnostics> | null | undefined,
  currentDecision: Partial<KalshiDecision> | null | undefined,
): KalshiPrimaryWaitReason | null => {
  const currentReasons = activeKalshiBlockingReasons(currentDecision?.blockingReasons);
  if (currentDecision?.action === 'WAIT' && currentReasons.length) {
    const operationalPriority = [
      'robot_scheduler_unhealthy',
      'account_snapshot_stale',
      'kalshi_live_shard_cash_unavailable',
      'kalshi_live_shard_cash_insufficient',
      'reference_ready',
      'data_freshness',
    ];
    const operationalReason = operationalPriority.find((key) => currentReasons.includes(key));
    if (operationalReason) return { key: operationalReason, source: 'current' };
  }

  const backendPrimary = normalizedPrimaryBlocker(diagnostics?.primaryBlocker)
    || (diagnostics?.primaryBlockers || []).map(normalizedPrimaryBlocker).find(Boolean)
    || null;
  if (backendPrimary) return { ...backendPrimary, source: 'backend' };

  if (currentDecision?.action === 'WAIT' && currentReasons.length) {
    const systemPriority = [
      'entry_window',
    ];
    const systemReason = systemPriority.find((key) => currentReasons.includes(key));
    if (systemReason) return { key: systemReason, source: 'current' };
    if (currentReasons.includes('conservative_edge') || currentReasons.includes('net_edge')) {
      return {
        key: currentReasons.includes('conservative_edge') ? 'conservative_edge' : 'net_edge',
        source: 'current',
      };
    }
    const causalPriority = [
      'model_probability',
      'price_band',
      'spread',
      'relative_spread',
      'depth',
      'position_size',
      'single_market_exposure',
      'portfolio_exposure',
    ];
    return {
      key: causalPriority.find((key) => currentReasons.includes(key)) || currentReasons[0],
      source: 'current',
    };
  }

  const aggregate = (diagnostics?.blockers || [])
    .filter((item) => activeKalshiBlockingReasons([item.key]).length > 0);
  const hasEdgeBlock = aggregate.some((item) => ['conservative_edge', 'net_edge'].includes(item.key));
  const independent = aggregate
    .filter((item) => !(item.key === 'depth' && hasEdgeBlock))
    .sort((left, right) => Number(right.count || 0) - Number(left.count || 0));
  return independent[0]
    ? { key: independent[0].key, count: Number(independent[0].count || 0), source: 'aggregate' }
    : null;
};

const money = (value: unknown, digits = 2) => {
  const parsed = number(value);
  if (parsed === null) return '--';
  return parsed.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: digits });
};

const ratio = (value: unknown, digits = 2) => {
  if (value === Infinity) return '∞';
  const parsed = number(value);
  return parsed === null ? '--' : parsed.toFixed(digits);
};

const probability = (value: unknown, digits = 1) => {
  const parsed = number(value);
  return parsed === null ? '--' : `${(parsed * 100).toFixed(digits)}%`;
};

const cents = (value: unknown, digits = 1) => {
  const parsed = number(value);
  return parsed === null ? '--' : `${(parsed * 100).toFixed(digits)}c`;
};

export const kalshiAccountEquityDollars = (balance: KalshiPaperPortfolio['balance']): number => (
  (Number(balance?.balance || 0) + Number(balance?.portfolio_value || 0)) / 100
);

const orderSidePrice = (item: any, key: 'limit' | 'average') => {
  const direct = key === 'limit' ? item?.limit_price_dollars : item?.average_price_dollars;
  if (direct != null) return direct;
  const side = String(item?.outcome_side || '').toUpperCase();
  if (side === 'YES') return item?.yes_price_dollars;
  if (side === 'NO') return item?.no_price_dollars;
  return null;
};

const orderFee = (item: any) => {
  if (item?.fee_cost_dollars != null) return Number(item.fee_cost_dollars);
  if (Array.isArray(item?.matched_levels) && item.matched_levels.length) {
    return item.matched_levels.reduce((sum: number, level: any) => sum + Number(level.fee_cost_dollars || 0), 0);
  }
  return null;
};

export const positionSideLabel = (item: any): 'YES' | 'NO' | '--' => {
  const explicit = String(item?.net_side || '').toUpperCase();
  if (explicit === 'YES' || explicit === 'NO') return explicit;
  const rawPosition = number(item?.position_fp ?? item?.position) ?? 0;
  if (rawPosition > 0) return 'YES';
  if (rawPosition < 0) return 'NO';
  return '--';
};

export const portfolioEnvironmentMatchesMode = (
  portfolio: Pick<KalshiPaperPortfolio, 'environment'> | null | undefined,
  requestedMode: KalshiBotConfig['executionMode'],
): boolean => String(portfolio?.environment || '').trim().toLowerCase() === requestedMode;

export const shouldStartKalshiPortfolioRequest = (
  inFlightMode: KalshiBotConfig['executionMode'] | null,
  requestedMode: KalshiBotConfig['executionMode'],
): boolean => inFlightMode !== requestedMode;

export interface KalshiOperationToken {
  mode: KalshiBotConfig['executionMode'];
  epoch: number;
  requestId: number;
}

const declaredKalshiMode = (value: unknown): KalshiBotConfig['executionMode'] | null => {
  const normalized = String(value || '').trim().toLowerCase();
  return normalized === 'real' || normalized === 'paper' ? normalized : null;
};

export const kalshiResponseStateMatchesMode = (
  state: unknown,
  expectedMode: KalshiBotConfig['executionMode'],
): boolean => {
  if (!state || typeof state !== 'object') return false;
  const record = state as Record<string, any>;
  const configMode = declaredKalshiMode(record.config?.executionMode);
  const activeMode = declaredKalshiMode(record.activeEnvironment);
  const selectedMode = record.selectedEnvironment == null
    ? expectedMode
    : declaredKalshiMode(record.selectedEnvironment);
  return (
    configMode === expectedMode
    && activeMode === expectedMode
    && selectedMode === expectedMode
  );
};

export const shouldAcceptKalshiOperationResponse = (
  token: KalshiOperationToken,
  currentMode: KalshiBotConfig['executionMode'],
  currentEpoch: number,
  currentRequestId: number,
  responseState: unknown,
): boolean => (
  token.mode === currentMode
  && token.epoch === currentEpoch
  && token.requestId === currentRequestId
  && kalshiResponseStateMatchesMode(responseState, token.mode)
);

export const kalshiRequiresExplicitEnable = (
  state: KalshiPaperRobotState | null | undefined,
  mode: KalshiBotConfig['executionMode'],
): boolean => Boolean(
  mode === 'real'
  && state
  && !state.enabled
  && state.modeState?.real?.arming?.awaitingExplicitEnable,
);

const recordTimeMs = (record: Record<string, any>): number | null => {
  const raw = (
    record.created_time
    ?? record.createdAt
    ?? record.created_ts
    ?? record.createdTs
    ?? record.submitted_at
    ?? record.submittedAt
    ?? record.settled_time
    ?? record.settledAt
    ?? record.updated_time
    ?? record.updatedAt
    ?? record.ts
  );
  if (raw === null || raw === undefined || raw === '') return null;
  if (typeof raw === 'number' || /^\d+(?:\.\d+)?$/.test(String(raw).trim())) {
    const numeric = Number(raw);
    if (!Number.isFinite(numeric)) return null;
    return numeric < 1_000_000_000_000 ? numeric * 1000 : numeric;
  }
  const parsed = Date.parse(String(raw));
  return Number.isFinite(parsed) ? parsed : null;
};

export const isAlphaLabManagedLedgerRecord = (record: Record<string, any> | null | undefined): boolean => {
  if (!record || typeof record !== 'object') return false;
  return (
    record.alphaLabManaged === true
    || record.alphalabManaged === true
    || record.alphaLabOrder === true
    || String(record.source || '').trim().toLowerCase() === 'alphalab'
  );
};

export interface KalshiVisibleLedger {
  baselineReady: boolean;
  resetAt: string | null;
  orders: Array<Record<string, any>>;
  fills: Array<Record<string, any>>;
  settlements: Array<Record<string, any>>;
}

export const visibleKalshiLedger = (portfolio: KalshiPaperPortfolio): KalshiVisibleLedger => {
  const orders = Array.isArray(portfolio.orders) ? portfolio.orders : [];
  const fills = Array.isArray(portfolio.fills) ? portfolio.fills : [];
  const settlements = Array.isArray(portfolio.settlements) ? portfolio.settlements : [];
  if (String(portfolio.environment).toLowerCase() !== 'real') {
    return { baselineReady: true, resetAt: null, orders, fills, settlements };
  }

  const baseline = portfolio.analytics?.displayBaseline as (
    NonNullable<KalshiPaperPortfolio['analytics']>['displayBaseline'] & { alphaLabOnly?: boolean }
  ) | undefined;
  const resetAt = typeof baseline?.resetAt === 'string' ? baseline.resetAt : null;
  const resetAtMs = resetAt ? Date.parse(resetAt) : Number.NaN;
  const baselineEnvironment = String(baseline?.environment || 'real').toLowerCase();
  const baselineReady = Boolean(
    baseline?.active
    && Number.isFinite(resetAtMs)
    && baselineEnvironment === 'real'
    && baseline?.alphaLabOnly === true
  );
  if (!baselineReady) {
    return { baselineReady: false, resetAt, orders: [], fills: [], settlements: [] };
  }

  const afterBaseline = (record: Record<string, any>) => {
    const timestamp = recordTimeMs(record);
    return timestamp !== null && timestamp > resetAtMs;
  };
  const visibleOrders = orders.filter((record) => (
    afterBaseline(record) && isAlphaLabManagedLedgerRecord(record)
  ));
  const visibleOrderIds = new Set(
    visibleOrders
      .flatMap((record) => [record.order_id, record.orderId])
      .filter((value) => value !== null && value !== undefined && value !== '')
      .map(String),
  );
  const linkedToVisibleOrder = (record: Record<string, any>) => (
    [record.order_id, record.orderId]
      .filter((value) => value !== null && value !== undefined && value !== '')
      .some((value) => visibleOrderIds.has(String(value)))
  );
  const visibleEvent = (record: Record<string, any>) => (
    afterBaseline(record)
    && (isAlphaLabManagedLedgerRecord(record) || linkedToVisibleOrder(record))
  );

  return {
    baselineReady: true,
    resetAt,
    orders: visibleOrders,
    fills: fills.filter(visibleEvent),
    settlements: settlements.filter(visibleEvent),
  };
};

const warningStrings = (value: unknown): string[] => {
  if (typeof value === 'string' && value.trim()) return [value.trim()];
  if (Array.isArray(value)) return value.flatMap(warningStrings);
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return warningStrings(record.message ?? record.warning ?? record.detail);
  }
  return [];
};

export const kalshiPortfolioWarnings = (portfolio: unknown): string[] => {
  if (!portfolio || typeof portfolio !== 'object') return [];
  const record = portfolio as Record<string, unknown>;
  const completeness = record.completeness && typeof record.completeness === 'object'
    ? record.completeness as Record<string, unknown>
    : null;
  const warnings = [
    ...warningStrings(record.warnings),
    ...warningStrings(completeness?.warnings),
    ...warningStrings(completeness?.errors),
  ];
  const incompleteResources = ['balance', 'positions', 'orders', 'fills', 'settlements', 'history']
    .filter((key) => completeness?.[key] === false);
  if (incompleteResources.length) {
    warnings.push(`Incomplete account data: ${incompleteResources.join(', ')}`);
  }
  const missing = warningStrings(
    completeness?.missing
    ?? completeness?.missingResources
    ?? completeness?.missing_resources,
  );
  if (missing.length) warnings.push(`Missing account data: ${missing.join(', ')}`);

  const status = String(completeness?.status || '').trim().toLowerCase();
  const explicitlyIncomplete = (
    completeness?.complete === false
    || completeness?.isComplete === false
    || ['partial', 'incomplete', 'degraded', 'failed'].includes(status)
  );
  if (explicitlyIncomplete && warnings.length === 0) {
    warnings.push(status
      ? `Kalshi reported ${status} portfolio data.`
      : 'Kalshi reported incomplete portfolio data.');
  }

  return Array.from(new Set(warnings));
};

const exitTriggerLabel = (trigger: string | null | undefined, chinese: boolean) => {
  switch (trigger) {
    case 'fee_adjusted_take_profit':
      return chinese ? '扣费后止盈' : 'NET TAKE PROFIT';
    case 'protective_stop_loss':
      return chinese ? '保护止损' : 'PROTECTIVE STOP';
    case 'emergency_stop_loss':
      return chinese ? '紧急止损' : 'EMERGENCY STOP';
    default:
      return '';
  }
};

const compact = (value: unknown) => {
  const parsed = number(value);
  if (parsed === null) return '--';
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(parsed);
};

const readStoredConfig = (): KalshiBotConfig => {
  try {
    const parsed = JSON.parse(localStorage.getItem(KALSHI_CONFIG_STORAGE_KEY) || '{}');
    const stored = parsed && typeof parsed === 'object' ? { ...parsed } : {};
    delete stored.maxDailyLossPct;
    return { ...DEFAULT_KALSHI_BOT_CONFIG, ...stored };
  } catch {
    return { ...DEFAULT_KALSHI_BOT_CONFIG };
  }
};

const writeStoredConfig = (config: KalshiBotConfig, emitChange = false) => {
  try {
    localStorage.setItem(KALSHI_CONFIG_STORAGE_KEY, JSON.stringify(config));
    if (emitChange) {
      window.dispatchEvent(new CustomEvent(KALSHI_CONFIG_CHANGED_EVENT, { detail: config }));
    }
  } catch {}
};

const PnlChart: React.FC<{ points: Array<{ at: string; cumulativePnl: number }>; label: string }> = ({ points, label }) => {
  if (!points.length) return <div className="kalshi-pnl-empty">{label}</div>;
  const width = 820;
  const height = 230;
  const paddingX = 46;
  const paddingY = 24;
  const values = points.map((point) => Number(point.cumulativePnl) || 0);
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  const span = Math.max(1, high - low);
  const x = (index: number) => paddingX + (index / Math.max(1, points.length - 1)) * (width - paddingX * 2);
  const y = (value: number) => paddingY + ((high - value) / span) * (height - paddingY * 2);
  const line = points.map((point, index) => `${index ? 'L' : 'M'} ${x(index).toFixed(2)} ${y(Number(point.cumulativePnl) || 0).toFixed(2)}`).join(' ');
  const area = `${line} L ${x(points.length - 1).toFixed(2)} ${y(low).toFixed(2)} L ${x(0).toFixed(2)} ${y(low).toFixed(2)} Z`;
  const zeroY = y(0);
  const last = values[values.length - 1] || 0;
  const firstLabel = points[0]?.at ? new Date(points[0].at).toLocaleDateString() : '';
  const lastLabel = points[points.length - 1]?.at ? new Date(points[points.length - 1].at).toLocaleDateString() : '';
  return (
    <svg className="kalshi-pnl-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
      <defs>
        <linearGradient id="kalshiPnlArea" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={last >= 0 ? '#5f7f60' : '#b66a45'} stopOpacity="0.22" />
          <stop offset="100%" stopColor={last >= 0 ? '#5f7f60' : '#b66a45'} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((ratio) => <line key={ratio} x1={paddingX} y1={paddingY + ratio * (height - paddingY * 2)} x2={width - paddingX} y2={paddingY + ratio * (height - paddingY * 2)} className="kalshi-pnl-grid" />)}
      <line x1={paddingX} y1={zeroY} x2={width - paddingX} y2={zeroY} className="kalshi-pnl-zero" />
      <path d={area} className="kalshi-pnl-area" />
      <path d={line} className={last >= 0 ? 'is-positive' : 'is-negative'} />
      <circle cx={x(points.length - 1)} cy={y(last)} r="4.5" className={last >= 0 ? 'is-positive' : 'is-negative'} />
      <text x={paddingX} y={height - 7} className="kalshi-pnl-axis">{firstLabel}</text>
      <text x={width - paddingX} y={height - 7} textAnchor="end" className="kalshi-pnl-axis">{lastLabel}</text>
      <text x={paddingX - 8} y={y(high) + 4} textAnchor="end" className="kalshi-pnl-axis">{money(high)}</text>
      <text x={paddingX - 8} y={y(low) + 4} textAnchor="end" className="kalshi-pnl-axis">{money(low)}</text>
    </svg>
  );
};

const EdgeTimelineChart: React.FC<{
  points: KalshiFamilyDiagnostics['edgeTimeline'];
  emptyLabel: string;
}> = ({ points, emptyLabel }) => {
  const clean = points.filter((point) => number(point.netEdge) !== null || number(point.conservativeEdge) !== null);
  if (clean.length < 2) return <div className="kalshi-edge-empty">{emptyLabel}</div>;
  const width = 820;
  const height = 218;
  const paddingX = 48;
  const paddingY = 24;
  const values = clean.flatMap((point) => [number(point.netEdge), number(point.conservativeEdge)]).filter((value): value is number => value !== null);
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  const span = Math.max(0.01, high - low);
  const x = (index: number) => paddingX + (index / Math.max(1, clean.length - 1)) * (width - paddingX * 2);
  const y = (value: number) => paddingY + ((high - value) / span) * (height - paddingY * 2);
  const pathFor = (key: 'netEdge' | 'conservativeEdge') => clean
    .map((point, index) => `${index ? 'L' : 'M'} ${x(index).toFixed(2)} ${y(number(point[key]) || 0).toFixed(2)}`)
    .join(' ');
  const start = clean[0]?.at ? new Date(clean[0].at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
  const end = clean[clean.length - 1]?.at ? new Date(clean[clean.length - 1].at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
  return (
    <svg className="kalshi-edge-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={emptyLabel}>
      {[0.25, 0.5, 0.75].map((ratio) => <line key={ratio} x1={paddingX} y1={paddingY + ratio * (height - paddingY * 2)} x2={width - paddingX} y2={paddingY + ratio * (height - paddingY * 2)} className="kalshi-edge-grid" />)}
      <line x1={paddingX} y1={y(0)} x2={width - paddingX} y2={y(0)} className="kalshi-edge-zero" />
      <path d={pathFor('netEdge')} className="is-net" />
      <path d={pathFor('conservativeEdge')} className="is-conservative" />
      <text x={paddingX} y={height - 5} className="kalshi-edge-axis">{start}</text>
      <text x={width - paddingX} y={height - 5} textAnchor="end" className="kalshi-edge-axis">{end}</text>
      <text x={paddingX - 8} y={y(high) + 4} textAnchor="end" className="kalshi-edge-axis">{(high * 100).toFixed(1)}%</text>
      <text x={paddingX - 8} y={y(low) + 4} textAnchor="end" className="kalshi-edge-axis">{(low * 100).toFixed(1)}%</text>
    </svg>
  );
};

const actionLabel = (decision: KalshiDecision | null, chinese: boolean, isRealMode: boolean) => {
  if (!decision || decision.action === 'WAIT') return chinese ? '等待' : 'WAIT';
  if (isRealMode) {
    return decision.action === 'BUY_YES'
      ? (chinese ? '实盘预筛候选 YES' : 'REAL PREFLIGHT YES')
      : (chinese ? '实盘预筛候选 NO' : 'REAL PREFLIGHT NO');
  }
  if (decision.action === 'BUY_YES') return chinese ? '模拟买入 YES' : 'PAPER BUY YES';
  return chinese ? '模拟买入 NO' : 'PAPER BUY NO';
};

export const actionSummary = (decision: KalshiDecision | null, chinese: boolean, isRealMode: boolean) => {
  if (!decision) return chinese ? '正在等待首个完整快照。' : 'Waiting for the first complete snapshot.';
  if (decision.action === 'WAIT') {
    const activeReasons = activeKalshiBlockingReasons(decision.blockingReasons);
    if (activeReasons.includes('robot_scheduler_unhealthy')) {
      return chinese
        ? '后台实盘机器人当前不健康；页面只展示行情，不会把预筛候选标记为可下单。'
        : 'The live background robot is unhealthy; the page shows market evidence but will not mark this preflight as order-ready.';
    }
    if (activeReasons.includes('account_snapshot_stale')) {
      const age = decision.accountPreflight?.snapshotAgeSeconds;
      const ageLabel = Number.isFinite(Number(age)) ? `${Math.round(Number(age))}s` : '—';
      return chinese
        ? `后台账户快照已过期（${ageLabel}）；必须等机器人取得新的余额、持仓和订单数据后才能下单。`
        : `The scheduler-owned account snapshot is stale (${ageLabel}); fresh balance, position, and order data are required before routing.`;
    }
    const funding = deriveKalshiFundingReadiness(decision, isRealMode);
    if (funding && ['insufficient', 'unverified'].includes(funding.status)) {
      return kalshiFundingSummary(funding, chinese);
    }
    const count = activeReasons.length;
    const accountLabel = isRealMode ? (chinese ? 'Kalshi 实盘账户' : 'Kalshi Real account') : (chinese ? 'AlphaLab 模拟账户' : 'AlphaLab Paper account');
    return chinese
      ? `${count} 道门控尚未通过；本轮不向${accountLabel}提交订单。`
      : `${count} gate${count === 1 ? '' : 's'} remain blocked; no order is routed to the ${accountLabel}.`;
  }
  if (isRealMode) {
    return chinese
      ? '行情、账户与仓位预筛已通过；这不是成交回报。只有后台机器人最终路由并收到 Kalshi 回报后才算已下单。'
      : 'Market, account, and sizing preflight passed; this is not a fill report. An order exists only after the background robot routes it and Kalshi responds.';
  }
  return chinese
    ? `扣除费用和模型不确定性后仍有正边际，并通过盘口与账户门控；只有机器人运行时才会提交限价单。`
    : 'Edge remains positive after fees and uncertainty, and all book and account gates clear; only the running robot submits limit orders.';
};

export const KalshiFundingNotice: React.FC<{
  decision: Partial<KalshiDecision> | null;
  isRealMode: boolean;
  chinese: boolean;
}> = ({ decision, isRealMode, chinese }) => {
  const funding = deriveKalshiFundingReadiness(decision, isRealMode);
  if (!funding) return null;
  const copy = (en: string, zh: string) => chinese ? zh : en;
  const attention = funding.status === 'insufficient' || funding.status === 'unverified';
  const titles = {
    funded: copy('Contract exchange funds available', '合约分片资金可用'),
    insufficient: copy('Entry blocked: contract exchange needs funds', '开仓受阻：合约所属分片资金不足'),
    unverified: copy('Contract exchange balance awaiting verification', '合约分片余额待核实'),
    exit: copy('Position exits remain eligible for checks', '持仓退出仍可接受检查'),
  };
  const exchangeName = funding.exchangeIndex === 2
    ? copy('Crypto Predictions · exchange 2', '加密预测 · 分片 2')
    : funding.exchangeIndex === null
      ? copy('Contract exchange unverified', '合约分片待核实')
      : copy(`Contract exchange ${funding.exchangeIndex}`, `合约分片 ${funding.exchangeIndex}`);
  return (
    <section className={`kalshi-funding-notice${attention ? ' needs-attention' : ''}`} data-testid="kalshi-funding-readiness" aria-label={copy('Contract funding readiness', '合约资金状态')}>
      <div className="kalshi-funding-heading">
        {attention ? <WarningOutlined /> : <SafetyCertificateOutlined />}
        <div><strong>{titles[funding.status]}</strong><small>{exchangeName}</small></div>
        {funding.strategyQualified && <span>{copy('Signal qualified · funding checked separately', '信号已通过 · 资金单独检查')}</span>}
      </div>
      <dl className="kalshi-funding-balances">
        <div><dt>{copy('Cash across all exchanges', '所有分片合计现金')}</dt><dd>{money(funding.aggregateCash)}</dd></div>
        <div><dt>{copy('Cash on this contract’s exchange', '该合约分片可用现金')}</dt><dd>{funding.shardCash === null ? copy('Unverified', '待核实') : money(funding.shardCash)}</dd></div>
        {funding.requiredCash !== null && <div><dt>{copy('Planned entry debit', '计划开仓支出')}</dt><dd>{money(funding.requiredCash)}</dd></div>}
        {funding.fundingGap !== null && funding.fundingGap > 0 && <div><dt>{copy('Planned entry funding gap', '计划开仓资金缺口')}</dt><dd>{money(funding.fundingGap)}</dd></div>}
      </dl>
      <p>{kalshiFundingSummary(funding, chinese)}</p>
    </section>
  );
};

const Kalshi: React.FC = () => {
  const { language } = useLanguage();
  const location = useLocation();
  const navigate = useNavigate();
  const chinese = language === 'zh-CN';
  const view = resolveKalshiView(location.pathname);
  const isHourly = location.pathname.includes('btc-hourly');
  const copy = React.useCallback((english: string, chineseText: string) => (chinese ? chineseText : english), [chinese]);
  const [snapshot, setSnapshot] = React.useState<KalshiSnapshot | null>(null);
  const [decision, setDecision] = React.useState<KalshiDecision | null>(null);
  const [history, setHistory] = React.useState<KalshiDecision[]>([]);
  const [config, setConfig] = React.useState<KalshiBotConfig>(readStoredConfig);
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);
  const [error, setError] = React.useState('');
  const [accountStatus, setAccountStatus] = React.useState<Record<string, any> | null>(null);
  const [paperPortfolio, setPaperPortfolio] = React.useState<KalshiPaperPortfolio | null>(null);
  const [portfolioLoading, setPortfolioLoading] = React.useState(false);
  const [portfolioError, setPortfolioError] = React.useState('');
  const [portfolioResetting, setPortfolioResetting] = React.useState(false);
  const [robotState, setRobotState] = React.useState<KalshiPaperRobotState | null>(null);
  const [robotBusy, setRobotBusy] = React.useState(false);
  const [applyBusy, setApplyBusy] = React.useState(false);
  const [applyMessage, setApplyMessage] = React.useState('');
  const [analytics, setAnalytics] = React.useState<KalshiAnalyticsResponse | null>(null);
  const [clock, setClock] = React.useState(Date.now());
  const inFlightRef = React.useRef(false);
  const mountedRef = React.useRef(true);
  const syncedServerConfigRef = React.useRef('');
  const modeRef = React.useRef<KalshiBotConfig['executionMode']>(config.executionMode === 'real' ? 'real' : 'paper');
  const operationEpochRef = React.useRef(0);
  const writeOperationRequestRef = React.useRef(0);
  const activeWriteOperationRef = React.useRef<KalshiOperationToken | null>(null);
  const hourlyFamilyRef = React.useRef(isHourly);
  const portfolioRequestRef = React.useRef(0);
  const portfolioInFlightRef = React.useRef<KalshiOperationToken | null>(null);
  const portfolioResettingRef = React.useRef(false);
  const robotStatusRequestRef = React.useRef(0);
  const evaluationRequestRef = React.useRef(0);
  const executionMode: KalshiBotConfig['executionMode'] = config.executionMode === 'real' ? 'real' : 'paper';
  const isRealMode = executionMode === 'real';

  React.useLayoutEffect(() => {
    hourlyFamilyRef.current = isHourly;
  }, [isHourly]);

  const operationTokenIsCurrent = React.useCallback((
    token: KalshiOperationToken,
    currentRequestId: number,
  ): boolean => (
    mountedRef.current
    && token.mode === modeRef.current
    && token.epoch === operationEpochRef.current
    && token.requestId === currentRequestId
  ), []);

  const beginWriteOperation = React.useCallback((
    expectedMode: KalshiBotConfig['executionMode'],
  ): KalshiOperationToken | null => {
    if (activeWriteOperationRef.current) return null;
    const token: KalshiOperationToken = {
      mode: expectedMode,
      epoch: operationEpochRef.current,
      requestId: writeOperationRequestRef.current + 1,
    };
    writeOperationRequestRef.current = token.requestId;
    activeWriteOperationRef.current = token;

    // A write can change state, portfolio, and the evaluation snapshot. Any
    // older read must not commit after this operation starts.
    portfolioRequestRef.current += 1;
    portfolioInFlightRef.current = null;
    robotStatusRequestRef.current += 1;
    evaluationRequestRef.current += 1;
    inFlightRef.current = false;
    if (mountedRef.current) setPortfolioLoading(false);
    return token;
  }, []);

  const writeOperationIsCurrent = React.useCallback((
    token: KalshiOperationToken,
  ): boolean => (
    operationTokenIsCurrent(token, writeOperationRequestRef.current)
    && activeWriteOperationRef.current?.mode === token.mode
    && activeWriteOperationRef.current?.epoch === token.epoch
    && activeWriteOperationRef.current?.requestId === token.requestId
  ), [operationTokenIsCurrent]);

  React.useEffect(() => {
    modeRef.current = executionMode;
  }, [executionMode]);

  const acceptPayload = React.useCallback((payload: KalshiEvaluationResponse, expectedMode = modeRef.current) => {
    if (!mountedRef.current) return;
    if (
      modeRef.current !== expectedMode
      || !payload.robotState
      || !kalshiResponseStateMatchesMode(payload.robotState, expectedMode)
    ) return;
    setSnapshot(payload.snapshot);
    setDecision(payload.decision);
    setHistory((current) => {
      if (current[0]?.generatedAt === payload.decision.generatedAt) return current;
      return [payload.decision, ...current].slice(0, 24);
    });
    setError('');
    if (payload.robotState) setRobotState(payload.robotState);
  }, []);

  const acceptPortfolio = React.useCallback((
    candidate: KalshiPaperPortfolio,
    expectedMode: KalshiBotConfig['executionMode'],
  ): boolean => {
    if (!mountedRef.current || modeRef.current !== expectedMode) return false;
    if (!portfolioEnvironmentMatchesMode(candidate, expectedMode)) {
      const returnedEnvironment = String(candidate?.environment || copy('unknown', '未知')).toUpperCase();
      setPaperPortfolio(null);
      setPortfolioError(copy(
        `Portfolio environment mismatch: requested ${expectedMode.toUpperCase()}, but the backend returned ${returnedEnvironment}. AlphaLab blocked the response instead of relabeling it.`,
        `投资组合环境不一致：请求的是 ${expectedMode.toUpperCase()}，但后端返回了 ${returnedEnvironment}。AlphaLab 已阻止该响应，不会把它错误标记成当前模式。`,
      ));
      return false;
    }
    setPaperPortfolio(candidate);
    setPortfolioError('');
    return true;
  }, [copy]);

  const evaluate = React.useCallback(async (quiet = false) => {
    if (activeWriteOperationRef.current || inFlightRef.current || document.hidden) return;
    const expectedMode = executionMode;
    const expectedHourly = isHourly;
    const requestId = evaluationRequestRef.current + 1;
    evaluationRequestRef.current = requestId;
    const token: KalshiOperationToken = {
      mode: expectedMode,
      epoch: operationEpochRef.current,
      requestId,
    };
    const isCurrentEvaluation = () => (
      operationTokenIsCurrent(token, evaluationRequestRef.current)
      && hourlyFamilyRef.current === expectedHourly
    );
    inFlightRef.current = true;
    if (!quiet) setRefreshing(true);
    try {
      const response = expectedHourly
        ? await kalshiAPI.evaluateHourly(expectedMode)
        : await kalshiAPI.evaluate(config);
      if (!response.data?.success) throw new Error(response.data?.message || 'Kalshi evaluation failed');
      if (!isCurrentEvaluation()) return;
      if (!kalshiResponseStateMatchesMode(response.data?.robotState, expectedMode)) {
        throw new Error('Kalshi evaluation returned state for a stale execution mode.');
      }
      acceptPayload(response.data, expectedMode);
    } catch (requestError: any) {
      if (isCurrentEvaluation()) {
        setError(requestError?.response?.data?.message || requestError?.message || copy('Market data is temporarily unavailable.', '市场数据暂时不可用。'));
      }
    } finally {
      if (operationTokenIsCurrent(token, evaluationRequestRef.current)) inFlightRef.current = false;
      if (isCurrentEvaluation()) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [acceptPayload, config, copy, executionMode, isHourly, operationTokenIsCurrent]);

  React.useEffect(() => {
    mountedRef.current = true;
    void evaluate();
    return () => {
      mountedRef.current = false;
      operationEpochRef.current += 1;
      writeOperationRequestRef.current += 1;
      portfolioRequestRef.current += 1;
      robotStatusRequestRef.current += 1;
      evaluationRequestRef.current += 1;
      activeWriteOperationRef.current = null;
      portfolioInFlightRef.current = null;
      portfolioResettingRef.current = false;
      inFlightRef.current = false;
    };
  // Initial request is intentionally once; config changes are applied explicitly.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadPaperPortfolio = React.useCallback(async (modeOverride: KalshiBotConfig['executionMode'] = modeRef.current) => {
    if (activeWriteOperationRef.current || portfolioResettingRef.current) return;
    if (!shouldStartKalshiPortfolioRequest(portfolioInFlightRef.current?.mode ?? null, modeOverride)) return;
    const requestId = portfolioRequestRef.current + 1;
    portfolioRequestRef.current = requestId;
    const token: KalshiOperationToken = {
      mode: modeOverride,
      epoch: operationEpochRef.current,
      requestId,
    };
    portfolioInFlightRef.current = token;
    if (mountedRef.current) setPortfolioLoading(true);
    try {
      const response = await kalshiAPI.paperPortfolio(modeOverride);
      if (!operationTokenIsCurrent(token, portfolioRequestRef.current)) return;
      if (!shouldAcceptKalshiOperationResponse(
        token,
        modeRef.current,
        operationEpochRef.current,
        portfolioRequestRef.current,
        response.data?.state,
      )) {
        setPaperPortfolio(null);
        setPortfolioError(copy(
          'Kalshi returned account state for a different execution mode. AlphaLab blocked the stale response.',
          'Kalshi 返回了其他执行模式的账户状态。AlphaLab 已阻止该过期响应。',
        ));
        return;
      }
      if (response.data?.portfolio) {
        acceptPortfolio(response.data.portfolio, modeOverride);
      } else {
        setPaperPortfolio(null);
        setPortfolioError(copy(
          'Kalshi returned no portfolio payload. The account view remains unavailable for safety.',
          'Kalshi 未返回投资组合数据。为确保安全，账户页面将保持不可用。',
        ));
      }
      setRobotState(response.data.state);
    } catch (requestError: any) {
      if (operationTokenIsCurrent(token, portfolioRequestRef.current)) {
        setPortfolioError(requestError?.response?.data?.message || requestError?.message || copy(
          'Kalshi account refresh failed. Try again.',
          'Kalshi 账户刷新失败，请重试。',
        ));
      }
    } finally {
      if (
        portfolioInFlightRef.current?.requestId === token.requestId
        && portfolioInFlightRef.current?.epoch === token.epoch
        && portfolioInFlightRef.current?.mode === token.mode
      ) {
        portfolioInFlightRef.current = null;
        if (mountedRef.current) setPortfolioLoading(false);
      }
    }
  }, [acceptPortfolio, copy, operationTokenIsCurrent]);

  const loadAnalytics = React.useCallback(async (
    modeOverride: KalshiBotConfig['executionMode'] = modeRef.current,
  ) => {
    try {
      const response = await kalshiAPI.analytics(modeOverride, 24);
      if (!mountedRef.current || modeRef.current !== modeOverride || !response.data?.success) return;
      setAnalytics(response.data);
    } catch {
      // Trading/evaluation stays available if the durable diagnostics endpoint
      // is temporarily unavailable; its source card will show no samples.
    }
  }, []);

  const resetPortfolioDisplay = async () => {
    if (portfolioResetting) return;
    const confirmed = window.confirm(copy(
      'Start a new visible Portfolio period? Account equity and every historical order, fill and settlement will be preserved.',
      '确定开始一个新的 Portfolio 显示周期吗？账户权益以及所有历史订单、成交和结算都会完整保留。',
    ));
    if (!confirmed) return;
    const expectedMode = modeRef.current;
    const token = beginWriteOperation(expectedMode);
    if (!token) return;
    portfolioResettingRef.current = true;
    setPortfolioResetting(true);
    try {
      const response = await kalshiAPI.resetPortfolioDisplay(expectedMode);
      if (!writeOperationIsCurrent(token)) return;
      if (!response.data?.success || !response.data.portfolio) {
        throw new Error(response.data?.message || 'Portfolio display reset failed');
      }
      if (!shouldAcceptKalshiOperationResponse(
        token,
        modeRef.current,
        operationEpochRef.current,
        writeOperationRequestRef.current,
        response.data?.state,
      )) {
        throw new Error(copy(
          'Kalshi returned a stale mode state after resetting the Portfolio display.',
          '重置 Portfolio 显示周期后，Kalshi 返回了过期的模式状态。',
        ));
      }
      if (!acceptPortfolio(response.data.portfolio, expectedMode)) return;
      setRobotState(response.data.state);
      setError('');
    } catch (requestError: any) {
      if (writeOperationIsCurrent(token)) {
        setError(requestError?.response?.data?.message || requestError?.message || copy(
          'Portfolio display period could not be reset.',
          'Portfolio 显示周期重置失败。',
        ));
      }
    } finally {
      if (writeOperationIsCurrent(token)) {
        activeWriteOperationRef.current = null;
        portfolioResettingRef.current = false;
        setPortfolioResetting(false);
        void loadPaperPortfolio(expectedMode);
      }
    }
  };

  React.useEffect(() => {
    const handleExternalConfigChange = (event: Event) => {
      const detail = (event as CustomEvent<Partial<KalshiBotConfig> | undefined>).detail;
      if (!detail || typeof detail !== 'object') return;
      const nextConfig = { ...readStoredConfig(), ...detail } as KalshiBotConfig;
      const nextMode = nextConfig.executionMode === 'real' ? 'real' : 'paper';

      // Funding-environment changes are a hard async boundary. Invalidate
      // every response captured under the prior mode before updating refs/UI.
      operationEpochRef.current += 1;
      writeOperationRequestRef.current += 1;
      portfolioRequestRef.current += 1;
      robotStatusRequestRef.current += 1;
      evaluationRequestRef.current += 1;
      activeWriteOperationRef.current = null;
      portfolioInFlightRef.current = null;
      portfolioResettingRef.current = false;
      inFlightRef.current = false;

      setConfig(nextConfig);
      modeRef.current = nextMode;
      setPaperPortfolio(null);
      setPortfolioError('');
      setSnapshot(null);
      setDecision(null);
      setHistory([]);
      setRobotState(null);
      setAnalytics(null);
      setPortfolioLoading(false);
      setPortfolioResetting(false);
      setRobotBusy(false);
      setApplyBusy(false);
      setRefreshing(true);
      const evaluationRequestId = evaluationRequestRef.current + 1;
      evaluationRequestRef.current = evaluationRequestId;
      const expectedHourly = hourlyFamilyRef.current;
      const evaluationToken: KalshiOperationToken = {
        mode: nextMode,
        epoch: operationEpochRef.current,
        requestId: evaluationRequestId,
      };
      const modeEvaluationIsCurrent = () => (
        operationTokenIsCurrent(evaluationToken, evaluationRequestRef.current)
        && hourlyFamilyRef.current === expectedHourly
      );
      void Promise.all([
        loadPaperPortfolio(nextMode),
        loadAnalytics(nextMode),
        (expectedHourly ? kalshiAPI.evaluateHourly(nextMode) : kalshiAPI.evaluate(nextConfig)).then((response) => {
          if (!response.data?.success) throw new Error(response.data?.message || 'Kalshi evaluation failed');
          if (!modeEvaluationIsCurrent()) return;
          if (!kalshiResponseStateMatchesMode(response.data?.robotState, nextMode)) {
            throw new Error('Kalshi evaluation returned state for a stale execution mode.');
          }
          acceptPayload(response.data, nextMode);
        }),
      ])
        .catch((requestError: any) => {
          if (modeEvaluationIsCurrent()) {
            setError(requestError?.response?.data?.message || copy('Kalshi account refresh failed. Try again.', 'Kalshi 账户刷新失败，请重试。'));
          }
        })
        .finally(() => {
          if (modeEvaluationIsCurrent()) {
            setRefreshing(false);
          }
        });
    };
    window.addEventListener(KALSHI_CONFIG_CHANGED_EVENT, handleExternalConfigChange);
    return () => window.removeEventListener(KALSHI_CONFIG_CHANGED_EVENT, handleExternalConfigChange);
  }, [acceptPayload, copy, loadAnalytics, loadPaperPortfolio, operationTokenIsCurrent]);

  React.useEffect(() => {
    const mode = executionMode;
    const token: KalshiOperationToken = {
      mode,
      epoch: operationEpochRef.current,
      requestId: robotStatusRequestRef.current + 1,
    };
    robotStatusRequestRef.current = token.requestId;
    kalshiAPI.paperRobotStatus(mode)
      .then((response) => {
        if (!shouldAcceptKalshiOperationResponse(
          token,
          modeRef.current,
          operationEpochRef.current,
          robotStatusRequestRef.current,
          response.data?.state,
        )) return;
        setRobotState(response.data.state);
      })
      .catch(() => undefined);
    void loadPaperPortfolio(mode);
    void loadAnalytics(mode);
  }, [executionMode, loadAnalytics, loadPaperPortfolio]);

  React.useEffect(() => {
    const serverConfig = robotState?.config;
    if (!serverConfig || Object.keys(serverConfig).length === 0) return;
    const serverMode = serverConfig.executionMode === 'real' ? 'real' : 'paper';
    if (serverMode !== executionMode) return;
    const signature = JSON.stringify(serverConfig);
    if (syncedServerConfigRef.current === signature) return;
    syncedServerConfigRef.current = signature;
    setConfig((current) => {
      const next = { ...current, ...serverConfig } as KalshiBotConfig;
      writeStoredConfig(next, false);
      return next;
    });
  }, [executionMode, robotState?.config]);

  React.useEffect(() => {
    if (view !== 'connection') return;
    let active = true;
    kalshiAPI.status()
      .then((response) => { if (active) setAccountStatus(response.data || null); })
      .catch(() => { if (active) setAccountStatus(null); });
    return () => { active = false; };
  }, [view]);

  React.useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  React.useEffect(() => {
    const timer = window.setInterval(() => void evaluate(true), MARKET_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [evaluate]);

  React.useEffect(() => {
    setSnapshot(null);
    setDecision(null);
    setHistory([]);
    setLoading(true);
    inFlightRef.current = false;
    void evaluate();
  // Switching robot tabs keeps this page mounted, so refresh explicitly.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isHourly]);

  React.useEffect(() => {
    const timer = window.setInterval(() => void loadPaperPortfolio(), PORTFOLIO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadPaperPortfolio]);

  React.useEffect(() => {
    const timer = window.setInterval(() => void loadAnalytics(), 30_000);
    return () => window.clearInterval(timer);
  }, [loadAnalytics]);

  const toggleRobot = async () => {
    if (robotBusy || activeWriteOperationRef.current) return;
    const expectedMode = modeRef.current;
    const expectedHourly = hourlyFamilyRef.current;
    const token = beginWriteOperation(expectedMode);
    if (!token) return;
    const scopedConfig: KalshiBotConfig = {
      ...config,
      executionMode: expectedMode,
    };
    const requestedEnabled = !robotState?.enabled;
    setRobotBusy(true);
    try {
      writeStoredConfig(scopedConfig, false);
      const response = await kalshiAPI.setPaperRobot(
        requestedEnabled,
        scopedConfig,
        expectedMode,
        'kalshi-workspace-toggle',
      );
      if (!writeOperationIsCurrent(token)) return;
      if (!response.data?.success) {
        throw new Error(response.data?.message || 'Kalshi robot update failed');
      }
      if (!shouldAcceptKalshiOperationResponse(
        token,
        modeRef.current,
        operationEpochRef.current,
        writeOperationRequestRef.current,
        response.data?.state,
      )) {
        throw new Error(copy(
          'Kalshi returned robot state for a stale execution mode.',
          'Kalshi 返回了过期执行模式的机器人状态。',
        ));
      }
      setRobotState(response.data.state);
      // A successful start may include the tick's raw risk portfolio. Do not
      // commit it because Real display-baseline filtering is applied only by
      // the dedicated Portfolio GET performed in finally.
      if (
        hourlyFamilyRef.current === expectedHourly
        && response.data?.snapshot
        && response.data?.decision
      ) {
        acceptPayload({
          success: true,
          snapshot: response.data.snapshot,
          decision: response.data.decision,
          robotState: response.data.state,
        }, expectedMode);
      }
      setError('');
    } catch (requestError: any) {
      if (writeOperationIsCurrent(token)) {
        setError(requestError?.response?.data?.message || requestError?.message || copy(
          'Kalshi robot could not be updated.',
          'Kalshi 机器人无法更新。',
        ));
      }
    } finally {
      if (writeOperationIsCurrent(token)) {
        activeWriteOperationRef.current = null;
        setRobotBusy(false);
        void loadPaperPortfolio(expectedMode);
      }
    }
  };

  const applyConfig = async (nextConfig: KalshiBotConfig = config) => {
    if (applyBusy || activeWriteOperationRef.current) return;
    const expectedMode = modeRef.current;
    const expectedHourly = hourlyFamilyRef.current;
    const token = beginWriteOperation(expectedMode);
    if (!token) return;
    const scopedConfig: KalshiBotConfig = {
      ...nextConfig,
      executionMode: expectedMode,
    };
    setApplyBusy(true);
    setApplyMessage('');
    setConfig(scopedConfig);
    writeStoredConfig(scopedConfig, false);
    try {
      const saved = await kalshiAPI.savePaperRobotConfig(scopedConfig, expectedMode);
      if (!writeOperationIsCurrent(token)) return;
      if (!saved.data?.success) {
        throw new Error(saved.data?.message || 'Kalshi robot configuration could not be saved');
      }
      if (!shouldAcceptKalshiOperationResponse(
        token,
        modeRef.current,
        operationEpochRef.current,
        writeOperationRequestRef.current,
        saved.data?.state,
      )) {
        throw new Error(copy(
          'Kalshi returned configuration state for a stale execution mode.',
          'Kalshi 返回了过期执行模式的配置状态。',
        ));
      }
      setRobotState(saved.data.state);
      const response = expectedHourly
        ? await kalshiAPI.evaluateHourly(expectedMode)
        : await kalshiAPI.evaluate(scopedConfig);
      if (!writeOperationIsCurrent(token)) return;
      if (!response.data?.success) throw new Error(response.data?.message || 'Kalshi evaluation failed');
      if (hourlyFamilyRef.current === expectedHourly) {
        if (
          response.data.robotState
          && !kalshiResponseStateMatchesMode(response.data.robotState, expectedMode)
        ) {
          throw new Error(copy(
          'Kalshi evaluation returned state for a stale execution mode.',
          'Kalshi 评估返回了过期执行模式的状态。',
          ));
        }
        acceptPayload(response.data, expectedMode);
      }
      setApplyMessage(copy('Saved and evaluated with the new limits.', '已保存，并使用新限制完成评估。'));
    } catch (requestError: any) {
      if (writeOperationIsCurrent(token)) {
        setError(requestError?.response?.data?.message || requestError?.message || copy(
          'Robot limits could not be saved.',
          '机器人限制无法保存。',
        ));
      }
    } finally {
      if (writeOperationIsCurrent(token)) {
        activeWriteOperationRef.current = null;
        setApplyBusy(false);
        void loadPaperPortfolio(expectedMode);
      }
    }
  };

  const updateConfig = (key: keyof KalshiBotConfig, raw: number, scale = 1) => {
    if (!Number.isFinite(raw)) return;
    setConfig((current) => ({ ...current, [key]: raw / scale }));
  };

  const closeAt = decision?.market.closeTime ? Date.parse(decision.market.closeTime) : NaN;
  const secondsLeft = Number.isFinite(closeAt) ? Math.max(0, Math.floor((closeAt - clock) / 1000)) : null;
  const countdown = secondsLeft === null
    ? '--:--'
    : `${String(Math.floor(secondsLeft / 60)).padStart(2, '0')}:${String(secondsLeft % 60).padStart(2, '0')}`;
  const rawMarket = snapshot?.market || {};
  const rulesPrimary = typeof rawMarket.rules_primary === 'string' ? rawMarket.rules_primary : '';
  const rulesSecondary = typeof rawMarket.rules_secondary === 'string' ? rawMarket.rules_secondary : '';
  const active = snapshot?.selection === 'active';
  const blockedGateCount = decision?.gates.filter((gate) => gate.status === 'block').length || 0;
  const adaptiveGateCount = decision?.gates.filter((gate) => gate.status === 'observe').length || 0;
  const kalshiModeLabel = isRealMode ? copy('KALSHI REAL', 'KALSHI 实盘') : copy('ALPHALAB PAPER', 'ALPHALAB 模拟盘');

  const renderMetrics = () => (
    <section className="kalshi-metric-strip" aria-label={copy('Contract snapshot', '合约快照')}>
      <div><span>{copy('CONTRACT', '合约')}</span><strong>{decision?.market.ticker || 'KXBTC15M'}</strong><small>{active ? copy('Trading now', '正在交易') : copy('Next available interval', '下一个可用时段')}</small></div>
      <div><span>{copy('TIME LEFT', '剩余时间')}</span><strong>{countdown}</strong><small>{copy('Entry closes before settlement', '进场早于结算')}</small></div>
      <div><span>{copy('STRIKE', '结算基准')}</span><strong>{money(decision?.market.strike)}</strong><small>{copy('Reference at window open', '开盘参考价')}</small></div>
      <div><span>{copy('BTC REFERENCE', 'BTC 参考价')}</span><strong>{money(decision?.model.spot)}</strong><small>{decision?.model.isOfficialBrti ? `Official BRTI · ${decision.model.settlementWindowSamples || 0}/60` : decision?.model.referenceModel === 'brti_constituent_proxy' ? `BRTI proxy · ${decision.model.referenceVenueCount || 0} venues` : 'BTC-USD fallback'}</small></div>
      <div><span>{copy('YES / NO ASK', 'YES / NO 卖价')}</span><strong>{cents(decision?.market.yesAsk)} / {cents(decision?.market.noAsk)}</strong><small>{copy('Executable quotes', '可成交报价')}</small></div>
      <div><span>{copy('VOLUME / OI', '成交量 / 持仓量')}</span><strong>{compact(decision?.market.volume)} / {compact(decision?.market.openInterest)}</strong><small>{copy('Contract units', '合约份数')}</small></div>
    </section>
  );

  const renderDecision = () => (
    <section className="kalshi-desk-grid">
      <article className="kalshi-probability-panel">
        <div className="kalshi-section-head">
          <div><span>01 / {copy('PROBABILITY', '概率')}</span><h2>{copy('Market vs. model', '市场与模型')}</h2></div>
          <span className={`kalshi-live-mark${active ? ' is-live' : ''}`}><i />{active ? copy('LIVE CONTRACT', '实时合约') : copy('SCHEDULED', '等待开盘')}</span>
        </div>
        <div className="kalshi-probability-readout">
          <div><span>{copy('Market YES', '市场 YES')}</span><strong>{probability(decision?.model.marketYesProbability)}</strong><small>{copy('midpoint probability', '中间价概率')}</small></div>
          <div><span>{copy('Model YES', '模型 YES')}</span><strong>{probability(decision?.model.modelYesProbability)}</strong><small>{copy('spot and realized volatility', '现货与实现波动率')}</small></div>
          <div className="is-accent"><span>{copy('Tradable fair YES', '可交易公平 YES')}</span><strong>{probability(decision?.model.fairYesProbability)}</strong><small>{copy('requires a valid live book', '必须有有效实时盘口')}</small></div>
        </div>
        <div className="kalshi-probability-rail" aria-label={copy('YES probability comparison', 'YES 概率对比')}>
          <span className="kalshi-probability-axis"><i>0%</i><i>50%</i><i>100%</i></span>
          {number(decision?.model.marketYesProbability) !== null && <i className="is-market" style={{ left: `${Math.min(100, Math.max(0, Number(decision?.model.marketYesProbability) * 100))}%` }}><b>{copy('Market', '市场')}</b></i>}
          {number(decision?.model.fairYesProbability) !== null && <i className="is-model" style={{ left: `${Math.min(100, Math.max(0, Number(decision?.model.fairYesProbability) * 100))}%` }}><b>{copy('Fair', '公平')}</b></i>}
        </div>
        <dl className="kalshi-evidence-grid">
          <div><dt>{copy('Distance to strike', '距离基准')}</dt><dd>{number(decision?.model.distanceBps) === null ? '--' : `${Number(decision?.model.distanceBps).toFixed(1)} bps`}</dd></div>
          <div><dt>{copy('3m / 15m momentum', '3 / 15 分钟动量')}</dt><dd>{probability(decision?.model.momentum3m, 2)} / {probability(decision?.model.momentum15m, 2)}</dd></div>
          <div><dt>{copy('Horizon / 15m vol', '剩余周期 / 15 分钟波动')}</dt><dd>{probability(decision?.model.horizonVolatility, 2)} / {probability(decision?.model.projected15mVolatility, 2)}</dd></div>
          <div><dt>{copy('Model uncertainty', '模型不确定性')}</dt><dd>{probability(decision?.model.uncertainty, 1)}</dd></div>
          <div><dt>{copy('Vol regime / jump', '波动状态 / 跳跃')}</dt><dd>{number(decision?.model.volatilityRatio) === null ? '--' : `${Number(decision?.model.volatilityRatio).toFixed(2)}x / ${Number(decision?.model.jumpSigma || 0).toFixed(1)}σ`}</dd></div>
          <div><dt>{copy('Book imbalance', '盘口不平衡')}</dt><dd>{probability(decision?.market.bookImbalance)}</dd></div>
          <div><dt>{copy('Selected side', '选择方向')}</dt><dd>{decision?.edge.side || '--'}</dd></div>
        </dl>
      </article>

      <aside className={`kalshi-decision-panel is-${decision?.action === 'WAIT' ? 'wait' : 'advance'}`}>
        <div className="kalshi-section-head">
          <div><span>02 / {isRealMode ? copy('REAL READ-ONLY PREFLIGHT', '实盘只读预筛') : copy('PAPER DECISION', '模拟决策')}</span><h2>{copy('Risk-owned output', '风控主导输出')}</h2></div>
          <SafetyCertificateOutlined />
        </div>
        <div className="kalshi-action-line">
          <span>{actionLabel(decision, chinese, isRealMode)}</span>
          <strong>{decision?.signalQuality ?? 0}<small>/100</small></strong>
        </div>
        <p>{actionSummary(decision, chinese, isRealMode)}</p>
        <dl className="kalshi-decision-numbers">
          <div className="is-highlight"><dt>{copy('Favorite confidence', '优势侧胜率')}</dt><dd>{probability(decision?.edge.modelProbability ?? decision?.model.selectedModelProbability)}<em>{copy('min', '下限')} {probability(decision?.edge.minimumModelProbability, 0)}</em></dd></div>
          <div><dt>{copy('Executable price', '可成交价格')}</dt><dd>{cents(decision?.edge.price)}</dd></div>
          <div><dt>{copy('Conservative probability', '保守概率')}</dt><dd>{probability(decision?.edge.conservativeProbability)}</dd></div>
          <div><dt>{copy('Fee estimate', '费用估算')}</dt><dd>{cents(decision?.edge.feePerContract, 2)}</dd></div>
          <div><dt>{copy('Net / conservative edge', '净边际 / 保守边际')}</dt><dd>{probability(decision?.edge.netEdge)} / {probability(decision?.edge.conservativeEdge)}</dd></div>
          <div><dt>{copy('Required conservative edge', '最低保守边际')}</dt><dd>{probability(decision?.edge.minimumConservativeEdge)}</dd></div>
        </dl>
        <div className="kalshi-size-line">
          <span>{isRealMode ? copy('Preflight order size', '预筛订单数量') : copy('Paper size', '模拟仓位')}<small>{decision?.sizing.microSizingApplied ? copy('Bounded one-contract small-account sizing applied', '已应用受限的一份小账户仓位') : copy('Fractional Kelly, hard risk, cash, and book participation capped', '受分数凯利、硬风险、现金与盘口参与率共同限制')}</small></span>
          <strong>{decision?.sizing.contracts || 0} <small>{copy('contracts', '份')}</small></strong>
          <b>{money(decision?.sizing.maximumLoss)}</b>
        </div>
      </aside>
    </section>
  );

  const renderGates = () => (
    <section className="kalshi-gates-section">
      <div className="kalshi-section-head">
        <div><span>03 / {copy('TRADE GATES', '交易门控')}</span><h2>{copy('Hard controls and adaptive confirmation', '硬风控与自适应确认')}</h2></div>
        <strong>{decision ? `${blockedGateCount} ${copy('blocked', '阻断')} · ${adaptiveGateCount} ${copy('adaptive', '自适应')}` : '--'}</strong>
      </div>
      <div className="kalshi-gate-list">
        {(decision?.gates || []).map((gate: KalshiGate) => (
          <div key={gate.key} className={`kalshi-gate is-${gate.status}`}>
            {gate.status === 'pass' ? <CheckCircleOutlined /> : gate.status === 'observe' ? <ClockCircleOutlined /> : <CloseCircleOutlined />}
            <span><em>{String(gate.category || 'signal').toUpperCase()}</em><b>{chinese ? gate.labelZh : gate.label}</b><small>{gate.detail}</small></span>
            <strong>{gate.status === 'pass' ? copy('PASS', '通过') : gate.status === 'observe' ? copy('EDGE+', '提高边际') : copy('BLOCK', '阻断')}</strong>
          </div>
        ))}
      </div>
    </section>
  );

  const renderBook = () => {
    const rows = Math.max(snapshot?.orderbook.yes.length || 0, snapshot?.orderbook.no.length || 0, 1);
    return (
      <section className="kalshi-book-section">
        <div className="kalshi-section-head">
          <div><span>04 / {copy('ORDER BOOK', '订单簿')}</span><h2>{copy('Resting bid depth', '挂单买方深度')}</h2></div>
          <small>{copy('Asks are implied by the reciprocal YES / NO book', '卖价由 YES / NO 互补订单簿推导')}</small>
        </div>
        <div className="kalshi-book-table" role="table" aria-label={copy('Kalshi order book', 'Kalshi 订单簿')}>
          <div className="kalshi-book-header" role="row"><span>YES {copy('BID', '买价')}</span><span>{copy('SIZE', '数量')}</span><span>NO {copy('BID', '买价')}</span><span>{copy('SIZE', '数量')}</span></div>
          {Array.from({ length: Math.min(rows, 8) }).map((_, index) => {
            const yes = snapshot?.orderbook.yes[snapshot.orderbook.yes.length - 1 - index];
            const no = snapshot?.orderbook.no[snapshot.orderbook.no.length - 1 - index];
            return <div className="kalshi-book-row" role="row" key={index}><b>{yes ? cents(yes[0]) : '--'}</b><span>{yes ? compact(yes[1]) : '--'}</span><b>{no ? cents(no[0]) : '--'}</b><span>{no ? compact(no[1]) : '--'}</span></div>;
          })}
        </div>
      </section>
    );
  };

  const renderRiskControls = () => {
    const modeEquity = paperPortfolio
      ? kalshiAccountEquityDollars(paperPortfolio.balance)
      : Number(config.paperBankroll || 0);
    const controls: Array<{
      key: keyof KalshiBotConfig;
      label: [string, string];
      unit: [string, string];
      min: number;
      max: number;
      step: number;
      scale?: number;
    }> = [
      { key: 'riskPerTradePct', label: ['Risk per order', '每次下单风险'], unit: ['%', '%'], min: 0.1, max: 0.5, step: 0.05 },
      { key: 'minModelProbability', label: ['Model probability floor', '模型概率下限'], unit: ['%', '%'], min: 64, max: 90, step: 1, scale: 100 },
      { key: 'minPrice', label: ['Entry price floor', '进场价格下限'], unit: ['cents', '美分'], min: 47, max: 60, step: 1, scale: 100 },
      { key: 'maxPrice', label: ['Entry price ceiling', '进场价格上限'], unit: ['cents', '美分'], min: 60, max: 92, step: 1, scale: 100 },
      { key: 'minSecondsToClose', label: ['Entry window start', '进场窗口起点'], unit: ['seconds to close', '距关闭秒数'], min: 45, max: 360, step: 5 },
      { key: 'maxSecondsToClose', label: ['Entry window end', '进场窗口终点'], unit: ['seconds to close', '距关闭秒数'], min: 180, max: 840, step: 10 },
      { key: 'minNetEdge', label: ['Minimum net edge', '最低净边际'], unit: ['%', '%'], min: 1, max: 15, step: 0.25, scale: 100 },
      { key: 'minConservativeEdge', label: ['Conservative edge floor', '保守边际下限'], unit: ['%', '%'], min: 0.75, max: 10, step: 0.25, scale: 100 },
      { key: 'maxSpread', label: ['Maximum spread', '最大点差'], unit: ['cents', '美分'], min: 1, max: 20, step: 0.5, scale: 100 },
      { key: 'minDepthContracts', label: ['Minimum ask depth', '最低卖方深度'], unit: ['contracts', '份'], min: 1, max: 10000, step: 5 },
      { key: 'maxBookParticipation', label: ['Book participation cap', '盘口参与率上限'], unit: ['%', '%'], min: 1, max: 50, step: 1, scale: 100 },
      { key: 'maxPortfolioExposurePct', label: ['Portfolio exposure cap', '组合敞口上限'], unit: ['%', '%'], min: 2, max: 10, step: 1 },
      { key: 'maxSingleMarketExposurePct', label: ['Single-market / event exposure cap', '单一市场 / 事件敞口上限'], unit: ['%', '%'], min: 1, max: 2, step: 0.25 },
      { key: 'microPositionMaxLossDollars', label: ['Small-account absolute loss cap', '小账户单笔绝对风险上限'], unit: ['USD', '美元'], min: 0.25, max: 1, step: 0.05 },
      { key: 'microPositionMaxLossPct', label: ['Small-account equity loss cap', '小账户单笔权益风险上限'], unit: ['%', '%'], min: 1, max: 5, step: 0.25 },
      { key: 'microPositionMinNetEdge', label: ['Small-account minimum net edge', '小账户最低净边际'], unit: ['%', '%'], min: 2, max: 10, step: 0.25, scale: 100 },
      { key: 'microPositionMinConservativeEdge', label: ['Small-account conservative edge', '小账户最低保守边际'], unit: ['%', '%'], min: 1, max: 8, step: 0.25, scale: 100 },
      { key: 'addMinModelProbability', label: ['Add-on probability floor', '加仓概率下限'], unit: ['%', '%'], min: 50, max: 95, step: 1, scale: 100 },
      { key: 'addMinConservativeEdge', label: ['Add-on edge floor', '加仓边际下限'], unit: ['%', '%'], min: 0, max: 10, step: 0.25, scale: 100 },
      { key: 'addMinProbabilityImprovement', label: ['Add-on probability improvement', '加仓概率改善'], unit: ['percentage points', '百分点'], min: 1, max: 10, step: 0.25, scale: 100 },
      { key: 'addMinEdgeImprovement', label: ['Add-on edge improvement', '加仓边际改善'], unit: ['percentage points', '百分点'], min: 0.1, max: 3, step: 0.1, scale: 100 },
      { key: 'addSizeFraction', label: ['Add-on size fraction', '单次加仓比例'], unit: ['% of fresh size', '新计算仓位比例'], min: 10, max: 25, step: 5, scale: 100 },
      { key: 'minimumAddIntervalSeconds', label: ['Minimum add interval', '最短加仓间隔'], unit: ['seconds', '秒'], min: 90, max: 180, step: 5 },
      { key: 'executionPriceTolerance', label: ['IOC crossing allowance', 'IOC 成交容差'], unit: ['cents', '美分'], min: 0, max: 3, step: 0.25, scale: 100 },
      { key: 'minimumHoldSeconds', label: ['Minimum hold time', '最短持仓时间'], unit: ['seconds', '秒'], min: 60, max: 300, step: 5 },
      { key: 'exitValueBuffer', label: ['Exit edge buffer', '平仓边际缓冲'], unit: ['%', '%'], min: 0.25, max: 5, step: 0.25, scale: 100 },
      { key: 'minimumExitProfit', label: ['Minimum net exit profit', '最低净平仓盈利'], unit: ['cents per contract', '每份美分'], min: 0, max: 10, step: 0.5, scale: 100 },
      { key: 'takeProfitScaleOutPct', label: ['Take-profit scale-out', '止盈减仓比例'], unit: ['% of position', '持仓比例'], min: 10, max: 100, step: 5, scale: 100 },
      { key: 'exitProbabilityThreshold', label: ['Protective probability gate', '保护性概率门槛'], unit: ['%', '%'], min: 10, max: 49, step: 1, scale: 100 },
      { key: 'stopLossPct', label: ['Protective stop-loss gate', '保护性止损门槛'], unit: ['%', '%'], min: 15, max: 80, step: 5, scale: 100 },
      { key: 'emergencyStopLossPct', label: ['Emergency stop-loss gate', '紧急止损门槛'], unit: ['%', '%'], min: 10, max: 60, step: 5, scale: 100 },
    ];

    return <section className="kalshi-controls-section">
      <div className="kalshi-section-head">
        <div><span>{isRealMode ? copy('REAL RISK POLICY', '实盘风控策略') : copy('PAPER RISK POLICY', '模拟风控策略')}</span><h2>{isHourly ? copy('BTC hourly monotone ladder v2', 'BTC 整点单调阶梯策略 v2') : copy('BTC 15-minute settlement-aligned v7', 'BTC 15 分钟结算对齐策略 v7')}</h2></div>
        <div className="kalshi-apply-action">
          {applyMessage && <small>{applyMessage}</small>}
          <button type="button" onClick={() => void applyConfig()} disabled={applyBusy}><ThunderboltOutlined className={applyBusy ? 'is-spinning' : ''} />{applyBusy ? copy('Applying…', '正在应用…') : copy('Apply and evaluate', '应用并评估')}</button>
        </div>
      </div>
      <div className="kalshi-policy-note"><SafetyCertificateOutlined /><span><b>{copy('One transparent deterministic strategy.', '只保留一套透明的确定性策略。')}</b>{copy(' Data, liquidity, fee-adjusted edge and exposure are hard controls. Trend and book pressure are adaptive confirmations: disagreement raises the required edge instead of vetoing every trade.', ' 数据、流动性、扣费后边际和敞口属于硬风控；趋势与盘口压力属于自适应确认，出现分歧时会提高所需边际，而不是直接封死交易。')}</span></div>
      <div className="kalshi-control-grid">
        <label><span>{isRealMode ? copy('Real account equity', '实盘账户权益') : copy('Paper account equity', '模拟账户权益')}<small>{copy('USD', '美元')}</small></span><input type="number" value={Number.isFinite(modeEquity) ? modeEquity.toFixed(2) : config.paperBankroll} disabled readOnly /></label>
        {controls.map((control) => {
          const scale = control.scale || 1;
          return <label key={control.key}><span>{copy(control.label[0], control.label[1])}<small>{copy(control.unit[0], control.unit[1])}</small></span><input type="number" min={control.min} max={control.max} step={control.step} value={Number(config[control.key]) * scale} onChange={(event) => updateConfig(control.key, event.target.valueAsNumber, scale)} /></label>;
        })}
      </div>
      <div className="kalshi-policy-note"><SafetyCertificateOutlined /><span><b>{copy('No trade-count cap.', '不限制交易次数。')}</b>{copy(' Every order still needs positive fee-adjusted edge, fresh data, sufficient liquidity, and available exposure. Positions are held to settlement unless a fee-adjusted exit or protective exit is better.', ' 但每次下单仍须满足扣费后正边际、数据新鲜、流动性充足和敞口可用；仓位默认持有至结算，只有扣费后平仓更优或触发保护性退出时才离场。')}</span></div>
    </section>;
  };
  const renderDecisionLog = () => {
    const retainedDecisions: any[] = (robotState?.decisions?.length ? robotState.decisions : history) as any[];
    const item: any = retainedDecisions[0];
    const intent = String(item?.executionIntent || '');
    const decisionText = !item
      ? copy('WAIT', '等待')
      : `${intent.startsWith('CLOSE')
        ? copy('CLOSE', '平仓')
        : intent.startsWith('ADD')
          ? copy('ADD', '加仓')
          : intent.startsWith('HOLD')
            ? copy('HOLD', '持有')
            : item.action === 'WAIT'
              ? copy('WAIT', '等待')
              : copy('BUY', '买入')} ${item.side || ''}`;
    const reasonLabels: Record<string, string> = {
      contract_active: copy('Contract is not active', '合约当前不可交易'),
      entry_window: copy('Outside the permitted entry window', '不在允许进场时段'),
      data_freshness: copy('Market evidence is stale', '市场数据已过期'),
      history_sample: copy('Completed price history is insufficient, discontinuous or stale', '完整 K 线样本不足、不连续或已过期'),
      volatility_regime: copy('Volatility is outside the strategy range', '波动率超出策略范围'),
      model_market_agreement: copy('Model and market disagree too much', '模型与市场分歧过大'),
      model_probability: copy('Favorite-side confidence is below the floor', '优势侧模型胜率低于下限'),
      price_band: copy('Executable price is outside the favorite band', '可成交价不在优势侧价格区间'),
      book_pressure: copy('Order-book pressure is adverse', '盘口压力不利'),
      trend_confirmation: copy('Trend confirmation is insufficient', '趋势确认不足'),
      two_sided_quote: copy('No executable two-sided quote', '缺少可成交双边报价'),
      spread: copy('Spread is too wide', '点差过宽'),
      relative_spread: copy('Spread is too large relative to the contract price', '相对合约价格而言点差过宽'),
      depth: copy('Available depth is too low', '可成交深度不足'),
      net_edge: copy('Net edge is below the minimum', '净边际低于最低要求'),
      conservative_edge: copy('Conservative edge is below the minimum', '保守边际低于最低要求'),
      portfolio_exposure: copy('Portfolio exposure limit reached', '组合敞口已达上限'),
      market_exposure: copy('Single-market exposure limit reached', '单一市场敞口已达上限'),
      add_order_pending: copy('An add-on order is still pending', '加仓订单仍在处理中'),
      add_interval: copy('Minimum add-on interval has not elapsed', '尚未达到最短加仓间隔'),
      add_signal_not_improved: copy('The signal is not strong enough to add', '当前信号强度不足以加仓'),
      add_exposure_full: copy('No exposure room remains for an add-on', '当前没有可用的加仓敞口'),
      close_order_pending: copy('A close order is still pending', '平仓订单仍在处理中'),
      minimum_hold_period: copy('Minimum hold time has not elapsed', '尚未达到最短持仓时间'),
      protective_exit_confirmation: copy('Waiting for fresh protective-exit confirmations', '等待连续新数据确认保护性退出'),
      voluntary_exit_routing_economics: copy('This sale size and limit do not preserve net profit after fees', '按实际卖出数量和限价计算，扣费后尚不满足止盈条件'),
      kalshi_live_voluntary_exit_economics_changed: copy('Final sale economics changed; reevaluating the exit', '最终卖出成本已变化，正在重新评估退出'),
      kalshi_live_history_clock_unverified: copy('The price-history timestamps cannot be verified for Real trading', 'K 线时间戳未通过实盘校验'),
      account_snapshot_stale: copy('The scheduler-owned Real account snapshot is stale', '后台实盘账户快照已过期'),
      robot_scheduler_unhealthy: copy('The live robot scheduler is unhealthy', '实盘机器人调度器当前不健康'),
      ...Object.fromEntries(Object.entries(SHARD_FUNDING_BLOCKERS).map(([key, label]) => [key, copy(label[0], label[1])])),
    };
    const reasons = activeKalshiBlockingReasons(item?.blockingReasons)
      .map((reason: string) => reasonLabels[reason] || reason.replace(/_/g, ' '));
    return (
      <section className="kalshi-current-decision">
        <div className="kalshi-section-head"><div><span>{copy('DECISION AUDIT', '决策审计')}</span><h2>{copy('What the robot is doing now', '机器人现在在做什么')}</h2><small>{copy('Up to 250 compact decisions are retained per mode; orders and fills remain in their execution ledgers.', '每个模式最多保留 250 条精简决策；订单与成交长期保留在执行账本中。')}</small></div><strong>{retainedDecisions.length}</strong></div>
        {item ? <div className="kalshi-current-decision-grid">
          <article className={item.action === 'WAIT' ? 'is-waiting' : 'is-trading'}><span>{copy('DECISION', '当前决定')}</span><strong>{decisionText}</strong><small>{new Date(item.generatedAt).toLocaleString(chinese ? 'zh-CN' : 'en-US')}</small></article>
          <article><span>{copy('ORDER RESULT', '订单结果')}</span><strong>{item.orderFilled ? copy('FILLED', '已成交') : item.orderSubmitted ? copy('NOT FILLED', '未成交') : copy('NO ORDER', '未下单')}</strong><small>{item.fillCount ? `${copy('Quantity', '数量')} ${item.fillCount}` : kalshiModeLabel}</small></article>
          <article><span>{copy('MODEL / EXECUTABLE PRICE', '模型概率 / 可成交价')}</span><strong>{probability(item.fairProbability)} / {cents(item.price)}</strong><small>{copy('Probability compared with current cost', '模型概率与当前成本对比')}</small></article>
          <article><span>{copy('SIGNAL QUALITY', '信号质量')}</span><strong>{Math.round(Number(item.signalQuality || 0))}/100</strong><small>{reasons.length ? copy(`${reasons.length} controls blocked`, `${reasons.length} 项条件未通过`) : copy('All controls passed', '所有条件已通过')}</small></article>
        </div> : <div className="kalshi-empty-row">{copy('Waiting for the first complete market decision.', '正在等待第一条完整市场决策。')}</div>}
        {item && <div className="kalshi-decision-explanation"><b>{reasons.length ? copy('Why it is waiting', '为什么等待') : copy('Why it can trade', '为什么可以交易')}</b>{reasons.length ? <ul>{reasons.slice(0, 5).map((reason: string) => <li key={reason}>{reason}</li>)}</ul> : <p>{copy('The signal, executable price, liquidity and account limits all passed.', '信号、可成交价格、流动性和账户限制均已通过。')}</p>}</div>}
        {retainedDecisions.length > 1 && <div className="kalshi-decision-history">
          {retainedDecisions.slice(1, 13).map((row: any, index: number) => <div key={`${row.generatedAt}-${index}`}>
            <time>{row.generatedAt ? new Date(row.generatedAt).toLocaleTimeString(chinese ? 'zh-CN' : 'en-US') : '--'}</time>
            <b>{row.executionIntent || row.action || 'WAIT'}</b>
            <span>{row.ticker || '--'}</span>
            <span>{row.side || '--'} · {cents(row.price)}</span>
            <em>{probability(row.conservativeEdge)}</em>
            <small>{activeKalshiBlockingReasons(row.blockingReasons).length ? `${activeKalshiBlockingReasons(row.blockingReasons).length} ${copy('hard blocks', '项硬阻断')}` : row.orderFilled ? copy('FILLED', '已成交') : copy('CLEAR', '通过')}</small>
          </div>)}
        </div>}
      </section>
    );
  };

  const renderRules = () => (
    <section className="kalshi-reference-page">
      <div className="kalshi-reference-column"><span>01</span><h2>{copy('Resolution rule', '结算规则')}</h2><p>{rulesPrimary || copy('Waiting for the active contract rule.', '正在等待当前合约规则。')}</p></div>
      <div className="kalshi-reference-column"><span>02</span><h2>{copy('Reference methodology', '参考方法')}</h2><p>{rulesSecondary || copy('The official result is a 60-second average of the CF Benchmarks Real-Time Index over the final minute, not the last Coinbase trade.', '官方结果为结算前最后一分钟 CF Benchmarks 实时指数的 60 秒均价，而不是 Coinbase 最后一笔成交。')}</p></div>
      <div className="kalshi-reference-column"><span>03</span><h2>{copy('Model boundary', '模型边界')}</h2><p>{copy('The primary input is Kalshi\'s authenticated official BRTI stream. If it is unavailable, the engine clearly falls back to a four-venue proxy, raises its basis reserve, and keeps the stricter 50-cent price floor.', '模型主要使用 Kalshi 认证的官方 BRTI 实时流；若不可用，会明确回退到四交易所代理、提高基差缓冲，并保持更严格的 50 美分价格下限。')}</p></div>
    </section>
  );

  const renderPortfolio = () => {
    if (!paperPortfolio) {
      return <section className="kalshi-empty-workspace"><SafetyCertificateOutlined /><span>{kalshiModeLabel}</span><h2>{isRealMode ? copy('Your Kalshi account is loading.', '正在加载你的 Kalshi 账户。') : copy('The built-in Paper account is loading.', '内置 Paper 账户正在加载。')}</h2><p>{isRealMode ? copy('Real mode uses the API key saved in Settings.', '实盘模式使用设置里保存的 API Key。') : copy('No personal Kalshi API key is required.', '无需配置个人 Kalshi API Key。')}</p></section>;
    }
    const cash = Number(paperPortfolio.balance?.balance || 0) / 100;
    const portfolioMode = String(paperPortfolio.environment).toLowerCase() === 'real' ? 'real' : 'paper';
    const visibleLedger = visibleKalshiLedger(paperPortfolio);
    const portfolioWarnings = kalshiPortfolioWarnings(paperPortfolio);
    const visibleResetAtMs = visibleLedger.resetAt ? Date.parse(visibleLedger.resetAt) : Number.NaN;
    const visibleRealRecord = (record: Record<string, any>) => (
      portfolioMode !== 'real'
      || (
        visibleLedger.baselineReady
        && Number.isFinite(visibleResetAtMs)
        && (recordTimeMs(record) ?? Number.NEGATIVE_INFINITY) > visibleResetAtMs
      )
    );
    // Kalshi defines portfolio_value as the current value of positions only.
    // Total account equity is therefore cash balance plus portfolio value in
    // both Real and AlphaLab Paper environments.
    const accountEquity = kalshiAccountEquityDollars(paperPortfolio.balance);
    const analytics = paperPortfolio.analytics || {};
    const fallbackSettlementRecords = robotState?.strategy?.settlementRecords || [];
    const realizedRecords = (
      Array.isArray(analytics.realizedTradeRecords)
        ? analytics.realizedTradeRecords
        : robotState?.strategy?.realizedTradeRecords?.length
          ? robotState.strategy.realizedTradeRecords
          : analytics.settlementRecords?.length
            ? analytics.settlementRecords
            : fallbackSettlementRecords
    )
      .filter((record: any) => !record.environment || record.environment === portfolioMode)
      .filter(visibleRealRecord);
    const fallbackEquityCurve = robotState?.strategy?.equityCurve || [];
    const equityCurve = (Array.isArray(analytics.equityCurve) ? analytics.equityCurve : fallbackEquityCurve)
      .filter((point: any) => !point.environment || point.environment === portfolioMode)
      .filter(visibleRealRecord);
    const realizedSamples = portfolioMode === 'real'
      ? realizedRecords.length
      : analytics.realizedSamples ?? realizedRecords.length;
    const wins = portfolioMode === 'real'
      ? realizedRecords.filter((record) => record.pnl > 0).length
      : analytics.realizedWins ?? analytics.wins ?? realizedRecords.filter((record) => record.pnl > 0).length;
    const winRate = portfolioMode === 'real'
      ? (realizedSamples ? wins / realizedSamples : null)
      : analytics.realizedWinRate ?? analytics.winRate ?? (realizedSamples ? wins / realizedSamples : null);
    const totalPnl = portfolioMode === 'real'
      ? realizedRecords.reduce((sum, record) => sum + Number(record.pnl || 0), 0)
      : analytics.realizedTotalPnl ?? analytics.totalPnl ?? realizedRecords.reduce((sum, record) => sum + Number(record.pnl || 0), 0);
    const averagePnl = portfolioMode === 'real'
      ? (realizedSamples ? Number(totalPnl) / realizedSamples : 0)
      : analytics.realizedAveragePnl ?? analytics.averagePnl ?? (realizedSamples ? Number(totalPnl) / realizedSamples : 0);
    const positionRows = paperPortfolio.positions || [];
    const orderRows = visibleLedger.orders;
    const fillRows = visibleLedger.fills;
    const settlementRows = visibleLedger.settlements;
    const filledOrders = orderRows.filter((item: any) => Number(item.fill_count_fp || 0) > 0);
    const rejectedOrders = orderRows.filter((item: any) => String(item.status || '').toLowerCase() === 'rejected');
    const totalFees = orderRows.reduce((sum: number, item: any) => sum + Number(orderFee(item) || 0), 0);
    // Portfolio analytics ---------------------------------------------------
    const startingBalance = Number(paperPortfolio.balance?.starting_balance || 0) / 100;
    const displayBaseline = analytics.displayBaseline;
    const visiblePeriodActive = portfolioMode === 'real'
      ? visibleLedger.baselineReady
      : Boolean(displayBaseline?.active);
    const displayBaselineEquity = visiblePeriodActive
      ? Number(displayBaseline?.baselineEquityCents || 0) / 100
      : 0;
    const returnBase = displayBaselineEquity > 0
      ? displayBaselineEquity
      : portfolioMode === 'real' && !visiblePeriodActive
        ? 0
        : startingBalance;
    const unrealizedPnl = positionRows.reduce((sum: number, item: any) => sum + Number(item.unrealized_pnl_dollars || 0), 0);
    const openExposure = positionRows.reduce((sum: number, item: any) => sum + Number(item.market_exposure_dollars || 0), 0);
    const totalProfit = returnBase > 0 ? accountEquity - returnBase : null;
    const totalReturnPct = returnBase > 0 ? (accountEquity - returnBase) / returnBase : null;
    const pnlValues = realizedRecords.map((record: any) => Number(record.pnl || 0));
    const stability = deriveKalshiStabilityMetrics(
      portfolioMode === 'real' ? { records: realizedRecords } : analytics,
      realizedRecords,
    );
    const bestTrade = portfolioMode === 'real'
      ? (pnlValues.length ? Math.max(...pnlValues) : null)
      : analytics.realizedBestTrade ?? (pnlValues.length ? Math.max(...pnlValues) : null);
    const worstTrade = portfolioMode === 'real'
      ? (pnlValues.length ? Math.min(...pnlValues) : null)
      : analytics.realizedWorstTrade ?? (pnlValues.length ? Math.min(...pnlValues) : null);
    const losses = Math.max(0, realizedSamples - Number(wins || 0));
    const profitFactor = stability.profitFactor;
    const familyPerformance = (
      portfolioMode === 'real' && !visibleLedger.baselineReady
        ? {}
        : analytics.marketPerformance || {}
    ) as Record<string, any>;
    const portfolioCompletenessBanner = portfolioWarnings.length ? (
      <div className="kalshi-error" role="alert" data-testid="kalshi-portfolio-completeness-warning">
        <WarningOutlined />
        <span>
          <b>{copy('Kalshi returned partial account data', 'Kalshi 返回了不完整的账户数据')}</b>
          {portfolioWarnings.join(' · ')}
        </span>
      </div>
    ) : null;
    const realLedgerBanner = portfolioMode === 'real' ? (
      visibleLedger.baselineReady ? (
        <section className="kalshi-display-baseline" data-testid="kalshi-real-ledger-baseline">
          <DatabaseOutlined />
          <div>
            <span>{copy('ALPHALAB REAL LEDGER', 'ALPHALAB 实盘账本')}</span>
            <strong>{copy('Only AlphaLab-managed activity is shown', '仅显示由 AlphaLab 管理的活动')}</strong>
            <small>
              {copy('Execution records begin after', '执行记录起始于')} {visibleLedger.resetAt ? new Date(visibleLedger.resetAt).toLocaleString(chinese ? 'zh-CN' : 'en-US') : '--'}
              {' · '}
              {copy('Account balance and open positions still reflect the full Kalshi account.', '账户余额和未平仓持仓仍反映完整的 Kalshi 账户。')}
            </small>
          </div>
          <div><b>{orderRows.length}</b><span>{copy('visible AlphaLab orders', '笔可见 AlphaLab 订单')}</span></div>
        </section>
      ) : (
        <div className="kalshi-policy-note" role="status" data-testid="kalshi-real-ledger-baseline">
          <WarningOutlined />
          <span>
            <b>{copy('The AlphaLab Real execution ledger starts blank.', 'AlphaLab 实盘执行账本从空白开始。')}</b>
            {' '}
            {copy(
              'No real account history is attributed to AlphaLab until the backend establishes an AlphaLab-only baseline. Balance and open positions remain visible.',
              '在后端建立仅限 AlphaLab 的基线之前，不会把任何实盘账户历史归为 AlphaLab；账户余额和未平仓持仓仍会显示。',
            )}
          </span>
        </div>
      )
    ) : null;

    if (view === 'orders') {
      return (
        <>
          {portfolioCompletenessBanner}
          {realLedgerBanner}
          <section className="kalshi-execution-strip">
            <div><span>{copy('ORDER REQUESTS', '订单请求')}</span><strong>{orderRows.length}</strong><small>{portfolioMode === 'real' ? copy('AlphaLab visible-period ledger', 'AlphaLab 当前周期流水') : copy('Current account ledger', '当前账户流水')}</small></div>
            <div><span>{copy('FILLED', '已成交')}</span><strong>{filledOrders.length}</strong><small>{copy('Full or partial fills', '全部或部分成交')}</small></div>
            <div><span>{copy('REJECTED', '已拒绝')}</span><strong>{rejectedOrders.length}</strong><small>{copy('No position created', '未建立仓位')}</small></div>
            <div><span>{copy('REPORTED FEES', '已报告费用')}</span><strong>{money(totalFees)}</strong><small>{copy('Across displayed orders', '当前列表合计')}</small></div>
          </section>
          <section className="kalshi-ledger-section">
            <div className="kalshi-section-head"><div><span>{copy('EXECUTION LEDGER', '执行流水')}</span><h2>{copy('Orders and fills', '订单与成交')}</h2><small>{copy('IOC requests, fill quantity, executable prices, slippage and fees.', 'IOC 请求、成交数量、可成交价格、滑点与费用。')}</small></div><strong>{orderRows.length}</strong></div>
            <div className="kalshi-order-table">
              <div className="kalshi-order-head"><span>{copy('TIME', '时间')}</span><span>{copy('CONTRACT', '合约')}</span><span>{copy('ORDER', '订单')}</span><span>{copy('REQUEST / FILLED', '请求 / 成交')}</span><span>{copy('LIMIT / AVG', '限价 / 均价')}</span><span>{copy('SLIPPAGE / FEE', '滑点 / 费用')}</span><span>{copy('STATUS', '状态')}</span></div>
              {orderRows.length ? orderRows.map((item: any, index: number) => {
                const tradeAction = String(item.action || item.order_action || '').replace(/_/g, ' ').toUpperCase();
                const outcomeSide = String(item.outcome_side || '').toUpperCase();
                const orderLabel = [tradeAction, outcomeSide].filter(Boolean).join(' ') || '--';
                return (
                  <div className={`kalshi-order-row is-${String(item.status || 'unknown').replace(/_/g, '-')}`} key={item.order_id || `${item.ticker}-${index}`}>
                    <span>{item.created_time ? new Date(item.created_time).toLocaleTimeString(chinese ? 'zh-CN' : 'en-US') : '--'}</span>
                    <b>{item.ticker || '--'}</b>
                    <span>{orderLabel} · {String(item.time_in_force || 'IOC').toUpperCase()}</span>
                    <strong>{Number(item.count_fp || 0)} / {Number(item.fill_count_fp || 0)}</strong>
                    <span>{cents(orderSidePrice(item, 'limit'))} / {cents(orderSidePrice(item, 'average'))}</span>
                    <span>{item.slippage_dollars != null ? `${(Number(item.slippage_dollars) * 100).toFixed(1)}c` : Number(item.fill_count_fp || 0) > 0 ? '0.0c' : '--'} / {orderFee(item) == null ? '--' : money(orderFee(item))}</span>
                    <span><em>{String(item.status || '--').replace(/_/g, ' ')}</em>{item.rejection_reason ? <small>{item.rejection_reason}</small> : null}</span>
                  </div>
                );
              }) : <div className="kalshi-empty-row">{isRealMode ? copy('No baseline-qualified AlphaLab Real IOC orders are available yet.', '当前尚无符合基线条件的 AlphaLab 实盘 IOC 订单。') : copy('No Paper IOC orders have been submitted yet.', '尚无 Paper IOC 订单。')}</div>}
            </div>
          </section>
          <section className="kalshi-ledger-section">
            <div className="kalshi-section-head"><div><span>{copy('EXECUTION EVENTS', '执行事件')}</span><h2>{copy('Fills and settlements', '成交与结算')}</h2><small>{portfolioMode === 'real' ? copy('Baseline-qualified AlphaLab events for execution audit.', '用于执行审计、符合基线条件的 AlphaLab 事件。') : copy('Raw account events for execution audit.', '用于执行审计的原始账户事件。')}</small></div><strong>{fillRows.length + settlementRows.length}</strong></div>
            <div className="kalshi-activity-list">{[...fillRows.map((item) => ({ ...item, kind: 'FILL' })), ...settlementRows.map((item) => ({ ...item, kind: 'SETTLEMENT' }))].map((item: any, index) => {
              const eventTime = item.created_time || item.settled_time;
              return <div key={item.fill_id || item.settlement_id || `${item.ticker}-${index}`}><b className={item.kind === 'SETTLEMENT' ? 'is-settlement' : ''}>{item.kind}</b><strong>{item.ticker || item.market_ticker || '--'}</strong><span>{String(item.outcome_side || item.market_result || item.side || '--').toUpperCase()}</span><span>{item.count_fp || item.yes_count_fp || item.no_count_fp || '--'}</span><small>{eventTime ? new Date(eventTime).toLocaleString(chinese ? 'zh-CN' : 'en-US') : '--'}</small></div>;
            })}</div>
          </section>
        </>
      );
    }

    const returnClass = totalReturnPct === null ? '' : totalReturnPct >= 0 ? 'is-profit' : 'is-loss';
    return (
      <>
        {portfolioCompletenessBanner}
        {realLedgerBanner}
        {portfolioMode !== 'real' && visiblePeriodActive && <section className="kalshi-display-baseline" data-testid="kalshi-display-baseline">
          <DatabaseOutlined />
          <div>
            <span>{copy('VISIBLE PERIOD', '当前显示周期')}</span>
            <strong>{copy('New measurement period is active', '新的统计周期已启用')}</strong>
            <small>{copy('Visible P/L and results restart from', '可见盈亏与交易结果从')} {displayBaseline?.resetAt ? new Date(displayBaseline.resetAt).toLocaleString(chinese ? 'zh-CN' : 'en-US') : '--'} · {copy('The full execution ledger remains available in Orders.', '完整订单与成交历史仍保留在“订单”页面。')}</small>
          </div>
          <div><b>{displayBaseline?.archivedRealizedEvents || 0}</b><span>{copy('preserved prior events', '笔历史事件已保留')}</span></div>
        </section>}
        <section className="kalshi-family-performance">
          {([
            ['btc15m', copy('BTC 15-minute', 'BTC 15 分钟')],
            ['btchourly', copy('BTC hourly strikes', 'BTC 整点执行价')],
          ] as const).map(([family, label]) => {
            const performance = familyPerformance[family];
            const metrics = deriveKalshiStabilityMetrics(performance);
            const pnl = metrics.totalPnl;
            return (
              <article key={family} data-testid={`kalshi-stability-${family}`}>
                <header>
                  <span>{label}</span>
                  <strong className={pnl === null ? '' : pnl >= 0 ? 'is-profit' : 'is-loss'}>{pnl === null ? '--' : <>{pnl >= 0 ? '+' : ''}{money(pnl)}</>}</strong>
                  <small>{performance?.uniqueMarkets || 0} {copy('markets', '个市场')} · {metrics.samples} {copy('realized events', '笔已实现事件')} · {copy('win rate', '胜率')} {metrics.samples ? probability(metrics.wins / metrics.samples) : '--'}</small>
                </header>
                <dl>
                  <div><dt>{copy('AVG WIN', '平均盈利')}</dt><dd className="is-profit">{money(metrics.averageWin)}</dd></div>
                  <div><dt>{copy('AVG LOSS', '平均亏损')}</dt><dd className="is-loss">{metrics.averageLoss === null ? '--' : `-${money(metrics.averageLoss)}`}</dd></div>
                  <div><dt>{copy('PROFIT FACTOR', '收益因子')}</dt><dd>{ratio(metrics.profitFactor)}</dd></div>
                  <div><dt>{copy('MAX DRAWDOWN', '最大回撤')}</dt><dd>{metrics.maxDrawdown === null ? '--' : money(metrics.maxDrawdown)}</dd></div>
                  <div><dt>{copy('WORST TRADE', '最差单笔')}</dt><dd className="is-loss">{metrics.worstTrade === null ? '--' : money(metrics.worstTrade)}</dd></div>
                </dl>
                <div className={`kalshi-recovery-band${metrics.recoveryMultiple !== null && metrics.recoveryMultiple > 2 ? ' is-elevated' : ''}`}>
                  <span>{copy('LOSS RECOVERY', '亏损回补')}</span>
                  <strong>{metrics.recoveryMultiple === null
                    ? '--'
                    : copy(
                      `${ratio(metrics.recoveryMultiple)} average wins needed`,
                      `回本需 ${ratio(metrics.recoveryMultiple)} 次平均盈利`,
                    )}</strong>
                </div>
              </article>
            );
          })}
        </section>
        <section className="kalshi-account-strip">
          <div className="is-headline">
            <span>{copy('ACCOUNT EQUITY', '账户权益')}</span>
            <strong>{money(accountEquity)}</strong>
            <small>{totalReturnPct === null
              ? copy('Cash plus open-position value', '现金加未结持仓市值')
              : <>{visiblePeriodActive ? copy('Visible-period profit', '当前周期盈利') : copy('Total profit', '总盈利')} <em className={returnClass}>{Number(totalProfit) >= 0 ? '+' : ''}{money(Number(totalProfit))} · {totalReturnPct >= 0 ? '+' : ''}{(totalReturnPct * 100).toFixed(2)}%</em>{returnBase > 0 ? ` · ${copy('from', '起始资金')} ${money(returnBase)}` : ''}</>}</small>
          </div>
          <div><span>{isRealMode ? copy('REAL CASH', '实盘现金') : copy('PAPER CASH', '模拟现金')}</span><strong>{money(cash)}</strong><small>{copy('Available buying power', '可用购买力')}</small></div>
          <div><span>{copy('UNREALIZED P/L', '未实现盈亏')}</span><strong className={unrealizedPnl >= 0 ? 'is-profit' : 'is-loss'}>{unrealizedPnl >= 0 ? '+' : ''}{money(unrealizedPnl)}</strong><small>{positionRows.length} {copy('open · exposure', '持仓 · 敞口')} {money(openExposure)}</small></div>
          <div><span>{copy('REALIZED P/L', '已实现盈亏')}</span><strong className={Number(totalPnl) >= 0 ? 'is-profit' : 'is-loss'}>{Number(totalPnl) >= 0 ? '+' : ''}{money(totalPnl)}</strong><small>{copy('Net of fees · updated', '扣费后 · 更新于')} {new Date(paperPortfolio.asOf).toLocaleTimeString(chinese ? 'zh-CN' : 'en-US')}</small></div>
        </section>
        <section className="kalshi-performance-section">
          <div className="kalshi-performance-summary">
            <div><span>{copy('REALIZED EVENT WIN RATE', '已实现事件胜率')}</span><strong>{winRate === null ? '--' : probability(winRate)}</strong><small><em className="is-profit">{wins}{copy('W', ' 胜')}</em> · <em className="is-loss">{losses}{copy('L', ' 负')}</em> / {realizedSamples} {copy('events', '笔事件')}</small></div>
            <div><span>{copy('AVERAGE WIN / LOSS', '平均盈利 / 亏损')}</span><strong><em className="is-profit">{money(stability.averageWin)}</em> / <em className="is-loss">{stability.averageLoss === null ? '--' : `-${money(stability.averageLoss)}`}</em></strong><small>{copy('Average per realized event', '按已实现事件统计')} {averagePnl === null ? '--' : money(averagePnl)}</small></div>
            <div><span>{copy('LOSS RECOVERY', '亏损回补')}</span><strong className={stability.recoveryMultiple !== null && stability.recoveryMultiple > 2 ? 'is-loss' : ''}>{stability.recoveryMultiple === null ? '--' : `${ratio(stability.recoveryMultiple)}×`}</strong><small>{stability.recoveryMultiple === null ? copy('Needs both wins and losses', '需要同时积累盈利与亏损样本') : copy('Average wins needed after one average loss', `一次平均亏损需 ${ratio(stability.recoveryMultiple)} 次平均盈利回补`)}</small></div>
            <div><span>{copy('PROFIT FACTOR / DRAWDOWN', '收益因子 / 最大回撤')}</span><strong>{ratio(profitFactor)} / {money(stability.maxDrawdown)}</strong><small>{copy('Best / worst trade', '最佳 / 最差单笔')} <em className="is-profit">{money(bestTrade)}</em> / <em className="is-loss">{money(worstTrade)}</em></small></div>
          </div>
          <div className="kalshi-performance-chart">
            <div><span>{copy('CUMULATIVE REALIZED P/L', '累计已实现盈亏')}</span><small>{copy('Trade-by-trade realized account curve', '逐笔已实现交易账户曲线')}</small></div>
            <PnlChart points={equityCurve} label={copy('No realized trade curve is available yet.', '暂无已实现交易曲线。')} />
          </div>
        </section>
        <section className="kalshi-ledger-section">
          <div className="kalshi-section-head"><div><span>{copy('OPEN EXPOSURE', '当前敞口')}</span><h2>{copy('Positions and marked P/L', '持仓与盯市盈亏')}</h2><small>{kalshiModeLabel}</small></div><strong>{positionRows.length}</strong></div>
          <div className="kalshi-portfolio-table">
              <div className="kalshi-portfolio-head"><span>{copy('CONTRACT', '合约')}</span><span>{copy('SIDE / SIZE', '方向 / 数量')}</span><span>{copy('AVG ENTRY', '平均成本')}</span><span>{copy('MARK', '盯市价')}</span><span>{copy('VALUE / COST', '市值 / 成本')}</span><span>{copy('UNREALIZED / FEES', '浮盈亏 / 费用')}</span><span>{copy('UPDATED', '更新时间')}</span></div>
              {positionRows.length ? positionRows.map((item: any, index: number) => {
                const side = positionSideLabel(item);
                const avgEntry = side === 'NO' ? item.no_average_price_dollars : item.yes_average_price_dollars;
                const mark = side === 'NO' ? item.no_mark_dollars : item.yes_mark_dollars;
                const unrealized = Number(item.unrealized_pnl_dollars || 0);
                return (
                <div className="kalshi-portfolio-row" key={item.ticker || index}>
                  <b>{item.ticker || '--'}</b>
                  <span><em className={`kalshi-side-badge is-${side.toLowerCase()}`}>{side}</em> {Number(item.net_count_fp || 0)}</span>
                  <span>{cents(avgEntry)}</span>
                  <span>{cents(mark)}</span>
                  <span>{money(Number(item.market_value_dollars || 0))} / {money(Number(item.market_exposure_dollars || 0))}</span>
                  <span className={unrealized >= 0 ? 'is-profit' : 'is-loss'}>{unrealized >= 0 ? '+' : ''}{money(unrealized)} / {money(Number(item.fee_cost_dollars || 0))}</span>
                  <span>{item.last_trade_at ? new Date(item.last_trade_at).toLocaleTimeString(chinese ? 'zh-CN' : 'en-US') : '--'}</span>
                </div>
                );
              }) : <div className="kalshi-empty-row">{isRealMode ? copy('Your Kalshi account has no open positions yet.', '你的 Kalshi 账户当前没有持仓。') : copy('The Paper account has no open positions yet.', 'Paper 账户当前没有持仓。')}</div>}
          </div>
        </section>
        <section className="kalshi-ledger-section">
          <div className="kalshi-section-head"><div><span>{copy('REALIZED LEDGER', '已实现账本')}</span><h2>{copy('Realized trade outcomes', '已实现交易结果')}</h2><small>{visiblePeriodActive ? copy('Showing the current visible period; prior results remain preserved in the durable ledger.', '当前仅显示新周期；以前的结果仍完整保存在持久账本中。') : portfolioMode === 'real' ? copy('Waiting for the certified AlphaLab-only Real baseline.', '正在等待经过确认、仅限 AlphaLab 的实盘基线。') : copy('Every filled sale and final settlement is shown with net P/L.', '每笔成交卖出和最终结算均显示净收益。')}</small></div><strong>{realizedRecords.length}</strong></div>
          <div className="kalshi-settlement-table">
            <div className="kalshi-settlement-head"><span>{copy('SETTLED', '结算时间')}</span><span>{copy('CONTRACT', '合约')}</span><span>{copy('POSITION / RESULT', '方向 / 结果')}</span><span>{copy('BUY / EXIT', '买入 / 退出价')}</span><span>{copy('SIZE', '数量')}</span><span>{copy('COST / FEES', '成本 / 费用')}</span><span>{copy('REALIZED P/L', '已实现盈亏')}</span></div>
            {realizedRecords.length ? realizedRecords.map((record) => (
              <div className="kalshi-settlement-row" key={record.key}>
                <span>{record.settledAt ? new Date(record.settledAt).toLocaleString(chinese ? 'zh-CN' : 'en-US') : '--'}</span>
                <b>{record.ticker}</b>
                <span>
                  {record.side || '--'} → {record.exitType === 'sale' ? copy('SOLD', '卖出') : record.result || '--'}
                  {record.exitType === 'sale' && record.exitTrigger ? <small>{exitTriggerLabel(record.exitTrigger, chinese)}</small> : null}
                </span>
                <span><b>{cents(record.entryPrice ?? (Number(record.contracts || 0) > 0 ? Number(record.cost || 0) / Number(record.contracts) : null))}</b> → {cents(record.exitPrice ?? (record.side && record.result ? (record.side === record.result ? 1 : 0) : null))}<small>{record.exitType === 'sale' ? copy('sold', '卖出') : copy('settled', '结算')}</small></span>
                <span>{record.contracts || '--'}</span>
                <span>{money(record.cost)} / {money(record.fees)}</span>
                <strong className={record.pnl > 0 ? 'is-profit' : record.pnl < 0 ? 'is-loss' : ''}>{record.pnl > 0 ? '+' : ''}{money(record.pnl)}</strong>
              </div>
            )) : <div className="kalshi-empty-row">{copy('No realized trades are available yet.', '尚无已实现交易。')}</div>}
          </div>
        </section>
      </>
    );
  };

  const renderDiagnostics = () => {
    const familyKey: 'btc15m' | 'btchourly' = isHourly ? 'btchourly' : 'btc15m';
    const diagnostics = analytics?.analytics?.families?.[familyKey];
    const referenceFeed = analytics?.referenceFeed;
    const funnel = diagnostics?.funnel;
    const funnelSteps: Array<{ key: keyof KalshiFamilyDiagnostics['funnel']; en: string; zh: string }> = [
      { key: 'observations', en: 'Observed', zh: '已观察' },
      { key: 'dataReady', en: 'Fresh data', zh: '数据有效' },
      { key: 'entryWindow', en: 'Entry window', zh: '进场时窗' },
      { key: 'liquidityReady', en: 'Executable book', zh: '盘口可成交' },
      { key: 'positiveNetEdge', en: 'Positive net edge', zh: '扣费后正边际' },
      { key: 'positiveConservativeEdge', en: 'Conservative edge', zh: '保守边际为正' },
      { key: 'routable', en: 'Order candidate', zh: '可下单候选' },
      { key: 'orders', en: 'Order recorded', zh: '已记录订单' },
    ];
    const denominator = Math.max(1, Number(funnel?.observations || 0));
    const blockerLabels: Record<string, readonly [string, string]> = {
      conservative_edge: ['Conservative edge', '保守边际'],
      net_edge: ['Net edge after fees', '扣费后边际'],
      entry_window: ['Entry window', '进场时窗'],
      model_probability: ['Favorite confidence', '优势方向置信度'],
      depth: ['Executable depth', '可成交深度'],
      price_band: ['Contract price band', '合约价格区间'],
      spread: ['Absolute spread', '绝对点差'],
      relative_spread: ['Relative spread', '相对点差'],
      data_freshness: ['Data freshness', '数据新鲜度'],
      reference_ready: ['BRTI reference', 'BRTI 参考价'],
      robot_scheduler_unhealthy: ['Automation health', '自动化运行状态'],
      account_snapshot_stale: ['Account snapshot', '账户快照'],
      position_size: ['Risk-sized position', '风险仓位数量'],
      single_market_exposure: ['Single-market exposure', '单市场敞口'],
      portfolio_exposure: ['Portfolio exposure', '组合敞口'],
      ...SHARD_FUNDING_BLOCKERS,
    };
    const blockerName = (key: string) => {
      const label = blockerLabels[key];
      if (label) return copy(label[0], label[1]);
      return key.replace(/_/g, ' ');
    };
    const primaryReason = primaryKalshiNoTradeReason(diagnostics, decision);
    const primaryReasonDetails: Record<string, [string, string]> = {
      conservative_edge: [
        'The price does not leave enough expected return after fees and model uncertainty.',
        '当前价格扣除手续费并计入模型不确定性后，预期收益空间不足。',
      ],
      net_edge: [
        'The apparent probability advantage is consumed by executable price and fees.',
        '表面概率优势已被可成交价格和手续费消耗。',
      ],
      entry_window: [
        'The contract is outside the approved entry window; the strategy is waiting for its tested timing regime.',
        '合约尚未进入已验证的进场时窗，策略正在等待合适时段。',
      ],
      model_probability: [
        'The favored side is not yet reliable enough to justify its asymmetric loss.',
        '优势方向置信度尚不足以覆盖输掉合约时的不对称损失。',
      ],
      depth: [
        'Not enough contracts are executable at a price that preserves the required return.',
        '能够在不破坏预期收益的价格成交的合约数量不足。',
      ],
      price_band: [
        'The executable price is outside the strategy’s stable payoff range.',
        '可成交价格超出策略当前允许的稳定盈亏区间。',
      ],
      spread: ['The spread is too wide for a fee-adjusted entry.', '点差过宽，扣费后不适合进场。'],
      relative_spread: ['The spread is too large relative to the contract price.', '相对合约价格而言，点差过大。'],
      data_freshness: ['Market evidence is not fresh enough for a safe order.', '行情证据不够新鲜，暂不允许安全下单。'],
      reference_ready: ['The official BRTI reference is not ready.', '官方 BRTI 参考数据尚未就绪。'],
      robot_scheduler_unhealthy: ['The 24/7 scheduler is not healthy, so routing is blocked safely.', '24/7 调度器当前不健康，系统已安全阻止下单。'],
      account_snapshot_stale: ['Account buying power or exposure is stale.', '账户购买力或敞口快照已过期。'],
      position_size: ['The risk budget cannot support an economically valid contract size.', '当前风险预算不足以支持经济上合理的合约数量。'],
      single_market_exposure: ['This market has reached its exposure ceiling.', '该市场已经达到单市场敞口上限。'],
      portfolio_exposure: ['The Kalshi portfolio has reached its exposure ceiling.', 'Kalshi 组合已经达到总敞口上限。'],
      kalshi_live_shard_cash_insufficient: ['Cash on other exchanges cannot fund this contract; entries need collateral on the contract’s exchange.', '其他分片的现金不能用于该合约，开仓需要合约所属分片有足够资金。'],
      kalshi_live_shard_cash_unavailable: ['The contract’s exchange balance must be verified before opening a position.', '开仓前必须核实合约所属分片的可用余额。'],
    };
    const primaryDetail = primaryReason
      ? primaryReasonDetails[primaryReason.key]?.[chinese ? 1 : 0]
        || copy('The leading independent control did not pass.', '最主要的独立交易条件尚未通过。')
      : copy('No independent wait reason is available in this window.', '本时间窗尚无可确认的独立等待原因。');
    const plannedContracts = metricNumber(decision?.sizing || {}, ['plannedContracts', 'contracts']);
    const plannedMaxLoss = metricNumber(decision?.sizing || {}, ['maxLoss', 'maximumLoss']);
    const riskBudget = metricNumber(decision?.sizing || {}, ['riskBudget', 'scaledHardRiskBudget', 'hardRiskBudget']);
    const maxLossPct = number(decision?.sizing?.maxLossPct);
    const visibleNearMisses = (diagnostics?.nearMisses || [])
      .map((item) => ({
        ...item,
        blockingReasons: activeKalshiBlockingReasons(item.blockingReasons),
        primaryBlockingReason: primaryKalshiNoTradeReason(undefined, {
          action: 'WAIT',
          blockingReasons: activeKalshiBlockingReasons(item.blockingReasons),
        } as Partial<KalshiDecision>)?.key,
      }))
      .filter((item) => item.blockingReasons.length > 0);
    const officialNow = Boolean(decision?.dataQuality?.officialBrti || referenceFeed?.fresh);
    return (
      <section className="kalshi-diagnostics-section">
        <div className="kalshi-section-head">
          <div>
            <span>{copy('24H OPPORTUNITY AUDIT', '24 小时机会审计')}</span>
            <h2>{copy('Why the robot traded — or waited', '机器人为何交易或等待')}</h2>
            <small>{copy('Every server evaluation is stored durably and reduced to an auditable funnel.', '服务端每次评估都会持久保存，并汇总为可审计漏斗。')}</small>
          </div>
          <span className={`kalshi-source-health${officialNow ? ' is-live' : ''}`}>
            <i />
            <b>{officialNow ? copy('OFFICIAL BRTI LIVE', '官方 BRTI 实时') : copy('PROXY FALLBACK', '代理源回退')}</b>
            <small>{referenceFeed?.ageSeconds == null ? '--' : `${Number(referenceFeed.ageSeconds).toFixed(1)}s`}</small>
          </span>
        </div>
        <div className="kalshi-diagnostic-stats">
          <div><span>{copy('OBSERVATIONS', '评估次数')}</span><strong>{diagnostics?.observations?.toLocaleString() || '0'}</strong><small>{copy('durable server samples', '服务端持久样本')}</small></div>
          <div><span>{copy('MARKETS SCANNED', '扫描市场')}</span><strong>{diagnostics?.uniqueMarkets || 0}</strong><small>{isHourly ? copy('hourly strike contracts', '整点执行价合约') : copy('rolling 15-minute contracts', '滚动 15 分钟合约')}</small></div>
          <div><span>{copy('OFFICIAL FEED', '官方行情')}</span><strong>{diagnostics?.officialBrtiSamples || 0}</strong><small>{copy('BRTI-confirmed samples', 'BRTI 确认样本')}</small></div>
          <div><span>{copy('SNAPSHOT LATENCY', '快照延迟')}</span><strong>{diagnostics?.averageSnapshotLatencyMs == null ? '--' : `${Math.round(diagnostics.averageSnapshotLatencyMs)}ms`}</strong><small>{copy('market + reference acquisition', '市场与参考价获取')}</small></div>
        </div>
        <div className="kalshi-diagnostic-grid">
          <article className="kalshi-funnel-panel">
            <div className="kalshi-diagnostic-title"><span>{copy('OPPORTUNITY FUNNEL', '机会漏斗')}</span><small>{copy('Counts are independent gate passes, not a forced trade quota.', '统计为各门控独立通过数，不是强制交易配额。')}</small></div>
            <div className="kalshi-funnel-list">
              {funnelSteps.map((step) => {
                const value = Number(funnel?.[step.key] || 0);
                const width = Math.max(value > 0 ? 2 : 0, Math.min(100, value / denominator * 100));
                return <div key={step.key}><span>{copy(step.en, step.zh)}</span><i><b style={{ width: `${width}%` }} /></i><strong>{value}</strong></div>;
              })}
            </div>
          </article>
          <article className="kalshi-edge-panel">
            <div className="kalshi-diagnostic-title">
              <span>{copy('EDGE TIMELINE', '边际时间线')}</span>
              <small><i className="is-net" />{copy('Net', '净边际')}<i className="is-conservative" />{copy('Conservative', '保守边际')}</small>
            </div>
            <EdgeTimelineChart points={diagnostics?.edgeTimeline || []} emptyLabel={copy('Waiting for durable edge samples.', '正在等待持久化边际样本。')} />
          </article>
          <article className="kalshi-blocker-panel">
            <div className="kalshi-diagnostic-title"><span>{copy('PRIMARY NO-TRADE REASON', '今日未交易主因')}</span><small>{copy('Correlated gates are collapsed.', '重复关联门控已合并。')}</small></div>
            <div className="kalshi-primary-wait" data-testid="kalshi-primary-wait-reason">
              <WarningOutlined />
              <span>
                <small>{primaryReason?.source === 'current' ? copy('CURRENT DECISION', '当前决策') : copy('OBSERVATION WINDOW', '观察时间窗')}</small>
                <strong>{primaryReason ? blockerName(primaryReason.key) : '--'}</strong>
                <p>{primaryDetail}</p>
                {primaryReason?.count != null && <em>{primaryReason.count.toLocaleString()} {copy('affected observations', '次受影响评估')}</em>}
              </span>
            </div>
            <dl className="kalshi-live-risk-grid">
              <div><dt>{copy('PLANNED SIZE', '计划数量')}</dt><dd>{plannedContracts === null ? '--' : plannedContracts}</dd><small>{copy('current family', '当前市场类型')}</small></div>
              <div><dt>{copy('SINGLE-TRADE RISK', '单笔风险')}</dt><dd>{money(plannedMaxLoss)}</dd><small>{copy('planned maximum loss', '计划最大损失')}</small></div>
              <div><dt>{copy('RISK LIMIT', '风险上限')}</dt><dd>{money(riskBudget)}</dd><small>{maxLossPct === null ? copy('current risk budget', '当前风险预算') : `${maxLossPct.toFixed(2)}% ${copy('of equity', '账户权益')}`}</small></div>
            </dl>
          </article>
        </div>
        {!!visibleNearMisses.length && <div className="kalshi-near-miss-table">
          <div className="kalshi-near-miss-head"><span>{copy('NEAR-MISS TIME', '接近成交时间')}</span><span>{copy('CONTRACT', '合约')}</span><span>{copy('SIDE / PRICE', '方向 / 价格')}</span><span>{copy('NET / CONS. EDGE', '净 / 保守边际')}</span><span>{copy('PRIMARY REMAINING BLOCK', '主要剩余阻断')}</span></div>
          {visibleNearMisses.slice(0, 5).map((item: any, index) => <div className="kalshi-near-miss-row" key={`${item.at}-${item.ticker}-${index}`}>
            <time>{item.at ? new Date(item.at).toLocaleTimeString() : '--'}</time>
            <b>{item.ticker || '--'}</b>
            <span>{item.side || '--'} / {cents(item.price)}</span>
            <span>{probability(item.netEdge)} / {probability(item.conservativeEdge)}</span>
            <small>{item.primaryBlockingReason ? blockerName(item.primaryBlockingReason) : copy('None', '无')}</small>
          </div>)}
        </div>}
      </section>
    );
  };

  const renderStrategy = () => (
    <section className="kalshi-strategy-section">
      <div className="kalshi-section-head"><div><span>{copy('STRATEGY GOVERNANCE', '策略治理')}</span><h2>{isHourly ? copy('BTC Hourly Monotone Strike Ladder', 'BTC 整点单调执行价阶梯') : (robotState?.strategy?.name || 'BTC15 Settlement-Aligned v6')}</h2></div><strong>{isHourly ? 'v2' : `v${robotState?.strategy?.version || 6}`}</strong></div>
      <div className="kalshi-strategy-grid">
        <article><span>{copy('PHILOSOPHY', '策略理念')}</span><p>{robotState?.strategy?.philosophy || copy('Probability, edge, liquidity, and risk must agree before an order is allowed.', '概率、边际、流动性与风险必须同时通过后才允许下单。')}</p></article>
        <article><span>{copy('MODEL INPUTS', '模型输入')}</span><ul>{(robotState?.strategy?.components || []).map((component) => <li key={component}>{component}</li>)}</ul></article>
        <article><span>{copy('CONSERVATIVE ESTIMATE', '保守估计')}</span><strong>{probability(decision?.edge.conservativeProbability)}</strong><small>{decision?.side || '--'} · {copy('conservative edge', '保守边际')} {probability(decision?.edge.conservativeEdge)}</small></article>
        <article><span>{copy('LATEST CHANGE', '最近改动')}</span><p>{robotState?.strategy?.changes?.[0]?.summary || copy('No parameter changes recorded.', '尚无参数改动。')}</p><small>{robotState?.strategy?.changes?.[0]?.at ? new Date(robotState.strategy.changes[0].at).toLocaleString() : '--'}</small></article>
      </div>
    </section>
  );

  const renderData = () => (<>
    <section className="kalshi-source-grid">
      {[
        [copy('Contract and quotes', '合约与报价'), 'Kalshi Trade API v2', isHourly ? 'KXBTCD' : 'KXBTC15M'],
        [copy('Order book', '订单簿'), 'Kalshi batch orderbooks', copy('One batched request with a sub-second hot cache', '单次批量请求，并使用亚秒级热缓存')],
        [copy('Settlement authority', '结算依据'), 'CF Benchmarks Real-Time Index', copy('60-second average over the final minute before close', '结算前最后一分钟的 60 秒均价')],
        [copy('Live reference', '实时参考价'), 'Official BRTI WebSocket', copy('Authenticated one-second stream; four-venue proxy is failover only', '认证的一秒实时流；四交易所代理仅用于故障回退')],
      ].map(([title, source, detail]) => <div key={title}><DatabaseOutlined /><span>{title}</span><strong>{source}</strong><small>{detail}</small></div>)}
    </section>
    {renderDiagnostics()}
  </>);

  const renderConnection = () => (
    <section className="kalshi-connection-page">
      <div><span>{copy('PUBLIC MARKET DATA', '公开市场数据')}</span><strong className={error ? 'is-error' : 'is-ready'}>{error ? copy('DEGRADED', '异常') : copy('CONNECTED', '已连接')}</strong><small>{snapshot?.asOf ? new Date(snapshot.asOf).toLocaleString() : '--'}</small></div>
      <div>
        <span>{copy('PERSONAL ACCOUNT API', '个人账户 API')}</span>
        <strong className={accountStatus?.personalApiConfigured ? 'is-ready' : ''}>{accountStatus?.personalApiConfigured ? copy('CONFIGURED', '已配置') : copy('NOT CONFIGURED', '未配置')}</strong>
        <small>{accountStatus?.personalApiConfigured
          ? `${copy('Production credentials stored securely for signed account requests and Real orders', '生产凭证已安全保存，可用于签名账户请求和实盘下单')}`
          : copy('Not required for AlphaLab Paper', 'AlphaLab Paper 无需凭证')}</small>
        <button type="button" onClick={() => navigate('/settings/configuration#kalshi', { state: { returnTo: location.pathname } })}>{copy('Manage personal API', '管理个人 API')}</button>
      </div>
      <div><span>{copy('ORDER AUTHORITY', '下单权限')}</span><strong>{accountStatus?.personalApiConfigured ? copy('PAPER + REAL', '模拟 + 实盘') : copy('PAPER ONLY', '仅模拟')}</strong><small>{accountStatus?.personalApiConfigured ? copy('Real mode submits backend-signed IOC limit orders to Kalshi.', '实盘模式会向 Kalshi 提交后端签名的 IOC 限价单。') : copy('Add a production API key before enabling Real mode.', '启用实盘前请先添加生产 API Key。')}</small></div>
    </section>
  );

  const renderHourlyLadder = () => {
    const candidates = (snapshot?.candidateSummary || []).slice().sort(
      (left: any, right: any) => Number(left.strike || 0) - Number(right.strike || 0),
    );
    return (
      <section className="kalshi-hourly-ladder">
        <div className="kalshi-section-head">
          <div>
            <span>{copy('HOURLY STRIKE SCAN', '整点执行价扫描')}</span>
            <h2>{snapshot?.eventTicker || 'KXBTCD'}</h2>
            <small>{copy('Nearby contracts ranked after spread, fee, uncertainty and depth.', '附近合约按点差、手续费、不确定性和深度综合排序。')}</small>
          </div>
          <strong>{snapshot?.candidateCount || candidates.length} {copy('strikes', '个执行价')}</strong>
        </div>
        <div className="kalshi-hourly-grid">
          {candidates.slice(0, 9).map((item: any) => {
            const selected = item.ticker === decision?.market.ticker;
            const blocked = activeKalshiBlockingReasons(item.blockingReasons).length;
            return (
              <article key={item.ticker} className={selected ? 'is-selected' : ''}>
                <span>{money(item.strike, 0)}</span>
                <strong>{item.side || '--'} · {item.action === 'WAIT' ? copy('WAIT', '等待') : copy('READY', '可执行')}</strong>
                <small>{copy('Net', '净边际')} {probability(item.netEdge)} · {blocked} {copy('blocks', '项阻断')}</small>
              </article>
            );
          })}
        </div>
      </section>
    );
  };

  const renderBody = () => {
    if (view === 'rules') return renderRules();
    if (view === 'decisions') return renderDecisionLog();
    if (view === 'risk') return renderRiskControls();
    if (view === 'positions' || view === 'orders') return renderPortfolio();
    if (view === 'data') return renderData();
    if (view === 'connection') return renderConnection();
    if (view === 'bot') return <>{isHourly && renderHourlyLadder()}{renderStrategy()}{renderDecision()}{renderDiagnostics()}{renderGates()}</>;
    return <>{renderMetrics()}{isHourly && renderHourlyLadder()}{renderDecision()}{renderDiagnostics()}{renderGates()}{renderBook()}</>;
  };

  const pageMeta: Record<KalshiView, { eyebrow: string; title: string; description: string }> = {
    desk: { eyebrow: copy('KALSHI / LIVE MARKET', 'KALSHI / 实时市场'), title: copy('BTC 15-minute contract desk', 'BTC 15 分钟合约工作台'), description: copy('Live contract, executable order book, reference price and model evidence.', '实时合约、可成交订单簿、参考价格与模型证据。') },
    rules: { eyebrow: copy('KALSHI / METHODOLOGY', 'KALSHI / 结算方法'), title: copy('Contract rules and settlement', '合约规则与结算'), description: copy('The exact market question, BRTI settlement authority and model boundary.', '准确的市场问题、BRTI 结算依据与模型边界。') },
    bot: { eyebrow: copy('KALSHI / AUTOMATION', 'KALSHI / 自动化'), title: copy('BTC 15-minute robot monitor', 'BTC 15 分钟机器人监控'), description: copy('Current decision, position management, sizing and deterministic trade gates.', '当前决策、仓位管理、仓位大小与确定性交易门控。') },
    decisions: { eyebrow: copy('KALSHI / AUDIT', 'KALSHI / 审计'), title: copy('Decision audit log', '决策审计记录'), description: copy('The latest model decision, evidence, gate result and execution outcome.', '最近一次模型决策、证据、门控结果与执行结果。') },
    risk: { eyebrow: copy('KALSHI / GOVERNANCE', 'KALSHI / 策略治理'), title: copy('Strategy and risk controls', '策略与风控'), description: copy('Manage deterministic entry, add-on, exit and exposure limits.', '管理确定性的开仓、加仓、平仓与敞口限制。') },
    positions: { eyebrow: copy('KALSHI / PORTFOLIO', 'KALSHI / 组合'), title: copy('Portfolio overview', '投资组合总览'), description: copy('Account equity, open exposure, marked P/L and realized outcomes.', '账户权益、当前敞口、盯市盈亏与已实现结果。') },
    orders: { eyebrow: copy('KALSHI / EXECUTION', 'KALSHI / 执行'), title: copy('Order execution ledger', '订单执行流水'), description: copy('IOC requests, fills, executable prices, slippage, fees and rejects.', 'IOC 请求、成交、可成交价格、滑点、费用与拒单。') },
    data: { eyebrow: copy('KALSHI / DATA', 'KALSHI / 数据'), title: copy('Market data sources', '市场数据源'), description: copy('Contract, order-book, settlement and independent spot provenance.', '合约、订单簿、结算与独立现货的数据来源。') },
    connection: { eyebrow: copy('KALSHI / CONNECTION', 'KALSHI / 连接'), title: copy('Account connection', '账户连接'), description: copy('Public market data status and personal trading authorization.', '公开市场数据状态与个人交易授权。') },
  };
  const currentPage = isHourly && (view === 'desk' || view === 'bot')
    ? {
      eyebrow: copy('KALSHI / BTC HOURLY', 'KALSHI / BTC 整点市场'),
      title: view === 'bot' ? copy('BTC hourly strike robot', 'BTC 整点执行价机器人') : copy('BTC hourly strike ladder', 'BTC 整点执行价阶梯'),
      description: copy(
        'Scans the active hourly event across nearby strikes and routes only the strongest fee-adjusted favorite.',
        '扫描当前整点事件附近的执行价，只执行扣费后价值最高的优势方向。',
      ),
    }
    : pageMeta[view];
  const showRobotActions = view === 'desk' || view === 'bot';
  const showPortfolioRefresh = view === 'positions' || view === 'orders';
  const showSafetyBanner = view === 'bot' || view === 'risk';
  const showDecisionLoading = view === 'desk' || view === 'bot' || view === 'rules' || view === 'decisions';
  const requiresExplicitEnable = kalshiRequiresExplicitEnable(robotState, executionMode);

  return (
    <div className="kalshi-page">
      <header className="kalshi-command-header">
        <div>
          <span>{currentPage.eyebrow}</span>
          <h1>{currentPage.title}</h1>
          <p>{currentPage.description}</p>
        </div>
        {showRobotActions && <div className="kalshi-command-actions">
          <div className={`kalshi-monitor-state${robotState?.enabled ? ' is-on' : ''}${requiresExplicitEnable ? ' needs-enable' : ''}`}><i /><span>{robotState?.enabled ? copy('ROBOT ON', '机器人运行中') : requiresExplicitEnable ? copy('START REQUIRED', '需要重新启动') : copy('ROBOT OFF', '机器人已关闭')}</span><small>{requiresExplicitEnable ? copy('Real mode is selected but not armed', '已进入实盘，但自动交易尚未启用') : `${kalshiModeLabel} · ${copy('5-second server cycle', '服务端每 5 秒运行')}`}</small></div>
          <button type="button" className="is-secondary" onClick={() => void evaluate()} disabled={refreshing}><ReloadOutlined className={refreshing ? 'is-spinning' : ''} />{copy('Refresh', '刷新')}</button>
          <button type="button" className={robotState?.enabled ? 'is-stop' : 'is-start'} onClick={() => void toggleRobot()} disabled={robotBusy}>{robotState?.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}{robotState?.enabled ? copy('Stop robot', '停止机器人') : requiresExplicitEnable ? copy('Enable Real automation', '确认启用实盘自动交易') : copy('Start robot', '启动机器人')}</button>
        </div>}
        {showPortfolioRefresh && <div className="kalshi-command-actions">
          {view === 'positions' && <button type="button" className="is-secondary" data-testid="reset-portfolio-display" onClick={() => void resetPortfolioDisplay()} disabled={portfolioResetting || portfolioLoading}><DatabaseOutlined />{portfolioResetting ? copy('Resetting…', '重置中…') : copy('Reset visible period', '重置显示周期')}</button>}
          <button type="button" className="is-secondary" onClick={() => void loadPaperPortfolio()} disabled={portfolioLoading || portfolioResetting}><ReloadOutlined className={portfolioLoading ? 'is-spinning' : ''} />{portfolioLoading ? copy('Refreshing…', '刷新中…') : copy('Refresh account', '刷新账户')}</button>
        </div>}
      </header>
      <section className="kalshi-context-rail" aria-label={copy('Kalshi workspace status', 'Kalshi 工作区状态')}>
        <div><span>{copy('ENVIRONMENT', '运行环境')}</span><strong className={isRealMode ? 'is-real' : ''}>{kalshiModeLabel}</strong></div>
        <div><span>{copy('ACTIVE CONTRACT', '当前合约')}</span><strong>{decision?.market.ticker || 'KXBTC15M'}</strong></div>
        <div><span>{copy('TIME TO CLOSE', '距离关闭')}</span><strong>{countdown}</strong></div>
        <div><span>{copy('ENGINE', '策略引擎')}</span><strong>{isHourly ? copy('LADDER v2', '阶梯 v2') : copy('SETTLEMENT v6', '结算对齐 v6')}</strong></div>
        <div><span>{copy('AUTOMATION', '自动交易')}</span><strong className={robotState?.enabled ? 'is-on' : ''}>{robotState?.enabled ? copy('RUNNING', '运行中') : copy('STOPPED', '已停止')}</strong></div>
        <div><span>{copy('ACCOUNT SOURCE', '账户数据源')}</span><strong>{isRealMode ? 'KALSHI API' : 'ALPHALAB'}</strong></div>
      </section>

      {showRobotActions && <KalshiFundingNotice decision={decision} isRealMode={isRealMode} chinese={chinese} />}

      {requiresExplicitEnable && showRobotActions && (
        <div className="kalshi-rearm-banner" role="status" data-testid="kalshi-rearm-required">
          <WarningOutlined />
          <span>
            <b>{copy('Real mode is selected, but automation is still stopped.', '已切换到 Kalshi 实盘，但自动交易仍处于停止状态。')}</b>
            {copy(
              ' Mode switching never authorizes real-money orders. Review the account and risk settings, then use “Enable Real automation” above when you are ready.',
              ' 切换模式不会授权真实资金下单。请先核对账户和风控设置，准备好后再点击上方“确认启用实盘自动交易”。',
            )}
          </span>
        </div>
      )}

      {showSafetyBanner && <div className={`kalshi-safety-banner${isRealMode ? ' is-real' : ''}`}><SafetyCertificateOutlined /><span><b>{isRealMode ? copy('Kalshi Real mode.', 'Kalshi 实盘模式。') : copy('AlphaLab Paper mode.', 'AlphaLab 内置模拟盘。')}</b>{isRealMode ? copy(' Public market data is still used for evidence; orders are signed on the backend with your saved Kalshi API key and sent to your real Kalshi account.', ' 行情证据仍使用公开数据；订单会在后端用你保存的 Kalshi API Key 签名，并发送到你的真实 Kalshi 账户。') : copy(' Fills use production Kalshi public executable quotes and the official taker-fee schedule, but no order is sent to Kalshi and profitability is not guaranteed.', ' 成交使用 Kalshi 正式公开可成交报价和官方 taker 手续费规则，但不会向 Kalshi 发送订单，也不保证盈利。')}</span></div>}
      {showDecisionLoading && loading && !decision && <div className="kalshi-loading"><ClockCircleOutlined /><span>{copy('Loading Kalshi contract and BTC reference data...', '正在加载 Kalshi 合约与 BTC 参考数据……')}</span></div>}
      {error && <div className="kalshi-error" role="alert"><CloseCircleOutlined /><span><b>{copy('Data refresh failed', '数据刷新失败')}</b>{error}</span><button type="button" onClick={() => void evaluate()}>{copy('Retry', '重试')}</button></div>}
      {showPortfolioRefresh && portfolioError && <div className="kalshi-error" role="alert" data-testid="kalshi-portfolio-error"><CloseCircleOutlined /><span><b>{copy('Account data was blocked', '账户数据已被阻止')}</b>{portfolioError}</span><button type="button" onClick={() => void loadPaperPortfolio()} disabled={portfolioLoading}>{copy('Retry', '重试')}</button></div>}
      {!loading && renderBody()}
    </div>
  );
};

export default Kalshi;
