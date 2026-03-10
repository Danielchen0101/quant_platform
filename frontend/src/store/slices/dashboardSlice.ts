import { createSlice, createAsyncThunk, PayloadAction } from '@reduxjs/toolkit';
import { systemAPI, marketAPI } from '../../services/api';

interface DashboardState {
 systemStatus: any;
 stocks: any[];
 loading: boolean;
 error: string | null;
 lastUpdate: string | null;
}

const initialState: DashboardState = {
 systemStatus: null,
 stocks: [],
 loading: false,
 error: null,
 lastUpdate: null,
};

export const fetchDashboardData = createAsyncThunk(
 'dashboard/fetchData',
 async () => {
 const [statusRes, stocksRes] = await Promise.all([
 systemAPI.getSystemStatus(),
 marketAPI.getStocks(),
 ]);
 return {
 systemStatus: statusRes.data,
 stocks: stocksRes.data.stocks || [],
 };
 }
);

const dashboardSlice = createSlice({
 name: 'dashboard',
 initialState,
 reducers: {
 clearError: (state) => {
 state.error = null;
 },
 updateStocks: (state, action: PayloadAction<any[]>) => {
 state.stocks = action.payload;
 state.lastUpdate = new Date().toISOString();
 },
 },
 extraReducers: (builder) => {
 builder
 .addCase(fetchDashboardData.pending, (state) => {
 state.loading = true;
 state.error = null;
 })
 .addCase(fetchDashboardData.fulfilled, (state, action) => {
 state.loading = false;
 state.systemStatus = action.payload.systemStatus;
 state.stocks = action.payload.stocks;
 state.lastUpdate = new Date().toISOString();
 })
 .addCase(fetchDashboardData.rejected, (state, action) => {
 state.loading = false;
 state.error = action.error.message || 'Failed to load dashboard data';
 });
 },
});

export const { clearError, updateStocks } = dashboardSlice.actions;
export default dashboardSlice.reducer;