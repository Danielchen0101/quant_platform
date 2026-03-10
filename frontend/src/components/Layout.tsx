import React, { useState } from 'react';
import { Layout, Menu, Button, Avatar, Dropdown, Space } from 'antd';
import {
  DashboardOutlined,
  LineChartOutlined,
  StockOutlined,
  UserOutlined,
  SettingOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';

const { Header, Sider, Content } = Layout;

interface LayoutProps {
  children: React.ReactNode;
}

const AppLayout: React.FC<LayoutProps> = ({ children }) => {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const menuItems = [
    {
      key: '/dashboard',
      icon: <DashboardOutlined />,
      label: 'Dashboard',
    },
    {
      key: '/market',
      icon: <StockOutlined />,
      label: 'Market',
    },
    {
      key: '/analytics',
      icon: <LineChartOutlined />,
      label: 'Analytics',
    },
    {
      key: '/profile',
      icon: <UserOutlined />,
      label: 'Profile',
    },
  ];

  const userMenuItems = [
    {
      key: 'profile',
      icon: <UserOutlined />,
      label: 'Profile',
    },
    {
      key: 'settings',
      icon: <SettingOutlined />,
      label: 'Settings',
    },
    {
      type: 'divider' as const,
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: 'Logout',
    },
  ];

  const handleMenuClick = ({ key }: { key: string }) => {
    if (key === 'logout') {
      localStorage.removeItem('token');
      navigate('/login');
    } else if (key === 'profile') {
      navigate('/profile');
    } else if (key === 'settings') {
      navigate('/settings');
    }
  };

  const userDropdown = (
    <Dropdown menu={{ items: userMenuItems, onClick: handleMenuClick }} placement="bottomRight">
      <Space style={{ cursor: 'pointer', padding: '0 12px' }}>
        <Avatar icon={<UserOutlined />} />
        <span style={{ color: '#fff' }}>User</span>
      </Space>
    </Dropdown>
  );

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={240}
        style={{
          overflow: 'auto',
          height: '100vh',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          backgroundColor: '#0d1117', // GitHub dark sidebar color
        }}
      >
        <div style={{ padding: '16px', textAlign: 'center' }}>
          <h1 style={{ color: '#fff', margin: 0, fontSize: collapsed ? '16px' : '20px' }}>
            {collapsed ? 'QP' : 'Quant Platform'}
          </h1>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ backgroundColor: '#0d1117', borderRight: 0 }}
        />
      </Sider>
      <Layout style={{ marginLeft: collapsed ? 80 : 240, transition: 'all 0.2s' }}>
        <Header
          style={{
            padding: '0 24px',
            background: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            position: 'sticky',
            top: 0,
            zIndex: 100,
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
            style={{ fontSize: '16px' }}
          />
          <div style={{ display: 'flex', alignItems: 'center' }}>
            {userDropdown}
          </div>
        </Header>
        <Content
          style={{
            margin: '24px 16px',
            padding: 24,
            minHeight: 280,
            background: '#fff',
            borderRadius: 8,
            overflow: 'auto',
          }}
        >
          {children}
        </Content>
      </Layout>
    </Layout>
  );
};

export default AppLayout;