import React from 'react';
import { Link } from 'react-router-dom';
import { Menu } from 'antd';
import { 
  DashboardOutlined, 
  LineChartOutlined, 
  BarChartOutlined, 
  UserOutlined, 
  TrophyOutlined, 
  UnorderedListOutlined, 
  SwapOutlined, 
  RocketOutlined 
} from '@ant-design/icons';
import { useLanguage } from '../contexts/LanguageContext';

const NavigationMenu: React.FC = () => {
  const { t } = useLanguage();

  return (
    <Menu theme="dark" mode="inline" defaultSelectedKeys={['1']}>
      <Menu.Item key="1" icon={<DashboardOutlined />}>
        <Link to="/">{t.navigation.dashboard}</Link>
      </Menu.Item>
      <Menu.Item key="2" icon={<LineChartOutlined />}>
        <Link to="/market">{t.navigation.market}</Link>
      </Menu.Item>
      <Menu.Item key="3" icon={<BarChartOutlined />}>
        <Link to="/backtest">{t.navigation.backtest}</Link>
      </Menu.Item>
      <Menu.Item key="4" icon={<SwapOutlined />}>
        <Link to="/compare">{t.navigation.strategyComparison}</Link>
      </Menu.Item>
      <Menu.Item key="5" icon={<RocketOutlined />}>
        <Link to="/optimize">{t.navigation.parameterOptimization}</Link>
      </Menu.Item>
      <Menu.Item key="6" icon={<TrophyOutlined />}>
        <Link to="/ranking">{t.navigation.strategyRanking}</Link>
      </Menu.Item>
      <Menu.Item key="7" icon={<UnorderedListOutlined />}>
        <Link to="/watchlist">{t.navigation.watchlist}</Link>
      </Menu.Item>
      <Menu.Item key="8" icon={<UserOutlined />}>
        <Link to="/profile">{t.navigation.profile}</Link>
      </Menu.Item>
    </Menu>
  );
};

export default NavigationMenu;