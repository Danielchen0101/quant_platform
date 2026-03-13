import React, { useState, useEffect } from 'react';
import { Card, Form, Input, InputNumber, Button, Select, Alert, Row, Col } from 'antd';
import { RocketOutlined } from '@ant-design/icons';
import { backtraderAPI } from '../services/api';
import { useLanguage } from '../contexts/LanguageContext';
import OptimizationHeatmap, { OptimizationResult } from '../components/optimization/OptimizationHeatmap';
import OptimizationSummary from '../components/optimization/OptimizationSummary';
import OptimizationResultsTable from '../components/optimization/OptimizationResultsTable';

// Helper functions
const safeNumber = (value: any): number => {
  if (value === null || value === undefined || value === '') return 0;
  const num = Number(value);
  return isNaN(num) ? 0 : num;
};

const formatPercent = (value: number): string => {
  const safeValue = safeNumber(value);
  const sign = safeValue >= 0 ? '+' : '';
  return `${sign}${safeValue.toFixed(2)}%`;
};

const ParameterOptimization: React.FC = () => {
  const { t } = useLanguage();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [optimizationResults, setOptimizationResults] = useState<OptimizationResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState({
    totalCombinations: 0,
    validCombinations: 0,
    bestReturn: 0,
    worstReturn: 0,
    avgReturn: 0
  });

  // Default form values
  useEffect(() => {
    form.setFieldsValue({
      symbol: 'AAPL',
      strategy: 'moving_average',
      fast_mas: [5, 10, 20],
      slow_mas: [50, 100, 200],
      period: '1y',
      initial_capital: 100000
    });
  }, [form]);

  const handleRunOptimization = async (values: any) => {
    setLoading(true);
    setError(null);
    
    // Convert form values to new API payload format
    // Old format: fast_mas: [5, 10, 20], slow_mas: [50, 100, 200]
    // New format: parameters.short_ma: {min, max, step}, parameters.long_ma: {min, max, step}
    
    // Extract values from arrays
    const fast_mas_int = Array.isArray(values.fast_mas) 
      ? values.fast_mas.map((v: any) => parseInt(v, 10)).filter((v: number) => !isNaN(v))
      : [5, 10, 20];
    
    const slow_mas_int = Array.isArray(values.slow_mas)
      ? values.slow_mas.map((v: any) => parseInt(v, 10)).filter((v: number) => !isNaN(v))
      : [50, 100, 200];
    
    // Calculate min, max, step from arrays
    const shortMin = Math.min(...fast_mas_int);
    const shortMax = Math.max(...fast_mas_int);
    const shortStep = fast_mas_int.length > 1 
      ? Math.min(...fast_mas_int.slice(1).map((v: number, i: number) => v - fast_mas_int[i]))
      : 5;
    
    const longMin = Math.min(...slow_mas_int);
    const longMax = Math.max(...slow_mas_int);
    const longStep = slow_mas_int.length > 1
      ? Math.min(...slow_mas_int.slice(1).map((v: number, i: number) => v - slow_mas_int[i]))
      : 50;
    
    // Convert period to startDate/endDate
    let startDate, endDate;
    const today = new Date();
    endDate = today.toISOString().split('T')[0]; // YYYY-MM-DD
    
    switch (values.period) {
      case '3m':
        startDate = new Date(today.getFullYear(), today.getMonth() - 3, today.getDate())
          .toISOString().split('T')[0];
        break;
      case '6m':
        startDate = new Date(today.getFullYear(), today.getMonth() - 6, today.getDate())
          .toISOString().split('T')[0];
        break;
      case '1y':
        startDate = new Date(today.getFullYear() - 1, today.getMonth(), today.getDate())
          .toISOString().split('T')[0];
        break;
      default:
        startDate = new Date(today.getFullYear() - 1, today.getMonth(), today.getDate())
          .toISOString().split('T')[0];
    }
    
    const payload = {
      symbol: values.symbol,
      strategy: values.strategy,
      parameters: {
        short_ma: {
          min: shortMin,
          max: shortMax,
          step: shortStep
        },
        long_ma: {
          min: longMin,
          max: longMax,
          step: longStep
        }
      },
      start_date: startDate,
      end_date: endDate,
      initial_capital: values.initial_capital
    };
    
    console.log('=== ParameterOptimization.tsx: Sending optimization request ===');
    console.log('Payload:', JSON.stringify(payload, null, 2));
    
    try {
      const response = await backtraderAPI.runParameterOptimization(payload);
      console.log('=== ParameterOptimization.tsx: Optimization response ===');
      console.log('Response status:', response.status);
      console.log('Response data:', response.data);
      
      if (response.data && response.data.success) {
        // Transform API response to match our component interface
        const transformedResults = response.data.results.map((item: any, index: number) => ({
          rank: index + 1,
          short_ma: item.short_ma,
          long_ma: item.long_ma,
          totalReturn: item.total_return,
          annualizedReturn: item.annualized_return,
          sharpeRatio: item.sharpe_ratio,
          maxDrawdown: item.max_drawdown,
          trades: item.trades,
          winRate: item.win_rate,
          profitLoss: item.profit_loss,
          volatility: item.volatility,
          sortinoRatio: item.sortino_ratio,
          profitFactor: item.profit_factor,
          expectancy: item.expectancy,
          exposure: item.exposure
        }));
        
        setOptimizationResults(transformedResults);
        
        // Calculate statistics
        const totalCombinations = response.data.total_combinations || transformedResults.length;
        const validCombinations = response.data.valid_combinations || transformedResults.length;
        const bestReturn = transformedResults.length > 0 ? Math.max(...transformedResults.map((r: OptimizationResult) => r.totalReturn)) : 0;
        const worstReturn = transformedResults.length > 0 ? Math.min(...transformedResults.map((r: OptimizationResult) => r.totalReturn)) : 0;
        const avgReturn = transformedResults.length > 0 ? transformedResults.reduce((sum: number, r: OptimizationResult) => sum + r.totalReturn, 0) / transformedResults.length : 0;
        
        setStats({
          totalCombinations,
          validCombinations,
          bestReturn,
          worstReturn,
          avgReturn
        });
      } else {
        setError(response.data?.error || 'Optimization failed');
      }
    } catch (err: any) {
      console.error('Optimization error:', err);
      setError(err.response?.data?.error || err.message || 'Failed to run optimization');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ marginBottom: '8px' }}>
          <RocketOutlined style={{ marginRight: '12px', color: '#1890ff' }} />
          {t.optimization.title}
        </h1>
        <div style={{ color: '#666', fontSize: '14px' }}>
          {t.optimization.subtitle}
        </div>
      </div>

      {/* Optimization Form */}
      <Card style={{ marginBottom: '24px' }}>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleRunOptimization}
          initialValues={{
            symbol: 'AAPL',
            strategy: 'moving_average',
            fast_mas: [5, 10, 20],
            slow_mas: [50, 100, 200],
            period: '1y',
            initial_capital: 100000
          }}
        >
          <Row gutter={[16, 16]}>
            <Col span={6}>
              <Form.Item
                label={t.optimization.symbol || "Symbol"}
                name="symbol"
                rules={[{ required: true, message: 'Please select a symbol' }]}
              >
                <Input placeholder="e.g., AAPL" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                label={t.optimization.strategy || "Strategy"}
                name="strategy"
              >
                <Select disabled>
                  <Select.Option value="moving_average">Moving Average</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                label={t.optimization.period || "Period"}
                name="period"
              >
                <Select>
                  <Select.Option value="3m">3 Months</Select.Option>
                  <Select.Option value="6m">6 Months</Select.Option>
                  <Select.Option value="1y">1 Year</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item
                label={t.optimization.initialCapital || "Initial Capital"}
                name="initial_capital"
              >
                <InputNumber
                  style={{ width: '100%' }}
                  min={1000}
                  max={1000000}
                  step={10000}
                  formatter={value => `$ ${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col span={12}>
              <Form.Item
                label={t.optimization.fastMAValues || "Fast MA Values"}
                name="fast_mas"
                rules={[{ required: true, message: 'Please select at least one Fast MA value' }]}
                tooltip="Fast moving average periods to test (e.g., 5, 10, 20)"
              >
                <Select mode="tags" placeholder="Enter Fast MA values">
                  <Select.Option value="5">5</Select.Option>
                  <Select.Option value="10">10</Select.Option>
                  <Select.Option value="20">20</Select.Option>
                  <Select.Option value="30">30</Select.Option>
                  <Select.Option value="40">40</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label={t.optimization.slowMAValues || "Slow MA Values"}
                name="slow_mas"
                rules={[{ required: true, message: 'Please select at least one Slow MA value' }]}
                tooltip="Slow moving average periods to test (e.g., 50, 100, 200)"
              >
                <Select mode="tags" placeholder="Enter Slow MA values">
                  <Select.Option value="50">50</Select.Option>
                  <Select.Option value="100">100</Select.Option>
                  <Select.Option value="150">150</Select.Option>
                  <Select.Option value="200">200</Select.Option>
                  <Select.Option value="250">250</Select.Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>

          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              icon={<RocketOutlined />}
              size="large"
            >
              {t.optimization.runOptimization}
            </Button>
            <span style={{ marginLeft: '12px', fontSize: '12px', color: '#666' }}>
              Will test {Form.useWatch('fast_mas', form)?.length || 0} × {Form.useWatch('slow_mas', form)?.length || 0} = {(Form.useWatch('fast_mas', form)?.length || 0) * (Form.useWatch('slow_mas', form)?.length || 0)} combinations
            </span>
          </Form.Item>
        </Form>
      </Card>

      {/* Error Display */}
      {error && (
        <Alert
          message="Optimization Error"
          description={error}
          type="error"
          showIcon
          style={{ marginBottom: '24px' }}
        />
      )}

      {/* Statistics and Heatmap */}
      {optimizationResults.length > 0 && (
        <>
          {/* Best Combination Summary */}
          <OptimizationSummary 
            results={optimizationResults}
            totalCombinations={stats.totalCombinations}
            validCombinations={stats.validCombinations}
          />

          {/* Optimization Heatmap */}
          <Card style={{ marginBottom: '24px' }}>
            <h3 style={{ marginBottom: '16px' }}>Optimization Heatmap</h3>
            <div style={{ 
              background: 'white',
              borderRadius: '8px',
              padding: '20px',
              border: '1px solid #e8e8e8',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center'
            }}>
              <div style={{ marginBottom: '16px', fontSize: '12px', color: '#666', textAlign: 'center' }}>
                X-axis: Short MA (fast), Y-axis: Long MA (slow). Color represents Sharpe Ratio.
              </div>
              <OptimizationHeatmap results={optimizationResults} />
            </div>
          </Card>

          {/* Optimization Results Table */}
          <Card title="Optimization Results">
            <OptimizationResultsTable results={optimizationResults} />
          </Card>
        </>
      )}
    </div>
  );
};

export default ParameterOptimization;