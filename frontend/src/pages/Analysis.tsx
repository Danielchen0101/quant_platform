import React, { useState, useEffect } from 'react';
import { Card, Table, Tag, Input, Button, Row, Col, Statistic, Space, Alert, message, Empty, Spin, Tabs } from 'antd';
import { SearchOutlined, LineChartOutlined, BarChartOutlined, ReloadOutlined, EyeOutlined, CalculatorOutlined } from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { marketAPI, backtraderAPI } from '../services/api';
import FinancialChart from '../components/FinancialChart';

const { TabPane } = Tabs;

interface Stock {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  marketCap: number;
  sector: string;
  peRatio?: number;
  dividendYield?: number;
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

const Analysis: React.FC = () => {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [filteredStocks, setFilteredStocks] = useState<Stock[]>([]);
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');
  const [searchText, setSearchText] = useState('');
  const [backtestHistory, setBacktestHistory] = useState<BacktestHistoryItem[]>([]);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('market');
  const location = useLocation();
  const navigate = useNavigate();

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
    }
    return `$${safeToFixed(safeValue, 2)}`;
  };

  useEffect(() => {
    fetchMarketData();
    fetchBacktestHistory();
    
    // 从URL参数或location state获取symbol
    if (location.state && location.state.symbol) {
      const symbol = location.state.symbol;
      // 稍后选择该股票
      setTimeout(() => {
        const stock = stocks.find(s => s.symbol === symbol);
        if (stock) {
          setSelectedStock(stock);
          setActiveTab('technical');
        }
      }, 1000);
    }
  }, []);

  useEffect(() => {
    filterStocks();
  }, [stocks, searchText]);

  const fetchMarketData = async () => {
    try {
      setLoading(true);
      const response = await marketAPI.getStocks();
      
      if (response.data && response.data.stocks) {
        const stockData = response.data.stocks;
        setStocks(stockData);
        setError('');
        
        // 如果没有选择股票，选择第一个
        if (!selectedStock && stockData.length > 0) {
          setSelectedStock(stockData[0]);
        }
      } else {
        setError('No stock data received from server');
      }
    } catch (err) {
      console.error('Failed to fetch market data:', err);
      setError('Failed to load market data. Please try again.');
      message.error('Failed to load market data');
    } finally {
      setLoading(false);
    }
  };

  const fetchBacktestHistory = async () => {
    try {
      setBacktestLoading(true);
      const response = await backtraderAPI.getBacktestHistory();
      if (response.data && Array.isArray(response.data)) {
        // 转换后端数据
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
        
        // 按创建时间排序，最新的在前面
        historyData.sort((a, b) => {
          const dateA = a.createdAt ? new Date(a.createdAt).getTime() : 0;
          const dateB = b.createdAt ? new Date(b.createdAt).getTime() : 0;
          return dateB - dateA;
        });
        
        setBacktestHistory(historyData);
      }
    } catch (err) {
      console.error('Failed to fetch backtest history:', err);
      // 如果接口不存在或出错，使用空数组
      setBacktestHistory([]);
    } finally {
      setBacktestLoading(false);
    }
  };

  const filterStocks = () => {
    if (!searchText) {
      setFilteredStocks(stocks);
      return;
    }
    
    const searchLower = searchText.toLowerCase();
    const filtered = stocks.filter(stock =>
      stock.symbol.toLowerCase().includes(searchLower) ||
      stock.name.toLowerCase().includes(searchLower)
    );
    
    setFilteredStocks(filtered);
  };

  const handleStockSelect = (stock: Stock) => {
    setSelectedStock(stock);
    setActiveTab('technical');
    message.info(`Selected ${stock.symbol} for analysis`);
  };

  const handleBacktest = (stock: Stock) => {
    navigate('/backtest', {
      state: {
        symbol: stock.symbol,
        strategy: 'moving_average',
        initialCapital: 100000
      }
    });
  };

  const handleViewBacktest = (backtestId: string) => {
    navigate(`/backtest?backtestId=${backtestId}`);
  };

  const getLatestBacktestForSymbol = (symbol: string) => {
    return backtestHistory.find(item => item.symbol === symbol);
  };

  const technicalIndicators = [
    { name: 'RSI (14)', value: 65.2, level: 'neutral', description: 'Relative Strength Index' },
    { name: 'MACD', value: 2.34, level: 'bullish', description: 'Moving Average Convergence Divergence' },
    { name: 'Bollinger Bands', value: 'Upper', level: 'neutral', description: 'Price volatility indicator' },
    { name: 'Moving Average (50)', value: 152.34, level: 'bullish', description: '50-day moving average' },
    { name: 'Moving Average (200)', value: 148.67, level: 'bullish', description: '200-day moving average' },
    { name: 'Volume', value: 'High', level: 'bullish', description: 'Trading volume trend' },
  ];

  const fundamentalIndicators = [
    { name: 'P/E Ratio', value: selectedStock?.peRatio || 28.5, level: 'neutral', description: 'Price to Earnings ratio' },
    { name: 'Dividend Yield', value: selectedStock?.dividendYield || 1.2, level: 'neutral', description: 'Annual dividend yield' },
    { name: 'Market Cap', value: selectedStock?.marketCap || 0, level: 'neutral', description: 'Total market capitalization' },
    { name: 'Beta', value: 1.23, level: 'high', description: 'Volatility relative to market' },
    { name: 'EPS', value: 6.45, level: 'bullish', description: 'Earnings per share' },
    { name: 'ROE', value: 22.3, level: 'bullish', description: 'Return on Equity' },
  ];

  const stockColumns = [
    {
      title: 'Symbol',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 80,
      render: (symbol: string) => <strong>{symbol}</strong>,
    },
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      width: 120,
    },
    {
      title: 'Price',
      dataIndex: 'price',
      key: 'price',
      width: 80,
      render: (price: number) => `$${safeToFixed(price, 2)}`,
    },
    {
      title: 'Change %',
      dataIndex: 'changePercent',
      key: 'changePercent',
      width: 100,
      render: (percent: number) => {
        const safePercent = safeNumber(percent);
        return (
          <span style={{ color: safePercent >= 0 ? '#3f8600' : '#cf1322' }}>
            {safePercent >= 0 ? '+' : ''}{safeToFixed(safePercent, 2)}%
          </span>
        );
      },
    },
    {
      title: 'Action',
      key: 'action',
      width: 120,
      render: (_: any, record: Stock) => (
        <Space size="small">
          <Button
            type="primary"
            size="small"
            onClick={() => handleStockSelect(record)}
          >
            Analyze
          </Button>
          <Button
            type="default"
            size="small"
            onClick={() => handleBacktest(record)}
          >
            Backtest
          </Button>
        </Space>
      ),
    },
  ];

  const backtestColumns = [
    {
      title: 'Symbol',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 80,
      render: (symbol: string) => <strong>{symbol}</strong>,
    },
    {
      title: 'Strategy',
      dataIndex: 'strategy',
      key: 'strategy',
      width: 100,
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
      title: 'Return',
      dataIndex: 'totalReturn',
      key: 'totalReturn',
      width: 80,
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
      width: 70,
      render: (value: number) => safeToFixed(safeNumber(value), 2),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 90,
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
      title: 'Action',
      key: 'action',
      width: 80,
      render: (_: any, record: BacktestHistoryItem) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => record.backtestId && handleViewBacktest(record.backtestId)}
          disabled={!record.backtestId}
        >
          View
        </Button>
      ),
    },
  ];

  const renderIndicator = (indicator: any) => {
    const value = indicator.value;
    const level = indicator.level;
    
    let color = '#666';
    let icon = null;
    
    if (level === 'bullish') {
      color = '#3f8600';
      icon = <span style={{ color }}>↑</span>;
    } else if (level === 'bearish') {
      color = '#cf1322';
      icon = <span style={{ color }}>↓</span>;
    } else if (level === 'high') {
      color = '#faad14';
    }
    
    return (
      <Card size="small" style={{ marginBottom: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontWeight: 'bold', fontSize: '14px' }}>{indicator.name}</div>
            <div style={{ fontSize: '12px', color: '#666' }}>{indicator.description}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '16px', color, fontWeight: 'bold' }}>
              {icon} {typeof value === 'number' ? safeToFixed(value, 2) : value}
            </div>
            <Tag color={level === 'bullish' ? 'green' : level === 'bearish' ? 'red' : 'default'} style={{ marginTop: 4 }}>
              {level}
            </Tag>
          </div>
        </div>
      </Card>
    );
  };

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>
        <BarChartOutlined /> Stock Analysis
      </h1>

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

      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="Market Overview" key="market">
          <Card
            title="Stocks"
            extra={
              <Space>
                <Input
                  placeholder="Search symbol or name"
                  prefix={<SearchOutlined />}
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  style={{ width: 200 }}
                  allowClear
                />
                <Button
                  icon={<ReloadOutlined />}
                  onClick={fetchMarketData}
                  loading={loading}
                >
                  Refresh
                </Button>
              </Space>
            }
          >
            {loading ? (
              <div style={{ textAlign: 'center', padding: '40px' }}>
                <Spin size="large" />
                <div style={{ marginTop: '16px', color: '#666' }}>Loading market data...</div>
              </div>
            ) : filteredStocks.length > 0 ? (
              <Table
                columns={stockColumns}
                dataSource={filteredStocks}
                rowKey="symbol"
                pagination={{ pageSize: 10 }}
                size="middle"
                scroll={{ x: 600 }}
              />
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={searchText ? "No stocks match your search" : "No stock data available"}
              >
                {searchText ? (
                  <Button type="primary" onClick={() => setSearchText('')}>
                    Clear Search
                  </Button>
                ) : (
                  <Button type="primary" onClick={fetchMarketData}>
                    Refresh Data
                  </Button>
                )}
              </Empty>
            )}
          </Card>
        </TabPane>

        <TabPane tab="Technical Analysis" key="technical" disabled={!selectedStock}>
          {selectedStock ? (
            <div>
              <Row gutter={[16, 16]}>
                <Col span={16}>
                  <FinancialChart
                    symbol={selectedStock.symbol}
                    currentPrice={selectedStock.price}
                  />
                </Col>
                <Col span={8}>
                  <Card title={`${selectedStock.symbol} - ${selectedStock.name}`}>
                    <Row gutter={[8, 8]}>
                      <Col span={12}>
                        <Statistic
                          title="Current Price"
                          value={safeToFixed(selectedStock.price, 2)}
                          prefix="$"
                          valueStyle={{ fontSize: '20px' }}
                        />
                      </Col>
                      <Col span={12}>
                        <Statistic
                          title="Change"
                          value={safeToFixed(selectedStock.changePercent, 2)}
                          suffix="%"
                          valueStyle={{ 
                            color: selectedStock.changePercent >= 0 ? '#3f8600' : '#cf1322',
                            fontSize: '20px'
                          }}
                        />
                      </Col>
                    </Row>
                    
                    <div style={{ marginTop: '16px' }}>
                      <div><strong>Sector:</strong> {selectedStock.sector || 'N/A'}</div>
                      <div><strong>Market Cap:</strong> {formatCurrency(selectedStock.marketCap)}</div>
                      <div><strong>Volume:</strong> {selectedStock.volume.toLocaleString()}</div>
                    </div>
                    
                    <div style={{ marginTop: '16px' }}>
                      <Button 
                        type="primary" 
                        block
                        onClick={() => handleBacktest(selectedStock)}
                        icon={<CalculatorOutlined />}
                      >
                        Run Backtest
                      </Button>
                    </div>
                  </Card>
                </Col>
              </Row>
              
              <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
                <Col span={12}>
                  <Card title="Technical Indicators">
                    {technicalIndicators.map((indicator, index) => (
                      <div key={index}>
                        {renderIndicator(indicator)}
                      </div>
                    ))}
                  </Card>
                </Col>
                <Col span={12}>
                  <Card title="Fundamental Analysis">
                    {fundamentalIndicators.map((indicator, index) => (
                      <div key={index}>
                        {renderIndicator(indicator)}
                      </div>
                    ))}
                  </Card>
                </Col>
              </Row>
              
              {/* 显示该股票的回测历史 */}
              <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
                <Col span={24}>
                  <Card 
                    title={`Backtest History for ${selectedStock.symbol}`}
                    extra={
                      <Button 
                        type="text" 
                        icon={<ReloadOutlined />} 
                        onClick={fetchBacktestHistory}
                        loading={backtestLoading}
                        size="small"
                      />
                    }
                  >
                    {backtestLoading ? (
                      <div style={{ textAlign: 'center', padding: '20px' }}>
                        <Spin />
                      </div>
                    ) : backtestHistory.filter(item => item.symbol === selectedStock.symbol).length > 0 ? (
                      <Table
                        columns={backtestColumns}
                        dataSource={backtestHistory.filter(item => item.symbol === selectedStock.symbol)}
                        rowKey="backtestId"
                        pagination={{ pageSize: 5, simple: true }}
                        size="small"
                      />
                    ) : (
                      <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={`No backtest history for ${selectedStock.symbol}`}
                      >
                        <Button 
                          type="primary" 
                          onClick={() => handleBacktest(selectedStock)}
                        >
                          Run First Backtest
                        </Button>
                      </Empty>
                    )}
                  </Card>
                </Col>
              </Row>
            </div>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="Please select a stock from the Market Overview tab"
            >
              <Button type="primary" onClick={() => setActiveTab('market')}>
                Browse Stocks
              </Button>
            </Empty>
          )}
        </TabPane>

        <TabPane tab="Backtest Analytics" key="backtest">
          <Card
            title="Historical Backtest Results"
            extra={
              <Button 
                icon={<ReloadOutlined />} 
                onClick={fetchBacktestHistory}
                loading={backtestLoading}
              >
                Refresh
              </Button>
            }
          >
            {backtestLoading ? (
              <div style={{ textAlign: 'center', padding: '40px' }}>
                <Spin size="large" />
                <div style={{ marginTop: '16px', color: '#666' }}>Loading backtest history...</div>
              </div>
            ) : backtestHistory.length > 0 ? (
              <div>
                <Table
                  columns={backtestColumns}
                  dataSource={backtestHistory}
                  rowKey="backtestId"
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  size="middle"
                  scroll={{ x: 600 }}
                />
                
                <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
                  <Col span={8}>
                    <Card size="small">
                      <Statistic
                        title="Total Backtests"
                        value={backtestHistory.length}
                        valueStyle={{ fontSize: '24px' }}
                      />
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card size="small">
                      <Statistic
                        title="Success Rate"
                        value={safeToFixed(
                          (backtestHistory.filter(item => item.status === 'completed').length / backtestHistory.length) * 100,
                          1
                        )}
                        suffix="%"
                        valueStyle={{ fontSize: '24px' }}
                      />
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card size="small">
                      <Statistic
                        title="Avg Return"
                        value={safeToFixed(
                          backtestHistory.reduce((sum, item) => sum + safeNumber(item.totalReturn), 0) / backtestHistory.length,
                          2
                        )}
                        suffix="%"
                        valueStyle={{ fontSize: '24px' }}
                      />
                    </Card>
                  </Col>
                </Row>
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="No backtest history available"
              >
                <Button 
                  type="primary" 
                  onClick={() => navigate('/backtest')}
                >
                  Run Your First Backtest
                </Button>
              </Empty>
            )}
          </Card>
        </TabPane>
      </Tabs>
    </div>
  );
};

export default Analysis;