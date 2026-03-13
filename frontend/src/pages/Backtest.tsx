import React, { useState, useEffect, useRef } from 'react';
import { Card, Form, Input, InputNumber, Button, Select, DatePicker, Row, Col, Statistic, Table, Tag, Alert, Space, Divider, message, Empty, Spin, Progress, Tabs, Checkbox } from 'antd';
import { PlayCircleOutlined, HistoryOutlined, LineChartOutlined, ArrowUpOutlined, ArrowDownOutlined, ReloadOutlined, EyeOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { backtraderAPI } from '../services/api';
import dayjs from 'dayjs';
import TradingChart from '../components/TradingChart';

const { Option } = Select;
const { RangePicker } = DatePicker;

interface BacktestConfig {
  symbol: string;
  strategy: string;
  startDate: string;
  endDate: string;
  initialCapital: number;
}

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
  drawdownCurve?: Array<{ date: string; drawdown: number }>;
}

interface BacktestHistoryItem {
  backtestId: string;
  status: 'running' | 'completed' | 'failed';
  results?: {
    totalReturn: number;
    sharpeRatio: number;
    maxDrawdown: number;
    winRate: number;
    trades: number;
    annualizedReturn?: number;
    profitLoss?: number;
  };
  parameters?: {
    strategy: string;
    symbols: string[];
    period: string;
    initialCapital: number;
  };
  createdAt?: string;
  symbol?: string;
  strategy?: string;
  startDate?: string;
  endDate?: string;
  initialCapital?: number;
  totalReturn?: number;
  sharpeRatio?: number;
  maxDrawdown?: number;
  winRate?: number;
  trades?: number;
}

