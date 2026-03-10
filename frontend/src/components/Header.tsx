import React from 'react';
import { Layout, Avatar, Dropdown, Space, Typography, Badge } from 'antd';
import {
  BellOutlined,
  UserOutlined,
  DownOutlined,
} from '@ant-design/icons';
import { useAppSelector } from '../store/hooks';

const { Header } = Layout;
const { Text } = Typography;

const AppHeader: React.FC = () => {
  const user = useAppSelector(state => state.auth.user);

  const userMenuItems = [
    {
      key: 'profile',
      label: '个人资料',
    },
    {
      key: 'settings',
      label: '账户设置',
    },
    {
      key: 'divider',
      type: 'divider' as const,
    },
    {
      key: 'logout',
      label: '退出登录',
    },
  ];

  return (
    <Header
      style={{
        padding: '0 24px',
        background: '#fff',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        boxShadow: '0 1px 4px rgba(0,21,41,.08)',
      }}
    >
      <div>
        <Text strong style={{ fontSize: '18px' }}>
          量化交易平台
        </Text>
      </div>

      <Space size="large">
        <Badge count={5}>
          <BellOutlined style={{ fontSize: '18px', cursor: 'pointer' }} />
        </Badge>

        <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
          <Space style={{ cursor: 'pointer' }}>
            <Avatar icon={<UserOutlined />} />
            <Text>{user?.name || '用户'}</Text>
            <DownOutlined />
          </Space>
        </Dropdown>
      </Space>
    </Header>
  );
};

export default AppHeader;