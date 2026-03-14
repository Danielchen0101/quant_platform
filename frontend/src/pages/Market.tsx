import React, { useState, useEffect } from 'react';
import { Card, Table, Tag, Input, Select, Button, Row, Col, Statistic, Space, Alert, message, Empty, Spin } from 'antd';
import { SearchOutlined, LineChartOutlined, PlayCircleOutlined, BarChartOutlined, ReloadOutlined, EyeOutlined, StarOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { marketAPI } from '../services/api';
import { useLanguage } from '../contexts/LanguageContext';

const { Option } = Select;

interface Stock {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  marketCap: number;
  sector: string;
  // PE 相关字段，支持多种可能的字段名
  peRatio?: number;        // 通用 PE 字段
  trailingPE?: number;     // 追踪市盈率（Yahoo Finance 常用）
  forwardPE?: number;      // 预期市盈率
  pe?: number;             // 简写 PE
}

const Market: React.FC = () => {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [filteredStocks, setFilteredStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');
  const [searchText, setSearchText] = useState('');
  const [selectedSector, setSelectedSector] = useState<string>('all');
  const [sortField, setSortField] = useState<string>('symbol');
  const [sortOrder, setSortOrder] = useState<'ascend' | 'descend'>('ascend');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [searching, setSearching] = useState(false);
  const [watchlist, setWatchlist] = useState<any[]>([]);
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

  const formatVolume = (value: number): string => {
    const safeValue = safeNumber(value);
    if (safeValue >= 1e9) {
      return `${safeToFixed(safeValue / 1e9, 1)}B`;
    } else if (safeValue >= 1e6) {
      return `${safeToFixed(safeValue / 1e6, 1)}M`;
    } else if (safeValue >= 1e3) {
      return `${safeToFixed(safeValue / 1e3, 1)}K`;
    }
    return safeToFixed(safeValue, 0);
  };

  useEffect(() => {
    fetchMarketData();
    loadWatchlist();
  }, []);

  const loadWatchlist = () => {
    try {
      const saved = localStorage.getItem('quant_watchlist');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          setWatchlist(parsed);
        }
      }
    } catch (err) {
      console.error('Failed to load watchlist:', err);
      setWatchlist([]);
    }
  };

  const isInWatchlist = (symbol: string): boolean => {
    return watchlist.some(item => item.symbol === symbol);
  };

  // 计算 sector 分布
  const getSectorDistribution = () => {
    const sectorCounts: Record<string, number> = {};
    const totalStocks = stocks.length;
    
    // 统计每个 sector 的数量
    stocks.forEach(stock => {
      const sector = stock.sector || 'Unknown';
      sectorCounts[sector] = (sectorCounts[sector] || 0) + 1;
    });
    
    // 转换为数组并排序（数量多的在前）
    const distribution = Object.entries(sectorCounts)
      .map(([sector, count]) => ({
        sector,
        count,
        percentage: totalStocks > 0 ? (count / totalStocks * 100) : 0
      }))
      .sort((a, b) => b.count - a.count); // 按数量降序排序
    
    return distribution;
  };

  useEffect(() => {
    filterAndSortStocks();
    
    // 检查是否需要搜索新股票
    const checkAndSearchStock = async () => {
      const symbol = searchText.trim().toUpperCase();
      if (symbol && /^[A-Z]{1,5}$/.test(symbol)) {
        // 检查是否已经在 stocks 列表中
        const existingStock = stocks.find(s => s.symbol.toUpperCase() === symbol);
        if (!existingStock) {
          // 如果不在列表中，自动搜索
          await searchStockBySymbol(symbol);
        }
      }
    };
    
    // 添加延迟，避免频繁搜索
    const timer = setTimeout(() => {
      checkAndSearchStock();
    }, 1000);
    
    return () => clearTimeout(timer);
  }, [stocks, searchText, selectedSector, sortField, sortOrder]);

  const fetchMarketData = async () => {
    try {
      setLoading(true);
      const response = await marketAPI.getStocks();
      
      if (response.data && response.data.stocks) {
        const stockData = response.data.stocks;
        
        // 调试：检查第一个股票的字段
        if (stockData.length > 0) {
          console.log('=== Market API Response Sample ===');
          console.log('First stock fields:', Object.keys(stockData[0]));
          console.log('First stock data:', stockData[0]);
          
          // 检查 PE 相关字段
          const firstStock = stockData[0];
          const peFields = ['peRatio', 'trailingPE', 'forwardPE', 'pe'];
          const foundPeFields = peFields.filter(field => field in firstStock);
          console.log('Available PE fields:', foundPeFields);
          if (foundPeFields.length > 0) {
            foundPeFields.forEach(field => {
              console.log(`${field}:`, firstStock[field as keyof typeof firstStock]);
            });
          } else {
            console.log('No PE fields found in API response');
          }
        }
        
        setStocks(stockData);
        setLastUpdated(new Date());
        setError('');
        message.success('Market data refreshed');
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

  const searchStockBySymbol = async (symbol: string) => {
    // 检查是否已经是有效的股票 symbol（全大写字母，长度 1-5）
    const isValidSymbol = /^[A-Z]{1,5}$/.test(symbol);
    if (!isValidSymbol) {
      return false;
    }
    
    // 检查是否已经在 stocks 列表中
    const existingStock = stocks.find(s => s.symbol.toUpperCase() === symbol.toUpperCase());
    if (existingStock) {
      return true;
    }
    
    try {
      setSearching(true);
      // 尝试调用 API 获取该股票数据
      // 注意：这里假设后端有相应的 API，如果没有，我们可以模拟数据
      const response = await marketAPI.getStockHistory(symbol);
      
      if (response.data && response.data.symbol) {
        // 从历史数据中提取最新价格信息
        const stockData = response.data;
        const newStock: Stock = {
          symbol: stockData.symbol || symbol,
          name: stockData.name || `${symbol} Inc.`,
          price: stockData.lastPrice || 0,
          change: stockData.change || 0,
          changePercent: stockData.changePercent || 0,
          volume: stockData.volume || 0,
          marketCap: stockData.marketCap || 0,
          sector: stockData.sector || 'Technology'
        };
        
        // 添加到 stocks 列表
        setStocks(prev => [...prev, newStock]);
        message.success(`Added ${symbol} to market data`);
        return true;
      } else {
        // 如果 API 没有返回数据，创建一个模拟的股票
        const mockStock: Stock = {
          symbol: symbol,
          name: `${symbol} Inc.`,
          price: 100 + Math.random() * 100,
          change: (Math.random() - 0.5) * 10,
          changePercent: (Math.random() - 0.5) * 5,
          volume: Math.floor(Math.random() * 10000000),
          marketCap: Math.floor(Math.random() * 1000000000),
          sector: 'Technology'
        };
        
        setStocks(prev => [...prev, mockStock]);
        message.info(`Added ${symbol} with simulated data`);
        return true;
      }
    } catch (error) {
      console.error(`Failed to fetch data for ${symbol}:`, error);
      
      // 如果 API 调用失败，创建一个模拟的股票
      const mockStock: Stock = {
        symbol: symbol,
        name: `${symbol} Inc.`,
        price: 100 + Math.random() * 100,
        change: (Math.random() - 0.5) * 10,
        changePercent: (Math.random() - 0.5) * 5,
        volume: Math.floor(Math.random() * 10000000),
        marketCap: Math.floor(Math.random() * 1000000000),
        sector: 'Technology'
      };
      
      setStocks(prev => [...prev, mockStock]);
      message.info(`Added ${symbol} with simulated data (API unavailable)`);
      return true;
    } finally {
      setSearching(false);
    }
  };

  const filterAndSortStocks = () => {
    let filtered = [...stocks];
    
    // 搜索过滤
    if (searchText) {
      const searchLower = searchText.toLowerCase();
      filtered = filtered.filter(stock =>
        stock.symbol.toLowerCase().includes(searchLower) ||
        stock.name.toLowerCase().includes(searchLower)
      );
    }
    
    // 行业过滤
    if (selectedSector !== 'all') {
      filtered = filtered.filter(stock => stock.sector === selectedSector);
    }
    
    // 排序
    filtered.sort((a, b) => {
      let aValue: any = a[sortField as keyof Stock];
      let bValue: any = b[sortField as keyof Stock];
      
      if (sortField === 'marketCap' || sortField === 'price' || sortField === 'volume' || sortField === 'change' || sortField === 'changePercent') {
        aValue = safeNumber(aValue);
        bValue = safeNumber(bValue);
      }
      
      if (sortOrder === 'ascend') {
        return aValue > bValue ? 1 : -1;
      } else {
        return aValue < bValue ? 1 : -1;
      }
    });
    
    setFilteredStocks(filtered);
  };

  const handleBacktest = (stock: Stock) => {
    navigate('/backtest', {
      state: {
        symbol: stock.symbol,
        strategy: 'moving_average',
        initialCapital: 100000
      }
    });
    message.info(`Starting backtest for ${stock.symbol}`);
  };

  const handleAnalysis = (stock: Stock) => {
    navigate('/analytics', {
      state: {
        symbol: stock.symbol
      }
    });
    message.info(`Analyzing ${stock.symbol}`);
  };

  const handleViewDetails = (stock: Stock) => {
    // 可以跳转到详情页面或显示模态框
    message.info(`Viewing details for ${stock.symbol} - ${stock.name}`);
  };

  const toggleWatchlist = (stock: Stock) => {
    try {
      // 从 localStorage 获取现有 watchlist
      const saved = localStorage.getItem('quant_watchlist');
      let newWatchlist: any[] = [];
      
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          if (Array.isArray(parsed)) {
            newWatchlist = parsed;
          }
        } catch (err) {
          console.error('Failed to parse watchlist:', err);
          newWatchlist = [];
        }
      }
      
      // 检查是否已经存在
      const existingIndex = newWatchlist.findIndex(item => item.symbol === stock.symbol);
      
      if (existingIndex >= 0) {
        // 如果已存在，移除它
        newWatchlist = newWatchlist.filter(item => item.symbol !== stock.symbol);
        message.success(`${stock.symbol} removed from watchlist`);
      } else {
        // 如果不存在，添加新股票
        const stockData = {
          symbol: stock.symbol,
          name: stock.name,
          price: stock.price,
          change: stock.change,
          changePercent: stock.changePercent,
          volume: stock.volume,
          marketCap: stock.marketCap,
          sector: stock.sector,
          addedAt: new Date().toISOString()
        };
        newWatchlist.push(stockData);
        message.success(`Added ${stock.symbol} to watchlist`);
      }
      
      // 保存回 localStorage 并更新状态
      localStorage.setItem('quant_watchlist', JSON.stringify(newWatchlist));
      setWatchlist(newWatchlist);
      
    } catch (error) {
      console.error('Failed to toggle watchlist:', error);
      message.error('Failed to update watchlist');
    }
  };

  const sectors = Array.from(new Set(stocks.map(stock => stock.sector))).filter(Boolean);

  const marketStats = {
    totalStocks: stocks.length,
    avgChange: stocks.length > 0 ? stocks.reduce((sum, stock) => sum + safeNumber(stock.changePercent), 0) / stocks.length : 0,
    totalMarketCap: stocks.reduce((sum, stock) => sum + safeNumber(stock.marketCap), 0),
    gainers: stocks.filter(stock => safeNumber(stock.changePercent) > 0).length,
    losers: stocks.filter(stock => safeNumber(stock.changePercent) < 0).length,
  };

  const columns = [
    {
      title: 'Symbol',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 100,
      sorter: true,
      render: (symbol: string) => <strong>{symbol}</strong>,
    },
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      width: 150,
      sorter: true,
    },
    {
      title: 'Price',
      dataIndex: 'price',
      key: 'price',
      width: 100,
      sorter: true,
      render: (price: number) => `$${safeToFixed(price, 2)}`,
    },
    {
      title: 'Change',
      dataIndex: 'change',
      key: 'change',
      width: 100,
      sorter: true,
      render: (change: number) => {
        const safeChange = safeNumber(change);
        return (
          <Tag color={safeChange >= 0 ? 'green' : 'red'}>
            {safeChange >= 0 ? '+' : ''}{safeToFixed(safeChange, 2)}
          </Tag>
        );
      },
    },
    {
      title: 'Change %',
      dataIndex: 'changePercent',
      key: 'changePercent',
      width: 100,
      sorter: true,
      render: (percent: number) => {
        const safePercent = safeNumber(percent);
        const isPositive = safePercent > 0.01;  // 大于0.01%算正值
        const isNegative = safePercent < -0.01; // 小于-0.01%算负值
        const isNeutral = !isPositive && !isNegative; // 接近0算中性
        
        let color = '#666'; // 中性颜色
        let arrow = '';
        
        if (isPositive) {
          color = '#3f8600'; // 绿色
          arrow = '▲ ';
        } else if (isNegative) {
          color = '#cf1322'; // 红色
          arrow = '▼ ';
        }
        
        // 格式化显示，中性值不显示+号
        const displayValue = isNeutral ? 
          `${safeToFixed(safePercent, 2)}%` : 
          `${safePercent >= 0 ? '+' : ''}${safeToFixed(safePercent, 2)}%`;
        
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {arrow}{displayValue}
          </span>
        );
      },
    },
    {
      title: 'Volume',
      dataIndex: 'volume',
      key: 'volume',
      width: 100,
      sorter: true,
      render: (volume: number) => (
        <span style={{ color: '#8c8c8c', fontSize: '13px' }}>
          {formatVolume(volume)}
        </span>
      ),
    },
    {
      title: 'Market Cap',
      dataIndex: 'marketCap',
      key: 'marketCap',
      width: 120,
      sorter: true,
      render: (cap: number) => (
        <span style={{ color: '#262626', fontWeight: '500' }}>
          {formatCurrency(cap)}
        </span>
      ),
    },
    {
      title: 'P/E',
      dataIndex: 'peRatio',
      key: 'peRatio',
      width: 80,
      sorter: true,
      render: (value: any, record: Stock) => {
        // 尝试多种可能的 PE 字段名，优先级：trailingPE > forwardPE > peRatio > pe
        const peValue = 
          record.trailingPE !== undefined && record.trailingPE !== null ? record.trailingPE :
          record.forwardPE !== undefined && record.forwardPE !== null ? record.forwardPE :
          record.peRatio !== undefined && record.peRatio !== null ? record.peRatio :
          record.pe !== undefined && record.pe !== null ? record.pe :
          undefined;
        
        if (peValue === undefined || peValue === null || isNaN(peValue)) {
          return <span style={{ color: '#666' }}>--</span>;
        }
        return safeToFixed(peValue, 2);
      },
    },
    {
      title: 'Sector',
      dataIndex: 'sector',
      key: 'sector',
      width: 120,
      sorter: true,
      render: (sector: string) => sector || 'N/A',
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 180,
      fixed: 'right' as const,
      render: (_: any, record: Stock) => (
        <Space size="small">
          <Button
            type="primary"
            size="small"
            icon={<PlayCircleOutlined />}
            onClick={() => handleBacktest(record)}
          >
            Backtest
          </Button>
          <Button
            type="default"
            size="small"
            icon={<BarChartOutlined />}
            onClick={() => handleAnalysis(record)}
          >
            Analyze
          </Button>
          <Button
            type={isInWatchlist(record.symbol) ? "primary" : "default"}
            size="small"
            icon={<StarOutlined />}
            onClick={() => toggleWatchlist(record)}
            style={isInWatchlist(record.symbol) ? { 
              backgroundColor: '#1890ff',
              borderColor: '#1890ff',
              color: '#fff'
            } : {}}
          >
            {isInWatchlist(record.symbol) ? 'In Watchlist' : 'Watchlist'}
          </Button>
        </Space>
      ),
    },
  ];

  const handleTableChange = (pagination: any, filters: any, sorter: any) => {
    if (sorter.field) {
      setSortField(sorter.field);
      setSortOrder(sorter.order || 'ascend');
    }
  };

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>
        <LineChartOutlined /> Market Overview
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

      <Row gutter={[16, 16]} style={{ marginBottom: 24, alignItems: 'stretch' }}>
        <Col span={6} style={{ display: 'flex' }}>
          <Card 
            size="small" 
            style={{ width: '100%', minHeight: '140px' }}
            bodyStyle={{ padding: '16px', display: 'flex', flexDirection: 'column', height: '100%' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
              <Statistic
                title="Tracked Symbols"
                value={marketStats.totalStocks}
                valueStyle={{ fontSize: '24px' }}
              />
            </div>
            <div style={{ flex: 1, minHeight: '20px' }}></div>
            <div style={{ marginTop: 'auto', flexShrink: 0, fontSize: '12px', color: '#666' }}>
              US-listed stocks
            </div>
          </Card>
        </Col>
        <Col span={6} style={{ display: 'flex' }}>
          <Card 
            size="small" 
            style={{ width: '100%', minHeight: '140px' }}
            bodyStyle={{ padding: '16px', display: 'flex', flexDirection: 'column', height: '100%' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
              <Statistic
                title="Avg Market Move"
                value={safeToFixed(marketStats.avgChange, 2)}
                suffix="%"
                valueStyle={{ 
                  color: marketStats.avgChange >= 0 ? '#3f8600' : '#cf1322',
                  fontSize: '24px'
                }}
              />
            </div>
            <div style={{ flex: 1, minHeight: '20px' }}></div>
            <div style={{ marginTop: 'auto', flexShrink: 0, fontSize: '12px', color: '#666' }}>
              Daily average
            </div>
          </Card>
        </Col>
        <Col span={6} style={{ display: 'flex' }}>
          <Card 
            size="small" 
            style={{ width: '100%', minHeight: '140px' }}
            bodyStyle={{ padding: '16px', display: 'flex', flexDirection: 'column', height: '100%' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
              <Statistic
                title="Total Market Cap"
                value={formatCurrency(marketStats.totalMarketCap)}
                valueStyle={{ fontSize: '24px' }}
              />
            </div>
            <div style={{ flex: 1, minHeight: '20px' }}></div>
            <div style={{ marginTop: 'auto', flexShrink: 0, fontSize: '12px', color: '#666' }}>
              Combined value
            </div>
          </Card>
        </Col>
        <Col span={6} style={{ display: 'flex' }}>
          <Card 
            size="small" 
            style={{ width: '100%', minHeight: '140px' }}
            bodyStyle={{ padding: '16px', display: 'flex', flexDirection: 'column', height: '100%' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '12px', flexShrink: 0 }}>
              <Statistic
                title="Advancers / Decliners"
                value={`${marketStats.gainers} / ${marketStats.losers}`}
                valueStyle={{ fontSize: '24px' }}
              />
            </div>
            <div style={{ flex: 1, minHeight: '20px' }}></div>
            <div style={{ marginTop: 'auto', flexShrink: 0, fontSize: '12px', color: '#666' }}>
              Market sentiment
            </div>
          </Card>
        </Col>
      </Row>

      <Card
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Stocks</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {lastUpdated && (
                <span style={{ fontSize: '12px', color: '#666' }}>
                  Last updated: {lastUpdated.toLocaleTimeString()}
                </span>
              )}
              <Button
                type="text"
                icon={<ReloadOutlined />}
                onClick={fetchMarketData}
                loading={loading}
                size="small"
              />
            </div>
          </div>
        }
        extra={
          <Space>
            <Input
              placeholder="Search symbol or name (e.g., AAPL, NVDA)"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onPressEnter={async () => {
                const symbol = searchText.trim().toUpperCase();
                if (symbol && /^[A-Z]{1,5}$/.test(symbol)) {
                  await searchStockBySymbol(symbol);
                }
              }}
              style={{ width: 220 }}
              allowClear
            />
            <Button
              type="primary"
              icon={<SearchOutlined />}
              loading={searching}
              onClick={async () => {
                const symbol = searchText.trim().toUpperCase();
                if (symbol && /^[A-Z]{1,5}$/.test(symbol)) {
                  await searchStockBySymbol(symbol);
                } else if (searchText) {
                  // 如果不是有效的 symbol，就进行普通搜索
                  setSearchText(searchText);
                }
              }}
            >
              Search
            </Button>
            <Select
              placeholder="Filter by sector"
              value={selectedSector}
              onChange={setSelectedSector}
              style={{ width: 150 }}
              allowClear
            >
              <Option value="all">All Sectors</Option>
              {sectors.map(sector => (
                <Option key={sector} value={sector}>{sector}</Option>
              ))}
            </Select>
            <Button
              type="default"
              onClick={() => {
                setSearchText('');
                setSelectedSector('all');
                setSortField('symbol');
                setSortOrder('ascend');
                message.info('Filters reset');
              }}
            >
              Reset
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
            columns={columns}
            dataSource={filteredStocks}
            rowKey="symbol"
            pagination={{ 
              pageSize: 10, 
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total, range) => `${range[0]}-${range[1]} of ${total} stocks`
            }}
            size="middle"
            scroll={{ x: 1000 }}
            onChange={handleTableChange}
            onRow={(record) => ({
              onClick: () => handleViewDetails(record),
              style: { cursor: 'pointer' }
            })}
          />
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              searchText || selectedSector !== 'all' 
                ? "No stocks match your filters" 
                : "No stock data available"
            }
          >
            {searchText || selectedSector !== 'all' ? (
              <Button type="primary" onClick={() => {
                setSearchText('');
                setSelectedSector('all');
              }}>
                Clear Filters
              </Button>
            ) : (
              <Button type="primary" onClick={fetchMarketData}>
                Refresh Data
              </Button>
            )}
          </Empty>
        )}
      </Card>

      {/* Sector Distribution */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Sector Distribution" size="small">
            {stocks.length > 0 ? (
              <div>
                <div style={{ marginBottom: '12px', fontSize: '13px', color: '#666' }}>
                  Distribution of {stocks.length} tracked stocks across sectors
                </div>
                <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                  {getSectorDistribution().map((item, index) => (
                    <div 
                      key={item.sector} 
                      style={{ 
                        marginBottom: '8px',
                        padding: '8px 12px',
                        backgroundColor: index % 2 === 0 ? '#fafafa' : '#fff',
                        borderRadius: '4px',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center'
                      }}
                    >
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: '500', fontSize: '14px' }}>
                          {item.sector}
                        </div>
                        <div style={{ fontSize: '12px', color: '#8c8c8c' }}>
                          {item.count} stock{item.count !== 1 ? 's' : ''}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ fontWeight: '600', fontSize: '14px', color: '#1890ff' }}>
                          {item.percentage.toFixed(1)}%
                        </div>
                        <div style={{ 
                          width: '120px', 
                          height: '6px', 
                          backgroundColor: '#f0f0f0',
                          borderRadius: '3px',
                          marginTop: '4px',
                          overflow: 'hidden'
                        }}>
                          <div 
                            style={{ 
                              width: `${item.percentage}%`, 
                              height: '100%', 
                              backgroundColor: '#1890ff',
                              borderRadius: '3px'
                            }}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: '12px', fontSize: '12px', color: '#666', textAlign: 'center' }}>
                  Total: {stocks.length} stocks across {getSectorDistribution().length} sectors
                </div>
              </div>
            ) : (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="No sector data available"
                style={{ padding: '20px 0' }}
              >
                <Button type="primary" onClick={fetchMarketData}>
                  Load Market Data
                </Button>
              </Empty>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card title="Market Insights" size="small">
            <Row gutter={16}>
              <Col span={8}>
                <div><strong>Data Source:</strong> Yahoo Finance API</div>
              </Col>
              <Col span={8}>
                <div><strong>Stocks Tracked:</strong> {stocks.length} US-listed stocks</div>
              </Col>
              <Col span={8}>
                <div><strong>Update Frequency:</strong> Real-time (15 min delay)</div>
              </Col>
            </Row>
            <div style={{ marginTop: '8px', fontSize: '12px', color: '#666' }}>
              Click on any stock row to view details, or use the Backtest/Analyze buttons for deeper analysis.
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Market;