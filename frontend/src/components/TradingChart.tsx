import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, Scatter } from 'recharts';

interface ChartDataItem {
  date: string;
  close: number;
  signal: number;  // 1: buy, -1: sell, 0: no signal
  sma20?: number;
  sma50?: number;
}

interface TradingChartProps {
  data: ChartDataItem[];
  height?: number;
}

const TradingChart: React.FC<TradingChartProps> = ({ data, height = 400 }) => {
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

  // Prepare data for Recharts
  const chartData = data.map(item => ({
    ...item,
    // Create separate fields for buy/sell signals
    buySignal: item.signal === 1 ? item.close : null,
    sellSignal: item.signal === -1 ? item.close : null,
  }));

  // Find min and max for better Y-axis scaling
  const prices = data.map(d => d.close).filter(Boolean);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const padding = (maxPrice - minPrice) * 0.1; // 10% padding

  return (
    <div style={{ 
      border: '1px solid #e8e8e8', 
      borderRadius: '8px', 
      padding: '16px',
      backgroundColor: '#fff'
    }}>
      <h4 style={{ marginBottom: '16px', color: '#333' }}>Price Chart with Trading Signals</h4>
      
      <LineChart
        width={800}
        height={height}
        data={chartData}
        margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis 
          dataKey="date" 
          tick={{ fontSize: 12 }}
          tickFormatter={(value) => {
            // Show only some dates to avoid crowding
            const date = new Date(value);
            return `${date.getMonth() + 1}/${date.getDate()}`;
          }}
        />
        <YAxis 
          domain={[minPrice - padding, maxPrice + padding]}
          tick={{ fontSize: 12 }}
          tickFormatter={(value) => `$${value.toFixed(2)}`}
        />
        <Tooltip 
          formatter={(value, name) => {
            if (name === 'close' || name === 'sma20' || name === 'sma50') {
              return [`$${Number(value).toFixed(2)}`, name];
            }
            return [value, name];
          }}
          labelFormatter={(label) => `Date: ${label}`}
        />
        <Legend />
        
        {/* Price line */}
        <Line
          type="monotone"
          dataKey="close"
          stroke="#1890ff"
          strokeWidth={2}
          dot={false}
          name="Close Price"
        />
        
        {/* SMA20 line */}
        {data.some(d => d.sma20 !== undefined) && (
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
        {data.some(d => d.sma50 !== undefined) && (
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
        
        {/* Buy signals */}
        <Scatter
          dataKey="buySignal"
          fill="#52c41a"
          shape="triangle"
          name="Buy Signal"
        />
        
        {/* Sell signals */}
        <Scatter
          dataKey="sellSignal"
          fill="#f5222d"
          shape="triangle"
          name="Sell Signal"
        />
      </LineChart>
      
      <div style={{ 
        marginTop: '16px', 
        fontSize: '12px', 
        color: '#666',
        display: 'flex',
        justifyContent: 'space-between'
      }}>
        <div>
          <span style={{ display: 'inline-block', width: '12px', height: '12px', backgroundColor: '#1890ff', marginRight: '4px' }}></span>
          <span>Close Price</span>
        </div>
        <div>
          <span style={{ display: 'inline-block', width: '12px', height: '12px', backgroundColor: '#52c41a', marginRight: '4px' }}></span>
          <span>SMA 20</span>
        </div>
        <div>
          <span style={{ display: 'inline-block', width: '12px', height: '12px', backgroundColor: '#fa8c16', marginRight: '4px' }}></span>
          <span>SMA 50</span>
        </div>
        <div>
          <span style={{ color: '#52c41a', fontWeight: 'bold' }}>▲</span>
          <span> Buy Signal</span>
        </div>
        <div>
          <span style={{ color: '#f5222d', fontWeight: 'bold' }}>▼</span>
          <span> Sell Signal</span>
        </div>
      </div>
    </div>
  );
};

export default TradingChart;