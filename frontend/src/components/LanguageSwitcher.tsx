import React from 'react';
import { GlobalOutlined } from '@ant-design/icons';
import { Dropdown, MenuProps, Button } from 'antd';
import { useLanguage, Language } from '../contexts/LanguageContext';

const LanguageSwitcher: React.FC = () => {
  const { language, setLanguage, t } = useLanguage();

  const languageOptions: { key: Language; label: string; icon: string }[] = [
    { key: 'en-US', label: t.language.english, icon: '🇺🇸' },
    { key: 'zh-CN', label: t.language.chinese, icon: '🇨🇳' },
  ];

  const items: MenuProps['items'] = languageOptions.map((option) => ({
    key: option.key,
    label: (
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        gap: '10px',
        padding: '8px 12px',
        borderRadius: '4px',
        transition: 'background 0.3s ease',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = '#f5f5f5';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent';
      }}
      >
        <span style={{ fontSize: '18px' }}>{option.icon}</span>
        <span style={{ fontSize: '14px', fontWeight: '500' }}>{option.label}</span>
        {language === option.key && (
          <span style={{ marginLeft: 'auto', color: '#1890ff', fontWeight: 'bold' }}>✓</span>
        )}
      </div>
    ),
    style: {
      padding: '4px',
    },
  }));

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    setLanguage(key as Language);
  };

  const currentLanguage = languageOptions.find(opt => opt.key === language);

  return (
    <Dropdown
      menu={{ items, onClick: handleMenuClick }}
      placement="bottomRight"
      trigger={['click']}
    >
      <Button
        type="default"
        icon={<GlobalOutlined />}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          color: '#000',
          fontWeight: '500',
          border: '1px solid #d9d9d9',
          background: '#fff',
          boxShadow: '0 2px 0 rgba(0, 0, 0, 0.02)',
          transition: 'all 0.3s ease',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.borderColor = '#1890ff';
          e.currentTarget.style.color = '#1890ff';
          e.currentTarget.style.boxShadow = '0 2px 8px rgba(24, 144, 255, 0.2)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.borderColor = '#d9d9d9';
          e.currentTarget.style.color = '#000';
          e.currentTarget.style.boxShadow = '0 2px 0 rgba(0, 0, 0, 0.02)';
        }}
      >
        {currentLanguage?.icon}
        <span style={{ fontSize: '13px', fontWeight: '500' }}>
          {language === 'en-US' ? 'ENGLISH' : '中文'}
        </span>
      </Button>
    </Dropdown>
  );
};

export default LanguageSwitcher;