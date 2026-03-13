import React from 'react';
import { Tooltip } from 'antd';

export interface OptimizationResult {
  rank: number;
  short_ma: number;
  long_ma: number;
  totalReturn: number;
  annualizedReturn: number;
  sharpeRatio: number;
  maxDrawdown: number;
  trades: number;
  winRate?: number;
  profitLoss?: number;
  volatility?: number;
  sortinoRatio?: number;
  profitFactor?: number;
  expectancy?: number;
  exposure?: number;
}

interface OptimizationHeatmapProps {
  results: OptimizationResult[];
}

const OptimizationHeatmap: React.FC<OptimizationHeatmapProps> = ({ results }) => {
  // Get unique short_ma and long_ma values
  const shortSet = new Set<number>();
  const longSet = new Set<number>();
  results.forEach((r: OptimizationResult) => {
    shortSet.add(r.short_ma);
    longSet.add(r.long_ma);
  });
  const shortValues = Array.from(shortSet).sort((a, b) => a - b);
  const longValues = Array.from(longSet).sort((a, b) => a - b);

  // Create a map for quick lookup
  const resultMap = new Map<string, OptimizationResult>();
  results.forEach((result: OptimizationResult) => {
    resultMap.set(`${result.short_ma}_${result.long_ma}`, result);
  });

  // Calculate Sharpe Ratio range for color scaling
  const sharpeValues = results.map((r: OptimizationResult) => r.sharpeRatio);
  const minSharpe = Math.min(...sharpeValues);
  const maxSharpe = Math.max(...sharpeValues);
  const sharpeRange = maxSharpe - minSharpe;

  // Function to get color based on Sharpe Ratio
  const getColor = (sharpe: number) => {
    if (sharpeRange === 0) return '#d9d9d9'; // Gray if all values are the same
    
    const normalized = (sharpe - minSharpe) / sharpeRange;
    
    // Color gradient: red (low) -> yellow (medium) -> green (high)
    if (normalized < 0.5) {
      // Red to Yellow
      const r = 255;
      const g = Math.round(255 * (normalized * 2));
      return `rgb(${r}, ${g}, 0)`;
    } else {
      // Yellow to Green
      const r = Math.round(255 * (1 - (normalized - 0.5) * 2));
      const g = 255;
      return `rgb(${r}, ${g}, 0)`;
    }
  };

  // Helper function to format percentages
  const formatPercent = (value: number): string => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  return (
    <div style={{ 
      display: 'grid',
      gridTemplateColumns: `auto repeat(${shortValues.length}, 1fr)`,
      gap: '4px',
      fontSize: '12px',
      maxWidth: '800px',
      margin: '0 auto'
    }}>
      {/* Top-left empty cell */}
      <div style={{ 
        padding: '12px',
        textAlign: 'center',
        fontWeight: '600',
        background: '#fafafa',
        fontSize: '11px',
        color: '#333',
        borderRight: '2px solid #1890ff',
        borderBottom: '2px solid #1890ff'
      }}>
        <div>Short MA</div>
        <div style={{ fontSize: '10px', color: '#666', marginTop: '2px' }}>→ X-axis</div>
      </div>
      
      {/* X-axis headers (short_ma values) */}
      {shortValues.map(shortVal => (
        <div key={`header-${shortVal}`} style={{ 
          padding: '12px',
          textAlign: 'center',
          fontWeight: '600',
          background: '#fafafa',
          borderBottom: '2px solid #1890ff',
          fontSize: '12px',
          color: '#333'
        }}>
          {shortVal}
        </div>
      ))}
      
      {/* Heatmap rows */}
      {longValues.map(longVal => (
        <React.Fragment key={`row-${longVal}`}>
          {/* Y-axis header (long_ma value) */}
          <div style={{ 
            padding: '12px',
            textAlign: 'center',
            fontWeight: '600',
            background: '#fafafa',
            borderRight: '2px solid #1890ff',
            fontSize: '12px',
            color: '#333'
          }}>
            <div>{longVal}</div>
            <div style={{ fontSize: '10px', color: '#666', marginTop: '2px' }}>Y-axis</div>
          </div>
          
          {/* Heatmap cells */}
          {shortValues.map(shortVal => {
            const result = resultMap.get(`${shortVal}_${longVal}`);
            const hasResult = !!result;
            const sharpe = hasResult ? result.sharpeRatio : 0;
            
            return (
              <Tooltip
                key={`cell-${shortVal}-${longVal}`}
                title={hasResult ? (
                  <div style={{ fontSize: '13px', color: '#000', padding: '4px 0' }}>
                    <div style={{ marginBottom: '6px', fontWeight: '600', fontSize: '14px' }}>
                      Short MA: {shortVal}, Long MA: {longVal}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                      <div>
                        <div style={{ fontSize: '11px', color: '#666' }}>Sharpe</div>
                        <div style={{ color: sharpe >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: '600' }}>
                          {sharpe.toFixed(2)}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '11px', color: '#666' }}>Return</div>
                        <div style={{ color: result.totalReturn >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: '600' }}>
                          {formatPercent(result.totalReturn)}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '11px', color: '#666' }}>Max DD</div>
                        <div style={{ color: '#ff4d4f', fontWeight: '600' }}>
                          {result.maxDrawdown.toFixed(2)}%
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '11px', color: '#666' }}>Trades</div>
                        <div style={{ fontWeight: '600' }}>
                          {result.trades}
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div style={{ color: '#000', fontSize: '13px' }}>
                    No data for Short MA={shortVal}, Long MA={longVal}
                  </div>
                )}
                placement="top"
                color="white"
                overlayStyle={{ maxWidth: '280px' }}
              >
                <div
                  style={{
                    width: '40px',
                    height: '40px',
                    background: hasResult ? getColor(sharpe) : '#f5f5f5',
                    border: '1px solid #e8e8e8',
                    borderRadius: '4px',
                    cursor: hasResult ? 'pointer' : 'default',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    transition: 'transform 0.2s',
                    fontSize: '10px',
                    fontWeight: 'bold'
                  }}
                  onMouseEnter={(e) => {
                    if (hasResult) {
                      e.currentTarget.style.transform = 'scale(1.1)';
                      e.currentTarget.style.zIndex = '1';
                      e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.15)';
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (hasResult) {
                      e.currentTarget.style.transform = 'scale(1)';
                      e.currentTarget.style.zIndex = '0';
                      e.currentTarget.style.boxShadow = 'none';
                    }
                  }}
                >
                  {hasResult && (
                    <span style={{
                      color: sharpe >= 0 ? '#000' : '#fff',
                      fontWeight: 'bold',
                      fontSize: '9px'
                    }}>
                      {sharpe.toFixed(1)}
                    </span>
                  )}
                </div>
              </Tooltip>
            );
          })}
        </React.Fragment>
      ))}
      
      {/* Color legend */}
      <div style={{ 
        gridColumn: `1 / span ${shortValues.length + 1}`,
        marginTop: '16px',
        paddingTop: '16px',
        borderTop: '1px solid #e8e8e8'
      }}>
        <div style={{ fontSize: '11px', color: '#666', marginBottom: '8px' }}>
          Sharpe Ratio Color Legend:
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ width: '12px', height: '12px', background: 'rgb(255, 0, 0)', marginRight: '4px' }}></div>
            <span>Low ({minSharpe.toFixed(2)})</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ width: '12px', height: '12px', background: 'rgb(255, 255, 0)', marginRight: '4px' }}></div>
            <span>Medium</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ width: '12px', height: '12px', background: 'rgb(0, 255, 0)', marginRight: '4px' }}></div>
            <span>High ({maxSharpe.toFixed(2)})</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{ width: '12px', height: '12px', background: '#f5f5f5', border: '1px solid #e8e8e8', marginRight: '4px' }}></div>
            <span>No Data</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OptimizationHeatmap;