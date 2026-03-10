import React, { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Card, Table, Tag, Button, Spin, Alert, Empty, Row, Col, Statistic, Divider } from 'antd';
import { ArrowLeftOutlined, LineChartOutlined } from '@ant-design/icons';
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
  const sign = safeValue < 0 ? '-' : '+';
  
  if (absValue >= 1000000) {
    return `${sign}$${(absValue / 1000000).toFixed(2)}M`;
  } else if (absValue >= 1000) {
    return `${sign}$${(absValue / 1000).toFixed(2)}K`;
  } else {
    return `${sign}$${absValue.toFixed(2)}`;
  }
};

const formatPercent = (value: number): string => {
  const safeValue = safeNumber(value);
  const sign = safeValue >= 0 ? '+' : '';
  return `${sign}${safeValue.toFixed(2)}%`;
};

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

const StrategyComparison: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  
  const [loading, setLoading] = useState(true);
  const [backtestResults, setBacktestResults] = useState<BacktestResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Get backtest IDs from URL query parameter
  const queryParams = new URLSearchParams(location.search);
  const backtestIds = queryParams.get('ids')?.split(',') || [];

  useEffect(() => {
    if (backtestIds.length > 0) {
      fetchBacktestResults();
    } else {
      setError('No backtests selected for comparison');
      setLoading(false);
    }
  }, [location.search]);

  const fetchBacktestResults = async () => {
    setLoading(true);
    setError(null);
    
    try {
      // Get all backtests from history
      const historyResponse = await backtraderAPI.getBacktestHistory();
      if (historyResponse.data && Array.isArray(historyResponse.data)) {
        const history = historyResponse.data;
        
        // Filter to only selected backtests
        const selectedResults = history.filter((item: any) => 
          backtestIds.includes(item.backtestId)
        );
        
        if (selectedResults.length === 0) {
          setError('No matching backtests found in history');
        } else {
          setBacktestResults(selectedResults);
          
          // DEBUG: Print equity curve information
          console.log('=== DEBUG: Compare Page Equity Curve Data ===');
          selectedResults.forEach((result: any, index: number) => {
            console.log(`Backtest ${index + 1}:`);
            console.log(`  backtestId: ${result.backtestId}`);
            console.log(`  symbol: ${result.parameters?.symbols?.join(', ')}`);
            console.log(`  equityCurve length: ${result.results?.equityCurve?.length || 0}`);
            
            if (result.results?.equityCurve && result.results.equityCurve.length > 0) {
              const firstPoint = result.results.equityCurve[0];
              const lastPoint = result.results.equityCurve[result.results.equityCurve.length - 1];
              console.log(`  first point: date=${firstPoint.date}, equity=${firstPoint.equity}`);
              console.log(`  last point: date=${lastPoint.date}, equity=${lastPoint.equity}`);
              
              // Check if it's old data (10 points) or new data (250 points)
              const pointCount = result.results.equityCurve.length;
              if (pointCount <= 15) {
                console.log(`  ⚠️ WARNING: Only ${pointCount} points - likely OLD sampled data (10 points)`);
              } else if (pointCount >= 200) {
                console.log(`  ✅ GOOD: ${pointCount} points - likely NEW full daily data`);
              } else {
                console.log(`  ℹ️ INFO: ${pointCount} points - intermediate amount`);
              }
            } else {
              console.log(`  ❌ ERROR: No equity curve data`);
            }
            console.log('---');
          });
          console.log('=== END DEBUG ===');
        }
      } else {
        setError('Failed to load backtest history');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load backtest results');
    } finally {
      setLoading(false);
    }
  };

  // Generate comparison data for parameters table
  const parameterColumns = [
    {
      title: 'Parameter',
      dataIndex: 'parameter',
      key: 'parameter',
      width: 150,
    },
    ...backtestResults.map((result, index) => ({
      title: `Backtest ${index + 1}`,
      dataIndex: `value${index}`,
      key: `value${index}`,
      render: (value: any) => {
        if (typeof value === 'number') {
          if (result.parameters.initialCapital === value) {
            return formatCurrency(value);
          }
          return safeToFixed(value, 2);
        }
        return value || 'N/A';
      },
    })),
  ];

  const parameterData = [
    {
      key: 'symbol',
      parameter: 'Symbol',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.parameters.symbols?.join(', ') || 'Unknown'
      }), {})
    },
    {
      key: 'strategy',
      parameter: 'Strategy',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.parameters.strategy || 'Unknown'
      }), {})
    },
    {
      key: 'period',
      parameter: 'Period',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.parameters.period || 'Unknown'
      }), {})
    },
    {
      key: 'initialCapital',
      parameter: 'Initial Capital',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.parameters.initialCapital || 0
      }), {})
    },
    {
      key: 'status',
      parameter: 'Status',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: (
          <Tag color={result.status === 'completed' ? 'success' : result.status === 'running' ? 'processing' : 'error'}>
            {result.status.toUpperCase()}
          </Tag>
        )
      }), {})
    },
  ];

  // Generate comparison data for metrics table
  const metricColumns = [
    {
      title: 'Metric',
      dataIndex: 'metric',
      key: 'metric',
      width: 180,
    },
    ...backtestResults.map((result, index) => ({
      title: `Backtest ${index + 1}`,
      dataIndex: `value${index}`,
      key: `value${index}`,
      render: (value: number, record: any) => {
        const safeValue = safeNumber(value);
        
        if (record.metric === 'Profit / Loss') {
          const color = safeValue >= 0 ? '#3f8600' : '#cf1322';
          const formatted = formatCurrency(safeValue);
          return <span style={{ color, fontWeight: 'bold' }}>{formatted}</span>;
        } else if (record.metric.includes('Return') || record.metric === 'Expectancy' || 
                   record.metric === 'Volatility' || record.metric === 'Exposure' || 
                   record.metric === 'Win Rate') {
          const color = safeValue >= 0 ? '#3f8600' : '#cf1322';
          const prefix = record.metric.includes('$') ? '' : (safeValue >= 0 ? '+' : '');
          const suffix = record.metric.includes('$') ? '' : '%';
          return <span style={{ color, fontWeight: 'bold' }}>{prefix}{safeToFixed(safeValue, 2)}{suffix}</span>;
        } else if (record.metric === 'Max Drawdown') {
          // Max Drawdown 越小越好：>-20%绿色，-20%~-40%橙色，<-40%红色
          let color = '#cf1322'; // 默认红色
          if (safeValue > -20) {
            color = '#3f8600'; // 绿色
          } else if (safeValue >= -40) {
            color = '#fa8c16'; // 橙色
          }
          return <span style={{ color, fontWeight: 'bold' }}>{safeToFixed(safeValue, 2)}%</span>;
        } else if (record.metric === 'Sharpe Ratio' || record.metric === 'Calmar Ratio' || 
                   record.metric === 'Sortino Ratio' || record.metric === 'Profit Factor') {
          const color = safeValue >= 1 ? '#3f8600' : safeValue >= 0 ? '#faad14' : '#cf1322';
          return <span style={{ color, fontWeight: 'bold' }}>{safeToFixed(safeValue, 2)}</span>;
        } else if (record.metric === 'Trades') {
          return <span style={{ fontWeight: 'bold' }}>{Math.round(safeValue)}</span>;
        }
        return safeToFixed(safeValue, 2);
      },
    })),
  ];

  const metricData = [
    {
      key: 'totalReturn',
      metric: 'Total Return',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.totalReturn || 0
      }), {})
    },
    {
      key: 'annualizedReturn',
      metric: 'Annualized Return',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.annualizedReturn || 0
      }), {})
    },
    {
      key: 'profitLoss',
      metric: 'Profit / Loss',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.profitLoss || 0
      }), {})
    },
    {
      key: 'sharpeRatio',
      metric: 'Sharpe Ratio',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.sharpeRatio || 0
      }), {})
    },
    {
      key: 'sortinoRatio',
      metric: 'Sortino Ratio',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.sortinoRatio || 0
      }), {})
    },
    {
      key: 'maxDrawdown',
      metric: 'Max Drawdown',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.maxDrawdown || 0
      }), {})
    },
    {
      key: 'volatility',
      metric: 'Volatility',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.volatility || 0
      }), {})
    },
    {
      key: 'winRate',
      metric: 'Win Rate',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.winRate || 0
      }), {})
    },
    {
      key: 'trades',
      metric: 'Trades',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.trades || 0
      }), {})
    },
    {
      key: 'profitFactor',
      metric: 'Profit Factor',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.profitFactor || 0
      }), {})
    },
    {
      key: 'expectancy',
      metric: 'Expectancy',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.expectancy || 0
      }), {})
    },
    {
      key: 'exposure',
      metric: 'Exposure',
      ...backtestResults.reduce((acc, result, index) => ({
        ...acc,
        [`value${index}`]: result.results?.exposure || 0
      }), {})
    },
  ];

  // Prepare equity curve data for comparison chart
  const prepareEquityCurveData = () => {
    if (backtestResults.length === 0) return [];
    
    const colors = ['#1890ff', '#52c41a', '#fa8c16', '#f5222d', '#722ed1', '#13c2c2'];
    
    // Filter out backtests without equity curve data
    const validBacktests = backtestResults.filter(result => 
      result.results?.equityCurve && result.results.equityCurve.length > 0
    );
    
    return validBacktests.map((result, index) => {
      const equityCurve = result.results?.equityCurve || [];
      const strategyName = result.parameters.strategy || `Strategy ${index + 1}`;
      const symbol = result.parameters.symbols?.[0] || 'Unknown';
      const initialCapital = result.parameters.initialCapital || 100000;
      
      // Normalize equity curve to percentage return (relative to initial capital)
      const normalizedData = equityCurve.map(point => ({
        date: point.date,
        equity: ((point.equity - initialCapital) / initialCapital * 100) + 100, // 100% = initial capital
        rawEquity: point.equity,
      }));
      
      // Create unique legend name
      const backtestIdShort = result.backtestId ? result.backtestId.slice(-8) : `#${index + 1}`;
      const createdAt = result.createdAt ? new Date(result.createdAt).toLocaleDateString() : '';
      const legendName = `${strategyName} (${symbol}) - ${backtestIdShort}${createdAt ? ` - ${createdAt}` : ''}`;
      
      return {
        name: legendName,
        data: normalizedData,
        color: colors[index % colors.length],
        initialCapital,
        backtestId: result.backtestId,
      };
    });
  };

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: '16px', color: '#666' }}>Loading comparison data...</div>
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

  if (backtestResults.length === 0) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <Empty
          description="No backtest results to compare"
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

  const equityCurveData = prepareEquityCurveData();
  
  // Calculate global max/min for normalized equity values
  const allNormalizedEquityValues = equityCurveData.flatMap(curve =>
    curve.data.map(point => point.equity)
  );
  
  const maxNormalizedEquity = allNormalizedEquityValues.length > 0 ? Math.max(...allNormalizedEquityValues) : 100;
  const minNormalizedEquity = allNormalizedEquityValues.length > 0 ? Math.min(...allNormalizedEquityValues) : 100;
  
  // Calculate global min and max dates across ALL equity curves
  const allDates = equityCurveData.flatMap(curve =>
    curve.data.map(point => new Date(point.date).getTime())
  );
  
  const globalMinDate = allDates.length > 0 ? Math.min(...allDates) : Date.now();
  const globalMaxDate = allDates.length > 0 ? Math.max(...allDates) : Date.now();
  const globalDateRange = globalMaxDate - globalMinDate;

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
        
        <h1 style={{ marginBottom: '8px' }}>Strategy Comparison</h1>
        <div style={{ color: '#666', fontSize: '14px' }}>
          Comparing {backtestResults.length} backtest{backtestResults.length > 1 ? 's' : ''}
        </div>
      </div>

      {/* Summary Stats */}
      <Row gutter={[16, 16]} style={{ marginBottom: '24px' }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="Backtests Compared"
              value={backtestResults.length}
              valueStyle={{ color: '#1890ff', fontSize: '24px' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Strategies"
              value={Array.from(new Set(backtestResults.map(r => r.parameters.strategy))).length}
              valueStyle={{ color: '#52c41a', fontSize: '24px' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Symbols"
              value={Array.from(new Set(backtestResults.flatMap(r => r.parameters.symbols))).length}
              valueStyle={{ color: '#fa8c16', fontSize: '24px' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Avg Return"
              value={backtestResults.reduce((sum, r) => sum + safeNumber(r.results?.totalReturn), 0) / backtestResults.length}
              formatter={(value) => formatPercent(value as number)}
              valueStyle={{ color: '#f5222d', fontSize: '24px' }}
            />
          </Card>
        </Col>
      </Row>

      {/* Parameters Comparison */}
      <Card title="Parameters Comparison" style={{ marginBottom: '24px' }}>
        <Table
          columns={parameterColumns}
          dataSource={parameterData}
          pagination={false}
          size="small"
          bordered
        />
      </Card>

      {/* Metrics Comparison */}
      <Card title="Performance Metrics Comparison" style={{ marginBottom: '24px' }}>
        <Table
          columns={metricColumns}
          dataSource={metricData}
          pagination={false}
          size="small"
          bordered
        />
      </Card>

      {/* Equity Curve Comparison */}
      <Card 
        title={
          <span>
            <LineChartOutlined style={{ marginRight: '8px' }} />
            Equity Curve Comparison (Normalized to 100% = Initial Capital)
          </span>
        }
        style={{ marginBottom: '24px' }}
      >
        {equityCurveData.length > 0 ? (
          <div style={{ 
            height: '500px', 
            background: '#fafafa',
            borderRadius: '8px',
            padding: '16px',
            position: 'relative'
          }}>
            {/* X-axis (time) */}
            <div style={{ 
              height: '350px', 
              position: 'relative',
              borderBottom: '1px solid #e8e8e8',
              borderLeft: '1px solid #e8e8e8',
              marginBottom: '16px',
              marginLeft: '40px'
            }}>
              {/* Main SVG container for all curves */}
              <svg
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  height: '100%',
                  overflow: 'visible'
                }}
                viewBox="0 0 1000 300"  // Fixed coordinate system: 1000 units wide, 300 units tall
                preserveAspectRatio="none"  // Stretch to fill container
              >
                {/* Grid lines for better readability */}
                {/* Horizontal grid lines */}
                {[0, 60, 120, 180, 240, 300].map((y, index) => (
                  <line
                    key={`h-grid-${index}`}
                    x1="0"
                    y1={y}
                    x2="1000"
                    y2={y}
                    stroke="#e8e8e8"
                    strokeWidth="0.5"
                    strokeDasharray="2,2"
                  />
                ))}
                {/* Vertical grid lines (every 100 units) */}
                {[0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000].map((x, index) => (
                  <line
                    key={`v-grid-${index}`}
                    x1={x}
                    y1="0"
                    x2={x}
                    y2="300"
                    stroke="#e8e8e8"
                    strokeWidth="0.5"
                    strokeDasharray="2,2"
                  />
                ))}
                {/* Draw each equity curve */}
                {equityCurveData.map((curve, curveIndex) => {
                  const points = curve.data;
                  if (points.length === 0) return null;
                  
                  // Find min and max equity values for this curve (normalized)
                  const equities = points.map(p => p.equity);
                  const curveMinEquity = Math.min(...equities);
                  const curveMaxEquity = Math.max(...equities);
                  const equityRange = curveMaxEquity - curveMinEquity;
                  
                  // Draw continuous path using SVG - use GLOBAL date range for X axis
                  const pathData = points.map((point, pointIndex) => {
                    const date = new Date(point.date).getTime();
                    // Convert to SVG coordinates: x from 0 to 1000, y from 0 to 300
                    const x = globalDateRange > 0 ? 
                      ((date - globalMinDate) / globalDateRange * 1000) : 
                      (pointIndex / (points.length - 1) * 1000);
                    const y = equityRange > 0 ? 
                      300 - ((point.equity - curveMinEquity) / equityRange * 300) : 
                      150;  // Middle if no range
                    return `${pointIndex === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
                  }).join(' ');
                  
                  return (
                    <g key={curveIndex}>
                      <path
                        d={pathData}
                        stroke={curve.color}
                        strokeWidth="2"
                        fill="none"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                      
                      {/* Add data points */}
                      {points.map((point, pointIndex) => {
                        if (pointIndex % Math.max(1, Math.floor(points.length / 10)) !== 0) return null;
                        const date = new Date(point.date).getTime();
                        const x = globalDateRange > 0 ? 
                          ((date - globalMinDate) / globalDateRange * 1000) : 
                          (pointIndex / (points.length - 1) * 1000);
                        const y = equityRange > 0 ? 
                          300 - ((point.equity - curveMinEquity) / equityRange * 300) : 
                          150;
                        
                        return (
                          <circle
                            key={pointIndex}
                            cx={x}
                            cy={y}
                            r="3"
                            fill={curve.color}
                            stroke="white"
                            strokeWidth="1"
                          />
                        );
                      })}
                    </g>
                  );
                })}
              </svg>
              
              {/* Y-axis labels (normalized percentage) */}
              <div style={{ 
                position: 'absolute', 
                left: '-40px', 
                top: '0', 
                bottom: '0', 
                width: '40px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between'
              }}>
                {[150, 140, 130, 120, 110, 100].map((value, index) => (
                  <div key={index} style={{ 
                    fontSize: '11px', 
                    color: '#666',
                    textAlign: 'right',
                    paddingRight: '4px'
                  }}>
                    {value}%
                  </div>
                ))}
              </div>
              
              {/* X-axis date labels */}
              <div style={{ 
                position: 'absolute', 
                left: '0', 
                right: '0', 
                bottom: '-20px',
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: '11px',
                color: '#666'
              }}>
                <div>
                  {new Date(globalMinDate).toLocaleDateString()}
                </div>
                <div>
                  {new Date(globalMaxDate).toLocaleDateString()}
                </div>
              </div>
            </div>
            
            {/* Legend with more details */}
            <div style={{ 
              display: 'flex', 
              flexWrap: 'wrap',
              gap: '12px',
              justifyContent: 'center',
              marginTop: '20px'
            }}>
              {equityCurveData.map((curve, index) => {
                const lastPoint = curve.data[curve.data.length - 1];
                const totalReturn = lastPoint ? (lastPoint.equity - 100).toFixed(1) : '0.0';
                const isPositive = parseFloat(totalReturn) >= 0;
                
                return (
                  <div 
                    key={index} 
                    style={{ 
                      display: 'flex', 
                      alignItems: 'center', 
                      gap: '8px',
                      padding: '6px 12px',
                      background: '#fff',
                      borderRadius: '6px',
                      border: `1px solid ${curve.color}20`,
                      boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
                    }}
                  >
                    <div style={{ 
                      width: '12px', 
                      height: '12px', 
                      backgroundColor: curve.color,
                      borderRadius: '2px'
                    }} />
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                      <span style={{ fontSize: '12px', fontWeight: '500', color: '#333' }}>
                        {curve.name}
                      </span>
                      <span style={{ 
                        fontSize: '11px', 
                        color: isPositive ? '#3f8600' : '#cf1322',
                        fontWeight: 'bold'
                      }}>
                        {isPositive ? '+' : ''}{totalReturn}% total
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
            
            {/* Chart explanation */}
            <div style={{ 
              marginTop: '16px', 
              padding: '8px 12px', 
              background: '#f0f0f0', 
              borderRadius: '4px',
              fontSize: '11px',
              color: '#666',
              textAlign: 'center'
            }}>
              All equity curves normalized to 100% = initial capital. Each curve shows percentage return over time.
            </div>
          </div>
        ) : (
          <Empty 
            description="No equity curve data available for comparison" 
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ padding: '40px 0' }}
          />
        )}
      </Card>

      {/* Actions */}
      <div style={{ textAlign: 'center', marginTop: '24px' }}>
        <Button 
          type="primary" 
          onClick={fetchBacktestResults}
          loading={loading}
        >
          Refresh Comparison
        </Button>
      </div>
    </div>
  );
};

export default StrategyComparison;