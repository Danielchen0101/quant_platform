import React, { useState, useEffect } from 'react';
import { Card, Form, Input, InputNumber, Button, Select, Alert, Row, Col } from 'antd';
import { RocketOutlined, DownloadOutlined, PlayCircleOutlined } from '@ant-design/icons';
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
  const [success, setSuccess] = useState<string | null>(null);
  const [stats, setStats] = useState({
    totalCombinations: 0,
    validCombinations: 0,
    bestReturn: 0,
    worstReturn: 0,
    avgReturn: 0
  });
  
  // Maximum allowed combinations (increased from 50 to 1500)
  const MAX_COMBINATIONS = 1500;
  
  // Watch form values for real-time validation
  const shortStart = Form.useWatch('shortMaStart', form) || 5;
  const shortEnd = Form.useWatch('shortMaEnd', form) || 50;
  const shortStep = Form.useWatch('shortMaStep', form) || 5;
  const longStart = Form.useWatch('longMaStart', form) || 50;
  const longEnd = Form.useWatch('longMaEnd', form) || 200;
  const longStep = Form.useWatch('longMaStep', form) || 25;
  
  // Calculate combinations based on watched values
  const shortCount = shortStep > 0 ? Math.floor((shortEnd - shortStart) / shortStep) + 1 : 0;
  const longCount = longStep > 0 ? Math.floor((longEnd - longStart) / longStep) + 1 : 0;
  const totalCombinations = shortCount * longCount;
  const exceedsLimit = totalCombinations > MAX_COMBINATIONS;
  
  // Export CSV function
  const exportToCSV = () => {
    if (optimizationResults.length === 0) {
      setError('No optimization results to export');
      return;
    }
    
    // Define CSV headers
    const headers = [
      'Short MA',
      'Long MA',
      'Total Return (%)',
      'Annualized Return (%)',
      'Sharpe Ratio',
      'Max Drawdown (%)',
      'Trades',
      'Win Rate (%)'
    ];
    
    // Convert results to CSV rows
    const rows = optimizationResults.map(result => {
      return [
        result.short_ma,
        result.long_ma,
        result.totalReturn !== undefined && result.totalReturn !== null && !isNaN(result.totalReturn) ? result.totalReturn.toFixed(2) : '',
        result.annualizedReturn !== undefined && result.annualizedReturn !== null && !isNaN(result.annualizedReturn) ? result.annualizedReturn.toFixed(2) : '',
        result.sharpeRatio !== undefined && result.sharpeRatio !== null && !isNaN(result.sharpeRatio) ? result.sharpeRatio.toFixed(2) : '',
        result.maxDrawdown !== undefined && result.maxDrawdown !== null && !isNaN(result.maxDrawdown) ? result.maxDrawdown.toFixed(2) : '',
        result.trades !== undefined && result.trades !== null && !isNaN(result.trades) ? result.trades : '',
        result.winRate !== undefined && result.winRate !== null && !isNaN(result.winRate) ? result.winRate.toFixed(1) : ''
      ];
    });
    
    // Combine headers and rows
    const csvContent = [
      headers.join(','),
      ...rows.map(row => row.join(','))
    ].join('\n');
    
    // Create download link
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `optimization_results_${new Date().toISOString().split('T')[0]}.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    // Show success message
    setError(null);
    console.log(`Exported ${optimizationResults.length} optimization results to CSV`);
  };
  
  // Function to get best combination by Sharpe Ratio
  const getBestCombinationBySharpe = (): OptimizationResult | null => {
    if (optimizationResults.length === 0) {
      return null;
    }
    
    return optimizationResults.reduce((best, current) => 
      (current.sharpeRatio > best.sharpeRatio) ? current : best
    );
  };
  
  // Function to run backtest with best parameters
  const runBacktestWithBestParams = async () => {
    const bestCombination = getBestCombinationBySharpe();
    if (!bestCombination) {
      setError('No optimization results available. Please run optimization first.');
      setSuccess(null);
      return;
    }
    
    // Get current form values
    const formValues = form.getFieldsValue();
    if (!formValues.symbol) {
      setError('Symbol is required. Please enter a symbol.');
      setSuccess(null);
      return;
    }
    
    setLoading(true);
    setError(null);
    setSuccess(null);
    
    try {
      // Convert period to startDate/endDate (reuse the same logic from handleRunOptimization)
      let startDate, endDate;
      const today = new Date();
      endDate = today.toISOString().split('T')[0]; // YYYY-MM-DD
      
      switch (formValues.period) {
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
      
      // Prepare backtest config with best parameters
      const config = {
        symbol: formValues.symbol.toUpperCase(),
        strategy: 'moving_average',
        startDate: startDate,
        endDate: endDate,
        initialCapital: formValues.initial_capital || 100000,
        parameters: {
          shortMaPeriod: bestCombination.short_ma,
          longMaPeriod: bestCombination.long_ma
        }
      };
      
      console.log('Running backtest with best parameters:', config);
      
      const response = await backtraderAPI.runBacktest(config);
      
      if (response.data && response.data.success) {
        // Show success message with backtest ID
        const backtestId = response.data.backtestId;
        setSuccess(`Backtest started successfully! Backtest ID: ${backtestId}. You can view the results on the Backtest page.`);
        setError(null); // Clear any previous error
        
        // Log the best parameters used
        console.log(`Backtest started with best parameters: Short MA=${bestCombination.short_ma}, Long MA=${bestCombination.long_ma}`);
        console.log(`Backtest ID: ${backtestId}`);
      } else {
        setError(response.data?.error || 'Failed to run backtest with best parameters');
        setSuccess(null); // Clear success on error
      }
    } catch (err: any) {
      console.error('Backtest error:', err);
      setError(err.response?.data?.error || err.message || 'Failed to run backtest');
      setSuccess(null); // Clear success on error
    } finally {
      setLoading(false);
    }
  };

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
    setSuccess(null);
    
    // Use new form field names directly
    const shortMin = values.shortMaStart || 5;
    const shortMax = values.shortMaEnd || 50;
    const shortStep = values.shortMaStep || 5;
    
    const longMin = values.longMaStart || 50;
    const longMax = values.longMaEnd || 200;
    const longStep = values.longMaStep || 25;
    
    // Frontend validation: check if combinations exceed limit
    const shortCount = shortStep > 0 ? Math.floor((shortMax - shortMin) / shortStep) + 1 : 0;
    const longCount = longStep > 0 ? Math.floor((longMax - longMin) / longStep) + 1 : 0;
    const totalCombinations = shortCount * longCount;
    
    if (totalCombinations > MAX_COMBINATIONS) {
      setError(`Too many combinations: ${totalCombinations}. Maximum allowed is ${MAX_COMBINATIONS}. Please reduce parameter ranges.`);
      setLoading(false);
      return;
    }
    
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
        console.log('=== ParameterOptimization.tsx: Raw optimization results ===');
        console.log('Response data:', JSON.stringify(response.data, null, 2));
        
        if (response.data.results && response.data.results.length > 0) {
          console.log('=== First optimization result item ===');
          console.log('Item keys:', Object.keys(response.data.results[0]));
          console.log('Item values:', response.data.results[0]);
        }
        
        // Transform API response to match our component interface
        const transformedResults = response.data.results.map((item: any, index: number) => {
          // Debug: log the actual item structure
          console.log(`=== Optimization result item ${index} ===`);
          console.log('Item:', item);
          
          // Try multiple possible field names for each metric
          // This handles variations in backend field naming
          return {
            rank: index + 1,
            short_ma: item.short_ma || item.shortMa || item.short_period || item.fast_ma || 0,
            long_ma: item.long_ma || item.longMa || item.long_period || item.slow_ma || 0,
            
            // Total Return - try multiple field names
            totalReturn: item.total_return !== undefined ? item.total_return : 
                        item.totalReturn !== undefined ? item.totalReturn :
                        item.return !== undefined ? item.return :
                        item.pnl !== undefined ? item.pnl :
                        item.profit !== undefined ? item.profit : 0,
            
            // Annualized Return - try multiple field names
            annualizedReturn: item.annualized_return !== undefined ? item.annualized_return :
                            item.annualizedReturn !== undefined ? item.annualizedReturn :
                            item.annual_return !== undefined ? item.annual_return :
                            item.annualized !== undefined ? item.annualized : 0,
            
            // Sharpe Ratio - try multiple field names
            sharpeRatio: item.sharpe_ratio !== undefined ? item.sharpe_ratio :
                        item.sharpeRatio !== undefined ? item.sharpeRatio :
                        item.sharpe !== undefined ? item.sharpe : 0,
            
            // Max Drawdown - try multiple field names
            maxDrawdown: item.max_drawdown !== undefined ? item.max_drawdown :
                        item.maxDrawdown !== undefined ? item.maxDrawdown :
                        item.drawdown !== undefined ? item.drawdown :
                        item.max_dd !== undefined ? item.max_dd : 0,
            
            // Trades
            trades: item.trades !== undefined ? item.trades :
                   item.total_trades !== undefined ? item.total_trades :
                   item.num_trades !== undefined ? item.num_trades : 0,
            
            // Win Rate - try multiple field names
            winRate: item.win_rate !== undefined ? item.win_rate :
                    item.winRate !== undefined ? item.winRate :
                    item.win_ratio !== undefined ? item.win_ratio : 0,
            
            // Other optional fields with fallbacks
            profitLoss: item.profit_loss || item.profitLoss || item.pnl || 0,
            volatility: item.volatility || 0,
            sortinoRatio: item.sortino_ratio || item.sortinoRatio || item.sortino || 0,
            profitFactor: item.profit_factor || item.profitFactor || 0,
            expectancy: item.expectancy || 0,
            exposure: item.exposure || 0
          };
        });
        
        console.log('=== Transformed results ===');
        console.log('First transformed item:', transformedResults[0]);
        
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
            period: '1y',
            initial_capital: 100000,
            // New parameter fields
            shortMaStart: 5,
            shortMaEnd: 50,
            shortMaStep: 5,
            longMaStart: 50,
            longMaEnd: 200,
            longMaStep: 25
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

          {/* Short MA Parameters */}
          <div style={{ marginBottom: '24px', padding: '16px', background: '#fafafa', borderRadius: '8px' }}>
            <h4 style={{ marginBottom: '12px' }}>Short MA Parameters</h4>
            <Row gutter={[16, 16]}>
              <Col span={8}>
                <Form.Item
                  label="Start"
                  name="shortMaStart"
                  initialValue={5}
                  rules={[
                    { required: true, message: 'Please enter start value' },
                    { type: 'number', min: 1, message: 'Must be greater than 0' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        const endValue = getFieldValue('shortMaEnd');
                        if (!endValue || !value || value <= endValue) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error('Start must be less than or equal to end'));
                      },
                    }),
                  ]}
                  help="Starting value for Short MA"
                >
                  <InputNumber
                    min={1}
                    max={200}
                    size="large"
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  label="End"
                  name="shortMaEnd"
                  initialValue={50}
                  rules={[
                    { required: true, message: 'Please enter end value' },
                    { type: 'number', min: 1, message: 'Must be greater than 0' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        const startValue = getFieldValue('shortMaStart');
                        if (!startValue || !value || value >= startValue) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error('End must be greater than or equal to start'));
                      },
                    }),
                  ]}
                  help="Ending value for Short MA"
                >
                  <InputNumber
                    min={1}
                    max={200}
                    size="large"
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  label="Step"
                  name="shortMaStep"
                  initialValue={5}
                  rules={[
                    { required: true, message: 'Please enter step value' },
                    { type: 'number', min: 1, message: 'Must be greater than 0' },
                  ]}
                  help="Step size for Short MA"
                >
                  <InputNumber
                    min={1}
                    max={50}
                    size="large"
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
            </Row>
          </div>
          
          {/* Long MA Parameters */}
          <div style={{ marginBottom: '24px', padding: '16px', background: '#fafafa', borderRadius: '8px' }}>
            <h4 style={{ marginBottom: '12px' }}>Long MA Parameters</h4>
            <Row gutter={[16, 16]}>
              <Col span={8}>
                <Form.Item
                  label="Start"
                  name="longMaStart"
                  initialValue={50}
                  rules={[
                    { required: true, message: 'Please enter start value' },
                    { type: 'number', min: 1, message: 'Must be greater than 0' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        const endValue = getFieldValue('longMaEnd');
                        if (!endValue || !value || value <= endValue) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error('Start must be less than or equal to end'));
                      },
                    }),
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        const shortMaStart = getFieldValue('shortMaStart');
                        if (!shortMaStart || !value || value > shortMaStart) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error('Long MA should generally be larger than Short MA'));
                      },
                    }),
                  ]}
                  help="Starting value for Long MA"
                >
                  <InputNumber
                    min={1}
                    max={300}
                    size="large"
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  label="End"
                  name="longMaEnd"
                  initialValue={200}
                  rules={[
                    { required: true, message: 'Please enter end value' },
                    { type: 'number', min: 1, message: 'Must be greater than 0' },
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        const startValue = getFieldValue('longMaStart');
                        if (!startValue || !value || value >= startValue) {
                          return Promise.resolve();
                        }
                        return Promise.reject(new Error('End must be greater than or equal to start'));
                      },
                    }),
                  ]}
                  help="Ending value for Long MA"
                >
                  <InputNumber
                    min={1}
                    max={300}
                    size="large"
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item
                  label="Step"
                  name="longMaStep"
                  initialValue={25}
                  rules={[
                    { required: true, message: 'Please enter step value' },
                    { type: 'number', min: 1, message: 'Must be greater than 0' },
                  ]}
                  help="Step size for Long MA"
                >
                  <InputNumber
                    min={1}
                    max={100}
                    size="large"
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
            </Row>
          </div>

          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              icon={<RocketOutlined />}
              size="large"
              disabled={exceedsLimit}
            >
              {t.optimization.runOptimization}
            </Button>
            <span style={{ marginLeft: '12px', fontSize: '12px', color: '#666' }}>
              Will test {shortCount} Short MA × {longCount} Long MA = {totalCombinations} combinations{exceedsLimit ? ` (Maximum allowed: ${MAX_COMBINATIONS})` : ''}
            </span>
          </Form.Item>
        </Form>
      </Card>

      {/* Success Display */}
      {success && (
        <Alert
          message="Backtest Started Successfully"
          description={success}
          type="success"
          showIcon
          style={{ marginBottom: '24px' }}
        />
      )}
      
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
          
          {/* Run Backtest with Best Parameters Button */}
          {optimizationResults.length > 0 && (
            <Card style={{ marginBottom: '24px', background: '#f6ffed', border: '1px solid #b7eb8f' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontSize: '16px', fontWeight: '600', color: '#389e0d', marginBottom: '4px' }}>
                    🚀 Run Backtest with Best Parameters
                  </div>
                  <div style={{ fontSize: '12px', color: '#666' }}>
                    Run a detailed backtest using the best combination found by optimization.
                  </div>
                </div>
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={runBacktestWithBestParams}
                  loading={loading}
                  size="large"
                  style={{ background: '#389e0d', borderColor: '#389e0d' }}
                >
                  Run Backtest
                </Button>
              </div>
            </Card>
          )}

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
          <Card 
            title="Optimization Results"
            extra={
              <Button
                type="default"
                icon={<DownloadOutlined />}
                onClick={exportToCSV}
                disabled={optimizationResults.length === 0}
                size="middle"
              >
                Export CSV
              </Button>
            }
          >
            <OptimizationResultsTable results={optimizationResults} />
          </Card>
        </>
      )}
    </div>
  );
};

export default ParameterOptimization;