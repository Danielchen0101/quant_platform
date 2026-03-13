import React from 'react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Scatter } from 'recharts';

interface DrawdownDataPoint {
  date: string;
  drawdown: number; // 百分比，负值表示回撤
}

interface EquityDataPoint {
  date: string;
  equity: number;
}

interface DrawdownChartProps {
  data: DrawdownDataPoint[];
  equityData?: EquityDataPoint[]; // 新增：用于显示 Equity 信息
  height?: number;
}

const DrawdownChart: React.FC<DrawdownChartProps> = ({ data, equityData, height = 200 }) => {
  if (!data || data.length === 0) {
    return (
      <div style={{ 
        height, 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center',
        background: '#fafafa',
        borderRadius: '8px',
        border: '1px solid #e8e8e8'
      }}>
        <div style={{ color: '#999', fontSize: '14px' }}>No drawdown data available</div>
      </div>
    );
  }

  // 找到最大回撤（最小的drawdown值，因为是负数）
  const maxDrawdown = Math.min(...data.map(d => d.drawdown));
  const maxDrawdownPoint = data.find(d => d.drawdown === maxDrawdown);
  
  // 准备最大回撤标记数据
  const maxDrawdownMarkerData = maxDrawdownPoint ? [{
    date: maxDrawdownPoint.date,
    drawdown: maxDrawdownPoint.drawdown,
    isMaxDrawdown: true
  }] : [];

  // 格式化日期
  const formatDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr);
      return `${date.getMonth() + 1}/${date.getDate()}`;
    } catch {
      return dateStr;
    }
  };

  // 格式化货币
  const formatCurrency = (amount: number): string => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(amount);
  };

  // 自定义Tooltip
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const point = payload[0].payload;
      
      // 查找对应的 Equity 数据
      let equityValue = null;
      if (equityData) {
        const equityPoint = equityData.find(d => d.date === label);
        if (equityPoint) {
          equityValue = equityPoint.equity;
        }
      }
      
      return (
        <div style={{
          backgroundColor: 'white',
          padding: '12px',
          border: '1px solid #e8e8e8',
          borderRadius: '4px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
          fontSize: '13px',
          minWidth: '180px'
        }}>
          <p style={{ margin: 0, fontWeight: 'bold', color: '#333', fontSize: '13px' }}>
            Date: {label}
          </p>
          
          {equityValue !== null && (
            <p style={{ margin: '6px 0 0 0', color: '#666' }}>
              Equity: <span style={{ 
                fontWeight: 'bold', 
                color: '#1890ff',
                fontSize: '13px'
              }}>
                {formatCurrency(equityValue)}
              </span>
            </p>
          )}
          
          <p style={{ margin: equityValue !== null ? '4px 0 0 0' : '6px 0 0 0', color: '#666' }}>
            Drawdown: <span style={{ 
              fontWeight: 'bold', 
              color: point.drawdown < 0 ? '#cf1322' : '#3f8600',
              fontSize: '13px'
            }}>
              {point.drawdown.toFixed(2)}%
            </span>
          </p>
          
          {point.isMaxDrawdown && (
            <p style={{ 
              margin: '6px 0 0 0', 
              color: '#cf1322',
              fontWeight: 'bold',
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center'
            }}>
              <span style={{ marginRight: '4px' }}>⚠️</span>
              Maximum Drawdown
            </p>
          )}
        </div>
      );
    }
    return null;
  };

  return (
    <div style={{ 
      height,
      background: '#fafafa',
      borderRadius: '8px',
      padding: '16px',
      border: '1px solid #e8e8e8'
    }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ top: 10, right: 30, left: 40, bottom: 10 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e8e8e8" vertical={false} />
          <XAxis 
            dataKey="date" 
            tick={{ fontSize: 12 }}  // 增大字体
            tickFormatter={formatDate}
            tickMargin={10}
          />
          <YAxis 
            tick={{ fontSize: 12 }}  // 增大字体
            tickFormatter={(value) => `${value.toFixed(1)}%`}
            domain={[maxDrawdown - 1, 0]} // 固定顶部为0%，底部留1%空间
            tickMargin={10}
            allowDataOverflow={false}
          />
          <Tooltip content={<CustomTooltip />} />
          
          {/* 零线 */}
          <Area
            type="linear"
            dataKey={() => 0}
            stroke="#999"
            strokeWidth={1}
            strokeDasharray="3 3"
            fill="none"
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
          
          {/* 回撤区域 */}
          <Area
            type="monotone"
            dataKey="drawdown"
            stroke="#cf1322"
            strokeWidth={2}
            fill="url(#drawdownGradient)"
            fillOpacity={0.6}
            activeDot={{ 
              r: 4, 
              stroke: '#fff', 
              strokeWidth: 2,
              fill: '#cf1322'
            }}
            connectNulls
          />
          
          {/* 最大回撤标记 - 使用 Scatter 组件 */}
          {maxDrawdownMarkerData.length > 0 && (
            <Scatter
              data={maxDrawdownMarkerData}
              dataKey="drawdown"
              fill="#cf1322"
              shape={(props: any) => {
                const { cx, cy } = props;
                return (
                  <g>
                    <circle 
                      cx={cx} 
                      cy={cy} 
                      r={6}  // 半径6px
                      fill="#cf1322" 
                      stroke="white" 
                      strokeWidth={2}
                      opacity={1}
                      filter="drop-shadow(0px 1px 2px rgba(0,0,0,0.3))"
                    />
                    <circle 
                      cx={cx} 
                      cy={cy} 
                      r={3}  // 内圆
                      fill="white" 
                      opacity={1}
                    />
                  </g>
                );
              }}
              name="Max Drawdown"
            />
          )}
          
          {/* 渐变定义 */}
          <defs>
            <linearGradient id="drawdownGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#cf1322" stopOpacity={0.8}/>
              <stop offset="95%" stopColor="#cf1322" stopOpacity={0.1}/>
            </linearGradient>
          </defs>
        </AreaChart>
      </ResponsiveContainer>
      
      {/* 图例 */}
      <div style={{ 
        marginTop: '16px',
        fontSize: '13px',  // 增大字体
        color: '#666',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <span style={{ 
            display: 'inline-block', 
            width: '14px',  // 增大
            height: '14px',  // 增大
            background: 'linear-gradient(to bottom, #cf1322, #ffa39e)',
            marginRight: '8px',  // 增大间距
            borderRadius: '3px'
          }}></span>
          <span style={{ fontWeight: '500' }}>Drawdown</span>
        </div>
        
        {maxDrawdownPoint && (
          <div style={{ 
            fontSize: '13px',  // 增大字体
            color: '#cf1322',
            fontWeight: '600',  // 加粗
            display: 'flex',
            alignItems: 'center'
          }}>
            <span style={{ 
              display: 'inline-block',
              width: '8px',
              height: '8px',
              backgroundColor: '#cf1322',
              borderRadius: '50%',
              marginRight: '6px',
              border: '1px solid white',
              boxShadow: '0 0 2px rgba(0,0,0,0.3)'
            }}></span>
            Max Drawdown: <span style={{ marginLeft: '4px', fontWeight: '700' }}>
              {maxDrawdown.toFixed(2)}%
            </span>
            {maxDrawdownPoint.date && (
              <span style={{ marginLeft: '8px', color: '#999', fontWeight: '500', fontSize: '12px' }}>
                on {formatDate(maxDrawdownPoint.date)}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default DrawdownChart;