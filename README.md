# Professional Quantitative Trading Platform

A modern quantitative trading platform with frontend-backend separation architecture.

## Project Structure

```
professional_quant_platform/
│
├── backend/          # Python Flask backend
│   ├── start_quant_backend.py  # Main application file
│   ├── requirements.txt        # Python dependencies
│   ├── .env                   # Environment configuration
│   └── test_equity_curve.py   # Equity curve testing
│
├── frontend/         # React frontend application
│   ├── src/          # Source code
│   ├── public/       # Static resources
│   └── package.json  # Frontend dependencies
│
├── scripts/          # Startup and utility scripts
│   ├── start_backend.bat
│   ├── start_frontend.bat
│   ├── start_platform.bat
│   ├── start_all.bat
│   ├── start_platform.ps1
│   ├── check_python.bat
│   ├── check_python.ps1
│   └── check-english-files.ps1
│
├── tests/            # Test scripts
│   ├── test_all.py
│   ├── test_api_response.py
│   ├── test_api_sync.py
│   ├── test_backtest.py
│   ├── test_direct.py
│   ├── test_extreme_case.py
│   ├── test_future_dates.py
│   ├── test_import.py
│   └── test_profit_bug.py
│
├── dev/              # Development and debugging scripts
│   ├── debug_backtest.py
│   ├── debug_strategy_returns.py
│   └── network_diagnostic.py
│
├── docs/             # Documentation
│   ├── DEBUG_REPORT.md
│   ├── FIX_GUIDE.md
│   ├── FRONTEND_FIX_SUMMARY.md
│   ├── INTEGRATION_REPORT.md
│   ├── VERIFY_CHANGES.md
│   ├── PYTHON_SETUP.md
│   └── QUICK_START.md
│
├── README.md         # Main project documentation
└── .gitignore        # Git ignore rules
```

## Quick Start

### 1. Frontend Setup
```bash
cd frontend
npm install
npm start
```
Frontend will start at http://localhost:3000

### 2. Backend Setup
Ensure Python 3.8+ is installed, then:
```bash
cd backend
pip install -r requirements.txt
python start_quant_backend.py
```
Backend will start at http://localhost:8889

Detailed Python installation guide: [PYTHON_SETUP.md](./docs/PYTHON_SETUP.md)

## Features

### Frontend Features
- **Dashboard** - System status and market overview
- **Market Data** - Real-time stock data display
- **Backtest Engine** - Strategy testing with 15+ metrics
- **Strategy Comparison** - Multi-strategy performance comparison
- **Strategy Ranking** - Historical backtest performance ranking
- **Watchlist** - Stock symbol management
- **Trading Charts** - K-line charts with buy/sell signals
- **Backtest History** - Complete backtest result tracking
- **Backtest Detail** - Detailed analysis of individual backtests

### Backend Features
- **RESTful API** - Clean API endpoints
- **Stock Data** - Yahoo Finance integration (yfinance)
- **Backtest Engine** - Moving average strategy implementation
- **Performance Metrics** - 15+ financial metrics calculation
- **Data Caching** - Efficient data retrieval
- **History Storage** - Backtest result persistence

## API Endpoints

### System & Market
- `GET /api/system/status` - System health check
- `GET /api/market/stocks` - Market data
- `POST /api/auth/login` - User authentication

### Backtest Engine
- `POST /api/backtest/run` - Run backtest (synchronous)
- `GET /api/backtest/history` - Get backtest history
- `GET /api/backtest/results/{backtest_id}` - Get specific backtest results

