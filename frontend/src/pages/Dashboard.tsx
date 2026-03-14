import React, { useState, useEffect } from 'react';
import { Card, Row, Col, Statistic, Table, Tag, Progress, Alert, Button, Space, Spin, Empty, message } from 'antd';
import { ArrowUpOutlined, ArrowDownOutlined, LineChartOutlined, PlayCircleOutlined, EyeOutlined, ReloadOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import { Server, Cpu, MemoryStick, TrendingUp, TrendingDown, Target, Award, BarChart3, LineChart, DollarSign, TrendingUp as TrendingUpIcon, TrendingDown as TrendingDownIcon, Building2, Hash, Search, PlayCircle, BarChart, RefreshCw, Layers, History, Trophy, Percent } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { systemAPI, marketAPI, backtraderAPI } from '../services/api';
import { useLanguage } from '../contexts/LanguageContext';

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
  const { t } = useLanguage();
  
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
    navigate('/analytics');
  };

  const stockColumns = [
    {
      title: (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Hash size={14} color="#666" />
          <span style={{ fontSize: '14px', fontWeight: '600', color: '#333' }}>SYMBOL</span>
        </div>
      ),
      dataIndex: 'symbol',
      key: 'symbol',
      width: 90,
      render: (symbol: string) => (
        <div style={{ 
          fontWeight: '600', 
          fontSize: '14px',
          color: '#333',
          letterSpacing: '0.3px'
        }}>
          {symbol}
        </div>
      ),
      align: 'left' as const,
    },
    {
      title: (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Building2 size={14} color="#666" />
          <span style={{ fontSize: '14px', fontWeight: '600', color: '#333' }}>NAME</span>
        </div>
      ),
      dataIndex: 'name',
      key: 'name',
      width: 140,
      render: (name: string) => (
        <div style={{ 
          fontSize: '14px',
          color: '#555',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis'
        }}>
          {name}
        </div>
      ),
      align: 'left' as const,
    },
    {
      title: (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <DollarSign size={14} color="#666" />
          <span style={{ fontSize: '14px', fontWeight: '600', color: '#333' }}>PRICE</span>
        </div>
      ),
      dataIndex: 'price',
      key: 'price',
      width: 100,
      render: (price: number) => (
        <div style={{ 
          textAlign: 'right',
          fontFamily: "'Roboto Mono', monospace",
          fontSize: '14px',
          fontWeight: '500',
          color: '#333'
        }}>
          ${safeToFixed(price, 2)}
        </div>
      ),
      align: 'right' as const,
    },
    {
      title: (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <TrendingUpIcon size={14} color="#666" />
          <span style={{ fontSize: '14px', fontWeight: '600', color: '#333' }}>CHANGE %</span>
        </div>
      ),
      dataIndex: 'changePercent',
      key: 'changePercent',
      width: 110,
      render: (percent: number) => {
        const safePercent = safeNumber(percent);
        const isPositive = safePercent >= 0;
        return (
          <div style={{ 
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            gap: '4px'
          }}>
            {isPositive ? (
              <TrendingUpIcon size={12} color="#34a853" />
            ) : (
              <TrendingDownIcon size={12} color="#ea4335" />
            )}
            <div style={{ 
              fontFamily: "'Roboto Mono', monospace",
              fontSize: '14px',
              fontWeight: '600',
              color: isPositive ? '#34a853' : '#ea4335',
              textAlign: 'right'
            }}>
              {isPositive ? '+' : ''}{safeToFixed(safePercent, 2)}%
            </div>
          </div>
        );
      },
      align: 'right' as const,
    },
    {
      title: (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <TrendingUp size={14} color="#666" />
          <span style={{ fontSize: '14px', fontWeight: '600', color: '#333' }}>MKT CAP</span>
        </div>
      ),
      dataIndex: 'marketCap',
      key: 'marketCap',
      width: 110,
      render: (cap: number) => (
        <div style={{ 
          textAlign: 'right',
          fontFamily: "'Roboto Mono', monospace",
          fontSize: '14px',
          fontWeight: '500',
          color: '#666'
        }}>
          {formatCurrency(cap)}
        </div>
      ),
      align: 'right' as const,
    },
  ];

  // 计算最佳夏普比率
  const getBestSharpeRatio = () => {
    if (backtestData.length === 0) return 0;
    let bestSharpe = -Infinity;
    backtestData.forEach(item => {
      if (item.results?.sharpeRatio && item.results.sharpeRatio > bestSharpe) {
        bestSharpe = item.results.sharpeRatio;
      }
    });
    return bestSharpe === -Infinity ? 0 : bestSharpe;
  };

  // 计算平均收益率
  const getAverageReturn = () => {
    if (backtestData.length === 0) return 0;
    let totalReturn = 0;
    let count = 0;
    backtestData.forEach(item => {
      if (item.results?.totalReturn !== undefined) {
        totalReturn += item.results.totalReturn;
        count++;
      }
    });
    return count > 0 ? totalReturn / count : 0;
  };

  const getLatestBacktest = () => {
    if (backtestData.length === 0) return null;
    return backtestData[0];
  };

  const latestBacktest = getLatestBacktest();

  return (
    <div>
      <h1 style={{ marginBottom: 24, fontSize: '28px', fontWeight: '600' }}>
        <LineChartOutlined /> {t.dashboard.title}
      </h1>
      <div style={{ color: '#666', fontSize: '16px', marginBottom: '24px' }}>
        {t.dashboard.subtitle}
      </div>

      {/* 系统状态模块 - 优化版 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24, alignItems: 'stretch' }}>
        {/* 卡片1: Total Strategies */}
        <Col span={6} style={{ display: 'flex' }}>
          <Card 
            size="small"
            style={{ width: '100%', minHeight: '140px' }}
            styles={{
              body: { 
                padding: '16px',
                display: 'flex',
                flexDirection: 'column',
                height: '100%'
              }
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
              <div style={{ 
                background: 'rgba(66, 133, 244, 0.1)', 
                borderRadius: '8px',
                padding: '8px',
                marginRight: '12px'
              }}>
                <Layers size={20} color="#4285f4" />
              </div>
              <div>
                <div style={{ fontSize: '14px', color: '#666', fontWeight: '500' }}>Total Strategies</div>
                <div style={{ 
                  fontSize: '22px', 
                  fontWeight: '600',
                  color: '#4285f4'
                }}>
                  3
                </div>
              </div>
            </div>
            <div style={{ flex: 1, minHeight: '20px' }}></div>
            <div style={{ fontSize: '11px', color: '#888', marginTop: 'auto', flexShrink: 0 }}>
              Active: moving_average, RSI, MACD
            </div>
          </Card>
        </Col>

        {/* 卡片2: Backtests Run */}
        <Col span={6} style={{ display: 'flex' }}>
          <Card 
            size="small"
            style={{ width: '100%', minHeight: '140px' }}
            styles={{
              body: { 
                padding: '16px',
                display: 'flex',
                flexDirection: 'column',
                height: '100%'
              }
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
              <div style={{ 
                background: 'rgba(52, 168, 83, 0.1)', 
                borderRadius: '8px',
                padding: '8px',
                marginRight: '12px'
              }}>
                <History size={20} color="#34a853" />
              </div>
              <div>
                <div style={{ fontSize: '14px', color: '#666', fontWeight: '500' }}>Backtests Run</div>
                <div style={{ 
                  fontSize: '22px', 
                  fontWeight: '600',
                  color: '#34a853'
                }}>
                  {backtestData.length}
                </div>
              </div>
            </div>
            <div style={{ flex: 1, minHeight: '20px' }}></div>
            <div style={{ fontSize: '11px', color: '#888', marginTop: 'auto', flexShrink: 0 }}>
              Last 30 days: {backtestData.length}
            </div>
          </Card>
        </Col>

        {/* 卡片3: Best Sharpe Ratio */}
        <Col span={6} style={{ display: 'flex' }}>
          <Card 
            size="small"
            style={{ width: '100%', minHeight: '140px' }}
            styles={{
              body: { 
                padding: '16px',
                display: 'flex',
                flexDirection: 'column',
                height: '100%'
              }
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
              <div style={{ 
                background: 'rgba(251, 188, 5, 0.1)', 
                borderRadius: '8px',
                padding: '8px',
                marginRight: '12px'
              }}>
                <Trophy size={20} color="#fbbc05" />
              </div>
              <div>
                <div style={{ fontSize: '14px', color: '#666', fontWeight: '500' }}>Best Sharpe Ratio</div>
                <div style={{ 
                  fontSize: '22px', 
                  fontWeight: '600',
                  color: '#fbbc05'
                }}>
                  {safeToFixed(getBestSharpeRatio(), 2)}
                </div>
              </div>
            </div>
            <div style={{ flex: 1, minHeight: '20px' }}></div>
            <div style={{ fontSize: '11px', color: '#888', marginTop: 'auto', flexShrink: 0 }}>
              From {backtestData.length} backtests
            </div>
          </Card>
        </Col>

        {/* 卡片4: Avg Return */}
        <Col span={6} style={{ display: 'flex' }}>
          <Card 
            size="small"
            style={{ width: '100%', minHeight: '140px' }}
            styles={{
              body: { 
                padding: '16px',
                display: 'flex',
                flexDirection: 'column',
                height: '100%'
              }
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
              <div style={{ 
                background: getAverageReturn() >= 0 ? 'rgba(52, 168, 83, 0.1)' : 'rgba(234, 67, 53, 0.1)', 
                borderRadius: '8px',
                padding: '8px',
                marginRight: '12px'
              }}>
                <Percent size={20} color={getAverageReturn() >= 0 ? '#34a853' : '#ea4335'} />
              </div>
              <div>
                <div style={{ fontSize: '14px', color: '#666', fontWeight: '500' }}>Avg Return</div>
                <div style={{ 
                  fontSize: '22px', 
                  fontWeight: '600',
                  color: getAverageReturn() >= 0 ? '#34a853' : '#ea4335'
                }}>
                  {getAverageReturn() >= 0 ? '+' : ''}{safeToFixed(getAverageReturn(), 2)}%
                </div>
              </div>
            </div>
            <div style={{ flex: 1, minHeight: '20px' }}></div>
            <div style={{ fontSize: '11px', color: '#888', marginTop: 'auto', flexShrink: 0 }}>
              Across all backtests
            </div>
          </Card>
        </Col>
      </Row>

      {/* 市场活动模块 - 优化版 */}
      <Row gutter={[16, 16]}>
        <Col span={12}>
          <Card 
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{ 
                  background: 'rgba(66, 133, 244, 0.1)', 
                  borderRadius: '6px',
                  padding: '4px'
                }}>
                  <TrendingUp size={16} color="#4285f4" />
                </div>
                <span style={{ fontSize: '18px', fontWeight: '600', color: '#333' }}>
                  Recent Market Activity
                </span>
              </div>
            }
            extra={
              <Button 
                type="text" 
                icon={<ReloadOutlined />} 
                onClick={() => fetchMarketData(true)}
                size="small"
                loading={marketLoading}
                style={{ 
                  color: '#666',
                  fontWeight: '500'
                }}
              >
                Refresh
              </Button>
            }
            styles={{
              body: { padding: '0' }
            }}
          >
            {marketLoading ? (
              <div style={{ 
                textAlign: 'center', 
                padding: '48px 24px',
                background: '#fafafa'
              }}>
                <Spin size="large" />
                <div style={{ 
                  marginTop: '16px', 
                  fontSize: '14px', 
                  color: '#666',
                  fontWeight: '500'
                }}>
                  Loading market data...
                </div>
                <div style={{ 
                  marginTop: '8px', 
                  fontSize: '12px', 
                  color: '#999'
                }}>
                  Fetching real-time stock prices
                </div>
              </div>
            ) : marketError ? (
              <div style={{ 
                textAlign: 'center', 
                padding: '40px 24px',
                background: '#fafafa'
              }}>
                <ExclamationCircleOutlined style={{ 
                  color: '#ea4335', 
                  fontSize: '32px', 
                  marginBottom: '16px' 
                }} />
                <div style={{ 
                  fontSize: '14px', 
                  color: '#ea4335',
                  fontWeight: '600',
                  marginBottom: '8px'
                }}>
                  Failed to load market data
                </div>
                <div style={{ 
                  fontSize: '12px', 
                  color: '#999',
                  marginBottom: '20px',
                  maxWidth: '300px',
                  margin: '0 auto 20px'
                }}>
                  Unable to connect to market data service. Please check your connection.
                </div>
                <Button 
                  type="primary" 
                  onClick={() => fetchMarketData(true)} 
                  icon={<ReloadOutlined />}
                  size="middle"
                >
                  Retry Connection
                </Button>
              </div>
            ) : marketData.length > 0 ? (
              <>
                <div style={{ 
                  background: '#f8f9fa',
                  borderBottom: '1px solid #f0f0f0',
                  padding: '12px 16px'
                }}>
                  <div style={{ 
                    display: 'flex', 
                    justifyContent: 'space-between',
                    alignItems: 'center'
                  }}>
                    <div style={{ fontSize: '12px', color: '#666' }}>
                      Showing {marketData.length} active stocks
                    </div>
                    <div style={{ fontSize: '11px', color: '#999' }}>
                      Real-time data
                    </div>
                  </div>
                </div>
                <Table
                  columns={stockColumns}
                  dataSource={marketData}
                  rowKey="symbol"
                  pagination={false}
                  size="middle"
                  onRow={(record) => ({
                    onClick: () => navigate('/market'),
                    style: { 
                      cursor: 'pointer',
                      background: '#fff'
                    }
                  })}
                  rowClassName={() => 'market-table-row'}
                  style={{ 
                    border: 'none',
                    borderRadius: '0'
                  }}
                  components={{
                    header: {
                      cell: (props: any) => (
                        <th {...props} style={{ 
                          ...props.style,
                          background: '#f8f9fa',
                          borderBottom: '2px solid #e8e8e8',
                          padding: '12px 16px',
                          fontWeight: '600'
                        }} />
                      ),
                    },
                    body: {
                      cell: (props: any) => (
                        <td {...props} style={{ 
                          ...props.style,
                          padding: '12px 16px',
                          borderBottom: '1px solid #f5f5f5'
                        }} />
                      ),
                    },
                  }}
                />
                <div style={{ 
                  padding: '16px',
                  borderTop: '1px solid #f0f0f0',
                  background: '#fafafa',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center'
                }}>
                  <div style={{ fontSize: '12px', color: '#666' }}>
                    Click any row to view detailed analysis
                  </div>
                  <Button 
                    type="primary" 
                    onClick={handleViewMarket}
                    size="small"
                    style={{ 
                      fontWeight: '500',
                      background: '#4285f4',
                      borderColor: '#4285f4'
                    }}
                  >
                    View Full Market Dashboard
                  </Button>
                </div>
              </>
            ) : (
              <div style={{ 
                textAlign: 'center', 
                padding: '48px 24px',
                background: '#fafafa'
              }}>
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={
                    <div>
                      <div style={{ 
                        fontSize: '14px', 
                        color: '#666',
                        fontWeight: '600',
                        marginBottom: '8px'
                      }}>
                        No recent market data
                      </div>
                      <div style={{ 
                        fontSize: '12px', 
                        color: '#999',
                        marginBottom: '20px'
                      }}>
                        Market data service is currently unavailable
                      </div>
                    </div>
                  }
                />
                <Button 
                  type="primary" 
                  onClick={handleViewMarket}
                  size="middle"
                  style={{ marginTop: '16px' }}
                >
                  Go to Market Overview
                </Button>
              </div>
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
                {/* 基本信息行 */}
                <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
                  <Col span={12}>
                    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
                      <div style={{ 
                        background: 'rgba(66, 133, 244, 0.1)', 
                        borderRadius: '6px',
                        padding: '4px',
                        marginRight: '10px'
                      }}>
                        <Target size={14} color="#4285f4" />
                      </div>
                      <div>
                        <div style={{ fontSize: '24px', fontWeight: '600', color: '#333' }}>
                          {latestBacktest.symbol || 'Unknown'}
                        </div>
                        <div style={{ fontSize: '16px', color: '#666' }}>
                          {latestBacktest.strategy || 'Unknown'} Strategy
                        </div>
                      </div>
                    </div>
                    <div style={{ fontSize: '16px', color: '#666', lineHeight: '1.6' }}>
                      <div>Period: {latestBacktest.startDate} to {latestBacktest.endDate}</div>
                      <div>Capital: ${safeNumber(latestBacktest.initialCapital).toLocaleString()}</div>
                    </div>
                  </Col>
                  <Col span={12}>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
                      <div style={{
                        background: latestBacktest.status === 'completed' ? 'rgba(52, 168, 83, 0.1)' : 
                                   latestBacktest.status === 'running' ? 'rgba(66, 133, 244, 0.1)' : 'rgba(234, 67, 53, 0.1)',
                        borderRadius: '12px',
                        padding: '4px 12px',
                        fontSize: '11px',
                        fontWeight: '600',
                        color: latestBacktest.status === 'completed' ? '#34a853' : 
                               latestBacktest.status === 'running' ? '#4285f4' : '#ea4335',
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px'
                      }}>
                        {latestBacktest.status || 'UNKNOWN'}
                      </div>
                    </div>
                    
                    {/* 强化 Total Return 主指标 */}
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '16px', color: '#666', marginBottom: '4px' }}>Total Return</div>
                      <div style={{ 
                        fontSize: '32px', 
                        fontWeight: '700',
                        color: safeNumber(latestBacktest.totalReturn) >= 0 ? '#34a853' : '#ea4335',
                        lineHeight: '1.2'
                      }}>
                        {safeNumber(latestBacktest.totalReturn) >= 0 ? '+' : ''}{safeToFixed(safeNumber(latestBacktest.totalReturn), 2)}%
                      </div>
                      <div style={{ 
                        fontSize: '15px', 
                        color: safeNumber(latestBacktest.totalReturn) >= 0 ? '#34a853' : '#ea4335',
                        marginTop: '4px'
                      }}>
                        {safeNumber(latestBacktest.totalReturn) >= 0 ? 'Profit' : 'Loss'}
                      </div>
                    </div>
                  </Col>
                </Row>
                
                {/* 三个关键指标行 - 统一排版 */}
                <div style={{ 
                  background: '#f8f9fa', 
                  borderRadius: '8px',
                  padding: '16px',
                  marginBottom: '20px'
                }}>
                  <div style={{ fontSize: '16px', color: '#666', fontWeight: '600', marginBottom: '12px' }}>
                    Performance Metrics
                  </div>
                  <Row gutter={[16, 8]}>
                    <Col span={8}>
                      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
                        <div style={{ marginRight: '8px' }}>
                          <LineChart size={14} color={safeNumber(latestBacktest.sharpeRatio) >= 1 ? '#34a853' : 
                                                      safeNumber(latestBacktest.sharpeRatio) >= 0 ? '#faad14' : '#ea4335'} />
                        </div>
                        <div style={{ fontSize: '14px', color: '#666' }}>Sharpe</div>
                      </div>
                      <div style={{ 
                        fontSize: '24px', 
                        fontWeight: '600',
                        color: safeNumber(latestBacktest.sharpeRatio) >= 1 ? '#34a853' : 
                               safeNumber(latestBacktest.sharpeRatio) >= 0 ? '#faad14' : '#ea4335'
                      }}>
                        {safeToFixed(safeNumber(latestBacktest.sharpeRatio), 2)}
                      </div>
                    </Col>
                    <Col span={8}>
                      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
                        <div style={{ marginRight: '8px' }}>
                          <TrendingDown size={14} color="#ea4335" />
                        </div>
                        <div style={{ fontSize: '14px', color: '#666' }}>Max DD</div>
                      </div>
                      <div style={{ 
                        fontSize: '24px', 
                        fontWeight: '600',
                        color: '#ea4335'
                      }}>
                        {safeToFixed(safeNumber(latestBacktest.maxDrawdown), 2)}%
                      </div>
                    </Col>
                    <Col span={8}>
                      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
                        <div style={{ marginRight: '8px' }}>
                          <Award size={14} color={safeNumber(latestBacktest.winRate) >= 60 ? '#34a853' : 
                                                  safeNumber(latestBacktest.winRate) >= 40 ? '#faad14' : '#ea4335'} />
                        </div>
                        <div style={{ fontSize: '14px', color: '#666' }}>Win Rate</div>
                      </div>
                      <div style={{ 
                        fontSize: '24px', 
                        fontWeight: '600',
                        color: safeNumber(latestBacktest.winRate) >= 60 ? '#34a853' : 
                               safeNumber(latestBacktest.winRate) >= 40 ? '#faad14' : '#ea4335'
                      }}>
                        {safeToFixed(safeNumber(latestBacktest.winRate), 1)}%
                      </div>
                    </Col>
                  </Row>
                </div>
                
                {/* 按钮区 - 更整齐专业 */}
                <div style={{ 
                  display: 'flex', 
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  paddingTop: '16px',
                  borderTop: '1px solid #f0f0f0'
                }}>
                  <div style={{ fontSize: '13px', color: '#888' }}>
                    Backtest ID: {latestBacktest.backtestId?.substring(0, 8) || 'N/A'}
                  </div>
                  <Space>
                    <Button 
                      type="primary"
                      size="small"
                      icon={<EyeOutlined />}
                      onClick={() => latestBacktest.backtestId && handleViewBacktest(latestBacktest.backtestId)}
                      style={{ 
                        background: '#4285f4',
                        borderColor: '#4285f4',
                        fontWeight: '500',
                        fontSize: '14px'
                      }}
                    >
                      View Details
                    </Button>
                    <Button 
                      type="default"
                      size="small"
                      icon={<BarChart3 size={14} />}
                      onClick={() => latestBacktest.backtestId && navigate(`/analytics?backtestId=${latestBacktest.backtestId}`)}
                      style={{ fontWeight: '500', fontSize: '14px' }}
                    >
                      Analyze
                    </Button>
                  </Space>
                </div>
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: '14px', color: '#666', marginBottom: '8px' }}>No backtest history yet</div>
                    <div style={{ fontSize: '12px', color: '#999', marginBottom: '16px' }}>
                      Run your first backtest to see results here
                    </div>
                    <Button 
                      type="primary" 
                      onClick={handleRunBacktest}
                      icon={<PlayCircleOutlined />}
                      style={{ fontWeight: '500' }}
                    >
                      Run First Backtest
                    </Button>
                  </div>
                }
              />
            )}
          </Card>
        </Col>
      </Row>

      {/* 快速操作 - 优化版 */}
      <Row gutter={[16, 16]} style={{ marginTop: 24 }}>
        <Col span={24}>
          <Card 
            title={
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div style={{ 
                  background: 'rgba(66, 133, 244, 0.1)', 
                  borderRadius: '6px',
                  padding: '4px'
                }}>
                  <PlayCircle size={16} color="#4285f4" />
                </div>
                <span style={{ fontSize: '16px', fontWeight: '600', color: '#333' }}>
                  Quick Actions
                </span>
              </div>
            }
            styles={{
              body: { padding: '20px 24px' }
            }}
          >
            <Row gutter={[20, 16]}>
              <Col span={6}>
                <Button 
                  type="default" 
                  block
                  icon={<Search size={16} />}
                  onClick={handleViewMarket}
                  style={{ 
                    height: '44px',
                    fontSize: '14px',
                    fontWeight: '500',
                    color: '#333',
                    borderColor: '#d9d9d9',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '8px'
                  }}
                >
                  Browse Market
                </Button>
                <div style={{ 
                  fontSize: '12px', 
                  color: '#666', 
                  marginTop: '8px',
                  textAlign: 'center'
                }}>
                  Explore stocks & trends
                </div>
              </Col>
              <Col span={6}>
                <Button 
                  type="default" 
                  block
                  icon={<PlayCircle size={16} />}
                  onClick={handleRunBacktest}
                  style={{ 
                    height: '44px',
                    fontSize: '14px',
                    fontWeight: '500',
                    color: '#333',
                    borderColor: '#d9d9d9',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '8px'
                  }}
                >
                  Run Backtest
                </Button>
                <div style={{ 
                  fontSize: '12px', 
                  color: '#666', 
                  marginTop: '8px',
                  textAlign: 'center'
                }}>
                  Test strategies
                </div>
              </Col>
              <Col span={6}>
                <Button 
                  type="default" 
                  block
                  icon={<BarChart size={16} />}
                  onClick={handleViewAnalysis}
                  style={{ 
                    height: '44px',
                    fontSize: '14px',
                    fontWeight: '500',
                    color: '#333',
                    borderColor: '#d9d9d9',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '8px'
                  }}
                >
                  View Analytics
                </Button>
                <div style={{ 
                  fontSize: '12px', 
                  color: '#666', 
                  marginTop: '8px',
                  textAlign: 'center'
                }}>
                  Performance insights
                </div>
              </Col>
              <Col span={6}>
                <Button 
                  type="default" 
                  block
                  icon={<RefreshCw size={16} />}
                  onClick={fetchDashboardData}
                  style={{ 
                    height: '44px',
                    fontSize: '14px',
                    fontWeight: '500',
                    color: '#333',
                    borderColor: '#d9d9d9',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '8px'
                  }}
                >
                  Refresh Dashboard
                </Button>
                <div style={{ 
                  fontSize: '12px', 
                  color: '#666', 
                  marginTop: '8px',
                  textAlign: 'center'
                }}>
                  Update all data
                </div>
              </Col>
            </Row>
            <div style={{ 
              marginTop: '20px',
              paddingTop: '16px',
              borderTop: '1px solid #f0f0f0',
              fontSize: '12px',
              color: '#999',
              textAlign: 'center'
            }}>
              Click any action to navigate or refresh dashboard data
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Dashboard;