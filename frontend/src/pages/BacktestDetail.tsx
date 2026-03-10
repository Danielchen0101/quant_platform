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
    }>;
  };
  parameters: {
    strategy: string;
    symbols: string[];
    period: string;
    initialCapital: number;
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

      {/* Parameters Card */}
      <Card title="Parameters" style={{ marginBottom: '24px' }}>
        <Row gutter={[16, 16]}>
          <Col span={6}>
            <Statistic
              title="Strategy"
              value={parameters.strategy}
              valueStyle={{ fontSize: '16px', fontWeight: 'bold' }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="Symbol"
              value={parameters.symbols?.join(', ') || 'Unknown'}
              valueStyle={{ fontSize: '16px', fontWeight: 'bold' }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="Period"
              value={parameters.period}
              valueStyle={{ fontSize: '16px', fontWeight: 'bold' }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="Initial Capital"
              value={formatCurrency(parameters.initialCapital)}
              valueStyle={{ fontSize: '16px', fontWeight: 'bold', color: '#1890ff' }}
            />
          </Col>
        </Row>
        
        {backtestResult.status && (
          <div style={{ marginTop: '16px' }}>
            <Tag color={backtestResult.status === 'completed' ? 'success' : backtestResult.status === 'running' ? 'processing' : 'error'}>
              {backtestResult.status.toUpperCase()}
            </Tag>
          </div>
        )}
      </Card>

      {/* Results Tabs */}
      <Card title="Results" style={{ marginBottom: '24px' }}>
        <Tabs defaultActiveKey="results">
          <TabPane tab="Results Table" key="results">
            <Table
              columns={resultColumns}
              dataSource={resultData}
              pagination={false}
              size="small"
              style={{ marginBottom: '24px' }}
            />
          </TabPane>
          
          <TabPane tab="Trading Chart" key="chart">
            {backtestResult.results?.chartData ? (
              <TradingChart
                data={backtestResult.results.chartData}
                height={500}
              />
            ) : (
              <Empty 
                description="No chart data available" 
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                style={{ padding: '40px 0' }}
              />
            )}
          </TabPane>
        </Tabs>
      </Card>

      {/* Equity Curve */}
      <Card title="Equity Curve" style={{ marginBottom: '24px' }}>
        {equityCurveData.length > 0 ? (
          <div style={{ 
            height: '150px', 
            background: '#fafafa',
            borderRadius: '8px',
            padding: '16px',
            position: 'relative'
          }}>
            <div style={{ 
              display: 'flex', 
              alignItems: 'flex-end', 
              height: '100px',
              justifyContent: 'space-between',
              marginBottom: '8px'
            }}>
              {equityCurveData.map((point, index) => {
                const prices = equityCurveData.map(p => p.equity);
                const maxPrice = Math.max(...prices);
                const minPrice = Math.min(...prices);
                const price = point.equity;
                const heightPercent = ((price - minPrice) / (maxPrice - minPrice)) * 100;
                
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