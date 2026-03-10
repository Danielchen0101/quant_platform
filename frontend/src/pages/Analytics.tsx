import React from 'react';
import { Card, Row, Col, Typography, Progress, List, Tag } from 'antd';
import { 
  LineChartOutlined, 
  PieChartOutlined, 
  BarChartOutlined,
  RiseOutlined,
  FallOutlined
} from '@ant-design/icons';

const { Title, Text } = Typography;

const Analytics: React.FC = () => {
  const performanceData = [
    { month: 'Jan', value: 65 },
    { month: 'Feb', value: 72 },
    { month: 'Mar', value: 80 },
    { month: 'Apr', value: 75 },
    { month: 'May', value: 85 },
    { month: 'Jun', value: 90 },
  ];

  const topPerformers = [
    { symbol: 'AAPL', name: 'Apple Inc.', return: 25.4, risk: 'Low' },
    { symbol: 'MSFT', name: 'Microsoft', return: 18.7, risk: 'Medium' },
    { symbol: 'GOOGL', name: 'Alphabet', return: 15.2, risk: 'Low' },
    { symbol: 'AMZN', name: 'Amazon', return: 12.8, risk: 'High' },
    { symbol: 'TSLA', name: 'Tesla', return: 8.5, risk: 'High' },
  ];

  const riskMetrics = [
    { metric: 'Sharpe Ratio', value: 1.8, target: '>1.5', status: 'good' },
    { metric: 'Max Drawdown', value: -8.5, target: '<-10%', status: 'good' },
    { metric: 'Volatility', value: 12.3, target: '<15%', status: 'good' },
    { metric: 'Beta', value: 1.2, target: '0.8-1.2', status: 'warning' },
  ];

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24}>
          <Card>
            <Title level={3} style={{ margin: 0 }}>
              <LineChartOutlined /> Portfolio Analytics
            </Title>
            <Text type="secondary">Comprehensive analysis of your portfolio performance</Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} lg={8}>
          <Card title="Performance Overview">
            <div style={{ textAlign: 'center' }}>
              <Progress
                type="circle"
                percent={85}
                strokeColor={{
                  '0%': '#108ee9',
                  '100%': '#87d068',
                }}
                format={() => (
                  <div>
                    <div style={{ fontSize: 24, fontWeight: 'bold' }}>85%</div>
                    <div style={{ fontSize: 12, color: '#666' }}>YTD Return</div>
                  </div>
                )}
              />
            </div>
            <List
              dataSource={performanceData}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta
                    title={item.month}
                    description={
                      <Progress
                        percent={item.value}
                        size="small"
                        strokeColor={item.value >= 80 ? '#52c41a' : '#1890ff'}
                      />
                    }
                  />
                  <Text strong>{item.value}%</Text>
                </List.Item>
              )}
            />
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="Risk Metrics">
            <List
              dataSource={riskMetrics}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta
                    title={item.metric}
                    description={`Target: ${item.target}`}
                  />
                  <div>
                    <Text strong style={{ marginRight: 8 }}>
                      {typeof item.value === 'number' && item.value > 0 ? '+' : ''}{item.value}
                      {item.metric === 'Volatility' || item.metric === 'Max Drawdown' ? '%' : ''}
                    </Text>
                    <Tag color={
                      item.status === 'good' ? 'success' : 
                      item.status === 'warning' ? 'warning' : 'error'
                    }>
                      {item.status === 'good' ? 'Good' : 'Needs Attention'}
                    </Tag>
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="Asset Allocation">
            <div style={{ textAlign: 'center', marginBottom: 24 }}>
              <Progress
                type="dashboard"
                percent={100}
                strokeColor={{
                  '0%': '#108ee9',
                  '25%': '#2db7f5',
                  '50%': '#87d068',
                  '75%': '#ffc53d',
                  '100%': '#ff4d4f',
                }}
                format={() => (
                  <div>
                    <div style={{ fontSize: 24, fontWeight: 'bold' }}>Diversified</div>
                    <div style={{ fontSize: 12, color: '#666' }}>Portfolio</div>
                  </div>
                )}
              />
            </div>
            <List
              dataSource={[
                { asset: 'Stocks', allocation: 60, color: '#1890ff' },
                { asset: 'Bonds', allocation: 25, color: '#52c41a' },
                { asset: 'Cash', allocation: 10, color: '#faad14' },
                { asset: 'Alternatives', allocation: 5, color: '#f5222d' },
              ]}
              renderItem={(item) => (
                <List.Item>
                  <div style={{ display: 'flex', alignItems: 'center', width: '100%' }}>
                    <div style={{ width: 12, height: 12, backgroundColor: item.color, marginRight: 8 }} />
                    <Text style={{ flex: 1 }}>{item.asset}</Text>
                    <Text strong>{item.allocation}%</Text>
                  </div>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24}>
          <Card title="Top Performers">
            <List
              dataSource={topPerformers}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Tag color={item.risk === 'Low' ? 'success' : item.risk === 'Medium' ? 'warning' : 'error'}>
                      {item.risk} Risk
                    </Tag>,
                    <Text strong style={{ color: item.return >= 0 ? '#52c41a' : '#ff4d4f' }}>
                      {item.return >= 0 ? <RiseOutlined /> : <FallOutlined />}
                      {item.return}%
                    </Text>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={
                      <div style={{
                        width: 40,
                        height: 40,
                        borderRadius: '50%',
                        backgroundColor: '#1890ff',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: '#fff',
                        fontWeight: 'bold',
                      }}>
                        {item.symbol.charAt(0)}
                      </div>
                    }
                    title={<Text strong>{item.symbol}</Text>}
                    description={item.name}
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Analytics;