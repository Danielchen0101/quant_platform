#!/usr/bin/env python3
"""
Test script to verify equity curve data generation
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock the calculate_backtest_metrics function
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def test_equity_curve_generation():
    """Test the equity curve generation logic"""
    
    # Create mock historical data (250 trading days)
    dates = pd.date_range(start='2023-01-01', periods=250, freq='B')
    np.random.seed(42)
    
    # Create mock cumulative returns
    cumulative = pd.Series(np.linspace(1.0, 1.5, 250), index=dates)
    
    # Test the old logic (10 points)
    print("=== OLD LOGIC (10 points) ===")
    equity_curve_old = []
    if len(cumulative) > 0:
        step = max(1, len(cumulative) // 10)
        for i in range(0, len(cumulative), step):
            if i >= len(cumulative):
                break
            equity = 100000 * cumulative.iloc[i]
            date = cumulative.index[i].strftime('%Y-%m-%d')
            equity_curve_old.append({"date": date, "equity": round(equity, 2)})
        
        # Ensure we have the last point
        if len(equity_curve_old) == 0 or equity_curve_old[-1]["date"] != cumulative.index[-1].strftime('%Y-%m-%d'):
            equity = 100000 * cumulative.iloc[-1]
            date = cumulative.index[-1].strftime('%Y-%m-%d')
            equity_curve_old.append({"date": date, "equity": round(equity, 2)})
    
    print(f"Old equity curve length: {len(equity_curve_old)}")
    print(f"Old equity curve points: {[item['date'] for item in equity_curve_old]}")
    
    # Test the new logic (all points)
    print("\n=== NEW LOGIC (all points) ===")
    equity_curve_new = []
    if len(cumulative) > 0:
        # Use all data points for daily equity curve
        for i in range(len(cumulative)):
            equity = 100000 * cumulative.iloc[i]
            date = cumulative.index[i].strftime('%Y-%m-%d')
            equity_curve_new.append({"date": date, "equity": round(equity, 2)})
    
    print(f"New equity curve length: {len(equity_curve_new)}")
    print(f"New equity curve first date: {equity_curve_new[0]['date']}")
    print(f"New equity curve last date: {equity_curve_new[-1]['date']}")
    
    # Verify the fix
    print("\n=== VERIFICATION ===")
    print(f"Old logic had {len(equity_curve_old)} points (should be ~10)")
    print(f"New logic has {len(equity_curve_new)} points (should be 250)")
    print(f"Improvement: {len(equity_curve_new) / len(equity_curve_old):.1f}x more data points")
    
    # Check if dates are evenly distributed
    if len(equity_curve_old) > 1:
        old_dates = [datetime.strptime(item['date'], '%Y-%m-%d') for item in equity_curve_old]
        old_date_diff = [(old_dates[i+1] - old_dates[i]).days for i in range(len(old_dates)-1)]
        print(f"\nOld logic date intervals: {old_date_diff}")
        print(f"Old logic average interval: {sum(old_date_diff)/len(old_date_diff):.1f} days")
    
    if len(equity_curve_new) > 1:
        new_dates = [datetime.strptime(item['date'], '%Y-%m-%d') for item in equity_curve_new]
        new_date_diff = [(new_dates[i+1] - new_dates[i]).days for i in range(len(new_dates)-1)]
        print(f"\nNew logic date intervals: mostly 1 day (daily data)")
        print(f"New logic has {sum(1 for d in new_date_diff if d == 1)} consecutive daily points")

if __name__ == "__main__":
    test_equity_curve_generation()