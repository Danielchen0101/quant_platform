import React from 'react';
import { Card, Row, Col } from 'antd';
import { OptimizationResult } from './OptimizationHeatmap';

interface OptimizationSummaryProps {
  results: OptimizationResult[];
  totalCombinations?: number;
  validCombinations?: number;
}

const OptimizationSummary: React.FC<OptimizationSummaryProps> = ({ 
  results, 
  totalCombinations, 
  validCombinations 
}) => {
  // Calculate statistics
  const stats = {
    totalCombinations: totalCombinations || results.length,
    validCombinations: validCombinations || results.length,
    bestReturn: results.length > 0 ? Math.max(...results.map(r => r.totalReturn)) : 0,
    worstReturn: results.length > 0 ? Math.min(...results.map(r => r.totalReturn)) : 0,
    avgReturn: results.length > 0 ? results.reduce((sum, r) => sum + r.totalReturn, 0) / results.length : 0,
    bestCombination: results.length > 0 ? results[0] : null
  };

  // Helper function to format percentages
  const formatPercent = (value: number): string => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  return (
    <Card style={{ marginBottom: '24px' }}>
      <div style={{ marginBottom: '16px', fontSize: '16px', fontWeight: '600', color: '#333' }}>
        Optimization Summary
      </div>
      <Row gutter={[24, 24]}>
        <Col span={4}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '24px', fontWeight: '600', color: '#1890ff', marginBottom: '4px' }}>
              {stats.totalCombinations}
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Total Combinations
            </div>
          </div>
        </Col>
        <Col span={4}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '24px', fontWeight: '600', color: '#52c41a', marginBottom: '4px' }}>
              {stats.validCombinations}
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Valid Results
            </div>
          </div>
        </Col>
        <Col span={4}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '24px', fontWeight: '600', color: '#3f8600', marginBottom: '4px' }}>
              {formatPercent(stats.bestReturn)}
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Best Return
            </div>
          </div>
        </Col>
        <Col span={4}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '24px', fontWeight: '600', color: '#cf1322', marginBottom: '4px' }}>
              {formatPercent(stats.worstReturn)}
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Worst Return
            </div>
          </div>
        </Col>
        <Col span={4}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '24px', fontWeight: '600', color: '#fa8c16', marginBottom: '4px' }}>
              {formatPercent(stats.avgReturn)}
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Average Return
            </div>
          </div>
        </Col>
        <Col span={4}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '24px', fontWeight: '600', color: '#ffd700', marginBottom: '4px' }}>
              {stats.bestCombination ? `${stats.bestCombination.short_ma}/${stats.bestCombination.long_ma}` : 'N/A'}
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Top Combination
            </div>
          </div>
        </Col>
      </Row>
    </Card>
  );
};

export default OptimizationSummary;