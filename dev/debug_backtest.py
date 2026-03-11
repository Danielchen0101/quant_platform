#!/usr/bin/env python3
"""
Debug backtest calculations
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/backend')

# Mock the necessary imports
import random
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# Create a simplified version of the function to test
def debug_run_real_backtest(symbol, strategy, start_date, end_date, initial_capital):
    """Debug version of run_real_backtest"""
    try:
        # Mock some data for testing
        print(f"Testing with: symbol={symbol}, strategy={strategy}")
        
        # Create mock historical data
        dates = pd.date_range(start=start_date, end=end_date, freq='D')
        mock_data = pd.DataFrame({
            'Close': [100 + i * 0.1 + random.uniform(-2, 2) for i in range(len(dates))]
        }, index=dates)
        
        hist_data = mock_data
        
        if strategy == 'moving_average':
            # Calculate moving averages
            hist_data['SMA_20'] = hist_data['Close'].rolling(window=20).mean()
            hist_data['SMA_50'] = hist_data['Close'].rolling(window=50).mean()
            
            # Generate signals
            hist_data['Signal'] = 0
            hist_data.loc[hist_data['SMA_20'] > hist_data['SMA_50'], 'Signal'] = 1  # Buy
            hist_data.loc[hist_data['SMA_20'] < hist_data['SMA_50'], 'Signal'] = -1  # Sell
            
            # Calculate returns
            hist_data['Returns'] = hist_data['Close'].pct_change()
            hist_data['Strategy_Returns'] = hist_data['Signal'].shift(1) * hist_data['Returns']
            
            print(f"Data shape: {hist_data.shape}")
            print(f"Signal values: {hist_data['Signal'].value_counts().to_dict()}")
            print(f"Strategy Returns stats: mean={hist_data['Strategy_Returns'].mean():.6f}, std={hist_data['Strategy_Returns'].std():.6f}")
            
            # Calculate metrics - FIXED VERSION
            # Calculate cumulative returns properly
            cumulative = (1 + hist_data['Strategy_Returns']).cumprod()
            total_return_pct = (cumulative.iloc[-1] - 1) * 100 if len(cumulative) > 0 else 0
            
            print(f"Total return: {total_return_pct}%")
            
            # Calculate annualized return
            trading_days = len(hist_data)
            annualized_return = 0
            if trading_days > 0 and total_return_pct > -100:  # Avoid math error for total loss
                try:
                    total_return_decimal = total_return_pct / 100
                    annualized_return = ((1 + total_return_decimal) ** (252 / trading_days) - 1) * 100
                except Exception as e:
                    print(f"Error calculating annualized return: {e}")
                    annualized_return = 0
            
            print(f"Annualized return: {annualized_return}%")
            
            # Calculate profit/loss amount
            profit_loss = initial_capital * (total_return_pct / 100)
            print(f"Profit/Loss: ${profit_loss:.2f}")
            
            sharpe_ratio = (hist_data['Strategy_Returns'].mean() / hist_data['Strategy_Returns'].std() * (252 ** 0.5)) if hist_data['Strategy_Returns'].std() > 0 else 0
            print(f"Sharpe ratio: {sharpe_ratio}")
            
            # Calculate max drawdown
            running_max = cumulative.expanding().max()
            drawdown = (cumulative - running_max) / running_max
            max_drawdown_pct = drawdown.min() * 100
            print(f"Max drawdown: {max_drawdown_pct}%")
            
            # Calculate Calmar ratio (annualized return / abs(max drawdown))
            calmar_ratio = 0
            if max_drawdown_pct < 0:  # max_drawdown is negative
                calmar_ratio = annualized_return / abs(max_drawdown_pct)
            print(f"Calmar ratio: {calmar_ratio}")
            
            # Count trades and calculate win rate properly
            signal_changes = hist_data['Signal'].diff().fillna(0)
            trade_starts = signal_changes != 0
            trades = trade_starts.sum()
            print(f"Trades (signal changes): {trades}")
            
            # For win rate
            positive_return_days = (hist_data['Strategy_Returns'] > 0).sum()
            total_days_with_returns = (hist_data['Strategy_Returns'] != 0).sum()
            win_rate = (positive_return_days / total_days_with_returns * 100) if total_days_with_returns > 0 else 0
            win_rate = max(0, min(100, win_rate))
            print(f"Win rate: {win_rate}% (positive days: {positive_return_days}, total days with returns: {total_days_with_returns})")
            
            # Calculate average return per trade
            avg_return_per_trade = (total_return_pct / trades) if trades > 0 else 0
            print(f"Avg return per trade: {avg_return_per_trade}%")
            
            # Generate simple equity curve data
            equity_curve = []
            if len(cumulative) > 0:
                step = max(1, len(cumulative) // 10)
                for i in range(0, len(cumulative), step):
                    if i >= len(cumulative):
                        break
                    equity = initial_capital * cumulative.iloc[i]
                    date_idx = min(i, len(hist_data) - 1)
                    date = hist_data.index[date_idx].strftime('%Y-%m-%d') if hasattr(hist_data.index[date_idx], 'strftime') else str(hist_data.index[date_idx])
                    equity_curve.append({"date": date, "equity": round(equity, 2)})
                
                if len(equity_curve) == 0 or equity_curve[-1]["date"] != hist_data.index[-1].strftime('%Y-%m-%d'):
                    equity = initial_capital * cumulative.iloc[-1]
                    date = hist_data.index[-1].strftime('%Y-%m-%d') if hasattr(hist_data.index[-1], 'strftime') else str(hist_data.index[-1])
                    equity_curve.append({"date": date, "equity": round(equity, 2)})
            
            print(f"Equity curve points: {len(equity_curve)}")
            
            return {
                "totalReturn": round(total_return_pct, 2),
                "annualizedReturn": round(annualized_return, 2),
                "profitLoss": round(profit_loss, 2),
                "sharpeRatio": round(sharpe_ratio, 2),
                "calmarRatio": round(calmar_ratio, 2),
                "maxDrawdown": round(max_drawdown_pct, 2),
                "winRate": round(win_rate, 1),
                "trades": int(trades),
                "avgReturnPerTrade": round(avg_return_per_trade, 2),
                "equityCurve": equity_curve
            }
        
        return None
        
    except Exception as e:
        print(f"Error in debug function: {e}")
        import traceback
        traceback.print_exc()
        return None

# Test the function
if __name__ == '__main__':
    result = debug_run_real_backtest(
        symbol='AAPL',
        strategy='moving_average',
        start_date='2023-01-01',
        end_date='2024-01-01',
        initial_capital=100000
    )
    
    if result:
        print("\n=== Final Result ===")
        for key, value in result.items():
            if key != 'equityCurve':
                print(f"{key}: {value}")
            else:
                print(f"{key}: {len(value)} data points")
                if value:
                    print(f"  First: {value[0]}")
                    print(f"  Last: {value[-1]}")