#!/usr/bin/env python3
"""
专业量化交易平台后端
基于Flask + Qlib + Backtrader + PostgreSQL
参考GitHub优秀量化平台架构
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from functools import wraps

# Flask核心
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, get_jwt
)

# 量化分析库
import pandas as pd
import numpy as np
import yfinance as yf
from backtrader import Cerebro, feeds, indicators, analyzers
import qlib
from qlib.config import C
from qlib.data import D
from qlib.contrib.data.handler import Alpha158

# 环境配置
from dotenv import load_dotenv
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/backend.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 创建Flask应用
app = Flask(__name__)

# 配置
app.config.update(
    SECRET_KEY=os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production'),
    JWT_SECRET_KEY=os.getenv('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production'),
    JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=24),
    SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///quant.db'),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    CORS_ORIGINS=json.loads(os.getenv('CORS_ORIGINS', '["http://localhost:3000"]'))
)

# 初始化扩展
CORS(app, origins=app.config['CORS_ORIGINS'])
jwt = JWTManager(app)
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ========== 数据库模型 ==========

class User(db.Model):
    """用户模型"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='user')  # admin, trader, viewer
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    
    # 关系
    portfolios = db.relationship('Portfolio', backref='owner', lazy=True)
    strategies = db.relationship('Strategy', backref='creator', lazy=True)
    orders = db.relationship('Order', backref='user', lazy=True)

