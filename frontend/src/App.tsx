import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import { Layout, Menu, ConfigProvider } from 'antd';
import { DashboardOutlined, LineChartOutlined, BarChartOutlined, UserOutlined, TrophyOutlined, UnorderedListOutlined, SwapOutlined } from '@ant-design/icons';
import Dashboard from './pages/Dashboard';
import Market from './pages/Market';
import Backtest from './pages/Backtest';
import BacktestDetail from './pages/BacktestDetail';
import StrategyComparison from './pages/StrategyComparison';
import Watchlist from './pages/Watchlist';
import StrategyRanking from './pages/StrategyRanking';
import './App.css';

const { Header, Content, Sider } = Layout;

const App: React.FC = () => {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#1890ff',
          borderRadius: 6,
        },
      }}
    >
      <Router>
        <Layout style={{ minHeight: '100vh' }}>
          <Sider collapsible>
            <div style={{ height: 32, margin: 16, background: 'rgba(255, 255, 255, 0.2)', borderRadius: 6 }} />
            <Menu theme="dark" mode="inline" defaultSelectedKeys={['1']}>
              <Menu.Item key="1" icon={<DashboardOutlined />}>
                <Link to="/">Dashboard</Link>
              </Menu.Item>
              <Menu.Item key="2" icon={<LineChartOutlined />}>
                <Link to="/market">Market</Link>
              </Menu.Item>
              <Menu.Item key="3" icon={<BarChartOutlined />}>
                <Link to="/backtest">Backtest</Link>
              </Menu.Item>
              <Menu.Item key="4" icon={<SwapOutlined />}>
                <Link to="/compare">Strategy Comparison</Link>
              </Menu.Item>
              <Menu.Item key="5" icon={<TrophyOutlined />}>
                <Link to="/ranking">Strategy Ranking</Link>
              </Menu.Item>
              <Menu.Item key="6" icon={<UnorderedListOutlined />}>
                <Link to="/watchlist">Watchlist</Link>
              </Menu.Item>
              <Menu.Item key="7" icon={<UserOutlined />}>
                <Link to="/profile">Profile</Link>
              </Menu.Item>
            </Menu>
          </Sider>
          <Layout>
            <Header style={{ padding: 0, background: '#fff' }} />
            <Content style={{ margin: '24px 16px 0', overflow: 'initial' }}>
              <div style={{ padding: 24, background: '#fff', borderRadius: 8 }}>
                <Routes>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/market" element={<Market />} />
                  <Route path="/backtest" element={<Backtest />} />
                  <Route path="/backtest/:id" element={<BacktestDetail />} />
                  <Route path="/compare" element={<StrategyComparison />} />
                  <Route path="/watchlist" element={<Watchlist />} />
                  <Route path="/ranking" element={<StrategyRanking />} />
                  <Route path="/profile" element={<div>Profile Page (Coming Soon)</div>} />
                </Routes>
              </div>
            </Content>
          </Layout>
        </Layout>
      </Router>
    </ConfigProvider>
  );
};

export default App;