import React from 'react';
import { Card, Row, Col, Statistic, Progress, Tag } from 'antd';
import { LineChartOutlined, RiseOutlined, FallOutlined } from '@ant-design/icons';

interface ChartDataPoint {
  date: string;
  price: number;
  volume: number;
}

interface FinancialChartProps {
  symbol: string;
  chartData?: ChartDataPoint[];
  currentPrice?: number;
  period?: '1D' | '1W' | '1M' | '3M' | '1Y' | '5Y';
}

const FinancialChart: React.FC<FinancialChartProps> = ({
  symbol,
  chartData = [],
  currentPrice = 0,
  period = '1M'
}) => {
  const safeNumber = (value: any): number => {
    return typeof value === 'number' && !isNaN(value) ? value : 0;
  };

  const safeToFixed = (value: any, decimals: number = 2): string => {
    const num = safeNumber(value);
    return num.toFixed(decimals);
  };

  // 模拟图表数据
  const generateMockData = () => {
    const data: ChartDataPoint[] = [];
    const basePrice = safeNumber(currentPrice);
    
    for (let i = 0; i < 30; i++) {
      const date = new Date();
      date.setDate(date.getDate() - (29 - i));
      
      // 模拟价格波动
      const volatility = 0.02;
      const randomChange = (Math.random() - 0.5) * 2 * volatility;
      const price = basePrice * (1 + randomChange);
      
      data.push({
        date: date.toISOString().split('T')[0],
        price: safeNumber(price),
        volume: Math.floor(Math.random() * 1000000) + 500000
      });
    }
    
    return data;
  };

  const displayData = chartData.length > 0 ? chartData : generateMockData();
  
  // 计算统计信息
  const prices = displayData.map(d => safeNumber(d.price));
  const maxPrice = Math.max(...prices);
  const minPrice = Math.min(...prices);
  const avgPrice = prices.reduce((sum, price) => sum + price, 0) / prices.length;
  
  const safeMaxPrice = safeNumber(maxPrice);
  const safeMinPrice = safeNumber(minPrice);
  const safeAvgPrice = safeNumber(avgPrice);
  const safeCurrentPrice = safeNumber(currentPrice);
  
  // 安全计算百分比变化
  const pctChange = safeMinPrice !== 0 ? ((safeMaxPrice - safeMinPrice) / safeMinPrice * 100) : 0;
  const currentVsAvg = safeAvgPrice !== 0 ? ((safeCurrentPrice - safeAvgPrice) / safeAvgPrice * 100) : 0;
  
  const periodLabels = {
    '1D': '1 Day',
    '1W': '1 Week',
    '1M': '1 Month',
    '3M': '3 Months',
    '1Y': '1 Year',
    '5Y': '5 Years'
  };

  return (
    <Card title={`${symbol} Price Chart`} extra={<LineChartOutlined />}>
      <Row gutter={[16, 16]}>
        <Col span={24}>
          <div style={{ 
            height: '200px', 
            background: 'linear-gradient(180deg, #f0f2f5 0%, #ffffff 100%)',
            borderRadius: '8px',
            padding: '16px',
            position: 'relative'
          }}>
            {/* 模拟图表 */}
            <div style={{ 
              display: 'flex', 
              alignItems: 'flex-end', 
              height: '150px',
              justifyContent: 'space-between',
              marginBottom: '8px'
            }}>
              {displayData.map((point, index) => {
                const price = safeNumber(point.price);
                const heightPercent = ((price - safeMinPrice) / (safeMaxPrice - safeMinPrice)) * 100;
                
                return (
                  <div
                    key={index}
                    style={{
                      width: '2%',
                      height: `${Math.max(heightPercent, 5)}%`,
                      backgroundColor: price >= safeCurrentPrice ? '#3f8600' : '#cf1322',
                      borderRadius: '2px',
                      position: 'relative'
                    }}
                    title={`${point.date}: $${safeToFixed(price, 2)}`}
                  />
                );
              })}
            </div>
            
            {/* X轴标签 */}
            <div style={{ 
              display: 'flex', 
              justifyContent: 'space-between',
              fontSize: '10px',
              color: '#666'
            }}>
              <span>{displayData[0]?.date || 'Start'}</span>
              <span>{periodLabels[period]}</span>
              <span>{displayData[displayData.length - 1]?.date || 'End'}</span>
            </div>
            
            {/* 当前价格线 */}
            <div style={{
              position: 'absolute',
              left: 0,
              right: 0,
              top: `${100 - ((safeCurrentPrice - safeMinPrice) / (safeMaxPrice - safeMinPrice)) * 100}%`,
              borderTop: '2px dashed #1890ff',
              opacity: 0.5
            }}>
              <div style={{
                position: 'absolute',
                right: '8px',
                top: '-12px',
                background: '#1890ff',
                color: 'white',
                padding: '2px 6px',
                borderRadius: '4px',
                fontSize: '12px'
              }}>
                Current: ${safeToFixed(safeCurrentPrice, 2)}
              </div>
            </div>
          </div>
        </Col>
      </Row>
      
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="Current Price"
              value={safeCurrentPrice}
              prefix="$"
              precision={2}
              valueStyle={{ fontSize: '18px' }}
            />
          </Card>
        </Col>
        
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="High"
              value={safeMaxPrice}
              prefix="$"
              precision={2}
              valueStyle={{ color: '#3f8600', fontSize: '18px' }}
            />
            <div style={{ fontSize: '12px', color: '#999', marginTop: '4px' }}>
              {safeToFixed(pctChange, 2)}% from low
            </div>
          </Card>
        </Col>
        
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="Low"
              value={safeMinPrice}
              prefix="$"
              precision={2}
              valueStyle={{ color: '#cf1322', fontSize: '18px' }}
            />
          </Card>
        </Col>
        
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="Average"
              value={safeAvgPrice}
              prefix="$"
              precision={2}
              valueStyle={{ fontSize: '18px' }}
            />
            <div style={{ fontSize: '12px', color: '#999', marginTop: '4px' }}>
              Current is {currentVsAvg >= 0 ? '+' : ''}{safeToFixed(currentVsAvg, 2)}%
            </div>
          </Card>
        </Col>
      </Row>
      
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <Tag color={safeCurrentPrice >= safeAvgPrice ? 'green' : 'red'} icon={safeCurrentPrice >= safeAvgPrice ? <RiseOutlined /> : <FallOutlined />}>
                {safeCurrentPrice >= safeAvgPrice ? 'Above' : 'Below'} Average
              </Tag>
              <span style={{ marginLeft: '8px', fontSize: '14px' }}>
                ${safeToFixed(Math.abs(safeCurrentPrice - safeAvgPrice), 2)} difference
              </span>
            </div>
            
            <div>
              <span style={{ marginRight: '8px', fontSize: '14px' }}>Price Range:</span>
              <Progress 
                percent={((safeCurrentPrice - safeMinPrice) / (safeMaxPrice - safeMinPrice)) * 100}
                size="small" 
                style={{ width: '100px' }}
                showInfo={false}
              />
              <span style={{ marginLeft: '8px', fontSize: '12px', color: '#666' }}>
                ${safeToFixed(safeMinPrice, 0)} - ${safeToFixed(safeMaxPrice, 0)}
              </span>
            </div>
          </div>
        </Col>
      </Row>
      
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <div style={{ 
            background: '#fafafa', 
            padding: '12px', 
            borderRadius: '6px',
            fontSize: '12px',
            color: '#666'
          }}>
            <strong>Chart Info:</strong> Showing {periodLabels[period]} price data for {symbol}. 
            {displayData.length > 0 ? ` Data points: ${displayData.length}.` : ' Using simulated data.'}
            {` Range: $${safeToFixed(safeMinPrice, 2)} - $${safeToFixed(safeMaxPrice, 2)} (${safeToFixed(pctChange, 2)}% spread).`}
          </div>
        </Col>
      </Row>
    </Card>
  );
};

export default FinancialChart;