#!/usr/bin/env python3
"""
平台功能全面测试脚本
测试前端和后端的所有核心功能
"""

import requests
import json
import time
import sys

BASE_URL = "http://localhost:8889"
TEST_USER = {"username": "admin", "password": "admin123"}

def print_header(text):
    print("\n" + "="*60)
    print(f"🔍 {text}")
    print("="*60)

def print_success(text):
    print(f"✅ {text}")

def print_warning(text):
    print(f"⚠️  {text}")

def print_error(text):
    print(f"❌ {text}")

def test_system_status():
    """测试系统状态接口"""
    print_header("测试系统状态接口")
    try:
        response = requests.get(f"{BASE_URL}/api/system/status", timeout=5)
        if response.status_code == 200:
            data = response.json()
            print_success(f"系统状态: {data.get('status')}")
            print_success(f"版本: {data.get('version')}")
            print_success(f"Qlib状态: {data.get('services', {}).get('qlib')}")
            print_success(f"Backtrader状态: {data.get('services', {}).get('backtrader')}")
            return True
        else:
            print_error(f"状态码错误: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"请求失败: {e}")
        return False

def test_user_login():
    """测试用户登录接口"""
    print_header("测试用户登录接口")
    try:
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json=TEST_USER,
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            print_success(f"登录成功: {data.get('user', {}).get('username')}")
            print_success(f"角色: {data.get('user', {}).get('role')}")
            print_success("JWT令牌获取成功")
            return data.get('access_token')
        else:
            print_error(f"登录失败: {response.status_code}")
            print_error(f"响应: {response.text}")
            return None
    except Exception as e:
        print_error(f"登录请求失败: {e}")
        return None

def test_market_data(token):
    """测试市场数据接口"""
    print_header("测试市场数据接口")
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = requests.get(
            f"{BASE_URL}/api/market/stocks",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            stocks = data.get('stocks', [])
            print_success(f"获取到 {len(stocks)} 支股票数据")
            for stock in stocks[:3]:  # 显示前3支
                print_success(f"  {stock.get('symbol')}: ${stock.get('price')} ({stock.get('change_pct')}%)")
            return True
        else:
            print_error(f"市场数据获取失败: {response.status_code}")
            return False
    except Exception as e:
        print_error(f"市场数据请求失败: {e}")
        return False

def test_qlib_status(token):
    """测试Qlib状态接口"""
    print_header("测试Qlib状态接口")
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = requests.get(
            f"{BASE_URL}/api/qlib/status",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            print_success(f"Qlib状态: {data.get('status')}")
            print_success(f"版本: {data.get('version')}")
            return True
        else:
            print_warning(f"Qlib状态获取失败: {response.status_code}")
            return False
    except Exception as e:
        print_warning(f"Qlib状态请求失败: {e}")
        return False

def test_backtrader_strategies(token):
    """测试Backtrader策略接口"""
    print_header("测试Backtrader策略接口")
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = requests.get(
            f"{BASE_URL}/api/backtrader/strategies",
            headers=headers,
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            strategies = data.get('strategies', [])
            print_success(f"获取到 {len(strategies)} 个策略")
            for strategy in strategies:
                print_success(f"  策略: {strategy.get('name')} - {strategy.get('description')}")
            return True
        else:
            print_warning(f"策略获取失败: {response.status_code}")
            return False
    except Exception as e:
        print_warning(f"策略请求失败: {e}")
        return False

def test_frontend_health():
    """测试前端健康状态"""
    print_header("测试前端健康状态")
    try:
        response = requests.get("http://localhost:3000", timeout=5)
        if response.status_code == 200:
            print_success("前端服务运行正常")
            print_success("React应用可访问")
            return True
        else:
            print_warning(f"前端状态码: {response.status_code}")
            return False
    except Exception as e:
        print_warning(f"前端访问失败: {e}")
        print_warning("请确保前端服务已启动: npm start")
        return False

def test_api_response_time():
    """测试API响应时间"""
    print_header("测试API响应时间")
    endpoints = [
        "/api/system/status",
        "/api/auth/login",
        "/api/market/stocks"
    ]
    
    for endpoint in endpoints:
        try:
            start_time = time.time()
            if endpoint == "/api/auth/login":
                response = requests.post(
                    f"{BASE_URL}{endpoint}",
                    json=TEST_USER,
                    timeout=5
                )
            else:
                response = requests.get(f"{BASE_URL}{endpoint}", timeout=5)
            end_time = time.time()
            
            response_time = (end_time - start_time) * 1000  # 转换为毫秒
            if response.status_code == 200:
                print_success(f"{endpoint}: {response_time:.1f}ms")
            else:
                print_warning(f"{endpoint}: {response_time:.1f}ms (状态码: {response.status_code})")
        except Exception as e:
            print_error(f"{endpoint}: 测试失败 - {e}")

def run_comprehensive_test():
    """运行全面测试"""
    print("\n" + "="*60)
    print("🚀 开始平台全面测试")
    print("="*60)
    
    # 记录测试结果
    test_results = {
        "system_status": False,
        "user_login": False,
        "market_data": False,
        "qlib_status": False,
        "backtrader": False,
        "frontend": False
    }
    
    # 测试后端API
    test_results["system_status"] = test_system_status()
    
    token = test_user_login()
    test_results["user_login"] = token is not None
    
    if token:
        test_results["market_data"] = test_market_data(token)
        test_results["qlib_status"] = test_qlib_status(token)
        test_results["backtrader"] = test_backtrader_strategies(token)
    
    # 测试前端
    test_results["frontend"] = test_frontend_health()
    
    # 性能测试
    test_api_response_time()
    
    # 生成测试报告
    print_header("测试结果汇总")
    passed = sum(test_results.values())
    total = len(test_results)
    
    print(f"📊 测试通过率: {passed}/{total} ({passed/total*100:.1f}%)")
    
    for test_name, result in test_results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {test_name.replace('_', ' ').title()}: {status}")
    
    print_header("平台状态评估")
    if passed == total:
        print_success("🎉 所有测试通过！平台运行正常")
        print_success("🚀 平台已准备好投入使用")
    elif passed >= total * 0.7:
        print_warning("⚠️  大部分测试通过，平台基本可用")
        print_warning("🔧 建议检查失败的项目")
    else:
        print_error("❌ 多个测试失败，平台需要调试")
        print_error("🔧 请检查后端和前端服务")
    
    return test_results

if __name__ == "__main__":
    print("🔧 量化平台全面测试脚本")
    print(f"后端地址: {BASE_URL}")
    print(f"前端地址: http://localhost:3000")
    print(f"测试用户: {TEST_USER['username']}")
    
    try:
        results = run_comprehensive_test()
        
        # 提供建议
        print_header("下一步建议")
        if not results["system_status"]:
            print("1. 🔧 检查后端服务是否启动: python app.py")
        if not results["user_login"]:
            print("2. 🔐 检查用户认证系统")
        if not results["frontend"]:
            print("3. 🎨 启动前端服务: cd frontend && npm start")
        if all(results.values()):
            print("1. 🌐 访问平台: http://localhost:3000")
            print("2. 🔐 登录账号: admin / admin123")
            print("3. 📊 开始使用量化分析功能")
        
        print("\n" + "="*60)
        print("测试完成！")
        print("="*60)
        
        # 返回退出码
        sys.exit(0 if sum(results.values()) >= len(results) * 0.7 else 1)
        
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        sys.exit(1)