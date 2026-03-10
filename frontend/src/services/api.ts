import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || '/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

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
};

// User API
export const userAPI = {
  getProfile: () => api.get('/user/profile'),
  updateProfile: (profileData: any) => api.put('/user/profile', profileData),
};

export default api;