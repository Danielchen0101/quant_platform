import React from 'react';
import { Table, Tag } from 'antd';
import { OptimizationResult } from './OptimizationHeatmap';

interface OptimizationResultsTableProps {
  results: OptimizationResult[];
}

const OptimizationResultsTable: React.FC<OptimizationResultsTableProps> = ({ results }) => {
  // Helper function to format percentages
  const formatPercent = (value: number): string => {
    if (value === undefined || value === null || isNaN(value)) {
      return 'N/A';
    }
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  const columns = [
    {
      title: 'Rank',
      dataIndex: 'rank',
      key: 'rank',
      width: 80,
      render: (rank: number) => (
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'center',
          fontWeight: 'bold',
          fontSize: rank === 1 ? '16px' : '14px',
          color: rank === 1 ? '#ffd700' : rank === 2 ? '#c0c0c0' : rank === 3 ? '#cd7f32' : '#666'
        }}>
          {rank}
        </div>
      ),
    },
    {
      title: 'Short MA',
      dataIndex: 'short_ma',
      key: 'short_ma',
      width: 90,
      render: (value: number) => (
        <Tag color="blue" style={{ fontWeight: 'bold' }}>
          {value}
        </Tag>
      ),
    },
    {
      title: 'Long MA',
      dataIndex: 'long_ma',
      key: 'long_ma',
      width: 90,
      render: (value: number) => (
        <Tag color="green" style={{ fontWeight: 'bold' }}>
          {value}
        </Tag>
      ),
    },
    {
      title: 'Total Return',
      dataIndex: 'totalReturn',
      key: 'totalReturn',
      width: 120,
      defaultSortOrder: 'descend' as const,
      sorter: (a: OptimizationResult, b: OptimizationResult) => a.totalReturn - b.totalReturn,
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
      title: 'Annualized',
      dataIndex: 'annualizedReturn',
      key: 'annualizedReturn',
      width: 120,
      sorter: (a: OptimizationResult, b: OptimizationResult) => a.annualizedReturn - b.annualizedReturn,
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
      title: 'Sharpe',
      dataIndex: 'sharpeRatio',
      key: 'sharpeRatio',
      width: 90,
      sorter: (a: OptimizationResult, b: OptimizationResult) => a.sharpeRatio - b.sharpeRatio,
      render: (value: number) => {
        const color = value >= 1 ? '#3f8600' : value >= 0 ? '#fa8c16' : '#cf1322';
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {value !== undefined && value !== null && !isNaN(value) ? value.toFixed(2) : 'N/A'}
          </span>
        );
      },
    },
    {
      title: 'Max DD',
      dataIndex: 'maxDrawdown',
      key: 'maxDrawdown',
      width: 90,
      sorter: (a: OptimizationResult, b: OptimizationResult) => a.maxDrawdown - b.maxDrawdown,
      render: (value: number) => {
        let color = '#cf1322'; // 默认红色
        if (value > -20) {
          color = '#3f8600'; // 绿色
        } else if (value >= -40) {
          color = '#fa8c16'; // 橙色
        }
        return (
          <span style={{ color, fontWeight: 'bold' }}>
            {value !== undefined && value !== null && !isNaN(value) ? value.toFixed(1) + '%' : 'N/A'}
          </span>
        );
      },
    },
    {
      title: 'Trades',
      dataIndex: 'trades',
      key: 'trades',
      width: 80,
      sorter: (a: OptimizationResult, b: OptimizationResult) => a.trades - b.trades,
      render: (value: number) => (
        <span style={{ fontWeight: 'bold' }}>
          {Math.round(value)}
        </span>
      ),
    },
  ];

  return (
    <Table
      columns={columns}
      dataSource={results}
      pagination={{
        pageSize: 10,
        showSizeChanger: true,
        showQuickJumper: true,
        showTotal: (total, range) => `${range[0]}-${range[1]} of ${total} combinations`,
      }}
      size="middle"
      scroll={{ x: 800 }}
      bordered
      rowClassName={(record, index) => 
        index === 0 ? 'top-rank-row' : index === 1 ? 'second-rank-row' : index === 2 ? 'third-rank-row' : ''
      }
    />
  );
};

export default OptimizationResultsTable;