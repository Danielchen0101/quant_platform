import React, { useState, useEffect } from 'react';
import { Table, Card, Spin, Alert, Empty, Tag, Tooltip } from 'antd';
import { TrophyOutlined, LineChartOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { backtraderAPI } from '../services/api';

// Helper functions
const safeNumber = (value: any): number => {
  if (value === null || value === undefined || value === '') return 0;
  const num = Number(value);
  return isNaN(num) ? 0 : num;
};

const formatPercent = (value: number): string => {
  const safeValue = safeNumber(value);
  const sign = safeValue >= 0 ? '+' : '';
  return `${sign}${safeValue.toFixed(2)}%`;
};

interface RankingItem {
  key: string;
  backtestId: string;
  symbol: string;
  strategy: string;
  totalReturn: number;
  annualizedReturn: number;
  sharpeRatio: number;
  sortinoRatio: number;
  maxDrawdown: number;
  volatility: number;
  winRate: number;
  profitFactor: number;
  createdAt: string;
}

const StrategyRanking: React.FC = () => {
  const [loading, setLoading] = useState(true);
  const [rankingData, setRankingData] = useState<RankingItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRankingData();
  }, []);

  const fetchRankingData = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const historyResponse = await backtraderAPI.getBacktestHistory();
      if (historyResponse.data && Array.isArray(historyResponse.data)) {
        const history = historyResponse.data;
        
        // Transform history data to ranking items
        const rankingItems: RankingItem[] = history
          .filter((item: any) => 
            item.results && 
            item.parameters?.symbols?.length > 0 &&
            item.status === 'completed'
          )
          .map((item: any, index: number) => {
            const symbol = item.parameters?.symbols?.[0] || 'Unknown';
            const strategy = item.parameters?.strategy || 'Unknown';
            
            return {
              key: item.backtestId || `item-${index}`,
              backtestId: item.backtestId,
              symbol,
              strategy,
              totalReturn: safeNumber(item.results?.totalReturn),
              annualizedReturn: safeNumber(item.results?.annualizedReturn),
              sharpeRatio: safeNumber(item.results?.sharpeRatio),
              sortinoRatio: safeNumber(item.results?.sortinoRatio),
              maxDrawdown: safeNumber(item.results?.maxDrawdown),
              volatility: safeNumber(item.results?.volatility),
              winRate: safeNumber(item.results?.winRate),
              profitFactor: safeNumber(item.results?.profitFactor),
              createdAt: item.createdAt,
            };
          })
          .sort((a, b) => b.totalReturn - a.totalReturn); // 默认按totalReturn降序排序
        
        setRankingData(rankingItems);
        
        // Debug log
        console.log(`Loaded ${rankingItems.length} ranking items`);
      } else {
        setError('Failed to load backtest history data');
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load ranking data');
    } finally {
      setLoading(false);
    }
  };

  const columns = [
    {
      title: 'Rank',
      key: 'rank',
      width: 80,
      render: (_: any, __: any, index: number) => (
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          fontWeight: 'bold',
          fontSize: index < 3 ? '16px' : '14px',
          color: index === 0 ? '#ffd700' : index === 1 ? '#c0c0c0' : index === 2 ? '#cd7f32' : '#666'
        }}>
          {index === 0 && <TrophyOutlined style={{ marginRight: '4px' }} />}
          {index + 1}
        </div>
      ),
    },
    {
      title: 'Symbol',
      dataIndex: 'symbol',
      key: 'symbol',
      width: 100,
      sorter: (a: RankingItem, b: RankingItem) => a.symbol.localeCompare(b.symbol),
      render: (symbol: string) => (
        <Tag color="blue" style={{ fontWeight: 'bold', fontSize: '14px' }}>
          {symbol}
        </Tag>
      ),
    },
    {
      title: 'Strategy',
      dataIndex: 'strategy',
      key: 'strategy',
      width: 150,
      sorter: (a: RankingItem, b: RankingItem) => a.strategy.localeCompare(b.strategy),
      render: (strategy: string) => (
        <span style={{ fontWeight: '500' }}>
          {strategy.replace('_', ' ').toUpperCase()}
        </span>
      ),
    },
    {
      title: (
        <span>
          Total Return
          <Tooltip title="Total return over the backtest period">
            <InfoCircleOutlined style={{ marginLeft: '4px', color: '#666', fontSize: '12px' }} />
          </Tooltip>
        </span>
      ),
      dataIndex: 'totalReturn',
      key: 'totalReturn',
      width: 130,
      defaultSortOrder: 'descend' as const,
      sorter: (a: RankingItem, b: RankingItem) => a.totalReturn - b.totalReturn,
      render: (value: number) => {
        const color = value >= 0 ? '#3f8600' : '#cf1322';
        return (
          <span style={{ color, fontWeight: 'bold', fontSize: '14px' }}>
            {formatPercent(value)}
          </span>
        );
      },
    },
    {
      title: (
        <span>
          Annualized
          <Tooltip title="Annualized return (CAGR)">
            <InfoCircleOutlined style={{ marginLeft: '4px', color: '#666', fontSize: '12px' }} />
          </Tooltip>
        </span>
      ),
      dataIndex: 'annualizedReturn',
      key: 'annualizedReturn',
      width: 130,
      sorter: (a: RankingItem, b: RankingItem) => a.annualizedReturn - b.annualizedReturn,
      render: (value: number) => {
        const color = value >= 0 ? '#3f8600' : '#cf1322';
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {formatPercent(value)}
          </span>
        );
      },
    },
    {
      title: (
        <span>
          Sharpe
          <Tooltip title="Sharpe Ratio (risk-adjusted return)">
            <InfoCircleOutlined style={{ marginLeft: '4px', color: '#666', fontSize: '12px' }} />
          </Tooltip>
        </span>
      ),
      dataIndex: 'sharpeRatio',
      key: 'sharpeRatio',
      width: 100,
      sorter: (a: RankingItem, b: RankingItem) => a.sharpeRatio - b.sharpeRatio,
      render: (value: number) => {
        const color = value >= 1 ? '#3f8600' : value >= 0 ? '#fa8c16' : '#cf1322';
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {value.toFixed(2)}
          </span>
        );
      },
    },
    {
      title: (
        <span>
          Sortino
          <Tooltip title="Sortino Ratio (downside risk-adjusted return)">
            <InfoCircleOutlined style={{ marginLeft: '4px', color: '#666', fontSize: '12px' }} />
          </Tooltip>
        </span>
      ),
      dataIndex: 'sortinoRatio',
      key: 'sortinoRatio',
      width: 100,
      sorter: (a: RankingItem, b: RankingItem) => a.sortinoRatio - b.sortinoRatio,
      render: (value: number) => {
        const color = value >= 1 ? '#3f8600' : value >= 0 ? '#fa8c16' : '#cf1322';
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {value.toFixed(2)}
          </span>
        );
      },
    },
    {
      title: (
        <span>
          Max DD
          <Tooltip title="Maximum Drawdown (peak to trough decline)">
            <InfoCircleOutlined style={{ marginLeft: '4px', color: '#666', fontSize: '12px' }} />
          </Tooltip>
        </span>
      ),
      dataIndex: 'maxDrawdown',
      key: 'maxDrawdown',
      width: 100,
      sorter: (a: RankingItem, b: RankingItem) => a.maxDrawdown - b.maxDrawdown,
      render: (value: number) => {
        // Max Drawdown 越小越好
        let color = '#cf1322'; // 默认红色
        if (value > -20) {
          color = '#3f8600'; // 绿色
        } else if (value >= -40) {
          color = '#fa8c16'; // 橙色
        }
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {value.toFixed(1)}%
          </span>
        );
      },
    },
    {
      title: (
        <span>
          Volatility
          <Tooltip title="Annualized volatility">
            <InfoCircleOutlined style={{ marginLeft: '4px', color: '#666', fontSize: '12px' }} />
          </Tooltip>
        </span>
      ),
      dataIndex: 'volatility',
      key: 'volatility',
      width: 100,
      sorter: (a: RankingItem, b: RankingItem) => a.volatility - b.volatility,
      render: (value: number) => {
        const color = value < 20 ? '#3f8600' : value < 40 ? '#fa8c16' : '#cf1322';
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {value.toFixed(1)}%
          </span>
        );
      },
    },
    {
      title: (
        <span>
          Win Rate
          <Tooltip title="Percentage of winning trades">
            <InfoCircleOutlined style={{ marginLeft: '4px', color: '#666', fontSize: '12px' }} />
          </Tooltip>
        </span>
      ),
      dataIndex: 'winRate',
      key: 'winRate',
      width: 100,
      sorter: (a: RankingItem, b: RankingItem) => a.winRate - b.winRate,
      render: (value: number) => {
        const color = value >= 60 ? '#3f8600' : value >= 40 ? '#fa8c16' : '#cf1322';
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {value.toFixed(1)}%
          </span>
        );
      },
    },
    {
      title: (
        <span>
          Profit Factor
          <Tooltip title="Gross profit / gross loss">
            <InfoCircleOutlined style={{ marginLeft: '4px', color: '#666', fontSize: '12px' }} />
          </Tooltip>
        </span>
      ),
      dataIndex: 'profitFactor',
      key: 'profitFactor',
      width: 110,
      sorter: (a: RankingItem, b: RankingItem) => a.profitFactor - b.profitFactor,
      render: (value: number) => {
        const color = value >= 2 ? '#3f8600' : value >= 1 ? '#fa8c16' : '#cf1322';
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {value.toFixed(2)}
          </span>
        );
      },
    },
  ];

  if (loading) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <Spin size="large" />
        <div style={{ marginTop: '16px', color: '#666' }}>Loading strategy ranking data...</div>
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
        />
      </div>
    );
  }

  return (
    <div style={{ padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ marginBottom: '8px' }}>
          <TrophyOutlined style={{ marginRight: '12px', color: '#ffd700' }} />
          Strategy Ranking
        </h1>
        <div style={{ color: '#666', fontSize: '14px' }}>
          Performance ranking based on historical backtest results. Sorted by Total Return (highest first).
          {rankingData.length > 0 && (
            <span style={{ marginLeft: '12px', fontWeight: '500' }}>
              Showing {rankingData.length} backtest{rankingData.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>
      </div>

      {/* Ranking Table */}
      <Card>
        {rankingData.length > 0 ? (
          <Table
            columns={columns}
            dataSource={rankingData}
            pagination={{
              pageSize: 20,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total, range) => `${range[0]}-${range[1]} of ${total} items`,
            }}
            size="middle"
            scroll={{ x: 1300 }}
            bordered
            rowClassName={(record, index) => 
              index === 0 ? 'top-rank-row' : index === 1 ? 'second-rank-row' : index === 2 ? 'third-rank-row' : ''
            }
          />
        ) : (
          <Empty
            description="No backtest data available for ranking"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ padding: '40px 0' }}
          />
        )}
      </Card>

      {/* Legend */}
      {rankingData.length > 0 && (
        <Card style={{ marginTop: '24px' }}>
          <div style={{ fontSize: '14px', fontWeight: '500', marginBottom: '12px' }}>
            📊 Color Legend
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', fontSize: '13px', color: '#666' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', backgroundColor: '#3f8600', borderRadius: '2px' }} />
              <span>Good performance</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', backgroundColor: '#fa8c16', borderRadius: '2px' }} />
              <span>Average performance</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', backgroundColor: '#cf1322', borderRadius: '2px' }} />
              <span>Poor performance</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', backgroundColor: '#ffd700', borderRadius: '50%' }} />
              <span>🥇 1st place</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', backgroundColor: '#c0c0c0', borderRadius: '50%' }} />
              <span>🥈 2nd place</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ width: '12px', height: '12px', backgroundColor: '#cd7f32', borderRadius: '50%' }} />
              <span>🥉 3rd place</span>
            </div>
          </div>
        </Card>
      )}

      {/* Refresh Button */}
      <div style={{ textAlign: 'center', marginTop: '24px' }}>
        <button
          onClick={fetchRankingData}
          style={{
            padding: '8px 16px',
            background: '#1890ff',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: '500',
          }}
        >
          Refresh Ranking
        </button>
      </div>
    </div>
  );
};

export default StrategyRanking;