import React, { useState, useEffect } from 'react';
import { Card, Table, Tag, Input, Select, Button, Row, Col, Statistic, Space, Alert, message, Empty, Spin } from 'antd';
import { SearchOutlined, LineChartOutlined, PlayCircleOutlined, BarChartOutlined, ReloadOutlined, EyeOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { marketAPI } from '../services/api';

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
  }, []);

  useEffect(() => {
    filterAndSortStocks();
  }, [stocks, searchText, selectedSector, sortField, sortOrder]);

  const fetchMarketData = async () => {
    try {
      setLoading(true);
      const response = await marketAPI.getStocks();
      
      if (response.data && response.data.stocks) {
        const stockData = response.data.stocks;
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
      
      if (sortField === 'marketCap' || sortField === 'price' || sortField === 'volume') {
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
    navigate('/analysis', {
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
        return (
          <span style={{ color: safePercent >= 0 ? '#3f8600' : '#cf1322', fontWeight: 'bold' }}>
            {safePercent >= 0 ? '+' : ''}{safeToFixed(safePercent, 2)}%
          </span>
        );
      },
    },
    {
      title: 'Market Cap',
      dataIndex: 'marketCap',
      key: 'marketCap',
      width: 120,
      sorter: true,
      render: (cap: number) => formatCurrency(cap),
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
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleViewDetails(record)}
          />
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

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="Total Stocks"
              value={marketStats.totalStocks}
              valueStyle={{ fontSize: '24px' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="Avg Change"
              value={safeToFixed(marketStats.avgChange, 2)}
              suffix="%"
              valueStyle={{ 
                color: marketStats.avgChange >= 0 ? '#3f8600' : '#cf1322',
                fontSize: '24px'
              }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="Total Market Cap"
              value={formatCurrency(marketStats.totalMarketCap)}
              valueStyle={{ fontSize: '20px' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="Gainers / Losers"
              value={`${marketStats.gainers} / ${marketStats.losers}`}
              valueStyle={{ fontSize: '24px' }}
            />
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
              placeholder="Search symbol or name"
              prefix={<SearchOutlined />}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              style={{ width: 200 }}
              allowClear
            />
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