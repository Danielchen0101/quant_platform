import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Layout, ConfigProvider } from 'antd';
import Dashboard from './pages/Dashboard';
import Market from './pages/Market';
import Backtest from './pages/Backtest';
import BacktestDetail from './pages/BacktestDetail';
import StrategyComparison from './pages/StrategyComparison';
import Watchlist from './pages/Watchlist';
import StrategyRanking from './pages/StrategyRanking';
import ParameterOptimization from './pages/ParameterOptimization';
import Analytics from './pages/Analytics';
import LanguageTest from './pages/LanguageTest';
import LanguageButtonPreview from './components/LanguageButtonPreview';
import LanguageSwitcher from './components/LanguageSwitcher';
import NavigationMenu from './components/NavigationMenu';
import { LanguageProvider } from './contexts/LanguageContext';
import './App.css';

const { Header, Content, Sider } = Layout;

const App: React.FC = () => {
  return (
    <LanguageProvider>
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
              <div style={{ 
                height: 32, 
                margin: 16,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#fff',
                fontSize: '18px',
                fontWeight: 'bold',
                letterSpacing: '0.5px'
              }}>
                AlphaLab
              </div>
              <NavigationMenu />
            </Sider>
            <Layout>
              <Header style={{ padding: '0 24px', background: '#fff', display: 'flex', justifyContent: 'flex-end', alignItems: 'center' }}>
                <LanguageSwitcher />
              </Header>
              <Content style={{ margin: '24px 16px 0', overflow: 'initial' }}>
                <div style={{ padding: 24, background: '#fff', borderRadius: 8 }}>
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/market" element={<Market />} />
                    <Route path="/backtest" element={<Backtest />} />
                    <Route path="/backtest/:id" element={<BacktestDetail />} />
                    <Route path="/compare" element={<StrategyComparison />} />
                    <Route path="/optimize" element={<ParameterOptimization />} />
                    <Route path="/watchlist" element={<Watchlist />} />
                    <Route path="/ranking" element={<StrategyRanking />} />
                    <Route path="/analytics" element={<Analytics />} />
                    <Route path="/profile" element={<div>Profile Page (Coming Soon)</div>} />
                    <Route path="/language-test" element={<LanguageTest />} />
                    <Route path="/button-preview" element={<LanguageButtonPreview />} />
                  </Routes>
                </div>
              </Content>
            </Layout>
          </Layout>
        </Router>
      </ConfigProvider>
    </LanguageProvider>
  );
};

export default App;