### Performance Metrics (15+)
1. **Total Return** - Overall return percentage
2. **Annualized Return** - Compounded annual growth rate
3. **Profit/Loss** - Absolute profit/loss amount
4. **Sharpe Ratio** - Risk-adjusted return
5. **Sortino Ratio** - Downside risk-adjusted return
6. **Max Drawdown** - Maximum peak-to-trough decline
7. **Calmar Ratio** - Return to max drawdown ratio
8. **Win Rate** - Percentage of winning trades
9. **Trades** - Total number of trades
10. **Avg Return per Trade** - Average trade return
11. **Volatility** - Annualized volatility
12. **Profit Factor** - Gross profit / gross loss ratio
13. **Expectancy** - Expected value per trade
14. **Exposure** - Market exposure percentage
15. **Equity Curve** - Daily portfolio value progression

## Pages Overview

### 1. Dashboard (`/`)
System overview with market data and recent backtests.

### 2. Market (`/market`)
Real-time stock market data with popular symbols.

### 3. Backtest (`/backtest`)
Core backtesting interface with strategy configuration and results display.

### 4. Strategy Comparison (`/compare`)
Compare multiple backtest results side-by-side with normalized equity curves.

### 5. Strategy Ranking (`/ranking`)
Rank historical backtests by performance metrics (default: Total Return).

### 6. Watchlist (`/watchlist`)
Manage favorite stock symbols and run quick backtests.

### 7. Backtest Detail (`/backtest/:id`)
Detailed view of individual backtest with full metrics and charts.

### 8. Profile (`/profile`)
User profile page (coming soon).

## Technical Stack

### Frontend
- **React 18** - UI library
- **TypeScript** - Type safety
- **Ant Design** - UI components
- **Recharts** - Data visualization
- **React Router** - Navigation
- **Axios** - HTTP client

### Backend
- **Flask** - Web framework
- **yfinance** - Stock data
- **pandas** - Data analysis
- **numpy** - Numerical computing
- **Flask-CORS** - Cross-origin support

## Development Guide

### Code Standards
- Frontend: TypeScript with ESLint
- Backend: PEP 8 Python style guide
- API: RESTful design principles

### Testing
```bash
# Frontend testing
cd frontend
npm test

# Backend testing
cd backend
python -m pytest
```

## Environment Configuration

### Backend Environment Variables
Copy `.env.example` to `.env` and configure:
```env
FLASK_APP=start_quant_backend.py
FLASK_ENV=development
JWT_SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///quant.db
```

## Deployment

### Production Deployment
1. Set production environment variables
2. Use Gunicorn for backend
3. Build frontend production version
4. Configure Nginx reverse proxy

### Docker Deployment
```bash
docker-compose up --build
```

## Troubleshooting

Common issues and solutions: [DEBUG_REPORT.md](./docs/DEBUG_REPORT.md)

## Project Status

### ✅ Completed Features
- Backtest engine with 15+ metrics
- Real-time market data
- Strategy comparison
- Performance ranking
- Watchlist management
- Trading charts
- History tracking

### 🔄 In Progress
- User authentication system
- Additional strategy types
- Real-time data streaming
- Advanced risk analysis

### 📋 Planned Features
- Portfolio optimization
- Machine learning integration
- Paper trading
- Social features
- Mobile application

## License

MIT License

---

## 中文翻译备注

### 项目概述
专业量化交易平台，采用前后端分离架构，提供完整的量化交易功能。

### 核心功能
- **回测引擎**：支持15+金融指标计算
- **策略比较**：多策略并行对比分析
- **性能排名**：历史回测结果排名
- **观察列表**：股票符号管理
- **交易图表**：K线图+买卖信号标记

### 技术特点
- **前端**：React + TypeScript + Ant Design
- **后端**：Flask + yfinance + pandas
- **数据**：Yahoo Finance实时数据
- **架构**：RESTful API设计

### 使用说明
1. 启动后端：`python start_quant_backend.py` (端口8889)
2. 启动前端：`npm start` (端口3000)
3. 访问地址：http://localhost:3000

### 开发状态
✅ 核心功能已完成
🔄 部分功能开发中
📋 计划功能待开发

### 注意事项
- 需要Python 3.8+环境
- 首次运行需安装依赖：`pip install -r requirements.txt`
- 详细问题排查请查看DEBUG_REPORT.md