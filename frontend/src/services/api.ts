import axios from 'axios';

// 使用相对路径，依赖 CRA 代理配置
// 开发模式下：/api/* → http://127.0.0.1:8889/api/*
// 生产模式下：需要配置正确的后端地址
const API_BASE_URL = '/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 添加请求拦截器用于调试（仅记录优化请求）
api.interceptors.request.use(
  (config) => {
    if (config.url && config.url.includes('/backtest/optimize')) {
      console.log('=== OPTIMIZATION REQUEST ===');
      console.log('URL:', config.url);
      console.log('Method:', config.method);
      console.log('Data:', config.data);
    }
    return config;
  },
  (error) => {
    console.error('Request error:', error);
    return Promise.reject(error);
  }
);

// 添加响应拦截器用于调试（仅记录优化响应）
api.interceptors.response.use(
  (response) => {
    if (response.config.url && response.config.url.includes('/backtest/optimize')) {
      console.log('=== OPTIMIZATION RESPONSE ===');
      console.log('Status:', response.status);
      console.log('Success:', response.data?.success);
    }
    return response;
  },
  (error) => {
    console.error('Response error:', error.message);
    if (error.response) {
      console.error('Status:', error.response.status);
      console.error('Data:', error.response.data);
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authAPI = {
  login: (credentials: any) => api.post('/auth/login', credentials),
  logout: () => api.post('/auth/logout'),
  register: (userData: any) => api.post('/auth/register', userData),
};

// System API
export const systemAPI = {
  getSystemStatus: () => api.get('/system/status'),
  getSystemMetrics: () => api.get('/system/metrics'),
};

// Market API
export const marketAPI = {
  getStocks: () => api.get('/market/stocks'),
  getStockHistory: (symbol: string) => api.get(`/market/history/${symbol}`),
};

// Backtrader API
export const backtraderAPI = {
  runBacktest: (config: any) => api.post('/backtest/run', config),
  getBacktestResults: (id: string) => api.get(`/backtest/results/${id}`),
  getBacktestHistory: () => api.get('/backtest/history'),
  runParameterOptimization: (config: any) => {
    console.log('=== API CALL: runParameterOptimization ===');
    console.log('Request config:', JSON.stringify(config, null, 2));
    return api.post('/backtest/optimize', config);
  },
};

// User API
export const userAPI = {
  getProfile: () => api.get('/user/profile'),
  updateProfile: (profileData: any) => api.put('/user/profile', profileData),
};

export default api;