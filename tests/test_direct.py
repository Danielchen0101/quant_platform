import sys
sys.path.insert(0, 'backend')

try:
    from start_quant_backend import run_real_backtest
    
    print('Testing run_real_backtest directly...')
    
    # Test RSI strategy
    result = run_real_backtest(
        symbol='AAPL',
        strategy='rsi',
        start_date='2023-01-01',
        end_date='2024-01-01',
        initial_capital=100000
    )
    
    print(f'Result is None: {result is None}')
    if result:
        print(f'Result keys: {list(result.keys())}')
        print(f'Number of keys: {len(result.keys())}')
        print('\nAll results:')
        for key, value in result.items():
            print(f'{key}: {value}')
    else:
        print('Result is None')
        
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()