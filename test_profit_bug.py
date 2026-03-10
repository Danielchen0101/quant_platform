#!/usr/bin/env python3
"""
测试 profit/loss 计算错误的根本原因
"""

import sys
sys.path.insert(0, 'backend')

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def debug_calculation(symbol='AAPL', start_date='2023-01-01', end_date='2024-01-01'):
    """调试计算过程，查找问题"""
    print(f"=== 调试 {symbol} 从 {start_date} 到 {end_date} ===")
    
    # 获取数据
    stock = yf.Ticker(symbol)
    hist_data = stock.history(start=start_date, end=end_date)
    
    print(f"数据形状: {hist_data.shape}")
    print(f"价格范围: {hist_data['Close'].min():.2f} - {hist_data['Close'].max():.2f}")
    
    # 检查价格异常
    price_changes = hist_data['Close'].pct_change()
    print(f"价格变化百分比范围: {price_changes.min():.6f} - {price_changes.max():.6f}")
    print(f"价格变化绝对值 > 10% 的天数: {(abs(price_changes) > 0.1).sum()}")
    print(f"价格变化绝对值 > 50% 的天数: {(abs(price_changes) > 0.5).sum()}")
    
    # 计算移动平均和信号
    hist_data['SMA_20'] = hist_data['Close'].rolling(window=20).mean()
    hist_data['SMA_50'] = hist_data['Close'].rolling(window=50).mean()
    hist_data['Signal'] = 0
    hist_data.loc[hist_data['SMA_20'] > hist_data['SMA_50'], 'Signal'] = 1
    hist_data.loc[hist_data['SMA_20'] < hist_data['SMA_50'], 'Signal'] = -1
    
    print(f"信号值范围: {hist_data['Signal'].min()} - {hist_data['Signal'].max()}")
    print(f"信号分布: 1={ (hist_data['Signal'] == 1).sum()}, -1={ (hist_data['Signal'] == -1).sum()}, 0={ (hist_data['Signal'] == 0).sum()}")
    
    # 计算收益
    hist_data['Returns'] = hist_data['Close'].pct_change()
    hist_data['Strategy_Returns'] = hist_data['Signal'].shift(1) * hist_data['Returns']
    
    print(f"策略收益范围: {hist_data['Strategy_Returns'].min():.6f} - {hist_data['Strategy_Returns'].max():.6f}")
    
    # 检查异常大的收益
    large_returns = hist_data['Strategy_Returns'][abs(hist_data['Strategy_Returns']) > 0.5]
    if len(large_returns) > 0:
        print(f"警告: 发现 {len(large_returns)} 天策略收益 > 50%:")
        for date, value in large_returns.head().items():
            print(f"  {date}: {value:.4f}")
    
    # 计算累积收益
    cumulative = (1 + hist_data['Strategy_Returns']).cumprod()
    print(f"累积收益最终值: {cumulative.iloc[-1]:.6f}")
    
    # 计算总收益率
    total_return_pct = (cumulative.iloc[-1] - 1) * 100
    print(f"总收益率: {total_return_pct:.2f}%")
    
    # 模拟初始资本
    initial_capital = 100000
    profit_loss = initial_capital * (total_return_pct / 100)
    print(f"盈亏金额: ${profit_loss:.2f}")
    
    # 检查是否出现异常大的值
    if abs(total_return_pct) > 1000:
        print(f"!!! 异常: 总收益率 {total_return_pct:.2f}% 超过 1000%")
        # 进一步分析
        print(f"累积收益最大值: {cumulative.max():.2f}")
        print(f"累积收益最小值: {cumulative.min():.2f}")
        
        # 找出导致问题的日期
        if len(cumulative) > 0:
            # 查找累积收益突然变化的日子
            cumulative_pct_change = cumulative.pct_change()
            large_changes = cumulative_pct_change[abs(cumulative_pct_change) > 0.5]
            if len(large_changes) > 0:
                print(f"累积收益大幅变化的日子:")
                for date, change in large_changes.head().items():
                    idx = hist_data.index.get_loc(date)
                    signal = hist_data.iloc[idx-1]['Signal'] if idx > 0 else 'N/A'
                    returns = hist_data.iloc[idx]['Returns'] if idx < len(hist_data) else 'N/A'
                    strat_returns = hist_data.iloc[idx]['Strategy_Returns'] if idx < len(hist_data) else 'N/A'
                    print(f"  {date}: 变化={change:.2f}, 信号={signal}, 日收益={returns:.4f}, 策略收益={strat_returns:.4f}")
    
    return hist_data, cumulative

def test_specific_symbols():
    """测试特定股票符号"""
    test_cases = [
        ('AAPL', '2023-01-01', '2024-01-01'),
        ('TSLA', '2023-01-01', '2024-01-01'),
        ('GME', '2023-01-01', '2024-01-01'),  # 波动性大的股票
        ('AMC', '2023-01-01', '2024-01-01'),   # 波动性大的股票
    ]
    
    for symbol, start, end in test_cases:
        try:
            hist_data, cumulative = debug_calculation(symbol, start, end)
            print()
        except Exception as e:
            print(f"测试 {symbol} 时出错: {e}")
            print()

if __name__ == "__main__":
    print("开始测试 profit/loss 计算错误...")
    test_specific_symbols()