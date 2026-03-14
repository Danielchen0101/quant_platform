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
  RocketOutlined,
  AreaChartOutlined 
} from '@ant-design/icons';
import { useLanguage } from '../contexts/LanguageContext';
import styles from './NavigationMenu.module.css';

const NavigationMenu: React.FC = () => {
  const { t } = useLanguage();

  // 创建菜单项组件的函数，确保所有菜单项使用完全相同的结构
  const createMenuItem = (key: string, icon: React.ReactNode, text: string, to: string) => (
    <Menu.Item 
      key={key} 
      icon={icon}
    >
      <Link to={to}>{text}</Link>
    </Menu.Item>
  );

  return (
    <div className={styles.navigationMenu}>
      <Menu 
        theme="dark" 
        mode="inline" 
        defaultSelectedKeys={['1']}
        style={{
          backgroundColor: '#001529',
          borderRight: 'none',
        }}
      >
        {createMenuItem('1', <DashboardOutlined />, t.navigation.dashboard, '/')}
        {createMenuItem('2', <LineChartOutlined />, t.navigation.market, '/market')}
        {createMenuItem('3', <UnorderedListOutlined />, t.navigation.watchlist, '/watchlist')}
        {createMenuItem('4', <BarChartOutlined />, t.navigation.backtest, '/backtest')}
        {createMenuItem('5', <RocketOutlined />, t.navigation.parameterOptimization, '/optimize')}
        {createMenuItem('6', <SwapOutlined />, t.navigation.strategyComparison, '/compare')}
        {createMenuItem('7', <TrophyOutlined />, t.navigation.strategyRanking, '/ranking')}
        {createMenuItem('8', <AreaChartOutlined />, t.navigation.analytics, '/analytics')}
        {createMenuItem('9', <UserOutlined />, t.navigation.profile, '/profile')}
      </Menu>
    </div>
  );
};

export default NavigationMenu;