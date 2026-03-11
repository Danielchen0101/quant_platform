#!/usr/bin/env python3
"""
测试极端情况下的 Strategy_Returns 计算
模拟价格剧烈波动的情况
"""

import sys
sys.path.insert(0, 'backend')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def test_extreme_price_changes():
    """测试极端价格变化场景"""
    print("=== 测试极端价格变化 ===")
    
    # 场景1: 价格剧烈波动 (模拟股票分割等情况)
    dates = pd.date_range('2023-01-01', periods=10, freq='D')
    
    # 模拟价格: 100 -> 1 -> 100 -> 1 ...
    extreme_prices = [100, 1, 100, 1, 100, 1, 100, 1, 100, 1]
    
    hist_data = pd.DataFrame({
        'Close': extreme_prices,
    }, index=dates)
    
    print(f"模拟价格序列: {extreme_prices}")
    
    # 计算 Returns
    hist_data['Returns'] = hist_data['Close'].pct_change()
    print(f"Returns: {hist_data['Returns'].tolist()}")
    print(f"注意: 从 100 到 1: pct_change = (1-100)/100 = -0.99 (下降99%)")
    print(f"      从 1 到 100: pct_change = (100-1)/1 = 99.0 (上涨9900%)")
    
    # 模拟 Signal (假设总是买入)
    hist_data['Signal'] = 1  # 总是持有
    
    # 计算 Strategy_Returns
    hist_data['Strategy_Returns'] = hist_data['Signal'].shift(1) * hist_data['Returns']
    print(f"Strategy_Returns: {hist_data['Strategy_Returns'].tolist()}")
    
    # 计算累积收益
    cumulative = (1 + hist_data['Strategy_Returns']).cumprod()
    print(f"累积收益: {cumulative.tolist()}")
    
    if len(cumulative) > 0:
        final_cumulative = cumulative.iloc[-1]
        total_return_pct = (final_cumulative - 1) * 100
        print(f"最终累积值: {final_cumulative:.6f}")
        print(f"总收益率: {total_return_pct:.2f}%")
        
        # 验证计算
        print(f"\n验证计算:")
        print(f"第1天: Signal=NaN, Returns=NaN, Strategy_Returns=NaN")
        for i in range(1, min(5, len(hist_data))):
            signal = hist_data.iloc[i-1]['Signal'] if i > 0 else np.nan
            returns = hist_data.iloc[i]['Returns']
            strat_returns = hist_data.iloc[i]['Strategy_Returns']
            print(f"第{i+1}天: Signal.shift(1)={signal}, Returns={returns:.2f}, Strategy_Returns={strat_returns:.2f}")
    
    return hist_data

