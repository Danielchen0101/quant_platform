import React, { useState, useEffect } from 'react';
import { Card, Row, Col, Statistic, Table, Tag, Progress, Alert, Button, Space, Spin, Empty, message } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined, LineChartOutlined, PlayCircleOutlined, EyeOutlined, ReloadOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { systemAPI, marketAPI, backtraderAPI } from '../services/api';

interface Stock {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  marketCap: number;
  sector: string;
}

interface SystemStatus {
  cpuUsage: number;
  memoryUsage: number;
  uptime: string;
  lastUpdate: string;
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

const Dashboard: React.FC = () => {
  // 独立的状态管理 - 系统状态
  const [systemData, setSystemData] = useState<SystemStatus | null>(null);
  const [systemLoading, setSystemLoading] = useState(true);
  const [systemError, setSystemError] = useState<string>('');

  // 独立的状态管理 - 市场数据
  const [marketData, setMarketData] = useState<Stock[]>([]);
  const [marketLoading, setMarketLoading] = useState(true);
  const [marketError, setMarketError] = useState<string>('');

  // 独立的状态管理 - 回测历史
  const [backtestData, setBacktestData] = useState<BacktestHistoryItem[]>([]);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestError, setBacktestError] = useState<string>('');

  // 缓存和重试状态
  const [systemLastFetched, setSystemLastFetched] = useState<number>(0);
  const [marketLastFetched, setMarketLastFetched] = useState<number>(0);
  const [backtestLastFetched, setBacktestLastFetched] = useState<number>(0);
  const [systemRetryCount, setSystemRetryCount] = useState<number>(0);
  const [marketRetryCount, setMarketRetryCount] = useState<number>(0);
  const [backtestRetryCount, setBacktestRetryCount] = useState<number>(0);

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
    // 独立获取各个模块的数据（使用缓存如果可用）
    fetchSystemData();
    fetchMarketData();
    fetchBacktestHistory();
  }, []);

  // 独立获取系统状态（带重试机制）
  const fetchSystemData = async (forceRefresh: boolean = false) => {
    // 检查缓存：5秒内不重复请求，除非强制刷新
    const now = Date.now();
    const cacheTime = 5000; // 5秒缓存
    
    if (!forceRefresh && systemData && (now - systemLastFetched < cacheTime)) {
      console.log('Using cached system data');
      return;
    }

    try {
      setSystemLoading(true);
      setSystemError('');
      const response = await systemAPI.getSystemStatus();
      if (response.data) {
        setSystemData(response.data);
        setSystemLastFetched(now);
        setSystemRetryCount(0); // 重置重试计数
      }
    } catch (err) {
      console.error('Failed to fetch system status:', err);
      
      // 重试逻辑：最多重试2次
      if (systemRetryCount < 2) {
        setSystemRetryCount(prev => prev + 1);
        setTimeout(() => {
          console.log(`Retrying system data fetch (attempt ${systemRetryCount + 1})`);
          fetchSystemData(true);
        }, 1000 * (systemRetryCount + 1)); // 递增延迟：1秒, 2秒
      } else {
        setSystemError('Failed to load system status. Please try again.');
      }
    } finally {
      setSystemLoading(false);
    }
  };

  // 独立获取市场数据（带重试机制）
  const fetchMarketData = async (forceRefresh: boolean = false) => {
    // 检查缓存：10秒内不重复请求，除非强制刷新（市场数据变化较慢）
    const now = Date.now();
    const cacheTime = 10000; // 10秒缓存
    
    if (!forceRefresh && marketData.length > 0 && (now - marketLastFetched < cacheTime)) {
      console.log('Using cached market data');
      return;
    }

    try {
      setMarketLoading(true);
      setMarketError('');
      const response = await marketAPI.getStocks();
      if (response.data && response.data.stocks) {
        const stocks = response.data.stocks;
        // 取前5只股票作为最近活跃
        setMarketData(stocks.slice(0, 5));
        setMarketLastFetched(now);
        setMarketRetryCount(0); // 重置重试计数
      }
    } catch (err) {
      console.error('Failed to fetch market data:', err);
      
      // 重试逻辑：最多重试2次
      if (marketRetryCount < 2) {
        setMarketRetryCount(prev => prev + 1);
        setTimeout(() => {
          console.log(`Retrying market data fetch (attempt ${marketRetryCount + 1})`);
          fetchMarketData(true);
        }, 1000 * (marketRetryCount + 1)); // 递增延迟：1秒, 2秒
      } else {
        setMarketError('Failed to load market data. Please try again.');
      }
    } finally {
      setMarketLoading(false);
    }
  };

  // 同时获取系统状态和市场数据（用于整体刷新）
  const fetchDashboardData = () => {
    fetchSystemData(true); // 强制刷新
    fetchMarketData(true); // 强制刷新
  };

  const fetchBacktestHistory = async (forceRefresh: boolean = false) => {
    // 检查缓存：30秒内不重复请求，除非强制刷新（回测历史变化较慢）
    const now = Date.now();
    const cacheTime = 30000; // 30秒缓存
    
    if (!forceRefresh && backtestData.length > 0 && (now - backtestLastFetched < cacheTime)) {
      console.log('Using cached backtest data');
      return;
    }

    try {
      setBacktestLoading(true);
      setBacktestError('');
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
            // 平铺字段用于显示
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
        
        setBacktestData(historyData);
        setBacktestLastFetched(now);
        setBacktestRetryCount(0); // 重置重试计数
      }
    } catch (err) {
      console.error('Failed to fetch backtest history:', err);
      
      // 重试逻辑：最多重试1次（回测接口可能不存在）
      if (backtestRetryCount < 1) {
        setBacktestRetryCount(prev => prev + 1);
        setTimeout(() => {
          console.log(`Retrying backtest history fetch (attempt ${backtestRetryCount + 1})`);
          fetchBacktestHistory(true);
        }, 2000); // 2秒后重试
      } else {
        setBacktestError('Failed to load backtest history. Please try again.');
        // 如果接口不存在或出错，使用空数组
        setBacktestData([]);
      }
    } finally {
      setBacktestLoading(false);
    }
  };

  const handleViewBacktest = (backtestId: string) => {
    navigate(`/backtest?backtestId=${backtestId}`);
    message.info('Loading backtest details...');
  };

  const handleRunBacktest = () => {
    navigate('/backtest');
    message.info('Navigate to backtest page');
  };

  const handleViewMarket = () => {
    navigate('/market');
  };

  const handleViewAnalysis = () => {
    navigate('/analysis');
  };

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
      title: 'Market Cap',
      dataIndex: 'marketCap',
      key: 'marketCap',
      width: 100,
      render: (cap: number) => formatCurrency(cap),
    },
  ];

  const getLatestBacktest = () => {
    if (backtestData.length === 0) return null;
    return backtestData[0];
  };

  const latestBacktest = getLatestBacktest();

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>
        <LineChartOutlined /> Dashboard
      </h1>

      {/* 系统状态模块 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card size="small">
            {systemLoading ? (
              <div style={{ textAlign: 'center', padding: '20px' }}>
                <Spin size="small" />
              </div>
            ) : systemError ? (
              <div style={{ textAlign: 'center', padding: '10px' }}>
                <ExclamationCircleOutlined style={{ color: '#ff4d4f', fontSize: '18px', marginBottom: '8px' }} />
                <div style={{ color: '#ff4d4f', fontSize: '12px', marginBottom: '8px' }}>System Status Error</div>
                <Button 
                  type="link" 
                  size="small" 
                  onClick={() => fetchSystemData(true)}
                  icon={<ReloadOutlined />}
                >
                  Retry
                </Button>
              </div>
            ) : (
              <>
                <Statistic
                  title="System Status"
                  value={systemData?.cpuUsage ? 'Online' : 'Offline'}
                  valueStyle={{ 
                    color: systemData?.cpuUsage ? '#3f8600' : '#cf1322',
                    fontSize: '24px'
                  }}
                />
                <div style={{ marginTop: '8px', fontSize: '12px', color: '#666' }}>
                  Uptime: {systemData?.uptime || 'N/A'}
                </div>
              </>
            )}
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            {systemLoading ? (
              <div style={{ textAlign: 'center', padding: '20px' }}>
                <Spin size="small" />
              </div>
            ) : systemError ? (
              <div style={{ textAlign: 'center', padding: '10px' }}>
                <ExclamationCircleOutlined style={{ color: '#ff4d4f', fontSize: '18px', marginBottom: '8px' }} />
                <div style={{ color: '#ff4d4f', fontSize: '12px', marginBottom: '8px' }}>CPU Data Error</div>
                <Button 
                  type="link" 
                  size="small" 
                  onClick={() => fetchSystemData(true)}
                  icon={<ReloadOutlined />}
                >
                  Retry
                </Button>
              </div>
            ) : (
              <>
                <Statistic
                  title="CPU Usage"
                  value={safeToFixed(safeNumber(systemData?.cpuUsage), 1)}
                  suffix="%"
                  valueStyle={{ 
                    color: safeNumber(systemData?.cpuUsage) > 80 ? '#cf1322' : '#3f8600',
                    fontSize: '24px'
                  }}
                />
                <Progress 
                  percent={safeNumber(systemData?.cpuUsage)} 
                  size="small" 
                  showInfo={false}
                  strokeColor={safeNumber(systemData?.cpuUsage) > 80 ? '#cf1322' : '#3f8600'}
                />
              </>
            )}
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            {systemLoading ? (
              <div style={{ textAlign: 'center', padding: '20px' }}>
                <Spin size="small" />
              </div>
            ) : systemError ? (
              <div style={{ textAlign: 'center', padding: '10px' }}>
                <ExclamationCircleOutlined style={{ color: '#ff4d4f', fontSize: '18px', marginBottom: '8px' }} />
                <div style={{ color: '#ff4d4f', fontSize: '12px', marginBottom: '8px' }}>Memory Data Error</div>
                <Button 
                  type="link" 
                  size="small" 
                  onClick={() => fetchSystemData(true)}
                  icon={<ReloadOutlined />}
                >
                  Retry
                </Button>
              </div>
            ) : (
              <>
                <Statistic
                  title="Memory Usage"
                  value={safeToFixed(safeNumber(systemData?.memoryUsage), 1)}
                  suffix="%"
                  valueStyle={{ 
                    color: safeNumber(systemData?.memoryUsage) > 80 ? '#cf1322' : '#3f8600',
                    fontSize: '24px'
                  }}
                />
                <Progress 
                  percent={safeNumber(systemData?.memoryUsage)} 
                  size="small" 
                  showInfo={false}
                  strokeColor={safeNumber(systemData?.memoryUsage) > 80 ? '#cf1322' : '#3f8600'}
                />
              </>
            )}
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            {marketLoading ? (
              <div style={{ textAlign: 'center', padding: '20px' }}>
                <Spin size="small" />
              </div>
            ) : marketError ? (
              <div style={{ textAlign: 'center', padding: '10px' }}>
                <ExclamationCircleOutlined style={{ color: '#ff4d4f', fontSize: '18px', marginBottom: '8px' }} />
                <div style={{ color: '#ff4d4f', fontSize: '12px', marginBottom: '8px' }}>Market Data Error</div>
                <Button 
                  type="link" 
                  size="small" 
                  onClick={() => fetchMarketData(true)}
                  icon={<ReloadOutlined />}
                >
                  Retry
                </Button>
              </div>
            ) : (
              <>
                <Statistic
                  title="Active Stocks"
                  value={marketData.length}
                  valueStyle={{ fontSize: '24px' }}
                />
                <div style={{ marginTop: '8px', fontSize: '12px', color: '#666' }}>
                  Last update: {systemData?.lastUpdate || 'N/A'}
                </div>
              </>
            )}
          </Card>
        </Col>
      </Row>

      {/* 市场活动模块 */}
      <Row gutter={[16, 16]}>
        <Col span={12}>
          <Card 
            title="Recent Market Activity" 
            extra={
              <Button 
                type="text" 
                icon={<ReloadOutlined />} 
                onClick={() => fetchMarketData(true)}
                size="small"
                loading={marketLoading}
              />
            }
          >
            {marketLoading ? (
              <div style={{ textAlign: 'center', padding: '40px' }}>
                <Spin />
                <div style={{ marginTop: '16px', color: '#666' }}>Loading market data...</div>
              </div>
            ) : marketError ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <div>
                    <div style={{ color: '#ff4d4f', marginBottom: '8px' }}>Failed to load market data</div>
                    <Button type="primary" onClick={() => fetchMarketData(true)} icon={<ReloadOutlined />}>
                      Retry
                    </Button>
                  </div>
                }
              />
            ) : marketData.length > 0 ? (
              <>
                <Table
                  columns={stockColumns}
                  dataSource={marketData}
                  rowKey="symbol"
                  pagination={false}
                  size="small"
                  onRow={(record) => ({
                    onClick: () => navigate('/market'),
                    style: { cursor: 'pointer' }
                  })}
                />
                <div style={{ marginTop: '16px', textAlign: 'center' }}>
                  <Button type="link" onClick={handleViewMarket}>
                    View Full Market →
                  </Button>
                </div>
              </>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="No recent market data"
              >
                <Button type="primary" onClick={handleViewMarket}>
                  Go to Market
                </Button>
              </Empty>
            )}
          </Card>
        </Col>
        
        {/* 回测结果模块 */}
        <Col span={12}>
          <Card 
            title="Latest Backtest Result" 
            extra={
              <Space>
                <Button 
                  type="text" 
                  icon={<ReloadOutlined />} 
                  onClick={() => fetchBacktestHistory(true)}
                  loading={backtestLoading}
                  size="small"
                />
                <Button 
                  type="primary" 
                  size="small"
                  icon={<PlayCircleOutlined />}
                  onClick={handleRunBacktest}
                >
                  New Backtest
                </Button>
              </Space>
            }
          >
            {backtestLoading ? (
              <div style={{ textAlign: 'center', padding: '20px' }}>
                <Spin />
              </div>
            ) : backtestError ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <div>
                    <div style={{ color: '#ff4d4f', marginBottom: '8px' }}>Failed to load backtest history</div>
                    <Button type="primary" onClick={() => fetchBacktestHistory(true)} icon={<ReloadOutlined />}>
                      Retry
                    </Button>
                  </div>
                }
              />
            ) : latestBacktest ? (
              <div>
                <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                  <Col span={12}>
                    <div><strong>Symbol:</strong> {latestBacktest.symbol || 'Unknown'}</div>
                    <div><strong>Strategy:</strong> {latestBacktest.strategy || 'Unknown'}</div>
                    <div><strong>Period:</strong> {latestBacktest.startDate} to {latestBacktest.endDate}</div>
                    <div><strong>Capital:</strong> ${safeNumber(latestBacktest.initialCapital).toLocaleString()}</div>
                  </Col>
                  <Col span={12}>
                    <div style={{ textAlign: 'right' }}>
                      <Tag color={latestBacktest.status === 'completed' ? 'green' : 
                                 latestBacktest.status === 'running' ? 'blue' : 'red'}>
                        {latestBacktest.status?.toUpperCase()}
                      </Tag>
                    </div>
                    <div style={{ marginTop: '8px' }}>
                      <Statistic
                        title="Total Return"
                        value={safeNumber(latestBacktest.totalReturn)}
                        suffix="%"
                        valueStyle={{ 
                          color: safeNumber(latestBacktest.totalReturn) >= 0 ? '#3f8600' : '#cf1322',
                          fontSize: '24px'
                        }}
                      />
                    </div>
                  </Col>
                </Row>
                
                <Row gutter={[16, 16]}>
                  <Col span={8}>
                    <Statistic
                      title="Sharpe Ratio"
                      value={safeToFixed(safeNumber(latestBacktest.sharpeRatio), 2)}
                      valueStyle={{ 
                        color: safeNumber(latestBacktest.sharpeRatio) >= 1 ? '#3f8600' : 
                               safeNumber(latestBacktest.sharpeRatio) >= 0 ? '#faad14' : '#cf1322',
                        fontSize: '18px'
                      }}
                    />
                  </Col>
                  <Col span={8}>
                    <Statistic
                      title="Max Drawdown"
                      value={safeToFixed(safeNumber(latestBacktest.maxDrawdown), 2)}
                      suffix="%"
                      valueStyle={{ 
                        color: '#cf1322',
                        fontSize: '18px'
                      }}
                    />
                  </Col>
                  <Col span={8}>
                    <Statistic
                      title="Win Rate"
                      value={safeToFixed(safeNumber(latestBacktest.winRate), 1)}
                      suffix="%"
                      valueStyle={{ 
                        color: safeNumber(latestBacktest.winRate) >= 60 ? '#3f8600' : 
                               safeNumber(latestBacktest.winRate) >= 40 ? '#faad14' : '#cf1322',
                        fontSize: '18px'
                      }}
                    />
                  </Col>
                </Row>
                
                <div style={{ marginTop: '16px', textAlign: 'center' }}>
                  <Space>
                    <Button 
                      type="primary"
                      icon={<EyeOutlined />}
                      onClick={() => latestBacktest.backtestId && handleViewBacktest(latestBacktest.backtestId)}
                    >
                      View Details
                    </Button>
                    <Button 
                      type="default"
                      onClick={() => navigate('/analysis')}
                    >
                      Analyze Results
                    </Button>
                  </Space>
                </div>
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="No backtest history yet"
              >
                <Button type="primary" onClick={handleRunBacktest}>
                  Run Your First Backtest
                </Button>
              </Empty>
            )}
          </Card>
        </Col>
      </Row>

      {/* 快速操作 */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Quick Actions" size="small">
            <Row gutter={16}>
              <Col span={6}>
                <Button 
                  type="default" 
                  block
                  icon={<LineChartOutlined />}
                  onClick={handleViewMarket}
                >
                  Browse Market
                </Button>
              </Col>
              <Col span={6}>
                <Button 
                  type="default" 
                  block
                  icon={<PlayCircleOutlined />}
                  onClick={handleRunBacktest}
                >
                  Run Backtest
                </Button>
              </Col>
              <Col span={6}>
                <Button 
                  type="default" 
                  block
                  onClick={handleViewAnalysis}
                >
                  View Analytics
                </Button>
              </Col>
              <Col span={6}>
                <Button 
                  type="default" 
                  block
                  onClick={fetchDashboardData}
                  icon={<ReloadOutlined />}
                >
                  Refresh Dashboard
                </Button>
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Dashboard;