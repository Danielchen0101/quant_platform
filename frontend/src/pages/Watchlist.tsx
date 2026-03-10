import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Button, Input, Space, Alert, Empty, Tag, message } from 'antd';
import { PlusOutlined, PlayCircleOutlined, DeleteOutlined } from '@ant-design/icons';

const Watchlist: React.FC = () => {
  const navigate = useNavigate();
  const [symbols, setSymbols] = useState<string[]>([]);
  const [newSymbol, setNewSymbol] = useState('');
  const [loading, setLoading] = useState(false);

  // Load watchlist from localStorage on component mount
  useEffect(() => {
    const savedWatchlist = localStorage.getItem('quant_watchlist');
    if (savedWatchlist) {
      try {
        const parsed = JSON.parse(savedWatchlist);
        if (Array.isArray(parsed)) {
          setSymbols(parsed);
        }
      } catch (err) {
        console.error('Failed to parse watchlist from localStorage:', err);
      }
    }
  }, []);

  // Save watchlist to localStorage whenever it changes
  useEffect(() => {
    localStorage.setItem('quant_watchlist', JSON.stringify(symbols));
  }, [symbols]);

  const handleAddSymbol = () => {
    const symbol = newSymbol.trim().toUpperCase();
    
    if (!symbol) {
      message.warning('Please enter a stock symbol');
      return;
    }

    // Basic validation: 1-5 letters
    if (!/^[A-Z]{1,5}$/.test(symbol)) {
      message.error('Invalid stock symbol. Use 1-5 uppercase letters (e.g., AAPL, TSLA)');
      return;
    }

    // Check for duplicates
    if (symbols.includes(symbol)) {
      message.warning(`${symbol} is already in your watchlist`);
      return;
    }

    setSymbols([...symbols, symbol]);
    setNewSymbol('');
    message.success(`${symbol} added to watchlist`);
  };

  const handleRemoveSymbol = (symbolToRemove: string) => {
    setSymbols(symbols.filter(symbol => symbol !== symbolToRemove));
    message.success(`${symbolToRemove} removed from watchlist`);
  };

  const handleRunBacktest = (symbol: string) => {
    // Navigate to backtest page with symbol pre-filled
    navigate(`/backtest?symbol=${symbol}`);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleAddSymbol();
    }
  };

  const columns = [
    {
      title: 'Symbol',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 120,
      render: (symbol: string) => (
        <Tag color="blue" style={{ fontSize: '14px', fontWeight: 'bold' }}>
          {symbol}
        </Tag>
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 200,
      render: (_: any, record: { symbol: string }) => (
        <Space size="small">
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => handleRunBacktest(record.symbol)}
            size="small"
          >
            Run Backtest
          </Button>
          <Button
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleRemoveSymbol(record.symbol)}
            size="small"
          >
            Remove
          </Button>
        </Space>
      ),
    },
  ];

  const dataSource = symbols.map(symbol => ({
    key: symbol,
    symbol,
  }));

  return (
    <div style={{ padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ marginBottom: '8px' }}>My Watchlist</h1>
        <div style={{ color: '#666', fontSize: '14px' }}>
          Manage your favorite stocks and run quick backtests
        </div>
      </div>

      {/* Add Symbol Form */}
      <Card style={{ marginBottom: '24px' }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <div style={{ fontSize: '14px', fontWeight: '500', marginBottom: '8px' }}>
            Add New Symbol
          </div>
          <Space.Compact style={{ width: '100%' }}>
            <Input
              placeholder="Enter stock symbol (e.g., AAPL, TSLA)"
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
              onKeyPress={handleKeyPress}
              style={{ maxWidth: '300px' }}
            />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleAddSymbol}
              loading={loading}
            >
              Add Symbol
            </Button>
          </Space.Compact>
          <div style={{ fontSize: '12px', color: '#666', marginTop: '8px' }}>
            Enter 1-5 uppercase letters. Example: AAPL, MSFT, TSLA, NVDA
          </div>
        </Space>
      </Card>

      {/* Watchlist Table */}
      <Card title={`Watchlist (${symbols.length} symbols)`}>
        {symbols.length > 0 ? (
          <Table
            columns={columns}
            dataSource={dataSource}
            pagination={false}
            size="middle"
            bordered
          />
        ) : (
          <Empty
            description="Your watchlist is empty"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ padding: '40px 0' }}
          >
            <Button
              type="primary"
              onClick={() => setNewSymbol('AAPL')}
            >
              Add Example Symbols
            </Button>
          </Empty>
        )}
      </Card>

      {/* Quick Tips */}
      <Card style={{ marginTop: '24px' }}>
        <div style={{ fontSize: '14px', fontWeight: '500', marginBottom: '12px' }}>
          💡 Quick Tips
        </div>
        <ul style={{ margin: 0, paddingLeft: '20px', color: '#666', fontSize: '13px' }}>
          <li>Click "Run Backtest" to quickly test strategies on any symbol</li>
          <li>Your watchlist is saved automatically in your browser</li>
          <li>Popular symbols: AAPL, MSFT, GOOGL, AMZN, TSLA, NVDA, META</li>
          <li>You can add up to 20 symbols to your watchlist</li>
        </ul>
      </Card>
    </div>
  );
};

export default Watchlist;