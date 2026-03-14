import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, Table, Button, Input, Space, Alert, Empty, Tag, message, Statistic } from 'antd';
import { PlusOutlined, PlayCircleOutlined, DeleteOutlined, EyeOutlined } from '@ant-design/icons';
import { useLanguage } from '../contexts/LanguageContext';

const STORAGE_KEY = "quant_watchlist";

interface WatchlistItem {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  marketCap: number;
  sector: string;
  addedAt: string;
}

const Watchlist: React.FC = () => {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [newSymbol, setNewSymbol] = useState('');
  const [loading, setLoading] = useState(false);
  const hasLoaded = React.useRef(false);

  // 安全的格式化函数
  const safeToFixed = (value: any, decimals: number = 2): string => {
    if (typeof value === 'number' && !isNaN(value)) {
      return value.toFixed(decimals);
    }
    return '0.00';
  };

  // Load watchlist from localStorage on component mount and listen for changes
  useEffect(() => {
    // Prevent double loading in React Strict Mode
    if (hasLoaded.current) {
      return;
    }
    
    const loadWatchlist = () => {
      const saved = localStorage.getItem(STORAGE_KEY);
      
      if (saved) {
        try {
          const parsed = JSON.parse(saved);
          if (Array.isArray(parsed)) {
            setWatchlist(parsed);
          } else {
            setWatchlist([]);
          }
        } catch (err) {
          console.error('Failed to parse watchlist from localStorage:', err);
          setWatchlist([]);
        }
      } else {
        setWatchlist([]);
      }
    };
    
    // Initial load
    loadWatchlist();
    
    // Listen for storage events (changes from other tabs/windows)
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) {
        loadWatchlist();
      }
    };
    
    window.addEventListener('storage', handleStorageChange);
    
    hasLoaded.current = true;
    
    // Cleanup
    return () => {
      window.removeEventListener('storage', handleStorageChange);
    };
  }, []);

  // Save watchlist to localStorage whenever it changes
  useEffect(() => {
    // Don't save on initial mount (empty array)
    if (watchlist.length === 0 && !hasLoaded.current) {
      return;
    }
    
    localStorage.setItem(STORAGE_KEY, JSON.stringify(watchlist));
  }, [watchlist]);

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

    // Check for duplicates using functional update to ensure consistency
    setWatchlist(prevWatchlist => {
      if (prevWatchlist.some(item => item.symbol === symbol)) {
        message.warning(`${symbol} is already in your watchlist`);
        return prevWatchlist;
      }
      
      // 创建基本的股票信息（可以从 Market 页面添加时会有完整信息）
      const newItem: WatchlistItem = {
        symbol: symbol,
        name: `${symbol} Inc.`,
        price: 100 + Math.random() * 100,
        change: (Math.random() - 0.5) * 10,
        changePercent: (Math.random() - 0.5) * 5,
        volume: Math.floor(Math.random() * 10000000),
        marketCap: Math.floor(Math.random() * 1000000000),
        sector: 'Technology',
        addedAt: new Date().toISOString()
      };
      
      const updatedWatchlist = [...prevWatchlist, newItem];
      message.success(`${symbol} added to watchlist`);
      return updatedWatchlist;
    });
    
    setNewSymbol('');
  };

  const handleRemoveSymbol = (symbolToRemove: string) => {
    setWatchlist(prevWatchlist => {
      const updatedWatchlist = prevWatchlist.filter(item => item.symbol !== symbolToRemove);
      message.success(`${symbolToRemove} removed from watchlist`);
      return updatedWatchlist;
    });
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
      width: 100,
      render: (symbol: string) => (
        <Tag color="blue" style={{ fontSize: '14px', fontWeight: 'bold' }}>
          {symbol}
        </Tag>
      ),
    },
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      width: 150,
    },
    {
      title: 'Price',
      dataIndex: 'price',
      key: 'price',
      width: 100,
      render: (price: number) => `$${safeToFixed(price, 2)}`,
    },
    {
      title: 'Change %',
      dataIndex: 'changePercent',
      key: 'changePercent',
      width: 100,
      render: (percent: number) => {
        const safePercent = typeof percent === 'number' && !isNaN(percent) ? percent : 0;
        const color = safePercent >= 0 ? '#3f8600' : '#cf1322';
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {safePercent >= 0 ? '+' : ''}{safeToFixed(safePercent, 2)}%
          </span>
        );
      },
    },
    {
      title: 'Sector',
      dataIndex: 'sector',
      key: 'sector',
      width: 120,
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 200,
      render: (_: any, record: WatchlistItem) => (
        <Space size="small">
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            onClick={() => handleRunBacktest(record.symbol)}
            size="small"
          >
            Backtest
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

  const dataSource = watchlist.map(item => ({
    key: item.symbol,
    ...item
  }));

  return (
    <div style={{ padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ marginBottom: '8px' }}>{t.watchlist.title}</h1>
        <div style={{ color: '#666', fontSize: '14px' }}>
          {t.watchlist.subtitle}
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
      <Card title={`Watchlist (${watchlist.length} stocks)`}>
        {watchlist.length > 0 ? (
          <Table
            columns={columns}
            dataSource={dataSource}
            pagination={false}
            size="middle"
            bordered
            scroll={{ x: 800 }}
          />
        ) : (
          <Empty
            description="Your watchlist is empty"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ padding: '40px 0' }}
          >
            <div style={{ marginBottom: '16px' }}>
              <p style={{ color: '#666', marginBottom: '8px' }}>
                You can add stocks to your watchlist from:
              </p>
              <ul style={{ textAlign: 'left', margin: '0 auto', display: 'inline-block', color: '#666' }}>
                <li>Market page - Click "Watchlist" button on any stock</li>
                <li>This page - Use the form above to add symbols</li>
              </ul>
            </div>
            <Button
              type="primary"
              onClick={() => setNewSymbol('AAPL')}
            >
              Add Example Stock (AAPL)
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