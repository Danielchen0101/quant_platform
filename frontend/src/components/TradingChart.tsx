import React, { useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, Scatter, BarChart, Bar, ResponsiveContainer, Cell } from 'recharts';
import { Checkbox, Space, Card, Row, Col } from 'antd';

interface ChartDataItem {
  date: string;
  close: number;
  volume?: number;  // Volume for volume chart (optional)
  signal: number;   // 1: buy, -1: sell, 0: no signal
  sma20?: number;
  sma50?: number;
}

interface TradingChartProps {
  data: ChartDataItem[];
  height?: number;
  parameters?: {
    strategy?: string;
    symbol?: string;
    period?: string;
    initialCapital?: number;
  };
}

const TradingChart: React.FC<TradingChartProps> = ({ data, height = 500, parameters }) => {
  // State for chart controls
  const [showClosePrice, setShowClosePrice] = useState(true);
  const [showSMA20, setShowSMA20] = useState(true);
  const [showSMA50, setShowSMA50] = useState(true);
  const [showSignals, setShowSignals] = useState(true);
  const [showVolume, setShowVolume] = useState(true);

  if (!data || data.length === 0) {
    return (
      <div style={{ 
        height, 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center',
        border: '1px solid #e8e8e8',
        borderRadius: '8px',
        backgroundColor: '#fafafa'
      }}>
        <div style={{ color: '#999', fontSize: '16px' }}>No chart data available</div>
      </div>
    );
  }

  // Prepare data for Recharts with volume color calculation
  const chartData = data.map((item, index) => {
    // Calculate volume color based on price movement
    let volumeColor = '#999'; // Default gray
    if (item.volume !== undefined && item.volume > 0) {
      if (index === 0) {
        // First day, no previous close to compare
        volumeColor = '#999';
      } else {
        const currentClose = item.close;
        const prevClose = data[index - 1].close;
        volumeColor = currentClose >= prevClose ? '#52c41a' : '#f5222d';
      }
    }

    // Enhanced signal data with tooltip text
    const signalType = item.signal === 1 ? 'BUY' : item.signal === -1 ? 'SELL' : null;
    const signalColor = item.signal === 1 ? '#52c41a' : '#f5222d';

    return {
      ...item,
      // Enhanced signal data
      buySignal: item.signal === 1 ? item.close : null,
      sellSignal: item.signal === -1 ? item.close : null,
      signalType,
      signalColor,
      // Add volume color for styling
      volumeColor,
      // For volume chart, we need a separate value for display
      volumeDisplay: item.volume || 0,
    };
  });

  // Find min and max for better Y-axis scaling (price chart)
  const prices = data.map(d => d.close).filter(Boolean);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const pricePadding = (maxPrice - minPrice) * 0.1; // 10% padding

  // Find min and max for volume Y-axis scaling
  const volumes = data.map(d => d.volume || 0).filter(Boolean);
  const maxVolume = volumes.length > 0 ? Math.max(...volumes) : 0;
  const volumePadding = maxVolume * 0.1; // 10% padding

  // Check if we have data to decide what to show
  const hasVolumeData = data.some(d => d.volume !== undefined && d.volume > 0);
  const hasSMA20 = data.some(d => d.sma20 !== undefined);
  const hasSMA50 = data.some(d => d.sma50 !== undefined);
  const hasSignals = data.some(d => d.signal !== 0);
  
  // Debug: Check signal data
  const buySignals = data.filter(d => d.signal === 1);
  const sellSignals = data.filter(d => d.signal === -1);
  console.log(`TradingChart Debug: Total data points: ${data.length}`);
  console.log(`TradingChart Debug: Buy signals: ${buySignals.length}`);
  console.log(`TradingChart Debug: Sell signals: ${sellSignals.length}`);
  console.log(`TradingChart Debug: Has signals: ${hasSignals}`);

  // Calculate chart heights with optimized proportions
  const priceChartHeight = (hasVolumeData && showVolume) ? height * 0.65 : height * 0.8;
  const volumeChartHeight = (hasVolumeData && showVolume) ? height * 0.35 : 0;

  // Format date for X-axis
  const formatDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr);
      return `${date.getMonth() + 1}/${date.getDate()}`;
    } catch {
      return dateStr;
    }
  };

  // Custom tooltip component with offset to avoid covering data points
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      // Find the data point
      const dataPoint = chartData.find(item => item.date === label);
      if (!dataPoint) return null;

      return (
        <div style={{
          backgroundColor: 'white',
          padding: '12px',
          border: '1px solid #e8e8e8',
          borderRadius: '4px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
          transform: 'translate(-50%, -100%)', // Offset to avoid covering data point
          marginTop: '-10px' // Additional offset
        }}>
          <p style={{ margin: 0, fontWeight: 'bold', color: '#333' }}>
            Date: {label}
          </p>
          <p style={{ margin: '4px 0 0 0', color: '#666' }}>
            Close Price: <span style={{ fontWeight: 'bold', color: '#1890ff' }}>
              ${dataPoint.close.toFixed(2)}
            </span>
          </p>
          
          {dataPoint.sma20 !== undefined && (
            <p style={{ margin: '2px 0 0 0', color: '#666' }}>
              SMA 20: <span style={{ fontWeight: 'bold', color: '#52c41a' }}>
                ${dataPoint.sma20.toFixed(2)}
              </span>
            </p>
          )}
          
          {dataPoint.sma50 !== undefined && (
            <p style={{ margin: '2px 0 0 0', color: '#666' }}>
              SMA 50: <span style={{ fontWeight: 'bold', color: '#fa8c16' }}>
                ${dataPoint.sma50.toFixed(2)}
              </span>
            </p>
          )}
          
          {dataPoint.volume !== undefined && dataPoint.volume > 0 && (
            <p style={{ margin: '2px 0 0 0', color: '#666' }}>
              Volume: <span style={{ fontWeight: 'bold' }}>
                {formatVolume(dataPoint.volume)}
              </span>
            </p>
          )}
          
          {dataPoint.signal !== 0 && (
            <p style={{ 
              margin: '4px 0 0 0', 
              fontWeight: 'bold',
              color: dataPoint.signal === 1 ? '#52c41a' : '#f5222d'
            }}>
              Signal: {dataPoint.signal === 1 ? 'BUY' : 'SELL'}
            </p>
          )}
        </div>
      );
    }
    return null;
  };

  // Format volume for display
  const formatVolume = (volume: number): string => {
    if (volume >= 1000000) {
      return `${(volume / 1000000).toFixed(1)}M`;
    } else if (volume >= 1000) {
      return `${(volume / 1000).toFixed(0)}K`;
    }
    return volume.toString();
  };

  // Format currency
  const formatCurrency = (amount: number): string => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(amount);
  };

  // Custom shape for buy signals - Enhanced visibility with z-index
  const BuySignalShape = (props: any) => {
    const { cx, cy } = props;
    return (
      <g style={{ pointerEvents: 'all' }}>
        <circle 
          cx={cx} 
          cy={cy} 
          r={10}
          fill="#52c41a" 
          stroke="white" 
          strokeWidth={2}
          opacity={0.95}
          filter="drop-shadow(0px 1px 2px rgba(0,0,0,0.2))"
        />
        <text
          x={cx}
          y={cy}
          dy={4}
          textAnchor="middle"
          fill="white"
          fontSize={12}
          fontWeight="bold"
        >
          B
        </text>
      </g>
    );
  };

  // Custom shape for sell signals - Enhanced visibility with z-index
  const SellSignalShape = (props: any) => {
    const { cx, cy } = props;
    return (
      <g style={{ pointerEvents: 'all' }}>
        <circle 
          cx={cx} 
          cy={cy} 
          r={10}
          fill="#f5222d" 
          stroke="white" 
          strokeWidth={2}
          opacity={0.95}
          filter="drop-shadow(0px 1px 2px rgba(0,0,0,0.2))"
        />
        <text
          x={cx}
          y={cy}
          dy={4}
          textAnchor="middle"
          fill="white"
          fontSize={12}
          fontWeight="bold"
        >
          S
        </text>
      </g>
    );
  };

  return (
    <div style={{ 
      border: '1px solid #e8e8e8', 
      borderRadius: '8px', 
      padding: '20px',
      backgroundColor: '#fff',
      minHeight: height
    }}>
      {/* Header with Chart Controls - Optimized position */}
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center', 
        marginBottom: '20px',
        padding: '0 8px' // Added padding to keep distance from edges
      }}>
        <h4 style={{ margin: 0, color: '#333' }}>Price Chart with Trading Signals</h4>
        
        {/* Chart Controls - Optimized with more padding */}
        <Card size="small" style={{ 
          width: 'auto',
          padding: '8px 12px',
          boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
        }}>
          <Space direction="horizontal" size="middle">
            <Checkbox 
              checked={showClosePrice} 
              onChange={(e) => setShowClosePrice(e.target.checked)}
            >
              Close Price
            </Checkbox>
            
            {hasSMA20 && (
              <Checkbox 
                checked={showSMA20} 
                onChange={(e) => setShowSMA20(e.target.checked)}
              >
                SMA 20
              </Checkbox>
            )}
            
            {hasSMA50 && (
              <Checkbox 
                checked={showSMA50} 
                onChange={(e) => setShowSMA50(e.target.checked)}
              >
                SMA 50
              </Checkbox>
            )}
            
            {hasSignals && (
              <Checkbox 
                checked={showSignals} 
                onChange={(e) => setShowSignals(e.target.checked)}
              >
                Buy/Sell Signals
              </Checkbox>
            )}
            
            {hasVolumeData && (
              <Checkbox 
                checked={showVolume} 
                onChange={(e) => setShowVolume(e.target.checked)}
              >
                Volume
              </Checkbox>
            )}
          </Space>
        </Card>
      </div>
      
      {/* Price Chart */}
      <div style={{ 
        height: priceChartHeight, 
        marginBottom: (hasVolumeData && showVolume) ? '32px' : '0'  // Increased spacing
      }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={chartData}
            margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis 
              dataKey="date" 
              tick={{ fontSize: 12 }}
              tickFormatter={formatDate}
            />
            <YAxis 
              domain={[minPrice - pricePadding, maxPrice + pricePadding]}
              tick={{ fontSize: 12 }}
              tickFormatter={(value) => `$${value.toFixed(2)}`}
            />
            <Tooltip 
              content={<CustomTooltip />}
              offset={10} // Add offset to tooltip
            />
            <Legend wrapperStyle={{ paddingTop: '10px' }} />
            
            {/* Price line */}
            {showClosePrice && (
              <Line
                type="monotone"
                dataKey="close"
                stroke="#1890ff"
                strokeWidth={2}
                dot={false}
                name="Close Price"
                activeDot={{ r: 6 }}
              />
            )}
            
            {/* SMA20 line */}
            {showSMA20 && hasSMA20 && (
              <Line
                type="monotone"
                dataKey="sma20"
                stroke="#52c41a"
                strokeWidth={1.5}
                strokeDasharray="5 5"
                dot={false}
                name="SMA 20"
              />
            )}
            
            {/* SMA50 line */}
            {showSMA50 && hasSMA50 && (
              <Line
                type="monotone"
                dataKey="sma50"
                stroke="#fa8c16"
                strokeWidth={1.5}
                strokeDasharray="5 5"
                dot={false}
                name="SMA 50"
              />
            )}
            
            {/* Buy signals - Rendered last to ensure they're on top */}
            {showSignals && hasSignals && (
              <Scatter
                dataKey="buySignal"
                fill="#52c41a"
                shape={BuySignalShape}
                name="Buy Signal"
              />
            )}
            
            {/* Sell signals - Rendered last to ensure they're on top */}
            {showSignals && hasSignals && (
              <Scatter
                dataKey="sellSignal"
                fill="#f5222d"
                shape={SellSignalShape}
                name="Sell Signal"
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Volume Chart (only if we have volume data and it's enabled) */}
      {hasVolumeData && showVolume && (
        <div style={{ 
          height: volumeChartHeight, 
          marginBottom: '24px'  // Spacing before legend
        }}>
          <h5 style={{ marginBottom: '12px', color: '#666', fontSize: '14px' }}>Volume Chart</h5>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartData}
              margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
              <XAxis 
                dataKey="date" 
                tick={{ fontSize: 10 }}
                tickFormatter={formatDate}
              />
              <YAxis 
                tick={{ fontSize: 10 }}
                tickFormatter={(value) => {
                  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
                  if (value >= 1000) return `${(value / 1000).toFixed(0)}K`;
                  return value;
                }}
              />
              <Tooltip 
                formatter={(value: any) => [formatVolume(value), 'Volume']}
                labelFormatter={(label) => `Date: ${label}`}
                offset={10}
              />
              
              {/* Volume bars with dynamic colors */}
              <Bar
                dataKey="volumeDisplay"
                name="Volume"
                fill="#999"  // Default color
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.volumeColor || '#999'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Unified Legend - All in one place below Volume Chart */}
      <div style={{ 
        marginTop: '0',
        marginBottom: '24px',  // Spacing before parameters
        padding: '16px',
        backgroundColor: '#fafafa',
        borderRadius: '6px',
        border: '1px solid #e8e8e8',
        fontSize: '13px',
        color: '#666',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
        gap: '16px',
        alignItems: 'center'
      }}>
        {showClosePrice && (
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span style={{ 
              display: 'inline-block', 
              width: '14px', 
              height: '14px', 
              backgroundColor: '#1890ff', 
              marginRight: '8px',
              borderRadius: '2px'
            }}></span>
            <span>Close Price</span>
          </div>
        )}
        {showSMA20 && hasSMA20 && (
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span style={{ 
              display: 'inline-block', 
              width: '14px', 
              height: '14px', 
              backgroundColor: '#52c41a', 
              marginRight: '8px',
              borderRadius: '2px'
            }}></span>
            <span>SMA 20</span>
          </div>
        )}
        {showSMA50 && hasSMA50 && (
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span style={{ 
              display: 'inline-block', 
              width: '14px', 
              height: '14px', 
              backgroundColor: '#fa8c16', 
              marginRight: '8px',
              borderRadius: '2px'
            }}></span>
            <span>SMA 50</span>
          </div>
        )}
        {showSignals && hasSignals && (
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{
              width: '18px',
              height: '18px',
              borderRadius: '50%',
              backgroundColor: '#52c41a',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginRight: '8px',
              color: 'white',
              fontSize: '11px',
              fontWeight: 'bold',
              border: '1px solid white'
            }}>
              B
            </div>
            <span>Buy Signal</span>
          </div>
        )}
        {showSignals && hasSignals && (
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{
              width: '18px',
              height: '18px',
              borderRadius: '50%',
              backgroundColor: '#f5222d',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginRight: '8px',
              color: 'white',
              fontSize: '11px',
              fontWeight: 'bold',
              border: '1px solid white'
            }}>
              S
            </div>
            <span>Sell Signal</span>
          </div>
        )}
        {hasVolumeData && showVolume && (
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span style={{ 
              display: 'inline-block', 
              width: '14px', 
              height: '14px', 
              backgroundColor: '#52c41a', 
              marginRight: '8px',
              borderRadius: '2px'
            }}></span>
            <span>Volume Up</span>
          </div>
        )}
        {hasVolumeData && showVolume && (
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <span style={{ 
              display: 'inline-block', 
              width: '14px', 
              height: '14px', 
              backgroundColor: '#f5222d', 
              marginRight: '8px',
              borderRadius: '2px'
            }}></span>
            <span>Volume Down</span>
          </div>
        )}
      </div>

      {/* Parameters Section - At the bottom with responsive grid */}
      {parameters && (
        <div style={{ 
          marginTop: '0',
          paddingTop: '20px',
          borderTop: '1px solid #f0f0f0'
        }}>
          <h5 style={{ marginBottom: '16px', color: '#666', fontSize: '14px' }}>Parameters</h5>
          <Row gutter={[16, 16]}>
            {parameters.strategy && (
              <Col xs={24} sm={12} md={6} lg={6}>
                <div style={{ 
                  padding: '12px',
                  backgroundColor: '#fafafa',
                  borderRadius: '6px',
                  border: '1px solid #e8e8e8'
                }}>
                  <div style={{ fontSize: '12px', color: '#999', marginBottom: '4px' }}>Strategy</div>
                  <div style={{ fontSize: '14px', fontWeight: '500', color: '#333' }}>
                    {parameters.strategy}
                  </div>
                </div>
              </Col>
            )}
            {parameters.symbol && (
              <Col xs={24} sm={12} md={6} lg={6}>
                <div style={{ 
                  padding: '12px',
                  backgroundColor: '#fafafa',
                  borderRadius: '6px',
                  border: '1px solid #e8e8e8'
                }}>
                  <div style={{ fontSize: '12px', color: '#999', marginBottom: '4px' }}>Symbol</div>
                  <div style={{ fontSize: '14px', fontWeight: '500', color: '#333' }}>
                    {parameters.symbol}
                  </div>
                </div>
              </Col>
            )}
            {parameters.period && (
              <Col xs={24} sm={12} md={6} lg={6}>
                <div style={{ 
                  padding: '12px',
                  backgroundColor: '#fafafa',
                  borderRadius: '6px',
                  border: '1px solid #e8e8e8'
                }}>
                  <div style={{ fontSize: '12px', color: '#999', marginBottom: '4px' }}>Period</div>
                  <div style={{ fontSize: '14px', fontWeight: '500', color: '#333' }}>
                    {parameters.period}
                  </div>
                </div>
              </Col>
            )}
            {parameters.initialCapital && (
              <Col xs={24} sm={12} md={6} lg={6}>
                <div style={{ 
                  padding: '12px',
                  backgroundColor: '#fafafa',
                  borderRadius: '6px',
                  border: '1px solid #e8e8e8'
                }}>
                  <div style={{ fontSize: '12px', color: '#999', marginBottom: '4px' }}>Initial Capital</div>
                  <div style={{ fontSize: '14px', fontWeight: '500', color: '#333' }}>
                    {formatCurrency(parameters.initialCapital)}
                  </div>
                </div>
              </Col>
            )}
          </Row>
        </div>
      )}
    </div>
  );
};

export default TradingChart;
