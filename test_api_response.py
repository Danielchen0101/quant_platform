#!/usr/bin/env python3
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

print('测试 /api/backtest/run 接口的实际返回结构...')
print('请求数据:', json.dumps(payload, indent=2))

try:
    response = requests.post(url, json=payload, timeout=10)
    print(f'响应状态码: {response.status_code}')
    
    if response.status_code == 200:
        result = response.json()
        print('\n实际返回内容:')
        print(json.dumps(result, indent=2))
        
        # 检查关键字段
        print('\n关键字段检查:')
        print(f'1. 是否有 status 字段: {"status" in result}')
        if 'status' in result:
            print(f'   status 值: {result["status"]}')
        
        print(f'2. 是否有 results 字段: {"results" in result}')
        if 'results' in result:
            print(f'   results 类型: {type(result["results"])}')
            if result['results']:
                print(f'   results 包含的键: {list(result["results"].keys())}')
                print(f'   results.totalReturn: {result["results"].get("totalReturn", "N/A")}')
        
        print(f'3. 是否有 parameters 字段: {"parameters" in result}')
        if 'parameters' in result:
            print(f'   parameters 类型: {type(result["parameters"])}')
            if result['parameters']:
                print(f'   parameters 包含的键: {list(result["parameters"].keys())}')
        
        print(f'4. 是否有 createdAt 字段: {"createdAt" in result}')
        if 'createdAt' in result:
            print(f'   createdAt 值: {result["createdAt"]}')
        
        print(f'5. 是否有 backtestId 字段: {"backtestId" in result}')
        if 'backtestId' in result:
            print(f'   backtestId 值: {result["backtestId"]}')
        
        print(f'6. 是否有 success 字段: {"success" in result}')
        if 'success' in result:
            print(f'   success 值: {result["success"]}')
        
    else:
        print(f'错误: {response.status_code}')
        print(response.text)
        
except Exception as e:
    print(f'请求异常: {e}')