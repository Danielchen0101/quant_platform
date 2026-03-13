import React from 'react';
import { Card, Alert, Space, Tag, Button } from 'antd';
import { useLanguage } from '../contexts/LanguageContext';

const LanguageTest: React.FC = () => {
  const { t, language, setLanguage } = useLanguage();

  return (
    <div style={{ padding: '24px' }}>
      <h1>语言切换测试页面</h1>
      <h1>Language Switch Test Page</h1>
      
      <Card title="当前语言状态 / Current Language Status" style={{ marginBottom: '24px' }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert
            message="语言信息 / Language Info"
            description={
              <div>
                <p><strong>当前语言 / Current Language:</strong> <Tag color="blue">{language}</Tag></p>
                <p><strong>显示文本 / Display Text:</strong> {language === 'zh-CN' ? '中文' : 'English'}</p>
              </div>
            }
            type="info"
            showIcon
          />
          
          <Alert
            message="导航菜单测试 / Navigation Menu Test"
            description={
              <div>
                <p><strong>仪表板 / Dashboard:</strong> {t.navigation.dashboard}</p>
                <p><strong>市场 / Market:</strong> {t.navigation.market}</p>
                <p><strong>回测 / Backtest:</strong> {t.navigation.backtest}</p>
                <p><strong>策略比较 / Strategy Comparison:</strong> {t.navigation.strategyComparison}</p>
                <p><strong>参数优化 / Parameter Optimization:</strong> {t.navigation.parameterOptimization}</p>
              </div>
            }
            type="success"
            showIcon
          />
          
          <Alert
            message="通用文本测试 / Common Text Test"
            description={
              <div>
                <p><strong>加载中 / Loading:</strong> {t.common.loading}</p>
                <p><strong>错误 / Error:</strong> {t.common.error}</p>
                <p><strong>成功 / Success:</strong> {t.common.success}</p>
                <p><strong>确认 / Confirm:</strong> {t.common.confirm}</p>
                <p><strong>取消 / Cancel:</strong> {t.common.cancel}</p>
              </div>
            }
            type="warning"
            showIcon
          />
          
          <div style={{ display: 'flex', gap: '12px', marginTop: '16px' }}>
            <Button 
              type="primary" 
              onClick={() => setLanguage('zh-CN')}
              disabled={language === 'zh-CN'}
            >
              切换到中文 / Switch to Chinese
            </Button>
            
            <Button 
              type="primary" 
              onClick={() => setLanguage('en-US')}
              disabled={language === 'en-US'}
            >
              Switch to English / 切换到英文
            </Button>
          </div>
          
          <Alert
            message="使用说明 / Instructions"
            description={
              <div>
                <p>1. 点击右上角的 🌐 按钮切换语言 / Click the 🌐 button in the top right corner to switch language</p>
                <p>2. 页面刷新后语言设置会保持 / Language settings persist after page refresh</p>
                <p>3. 股票代码和公司名称保持英文 / Stock symbols and company names remain in English</p>
                <p>4. 所有界面文本会根据选择的语言切换 / All interface text switches based on selected language</p>
              </div>
            }
            type="info"
            showIcon
          />
        </Space>
      </Card>
      
      <Card title="已国际化的页面 / Internationalized Pages">
        <Space direction="vertical" style={{ width: '100%' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            <Tag color="green">✅ 参数优化 / Parameter Optimization</Tag>
            <Tag color="green">✅ 策略比较 / Strategy Comparison</Tag>
            <Tag color="green">✅ 观察列表 / Watchlist</Tag>
            <Tag color="green">✅ 导航菜单 / Navigation Menu</Tag>
            <Tag color="blue">🔄 仪表板 / Dashboard</Tag>
            <Tag color="blue">🔄 市场 / Market</Tag>
            <Tag color="orange">⏳ 回测 / Backtest</Tag>
            <Tag color="orange">⏳ 策略排名 / Strategy Ranking</Tag>
          </div>
          
          <p>
            <strong>状态说明 / Status Legend:</strong><br/>
            ✅ 完全国际化 / Fully Internationalized<br/>
            🔄 部分国际化 / Partially Internationalized<br/>
            ⏳ 待国际化 / To be Internationalized
          </p>
        </Space>
      </Card>
    </div>
  );
};

export default LanguageTest;