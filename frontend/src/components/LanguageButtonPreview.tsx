import React from 'react';
import { Card, Row, Col, Space, Typography } from 'antd';
import LanguageSwitcher from './LanguageSwitcher';

const { Title, Text } = Typography;

const LanguageButtonPreview: React.FC = () => {
  return (
    <div style={{ padding: '24px', background: '#f0f2f5', minHeight: '100vh' }}>
      <Title level={2}>语言切换按钮预览</Title>
      <Text type="secondary">Language Switch Button Preview</Text>
      
      <Row gutter={[24, 24]} style={{ marginTop: '24px' }}>
        <Col span={12}>
          <Card title="白色背景测试 (White Background Test)" style={{ height: '100%' }}>
            <div style={{ 
              padding: '24px', 
              background: '#fff', 
              borderRadius: '8px',
              display: 'flex',
              justifyContent: 'flex-end',
              alignItems: 'center',
              height: '200px',
              border: '1px solid #e8e8e8'
            }}>
              <LanguageSwitcher />
            </div>
            <div style={{ marginTop: '16px' }}>
              <Text>在白色背景上，按钮显示为：</Text>
              <ul>
                <li>黑色文字和边框</li>
                <li>白色背景</li>
                <li>悬停时变为蓝色</li>
                <li>带轻微阴影效果</li>
              </ul>
            </div>
          </Card>
        </Col>
        
        <Col span={12}>
          <Card title="按钮特性 (Button Features)" style={{ height: '100%' }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <div style={{ padding: '16px', background: '#fafafa', borderRadius: '6px' }}>
                <Text strong>外观设计 (Appearance):</Text>
                <ul>
                  <li>🌐 地球图标 + 语言标识 (EN/中文)</li>
                  <li>黑色文字，白色背景，灰色边框</li>
                  <li>字体加粗，清晰易读</li>
                  <li>适当的间距和阴影</li>
                </ul>
              </div>
              
              <div style={{ padding: '16px', background: '#fafafa', borderRadius: '6px' }}>
                <Text strong>交互效果 (Interaction):</Text>
                <ul>
                  <li>悬停时：边框和文字变为蓝色</li>
                  <li>悬停时：添加蓝色阴影</li>
                  <li>平滑的过渡动画 (0.3s)</li>
                  <li>点击弹出语言选择菜单</li>
                </ul>
              </div>
              
              <div style={{ padding: '16px', background: '#fafafa', borderRadius: '6px' }}>
                <Text strong>下拉菜单 (Dropdown Menu):</Text>
                <ul>
                  <li>🇺🇸 ENGLISH - 英文选项</li>
                  <li>🇨🇳 中文 - 中文选项</li>
                  <li>当前选中语言显示 ✓ 标记</li>
                  <li>悬停时背景变浅灰色</li>
                  <li>清晰的视觉层次</li>
                </ul>
              </div>
            </Space>
          </Card>
        </Col>
        
        <Col span={24}>
          <Card title="使用说明 (Instructions)">
            <Row gutter={[16, 16]}>
              <Col span={8}>
                <div style={{ textAlign: 'center', padding: '16px' }}>
                  <div style={{ 
                    width: '60px', 
                    height: '60px', 
                    background: '#fff', 
                    border: '1px solid #d9d9d9',
                    borderRadius: '6px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    margin: '0 auto 12px',
                    fontSize: '24px'
                  }}>
                    🌐
                  </div>
                  <Text strong>步骤 1: 找到按钮</Text>
                  <p style={{ marginTop: '8px', color: '#666' }}>
                    在页面右上角寻找 🌐 图标 + 语言标识
                  </p>
                </div>
              </Col>
              
              <Col span={8}>
                <div style={{ textAlign: 'center', padding: '16px' }}>
                  <div style={{ 
                    width: '60px', 
                    height: '60px', 
                    background: '#1890ff', 
                    borderRadius: '6px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    margin: '0 auto 12px',
                    fontSize: '24px',
                    color: '#fff'
                  }}>
                    👆
                  </div>
                  <Text strong>步骤 2: 点击按钮</Text>
                  <p style={{ marginTop: '8px', color: '#666' }}>
                    点击按钮弹出语言选择菜单
                  </p>
                </div>
              </Col>
              
              <Col span={8}>
                <div style={{ textAlign: 'center', padding: '16px' }}>
                  <div style={{ 
                    width: '60px', 
                    height: '60px', 
                    background: '#52c41a', 
                    borderRadius: '6px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    margin: '0 auto 12px',
                    fontSize: '24px',
                    color: '#fff'
                  }}>
                    ✓
                  </div>
                  <Text strong>步骤 3: 选择语言</Text>
                  <p style={{ marginTop: '8px', color: '#666' }}>
                    选择 🇺🇸 ENGLISH 或 🇨🇳 中文
                  </p>
                </div>
              </Col>
            </Row>
            
            <div style={{ marginTop: '24px', padding: '16px', background: '#e6f7ff', borderRadius: '6px' }}>
              <Text strong>💡 提示 (Tips):</Text>
              <ul style={{ marginTop: '8px' }}>
                <li>按钮在白色背景上显示为黑色，非常醒目</li>
                <li>语言选择会立即生效，无需刷新页面</li>
                <li>你的选择会被浏览器记住</li>
                <li>股票代码和公司名称保持英文不变</li>
              </ul>
            </div>
          </Card>
        </Col>
      </Row>
      
      <div style={{ marginTop: '24px', textAlign: 'center', color: '#999' }}>
        <Text>现在按钮应该非常明显了！如果还是看不到，请检查CSS样式或浏览器控制台。</Text>
      </div>
    </div>
  );
};

export default LanguageButtonPreview;