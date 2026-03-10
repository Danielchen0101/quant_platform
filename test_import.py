import sys
sys.path.insert(0, 'backend')

try:
    from start_quant_backend import calculate_backtest_metrics
    print('calculate_backtest_metrics function imported successfully')
    
    # Check if run_real_backtest exists
    from start_quant_backend import run_real_backtest
    print('run_real_backtest function imported successfully')
    
    # Check the source code
    import inspect
    source = inspect.getsource(run_real_backtest)
    
    # Check for RSI strategy
    if "elif strategy == 'rsi':" in source:
        print('RSI strategy code found in run_real_backtest')
    else:
        print('RSI strategy code NOT found in run_real_backtest')
        
    # Check for calculate_backtest_metrics call
    if 'calculate_backtest_metrics' in source:
        print('calculate_backtest_metrics is called in run_real_backtest')
    else:
        print('calculate_backtest_metrics is NOT called in run_real_backtest')
        
    # Print a snippet of the source
    lines = source.split('\n')
    for i, line in enumerate(lines):
        if 'elif strategy' in line or 'calculate_backtest_metrics' in line:
            print(f'Line {i}: {line}')
            
except Exception as e:
    print(f'Error: {e}')
    import traceback
    traceback.print_exc()