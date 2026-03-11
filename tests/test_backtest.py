#!/usr/bin/env python3
"""
Test script to verify backtest calculations
"""
import requests
import json
import time
import sys

def test_backtest():
    """Test the backtest API"""
    url = 'http://localhost:8889/api/backtest/run'
    
    # Test 1: moving_average strategy (should use real Yahoo Finance data)
    print("Test 1: Moving Average Strategy with AAPL")
    payload = {
        'symbol': 'AAPL',
        'strategy': 'moving_average',
        'startDate': '2023-01-01',
        'endDate': '2024-01-01',
        'initialCapital': 100000
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"Response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            backtest_id = result.get('backtestId')
            print(f"Backtest ID: {backtest_id}")
            
            if backtest_id:
                # Wait for completion
                time.sleep(3)
                
                # Get results
                results_url = f'http://localhost:8889/api/backtest/results/{backtest_id}'
                results_response = requests.get(results_url, timeout=10)
                
                if results_response.status_code == 200:
                    full_results = results_response.json()
                    results_data = full_results.get('results', {})
                    
                    print("\n=== Backtest Results ===")
                    print(f"Status: {full_results.get('status')}")
                    
                    # Check all expected fields
                    expected_fields = [
                        'totalReturn', 'annualizedReturn', 'profitLoss',
                        'sharpeRatio', 'calmarRatio', 'maxDrawdown',
                        'winRate', 'trades', 'avgReturnPerTrade', 'equityCurve'
                    ]
                    
                    for field in expected_fields:
                        value = results_data.get(field)
                        if value is not None:
                            print(f"{field}: {value}")
                        else:
                            print(f"{field}: MISSING")
                    
                    # Validate values
                    print("\n=== Validation ===")
                    
                    # totalReturn should be percentage
                    total_return = results_data.get('totalReturn')
                    if total_return is not None:
                        print(f"totalReturn: {total_return}% (should be percentage)")
                    
                    # profitLoss should be dollar amount
                    profit_loss = results_data.get('profitLoss')
                    if profit_loss is not None:
                        print(f"profitLoss: ${profit_loss:.2f} (should be dollar amount)")
                        # Check if profitLoss ≈ initial_capital * total_return/100
                        expected_pl = 100000 * (total_return / 100) if total_return else 0
                        diff = abs(profit_loss - expected_pl)
                        print(f"  Check: ${profit_loss:.2f} ≈ ${expected_pl:.2f}? Diff: ${diff:.2f}")
                    
                    # winRate should be between 0-100
                    win_rate = results_data.get('winRate')
                    if win_rate is not None:
                        if 0 <= win_rate <= 100:
                            print(f"winRate: {win_rate}% (valid)")
                        else:
                            print(f"winRate: {win_rate}% (INVALID: should be 0-100)")
                    
                    # maxDrawdown should be negative
                    max_drawdown = results_data.get('maxDrawdown')
                    if max_drawdown is not None:
                        if max_drawdown <= 0:
                            print(f"maxDrawdown: {max_drawdown}% (valid: negative)")
                        else:
                            print(f"maxDrawdown: {max_drawdown}% (INVALID: should be negative)")
                    
                    # equityCurve should have data
                    equity_curve = results_data.get('equityCurve')
                    if equity_curve:
                        print(f"equityCurve: {len(equity_curve)} data points")
                        if len(equity_curve) > 0:
                            print(f"  First: {equity_curve[0]}")
                            print(f"  Last: {equity_curve[-1]}")
                    else:
                        print("equityCurve: MISSING or empty")
                        
                else:
                    print(f"Failed to get results: {results_response.status_code}")
                    print(f"Response: {results_response.text}")
        else:
            print(f"Error: {response.text}")
            
    except Exception as e:
        print(f"Test 1 failed: {e}")
    
    # Test 2: RSI strategy (should use simulated results)
    print("\n\nTest 2: RSI Strategy (simulated)")
    payload2 = {
        'symbol': 'MSFT',
        'strategy': 'rsi',
        'startDate': '2023-01-01',
        'endDate': '2024-01-01',
        'initialCapital': 50000
    }
    
    try:
        response = requests.post(url, json=payload2, timeout=10)
        if response.status_code == 200:
            result = response.json()
            backtest_id = result.get('backtestId')
            
            time.sleep(2)
            results_url = f'http://localhost:8889/api/backtest/results/{backtest_id}'
            results_response = requests.get(results_url, timeout=10)
            
            if results_response.status_code == 200:
                full_results = results_response.json()
                results_data = full_results.get('results', {})
                
                print("\n=== Simulated Results ===")
                for key, value in results_data.items():
                    if key != 'equityCurve':
                        print(f"{key}: {value}")
                
                # Check equity curve
                equity_curve = results_data.get('equityCurve', [])
                print(f"equityCurve: {len(equity_curve)} data points")
                
    except Exception as e:
        print(f"Test 2 failed: {e}")

if __name__ == '__main__':
    # Check if server is running
    try:
        health_response = requests.get('http://localhost:8889/api/health', timeout=5)
        print(f"Server health: {health_response.status_code}")
    except:
        print("ERROR: Backend server not running on localhost:8889")
        print("Please start the backend first: cd backend && python start_quant_backend.py")
        sys.exit(1)
    
    test_backtest()