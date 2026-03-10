#!/usr/bin/env python3
"""
调试 Strategy_Returns 计算逻辑
检查：Signal 值、Market_Returns、Strategy_Returns 是否正常
"""

import sys
sys.path.insert(0, 'backend')

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def analyze_strategy_calculation(symbol='TSLA', start_date='2025-03-10', end_date='2026-03-10', strategy='moving_average'):
    """分析策略计算过程，检查每个步骤"""
    print(f"=== 分析 {symbol} {strategy} 策略 ===")
    print(f"日期范围: {start_date} 到 {end_date}")
    
    # 获取数据
    stock = yf.Ticker(symbol)
    hist_data = stock.history(start=start_date, end=end_date)
    
    if hist_data.empty:
        print("数据为空")
        return None
    
    print(f"数据天数: {len(hist_data)}")
    
    # 根据策略计算
    if strategy == 'moving_average':
        hist_data['SMA_20'] = hist_data['Close'].rolling(window=20).mean()
        hist_data['SMA_50'] = hist_data['Close'].rolling(window=50).mean()
        hist_data['Signal'] = 0
        hist_data.loc[hist_data['SMA_20'] > hist_data['SMA_50'], 'Signal'] = 1
        hist_data.loc[hist_data['SMA_20'] < hist_data['SMA_50'], 'Signal'] = -1
        
    elif strategy == 'rsi':
        delta = hist_data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        hist_data['RSI'] = 100 - (100 / (1 + rs))
        hist_data['Signal'] = 0
        hist_data.loc[hist_data['RSI'] < 30, 'Signal'] = 1
        hist_data.loc[hist_data['RSI'] > 70, 'Signal'] = -1
        
    elif strategy == 'macd':
        exp1 = hist_data['Close'].ewm(span=12, adjust=False).mean()
        exp2 = hist_data['Close'].ewm(span=26, adjust=False).mean()
        hist_data['MACD'] = exp1 - exp2
        hist_data['Signal_Line'] = hist_data['MACD'].ewm(span=9, adjust=False).mean()
        hist_data['Signal'] = 0
        hist_data.loc[hist_data['MACD'] > hist_data['Signal_Line'], 'Signal'] = 1
        hist_data.loc[hist_data['MACD'] < hist_data['Signal_Line'], 'Signal'] = -1
        
    elif strategy == 'momentum':
        hist_data['Momentum'] = hist_data['Close'].pct_change(periods=10)
        hist_data['Signal'] = 0
        hist_data.loc[hist_data['Momentum'] > 0, 'Signal'] = 1
        hist_data.loc[hist_data['Momentum'] < 0, 'Signal'] = -1
    
    # 计算 Returns 和 Strategy_Returns
    hist_data['Returns'] = hist_data['Close'].pct_change()
    hist_data['Strategy_Returns'] = hist_data['Signal'].shift(1) * hist_data['Returns']
    
    # 检查 Signal 值
    print(f"\n1. Signal 检查:")
    signal_values = hist_data['Signal'].unique()
    print(f"  唯一值: {sorted(signal_values)}")
    print(f"  是否在 [-1, 0, 1] 内: {all(v in [-1, 0, 1] for v in signal_values if pd.notna(v))}")
    
    signal_counts = hist_data['Signal'].value_counts()
    for val, count in signal_counts.items():
        print(f"  Signal={val}: {count} 天")
    
    # 检查 Returns
    print(f"\n2. Returns (Close.pct_change()) 检查:")
    returns_stats = hist_data['Returns'].describe()
    print(f"  统计: min={returns_stats['min']:.6f}, max={returns_stats['max']:.6f}, mean={returns_stats['mean']:.6f}")
    
    # 检查异常 Returns
    abnormal_returns = hist_data['Returns'][(hist_data['Returns'] > 0.5) | (hist_data['Returns'] < -0.5)]
    print(f"  异常 Returns (>0.5 或 <-0.5): {len(abnormal_returns)} 天")
    if len(abnormal_returns) > 0:
        for date, value in abnormal_returns.head().items():
            idx = hist_data.index.get_loc(date)
            close_price = hist_data.iloc[idx]['Close'] if idx < len(hist_data) else 'N/A'
            prev_close = hist_data.iloc[idx-1]['Close'] if idx > 0 else 'N/A'
            print(f"    {date}: Returns={value:.4f}, Close={close_price}, Prev Close={prev_close}")
    
    # 检查 Strategy_Returns
    print(f"\n3. Strategy_Returns 检查:")
    strat_returns_stats = hist_data['Strategy_Returns'].describe()
    print(f"  统计: min={strat_returns_stats['min']:.6f}, max={strat_returns_stats['max']:.6f}, mean={strat_returns_stats['mean']:.6f}")
    
    # 检查异常 Strategy_Returns
    abnormal_strat_returns = hist_data['Strategy_Returns'][
        (hist_data['Strategy_Returns'] > 5.0) | (hist_data['Strategy_Returns'] < -5.0)
    ]
    print(f"  异常 Strategy_Returns (>5 或 <-5): {len(abnormal_strat_returns)} 天")
    
    if len(abnormal_strat_returns) > 0:
        print(f"  !!! 发现异常 Strategy_Returns !!!")
        for date, value in abnormal_strat_returns.head().items():
            idx = hist_data.index.get_loc(date)
            signal = hist_data.iloc[idx-1]['Signal'] if idx > 0 else 'N/A'
            returns = hist_data.iloc[idx]['Returns'] if idx < len(hist_data) else 'N/A'
            close_price = hist_data.iloc[idx]['Close'] if idx < len(hist_data) else 'N/A'
            prev_close = hist_data.iloc[idx-1]['Close'] if idx > 0 else 'N/A'
            
            print(f"\n    日期: {date}")
            print(f"    Strategy_Returns: {value:.6f}")
            print(f"    Signal.shift(1): {signal}")
            print(f"    Returns: {returns:.6f}")
            print(f"    验证: {signal} * {returns:.6f} = {signal * returns:.6f}")
            print(f"    价格: {prev_close} → {close_price}")
            
            # 检查计算是否正确
            if idx > 0:
                actual_signal = hist_data.iloc[idx-1]['Signal']
                actual_returns = hist_data.iloc[idx]['Returns']
                calculated = actual_signal * actual_returns
                print(f"    实际计算: {actual_signal} * {actual_returns:.6f} = {calculated:.6f}")
                print(f"    匹配: {abs(value - calculated) < 0.0001}")
    
    # 检查 cumulative 计算
    print(f"\n4. 累积收益检查:")
    cumulative = (1 + hist_data['Strategy_Returns']).cumprod()
    if len(cumulative) > 0:
        final_cumulative = cumulative.iloc[-1]
        total_return_pct = (final_cumulative - 1) * 100
        print(f"  最终累积值: {final_cumulative:.6f}")
        print(f"  总收益率: {total_return_pct:.2f}%")
        
        # 检查累积值是否异常
        if final_cumulative > 100 or final_cumulative < 0.01:
            print(f"  !!! 异常累积值: {final_cumulative:.2f}")
            # 分析哪几天导致异常
            daily_contributions = hist_data['Strategy_Returns']
            large_contributions = daily_contributions[abs(daily_contributions) > 0.5]
            if len(large_contributions) > 0:
                print(f"  导致异常的大幅波动:")
                for date, value in large_contributions.head().items():
                    print(f"    {date}: {value:.4f}")
    
    return hist_data

def test_multiple_symbols():
    """测试多个股票符号"""
    test_cases = [
        ('TSLA', '2025-03-10', '2026-03-10', 'moving_average'),
        ('AAPL', '2023-01-01', '2024-01-01', 'moving_average'),
        ('GME', '2023-01-01', '2024-01-01', 'moving_average'),  # 波动性大的股票
    ]
    
    for symbol, start, end, strategy in test_cases:
        try:
            hist_data = analyze_strategy_calculation(symbol, start, end, strategy)
            print("\n" + "="*60 + "\n")
        except Exception as e:
            print(f"测试 {symbol} 时出错: {e}")
            print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    print("开始调试 Strategy_Returns 计算逻辑...")
    test_multiple_symbols()