import React from 'react';
import { Layout, Menu } from 'antd';
import {
  DashboardOutlined,
  LineChartOutlined,
  FundOutlined,
  SettingOutlined,
  LogoutOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { useAppDispatch } from '../store/hooks';
import { logout } from '../store/slices/authSlice';

const { Sider } = Layout;

const Sidebar: React.FC = () => {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();

  const menuItems = [
    {
      key: 'dashboard',
      icon: <DashboardOutlined />,
      label: '仪表板',
      onClick: () => navigate('/dashboard'),
    },
    {
      key: 'backtest',
      icon: <LineChartOutlined />,
      label: '策略回测',
      onClick: () => navigate('/backtest'),
    },
    {
      key: 'analysis',
      icon: <FundOutlined />,
      label: '市场分析',
      onClick: () => navigate('/analysis'),
    },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: '系统设置',
      onClick: () => navigate('/settings'),
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: () => dispatch(logout()),
    },
  ];

  return (
    <Sider
      breakpoint="lg"
      collapsedWidth="0"
      style={{
        overflow: 'auto',
        height: '100vh',
        position: 'fixed',
        left: 0,
        top: 0,
        bottom: 0,
      }}
    >
      <div style={{ padding: '24px 16px', textAlign: 'center' }}>
        <h2 style={{ color: '#fff', margin: 0 }}>📊 量化平台</h2>
      </div>
      <Menu
        theme="dark"
        mode="inline"
        defaultSelectedKeys={['dashboard']}
        items={menuItems}
      />
    </Sider>
  );
};

export default Sidebar;