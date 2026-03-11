#!/usr/bin/env python3
"""
测试修改后的 /api/backtest/run 接口是否同步返回完整结果
"""

import requests
import json
import time

url = 'http://localhost:8889/api/backtest/run'

# 测试请求
payload = {
    'symbol': 'AAPL',
    'strategy': 'moving_average',
    'startDate': '2023-01-01',
    'endDate': '2024-01-01',
    'initialCapital': 100000
}

print('测试修改后的 /api/backtest/run 接口...')
print('请求数据:', json.dumps(payload, indent=2))

try:
    response = requests.post(url, json=payload, timeout=10)
    print(f'响应状态码: {response.status_code}')
    
    if response.status_code == 200:
        result = response.json()
        print('\n接口返回内容:')
        print(json.dumps(result, indent=2))
        
        # 检查关键字段
        print('\n关键字段检查:')
        has_status = 'status' in result
        print(f'1. 是否有 status 字段: {has_status}')
        if has_status:
            print(f'   status 值: {result["status"]}')
        
        has_results = 'results' in result
        print(f'2. 是否有 results 字段: {has_results}')
        if has_results:
            print(f'   results 类型: {type(result["results"])}')
            print(f'   results 包含的键: {list(result["results"].keys())}')
        
        has_estimated = 'estimatedCompletion' in result
        print(f'3. 是否有 estimatedCompletion 字段: {has_estimated}')
        if has_estimated:
            print(f'   estimatedCompletion 值: {result["estimatedCompletion"]}')
        
        has_message = 'message' in result
        print(f'4. 是否有 message 字段: {has_message}')
        if has_message:
            print(f'   message 值: {result["message"]}')
        
        # 验证是否是同步返回
        print('\n同步执行验证:')
        if has_status and result['status'] == 'completed' and has_results:
            print('✅ 接口已同步返回完整结果')
            total_return = result['results'].get('totalReturn', 'N/A')
            profit_loss = result['results'].get('profitLoss', 'N/A')
            print(f'   总收益率: {total_return}%')
            print(f'   盈亏金额: ${profit_loss:,.2f}')
        else:
            print('❌ 接口仍返回异步响应，需要继续轮询')
        
    else:
        print(f'错误: {response.status_code}')
        print(response.text)
        
except Exception as e:
    print(f'请求异常: {e}')