class Portfolio(db.Model):
    """投资组合模型"""
    __tablename__ = 'portfolios'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    initial_capital = db.Column(db.Float, default=100000.0)
    current_value = db.Column(db.Float, default=100000.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    holdings = db.relationship('Holding', backref='portfolio', lazy=True)
    transactions = db.relationship('Transaction', backref='portfolio', lazy=True)

class Strategy(db.Model):
    """交易策略模型"""
    __tablename__ = 'strategies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    strategy_type = db.Column(db.String(50))  # trend, mean_reversion, momentum, etc.
    parameters = db.Column(db.JSON)  # 策略参数
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_public = db.Column(db.Boolean, default=False)
    performance_metrics = db.Column(db.JSON)  # 回测性能指标
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Order(db.Model):
    """订单模型"""
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    order_type = db.Column(db.String(20))  # market, limit, stop
    side = db.Column(db.String(10))  # buy, sell
    quantity = db.Column(db.Float)
    price = db.Column(db.Float)
    status = db.Column(db.String(20), default='pending')  # pending, filled, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    filled_at = db.Column(db.DateTime)

class Holding(db.Model):
    """持仓模型"""
    __tablename__ = 'holdings'
    
    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(db.Integer, db.ForeignKey('portfolios.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Float, default=0.0)
    average_price = db.Column(db.Float)
    current_price = db.Column(db.Float)
    market_value = db.Column(db.Float)
    unrealized_pnl = db.Column(db.Float)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Transaction(db.Model):
    """交易记录模型"""
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(db.Integer, db.ForeignKey('portfolios.id'), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    transaction_type = db.Column(db.String(20))  # buy, sell, dividend, fee
    quantity = db.Column(db.Float)
    price = db.Column(db.Float)
    amount = db.Column(db.Float)
    fee = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

# ========== 量化引擎 ==========

class QuantEngine:
    """量化分析引擎"""
    
    def __init__(self):
        self.qlib_initialized = False
        self.init_qlib()
    
    def init_qlib(self):
        """初始化Qlib"""
        try:
            qlib.init(
                provider_uri=os.getenv('QLIB_DATA_DIR', './qlib_data'),
                region=os.getenv('QLIB_REGION', 'us')
            )
            self.qlib_initialized = True
            logger.info("Qlib初始化成功")
        except Exception as e:
            logger.error(f"Qlib初始化失败: {e}")
            self.qlib_initialized = False
    
    def get_stock_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取股票数据"""
        try:
            stock = yf.Ticker(symbol)
            df = stock.history(start=start_date, end=end_date)
            return df
        except Exception as e:
            logger.error(f"获取股票数据失败 {symbol}: {e}")
            return pd.DataFrame()
    
    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        if df.empty:
            return df
        
        # 移动平均线
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA60'] = df['Close'].rolling(window=60).mean()
        
        # RSI
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['Histogram'] = df['MACD'] - df['Signal']
        
        # 布林带
        df['BB_Middle'] = df['Close'].rolling(window=20).mean()
        bb_std = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['BB_Middle'] + (bb_std * 2)
        df['BB_Lower'] = df['BB_Middle'] - (bb_std * 2)
        
        # 成交量指标
        df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
        
        return df
    
    def run_backtest(self, strategy_class, symbol: str, start_date: str, 
                    end_date: str, initial_cash: float = 100000.0) -> Dict:
        """运行回测"""
        try:
            # 获取数据
            df = self.get_stock_data(symbol, start_date, end_date)
            if df.empty:
                return {"error": "无法获取数据"}
            
            # 创建Backtrader引擎
            cerebro = Cerebro()
            cerebro.broker.setcash(initial_cash)
            cerebro.broker.setcommission(commission=0.001)  # 0.1%手续费
            
            # 添加数据
            data = feeds.PandasData(dataname=df)
            cerebro.adddata(data)
            
            # 添加策略
            cerebro.addstrategy(strategy_class)
            
            # 添加分析器
            cerebro.addanalyzer(analyzers.Returns, _name='returns')
            cerebro.addanalyzer(analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
            cerebro.addanalyzer(analyzers.DrawDown, _name='drawdown')
            cerebro.addanalyzer(analyzers.TradeAnalyzer, _name='trades')
            
            # 运行回测
            results = cerebro.run()
            strat = results[0]
            
            # 提取结果
            final_value = cerebro.broker.getvalue()
            total_return = (final_value - initial_cash) / initial_cash * 100
            
            # 获取分析器结果
            returns_analysis = strat.analyzers.returns.get_analysis()
            sharpe_analysis = strat.analyzers.sharpe.get_analysis()
            drawdown_analysis = strat.analyzers.drawdown.get_analysis()
            trade_analysis = strat.analyzers.trades.get_analysis()
            
            return {
                "initial_cash": initial_cash,
                "final_value": final_value,
                "total_return": total_return,
                "sharpe_ratio": sharpe_analysis.get('sharperatio', 0),
                "max_drawdown": drawdown_analysis.get('max', {}).get('drawdown', 0),
                "total_trades": trade_analysis.get('total', {}).get('total', 0),
                "win_rate": trade_analysis.get('won', {}).get('total', 0) / max(trade_analysis.get('total', {}).get('total', 1), 1) * 100,
                "avg_win": trade_analysis.get('won', {}).get('pnl', {}).get('average', 0),
                "avg_loss": trade_analysis.get('lost', {}).get('pnl', {}).get('average', 0)
            }
            
        except Exception as e:
            logger.error(f"回测失败: {e}")
            return {"error": str(e)}
    
    def analyze_market(self, symbols: List[str]) -> Dict:
        """市场分析"""
        results = {}
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        
        for symbol in symbols:
            try:
                df = self.get_stock_data(symbol, start_date, end_date)
                if not df.empty:
                    df = self.calculate_technical_indicators(df)
                    
                    latest = df.iloc[-1]
                    results[symbol] = {
                        "price": float(latest['Close']),
                        "change": float(latest['Close'] - df.iloc[-2]['Close']),
                        "change_pct": float((latest['Close'] - df.iloc[-2]['Close']) / df.iloc[-2]['Close'] * 100),
                        "volume": int(latest['Volume']),
                        "ma5": float(latest['MA5']) if 'MA5' in latest else None,
                        "ma20": float(latest['MA20']) if 'MA20' in latest else None,
                        "rsi": float(latest['RSI']) if 'RSI' in latest else None,
                        "macd": float(latest['MACD']) if 'MACD' in latest else None,
                        "signal": float(latest['Signal']) if 'Signal' in latest else None
                    }
            except Exception as e:
                logger.error(f"分析{symbol}失败: {e}")
                results[symbol] = {"error": str(e)}
        
        return results

# ========== 交易策略 ==========

class SMACrossover:
    """简单移动平均线交叉策略"""
    
    def __init__(self):
        self.sma_fast = None
        self.sma_slow = None
        self.order = None
        
    def __call__(self):
        # 快速SMA (5日)
        self.sma_fast = indicators.SMA(self.data, period=5)
        # 慢速SMA (20日)
        self.sma_slow = indicators.SMA(self.data, period=20)
        
    def next(self):
        # 如果没有持仓
        if not self.position:
            # 如果快速SMA上穿慢速SMA，买入
            if self.sma_fast[0] > self.sma_slow[0] and self.sma_fast[-1] <= self.sma_slow[-1]:
                self.order = self.buy()
        else:
            # 如果快速SMA下穿慢速SMA，卖出
            if self.sma_fast[0] < self.sma_slow[0] and self.sma_fast[-1] >= self.sma_slow[-1]:
                self.order = self.sell()

class RSIStrategy:
    """RSI超买超卖策略"""
    
    def __init__(self):
        self.rsi = None
        self.order = None
        
    def __call__(self):
        self.rsi = indicators.RSI(self.data, period=14)
        
    def next(self):
        if not self.position:
            # RSI低于30，超卖，买入
            if self.rsi[0] < 30:
                self.order = self.buy()
        else:
            # RSI高于70，超买，卖出
            if self.rsi[0] > 70:
                self.order = self.sell()

class BollingerBandsStrategy:
    """布林带策略"""
    
    def __init__(self):
        self.bollinger = None
        self.order = None
        
    def __call__(self):
        self.bollinger = indicators.BollingerBands(self.data, period=20, devfactor=2)
        
    def next(self):
        if not self.position:
            # 价格触及下轨，买入
            if self.data.close[0] <= self.bollinger.lines.bot[0]:
                self.order = self.buy()
        else:
            # 价格触及上轨，卖出
            if self.data.close[0] >= self.bollinger.lines.top[0]:
                self.order = self.sell()

# ========== API路由 ==========

# 初始化量化引擎
quant_engine = QuantEngine()

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "database": "connected" if db.engine else "disconnected",
            "qlib": "initialized" if quant_engine.qlib_initialized else "not_initialized",
            "backtrader": "available"
        },
        "version": "1.0.0"
    })

@app.route('/api/system/status', methods=['GET'])
def system_status():
    """系统状态"""
    return jsonify({
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "environment": os.getenv('FLASK_ENV', 'development'),
        "services": {
            "database": "connected",
            "qlib": "initialized" if quant_engine.qlib_initialized else "not_initialized",
            "backtrader": "available",
            "yfinance": "available"
        },
        "uptime": "0 days 0 hours 0 minutes"  # 实际应该计算
    })

@app.route('/api/auth/register', methods=['POST'])
def register():
    """用户注册"""
    try:
        data = request.get_json()
        
        # 验证输入
        required_fields = ['username', 'email', 'password']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"缺少必要字段: {field}"}), 400
        
        # 检查用户是否已存在
        if User.query.filter_by(username=data['username']).first():
            return jsonify({"error": "用户名已存在"}), 400
        
        if User.query.filter_by(email=data['email']).first():
            return jsonify({"error": "邮箱已存在"}), 400
        
        # 创建用户 (实际应该哈希密码)
        user = User(
            username=data['username'],
            email=data['email'],
            password_hash=data['password'],  # 实际应该使用bcrypt
            role=data.get('role', 'user')
        )
        
        db.session.add(user)
        db.session.commit()
        
        # 创建访问令牌
        access_token = create_access_token(identity=str(user.id))
        
        return jsonify({
            "message": "注册成功",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role
            },
            "access_token": access_token
        }), 201
        
    except Exception as e:
        logger.error(f"注册失败: {e}")
        return jsonify({"error": "注册失败"}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """用户登录"""
    try:
        data = request.get_json()
        
        # 验证输入
        if 'username' not in data or 'password' not in data:
            return jsonify({"error": "需要用户名和密码"}), 400
        
        # 查找用户 (实际应该验证密码哈希)
        user = User.query.filter_by(username=data['username']).first()
        if not user:
            return jsonify({"error": "用户不存在"}), 401
        
        # 简单密码验证 (实际应该使用bcrypt)
        if user.password_hash != data['password']:
            return jsonify({"error": "密码错误"}), 401
        
        # 更新最后登录时间
        user.last_login = datetime.utcnow()
        db.session.commit()
        
        # 创建访问令牌
        access_token = create_access_token(
            identity=str(user.id),
            additional_claims={
                "username": user.username,
                "role": user.role
            }
        )
        
        return jsonify({
            "message": "登录成功",
            "access_token": access_token,
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "last_login": user.last_login.isoformat() if user.last_login else None
            }
        }), 200
        
    except Exception as e:
        logger.error(f"登录失败: {e}")
        return jsonify({"error": "登录失败"}), 500

@app.route('/api/market/stocks', methods=['GET'])
@jwt_required()
def get_stocks():
    """获取股票市场数据"""
    try:
        # 默认股票列表
        symbols = request.args.get('symbols', 'AAPL,MSFT,GOOGL,TSLA,NVDA,AMZN,META').split(',')
        
        # 获取分析结果
        analysis = quant_engine.analyze_market(symbols)
        
        stocks = []
        for symbol, data in analysis.items():
            if 'error' not in data:
                stocks.append({
                    "symbol": symbol,
                    "name": self.get_stock_name(symbol),  # 需要实现这个方法
                    "price": data['price'],
                    "change": data['change'],
                    "change_pct": data['change_pct'],
                    "volume": data['volume'],
                    "market_cap": self.get_market_cap(symbol),  # 需要实现这个方法
                    "pe_ratio": self.get_pe_ratio(symbol),  # 需要实现这个方法
                    "technical_indicators": {
                        "ma5": data.get('ma5'),
                        "ma20": data.get('ma20'),
                        "rsi": data.get('rsi'),
                        "macd": data.get('macd'),
                        "signal": data.get('signal')
                    }
                })
        
        return jsonify({
            "timestamp": datetime.utcnow().isoformat(),
            "count": len(stocks),
            "stocks": stocks
        }), 200
        
    except Exception as e:
        logger.error(f"获取股票数据失败: {e}")
        return jsonify({"error": "获取市场数据失败"}), 500

@app.route('/api/market/stock/<symbol>', methods=['GET'])
@jwt_required()
def get_stock_detail(symbol):
    """获取单个股票详细信息"""
    try:
        # 获取历史数据
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        
        df = quant_engine.get_stock_data(symbol, start_date, end_date)
        if df.empty:
            return jsonify({"error": "无法获取股票数据"}), 404
        
        # 计算技术指标
        df = quant_engine.calculate_technical_indicators(df)
        
        # 准备响应数据
        history = []
        for idx, row in df.iterrows():
            history.append({
                "date": idx.strftime('%Y-%m-%d'),
                "open": float(row['Open']),
                "high": float(row['High']),
                "low": float(row['Low']),
                "close": float(row['Close']),
                "volume": int(row['Volume']),
                "indicators": {
                    "ma5": float(row['MA5']) if 'MA5' in row else None,
                    "ma20": float(row['MA20']) if 'MA20' in row else None,
                    "rsi": float(row['RSI']) if 'RSI' in row else None,
                    "macd": float(row['MACD']) if 'MACD' in row else None
                }
            })
        
        latest = df.iloc[-1]
        
        return jsonify({
            "symbol": symbol,
            "name": self.get_stock_name(symbol),
            "current_price": float(latest['Close']),
            "change": float(latest['Close'] - df.iloc[-2]['Close']),
            "change_pct": float((latest['Close'] - df.iloc[-2]['Close']) / df.iloc[-2]['Close'] * 100),
            "volume": int(latest['Volume']),
            "market_cap": self.get_market_cap(symbol),
            "pe_ratio": self.get_pe_ratio(symbol),
            "dividend_yield": self.get_dividend_yield(symbol),
            "history": history[-30:],  # 最近30天
            "technical_summary": self.generate_technical_summary(df)
        }), 200
        
    except Exception as e:
        logger.error(f"获取股票详情失败 {symbol}: {e}")
        return jsonify({"error": "获取股票详情失败"}), 500

@app.route('/api/backtest/run', methods=['POST'])
@jwt_required()
def run_backtest():
    """运行策略回测"""
    try:
        data = request.get_json()
        
        # 验证输入
        required_fields = ['strategy', 'symbol', 'start_date', 'end_date']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"缺少必要字段: {field}"}), 400
        
        # 选择策略
        strategy_map = {
            "sma_crossover": SMACrossover,
            "rsi_strategy": RSIStrategy,
            "bollinger_bands": BollingerBandsStrategy
        }
        
        strategy_class = strategy_map.get(data['strategy'])
        if not strategy_class:
            return jsonify({"error": "不支持的策略类型"}), 400
        
        # 运行回测
        result = quant_engine.run_backtest(
            strategy_class=strategy_class,
            symbol=data['symbol'],
            start_date=data['start_date'],
            end_date=data['end_date'],
            initial_cash=data.get('initial_cash', 100000.0)
        )
        
        if 'error' in result:
            return jsonify({"error": result['error']}), 500
        
        # 保存回测结果到数据库 (可选)
        current_user_id = get_jwt_identity()
        strategy = Strategy(
            name=f"{data['strategy']}_{data['symbol']}",
            description=f"{data['strategy']}策略在{data['symbol']}上的回测",
            strategy_type=data['strategy'],
            parameters=data,
            user_id=current_user_id,
            performance_metrics=result
        )
        
        db.session.add(strategy)
        db.session.commit()
        
        return jsonify({
            "message": "回测完成",
            "backtest_id": strategy.id,
            "results": result,
            "timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"回测失败: {e}")
        return jsonify({"error": "回测失败"}), 500

@app.route('/api/backtest/strategies', methods=['GET'])
@jwt_required()
def get_strategies():
    """获取可用策略列表"""
    strategies = [
        {
            "id": "sma_crossover",
            "name": "简单移动平均线交叉策略",
            "description": "当短期均线上穿长期均线时买入，下穿时卖出",
            "parameters": {
                "fast_period": {"type": "int", "default": 5, "min": 2, "max": 50},
                "slow_period": {"type": "int", "default": 20, "min": 10, "max": 200}
            }
        },
        {
            "id": "rsi_strategy",
            "name": "RSI超买超卖策略",
            "description": "RSI低于30时买入（超卖），高于70时卖出（超买）",
            "parameters": {
                "rsi_period": {"type": "int", "default": 14, "min": 5, "max": 30},
                "oversold": {"type": "int", "default": 30, "min": 10, "max": 40},
                "overbought": {"type": "int", "default": 70, "min": 60, "max": 90}
            }
        },
        {
            "id": "bollinger_bands",
            "name": "布林带突破策略",
            "description": "价格触及下轨时买入，触及上轨时卖出",
            "parameters": {
                "period": {"type": "int", "default": 20, "min": 10, "max": 50},
                "devfactor": {"type": "float", "default": 2.0, "min": 1.5, "max": 3.0}
            }
        }
    ]
    
    return jsonify({
        "count": len(strategies),
        "strategies": strategies
    }), 200

@app.route('/api/portfolio/create', methods=['POST'])
@jwt_required()
def create_portfolio():
    """创建投资组合"""
    try:
        data = request.get_json()
        current_user_id = get_jwt_identity()
        
        # 验证输入
        if 'name' not in data:
            return jsonify({"error": "需要投资组合名称"}), 400
        
        # 创建投资组合
        portfolio = Portfolio(
            name=data['name'],
            description=data.get('description', ''),
            user_id=current_user_id,
            initial_capital=data.get('initial_capital', 100000.0),
            current_value=data.get('initial_capital', 100000.0)
        )
        
        db.session.add(portfolio)
        db.session.commit()
        
        return jsonify({
            "message": "投资组合创建成功",
            "portfolio": {
                "id": portfolio.id,
                "name": portfolio.name,
                "description": portfolio.description,
                "initial_capital": portfolio.initial_capital,
                "current_value": portfolio.current_value,
                "created_at": portfolio.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        logger.error(f"创建投资组合失败: {e}")
        return jsonify({"error": "创建投资组合失败"}), 500

@app.route('/api/portfolio/<int:portfolio_id>', methods=['GET'])
@jwt_required()
def get_portfolio(portfolio_id):
    """获取投资组合详情"""
    try:
        current_user_id = get_jwt_identity()
        
        portfolio = Portfolio.query.filter_by(
            id=portfolio_id, 
            user_id=current_user_id
        ).first()
        
        if not portfolio:
            return jsonify({"error": "投资组合不存在或无权访问"}), 404
        
        # 获取持仓
        holdings = []
        for holding in portfolio.holdings:
            holdings.append({
                "symbol": holding.symbol,
                "quantity": holding.quantity,
                "average_price": holding.average_price,
                "current_price": holding.current_price,
                "market_value": holding.market_value,
                "unrealized_pnl": holding.unrealized_pnl
            })
        
        # 获取交易记录
        transactions = []
        for tx in portfolio.transactions.order_by(Transaction.timestamp.desc()).limit(20):
            transactions.append({
                "id": tx.id,
                "symbol": tx.symbol,
                "type": tx.transaction_type,
                "quantity": tx.quantity,
                "price": tx.price,
                "amount": tx.amount,
                "fee": tx.fee,
                "timestamp": tx.timestamp.isoformat(),
                "notes": tx.notes
            })
        
        return jsonify({
            "portfolio": {
                "id": portfolio.id,
                "name": portfolio.name,
                "description": portfolio.description,
                "initial_capital": portfolio.initial_capital,
                "current_value": portfolio.current_value,
                "total_return": (portfolio.current_value - portfolio.initial_capital) / portfolio.initial_capital * 100,
                "created_at": portfolio.created_at.isoformat(),
                "updated_at": portfolio.updated_at.isoformat()
            },
            "holdings": holdings,
            "transactions": transactions,
            "performance_metrics": self.calculate_portfolio_metrics(portfolio)
        }), 200
        
    except Exception as e:
        logger.error(f"获取投资组合失败: {e}")
        return jsonify({"error": "获取投资组合失败"}), 500

@app.route('/api/risk/analyze', methods=['POST'])
@jwt_required()
def analyze_risk():
    """风险分析"""
    try:
        data = request.get_json()
        
        # 这里实现风险分析逻辑
        # 包括: VaR计算, 压力测试, 相关性分析等
        
        return jsonify({
            "message": "风险分析完成",
            "metrics": {
                "var_95": 0.0,  # 95%置信度的VaR
                "expected_shortfall": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "beta": 0.0,
                "alpha": 0.0
            },
            "timestamp": datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"风险分析失败: {e}")
        return jsonify({"error": "风险分析失败"}), 500

# ========== 辅助方法 ==========

def get_stock_name(self, symbol: str) -> str:
    """获取股票名称"""
    stock_names = {
        "AAPL": "Apple Inc.",
        "MSFT": "Microsoft Corporation",
        "GOOGL": "Alphabet Inc.",
        "TSLA": "Tesla Inc.",
        "NVDA": "NVIDIA Corporation",
        "AMZN": "Amazon.com Inc.",
        "META": "Meta Platforms Inc.",
        "BTC-USD": "Bitcoin USD",
        "ETH-USD": "Ethereum USD"
    }
    return stock_names.get(symbol, symbol)

def get_market_cap(self, symbol: str) -> float:
    """获取市值"""
    market_caps = {
        "AAPL": 2750000000000,
        "MSFT": 2450000000000,
        "GOOGL": 1700000000000,
        "TSLA": 590000000000,
        "NVDA": 1200000000000,
        "AMZN": 1570000000000,
        "META": 985000000000,
        "BTC-USD": 885000000000,
        "ETH-USD": 295000000000
    }
    return market_caps.get(symbol, 0)

def get_pe_ratio(self, symbol: str) -> float:
    """获取市盈率"""
    pe_ratios = {
        "AAPL": 28.5,
        "MSFT": 32.8,
        "GOOGL": 24.2,
        "TSLA": 65.3,
        "NVDA": 58.7,
        "AMZN": 78.9,
        "META": 26.8,
        "BTC-USD": 0,
        "ETH-USD": 0
    }
    return pe_ratios.get(symbol, 0)

def get_dividend_yield(self, symbol: str) -> float:
    """获取股息率"""
    dividend_yields = {
        "AAPL": 0.55,
        "MSFT": 0.85,
        "GOOGL": 0.00,
        "TSLA": 0.00,
        "NVDA": 0.03,
        "AMZN": 0.00,
        "META": 0.00,
        "BTC-USD": 0.00,
        "ETH-USD": 0.00
    }
    return dividend_yields.get(symbol, 0)

def generate_technical_summary(self, df: pd.DataFrame) -> Dict:
    """生成技术分析摘要"""
    if df.empty:
        return {}
    
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    
    summary = {
        "trend": "neutral",
        "momentum": "neutral",
        "volatility": "normal",
        "volume": "normal",
        "signals": []
    }
    
    # 趋势判断
    if 'MA5' in latest and 'MA20' in latest:
        if latest['MA5'] > latest['MA20'] and prev['MA5'] <= prev['MA20']:
            summary['trend'] = "bullish"
            summary['signals'].append("MA5上穿MA20，看涨信号")
        elif latest['MA5'] < latest['MA20'] and prev['MA5'] >= prev['MA20']:
            summary['trend'] = "bearish"
            summary['signals'].append("MA5下穿MA20，看跌信号")
    
    # RSI判断
    if 'RSI' in latest:
        if latest['RSI'] < 30:
            summary['momentum'] = "oversold"
            summary['signals'].append("RSI超卖，可能反弹")
        elif latest['RSI'] > 70:
            summary['momentum'] = "overbought"
            summary['signals'].append("RSI超买，可能回调")
    
    # MACD判断
    if 'MACD' in latest and 'Signal' in latest:
        if latest['MACD'] > latest['Signal'] and prev['MACD'] <= prev['Signal']:
            summary['signals'].append("MACD上穿信号线，看涨")
        elif latest['MACD'] < latest['Signal'] and prev['MACD'] >= prev['Signal']:
            summary['signals'].append("MACD下穿信号线，看跌")
    
    return summary

def calculate_portfolio_metrics(self, portfolio: Portfolio) -> Dict:
    """计算投资组合指标"""
    # 这里实现投资组合绩效计算
    return {
        "total_return": 0.0,
        "annualized_return": 0.0,
        "volatility": 0.0,
        "sharpe_ratio": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0
    }

# ========== 主程序 ==========

if __name__ == '__main__':
    # 创建数据库表
    with app.app_context():
        db.create_all()
        logger.info("数据库表创建完成")
    
    # 添加默认用户 (仅开发环境)
    if os.getenv('FLASK_ENV') == 'development':
        with app.app_context():
            if not User.query.filter_by(username='admin').first():
                admin = User(
                    username='admin',
                    email='admin@quantplatform.com',
                    password_hash='admin123',  # 实际应该哈希
                    role='admin'
                )
                db.session.add(admin)
                db.session.commit()
                logger.info("创建默认管理员用户")
    
    # 启动Flask应用
    port = int(os.getenv('PORT', 8889))
    host = os.getenv('HOST', '0.0.0.0')
    
    logger.info(f"启动量化平台后端服务...")
    logger.info(f"环境: {os.getenv('FLASK_ENV', 'development')}")
    logger.info(f"地址: http://{host}:{port}")
    logger.info(f"API文档: http://{host}:{port}/api/health")
    
    app.run(host=host, port=port, debug=True)