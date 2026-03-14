import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Row, Col, Statistic, Table, Tag, Divider, Button, Spin, Alert, Empty, Tabs } from 'antd';
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { backtraderAPI } from '../services/api';
import TradingChart from '../components/TradingChart';

// Helper functions (copied from Backtest.tsx)
const safeToFixed = (value: any, decimals: number = 2): string => {
  const num = safeNumber(value);
  if (isNaN(num)) return '0.00';
  return num.toFixed(decimals);
};

const safeNumber = (value: any): number => {
  if (value === null || value === undefined || value === '') return 0;
  const num = Number(value);
  return isNaN(num) ? 0 : num;
};

const formatCurrency = (value: number): string => {
  const safeValue = safeNumber(value);
  const absValue = Math.abs(safeValue);
  const sign = safeValue < 0 ? '-' : '';
  
  if (absValue >= 1000000) {
    return `${sign}$${(absValue / 1000000).toFixed(2)}M`;
  } else if (absValue >= 1000) {
    return `${sign}$${(absValue / 1000).toFixed(2)}K`;
  } else {
    return `${sign}$${absValue.toFixed(2)}`;
  }
};

const { TabPane } = Tabs;

interface BacktestResult {
  backtestId: string;
  status: 'running' | 'completed' | 'failed';
  results: {
    totalReturn: number;
    sharpeRatio: number;
    maxDrawdown: number;
    winRate: number;
    trades: number;
    annualizedReturn: number;
    profitLoss?: number;
    calmarRatio: number;
    avgReturnPerTrade?: number;
    avgWin?: number;
    avgLoss?: number;
    equityCurve?: Array<{ date: string; equity: number }>;
    volatility?: number;
    sortinoRatio?: number;
    profitFactor?: number;
    expectancy?: number;
    exposure?: number;
    chartData?: Array<{
      date: string;
      close: number;
      signal: number;
      sma20?: number;
      sma50?: number;
      volume?: number;
    }>;
  };
  parameters?: {
    strategy: string;
    symbols: string[];
    period: string;
    initialCapital: number;
    // 策略特定参数
    shortMaPeriod?: number;
    longMaPeriod?: number;
    rsiPeriod?: number;
    rsiOversold?: number;
    rsiOverbought?: number;
    macdFast?: number;
    macdSlow?: number;
    macdSignal?: number;
    startDate?: string;
    endDate?: string;
  };
  createdAt?: string;
}

const BacktestDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  
  const [loading, setLoading] = useState(true);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchBacktestDetail();
  }, [id]);

  const fetchBacktestDetail = async () => {
    if (!id) return;
    
    setLoading(true);
    setError(null);
    
    try {
      // First try to get from history
      const historyResponse = await backtraderAPI.getBacktestHistory();
      console.log('History API response:', historyResponse.data);
      console.log('Looking for backtestId:', id);
      
      if (historyResponse.data && Array.isArray(historyResponse.data)) {
        const history = historyResponse.data;
        console.log('History length:', history.length);
        console.log('History backtestIds:', history.map((item: any) => item.backtestId));
        
        const found = history.find((item: any) => item.backtestId === id);
        
        if (found) {
          console.log('Found backtest:', found.backtestId);
          setBacktestResult(found);
          setLoading(false);
          return;
        } else {
          console.log('Backtest not found in history');
        }
      } else {
        console.log('History data is not an array:', historyResponse.data);
      }
      
      // If not found in history, try to re-run with the ID
      // For now, we'll show an error since we don't have the original parameters
      setError('Backtest not found in history. Please run a new backtest from the main page.');
    } catch (err: any) {
      console.error('Error fetching backtest detail:', err);
      setError(err.message || 'Failed to load backtest details');
    } finally {
      setLoading(false);
    }
  };

  // Generate result data for table (reused from Backtest.tsx)
  const generateResultData = () => {
    if (!backtestResult?.results) return [];
    
    const { results, parameters } = backtestResult;
    
    return [
      { 
        key: 'totalReturn', 
        metric: 'Total Return', 
        value: safeNumber(results.totalReturn), 
        description: 'Total return over the period' 
      },
      { 
        key: 'annualizedReturn', 
        metric: 'Annualized Return', 
        value: safeNumber(results.annualizedReturn), 
        description: 'Annualized return (CAGR)' 
      },
      { 
        key: 'profitLoss', 
        metric: 'Profit / Loss', 
        value: safeNumber(results.profitLoss), 
        description: `Profit/Loss amount (from $${safeNumber(parameters?.initialCapital).toLocaleString()})` 
      },
      { 
        key: 'sharpeRatio', 
        metric: 'Sharpe Ratio', 
        value: safeNumber(results.sharpeRatio), 
        description: 'Risk-adjusted return (higher is better)' 
      },
      { 
        key: 'calmarRatio', 
        metric: 'Calmar Ratio', 
        value: safeNumber(results.calmarRatio), 
        description: 'Return vs max drawdown (higher is better)' 
      },
      { 
        key: 'maxDrawdown', 
        metric: 'Max Drawdown', 
        value: safeNumber(results.maxDrawdown), 
        description: 'Maximum loss from a peak' 
      },
      { 
        key: 'winRate', 
        metric: 'Win Rate', 
        value: safeNumber(results.winRate), 
        description: 'Percentage of winning trades' 
      },
      { 
        key: 'trades', 
        metric: 'Trades', 
        value: safeNumber(results.trades), 
        description: 'Total number of trades executed' 
      },
      { 
        key: 'avgReturnPerTrade', 
        metric: 'Avg Return per Trade', 
        value: safeNumber(results.avgReturnPerTrade), 
        description: 'Average return per trade (annualized)' 
      },
      { 
        key: 'volatility', 
        metric: 'Volatility', 
        value: safeNumber(results.volatility), 
        description: 'Annualized volatility of strategy returns' 
      },
      { 
        key: 'sortinoRatio', 
        metric: 'Sortino Ratio', 
        value: safeNumber(results.sortinoRatio), 
        description: 'Risk-adjusted return considering only downside volatility' 
      },
      { 
        key: 'profitFactor', 
        metric: 'Profit Factor', 
        value: safeNumber(results.profitFactor), 
        description: 'Gross profit divided by gross loss (higher is better)' 
      },
      { 
        key: 'expectancy', 
        metric: 'Expectancy', 
        value: safeNumber(results.expectancy), 
        description: 'Expected return per trade based on win rate and average win/loss' 
      },
      { 
        key: 'exposure', 
        metric: 'Exposure', 
        value: safeNumber(results.exposure), 
        description: 'Percentage of time the strategy held positions' 
      },
    ];
  };

  // Generate equity curve data
  const equityCurveData = backtestResult?.results?.equityCurve || [];

  // Result columns (reused from Backtest.tsx)
  const resultColumns = [
    {
      title: 'Metric',
      dataIndex: 'metric',
      key: 'metric',
      width: '200px',
    },
    {
      title: 'Value',
      dataIndex: 'value',
      key: 'value',
      render: (value: number, record: any) => {
        const safeValue = safeNumber(value);
        
        if (record.metric === 'Profit / Loss') {
          const color = safeValue >= 0 ? '#3f8600' : '#cf1322';
          const formatted = formatCurrency(safeValue);
          return <span style={{ color, fontWeight: 'bold' }}>{formatted}</span>;
        } else if (record.metric.includes('Return')) {
          const color = safeValue >= 0 ? '#3f8600' : '#cf1322';
          const prefix = record.metric.includes('$') ? '' : (safeValue >= 0 ? '+' : '');
          const suffix = record.metric.includes('$') ? '' : '%';
          return <span style={{ color, fontWeight: 'bold' }}>{prefix}{safeToFixed(safeValue, 2)}{suffix}</span>;
        } else if (record.metric === 'Expectancy') {
          const color = safeValue >= 0 ? '#3f8600' : '#cf1322';
          const prefix = safeValue >= 0 ? '+' : '';
          return <span style={{ color, fontWeight: 'bold' }}>{prefix}{safeToFixed(safeValue, 2)}%</span>;
        } else if (record.metric === 'Volatility') {
          const color = safeValue < 20 ? '#3f8600' : safeValue < 40 ? '#faad14' : '#cf1322';
          return <span style={{ color, fontWeight: 'bold' }}>{safeToFixed(safeValue, 2)}%</span>;
        } else if (record.metric === 'Exposure') {
          const color = safeValue > 80 ? '#3f8600' : safeValue > 50 ? '#faad14' : '#cf1322';
          return <span style={{ color, fontWeight: 'bold' }}>{safeToFixed(safeValue, 1)}%</span>;
        } else if (record.metric === 'Sharpe Ratio' || record.metric === 'Calmar Ratio' || record.metric === 'Sortino Ratio' || record.metric === 'Profit Factor') {
          const color = safeValue >= 1 ? '#3f8600' : safeValue >= 0 ? '#faad14' : '#cf1322';
          return <span style={{ color, fontWeight: 'bold' }}>{safeToFixed(safeValue, 2)}</span>;
        } else if (record.metric === 'Max Drawdown') {
          return <span style={{ color: '#cf1322', fontWeight: 'bold' }}>{safeToFixed(safeValue, 2)}%</span>;
        } else if (record.metric === 'Win Rate') {
          const color = safeValue >= 60 ? '#3f8600' : safeValue >= 40 ? '#faad14' : '#cf1322';
          return <span style={{ color, fontWeight: 'bold' }}>{safeToFixed(safeValue, 1)}%</span>;
        } else if (record.metric === 'Trades') {
          return <span style={{ fontWeight: 'bold' }}>{Math.round(safeValue)}</span>;
        }
        return safeToFixed(safeValue, 2);
      },
    },
    {
      title: 'Description',
      dataIndex: 'description',
      key: 'description',
    },
  ];

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: '16px', color: '#666' }}>Loading backtest details...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '24px' }}>
        <Alert
          message="Error"
          description={error}
          type="error"
          showIcon
          action={
            <Button type="primary" onClick={() => navigate('/backtest')}>
              Go to Backtest Page
            </Button>
          }
        />
      </div>
    );
  }

  if (!backtestResult) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <Empty
          description="Backtest not found"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
        <Button 
          type="primary" 
          onClick={() => navigate('/backtest')}
          style={{ marginTop: '16px' }}
        >
          Go to Backtest Page
        </Button>
      </div>
    );
  }

  const { parameters, createdAt } = backtestResult;
  const resultData = generateResultData();

  return (
    <div style={{ padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <Button 
          type="text" 
          icon={<ArrowLeftOutlined />} 
          onClick={() => navigate('/backtest')}
          style={{ marginBottom: '16px' }}
        >
          Back to Backtest
        </Button>
        
        <h1 style={{ marginBottom: '8px' }}>Backtest Details</h1>
        <div style={{ color: '#666', fontSize: '14px' }}>
          Backtest ID: {id} • {createdAt ? `Created: ${new Date(createdAt).toLocaleString()}` : 'No creation date'}
        </div>
      </div>

      {/* Top Summary Cards - Same as Backtest.tsx */}
      {backtestResult?.results && (
        <div style={{ marginBottom: '24px' }}>
          <Row gutter={[16, 16]}>
            <Col span={4}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <Statistic
                  title="Total Return"
                  value={backtestResult.results.totalReturn || 0}
                  precision={2}
                  suffix="%"
                  valueStyle={{
                    color: (backtestResult.results.totalReturn || 0) >= 0 ? '#3f8600' : '#cf1322',
                    fontWeight: 'bold'
                  }}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <Statistic
                  title="Sharpe Ratio"
                  value={backtestResult.results.sharpeRatio || 0}
                  precision={2}
                  valueStyle={{
                    color:
                      (backtestResult.results.sharpeRatio || 0) >= 1
                        ? '#3f8600'
                        : (backtestResult.results.sharpeRatio || 0) >= 0
                        ? '#fa8c16'
                        : '#cf1322',
                    fontWeight: 'bold'
                  }}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <Statistic
                  title="Max Drawdown"
                  value={backtestResult.results.maxDrawdown || 0}
                  precision={2}
                  suffix="%"
                  valueStyle={{
                    color: '#cf1322',
                    fontWeight: 'bold'
                  }}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <Statistic
                  title="Win Rate"
                  value={backtestResult.results.winRate || 0}
                  precision={1}
                  suffix="%"
                  valueStyle={{
                    color: (backtestResult.results.winRate || 0) >= 60 ? '#3f8600' : (backtestResult.results.winRate || 0) >= 40 ? '#fa8c16' : '#cf1322',
                    fontWeight: 'bold'
                  }}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <Statistic
                  title="Total Trades"
                  value={backtestResult.results.trades || 0}
                  valueStyle={{
                    color: '#1890ff',
                    fontWeight: 'bold'
                  }}
                />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <Statistic
                  title="Annualized Return"
                  value={backtestResult.results.annualizedReturn || 0}
                  precision={2}
                  suffix="%"
                  valueStyle={{
                    color: (backtestResult.results.annualizedReturn || 0) >= 0 ? '#3f8600' : '#cf1322',
                    fontWeight: 'bold'
                  }}
                />
              </Card>
            </Col>
          </Row>
        </div>
      )}

      {/* Tabs for detailed results - Same structure as Backtest.tsx */}
      <Card title="Backtest Results" style={{ marginTop: 16 }}>
        <Tabs defaultActiveKey="overview">
          {/* Overview Tab */}
          <TabPane tab="Overview" key="overview">
            <Table
              columns={resultColumns}
              dataSource={resultData}
              pagination={false}
              size="small"
              rowKey="key"
            />
          </TabPane>

          {/* Charts Tab */}
          <TabPane tab="Charts" key="charts">
            {/* Equity Curve Chart */}
            <Card title="Equity Curve" style={{ marginBottom: '24px' }}>
              {equityCurveData.length > 0 ? (
                <div>
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'flex-end', 
                    height: '200px',
                    borderBottom: '1px solid #e8e8e8',
                    marginBottom: '8px'
                  }}>
                    {equityCurveData.map((point, index) => {
                      const prices = equityCurveData.map((p) => p.equity);
                      const maxPrice = Math.max(...prices);
                      const minPrice = Math.min(...prices);
                      const range = maxPrice - minPrice;
                      const price = point.equity;
                      const heightPercent = range === 0 ? 50 : ((price - minPrice) / range) * 100;
                      
                      return (
                        <div
                          key={index}
                          style={{
                            width: '8%',
                            height: `${Math.max(heightPercent, 5)}%`,
                            backgroundColor: price >= equityCurveData[0].equity ? '#3f8600' : '#cf1322',
                            borderRadius: '2px',
                            position: 'relative'
                          }}
                          title={`${point.date}: $${safeToFixed(price, 2)}`}
                        />
                      );
                    })}
                  </div>
                  
                  <div style={{ 
                    display: 'flex', 
                    justifyContent: 'space-between',
                    fontSize: '12px',
                    color: '#666'
                  }}>
                    <span>{equityCurveData[0]?.date || 'Start'}</span>
                    <span>Equity Curve</span>
                    <span>{equityCurveData[equityCurveData.length - 1]?.date || 'End'}</span>
                  </div>
                </div>
              ) : (
                <Empty description="No equity curve data" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </Card>

            {/* Drawdown Chart */}
            <Card title="Drawdown Chart" style={{ marginBottom: '24px' }}>
              {equityCurveData.length > 0 ? (
                <div>
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'flex-start', 
                    height: '150px',
                    borderTop: '1px solid #e8e8e8',
                    position: 'relative'
                  }}>
                    {equityCurveData.map((point, index) => {
                      // Calculate drawdown
                      const prices = equityCurveData.slice(0, index + 1).map(p => p.equity);
                      const peak = Math.max(...prices);
                      const drawdown = ((peak - point.equity) / peak) * 100;
                      const maxDrawdown = Math.max(...equityCurveData.map((p, i) => {
                        const pricesToI = equityCurveData.slice(0, i + 1).map(p2 => p2.equity);
                        const peakToI = Math.max(...pricesToI);
                        return ((peakToI - p.equity) / peakToI) * 100;
                      }));
                      
                      const drawdownPercent = maxDrawdown === 0 ? 0 : (drawdown / maxDrawdown) * 100;
                      
                      return (
                        <div
                          key={index}
                          style={{
                            width: '8%',
                            height: `${Math.max(drawdownPercent, 2)}%`,
                            backgroundColor: '#cf1322',
                            borderRadius: '0 0 2px 2px',
                            position: 'relative'
                          }}
                          title={`${point.date}: ${safeToFixed(drawdown, 2)}% drawdown`}
                        />
                      );
                    })}
                  </div>
                  
                  <div style={{ 
                    display: 'flex', 
                    justifyContent: 'space-between',
                    fontSize: '12px',
                    color: '#666'
                  }}>
                    <span>{equityCurveData[0]?.date || 'Start'}</span>
                    <span>Drawdown</span>
                    <span>{equityCurveData[equityCurveData.length - 1]?.date || 'End'}</span>
                  </div>
                </div>
              ) : (
                <Empty description="No drawdown data" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </Card>

            {/* Trading Chart */}
            <Card title="Trading Chart" style={{ marginBottom: '24px' }}>
              {(() => {
                // 调试日志：检查数据结构
                console.log('=== Trading Chart Debug ===');
                console.log('backtestResult:', backtestResult);
                console.log('backtestResult?.parameters?.symbols:', backtestResult?.parameters?.symbols);
                console.log('symbols length:', backtestResult?.parameters?.symbols?.length);
                console.log('backtestResult?.results?.chartData:', backtestResult?.results?.chartData);
                console.log('chartData length:', backtestResult?.results?.chartData?.length);
                console.log('chartData first item:', backtestResult?.results?.chartData?.[0]);
                
                const symbols = backtestResult?.parameters?.symbols;
                const chartData = backtestResult?.results?.chartData;
                
                if (symbols && symbols.length > 1) {
                  // Portfolio 模式：不显示 Trading Chart
                  return (
                    <Empty 
                      description={
                        <div>
                          <div style={{ marginBottom: '8px', fontWeight: '500' }}>Trading Chart is not available in portfolio mode</div>
                          <div style={{ fontSize: '14px', color: '#666' }}>
                            Portfolio backtest includes multiple stocks ({symbols.join(', ')}).
                            <br />
                            Individual price charts are not available for portfolio analysis.
                          </div>
                        </div>
                      }
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      style={{ padding: '40px 0' }}
                    />
                  );
                } else if (chartData) {
                  // 单股票模式：显示 Trading Chart
                  console.log('Rendering TradingChart with data length:', chartData.length);
                  return (
                    <TradingChart
                      data={chartData}
                      height={400}
                      parameters={{
                        strategy: backtestResult?.parameters?.strategy,
                        symbol: symbols?.[0],
                        period: backtestResult?.parameters?.period,
                        initialCapital: backtestResult?.parameters?.initialCapital
                      }}
                    />
                  );
                } else {
                  // 单股票模式但没有 chartData
                  console.log('No chartData available for single stock mode');
                  return (
                    <Empty 
                      description="No chart data available" 
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      style={{ padding: '40px 0' }}
                    />
                  );
                }
              })()}
            </Card>
          </TabPane>

          {/* Trades Tab */}
          <TabPane tab="Trades" key="trades">
            <Card>
              <h4 style={{ marginBottom: '16px' }}>Trade Log</h4>
              {backtestResult?.results?.trades && backtestResult.results.trades > 0 ? (
                <>
                  {/* Trade Summary */}
                  <div style={{ marginBottom: '24px', padding: '16px', background: '#fafafa', borderRadius: '8px' }}>
                    <Row gutter={[16, 16]}>
                      <Col span={6}>
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Total Trades</div>
                          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#1890ff' }}>
                            {backtestResult.results.trades}
                          </div>
                        </div>
                      </Col>
                      <Col span={6}>
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Win Rate</div>
                          <div style={{ 
                            fontSize: '24px', 
                            fontWeight: 'bold', 
                            color: (backtestResult.results.winRate || 0) >= 60 ? '#3f8600' : (backtestResult.results.winRate || 0) >= 40 ? '#fa8c16' : '#cf1322'
                          }}>
                            {safeToFixed(backtestResult.results.winRate || 0, 1)}%
                          </div>
                        </div>
                      </Col>
                      <Col span={6}>
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Avg Win</div>
                          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#3f8600' }}>
                            ${safeToFixed(backtestResult.results.avgWin || 0, 0)}
                          </div>
                        </div>
                      </Col>
                      <Col span={6}>
                        <div style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Avg Loss</div>
                          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#cf1322' }}>
                            ${safeToFixed(backtestResult.results.avgLoss || 0, 0)}
                          </div>
                        </div>
                      </Col>
                    </Row>
                  </div>

                  {/* Trade Table Placeholder */}
                  <div style={{ 
                    textAlign: 'center', 
                    padding: '40px', 
                    background: '#fafafa',
                    borderRadius: '8px',
                    border: '1px dashed #d9d9d9'
                  }}>
                    <Empty
                      description={
                        <div>
                          <div style={{ marginBottom: '8px', fontWeight: '500' }}>Trade List Data</div>
                          <div style={{ fontSize: '14px', color: '#666' }}>
                            Detailed trade list is not available in historical backtest results.
                            <br />
                            Run a new backtest to see individual trade details.
                          </div>
                        </div>
                      }
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                    />
                  </div>
                </>
              ) : (
                <Empty
                  description="No trade data available"
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  style={{ padding: '40px 0' }}
                />
              )}
            </Card>
          </TabPane>

          {/* Parameters Tab */}
          <TabPane tab="Parameters" key="parameters">
            <Card>
              <Row gutter={[16, 16]}>
                <Col span={6}>
                  <div>
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Strategy</div>
                    <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters?.strategy || 'Unknown'}</div>
                  </div>
                </Col>
                <Col span={6}>
                  <div>
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Symbol</div>
                    <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters?.symbols?.join(', ') || 'Unknown'}</div>
                  </div>
                </Col>
                <Col span={6}>
                  <div>
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Period</div>
                    <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters?.period || 'N/A'}</div>
                  </div>
                </Col>
                <Col span={6}>
                  <div>
                    <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Initial Capital</div>
                    <div style={{ fontSize: '16px', fontWeight: 'bold' }}>${safeToFixed(parameters?.initialCapital || 0, 0)}</div>
                  </div>
                </Col>
              </Row>
              
              {/* Status Tag */}
              {backtestResult.status && (
                <div style={{ marginTop: '16px' }}>
                  <Tag color={backtestResult.status === 'completed' ? 'success' : backtestResult.status === 'running' ? 'processing' : 'error'}>
                    {backtestResult.status.toUpperCase()}
                  </Tag>
                </div>
              )}
              
              {/* Strategy Specific Parameters */}
              {parameters?.strategy === 'moving_average' && (
                <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #f0f0f0' }}>
                  <h4 style={{ marginBottom: '12px' }}>Moving Average Parameters</h4>
                  <Row gutter={[16, 16]}>
                    <Col span={6}>
                      <div>
                        <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Short MA Period</div>
                        <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters.shortMaPeriod || 20}</div>
                      </div>
                    </Col>
                    <Col span={6}>
                      <div>
                        <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Long MA Period</div>
                        <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters.longMaPeriod || 50}</div>
                      </div>
                    </Col>
                  </Row>
                </div>
              )}
              
              {parameters?.strategy === 'rsi' && (
                <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #f0f0f0' }}>
                  <h4 style={{ marginBottom: '12px' }}>RSI Parameters</h4>
                  <Row gutter={[16, 16]}>
                    <Col span={6}>
                      <div>
                        <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>RSI Period</div>
                        <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters.rsiPeriod || 14}</div>
                      </div>
                    </Col>
                    <Col span={6}>
                      <div>
                        <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Oversold Level</div>
                        <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters.rsiOversold || 30}</div>
                      </div>
                    </Col>
                    <Col span={6}>
                      <div>
                        <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Overbought Level</div>
                        <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters.rsiOverbought || 70}</div>
                      </div>
                    </Col>
                  </Row>
                </div>
              )}
              
              {parameters?.strategy === 'macd' && (
                <div style={{ marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #f0f0f0' }}>
                  <h4 style={{ marginBottom: '12px' }}>MACD Parameters</h4>
                  <Row gutter={[16, 16]}>
                    <Col span={6}>
                      <div>
                        <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Fast Period</div>
                        <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters.macdFast || 12}</div>
                      </div>
                    </Col>
                    <Col span={6}>
                      <div>
                        <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Slow Period</div>
                        <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters.macdSlow || 26}</div>
                      </div>
                    </Col>
                    <Col span={6}>
                      <div>
                        <div style={{ fontSize: '12px', color: '#666', marginBottom: '4px' }}>Signal Period</div>
                        <div style={{ fontSize: '16px', fontWeight: 'bold' }}>{parameters.macdSignal || 9}</div>
                      </div>
                    </Col>
                  </Row>
                </div>
              )}
            </Card>
          </TabPane>
        </Tabs>
      </Card>

      {/* Actions */}
      <div style={{ textAlign: 'center', marginTop: '24px' }}>
        <Button 
          type="primary" 
          icon={<ReloadOutlined />}
          onClick={fetchBacktestDetail}
          loading={loading}
        >
          Refresh
        </Button>
      </div>
    </div>
  );
};

export default BacktestDetail;