const Backtest: React.FC = () => {
  const [form] = Form.useForm();
  const location = useLocation();
  const navigate = useNavigate();
  const resultsRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(false);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [backtestHistory, setBacktestHistory] = useState<BacktestHistoryItem[]>([]);
  const [error, setError] = useState<string>('');
  const [historyLoading, setHistoryLoading] = useState(true);
  const [selectedBacktests, setSelectedBacktests] = useState<string[]>([]);

  // 设置默认日期范围（最近1年）使用 dayjs
  const defaultDateRange = () => {
    const end = dayjs();
    const start = dayjs().subtract(1, 'year');
    return [start, end];
  };

  // 从URL参数或location state获取symbol
  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const symbolFromUrl = searchParams.get('symbol');
    
    if (symbolFromUrl) {
      form.setFieldsValue({ 
        symbol: symbolFromUrl.toUpperCase(),
        dateRange: defaultDateRange()
      });
    }
    
    // 从location state获取symbol（从Market页面跳转时）
    if (location.state && location.state.symbol) {
      form.setFieldsValue({ 
        symbol: location.state.symbol.toUpperCase(),
        strategy: location.state.strategy || 'moving_average',
        dateRange: defaultDateRange(),
        initialCapital: location.state.initialCapital || 100000
      });
    } else {
      // 设置默认值
      form.setFieldsValue({
        dateRange: defaultDateRange(),
        initialCapital: 100000,
        strategy: 'moving_average'
      });
    }
    
    // 加载回测历史
    fetchBacktestHistory();
  }, [location, form]);

  const safeToFixed = (value: any, decimals: number = 2): string => {
    if (typeof value === 'number' && !isNaN(value)) {
      return value.toFixed(decimals);
    }
    return '0.00';
  };

  const safeNumber = (value: any): number => {
    if (typeof value === 'number' && !isNaN(value)) {
      return value;
    }
    return 0;
  };

  const formatCurrency = (value: number): string => {
    const safeValue = safeNumber(value);
    if (safeValue >= 1e9) {
      return `$${safeToFixed(safeValue / 1e9, 2)}B`;
    } else if (safeValue >= 1e6) {
      return `$${safeToFixed(safeValue / 1e6, 2)}M`;
    } else if (safeValue >= 1e3) {
      return `$${safeToFixed(safeValue / 1e3, 2)}K`;
    }
    return `$${safeToFixed(safeValue, 2)}`;
  };

  const fetchBacktestHistory = async () => {
    try {
      setHistoryLoading(true);
      const response = await backtraderAPI.getBacktestHistory();
      if (response.data && Array.isArray(response.data)) {
        // 转换后端数据为前端需要的平铺结构
        const historyData = response.data.map((item: any) => {
          const symbol = item.parameters?.symbols?.[0] || 'Unknown';
          const strategy = item.parameters?.strategy || 'Unknown';
          const period = item.parameters?.period || '';
          const [startDate, endDate] = period.split(' to ') || ['', ''];
          
          return {
            backtestId: item.backtestId || '',
            status: item.status || 'unknown',
            results: item.results,
            parameters: item.parameters,
            createdAt: item.createdAt,
            // 平铺字段用于表格显示
            symbol: symbol,
            strategy: strategy,
            startDate: startDate,
            endDate: endDate,
            initialCapital: safeNumber(item.parameters?.initialCapital),
            totalReturn: safeNumber(item.results?.totalReturn),
            sharpeRatio: safeNumber(item.results?.sharpeRatio),
            maxDrawdown: safeNumber(item.results?.maxDrawdown),
            winRate: safeNumber(item.results?.winRate),
            trades: safeNumber(item.results?.trades),
            annualizedReturn: safeNumber(item.results?.annualizedReturn),
            profitLoss: safeNumber(item.results?.profitLoss),
          };
        });
        
        setBacktestHistory(historyData);
      }
    } catch (err) {
      console.error('Failed to fetch backtest history:', err);
      // 如果接口不存在或出错，使用空数组
      setBacktestHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleRunBacktest = async (values: any) => {
    setLoading(true);
    setError('');
    setBacktestResult(null); // 清除旧结果，开始新的回测
    
    try {
      const symbol = values.symbol.toUpperCase();
      const config = {
        symbol: symbol,
        strategy: values.strategy,
        startDate: values.dateRange[0].format('YYYY-MM-DD'),
        endDate: values.dateRange[1].format('YYYY-MM-DD'),
        initialCapital: values.initialCapital,
      };
      
      console.log('Running backtest with config:', config);
      
      const response = await backtraderAPI.runBacktest(config);
      
      if (response.data) {
        const result = response.data;
        
        // 检查后端是否同步返回完整结果（主要检查results字段）
        if (result.results) {
          // 后端已同步返回完整结果，直接使用
          setBacktestResult(result);
          setLoading(false);
          
          // 如果有status字段，根据状态显示相应消息
          if (result.status === 'completed') {
            message.success('Backtest completed successfully!');
          } else if (result.status === 'failed') {
            message.error('Backtest failed. Please check parameters and try again.');
          } else if (result.status) {
            message.info(`Backtest status: ${result.status}`);
          } else {
            message.success('Backtest completed!');
          }
          
          // 滚动到结果区域
          setTimeout(() => {
            resultsRef.current?.scrollIntoView({ behavior: 'smooth' });
          }, 100);
          
          // 刷新历史记录
          fetchBacktestHistory();
        } else if (result.backtestId) {
          // 兼容旧版本：后端返回了 backtestId 但没有完整结果
          // 这种情况下可能需要轮询，但根据当前修改，后端应该总是返回完整结果
          setBacktestResult(null);
          setError('Backtest started but results not available immediately. Please try again.');
          message.error('Backtest response incomplete');
          setLoading(false);
        } else {
          setBacktestResult(null);
          setError('Failed to start backtest: Invalid response format');
          message.error('Failed to start backtest');
          setLoading(false);
        }
      } else {
        setBacktestResult(null);
        setError('Failed to start backtest: No response data');
        message.error('Failed to start backtest');
        setLoading(false);
      }
    } catch (err: any) {
      setBacktestResult(null);
      setError(`Error running backtest: ${err.message || 'Unknown error'}`);
      message.error('Failed to run backtest');
      console.error('Backtest error:', err);
      setLoading(false);
    }
  };

  const loadBacktestResult = async (backtestId: string) => {
    try {
      const response = await backtraderAPI.getBacktestResults(backtestId);
      if (response.data) {
        setBacktestResult(response.data);
        // 滚动到结果区域
        setTimeout(() => {
          resultsRef.current?.scrollIntoView({ behavior: 'smooth' });
        }, 100);
        message.success('Backtest results loaded');
      }
    } catch (err) {
      console.error('Error loading backtest:', err);
      message.error('Failed to load backtest results');
    }
  };

  const strategyOptions = [
    { value: 'moving_average', label: 'Moving Average Crossover', type: 'real', description: 'Real calculation using Yahoo Finance data' },
    { value: 'rsi', label: 'RSI Strategy', type: 'real', description: 'Real calculation using Yahoo Finance data' },
    { value: 'macd', label: 'MACD Strategy', type: 'real', description: 'Real calculation using Yahoo Finance data' },
    { value: 'bollinger', label: 'Bollinger Bands', type: 'simulated', description: 'Simulated results (to be implemented)' },
    { value: 'momentum', label: 'Momentum Strategy', type: 'real', description: 'Real calculation using Yahoo Finance data' },
  ];

  const resultColumns = [
    {
      title: 'Metric',
      dataIndex: 'metric',
      key: 'metric',
      width: 150,
    },
    {
      title: 'Value',
      dataIndex: 'value',
      key: 'value',
      render: (value: any, record: any) => {
        // Handle non-numeric values for specific metrics
        if (record.metric === 'Strategy Type' || record.metric === 'Status') {
          if (record.metric === 'Status') {
            const statusColors: Record<string, string> = {
              'running': 'blue',
              'completed': 'green',
              'failed': 'red'
            };
            const statusValue = value || 'unknown';
            return <Tag color={statusColors[statusValue] || 'default'}>{statusValue}</Tag>;
          } else {
            // Strategy Type
            return <span style={{ fontWeight: 'bold' }}>{value || 'Unknown'}</span>;
          }
        }
        
        // For numeric metrics, use safeNumber
        const safeValue = safeNumber(value);
        
        if (record.metric === 'Profit / Loss') {
          // Profit/Loss 是金额，使用货币格式
          const color = safeValue >= 0 ? '#3f8600' : '#cf1322';
          const formatted = formatCurrency(safeValue);
          return <span style={{ color, fontWeight: 'bold' }}>{formatted}</span>;
        } else if (record.metric.includes('Return')) {
          // Return 类指标使用百分比格式
          const color = safeValue >= 0 ? '#3f8600' : '#cf1322';
          const prefix = record.metric.includes('$') ? '' : (safeValue >= 0 ? '+' : '');
          const suffix = record.metric.includes('$') ? '' : '%';
          return <span style={{ color, fontWeight: 'bold' }}>{prefix}{safeToFixed(safeValue, 2)}{suffix}</span>;
        } else if (record.metric === 'Expectancy') {
          // Expectancy 使用百分比格式
          const color = safeValue >= 0 ? '#3f8600' : '#cf1322';
          const prefix = safeValue >= 0 ? '+' : '';
          return <span style={{ color, fontWeight: 'bold' }}>{prefix}{safeToFixed(safeValue, 2)}%</span>;
        } else if (record.metric === 'Volatility') {
          // Volatility 使用百分比格式
          const color = safeValue < 20 ? '#3f8600' : safeValue < 40 ? '#faad14' : '#cf1322';
          return <span style={{ color, fontWeight: 'bold' }}>{safeToFixed(safeValue, 2)}%</span>;
        } else if (record.metric === 'Exposure') {
          // Exposure 使用百分比格式
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

  const historyColumns = [
    {
      title: 'Select',
      key: 'selection',
      width: 60,
      render: (_: any, record: BacktestHistoryItem) => (
        <Checkbox
          checked={selectedBacktests.includes(record.backtestId)}
          onChange={(e) => {
            if (e.target.checked) {
              setSelectedBacktests([...selectedBacktests, record.backtestId]);
            } else {
              setSelectedBacktests(selectedBacktests.filter(id => id !== record.backtestId));
            }
          }}
        />
      ),
    },
    {
      title: 'Symbol',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 100,
      render: (symbol: string) => <strong>{symbol || 'Unknown'}</strong>,
    },
    {
      title: 'Strategy',
      dataIndex: 'strategy',
      key: 'strategy',
      width: 150,
      render: (strategy: string) => {
        const strategyNames: Record<string, string> = {
          'moving_average': 'MA Crossover',
          'rsi': 'RSI',
          'macd': 'MACD',
          'bollinger': 'Bollinger',
          'momentum': 'Momentum'
        };
        return strategyNames[strategy] || strategy || 'Unknown';
      },
    },
    {
      title: 'Period',
      dataIndex: 'startDate',
      key: 'period',
      width: 120,
      render: (startDate: string, record: BacktestHistoryItem) => {
        if (!startDate || !record.endDate) return 'N/A';
        return `${startDate} to ${record.endDate}`.replace(/^(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})$/, (_, start, end) => {
          return `${start.split('-').slice(1).join('/')} - ${end.split('-').slice(1).join('/')}`;
        });
      },
    },
    {
      title: 'Return',
      dataIndex: 'totalReturn',
      key: 'totalReturn',
      width: 100,
      render: (value: number) => {
        const safeValue = safeNumber(value);
        const color = safeValue >= 0 ? '#3f8600' : '#cf1322';
        return <span style={{ color, fontWeight: 'bold' }}>{safeValue >= 0 ? '+' : ''}{safeToFixed(safeValue, 2)}%</span>;
      },
    },
    {
      title: 'Sharpe',
      dataIndex: 'sharpeRatio',
      key: 'sharpeRatio',
      width: 80,
      render: (value: number) => safeToFixed(safeNumber(value), 2),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const statusColors: Record<string, string> = {
          'running': 'blue',
          'completed': 'green',
          'failed': 'red'
        };
        return <Tag color={statusColors[status] || 'default'}>{status}</Tag>;
      },
    },
    {
      title: 'Date',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 100,
      render: (date: string) => {
        if (!date) return 'N/A';
        try {
          return new Date(date).toLocaleDateString();
        } catch {
          return 'Invalid Date';
        }
      },
    },
    {
      title: 'Action',
      key: 'action',
      width: 80,
      render: (_: any, record: BacktestHistoryItem) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => record.backtestId && navigate(`/backtest/${record.backtestId}`)}
          disabled={!record.backtestId}
        >
          View
        </Button>
      ),
    },
  ];

  // Get current strategy info
  const currentStrategy = strategyOptions.find(opt => opt.value === backtestResult?.parameters?.strategy);
  const strategyType = currentStrategy?.type || 'unknown';
  const strategyDescription = currentStrategy?.description || '';
  
  // Add strategy type info to result data
  const resultData = backtestResult ? [
    { 
      key: 'strategyType', 
      metric: 'Strategy Type', 
      value: strategyType === 'real' ? 'Real Calculation' : 'Simulated Results', 
      description: strategyDescription 
    },
    { 
      key: 'status', 
      metric: 'Status', 
      value: backtestResult.status, 
      description: 'Current backtest status' 
    },
    { 
      key: 'totalReturn', 
      metric: 'Total Return', 
      value: safeNumber(backtestResult.results?.totalReturn), 
      description: 'Total return over the period' 
    },
    { 
      key: 'annualizedReturn', 
      metric: 'Annualized Return', 
      value: safeNumber(backtestResult.results?.annualizedReturn), 
      description: 'Annualized return (CAGR)' 
    },
    { 
      key: 'profitLoss', 
      metric: 'Profit / Loss', 
      value: safeNumber(backtestResult.results?.profitLoss), 
      description: `Profit/Loss amount (from $${safeNumber(backtestResult.parameters?.initialCapital).toLocaleString()})` 
    },
    { 
      key: 'sharpeRatio', 
      metric: 'Sharpe Ratio', 
      value: safeNumber(backtestResult.results?.sharpeRatio), 
      description: 'Risk-adjusted return (higher is better)' 
    },
    { 
      key: 'calmarRatio', 
      metric: 'Calmar Ratio', 
      value: safeNumber(backtestResult.results?.calmarRatio), 
      description: 'Return vs max drawdown (higher is better)' 
    },
    { 
      key: 'maxDrawdown', 
      metric: 'Max Drawdown', 
      value: safeNumber(backtestResult.results?.maxDrawdown), 
      description: 'Maximum loss from a peak' 
    },
    { 
      key: 'winRate', 
      metric: 'Win Rate', 
      value: safeNumber(backtestResult.results?.winRate), 
      description: 'Percentage of winning trades' 
    },
    { 
      key: 'trades', 
      metric: 'Trades', 
      value: safeNumber(backtestResult.results?.trades), 
      description: 'Total number of trades executed' 
    },
    { 
      key: 'avgReturnPerTrade', 
      metric: 'Avg Return per Trade', 
      value: safeNumber(backtestResult.results?.avgReturnPerTrade), 
      description: 'Average return per trade (annualized)' 
    },
    { 
      key: 'volatility', 
      metric: 'Volatility', 
      value: safeNumber(backtestResult.results?.volatility), 
      description: 'Annualized volatility of strategy returns' 
    },
    { 
      key: 'sortinoRatio', 
      metric: 'Sortino Ratio', 
      value: safeNumber(backtestResult.results?.sortinoRatio), 
      description: 'Risk-adjusted return considering only downside volatility' 
    },
    { 
      key: 'profitFactor', 
      metric: 'Profit Factor', 
      value: safeNumber(backtestResult.results?.profitFactor), 
      description: 'Gross profit divided by gross loss (higher is better)' 
    },
    { 
      key: 'expectancy', 
      metric: 'Expectancy', 
      value: safeNumber(backtestResult.results?.expectancy), 
      description: 'Expected return per trade based on win rate and average win/loss' 
    },
    { 
      key: 'exposure', 
      metric: 'Exposure', 
      value: safeNumber(backtestResult.results?.exposure), 
      description: 'Percentage of time the strategy held positions' 
    },
  ] : [];

  // 生成模拟权益曲线数据（简化版本，不使用图表库）
  const generateEquityCurveData = () => {
    if (backtestResult?.results?.equityCurve && backtestResult.results.equityCurve.length > 0) {
      return backtestResult.results.equityCurve;
    }
    
    // 模拟数据
    const curve = [];
    const initialCapital = safeNumber(backtestResult?.parameters?.initialCapital) || 100000;
    const totalReturn = safeNumber(backtestResult?.results?.totalReturn) || 15.23;
    const finalEquity = initialCapital * (1 + totalReturn / 100);
    
    for (let i = 0; i < 10; i++) {
      const progress = i / 9;
      const equity = initialCapital + (finalEquity - initialCapital) * progress;
      
      const date = new Date();
      date.setDate(date.getDate() - (9 - i));
      
      curve.push({
        date: date.toISOString().split('T')[0],
        equity: Math.max(equity, initialCapital * 0.8)
      });
    }
    
    return curve;
  };

  const equityCurveData = generateEquityCurveData();

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>Strategy Backtest</h1>
      
      {error && (
        <Alert
          message="Error"
          description={error}
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          closable
          onClose={() => setError('')}
        />
      )}
      
      <Row gutter={[16, 16]}>
        <Col span={16}>
          <Card title="Backtest Configuration">
            <Form
              form={form}
              layout="vertical"
              onFinish={handleRunBacktest}
              initialValues={{
                symbol: '',
                strategy: 'moving_average',
                initialCapital: 100000,
              }}
            >
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    label="Stock Symbol"
                    name="symbol"
                    rules={[{ required: true, message: 'Please enter stock symbol' }]}
                    help="e.g., AAPL, MSFT, GOOGL, TSLA"
                  >
                    <Input 
                      placeholder="Enter stock symbol" 
                      size="large"
                      prefix={<LineChartOutlined />}
                      onBlur={(e) => {
                        if (e.target.value) {
                          form.setFieldsValue({ symbol: e.target.value.toUpperCase() });
                        }
                      }}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    label="Strategy"
                    name="strategy"
                    rules={[{ required: true, message: 'Please select a strategy' }]}
                  >
                    <Select size="large" placeholder="Select strategy">
                      {strategyOptions.map(option => (
                        <Option key={option.value} value={option.value}>
                          {option.label} {option.type === 'simulated' ? '(Simulated)' : '(Real)'}
                        </Option>
                      ))}
                    </Select>
                  </Form.Item>
                </Col>
              </Row>
              
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    label="Date Range"
                    name="dateRange"
                    rules={[{ required: true, message: 'Please select date range' }]}
                    help="Default: Last 1 year"
                  >
                    <RangePicker size="large" style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    label="Initial Capital ($)"
                    name="initialCapital"
                    rules={[
                      { required: true, message: 'Please enter initial capital' },
                      { type: 'number', min: 1000, message: 'Minimum $1,000' },
                    ]}
                    help="Minimum: $1,000"
                  >
                    <InputNumber
                      min={1000}
                      size="large"
                      style={{ width: '100%' }}
                    />
                  </Form.Item>
                </Col>
              </Row>
              
              <Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  size="large"
                  loading={loading}
                  icon={<PlayCircleOutlined />}
                  style={{ width: '100%' }}
                  disabled={loading}
                >
                  {loading ? 'Running Backtest...' : 'Run Backtest'}
                </Button>
              </Form.Item>
            </Form>
          </Card>
          
          {backtestResult && (
            <div ref={resultsRef}>
              <Card title="Backtest Results" style={{ marginTop: 16 }}>
                <Tabs
                  defaultActiveKey="results"
                  items={[
                    {
 key: 'results',
 label: 'Overview',
 children: (
 <>
 {/* Performance Summary Cards */}
 {backtestResult?.results && (
 <div style={{ marginBottom: '24px' }}>
 <h4 style={{ margin: '0 0 16px 0' }}>Performance Summary</h4>
 <Row gutter={[16, 16]}>
 <Col span={8}>
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

 <Col span={8}>
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

 <Col span={8}>
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

 <Col span={8}>
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

 <Col span={8}>
 <Card size="small" style={{ textAlign: 'center' }}>
 <Statistic
 title="Win Rate"
 value={backtestResult.results.winRate || 0}
 precision={1}
 suffix="%"
 valueStyle={{
 color:
 (backtestResult.results.winRate || 0) >= 60
 ? '#3f8600'
 : (backtestResult.results.winRate || 0) >= 40
 ? '#fa8c16'
 : '#cf1322',
 fontWeight: 'bold'
 }}
 />
 </Card>
 </Col>

 <Col span={8}>
 <Card size="small" style={{ textAlign: 'center' }}>
 <Statistic
 title="Profit Factor"
 value={backtestResult.results.profitFactor || 0}
 precision={2}
 valueStyle={{
 color:
 (backtestResult.results.profitFactor || 0) >= 1.5
 ? '#3f8600'
 : (backtestResult.results.profitFactor || 0) >= 1
 ? '#fa8c16'
 : '#cf1322',
 fontWeight: 'bold'
 }}
 />
 </Card>
 </Col>
 </Row>
 </div>
 )}

 <Divider />

 <Table
 columns={resultColumns}
 dataSource={resultData}
 pagination={false}
 size="small"
 />


 </>
 ),
},
                    {
                      key: 'charts',
                      label: 'Charts',
                      children: (
                        <>
                          <h4>Equity Curve</h4>
                          {equityCurveData.length > 0 ? (
                            <div
                              style={{
                                height: '150px',
                                background: '#fafafa',
                                borderRadius: '8px',
                                padding: '16px',
                                position: 'relative'
                              }}
                            >
                              <div
                                style={{
                                  display: 'flex',
                                  alignItems: 'flex-end',
                                  height: '100px',
                                  justifyContent: 'space-between',
                                  marginBottom: '8px'
                                }}
                              >
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

                              <div
                                style={{
                                  display: 'flex',
                                  justifyContent: 'space-between',
                                  fontSize: '10px',
                                  color: '#666'
                                }}
                              >
                                <span>{equityCurveData[0]?.date || 'Start'}</span>
                                <span>Equity Curve</span>
                                <span>{equityCurveData[equityCurveData.length - 1]?.date || 'End'}</span>
                              </div>
                            </div>
                          ) : (
                            <div style={{ textAlign: 'center', padding: '40px', color: '#999' }}>
                              No equity curve data available
                            </div>
                          )}

                          <Divider />

                          <h4>Drawdown Chart</h4>
                          {equityCurveData.length > 0 ? (
                            <div
                              style={{
                                height: '150px',
                                background: '#fafafa',
                                borderRadius: '8px',
                                padding: '16px',
                                position: 'relative'
                              }}
                            >
                              {/* 计算最大回撤数据 */}
                              {(() => {
                                // 计算每个点的回撤
                                const drawdownData: Array<{date: string, drawdown: number, equity: number, peak: number}> = [];
                                let peak = equityCurveData[0].equity;
                                
                                for (let i = 0; i < equityCurveData.length; i++) {
                                  const currentEquity = equityCurveData[i].equity;
                                  peak = Math.max(peak, currentEquity);
                                  const drawdown = ((peak - currentEquity) / peak) * 100;
                                  drawdownData.push({
                                    date: equityCurveData[i].date,
                                    drawdown: drawdown,
                                    equity: currentEquity,
                                    peak: peak
                                  });
                                }
                                
                                // 找到最大回撤
                                const maxDrawdown = Math.max(...drawdownData.map(d => d.drawdown));
                                const maxDrawdownPoint = drawdownData.find(d => d.drawdown === maxDrawdown);
                                
                                // 计算最大回撤值（避免在 map 内部重复计算）
                                const maxDrawdownValue = Math.max(...drawdownData.map(d => d.drawdown));
                                
                                return (
                                  <>
                                    <div
                                      style={{
                                        display: 'flex',
                                        alignItems: 'flex-start',
                                        height: '100px',
                                        justifyContent: 'space-between',
                                        marginBottom: '8px',
                                        borderTop: '1px solid #ddd'
                                      }}
                                    >
                                      {drawdownData.map((point, index) => {
                                        const drawdownPercent = maxDrawdownValue === 0 ? 0 : (point.drawdown / maxDrawdownValue) * 100;
                                        
                                        return (
                                          <div
                                            key={index}
                                            style={{
                                              width: `${100 / drawdownData.length}%`,
                                              height: point.drawdown === 0 ? '0%' : `${Math.max(drawdownPercent, 5)}%`,
                                              backgroundColor: '#cf1322',
                                              borderRadius: '0 0 2px 2px',
                                              position: 'relative'
                                            }}
                                            title={`${point.date}: ${safeToFixed(point.drawdown, 2)}% drawdown`}
                                          />
                                        );
                                      })}
                                    </div>
                                    
                                    <div
                                      style={{
                                        display: 'flex',
                                        justifyContent: 'space-between',
                                        fontSize: '10px',
                                        color: '#666'
                                      }}
                                    >
                                      <span>{equityCurveData[0]?.date || 'Start'}</span>
                                      <span>
                                        Max Drawdown: <strong style={{ color: '#cf1322' }}>{safeToFixed(maxDrawdown, 2)}%</strong>
                                        {maxDrawdownPoint && ` (${maxDrawdownPoint.date})`}
                                      </span>
                                      <span>{equityCurveData[equityCurveData.length - 1]?.date || 'End'}</span>
                                    </div>
                                  </>
                                );
                              })()}
                            </div>
                          ) : (
                            <div style={{ textAlign: 'center', padding: '40px', color: '#999' }}>
                              No drawdown data available
                            </div>
                          )}

                          <Divider />

                          <h4>Trading Chart</h4>
                          {backtestResult?.results?.chartData ? (
                            <TradingChart
                              data={backtestResult.results.chartData}
                              height={400}
                            />
                          ) : (
                            <Empty 
                              description="No chart data available" 
                              image={Empty.PRESENTED_IMAGE_SIMPLE}
                              style={{ padding: '40px 0' }}
                            />
                          )}
                        </>
                      ),
                    },
                    {
                      key: 'trades',
                      label: 'Trades',
                      children: (
                        <div style={{ padding: '40px', textAlign: 'center', color: '#999' }}>
                          Trade log will be displayed here
                        </div>
                      ),
                    },
                    {
                      key: 'parameters',
                      label: 'Parameters',
                      children: (
                        <div style={{ padding: '40px', textAlign: 'center', color: '#999' }}>
                          Strategy parameters will be displayed here
                        </div>
                      ),
                    },
                  ]}
                />
                
                <Divider />
                
                <h4>Parameters</h4>
                <Row gutter={16}>
                  <Col span={6}>
                    <div><strong>Strategy:</strong> {backtestResult.parameters?.strategy || 'Unknown'}</div>
                  </Col>
                  <Col span={6}>
                    <div><strong>Symbols:</strong> {backtestResult.parameters?.symbols?.join(', ') || 'Unknown'}</div>
                  </Col>
                  <Col span={6}>
                    <div><strong>Period:</strong> {backtestResult.parameters?.period || 'Unknown'}</div>
                  </Col>
                  <Col span={6}>
                    <div><strong>Initial Capital:</strong> ${safeNumber(backtestResult.parameters?.initialCapital).toLocaleString()}</div>
                  </Col>
                </Row>
              </Card>
            </div>
          )}
        </Col>
        
        <Col span={8}>
          <Card 
            title="Recent Backtests" 
            extra={
              <Space>
                {selectedBacktests.length > 0 && (
                  <Button 
                    type="primary" 
                    size="small"
                    onClick={() => navigate(`/compare?ids=${selectedBacktests.join(',')}`)}
                  >
                    Compare ({selectedBacktests.length})
                  </Button>
                )}
                <Button 
                  type="text" 
                  icon={<ReloadOutlined />} 
                  onClick={fetchBacktestHistory}
                  loading={historyLoading}
                  size="small"
                />
              </Space>
            }
          >
            {historyLoading ? (
              <div style={{ textAlign: 'center', padding: '40px' }}>
                <Spin />
              </div>
            ) : backtestHistory.length > 0 ? (
              <Table
                columns={historyColumns}
                dataSource={backtestHistory}
                rowKey="backtestId"
                pagination={{ pageSize: 5, simple: true }}
                size="small"
                scroll={{ y: 300 }}
              />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="No backtest history yet"
              >
                <Button type="primary" onClick={() => {
                  form.setFieldsValue({
                    symbol: 'AAPL',
                    strategy: 'moving_average',
                    initialCapital: 100000,
                    dateRange: defaultDateRange()
                  });
                  message.info('AAPL example loaded');
                }}>
                  Try AAPL Example
                </Button>
              </Empty>
            )}
          </Card>
          
          <Card title="Quick Actions" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button 
                type="default" 
                block
                onClick={() => navigate('/market')}
                icon={<LineChartOutlined />}
              >
                Browse Market
              </Button>
              <Button 
                type="default" 
                block
                onClick={() => {
                  form.setFieldsValue({
                    symbol: 'AAPL',
                    strategy: 'moving_average',
                    initialCapital: 100000,
                    dateRange: defaultDateRange()
                  });
                  message.info('AAPL example loaded');
                }}
              >
                Load AAPL Example
              </Button>
              <Button 
                type="default" 
                block
                onClick={() => {
                  form.setFieldsValue({
                    symbol: 'MSFT',
                    strategy: 'rsi',
                    initialCapital: 50000,
                    dateRange: defaultDateRange()
                  });
                  message.info('MSFT example loaded');
                }}
              >
                Load MSFT Example
              </Button>
              <Button 
                type="default" 
                block
                onClick={() => {
                  form.setFieldsValue({
                    symbol: 'TSLA',
                    strategy: 'momentum',
                    initialCapital: 75000,
                    dateRange: defaultDateRange()
                  });
                  message.info('TSLA example loaded');
                }}
              >
                Load TSLA Example
              </Button>
            </Space>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Backtest;