def test_realistic_extreme_case():
    """测试更现实的极端情况"""
    print("\n=== 测试更现实的极端情况 ===")
    
    dates = pd.date_range('2023-01-01', periods=20, freq='D')
    
    # 更现实的场景：大部分时间正常，偶尔极端
    # 第5天：价格从 100 跌到 50 (-50%)
    # 第10天：价格从 50 涨到 150 (+200%)
    prices = [100, 101, 102, 103, 100, 50, 51, 52, 53, 50, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159]
    
    hist_data = pd.DataFrame({
        'Close': prices,
    }, index=dates)
    
    # 计算移动平均和 Signal
    hist_data['SMA_20'] = hist_data['Close'].rolling(window=5).mean()  # 使用较小的窗口便于测试
    hist_data['SMA_50'] = hist_data['Close'].rolling(window=10).mean()
    hist_data['Signal'] = 0
    hist_data.loc[hist_data['SMA_20'] > hist_data['SMA_50'], 'Signal'] = 1
    hist_data.loc[hist_data['SMA_20'] < hist_data['SMA_50'], 'Signal'] = -1
    
    print(f"价格序列 (第5天: 100→50, 第10天: 50→150):")
    for i, (date, row) in enumerate(hist_data.iterrows()):
        print(f"  第{i+1}天: Close={row['Close']}, SMA_20={row['SMA_20']:.1f}, SMA_50={row['SMA_50']:.1f}, Signal={row['Signal']}")
    
    # 计算 Returns 和 Strategy_Returns
    hist_data['Returns'] = hist_data['Close'].pct_change()
    hist_data['Strategy_Returns'] = hist_data['Signal'].shift(1) * hist_data['Returns']
    
    print(f"\n关键日期分析:")
    # 第5天：价格从 100 跌到 50
    idx = 4  # 0-indexed
    if idx < len(hist_data):
        print(f"第5天 (idx={idx}):")
        print(f"  Close: {hist_data.iloc[idx-1]['Close']} → {hist_data.iloc[idx]['Close']}")
        print(f"  Returns: {hist_data.iloc[idx]['Returns']:.4f} (-50%)")
        print(f"  Signal.shift(1): {hist_data.iloc[idx-1]['Signal'] if idx > 0 else 'NaN'}")
        print(f"  Strategy_Returns: {hist_data.iloc[idx]['Strategy_Returns']:.4f}")
    
    # 第10天：价格从 50 涨到 150
    idx = 9
    if idx < len(hist_data):
        print(f"\n第10天 (idx={idx}):")
        print(f"  Close: {hist_data.iloc[idx-1]['Close']} → {hist_data.iloc[idx]['Close']}")
        print(f"  Returns: {hist_data.iloc[idx]['Returns']:.4f} (+200%)")
        print(f"  Signal.shift(1): {hist_data.iloc[idx-1]['Signal'] if idx > 0 else 'NaN'}")
        print(f"  Strategy_Returns: {hist_data.iloc[idx]['Strategy_Returns']:.4f}")
    
    # 检查异常值
    abnormal_returns = hist_data['Returns'][(hist_data['Returns'] > 1.0) | (hist_data['Returns'] < -0.5)]
    print(f"\n异常 Returns (>1.0 或 <-0.5): {len(abnormal_returns)} 天")
    
    abnormal_strat = hist_data['Strategy_Returns'][(hist_data['Strategy_Returns'] > 5.0) | (hist_data['Strategy_Returns'] < -5.0)]
    print(f"异常 Strategy_Returns (>5 或 <-5): {len(abnormal_strat)} 天")
    
    if len(abnormal_strat) > 0:
        print(f"!!! 发现异常 Strategy_Returns !!!")
        for date, value in abnormal_strat.items():
            print(f"  {date}: {value:.4f}")

def test_signal_calculation():
    """测试 Signal 计算是否正确"""
    print("\n=== 测试 Signal 计算 ===")
    
    dates = pd.date_range('2023-01-01', periods=10, freq='D')
    
    # 创建简单的价格序列
    prices = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]
    
    hist_data = pd.DataFrame({
        'Close': prices,
    }, index=dates)
    
    # 计算 SMA
    hist_data['SMA_3'] = hist_data['Close'].rolling(window=3).mean()
    hist_data['SMA_5'] = hist_data['Close'].rolling(window=5).mean()
    
    # 检查 NaN 值
    print(f"SMA_3 前2天为 NaN: {pd.isna(hist_data['SMA_3'].iloc[0])}, {pd.isna(hist_data['SMA_3'].iloc[1])}")
    print(f"SMA_5 前4天为 NaN: {pd.isna(hist_data['SMA_5'].iloc[0])}, {pd.isna(hist_data['SMA_5'].iloc[3])}")
    
    # 测试比较操作
    print(f"\n测试比较操作 (SMA_3 > SMA_5):")
    for i in range(len(hist_data)):
        sma3 = hist_data.iloc[i]['SMA_3']
        sma5 = hist_data.iloc[i]['SMA_5']
        comparison = sma3 > sma5
        print(f"  第{i+1}天: SMA_3={sma3:.1f}, SMA_5={sma5:.1f}, SMA_3 > SMA_5 = {comparison}")

if __name__ == "__main__":
    test_extreme_price_changes()
    test_realistic_extreme_case()
    test_signal_calculation()