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
    bestSharpeRatio: results.length > 0 ? Math.max(...results.map(r => r.sharpeRatio)) : 0,
    bestMaxDrawdown: results.length > 0 ? Math.min(...results.map(r => r.maxDrawdown)) : 0, // Most negative is best
    bestCombinationBySharpe: results.length > 0 ? 
      results.reduce((best, current) => 
        (current.sharpeRatio > best.sharpeRatio) ? current : best
      ) : null,
    bestCombinationByReturn: results.length > 0 ? 
      results.reduce((best, current) => 
        (current.totalReturn > best.totalReturn) ? current : best
      ) : null
  };

  // Helper function to format percentages
  const formatPercent = (value: number): string => {
    if (value === undefined || value === null || isNaN(value)) {
      return 'N/A';
    }
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  return (
    <Card style={{ marginBottom: '24px' }}>
      <div style={{ marginBottom: '16px', fontSize: '16px', fontWeight: '600', color: '#333' }}>
        Optimization Summary
      </div>
      
      {/* Basic Statistics Row */}
      <Row gutter={[24, 24]} style={{ marginBottom: '24px' }}>
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
            <div style={{ fontSize: '24px', fontWeight: '600', color: '#722ed1', marginBottom: '4px' }}>
              {stats.bestSharpeRatio !== undefined && stats.bestSharpeRatio !== null && !isNaN(stats.bestSharpeRatio) ? stats.bestSharpeRatio.toFixed(2) : 'N/A'}
            </div>
            <div style={{ fontSize: '12px', color: '#666' }}>
              Best Sharpe
            </div>
          </div>
        </Col>
      </Row>
      
      {/* Best Combination Details */}
      {stats.bestCombinationBySharpe && (
        <div style={{ 
          background: '#f6ffed', 
          border: '1px solid #b7eb8f', 
          borderRadius: '8px', 
          padding: '16px',
          marginTop: '16px'
        }}>
          <div style={{ fontSize: '14px', fontWeight: '600', color: '#389e0d', marginBottom: '12px' }}>
            🏆 Best Combination (by Sharpe Ratio)
          </div>
          <Row gutter={[24, 16]}>
            <Col span={4}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '18px', fontWeight: '600', color: '#1890ff', marginBottom: '2px' }}>
                  {stats.bestCombinationBySharpe.short_ma}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  Best Short MA
                </div>
              </div>
            </Col>
            <Col span={4}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '18px', fontWeight: '600', color: '#1890ff', marginBottom: '2px' }}>
                  {stats.bestCombinationBySharpe.long_ma}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  Best Long MA
                </div>
              </div>
            </Col>
            <Col span={4}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '18px', fontWeight: '600', color: '#722ed1', marginBottom: '2px' }}>
                  {stats.bestCombinationBySharpe.sharpeRatio !== undefined && stats.bestCombinationBySharpe.sharpeRatio !== null && !isNaN(stats.bestCombinationBySharpe.sharpeRatio) ? 
                    stats.bestCombinationBySharpe.sharpeRatio.toFixed(2) : 'N/A'}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  Sharpe Ratio
                </div>
              </div>
            </Col>
            <Col span={4}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '18px', fontWeight: '600', color: '#3f8600', marginBottom: '2px' }}>
                  {formatPercent(stats.bestCombinationBySharpe.totalReturn)}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  Total Return
                </div>
              </div>
            </Col>
            <Col span={4}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '18px', fontWeight: '600', color: '#cf1322', marginBottom: '2px' }}>
                  {stats.bestCombinationBySharpe.maxDrawdown !== undefined && stats.bestCombinationBySharpe.maxDrawdown !== null && !isNaN(stats.bestCombinationBySharpe.maxDrawdown) ? 
                    stats.bestCombinationBySharpe.maxDrawdown.toFixed(2) + '%' : 'N/A'}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  Max Drawdown
                </div>
              </div>
            </Col>
            <Col span={4}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '18px', fontWeight: '600', color: '#fa8c16', marginBottom: '2px' }}>
                  {stats.bestCombinationBySharpe.winRate !== undefined && stats.bestCombinationBySharpe.winRate !== null && !isNaN(stats.bestCombinationBySharpe.winRate) ? 
                    stats.bestCombinationBySharpe.winRate.toFixed(1) + '%' : 'N/A'}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  Win Rate
                </div>
              </div>
            </Col>
          </Row>
        </div>
      )}
      
      {/* Best by Return (alternative) */}
      {stats.bestCombinationByReturn && stats.bestCombinationByReturn !== stats.bestCombinationBySharpe && (
        <div style={{ 
          background: '#fff7e6', 
          border: '1px solid #ffd591', 
          borderRadius: '8px', 
          padding: '16px',
          marginTop: '12px'
        }}>
          <div style={{ fontSize: '14px', fontWeight: '600', color: '#d46b08', marginBottom: '12px' }}>
            📈 Best Combination (by Total Return)
          </div>
          <Row gutter={[24, 16]}>
            <Col span={3}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '16px', fontWeight: '600', color: '#1890ff', marginBottom: '2px' }}>
                  {stats.bestCombinationByReturn.short_ma}/{stats.bestCombinationByReturn.long_ma}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  MA Pair
                </div>
              </div>
            </Col>
            <Col span={3}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '16px', fontWeight: '600', color: '#3f8600', marginBottom: '2px' }}>
                  {formatPercent(stats.bestCombinationByReturn.totalReturn)}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  Return
                </div>
              </div>
            </Col>
            <Col span={3}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '16px', fontWeight: '600', color: '#722ed1', marginBottom: '2px' }}>
                  {stats.bestCombinationByReturn.sharpeRatio !== undefined && stats.bestCombinationByReturn.sharpeRatio !== null && !isNaN(stats.bestCombinationByReturn.sharpeRatio) ? 
                    stats.bestCombinationByReturn.sharpeRatio.toFixed(2) : 'N/A'}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  Sharpe
                </div>
              </div>
            </Col>
            <Col span={3}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '16px', fontWeight: '600', color: '#cf1322', marginBottom: '2px' }}>
                  {stats.bestCombinationByReturn.maxDrawdown !== undefined && stats.bestCombinationByReturn.maxDrawdown !== null && !isNaN(stats.bestCombinationByReturn.maxDrawdown) ? 
                    stats.bestCombinationByReturn.maxDrawdown.toFixed(2) + '%' : 'N/A'}
                </div>
                <div style={{ fontSize: '11px', color: '#666' }}>
                  Max DD
                </div>
              </div>
            </Col>
          </Row>
        </div>
      )}
    </Card>
  );
};

export default OptimizationSummary;