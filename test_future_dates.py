#!/usr/bin/env python3
"""
测试未来日期的数据获取
"""

import sys
sys.path.insert(0, 'backend')

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def test_future_data(symbol='TSLA'):
    """测试未来日期的数据获取"""
    print(f"=== 测试 {symbol} 的未来日期数据 ===")
    
    # 未来日期
    future_start = '2025-03-10'
    future_end = '2026-03-10'
    
    print(f"请求日期: {future_start} 到 {future_end}")
    
    stock = yf.Ticker(symbol)
    hist_data = stock.history(start=future_start, end=future_end)
    
    print(f"数据形状: {hist_data.shape}")
    if not hist_data.empty:
        print(f"数据列: {list(hist_data.columns)}")
        print(f"数据前5行:")
        print(hist_data.head())
        print(f"数据后5行:")
        print(hist_data.tail())
        
        # 检查价格
        print(f"价格范围: {hist_data['Close'].min():.2f} - {hist_data['Close'].max():.2f}")
        
        # 检查是否有异常价格
        if len(hist_data) > 0:
            price_pct_change = hist_data['Close'].pct_change()
            print(f"价格变化范围: {price_pct_change.min():.6f} - {price_pct_change.max():.6f}")
            
            # 如果有价格数据，测试计算
            hist_data['SMA_20'] = hist_data['Close'].rolling(window=20).mean()
            hist_data['SMA_50'] = hist_data['Close'].rolling(window=50).mean()
            hist_data['Signal'] = 0
            hist_data.loc[hist_data['SMA_20'] > hist_data['SMA_50'], 'Signal'] = 1
            hist_data.loc[hist_data['SMA_20'] < hist_data['SMA_50'], 'Signal'] = -1
            
            hist_data['Returns'] = hist_data['Close'].pct_change()
            hist_data['Strategy_Returns'] = hist_data['Signal'].shift(1) * hist_data['Returns']
            
            cumulative = (1 + hist_data['Strategy_Returns']).cumprod()
            if len(cumulative) > 0:
                total_return_pct = (cumulative.iloc[-1] - 1) * 100
                print(f"总收益率: {total_return_pct:.2f}%")
                
                if abs(total_return_pct) > 10000:
                    print(f"!!! 发现异常大的总收益率: {total_return_pct:.2f}%")
                    print(f"累积收益最终值: {cumulative.iloc[-1]:.2f}")
                    print(f"策略收益统计:")
                    print(f"  非NaN数量: {hist_data['Strategy_Returns'].notna().sum()}")
                    print(f"  最大值: {hist_data['Strategy_Returns'].max():.6f}")
                    print(f"  最小值: {hist_data['Strategy_Returns'].min():.6f}")
                    print(f"  平均值: {hist_data['Strategy_Returns'].mean():.6f}")
                    
                    # 检查具体的策略收益
                    print(f"策略收益值:")
                    for i in range(min(10, len(hist_data))):
                        if not pd.isna(hist_data['Strategy_Returns'].iloc[i]):
                            print(f"  第{i}天: {hist_data['Strategy_Returns'].iloc[i]:.6f}")
    else:
        print("数据为空！yfinance 返回空数据框")
        
        # 测试过去日期作为对比
        print(f"\n=== 作为对比，测试过去日期 ===")
        past_start = '2023-01-01'
        past_end = '2024-01-01'
        
        past_data = stock.history(start=past_start, end=past_end)
        print(f"过去数据形状: {past_data.shape}")

def test_edge_cases():
    """测试边界情况"""
    print("\n=== 测试边界情况 ===")
    
    # 测试空数据
    print("1. 测试空数据帧:")
    empty_df = pd.DataFrame()
    print(f"空数据帧形状: {empty_df.shape}")
    
    # 测试只有一行的数据
    print("\n2. 测试模拟异常数据:")
    test_data = pd.DataFrame({
        'Close': [100, 10000, 100, 10000],  # 剧烈波动的价格
    }, index=pd.date_range('2023-01-01', periods=4))
    
    test_data['Returns'] = test_data['Close'].pct_change()
    print(f"模拟价格: {test_data['Close'].tolist()}")
    print(f"价格变化: {test_data['Returns'].tolist()}")
    
    # 模拟信号
    test_data['Signal'] = [1, 1, -1, -1]
    test_data['Strategy_Returns'] = test_data['Signal'].shift(1) * test_data['Returns']
    print(f"策略收益: {test_data['Strategy_Returns'].tolist()}")
    
    cumulative = (1 + test_data['Strategy_Returns']).cumprod()
    print(f"累积收益: {cumulative.tolist()}")
    total_return_pct = (cumulative.iloc[-1] - 1) * 100
    print(f"总收益率: {total_return_pct:.2f}%")
    
    # 测试极端情况
    print("\n3. 测试极端价格变化:")
    extreme_data = pd.DataFrame({
        'Close': [100, 1, 100, 1],  # 价格在1和100之间振荡
    }, index=pd.date_range('2023-01-01', periods=4))
    
    extreme_data['Returns'] = extreme_data['Close'].pct_change()
    print(f"极端价格变化: {extreme_data['Returns'].tolist()}")
    print(f"注意: pct_change 从 100 到 1 是 -0.99 (下降99%)")
    print(f"      从 1 到 100 是 99.0 (上涨9900%)")

if __name__ == "__main__":
    test_future_data('TSLA')
    test_edge_cases()